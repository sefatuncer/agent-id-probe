"""C05's denominator is "challenged or published", and that has to stay visible.

The defect these tests lock down was invisible for three referee rounds because nothing in
the code or the output distinguished "endpoints that answered an authorization challenge"
from "endpoints the check scored". Section 6.1 asserted the first and the instrument
computed the second, and the difference was 1,375 of 2,976 endpoints -- 46.2% -- every one
of which entered only by satisfying the numerator.

Two of these tests fail if the widening is ever silently reintroduced; the rest pin the
shape of the reported composition so a reader can check the population rather than trust
its description.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentidprobe.analysis import (
    CHALLENGE_STATUSES,
    challenge_share,
    challenged,
    denominator_composition,
    rate_by_unit,
)
from agentidprobe.models import (
    CheckId,
    CheckResult,
    Endpoint,
    EndpointReport,
    Modality,
    NormativeStrength,
    Outcome,
)

C05 = CheckId.PRM_PRESENT


def _report(eid: str, status: int | None, outcome: Outcome, apex: str = "example.com"):
    return EndpointReport(
        endpoint=Endpoint(
            endpoint_id=eid,
            url=f"https://{eid}.{apex}/mcp",
            kind="mcp_remote",
            source="test",
            apex_domain=apex,
            first_seen=datetime(2026, 7, 30, tzinfo=UTC),
            last_seen=datetime(2026, 7, 30, tzinfo=UTC),
        ),
        modality=Modality.OAUTH_METADATA,
        reachable=True,
        http_status=status,
        checks=[
            CheckResult(
                check_id=C05,
                outcome=outcome,
                normative_strength=NormativeStrength.MUST,
                spec_ref="MCP: servers MUST implement RFC 9728",
                spec_url="https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization",
            )
        ],
        evidence={},
        probed_at=datetime(2026, 7, 30, tzinfo=UTC),
        run_id="test",
    )


@pytest.fixture
def mixed_population():
    """Four challengers (3 pass), four non-challengers that all pass.

    The non-challengers pass unanimously on purpose: that is the real shape of the bias,
    because the only route into the denominator without a challenge is publishing, which
    is the numerator.
    """
    return [
        _report("c1", 401, Outcome.PASS),
        _report("c2", 401, Outcome.PASS),
        _report("c3", 403, Outcome.PASS),
        _report("c4", 401, Outcome.FAIL_UNIMPLEMENTED),
        _report("n1", 405, Outcome.PASS),
        _report("n2", 200, Outcome.PASS),
        _report("n3", 404, Outcome.PASS),
        _report("n4", 406, Outcome.PASS),
    ]


def test_challenge_statuses_are_only_401_and_403():
    """RFC 9728 3.1 hangs the requirement on the challenge. 405 is not a challenge."""
    assert CHALLENGE_STATUSES == (401, 403)
    assert challenged(_report("a", 401, Outcome.PASS))
    assert challenged(_report("b", 403, Outcome.PASS))
    for status in (200, 400, 404, 405, 406, 500, None):
        assert not challenged(_report("c", status, Outcome.PASS)), status


def test_the_two_denominators_are_not_the_same_population(mixed_population):
    """The regression guard. If these ever coincide the widening is back."""
    wide = rate_by_unit(mixed_population, C05, "endpoint")
    narrow = rate_by_unit(mixed_population, C05, "endpoint", challenged_only=True)

    assert wide.n == 8
    assert narrow.n == 4
    assert narrow.n < wide.n, (
        "C05's challenged-only denominator must be strictly smaller than the scored one; "
        "if it is not, endpoints that never challenged are no longer being admitted and "
        "the sensitivity arm has become a duplicate of the primary rate"
    )


def test_the_widening_inflates_the_rate(mixed_population):
    """The direction matters: the bias runs the way that flatters the study."""
    wide = rate_by_unit(mixed_population, C05, "endpoint")
    narrow = rate_by_unit(mixed_population, C05, "endpoint", challenged_only=True)

    assert narrow.p_hat == pytest.approx(3 / 4)
    assert wide.p_hat == pytest.approx(7 / 8)
    assert wide.p_hat > narrow.p_hat


def test_the_restriction_applies_at_every_unit(mixed_population):
    """R10.1 publishes three units, so the correction has to reach all three."""
    for unit in ("endpoint", "apex", "implementation"):
        narrow = rate_by_unit(mixed_population, C05, unit, challenged_only=True)
        assert narrow.n <= rate_by_unit(mixed_population, C05, unit).n


def test_composition_splits_the_denominator_and_names_the_share(mixed_population):
    comp = denominator_composition(mixed_population, C05)

    assert comp["total"]["n"] == 8
    assert comp["challenged"]["n"] == 4
    assert comp["not_challenged"]["n"] == 4
    assert comp["not_challenged_share"] == pytest.approx(0.5)
    assert comp["challenged"]["rate"] == pytest.approx(3 / 4)
    assert comp["not_challenged"]["rate"] == pytest.approx(1.0)
    # The halves have to reconstitute the whole, or the composition is not one.
    assert comp["challenged"]["n"] + comp["not_challenged"]["n"] == comp["total"]["n"]
    assert comp["challenged"]["k"] + comp["not_challenged"]["k"] == comp["total"]["k"]


def test_composition_breaks_down_by_status(mixed_population):
    by_status = denominator_composition(mixed_population, C05)["by_status"]

    assert by_status["401"]["n"] == 3
    assert by_status["403"]["n"] == 1
    assert by_status["405"]["n"] == 1
    assert sum(row["n"] for row in by_status.values()) == 8


def test_challenge_share_counts_over_the_arm_not_the_denominator():
    """Section 6.1 printed the denominator's corpus share as the challenged share.

    They differ because NOT_APPLICABLE endpoints leave the denominator but remain part of
    the arm the census reached, and the Zhou et al. comparison bracket was built on the
    first figure while the sentence around it claimed the second.
    """
    population = [
        _report("c1", 401, Outcome.PASS),
        _report("c2", 401, Outcome.FAIL_UNIMPLEMENTED),
        _report("n1", 200, Outcome.PASS),
        # Never challenged, published nothing: leaves the denominator, stays in the arm.
        _report("x1", 200, Outcome.NOT_APPLICABLE),
        _report("x2", 404, Outcome.NOT_APPLICABLE),
        _report("x3", 404, Outcome.NOT_APPLICABLE),
    ]
    share = challenge_share(population, C05)
    assert share["arm"] == 6
    assert share["challenged"] == 2
    assert share["share"] == pytest.approx(2 / 6)

    # The denominator's share of the arm is a different and larger number, which is
    # exactly the substitution the manuscript made.
    denominator_n = rate_by_unit(population, C05, "endpoint").n
    assert denominator_n == 3
    assert denominator_n / share["arm"] > share["share"]


def test_a_population_of_pure_challengers_leaves_both_rates_equal():
    """The correction must be a no-op where the described population is the real one."""
    population = [
        _report("c1", 401, Outcome.PASS),
        _report("c2", 403, Outcome.FAIL_UNIMPLEMENTED),
    ]
    wide = rate_by_unit(population, C05, "endpoint")
    narrow = rate_by_unit(population, C05, "endpoint", challenged_only=True)
    assert (wide.n, wide.p_hat) == (narrow.n, narrow.p_hat)
    assert denominator_composition(population, C05)["not_challenged_share"] == 0.0
