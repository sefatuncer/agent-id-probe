"""The safeguards this study promises third parties, tested rather than asserted.

Every defect covered here shipped and survived because nothing exercised it. `docs/ETHICS.md`
§11 had the opt-out and the abort threshold ticked off as satisfied while an audit found
that neither actually did anything — the opt-out wrote a MUST-level failure against the
operator who requested it, and the kill switch let all 250 endpoints of a synthetic run
through. A promise made to someone else needs a test, not a checkbox.
"""

import asyncio

import httpx
import pytest
import respx

from agentidprobe.checks_oauth import probe_oauth
from agentidprobe.collectors import apex_domain, endpoint_id
from agentidprobe.config import AbortPolicy, MeasurementConfig, RatePolicy
from agentidprobe.fetcher import Fetcher, FetchResult
from agentidprobe.models import CheckId, Endpoint, EndpointKind, Modality, Outcome
from agentidprobe.runner import Runner, summarise
from agentidprobe.store import RunStore

FAST = MeasurementConfig(
    rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0)
)


def _endpoint(url: str) -> Endpoint:
    return Endpoint(endpoint_id=endpoint_id(url), url=url, kind=EndpointKind.MCP_REMOTE,
                    source="t", apex_domain=apex_domain(url))


# --- the kill switch ----------------------------------------------------------


class _SlowRunner(Runner):
    """Counts probes and suspends in each one, so ordering is realistic.

    The original defect was invisible without this: `respx` resolves synchronously, so a
    test using it let every worker finish before the next began and the abort appeared to
    work. Real network I/O suspends, every task reaches its abort check on the first pass
    through the event loop, and the flag is still unset.
    """

    def __init__(self, *args, fail_from: int = 0, **kwargs):
        super().__init__(*args, **kwargs)
        self.probed = 0
        self.fail_from = fail_from

    async def _probe_one(self, fetcher, endpoint, modality):
        await asyncio.sleep(0)
        self.probed += 1
        from datetime import UTC, datetime

        from agentidprobe.models import EndpointReport
        return EndpointReport(
            endpoint=endpoint, modality=modality,
            reachable=self.probed < self.fail_from,
            checks=[], probed_at=datetime.now(UTC), run_id="r1",
        )


async def test_the_abort_actually_stops_endpoints_from_being_contacted(tmp_path):
    """The point of a kill switch is the requests it prevents. Building a task per endpoint
    up front meant all of them passed the abort check before any result existed, so the
    flag rose at endpoint 200 and spared exactly none of the remaining 50."""
    config = MeasurementConfig(
        rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0, global_concurrency=8),
        abort=AbortPolicy(min_endpoints_before_abort=20, max_failure_fraction=0.25),
    )
    endpoints = [_endpoint(f"https://h{i}-example.org/mcp") for i in range(250)]
    runner = _SlowRunner(RunStore(tmp_path, "r1"), config, fail_from=1)

    reports = await runner.run(endpoints, Modality.OAUTH_METADATA, progress_every=0)

    assert runner._aborted, "the abort threshold was never reached"
    assert runner.probed < len(endpoints), (
        f"the kill switch prevented nothing: {runner.probed} of {len(endpoints)} probed"
    )
    assert runner._skipped > 0
    assert runner.probed + runner._skipped == len(endpoints)
    assert len(reports) == runner.probed


async def test_a_healthy_run_is_never_aborted(tmp_path):
    config = MeasurementConfig(
        rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0, global_concurrency=8),
        abort=AbortPolicy(min_endpoints_before_abort=20, max_failure_fraction=0.25),
    )
    endpoints = [_endpoint(f"https://ok{i}-example.org/mcp") for i in range(60)]
    runner = _SlowRunner(RunStore(tmp_path, "r1"), config, fail_from=10_000)
    reports = await runner.run(endpoints, Modality.OAUTH_METADATA, progress_every=0)
    assert not runner._aborted
    assert len(reports) == 60


# --- opt-out ------------------------------------------------------------------


