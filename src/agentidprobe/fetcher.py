"""Polite HTTP fetching for a passive measurement study.

Two things here are load-bearing for the paper rather than merely operational:

1. **Block detection.** Decision rule R4 says an access block is never a finding. If a
   WAF answers instead of the origin, we learn nothing about whether the origin
   implements a spec — and counting that as "unimplemented" would bias the result in
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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from urllib.parse import urlsplit

import httpx
from protego import Protego

from .config import DEFAULT_CONFIG, MeasurementConfig
from .models import TlsInfo


class ErrorKind(str, Enum):
    NONE = "none"
    TIMEOUT = "timeout"
    DNS = "dns"
    TLS = "tls"
    CONNECTION = "connection"
    BLOCKED = "blocked"          # WAF / bot challenge / 403 / 429 — R4: never a finding
    TOO_LARGE = "too_large"
    ROBOTS_DISALLOWED = "robots_disallowed"
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

    403 and 429 are treated as blocks unconditionally. 503 counts only when it carries
    a WAF fingerprint, since a plain 503 is an ordinary outage.
    """
    if status in (401, 402, 404, 410):
        return False  # these are genuine answers about the resource
    if status in (403, 429):
        return True
    if status == 503:
        head = body[:4096]
        if any(m in head for m in _BLOCK_BODY_MARKERS):
            return True
        lowered = {k.lower(): (v or "").lower() for k, v in headers.items()}
        return any(
            hint in lowered.get(name, "") if hint else name in lowered
            for name, hint in _BLOCK_HEADER_HINTS
        )
    if status == 200 and body:
        head = body[:4096]
        if any(m in head for m in _BLOCK_BODY_MARKERS):
            return True
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

    def __init__(self, config: MeasurementConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self._throttle = _HostThrottle(1.0 / config.rate.per_host_requests_per_second)
        self._semaphore = asyncio.Semaphore(config.rate.global_concurrency)
        self._robots: dict[str, Protego | None] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}
        self._client: httpx.AsyncClient | None = None
        self._host_failures: dict[str, int] = {}

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
                resp = await self._client.get(f"{origin}/robots.txt")
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
        """Fetch one URL, following redirects manually and recording the chain."""
        if self._client is None:
            raise RuntimeError("Fetcher must be used as an async context manager")

        host = urlsplit(url).netloc
        if self._host_failures.get(host, 0) >= self.config.rate.host_failure_budget:
            return FetchResult(url=url, ok=False, error_kind=ErrorKind.BLOCKED,
                               error_detail="host failure budget exhausted")

        if not await self.allowed(url):
            # R4 denominator rule: these leave the study entirely.
            return FetchResult(url=url, ok=False, error_kind=ErrorKind.ROBOTS_DISALLOWED)

        rate = self.config.rate
        chain: list[str] = []
        current = url
        started = time.perf_counter()

        async with self._semaphore:
            for _hop in range(self.config.scope.max_redirects + 1):
                hop_host = urlsplit(current).netloc
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
                if (
                    response.is_redirect
                    and self.config.scope.follow_redirects
                    and response.headers.get("location")
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
