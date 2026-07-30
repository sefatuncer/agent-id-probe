"""Normalized data model shared by collectors, checks and analysis.

The checks below are the paper's instrument. Each one is bound to a sentence in a
published specification (see docs/spec-mapping.md) and carries the *normative strength*
of that sentence. That binding, plus the decision rules in docs/decision-rules.md, is
what keeps the instrument outside the authors' control: a check may only report a
failure when it can point at a MUST. Anything weaker is reported as UNSPECIFIED, which
is feedback to the standards body rather than to the deployment.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CheckId(StrEnum):
    """The measurement instrument.

    C01-C04 concern the signed-document modality (A2A Agent Cards, did:web).
    C05-C07 and C11-C15 concern the OAuth modality (MCP authorization metadata).
    The two are scored in separate funnels: an endpoint that legitimately uses
    OAuth-only identity must not be counted as failing a signature check it was
    never required to satisfy.
    """

    IDENTITY_METADATA_PUBLISHED = "C01"   # an identity document is served at all
    CARD_SIGNED = "C02"                   # that document carries a JWS signature
    KEY_RESOLVABLE = "C03"                # jku / kid / did:web resolves to a usable key
    SIGNATURE_VERIFIES = "C04"            # the signature actually verifies (RFC 7515 + 8785)
    PRM_PRESENT = "C05"                   # RFC 9728 protected-resource metadata reachable
    # C06 and C10 were removed on 2026-07-28. Both were defined, documented, and never
    # emitted by any code path, and a paper that lists a check it does not run claims a
    # measurement it did not make -- the cheapest possible way to lose a reviewer.
    # C06 (AS metadata valid) was also redundant: C13 already fetches and parses the
    # authorization-server document, so an unparseable one already fails there.
    # C10 (key chains to an organisational trust root) had no specification to anchor to;
    # defining one would have been the authors' rubric, which is the objection that killed
    # three earlier framings of this project.
    WWW_AUTH_RESOURCE_METADATA = "C07"    # 401 carries WWW-Authenticate: resource_metadata
    SENDER_CONSTRAINED = "C08"            # DPoP / mTLS declared  (descriptive only)
    REVOCATION_DECLARED = "C09"           # revocation_endpoint declared  (descriptive only)
    TLS_VALID = "C11"                     # endpoint TLS itself is valid (BCP 195)
    PRM_RESOURCE_IDENTITY_MATCH = "C12"   # PRM `resource` == canonical resource identifier
    AS_CORRESPONDENCE = "C13"             # declared issuer actually returns that issuer
    PKCE_DECLARED = "C14"                 # code_challenge_methods_supported present
    KEY_STRENGTH = "C15"                  # alg / key size / kid resolvable

    # C16-C18 read fields already present in the authorization-server metadata document
    # that C13 fetches, so they cost no additional request. All three are descriptive:
    # each rests on a MUST that binds somebody we cannot observe (the client) or on an
    # OPTIONAL parameter, so R1 forbids them from reporting a failure. They exist because
    # each is a candidate headline whose value cannot be guessed in advance, and declaring
    # them before collection is what keeps the choice between them from being post-hoc.
    ISS_PARAMETER_DECLARED = "C16"        # RFC 9207 mix-up defence advertised by the issuer
    CLIENT_BOOTSTRAP_DECLARED = "C17"     # CIMD or RFC 7591 registration available
    PROTECTED_RESOURCES_DECLARED = "C18"  # RFC 9728 Â§4 list, i.e. Â§7.6 cross-check possible


class NormativeStrength(StrEnum):
    """How hard the specification pushes. Enforced by decision rule R1: only a MUST
    may produce a FAIL_* outcome."""

    MUST = "must"
    SHOULD = "should"
    MAY = "may"
    SILENT = "silent"     # the spec does not address this at all


class Outcome(StrEnum):
    PASS = "pass"
    FAIL_UNIMPLEMENTED = "fail_unimplemented"      # the field/mechanism is absent
    FAIL_MISIMPLEMENTED = "fail_misimplemented"    # present but violates a MUST
    UNSPECIFIED = "unspecified"                    # the spec does not settle it
    NOT_APPLICABLE = "not_applicable"              # check does not apply to this endpoint
    ERROR = "error"                                # transport/tooling failure, NOT a finding


# Decision rule R2: when two verdicts collide, the earlier entry wins.
OUTCOME_PRECEDENCE: tuple[Outcome, ...] = (
    Outcome.ERROR,
    Outcome.NOT_APPLICABLE,
    Outcome.UNSPECIFIED,
    Outcome.FAIL_MISIMPLEMENTED,
    Outcome.FAIL_UNIMPLEMENTED,
    Outcome.PASS,
)

# Decision rule R1: checks whose spec anchor is weaker than MUST can never fail.
# These are collected and reported, but only descriptively.
DESCRIPTIVE_ONLY: frozenset[CheckId] = frozenset(
    {
        CheckId.CARD_SIGNED,          # A2A: `signatures` is OPTIONAL for the publisher
        CheckId.SENDER_CONSTRAINED,   # neither MCP nor RFC 9449 mandates DPoP/mTLS
        CheckId.REVOCATION_DECLARED,  # no spec requires an agent identity to be revocable
        # RFC 9700 (BCP 240) 2.1 makes a mix-up defence REQUIRED, but of the *client*, and
        # a passive probe cannot observe clients. What is observable is whether the issuer
        # makes the defence available at all. Recording the absence as the issuer's failure
        # would be scoring one party for another's obligation.
        CheckId.ISS_PARAMETER_DECLARED,
        # MCP lists four registration paths and permits ending at "prompt the user"; none
        # of them is mandatory for an authorization server.
        CheckId.CLIENT_BOOTSTRAP_DECLARED,
        # RFC 9728 4: `protected_resources` is OPTIONAL, and 7.6 puts the selection problem
        # it addresses explicitly out of scope.
        CheckId.PROTECTED_RESOURCES_DECLARED,
        # Demoted on 29 July 2026 after the anchor was read rather than assumed. RFC 8414 2
        # marks `code_challenge_methods_supported` "OPTIONAL"; RFC 9700 (BCP 240) 2.1.1 --
        # the only text bridging "authorization servers MUST support PKCE" to advertising
        # it -- sets that bridge at RECOMMENDED and adds that a server "MAY instead provide
        # a deployment-specific way", which no passive prober can observe. The sentence
        # this check used to cite ("MCP clients MUST refuse to proceed") binds the client.
        CheckId.PKCE_DECLARED,
    }
)


class BoundParty(StrEnum):
    """Whose obligation the anchoring sentence states.

    This is the paper's argument in one column, and it is the reason Table 1 exists rather
    than a list of check names: the clauses along the discovery chain bind different
    parties, and at the step that decides which issuer a client will trust, none of them
    binds anybody. It is also an R1 guard with teeth — a sentence that binds the *client*
    describes an obligation a passive probe cannot observe, so a check anchored to one
    must be descriptive-only or it is scoring one party for another's obligation.
    """

    RESOURCE_SERVER = "resource server"
    AUTHORIZATION_SERVER = "authorization server"
    CLIENT = "client"
    CARD_PUBLISHER = "card publisher"


# (short clause label, party the anchoring sentence binds), one row per live check.
#
# The label is deliberately short: the verbatim sentences are quoted in the paper's §2
# where each is argued, and repeating them here would put the same text in the manuscript
# twice. `tests/test_paper_table.py` asserts that every label's RFC number really appears
# in a `spec_ref` or `spec_url` the code emits for that check, so the label cannot drift
# into naming a clause the instrument does not cite.
SPEC_ANCHOR_SUMMARY: dict[CheckId, tuple[str, BoundParty]] = {
    CheckId.IDENTITY_METADATA_PUBLISHED: ("A2A agent discovery", BoundParty.CARD_PUBLISHER),
    CheckId.CARD_SIGNED: ("A2A §4.4.7", BoundParty.CARD_PUBLISHER),
    CheckId.KEY_RESOLVABLE: ("A2A §8.4", BoundParty.CARD_PUBLISHER),
    CheckId.SIGNATURE_VERIFIES: ("RFC 7515 §5.2; RFC 8785", BoundParty.CARD_PUBLISHER),
    CheckId.PRM_PRESENT: ("RFC 9728 §3.2", BoundParty.RESOURCE_SERVER),
    CheckId.WWW_AUTH_RESOURCE_METADATA: ("MCP Authorization, discovery",
                                         BoundParty.RESOURCE_SERVER),
    CheckId.SENDER_CONSTRAINED: ("RFC 9449", BoundParty.AUTHORIZATION_SERVER),
    CheckId.REVOCATION_DECLARED: ("RFC 7009; RFC 8414", BoundParty.AUTHORIZATION_SERVER),
    CheckId.TLS_VALID: ("MCP Authorization, HTTPS", BoundParty.RESOURCE_SERVER),
    CheckId.PRM_RESOURCE_IDENTITY_MATCH: ("RFC 9728 §3.3", BoundParty.RESOURCE_SERVER),
    CheckId.AS_CORRESPONDENCE: ("RFC 8414 §3.3", BoundParty.AUTHORIZATION_SERVER),
    CheckId.PKCE_DECLARED: ("RFC 9700 §2.1.1; RFC 8414 §2", BoundParty.AUTHORIZATION_SERVER),
    # RFC 7518 §3.3 only. C15 was split on 30 July 2026 (R9.7): §3.3's "a key of size 2048
    # bits or larger MUST be used" binds the signer and is the one condition of the three
    # that can convict. `none` and `HS*` are recorded as UNSPECIFIED, because §3.6 binds the
    # verifier and RFC 8725 governs JWTs rather than a detached JWS. The label said bare
    # "RFC 7518", which named the right document for the wrong reason -- it covered all three
    # conditions equally, and two of them had nothing in that document behind them.
    CheckId.KEY_STRENGTH: ("RFC 7518 §3.3", BoundParty.CARD_PUBLISHER),
    # RFC 9207 §2.3 binds the authorization server -- "The server MUST indicate its support
    # for the iss parameter by setting the metadata parameter
    # authorization_response_iss_parameter_supported ... to true" -- and that is the sentence
    # governing the thing this check observes. RFC 9700 §2.1's REQUIRED binds the client and is
    # the motivation, not the anchor. Recorded as CLIENT until 29 July 2026, when the
    # Figure 1 cross-check caught the disagreement; the paper's §2 already said this.
    #
    # The section was §3 until 30 July 2026, here and at the emission site and in the
    # amendment log. §3 introduces the parameter and states its false-by-default and contains
    # no MUST whatsoever, so the label named a clause that authorises nothing -- in the row a
    # reviewer checks first, for R11.1's rank-1 headline candidate. Nothing caught it because
    # the Table 1 cross-check compared document identifiers only; it now compares sections too.
    #
    # It stays descriptive regardless: §2.3's MUST is conditional on "Authorization servers
    # supporting this specification", so an absent flag means "does not support", which
    # nothing forbids.
    CheckId.ISS_PARAMETER_DECLARED: ("RFC 9207 §2.3", BoundParty.AUTHORIZATION_SERVER),
    CheckId.CLIENT_BOOTSTRAP_DECLARED: ("MCP Authorization, registration",
                                        BoundParty.CLIENT),
    CheckId.PROTECTED_RESOURCES_DECLARED: ("RFC 9728 §4", BoundParty.AUTHORIZATION_SERVER),
}

# Empty, and kept rather than deleted so the guard survives its own success.
#
# It held C14 for one day. C14 reported a failure against the authorization server while
# anchored to "MCP clients MUST refuse to proceed" -- a sentence binding the client. The
# resolution was not chosen: three independent readings of the primary text agreed that no
# sentence in the frozen revision set makes an absent `code_challenge_methods_supported` an
# authorization-server violation. RFC 8414 §2 marks the element OPTIONAL; RFC 9700 §2.1.1
# sets publishing it at RECOMMENDED and expressly permits "a deployment-specific way"
# instead; and the one server-binding MUST that does exist (MCP 2025-11-25, conditioned on
# OpenID Connect Discovery) is absent from MCP 2025-06-18, which R7 makes the governing
# revision. C14 became descriptive and left the OAuth funnel.
#
# The precedent was already in this repository: MCP's Resource Indicators clause was
# rejected as unmeasurable for the identical reason, and C07 was rewritten for it. C14 was
# the same shape and nobody had noticed. `tests/test_paper_table.py` keeps this set empty,
# so the third instance fails a build instead of reaching a reviewer.
CLIENT_BOUND_BUT_FAILABLE: frozenset[CheckId] = frozenset()


def resolve_precedence(outcomes: list[Outcome]) -> Outcome:
    """Apply decision rule R2."""
    for candidate in OUTCOME_PRECEDENCE:
        if candidate in outcomes:
            return candidate
    return Outcome.ERROR


class EndpointKind(StrEnum):
    A2A_AGENT_CARD = "a2a_agent_card"
    MCP_REMOTE = "mcp_remote"
    DID_WEB = "did_web"


class Modality(StrEnum):
    """Which funnel an endpoint is scored in."""

    SIGNED_DOCUMENT = "signed_document"   # A2A card / did:web
    OAUTH_METADATA = "oauth_metadata"     # MCP authorization


class Hosting(StrEnum):
    HOSTED_PLATFORM = "hosted_platform"
    SELF_HOSTED = "self_hosted"
    UNKNOWN = "unknown"


class TlsInfo(BaseModel):
    version: str | None = None
    cert_sha256: str | None = None
    issuer_cn: str | None = None
    not_after: datetime | None = None
    chain_valid: bool | None = None
    san_match: bool | None = None


class Endpoint(BaseModel):
    endpoint_id: str = Field(description="stable hash of the canonical URL")
    url: str
    kind: EndpointKind
    source: str = Field(description="which free directory/registry surfaced it")
    source_url: str | None = None
    apex_domain: str | None = Field(
        default=None, description="eTLD+1; required for key-reuse and same-org analysis"
    )
    publisher_namespace: str | None = Field(
        default=None,
        description="reverse-DNS namespace the registry itself verified, e.g. io.github.x; "
                    "an externally supplied clustering arm under R10.2b",
    )
    # Sensitivity arms that are declared but not yet collected. R10.2 forbids an
    # uncollected arm from feeding any decision rule, precisely so that the mistake which
    # invalidated the first go/no-go criterion -- resting it on a quantity nothing
    # measures -- cannot repeat.
    asn: str | None = None
    country: str | None = None
    hosting: Hosting = Hosting.UNKNOWN
    registry_listed: bool = False
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class CheckResult(BaseModel):
    # Frozen so decision rule R1 cannot be bypassed after construction. Review showed
    # that plain assignment and model_copy(update=...) both slipped past the validator,
    # which would let a re-scoring pass quietly turn an UNSPECIFIED into a failure.
    model_config = ConfigDict(frozen=True, validate_assignment=True)

    check_id: CheckId
    outcome: Outcome
    normative_strength: NormativeStrength
    spec_ref: str = Field(default="", description="clause cited in docs/spec-mapping.md")
    spec_url: str = ""
    spec_version: str = Field(
        default="", description="endpoints are scored against the revision they declare"
    )
    observed_value: str | None = None
    detail: str = ""
    evidence_sha256: str | None = None

    def model_post_init(self, _context) -> None:
        # Decision rule R1, enforced mechanically rather than promised in prose.
        if self.outcome in (Outcome.FAIL_UNIMPLEMENTED, Outcome.FAIL_MISIMPLEMENTED):
            if self.normative_strength is not NormativeStrength.MUST:
                raise ValueError(
                    f"{self.check_id.value}: a FAIL outcome requires a MUST-level spec "
                    f"anchor, got {self.normative_strength.value}. Report UNSPECIFIED."
                )
            if self.check_id in DESCRIPTIVE_ONLY:
                raise ValueError(
                    f"{self.check_id.value} is descriptive-only and may not report a failure."
                )


class RunContext(BaseModel):
    """Without this a run is not reproducible; probe_version alone is not enough."""

    run_id: str
    vantage_point: str = Field(description="e.g. 'residential-TR' or 'msku-ulakbim'")
    dns_resolver: str | None = None
    probe_git_commit: str | None = None
    started_at: datetime


class EndpointReport(BaseModel):
    endpoint: Endpoint
    modality: Modality
    reachable: bool
    http_status: int | None = None
    final_url: str | None = None
    redirect_chain: list[str] = Field(default_factory=list)
    tls: TlsInfo | None = None
    elapsed_ms: float | None = None
    server_header: str | None = None
    robots_allowed: bool = True
    # The operator asked not to be measured. Kept in the corpus so the exclusion is
    # auditable, removed from every denominator, and counted in the paper (ETHICS.md 7).
    opted_out: bool = False
    raw_artifact_path: str | None = None
    checks: list[CheckResult] = Field(default_factory=list)
    # The structured observations behind the verdicts: the declared resource, every
    # declared issuer and its metadata, and how each comparison missed. A CheckResult
    # records what was decided; this records what it was decided from. Without it the
    # resource -> issuer graph -- the study's headline figure -- could only be rebuilt by
    # scanning several thousand third-party hosts a second time.
    evidence: dict = Field(default_factory=dict)
    probed_at: datetime
    run_id: str

    def outcome_of(self, check_id: CheckId) -> Outcome | None:
        for c in self.checks:
            if c.check_id == check_id:
                return c.outcome
        return None

    def crossed_origin(self) -> bool:
        """A card found after a cross-origin redirect cannot be attributed to the
        original host. Reviewer A flagged this as a silent attribution bug."""
        if not self.final_url or not self.redirect_chain:
            return False
        from urllib.parse import urlsplit

        return urlsplit(self.endpoint.url).netloc != urlsplit(self.final_url).netloc


# Two funnels, scored over disjoint denominators. Reporting a single funnel would
# count composition (endpoints that never opted into a modality) as failure.
FUNNEL_OAUTH: list[tuple[str, CheckId | None]] = [
    ("reachable", None),
    ("publishes protected-resource metadata", CheckId.PRM_PRESENT),
    ("resource identifier matches", CheckId.PRM_RESOURCE_IDENTITY_MATCH),
    ("declared issuer corresponds", CheckId.AS_CORRESPONDENCE),
    # C14 was the fifth stage until 29 July 2026. A descriptive check cannot be a funnel
    # stage here: `runner.summarise()` narrows each stage to its PASS set, so a
    # non-advertising endpoint would count in the denominator and never in the numerator --
    # the "composition as failure" error that the same function's docstring exists to warn
    # about. The funnel now ends where the paper's thesis does, at issuer correspondence.
]

FUNNEL_SIGNED: list[tuple[str, CheckId | None]] = [
    ("reachable", None),
    ("publishes identity metadata", CheckId.IDENTITY_METADATA_PUBLISHED),
    ("carries a signature", CheckId.CARD_SIGNED),
    ("key resolvable", CheckId.KEY_RESOLVABLE),
    ("signature verifies", CheckId.SIGNATURE_VERIFIES),
]

FUNNELS: dict[Modality, list[tuple[str, CheckId | None]]] = {
    Modality.OAUTH_METADATA: FUNNEL_OAUTH,
    Modality.SIGNED_DOCUMENT: FUNNEL_SIGNED,
}


def has_cryptographic_binding(report: EndpointReport) -> bool:
    """The headline binary, defined once so it cannot drift between figures:
    does *any* cryptographic verification path close for this endpoint?"""
    return report.outcome_of(CheckId.SIGNATURE_VERIFIES) is Outcome.PASS
