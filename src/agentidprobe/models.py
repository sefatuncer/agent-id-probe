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
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CheckId(str, Enum):
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
    AS_METADATA_VALID = "C06"             # RFC 8414 authorization-server metadata valid
    WWW_AUTH_RESOURCE_METADATA = "C07"    # 401 carries WWW-Authenticate: resource_metadata
    SENDER_CONSTRAINED = "C08"            # DPoP / mTLS declared  (descriptive only)
    REVOCATION_DECLARED = "C09"           # revocation_endpoint declared  (descriptive only)
    TRUST_ANCHORED = "C10"                # key origin chains to a public CA root
    TLS_VALID = "C11"                     # endpoint TLS itself is valid (BCP 195)
    PRM_RESOURCE_IDENTITY_MATCH = "C12"   # PRM `resource` == canonical resource identifier
    AS_CORRESPONDENCE = "C13"             # declared issuer actually returns that issuer
    PKCE_DECLARED = "C14"                 # code_challenge_methods_supported present
    KEY_STRENGTH = "C15"                  # alg / key size / kid resolvable


class NormativeStrength(str, Enum):
    """How hard the specification pushes. Enforced by decision rule R1: only a MUST
    may produce a FAIL_* outcome."""

    MUST = "must"
    SHOULD = "should"
    MAY = "may"
    SILENT = "silent"     # the spec does not address this at all


class Outcome(str, Enum):
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
        CheckId.TRUST_ANCHORED,       # "organisational trust root" is not spec-defined
    }
)


def resolve_precedence(outcomes: list[Outcome]) -> Outcome:
    """Apply decision rule R2."""
    for candidate in OUTCOME_PRECEDENCE:
        if candidate in outcomes:
            return candidate
    return Outcome.ERROR


class EndpointKind(str, Enum):
    A2A_AGENT_CARD = "a2a_agent_card"
    MCP_REMOTE = "mcp_remote"
    DID_WEB = "did_web"


class Modality(str, Enum):
    """Which funnel an endpoint is scored in."""

    SIGNED_DOCUMENT = "signed_document"   # A2A card / did:web
    OAUTH_METADATA = "oauth_metadata"     # MCP authorization


class Hosting(str, Enum):
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
    raw_artifact_path: str | None = None
    checks: list[CheckResult] = Field(default_factory=list)
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
    ("PKCE declared", CheckId.PKCE_DECLARED),
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
