"""Corpus collection from free, keyless public registries.

Every source here is queried through its documented public API, without an account,
API key or paid tier. That is a hard project constraint, not a preference.

The unit of analysis is the **apex domain**, not the endpoint URL. Registries list the
same server many times (one entry per version) and a single operator often exposes many
paths under one host, so counting URLs would silently weight the results toward whoever
publishes most often. Deduplication happens here, once, rather than being remembered
later in the analysis.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import tldextract

from .fetcher import Fetcher
from .models import Endpoint, EndpointKind, Hosting

# Resolve suffixes from the bundled snapshot; no network fetch, so a collection run is
# reproducible and works offline.
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)

MCP_REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
SMITHERY_REGISTRY = "https://registry.smithery.ai/servers"
# Glama was evaluated as a third corpus source on 30 July 2026 and **cut**. The constant stays
# so the negative result has somewhere to live, because it is a finding about the frame rather
# than a failed experiment.
#
# The API is free, keyless and cursor-paginated, so the obstacle was not access. Across 500
# records, 280 of them tagged `hosting:remote-capable`, the response exposes eleven fields --
# attributes, description, environmentVariablesJsonSchema, id, name, namespace, repository,
# slug, spdxLicense, tools, url -- and **not one of them is a remote endpoint URL**. `url` is
# always a glama.ai catalogue page (`https://glama.ai/mcp/servers/<id>`) and `repository` is a
# source repository. There is nothing to probe.
#
# Wiring it in anyway would have repeated the Smithery defect exactly: that collector read
# `homepage` as an MCP endpoint, `homepage` was a project page, and 85% of the corpus became
# garbage with `github.com` in it sixty-six times. Here `url` is the same trap -- it is a URL,
# it is even server-specific, and every endpoint derived from it would resolve to one apex,
# `glama.ai`.
#
# The finding is reportable and belongs in the paper's frame discussion: of the three public MCP
# registries, only `registry.modelcontextprotocol.io` publishes remote endpoint URLs. Smithery
# does not, Glama does not. That is a ceiling on what *any* registry-framed measurement of this
# ecosystem can observe, not a limitation of this instrument.
GLAMA_REGISTRY = "https://glama.ai/api/mcp/v1/servers"
GLAMA_CUT_REASON = (
    "evaluated 2026-07-30 and cut: the API publishes no remote endpoint URL. Across 500 "
    "records (280 tagged hosting:remote-capable) the only URL-shaped fields are a glama.ai "
    "catalogue page and a source repository."
)

# Hosts that serve many unrelated operators' agents. Their endpoints are still measured,
# but they are marked so the clustering analysis can separate "the platform got it wrong
# once" from "a thousand operators each got it wrong".
_KNOWN_PLATFORM_SUFFIXES = (
    "smithery.ai",
    "glama.ai",
    "mcp.run",
    "modelcontextprotocol.io",
    "vercel.app",
    "onrender.com",
    "fly.dev",
    "herokuapp.com",
    "railway.app",
    "cloudflareaccess.com",
    "workers.dev",
    "azurewebsites.net",
    "run.app",
    "replit.app",
    "ngrok.io",
    "ngrok-free.app",
)


def public_suffix_provenance() -> dict:
    """Which public-suffix list this run used, identified well enough to reproduce.

    Defect D10, closed 30 July 2026. The list is already pinned *against the network* --
    `suffix_list_urls=()` with `fallback_to_snapshot=True` means the bundled snapshot is the
    only source and no run can silently pick up a fresher one mid-measurement. What was not
    pinned is *which* snapshot: `tldextract>=5.1,<6.0` admits any patch release, and each
    ships its own.

    That is not a cosmetic gap, because the list decides two things that reach the paper:

    * **The primary unit of analysis.** R10.2 makes the apex domain the unit, so a snapshot
      that resolves one host differently changes the cluster count, and with it every
      confidence interval and the design effect beside it.
    * **Which hosts are contacted at all.** `_issuer_rejection_reason` withholds any issuer
      with no registrable domain, so a suffix present in one snapshot and absent from another
      changes the set of requests the instrument sends -- and since 30 July 2026 a withheld
      issuer leaves the denominator, so it changes the population too.

    R8 leg 2 promises that re-scoring stored artefacts reproduces every verdict bit for bit.
    Replay does not re-fetch, but it does re-derive apexes, so that promise was inheriting an
    unrecorded dependency. Recording the version and the snapshot digest in every manifest
    turns "our numbers are reproducible" into something a reviewer can check rather than
    accept: a mismatch is now visible instead of silently shifting the clustering.
    """
    try:
        version = importlib.metadata.version("tldextract")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - not installed
        version = "unknown"

    digest = None
    snapshot = Path(tldextract.__file__).parent / ".tld_set_snapshot"
    if snapshot.exists():
        digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    return {
        "library": "tldextract",
        "version": version,
        "snapshot_sha256": digest,
        # Stated rather than implied: the private section is off, so two tenants of one
        # hosting platform share an apex. That is correct for clustering and it
        # under-estimates the cross-operator delegation rate, which is the safe direction and
        # is written into the paper's §3.5 and §9.4.
        "include_psl_private_domains": False,
        "suffix_list_urls": [],
    }


def apex_domain(url: str) -> str | None:
    """eTLD+1 for the URL's host, or None when the host is an IP or unparseable."""
    host = urlsplit(url).hostname
    if not host:
        return None
    extracted = _EXTRACT(host)
    if not extracted.domain or not extracted.suffix:
        return None
    return f"{extracted.domain}.{extracted.suffix}"


