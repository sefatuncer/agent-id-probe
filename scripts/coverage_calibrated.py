"""Coverage of each published interval, simulated from that interval's own cluster structure.

`wilson_coverage_under_clustering.py` measures the estimators over ten synthetic Zipf shapes,
but a range over invented shapes does not say what any *printed* interval covers. This script
answers that question for each one.

For every published interval it takes the clusters the interval was computed over, read through
the instrument's own `unit_clusters` and `issuer_clusters` so that no denominator rule is
re-implemented here, and a *dependence grouping*: the groups within which outcomes are believed
to be correlated. For the endpoint and issuer rates that is the interval's own clustering. For
the apex and implementation units, where each cluster is a single observation, it is the
grouping the published interval does not correct for: apexes sharing an implementation
fingerprint, and fingerprints sharing an apex.

Outcomes are then drawn from a beta-binomial model. Each dependence group draws a propensity
from a Beta distribution with the interval's observed rate as its mean and a given intra-class
correlation, and each member draws its outcome independently given that propensity. The
published estimator, `cluster_robust_proportion` with every rule it applies, is run on each
draw, and coverage is the share of draws whose interval contains the model's mean. Where the
dependence grouping differs from the published clustering, the interval clustered on the
dependence grouping is measured too: it is the correction the published interval leaves out.

The ICC is the one-way ANOVA estimate from the data, and coverage is also reported over a fixed
grid of ICC values. Both of these, and one exclusion, were added after a 40-trial smoke run and
before any full run, because the smoke run showed two things the design had not anticipated:

* The ANOVA estimator is unstable for a rare outcome. Its within-group variance then comes from
  a handful of mixed groups, and for C18 it reached the 0.999 clamp. The grid shows how much the
  coverage depends on that one poorly estimated parameter.
* For C05, grouping apexes by implementation fingerprint sorts them by their own outcome. The
  fingerprint is built from the documents C05 asks for, and an endpoint that fails for want of
  a document is fingerprinted by its Server header alone. That row is therefore not simulated.

The model is a stated assumption, not a property of the corpus: a beta-binomial cannot carry the
size-outcome dependence that `ProportionEstimate.n_eff_interpretable` flags. A count of zero has
no interior rate to simulate at and is reported as not simulated.

    python scripts/coverage_calibrated.py --run-id census2            # print the table
    python scripts/coverage_calibrated.py --run-id census2 --write    # regenerate the JSON

The simulation runs at idle priority on `--workers` processes (default 3), so it does not take
the machine it runs on: a run on all cores left the machine unusable. Every job carries its own
seed, so the result does not depend on the number of workers.

The result is committed as `docs/coverage-calibrated.json`. It carries no endpoint, domain or
issuer: only each interval's counts, numbers of clusters, ICC and coverage.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentidprobe.analysis import (  # noqa: E402
    _advertises_iss,
    _apex,
    _offers_client_bootstrap,
    _publishes_protected_resources,
    build_delegation_graph,
    cluster_robust_proportion,
    issuer_clusters,
    issuer_documents,
    unit_clusters,
    wild_cluster_bootstrap_ci,
)

RESULT_FILE = ROOT / "docs" / "coverage-calibrated.json"
SCHEMA = "agent-id-probe/coverage-calibrated/1"
# Chosen before the first run, so the printed coverages are reproducible and were not searched
# for. The date the calibration was written.
SEED = 20261101
TRIALS = 10000
WCB_REPS = 9999
# From independence to near-total agreement within a group. Fixed with the grid's introduction
# after the smoke run (see the module docstring), before any full run.
ICC_GRID = (0.0, 0.05, 0.2, 0.5, 0.9)


# -- the model -------------------------------------------------------------------------

def anova_icc(groups: list[tuple[int, int]]) -> float:
    """One-way ANOVA estimator of the intra-class correlation of a binary outcome.

    `groups` are (successes, size). Unequal sizes enter through n0, the usual adjusted mean
    group size. Singleton groups carry no within-group information, so a grouping made only
    of singletons has no estimable ICC and returns 0. The estimate is clamped to [0, 0.999]:
    a negative ICC is sampling noise around independence, and 1 leaves no Beta distribution.
    """
    groups = [(k, n) for k, n in groups if n > 0]
    m = len(groups)
    total = sum(n for _, n in groups)
    if m < 2 or total <= m:
        return 0.0
    p = sum(k for k, _ in groups) / total
    msb = sum(n * (k / n - p) ** 2 for k, n in groups) / (m - 1)
    msw = sum(k - k * k / n for k, n in groups) / (total - m)
    n0 = (total - sum(n * n for _, n in groups) / total) / (m - 1)
    denominator = msb + (n0 - 1.0) * msw
    if denominator <= 0:
        return 0.0
    return min(max((msb - msw) / denominator, 0.0), 0.999)


def draw_propensity(rng: random.Random, p: float, icc: float) -> float:
    """One dependence group's propensity under the beta-binomial model."""
    if icc <= 0.0:
        return p
    scale = 1.0 / icc - 1.0
    return rng.betavariate(p * scale, (1.0 - p) * scale)


