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
from typing import Any

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
        payload = {
            "run_context": json.loads(context.model_dump_json()),
            "probe_version": PROBE_VERSION,
            "written_at": datetime.now(UTC).isoformat(),
            **(extra or {}),
        }
        self.manifest_path.write_text(_dump(payload) + "\n", encoding="utf-8")

    def write_corpus(self, endpoints: list[Endpoint]) -> None:
        with self.corpus_path.open("w", encoding="utf-8") as handle:
            for endpoint in endpoints:
                handle.write(endpoint.model_dump_json() + "\n")

    def append_artifact(self, endpoint_id: str, label: str, result: FetchResult) -> None:
        """Persist a fetched document verbatim so the verdict can be recomputed."""
        record = {
            "endpoint_id": endpoint_id,
            "label": label,
            "url": result.url,
            "final_url": result.final_url,
            "redirect_chain": result.redirect_chain,
            "status": result.status,
            "headers": result.headers,
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

    @staticmethod
    def _append(path: Path, record: dict) -> None:
        # Flush and fsync per record: a run may take hours and the machine is a laptop.
        # Losing the tail of a run to a lid close would mean re-fetching third-party
        # hosts we have already bothered once.
        with path.open("a", encoding="utf-8") as handle:
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
        reports: list[EndpointReport] = []
        if not self.reports_path.exists():
            return reports
        with self.reports_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    reports.append(EndpointReport.model_validate_json(line))
                except Exception:  # noqa: BLE001 - a truncated tail must not break analysis
                    continue
        return reports

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
