"""What the per-host cap costs the endpoint-unit rate.

Section 9.6 asserted the sampling bias had "a known sign" and gave no number, in a sentence
whose own clause said the direction depended on "whatever a handful of large platforms happen
to do". Both halves could not be true, and nothing in the repository measured either.

`sampling_bias` estimates the uncapped rate by letting each measured endpoint on a capped host
stand for its host's whole listing. The tests below fix three things a later change could
break silently: that an uncapped corpus is left exactly alone, that the weight is the frame
size over the admitted size rather than over the applicable size, and that the direction is
whatever the capped hosts actually do rather than a sign written into the code.
"""

from datetime import UTC, datetime

from agentidprobe.analysis import sampling_bias
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
CAP = 25


def _report(host: str, index: int, outcome: Outcome) -> EndpointReport:
    return EndpointReport(
        endpoint=Endpoint(endpoint_id=f"{host}-{index}", url=f"https://{host}/mcp/{index}",
                          kind=EndpointKind.MCP_REMOTE, source="t",
                          apex_domain=".".join(host.split(".")[-2:])),
        modality=Modality.OAUTH_METADATA,
        reachable=True,
        checks=[CheckResult(check_id=CHECK, outcome=outcome,
                            normative_strength=NormativeStrength.MUST, detail="d")],
        probed_at=datetime.now(UTC),
        run_id="r1",
    )


def _corpus(spec: dict[str, tuple[int, int]]) -> list[EndpointReport]:
    """`spec` maps host -> (passing, failing)."""
    reports = []
    for host, (passing, failing) in spec.items():
        reports += [_report(host, i, Outcome.PASS) for i in range(passing)]
        reports += [_report(host, 100 + i, Outcome.FAIL_MISIMPLEMENTED)
                    for i in range(failing)]
    return reports


def test_an_uncapped_corpus_is_unchanged() -> None:
    reports = _corpus({"a.test": (7, 3), "b.test": (5, 5)})
    result = sampling_bias(reports, CHECK, {}, CAP)
    assert result["published_rate"] == result["reweighted_rate"] == 0.6
    assert result["capped_n"] == 0
    assert result["capped_hosts_measured"] == 0


def test_a_capped_host_on_the_minority_side_pulls_the_rate_down() -> None:
    """The shape the census has: one large host, entirely failing, mostly unmeasured."""
    reports = _corpus({"small.test": (90, 10), "bulk.test": (0, 10)})
    # bulk.test carried 25 + 1256 endpoints in the frame and ten were applicable
    result = sampling_bias(reports, CHECK, {"bulk.test": 1256}, CAP)

    assert result["published_rate"] == 0.9 * 100 / 110
    # weight = (25 + 1256) / 25 = 51.24, applied to ten failing observations
    weighted_total = 110 - 10 + 10 * (CAP + 1256) / CAP
    assert result["reweighted_rate"] == 90 / weighted_total
    assert result["reweighted_rate"] < result["published_rate"]
    assert result["capped_rate"] == 0.0
    assert result["uncapped_rate"] == 0.9


def test_the_sign_is_not_written_into_the_code() -> None:
    """A capped host that conforms better pulls the rate up, and must be allowed to."""
    reports = _corpus({"small.test": (50, 50), "bulk.test": (10, 0)})
    result = sampling_bias(reports, CHECK, {"bulk.test": 475}, CAP)
    assert result["reweighted_rate"] > result["published_rate"]
    assert result["capped_rate"] == 1.0


def test_the_weight_is_over_the_admitted_count_not_the_applicable_one() -> None:
    """Endpoints the cap admitted but the check did not apply to must not inflate the weight.

    Dividing the frame size by the number of *applicable* observations would make every
    endpoint excluded by an outcome rule multiply the host's remaining ones, which turns the
    exclusion ledger into a weighting scheme nobody declared.
    """
    conforming = _corpus({"bulk.test": (4, 0)})
    not_applicable = [
        EndpointReport(
            endpoint=Endpoint(endpoint_id=f"bulk-na-{i}", url=f"https://bulk.test/mcp/na{i}",
                              kind=EndpointKind.MCP_REMOTE, source="t",
                              apex_domain="bulk.test"),
            modality=Modality.OAUTH_METADATA,
            reachable=True,
            checks=[CheckResult(check_id=CHECK, outcome=Outcome.NOT_APPLICABLE,
                                normative_strength=NormativeStrength.MUST, detail="d")],
            probed_at=datetime.now(UTC),
            run_id="r1",
        )
        for i in range(21)
    ]
    plain = _corpus({"other.test": (0, 4)})
    result = sampling_bias(conforming + not_applicable + plain, CHECK, {"bulk.test": 75}, CAP)

    # four applicable observations, each standing for (25 + 75) / 25 = 4 of the frame
    assert result["capped_n"] == 4
    assert result["reweighted_rate"] == 16 / 20


def test_endpoints_the_access_policy_declined_do_not_enter() -> None:
    """The same populations leave here as leave `rate_by_unit`."""
    reports = _corpus({"a.test": (2, 2)})
    blocked = _report("a.test", 200, Outcome.PASS)
    result_without = sampling_bias(reports, CHECK, {}, CAP)
    result_with = sampling_bias(
        reports + [blocked.model_copy(update={"robots_allowed": False})], CHECK, {}, CAP)
    assert result_without["published_rate"] == result_with["published_rate"]
