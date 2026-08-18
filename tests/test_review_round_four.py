"""Tests for the quantities the fourth review round asked for.

Each of these exists because a referee found a published sentence that the corpus does not
support, and each test fails if the defect it describes comes back. They are written against
constructed populations rather than against the census, so they check the arithmetic and not
the run.
"""

from datetime import UTC, datetime

from agentidprobe.analysis import (
    _oidc_id_token_carrier,
    _publishes_oidc_metadata,
    challenge_evidence,
    failure_fingerprint_composition,
    implementation_unit_composition,
    issuers_per_endpoint,
    mixup_defence_carriers,
)


def _report(endpoint_id: str, *, apex: str = "a.test", status: int | None = 401,
            www_authenticate: str | None = 'Bearer realm="x"',
            fingerprint: str | None = "fp-1", outcome=None, check=None,
            issuers: list[str] | None = None,
            documents: dict | None = None, robots_allowed: bool = True):
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
    check = check or CheckId.PRM_PRESENT
    outcome = Outcome.PASS if outcome is None else outcome
    return EndpointReport(
        endpoint=Endpoint(endpoint_id=endpoint_id, url=f"https://{endpoint_id}.test/mcp",
                          kind=EndpointKind.MCP_REMOTE, source="t", apex_domain=apex),
        modality=Modality.OAUTH_METADATA,
        reachable=True,
        robots_allowed=robots_allowed,
        http_status=status,
        checks=[CheckResult(check_id=check, outcome=outcome,
                            normative_strength=NormativeStrength.MUST,
                            spec_ref="RFC 9728 3.1")],
        evidence={
            "implementation_fingerprint": fingerprint,
            "www_authenticate": www_authenticate,
            "authorization_servers": issuers or [],
            "as_documents": documents or {},
        },
        probed_at=datetime.now(UTC),
        run_id="r1",
    )


# --- the second carrier of the mix-up defence ---------------------------------


def test_id_token_carrier_needs_the_authorization_response_not_merely_openid():
    """RFC 9700 4.4.2 puts the issuer in an ID Token *returned in the authorization
    response*. A provider that only ever returns it at the token endpoint has not given
    the client the same check, so the narrow predicate must not fire on it."""
    token_endpoint_only = {"response_types_supported": ["code"],
                           "subject_types_supported": ["public"]}
    hybrid = {"response_types_supported": ["code", "code id_token"]}

    assert not _oidc_id_token_carrier(token_endpoint_only)
    assert _oidc_id_token_carrier(hybrid)
    # the wide reading fires on both, which is why both are reported
    assert _publishes_oidc_metadata(token_endpoint_only)
    assert not _publishes_oidc_metadata(hybrid)


def test_carrier_union_is_a_union_and_not_a_sum():
    """An issuer that advertises RFC 9207 *and* returns an ID Token must be counted once.
    Adding the two rates would double it, which is the arithmetic the paper would have
    done had it reported them separately."""
    both = {"authorization_response_iss_parameter_supported": True,
            "response_types_supported": ["code id_token"]}
    iss_only = {"authorization_response_iss_parameter_supported": True}
    reports = [
        _report("e1", issuers=["https://i1.test"], documents={"https://i1.test": both}),
        _report("e2", issuers=["https://i2.test"], documents={"https://i2.test": iss_only}),
    ]
    carriers = mixup_defence_carriers(reports)

    assert carriers["observed_issuers"] == 2
    assert carriers["rfc9207"] == 2
    narrow = carriers["id_token_in_authorization_response"]
    assert narrow["carrier"] == 1
    assert narrow["carrier_only"] == 0      # it also advertises iss
    assert narrow["union"] == 2             # not 3


def test_unobservable_carrier_is_named_rather_than_silently_dropped():
    """The third countermeasure is a client-side arrangement no server document shows.
    Leaving it unnamed would let the union read as the whole of what is available."""
    carriers = mixup_defence_carriers([_report("e1")])
    assert any("redirection URI" in note for note in carriers["unobservable_carriers"])


# --- what the two challenge statuses carried ----------------------------------


def test_403_without_a_challenge_header_is_visible_as_such():
    """Every 403 in the census answered without WWW-Authenticate, which is what a filter
    returns rather than an authorization server. The rule still counts them; the record
    has to make the cost of that visible."""
    reports = [
        _report("ok", status=401, www_authenticate='Bearer realm="x"'),
        _report("waf", status=403, www_authenticate=None),
        _report("waf2", status=403, www_authenticate=None),
    ]
    evidence = challenge_evidence(reports)

    assert evidence["by_status"]["403"]["n"] == 2
    assert evidence["by_status"]["403"]["with_header"] == 0
    assert evidence["by_status"]["403"]["header_rate"] == 0.0
    assert evidence["by_status"]["401"]["with_header"] == 1


