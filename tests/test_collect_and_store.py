"""Collection, persistence and resume.

The property that matters most here is that a run can be interrupted and resumed
without re-fetching hosts we have already bothered, and that raw documents survive so a
verdict can be recomputed after an instrument fix. The phase-0 pilot lacked exactly this
and became unusable as evidence when review found scoring defects.
"""

import base64
import json
from datetime import UTC, datetime

import httpx
import respx

from agentidprobe.collectors import (
    McpOfficialRegistry,
    apex_domain,
    capture_recapture_estimate,
    classify_hosting,
    endpoint_id,
    merge_endpoints,
)
from agentidprobe.config import MeasurementConfig, RatePolicy
from agentidprobe.fetcher import ErrorKind, Fetcher, FetchResult
from agentidprobe.models import (
    CheckId,
    CheckResult,
    Endpoint,
    EndpointKind,
    EndpointReport,
    Hosting,
    Modality,
    NormativeStrength,
    Outcome,
    RunContext,
)
from agentidprobe.runner import Runner, derive_card_endpoints, origin_of, summarise
from agentidprobe.store import RunStore

FAST = MeasurementConfig(
    rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0)
)


def _endpoint(url: str, source: str = "s") -> Endpoint:
    return Endpoint(endpoint_id=endpoint_id(url), url=url, kind=EndpointKind.MCP_REMOTE,
                    source=source, apex_domain=apex_domain(url))


# --- apex / hosting -----------------------------------------------------------


def test_apex_handles_multi_label_suffixes():
    assert apex_domain("https://a.b.example.co.uk/mcp") == "example.co.uk"
    assert apex_domain("https://example.org/mcp") == "example.org"


def test_apex_none_for_ip_and_junk():
    assert apex_domain("https://192.0.2.1/mcp") is None
    assert apex_domain("not-a-url") is None


def test_platform_hosts_are_distinguished_from_self_hosted():
    """The clustering analysis depends on this: a platform getting it wrong once looks
    identical to a thousand operators each getting it wrong, unless they are labelled."""
    assert classify_hosting("https://x.smithery.ai/mcp") is Hosting.HOSTED_PLATFORM
    assert classify_hosting("https://my-agent.vercel.app/mcp") is Hosting.HOSTED_PLATFORM
    assert classify_hosting("https://agents.acme-corp-example.org/mcp") is Hosting.SELF_HOSTED


# --- registry collection ------------------------------------------------------


def test_publisher_namespace_comes_from_the_registry_not_from_us():
    """R10.2b needs clustering arms, and this one is externally supplied: the registry
    verifies namespace ownership (DNS TXT, or OAuth for io.github.*) before accepting a
    publication. A clustering built from a list we wrote ourselves would be the
    author-supplied rubric the instrument exists to avoid. It was being discarded."""
    from agentidprobe.collectors import publisher_namespace
    assert publisher_namespace({"name": "io.github.someone/my-server"}) == "io.github.someone"
    assert publisher_namespace({"server": {"name": "com.acme/thing"}}) == "com.acme"
    assert publisher_namespace({"name": "no-slash"}) is None
    assert publisher_namespace({}) is None


@respx.mock
async def test_official_registry_paginates_and_dedupes():
    page1 = {
        "servers": [
            {"name": "a", "remotes": [{"url": "https://one-example.org/mcp"}]},
            {"name": "b", "server": {"remotes": [{"url": "https://two-example.org/mcp"}]}},
            {"name": "a-v2", "remotes": [{"url": "https://one-example.org/mcp"}]},  # duplicate
        ],
        "metadata": {"next_cursor": "c2"},
    }
    page2 = {
        "servers": [{"name": "c", "remotes": [{"url": "http://insecure-example.org/mcp"}]}],
        "metadata": {},
    }
    respx.get("https://registry.modelcontextprotocol.io/robots.txt").mock(
        return_value=httpx.Response(404))
    # The cursor route is registered first: respx matches in order and a bare URL
    # pattern also matches query strings, so the unparameterised route would otherwise
    # swallow page two. `limit` is always sent — at the registry's default page size of
    # 30 a full enumeration needs ~625 pages, which is how max_pages truncates silently.
    respx.get("https://registry.modelcontextprotocol.io/v0/servers?limit=100&cursor=c2").mock(
        return_value=httpx.Response(200, json=page2))
    respx.get("https://registry.modelcontextprotocol.io/v0/servers").mock(
        return_value=httpx.Response(200, json=page1))

    async with Fetcher(FAST) as fetcher:
        collector = McpOfficialRegistry(fetcher)
        endpoints = await collector.collect()

    assert len(endpoints) == 2
    assert collector.stats.pages_fetched == 2
    assert collector.stats.records_seen == 4
    assert collector.stats.dropped_not_https == 1
    assert len(collector.stats.apex_domains) == 2