def classify_hosting(url: str) -> Hosting:
    apex = apex_domain(url)
    if apex is None:
        return Hosting.UNKNOWN
    if any(apex == p or apex.endswith("." + p) for p in _KNOWN_PLATFORM_SUFFIXES):
        return Hosting.HOSTED_PLATFORM
    return Hosting.SELF_HOSTED


def endpoint_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


@dataclass
class CollectionStats:
    """Reported in the paper's methodology section: the reader needs to see how a raw
    registry count becomes the analysed population."""

    source: str
    records_seen: int = 0
    remote_urls_seen: int = 0
    endpoints_kept: int = 0
    apex_domains: set[str] = field(default_factory=set)
    dropped_no_apex: int = 0
    dropped_not_https: int = 0
    pages_fetched: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "records_seen": self.records_seen,
            "remote_urls_seen": self.remote_urls_seen,
            "endpoints_kept": self.endpoints_kept,
            "unique_apex_domains": len(self.apex_domains),
            "dropped_no_apex": self.dropped_no_apex,
            "dropped_not_https": self.dropped_not_https,
            "pages_fetched": self.pages_fetched,
            "errors": self.errors,
        }


def _remote_urls_from_mcp_record(record: dict) -> list[str]:
    """Pull remote transport URLs out of one registry record.

    Registry schemas have shifted; both the top-level `remotes` list and the nested
    `server.remotes` form appear in live data, so both are read rather than assuming
    whichever version happens to be current.
    """
    urls: list[str] = []
    candidates: list = []
    for holder in (record, record.get("server") if isinstance(record.get("server"), dict) else {}):
        if not isinstance(holder, dict):
            continue
        remotes = holder.get("remotes")
        if isinstance(remotes, list):
            candidates.extend(remotes)
    for remote in candidates:
        if isinstance(remote, dict) and isinstance(remote.get("url"), str):
            urls.append(remote["url"])
        elif isinstance(remote, str):
            urls.append(remote)
    return urls


def publisher_namespace(record: dict) -> str | None:
    """The reverse-DNS namespace the registry itself verified, e.g. `io.github.someone`.

    Decision rule R10.2b needs sensitivity arms for clustering, and this one is unusual in
    being externally supplied: the registry verifies namespace ownership (DNS TXT for
    domain namespaces, OAuth for `io.github.*`) before accepting a publication, so it is
    ground truth we did not invent. That matters here specifically — a clustering built
    from a list we wrote ourselves is the author-supplied rubric this instrument exists to
    avoid. It was being read off every record and discarded.
    """
    name = record.get("name") or (record.get("server") or {}).get("name")
    if not isinstance(name, str) or "/" not in name:
        return None
    namespace = name.split("/", 1)[0].strip().lower()
    return namespace or None


