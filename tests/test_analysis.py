"""Tests for the statistics that decide the paper's headline.

The arithmetic here is checked against published values rather than against itself: a
cluster-robust interval that is subtly wrong would not fail visibly, it would just publish
a confident number.
"""

import math

from agentidprobe.analysis import (
    VARIANCE_CEILING,
    VARIANCE_FLOOR,
    cluster_robust_proportion,
    passes_variance_test,
    select_headline,
    student_t_cdf,
    student_t_ppf,
    three_unit_table,
    wild_cluster_bootstrap_ci,
    wilson_interval,
)

# --- Student-t against published table values ---------------------------------


def test_t_quantiles_match_published_tables():
    """Two-sided 95%, i.e. the 0.975 quantile. If these drift, every interval in the
    paper drifts with them."""
    assert abs(student_t_ppf(0.975, 1) - 12.706) < 0.01
    assert abs(student_t_ppf(0.975, 10) - 2.228) < 0.001
    assert abs(student_t_ppf(0.975, 24) - 2.064) < 0.001
    assert abs(student_t_ppf(0.975, 30) - 2.042) < 0.001
    assert abs(student_t_ppf(0.975, 120) - 1.980) < 0.002


def test_t_approaches_normal_for_large_df():
    assert abs(student_t_ppf(0.975, 1e6) - 1.96) < 0.001


def test_t_cdf_is_symmetric_and_bounded():
    assert abs(student_t_cdf(0.0, 5) - 0.5) < 1e-9
    assert abs(student_t_cdf(2.0, 7) + student_t_cdf(-2.0, 7) - 1.0) < 1e-9
    assert 0.0 < student_t_cdf(-50.0, 3) < 1e-3


# --- Wilson -------------------------------------------------------------------


def test_wilson_matches_known_values():
    lo, hi = wilson_interval(8, 166)
    assert abs(lo - 0.0246) < 0.002
    assert abs(hi - 0.0921) < 0.002


def test_wilson_handles_zero_successes_without_collapsing():
    lo, hi = wilson_interval(0, 166)
    assert lo == 0.0
    assert 0.015 < hi < 0.030          # rule of three territory, not zero


# --- cluster-robust -----------------------------------------------------------


def test_singleton_clusters_reproduce_the_independent_case():
    """166 clusters of one is the iid case, so the cluster-robust interval should land
    close to Wilson. If it does not, the estimator is wrong."""
    clusters = [(1, 1)] * 30 + [(0, 1)] * 136
    est = cluster_robust_proportion(clusters)
    assert est.m == 166
    assert abs(est.p_hat - 30 / 166) < 1e-12
    assert abs(est.deff - 1.0) < 0.05
    naive_lo, naive_hi = wilson_interval(30, 166)
    assert abs(est.lo - naive_lo) < 0.02
    assert abs(est.hi - naive_hi) < 0.02


def test_concentrated_failures_widen_the_interval_a_lot():
    """Twelve platforms, three of them entirely broken. This is the shape that makes a
    naive interval a lie: same point estimate, radically different precision."""
    clusters = [(14, 14)] * 3 + [(0, 14)] * 9
    est = cluster_robust_proportion(clusters)
    assert est.m == 12
    assert abs(est.p_hat - 0.25) < 1e-12
    assert est.deff > 5
    assert est.n_eff < 30
    naive_lo, naive_hi = wilson_interval(est.k, est.n)
    assert est.width > (naive_hi - naive_lo) * 2


def test_clustering_can_also_narrow_the_interval():
    """Evenly spread properties give a design effect below 1. The rule is a measurement,
    not a safety margin, and a test suite that only ever checks widening would hide an
    estimator that always widens."""
    # Varies from cluster to cluster, but less than binomial sampling would: 30 clusters
    # on the rate, five just under, five just over.
    clusters = [(1, 4)] * 30 + [(0, 4)] * 5 + [(2, 4)] * 5
    est = cluster_robust_proportion(clusters)
    assert est.deff is not None and est.deff < 1.0
    assert est.n_eff > est.n


def test_perfectly_homogeneous_clusters_do_not_produce_a_zero_width_interval():
    """Every cluster exactly on the overall rate makes the between-cluster variance
    estimate zero, and a t-interval would collapse to a point — infinite confidence as an
    artefact of the estimator, which is the most confident possible way to be wrong.
    The variance floor catches this as one case of a general problem rather than as a
    special case, and the method string says so."""
    est = cluster_robust_proportion([(1, 4)] * 40)
    assert est.width > 0.0
    assert "floored" in est.method
    assert est.deff == 0.0


