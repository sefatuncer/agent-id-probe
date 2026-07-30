"""What a naive 95% Wilson interval actually covers when the corpus is clustered.

`analysis.py` and decision rule R10.4 both justify refusing to publish a naive binomial
interval by quoting a coverage range from "simulation over the shapes this corpus plausibly
takes". That simulation existed only as a sentence: nothing in the repository computed the
number, the two documents quoting it disagreed with each other (46%-82% in one, 45%-82% in the
other), and a reviewer asking where it came from would have found an assertion. Writing it put
the real range at **20%-88%**, so both quoted figures understated the low end by more than
twenty points -- in the argument that licenses this paper's entire interval methodology.

    python scripts/wilson_coverage_under_clustering.py            # print the table
    python scripts/wilson_coverage_under_clustering.py --write    # regenerate the JSON

The result is committed as `docs/wilson-coverage.json` and the test suite checks the prose
against **that file**, not against a fresh run. The reason is Monte Carlo error: at a trial
count small enough to sit inside a test timeout the bounds move by several points between
grids, so a test that re-simulated would either be flaky or carry a tolerance wide enough to
pass anything. Treating the simulation like the captured control documents -- run it, commit
the output with its seed, check the prose against the committed value, re-run to audit --
gives a reviewer something to reproduce and the suite something exact to enforce.

The generative model is the corpus's own known shape rather than a convenient one. Endpoints
arrive in clusters (one SDK default, one bulk publisher's listings, one platform's tenants);
the cluster draws the outcome, and each endpoint in it inherits that outcome with probability
`rho`. `rho = 1.0` is the pure case -- every endpoint in a cluster agrees, which is exactly
what a shared SDK default produces -- and lower values mix in per-endpoint independence.
Cluster sizes are Zipf-shaped because that is what the registry looks like: in a 2,500-record
slice the largest apex held 14.5% of remote URLs, the top five held 44.8%, and URL-level counts
exceeded apex-level counts by 3.6x.

The grid deliberately includes the shapes that make the argument *weakest* -- partial
agreement, many small clusters -- because a range quoted over favourable scenarios only would
be the same kind of choice R11 exists to forbid.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentidprobe.analysis import wilson_interval  # noqa: E402

RESULT_FILE = ROOT / "docs" / "wilson-coverage.json"
SCHEMA = "agent-id-probe/wilson-coverage/1"

# Fixed so the published number is reproducible. R8's determinism requirement applies to a
# statistic quoted in the paper no less than to a verdict.
SEED = 20260730
TRIALS = 4000

# (label, clusters m, Zipf exponent, intra-cluster agreement rho, true propensity p)
SCENARIOS: tuple[tuple[str, int, float, float, float], ...] = (
    ("few large clusters, full agreement",      30, 1.4, 1.0, 0.50),
    ("few large clusters, partial agreement",   30, 1.4, 0.5, 0.50),
    ("many clusters, full agreement",          300, 1.1, 1.0, 0.50),
    ("many clusters, partial agreement",       300, 1.1, 0.5, 0.50),
    ("heavy tail, full agreement",              80, 1.8, 1.0, 0.50),
    ("rate near the edge, full agreement",     300, 1.1, 1.0, 0.90),
    ("rate near the edge, heavy tail",          80, 1.8, 1.0, 0.90),
)


def _cluster_sizes(m: int, exponent: float) -> list[int]:
    """Zipf-shaped sizes, floored at one endpoint per cluster."""
    return [max(1, int((m / (i + 1)) ** (1.0 / exponent))) for i in range(m)]


def coverage(
    m: int, exponent: float, rho: float, p: float, rng: random.Random, trials: int = TRIALS
) -> tuple[float, int, int]:
    """Fraction of naive 95% Wilson intervals containing `p`, with n and the cluster count."""
    sizes = _cluster_sizes(m, exponent)
    n = sum(sizes)
    covered = 0
    for _ in range(trials):
        k = 0
        for size in sizes:
            cluster_outcome = 1 if rng.random() < p else 0
            for _ in range(size):
                # With probability rho the endpoint inherits its cluster's outcome -- a shared
                # default, copied. Otherwise it draws for itself.
                if rng.random() < rho:
                    k += cluster_outcome
                elif rng.random() < p:
                    k += 1
        low, high = wilson_interval(k, n)
        if low <= p <= high:
            covered += 1
    return covered / trials, n, len(sizes)


def simulate(trials: int = TRIALS) -> dict:
    rng = random.Random(SEED)
    rows = []
    for label, m, exponent, rho, p in SCENARIOS:
        cov, n, clusters = coverage(m, exponent, rho, p, rng, trials)
        rows.append({
            "scenario": label, "clusters": clusters, "n": n,
            "zipf_exponent": exponent, "rho": rho, "propensity": p,
            "naive_wilson_coverage": round(cov, 4),
        })
    values = [row["naive_wilson_coverage"] for row in rows]
    return {
        "schema": SCHEMA,
        "seed": SEED,
        "trials_per_scenario": trials,
        "nominal_coverage": 0.95,
        "quoted_range": [math.floor(min(values) * 100) / 100,
                         math.ceil(max(values) * 100) / 100],
        "note": (
            "Real coverage of a nominal 95% Wilson interval when endpoints are clustered. "
            "The `quoted_range` bounds are what analysis.py's docstring and decision rule "
            "R10.4 are permitted to state; tests/test_analysis.py enforces the match. "
            "Regenerate with scripts/wilson_coverage_under_clustering.py --write."
        ),
        "scenarios": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help=f"regenerate {RESULT_FILE.relative_to(ROOT)}")
    parser.add_argument("--trials", type=int, default=TRIALS)
    args = parser.parse_args()

    result = simulate(args.trials)
    print(f"Naive 95% Wilson coverage under clustering "
          f"({args.trials} trials/scenario, seed {SEED})\n")
    for row in result["scenarios"]:
        print(f"{row['naive_wilson_coverage'] * 100:5.1f}%  n={row['n']:>6}  "
              f"m={row['clusters']:>4}  p={row['propensity']:.2f}  "
              f"rho={row['rho']:.1f}  {row['scenario']}")
    low, high = result["quoted_range"]
    print(f"\nrange across scenarios: {low:.0%}-{high:.0%} (nominal 95%)")

    if args.write:
        RESULT_FILE.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {RESULT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