class RegistryCollector:
    """Base for the free registries. Subclasses supply pagination and record shape."""

    source_name = "registry"

    def __init__(self, fetcher: Fetcher, max_pages: int = 500) -> None:
        self.fetcher = fetcher
        self.max_pages = max_pages
        self.stats = CollectionStats(source=self.source_name)

    async def _pages(self) -> AsyncIterator[dict]:
        raise NotImplementedError

    def _records(self, page: dict) -> Iterable[dict]:
        raise NotImplementedError

    def _urls(self, record: dict) -> list[str]:
        return _remote_urls_from_mcp_record(record)

    async def collect(self) -> list[Endpoint]:
        seen: dict[str, Endpoint] = {}
        now = datetime.now(UTC)

        async for page in self._pages():
            self.stats.pages_fetched += 1
            for record in self._records(page):
                self.stats.records_seen += 1
                for url in self._urls(record):
                    self.stats.remote_urls_seen += 1
                    if not url.startswith("https://"):
                        # Plain HTTP cannot carry a meaningful identity claim; recorded
                        # as a drop so the count appears in the methodology, not lost.
                        self.stats.dropped_not_https += 1
                        continue
                    apex = apex_domain(url)
                    if apex is None:
                        self.stats.dropped_no_apex += 1
                        continue
                    eid = endpoint_id(url)
                    if eid in seen:
                        continue
                    seen[eid] = Endpoint(
                        endpoint_id=eid,
                        url=url,
                        kind=EndpointKind.MCP_REMOTE,
                        source=self.source_name,
                        apex_domain=apex,
                        publisher_namespace=publisher_namespace(record),
                        hosting=classify_hosting(url),
                        registry_listed=True,
                        first_seen=now,
                        last_seen=now,
                    )
                    self.stats.apex_domains.add(apex)

        self.stats.endpoints_kept = len(seen)
        return list(seen.values())


class McpOfficialRegistry(RegistryCollector):
    """registry.modelcontextprotocol.io — cursor pagination, no authentication."""

    source_name = "mcp-official-registry"

    # The registry defaults to 30 records per page and accepts up to 100; ?limit=500 is
    # rejected with 422. At the default it takes ~625 pages to enumerate the corpus, which
    # is how a max_pages set for a trial run silently truncates a full one.
    page_size = 100

    async def _pages(self) -> AsyncIterator[dict]:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(self.max_pages):
            # A registry that echoes the same cursor back would otherwise keep us
            # paginating until max_pages, re-counting the same records and quietly
            # inflating every statistic derived from them.
            if cursor is not None:
                if cursor in seen_cursors:
                    self.stats.errors.append(f"cursor repeated ({cursor}); stopping pagination")
                    return
                seen_cursors.add(cursor)
            query = f"limit={self.page_size}" + (f"&cursor={cursor}" if cursor else "")
            url = f"{MCP_REGISTRY}?{query}"
            result = await self.fetcher.fetch(url)
            if result.status != 200 or not result.body:
                self.stats.errors.append(f"{url} -> {result.status} {result.error_kind.value}")
                return
            try:
                page = json.loads(result.body)
            except json.JSONDecodeError as exc:
                self.stats.errors.append(f"{url} -> unparseable: {exc}")
                return
            yield page
            metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
            cursor = metadata.get("next_cursor") or metadata.get("nextCursor")
            if not cursor:
                return
        # Falling out of the loop means the registry still had records. Saying so is the
        # whole point: a truncated corpus that leaves no trace in the manifest looks
        # exactly like a complete one.
        self.stats.errors.append(
            f"TRUNCATED: pagination stopped at max_pages={self.max_pages} with more "
            f"records available (next cursor {cursor!r}). The corpus is incomplete."
        )

    def _records(self, page: dict) -> Iterable[dict]:
        servers = page.get("servers")
        return [s for s in servers if isinstance(s, dict)] if isinstance(servers, list) else []