def test_rfc6750_population_excludes_what_our_own_policy_declined_to_ask():
    """R4: a politeness exclusion must never be published as an operator's failure. An
    endpoint robots.txt kept us away from cannot be scored for a missing header."""
    reports = [
        _report("a", status=401, www_authenticate=None),
        _report("b", status=401, www_authenticate=None, robots_allowed=False),
        _report("c", status=401, www_authenticate='Bearer realm="x"'),
    ]
    evidence = challenge_evidence(reports)

    assert evidence["rfc6750_population"] == 2      # not 3
    assert evidence["rfc6750_failing"] == 1
    assert evidence["rfc6750_conforming"] == 1


def test_rfc6750_rate_is_clustered_by_apex():
    """Ten endpoints on one apex all missing the header would otherwise set the interval
    as if they were ten independent observations."""
    reports = [
        _report(f"bulk{i}", apex="bulk.test", status=401, www_authenticate=None)
        for i in range(10)
    ] + [
        _report(f"solo{i}", apex=f"solo{i}.test", status=401,
                www_authenticate='Bearer realm="x"')
        for i in range(10)
    ]
    evidence = challenge_evidence(reports)

    assert evidence["rfc6750_population"] == 20
    assert evidence["rfc6750_failing"] == 10
    assert evidence["rfc6750_rate"]["m"] == 11      # ten solo apexes plus the bulk one


# --- what the implementation unit is made of ----------------------------------


def test_implementation_unit_separates_fingerprints_from_their_absence():
    """C05's fingerprint is a hash over the document whose absence is the failure, so an
    endpoint that publishes nothing cannot have one and becomes its own singleton cluster.
    The collapsed rate is then a mixture of implementations and of endpoints standing in
    for the absence of one, and reporting it as a property of implementations is wrong."""
    from agentidprobe.models import CheckId, Outcome

    reports = [
        _report(f"pass{i}", apex=f"p{i}.test", fingerprint="fp-shared",
                outcome=Outcome.PASS)
        for i in range(4)
    ] + [
        _report(f"fail{i}", apex=f"f{i}.test", fingerprint=None,
                outcome=Outcome.FAIL_UNIMPLEMENTED)
        for i in range(6)
    ]
    rows = implementation_unit_composition(reports, CheckId.PRM_PRESENT)

    assert rows["fingerprinted"]["n"] == 1          # four endpoints, one implementation
    assert rows["fingerprinted"]["rate"] == 1.0
    assert rows["synthetic"]["n"] == 6              # six singletons that are not implementations
    assert rows["synthetic"]["rate"] == 0.0
    assert abs(rows["total"]["rate"] - 1 / 7) < 1e-9
    assert abs(rows["synthetic_share"] - 6 / 7) < 1e-9


# --- the denominator under the concentration statistic ------------------------


def test_top10_share_is_reported_over_both_denominators():
    """Section 6.8's share is over the failures that have a fingerprint. The share over
    every failure is smaller and is the one the sentence sounds like it is making."""
    from agentidprobe.models import Outcome

    reports = [
        _report(f"fp{i}", fingerprint="fp-a", outcome=Outcome.FAIL_MISIMPLEMENTED)
        for i in range(3)
    ] + [
        _report(f"none{i}", fingerprint=None, outcome=Outcome.FAIL_UNIMPLEMENTED)
        for i in range(7)
    ]
    composition = failure_fingerprint_composition(reports)

    assert composition["failures_total"] == 10
    assert composition["failures_with_fingerprint"] == 3
    assert composition["failures_without_fingerprint"] == 7
    assert composition["top10_share_of_fingerprinted"] == 1.0
    assert abs(composition["top10_share_of_all"] - 0.3) < 1e-9


# --- how many authorization servers one resource names ------------------------


def test_issuers_per_endpoint_counts_the_selection_the_defence_addresses():
    """BCP 240 requires a mix-up defence of a client able to reach more than one
    authorization server. Whether that selection arises at an endpoint is an empirical
    question about the corpus, and Section 8.2 answered it by assumption."""
    reports = [
        _report("one", issuers=["https://i1.test"]),
        _report("two", issuers=["https://i1.test", "https://i2.test"]),
        _report("none", issuers=[]),
    ]
    per_endpoint = issuers_per_endpoint(reports)

    assert per_endpoint["declaring_endpoints"] == 2   # the endpoint declaring nothing leaves
    assert per_endpoint["declarations"] == 3
    assert per_endpoint["max"] == 2
    assert per_endpoint["more_than_one"] == 1
    assert abs(per_endpoint["more_than_one_share"] - 0.5) < 1e-9
