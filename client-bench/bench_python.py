"""The Python MCP SDK arm of the client bench.

Same case matrix as `bench.mjs` (CASE-MATRIX.md, frozen 10 August 2026), driven against the
SDK's own exported comparison functions rather than a reimplementation of them. The A-series
here needs no server: `check_resource_allowed` is pure and takes both identifiers, so the
comparison the specification governs can be exercised directly.

This arm covers the A-series and C1 only. The B, C2 and D series are **not implemented here**,
and until 13 August 2026 that showed up as nine rows simply missing from `results.jsonl` --
violating the matrix's first recording rule, which exists because the census learned in July
that a row vanishing from a report shrinks every denominator in silence. It mattered in a
particular direction: the manuscript's Table 9 dropped the two cases the implementations
*passed*, so the omission flattered nobody but made the bench look more damning than the
matrix it came from. The gap is now written down as `not_exercised` records with the reason,
which is what the rule asks for, and `--coverage-only` emits just those, since it needs
neither the SDK nor a server.

Appends to results.jsonl in the same record shape the TypeScript arm writes.

Run with the throwaway venv that has `mcp` installed, not the project venv:
    python bench_python.py
    python bench_python.py --coverage-only
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import UTC, datetime

IMPL = "python-sdk"
PKG = "mcp"

REQUESTED = "http://127.0.0.1:8000/tenant-a/mcp"

# Every case in CASE-MATRIX.md this arm does not drive, with the reason. The reason is a fact
# about the bench, not about the SDK: it says the case was never put to the implementation,
# which is the only thing the records may claim. Reading a negative here as "the Python SDK
# does not do this" is exactly the inference the record exists to block.
NOT_EXERCISED: list[tuple[str, str, str]] = [
    ("B", "B1", "the Python arm drives no discovery flow, so RFC 8414 issuer comparison is "
                "never reached"),
    ("B", "B2", "the Python arm drives no discovery flow, so RFC 8414 issuer comparison is "
                "never reached"),
    ("C", "C2", "selection among several authorization_servers requires a client flow this "
                "arm does not run"),
    *[("D", f"D{i}", "the Python arm drives no authorization-response handling, so RFC 9207 "
                     "iss validation is never reached") for i in range(1, 7)],
]

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
    import mcp

    root = pathlib.Path(mcp.__file__).parent
    return sum(
        1 for p in root.rglob("*.py")
        if needle in p.read_text(encoding="utf-8", errors="ignore")
    )


def coverage_records(version: str, now: str) -> list[dict]:
    """The cases this arm does not drive, recorded rather than omitted."""
    return [
        {
            "implementation": IMPL, "package": PKG, "version": version,
            "series": series, "case_id": case_id,
            "outcome": "not_exercised", "conformant": None,
            "detail": reason, "run_at": now,
        }
        for series, case_id, reason in NOT_EXERCISED
    ]


def main() -> None:
    now = datetime.now(UTC).isoformat()
    out = pathlib.Path("results.jsonl")

    if "--coverage-only" in sys.argv:
        # The version the measured rows carry, so the coverage rows sit beside them rather
        # than under a version this arm never ran against.
        measured = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
        versions = {r["version"] for r in measured if r["implementation"] == IMPL}
        if len(versions) != 1:
            raise SystemExit(f"expected one recorded version for {IMPL}, found {versions}")
        records = coverage_records(versions.pop(), now)
        with out.open("a", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record) + "\n")
        print(f"appended {len(records)} coverage records for {IMPL}")
        return

    import importlib.metadata

    version = importlib.metadata.version("mcp")
    from mcp.shared.auth_utils import check_resource_allowed

    records = []

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
            "implementation": IMPL, "package": PKG, "version": version,
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
        "implementation": IMPL, "package": PKG, "version": version,
        "series": "C", "case_id": "C1", "strength": "descriptive",
        "served_protected_resources": True,
        "key_retained": None, "control_key_retained": None,
        "schema_knows_field": occurrences > 0,
        "source_occurrences": occurrences,
        "detail": "counted over the installed package's Python sources",
        "run_at": now,
    })

    records += coverage_records(version, now)

    with out.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    print(f"appended {len(records)} records for {IMPL} {version}")


if __name__ == "__main__":
    main()
