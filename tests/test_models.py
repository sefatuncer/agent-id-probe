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
    """C16-C18 added and C06/C10 removed on 2026-07-28, before collection. This assertion
    exists so the instrument can neither grow nor shrink silently once data exists."""
    assert len(list(CheckId)) == 16
    assert not hasattr(CheckId, "AS_METADATA_VALID")   # C06: redundant with C13
    assert not hasattr(CheckId, "TRUST_ANCHORED")      # C10: no specification to anchor to


def test_every_declared_check_is_actually_emitted_somewhere():
    """A check that exists in the enum and in the specification map but in no code path
    lets the paper claim a measurement it never made. Five checks were in that state until
    2026-07-28; two were deleted and three wired up. This test is what stops the state
    from coming back."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentidprobe"
    emitted = "".join(
        (src / name).read_text(encoding="utf-8")
        for name in ("checks_oauth.py", "checks_signed.py")
    )
    for check in CheckId:
        assert f"CheckId.{check.name}" in emitted, f"{check.value} is declared but never emitted"


# --- R1: only a MUST may fail -------------------------------------------------


def test_r1_rejects_failure_without_must_anchor():
    """The strength branch of R1, exercised on its own.

    This used C14 until C14 became descriptive-only, at which point the constructor would
    have raised for the *other* reason and the test would have passed for years without
    ever reaching the branch it names. C12 is failable and stays failable, so a SHOULD here
    can only be rejected on strength.
    """
    with pytest.raises(ValidationError):
        CheckResult(
            check_id=CheckId.PRM_RESOURCE_IDENTITY_MATCH,
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
        spec_ref="A2A 5.5.6",
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
        CheckId.ISS_PARAMETER_DECLARED,
        CheckId.CLIENT_BOOTSTRAP_DECLARED,
        CheckId.PROTECTED_RESOURCES_DECLARED,
        # Joined on 29 July 2026: RFC 8414 §2 marks `code_challenge_methods_supported`
        # OPTIONAL and RFC 9700 §2.1.1 sets publishing it at RECOMMENDED while expressly
        # permitting a deployment-specific alternative, so its absence is not evidence of
        # any authorization-server MUST being violated.
        CheckId.PKCE_DECLARED,
        # Joined on 5 August 2026. Both were anchored to "A2A §8.4", which is not in the
        # revision R7 pins: A2A v0.3.0 has no §8.4, no §4.4.7, no reference to RFC 8785, and
        # no RFC 2119 keyword anywhere about card signatures — `AgentCardSignature` (§5.5.6)
        # defines a data structure and stops. The fallback, RFC 7515 §5.2, binds the party
        # validating a JWS rather than the one publishing it, so it cannot convict a
        # publisher either. C15 stays failable because RFC 7518 §3.3's 2048-bit floor does
        # bind the signer.
        CheckId.KEY_RESOLVABLE,
        CheckId.SIGNATURE_VERIFIES,
    }


def test_c16_cannot_charge_the_issuer_for_the_clients_obligation():
    """RFC 9700 §2.1 makes a mix-up defence REQUIRED, but of the *client*. A passive probe
    sees issuers, not clients, so recording the missing flag as the issuer's failure would
    score one party for another party's obligation. R1 makes that impossible."""
    with pytest.raises(ValidationError):
        CheckResult(
            check_id=CheckId.ISS_PARAMETER_DECLARED,
            outcome=Outcome.FAIL_UNIMPLEMENTED,
            normative_strength=NormativeStrength.MUST,
            spec_ref="RFC 9207 3",
        )


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


def test_the_signed_funnel_is_descriptive_except_for_key_strength():
    """A descriptive-only check may sit in a funnel; it just cannot fail there.

    Until 5 August 2026 CARD_SIGNED was the only such case. C03 and C04 joined it when their
    anchor turned out to be absent from the pinned A2A revision, which makes the whole
    signed-document funnel descriptive apart from C15 — and that is the accurate description
    of a terminated arm reported as prevalence. The OAuth funnel is unaffected and must stay
    so: every one of its stages can still convict.
    """
    descriptive_in_funnels = {
        check for stages in FUNNELS.values() for _, check in stages if check in DESCRIPTIVE_ONLY
    }
    assert descriptive_in_funnels == {
        CheckId.CARD_SIGNED, CheckId.KEY_RESOLVABLE, CheckId.SIGNATURE_VERIFIES,
    }
    oauth_stages = {check for _, check in FUNNELS[Modality.OAUTH_METADATA] if check is not None}
    assert not (oauth_stages & DESCRIPTIVE_ONLY)


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
