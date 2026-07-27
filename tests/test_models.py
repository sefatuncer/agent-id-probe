"""Tests for the measurement instrument.

These are about *invariants we must not silently break* rather than coverage. The
decision rules in docs/decision-rules.md are frozen before data collection; each rule
that is machine-enforceable has a test here, so a later edit that weakens the
instrument fails CI instead of quietly changing the paper's numbers.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentidprobe import __version__
from agentidprobe.config import DEFAULT_CONFIG, USER_AGENT
from agentidprobe.models import (
    DESCRIPTIVE_ONLY,
    FUNNELS,
    CheckId,
    CheckResult,
    Endpoint,
    EndpointKind,
    EndpointReport,
    Hosting,
    Modality,
    NormativeStrength,
    Outcome,
    has_cryptographic_binding,
    resolve_precedence,
)


def _endpoint(url: str = "https://example.org/mcp") -> Endpoint:
    return Endpoint(
        endpoint_id="abc123",
        url=url,
        kind=EndpointKind.MCP_REMOTE,
        source="unit-test",
        apex_domain="example.org",
        hosting=Hosting.SELF_HOSTED,
    )


def _report(checks: list[CheckResult], **kw) -> EndpointReport:
    return EndpointReport(
        endpoint=kw.pop("endpoint", _endpoint()),
        modality=kw.pop("modality", Modality.OAUTH_METADATA),
        reachable=True,
        http_status=200,
        checks=checks,
        probed_at=datetime.now(UTC),
        run_id="test-run",
        **kw,
    )


def test_version_present():
    assert __version__


def test_check_set_is_complete():
    assert len(list(CheckId)) == 15


# --- R1: only a MUST may fail -------------------------------------------------


def test_r1_rejects_failure_without_must_anchor():
    with pytest.raises(ValidationError):
        CheckResult(
            check_id=CheckId.PKCE_DECLARED,
            outcome=Outcome.FAIL_UNIMPLEMENTED,
            normative_strength=NormativeStrength.SHOULD,
        )


def test_r1_rejects_failure_on_descriptive_only_check():
    with pytest.raises(ValidationError):
        CheckResult(
            check_id=CheckId.CARD_SIGNED,
            outcome=Outcome.FAIL_UNIMPLEMENTED,
            normative_strength=NormativeStrength.MUST,
        )


def test_r1_allows_unspecified_at_should_level():
    result = CheckResult(
        check_id=CheckId.CARD_SIGNED,
        outcome=Outcome.UNSPECIFIED,
        normative_strength=NormativeStrength.SHOULD,
        spec_ref="A2A 8.4",
    )
    assert result.outcome is Outcome.UNSPECIFIED


def test_r1_allows_failure_at_must_level():
    result = CheckResult(
        check_id=CheckId.PRM_RESOURCE_IDENTITY_MATCH,
        outcome=Outcome.FAIL_MISIMPLEMENTED,
        normative_strength=NormativeStrength.MUST,
        spec_ref="RFC 9728 3.3",
    )
    assert result.outcome is Outcome.FAIL_MISIMPLEMENTED


def test_descriptive_only_set_matches_intent():
    assert DESCRIPTIVE_ONLY == {
        CheckId.CARD_SIGNED,
        CheckId.SENDER_CONSTRAINED,
        CheckId.REVOCATION_DECLARED,
        CheckId.TRUST_ANCHORED,
    }


# --- R2: outcome precedence ---------------------------------------------------


def test_r2_error_beats_everything():
    assert resolve_precedence([Outcome.PASS, Outcome.ERROR]) is Outcome.ERROR


def test_r2_unspecified_beats_failure():
    assert (
        resolve_precedence([Outcome.FAIL_MISIMPLEMENTED, Outcome.UNSPECIFIED])
        is Outcome.UNSPECIFIED
    )


def test_r2_misimplemented_beats_unimplemented():
    assert (
        resolve_precedence([Outcome.FAIL_UNIMPLEMENTED, Outcome.FAIL_MISIMPLEMENTED])
        is Outcome.FAIL_MISIMPLEMENTED
    )


# --- Funnels ------------------------------------------------------------------


def test_two_disjoint_funnels_exist():
    assert set(FUNNELS) == {Modality.OAUTH_METADATA, Modality.SIGNED_DOCUMENT}
    oauth = {c for _, c in FUNNELS[Modality.OAUTH_METADATA] if c}
    signed = {c for _, c in FUNNELS[Modality.SIGNED_DOCUMENT] if c}
    assert not (oauth & signed), "a check may not appear in both funnels"


def test_no_descriptive_check_is_a_funnel_stage_that_can_fail():
    """A descriptive-only check may appear in a funnel (CARD_SIGNED does), but it can
    never produce a failure, so the funnel must not treat its absence as a violation."""
    for stages in FUNNELS.values():
        for _, check in stages:
            if check in DESCRIPTIVE_ONLY:
                assert check is CheckId.CARD_SIGNED  # the only intentional case


def test_every_funnel_starts_with_reachability():
    for stages in FUNNELS.values():
        assert stages[0][1] is None


# --- Attribution safety -------------------------------------------------------


def test_cross_origin_redirect_is_detected():
    report = _report(
        [],
        endpoint=_endpoint("https://example.org/mcp"),
        final_url="https://cdn.elsewhere.net/mcp",
        redirect_chain=["https://example.org/mcp", "https://cdn.elsewhere.net/mcp"],
    )
    assert report.crossed_origin() is True


def test_same_origin_redirect_is_not_flagged():
    report = _report(
        [],
        final_url="https://example.org/mcp/",
        redirect_chain=["https://example.org/mcp", "https://example.org/mcp/"],
    )
    assert report.crossed_origin() is False


def test_headline_binary_requires_a_verified_signature():
    unsigned = _report(
        [
            CheckResult(
                check_id=CheckId.PRM_PRESENT,
                outcome=Outcome.PASS,
                normative_strength=NormativeStrength.MUST,
            )
        ]
    )
    assert has_cryptographic_binding(unsigned) is False

    signed = _report(
        [
            CheckResult(
                check_id=CheckId.SIGNATURE_VERIFIES,
                outcome=Outcome.PASS,
                normative_strength=NormativeStrength.MUST,
            )
        ],
        modality=Modality.SIGNED_DOCUMENT,
    )
    assert has_cryptographic_binding(signed) is True


# --- Policy -------------------------------------------------------------------


def test_user_agent_identifies_and_offers_optout():
    assert "agent-id-probe" in USER_AGENT
    assert "contact:" in USER_AGENT


def test_rate_policy_is_conservative():
    rate = DEFAULT_CONFIG.rate
    assert rate.per_host_requests_per_second <= 1.0
    assert rate.respect_robots_txt
    assert rate.honour_retry_after
    assert rate.global_concurrency <= 16


def test_report_lookup():
    report = _report(
        [
            CheckResult(
                check_id=CheckId.PRM_PRESENT,
                outcome=Outcome.PASS,
                normative_strength=NormativeStrength.MUST,
                spec_ref="MCP authorization",
            )
        ]
    )
    assert report.outcome_of(CheckId.PRM_PRESENT) is Outcome.PASS
    assert report.outcome_of(CheckId.TLS_VALID) is None