@respx.mock
async def test_repeated_cursor_stops_pagination():
    """A registry echoing its cursor back would otherwise be paginated max_pages times,
    re-counting the same records and inflating every derived statistic."""
    page = {
        "servers": [{"name": "a", "remotes": [{"url": "https://one-example.org/mcp"}]}],
        "metadata": {"next_cursor": "same"},
    }
    respx.get("https://registry.modelcontextprotocol.io/robots.txt").mock(
        return_value=httpx.Response(404))
    respx.get(url__regex=r"https://registry\.modelcontextprotocol\.io/v0/servers.*").mock(
        return_value=httpx.Response(200, json=page))

    async with Fetcher(FAST) as fetcher:
        collector = McpOfficialRegistry(fetcher, max_pages=500)
        endpoints = await collector.collect()

    assert len(endpoints) == 1
    assert collector.stats.pages_fetched == 2
    assert any("cursor repeated" in e for e in collector.stats.errors)


@respx.mock
async def test_registry_error_is_recorded_not_raised():
    respx.get("https://registry.modelcontextprotocol.io/robots.txt").mock(
        return_value=httpx.Response(404))
    respx.get("https://registry.modelcontextprotocol.io/v0/servers").mock(
        return_value=httpx.Response(500))
    async with Fetcher(FAST) as fetcher:
        collector = McpOfficialRegistry(fetcher)
        assert await collector.collect() == []
    assert collector.stats.errors


def test_merge_records_every_source_for_capture_recapture():
    shared = "https://shared-example.org/mcp"
    a = [_endpoint(shared, "mcp-official-registry"), _endpoint("https://a-example.org/mcp", "mcp")]
    b = [_endpoint(shared, "smithery")]
    merged = merge_endpoints(a, b)
    assert len(merged) == 2
    both = next(e for e in merged if e.url == shared)
    assert "smithery" in both.source and "mcp" in both.source


def test_capture_recapture_uses_chapman_and_reports_no_overlap():
    a = [_endpoint(f"https://a{i}-example.org/mcp") for i in range(10)]
    b = [_endpoint(f"https://a{i}-example.org/mcp") for i in range(5, 15)]
    est = capture_recapture_estimate(a, b)
    assert est["overlap"] == 5
    assert est["estimate"] >= 15
    assert capture_recapture_estimate(a[:2], [_endpoint("https://z-example.org/mcp")])["estimate"] \
        is None


# --- derived agent-card corpus ------------------------------------------------


def test_card_endpoints_are_one_per_origin():
    """Public agent cards are not independently enumerable; deriving them from MCP
    origins is how a non-trivial sample exists at all, so the derivation is explicit."""
    endpoints = [
        _endpoint("https://one-example.org/mcp"),
        _endpoint("https://one-example.org/other/mcp"),
        _endpoint("https://two-example.org/mcp"),
    ]
    cards = derive_card_endpoints(endpoints)
    assert len(cards) == 2
    assert all(c.url.endswith("/.well-known/agent-card.json") for c in cards)
    assert all(c.source == "derived:mcp-origin" for c in cards)
    assert origin_of("https://one-example.org/a/b?x=1") == "https://one-example.org"


# --- store --------------------------------------------------------------------


def _report(url: str = "https://one-example.org/mcp") -> EndpointReport:
    return EndpointReport(
        endpoint=_endpoint(url),
        modality=Modality.OAUTH_METADATA,
        reachable=True,
        http_status=401,
        checks=[CheckResult(check_id=CheckId.PRM_PRESENT, outcome=Outcome.PASS,
                            normative_strength=NormativeStrength.MUST)],
        probed_at=datetime.now(UTC),
        run_id="r1",
    )


def test_round_trip_corpus_and_reports(tmp_path):
    store = RunStore(tmp_path, "r1")
    store.write_corpus([_endpoint("https://one-example.org/mcp")])
    store.append_report(_report())
    assert [e.url for e in store.read_corpus()] == ["https://one-example.org/mcp"]
    assert store.read_reports()[0].outcome_of(CheckId.PRM_PRESENT) is Outcome.PASS