def simulate(task: dict) -> dict:
    """Coverage of the published estimator (and of the dependence-clustered one) on one interval.

    `task["layout"]` holds one (size, singletons) pair per dependence group. When `singletons`
    is False the group is one published cluster; when True each member is its own published
    cluster, as at the apex and implementation units. Members share the group's propensity and
    draw independently given it.
    """
    rng = random.Random(task["seed"])
    p, icc = task["p_hat"], task["icc"]
    covered = covered_alt = 0
    for _ in range(task["trials"]):
        published: list[tuple[int, int]] = []
        dependence: list[tuple[int, int]] = []
        for size, singletons in task["layout"]:
            propensity = draw_propensity(rng, p, icc)
            draws = [1 if rng.random() < propensity else 0 for _ in range(size)]
            hits = sum(draws)
            dependence.append((hits, size))
            if singletons:
                published.extend((d, 1) for d in draws)
            else:
                published.append((hits, size))
        estimate = cluster_robust_proportion(published)
        if estimate.lo <= p <= estimate.hi:
            covered += 1
        if task["alternative"]:
            alt = cluster_robust_proportion(dependence)
            if alt.lo <= p <= alt.hi:
                covered_alt += 1
    trials = task["trials"]
    return {"coverage": covered / trials,
            "coverage_dependence_clustered": (covered_alt / trials if task["alternative"]
                                              else None)}


# -- the published intervals -------------------------------------------------------------

def _layout(groups: list[tuple[int, int]], singletons: bool) -> list[tuple[int, bool]]:
    return [(n, singletons) for _, n in groups]


