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

import hashlib
import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from .config import as_metadata_candidate_urls, prm_candidate_urls
from .fetcher import ErrorKind, Fetcher, FetchResult
from .jcs import canonicalize
from .models import CheckId, CheckResult, NormativeStrength, Outcome

# Pinned to a dated revision, not `/latest/`. Decision rule R7 freezes the revision set
# precisely so a specification published on the day of the run cannot be swallowed
# silently -- and that is no longer hypothetical: `/latest/` resolves to revision
# 2026-07-28, which is outside the frozen set and which moved the authorization
# text onto sub-pages, so several sentences cited below are not on that page at all.
# Every stored verdict records this URL, so an unpinned anchor means a reviewer
# following the link from the data finds a document that does not contain the quote.
SPEC_MCP = "https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization"
SPEC_MCP_2025_11_25 = (
    "https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization"
)
SPEC_RFC9700 = "https://www.rfc-editor.org/rfc/rfc9700.html"
SPEC_RFC9728 = "https://www.rfc-editor.org/rfc/rfc9728.html"
SPEC_RFC8414 = "https://www.rfc-editor.org/rfc/rfc8414.html"

# Default ports are the only normalisation RFC 9728 tolerates; everything else must
# match byte for byte. Near-misses are recorded rather than forgiven, because "almost
# identical" is precisely the finding.
_DEFAULT_PORTS = {"https": "443", "http": "80"}


WELL_KNOWN_PRM = "/.well-known/oauth-protected-resource"

# Decision rule R9.3. Relations routed to UNSPECIFIED by R6 -- "our uncertainty is
# UNSPECIFIED" -- rather than scored against the operator.
#
# `trailing_slash_only` is here for C12 and *not* for C13, and the asymmetry is forced by
# the specifications rather than chosen. RFC 9728 3.1 removes any terminating slash before
# inserting the well-known suffix, so `https://h/mcp` and `https://h/mcp/` are served from
# the *same* metadata URL. Recovering the identifier from that URL therefore yields a
# two-element set, not a value: a server whose identifier really is `/mcp/` conforms
# perfectly by echoing `/mcp/`, and one whose identifier is `/mcp` violates 3.3 by doing
# the same. The instrument cannot separate them, so it must not penalise either.
# C13 has no such problem: the issuer string is read literally out of the resource's own
# `authorization_servers` array, so RFC 8414 3.3 has an observed left-hand side and a
# slash difference is a real, mechanically detectable MUST violation.
_R6_UNSPECIFIED_C12 = frozenset({"trailing_slash_only"})

# The OAuth checks that can still convict somebody, and therefore the ones the shared
# ERROR / NOT_APPLICABLE paths may emit at MUST. C14 left this set on 29 July 2026 when it
# became descriptive; it is emitted alongside at SHOULD rather than inside the loop,
# because the strength recorded on an inert path is still the strength the paper's Table 1
# reports for the check.
_MUST_STAGES = (CheckId.PRM_PRESENT, CheckId.PRM_RESOURCE_IDENTITY_MATCH,
                CheckId.AS_CORRESPONDENCE)


def canonical_resource_identifier(url: str) -> str:
    """The resource identifier a conforming server should echo back.

    Per RFC 8707 the identifier is an absolute URI without a fragment. We strip the
    fragment and any default port, and nothing else.

    Decision rule R9.2 requires this to be applied to *both* sides of every comparison.
    Applying it only to the expected side dropped a conforming server that reflected its
    resource back with an explicit `:443` into the heaviest bucket of the taxonomy.
    """
    parts = urlsplit(url)
    netloc = parts.netloc
    if ":" in netloc:
        host, _, port = netloc.rpartition(":")
        if port == _DEFAULT_PORTS.get(parts.scheme):
            netloc = host
    # RFC 3986 6.2.2.1: the scheme and host are case-insensitive; every other component
    # is case-sensitive unless the scheme says otherwise. Lowercasing the whole URI would
    # forgive `/MCP` vs `/mcp`, which really are different paths.
    scheme = parts.scheme.lower()
    netloc = netloc.lower()
    # RFC 3986 6.2.3 lists `http://example.com` and `http://example.com/` among four URIs
    # it declares equivalent, so an empty path and a bare "/" are the same resource.
    path = "" if parts.path == "/" else parts.path
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def identifier_from_metadata_url(doc_url: str) -> str | None:
    """The resource identifier implied by the URL the metadata was actually served from.

    RFC 9728 3.3 does not compare against the endpoint URL we started with. It compares
    against "the protected resource's resource identifier value into which the well-known
    URI path suffix was inserted to create the URL used to retrieve the metadata" — so the
    expected value depends on *which* candidate location answered, and is recovered by
    removing the well-known prefix again.

    The reversal is *not* exact. RFC 9728 3.1 removes any terminating slash before
    inserting the suffix, and that step is lossy: `https://h/mcp` and `https://h/mcp/` are
    both served from `.../oauth-protected-resource/mcp`. What this function returns is one
    of the two identifiers consistent with the URL, so a trailing-slash difference against
    it is uncertainty on our side rather than a violation on theirs (R9.3, R6).

    Returns None when the URL is not in well-known form (the WWW-Authenticate hint may
    point anywhere); R9.1 then applies the request-URL rule of RFC 9728 3.3 paragraph 2.
    """
    parts = urlsplit(doc_url)
    if not parts.path.startswith(WELL_KNOWN_PRM):
        return None
    remainder = parts.path[len(WELL_KNOWN_PRM):]
    return urlunsplit((parts.scheme, parts.netloc, remainder, "", ""))


