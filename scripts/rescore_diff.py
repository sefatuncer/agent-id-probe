#!/usr/bin/env python3
"""What a corrected instrument changed, verdict by verdict, between two scorings of one run.

Written 3 October 2026 for the re-score that followed the review of 1 October (H2-M1 to M4).
The manuscript's deviation table prints the figures before and after each correction, and a
figure typed into a table is the kind this repository has watched drift, so the comparison is
a command and its output is a committed file the manuscript's build reads.

Aggregates only: transitions are counted per check, and no endpoint is named in the output.

    python scripts/rescore_diff.py --before census2-pre-2026-10-03 --after census2 \\
        --out docs/rescore-2026-10-03-census2.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentidprobe.store import RunStore  # noqa: E402

MUST_STAGES = ("C05", "C12", "C13")


def _failures(reports: dict) -> Counter:
    return Counter(check.check_id.value for report in reports.values()
                   for check in report.checks if check.outcome.value.startswith("fail"))


def _failing_units(reports: dict) -> dict:
    endpoints, apexes = set(), set()
    for (endpoint_id, _), report in reports.items():
        if any(c.outcome.value.startswith("fail") and c.check_id.value in MUST_STAGES
               for c in report.checks):
            endpoints.add(endpoint_id)
            apexes.add(report.endpoint.apex_domain or f"?{endpoint_id}")
    return {"endpoints": len(endpoints), "apexes": len(apexes)}


def _rescore_manifest(store: RunStore) -> dict:
    """The manifest the re-score wrote, kept beside the run's collection manifest when the
    re-scored reports replaced the original ones; the collection manifest otherwise."""
    written = sorted(store.run_dir.glob("manifest-rescore-*.json"))
    if written:
        return json.loads(written[-1].read_text(encoding="utf-8"))
    return store.read_manifest()


def diff(before_id: str, after_id: str, root: Path = ROOT) -> dict:
    def load(run_id: str) -> dict:
        return {(r.endpoint.endpoint_id, r.modality.value): r
                for r in RunStore(root, run_id).read_reports()}

    before, after = load(before_id), load(after_id)
    transitions: Counter = Counter()
    for key in before.keys() & after.keys():
        old = {c.check_id.value: c.outcome.value for c in before[key].checks}
        new = {c.check_id.value: c.outcome.value for c in after[key].checks}
        for check in MUST_STAGES:
            a, b = old.get(check, "absent"), new.get(check, "absent")
            if a != b:
                transitions[f"{check}: {a} -> {b}"] += 1
    fb, fa = _failures(before), _failures(after)
    return {
        "schema": "agent-id-probe/rescore-diff/1",
        "before": before_id,
        "after": after_id,
        "reports_before": len(before),
        "reports_after": len(after),
        "reports_only_before": len(before.keys() - after.keys()),
        "must_failures_before": {c: fb[c] for c in MUST_STAGES} | {
            "total": sum(fb[c] for c in MUST_STAGES)},
        "must_failures_after": {c: fa[c] for c in MUST_STAGES} | {
            "total": sum(fa[c] for c in MUST_STAGES)},
        "failing_units_before": _failing_units(before),
        "failing_units_after": _failing_units(after),
        "transitions": dict(sorted(transitions.items())),
        "manifest_after": _rescore_manifest(RunStore(root, after_id)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = diff(args.before, args.after)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("must_failures_before", "must_failures_after",
                                              "failing_units_before", "failing_units_after")},
                     indent=1))
    for transition, n in result["transitions"].items():
        print(f"  {n:5}  {transition}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
