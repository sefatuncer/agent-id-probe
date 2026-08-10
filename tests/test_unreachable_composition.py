"""The unobserved fraction has to say what is inside it.

Section 9.2 named WAFs as the mechanism behind the endpoints that did not answer and gave no
number for how much of the fraction that mechanism could account for. An external review read
the sentence exactly as it was written and concluded the study loses mature enterprise
deployments to bot management. Over the census the access blocks are 37 endpoints of 8,896,
and more than half the fraction is hosts that no longer resolve -- so the sentence was
carrying a claim the corpus does not support, and nothing failed because nothing looked.

These tests fix three things a future change could quietly break:

* the buckets are keyed to `ErrorKind`, so a renamed member surfaces as `uncategorised`
  rather than emptying a bucket;
* the detail strings `checks_oauth` writes are the contract this reads, so a reworded string
  fails here instead of silently zeroing the composition;
* `OUT_OF_SCOPE` is our own gate and stays out of the operator-caused count, which is the
  population Section 9.2's narrowest Manski row is computed over.
"""

from datetime import UTC, datetime

import pytest

from agentidprobe.analysis import unreachable_composition
from agentidprobe.fetcher import ErrorKind
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

CHECK = CheckId.PRM_PRESENT


def _unreachable(
    endpoint_id: str,
    detail: str,
    *,
    robots_allowed: bool = True,
    opted_out: bool = False,
    reachable: bool = False,
) -> EndpointReport:
    return EndpointReport(
        endpoint=Endpoint(endpoint_id=endpoint_id, url=f"https://{endpoint_id}.test/mcp",
                          kind=EndpointKind.MCP_REMOTE, source="t", apex_domain="example.org"),
        modality=Modality.OAUTH_METADATA,
        reachable=reachable,
        robots_allowed=robots_allowed,
        opted_out=opted_out,
        checks=[
            CheckResult(check_id=CHECK, outcome=Outcome.ERROR,
                        normative_strength=NormativeStrength.MUST, detail=detail),
        ],
        probed_at=datetime.now(UTC),
        run_id="r1",
    )


def _detail(kind: ErrorKind) -> str:
    """The string `checks_oauth._probe` writes for a fetch that produced no status."""
    return f"not observed: {kind.value} (R4/R5)"


def test_buckets_split_dead_hosts_from_access_blocks():
    reports = [
        _unreachable("a", "access block (R4)"),
        _unreachable("b", _detail(ErrorKind.DNS)),
        _unreachable("c", _detail(ErrorKind.TLS)),
        _unreachable("d", _detail(ErrorKind.CONNECTION)),
        _unreachable("e", _detail(ErrorKind.TIMEOUT)),
    ]
    result = unreachable_composition(reports)
    assert result["total"] == 5
    assert result["blocked"] == 1
    assert result["dead"] == 3
    # A silent drop by a bot manager and an abandoned host look identical from outside, so a
    # timeout is reported on its own rather than assigned to either side.
    assert result["timeout"] == 1
    assert result["uncategorised"] == 0


def test_scope_gated_endpoints_leave_the_operator_caused_count():
    """`fetcher.ErrorKind` says OUT_OF_SCOPE is our decision and leaves every denominator."""
    reports = [
        _unreachable("a", _detail(ErrorKind.DNS)),
        _unreachable("b", _detail(ErrorKind.OUT_OF_SCOPE)),
        _unreachable("c", _detail(ErrorKind.OUT_OF_SCOPE)),
    ]
    result = unreachable_composition(reports)
    assert result["total"] == 3
    assert result["scope_gated"] == 2
    assert result["operator_caused"] == 1


def test_politeness_exclusions_are_not_in_the_population_at_all():
    """Robots and opt-out are counted in the exclusion ledger, not here."""
    reports = [
        _unreachable("a", _detail(ErrorKind.DNS)),
        _unreachable("b", _detail(ErrorKind.ROBOTS_DISALLOWED), robots_allowed=False),
        _unreachable("c", _detail(ErrorKind.OPTED_OUT), opted_out=True),
    ]
    result = unreachable_composition(reports)
    assert result["total"] == 1
    assert result["by_kind"] == {ErrorKind.DNS.value: 1}


def test_reachable_endpoints_are_excluded():
    reports = [
        _unreachable("a", _detail(ErrorKind.DNS), reachable=True),
        _unreachable("b", _detail(ErrorKind.DNS)),
    ]
    assert unreachable_composition(reports)["total"] == 1


def test_an_unrecognised_detail_string_is_surfaced_not_absorbed():
    """The failure mode this guards is a reworded detail emptying a bucket in silence."""
    reports = [_unreachable("a", "the fetch did not work out")]
    result = unreachable_composition(reports)
    assert result["total"] == 1
    assert result["uncategorised"] == 1
    assert result["blocked"] == 0
    assert result["dead"] == 0
    # An uncategorised endpoint is still unobserved for a reason that is not ours, so it
    # stays in the count Section 9.2 bounds rather than vanishing from every row.
    assert result["operator_caused"] == 1


@pytest.mark.parametrize("kind", [k for k in ErrorKind if k is not ErrorKind.NONE])
def test_every_error_kind_is_categorised(kind: ErrorKind):
    """Adding a member to `ErrorKind` without teaching this function about it fails here."""
    detail = "access block (R4)" if kind is ErrorKind.BLOCKED else _detail(kind)
    report = _unreachable(
        "a", detail,
        robots_allowed=kind is not ErrorKind.ROBOTS_DISALLOWED,
        opted_out=kind is ErrorKind.OPTED_OUT,
    )
    result = unreachable_composition([report])
    if kind in (ErrorKind.ROBOTS_DISALLOWED, ErrorKind.OPTED_OUT):
        assert result["total"] == 0
        return
    assert result["uncategorised"] == 0, f"{kind.value} fell into no bucket"


def test_detail_string_contract_matches_what_the_probe_writes():
    """Reads the source of truth rather than trusting the copy in this file.

    `checks_oauth` builds these strings in one place. If that formatting changes, the
    composition silently becomes all-uncategorised, and the census would report a corpus of
    endpoints that failed for no recorded reason.
    """
    import inspect

    from agentidprobe import checks_oauth

    source = inspect.getsource(checks_oauth)
    assert 'f"not observed: {initial.error_kind.value} (R4/R5)"' in source
    assert '"access block (R4)"' in source