class SmitheryRegistry(RegistryCollector):
    """registry.smithery.ai — page-number pagination."""

    source_name = "smithery"

    async def _pages(self) -> AsyncIterator[dict]:
        for page_number in range(1, self.max_pages + 1):
            url = f"{SMITHERY_REGISTRY}?page={page_number}&pageSize=100"
            result = await self.fetcher.fetch(url)
            if result.status != 200 or not result.body:
                self.stats.errors.append(f"{url} -> {result.status} {result.error_kind.value}")
                return
            try:
                page = json.loads(result.body)
            except json.JSONDecodeError as exc:
                self.stats.errors.append(f"{url} -> unparseable: {exc}")
                return
            yield page
            servers = page.get("servers")
            if not isinstance(servers, list) or not servers:
                return

    def _records(self, page: dict) -> Iterable[dict]:
        servers = page.get("servers")
        return [s for s in servers if isinstance(s, dict)] if isinstance(servers, list) else []

    def _urls(self, record: dict) -> list[str]:
        """Only fields that actually denote an MCP endpoint.

        `homepage` and `url` were harvested here until 2026-07-28 and they are not
        endpoints: on the `/servers` listing they hold the project's marketing or source
        page. A live collection run showed the damage — 203 of 238 corpus entries came
        from this collector and every one of them was a `homepage`, including
        `https://github.com/` sixty-six times and bare origins with no path at all. Each
        would have been probed for `/.well-known/oauth-protected-resource`, returned 404,
        and been counted as C05 FAIL_UNIMPLEMENTED, corrupting both the numerator and the
        denominator of the study's headline funnel.

        The `/servers` listing does not carry a deployment URL at all (`remote` there is a
        boolean, not a URL). Reaching the real endpoint needs a per-server detail request,
        `GET /servers/{qualifiedName}` -> `connections[].deploymentUrl`, which this
        collector does not make. Until it does, Smithery contributes nothing to the corpus
        and is kept only as a frame-validity cross-check.
        """
        return _remote_urls_from_mcp_record(record)


def merge_endpoints(*groups: list[Endpoint]) -> list[Endpoint]:
    """Union across registries, keeping the earliest discovery and noting every source.

    Overlap between registries is itself a measurement: it is what makes a
    capture-recapture estimate of the total remote-MCP population possible, so the
    per-source membership is preserved rather than collapsed.
    """
    merged: dict[str, Endpoint] = {}
    for group in groups:
        for endpoint in group:
            existing = merged.get(endpoint.endpoint_id)
            if existing is None:
                merged[endpoint.endpoint_id] = endpoint
                continue
            sources = sorted(set(existing.source.split("+")) | {endpoint.source})
            merged[endpoint.endpoint_id] = existing.model_copy(
                update={"source": "+".join(sources)}
            )
    return list(merged.values())


# `capture_recapture_estimate` was deleted on 30 July 2026. It computed a Lincoln-Petersen /
# Chapman population estimate across two registries to answer "is your corpus representative?"
# with a number, and the number would not have meant what it said. Capture-recapture requires a
# closed population and independent samples, and both assumptions fail here: the MCP registry
# and Smithery are not independent draws -- Smithery indexes largely what the official registry
# publishes -- and the population is open, with servers registered and withdrawn continuously.
# An estimate resting on two false assumptions is worse than the shrug it replaced, because it
# looks like evidence.
#
# The decision to drop it was recorded before this deletion, and the live code kept computing it
# anyway and writing it into every manifest. That gap is the reason this comment exists rather
# than a silent removal: a frozen decision contradicted by running code is the failure mode this
# repository keeps rediscovering, and the frame-validity question is now answered where it
# belongs -- by reporting the frame's shape (top-k concentration, HHI, URL-to-apex ratio) and
# stating plainly that the registry is not the ecosystem. See paper §9.1 and R10.5.

