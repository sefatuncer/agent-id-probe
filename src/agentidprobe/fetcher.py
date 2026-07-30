"""Polite HTTP fetching for a passive measurement study.

Two things here are load-bearing for the paper rather than merely operational:

1. **Block detection.** Decision rule R4 says an access block is never a finding. If a
   WAF answers instead of the origin, we learn nothing about whether the origin
   implements a spec â€” and counting that as "unimplemented" would bias the result in
   exactly the direction of the property being measured, because mature deployments are
   the ones sitting behind WAFs. So blocks are classified and returned as errors.

2. **Redirect chains.** A document found after a cross-origin redirect cannot be
   attributed to the host we asked. The chain is recorded so attribution can be checked
   downstream rather than silently assumed.
"""

from __future__ import annotations

import asyncio
import hashlib
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlsplit

import httpx
from protego import Protego

from .config import DEFAULT_CONFIG, MeasurementConfig, is_opted_out
from .models import TlsInfo


class ErrorKind(StrEnum):
    NONE = "none"
    TIMEOUT = "timeout"
    DNS = "dns"
    TLS = "tls"
    CONNECTION = "connection"
    BLOCKED = "blocked"          # WAF / bot challenge / 403 / 429 â€” R4: never a finding
    TOO_LARGE = "too_large"
    ROBOTS_DISALLOWED = "robots_disallowed"
    OPTED_OUT = "opted_out"      # operator asked to be excluded; leaves every denominator
    # A redirect pointed somewhere the scope statement does not permit us to follow. Our
    # decision, so it leaves every denominator exactly as the two above do.
    OUT_OF_SCOPE = "out_of_scope"
    OTHER = "other"


# Fingerprints of interstitials that answer *instead of* the origin. Frozen before
# data collection so the classification cannot be tuned to taste afterwards.
_BLOCK_BODY_MARKERS: tuple[bytes, ...] = (
    b"cf-browser-verification",
    b"cf_chl_opt",
    b"Just a moment...",
    b"Attention Required! | Cloudflare",
    b"Checking your browser before accessing",
    b"Request blocked",
    b"Access denied",
    b"<title>403 Forbidden</title>",
    b"Incapsula incident ID",
    b"Sucuri WebSite Firewall",
    b"captcha-delivery.com",
    b"Please enable JS and disable any ad blocker",
)

_BLOCK_HEADER_HINTS: tuple[tuple[str, str], ...] = (
    ("server", "cloudflare"),
    ("server", "awselb"),
    ("x-sucuri-id", ""),
    ("x-datadome", ""),
    ("x-iinfo", ""),  # Imperva/Incapsula
)


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    final_url: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    elapsed_ms: float | None = None
    tls: TlsInfo | None = None
    error_kind: ErrorKind = ErrorKind.NONE
    error_detail: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def body_sha256(self) -> str | None:
        return hashlib.sha256(self.body).hexdigest() if self.body else None

    def crossed_origin(self) -> bool:
        if not self.final_url:
            return False
        return urlsplit(self.url).netloc != urlsplit(self.final_url).netloc


