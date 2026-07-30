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
from agentidprobe.fetcher import ErrorKind, Fetcher, FetchResult
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


# --- D7: the accepting direction, which nothing pinned -------------------------


LEGITIMATE_ISSUERS = (
    ("https://as.example.org", "the ordinary case"),
    ("https://as.example.org:8443", "a non-default port is not a defect"),
    ("https://as.example.org/tenant/1", "RFC 8414 issuers may carry a path"),
    ("https://login.eu.as.example.org", "arbitrarily deep sub-domains"),
    ("https://xn--bcher-kva.example.org", "an IDN in punycode form"),
    ("https://as.example.org/", "a terminating slash"),
    ("https://AS.Example.ORG", "mixed case in the host (RFC 3986 6.2.2.1)"),
    ("https://as.example.co.uk", "a multi-label public suffix"),
    ("https://as.example.org/a?b=c", "a query component"),
)


@pytest.mark.parametrize("issuer,why", LEGITIMATE_ISSUERS, ids=[i for i, _ in LEGITIMATE_ISSUERS])
def test_a_legitimate_issuer_is_not_withheld(issuer: str, why: str) -> None:
    """Defect D7, reported by an adversarial review on 30 July 2026.

    The issuer filter had tests for everything it must refuse -- loopback, RFC 1918,
    special-use names, plain http -- and nothing for what it must *accept*. An
    implementation that also rejected a port-carrying or IDN issuer would have passed the
    entire suite, and a forgiving-in-one-direction rule needs both directions pinned or the
    test only proves it is strict.

    This got sharper the same day D8 was fixed. A withheld issuer now *leaves* the
    denominator instead of counting as "does not advertise", which is correct -- and it means
    over-rejection no longer shows up as a bad rate. It shows up as a smaller population, and
    a smaller population is exactly what a study of an under-deployed mechanism expects to
    see. The two changes compound: without this test, an over-strict filter would be
    invisible in the output and would look like a finding.
    """
    from agentidprobe.checks_oauth import _issuer_rejection_reason

    assert _issuer_rejection_reason(issuer) is None, (
        f"withheld a legitimate issuer ({why}): {_issuer_rejection_reason(issuer)}"
    )


@respx.mock
async def test_an_issuer_on_a_nonstandard_port_is_actually_requested_and_scored() -> None:
    """The filter accepting it is necessary but not sufficient: the request has to happen.

    Asserted end to end rather than on the predicate, because the predicate is one of three
    gates the issuer passes through -- scheme check, per-endpoint cap, per-host ceiling -- and
    a shape can be admitted by the first and dropped by the arithmetic in the others.
    """
    issuer = "https://as.example.org:8443"
    _prm_mock([issuer])
    respx.get(f"{issuer}/.well-known/oauth-authorization-server").mock(
        return_value=httpx.Response(200, json={"issuer": issuer})
    )

    async with Fetcher(FAST) as f:
        checks, ev = await probe_oauth(f, "https://api.example.org/mcp", _initial())

    assert not ev.as_not_fetched, f"withheld {ev.as_not_fetched}"
    assert ev.as_issuer_relations == {issuer: "identical"}
    assert _outcome(checks, CheckId.AS_CORRESPONDENCE) is Outcome.PASS


# --- the narrow-slice rehearsal must not be biased by corpus order -------------


def _corpus_endpoint(url: str, apex: str | None):
    return Endpoint(endpoint_id=endpoint_id(url), url=url, apex_domain=apex,
                    kind=EndpointKind.MCP_REMOTE, source="t")


def test_the_rehearsal_slice_spreads_across_apexes_instead_of_taking_the_first_n():
    """ETHICS.md §11.3's rehearsal, and why `--limit` could not serve it.

    `--limit N` takes the first N in corpus order, which is the registry's pagination order --
    broadly newest-first. Recency correlates with operational maturity, maturity correlates
    with sitting behind a WAF, and the block rate is the single number the rehearsal exists to
    produce. So the cheapest way to take a slice would have biased the one measurement that
    decides whether the full run proceeds.

    A bulk publisher with hundreds of listings is the other half: a naive sample of 200 can be
    a handful of operators, and the rehearsal is about how *hosts* respond to us.
    """
    from agentidprobe.runner import rehearsal_slice

    endpoints = (
        [_corpus_endpoint(f"https://bulk.example.com/mcp/{i}", "bulk.example.com")
         for i in range(300)]
        + [_corpus_endpoint(f"https://op{i}.example.org/mcp", f"op{i}.example.org")
           for i in range(50)]
    )
    chosen = rehearsal_slice(endpoints, 40)

    assert len(chosen) == 40
    apexes = [e.apex_domain for e in chosen]
    assert len(set(apexes)) == 40, "one endpoint per apex before a second from any"
    assert apexes.count("bulk.example.com") == 1, (
        "a bulk publisher must not be able to fill the rehearsal"
    )


