"""Fetcher tests, run entirely against mocked transports — no network.

The block classifier gets the most attention because decision rule R4 depends on it:
if a WAF interstitial is mistaken for an origin answer, the study silently acquires a
bias in the direction of the property it is measuring.
"""

import httpx
import pytest
import respx

from agentidprobe.config import MeasurementConfig, RatePolicy
from agentidprobe.fetcher import ErrorKind, Fetcher, classify_block

FAST = MeasurementConfig(
    rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0)
)


# --- block classification (R4) ------------------------------------------------


def test_403_and_429_are_blocks():
    assert classify_block(403, {}, b"") is True
    assert classify_block(429, {}, b"") is True


def test_401_and_404_are_genuine_answers_not_blocks():
    """A 401 is the single most informative response in this study: it means the
    endpoint opted into authorization and C05 becomes applicable."""
    assert classify_block(401, {}, b"") is False
    assert classify_block(404, {}, b"") is False
    assert classify_block(410, {}, b"") is False


def test_cloudflare_challenge_served_with_200_is_a_block():
    body = b"<html><head><title>Just a moment...</title></head></html>"
    assert classify_block(200, {"server": "cloudflare"}, body) is True


def test_plain_503_is_an_outage_not_a_block():
    assert classify_block(503, {}, b"upstream unavailable") is False


def test_503_with_waf_fingerprint_is_a_block():
    assert classify_block(503, {}, b"...Incapsula incident ID: 1234...") is True


def test_ordinary_json_200_is_not_a_block():
    assert classify_block(200, {"content-type": "application/json"}, b'{"issuer":"x"}') is False


# --- fetching -----------------------------------------------------------------


@respx.mock
async def test_fetch_success_records_body_and_hash():
    respx.get("https://example.org/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://example.org/a.json").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with Fetcher(FAST) as f:
        result = await f.fetch("https://example.org/a.json")
    assert result.ok and result.status == 200
    assert result.body_sha256
    assert result.elapsed_ms is not None


@respx.mock
async def test_redirect_chain_is_recorded_and_cross_origin_detected():
    respx.get("https://example.org/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://cdn.other.net/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://example.org/a.json").mock(
        return_value=httpx.Response(302, headers={"location": "https://cdn.other.net/a.json"})
    )
    respx.get("https://cdn.other.net/a.json").mock(return_value=httpx.Response(200, json={}))

    async with Fetcher(FAST) as f:
        result = await f.fetch("https://example.org/a.json")

    assert result.status == 200
    assert len(result.redirect_chain) == 2
    assert result.crossed_origin() is True


@respx.mock
async def test_robots_disallow_removes_endpoint_from_the_study():
    respx.get("https://example.org/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /.well-known/")
    )
    async with Fetcher(FAST) as f:
        result = await f.fetch("https://example.org/.well-known/agent-card.json")
    assert result.error_kind is ErrorKind.ROBOTS_DISALLOWED
    assert result.ok is False


@respx.mock
async def test_missing_robots_txt_means_allowed():
    respx.get("https://example.org/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://example.org/x").mock(return_value=httpx.Response(200, text="hi"))
    async with Fetcher(FAST) as f:
        assert await f.allowed("https://example.org/x") is True


@respx.mock
async def test_blocked_response_is_not_ok_and_is_flagged():
    respx.get("https://example.org/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://example.org/x").mock(return_value=httpx.Response(403, text="nope"))
    async with Fetcher(FAST) as f:
        result = await f.fetch("https://example.org/x")
    assert result.ok is False
    assert result.error_kind is ErrorKind.BLOCKED


@respx.mock
async def test_timeout_is_reported_as_timeout_not_as_a_finding():
    respx.get("https://example.org/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://example.org/x").mock(side_effect=httpx.ReadTimeout("slow"))
    async with Fetcher(FAST) as f:
        result = await f.fetch("https://example.org/x")
    assert result.ok is False
    assert result.error_kind is ErrorKind.TIMEOUT


@respx.mock
async def test_host_failure_budget_stops_hammering_a_blocking_host():
    respx.get("https://example.org/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url__regex=r"https://example\.org/.*").mock(return_value=httpx.Response(403))
    async with Fetcher(FAST) as f:
        for _ in range(4):
            last = await f.fetch("https://example.org/x")
    assert "budget" in last.error_detail


def test_fetcher_requires_context_manager():
    with pytest.raises(RuntimeError):
        import asyncio

        asyncio.get_event_loop().run_until_complete(Fetcher(FAST).fetch("https://x.test/"))