def classify_block(status: int | None, headers: dict[str, str], body: bytes) -> bool:
    """R4: is this an access block rather than an answer from the origin?

    429 is a block unconditionally. 403 is *not*: the MCP authorization specification
    lists `403 Forbidden â€” Invalid scopes or insufficient permissions` in its own error
    table, so a 403 is frequently the MCP server answering a question we asked. Treating
    every 403 as a WAF discarded those endpoints as ERROR, and made the
    `status in (401, 403)` branch in checks_oauth unreachable â€” an authorization-requiring
    population that the pilot counted (37.9% "401/403") but the code could never reproduce.

    A 403 is therefore only a block when nothing indicates the origin answered. The
    default when ambiguous stays "block", because R4's asymmetry is deliberate: scoring a
    WAF page as a specification failure writes a violation against an operator we never
    observed, while scoring a genuine 403 as a block only costs us one observation.

    503 counts only when it carries a WAF fingerprint, since a plain 503 is an outage.
    """
    if status in (401, 402, 404, 410):
        return False  # these are genuine answers about the resource
    if status == 429:
        return True
    lowered = {k.lower(): (v or "").lower() for k, v in headers.items()}
    if status == 403:
        # Positive evidence that the origin, not an intermediary, produced this.
        if "www-authenticate" in lowered:
            return False                   # an OAuth challenge is an answer, not a block
        content_type = lowered.get("content-type", "")
        if "json" in content_type:
            return False
    # Body fingerprints are only meaningful in an HTML interstitial. Applied to JSON
    # they misfire on ordinary payloads â€” an API answering {"error": "Access denied"}
    # is the origin talking, not a WAF, and review found such endpoints were both
    # dropped from the denominator and charged against the host failure budget.
    is_html = "text/html" in lowered.get("content-type", "")
    if is_html and body and any(m in body[:4096] for m in _BLOCK_BODY_MARKERS):
        return True
    if status == 403:
        return True                        # ambiguous 403: stay on the R4-safe side
    if status == 503:
        # A bare 503 is an outage. Requiring a body fingerprint rather than trusting a
        # `server: cloudflare` header matters: CDN use correlates with operational
        # maturity, so header-only classification would bias exactly the population we
        # are trying to measure.
        return any(name in lowered for name, hint in _BLOCK_HEADER_HINTS if not hint)
    return False