def test_the_rehearsal_slice_is_deterministic_and_ignores_corpus_order():
    """Reproducible without a stored seed, and unchanged by how the registry paginated.

    Selection is by `endpoint_id`, already a SHA-256 prefix of the URL. `random.sample` would
    have given neither property, and R8's determinism requirement needs both: the same corpus
    must yield the same slice, so that a re-run is a re-run.
    """
    from agentidprobe.runner import rehearsal_slice

    endpoints = [_corpus_endpoint(f"https://op{i}.example.org/mcp", f"op{i}.example.org")
                 for i in range(80)]

    first = [e.endpoint_id for e in rehearsal_slice(endpoints, 20)]
    again = [e.endpoint_id for e in rehearsal_slice(endpoints, 20)]
    reversed_corpus = [e.endpoint_id for e in rehearsal_slice(list(reversed(endpoints)), 20)]

    assert first == again
    assert first == reversed_corpus, "the slice must not depend on registry pagination order"


def test_endpoints_with_no_resolvable_apex_each_count_as_their_own_operator():
    """The conservative reading, and the one that keeps them observable.

    A null apex means we cannot tell one operator from another. Grouping them together would
    let a single unresolvable host crowd out every other one; giving each its own group keeps
    the class represented, which matters because `dropped_no_apex` is a counter the frame
    analysis reads.
    """
    from agentidprobe.runner import rehearsal_slice

    endpoints = [_corpus_endpoint(f"https://10.0.0.{i}/mcp", None) for i in range(1, 11)]
    chosen = rehearsal_slice(endpoints, 5)
    assert len({e.endpoint_id for e in chosen}) == 5


# --- a response that never ends must not hold the run -------------------------


async def test_an_endless_response_hits_a_total_deadline_rather_than_holding_a_worker():
    """The third finding of the 30 July 2026 rehearsal, and the one specific to MCP.

    httpx applies its `read` timeout per read operation. MCP's streamable-HTTP transport
    answers GET with `text/event-stream`, so a conforming server may hold the response open
    and emit a keepalive every few seconds; each one resets the timeout and `client.get()`
    never returns. `max_response_bytes` cannot help — it slices `response.content` after the
    body is read in full, which for a stream is never.

    Two of 200 endpoints did this and held their workers for over 35 minutes while the other
    198 finished in twelve. At census scale that is around ninety endpoints against eight
    workers, and the run would not have terminated on any predictable schedule.

    The endpoint here is a conforming MCP server, not a broken one, so the deadline is
    recorded as our limit — TIMEOUT, therefore ERROR under R4 — and R5's second run re-asks.
    """
    config = MeasurementConfig(rate=RatePolicy(
        per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0,
        total_request_timeout_s=0.5))

    async def never_ends(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)          # longer than any patience the run can afford
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(never_ends)
    async with Fetcher(config) as f:
        f._client = httpx.AsyncClient(transport=transport)
        result = await asyncio.wait_for(f.fetch("https://stream-example.org/mcp"), timeout=10)

    assert result.status is None
    assert result.error_kind is ErrorKind.TIMEOUT
    assert "total deadline" in result.error_detail, result.error_detail


async def test_a_robots_txt_that_never_ends_cannot_hold_an_origin_hostage():
    """The worse half of the same defect, found while writing the test above.

    `_robots_for` calls the client directly instead of going through `_request_with_retry`,
    so it inherited no deadline at all. It also runs before every gate and once per new
    origin, which means a single origin whose `robots.txt` trickles forever would hold a
    worker indefinitely and no endpoint on that origin could ever be reached — a denial of
    service we would be performing on ourselves, one worker at a time.

    A `robots.txt` we cannot read means no rules, which is what every other failure on this
    path already resolves to.
    """
    config = MeasurementConfig(rate=RatePolicy(
        per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0,
        total_request_timeout_s=0.5))

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            await asyncio.sleep(30)
        return httpx.Response(401, headers={"www-authenticate": "Bearer"})

    async with Fetcher(config) as f:
        f._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        result = await asyncio.wait_for(f.fetch("https://slow-robots-example.org/mcp"), 10)

    assert result.status == 401, "the endpoint must still be reached once robots gives up"


