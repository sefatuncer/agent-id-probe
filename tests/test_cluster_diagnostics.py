"""What the cluster-robust ratio is allowed to claim about itself.

Two defects were published side by side and neither had a test.

The first: the interval is a symmetric t interval clamped into [0, 1] afterwards, so a rate
of nine successes in 202 observations printed as ``4.5% [0.0%, 9.0%]``. A lower bound of
exactly zero says the nine may not have occurred, which the data excludes. Where the clamp
binds the published interval is now Wilson at the effective sample size, which respects the
boundary and keeps the clustering correction instead of discarding it.

The second is subtler and was the one a referee could not have checked without the corpus:
``deff`` is a ratio of two variances and ``n_eff`` divides the observation count by it, and
over the delegation graph that produced ``n_eff = 123`` beside ``m = 1,814`` clusters.

The obvious reading -- that an effective sample below the cluster count is impossible -- is
wrong, and these tests fix that too. A ratio estimator weights clusters by size, so a corpus
with a few large clusters really can carry less information than an equally weighted mean
over its clusters would; ``n_eff < m`` is then correct arithmetic about a real loss.

What is diagnostic is the ceiling. Under the exchangeable model ``deff = 1 + (kish - 1) *
ICC`` with ``ICC <= 1``, so ``kish * m/(m-1)`` bounds what the cluster *sizes* can produce.
Above it the excess comes from the outcome depending on cluster size -- the largest clusters
sitting on the minority side of the rate -- and the sentence "as if it were n_eff independent
observations" stops being true of the number. The interval is not the defect: one apex
declaring eighty issuers really does move a rate. So the interval stands and only the gloss
on the derived statistic is withdrawn.
"""

import math

from agentidprobe.analysis import cluster_robust_proportion


def test_kish_is_the_effective_cluster_size() -> None:
    # sum(n_i^2)/sum(n_i) = (4 + 4 + 16) / 8 = 3.0
    est = cluster_robust_proportion([(1, 2), (1, 2), (2, 4)])
    assert est.kish == 3.0


def test_equal_singletons_have_a_ceiling_of_one_and_stay_interpretable() -> None:
    """With one observation per cluster there is no clustering to correct for."""
    est = cluster_robust_proportion([(1, 1)] * 30 + [(0, 1)] * 70)
    assert est.kish == 1.0
    assert est.n_eff_interpretable
    assert est.deff is not None and est.deff <= est.size_outcome_ceiling


def test_size_skew_alone_may_put_n_eff_below_m_and_that_is_not_a_defect() -> None:
    """Unequal clusters that agree with each other: real precision loss, no flag.

    This is the case the crude "n_eff < m is impossible" reading would have condemned.
    The rate is the same inside every cluster, so nothing about the outcome depends on
    cluster size, and the design effect stays inside the ceiling.
    """
    # Small clusters sit on the overall rate; the large ones scatter around it in both
    # directions, so size carries no information about the outcome.
    clusters = [(1, 2)] * 200 + [(32, 40)] * 2 + [(8, 40)] * 3 + [(72, 120)]
    est = cluster_robust_proportion(clusters)
    assert est.n_eff is not None and est.n_eff < est.m
    assert est.deff is not None and est.deff > 1.0
    assert est.n_eff_interpretable, "an honest precision loss must not be flagged"


def test_one_dominant_cluster_pushes_deff_past_what_the_sizes_allow() -> None:
    """The corpus shape that produced n_eff = 123 over 1,814 clusters.

    Many singletons on one side, plus one large cluster entirely on the other. The design
    effect the estimator returns is above the ceiling the cluster sizes impose, which is
    the signal that the outcome depends on cluster size rather than that observations
    inside a cluster resemble each other.
    """
    clusters = [(0, 1)] * 1000 + [(80, 80)]
    est = cluster_robust_proportion(clusters)

    assert est.deff is not None and est.size_outcome_ceiling is not None
    assert est.deff > est.size_outcome_ceiling * 1.10, (
        "the fixture must reproduce the published condition"
    )
    assert not est.n_eff_interpretable
    # and the diagnostic says which cluster it is
    assert est.top_cluster_variance_share is not None
    assert est.top_cluster_variance_share > 0.5


def test_the_dominant_clusters_interval_is_left_alone() -> None:
    """The correction is to the reported statistic, not to the interval.

    A revision that "fixed" n_eff by shrinking the interval would delete the finding the
    clustering correction exists to surface.
    """
    clusters = [(0, 1)] * 1000 + [(80, 80)]
    est = cluster_robust_proportion(clusters)
    naive_width = est.naive_hi - est.naive_lo
    assert est.width > naive_width


def test_a_boundary_hugging_rate_does_not_publish_an_impossible_lower_bound() -> None:
    """Nine successes cannot be consistent with a rate of exactly zero."""
    # 202 observations carrying 9 successes, concentrated the way the crossing issuers'
    # successes are, which is what drives the symmetric interval through zero
    clusters = [(9, 9), (0, 58), (0, 15)] + [(0, 5)] * 12 + [(0, 1)] * 60
    est = cluster_robust_proportion(clusters)
    assert (est.k, est.n) == (9, 202)
    assert est.lo > 0.0, "a rate with successes may not publish a zero lower bound"
    assert est.lo < est.p_hat < est.hi
    assert "Wilson at the effective sample size" in est.method


def test_a_genuine_zero_still_publishes_zero() -> None:
    """The boundary rule fires on the clamp, not on small rates.

    C18 over the crossing issuers is a true zero and must stay one; substituting an
    interval that excludes zero there would invent an observation.
    """
    est = cluster_robust_proportion([(0, 1)] * 80 + [(0, 60)] + [(0, 62)])
    assert est.k == 0
    assert est.lo == 0.0
    assert "Wilson at the effective sample size" not in est.method


def test_a_saturated_rate_does_not_publish_an_impossible_upper_bound() -> None:
    """The same clamp in the other direction."""
    clusters = [(0, 9), (58, 58), (15, 15)] + [(5, 5)] * 12 + [(1, 1)] * 60
    est = cluster_robust_proportion(clusters)
    assert est.k < est.n
    assert est.hi < 1.0, "a rate with failures may not publish a unit upper bound"
    assert "Wilson at the effective sample size" in est.method


def test_the_record_carries_the_diagnosis() -> None:
    """A downstream reader must not have to recompute the ceiling to know it was crossed."""
    record = cluster_robust_proportion([(0, 1)] * 1000 + [(80, 80)]).as_record()
    for field in ("kish", "size_outcome_ceiling", "top_cluster_variance_share",
                  "n_eff_interpretable"):
        assert field in record
    assert record["n_eff_interpretable"] is False


def test_the_ceiling_binds_where_the_identity_is_exact() -> None:
    """Equal-sized, internally unanimous clusters are the ICC = 1 case.

    The design effect should sit at the ceiling and not above it, which is what makes an
    excess elsewhere mean something. The m/(m-1) factor is part of the estimator, so the
    ceiling carries it too.
    """
    clusters = [(4, 4)] * 25 + [(0, 4)] * 75
    est = cluster_robust_proportion(clusters)
    assert est.kish is not None and math.isclose(est.kish, 4.0)
    assert est.size_outcome_ceiling is not None
    assert math.isclose(est.size_outcome_ceiling, 4.0 * 100 / 99)
    assert est.deff is not None
    assert math.isclose(est.deff, est.size_outcome_ceiling, rel_tol=1e-9)
    assert est.n_eff_interpretable