@respx.mock
async def test_an_opted_out_operator_is_never_charged_with_a_violation():
    """docs/ETHICS.md §7 promises removal on request. Scoring the resulting silence as
    `C05 fail_unimplemented` charges the operator for a document we deliberately did not
    ask for — the same class of defect as the robots.txt one, on the branch that was added
    later and missed."""
    config = MeasurementConfig(
        rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0),
        opted_out=frozenset({"quiet-example.org"}),
    )
    async with Fetcher(config) as f:
        initial = FetchResult(url="https://quiet-example.org/mcp", ok=True, status=401)
        checks, ev = await probe_oauth(f, "https://quiet-example.org/mcp", initial)

    for check_id in (CheckId.PRM_PRESENT, CheckId.PRM_RESOURCE_IDENTITY_MATCH,
                     CheckId.AS_CORRESPONDENCE):
        assert _outcome(checks, check_id) is Outcome.ERROR, f"{check_id} penalised an opt-out"


@respx.mock
async def test_an_opted_out_issuer_is_not_scored_as_an_unreachable_one():
    """C13 reports FAIL_UNIMPLEMENTED when no declared issuer serves metadata. An issuer we
    chose not to contact has not failed to serve anything."""
    config = MeasurementConfig(
        rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0),
        opted_out=frozenset({"quiet-idp-example.org"}),
    )
    respx.get("https://api-example.org/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://api-example.org/.well-known/oauth-protected-resource/mcp").mock(
        return_value=httpx.Response(200, json={
            "resource": "https://api-example.org/mcp",
            "authorization_servers": ["https://quiet-idp-example.org"]}))
    async with Fetcher(config) as f:
        initial = FetchResult(url="https://api-example.org/mcp", ok=True, status=401)
        checks, _ = await probe_oauth(f, "https://api-example.org/mcp", initial)
    assert _outcome(checks, CheckId.AS_CORRESPONDENCE) is not Outcome.FAIL_UNIMPLEMENTED


def test_opted_out_endpoints_leave_every_denominator_and_are_counted(tmp_path):
    from datetime import UTC, datetime

    from agentidprobe.models import EndpointReport

    def report(url, opted_out=False):
        return EndpointReport(
            endpoint=_endpoint(url), modality=Modality.OAUTH_METADATA,
            reachable=not opted_out, opted_out=opted_out, checks=[],
            probed_at=datetime.now(UTC), run_id="r1",
        )

    out = summarise([report("https://a-example.org/mcp"),
                     report("https://quiet-example.org/mcp", opted_out=True)])
    oauth = out["modalities"]["oauth_metadata"]
    assert oauth["total"] == 2
    assert oauth["excluded_opt_out"] == 1
    assert oauth["in_scope"] == 1
    assert oauth["funnel"][0]["eligible"] == 1


def test_cross_origin_documents_are_not_attributed_to_the_host_we_asked(tmp_path):
    """A frozen denominator rule that nothing implemented: `crossed_origin()` was defined,
    tested, and never called from production code. A document served after a redirect to
    another origin describes whoever answered, so scoring it against the endpoint we asked
    about attributes someone else's conformance — or someone else's failure — to them."""
    from datetime import UTC, datetime

    from agentidprobe.models import EndpointReport

    def report(url, final_url=None):
        return EndpointReport(
            endpoint=_endpoint(url), modality=Modality.OAUTH_METADATA, reachable=True,
            final_url=final_url, redirect_chain=[url] if final_url else [],
            checks=[], probed_at=datetime.now(UTC), run_id="r1",
        )

    out = summarise([
        report("https://a-example.org/mcp"),
        report("https://b-example.org/mcp", final_url="https://elsewhere-example.net/mcp"),
    ])
    oauth = out["modalities"]["oauth_metadata"]
    assert oauth["excluded_crossed_origin"] == 1
    assert oauth["in_scope"] == 1
    assert oauth["funnel"][0]["eligible"] == 1


# --- the WWW-Authenticate hint ------------------------------------------------