def test_similar_clusters_cannot_manufacture_precision_no_sample_could_have():
    """The defect the floor exists for, and the reason an exact `var == 0` guard was not
    enough: moving one endpoint made the between-cluster variance merely tiny rather than
    zero, the guard stopped firing, and the estimator reported an effective sample of
    313,000 observations drawn from 1,000. It would have published 49.9% [49.7%, 50.1%]."""
    clusters = [(62, 125)] * 4 + [(63, 125)] * 4          # eight near-identical platforms
    est = cluster_robust_proportion(clusters)
    assert est.n == 1000
    assert est.deff < 1.0                                  # genuinely low, and reported
    assert est.n_eff is not None and est.n_eff > est.n     # reported, not used
    naive_lo, naive_hi = wilson_interval(est.k, est.n)
    assert est.width >= (naive_hi - naive_lo) * 0.99, (
        "the published interval is narrower than a simple random sample of this size"
    )
    assert "floored" in est.method


def test_bootstrap_never_returns_a_point_estimate_as_an_interval():
    """Near p=0 every replicate lands on the point estimate and the bootstrap returns a
    zero-width interval. R11.2 reads these bounds to choose the paper's headline, so it
    must never be handed a point."""
    lo, hi = wild_cluster_bootstrap_ci([(0, 50)] * 4 + [(1, 50)] * 16, reps=400)
    assert hi > lo


def test_single_cluster_falls_back_and_says_so():
    est = cluster_robust_proportion([(3, 10)])
    assert est.m == 1
    assert "single cluster" in est.method
    assert est.deff is None


def test_empty_input_does_not_raise():
    est = cluster_robust_proportion([])
    assert est.n == 0 and est.method == "empty"


def test_naive_interval_is_carried_alongside_for_comparison():
    """R10.4 forbids publishing the naive interval alone, which means the estimate has to
    carry it so the gap can be shown rather than described."""
    est = cluster_robust_proportion([(14, 14)] * 3 + [(0, 14)] * 9)
    assert est.naive_hi > est.naive_lo
    assert (est.naive_hi - est.naive_lo) < est.width


# --- wild bootstrap -----------------------------------------------------------


def test_wild_bootstrap_is_deterministic_under_its_seed():
    clusters = [(14, 14)] * 3 + [(0, 14)] * 9
    assert wild_cluster_bootstrap_ci(clusters, reps=400) == \
        wild_cluster_bootstrap_ci(clusters, reps=400)


def test_wild_bootstrap_is_in_the_same_territory_as_the_t_interval():
    clusters = [(7, 10)] * 5 + [(1, 10)] * 20
    t_est = cluster_robust_proportion(clusters)
    lo, hi = wild_cluster_bootstrap_ci(clusters, reps=600)
    assert 0.0 <= lo < t_est.p_hat < hi <= 1.0
    assert abs((hi - lo) - t_est.width) < 0.25


# --- R10.1 three-unit reporting -----------------------------------------------


def _fake_report(endpoint_id, apex, fingerprint, outcome):
    from datetime import UTC, datetime

    from agentidprobe.models import (
        CheckId,
        CheckResult,
        Endpoint,
        EndpointKind,
        EndpointReport,
        Modality,
        NormativeStrength,
    )
    return EndpointReport(
        endpoint=Endpoint(endpoint_id=endpoint_id, url=f"https://{endpoint_id}.test/mcp",
                          kind=EndpointKind.MCP_REMOTE, source="t", apex_domain=apex),
        modality=Modality.OAUTH_METADATA,
        reachable=True,
        checks=[CheckResult(check_id=CheckId.PRM_RESOURCE_IDENTITY_MATCH, outcome=outcome,
                            normative_strength=NormativeStrength.MUST,
                            spec_ref="RFC 9728 3.3")],
        evidence={"implementation_fingerprint": fingerprint},
        probed_at=datetime.now(UTC),
        run_id="r1",
    )


def test_three_unit_table_shows_how_much_the_unit_matters():
    """Ten endpoints on one apex, all failing, plus ten independent ones all passing.
    Per endpoint the rate is 50%; per apex it is 10 of 11. Publishing only the first would
    let a single operator set the headline."""
    from agentidprobe.models import CheckId, Outcome

    reports = [
        _fake_report(f"bulk{i}", "bulk.test", "fp-bulk", Outcome.FAIL_MISIMPLEMENTED)
        for i in range(10)
    ] + [
        _fake_report(f"solo{i}", f"solo{i}.test", f"fp-{i}", Outcome.PASS)
        for i in range(10)
    ]
    table = three_unit_table(reports, CheckId.PRM_RESOURCE_IDENTITY_MATCH)

    assert table["endpoint"]["n"] == 20
    assert abs(table["endpoint"]["p_hat"] - 0.5) < 1e-9
    assert table["apex"]["m"] == 11              # ten solo apexes plus the bulk one
    assert table["implementation"]["m"] == 11
    assert table["apex"]["p_hat"] > table["endpoint"]["p_hat"]


