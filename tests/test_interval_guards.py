"""Two guards on the interval machinery, both added after a referee ran it.

The first is the boundary substitution's divisor. `cluster_robust_proportion` already floors
the *variance* at the simple-random-sample variance, on the principle that clustering may
reveal a smaller effective sample but may never manufacture precision no sample of this size
could have. The substitution that replaces a clamped symmetric interval divided by the raw
design effect, which is not floored, so where the clustering happens to be tighter than
random sampling the substitution evaluated Wilson at *more* observations than were collected
-- breaking the same principle two dozen lines below where it is stated.

The second is the tolerance in the design-effect ceiling test. It was 10%, undocumented, and
it was what kept one published interval unflagged.
"""
from __future__ import annotations

import pytest

from agentidprobe.analysis import (
    RELATIVE_EPSILON,
    cluster_robust_proportion,
    wilson_interval,
)

#: Found by search over random cluster configurations: the design effect falls below one
#: and the symmetric interval still clamps, which is the combination that reaches the
#: unfloored divisor. Roughly one configuration in twenty-six of that search did, so the
#: branch is not hypothetical.
DEFF_BELOW_ONE = [(2, 40), (0, 13), (0, 3), (0, 1), (1, 3), (0, 5), (1, 1), (1, 5)]


def test_the_search_fixture_really_does_reach_the_branch():
    """Guard the guard: if this stops holding, the tests below prove nothing."""
    estimate = cluster_robust_proportion(DEFF_BELOW_ONE)
    assert estimate.deff is not None
    assert 0.0 < estimate.deff < 1.0, "fixture no longer produces a design effect below one"
    assert "Wilson at the effective sample size" in estimate.method, (
        "fixture no longer clamps, so the substitution is not exercised"
    )


def test_the_substitution_never_evaluates_wilson_at_more_than_n():
    """A design effect below one may not buy precision.

    Without the floor this returns Wilson at n / deff, which is a wider interval's worth of
    observations than exist. The floor makes it Wilson at n exactly.
    """
    estimate = cluster_robust_proportion(DEFF_BELOW_ONE)
    k = sum(hits for hits, _ in DEFF_BELOW_ONE)
    n = sum(size for _, size in DEFF_BELOW_ONE)
    expected = wilson_interval(k, n)

    assert (estimate.lo, estimate.hi) == pytest.approx(expected)

    unfloored = wilson_interval(k / estimate.deff, n / estimate.deff)
    assert (unfloored[1] - unfloored[0]) < (estimate.hi - estimate.lo), (
        "the unfloored substitution should be narrower, or this test is not testing the floor"
    )


def test_the_published_deff_still_reports_the_raw_ratio():
    """Only the substitution is floored. A design effect below one is a real finding."""
    estimate = cluster_robust_proportion(DEFF_BELOW_ONE)
    assert estimate.deff < 1.0
    assert estimate.n_eff > estimate.n


# -- the ceiling test -------------------------------------------------------------------


def _collapsed(m: int) -> list[tuple[int, int]]:
    """One observation per cluster, which is what the apex and implementation units are.

    Here the design effect and the ceiling are the same quantity -- both reduce to
    m / (m - 1) -- so they agree in exact arithmetic and differ in the last bit.
    """
    return [(1, 1)] * (m // 2) + [(0, 1)] * (m - m // 2)


@pytest.mark.parametrize("m", [1183, 1579, 1741, 2098, 1117])
def test_collapsed_units_are_never_flagged_by_floating_point_alone(m):
    """The failure a zero-tolerance rule produced.

    With no slack, five of these rows were marked and two otherwise identical ones were
    not, decided by the last bit of a division. The claim attached to the mark -- that the
    interval's width is a statement about one dominant cluster -- is false for every one of
    them, because each cluster holds a single observation.
    """
    estimate = cluster_robust_proportion(_collapsed(m))
    assert estimate.n_eff_interpretable, (
        f"m={m}: a unit whose clusters are singletons has no dominant cluster to warn about"
    )


def _size_outcome_dependent(cluster: int, singletons: int) -> list[tuple[int, int]]:
    """One all-successes cluster of size `cluster`, and `singletons` all-failure singletons.

    This is the corpus's own shape in miniature and the condition is exact rather than
    empirical: with the successes concentrated in the large clusters and the rate below a
    half, the sum of squares exceeds what the sizes alone can produce whenever the large
    cluster holds more than one observation.
    """
    return [(cluster, cluster)] + [(0, 1)] * singletons


@pytest.mark.parametrize(("cluster", "singletons"), [(15, 40), (10, 50), (6, 30)])
def test_a_substantive_excess_is_flagged(cluster, singletons):
    """The real condition: one large cluster carrying the rate on its own."""
    estimate = cluster_robust_proportion(_size_outcome_dependent(cluster, singletons))
    assert estimate.deff > estimate.size_outcome_ceiling
    assert estimate.top_cluster_variance_share > 0.9
    assert not estimate.n_eff_interpretable


def _marginal_excess(cluster: int) -> list[tuple[int, int]]:
    """One all-successes cluster of size `cluster`, and `cluster + 1` all-failure singletons.

    Solving the ratio exactly for this shape gives DEFF / ceiling = s(z + 1) / (s^2 + z),
    which approaches one from above as z approaches s. It is the only way to reach the
    band the old 10% tolerance covered, and the largest of these reproduces C05's own
    endpoint row to three decimal places.
    """
    return [(cluster, cluster)] + [(0, 1)] * (cluster + 1)


@pytest.mark.parametrize("cluster", [10, 20, 50, 100])
def test_a_marginal_excess_the_old_tolerance_spared_is_now_flagged(cluster):
    """The regression guard the first version of this file did not have.

    Written after a revert test found that restoring `ceiling * 1.10` left every test in
    this file passing: the fixtures above all exceed their ceiling by more than double, so
    they were flagged under either rule and locked down nothing. This is the band that
    separates them, and C05's endpoint row lives in it at 1.009.
    """
    estimate = cluster_robust_proportion(_marginal_excess(cluster))
    ratio = estimate.deff / estimate.size_outcome_ceiling
    assert 1.0 < ratio < 1.10, f"fixture no longer sits in the disputed band (ratio {ratio})"
    assert estimate.deff <= estimate.size_outcome_ceiling * 1.10, (
        "the old rule must spare this fixture, or it does not test the change"
    )
    assert not estimate.n_eff_interpretable, (
        "an excess the cluster sizes cannot produce must be flagged however small it is; "
        "restoring a substantive tolerance would let this pass"
    )


def test_the_tolerance_is_numerical_and_not_substantive():
    """The old rule allowed a 10% excess. This one allows about a billionth.

    The distinction is not academic: C05 at the endpoint unit exceeds its ceiling by 0.9%
    and was spared by the old constant while carrying 57% of its between-cluster sum of
    squares in a single cluster, which is the condition the flag announces.
    """
    assert RELATIVE_EPSILON < 1e-6

    estimate = cluster_robust_proportion(_size_outcome_dependent(15, 40))
    ceiling = estimate.size_outcome_ceiling
    assert ceiling is not None
    # An excess of a tenth of a percent -- two orders below the old tolerance -- must fall
    # outside the slack, or the slack is deciding results rather than absorbing float error.
    assert ceiling * 1.001 > ceiling * (1.0 + RELATIVE_EPSILON)
    # And the slack must still be wide enough to cover a last-bit disagreement.
    assert ceiling * (1.0 + 1e-15) <= ceiling * (1.0 + RELATIVE_EPSILON)