@pytest.mark.parametrize("hint,followable", [
    ("https://api-example.org/.well-known/oauth-protected-resource", True),
    ("https://sub.api-example.org/prm", True),          # same registrable domain
    ("http://api-example.org/prm", False),              # plaintext
    ("http://127.0.0.1:8080/admin", False),             # loopback: SSRF shape
    ("https://127.0.0.1:8080/admin", False),
    ("http://192.168.1.1/prm", False),                  # private address
    ("https://attacker-example.net/prm", False),        # third party
    ("https://api-example.org.evil-example.net/prm", False),   # suffix trick
])
def test_only_hints_that_stay_with_the_operator_are_followed(hint, followable):
    """A `WWW-Authenticate: resource_metadata` value is input from the host being measured.
    Accepting anything starting with "http" sent requests from the author's home network to
    loopback and RFC 1918 addresses — neither of which appears in the scope statement this
    study publishes to operators."""
    from agentidprobe.checks_oauth import _hint_is_followable
    assert _hint_is_followable(hint, "https://api-example.org/mcp") is followable


@respx.mock
async def test_a_hostile_hint_cannot_inject_an_edge_into_the_issuer_graph():
    """The severe half of the defect. A document fetched from an attacker's host was
    attributed to the victim endpoint, scored C12 PASS because the hint path compares
    against the client's own request URL, and wrote the attacker's issuer into the
    resource -> issuer graph that is this paper's headline figure."""
    victim = "https://victim-example.org/mcp"
    respx.get("https://victim-example.org/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url__regex=r"https://victim-example\.org/\.well-known/.*").mock(
        return_value=httpx.Response(404))
    attacker = respx.get("https://attacker-example.net/prm").mock(
        return_value=httpx.Response(200, json={
            "resource": victim, "authorization_servers": ["https://attacker-idp-example.net"]}))

    initial = FetchResult(
        url=victim, ok=True, status=401,
        headers={"www-authenticate": 'Bearer resource_metadata="https://attacker-example.net/prm"'},
    )
    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, victim, initial)

    assert not attacker.called, "the attacker's host was contacted"
    assert ev.authorization_servers == []
    assert ev.hint_rejected_reason is not None
    assert _outcome(checks, CheckId.PRM_PRESENT) is Outcome.FAIL_UNIMPLEMENTED


def _outcome(checks, check_id):
    return next((c.outcome for c in checks if c.check_id == check_id), None)


# --- the request budget is ours, not the measured party's ---------------------


def _prm_mock(issuers: list[str]) -> None:
    """A resource whose protected-resource metadata declares `issuers`.

    Every issuer host is mocked as reachable, so that a host which is *not* contacted is
    the instrument's decision rather than an artefact of the test setup.
    """
    respx.get(url__regex=r"https://[\w.-]+/robots\.txt").mock(
        return_value=httpx.Response(404))
    respx.get(url__regex=r"https://[\w.-]+/\.well-known/(oauth-authorization-server|"
                         r"openid-configuration)").mock(
        return_value=httpx.Response(200, json={"issuer": "https://unused.example.net"}))
    respx.get(
        "https://api.example.org/.well-known/oauth-protected-resource/mcp"
    ).mock(return_value=httpx.Response(200, json={
        "resource": "https://api.example.org/mcp", "authorization_servers": issuers,
    }))


def _initial() -> FetchResult:
    return FetchResult(url="https://api.example.org/mcp", ok=True, status=401)


@respx.mock
async def test_a_declared_issuer_list_cannot_dictate_how_many_requests_we_send():
    """`authorization_servers` is written by the host being measured.

    Until 29 July 2026 the loop iterated it with no cap, at up to three candidate URLs
    each, so a document declaring 200 issuers commanded 600 fetches aimed wherever it
    liked. The bound in README.md and ETHICS.md was a sentence with no code behind it.
    """
    issuers = [f"https://idp{i:03d}.example.net" for i in range(60)]
    _prm_mock(issuers)
    seen: set[str] = set()

    def record(result: FetchResult) -> None:
        seen.add(result.url)

    async with Fetcher(FAST, on_fetch=record) as f:
        _, ev = await probe_oauth(f, "https://api.example.org/mcp", _initial())

    cap = FAST.rate.max_issuers_fetched_per_endpoint
    # Asserted against a literal, not against the configured value. Reading the cap out of
    # config and checking consistency with it is self-referential: that version of this
    # test passed with the cap set to 60, and would pass with it set to a million.
    assert cap <= 25, "the per-endpoint issuer cap is no longer a meaningful bound"

    contacted = {u.split("/.well-known")[0] for u in seen if "idp" in u}
    assert len(contacted) == cap, f"contacted {len(contacted)} issuer hosts, cap is {cap}"
    # Every declared issuer is still recorded: the declaration is the observation, and the
    # resource -> issuer graph must not silently lose 50 edges because we declined to fetch.
    assert len(ev.authorization_servers) == 60
    assert len(ev.as_not_fetched) == 60 - cap


