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


# --- opt-out (ETHICS.md 7) ----------------------------------------------------


def test_opt_out_file_is_found_by_explicit_root_and_by_env_var(tmp_path, monkeypatch):
    """Resolving the list only relative to this module found the repository from a
    checkout and found nothing from an installed wheel — where it returned an empty set
    silently, disabling the ethics gate for anyone who ran `pip install`. Two states that
    must never look alike: "nobody opted out" and "the list is missing"."""
    from agentidprobe.config import load_opt_out
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "opt-out.txt").write_text(
        "# a comment\n\nexample.com\n  MCP.Example.ORG.  # trailing dot and case\n",
        encoding="utf-8",
    )
    assert load_opt_out(tmp_path) == frozenset({"example.com", "mcp.example.org"})

    monkeypatch.setenv("AGENT_ID_PROBE_OPT_OUT", str(docs / "opt-out.txt"))
    assert "example.com" in load_opt_out()


def test_opt_out_covers_subdomains_because_it_is_about_an_operator():
    from agentidprobe.config import is_opted_out
    opted = frozenset({"example.com", "mcp.other.org"})
    assert is_opted_out("https://example.com/mcp", opted) is True
    assert is_opted_out("https://deep.sub.example.com/mcp", opted) is True
    assert is_opted_out("https://mcp.other.org/x", opted) is True
    assert is_opted_out("https://other.org/x", opted) is False       # host-level entry
    assert is_opted_out("https://notexample.com/x", opted) is False  # suffix, not a label
    assert is_opted_out("https://anything.test/x", frozenset()) is False


@respx.mock
async def test_opted_out_host_is_not_contacted_at_all_not_even_robots():
    """The gate lives in the fetcher rather than in corpus filtering, so that no call path
    -- a declared jwks_uri, a WWW-Authenticate hint, a redirect -- can route around it. If
    any request were made, respx would raise on the unmocked route."""
    from agentidprobe.config import MeasurementConfig
    config = MeasurementConfig(
        rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0),
        opted_out=frozenset({"example.com"}),
    )
    async with Fetcher(config) as f:
        result = await f.fetch("https://mcp.example.com/.well-known/oauth-protected-resource")
    assert result.error_kind is ErrorKind.OPTED_OUT
    assert result.status is None


# --- block classification (R4) ------------------------------------------------


def test_429_is_always_a_block():
    assert classify_block(429, {}, b"") is True


def test_mcp_403_with_an_oauth_challenge_is_an_answer_not_a_block():
    """Amended 2026-07-28. The MCP authorization spec lists `403 Forbidden — Invalid scopes
    or insufficient permissions` in its own error table, so a 403 is frequently the MCP
    server answering. Classifying every 403 as a WAF discarded those endpoints as ERROR and
    left the `status in (401, 403)` branch in checks_oauth unreachable — the
    authorization-requiring population the pilot reported as "37.9% (401/403)" could not be
    reproduced by the code meant to measure it."""
    assert classify_block(
        403,
        {"WWW-Authenticate": 'Bearer error="insufficient_scope", scope="files:read"',
         "Content-Type": "application/json"},
        b'{"error":"insufficient_scope"}',
    ) is False


def test_json_403_is_an_answer_not_a_block():
    assert classify_block(
        403, {"Content-Type": "application/json"}, b'{"error":"forbidden"}'
    ) is False


def test_waf_403_interstitial_is_still_a_block():
    assert classify_block(
        403,
        {"Content-Type": "text/html", "Server": "cloudflare"},
        b"<html><title>403 Forbidden</title>Attention Required!</html>",
    ) is True


def test_ambiguous_403_stays_a_block():
    """R4 is deliberately asymmetric: scoring a WAF page as a specification failure writes
    a violation against an operator we never observed, while scoring a genuine 403 as a
    block costs one observation. With no positive evidence the origin answered, stay safe."""
    assert classify_block(403, {"Content-Type": "text/html"}, b"<html>Forbidden</html>") is True
    assert classify_block(403, {}, b"") is True


def test_401_and_404_are_genuine_answers_not_blocks():
    """A 401 is the single most informative response in this study: it means the
    endpoint opted into authorization and C05 becomes applicable."""
    assert classify_block(401, {}, b"") is False
    assert classify_block(404, {}, b"") is False
    assert classify_block(410, {}, b"") is False


def test_cloudflare_challenge_served_with_200_is_a_block():
    body = b"<html><head><title>Just a moment...</title></head></html>"
    headers = {"server": "cloudflare", "content-type": "text/html; charset=UTF-8"}
    assert classify_block(200, headers, body) is True


def test_plain_503_is_an_outage_not_a_block():
    assert classify_block(503, {}, b"upstream unavailable") is False


def test_503_html_interstitial_is_a_block():
    headers = {"content-type": "text/html"}
    assert classify_block(503, headers, b"...Incapsula incident ID: 1234...") is True


def test_503_with_waf_specific_header_is_a_block():
    assert classify_block(503, {"x-datadome": "protected"}, b"") is True


def test_503_from_a_cdn_backed_origin_is_still_just_an_outage():
    """CDN use correlates with operational maturity, so classifying `server: cloudflare`
    alone as a block would systematically drop the more mature half of the population —
    the opposite of what decision rule R4 exists to prevent."""
    assert classify_block(503, {"server": "cloudflare"}, b"upstream error") is False


def test_ordinary_json_200_is_not_a_block():
    assert classify_block(200, {"content-type": "application/json"}, b'{"issuer":"x"}') is False


def test_json_error_payload_mentioning_access_denied_is_not_a_block():
    """The origin is talking. Misreading it as a WAF both drops the endpoint from the
    denominator and charges it against the host failure budget, which can evict every
    other endpoint on the same host."""
    headers = {"content-type": "application/json"}
    assert classify_block(200, headers, b'{"error":"Access denied","code":403}') is False
    assert classify_block(200, headers, b'{"detail":"Request blocked by policy"}') is False


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