def test_three_unit_table_excludes_not_applicable_and_error_from_the_denominator():
    from agentidprobe.models import CheckId, Outcome

    reports = [
        _fake_report("a", "a.test", "fp-a", Outcome.PASS),
        _fake_report("b", "b.test", "fp-b", Outcome.NOT_APPLICABLE),
        _fake_report("c", "c.test", "fp-c", Outcome.ERROR),
    ]
    table = three_unit_table(reports, CheckId.PRM_RESOURCE_IDENTITY_MATCH)
    assert table["endpoint"]["n"] == 1
    assert table["endpoint"]["k"] == 1


def test_reports_without_a_fingerprint_do_not_collapse_into_one_cluster():
    """A missing fingerprint means the document was never retrieved. Bucketing those
    together would invent a cluster and shrink m, which widens or narrows every interval
    downstream for no reason."""
    from agentidprobe.models import CheckId, Outcome

    reports = [
        _fake_report(f"e{i}", f"e{i}.test", None, Outcome.PASS) for i in range(5)
    ]
    table = three_unit_table(reports, CheckId.PRM_RESOURCE_IDENTITY_MATCH)
    assert table["implementation"]["m"] == 5


# --- delegation graph (R11.1 candidate 3) -------------------------------------


def _graph_report(endpoint_id, apex, issuers, as_documents=None, declared_resource=None):
    from datetime import UTC, datetime

    from agentidprobe.models import Endpoint, EndpointKind, EndpointReport, Modality
    return EndpointReport(
        endpoint=Endpoint(endpoint_id=endpoint_id, url=f"https://{apex}/mcp",
                          kind=EndpointKind.MCP_REMOTE, source="t", apex_domain=apex),
        modality=Modality.OAUTH_METADATA,
        reachable=True,
        checks=[],
        evidence={
            "authorization_servers": issuers,
            "as_documents": as_documents or {},
            "declared_resource": declared_resource,
        },
        probed_at=datetime.now(UTC),
        run_id="r1",
    )


def test_graph_separates_self_hosted_from_cross_operator_delegation():
    from agentidprobe.analysis import build_delegation_graph
    reports = [
        _graph_report("a", "acme-example.org", ["https://auth.acme-example.org"]),
        _graph_report("b", "beta-example.org", ["https://beta.eu.idp-example.org"]),
        _graph_report("c", "gamma-example.org", ["https://beta.eu.idp-example.org"]),
    ]
    graph = build_delegation_graph(reports)
    assert graph.same_operator == 1
    assert graph.cross_operator == 2
    assert graph.total == 3


def test_special_use_tlds_are_counted_as_unknown_not_as_same_operator():
    """`apex_domain` returns None for special-use TLDs, and that is correct behaviour.
    Silently folding those edges into "same operator" would invent self-hosting."""
    from agentidprobe.analysis import build_delegation_graph
    graph = build_delegation_graph(
        [_graph_report("a", "acme.test", ["https://auth.acme.test"])])
    assert graph.unknown_operator == 1
    assert graph.same_operator == 0 and graph.cross_operator == 0


def test_issuer_concentration_is_computed_over_resources_not_issuers():
    """Five resources naming one issuer and one naming another is a concentrated
    ecosystem, not a two-issuer one. HHI has to weight by who depends on whom."""
    from agentidprobe.analysis import build_delegation_graph
    reports = [
        _graph_report(f"r{i}", f"r{i}-example.org", ["https://big.idp-example.org"])
        for i in range(5)
    ] + [_graph_report("x", "x-example.org", ["https://small.idp-example.org"])]
    conc = build_delegation_graph(reports).concentration()
    assert conc["issuers"] == 2
    assert abs(conc["top1_share"] - 5 / 6) < 1e-9
    assert conc["effective_issuers"] < 1.5     # nominally two, effectively one


def test_issuer_shared_across_apexes_is_detected_without_guessing_url_shape():
    """An identical issuer URL named by two different apexes contains nothing that
    separates them, whatever its subdomain looks like. Deciding which URL components are
    "tenant" components would be the authors' rubric — and would be wrong, since a
    subdomain like `shared.` separates nothing. The signal is the sharing itself."""
    from agentidprobe.analysis import build_delegation_graph
    shared = [
        _graph_report("a", "acme-example.org", ["https://shared.idp-example.org"]),
        _graph_report("b", "beta-example.org", ["https://shared.idp-example.org"]),
    ]
    assert build_delegation_graph(shared).shared_across_apexes == \
        ["https://shared.idp-example.org"]

    # Distinct issuer URLs per tenant: nothing is shared, nothing is flagged.
    scoped = [
        _graph_report("a", "acme-example.org", ["https://acme.eu.idp-example.org"]),
        _graph_report("b", "beta-example.org", ["https://beta.eu.idp-example.org"]),
    ]
    assert build_delegation_graph(scoped).shared_across_apexes == []

    path_scoped = [
        _graph_report("a", "acme-example.org", ["https://idp-example.org/acme"]),
        _graph_report("b", "beta-example.org", ["https://idp-example.org/beta"]),
    ]
    assert build_delegation_graph(path_scoped).shared_across_apexes == []


