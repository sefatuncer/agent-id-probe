"""Collection, persistence and resume.

The property that matters most here is that a run can be interrupted and resumed
without re-fetching hosts we have already bothered, and that raw documents survive so a
verdict can be recomputed after an instrument fix. The phase-0 pilot lacked exactly this
and became unusable as evidence when review found scoring defects.
"""

import base64
import json
import pathlib
import tempfile
from datetime import UTC, datetime

import httpx
import respx

from agentidprobe.collectors import (
    McpOfficialRegistry,
    apex_domain,
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


def test_merge_records_every_source_that_listed_an_endpoint():
    """Multi-source provenance survives the merge.

    Renamed on 30 July 2026: the reason this mattered used to be capture-recapture, which has
    been deleted. It still matters, for a different reason -- `source` is the only record of
    which registry surfaced an endpoint, and R10.2's publisher-namespace sensitivity arm reads
    it.
    """
    shared = "https://shared-example.org/mcp"
    a = [_endpoint(shared, "mcp-official-registry"), _endpoint("https://a-example.org/mcp", "mcp")]
    b = [_endpoint(shared, "smithery")]
    merged = merge_endpoints(a, b)
    assert len(merged) == 2
    both = next(e for e in merged if e.url == shared)
    assert "smithery" in both.source and "mcp" in both.source



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



# --- the census must fail loudly rather than truncate quietly ------------------


def test_the_default_pagination_ceiling_cannot_truncate_the_registry():
    """The default is a property of the study, not a convenience.

    `--max-pages` defaulted to 500 from the days when a "run" meant a few hundred endpoints.
    At 100 records a page that caps the corpus at 50,000 against a registry holding some
    60,000, so the *documented default behaviour* of a tool whose paper claims a census was to
    truncate the population. The manifest recorded `TRUNCATED`, which is necessary and was not
    sufficient: nothing read it.

    The number is asserted against the page size rather than written twice, so raising one and
    forgetting the other fails here.
    """
    from agentidprobe.cli import build_parser
    from agentidprobe.collectors import McpOfficialRegistry

    args = build_parser().parse_args(["collect", "--run-id", "x"])
    capacity = args.max_pages * McpOfficialRegistry.page_size
    assert capacity >= 500_000, (
        f"the default ceiling admits {capacity} records; the registry held roughly 60,000 on "
        f"30 July 2026 and a census default must have room to grow into"
    )


def test_smithery_is_opt_in_not_opt_out():
    """Inverted on 30 July 2026, and it is an ethics change as much as a data one.

    Smithery contributed nothing once the `homepage`-as-endpoint defect was fixed -- that field
    is a project page, and it had been supplying 85% of the corpus as garbage, `github.com`
    sixty-six times over. The other reason to query it, the capture-recapture estimate, has
    been deleted. So the default behaviour was to send several hundred paginated requests to a
    third party in exchange for no measurement, which docs/ETHICS.md §3 does not license.
    """
    from agentidprobe.cli import build_parser

    default = build_parser().parse_args(["collect", "--run-id", "x"])
    assert default.include_smithery is False
    assert not hasattr(default, "official_only"), (
        "`--official-only` was replaced by `--include-smithery`; leaving both would leave two "
        "ways to express the same thing and one of them stale"
    )
    opted_in = build_parser().parse_args(["collect", "--run-id", "x", "--include-smithery"])
    assert opted_in.include_smithery is True


@respx.mock
async def test_collect_exits_non_zero_when_the_corpus_was_truncated():
    """A truncated corpus is the wrong population, not a small one.

    Before 30 July 2026 truncation was recorded in the manifest and the command returned 0, so
    `probe` ran next and produced a clean-looking dataset over a fraction of the frame. Every
    rate in it would have been conditioned on where pagination happened to stop, and nothing in
    the output said so. The exit code is what the next step in the pipeline actually reads.
    """
    import argparse

    from agentidprobe.cli import _cmd_collect

    # Two pages, both with a next cursor, against a ceiling of one page.
    respx.get(url__startswith="https://registry.modelcontextprotocol.io").mock(
        return_value=httpx.Response(200, json={
            "servers": [{
                "name": "io.github.example/server",
                "remotes": [{"type": "streamable-http", "url": "https://a-example.org/mcp"}],
            }],
            "metadata": {"next_cursor": "more-records-remain"},
        })
    )
    respx.get(url__startswith="https://registry.modelcontextprotocol.io/robots.txt").mock(
        return_value=httpx.Response(404)
    )

    with tempfile.TemporaryDirectory() as tmp:
        args = argparse.Namespace(
            root=tmp, run_id="truncated", max_pages=1, include_smithery=False,
            vantage_point="test",
        )
        assert await _cmd_collect(args) == 2

        # And the partial corpus is still written, with the reason recorded: the operator needs
        # to see what was collected in order to judge how far short it fell.
        manifest = json.loads(
            (pathlib.Path(tmp) / "results" / "runs" / "truncated" / "manifest.json")
            .read_text(encoding="utf-8")
        )
        assert any("TRUNCATED" in e for e in manifest["sources"][0]["errors"])


# --- D10: the public suffix list is a recorded dependency, not an assumed one ---


def test_public_suffix_provenance_identifies_the_snapshot_in_use():
    """Defect D10, closed 30 July 2026.

    The list was already pinned against the network -- `suffix_list_urls=()` means no run can
    pick up a fresher one mid-measurement -- but not against the *dependency*:
    `tldextract>=5.1,<6.0` admits any patch release and each ships its own snapshot. That
    matters twice over. R10.2 makes the apex domain the primary unit of analysis, so the
    snapshot decides the cluster count and every interval computed from it; and an issuer with
    no registrable domain is never contacted, so it decides which requests the run sends and,
    since the D8 fix, which issuers are in the denominator.
    """
    from agentidprobe.collectors import public_suffix_provenance

    provenance = public_suffix_provenance()
    assert provenance["library"] == "tldextract"
    assert provenance["version"] not in ("", "unknown")
    assert provenance["snapshot_sha256"] and len(provenance["snapshot_sha256"]) == 64
    # The private section stays closed. Asserted rather than commented because the paper
    # states the resulting bias -- platform tenants share an apex, so the cross-operator
    # delegation rate is under-estimated -- and a silent flip would make that sentence false
    # in the safe-sounding direction.
    assert provenance["include_psl_private_domains"] is False
    assert provenance["suffix_list_urls"] == []


def test_every_manifest_records_the_public_suffix_list():
    """Written on all manifests, not only `collect`'s.

    `rescore` does not re-fetch but it does re-derive apexes, so R8 leg 2's promise of
    byte-identical verdicts on replay was inheriting this dependency unrecorded. A reviewer
    comparing their replay against ours can now see a snapshot mismatch instead of finding
    the clustering quietly different.
    """
    from agentidprobe.models import RunContext

    with tempfile.TemporaryDirectory() as tmp:
        store = RunStore(pathlib.Path(tmp), "psl")
        store.write_manifest(
            RunContext(run_id="psl", vantage_point="test", started_at=datetime.now(UTC))
        )
        manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))

    assert manifest["public_suffix_list"]["snapshot_sha256"]
    assert manifest["public_suffix_list"]["version"] not in ("", "unknown")