def published_intervals(reports: list) -> list[dict]:
    """Each interval the manuscript prints, with its clusters and dependence grouping."""
    from agentidprobe.models import CheckId

    tasks: list[dict] = []
    checks = (("c05", CheckId.PRM_PRESENT, True),
              ("c12", CheckId.PRM_RESOURCE_IDENTITY_MATCH, False),
              ("c13", CheckId.AS_CORRESPONDENCE, False))
    for key, check, challenged_only in checks:
        clusters = unit_clusters(reports, check, "endpoint", challenged_only=challenged_only)
        tasks.append({"key": f"{key}-endpoint", "unit": "endpoint",
                      "published_clustering": "apex", "dependence": "apex",
                      "clusters": clusters, "groups": clusters,
                      "layout": _layout(clusters, False), "alternative": False})
        for unit, dependence in (("apex", "implementation"), ("implementation", "apex")):
            clusters = unit_clusters(reports, check, unit, challenged_only=challenged_only)
            groups = unit_clusters(reports, check, unit, challenged_only=challenged_only,
                                   cluster_by=dependence)
            task = {"key": f"{key}-{unit}", "unit": unit,
                    "published_clustering": "none (one observation per cluster)",
                    "dependence": dependence, "clusters": clusters, "groups": groups,
                    "layout": _layout(groups, True), "alternative": True}
            if key == "c05" and dependence == "implementation":
                task["outcome_defined"] = (
                    "the implementation fingerprint is built from the documents C05 asks "
                    "for, so grouping C05's apexes by it sorts them by their own outcome")
            tasks.append(task)

    declared = issuer_documents(reports, "declared")
    observed = issuer_documents(reports, "observed")
    graph = build_delegation_graph(reports)
    crossing = {issuer for resource_apex, issuer in graph.edges
                if (ia := _apex(issuer)) is not None and ia != resource_apex}
    crossing_docs = {i: d for i, d in declared.items() if i in crossing}
    for key, docs, predicate in (
            ("c16", declared, _advertises_iss),
            ("c18", observed, _publishes_protected_resources),
            ("c16-crossing", crossing_docs, _advertises_iss),
            ("c18-crossing", crossing_docs, _publishes_protected_resources)):
        clusters = issuer_clusters(docs, predicate)
        tasks.append({"key": key, "unit": "issuer", "published_clustering": "issuer apex",
                      "dependence": "issuer apex", "clusters": clusters, "groups": clusters,
                      "layout": _layout(clusters, False), "alternative": False})

    # The remaining intervals Tables 5 and 7 print: C05's declared sensitivity arm and C17.
    # Appended rather than interleaved, so that adding them left every earlier row's seed
    # unchanged.
    clusters = unit_clusters(reports, CheckId.PRM_PRESENT, "endpoint")
    tasks.append({"key": "c05-wider-endpoint", "unit": "endpoint",
                  "published_clustering": "apex", "dependence": "apex",
                  "clusters": clusters, "groups": clusters,
                  "layout": _layout(clusters, False), "alternative": False})
    for unit, dependence in (("apex", "implementation"), ("implementation", "apex")):
        clusters = unit_clusters(reports, CheckId.PRM_PRESENT, unit)
        groups = unit_clusters(reports, CheckId.PRM_PRESENT, unit, cluster_by=dependence)
        task = {"key": f"c05-wider-{unit}", "unit": unit,
                "published_clustering": "none (one observation per cluster)",
                "dependence": dependence, "clusters": clusters, "groups": groups,
                "layout": _layout(groups, True), "alternative": True}
        if dependence == "implementation":
            task["outcome_defined"] = (
                "the implementation fingerprint is built from the documents C05 asks "
                "for, so grouping C05's apexes by it sorts them by their own outcome")
        tasks.append(task)
    clusters = issuer_clusters(declared, _offers_client_bootstrap)
    tasks.append({"key": "c17", "unit": "issuer", "published_clustering": "issuer apex",
                  "dependence": "issuer apex", "clusters": clusters, "groups": clusters,
                  "layout": _layout(clusters, False), "alternative": False})
    return tasks


