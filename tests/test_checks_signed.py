"""Signed-document checks, plus the conformance fixture pack required by decision rule R8.

R8 was rewritten on 28 July 2026: a mechanical instrument cannot be validated by
inter-rater reliability, because there is no rater. It is validated by known-conformant
and known-violating fixtures plus replay determinism, both of which live here.

The fixtures are built by signing real cards with real keys, so a passing test means the
checker agrees with an independent JOSE implementation about what a valid A2A signature
is — not merely with itself.
"""

import base64
import json
from pathlib import Path

import httpx
import respx
from joserfc import jws
from joserfc.jwk import ECKey

from agentidprobe.checks_signed import did_web_to_url, probe_signed, signing_payload
from agentidprobe.config import MeasurementConfig, RatePolicy
from agentidprobe.fetcher import ErrorKind, Fetcher, FetchResult
from agentidprobe.models import CheckId, Outcome

FAST = MeasurementConfig(
    rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0)
)

CARD_URL = "https://agent.example.org/.well-known/agent-card.json"
JKU = "https://agent.example.org/.well-known/jwks.json"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign_card(card: dict, key: ECKey, *, kid: str = "k1", tamper: bool = False) -> dict:
    """Produce an A2A-style detached signature over the JCS payload."""
    payload = signing_payload(card)
    compact = jws.serialize_compact({"alg": "ES256", "kid": kid, "jku": JKU}, payload, key)
    protected, _, signature = compact.split(".")
    if tamper:
        flipped = bytearray(base64.urlsafe_b64decode(signature + "=="))
        flipped[0] ^= 0xFF
        signature = _b64url(bytes(flipped))
    return {"protected": protected, "signature": signature, "header": {"kid": kid}}


def _card(**extra) -> dict:
    return {"name": "Example Agent", "version": "1.0.0",
            "url": "https://agent.example.org/a2a", **extra}


def _fetched(document: dict | None, status: int = 200) -> FetchResult:
    body = json.dumps(document).encode() if document is not None else b""
    return FetchResult(url=CARD_URL, ok=True, status=status, body=body)


def _no_robots(*hosts: str) -> None:
    for host in hosts:
        respx.get(f"{host}/robots.txt").mock(return_value=httpx.Response(404))


def _outcome(checks, check_id):
    return next(c.outcome for c in checks if c.check_id == check_id)


def _result(checks, check_id):
    """The whole CheckResult, for tests that assert on the anchor rather than the verdict.

    C15's split turns on which specification sentence a verdict carries, not only on whether it
    passes, so the reference has to be assertable: the version of this check that convicted a
    publisher did so citing "RFC 7518 / BCP 195", and nothing in the suite looked at that string.
    """
    return next(c for c in checks if c.check_id == check_id)


# --- did:web resolution -------------------------------------------------------


def test_did_web_bare_domain_resolves_to_wellknown():
    assert did_web_to_url("did:web:example.org") == "https://example.org/.well-known/did.json"


def test_did_web_with_path_resolves_without_wellknown():
    assert did_web_to_url("did:web:example.org:agents:a1") == \
        "https://example.org/agents/a1/did.json"


def test_did_web_percent_encoded_port_is_decoded():
    assert did_web_to_url("did:web:example.org%3A8443") == \
        "https://example.org:8443/.well-known/did.json"


def test_non_did_web_returns_none():
    assert did_web_to_url("did:key:z6Mk") is None


# --- R8 fixture pack: known-conformant ----------------------------------------


@respx.mock
async def test_known_conformant_signed_card_verifies():
    key = ECKey.generate_key("P-256")
    card = _card()
    card["signatures"] = [_sign_card(card, key)]

    _no_robots("https://agent.example.org")
    respx.get(JKU).mock(return_value=httpx.Response(
        200, json={"keys": [key.as_dict(private=False, kid="k1")]}))

    async with Fetcher(FAST) as f:
        checks, ev = await probe_signed(f, CARD_URL, _fetched(card))

    assert _outcome(checks, CheckId.IDENTITY_METADATA_PUBLISHED) is Outcome.PASS
    assert _outcome(checks, CheckId.CARD_SIGNED) is Outcome.PASS
    assert _outcome(checks, CheckId.KEY_RESOLVABLE) is Outcome.PASS
    assert _outcome(checks, CheckId.SIGNATURE_VERIFIES) is Outcome.PASS
    assert _outcome(checks, CheckId.KEY_STRENGTH) is Outcome.PASS
    assert ev.verified_count == 1


