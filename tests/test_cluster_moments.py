"""The published moments are sufficient for the published intervals (YK1, 1 November 2026).

The census is not shared, and what is shared in its place is, per printed interval, six sums.
That substitution is only honest if the sums reproduce the interval, so it is tested here against
the estimator itself rather than asserted.
"""

import math
import random

from agentidprobe.analysis import (
    cluster_moments,
    cluster_robust_proportion,
    proportion_from_moments,
)


def _agree(clusters):
    estimate = cluster_robust_proportion(clusters)
    p_hat, lo, hi = proportion_from_moments(cluster_moments(clusters))
    assert math.isclose(p_hat, estimate.p_hat, abs_tol=1e-12)
    assert math.isclose(lo, estimate.lo, abs_tol=1e-9), (clusters, lo, estimate.lo)
    assert math.isclose(hi, estimate.hi, abs_tol=1e-9), (clusters, hi, estimate.hi)


def test_moments_reproduce_the_interval_on_random_shapes():
    rng = random.Random(20261101)
    for _ in range(300):
        m = rng.randint(2, 60)
        p = rng.random()
        clusters = []
        for _ in range(m):
            n = max(1, int(rng.paretovariate(1.2)))
            clusters.append((sum(rng.random() < p for _ in range(n)), n))
        _agree(clusters)


def test_moments_reproduce_every_boundary_rule():
    _agree([(0, 3), (0, 1), (0, 7)])                      # zero: one-sided bound
    _agree([(3, 3), (1, 1), (7, 7)])                      # all: one-sided bound
    _agree([(1, 40)] + [(0, 1)] * 30)                     # clamp: Wilson at n_eff
    _agree([(5, 5)])                                      # one cluster: Wilson
    _agree([(1, 2), (1, 2), (1, 2)])                      # floor binds


def test_moments_carry_no_per_cluster_entry():
    moments = cluster_moments([(1, 1281), (0, 3), (2, 2)])
    assert set(moments) == {"m", "n", "k", "sum_n2", "sum_kn", "sum_k2"}


def test_the_committed_moments_reproduce_their_own_intervals():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "docs" / "cluster-moments-census2.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["intervals"]
    for row in data["intervals"]:
        assert set(row["moments"]) == {"m", "n", "k", "sum_n2", "sum_kn", "sum_k2"}
        p_hat, lo, hi = proportion_from_moments(row["moments"])
        assert math.isclose(p_hat, row["p_hat"], abs_tol=1e-12)
        assert math.isclose(lo, row["interval"][0], abs_tol=1e-12)
        assert math.isclose(hi, row["interval"][1], abs_tol=1e-12)