def _relation(declared: str, expected: str) -> str:
    """Describe *how* a mismatch misses, so the paper can report a taxonomy rather
    than a single undifferentiated failure count.

    Both sides are canonicalised first (R9.2). `unrelated_host` is a named category, not a
    fall-through: the paper's rhetorical punch — two unrelated resources naming the same
    issuer — must not be produced by an `else` branch that also swallows port and scheme
    differences.
    """
    declared = canonical_resource_identifier(declared)
    expected = canonical_resource_identifier(expected)

    if declared == expected:
        return "identical"
    if declared.rstrip("/") == expected.rstrip("/"):
        return "trailing_slash_only"
    # Scheme and host case is already normalised away above (RFC 3986 6.2.2.1), so what
    # reaches here is a case difference in the path or query -- components the same
    # section declares case-sensitive. That is a genuine mismatch, not a near-miss.
    if declared.lower() == expected.lower():
        return "case_path_only"

    d, e = urlsplit(declared), urlsplit(expected)
    d_host, e_host = d.netloc.split(":")[0], e.netloc.split(":")[0]

    # Same host: name the most severe component that differs, most severe first.
    if d_host == e_host:
        if d.scheme != e.scheme:
            return "scheme_only"
        if d.netloc != e.netloc:      # default ports already normalised away (R9.2)
            return "port_only"
        return "same_host_different_path"
    if d_host.endswith("." + e_host) or e_host.endswith("." + d_host):
        return "related_host"
    return "unrelated_host"


def _identity_outcome(relation: str, *, expectation_is_observed: bool) -> Outcome:
    """R9.3: map a relation to a verdict, in one table in one place.

    `expectation_is_observed` says whether the value the declaration is compared against
    was read directly (C13: the issuer string in `authorization_servers`) or reconstructed
    from the location the document was served from (C12). Only the reconstruction is
    ambiguous, and only there does a trailing-slash difference stop being evidence.
    """
    if relation == "identical":
        return Outcome.PASS
    if not expectation_is_observed and relation in _R6_UNSPECIFIED_C12:
        return Outcome.UNSPECIFIED
    return Outcome.FAIL_MISIMPLEMENTED


