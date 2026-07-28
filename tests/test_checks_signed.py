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
async def test_forbidden_algorithm_is_flagged():
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
    assert _outcome(checks, CheckId.KEY_STRENGTH) is Outcome.FAIL_MISIMPLEMENTED
    assert payload  # payload construction is exercised above


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
