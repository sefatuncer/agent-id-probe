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
ROOT_PRM_URL = "https://api.example.org/.well-known/oauth-protected-resource"
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
    respx.get(ROOT_PRM_URL).mock(return_value=httpx.Response(404))
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_PRESENT) is Outcome.FAIL_MISIMPLEMENTED


@respx.mock
async def test_spa_catch_all_at_path_form_does_not_hide_the_root_document():
    """A single-page app answering 200 with HTML at the path form is common. Stopping
    there would report FAIL_MISIMPLEMENTED for a server whose real metadata is at the
    root form, so every candidate is tried before a verdict is reached."""
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(200, text="<!doctype html><div/>"))
    respx.get(ROOT_PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": "https://api.example.org", "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER, "code_challenge_methods_supported": ["S256"]}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_PRESENT) is Outcome.PASS
    assert ev.prm_url == ROOT_PRM_URL


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
async def test_c12_trailing_slash_is_our_uncertainty_not_their_violation():
    """Inverted on 2026-07-28 (R9.3). The earlier assertion — FAIL — was unsafe, and the
    test suite contradicted itself: the fixture below expects `/mcp/` to PASS when the
    server echoes `/mcp`, while this one expected `/mcp` to FAIL when the server echoes
    `/mcp/`. Both documents are served from the *same* well-known URL, because RFC 9728
    §3.1 strips the terminating slash before inserting the suffix. The instrument cannot
    tell whether the server's identifier is `/mcp` or `/mcp/`, so both readings are
    consistent with conformance and R6 applies: our uncertainty is UNSPECIFIED.

    Scoring it FAIL put an undecidable class into the headline violation rate — exactly
    the "you chose the threshold that favoured your result" objection the frozen rules
    exist to make impossible."""
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE + "/", "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(200, json={"issuer": ISSUER}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.UNSPECIFIED
    assert ev.resource_relation == "trailing_slash_only"


@respx.mock
async def test_c12_case_difference_in_the_path_is_a_real_mismatch():
    """RFC 3986 §6.2.2.1: scheme and host are case-insensitive, every other component is
    case-sensitive. `/MCP` and `/mcp` are different paths, so this is not a near-miss."""
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": "https://api.example.org/MCP",
                   "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(200, json={"issuer": ISSUER}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert ev.resource_relation == "case_path_only"
    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.FAIL_MISIMPLEMENTED


@respx.mock
async def test_c12_root_form_slash_is_equivalent_under_rfc3986():
    """RFC 3986 §6.2.3 lists `http://example.com` and `http://example.com/` among four
    URIs it declares equivalent, so this cannot be a mismatch at all."""
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(ROOT_PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": "https://api.example.org/", "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER, "code_challenge_methods_supported": ["S256"]}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, "https://api.example.org", _initial())
    assert ev.resource_relation == "identical"
    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.PASS


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


@respx.mock
async def test_robots_excluded_metadata_is_never_the_operators_violation():
    """ETHICS.md §6 promises that a document we were not allowed to fetch is recorded as
    unobserved, never written up as the operator's specification violation, and decision
    rule R4 says the same. The AS path honoured this; the PRM path did not — a robots
    exclusion returns status=None, so the candidate loop fell through to "no metadata at
    any candidate location" and charged the operator FAIL_UNIMPLEMENTED for a document our
    own politeness policy stopped us from asking for. That is a bias correlated with the
    property being measured: mature deployments are the ones with a considered robots.txt.
    """
    respx.get("https://api.example.org/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /.well-known/"))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_PRESENT) is Outcome.ERROR
    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.ERROR
    assert ev.robots_excluded_urls
    assert "robots.txt" in _result(checks, CheckId.PRM_PRESENT).detail


# --- R9.1 conformance fixtures ------------------------------------------------
#
# Decision rule R8 requires a known-conforming and a known-violating fixture for every
# MUST-level check. These four are modelled on live deployments that the pre-R9 instrument
# scored wrongly: measured against eight large production MCP endpoints it reported a 75%
# C12 violation rate where the correct rule gives 25%. The expected identifier is not the
# endpoint URL we started from -- it is the one recoverable from the location that actually
# served the document (RFC 9728 §3.3, with §3.1's terminating-slash removal).