@dataclass
class OAuthEvidence:
    """What the checks observed, kept so results can be re-scored without re-fetching."""

    requires_authorization: bool = False
    www_authenticate: str | None = None
    prm_url: str | None = None
    prm_from_hint: bool = False
    hinted_url_declared: str | None = None
    hint_rejected_reason: str | None = None
    prm_scope_covers_endpoint: bool | None = None
    prm_document: dict | None = None
    declared_resource: str | None = None
    expected_resource: str | None = None
    resource_relation: str | None = None
    authorization_servers: list[str] = field(default_factory=list)
    malformed_authorization_servers: list = field(default_factory=list)
    as_documents: dict[str, dict] = field(default_factory=dict)
    as_errors: dict[str, str] = field(default_factory=dict)
    as_issuer_relations: dict[str, str] = field(default_factory=dict)
    robots_excluded_urls: list[str] = field(default_factory=list)

    def as_record(self, server_header: str | None = None) -> dict:
        """A JSON-serialisable snapshot, so a run can be re-scored and the
        resource -> issuer graph can be built without touching the network again."""
        first_as = next(iter(self.as_documents.values()), None)
        fingerprints = (
            {
                "implementation_fingerprint": implementation_fingerprint(
                    self.prm_document, first_as, server_header),
                "implementation_fingerprint_no_server": implementation_fingerprint(
                    self.prm_document, first_as, server_header, include_server=False),
            }
            if self.prm_document is not None
            else {"implementation_fingerprint": None,
                  "implementation_fingerprint_no_server": None}
        )
        return {
            **fingerprints,
            "requires_authorization": self.requires_authorization,
            "www_authenticate": self.www_authenticate,
            "prm_url": self.prm_url,
            "prm_from_hint": self.prm_from_hint,
            "hinted_url_declared": self.hinted_url_declared,
            "hint_rejected_reason": self.hint_rejected_reason,
            "prm_scope_covers_endpoint": self.prm_scope_covers_endpoint,
            "prm_document": self.prm_document,
            "declared_resource": self.declared_resource,
            "expected_resource": self.expected_resource,
            "resource_relation": self.resource_relation,
            "authorization_servers": list(self.authorization_servers),
            "malformed_authorization_servers": [
                repr(s) for s in self.malformed_authorization_servers
            ],
            "as_documents": self.as_documents,
            "as_errors": self.as_errors,
            "as_issuer_relations": self.as_issuer_relations,
            "robots_excluded_urls": list(self.robots_excluded_urls),
        }


def _json_shape(value: object) -> str:
    """A type description that contains no values.

    Two properties matter and each was got wrong once. Objects recurse, because
    `{"deep": {"nested": [1,2,3]}}` and `{"totally": "different"}` both reducing to
    "object" made unrelated implementations collide into one cluster. Arrays do *not*
    describe their elements, because `[]` and `["read"]` are the same member with
    different contents, and letting the contents change the shape split one SDK into two
    clusters -- a value leaking into a key that is supposed to be value-free.
    """
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        inner = ",".join(f"{k}:{_json_shape(v)}" for k, v in sorted(value.items()))
        return f"object<{inner}>"
    if isinstance(value, list):
        return "array"
    return "null"


def _server_family(server_header: str | None) -> str:
    """The product name from a `Server` header, without its version.

    `nginx/1.24.0` and `nginx/1.25.3` are the same implementation, and treating them as
    different clusters repeats exactly the mistake that sank the first fingerprint design:
    keying on something that varies with deployment rather than with the code.
    """
    if not server_header:
        return ""
    return server_header.strip().lower().split("/")[0].split(" ")[0]


def implementation_fingerprint(
    prm_document: dict | None,
    as_document: dict | None,
    server_header: str | None,
    *,
    include_server: bool = True,
) -> str:
    """Decision rule R10.2b: a cluster key that contains no values.

    Endpoints are not independent -- they run on a handful of SDKs and platforms -- and a
    rate reported as though they were overstates its own precision. Grouping them needs a
    key, and the obvious one, hashing the document, fails twice over: it is a property of
    whichever serialiser and proxy happened to be in the path rather than of the code that
    produced it, and stripping the host-specific values back out again requires a
    hand-written list of which fields those are, which is exactly the author-supplied rubric
    the whole instrument is built to avoid.

    Member names and their JSON types survive re-serialisation and still separate one SDK
    from another, and no value ever enters the hash, so no list is needed. The `server`
    header is the single hand-made choice here, which is why R10.2b reports the clustering
    both with and without it.
    """
    payload = {
        "prm_keys": sorted(prm_document or {}),
        "prm_types": [_json_shape((prm_document or {})[k]) for k in sorted(prm_document or {})],
        "as_keys": sorted(as_document or {}),
        "server": _server_family(server_header) if include_server else "",
    }
    return hashlib.sha256(canonicalize(payload)).hexdigest()


def _hint_rejection_reason(hinted: str, resource_url: str) -> str | None:
    """Why a `WWW-Authenticate: resource_metadata` value was not followed, or None."""
    from .collectors import apex_domain

    parts = urlsplit(hinted)
    if parts.scheme != "https":
        return f"scheme is {parts.scheme!r}, not https"
    host = parts.netloc.split(":")[0].lower()
    if not host:
        return "no host"
    hint_apex, resource_apex = apex_domain(hinted), apex_domain(resource_url)
    if hint_apex is None:
        # Covers loopback, RFC 1918 literals, special-use TLDs and bare IPs, none of which
        # have a registrable domain to compare against.
        return f"host {host!r} has no registrable domain"
    if hint_apex != resource_apex:
        return f"points at {hint_apex!r}, not the resource's own {resource_apex!r}"
    return None