@respx.mock
async def test_we_never_request_a_declared_issuer_that_is_not_a_public_https_host():
    """The SSRF-shaped half of the same defect.

    The filter accepted any `http`/`https` URL with a netloc, so a declared issuer of
    `http://127.0.0.1:8080` was fetched in plain text from the measurement's own
    residential line. The identical hole was closed for the WWW-Authenticate hint in the
    same week and this, much larger, path was missed.
    """
    hostile = [
        "http://plain.example.net",          # not https
        "https://127.0.0.1:8080",            # loopback
        "https://10.0.0.5",                  # RFC 1918
        "https://localhost:9000",            # special-use
        "https://good.example.net",          # the only one we should touch
    ]
    _prm_mock(hostile)
    seen: set[str] = set()

    async with Fetcher(FAST, on_fetch=lambda r: seen.add(r.url)) as f:
        _, ev = await probe_oauth(f, "https://api.example.org/mcp", _initial())

    for forbidden in ("127.0.0.1", "10.0.0.5", "localhost", "plain.example.net"):
        assert not any(forbidden in u for u in seen), f"requested {forbidden}"
    assert set(ev.as_not_fetched) == set(hostile[:4])


@respx.mock
async def test_declining_to_look_is_never_written_up_as_the_operators_violation():
    """R4/R6, in the branch added with the cap.

    The robots and opt-out branches each shipped this bug once: our own policy produced a
    MUST-level failure against the party we had chosen not to observe. The scope policy is
    the same class of decision and must land in the same place.
    """
    _prm_mock(["https://127.0.0.1:8080", "https://10.0.0.5"])

    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, "https://api.example.org/mcp", _initial())

    outcome = next(c.outcome for c in checks if c.check_id is CheckId.AS_CORRESPONDENCE)
    assert outcome is Outcome.ERROR, f"declining to look produced {outcome}"
    assert not ev.as_documents


@respx.mock
async def test_a_cross_operator_issuer_is_still_fetched():
    """The guard must not quietly delete the finding it exists beside.

    A resource naming an issuer it does not operate is this study's entire subject, so the
    issuer policy deliberately does not carry the hint rule's same-apex requirement. If it
    did, every cross-operator edge would vanish and the headline would read 0%.
    """
    _prm_mock(["https://auth.somebodyelse.example.net"])
    respx.get("https://auth.somebodyelse.example.net/robots.txt").mock(
        return_value=httpx.Response(404))
    respx.get(
        "https://auth.somebodyelse.example.net/.well-known/oauth-authorization-server"
    ).mock(return_value=httpx.Response(200, json={
        "issuer": "https://auth.somebodyelse.example.net"}))

    async with Fetcher(FAST) as f:
        _, ev = await probe_oauth(f, "https://api.example.org/mcp", _initial())

    assert "https://auth.somebodyelse.example.net" in ev.as_documents
    assert not ev.as_not_fetched


@respx.mock
async def test_no_single_host_receives_more_than_the_published_ceiling():
    """Capping issuers is not capping hosts, and the review proved the difference.

    Ten declared issuers can be ten paths or ten ports on one machine. Measured before the
    fix: 31 requests to that one host nominally, 91 with retries, 121 with a redirect chain.
    Nothing accumulated across endpoints either, so 200 endpoints naming one popular issuer
    delivered 401 requests to it -- and issuer concentration is one of this study's own
    headline candidates, so the most-named host is by construction the most-hit host.

    The ceiling is asserted against a literal. Reading it out of config would pass with the
    ceiling set to a million, which is how the first version of the issuer-cap test passed
    with the cap set to 60.
    """
    ceiling = FAST.rate.max_requests_per_host
    assert ceiling <= 40, "the per-host ceiling is no longer a meaningful bound"

    issuers = [f"https://one.example.net/t{i}" for i in range(10)]
    _prm_mock(issuers)
    respx.get(url__regex=r"https://one\.example\.net/.*").mock(
        return_value=httpx.Response(404))

    async with Fetcher(FAST) as f:
        await probe_oauth(f, "https://api.example.org/mcp", _initial())
        sent = dict(f._host_requests)

    assert sent["one.example.net"] <= ceiling, (
        f"one host received {sent['one.example.net']} requests, ceiling is {ceiling}"
    )


