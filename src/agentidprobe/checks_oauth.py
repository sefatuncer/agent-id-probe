"""OAuth-modality checks (MCP authorization metadata).

This module carries the study's decisive measurement. Prior work has established how
many MCP servers require authentication at all; nobody has asked whether the trust
relationships those servers *declare* are internally consistent. RFC 9728 §3.3 settles
the question at MUST level:

    "The `resource` value returned MUST be identical to the protected resource's
     resource identifier ... If these values are not identical, the data contained in
     the response MUST NOT be used."

So an endpoint whose protected-resource metadata names a different resource is not a
matter of opinion: it is publishing metadata that a conforming client must discard.
C12 measures exactly that, and C13 does the same for the declared issuer against
RFC 8414 §3.3.

Every verdict here carries the normative strength of the sentence it rests on, so
decision rule R1 (enforced in models.py) prevents this module from penalising anything
the specifications merely recommend.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from .config import as_metadata_candidate_urls, prm_candidate_urls
from .fetcher import ErrorKind, Fetcher, FetchResult
from .models import CheckId, CheckResult, NormativeStrength, Outcome

SPEC_MCP = "https://modelcontextprotocol.io/specification/latest/basic/authorization"
SPEC_RFC9728 = "https://www.rfc-editor.org/rfc/rfc9728.html"
SPEC_RFC8414 = "https://www.rfc-editor.org/rfc/rfc8414.html"

# Default ports are the only normalisation RFC 9728 tolerates; everything else must
# match byte for byte. Near-misses are recorded rather than forgiven, because "almost
# identical" is precisely the finding.
_DEFAULT_PORTS = {"https": "443", "http": "80"}


def canonical_resource_identifier(url: str) -> str:
    """The resource identifier a conforming server should echo back.

    Per RFC 8707 the identifier is an absolute URI without a fragment. We strip the
    fragment and any default port, and nothing else.
    """
    parts = urlsplit(url)
    netloc = parts.netloc
    if ":" in netloc:
        host, _, port = netloc.rpartition(":")
        if port == _DEFAULT_PORTS.get(parts.scheme):
            netloc = host
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))


def _relation(declared: str, expected: str) -> str:
    """Describe *how* a mismatch misses, so the paper can report a taxonomy rather
    than a single undifferentiated failure count."""
    if declared == expected:
        return "identical"
    if declared.rstrip("/") == expected.rstrip("/"):
        return "trailing_slash_only"
    if declared.lower() == expected.lower():
        return "case_only"
    if urlsplit(declared).netloc == urlsplit(expected).netloc:
        return "same_host_different_path"
    if urlsplit(declared).netloc.split(":")[0].endswith(
        "." + urlsplit(expected).netloc.split(":")[0]
    ) or urlsplit(expected).netloc.split(":")[0].endswith(
        "." + urlsplit(declared).netloc.split(":")[0]
    ):
        return "related_host"
    return "unrelated_host"


@dataclass
class OAuthEvidence:
    """What the checks observed, kept so results can be re-scored without re-fetching."""

    requires_authorization: bool = False
    www_authenticate: str | None = None
    prm_url: str | None = None
    prm_document: dict | None = None
    declared_resource: str | None = None
    expected_resource: str | None = None
    resource_relation: str | None = None
    authorization_servers: list[str] = field(default_factory=list)
    as_documents: dict[str, dict] = field(default_factory=dict)
    as_errors: dict[str, str] = field(default_factory=dict)


def _parse_json(result: FetchResult) -> dict | None:
    try:
        parsed = json.loads(result.body.decode("utf-8", errors="strict"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def probe_oauth(
    fetcher: Fetcher, resource_url: str, initial: FetchResult
) -> tuple[list[CheckResult], OAuthEvidence]:
    """Run the OAuth-modality checks against one MCP endpoint.

    `initial` is the response to the endpoint itself. Authorization is OPTIONAL in MCP,
    so unless the endpoint answered 401/403 none of these checks apply — reporting them
    as failures would count endpoints that never opted in, which is composition, not
    non-conformance.
    """
    ev = OAuthEvidence(expected_resource=canonical_resource_identifier(resource_url))
    checks: list[CheckResult] = []

    def add(check_id: CheckId, outcome: Outcome, strength: NormativeStrength, **kw) -> None:
        checks.append(
            CheckResult(
                check_id=check_id, outcome=outcome, normative_strength=strength, **kw
            )
        )

    # An access block tells us nothing about the origin (decision rule R4).
    if initial.error_kind is ErrorKind.BLOCKED:
        for cid in (CheckId.PRM_PRESENT, CheckId.PRM_RESOURCE_IDENTITY_MATCH,
                    CheckId.AS_CORRESPONDENCE, CheckId.PKCE_DECLARED):
            add(cid, Outcome.ERROR, NormativeStrength.MUST, detail="access block (R4)")
        return checks, ev

    ev.requires_authorization = initial.status in (401, 403)
    ev.www_authenticate = initial.headers.get("www-authenticate")

    if not ev.requires_authorization:
        for cid in (CheckId.PRM_PRESENT, CheckId.PRM_RESOURCE_IDENTITY_MATCH,
                    CheckId.AS_CORRESPONDENCE, CheckId.PKCE_DECLARED):
            add(cid, Outcome.NOT_APPLICABLE, NormativeStrength.MUST,
                detail="authorization is OPTIONAL in MCP and this endpoint did not require it",
                spec_ref="MCP Authorization", spec_url=SPEC_MCP)
        return checks, ev

    # C07 - discovery hint. Strength is SHOULD until the MCP clause is confirmed, so R1
    # keeps it incapable of producing a failure either way.
    add(
        CheckId.WWW_AUTH_RESOURCE_METADATA,
        Outcome.PASS if ev.www_authenticate and "resource_metadata" in ev.www_authenticate
        else Outcome.UNSPECIFIED,
        NormativeStrength.SHOULD,
        spec_ref="MCP Authorization, discovery",
        spec_url=SPEC_MCP,
        observed_value=ev.www_authenticate,
    )

    # C05 - protected-resource metadata. Both well-known forms are tried; probing only
    # the root form would manufacture failures for correctly configured servers.
    candidates = list(prm_candidate_urls(resource_url))
    if ev.www_authenticate and "resource_metadata=" in ev.www_authenticate:
        hinted = ev.www_authenticate.split("resource_metadata=", 1)[1].split(",")[0].strip(' "')
        if hinted.startswith("http"):
            candidates.insert(0, hinted)

    prm_doc: dict | None = None
    for candidate in candidates:
        result = await fetcher.fetch(candidate)
        if result.error_kind is ErrorKind.BLOCKED:
            add(CheckId.PRM_PRESENT, Outcome.ERROR, NormativeStrength.MUST,
                detail="access block (R4)", spec_url=SPEC_RFC9728)
            return checks, ev
        if result.status == 200:
            prm_doc = _parse_json(result)
            ev.prm_url = candidate
            if prm_doc is None:
                # R3: 200 with unparseable body is misimplementation, not absence.
                add(CheckId.PRM_PRESENT, Outcome.FAIL_MISIMPLEMENTED, NormativeStrength.MUST,
                    spec_ref="RFC 9728 3.2", spec_url=SPEC_RFC9728,
                    detail="200 response was not a JSON object",
                    evidence_sha256=result.body_sha256)
                return checks, ev
            break

    if prm_doc is None:
        add(CheckId.PRM_PRESENT, Outcome.FAIL_UNIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="MCP: servers MUST implement RFC 9728", spec_url=SPEC_MCP,
            detail=f"no metadata at {len(candidates)} candidate location(s)")
        return checks, ev

    ev.prm_document = prm_doc
    ev.authorization_servers = [s for s in prm_doc.get("authorization_servers", []) if
                                isinstance(s, str)]

    if not ev.authorization_servers:
        add(CheckId.PRM_PRESENT, Outcome.FAIL_MISIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="MCP: PRM MUST include authorization_servers with at least one entry",
            spec_url=SPEC_MCP, detail="authorization_servers absent or empty")
    else:
        add(CheckId.PRM_PRESENT, Outcome.PASS, NormativeStrength.MUST,
            spec_ref="RFC 9728 3.2", spec_url=SPEC_RFC9728,
            observed_value=ev.prm_url)

    # C12 - the decisive check.
    ev.declared_resource = prm_doc.get("resource") if isinstance(prm_doc.get("resource"), str) \
        else None
    if ev.declared_resource is None:
        add(CheckId.PRM_RESOURCE_IDENTITY_MATCH, Outcome.FAIL_UNIMPLEMENTED,
            NormativeStrength.MUST, spec_ref="RFC 9728 3.3", spec_url=SPEC_RFC9728,
            detail="required `resource` member absent")
    else:
        ev.resource_relation = _relation(ev.declared_resource, ev.expected_resource)
        add(
            CheckId.PRM_RESOURCE_IDENTITY_MATCH,
            Outcome.PASS if ev.resource_relation == "identical" else Outcome.FAIL_MISIMPLEMENTED,
            NormativeStrength.MUST,
            spec_ref="RFC 9728 3.3: the resource value returned MUST be identical",
            spec_url=SPEC_RFC9728,
            observed_value=f"{ev.declared_resource} ({ev.resource_relation})",
        )

    # C13 / C14 - does each declared issuer actually answer as that issuer?
    if not ev.authorization_servers:
        add(CheckId.AS_CORRESPONDENCE, Outcome.NOT_APPLICABLE, NormativeStrength.MUST,
            detail="no issuer declared")
        add(CheckId.PKCE_DECLARED, Outcome.NOT_APPLICABLE, NormativeStrength.MUST,
            detail="no issuer declared")
        return checks, ev

    mismatches: list[str] = []
    unreachable: list[str] = []
    pkce_seen = False

    for issuer in ev.authorization_servers:
        doc = None
        for candidate in as_metadata_candidate_urls(issuer):
            result = await fetcher.fetch(candidate)
            if result.status == 200:
                doc = _parse_json(result)
                if doc is not None:
                    break
        if doc is None:
            unreachable.append(issuer)
            ev.as_errors[issuer] = "metadata not retrievable at any well-known location"
            continue
        ev.as_documents[issuer] = doc
        returned = doc.get("issuer")
        if not isinstance(returned, str) or returned.rstrip("/") != issuer.rstrip("/"):
            mismatches.append(f"{issuer} -> {returned!r}")
        if doc.get("code_challenge_methods_supported"):
            pkce_seen = True

    if mismatches:
        add(CheckId.AS_CORRESPONDENCE, Outcome.FAIL_MISIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="RFC 8414 3.3: issuer value MUST be identical to the issuer requested",
            spec_url=SPEC_RFC8414, observed_value="; ".join(mismatches))
    elif unreachable and len(unreachable) == len(ev.authorization_servers):
        add(CheckId.AS_CORRESPONDENCE, Outcome.FAIL_UNIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="RFC 8414 3", spec_url=SPEC_RFC8414,
            observed_value="; ".join(unreachable),
            detail="every declared issuer failed to serve metadata")
    else:
        add(CheckId.AS_CORRESPONDENCE, Outcome.PASS, NormativeStrength.MUST,
            spec_ref="RFC 8414 3.3", spec_url=SPEC_RFC8414)

    if ev.as_documents:
        add(
            CheckId.PKCE_DECLARED,
            Outcome.PASS if pkce_seen else Outcome.FAIL_UNIMPLEMENTED,
            NormativeStrength.MUST,
            spec_ref="MCP: absent code_challenge_methods_supported means clients MUST refuse",
            spec_url=SPEC_MCP,
        )
    else:
        add(CheckId.PKCE_DECLARED, Outcome.ERROR, NormativeStrength.MUST,
            detail="no authorization server metadata retrievable")

    return checks, ev