@respx.mock
async def test_signature_survives_key_reordering_of_the_card():
    """JCS exists precisely so that member order does not change the signature. If this
    fails, every card whose server reserialises JSON would be falsely accused."""
    key = ECKey.generate_key("P-256")
    card = _card()
    signature = _sign_card(card, key)
    reordered = {"url": card["url"], "version": card["version"], "name": card["name"],
                 "signatures": [signature]}

    _no_robots("https://agent.example.org")
    respx.get(JKU).mock(return_value=httpx.Response(
        200, json={"keys": [key.as_dict(private=False, kid="k1")]}))

    async with Fetcher(FAST) as f:
        checks, _ = await probe_signed(f, CARD_URL, _fetched(reordered))
    assert _outcome(checks, CheckId.SIGNATURE_VERIFIES) is Outcome.PASS


# --- R8 fixture pack: known-violating -----------------------------------------


@respx.mock
async def test_tampered_signature_is_a_must_violation():
    key = ECKey.generate_key("P-256")
    card = _card()
    card["signatures"] = [_sign_card(card, key, tamper=True)]

    _no_robots("https://agent.example.org")
    respx.get(JKU).mock(return_value=httpx.Response(
        200, json={"keys": [key.as_dict(private=False, kid="k1")]}))

    async with Fetcher(FAST) as f:
        checks, _ = await probe_signed(f, CARD_URL, _fetched(card))
    assert _outcome(checks, CheckId.KEY_RESOLVABLE) is Outcome.PASS
    assert _outcome(checks, CheckId.SIGNATURE_VERIFIES) is Outcome.FAIL_MISIMPLEMENTED


@respx.mock
async def test_modified_card_body_breaks_the_signature():
    key = ECKey.generate_key("P-256")
    card = _card()
    signature = _sign_card(card, key)
    card["name"] = "Renamed After Signing"
    card["signatures"] = [signature]

    _no_robots("https://agent.example.org")
    respx.get(JKU).mock(return_value=httpx.Response(
        200, json={"keys": [key.as_dict(private=False, kid="k1")]}))

    async with Fetcher(FAST) as f:
        checks, _ = await probe_signed(f, CARD_URL, _fetched(card))
    assert _outcome(checks, CheckId.SIGNATURE_VERIFIES) is Outcome.FAIL_MISIMPLEMENTED


# --- unsigned and unreachable cases -------------------------------------------


async def test_unsigned_card_is_never_a_failure():
    """A2A makes `signatures` OPTIONAL for the publisher. Decision rule R1 means the
    model itself would reject a FAIL here, so this is the common case in the wild."""
    async with Fetcher(FAST) as f:
        checks, _ = await probe_signed(f, CARD_URL, _fetched(_card()))
    assert _outcome(checks, CheckId.CARD_SIGNED) is Outcome.UNSPECIFIED
    assert _outcome(checks, CheckId.SIGNATURE_VERIFIES) is Outcome.NOT_APPLICABLE


async def test_absent_card_is_unspecified_not_a_failure():
    async with Fetcher(FAST) as f:
        checks, _ = await probe_signed(f, CARD_URL, _fetched(None, status=404))
    assert _outcome(checks, CheckId.IDENTITY_METADATA_PUBLISHED) is Outcome.UNSPECIFIED


@respx.mock
async def test_unreachable_key_does_not_convict_the_signature():
    key = ECKey.generate_key("P-256")
    card = _card()
    card["signatures"] = [_sign_card(card, key)]

    _no_robots("https://agent.example.org")
    respx.get(JKU).mock(return_value=httpx.Response(404))

    async with Fetcher(FAST) as f:
        checks, _ = await probe_signed(f, CARD_URL, _fetched(card))
    assert _outcome(checks, CheckId.KEY_RESOLVABLE) is Outcome.FAIL_UNIMPLEMENTED
    assert _outcome(checks, CheckId.SIGNATURE_VERIFIES) is Outcome.NOT_APPLICABLE


async def test_blocked_fetch_yields_errors_only():
    blocked = FetchResult(url=CARD_URL, ok=False, status=403, error_kind=ErrorKind.BLOCKED)
    async with Fetcher(FAST) as f:
        checks, _ = await probe_signed(f, CARD_URL, blocked)
    assert all(c.outcome is Outcome.ERROR for c in checks)