@respx.mock
async def test_r9_root_form_expects_the_origin_not_the_endpoint_path():
    """Endpoint has a path, metadata lives at the root, document names the origin.
    Conforming: the document is internally consistent for the identifier it was served
    under. MCP mandates the root fallback, and RFC 9728 §7.6 puts 'does this document
    apply to my path?' explicitly out of scope, so this must not be a C12 failure."""
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(404))
    respx.get(ROOT_PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": "https://api.example.org", "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER, "code_challenge_methods_supported": ["S256"]}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.PASS
    assert ev.expected_resource == "https://api.example.org"
    assert ev.prm_scope_covers_endpoint is False      # recorded, never penalised


@respx.mock
async def test_r9_endpoint_with_trailing_slash_still_expects_the_stripped_form():
    """RFC 9728 §3.1: 'any terminating slash (/) following the host component MUST be
    removed before inserting /.well-known/'. So an endpoint registered as `/mcp/` has its
    metadata at `.../oauth-protected-resource/mcp`, and the identifier to echo back is
    `/mcp` without the slash. Deriving the expectation from the raw endpoint URL made
    every such server look non-conforming."""
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER, "code_challenge_methods_supported": ["S256"]}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE + "/", _initial())
    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.PASS
    assert ev.resource_relation == "identical"


@respx.mock
async def test_r9_explicit_default_port_is_not_an_unrelated_host():
    """A server reflecting its resource back with an explicit :443 is conforming under
    RFC 3986 §6.2.3. Canonicalising only the expected side dropped it into the heaviest
    bucket of the taxonomy -- a false positive aimed squarely at the headline finding."""
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": "https://api.example.org:443/mcp",
                   "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER, "code_challenge_methods_supported": ["S256"]}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert ev.resource_relation == "identical"
    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.PASS


@respx.mock
async def test_r9_host_case_is_normalised_away_not_reported_as_a_miss():
    """RFC 3986 §6.2.2.1: the scheme and host are case-insensitive and should be normalised
    to lowercase. MCP agrees explicitly — 'implementations SHOULD accept uppercase scheme
    and host components for robustness'. So this is the same identifier, not a near-miss,
    and it does not belong in a sensitivity arm either."""
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": "https://API.EXAMPLE.ORG/mcp",
                   "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER, "code_challenge_methods_supported": ["S256"]}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert ev.resource_relation == "identical"
    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.PASS


