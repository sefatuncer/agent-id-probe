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
# C04 is the only check here whose MUST comes from a specific clause rather than the document
# as a whole, so it deep-links: 5.2 "Message Signature or MAC Validation" is where "at least
# one JWS Signature value MUST successfully validate, or the JWS MUST be considered invalid"
# lives, and every stored C04 verdict carries the URL a reviewer will follow.
SPEC_RFC7515_VALIDATION = "https://www.rfc-editor.org/rfc/rfc7515.html#section-5.2"
# C15's two halves point at two different sections, and the split is the point: 3.3 carries a
# MUST on the signer, 3.6 carries MUSTs on the verifier. Citing RFC 7515 (and BCP 195, a TLS
# document) for both was how the difference stayed invisible.
SPEC_RFC7518_RSA = "https://www.rfc-editor.org/rfc/rfc7518.html#section-3.3"
SPEC_RFC7518_NONE = "https://www.rfc-editor.org/rfc/rfc7518.html#section-3.6"
SPEC_RFC8785 = "https://www.rfc-editor.org/rfc/rfc8785.html"
SPEC_DIDWEB = "https://w3c-ccg.github.io/did-method-web/"

# RFC 7518 / BCP 195. `none` is unauthenticated by construction; a symmetric algorithm
# alongside a public key set means anyone holding the published key can forge.
# Algorithms under which a "successful" verification is evidence of nothing: `none` is
# unauthenticated by construction, and a symmetric MAC whose key the operator publishes can be
# produced by anyone who fetched the JWKS. Verification is therefore never *attempted* under
# them, which keeps C04 honest.
#
# Renamed from `_FORBIDDEN_ALGS` on 30 July 2026, because "forbidden" was the claim that did
# not survive reading the primary text: RFC 7518 §3.6's prohibitions bind the verifier, not the
# publisher, and the document that would bind the publisher (RFC 8725) is a BCP about JWTs
# while an agent-card signature is a detached JWS over a JCS payload. Not creditable is not the
# same as forbidden, and the name asserted the stronger one. See `_key_strength_problem`.
_UNVERIFIABLE_ALGS = {"none", "HS256", "HS384", "HS512"}
# RFC 7518 §3.3, verbatim: "A key of size 2048 bits or larger MUST be used with these
# algorithms." This is the one C15 condition with a publisher-binding MUST behind it.
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