@respx.mock
async def test_an_unverifiable_algorithm_is_recorded_without_convicting_anybody():
    """The C15 split of 30 July 2026 (R9.7), on the side that lost its MUST.

    This test asserted `FAIL_MISIMPLEMENTED` until that date, on the strength of a `spec_ref`
    reading "RFC 7518 / BCP 195". Neither half held. Every MUST in RFC 7518 §3.6 binds an
    implementation *accepting* an unsecured JWS -- "Implementations that support Unsecured JWSs
    MUST NOT accept such objects as valid unless..." -- and nothing there forbids publishing
    one; the document that would forbid it, RFC 8725, is a BCP about JWTs while an agent-card
    signature is a detached JWS over a JCS payload. BCP 195 is about TLS and was simply the
    wrong reference. Convicting the publisher was the same error that demoted C14 and kept C16
    descriptive: reading an obligation on the consuming party as a defect in the observable one.

    What must NOT change is the security behaviour: verification is still never attempted under
    `none`, because a signature anyone can forge is not evidence of a binding and crediting it
    would inflate C04. Declining to credit and convicting are separate acts; only the second
    needed a MUST. Both halves are asserted here so a later "consistency" fix cannot quietly
    restore the conviction or, worse, start crediting the signature.
    """
    key = ECKey.generate_key("P-256")
    card = _card()
    payload = signing_payload(card)
    header = _b64url(json.dumps({"alg": "none", "kid": "k1", "jku": JKU}).encode())
    card["signatures"] = [{"protected": header, "signature": "", "header": {"kid": "k1"}}]

    _no_robots("https://agent.example.org")
    respx.get(JKU).mock(return_value=httpx.Response(
        200, json={"keys": [key.as_dict(private=False, kid="k1")]}))

    async with Fetcher(FAST) as f:
        checks, _ = await probe_signed(f, CARD_URL, _fetched(card))

    assert _outcome(checks, CheckId.KEY_STRENGTH) is Outcome.UNSPECIFIED
    result = _result(checks, CheckId.KEY_STRENGTH)
    assert "none" in result.observed_value, "the algorithm must still be recorded"
    assert "3.6" in result.spec_ref and "8725" in result.spec_ref, (
        "the verdict has to carry why it is not a violation, since that is the surprising half"
    )
    # And the signature is still not credited.
    assert _outcome(checks, CheckId.SIGNATURE_VERIFIES) is Outcome.UNSPECIFIED
    assert payload  # payload construction is exercised above


@respx.mock
async def test_an_undersized_rsa_key_is_a_must_violation_and_c04_is_not_charged_for_it():
    """The half of C15 that survived, and the false statement that removal exposed.

    RFC 7518 §3.3 -- "A key of size 2048 bits or larger MUST be used with these algorithms" --
    binds the signer, sits in the document C15 already cited, and is observable straight from
    the published key set. So C15 was not demoted wholesale: blanket-demoting it would have
    discarded a correctly anchored measurement in order to tidy up two badly anchored ones.

    The second assertion is the more important one. This card's signature is genuine and would
    verify; the instrument declines to attempt it because a 1024-bit RSA signature is not
    creditable. Until 30 July 2026 that fell through to C04 `FAIL_MISIMPLEMENTED` with the
    detail "key resolved but no signature verified over the JCS payload" -- a MUST-level
    accusation whose own detail string was false. R6 puts what we chose not to observe in
    UNSPECIFIED.
    """
    fixture = json.loads(
        (Path(__file__).resolve().parent / "fixtures"
         / "c15-violating-rsa-key-below-2048-bits.json").read_text(encoding="utf-8")
    )
    card = fixture["endpoint"]["response"]["json"]
    jwks = fixture["documents"][0]

    _no_robots("https://agent.example.org")
    respx.get(jwks["url"]).mock(return_value=httpx.Response(200, json=jwks["json"]))

    async with Fetcher(FAST) as f:
        checks, _ = await probe_signed(f, CARD_URL, _fetched(card))

    assert _outcome(checks, CheckId.KEY_STRENGTH) is Outcome.FAIL_MISIMPLEMENTED
    result = _result(checks, CheckId.KEY_STRENGTH)
    assert "3.3" in result.spec_ref and "2048" in result.spec_ref
    assert _outcome(checks, CheckId.SIGNATURE_VERIFIES) is Outcome.UNSPECIFIED

    # Third-party corroboration that the fixture's key really is undersized, rather than our
    # own arithmetic agreeing with itself: joserfc raises its own SecurityWarning on this key.
    # pyproject silences that warning for the suite, so it is asserted here instead of merely
    # tolerated -- if the fixture were ever regenerated at 2048 bits, this fails.
    n = jwks["json"]["keys"][0]["n"]
    assert len(base64.urlsafe_b64decode(n + "=" * (-len(n) % 4))) * 8 == 1024


# --- R8: replay determinism ---------------------------------------------------


@respx.mock
async def test_replay_determinism():
    """Same raw artefact, scored twice, must give identical verdicts. Without this the
    published dataset could not be re-scored after an instrument fix."""
    key = ECKey.generate_key("P-256")
    card = _card()
    card["signatures"] = [_sign_card(card, key)]

    _no_robots("https://agent.example.org")
    respx.get(JKU).mock(return_value=httpx.Response(
        200, json={"keys": [key.as_dict(private=False, kid="k1")]}))

    async with Fetcher(FAST) as f:
        first, _ = await probe_signed(f, CARD_URL, _fetched(card))
        second, _ = await probe_signed(f, CARD_URL, _fetched(card))

    assert [c.model_dump() for c in first] == [c.model_dump() for c in second]
