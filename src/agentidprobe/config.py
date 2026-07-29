"""Measurement policy, enforced in code rather than promised in prose.

Everything here exists because this study touches third-party hosts. The study is
passive and read-only: it fetches documents that operators deliberately publish at
well-known locations. It never authenticates, never writes, never probes for
vulnerabilities, and never attempts to bypass anything.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

PROBE_VERSION = "0.1.0"

# Identifies the crawler and gives operators a way to reach us or opt out.
# The URL and mailbox must be live before any wide run (see docs/ETHICS.md).
CONTACT_EMAIL = "tuncersefa@gmail.com"
INFO_URL = "https://github.com/sefatuncer/agent-id-probe"
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
    """What we are allowed to touch.

    This list is the one published in docs/ETHICS.md 3, and it has to stay honest in both
    directions. It listed `/.well-known/agent.json`, the pre-v0.3 Agent Card alias, which
    nothing ever requested -- a promise to fetch something we did not fetch is harmless to
    operators but it made the scope statement untrue, and an untrue scope statement is the
    one thing that cannot be allowed in this document.

    Adding the request was the other option and it is the wrong trade: one more request
    against every origin in the corpus, to find legacy cards in a modality whose population
    is around ten endpoints and whose funnel is already reduced to descriptive reporting.
    Fewer requests to third parties is the right side of that trade. The consequence --
    cards still served only at the pre-v0.3 path are counted as absent -- belongs in
    Limitations, and is written there.
    """

    wellknown_paths: tuple[str, ...] = (
        "/.well-known/agent-card.json",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration",
        "/.well-known/did.json",
        "/.well-known/jwks.json",
    )
    follow_redirects: bool = True
    max_redirects: int = 3


@dataclass(frozen=True)
class AbortPolicy:
    """The global kill switch promised in docs/ETHICS.md 10.

    A per-host failure budget stops us hurting one operator. It cannot notice that the
    whole run has gone wrong -- a bad network, a wrong User-Agent that everything rejects,
    or a rate policy that turns out to be too aggressive in practice. Those states are
    invisible per-host and obvious in aggregate, and a kill switch without a number is not
    a kill switch, so the number lives here rather than in prose.

    The threshold is deliberately loose: at a 25% blocked-or-failed rate the measurement is
    no longer describing the ecosystem, it is describing our own reception, and continuing
    would collect thousands of endpoints' worth of data we could not defend.
    """

    # Low enough that the ~200-endpoint rehearsal actually arms the switch. At 200 the
    # threshold could first be evaluated on the rehearsal's final endpoint, so the run
    # whose entire purpose is to rehearse the full run was the one run the safeguard could
    # not fire in. 50 is still far more than enough for the rate to settle.
    min_endpoints_before_abort: int = 50
    max_failure_fraction: float = 0.25


OPT_OUT_FILE = "docs/opt-out.txt"
_WARNED_NO_OPT_OUT = False


def load_opt_out(root: Path | str | None = None) -> frozenset[str]:
    """Hosts and apex domains that asked not to be measured.

    docs/ETHICS.md 7 promises removal on request, with no justification asked and the list
    committed to the public repository so the exclusion is auditable. That promise needs a
    file and a gate, not just a paragraph: an opt-out that only exists in prose cannot be
    honoured when the first request arrives.

    One host or apex per line; `#` comments and blanks ignored. Matching is on the host and
    on its registrable domain, so opting out `example.com` also opts out `mcp.example.com`.

    Resolution order matters more than it looks. Locating the file relative to this module
    finds the repository when running from a checkout and finds nothing at all when running
    from an installed wheel -- where it silently returned an empty set, so a `pip install`
    of this package disabled the ethics gate without a word. Candidates are therefore tried
    in order and a miss is announced on stderr rather than assumed to mean "nobody opted
    out", because those two states must never look the same.
    """
    candidates: list[Path] = []
    if root is not None:
        candidates.append(Path(root) / OPT_OUT_FILE)
    else:
        env = os.environ.get("AGENT_ID_PROBE_OPT_OUT")
        if env:
            candidates.append(Path(env))
        candidates.append(Path.cwd() / OPT_OUT_FILE)
        candidates.append(Path(__file__).resolve().parents[2] / OPT_OUT_FILE)
        candidates.append(Path(__file__).resolve().parent / "opt-out.txt")

    for path in candidates:
        if path.exists():
            entries = set()
            for line in path.read_text(encoding="utf-8").splitlines():
                entry = line.split("#", 1)[0].strip().lower().rstrip(".")
                if entry:
                    entries.add(entry)
            return frozenset(entries)

    # Once per process. The list is loaded as a dataclass default, so warning on every
    # construction buries the message under itself -- `--help` alone printed it four times.
    global _WARNED_NO_OPT_OUT
    if not _WARNED_NO_OPT_OUT:
        _WARNED_NO_OPT_OUT = True
        print(
            f"agent-id-probe: no opt-out list found (looked in "
            f"{', '.join(str(c) for c in candidates)}). Proceeding with an empty exclusion "
            f"list. If this is a measurement run that is almost certainly wrong -- set "
            f"AGENT_ID_PROBE_OPT_OUT or run from the repository root.",
            file=sys.stderr,
        )
    return frozenset()


def is_opted_out(url: str, opted_out: frozenset[str]) -> bool:
    if not opted_out:
        return False
    host = urlsplit(url).netloc.split(":")[0].lower().rstrip(".")
    if not host:
        return False
    if host in opted_out:
        return True
    # A request to opt out is a request about an operator, not about one hostname.
    return any(host.endswith("." + entry) for entry in opted_out)


@dataclass(frozen=True)
class MeasurementConfig:
    rate: RatePolicy = field(default_factory=RatePolicy)
    scope: Scope = field(default_factory=Scope)
    abort: AbortPolicy = field(default_factory=AbortPolicy)
    user_agent: str = USER_AGENT
    dry_run: bool = False
    opted_out: frozenset[str] = field(default_factory=load_opt_out)


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