# The strength of the specification sentence each check rests on, independent of which
# code path emits it. The access-block and no-card loops used to pass MUST for every check
# they touched, which recorded C01 at both SHOULD and MUST and C02 -- whose anchor is A2A's
# OPTIONAL `signatures` member, and which is DESCRIPTIVE_ONLY -- at both MAY and MUST. The
# verdicts on those paths are ERROR or NOT_APPLICABLE, so R1 never fired and nothing was
# mis-scored. But the generated check catalogue reads the strength that was actually
# recorded, so the published artefact claimed two anchors for checks that have one, and a
# later edit turning either loop into a FAIL_* would have been resting on a MUST that does
# not exist.
ANCHOR_STRENGTH: dict[CheckId, NormativeStrength] = {
    CheckId.IDENTITY_METADATA_PUBLISHED: NormativeStrength.SHOULD,  # A2A: location, not duty
    CheckId.CARD_SIGNED: NormativeStrength.MAY,                     # `signatures` is OPTIONAL
    CheckId.KEY_RESOLVABLE: NormativeStrength.MUST,                 # RFC 7515, if signed
    CheckId.SIGNATURE_VERIFIES: NormativeStrength.MUST,             # RFC 7515, if signed
    CheckId.KEY_STRENGTH: NormativeStrength.MUST,                   # RFC 7518 / BCP 195
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


def _key_strength_problem(header: dict, key_set: KeySet | None) -> tuple[str | None, str | None]:
    """Return `(violation, observation)` — the two halves of C15, which are not the same thing.

    Decision rule R9.7 / the C15 split of 30 July 2026. C15 rested on "RFC 7518 / BCP 195" for
    three conditions, and reading the primary text showed the citation supported one of them:

    **RSA below 2048 bits is a genuine, publisher-binding MUST.** RFC 7518 §3.3: *"A key of
    size 2048 bits or larger MUST be used with these algorithms."* It binds whoever signs, it
    is mechanically observable from the published JWKS, and a failure here is a real finding.
    This is the `violation` half.

    **`none` is not.** RFC 7518 §3.6's obligations bind the **verifier**: *"Implementations
    that support unsecured JWSs MUST NOT accept them as valid unless the application
    specifies that it is acceptable."* Nothing there forbids a *publisher* from emitting one.
    Scoring the publisher for it is precisely the error C14 was demoted for and C16 was made
    descriptive to avoid -- reading an obligation on the consuming party as a defect in the
    party we can observe.

    **`HS*` against a published JWKS is not either.** §3.2 sets a minimum HMAC key *size* and
    says nothing about publishing the key. The document that would forbid this is RFC 8725,
    and it does not reach: RFC 8725 is a BCP about **JWTs**, and an A2A agent-card signature is
    a detached JWS over a JCS-canonicalised card -- no claims set, not a JWT. That distinction
    is the whole answer to whether 8725 can be borrowed here, and it cannot.

    **BCP 195 was simply the wrong document.** It is about TLS and has nothing to say about JWS
    algorithm selection. It appeared in every C15 verdict's `spec_ref`.

    So `none` and `HS*` are still detected, still recorded, and no longer convict anybody:
    they come back as `observation` and C15 reports UNSPECIFIED. The security reasoning that
    put them here is untouched and remains the reason verification is never *attempted* under
    them -- a signature that "verifies" under `none` or under a key the operator publishes is
    evidence of nothing, and counting it would inflate C04. Refusing to score it and refusing
    to credit it are separate decisions, and only the second one needed a MUST.
    """
    alg = header.get("alg")
    observation: str | None = None
    if not isinstance(alg, str) or alg in _UNVERIFIABLE_ALGS:
        observation = f"algorithm {alg!r} carries no verifiable binding"
    if key_set is not None:
        for key in key_set.keys:
            if key.key_type == "RSA":
                n = key.dict_value.get("n")
                if isinstance(n, str) and len(_b64url_decode(n)) * 8 < _MIN_RSA_BITS:
                    return f"RSA key shorter than {_MIN_RSA_BITS} bits", observation
    return None, observation


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
            add(cid, Outcome.ERROR, ANCHOR_STRENGTH[cid], detail="access block (R4)")
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
            add(cid, Outcome.NOT_APPLICABLE, ANCHOR_STRENGTH[cid], detail="no card")
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
    strength_violations: list[str] = []
    strength_observations: list[str] = []
    # Signatures we declined to attempt, and signatures we attempted and that failed. C04's
    # verdict depends on which of the two happened, and conflating them made it assert
    # something false about the artefact.
    skipped_not_creditable: list[str] = []
    attempted_and_failed = 0

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

        violation, observation = _key_strength_problem(header, key_set)
        if violation:
            strength_violations.append(violation)
        if observation:
            strength_observations.append(observation)
        if violation or observation:
            # A signature that "verifies" under `none`, under a symmetric algorithm whose
            # key the operator publishes, or under an undersized RSA key is not evidence
            # of anything: anyone holding the public material can produce it. Counting it
            # as a cryptographic binding would inflate the paper's headline number, so it
            # is never attempted rather than attempted and passed. That decision is about
            # what C04 may credit and is unchanged by the C15 split -- declining to credit a
            # signature and convicting its publisher are different acts, and only the second
            # one needs a MUST.
            #
            # It is recorded, though, because C04 must not then report that the signature
            # failed to verify. It did not fail; we declined to try. Until 30 July 2026 this
            # branch fell through to `FAIL_MISIMPLEMENTED` with the detail "key resolved but
            # no signature verified over the JCS payload" -- a MUST-level accusation whose
            # own detail string was false, and demonstrably so for an undersized RSA key,
            # where the signature verifies perfectly well and the defect is the key length.
            # R6: what we chose not to observe is UNSPECIFIED.
            skipped_not_creditable.append(violation or observation or "")
            continue

        compact = f"{sig.get('protected')}.{payload_b64}.{sig.get('signature', '')}"
        try:
            jws.deserialize_compact(compact, key_set, registry=_VERIFY_REGISTRY)
            verified_any = True
            ev.verified_count += 1
        except Exception:  # noqa: BLE001 - a bad signature is data, not a crash
            attempted_and_failed += 1
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
    #
    # The section is 5.2, "Message Signature or MAC Validation", and until 30 July 2026 the
    # emission sites cited RFC 7515 with no section at all while the paper's Table 1 asserted
    # "RFC 7515 5.2" by hand. The label was right and the code was vague, which is the same
    # defect as the reverse: nothing tied the reference a reviewer follows to the reference the
    # data carries. 5.2 is the clause that makes this check failable at MUST -- "in all cases,
    # at least one JWS Signature value MUST successfully validate, or the JWS MUST be
    # considered invalid" -- so it is the one both must name.
    if verified_any:
        add(CheckId.SIGNATURE_VERIFIES, Outcome.PASS, NormativeStrength.MUST,
            spec_ref="RFC 7515 5.2 + A2A 8.4 (JCS payload)",
            spec_url=SPEC_RFC7515_VALIDATION,
            observed_value=f"{ev.verified_count}/{len(ev.signatures)} verified")
    elif not resolved_any:
        add(CheckId.SIGNATURE_VERIFIES, Outcome.NOT_APPLICABLE, NormativeStrength.MUST,
            detail="no key could be resolved, so the signature cannot be judged")
    elif not attempted_and_failed and skipped_not_creditable:
        # Every signature on this card was skipped rather than tested, so there is no
        # observation of a verification failure to report (R6).
        add(CheckId.SIGNATURE_VERIFIES, Outcome.UNSPECIFIED, NormativeStrength.MUST,
            spec_ref="RFC 7515 5.2; verification not attempted, so no failure was observed",
            spec_url=SPEC_RFC7515_VALIDATION,
            observed_value="; ".join(skipped_not_creditable),
            detail="verification was not attempted: the signing material is not creditable "
                   "as a cryptographic binding, which is our decision about what may count "
                   "and not an observation about whether the signature is well formed")
    else:
        add(CheckId.SIGNATURE_VERIFIES, Outcome.FAIL_MISIMPLEMENTED, NormativeStrength.MUST,
            # A2A 8.4 is the publisher-binding half and belongs here rather than only on the
            # PASS branch: RFC 7515 5.2's MUSTs tell a *verifier* to reject an invalid JWS,
            # and the objection that demoted two thirds of C15 would apply to this branch
            # too if the only citation were 5.2. A2A binds whoever published the card.
            spec_ref="A2A 8.4: a signed card MUST be verifiable against a discoverable key; "
                     "RFC 7515 5.2: at least one JWS Signature value MUST successfully "
                     "validate, or the JWS MUST be considered invalid",
            spec_url=SPEC_RFC7515_VALIDATION,
            observed_value=f"{attempted_and_failed} of {len(ev.signatures)} signature(s) "
                           f"tested and none verified",
            detail="key resolved but no signature verified over the JCS payload")

    # C15. Two conditions, two verdicts, because only one of them has a MUST behind it that
    # binds the party we can observe (R9.7; the reasoning is in `_key_strength_problem`).
    if strength_violations:
        add(CheckId.KEY_STRENGTH, Outcome.FAIL_MISIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="RFC 7518 3.3: a key of size 2048 bits or larger MUST be used with "
                     "these algorithms",
            spec_url=SPEC_RFC7518_RSA,
            observed_value="; ".join(strength_violations + strength_observations))
    elif strength_observations:
        # Recorded, never charged. RFC 7518 3.6 binds the verifier and RFC 8725 governs JWTs,
        # so an agent card published with `none` or with a symmetric algorithm violates no
        # sentence we can hold its publisher to -- and this is a striking descriptive finding
        # in its own right, which is why it is reported rather than dropped.
        add(CheckId.KEY_STRENGTH, Outcome.UNSPECIFIED, NormativeStrength.MUST,
            spec_ref="RFC 7518 3.6 binds the verifier, not the publisher, and RFC 8725's "
                     "prohibitions govern JWTs rather than a detached JWS; recorded without "
                     "penalty (R1, R6, R9.7)",
            spec_url=SPEC_RFC7518_NONE,
            observed_value="; ".join(strength_observations))
    elif resolved_any:
        add(CheckId.KEY_STRENGTH, Outcome.PASS, NormativeStrength.MUST,
            spec_ref="RFC 7518 3.3: a key of size 2048 bits or larger MUST be used with "
                     "these algorithms",
            spec_url=SPEC_RFC7518_RSA,
            observed_value=",".join(ev.algs))
    else:
        add(CheckId.KEY_STRENGTH, Outcome.NOT_APPLICABLE, NormativeStrength.MUST,
            detail="no key resolved")

    return checks, ev