@respx.mock
async def test_authorization_servers_as_a_bare_string_does_not_become_fifteen_issuers():
    """A JSON string here used to be iterated character by character, producing
    single-letter 'issuers', relative URLs, and a ValueError that escaped every except
    clause -- the endpoint then vanished from the report entirely."""
    _no_robots("https://api.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE, "authorization_servers": ISSUER}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert ev.authorization_servers == []
    assert _outcome(checks, CheckId.PRM_PRESENT) is Outcome.FAIL_MISIMPLEMENTED


# --- R10.2b implementation fingerprint ----------------------------------------


def test_fingerprint_contains_no_values_so_no_placeholder_list_is_needed():
    """The point of R10.2b. Two endpoints running the same SDK differ in every value and
    in nothing else, so a value-free key groups them without anyone deciding which fields
    are 'host-specific' — that decision would be the author-supplied rubric the instrument
    exists to avoid."""
    from agentidprobe.checks_oauth import implementation_fingerprint
    a = implementation_fingerprint(
        {"resource": "https://a.test/mcp", "authorization_servers": ["https://as-a.test"]},
        {"issuer": "https://as-a.test", "code_challenge_methods_supported": ["S256"]},
        "uvicorn")
    b = implementation_fingerprint(
        {"resource": "https://b.test/other", "authorization_servers": ["https://as-b.test"]},
        {"issuer": "https://as-b.test", "code_challenge_methods_supported": ["S256"]},
        "uvicorn")
    assert a == b


def test_fingerprint_does_not_collide_on_differently_shaped_nested_objects():
    """`{"deep": {...}}` and `{"totally": "different"}` both reduced to "object", so two
    unrelated implementations landed in one cluster and every interval computed from that
    clustering was wrong."""
    from agentidprobe.checks_oauth import implementation_fingerprint
    a = implementation_fingerprint({"x": {"nested": [1, 2, 3]}}, None, "uvicorn")
    b = implementation_fingerprint({"x": {"totally": "different", "shape": 1}}, None, "uvicorn")
    assert a != b


def test_fingerprint_ignores_array_contents_because_they_are_values():
    """`scopes_supported: []` and `["read"]` are the same member holding different data.
    Letting the contents change the shape split one SDK across two clusters — a value
    leaking into a key documented as value-free."""
    from agentidprobe.checks_oauth import implementation_fingerprint
    assert implementation_fingerprint({"scopes_supported": []}, None, "uvicorn") == \
        implementation_fingerprint({"scopes_supported": ["read", "write"]}, None, "uvicorn")


def test_fingerprint_ignores_the_server_version():
    """nginx 1.24 and nginx 1.25 are one implementation. Keying on the version repeats the
    mistake that sank the first fingerprint design: clustering on something that varies
    with the deployment rather than with the code."""
    from agentidprobe.checks_oauth import implementation_fingerprint
    doc = {"resource": "https://a.test/mcp"}
    assert implementation_fingerprint(doc, None, "nginx/1.24.0") == \
        implementation_fingerprint(doc, None, "nginx/1.25.3")
    assert implementation_fingerprint(doc, None, "nginx/1.24.0") != \
        implementation_fingerprint(doc, None, "uvicorn")


def test_fingerprint_separates_different_member_sets():
    from agentidprobe.checks_oauth import implementation_fingerprint
    a = implementation_fingerprint({"resource": "https://a.test"}, None, "uvicorn")
    b = implementation_fingerprint(
        {"resource": "https://a.test", "scopes_supported": ["x"]}, None, "uvicorn")
    assert a != b


def test_fingerprint_without_server_header_is_reported_alongside():
    """The `server` header is the one hand-made input, so R10.2b requires both clusterings
    to be reported and the code must therefore be able to produce both."""
    from agentidprobe.checks_oauth import implementation_fingerprint
    doc = {"resource": "https://a.test/mcp"}
    assert implementation_fingerprint(doc, None, "uvicorn", include_server=False) == \
        implementation_fingerprint(doc, None, "cloudflare", include_server=False)
    assert implementation_fingerprint(doc, None, "uvicorn") != \
        implementation_fingerprint(doc, None, "cloudflare")


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
async def test_c13_does_not_forgive_a_trailing_slash_on_issuer():
    """Inverted on 2026-07-28 (decision rule R9.4). The old assertion froze a leniency
    that has no basis in the specification: RFC 8414 §3.3 requires the returned issuer to
    be identical, and §4 requires the comparison to be a Unicode code-point-to-code-point
    equality with no normalisation applied. Forgiving the slash discarded real, mechanically
    detectable MUST violations -- and it was the opposite of what C12 did to the same class
    of near-miss, which is an asymmetry no reviewer would accept."""
    tenant = "https://auth.example.org/tenant1"
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE, "authorization_servers": [tenant]}))
    respx.get(url__regex=r"https://auth\.example\.org/.*").mock(
        return_value=httpx.Response(200, json={"issuer": tenant + "/"}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.AS_CORRESPONDENCE) is Outcome.FAIL_MISIMPLEMENTED
    assert ev.as_issuer_relations[tenant] == "trailing_slash_only"


@respx.mock
async def test_c13_root_issuer_slash_is_rfc3986_equivalence_not_a_violation():
    """RFC 3986 §6.2.3 names `http://example.com` and `http://example.com/` as equivalent
    URIs. A root issuer differing only by that slash is the same identifier, so this is
    normalised away in both checks — unlike a slash on a *path-bearing* issuer, which is a
    real difference the test above still catches."""
    _no_robots("https://api.example.org", "https://auth.example.org")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER + "/", "code_challenge_methods_supported": ["S256"]}))
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.AS_CORRESPONDENCE) is Outcome.PASS
    assert ev.as_issuer_relations[ISSUER] == "identical"


@respx.mock
async def test_c13_one_live_issuer_does_not_excuse_the_dead_ones():
    """A resource naming several issuers of which most are dead is the thesis in
    miniature. Scoring it PASS because one answered would discard the finding."""
    _no_robots("https://api.example.org", "https://auth.example.org", "https://dead.example.net")
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE,
                   "authorization_servers": [ISSUER, "https://dead.example.net"]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER, "code_challenge_methods_supported": ["S256"]}))
    respx.get(url__regex=r"https://dead\.example\.net/.*").mock(
        return_value=httpx.Response(404))
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, RESOURCE, _initial())
    assert _outcome(checks, CheckId.AS_CORRESPONDENCE) is Outcome.FAIL_UNIMPLEMENTED


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
    # Descriptive since 29 July 2026: an absent element is permitted by RFC 8414 §2 and
    # by RFC 9700 §2.1.1's "MAY instead provide a deployment-specific way", so the
    # instrument records it without convicting the issuer of anything.
    assert _outcome(checks, CheckId.PKCE_DECLARED) is Outcome.UNSPECIFIED


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
