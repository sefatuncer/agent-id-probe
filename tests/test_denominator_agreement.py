"""The funnel and the per-check rates must remove the same populations.

The manuscript prints both tables on facing pages. Until 6 August 2026 they were computed
under different rules -- `rate_by_unit` kept endpoints the access policy had declined to ask
and kept UNSPECIFIED outcomes, while the funnel removed the first and, for UNSPECIFIED,
counted it as a non-pass -- so the two disagreed by 21 endpoints on C05, 196 on C12 and 717 on
C13. Nothing failed, because no test compared them. Two external reviews read the published
disagreement as the study contradicting itself, which is what it was.

These tests fix the four exclusion classes in one place. A change to either computation that
does not change the other now fails here.
"""

from datetime import UTC, datetime

from agentidprobe.analysis import rate_by_unit
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
from agentidprobe.runner import summarise

CHECK = CheckId.PRM_RESOURCE_IDENTITY_MATCH


def _report(
    endpoint_id: str,
    outcome: Outcome,
    *,
    apex: str = "example.org",
    robots_allowed: bool = True,
    opted_out: bool = False,
    reachable: bool = True,
    checks: list[CheckResult] | None = None,
) -> EndpointReport:
    return EndpointReport(
        endpoint=Endpoint(endpoint_id=endpoint_id, url=f"https://{endpoint_id}.test/mcp",
                          kind=EndpointKind.MCP_REMOTE, source="t", apex_domain=apex),
        modality=Modality.OAUTH_METADATA,
        reachable=reachable,
        robots_allowed=robots_allowed,
        opted_out=opted_out,
        checks=checks if checks is not None else [
            CheckResult(check_id=CHECK, outcome=outcome,
                        normative_strength=NormativeStrength.MUST, spec_ref="RFC 9728 3.3"),
        ],
        probed_at=datetime.now(UTC),
        run_id="r1",
    )


def _rate(reports: list[EndpointReport]) -> tuple[int, int]:
    record = rate_by_unit(reports, CHECK, "endpoint").as_record()
    return record["k"], record["n"]


def test_unspecified_leaves_the_denominator():
    """The outcome records the instrument declining to score. A denominator that keeps it
    publishes our uncertainty as the operator's failure, which is the one thing Section 4.3
    undertakes not to do."""
    reports = [
        _report("a", Outcome.PASS, apex="a.test"),
        _report("b", Outcome.FAIL_MISIMPLEMENTED, apex="b.test"),
        _report("c", Outcome.UNSPECIFIED, apex="c.test"),
    ]
    assert _rate(reports) == (1, 2)


def test_robots_and_opt_out_leave_the_denominator():
    """Both are our own politeness policy. Retaining them reports our configuration as a
    property of the ecosystem."""
    reports = [
        _report("a", Outcome.PASS, apex="a.test"),
        _report("b", Outcome.FAIL_MISIMPLEMENTED, apex="b.test"),
        _report("c", Outcome.FAIL_MISIMPLEMENTED, apex="c.test", robots_allowed=False),
        _report("d", Outcome.FAIL_MISIMPLEMENTED, apex="d.test", opted_out=True),
    ]
    assert _rate(reports) == (1, 2)


def test_not_applicable_and_error_leave_the_denominator():
    reports = [
        _report("a", Outcome.PASS, apex="a.test"),
        _report("b", Outcome.NOT_APPLICABLE, apex="b.test"),
        _report("c", Outcome.ERROR, apex="c.test"),
    ]
    assert _rate(reports) == (1, 1)


def test_funnel_and_rate_agree_on_the_first_link():
    """C05 is the funnel's first check, so the chain conditions nothing above it and the two
    computations must land on the same fraction. Any drift between them means one of the two
    exclusion rules moved without the other."""
    reports = []
    for index, outcome in enumerate(
        [Outcome.PASS] * 5
        + [Outcome.FAIL_UNIMPLEMENTED] * 3
        + [Outcome.NOT_APPLICABLE, Outcome.ERROR, Outcome.UNSPECIFIED]
    ):
        reports.append(_report(
            f"e{index}", outcome, apex=f"e{index}.test",
            checks=[CheckResult(check_id=CheckId.PRM_PRESENT, outcome=outcome,
                                normative_strength=NormativeStrength.MUST,
                                spec_ref="RFC 9728 3.2")],
        ))
    # Two more the access policy declined to ask, both of which would pass if counted.
    reports.append(_report(
        "blocked", Outcome.PASS, apex="blocked.test", robots_allowed=False,
        checks=[CheckResult(check_id=CheckId.PRM_PRESENT, outcome=Outcome.PASS,
                            normative_strength=NormativeStrength.MUST,
                            spec_ref="RFC 9728 3.2")],
    ))
    reports.append(_report(
        "quiet", Outcome.PASS, apex="quiet.test", opted_out=True,
        checks=[CheckResult(check_id=CheckId.PRM_PRESENT, outcome=Outcome.PASS,
                            normative_strength=NormativeStrength.MUST,
                            spec_ref="RFC 9728 3.2")],
    ))

    stage = next(
        row for row in summarise(reports)["modalities"]["oauth_metadata"]["funnel"]
        if row["stage"] == "publishes protected-resource metadata"
    )
    record = rate_by_unit(reports, CheckId.PRM_PRESENT, "endpoint").as_record()

    assert (stage["n"], stage["eligible"]) == (5, 8)
    assert (record["k"], record["n"]) == (5, 8)


def test_funnel_reports_unspecified_as_its_own_excluded_class():
    """It has to be visible in the ledger, not merged into `error`: the two say different
    things, one about the specification and one about access."""
    reports = [
        _report("a", Outcome.PASS, apex="a.test", checks=[
            CheckResult(check_id=CheckId.PRM_PRESENT, outcome=Outcome.PASS,
                        normative_strength=NormativeStrength.MUST, spec_ref="RFC 9728 3.2"),
            CheckResult(check_id=CHECK, outcome=Outcome.UNSPECIFIED,
                        normative_strength=NormativeStrength.MUST, spec_ref="RFC 9728 3.3"),
        ]),
    ]
    stage = next(
        row for row in summarise(reports)["modalities"]["oauth_metadata"]["funnel"]
        if row["stage"] == "resource identifier matches"
    )
    assert stage["excluded"]["unspecified"] == 1
    assert stage["eligible"] == 0
