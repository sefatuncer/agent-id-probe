"""Signed-document checks (A2A Agent Cards, did:web).

Where the OAuth checks ask whether declared trust relationships are internally
consistent, these ask the harder question: can anything be *cryptographically* traced
back to a key the operator controls?

The pilot suggests the answer is almost always no — one signed card in twenty-five. That
makes correctness here unusually important, because a single false "signature broken"
verdict would be a large fraction of the positive class. Three safeguards:

* Publishing a card at all is only SHOULD in A2A, and carrying a signature is OPTIONAL
  for the publisher, so C01 and C02 can never report a failure (decision rule R1).
* Canonicalization ambiguity routes to UNSPECIFIED rather than to a failure (R6),
  because RFC 8785 and the A2A payload-construction rules leave real room for two
  honest implementations to disagree.
* A key we cannot fetch is an error, not a verdict about the operator.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlunsplit

from joserfc import jws
from joserfc.jwk import KeySet
from joserfc.jws import JWSRegistry

from .fetcher import ErrorKind, Fetcher, FetchResult
from .jcs import AmbiguousNumberError, JcsError, canonicalize
from .models import CheckId, CheckResult, NormativeStrength, Outcome

SPEC_A2A = "https://a2a-protocol.org/latest/specification/"
SPEC_A2A_DISCOVERY = "https://a2a-protocol.org/latest/topics/agent-discovery/"
SPEC_RFC7515 = "https://www.rfc-editor.org/rfc/rfc7515.html"
SPEC_RFC8785 = "https://www.rfc-editor.org/rfc/rfc8785.html"
SPEC_DIDWEB = "https://w3c-ccg.github.io/did-method-web/"

# RFC 7518 / BCP 195. `none` is unauthenticated by construction; a symmetric algorithm
# alongside a public key set means anyone holding the published key can forge.
_FORBIDDEN_ALGS = {"none", "HS256", "HS384", "HS512"}
_MIN_RSA_BITS = 2048

# joserfc's default registry admits only HS256/RS256/ES256 and rejects anything else as
# unsupported. Review showed that swallowed every valid ES384, PS256, RS512 and EdDSA
# signature into a "broken signature" verdict — and EdDSA is the usual choice for
# did:web, so the default would have zeroed out the very population we are counting.
# strict_check_header is off because real cards carry extra protected members (`iat`,
# `x5c`); an unrecognised header is not a forged signature.
_VERIFY_REGISTRY = JWSRegistry(
    algorithms=[
        "RS256", "RS384", "RS512",
        "PS256", "PS384", "PS512",
        "ES256", "ES384", "ES512",
        "EdDSA", "Ed25519",
    ],
    strict_check_header=False,
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def did_web_to_url(did: str) -> str | None:
    """Resolve a did:web identifier to its DID document URL.

    Per the method spec the method-specific identifier is the percent-encoded host
    (with `%3A` for a port) followed by colon-separated path segments; a bare domain
    resolves to /.well-known/did.json while a path resolves to <path>/did.json.
    """
    if not did.startswith("did:web:"):
        return None
    ident = did[len("did:web:") :]
    if not ident:
        return None
    parts = ident.split(":")
    host = parts[0].replace("%3A", ":").replace("%3a", ":")
    if not host:
        return None
    if len(parts) == 1:
        path = "/.well-known/did.json"
    else:
        path = "/" + "/".join(parts[1:]) + "/did.json"
    return urlunsplit(("https", host, path, "", ""))


@dataclass
class SignedEvidence:
    document: dict | None = None
    document_url: str | None = None
    signatures: list[dict] = field(default_factory=list)
    protected_headers: list[dict] = field(default_factory=list)
    key_sources: list[str] = field(default_factory=list)
    algs: list[str] = field(default_factory=list)
    verified_count: int = 0
    canonicalization_note: str | None = None

    def as_record(self) -> dict:
        """A JSON-serialisable snapshot, so a verdict can be re-scored from stored
        evidence rather than from the network."""
        return {
            "document": self.document,
            "document_url": self.document_url,
            "signatures": self.signatures,
            "protected_headers": self.protected_headers,
            "key_sources": list(self.key_sources),
            "algs": list(self.algs),
            "verified_count": self.verified_count,
            "canonicalization_note": self.canonicalization_note,
        }


def _decode_protected(sig: dict) -> dict | None:
    raw = sig.get("protected")
    if not isinstance(raw, str):
        return None
    try:
        header = json.loads(_b64url_decode(raw))
    except Exception:  # noqa: BLE001 - malformed header is data, not a crash
        return None
    return header if isinstance(header, dict) else None


def signing_payload(document: dict) -> bytes:
    """The bytes an A2A signer hashes: the card without `signatures`, JCS-canonical."""
    stripped = {k: v for k, v in document.items() if k != "signatures"}
    return canonicalize(stripped)


async def _resolve_keys(
    fetcher: Fetcher, header: dict, document: dict
) -> tuple[KeySet | None, str | None, str | None]:
    """Return (key set, source description, error). Sources tried in spec order."""
    jku = header.get("jku")
    if isinstance(jku, str) and jku.startswith("https://"):
        result = await fetcher.fetch(jku)
        if result.error_kind is ErrorKind.BLOCKED:
            return None, jku, "blocked"
        if result.status == 200:
            try:
                return KeySet.import_key_set(json.loads(result.body)), f"jku:{jku}", None
            except Exception as exc:  # noqa: BLE001
                return None, f"jku:{jku}", f"unusable JWKS: {exc}"
        return None, f"jku:{jku}", f"HTTP {result.status}"

    for candidate in (header.get("kid"), document.get("provider", {}).get("did")
                      if isinstance(document.get("provider"), dict) else None):
        if isinstance(candidate, str) and candidate.startswith("did:web:"):
            url = did_web_to_url(candidate)
            if not url:
                continue
            result = await fetcher.fetch(url)
            if result.error_kind is ErrorKind.BLOCKED:
                return None, url, "blocked"
            if result.status != 200:
                return None, f"did:web:{url}", f"HTTP {result.status}"
            try:
                doc = json.loads(result.body)
                methods = doc.get("verificationMethod", [])
                jwks = [m["publicKeyJwk"] for m in methods if isinstance(m, dict)
                        and isinstance(m.get("publicKeyJwk"), dict)]
                if not jwks:
                    return None, f"did:web:{url}", "no publicKeyJwk in DID document"
                return KeySet.import_key_set({"keys": jwks}), f"did:web:{url}", None
            except Exception as exc:  # noqa: BLE001
                return None, f"did:web:{url}", f"unusable DID document: {exc}"

    return None, None, "no jku or did:web reference in the signature header"


def _key_strength_problem(header: dict, key_set: KeySet | None) -> str | None:
    alg = header.get("alg")
    if not isinstance(alg, str) or alg in _FORBIDDEN_ALGS:
        return f"algorithm {alg!r}"
    if key_set is None:
        return None
    for key in key_set.keys:
        if key.key_type == "RSA":
            n = key.dict_value.get("n")
            if isinstance(n, str) and len(_b64url_decode(n)) * 8 < _MIN_RSA_BITS:
                return f"RSA key shorter than {_MIN_RSA_BITS} bits"
    return None


async def probe_signed(
    fetcher: Fetcher, card_url: str, fetched: FetchResult
) -> tuple[list[CheckResult], SignedEvidence]:
    """Run the signed-document checks against one fetched Agent Card."""
    ev = SignedEvidence(document_url=card_url)
    checks: list[CheckResult] = []

    def add(check_id: CheckId, outcome: Outcome, strength: NormativeStrength, **kw) -> None:
        checks.append(
            CheckResult(check_id=check_id, outcome=outcome, normative_strength=strength, **kw)
        )

    if fetched.error_kind is ErrorKind.BLOCKED:
        for cid in (CheckId.IDENTITY_METADATA_PUBLISHED, CheckId.CARD_SIGNED,
                    CheckId.KEY_RESOLVABLE, CheckId.SIGNATURE_VERIFIES, CheckId.KEY_STRENGTH):
            add(cid, Outcome.ERROR, NormativeStrength.MUST, detail="access block (R4)")
        return checks, ev

    # C01 - publishing a card is only SHOULD, so absence is never a failure.
    document: Any = None
    if fetched.status == 200:
        try:
            document = json.loads(fetched.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            document = None

    if not isinstance(document, dict):
        add(CheckId.IDENTITY_METADATA_PUBLISHED, Outcome.UNSPECIFIED, NormativeStrength.SHOULD,
            spec_ref="A2A agent discovery: the standard path is /.well-known/agent-card.json",
            spec_url=SPEC_A2A_DISCOVERY,
            detail=f"no usable card (HTTP {fetched.status})")
        for cid in (CheckId.CARD_SIGNED, CheckId.KEY_RESOLVABLE,
                    CheckId.SIGNATURE_VERIFIES, CheckId.KEY_STRENGTH):
            add(cid, Outcome.NOT_APPLICABLE, NormativeStrength.MUST, detail="no card")
        return checks, ev

    ev.document = document
    add(CheckId.IDENTITY_METADATA_PUBLISHED, Outcome.PASS, NormativeStrength.SHOULD,
        spec_ref="A2A agent discovery", spec_url=SPEC_A2A_DISCOVERY,
        evidence_sha256=fetched.body_sha256)

    # C02 - descriptive only: `signatures` is OPTIONAL for the publisher.
    raw_signatures = document.get("signatures")
    ev.signatures = [s for s in raw_signatures if isinstance(s, dict)] \
        if isinstance(raw_signatures, list) else []

    add(CheckId.CARD_SIGNED,
        Outcome.PASS if ev.signatures else Outcome.UNSPECIFIED,
        NormativeStrength.MAY,
        spec_ref="A2A 4.4.7: `signatures` is OPTIONAL; verifiers SHOULD verify one",
        spec_url=SPEC_A2A,
        observed_value=f"{len(ev.signatures)} signature(s)")

    if not ev.signatures:
        for cid in (CheckId.KEY_RESOLVABLE, CheckId.SIGNATURE_VERIFIES, CheckId.KEY_STRENGTH):
            add(cid, Outcome.NOT_APPLICABLE, NormativeStrength.MUST,
                detail="card carries no signature")
        return checks, ev

    # The payload is fixed across signatures; ambiguity here is an R6 case.
    try:
        payload = signing_payload(document)
    except AmbiguousNumberError as exc:
        ev.canonicalization_note = str(exc)
        for cid in (CheckId.KEY_RESOLVABLE, CheckId.SIGNATURE_VERIFIES):
            add(cid, Outcome.UNSPECIFIED, NormativeStrength.MUST,
                spec_ref="RFC 8785 number formatting", spec_url=SPEC_RFC8785,
                detail=f"canonicalization ambiguous (R6): {exc}")
        add(CheckId.KEY_STRENGTH, Outcome.NOT_APPLICABLE, NormativeStrength.MUST)
        return checks, ev
    except JcsError as exc:
        ev.canonicalization_note = str(exc)
        add(CheckId.KEY_RESOLVABLE, Outcome.FAIL_MISIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="RFC 8785", spec_url=SPEC_RFC8785,
            detail=f"card is not canonicalizable JSON: {exc}")
        for cid in (CheckId.SIGNATURE_VERIFIES, CheckId.KEY_STRENGTH):
            add(cid, Outcome.NOT_APPLICABLE, NormativeStrength.MUST)
        return checks, ev

    payload_b64 = _b64url(payload)
    resolved_any = False
    verified_any = False
    key_errors: list[str] = []
    strength_problems: list[str] = []

    for sig in ev.signatures:
        header = _decode_protected(sig)
        if header is None:
            key_errors.append("undecodable protected header")
            continue
        ev.protected_headers.append(header)
        if isinstance(header.get("alg"), str):
            ev.algs.append(header["alg"])

        key_set, source, error = await _resolve_keys(fetcher, header, document)
        if source:
            ev.key_sources.append(source)
        if key_set is None:
            key_errors.append(error or "unknown key resolution failure")
            continue
        resolved_any = True

        problem = _key_strength_problem(header, key_set)
        if problem:
            # A signature that "verifies" under `none`, under a symmetric algorithm whose
            # key the operator publishes, or under an undersized RSA key is not evidence
            # of anything: anyone holding the public material can produce it. Counting it
            # as a cryptographic binding would inflate the paper's headline number, so it
            # is never attempted rather than attempted and passed.
            strength_problems.append(problem)
            continue

        compact = f"{sig.get('protected')}.{payload_b64}.{sig.get('signature', '')}"
        try:
            jws.deserialize_compact(compact, key_set, registry=_VERIFY_REGISTRY)
            verified_any = True
            ev.verified_count += 1
        except Exception:  # noqa: BLE001 - a bad signature is data, not a crash
            continue

    # C03
    if resolved_any:
        add(CheckId.KEY_RESOLVABLE, Outcome.PASS, NormativeStrength.MUST,
            spec_ref="A2A 8.4 key discovery", spec_url=SPEC_A2A,
            observed_value="; ".join(ev.key_sources))
    elif any(e == "blocked" for e in key_errors):
        add(CheckId.KEY_RESOLVABLE, Outcome.ERROR, NormativeStrength.MUST,
            detail="key location blocked (R4)")
    else:
        add(CheckId.KEY_RESOLVABLE, Outcome.FAIL_UNIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="A2A 8.4: a signed card MUST be verifiable against a discoverable key",
            spec_url=SPEC_A2A, observed_value="; ".join(key_errors))

    # C04 - the headline. A signature that does not verify is a MUST violation of
    # RFC 7515; a signature we could not reach a key for is not the operator's verdict.
    if verified_any:
        add(CheckId.SIGNATURE_VERIFIES, Outcome.PASS, NormativeStrength.MUST,
            spec_ref="RFC 7515 + A2A 8.4 (JCS payload)", spec_url=SPEC_RFC7515,
            observed_value=f"{ev.verified_count}/{len(ev.signatures)} verified")
    elif not resolved_any:
        add(CheckId.SIGNATURE_VERIFIES, Outcome.NOT_APPLICABLE, NormativeStrength.MUST,
            detail="no key could be resolved, so the signature cannot be judged")
    else:
        add(CheckId.SIGNATURE_VERIFIES, Outcome.FAIL_MISIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="RFC 7515", spec_url=SPEC_RFC7515,
            detail="key resolved but no signature verified over the JCS payload")

    # C15
    if strength_problems:
        add(CheckId.KEY_STRENGTH, Outcome.FAIL_MISIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="RFC 7518 / BCP 195", spec_url=SPEC_RFC7515,
            observed_value="; ".join(strength_problems))
    elif resolved_any:
        add(CheckId.KEY_STRENGTH, Outcome.PASS, NormativeStrength.MUST,
            spec_ref="RFC 7518 / BCP 195", spec_url=SPEC_RFC7515,
            observed_value=",".join(ev.algs))
    else:
        add(CheckId.KEY_STRENGTH, Outcome.NOT_APPLICABLE, NormativeStrength.MUST,
            detail="no key resolved")

    return checks, ev
