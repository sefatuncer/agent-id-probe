"""Tests for the statistics that decide the paper's headline.

The arithmetic here is checked against published values rather than against itself: a
cluster-robust interval that is subtly wrong would not fail visibly, it would just publish
a confident number.
"""

import json
import math
from pathlib import Path

from agentidprobe.analysis import (
    MAX_HEADLINE_HALF_WIDTH,
    VARIANCE_CEILING,
    VARIANCE_FLOOR,
    _advertises_iss,
    cluster_robust_proportion,
    issuer_documents,
    issuer_rate,
    manski_bounds,
    passes_variance_test,
    select_headline,
    student_t_cdf,
    student_t_ppf,
    three_unit_table,
    wild_cluster_bootstrap_ci,
    wilson_interval,
    withheld_issuer_ledger,
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
    """Which interval R11.2 reads decides the verdict, so it is not a detail.

    Ten clusters at 100% and ten at 0%: the property is perfectly correlated inside each
    cluster, which is the realistic shape for an issuer-level rate, because `iss` support is
    a property of an identity product rather than of a tenant. The naive interval sees a
    thousand independent observations and reports +/-3.1pp — comfortably publishable. The
    cluster-robust interval knows there are really twenty and reports +/-24pp.

    R11.2 must reject this. Reading the naive interval would publish a headline at eight
    times the precision the sample can support, and the earlier form of this test asserted
    the *opposite* verdict on a different fixture — one whose point estimate was 0.8%, which
    the amended rule now rejects outright as "essentially nobody".
    """
    est = cluster_robust_proportion([(50, 50)] * 10 + [(0, 50)] * 10)
    naive_half_width = (est.naive_hi - est.naive_lo) / 2
    robust_half_width = (est.hi - est.lo) / 2
    assert naive_half_width < MAX_HEADLINE_HALF_WIDTH    # naive alone would allow it
    assert robust_half_width > MAX_HEADLINE_HALF_WIDTH   # the honest interval does not

    verdict = passes_variance_test(est)
    assert verdict.passed is False
    assert "wider than" in verdict.reason


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


def test_the_published_wilson_coverage_range_is_what_the_simulation_produced():
    """The one statistic in this repository that was an assertion rather than a computation.

    `analysis.py`'s docstring and decision rule R10.4 both justify refusing to publish a naive
    binomial interval by quoting a coverage range from "simulation over the shapes this corpus
    plausibly takes". Until 30 July 2026 no such simulation existed anywhere in the repository,
    and the two documents quoting the range disagreed with each other -- 46%-82% in one,
    45%-82% in the other -- which is the tell. Writing it put the real range at 20%-88%, so both
    figures had understated the low end by more than twenty points, in the argument licensing
    this paper's entire interval methodology.

    The check is against the committed simulation output rather than a fresh run. Re-simulating
    inside a test would have to use a trial count small enough for the timeout, and at that
    count Monte Carlo error moves the bounds by several points -- so the test would be either
    flaky or carry a tolerance wide enough to pass anything. The simulation is therefore treated
    like the captured control documents: run it, commit the output with its seed, enforce the
    prose against the committed value, re-run to audit.
    """
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "docs" / "wilson-coverage.json")
        .read_text(encoding="utf-8")
    )
    low, high = data["quoted_range"]
    per_scenario = [row["naive_wilson_coverage"] for row in data["scenarios"]]

    # The committed range must actually bound the committed scenarios -- otherwise the file
    # summarises itself wrongly and everything downstream inherits that.
    assert low <= min(per_scenario) and max(per_scenario) <= high

    # And the prose must quote that range. These two literals are the only place the numbers
    # are written by hand, and they are what a reviewer reads.
    assert (low, high) == (0.20, 0.89), (
        f"docs/wilson-coverage.json says {low:.0%}-{high:.0%}; analysis.py's docstring and "
        f"decision rule R10.4 say 20%-89%. Update the prose, or explain the new simulation."
    )
    assert data["nominal_coverage"] == 0.95

    # The claim has to still be worth making: coverage near nominal would make R10.4's
    # prohibition unnecessary rather than merely unproven.
    assert min(per_scenario) < 0.75, (
        "if the naive interval covered this well, R10.4 would need rewriting rather than citing"
    )


# --- D8: our own scope policy must not enter the headline ----------------------


def _issuer_report(endpoint_id, apex, issuers, as_documents=None, as_not_fetched=None):
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
            "as_not_fetched": as_not_fetched or {},
        },
        probed_at=datetime.now(UTC),
        run_id="r1",
    )


