"""Which endpoint represents an apex (analysis.apex_representative_sensitivity, 1 November 2026).

The published apex rate takes the lowest endpoint identifier. These tests pin that the
sensitivity uses the published rule as its `published` arm, that the two envelopes bound every
representative rule, and that only apexes whose endpoints disagree can move.
"""

from datetime import UTC, datetime

from agentidprobe.analysis import apex_representative_sensitivity, rate_by_unit
from agentidprobe.models import (
    CheckId,
    CheckResult,
    Endpoint,
    EndpointKind,
    EndpointReport,
    Modality,
    NormativeStrength,
    Outcome,
)

CHECK = CheckId.PRM_RESOURCE_IDENTITY_MATCH


def _report(endpoint_id: str, apex: str, outcome: Outcome) -> EndpointReport:
    return EndpointReport(
        endpoint=Endpoint(endpoint_id=endpoint_id, url=f"https://{endpoint_id}.test/mcp",
                          kind=EndpointKind.MCP_REMOTE, source="t", apex_domain=apex),
        modality=Modality.OAUTH_METADATA,
        reachable=True,
        checks=[CheckResult(check_id=CHECK, outcome=outcome,
                            normative_strength=NormativeStrength.MUST,
                            spec_ref="RFC 9728 3.3")],
        evidence={},
        probed_at=datetime.now(UTC),
        run_id="r1",
    )


def _corpus() -> list[EndpointReport]:
    fail, ok = Outcome.FAIL_MISIMPLEMENTED, Outcome.PASS
    return [
        # Mixed apex whose lowest identifier fails.
        _report("a0", "mixed.test", fail), _report("a1", "mixed.test", ok),
        _report("a2", "mixed.test", ok),
        # Uniform apexes, which no representative rule can move.
        _report("b0", "pass.test", ok), _report("b1", "pass.test", ok),
        _report("c0", "fail.test", fail),
        # Not rated: leaves every arm's denominator, as it leaves the published rate's.
        _report("d0", "unrated.test", Outcome.UNSPECIFIED),
    ]


def test_the_published_arm_is_the_published_apex_rate():
    reports = _corpus()
    result = apex_representative_sensitivity(reports, CHECK)
    published = rate_by_unit(reports, CHECK, "apex")
    assert (result["published"]["k"], result["published"]["n"]) == (published.k, published.n)
    assert result["apexes"] == 3


def test_envelopes_bound_every_representative_rule():
    result = apex_representative_sensitivity(_corpus(), CHECK)
    assert result["mixed_apexes"] == 1
    assert result["all_pass"]["k"] == 1      # only pass.test
    assert result["any_pass"]["k"] == 2      # pass.test and mixed.test
    assert result["published"]["k"] == 1     # mixed.test is represented by a0, which fails
    low, high = result["all_pass"]["p_hat"], result["any_pass"]["p_hat"]
    assert low <= result["published"]["p_hat"] <= high
    for arm in result["random"]:
        assert low <= arm["p_hat"] <= high


def test_no_mixed_apex_means_no_representative_can_move_the_rate():
    reports = [_report("x0", "x.test", Outcome.PASS), _report("x1", "x.test", Outcome.PASS),
               _report("y0", "y.test", Outcome.FAIL_MISIMPLEMENTED)]
    result = apex_representative_sensitivity(reports, CHECK)
    assert result["mixed_apexes"] == 0
    rates = {result["any_pass"]["p_hat"], result["all_pass"]["p_hat"],
             result["published"]["p_hat"], *result["random_range"]}
    assert len(rates) == 1


def test_random_representatives_are_reproducible():
    reports = _corpus()
    assert (apex_representative_sensitivity(reports, CHECK)["random"]
            == apex_representative_sensitivity(reports, CHECK)["random"])