# --- the per-host ceiling must not become silent data loss --------------------


def test_a_bulk_host_is_sampled_rather_than_attempted_and_lost():
    """The finding that stopped the census on 30 July 2026, before it started.

    `RatePolicy.max_requests_per_host` caps one host at 30 requests per pass. An endpoint
    costs two to six of those, and the corpus puts 1,281 endpoints on `gateway.pipeworx.io`
    with 2,015 across the eleven hostnames over thirty each. So the ceiling would have been
    spent after a handful, the remaining ~1,270 would have returned `OUT_OF_SCOPE` with
    `reachable=False`, the kill switch would have read a fifth of the corpus as unreachable,
    and the abort message would have blamed the ecosystem for our own configuration.

    Sampling first is both the honest repair and the kinder one: fewer requests reach the
    operator than the ceiling alone would have allowed, because we stop asking rather than
    asking and being refused.
    """
    from agentidprobe.runner import sample_per_host

    endpoints = (
        [_corpus_endpoint(f"https://gateway.bulk.example.com/mcp/{i}", "bulk.example.com")
         for i in range(1281)]
        + [_corpus_endpoint(f"https://op{i}.example.org/mcp", f"op{i}.example.org")
           for i in range(40)]
    )
    sampled, excluded = sample_per_host(endpoints, 25)

    assert len(sampled) == 25 + 40
    assert excluded == {"gateway.bulk.example.com": 1281 - 25}
    assert sum(1 for e in sampled
               if "gateway.bulk.example.com" in e.url) == 25
    assert all(f"op{i}.example.org" in {e.apex_domain for e in sampled} for i in range(40)), (
        "hosts under the cap must be untouched"
    )


def test_the_sample_is_deterministic_and_leaves_small_hosts_in_corpus_order():
    """R8 needs the same corpus to yield the same sample, without a stored seed.

    Selection is by `endpoint_id`, a SHA-256 prefix of the URL — the same reason the
    rehearsal slice uses it. Corpus order is preserved for everything else so that a run
    over a corpus with no large hosts is byte-identical to one taken before this rule.
    """
    from agentidprobe.runner import sample_per_host

    endpoints = [_corpus_endpoint(f"https://big.example.com/mcp/{i}", "big.example.com")
                 for i in range(60)]
    first, _ = sample_per_host(endpoints, 25)
    again, _ = sample_per_host(list(reversed(endpoints)), 25)
    assert {e.endpoint_id for e in first} == {e.endpoint_id for e in again}, (
        "the sample must not depend on the order the registry happened to paginate in"
    )

    small = [_corpus_endpoint(f"https://op{i}.example.org/mcp", f"op{i}.example.org")
             for i in range(10)]
    unchanged, excluded = sample_per_host(small, 25)
    assert unchanged == small, "a corpus with no large host must pass through untouched"
    assert excluded == {}


def test_a_robots_exclusion_does_not_push_the_run_toward_its_kill_switch(tmp_path):
    """ETHICS.md §10 sets the threshold over endpoints that were "unreachable or blocked".

    A robots exclusion is neither: we reached the host, read its rules, and chose not to
    ask. This is the branch that was missed when the identical opt-out case was fixed on
    29 July 2026 — and the rehearsal measured its size rather than leaving it theoretical.
    17 of 198 endpoints were excluded by robots.txt, which was 8.6 of the 15.2 percentage
    points the switch was reading. Since Okta and Auth0 both serve `Disallow: /`, a census
    stratum heavy in hosted identity platforms could have aborted the run on a property of
    the ecosystem while the message blamed our reception.
    """
    from datetime import UTC, datetime

    from agentidprobe.models import EndpointReport

    store = RunStore(tmp_path, "r")
    runner = Runner(store, MeasurementConfig(
        abort=AbortPolicy(min_endpoints_before_abort=10, max_failure_fraction=0.25)))

    def report(url, *, robots_allowed=True, reachable=True):
        return EndpointReport(
            endpoint=_endpoint(url), modality=Modality.OAUTH_METADATA,
            reachable=reachable, robots_allowed=robots_allowed,
            probed_at=datetime.now(UTC), run_id="r")

    for i in range(40):
        runner._observe_outcome(report(f"https://blocked{i}.example.org/mcp",
                                       robots_allowed=False, reachable=False))
    for i in range(20):
        runner._observe_outcome(report(f"https://fine{i}.example.org/mcp"))

    assert runner._aborted is False, "our own robots policy tripped the kill switch"
    assert runner._robots_excluded == 40, "and the exclusions must still be counted"

    # It must still fire on the thing it is actually for.
    for i in range(20):
        runner._observe_outcome(report(f"https://dead{i}.example.org/mcp", reachable=False))
    assert runner._aborted is True