def test_an_issuer_we_declined_to_request_leaves_the_denominator():
    """Defect D8. Reported by an adversarial review and open until 30 July 2026.

    `issuer_documents` read `authorization_servers` and ignored `as_not_fetched`, so an issuer
    the instrument deliberately never contacted -- not a public HTTPS host, or past the
    ten-per-endpoint cap -- arrived as `None` and was counted as "does not advertise". The rate
    that absorbed it is C16, R11.1's *first-ranked* headline candidate. So the paper's leading
    number moved with our own request policy, in the direction that makes the ecosystem look
    worse the harder we throttle, and R4 exists precisely to forbid that.

    The numbers here are chosen so the defect is visible rather than merely possible: two
    issuers advertise `iss` and two were never asked. Unfixed the rate is 50%; fixed it is 100%.
    """
    reports = [
        _issuer_report(
            "e1", "a.test",
            ["https://as1.test", "https://as2.test", "https://as3.test", "https://as4.test"],
            as_documents={
                "https://as1.test": {"authorization_response_iss_parameter_supported": True},
                "https://as2.test": {"authorization_response_iss_parameter_supported": True},
            },
            as_not_fetched={
                "https://as3.test": "host 'as3.test' has no registrable domain",
                "https://as4.test": "beyond the 10-issuer per-endpoint request cap",
            },
        )
    ]
    documents = issuer_documents(reports, "declared")
    assert set(documents) == {"https://as1.test", "https://as2.test"}, (
        "an issuer we never contacted must not appear in a denominator"
    )
    assert issuer_rate(reports, _advertises_iss, "declared").p_hat == 1.0


def test_an_issuer_withheld_by_one_endpoint_but_observed_via_another_stays():
    """The exclusion is a property of the issuer across the corpus, not of one declaration.

    A popular issuer sits past the cap for the eleventh resource that names it and inside the
    cap for the first. We did see its document, so dropping it would discard a real observation
    -- the mirror-image error of the one above, and just as easy to write.
    """
    reports = [
        _issuer_report("e1", "a.test", ["https://shared.test"],
                       as_documents={"https://shared.test": {
                           "authorization_response_iss_parameter_supported": True}}),
        _issuer_report("e2", "b.test", ["https://shared.test"],
                       as_not_fetched={"https://shared.test": "beyond the cap"}),
    ]
    assert set(issuer_documents(reports, "declared")) == {"https://shared.test"}
    ledger = withheld_issuer_ledger(reports)
    assert ledger["excluded_from_denominators"] == 0
    assert ledger["also_observed_elsewhere"] == ["https://shared.test"]


def test_the_withheld_ledger_names_which_of_our_rules_cost_what():
    """R4 lets our policy remove observations only if the removal is counted.

    One opaque total would not do: "not a public host" and "past the request cap" are different
    decisions with different defences, and a reviewer asking whether the cap distorted the
    result needs the cap's own number.
    """
    reports = [
        _issuer_report(
            "e1", "a.test", ["https://as3.test", "https://as4.test", "https://as5.test"],
            as_not_fetched={
                "https://as3.test": "host 'as3.test' has no registrable domain",
                "https://as4.test": "beyond the 10-issuer per-endpoint request cap",
                "https://as5.test": "beyond the 10-issuer per-endpoint request cap",
            },
        )
    ]
    ledger = withheld_issuer_ledger(reports)
    assert ledger["excluded_from_denominators"] == 3
    assert ledger["by_reason"]["beyond the 10-issuer per-endpoint request cap"] == 2
    assert ledger["by_reason"]["host 'as3.test' has no registrable domain"] == 1


# --- Manski worst-case bounds -------------------------------------------------


def test_manski_bounds_width_equals_the_unobserved_fraction():
    """The identified set is exactly as wide as our ignorance, whatever the rate is.

    This is the property that makes the bound worth printing beside a cluster-robust
    interval: it does not narrow as the corpus grows, so where it is the wider of the two
    the paper is limited by who would answer rather than by how many were asked.
    """
    for p_hat in (0.0, 0.062, 0.5, 0.93, 1.0):
        low, high = manski_bounds(p_hat, unobserved=130, observed=870)
        assert math.isclose(high - low, 0.13, abs_tol=1e-9)


def test_manski_bounds_collapse_to_the_point_estimate_when_nothing_is_unobserved():
    """With full observation there is nothing to bound, and the set is the estimate."""
    low, high = manski_bounds(0.42, unobserved=0, observed=500)
    assert math.isclose(low, 0.42) and math.isclose(high, 0.42)


def test_manski_bounds_stay_inside_the_unit_interval():
    """A rate near 1 with a large unobserved share must not report an upper bound above 1,
    which is where the arithmetic would otherwise put it."""
    low, high = manski_bounds(0.98, unobserved=300, observed=700)
    assert 0.0 <= low <= high <= 1.0


def test_manski_bounds_are_defined_on_an_empty_population():
    """Called on a check nothing was applicable to, it returns a point rather than raising:
    an empty denominator is a reporting decision elsewhere, not an arithmetic error here."""
    assert manski_bounds(0.0, unobserved=0, observed=0) == (0.0, 0.0)
