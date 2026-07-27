"""Measurement policy, enforced in code rather than promised in prose.

Everything here exists because this study touches third-party hosts. The study is
passive and read-only: it fetches documents that operators deliberately publish at
well-known locations. It never authenticates, never writes, never probes for
vulnerabilities, and never attempts to bypass anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

PROBE_VERSION = "0.1.0"

# Identifies the crawler and gives operators a way to reach us or opt out.
# The URL and mailbox must be live before any wide run (see docs/ETHICS.md).
CONTACT_EMAIL = "tuncersefa@gmail.com"
INFO_URL = "https://github.com/<org>/agent-id-probe"
USER_AGENT = (
    f"agent-id-probe/{PROBE_VERSION} (academic measurement; "
    f"+{INFO_URL}; contact: {CONTACT_EMAIL})"
)


@dataclass(frozen=True)
class RatePolicy:
    """Deliberately conservative. A measurement study that degrades the systems it
    measures is both unethical and self-invalidating."""

    per_host_requests_per_second: float = 1.0
    global_concurrency: int = 8
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 20.0
    max_retries: int = 2
    backoff_base_s: float = 2.0
    max_response_bytes: int = 5 * 1024 * 1024
    respect_robots_txt: bool = True
    honour_retry_after: bool = True
    # Hard stop: if a host returns this many consecutive 429/5xx, drop it for the run.
    host_failure_budget: int = 3


@dataclass(frozen=True)
class Scope:
    """What we are allowed to touch. Anything not on this list is out of scope."""

    wellknown_paths: tuple[str, ...] = (
        "/.well-known/agent-card.json",
        "/.well-known/agent.json",          # pre-v0.3 alias; recorded with a version note
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration",
        "/.well-known/did.json",
        "/.well-known/jwks.json",
    )
    follow_redirects: bool = True
    max_redirects: int = 3
    # We resolve these only when a fetched document points at them.
    follow_declared_uris: bool = True


@dataclass(frozen=True)
class MeasurementConfig:
    rate: RatePolicy = field(default_factory=RatePolicy)
    scope: Scope = field(default_factory=Scope)
    user_agent: str = USER_AGENT
    dry_run: bool = False


DEFAULT_CONFIG = MeasurementConfig()


def prm_candidate_urls(resource_url: str) -> list[str]:
    """Protected-resource metadata locations to try, in priority order.

    RFC 9728 places the metadata at a *path-suffixed* well-known URI when the
    resource identifier has a path component, and at the root form when it does not.
    A probe that only tries the root form manufactures failures for correctly
    configured servers — Reviewer A flagged this as a denominator bug that could not
    be repaired after collection, so both forms are generated here.

    Note the ordering rule: the well-known segment is inserted *between* the
    authority and the resource path, it does not replace the path.
    """
    parts = urlsplit(resource_url)
    origin = (parts.scheme, parts.netloc)
    path = parts.path.rstrip("/")

    candidates: list[str] = []
    if path:
        candidates.append(
            urlunsplit((*origin, f"/.well-known/oauth-protected-resource{path}", "", ""))
        )
    candidates.append(
        urlunsplit((*origin, "/.well-known/oauth-protected-resource", "", ""))
    )
    return candidates


def as_metadata_candidate_urls(issuer: str) -> list[str]:
    """Authorization-server metadata locations for a declared issuer.

    RFC 8414 uses the path-suffixed form; OpenID Connect Discovery appends
    /.well-known/openid-configuration to the issuer. Both are observed in the wild,
    so both are tried before concluding the issuer does not resolve.
    """
    parts = urlsplit(issuer)
    origin = (parts.scheme, parts.netloc)
    path = parts.path.rstrip("/")

    candidates = [
        urlunsplit((*origin, f"/.well-known/oauth-authorization-server{path}", "", "")),
        urlunsplit((*origin, f"{path}/.well-known/openid-configuration", "", "")),
    ]
    if path:
        candidates.append(
            urlunsplit((*origin, f"{path}/.well-known/oauth-authorization-server", "", ""))
        )
    return candidates
