"""The Python MCP SDK arm of the client bench.

Same case matrix as `bench.mjs` (CASE-MATRIX.md, frozen 10 August 2026), driven against the
SDK's own exported comparison functions rather than a reimplementation of them. The A-series
here needs no server: `check_resource_allowed` is pure and takes both identifiers, so the
comparison the specification governs can be exercised directly.

Appends to results.jsonl in the same record shape the TypeScript arm writes.

Run with the throwaway venv that has `mcp` installed, not the project venv:
    python bench_python.py
"""

from __future__ import annotations

import importlib.metadata
import json
import pathlib
from datetime import UTC, datetime

import mcp
from mcp.shared.auth_utils import check_resource_allowed

IMPL = "python-sdk"
PKG = "mcp"
VERSION = importlib.metadata.version("mcp")

REQUESTED = "http://127.0.0.1:8000/tenant-a/mcp"

# The A-series exactly as CASE-MATRIX.md fixes it. `required` is what RFC 9728 Section 3.3
# demands, derived from the quoted MUST and not from what any implementation does.
A_CASES: list[tuple[str, str, str | None, str]] = [
    ("A1", "identical", "http://127.0.0.1:8000/tenant-a/mcp", "use"),
    ("A2", "proper ancestor", "http://127.0.0.1:8000/", "reject"),
    ("A3", "sibling", "http://127.0.0.1:8000/tenant-b/mcp", "reject"),
    ("A4", "cross-origin", "http://attacker.example/mcp", "reject"),
    ("A5", "absent", None, "reject"),
    ("A6", "trailing slash", "http://127.0.0.1:8000/tenant-a/mcp/", "reject"),
    ("A7", "case-differing path", "http://127.0.0.1:8000/TENANT-A/mcp", "reject"),
]


def source_occurrences(needle: str) -> int:
    """Files of the installed package containing `needle`.

    The independent signal behind the C-series: a field the package never mentions cannot be
    acted on, whatever a parsed object happens to retain.
    """
    root = pathlib.Path(mcp.__file__).parent
    return sum(
        1 for p in root.rglob("*.py")
        if needle in p.read_text(encoding="utf-8", errors="ignore")
    )


def main() -> None:
    records = []
    now = datetime.now(UTC).isoformat()

    for case_id, label, declared, required in A_CASES:
        if declared is None:
            # The SDK skips the comparison when the document omits `resource`, so nothing is
            # rejected. RFC 9728 Section 2 makes the member REQUIRED, so a document without it
            # is malformed and Section 3.3's "MUST NOT be used" applies to it.
            observed, adopted = "use", REQUESTED
            detail = "no comparison performed when resource is absent"
        else:
            allowed = check_resource_allowed(
                requested_resource=REQUESTED, configured_resource=declared
            )
            observed = "use" if allowed else "reject"
            adopted = declared if allowed else None
            detail = "check_resource_allowed"

        records.append({
            "implementation": IMPL, "package": PKG, "version": VERSION,
            "series": "A", "case_id": case_id, "case_label": label,
            "requested_identifier": REQUESTED, "declared_resource": declared,
            "required": required, "observed": observed,
            "conformant": observed == required,
            "adopted_identifier": adopted,
            "audience_widened": observed == "use" and adopted is not None and adopted != REQUESTED,
            "detail": detail, "run_at": now,
        })

    occurrences = source_occurrences("protected_resources")
    records.append({
        "implementation": IMPL, "package": PKG, "version": VERSION,
        "series": "C", "case_id": "C1", "strength": "descriptive",
        "served_protected_resources": True,
        "key_retained": None, "control_key_retained": None,
        "schema_knows_field": occurrences > 0,
        "source_occurrences": occurrences,
        "detail": "counted over the installed package's Python sources",
        "run_at": now,
    })

    out = pathlib.Path("results.jsonl")
    with out.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    print(f"appended {len(records)} records for {IMPL} {VERSION}")


if __name__ == "__main__":
    main()
