"""The sufficient moments of every printed interval, for publication in place of the data.

The census itself is not shared (author decision, 1 October 2026). What a reader can check
without it is whether each printed interval follows from its clusters, and for that six sums
per interval suffice: m, N, K, sum(n_i^2), sum(k_i * n_i) and sum(k_i^2).
`analysis.proportion_from_moments` turns them back into the published rate and interval, and
`tests/test_cluster_moments.py` holds that it does so exactly.

Why not the per-cluster (k_i, n_i) vector, which was the first proposal (YK1(b)): its largest
entries are recognisable. A cluster of 1,281 endpoints is one host, and the public registry
says which, so the vector would publish that operator's failure count. The sums carry no entry
for any cluster.

The interval list is `coverage_calibrated.published_intervals`, so the two committed files
always describe the same intervals.

    python scripts/cluster_moments.py --run-id census2           # print and verify
    python scripts/cluster_moments.py --run-id census2 --write   # regenerate the JSON
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from coverage_calibrated import published_intervals  # noqa: E402

from agentidprobe.analysis import (  # noqa: E402
    cluster_moments,
    cluster_robust_proportion,
    proportion_from_moments,
)

SCHEMA = "agent-id-probe/cluster-moments/1"


def build(run_id: str) -> dict:
    from agentidprobe.store import RunStore

    reports = RunStore(ROOT, run_id).read_reports()
    rows = []
    for task in published_intervals(reports):
        moments = cluster_moments(task["clusters"])
        estimate = cluster_robust_proportion(task["clusters"])
        p_hat, lo, hi = proportion_from_moments(moments)
        if not all(math.isclose(a, b, abs_tol=1e-9)
                   for a, b in ((p_hat, estimate.p_hat), (lo, estimate.lo),
                                (hi, estimate.hi))):
            raise SystemExit(f"{task['key']}: the moments do not reproduce the interval")
        rows.append({"key": task["key"], "unit": task["unit"],
                     "clustering": task["published_clustering"], "moments": moments,
                     "p_hat": p_hat, "interval": [lo, hi]})
    return {"schema": SCHEMA, "run_id": run_id, "conf": 0.95,
            "reconstruct_with": "agentidprobe.analysis.proportion_from_moments",
            "intervals": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="census2")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = build(args.run_id)
    for row in result["intervals"]:
        lo, hi = row["interval"]
        mo = row["moments"]
        print(f"{row['key']:<20} m={mo['m']:>5} n={mo['n']:>5} k={mo['k']:>5} "
              f"{row['p_hat']:6.1%} [{lo:.1%}, {hi:.1%}]")
    if args.write:
        path = ROOT / "docs" / f"cluster-moments-{args.run_id}.json"
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
