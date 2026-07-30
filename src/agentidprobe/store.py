"""Run persistence.

The design constraint that shapes this module: **raw artefacts must survive the
instrument**. Decision rule R8 promises that any result can be re-scored without
touching the network, and the phase-0 pilot already showed why that matters — its
numbers exist only as a markdown table, so when review found five scoring defects there
was nothing to re-score and the pilot had to be treated as indicative rather than
evidence.

So every fetched document is written verbatim alongside the verdict derived from it.
Re-scoring after a fix is then a local, free, deterministic operation.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from .config import PROBE_VERSION
from .fetcher import FetchResult
from .models import Endpoint, EndpointReport, RunContext


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=_json_default)


class RunStore:
    """Append-only storage for one measurement run."""

    def __init__(self, root: Path | str, run_id: str) -> None:
        self.root = Path(root)
        self.run_id = run_id
        self.raw_dir = self.root / "data" / "raw" / run_id
        self.run_dir = self.root / "results" / "runs" / run_id
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    # -- paths -----------------------------------------------------------------

    @property
    def artifacts_path(self) -> Path:
        return self.raw_dir / "artifacts.jsonl"

    @property
    def reports_path(self) -> Path:
        return self.run_dir / "reports.jsonl"

    @property
    def corpus_path(self) -> Path:
        return self.run_dir / "corpus.jsonl"

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    # -- writing ---------------------------------------------------------------

    def write_manifest(self, context: RunContext, extra: dict | None = None) -> None:
        # The public-suffix list belongs in provenance, not in a dependency file (defect D10).
        # R10.2 makes the apex domain the primary unit of analysis, so the snapshot in use
        # decides the cluster count and therefore every published interval; and because an
        # issuer with no registrable domain is never contacted, it also decides which requests
        # the run sent. `tldextract>=5.1,<6.0` admits any patch release and each ships its own
        # snapshot, so "reproducible" was resting on a dependency nobody recorded. Written on
        # every manifest rather than only on `collect`, since `rescore` re-derives apexes too.
        from .collectors import public_suffix_provenance

        payload = {
            "run_context": json.loads(context.model_dump_json()),
            "probe_version": PROBE_VERSION,
            "public_suffix_list": public_suffix_provenance(),
            "written_at": datetime.now(UTC).isoformat(),
            **(extra or {}),
        }
        self.manifest_path.write_text(_dump(payload) + "\n", encoding="utf-8")

    def write_corpus(self, endpoints: list[Endpoint]) -> None:
        with self.corpus_path.open("w", encoding="utf-8") as handle:
            for endpoint in endpoints:
                handle.write(endpoint.model_dump_json() + "\n")

    ARTIFACT_SCHEMA = 1

    def append_artifact(self, endpoint_id: str, label: str, result: FetchResult) -> None:
        """Persist a fetched document verbatim so the verdict can be recomputed.

        Everything a check reads must be here, not just the body. `tls` is the case that
        proves the point: C11 scores the endpoint's certificate, and while it was omitted
        from this record a re-scoring pass saw `tls is None` and turned every live PASS
        into FAIL_UNIMPLEMENTED. Decision rule R8 promises byte-identical verdicts on
        replay, so a field a check consults and this record drops is not an omission, it is
        the rule being false.
        """
        record = {
            "artifact_schema": self.ARTIFACT_SCHEMA,
            "endpoint_id": endpoint_id,
            "label": label,
            "url": result.url,
            "ok": result.ok,
            "final_url": result.final_url,
            "redirect_chain": result.redirect_chain,
            "status": result.status,
            "headers": result.headers,
            "tls": result.tls.model_dump(mode="json") if result.tls is not None else None,
            "body_b64": base64.b64encode(result.body).decode("ascii"),
            "body_sha256": result.body_sha256,
            "elapsed_ms": result.elapsed_ms,
            "error_kind": result.error_kind.value,
            "error_detail": result.error_detail,
            "fetched_at": result.fetched_at.isoformat(),
        }
        self._append(self.artifacts_path, record)

    def append_report(self, report: EndpointReport) -> None:
        self._append(self.reports_path, json.loads(report.model_dump_json()))

    # Paths whose tail has already been checked in this process. A torn line can only come
    # from a *previous* run, so the check is worth doing once per file and never again:
    # re-opening the file read-only before every append cost 341 ms per record on Windows
    # against 28 ms without, which is 114 minutes of pure disk I/O on a full run, inside
    # synchronous calls that block the event loop the whole time.
    _tail_checked: ClassVar[set[Path]] = set()

    @classmethod
    def _append(cls, path: Path, record: dict) -> None:
        # Flush and fsync per record: a run may take hours and the machine is a laptop.
        # Losing the tail of a run to a lid close would mean re-fetching third-party
        # hosts we have already bothered once.
        with path.open("a", encoding="utf-8") as handle:
            # If the previous run died mid-write the file ends without a newline. Appending
            # straight onto that stub fuses two records into one unparseable line and the
            # *next* record is lost too — silently, because both the resume scan and the
            # reader skip malformed lines. Close the torn line first; it is discarded on
            # read, but it no longer takes a good record down with it.
            if path not in cls._tail_checked:
                cls._tail_checked.add(path)
                if path.exists() and path.stat().st_size:
                    with path.open("rb") as probe:
                        probe.seek(-1, os.SEEK_END)
                        if probe.read(1) != b"\n":
                            handle.write("\n")
            handle.write(_dump(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    # -- reading / resume ------------------------------------------------------

    def completed_endpoint_ids(self) -> set[str]:
        """Endpoints already scored in this run, so a resumed run does not re-probe
        them. Malformed trailing lines (a run killed mid-write) are ignored rather
        than aborting the resume."""
        done: set[str] = set()
        if not self.reports_path.exists():
            return done
        with self.reports_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                endpoint = record.get("endpoint")
                if isinstance(endpoint, dict) and isinstance(endpoint.get("endpoint_id"), str):
                    done.add(endpoint["endpoint_id"])
        return done

    def read_reports(self) -> list[EndpointReport]:
        """Scored reports, one per (endpoint, modality), latest write winning.

        The file is append-only, so re-probing an endpoint — with `--no-resume`, or by
        reusing a run id — leaves two records for it. Returning both would count that
        endpoint twice in every rate the paper publishes, and the duplicate is invisible
        in the file. De-duplication belongs here rather than in each caller.
        """
        latest: dict[tuple[str, str], EndpointReport] = {}
        if not self.reports_path.exists():
            return []
        with self.reports_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    report = EndpointReport.model_validate_json(line)
                except Exception:  # noqa: BLE001 - a truncated tail must not break analysis
                    continue
                latest[(report.endpoint.endpoint_id, report.modality.value)] = report
        return list(latest.values())

    def read_corpus(self) -> list[Endpoint]:
        endpoints: list[Endpoint] = []
        if not self.corpus_path.exists():
            return endpoints
        with self.corpus_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    endpoints.append(Endpoint.model_validate_json(line))
        return endpoints

    def read_artifacts(self, endpoint_id: str | None = None) -> list[dict]:
        """Raw documents, optionally for one endpoint. This is what makes re-scoring
        possible without going back to the network."""
        out: list[dict] = []
        if not self.artifacts_path.exists():
            return out
        with self.artifacts_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if endpoint_id is None or record.get("endpoint_id") == endpoint_id:
                    record["body"] = base64.b64decode(record.get("body_b64", ""))
                    out.append(record)
        return out
