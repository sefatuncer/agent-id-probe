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

from agentidprobe.analysis import (  # noqa: E402
    cluster_robust_proportion,
    wilson_interval,
)

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
    # Added 14 August 2026. The seven scenarios above vary the *naive* estimator, which the
    # paper does not publish; a referee pointed out that nothing measured the two estimators
    # it does publish, one of which -- Wilson evaluated at the effective sample size -- is
    # the naive estimator with a smaller argument, on the figure Section 8.1 leads with.
    # These three sit where that substitution actually fires: a low rate over a couple of
    # hundred observations in eighty-odd clusters, which is the 9-of-202 shape.
    ("boundary-adjacent rate, heavy tail",      82, 1.8, 1.0, 0.045),
    ("boundary-adjacent rate, partial",         82, 1.8, 0.5, 0.045),
    ("boundary-adjacent rate, many clusters",  200, 1.1, 1.0, 0.045),
)

#: The published estimators, and the naive one kept for the range Section 4.5 already
#: quotes. Appending scenarios rather than editing them keeps the earlier rows' random
#: stream and therefore the committed 20%-88% range intact.
ESTIMATORS = ("naive_wilson", "cluster_robust", "wilson_at_neff")


def _cluster_sizes(m: int, exponent: float) -> list[int]:
    """Zipf-shaped sizes, floored at one endpoint per cluster."""
    return [max(1, int((m / (i + 1)) ** (1.0 / exponent))) for i in range(m)]


def coverage(
    m: int, exponent: float, rho: float, p: float, rng: random.Random, trials: int = TRIALS
) -> tuple[dict[str, float], int, int]:
    """Real coverage of each 95% interval this repository can produce, against nominal.

    Three estimators are measured on the same draws, because the question a reader asks is
    not "is the naive interval bad" -- Section 4.5 already says it is -- but "is the one you
    published any better". They are the naive Wilson interval, the cluster-robust t interval
    that the paper publishes, and Wilson evaluated at the effective sample size, which the
    boundary rule substitutes when a symmetric interval would clamp onto zero or one.

    The random stream is untouched from the seven-scenario version: the extra estimators are
    computed from the same per-cluster counts and draw nothing of their own.
    """
    sizes = _cluster_sizes(m, exponent)
    n = sum(sizes)
    covered = dict.fromkeys(ESTIMATORS, 0)
    for _ in range(trials):
        clusters: list[tuple[int, int]] = []
        for size in sizes:
            cluster_outcome = 1 if rng.random() < p else 0
            hits = 0
            for _ in range(size):
                # With probability rho the endpoint inherits its cluster's outcome -- a shared
                # default, copied. Otherwise it draws for itself.
                if rng.random() < rho:
                    hits += cluster_outcome
                elif rng.random() < p:
                    hits += 1
            clusters.append((hits, size))
        k = sum(hits for hits, _ in clusters)

        low, high = wilson_interval(k, n)
        if low <= p <= high:
            covered["naive_wilson"] += 1

        estimate = cluster_robust_proportion(clusters)
        if estimate.lo <= p <= estimate.hi:
            covered["cluster_robust"] += 1

        # The substitution as `cluster_robust_proportion` applies it, including the floor:
        # a design effect below one may not buy precision. Applied here to every draw rather
        # than only to clamped ones, because the question is what the estimator covers.
        deff = max(estimate.deff or 1.0, 1.0)
        low, high = wilson_interval(k / deff, n / deff)
        if low <= p <= high:
            covered["wilson_at_neff"] += 1

    return {name: covered[name] / trials for name in ESTIMATORS}, n, len(sizes)


def simulate(trials: int = TRIALS) -> dict:
    rng = random.Random(SEED)
    rows = []
    for label, m, exponent, rho, p in SCENARIOS:
        cov, n, clusters = coverage(m, exponent, rho, p, rng, trials)
        rows.append({
            "scenario": label, "clusters": clusters, "n": n,
            "zipf_exponent": exponent, "rho": rho, "propensity": p,
            "naive_wilson_coverage": round(cov["naive_wilson"], 4),
            "cluster_robust_coverage": round(cov["cluster_robust"], 4),
            "wilson_at_neff_coverage": round(cov["wilson_at_neff"], 4),
        })

    def _range(field: str, rows_in: list[dict]) -> list[float]:
        values = [row[field] for row in rows_in]
        return [math.floor(min(values) * 100) / 100, math.ceil(max(values) * 100) / 100]

    boundary = [row for row in rows if row["propensity"] < 0.1]
    return {
        "schema": SCHEMA,
        "seed": SEED,
        "trials_per_scenario": trials,
        "nominal_coverage": 0.95,
        # Over every scenario, including the three added on 14 August 2026. Quoting it over
        # the first seven only would have kept Section 4.5's existing sentence intact and
        # would have been a range chosen over a subset of the scenarios actually run, which
        # is the shape of selection this repository exists to forbid. The top end moves
        # from 88% to 89% and the argument is unaffected.
        "quoted_range": _range("naive_wilson_coverage", rows),
        "published_estimator_range": _range("cluster_robust_coverage", rows),
        "wilson_at_neff_range": _range("wilson_at_neff_coverage", rows),
        # The substitution is only ever applied near a boundary, so its coverage there is
        # the number that licenses the one figure it produced.
        "wilson_at_neff_range_boundary": _range("wilson_at_neff_coverage", boundary)
        if boundary else None,
        "cluster_robust_range_boundary": _range("cluster_robust_coverage", boundary)
        if boundary else None,
        "note": (
            "Real coverage of three nominal 95% intervals when endpoints are clustered: the "
            "naive Wilson interval, the cluster-robust t interval this study publishes, and "
            "Wilson evaluated at the effective sample size, which the boundary rule "
            "substitutes when a symmetric interval would clamp. `quoted_range` covers the "
            "first seven scenarios only and is what analysis.py's docstring and decision "
            "rule R10.4 are permitted to state; tests/test_analysis.py enforces the match. "
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
    print(f"Real coverage of nominal 95% intervals under clustering "
          f"({args.trials} trials/scenario, seed {SEED})\n")
    print(f"{'naive':>7} {'robust':>7} {'W@neff':>7}  {'n':>6} {'m':>5} "
          f"{'p':>5} {'rho':>4}  scenario")
    for row in result["scenarios"]:
        print(f"{row['naive_wilson_coverage'] * 100:6.1f}% "
              f"{row['cluster_robust_coverage'] * 100:6.1f}% "
              f"{row['wilson_at_neff_coverage'] * 100:6.1f}%  "
              f"{row['n']:>6} {row['clusters']:>5} "
              f"{row['propensity']:>5.3f} {row['rho']:>4.1f}  {row['scenario']}")
    low, high = result["quoted_range"]
    print(f"\nnaive, first seven scenarios : {low:.0%}-{high:.0%}  (the quoted range)")
    low, high = result["published_estimator_range"]
    print(f"cluster-robust, all scenarios: {low:.0%}-{high:.0%}")
    low, high = result["wilson_at_neff_range"]
    print(f"Wilson at n_eff, all         : {low:.0%}-{high:.0%}")
    if result["wilson_at_neff_range_boundary"]:
        low, high = result["wilson_at_neff_range_boundary"]
        print(f"Wilson at n_eff, boundary    : {low:.0%}-{high:.0%}  "
              f"(where the substitution fires)")
        low, high = result["cluster_robust_range_boundary"]
        print(f"cluster-robust, boundary     : {low:.0%}-{high:.0%}")

    if args.write:
        RESULT_FILE.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {RESULT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