def _lower_priority() -> None:
    """Idle priority for this process and, by inheritance, its pool workers."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        idle = 0x00000040
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Without these the pseudo-handle -1 is passed as a 32-bit int and the call fails.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        if not kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), idle):
            raise OSError(ctypes.get_last_error(), "SetPriorityClass failed")
    else:
        import os

        os.nice(19)


def run(run_id: str, trials: int, workers: int = 3) -> dict:
    from agentidprobe.store import RunStore

    reports = RunStore(ROOT, run_id).read_reports()
    tasks = published_intervals(reports)
    jobs, rows = [], []
    for index, task in enumerate(tasks):
        estimate = cluster_robust_proportion(task["clusters"])
        groups = task["groups"]
        icc = anova_icc(groups)
        row = {
            "key": task["key"], "unit": task["unit"],
            "published_clustering": task["published_clustering"],
            "dependence_grouping": task["dependence"],
            "k": estimate.k, "n": estimate.n, "m": estimate.m,
            "m_dependence": len(groups),
            "dependence_singleton_share": sum(1 for _, n in groups if n == 1) / len(groups),
            "dependence_largest": max(n for _, n in groups),
            "p_hat": estimate.p_hat, "published": [estimate.lo, estimate.hi],
            "method": estimate.method, "icc": icc,
        }
        if task["alternative"]:
            alt = cluster_robust_proportion(groups)
            row["dependence_clustered"] = [alt.lo, alt.hi]
        row["wild_cluster_bootstrap"] = list(
            wild_cluster_bootstrap_ci(task["clusters"], reps=WCB_REPS, seed=SEED))
        rows.append(row)
        if "outcome_defined" in task:
            row["coverage"] = None
            row["coverage_note"] = "not simulated: " + task["outcome_defined"]
            continue
        if not 0 < estimate.k < estimate.n:
            row["coverage"] = None
            row["coverage_note"] = ("not simulated: the count is on the boundary, the interval "
                                    "is a one-sided bound, and there is no interior rate to "
                                    "simulate at")
            continue
        for position, value in enumerate((icc, *ICC_GRID)):
            jobs.append({"key": task["key"], "slot": "estimated" if position == 0 else value,
                         "p_hat": estimate.p_hat, "icc": value, "layout": task["layout"],
                         "alternative": task["alternative"], "trials": trials,
                         "seed": SEED + 100 * index + position})

    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(simulate, jobs))
    by_key: dict[str, list] = {}
    for job, result in zip(jobs, results, strict=True):
        by_key.setdefault(job["key"], []).append((job["slot"], result))
    for row in rows:
        for slot, result in by_key.get(row["key"], []):
            dependent = result["coverage_dependence_clustered"]
            if slot == "estimated":
                row["coverage"] = result["coverage"]
                if dependent is not None:
                    row["coverage_dependence_clustered"] = dependent
            else:
                row.setdefault("coverage_by_icc", {})[f"{slot:g}"] = result["coverage"]
                if dependent is not None:
                    row.setdefault("coverage_dependence_clustered_by_icc", {})[
                        f"{slot:g}"] = dependent

    simulated = [row for row in rows if row.get("coverage") is not None]
    at_estimate = [row["coverage"] for row in simulated]
    over_grid = [c for row in simulated for c in row["coverage_by_icc"].values()]
    return {
        "schema": SCHEMA, "run_id": run_id, "seed": SEED, "trials": trials,
        "wcb_reps": WCB_REPS, "nominal_coverage": 0.95, "icc_grid": list(ICC_GRID),
        "coverage_at_estimated_icc": [min(at_estimate), max(at_estimate)],
        "coverage_over_icc_grid": [min(over_grid), max(over_grid)],
        "below_090_at_estimated_icc": sorted(row["key"] for row in simulated
                                             if row["coverage"] < 0.90),
        "model": ("beta-binomial: one propensity per dependence group, Beta with the observed "
                  "rate as mean and the ANOVA ICC (or a grid value); members draw "
                  "independently given it; the coverage target is the model mean"),
        "intervals": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="census2")
    parser.add_argument("--trials", type=int, default=TRIALS)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    _lower_priority()
    result = run(args.run_id, args.trials, workers=args.workers)
    grid = "/".join(f"{g:g}" for g in ICC_GRID)
    print(f"{'key':<20} {'k/n':>11} {'m':>5} {'m_dep':>5} {'ICC':>6} {'published':>17} "
          f"{'cov':>6} {'dep-cl':>6}  cov at ICC {grid}")
    for row in result["intervals"]:
        cov = f"{row['coverage']:.1%}" if row.get("coverage") is not None else "  --"
        alt = row.get("coverage_dependence_clustered")
        alt = f"{alt:.1%}" if alt is not None else ""
        lo, hi = row["published"]
        by_icc = " ".join(f"{c:.0%}" for c in row.get("coverage_by_icc", {}).values())
        print(f"{row['key']:<20} {row['k']:>5}/{row['n']:<5} {row['m']:>5} "
              f"{row['m_dependence']:>5} {row['icc']:6.3f} [{lo:6.1%}, {hi:6.1%}] {cov:>6} "
              f"{alt:>6}  {by_icc}")
    print()
    for row in result["intervals"]:
        wlo, whi = row["wild_cluster_bootstrap"]
        extra = ""
        if "dependence_clustered" in row:
            dlo, dhi = row["dependence_clustered"]
            extra = f"   clustered on {row['dependence_grouping']}: [{dlo:.1%}, {dhi:.1%}]"
        print(f"{row['key']:<20} WCB [{wlo:.1%}, {whi:.1%}]{extra}")
    lo, hi = result["coverage_at_estimated_icc"]
    glo, ghi = result["coverage_over_icc_grid"]
    print(f"\nat the estimated ICC the published intervals cover {lo:.1%}-{hi:.1%}; "
          f"over the grid {glo:.1%}-{ghi:.1%} ({result['trials']} trials, seed {SEED})")
    print("below 90% at the estimated ICC:", ", ".join(result["below_090_at_estimated_icc"]))
    if args.write:
        RESULT_FILE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8",
                               newline="\n")
        print(f"wrote {RESULT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