@respx.mock
async def test_a_redirect_cannot_walk_out_of_the_public_web():
    """The gate ran once, against the URL we chose, and then httpx followed three hops.

    Measured before the fix: a declared issuer answering 302 to
    `http://127.0.0.1:8080/admin/metadata` produced exactly that request -- plain text,
    loopback, from a residential line -- and the response was stored as evidence and scored.
    `169.254.169.254` behaved the same way, which on a cloud VM is the instance metadata
    service, and this artefact ships under CC BY 4.0.
    """
    for target in ("http://127.0.0.1:8080/admin/metadata",
                   "http://169.254.169.254/latest/meta-data/",
                   "https://10.0.0.5/metadata"):
        respx.clear()
        # Registered before the catch-alls: respx resolves in registration order, so the
        # redirect has to be declared first or a permissive mock answers instead of it and
        # the test passes for the wrong reason.
        respx.get(
            url__regex=r"https://redir\.example\.net/\.well-known/.*"
        ).mock(return_value=httpx.Response(302, headers={"Location": target}))
        respx.get(url__regex=r"https?://.+/robots\.txt").mock(
            return_value=httpx.Response(404))
        respx.get("https://api.example.org/.well-known/oauth-protected-resource/mcp").mock(
            return_value=httpx.Response(200, json={
                "resource": "https://api.example.org/mcp",
                "authorization_servers": ["https://redir.example.net"]}))
        # The forbidden destinations are mocked as *available*, so that not reaching them is
        # the instrument's refusal rather than an unroutable address.
        respx.get(url__regex=r"https?://(127\.0\.0\.1|169\.254\.169\.254|10\.0\.0\.5).*").mock(
            return_value=httpx.Response(200, json={"issuer": "https://redir.example.net"}))

        seen: list[str] = []

        def record(result: FetchResult, sink: list[str] = seen) -> None:
            sink.append(result.url)

        async with Fetcher(FAST, on_fetch=record) as f:
            _, ev = await probe_oauth(f, "https://api.example.org/mcp", _initial())

        assert not any(bad in u for u in seen
                       for bad in ("127.0.0.1", "169.254", "10.0.0.5")), target
        assert not ev.as_documents, f"a refused redirect produced evidence: {target}"


@respx.mock
async def test_the_per_host_ceiling_does_not_truncate_the_corpus():
    """A safeguard that shrinks the population it protects is worse than none.

    The per-host ceiling added on 30 July 2026 counted the registry too. `collect`
    paginates one host several hundred times by design, so the 31st page returned
    OUT_OF_SCOPE, the collector saw a non-200 and stopped, and the census ended at roughly
    three thousand records with a single line in the manifest to say so. The exemption is
    `Scope.unmetered_hosts` and it lifts the aggregate count only -- the throttle, robots,
    the opt-out list and the failure budget all still apply to those hosts.
    """
    from agentidprobe.collectors import McpOfficialRegistry

    pages = {"n": 0}
    total = FAST.rate.max_requests_per_host * 3        # comfortably past the ceiling

    def page(request):
        pages["n"] += 1
        last = pages["n"] >= total
        return httpx.Response(200, json={
            "servers": [{"name": f"io.github.x/s{pages['n']}",
                         "remotes": [{"url": f"https://h{pages['n']}-example.org/mcp"}]}],
            "metadata": {} if last else {"next_cursor": f"c{pages['n']}"},
        })

    respx.get(url__regex=r".*/robots\.txt").mock(return_value=httpx.Response(404))
    respx.get(url__regex=r"https://registry\.modelcontextprotocol\.io/v0/servers.*").mock(
        side_effect=page)

    async with Fetcher(FAST) as f:
        registry = McpOfficialRegistry(f, max_pages=total + 10)
        endpoints = await registry.collect()

    assert pages["n"] == total, f"pagination stopped after {pages['n']} of {total} pages"
    assert len(endpoints) == total
    assert not registry.stats.errors, registry.stats.errors
