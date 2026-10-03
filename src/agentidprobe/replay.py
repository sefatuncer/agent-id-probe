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

from .config import DEFAULT_CONFIG, MeasurementConfig
from .fetcher import (
    UNREQUESTED_DETAIL_PREFIX,
    ErrorKind,
    Fetcher,
    FetchResult,
    is_ceiling_refusal,
    is_metadata_url,
)
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

    def __init__(self, artifacts: list[dict], *, strict: bool = True,
                 config: MeasurementConfig = DEFAULT_CONFIG,
                 unrequested_metadata_not_observed: bool = False) -> None:
        # The checks read policy off the fetcher -- the per-endpoint issuer cap, for one --
        # so a replay must carry the same configuration or it is scoring under different
        # rules than the run it claims to reproduce. If the cap has since changed, replay
        # will ask for an artefact that was never stored and `strict` will say so, which is
        # the correct outcome: a silent divergence would falsify R8's whole claim.
        self.config = config
        self._by_key: dict[tuple[str, str], list[dict]] = {}
        self._by_endpoint: dict[str, list[dict]] = {}
        for record in artifacts:
            key = (record.get("endpoint_id", ""), record.get("url", ""))
            self._by_key.setdefault(key, []).append(record)
            self._by_endpoint.setdefault(record.get("endpoint_id", ""), []).append(record)
        # Runs recorded before artefact schema 2 (3 October 2026) carry no record of the
        # reuse rule, so the replay applies it for them. A schema-2 run records every reuse
        # as it happened, and its refusals are the live outcome: re-deciding them would let a
        # replay answer a refusal the live run could not, for instance across a resume, which
        # is the non-determinism R8 forbids.
        self.legacy = all(int(r.get("artifact_schema", 1)) < 2 for r in artifacts) \
            if artifacts else False
        self._cursor: dict[tuple[str, str], int] = {}
        # The run's first successful response to each metadata URL, whichever endpoint it was
        # fetched for. A live `Fetcher` answers a ceiling refusal from the documents it had
        # already retrieved, so a replay must do the same, and must use only a document
        # retrieved *before* the refusal, or it would reproduce a verdict the live run could
        # not have reached. Stored runs collected before that rule existed are re-scored
        # under it this way, without a single new request.
        self._first_success: dict[str, dict] = {}
        for record in artifacts:
            url = record.get("url", "")
            if (record.get("status") == 200 and record.get("error_kind", "none") == "none"
                    and not record.get("reused") and is_metadata_url(url)):
                held = self._first_success.get(url)
                if held is None or _when(record) < _when(held):
                    self._first_success[url] = record
        self.reused = 0
        # A stored run collected before the ceiling rule existed sometimes stopped short of a
        # metadata request the corrected instrument now makes, because a document answered
        # from the run's own copy lets it walk one step further than the live run did. With
        # `unrequested_metadata_not_observed`, such a request is treated exactly as a ceiling
        # refusal at the time the endpoint was probed: answered from the run's earlier copy of
        # the same document if there is one, and otherwise not observed. Never fetched, never
        # invented. Counted so a replay that used it says so.
        self.unrequested_metadata_not_observed = unrequested_metadata_not_observed
        self.unrequested_answered = 0
        self.unrequested_not_observed = 0
        self._endpoint_started: dict[str, datetime] = {}
        for record in artifacts:
            endpoint = record.get("endpoint_id", "")
            when = _when(record)
            if endpoint not in self._endpoint_started or when < self._endpoint_started[endpoint]:
                self._endpoint_started[endpoint] = when
        self._endpoint_id: str = ""
        self.strict = strict
        self.misses: list[str] = []

    def bind(self, endpoint_id: str, endpoint_url: str | None = None) -> None:
        """Replay one endpoint, aligned to the last time the live run probed it.

        A resumed run can hold two attempts at one endpoint, and the stored report comes from
        the last. Replaying the first attempt's responses re-scored a different probe, which
        is how one census2 endpoint could not be re-scored at all until 3 October 2026 and,
        for a few hours that day, was re-scored as not observed while its report said pass.
        """
        self._endpoint_id = endpoint_id
        if endpoint_url is None:
            return
        records = self._by_endpoint.get(endpoint_id, [])
        starts = [_when(r) for r in records if r.get("url") == endpoint_url]
        if len(starts) < 2:
            return
        last = max(starts)
        for record in records:
            key = (endpoint_id, record.get("url", ""))
            queue = [r for r in self._by_key.get(key, []) if _when(r) >= last]
            self._by_key[key] = queue
            self._cursor[key] = 0
        self._endpoint_started[endpoint_id] = last

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
        if (not queue and self.unrequested_metadata_not_observed and self.legacy
                and is_metadata_url(url) and self._endpoint_id in self._endpoint_started):
            started = self._endpoint_started[self._endpoint_id]
            refusal = FetchResult(
                url=url, ok=False, error_kind=ErrorKind.OUT_OF_SCOPE,
                error_detail=f"{UNREQUESTED_DETAIL_PREFIX} (replay of a schema-1 run)",
                fetched_at=started)
            first = self._first_success.get(url)
            earlier = ({url: _to_fetch_result(first)}
                       if first is not None and _when(first) < started else {})
            result = Fetcher.reuse_or_keep(url, refusal, earlier)
            if result.reused:
                self.unrequested_answered += 1
            else:
                self.unrequested_not_observed += 1
            return result
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
        result = _to_fetch_result(queue[index])
        if self.legacy and is_ceiling_refusal(result):
            first = self._first_success.get(url)
            earlier = ({url: _to_fetch_result(first)}
                       if first is not None and _when(first) < _when(queue[index])
                       else {})
            result = Fetcher.reuse_or_keep(url, result, earlier)
            self.reused += result.reused
        return result


def _when(record: dict) -> datetime:
    return datetime.fromisoformat(record["fetched_at"])


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
        reused=bool(record.get("reused", False)),
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
