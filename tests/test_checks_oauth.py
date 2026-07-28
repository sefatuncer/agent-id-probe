"""OAuth-modality check tests, all against mocked transports.

C12 gets the heaviest coverage: it is the study's decisive measurement, it rests on a
MUST, and the interesting cases are the near-misses (trailing slash, different path on
the same host) that a coarse equality test would either forgive or lump together.
"""

import httpx
import respx

from agentidprobe.checks_oauth import canonical_resource_identifier, probe_oauth
from agentidprobe.config import MeasurementConfig, RatePolicy
from agentidprobe.fetcher import ErrorKind, Fetcher, FetchResult
from agentidprobe.models import CheckId, Outcome

FAST = MeasurementConfig(
    rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0)
)

RESOURCE = "https://api.example.org/mcp"
PRM_URL = "https://api.example.org/.well-known/oauth-protected-resource/mcp"
ISSUER = "https://auth.example.org"
AS_URL = "https://auth.example.org/.well-known/oauth-authorization-server"


def _initial(status: int = 401, **kw) -> FetchResult:
    return FetchResult(url=RESOURCE, ok=True, status=status, **kw)


def _no_robots(*hosts: str) -> None:
    for host in hosts:
        respx.get(f"{host}/robots.txt").mock(return_value=httpx.Response(404))


def _outcome(checks, check_id):
    return next(c.outcome for c in checks if c.check_id == check_id)


def _result(checks, check_id):
    return next(c for c in checks if c.check_id == check_id)


# --- canonicalisation ---------------------------------------------------------


def test_canonical_identifier_strips_fragment_and_default_port():
    assert canonical_resource_identifier("https://a.test:443/mcp#x") == "https://a.test/mcp"


def test_canonical_identifier_preserves_non_default_port_and_path():
    assert canonical_resource_identifier("https://a.test:8443/mcp") == "https://a.test:8443/mcp"


# --- applicability ------------------------------------------------------------


async def test_open_endpoint_is_not_applicable_not_a_failure():
    """Authorization is OPTIONAL in MCP. Counting open servers as failures would
    measure composition rather than conformance."""
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial(status=200))
    assert ev.requires_authorization is False
    for cid in (CheckId.PRM_PRESENT, CheckId.PRM_RESOURCE_IDENTITY_MATCH,
                CheckId.AS_CORRESPONDENCE, CheckId.PKCE_DECLARED):
        assert _outcome(checks, cid) is Outcome.NOT_APPLICABLE


async def test_blocked_endpoint_yields_errors_never_failures():
    blocked = FetchResult(url=RESOURCE, ok=False, status=403, error_kind=ErrorKind.BLOCKED)
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, RESOURCE, blocked)
    assert all(c.outcome is Outcome.ERROR for c in checks)


# --- C05 ----------------------------------------------------------------------


@respx.mock
async def test_missing_prm_is_unimplemented():
    _no_robots("https://api.example.org")
    respx.get(url__regex=r".*oauth-protected-resource.*").mock(return_value=httpx.Response(404))
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_PRESENT) is Outcome.FAIL_UNIMPLEMENTED


@respx.mock
async def test_prm_found_at_path_suffixed_location():
    """The root-only probe that review flagged would have scored this as absent."""
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(
        return_value=httpx.Response(
            200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}
        )
    )
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER, "code_challenge_methods_supported": ["S256"]}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_PRESENT) is Outcome.PASS
    assert ev.prm_url == PRM_URL


@respx.mock
async def test_200_with_unparseable_body_is_misimplemented_not_absent():
    _no_robots("https://api.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(200, text="<html>oops</html>"))
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_PRESENT) is Outcome.FAIL_MISIMPLEMENTED


@respx.mock
async def test_empty_authorization_servers_is_misimplemented():
    _no_robots("https://api.example.org")
    respx.get(PRM_URL).mock(
        return_value=httpx.Response(200, json={"resource": RESOURCE, "authorization_servers": []})
    )
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_PRESENT) is Outcome.FAIL_MISIMPLEMENTED


# --- C12: the decisive check --------------------------------------------------


@respx.mock
async def test_c12_passes_on_identical_resource():
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER, "code_challenge_methods_supported": ["S256"]}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.PASS
    assert ev.resource_relation == "identical"


@respx.mock
async def test_c12_trailing_slash_is_a_failure_but_labelled_as_a_near_miss():
    """RFC 9728 says identical. A trailing slash is still a violation, but the paper
    reports how it misses so the taxonomy is informative rather than a bare count."""
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE + "/", "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(200, json={"issuer": ISSUER}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.FAIL_MISIMPLEMENTED
    assert ev.resource_relation == "trailing_slash_only"


@respx.mock
async def test_c12_unrelated_host_is_the_severe_case():
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": "https://someone-else.test/mcp",
                   "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(200, json={"issuer": ISSUER}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert ev.resource_relation == "unrelated_host"
    assert "unrelated_host" in _result(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH).observed_value


@respx.mock
async def test_c12_missing_resource_member_is_unimplemented():
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(200, json={"issuer": ISSUER}))
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.FAIL_UNIMPLEMENTED


# --- C13 / C14 ----------------------------------------------------------------


@respx.mock
async def test_c13_detects_issuer_mismatch():
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": "https://different.example.net"}))
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.AS_CORRESPONDENCE) is Outcome.FAIL_MISIMPLEMENTED


@respx.mock
async def test_c13_tolerates_trailing_slash_on_issuer():
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(200, json={"issuer": ISSUER + "/"}))
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.AS_CORRESPONDENCE) is Outcome.PASS


@respx.mock
async def test_c13_unreachable_issuer_metadata_is_unimplemented():
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}))
    respx.get(url__regex=r"https://auth\.example\.org/\.well-known/.*").mock(
        return_value=httpx.Response(404))
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.AS_CORRESPONDENCE) is Outcome.FAIL_UNIMPLEMENTED
    assert _outcome(checks, CheckId.PKCE_DECLARED) is Outcome.ERROR


@respx.mock
async def test_c14_missing_pkce_declaration():
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(200, json={"issuer": ISSUER}))
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PKCE_DECLARED) is Outcome.FAIL_UNIMPLEMENTED


@respx.mock
async def test_www_authenticate_hint_is_followed_first():
    _no_robots("https://api.example.org", "https://auth.example.org")
    hinted = "https://api.example.org/custom-prm"
    respx.get(hinted).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(200, json={"issuer": ISSUER}))
    initial = _initial(headers={"www-authenticate": f'Bearer resource_metadata="{hinted}"'})
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, initial)
    assert ev.prm_url == hinted
    assert _outcome(checks, CheckId.WWW_AUTH_RESOURCE_METADATA) is Outcome.PASS