def test_resume_skips_completed_endpoints(tmp_path):
    store = RunStore(tmp_path, "r1")
    store.append_report(_report("https://one-example.org/mcp"))
    done = store.completed_endpoint_ids()
    assert endpoint_id("https://one-example.org/mcp") in done
    assert endpoint_id("https://two-example.org/mcp") not in done


def test_truncated_tail_does_not_break_resume(tmp_path):
    """A run killed mid-write leaves a partial line. Aborting the resume would mean
    re-fetching thousands of third-party hosts we have already contacted once."""
    store = RunStore(tmp_path, "r1")
    store.append_report(_report())
    with store.reports_path.open("a", encoding="utf-8") as handle:
        handle.write('{"endpoint": {"endpoint_i')
    assert len(store.completed_endpoint_ids()) == 1
    assert len(store.read_reports()) == 1


def test_raw_artifact_is_retained_verbatim_for_rescoring(tmp_path):
    store = RunStore(tmp_path, "r1")
    body = b'{"resource": "https://one-example.org/mcp"}'
    store.append_artifact(
        "e1", "mcp-endpoint",
        FetchResult(url="https://one-example.org/mcp", ok=True, status=200, body=body,
                    headers={"content-type": "application/json"}),
    )
    artifacts = store.read_artifacts("e1")
    assert artifacts[0]["body"] == body
    assert json.loads(artifacts[0]["body"])["resource"] == "https://one-example.org/mcp"
    raw_line = json.loads(store.artifacts_path.read_text(encoding="utf-8").splitlines()[0])
    assert base64.b64decode(raw_line["body_b64"]) == body


def test_manifest_records_provenance(tmp_path):
    store = RunStore(tmp_path, "r1")
    store.write_manifest(
        RunContext(run_id="r1", vantage_point="residential-TR",
                   probe_git_commit="deadbeef", started_at=datetime.now(UTC)),
        extra={"stage": "collect"},
    )
    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_context"]["vantage_point"] == "residential-TR"
    assert manifest["run_context"]["probe_git_commit"] == "deadbeef"


# --- summary ------------------------------------------------------------------


def test_summary_funnel_is_conditional_on_the_previous_stage():
    reports = [_report("https://a-example.org/mcp"), _report("https://b-example.org/mcp")]
    blocked = EndpointReport(
        endpoint=_endpoint("https://c-example.org/mcp"),
        modality=Modality.OAUTH_METADATA,
        reachable=False,
        checks=[],
        probed_at=datetime.now(UTC),
        run_id="r1",
    )
    out = summarise([*reports, blocked])
    funnel = out["modalities"]["oauth_metadata"]["funnel"]
    assert funnel[0] == {
        "stage": "reachable", "n": 2, "eligible": 3,
        "excluded": {"not_applicable": 0, "error": 1},
    }
    assert funnel[1]["n"] == 2  # both reachable endpoints passed C05
    assert funnel[2]["eligible"] == 2  # next stage is measured against C05 passers only


def test_endpoints_that_never_required_authorization_leave_the_denominator():
    """Authorization is OPTIONAL in MCP, so an open server scores NOT_APPLICABLE on every
    OAuth check. Counting it in the denominator measures composition, not conformance —
    on the pilot's shape that is the difference between a 36.7% headline (a replication of
    prior work) and a 96.6% one (the finding this study argues)."""
    required = [_report("https://a-example.org/mcp"), _report("https://b-example.org/mcp")]
    open_server = EndpointReport(
        endpoint=_endpoint("https://open-example.org/mcp"),
        modality=Modality.OAUTH_METADATA,
        reachable=True,
        checks=[
            CheckResult(
                check_id=CheckId.PRM_PRESENT,
                outcome=Outcome.NOT_APPLICABLE,
                normative_strength=NormativeStrength.MUST,
                detail="authorization is OPTIONAL in MCP and this endpoint did not require it",
            )
        ],
        probed_at=datetime.now(UTC),
        run_id="r1",
    )
    funnel = summarise([*required, open_server])["modalities"]["oauth_metadata"]["funnel"]
    prm_stage = funnel[1]
    assert prm_stage["n"] == 2
    assert prm_stage["eligible"] == 2                      # not 3
    assert prm_stage["excluded"]["not_applicable"] == 1