# --- a host that never answered has not told us anything ----------------------


@respx.mock
@pytest.mark.parametrize("kind", [ErrorKind.DNS, ErrorKind.TIMEOUT,
                                  ErrorKind.CONNECTION, ErrorKind.TLS])
async def test_a_transport_failure_is_an_error_not_an_endpoint_that_declined_authorization(
    kind,
):
    """Found by `dry-run` against a live endpoint whose DNS did not resolve, in the
    pre-flight before the narrow-slice rehearsal on 30 July 2026.

    With no response there is no 401, so `requires_authorization` is false, so every MUST
    stage took the composition branch and the dataset recorded
    *"authorization is OPTIONAL in MCP and this endpoint did not require it"* against a host
    we never reached. Under a DOI, about a named third party.

    The outcome was wrong as well as the sentence. R5 makes ERROR the set the second census
    run reconciles — an ERROR is final only once it recurs across two runs 24 hours apart —
    and NOT_APPLICABLE is not in that set. An endpoint suffering a transient failure during
    run 1 would have been booked as one that does not use authorization, and the run whose
    entire purpose is to re-ask would never have been pointed at it.

    Nothing published moves: both outcomes leave every denominator, and `summarise` already
    dropped these endpoints one stage earlier on `reachable`. The stored record changes from
    a false claim to a true one.
    """
    async with Fetcher(FAST) as f:
        initial = FetchResult(url="https://gone-example.org/mcp", ok=False,
                              status=None, error_kind=kind)
        checks, _ = await probe_oauth(f, "https://gone-example.org/mcp", initial)

    for check_id in (CheckId.PRM_PRESENT, CheckId.PRM_RESOURCE_IDENTITY_MATCH,
                     CheckId.AS_CORRESPONDENCE, CheckId.PKCE_DECLARED):
        outcome = _outcome(checks, check_id)
        assert outcome is Outcome.ERROR, f"{check_id} recorded {outcome} for a {kind} failure"

    details = " ".join(c.detail for c in checks if c.detail)
    assert "did not require it" not in details, (
        "a host that never answered was recorded as one that declined authorization"
    )
    assert kind.value in details, "the stored record must name what actually happened"


@respx.mock
async def test_a_transport_failure_on_the_card_path_is_not_absence_of_a_card():
    """The same distinction in the signed-document funnel.

    C01 asks whether an agent card is published. A host that did not answer has not been
    observed to lack one, but the no-card branch read `HTTP None` as absence and recorded it
    that way — putting the endpoint outside R5's reconciliation set for the same reason.
    """
    from agentidprobe.checks_signed import probe_signed

    async with Fetcher(FAST) as f:
        fetched = FetchResult(url="https://gone-example.org/.well-known/agent-card.json",
                              ok=False, status=None, error_kind=ErrorKind.TIMEOUT)
        checks, _ = await probe_signed(f, fetched.url, fetched)

    assert _outcome(checks, CheckId.IDENTITY_METADATA_PUBLISHED) is Outcome.ERROR
    assert all(c.outcome is Outcome.ERROR for c in checks)
    assert "timeout" in " ".join(c.detail for c in checks if c.detail)


@respx.mock
async def test_our_own_exclusions_say_so_rather_than_naming_the_error(monkeypatch):
    """An opt-out and a robots exclusion are our decisions, not the operator's behaviour.

    Both reach this branch with `status=None`, so the fix above had to keep them
    distinguishable from a dead host: the reader of the dataset must be able to tell an
    operator who asked to be left alone from one whose server was down.
    """
    config = MeasurementConfig(
        rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0),
        opted_out=frozenset({"quiet-example.org"}),
    )
    async with Fetcher(config) as f:
        initial = await f.fetch("https://quiet-example.org/mcp")
        checks, _ = await probe_oauth(f, "https://quiet-example.org/mcp", initial)

    assert initial.error_kind is ErrorKind.OPTED_OUT
    assert all(c.outcome is Outcome.ERROR for c in checks)
    details = " ".join(c.detail for c in checks if c.detail)
    assert "operator's request" in details
    assert "opted_out (R4/R5)" not in details
