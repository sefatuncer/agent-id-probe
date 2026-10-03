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

from agentidprobe.analysis import per_host_sampling, sampling_bias
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


def _not_applicable(host: str, count: int, *, refused: bool = False) -> list[EndpointReport]:
    """Sampled endpoints the check did not apply to, or, with `refused`, that our own
    per-host ceiling kept us from asking at all (as `checks_oauth` records it)."""
    detail = "not observed: out_of_scope (R4/R5)" if refused else "d"
    observed = "host has already received 30 requests this pass" if refused else None
    return [
        EndpointReport(
            endpoint=Endpoint(endpoint_id=f"{host}-na-{i}", url=f"https://{host}/mcp/na{i}",
                              kind=EndpointKind.MCP_REMOTE, source="t", apex_domain=host),
            modality=Modality.OAUTH_METADATA,
            reachable=not refused,
            checks=[CheckResult(check_id=CHECK,
                                outcome=Outcome.ERROR if refused else Outcome.NOT_APPLICABLE,
                                normative_strength=NormativeStrength.MUST, detail=detail,
                                observed_value=observed)],
            probed_at=datetime.now(UTC),
            run_id="r1",
        )
        for i in range(count)
    ]


def test_a_capped_host_on_the_minority_side_pulls_the_rate_down() -> None:
    """The shape the census has: one large host, entirely failing, mostly unmeasured."""
    # bulk.test carried 25 + 1256 endpoints in the frame, all 25 sampled were asked, and
    # ten of them were applicable
    reports = (_corpus({"small.test": (90, 10), "bulk.test": (0, 10)})
               + _not_applicable("bulk.test", 15))
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
    reports = (_corpus({"small.test": (50, 50), "bulk.test": (10, 0)})
               + _not_applicable("bulk.test", 15))
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


def test_the_weight_is_over_the_endpoints_actually_asked() -> None:
    """H2-M4. The ceiling refused 16 of the 25 sampled endpoints on the census's largest
    host, so it was measured through nine. Each measured endpoint stands for the frame over
    the endpoints actually asked, and weighting by the 25 sampled understated it 2.8-fold."""
    reports = (_corpus({"small.test": (90, 10), "bulk.test": (0, 9)})
               + _not_applicable("bulk.test", 16, refused=True))
    table = per_host_sampling(reports, {"bulk.test": 1256})
    row = table["hosts"]["bulk.test"]
    assert (row["frame"], row["sampled"], row["contacted"]) == (1281, 25, 9)
    assert table["capped_never_contacted"] == 16
    assert table["largest_weight"] == 1281 / 9

    result = sampling_bias(reports, CHECK, {"bulk.test": 1256}, CAP)
    assert result["reweighted_rate"] == 90 / (100 + 9 * 1281 / 9)


def test_a_host_the_sampling_rule_never_touched_is_still_weighted_if_the_ceiling_bit() -> None:
    """The ceiling left endpoints unasked on hosts the sampling rule never capped (ten in
    census2)."""
    reports = (_corpus({"small.test": (90, 10), "busy.test": (0, 5)})
               + _not_applicable("busy.test", 5, refused=True))
    table = per_host_sampling(reports, {})
    assert table["uncapped_hosts_refused"] == 1
    assert table["uncapped_never_contacted"] == 5
    assert table["weights"] == {"busy.test": 2.0}