class _HostThrottle:
    """One in-flight request per host, spaced by the configured interval."""

    def __init__(self, min_interval_s: float) -> None:
        self._min_interval = min_interval_s
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def acquire(self, host: str) -> asyncio.Lock:
        lock = self._locks.setdefault(host, asyncio.Lock())
        await lock.acquire()
        wait = self._min_interval - (time.monotonic() - self._last.get(host, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        return lock

    def release(self, host: str, lock: asyncio.Lock) -> None:
        self._last[host] = time.monotonic()
        lock.release()


def _extract_tls(response: httpx.Response) -> TlsInfo | None:
    """Best-effort peer certificate details. Absent on some transports; never fatal."""
    try:
        stream = response.extensions.get("network_stream")
        if stream is None:
            return None
        ssl_object: ssl.SSLObject | None = stream.get_extra_info("ssl_object")
        if ssl_object is None:
            return None
        der = ssl_object.getpeercert(binary_form=True)
        cert = ssl_object.getpeercert() or {}
        issuer_cn = None
        for rdn in cert.get("issuer", ()):
            for key, value in rdn:
                if key == "commonName":
                    issuer_cn = value
        not_after = None
        if cert.get("notAfter"):
            try:
                not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
                    tzinfo=UTC
                )
            except ValueError:
                not_after = None
        return TlsInfo(
            version=ssl_object.version(),
            cert_sha256=hashlib.sha256(der).hexdigest() if der else None,
            issuer_cn=issuer_cn,
            not_after=not_after,
            # A completed handshake with the default context means the chain validated
            # and the hostname matched; httpx verifies both.
            chain_valid=True,
            san_match=True,
        )
    except Exception:  # noqa: BLE001 - telemetry must never break a measurement
        return None


class Fetcher:
    """Rate-limited, robots-aware, redirect-tracking HTTP client."""

    def __init__(
        self,
        config: MeasurementConfig = DEFAULT_CONFIG,
        on_fetch: Callable[[FetchResult], None] | None = None,
    ) -> None:
        self.config = config
        # Every response this fetcher produces is handed to `on_fetch` before it is
        # returned. The checks fetch documents of their own â€” the protected-resource
        # metadata and each declared issuer's metadata â€” and those are precisely the
        # documents the decisive verdicts rest on. Persisting only what the caller
        # remembers to pass along means the inputs to C12 and C13 are never written down,
        # decision rule R8's replay guarantee cannot hold, and rebuilding the
        # resource -> issuer graph would mean a second scan of several thousand
        # third-party hosts. A capture hook here cannot be forgotten by a caller.
        self.on_fetch = on_fetch
        self._throttle = _HostThrottle(1.0 / config.rate.per_host_requests_per_second)
        self._semaphore = asyncio.Semaphore(config.rate.global_concurrency)
        self._robots: dict[str, Protego | None] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}
        self._client: httpx.AsyncClient | None = None
        self._host_failures: dict[str, int] = {}
        # Every request this pass has sent to each host, including redirect hops,
        # retries and robots.txt. The published per-host bound is only a bound if
        # something counts.
        self._host_requests: dict[str, int] = {}

    async def __aenter__(self) -> Fetcher:
        rate = self.config.rate
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.config.user_agent, "Accept": "application/json, */*"},
            timeout=httpx.Timeout(connect=rate.connect_timeout_s, read=rate.read_timeout_s,
                                  write=rate.read_timeout_s, pool=rate.connect_timeout_s),
            follow_redirects=False,  # followed manually so the chain is observable
            max_redirects=self.config.scope.max_redirects,
            verify=True,
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _robots_for(self, origin: str) -> Protego | None:
        if origin in self._robots:
            return self._robots[origin]
        lock = self._robots_locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin in self._robots:
                return self._robots[origin]
            parsed = None
            try:
                assert self._client is not None
                robots_host = urlsplit(origin).hostname or urlsplit(origin).netloc
                self._host_requests[robots_host] = self._host_requests.get(robots_host, 0) + 1
                lock = await self._throttle.acquire(robots_host)
                try:
                    resp = await self._client.get(f"{origin}/robots.txt")
                finally:
                    self._throttle.release(robots_host, lock)
                if resp.status_code == 200 and len(resp.content) < 512_000:
                    parsed = Protego.parse(resp.text)
            except Exception:  # noqa: BLE001 - unreachable robots.txt means no rules
                parsed = None
            self._robots[origin] = parsed
            return parsed

    async def allowed(self, url: str) -> bool:
        if not self.config.rate.respect_robots_txt:
            return True
        parts = urlsplit(url)
        robots = await self._robots_for(f"{parts.scheme}://{parts.netloc}")
        if robots is None:
            return True
        return bool(robots.can_fetch(url, self.config.user_agent))

    async def fetch(self, url: str) -> FetchResult:
        """Fetch one URL and hand the result to the capture hook before returning it.

        Every path out of `_fetch` goes through here, so no document a check consulted
        can escape persistence (see `on_fetch` in __init__).
        """
        result = await self._fetch(url)
        if self.on_fetch is not None:
            self.on_fetch(result)
        return result

    def _leaves_the_public_web(self, url: str) -> str | None:
        """Why a redirect target is outside the scope statement, or None.

        Applied to redirect hops only. The first URL of a fetch is the caller's to justify
        -- `checks_oauth._issuer_rejection_reason` and `_hint_is_followable` do that, and
        the collectors drop non-HTTPS endpoints -- but nothing chooses a redirect target
        except the host being measured, so this is the only place it can be checked.
        """
        from .collectors import apex_domain

        parts = urlsplit(url)
        if parts.scheme != "https":
            return f"redirect to {parts.scheme!r}, not https"
        if apex_domain(url) is None:
            # Loopback, RFC 1918, link-local (169.254.169.254 is cloud instance metadata),
            # bare IPs and special-use TLDs all land here.
            host = parts.hostname or ""
            return f"redirect to {host!r}, which has no registrable domain"
        return None

    async def _gate(self, url: str, *, is_redirect: bool) -> FetchResult | None:
        """Every reason we refuse to send a request, in one place.

        These ran once per fetch, against the URL we picked, until 30 July 2026 -- and then
        up to three redirect hops went wherever the response said, re-checking nothing. The
        opt-out gate in particular is a promise to a named operator, and a redirect walked
        straight through it.
        """
        if is_opted_out(url, self.config.opted_out):
            return FetchResult(url=url, ok=False, error_kind=ErrorKind.OPTED_OUT,
                               error_detail="operator opted out (docs/ETHICS.md 7)")

        host = urlsplit(url).hostname or urlsplit(url).netloc
        if self._host_failures.get(host, 0) >= self.config.rate.host_failure_budget:
            return FetchResult(url=url, ok=False, error_kind=ErrorKind.BLOCKED,
                               error_detail="host failure budget exhausted")

        # The aggregate bound, which nothing enforced until 30 July 2026. See
        # `RatePolicy.max_requests_per_host`: capping issuers is not capping hosts, and
        # nothing accumulated across endpoints at all.
        if self._host_requests.get(host, 0) >= self.config.rate.max_requests_per_host:
            return FetchResult(
                url=url, ok=False, error_kind=ErrorKind.OUT_OF_SCOPE,
                error_detail=f"host has already received "
                             f"{self.config.rate.max_requests_per_host} requests this pass")

        if is_redirect and (reason := self._leaves_the_public_web(url)) is not None:
            return FetchResult(url=url, ok=False, error_kind=ErrorKind.OUT_OF_SCOPE,
                               error_detail=reason)

        if not await self.allowed(url):
            # R4 denominator rule: these leave the study entirely.
            return FetchResult(url=url, ok=False, error_kind=ErrorKind.ROBOTS_DISALLOWED)
        return None

    async def _fetch(self, url: str) -> FetchResult:
        """Fetch one URL, following redirects manually and recording the chain."""
        if self._client is None:
            raise RuntimeError("Fetcher must be used as an async context manager")

        host = urlsplit(url).netloc

        # Checked before anything else, including robots and the failure budget: an
        # operator who has asked not to be measured must not be contacted even to read
        # their robots.txt. Enforcing this in the fetcher rather than at the corpus level
        # means no call path -- collection, a declared jwks_uri, a WWW-Authenticate hint --
        # can route around it.
        refusal = await self._gate(url, is_redirect=False)
        if refusal is not None:
            return refusal

        rate = self.config.rate
        chain: list[str] = []
        current = url
        started = time.perf_counter()

        async with self._semaphore:
            for hop in range(self.config.scope.max_redirects + 1):
                if hop:
                    # Every gate is re-applied on every redirect hop, and until 30 July 2026
                    # none of them was. They ran once, against the URL we chose, and then
                    # httpx followed up to three hops wherever the response pointed.
                    #
                    # An adversarial review demonstrated the consequence rather than
                    # arguing it: a declared issuer at `https://redir.example.net` that
                    # answered 302 to `http://127.0.0.1:8080/admin/metadata` produced
                    # exactly that request -- plain text, loopback, from a residential line
                    # -- and the response was stored as evidence and scored. Link-local
                    # `169.254.169.254` worked the same way, which on any cloud VM is the
                    # instance metadata service, and the artefact licence is CC BY 4.0.
                    # Redirects into an opted-out host, and into a host whose robots.txt
                    # forbids us, were also followed.
                    #
                    # So the scope statement is enforced per hop. The same-apex rule is
                    # deliberately *not* applied: a legitimate issuer redirecting to its own
                    # CDN or regional host is normal, and refusing that would delete real
                    # measurements. What is refused is leaving the public HTTPS web.
                    hop_refusal = await self._gate(current, is_redirect=True)
                    if hop_refusal is not None:
                        hop_refusal.url = url
                        hop_refusal.redirect_chain = chain
                        hop_refusal.elapsed_ms = (time.perf_counter() - started) * 1000
                        return hop_refusal
                # Keyed on the hostname, not the netloc. Ports are not machines: ten
                # declared issuers differing only by port measured 2.8 req/s against a
                # published promise of 1 req/s per host, because each port got its own
                # throttle bucket.
                hop_host = urlsplit(current).hostname or urlsplit(current).netloc
                self._host_requests[hop_host] = self._host_requests.get(hop_host, 0) + 1
                lock = await self._throttle.acquire(hop_host)
                try:
                    response = await self._request_with_retry(current)
                finally:
                    self._throttle.release(hop_host, lock)

                if isinstance(response, FetchResult):  # transport failure
                    response.url = url
                    response.redirect_chain = chain
                    response.elapsed_ms = (time.perf_counter() - started) * 1000
                    return response

                chain.append(current)
                # `has_redirect_location` rather than `is_redirect`: httpx only builds
                # next_request for statuses it considers followable, so a 300 or 305
                # carrying a Location left the loop re-requesting the same URL until
                # the hop budget ran out and reported a bogus redirect-limit error.
                if (
                    response.has_redirect_location
                    and self.config.scope.follow_redirects
                    and response.next_request is not None
                ):
                    current = str(response.next_request.url) if response.next_request else current
                    continue

                body = response.content[: rate.max_response_bytes]
                headers = dict(response.headers)
                blocked = classify_block(response.status_code, headers, body)
                if blocked:
                    self._host_failures[host] = self._host_failures.get(host, 0) + 1

                return FetchResult(
                    url=url,
                    ok=not blocked,
                    status=response.status_code,
                    headers=headers,
                    body=body,
                    final_url=str(response.url),
                    redirect_chain=chain,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    tls=_extract_tls(response),
                    error_kind=ErrorKind.BLOCKED if blocked else ErrorKind.NONE,
                    error_detail="access block classified per decision rule R4" if blocked else "",
                )

        return FetchResult(url=url, ok=False, error_kind=ErrorKind.OTHER,
                           error_detail="redirect limit exceeded", redirect_chain=chain)

    async def _request_with_retry(self, url: str) -> httpx.Response | FetchResult:
        assert self._client is not None
        rate = self.config.rate
        last_error = ""
        last_kind = ErrorKind.OTHER

        for attempt in range(rate.max_retries + 1):
            try:
                response = await self._client.get(url)
            except httpx.TimeoutException as exc:
                last_kind, last_error = ErrorKind.TIMEOUT, str(exc)
            except httpx.ConnectError as exc:
                detail = str(exc).lower()
                if "certificate" in detail or "ssl" in detail:
                    last_kind = ErrorKind.TLS
                elif "name or service not known" in detail or "getaddrinfo" in detail:
                    last_kind = ErrorKind.DNS
                else:
                    last_kind = ErrorKind.CONNECTION
                last_error = str(exc)
            except (ValueError, httpx.InvalidURL) as exc:
                # A malformed issuer in someone else's metadata yields a relative or
                # otherwise unusable URL, and httpx raises ValueError, which is not an
                # httpx.HTTPError. Uncaught it escaped probe_oauth entirely, the runner's
                # blanket handler dropped the endpoint, and because no report was written
                # the resume scan retried and re-dropped it on every run. A bad document
                # on a third-party host must cost that host one verdict, not our record
                # of the endpoint.
                last_kind, last_error = ErrorKind.OTHER, f"unusable URL: {exc}"
                break                        # deterministic: retrying cannot help
            except httpx.HTTPError as exc:
                last_kind, last_error = ErrorKind.OTHER, str(exc)
            else:
                if response.status_code == 429 and rate.honour_retry_after:
                    delay = _retry_after_seconds(response) or rate.backoff_base_s * (2**attempt)
                    if attempt < rate.max_retries:
                        await asyncio.sleep(min(delay, 60.0))
                        continue
                return response

            if attempt < rate.max_retries:
                await asyncio.sleep(rate.backoff_base_s * (2**attempt))

        return FetchResult(url=url, ok=False, error_kind=last_kind, error_detail=last_error)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
