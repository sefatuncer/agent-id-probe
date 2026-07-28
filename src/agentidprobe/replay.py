"""Re-scoring stored artefacts without touching the network.

Decision rule R8 promises that any verdict can be recomputed from what was stored, so that
an instrument defect found after collection costs a local re-run rather than a second scan
of several thousand third-party hosts. Until this module existed that promise had nothing
behind it: there was no way to execute it, and the phase-0 pilot had already demonstrated
the cost of that — its numbers survived only as a markdown table, so when review found
five scoring defects there was nothing left to re-score.

The design constraint is that a replay which quietly falls back to the network is not a
replay. `ReplayFetcher` therefore raises on a miss rather than fetching, and exposes the
same surface the checks use so it can be substituted for `Fetcher` directly.
"""

from __future__ import annotations

import base64
from datetime import datetime

from .fetcher import ErrorKind, FetchResult
from .models import TlsInfo


class ArtefactMissing(LookupError):
    """A check asked for a document the stored run does not contain.

    Raised rather than falling back to a live fetch: silently going to the network would
    make a failed replay look like a successful one, which is the single thing this module
    exists to prevent.
    """


class ReplayFetcher:
    """Serves stored artefacts in place of `Fetcher`.

    Keyed by (endpoint_id, url) with a queue per key, so a URL fetched more than once for
    one endpoint replays in the order it was originally fetched.
    """

    def __init__(self, artifacts: list[dict], *, strict: bool = True) -> None:
        self._by_key: dict[tuple[str, str], list[dict]] = {}
        for record in artifacts:
            key = (record.get("endpoint_id", ""), record.get("url", ""))
            self._by_key.setdefault(key, []).append(record)
        self._cursor: dict[tuple[str, str], int] = {}
        self._endpoint_id: str = ""
        self.strict = strict
        self.misses: list[str] = []

    def bind(self, endpoint_id: str) -> None:
        self._endpoint_id = endpoint_id

    async def __aenter__(self) -> ReplayFetcher:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def allowed(self, url: str) -> bool:
        # The stored result already encodes whatever robots.txt said at collection time;
        # re-deciding it here would let a robots.txt that changed since then alter a
        # historical verdict, which is exactly the non-determinism R8 forbids.
        return True

    async def fetch(self, url: str) -> FetchResult:
        key = (self._endpoint_id, url)
        queue = self._by_key.get(key)
        if not queue:
            self.misses.append(url)
            if self.strict:
                raise ArtefactMissing(
                    f"no stored artefact for {url!r} under endpoint {self._endpoint_id!r}. "
                    f"The run was collected before this document was fetched, or the "
                    f"instrument now asks for something it did not ask for then."
                )
            return FetchResult(url=url, ok=False, error_kind=ErrorKind.OTHER,
                               error_detail="artefact missing from stored run")
        index = min(self._cursor.get(key, 0), len(queue) - 1)
        self._cursor[key] = index + 1
        return _to_fetch_result(queue[index])


def _to_fetch_result(record: dict) -> FetchResult:
    tls = record.get("tls")
    return FetchResult(
        url=record.get("url", ""),
        ok=bool(record.get("ok", record.get("status") is not None)),
        status=record.get("status"),
        headers=record.get("headers") or {},
        body=base64.b64decode(record.get("body_b64") or ""),
        final_url=record.get("final_url"),
        redirect_chain=list(record.get("redirect_chain") or []),
        elapsed_ms=record.get("elapsed_ms"),
        tls=TlsInfo.model_validate(tls) if isinstance(tls, dict) else None,
        error_kind=ErrorKind(record.get("error_kind", "none")),
        error_detail=record.get("error_detail", ""),
        fetched_at=datetime.fromisoformat(record["fetched_at"]),
    )


def compare_reports(before: list, after: list) -> list[str]:
    """Differences between a stored run and its re-score, as human-readable lines.

    `probed_at` and `run_id` are excluded: they record when the verdict was computed, not
    what it was. Everything else must match, because R8's claim is about verdicts being
    reproducible rather than merely similar.
    """
    def key(report) -> tuple[str, str]:
        return (report.endpoint.endpoint_id, report.modality.value)

    old = {key(r): r for r in before}
    new = {key(r): r for r in after}
    differences: list[str] = []

    for k in sorted(old.keys() - new.keys()):
        differences.append(f"{k[0]} [{k[1]}]: present in the stored run, absent after replay")
    for k in sorted(new.keys() - old.keys()):
        differences.append(f"{k[0]} [{k[1]}]: produced by replay but not in the stored run")

    for k in sorted(old.keys() & new.keys()):
        a, b = old[k], new[k]
        if a.reachable != b.reachable:
            differences.append(f"{k[0]} [{k[1]}]: reachable {a.reachable} -> {b.reachable}")
        a_checks = {c.check_id: c for c in a.checks}
        b_checks = {c.check_id: c for c in b.checks}
        for check_id in sorted(a_checks.keys() | b_checks.keys(), key=lambda c: c.value):
            old_outcome = a_checks[check_id].outcome.value if check_id in a_checks else "absent"
            new_outcome = b_checks[check_id].outcome.value if check_id in b_checks else "absent"
            if old_outcome != new_outcome:
                differences.append(
                    f"{k[0]} [{k[1]}] {check_id.value}: {old_outcome} -> {new_outcome}"
                )
    return differences