def _hint_is_followable(hinted: str, resource_url: str) -> bool:
    """A discovery hint is followed only when it stays with the operator being measured.

    RFC 9728 5.1 lets a resource name its metadata location, and MCP requires clients to
    use it. A client has a relationship with that server and can accept the redirection; a
    measurement study has neither, and its scope statement is a promise to third parties
    about what it will request. So the hint is honoured within the resource's own
    registrable domain and recorded but not followed outside it.
    """
    return _hint_rejection_reason(hinted, resource_url) is None


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
    # expected_resource is deliberately not set here: under R9.1 it depends on which
    # candidate location actually served the document, which is not known until it is.
    ev = OAuthEvidence()
    checks: list[CheckResult] = []

    def add(check_id: CheckId, outcome: Outcome, strength: NormativeStrength, **kw) -> None:
        checks.append(
            CheckResult(
                check_id=check_id, outcome=outcome, normative_strength=strength, **kw
            )
        )

    # An access block tells us nothing about the origin (decision rule R4).
    if initial.error_kind is ErrorKind.BLOCKED:
        for cid in _MUST_STAGES:
            add(cid, Outcome.ERROR, NormativeStrength.MUST, detail="access block (R4)")
        add(CheckId.PKCE_DECLARED, Outcome.ERROR, NormativeStrength.SHOULD,
            detail="access block (R4)")
        return checks, ev

    ev.requires_authorization = initial.status in (401, 403)
    ev.www_authenticate = initial.headers.get("www-authenticate")

    # C11 - TLS. Emitted for every reachable endpoint rather than only for authorizing
    # ones: MCP requires HTTPS unconditionally, so unlike the OAuth checks this one does
    # not depend on the endpoint having opted into authorization. The data is collected on
    # every fetch already and was simply never scored.
    #
    # What this check can and cannot conclude, stated plainly because the difference is
    # easy to miss and easy to overclaim. A PASS means the handshake completed under
    # standard verification -- httpx validates the chain and the hostname, so reaching
    # this point at all is the evidence. A *failure*, however, is not observable as a
    # finding: a refused handshake surfaces as a connection error, and decision rule R4
    # classifies that as ERROR rather than as non-conformance, deliberately, because
    # blocking correlates with the property under study. The remaining branch below is
    # unreachable in practice too, since the collectors drop non-HTTPS URLs from the
    # corpus and count them as `dropped_not_https`.
    #
    # So C11 is a prevalence measure, not a violation detector, and it is reported as one.
    # It is kept rather than deleted -- unlike C06 and C10, which were removed for being
    # unemitted and unanchorable -- because its PASS carries real information: it is the
    # precondition every other check rests on.
    if initial.tls is not None:
        tls_ok = initial.tls.chain_valid is not False and initial.tls.san_match is not False
        add(CheckId.TLS_VALID,
            Outcome.PASS if tls_ok else Outcome.FAIL_MISIMPLEMENTED,
            NormativeStrength.MUST,
            spec_ref="MCP: all authorization server endpoints MUST be served over HTTPS; "
                     "BCP 195",
            spec_url=SPEC_MCP,
            observed_value=f"chain_valid={initial.tls.chain_valid} "
                           f"san_match={initial.tls.san_match}")
    elif urlsplit(resource_url).scheme != "https":
        add(CheckId.TLS_VALID, Outcome.FAIL_UNIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="MCP: endpoints MUST be served over HTTPS", spec_url=SPEC_MCP,
            observed_value=urlsplit(resource_url).scheme)

    if not ev.requires_authorization:
        for cid in _MUST_STAGES:
            add(cid, Outcome.NOT_APPLICABLE, NormativeStrength.MUST,
                detail="authorization is OPTIONAL in MCP and this endpoint did not require it",
                spec_ref="MCP Authorization", spec_url=SPEC_MCP)
        add(CheckId.PKCE_DECLARED, Outcome.NOT_APPLICABLE, NormativeStrength.SHOULD,
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
    hinted_url: str | None = None
    if ev.www_authenticate and "resource_metadata=" in ev.www_authenticate:
        hinted = ev.www_authenticate.split("resource_metadata=", 1)[1].split(",")[0].strip(' "')
        ev.hinted_url_declared = hinted
        if _hint_is_followable(hinted, resource_url):
            hinted_url = hinted
            candidates.insert(0, hinted)
        else:
            # Recorded, not followed. The header is attacker-controlled input from the
            # host being measured, and following it anywhere it points does two kinds of
            # damage. It sends requests we never promised to send -- docs/ETHICS.md 3 lists
            # exactly what we fetch, and `http://127.0.0.1:8080` is not on that list, but a
            # bare startswith("http") check accepted it, from the author's home network.
            # And it corrupts the result: a document fetched from an attacker's host was
            # attributed to the victim, scored C12 PASS because the hint path compares
            # against the client's own request URL, and wrote the attacker's issuer into
            # the resource->issuer graph that is this paper's headline figure. One hostile
            # or misconfigured endpoint could inject arbitrary edges.
            ev.hint_rejected_reason = _hint_rejection_reason(hinted, resource_url)

    prm_doc: dict | None = None
    malformed: FetchResult | None = None
    robots_excluded: list[str] = []
    for candidate in candidates:
        result = await fetcher.fetch(candidate)
        if result.error_kind is ErrorKind.BLOCKED:
            add(CheckId.PRM_PRESENT, Outcome.ERROR, NormativeStrength.MUST,
                detail="access block (R4)", spec_url=SPEC_RFC9728)
            return checks, ev
        if result.error_kind in (ErrorKind.ROBOTS_DISALLOWED, ErrorKind.OPTED_OUT):
            # Our own politeness policy, not an observation of the origin. A robots
            # exclusion returns status=None, so without this branch the loop fell through
            # to "no metadata at any candidate location" and wrote FAIL_UNIMPLEMENTED --
            # charging the operator for a document we chose not to ask for. ETHICS.md 6
            # promises the opposite, and R4 forbids it.
            robots_excluded.append(candidate)
            continue
        if result.status == 200:
            parsed = _parse_json(result)
            if parsed is None:
                # A catch-all SPA answering 200 with HTML at the path form must not stop
                # us from trying the root form, where the real document often lives.
                # Remember the malformed hit in case no candidate ever parses.
                if malformed is None:
                    malformed = result
                continue
            prm_doc = parsed
            ev.prm_url = candidate
            break

    if prm_doc is None:
        if malformed is not None:
            # R3: 200 with an unparseable body is misimplementation, not absence.
            add(CheckId.PRM_PRESENT, Outcome.FAIL_MISIMPLEMENTED, NormativeStrength.MUST,
                spec_ref="RFC 9728 3.2", spec_url=SPEC_RFC9728,
                detail="200 response was not a JSON object at any candidate location",
                evidence_sha256=malformed.body_sha256)
        elif robots_excluded:
            # Absence we were not allowed to look for is not absence. This leaves the
            # study rather than counting against the operator (denominator rules, R4).
            ev.robots_excluded_urls = list(robots_excluded)
            for cid in _MUST_STAGES:
                add(cid, Outcome.ERROR, NormativeStrength.MUST,
                    spec_url=SPEC_RFC9728,
                    observed_value="; ".join(robots_excluded),
                    detail="not observed: excluded by robots.txt (R4, ETHICS.md 6)")
            add(CheckId.PKCE_DECLARED, Outcome.ERROR, NormativeStrength.SHOULD,
                spec_url=SPEC_RFC9728,
                observed_value="; ".join(robots_excluded),
                detail="not observed: excluded by robots.txt (R4, ETHICS.md 6)")
            return checks, ev
        else:
            add(CheckId.PRM_PRESENT, Outcome.FAIL_UNIMPLEMENTED, NormativeStrength.MUST,
                spec_ref="MCP: servers MUST implement RFC 9728", spec_url=SPEC_MCP,
                detail=f"no metadata at {len(candidates)} candidate location(s)")
        return checks, ev

    # R9.1: the expected identifier depends on which candidate answered, not on the
    # endpoint URL we started from. A document reached through the WWW-Authenticate hint
    # is compared against the URL the client actually requested (RFC 9728 3.3 paragraph 2).
    ev.expected_resource = (
        identifier_from_metadata_url(ev.prm_url)
        or canonical_resource_identifier(resource_url)
    )
    ev.prm_from_hint = ev.prm_url == hinted_url
    if ev.prm_from_hint:
        ev.expected_resource = canonical_resource_identifier(resource_url)
    # Descriptive only (R9.1): did the document we found actually cover this endpoint's
    # path? RFC 9728 7.6 puts that selection question out of scope, so it never penalises.
    ev.prm_scope_covers_endpoint = (
        canonical_resource_identifier(resource_url) == ev.expected_resource
    )

    ev.prm_document = prm_doc
    declared_servers = prm_doc.get("authorization_servers")
    if not isinstance(declared_servers, list):
        # A bare string here used to be iterated character by character, turning
        # "https://as.example" into fifteen single-letter "issuers".
        if declared_servers is not None:
            ev.as_errors["<malformed>"] = (
                f"authorization_servers is {type(declared_servers).__name__}, not a list"
            )
        declared_servers = []
    ev.authorization_servers = [
        s for s in declared_servers
        if isinstance(s, str) and urlsplit(s).scheme in ("https", "http") and urlsplit(s).netloc
    ]
    ev.malformed_authorization_servers = [
        s for s in declared_servers if s not in ev.authorization_servers
    ]

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
            _identity_outcome(ev.resource_relation, expectation_is_observed=False),  # R9.3
            NormativeStrength.MUST,
            spec_ref="RFC 9728 3.3: the resource value returned MUST be identical",
            spec_url=SPEC_RFC9728,
            observed_value=f"{ev.declared_resource} ({ev.resource_relation})",
            detail=f"expected {ev.expected_resource} from {ev.prm_url}",
        )

    # C13 / C14 - does each declared issuer actually answer as that issuer?
    if not ev.authorization_servers:
        add(CheckId.AS_CORRESPONDENCE, Outcome.NOT_APPLICABLE, NormativeStrength.MUST,
            detail="no issuer declared")
        add(CheckId.PKCE_DECLARED, Outcome.NOT_APPLICABLE, NormativeStrength.SHOULD,
            detail="no issuer declared")
        return checks, ev

    mismatches: list[str] = []
    unreachable: list[str] = []
    ambiguous: list[str] = []
    blocked: list[str] = []

    for issuer in dict.fromkeys(ev.authorization_servers):   # same AS twice = one fetch
        doc = None
        was_blocked = False
        for candidate in as_metadata_candidate_urls(issuer):
            result = await fetcher.fetch(candidate)
            if result.error_kind in (ErrorKind.BLOCKED, ErrorKind.ROBOTS_DISALLOWED,
                                     ErrorKind.OPTED_OUT):
                # R4: our own politeness policy must never be written up as the
                # operator's MUST violation.
                was_blocked = True
                continue
            if result.status == 200:
                doc = _parse_json(result)
                if doc is not None:
                    break
        if doc is None:
            if was_blocked:
                blocked.append(issuer)
                ev.as_errors[issuer] = "authorization server metadata not observed (R4)"
            else:
                unreachable.append(issuer)
                ev.as_errors[issuer] = "metadata not retrievable at any well-known location"
            continue
        ev.as_documents[issuer] = doc
        returned = doc.get("issuer")
        if not isinstance(returned, str):
            mismatches.append(f"{issuer} -> {returned!r}")
            ev.as_issuer_relations[issuer] = "absent"
            continue
        # R9.4: the same comparison policy as C12. RFC 8414 4 makes this stricter than
        # C12, not looser -- it requires code-point equality and forbids normalisation,
        # so the previous rstrip("/") was silently discarding real MUST violations.
        relation = _relation(returned, issuer)
        ev.as_issuer_relations[issuer] = relation
        outcome = _identity_outcome(relation, expectation_is_observed=True)
        if outcome is Outcome.FAIL_MISIMPLEMENTED:
            mismatches.append(f"{issuer} -> {returned!r} ({relation})")
        elif outcome is Outcome.UNSPECIFIED:
            ambiguous.append(f"{issuer} -> {returned!r} ({relation})")

    observed = len(ev.as_documents)
    if mismatches:
        add(CheckId.AS_CORRESPONDENCE, Outcome.FAIL_MISIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="RFC 8414 3.3: issuer value MUST be identical to the issuer requested",
            spec_url=SPEC_RFC8414, observed_value="; ".join(mismatches))
    elif unreachable and not observed:
        add(CheckId.AS_CORRESPONDENCE, Outcome.FAIL_UNIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="RFC 8414 3", spec_url=SPEC_RFC8414,
            observed_value="; ".join(unreachable),
            detail="every declared issuer failed to serve metadata")
    elif blocked and not observed:
        add(CheckId.AS_CORRESPONDENCE, Outcome.ERROR, NormativeStrength.MUST,
            spec_url=SPEC_RFC8414, observed_value="; ".join(blocked),
            detail="no declared issuer could be observed (R4)")
    elif unreachable:
        # A resource that names five issuers of which four are dead is the thesis in
        # miniature; scoring it PASS because one answered would discard the finding.
        add(CheckId.AS_CORRESPONDENCE, Outcome.FAIL_UNIMPLEMENTED, NormativeStrength.MUST,
            spec_ref="RFC 8414 3", spec_url=SPEC_RFC8414,
            observed_value="; ".join(unreachable),
            detail=f"{len(unreachable)} of {len(ev.authorization_servers)} declared "
                   f"issuers served no metadata")
    elif ambiguous:
        add(CheckId.AS_CORRESPONDENCE, Outcome.UNSPECIFIED, NormativeStrength.MUST,
            spec_ref="RFC 8414 3.3", spec_url=SPEC_RFC8414,
            observed_value="; ".join(ambiguous), detail="R6/R9.3")
    else:
        add(CheckId.AS_CORRESPONDENCE, Outcome.PASS, NormativeStrength.MUST,
            spec_ref="RFC 8414 3.3", spec_url=SPEC_RFC8414)

    # C16-C18. Three properties of the issuers this resource points its clients at, read
    # from documents already fetched for C13. Each is DESCRIPTIVE_ONLY (R1) and each is a
    # candidate headline; which one carries the paper cannot be guessed before the data
    # exists, so all three are declared and collected and the choice is made by the rule
    # in decision-rules.md R11 rather than by whichever number turns out flattering.
    if ev.as_documents:
        # Two denominators, and they are not interchangeable. `observed` is how many issuer
        # documents were actually retrieved; `declared` is how many the resource named. An
        # issuer that never answered cannot advertise anything, and scoring these against
        # the observed count alone let an unreachable issuer push the result toward PASS --
        # on C16, which is the first-ranked headline candidate in R11.1 and which R11.3
        # already warns may stick at 100%. Both numbers are recorded so the analysis can
        # choose, and so the choice is visible.
        observed = len(ev.as_documents)
        declared = len(dict.fromkeys(ev.authorization_servers)) or observed

        def _descriptive(check_id, present: list[str], strength, **kw) -> None:
            add(check_id,
                Outcome.PASS if present and len(present) == declared else Outcome.UNSPECIFIED,
                strength,
                observed_value=f"{len(present)}/{observed} observed, "
                               f"{len(present)}/{declared} declared",
                **kw)

        # C16 - RFC 9207. BCP 240 2.1: "When an OAuth client can interact with more than
        # one authorization server, a defense against mix-up attacks ... is REQUIRED."
        # RFC 9207 makes the iss parameter that defence, and requires the server to
        # advertise it; absent the flag a conforming client must assume false, so what is
        # measured here is whether the required defence is *available* to a client that
        # only knows what discovery tells it.
        _descriptive(
            CheckId.ISS_PARAMETER_DECLARED,
            [issuer for issuer, doc in ev.as_documents.items()
             if doc.get("authorization_response_iss_parameter_supported") is True],
            NormativeStrength.SHOULD,
            spec_ref="RFC 9207 3: the server MUST advertise iss support in its metadata; "
                     "RFC 9700 (BCP 240) 2.1 makes a mix-up defence REQUIRED of the client",
            spec_url="https://www.rfc-editor.org/rfc/rfc9207.html")

        # C17 - can a client obtain credentials without a human? MCP's registration
        # ladder ends at "Prompt the user to enter the client information if no other
        # option is available", which an autonomous agent cannot do.
        _descriptive(
            CheckId.CLIENT_BOOTSTRAP_DECLARED,
            [issuer for issuer, doc in ev.as_documents.items()
             if doc.get("client_id_metadata_document_supported") is True
             or isinstance(doc.get("registration_endpoint"), str)],
            NormativeStrength.SHOULD,
            spec_ref="MCP: clients fall back to prompting the user when no registration "
                     "mechanism is advertised",
            spec_url=SPEC_MCP)

        # C18 - RFC 9728 4 defines `protected_resources` so that 7.6's cross-check has
        # something to check against. Whether it passes is a separate question from
        # whether it is *possible*, and both are recorded.
        # A present-but-empty `protected_resources` is not a published list: it enumerates
        # nothing, so §7.6's cross-check remains as impossible as if the member were absent.
        # Counting it as "publishes" inflated the second-ranked headline candidate. The
        # empty case is still recorded, because "declared the member and left it empty" is a
        # different thing from "did not declare it" and the difference is worth a number.
        listed: dict[str, list] = {}
        empty = 0
        for issuer, doc in ev.as_documents.items():
            resources = doc.get("protected_resources")
            if not isinstance(resources, list):
                continue
            if resources:
                listed[issuer] = resources
            else:
                empty += 1
        covered = [
            issuer for issuer, resources in listed.items()
            if ev.declared_resource and any(
                isinstance(r, str) and _relation(r, ev.declared_resource) == "identical"
                for r in resources
            )
        ]
        add(CheckId.PROTECTED_RESOURCES_DECLARED,
            Outcome.PASS if listed else Outcome.UNSPECIFIED,
            NormativeStrength.MAY,
            spec_ref="RFC 9728 4: `protected_resources` is OPTIONAL; 7.6 recommends "
                     "cross-checking the two lists but puts AS selection out of scope",
            spec_url=SPEC_RFC9728,
            observed_value=f"listed={len(listed)}/{observed} observed, {declared} declared; "
                           f"empty_list={empty}; cross_check_passes={len(covered)}")

        # C08/C09. Neither is required by any specification, so R1 keeps them descriptive.
        # They are emitted rather than left as enum entries because a paper that lists a
        # check it never ran claims a measurement it did not make, and both are a single
        # lookup in a document already fetched for C13. What they populate is the "what
        # the ecosystem does not declare" table, with two real numbers instead of a gap.
        sender_constrained = [
            issuer for issuer, doc in ev.as_documents.items()
            if doc.get("dpop_signing_alg_values_supported")
            or doc.get("tls_client_certificate_bound_access_tokens") is True
        ]
        add(CheckId.SENDER_CONSTRAINED,
            Outcome.PASS if len(sender_constrained) == len(ev.as_documents)
            else Outcome.UNSPECIFIED,
            NormativeStrength.MAY,
            spec_ref="RFC 9449 DPoP and mTLS sender-constraining are optional in MCP",
            spec_url=SPEC_MCP,
            observed_value=f"{len(sender_constrained)}/{len(ev.as_documents)}")

        revocable = [
            issuer for issuer, doc in ev.as_documents.items()
            if isinstance(doc.get("revocation_endpoint"), str)
        ]
        add(CheckId.REVOCATION_DECLARED,
            Outcome.PASS if len(revocable) == len(ev.as_documents) else Outcome.UNSPECIFIED,
            NormativeStrength.MAY,
            spec_ref="RFC 7009 revocation is optional; no specification requires an agent "
                     "identity to be revocable",
            spec_url=SPEC_RFC8414,
            observed_value=f"{len(revocable)}/{len(ev.as_documents)}")

        # C14 - PKCE advertisement. Descriptive, and the demotion was decided against the
        # specification text rather than by preference (decision-rules.md R1 log, 29 July
        # 2026). RFC 8414 2 marks `code_challenge_methods_supported` "OPTIONAL"; RFC 9700
        # (BCP 240) 2.1.1 is the only document that bridges "MUST support PKCE" to
        # advertising it, and it sets that bridge at RECOMMENDED -- "Authorization servers
        # MAY instead provide a deployment-specific way to ensure or determine PKCE
        # support" -- which a passive prober cannot observe either way. So an absent
        # element is not evidence that any authorization-server MUST was violated.
        #
        # The sentence this check used to cite binds the client: "MCP clients MUST refuse
        # to proceed." Scoring the server for it is the objection recorded against C16 a
        # hundred lines above, and it is the objection MCP's Resource Indicators clause was
        # already rejected for in spec-mapping.md. The one server-binding MUST that exists
        # (MCP 2025-11-25: "Authorization servers providing OpenID Connect Discovery 1.0
        # MUST include code_challenge_methods_supported") is absent from 2025-06-18, and R7
        # scores every endpoint against the most permissive frozen revision.
        #
        # Aggregation matches C16-C18 rather than the old "any issuer advertised it":
        # a resource naming five issuers of which one advertises PKCE has not given its
        # clients a working choice, and C13 four hundred lines up rejects exactly that
        # reasoning for exactly that reason.
        _descriptive(
            CheckId.PKCE_DECLARED,
            [issuer for issuer, doc in ev.as_documents.items()
             if doc.get("code_challenge_methods_supported")],
            NormativeStrength.SHOULD,
            spec_ref="RFC 9700 (BCP 240) 2.1.1: publishing "
                     "code_challenge_methods_supported is RECOMMENDED, and an authorization "
                     "server MAY instead provide a deployment-specific way to determine "
                     "PKCE support; RFC 8414 2 marks the element OPTIONAL",
            spec_url=SPEC_RFC9700,
        )
    else:
        add(CheckId.PKCE_DECLARED, Outcome.ERROR, NormativeStrength.SHOULD,
            detail="no authorization server metadata retrievable")

    return checks, ev