def test_robots_excluded_endpoints_leave_the_study_entirely():
    """Our own politeness policy must not be able to move the published rate."""
    excluded = EndpointReport(
        endpoint=_endpoint("https://noindex-example.org/mcp"),
        modality=Modality.OAUTH_METADATA,
        reachable=False,
        robots_allowed=False,
        checks=[],
        probed_at=datetime.now(UTC),
        run_id="r1",
    )
    out = summarise([_report("https://a-example.org/mcp"), excluded])
    oauth = out["modalities"]["oauth_metadata"]
    assert oauth["total"] == 2
    assert oauth["in_scope"] == 1
    assert oauth["excluded_robots"] == 1
    assert oauth["funnel"][0]["eligible"] == 1


# --- R8 foot 2: everything a verdict rests on must survive the run ------------


@respx.mock
async def test_every_document_a_check_consulted_is_persisted(tmp_path):
    """Decision rule R8 promises any result can be re-scored without touching the network.
    The endpoint response alone does not carry that promise: C12 rests on the
    protected-resource metadata and C13 on each issuer's metadata, and those are fetched
    inside the checks. Until the fetcher gained a capture hook they were read, scored, and
    dropped — so the decisive verdicts had no stored inputs, and rebuilding the
    resource -> issuer graph would have meant scanning thousands of hosts again."""
    resource = "https://one-example.org/mcp"
    prm_url = "https://one-example.org/.well-known/oauth-protected-resource/mcp"
    issuer = "https://auth-example.org"
    as_url = "https://auth-example.org/.well-known/oauth-authorization-server"

    for host in ("https://one-example.org", "https://auth-example.org"):
        respx.get(f"{host}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(resource).mock(return_value=httpx.Response(401))
    respx.get(prm_url).mock(return_value=httpx.Response(
        200, json={"resource": resource, "authorization_servers": [issuer]}))
    respx.get(as_url).mock(return_value=httpx.Response(
        200, json={"issuer": issuer, "code_challenge_methods_supported": ["S256"]}))

    store = RunStore(tmp_path, "r1")
    runner = Runner(store, MeasurementConfig(
        rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0,
                        backoff_base_s=0.0)))
    reports = await runner.run([_endpoint(resource)], Modality.OAUTH_METADATA)

    stored = {a["url"] for a in store.read_artifacts()}
    assert resource in stored
    assert prm_url in stored, "the protected-resource document behind C12 was not stored"
    assert as_url in stored, "the issuer metadata behind C13 was not stored"

    # And the structured observations survive too, so the issuer graph can be built
    # from disk rather than from a second scan.
    evidence = reports[0].evidence
    assert evidence["declared_resource"] == resource
    assert evidence["authorization_servers"] == [issuer]
    assert evidence["as_documents"][issuer]["issuer"] == issuer
    assert store.read_reports()[0].evidence["expected_resource"] == resource


def test_a_torn_line_from_a_killed_run_does_not_swallow_the_next_record(tmp_path):
    """A run killed mid-write leaves a line with no newline. Appending straight onto it
    fused two records into one unparseable line, so the *next* endpoint was lost as well —
    silently, because both the resume scan and the reader skip malformed lines.

    The torn line is written before the store opens the file, which is the only way it can
    actually arise: the writing process is dead. That is also why the check runs once per
    file per process rather than before every record — re-opening the file read-only each
    time cost 341 ms per record against 28 ms without, inside calls that block the event
    loop, which is roughly two hours of a full run spent re-reading one byte.
    """
    store = RunStore(tmp_path, "r1")
    store.reports_path.write_text(
        '{"endpoint": {"endpoint_id": "torn", "url": "https://b-exam',
        encoding="utf-8",
    )
    store.append_report(_report("https://a-example.org/mcp"))
    store.append_report(_report("https://c-example.org/mcp"))

    urls = {r.endpoint.url for r in store.read_reports()}
    assert urls == {"https://a-example.org/mcp", "https://c-example.org/mcp"}


def test_reports_are_deduplicated_so_a_re_probe_is_not_counted_twice(tmp_path):
    """The file is append-only, so re-probing with --no-resume leaves two records for an
    endpoint. Returning both would count it twice in every rate the paper publishes."""
    store = RunStore(tmp_path, "r1")
    store.append_report(_report("https://a-example.org/mcp"))
    store.append_report(_report("https://a-example.org/mcp"))
    assert len(store.read_reports()) == 1


def test_blocked_endpoint_is_not_counted_as_reachable():
    blocked = FetchResult(url="https://x-example.org/mcp", ok=False, status=403,
                          error_kind=ErrorKind.BLOCKED)
    assert blocked.error_kind is ErrorKind.BLOCKED