def test_cross_operator_rate_is_clustered_by_resource_apex():
    from agentidprobe.analysis import build_delegation_graph
    reports = [
        _graph_report(f"bulk{i}", "bulk-example.org", ["https://x.idp-example.org"])
        for i in range(10)
    ] + [_graph_report("solo", "solo-example.org", ["https://auth.solo-example.org"])]
    graph = build_delegation_graph(reports)
    est = cluster_robust_proportion(graph.cross_operator_clusters())
    assert est.m == 2                      # two apexes, not eleven endpoints


def test_cross_check_feasibility_separates_possible_from_passing():
    """§7.6 recommends a cross-check; §4 makes the list it needs OPTIONAL. Whether the
    check is possible and whether it passes are different numbers and both are reported."""
    from agentidprobe.analysis import cross_check_feasibility
    reports = [
        _graph_report("a", "acme-example.org", ["https://i1-example.org"],
                      as_documents={"https://i1-example.org": {
                          "protected_resources": ["https://acme-example.org/mcp"]}},
                      declared_resource="https://acme-example.org/mcp"),
        _graph_report("b", "beta-example.org", ["https://i2-example.org"],
                      as_documents={"https://i2-example.org": {
                          "protected_resources": ["https://someone-else-example.org/mcp"]}},
                      declared_resource="https://beta-example.org/mcp"),
        _graph_report("c", "gamma-example.org", ["https://i3-example.org"],
                      as_documents={"https://i3-example.org": {
                          "issuer": "https://i3-example.org"}},
                      declared_resource="https://gamma-example.org/mcp"),
    ]
    out = cross_check_feasibility(reports)
    assert out["issuers"] == 3
    assert out["cross_check_possible"] == 2
    assert out["cross_check_passes"] == 1


# --- R11.2 --------------------------------------------------------------------


def test_variance_test_rejects_essentially_nobody():
    verdict = passes_variance_test(cluster_robust_proportion([(0, 100)] * 20))
    assert verdict.passed is False
    assert "nobody" in verdict.reason


def test_variance_test_rejects_essentially_everybody():
    verdict = passes_variance_test(cluster_robust_proportion([(100, 100)] * 20))
    assert verdict.passed is False
    assert "everybody" in verdict.reason


def test_variance_test_accepts_a_real_spread():
    verdict = passes_variance_test(cluster_robust_proportion([(3, 10)] * 20))
    assert verdict.passed is True


def test_variance_test_uses_the_cluster_robust_interval_not_the_naive_one():
    """The two intervals can disagree about the verdict, so which one R11.2 reads is not a
    detail. Here every failure sits in one cluster: the naive interval says the rate is
    confined below the 2% floor and the candidate is "essentially nobody", while the
    cluster-robust interval — which knows the failures came from a single operator — is
    wide enough to cross it."""
    clusters = [(8, 50)] + [(0, 50)] * 19
    est = cluster_robust_proportion(clusters)
    assert est.naive_hi < VARIANCE_FLOOR       # naive alone would reject the candidate
    assert est.hi > VARIANCE_FLOOR             # the honest interval does not
    assert passes_variance_test(est).passed is True


def test_select_headline_respects_the_frozen_order():
    """R11.1 fixes the ranking by normative anchor strength. This function must not
    reorder candidates by how flattering they look."""
    flat = cluster_robust_proportion([(0, 100)] * 20)        # fails variance
    spread = cluster_robust_proportion([(3, 10)] * 20)       # passes
    name, _ = select_headline([("C16", flat), ("C18", spread)])
    assert name == "C18"
    name, _ = select_headline([("C16", spread), ("C18", spread)])
    assert name == "C16"                                      # first passing wins


def test_select_headline_falls_back_to_topology_when_nothing_varies():
    flat = cluster_robust_proportion([(0, 100)] * 20)
    full = cluster_robust_proportion([(100, 100)] * 20)
    name, reason = select_headline([("C16", flat), ("C18", full)])
    assert "topology" in name
    assert "not a rate" in reason


def test_variance_thresholds_are_the_ones_the_rules_declare():
    assert math.isclose(VARIANCE_FLOOR, 0.02)
    assert math.isclose(VARIANCE_CEILING, 0.98)
