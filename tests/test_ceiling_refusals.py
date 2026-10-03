"""Our own per-host request ceiling must never be written up as an operator's failure.

A referee ran the instrument over the stored census and found the opposite (H2-M1, review of
1 October 2026). When the ceiling refused a request for an issuer's metadata, the issuer loop
read the refusal as "served no metadata" and wrote a MUST-level C13 failure: 71 of the 136
C13 failures, and one issuer declared by eighty endpoints that passed for the twenty-nine
asked about it first and failed for the rest. The protected-resource loop did the same to
C05. The manuscript's outcome taxonomy promises the reverse, so these tests hold the code to
the promise, and each fails if its fix is reverted.

The same review found C05's challenged denominator admitting a bare 403, which the taxonomy
calls an access block, so the last two tests pin the rule that replaced it.
"""

from datetime import UTC, datetime, timedelta

import httpx
import respx

from agentidprobe.checks_oauth import probe_oauth
from agentidprobe.collectors import apex_domain, endpoint_id
from agentidprobe.config import MeasurementConfig, RatePolicy
from agentidprobe.fetcher import ErrorKind, Fetcher, FetchResult, is_ceiling_refusal
from agentidprobe.models import CheckId, Endpoint, EndpointKind, Modality, Outcome
from agentidprobe.replay import ReplayFetcher, compare_reports
from agentidprobe.runner import Runner, rescore
from agentidprobe.store import RunStore

ISSUER = "https://auth.example.org"
AS_URL = f"{ISSUER}/.well-known/oauth-authorization-server"


def _config(ceiling: int) -> MeasurementConfig:
    return MeasurementConfig(rate=RatePolicy(
        per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0,
        max_requests_per_host=ceiling))


def _initial(url: str, status: int = 401, headers: dict | None = None) -> FetchResult:
    return FetchResult(url=url, ok=True, status=status, headers=headers or {})


def _mock_resource(host: str, issuer: str = ISSUER) -> str:
    url = f"https://{host}/mcp"
    respx.get(f"https://{host}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url).mock(return_value=httpx.Response(401))
    respx.get(f"https://{host}/.well-known/oauth-protected-resource/mcp").mock(
        return_value=httpx.Response(200, json={"resource": url,
                                               "authorization_servers": [issuer]}))
    return url


def _mock_issuer() -> None:
    respx.get(f"{ISSUER}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER, "code_challenge_methods_supported": ["S256"]}))


def _outcome(checks, check_id):
    return next(c.outcome for c in checks if c.check_id is check_id)


@respx.mock
async def test_a_refused_issuer_request_is_answered_from_the_run_s_own_document():
    """Two resources name one issuer. The ceiling lets the first read its metadata and
    refuses the second; the second must get the same document and the same verdict."""
    _mock_issuer()
    first = _mock_resource("a.example.com")
    second = _mock_resource("b.example.net")
    async with Fetcher(_config(2)) as f:
        checks_a, _ = await probe_oauth(f, first, _initial(first))
        checks_b, ev_b = await probe_oauth(f, second, _initial(second))
        sent = f._host_requests["auth.example.org"]

    assert _outcome(checks_a, CheckId.AS_CORRESPONDENCE) is Outcome.PASS
    assert _outcome(checks_b, CheckId.AS_CORRESPONDENCE) is Outcome.PASS, (
        "the second endpoint was charged for a request our own ceiling refused")
    assert ISSUER in ev_b.as_documents
    assert sent == 2, "reuse must not send the issuer another request"


@respx.mock
async def test_an_issuer_the_run_never_retrieved_is_not_observed_rather_than_failed():
    _mock_issuer()
    url = _mock_resource("a.example.com")
    async with Fetcher(_config(2)) as f:
        f._host_requests["auth.example.org"] = 2      # spent on other endpoints' traffic
        checks, ev = await probe_oauth(f, url, _initial(url))

    assert _outcome(checks, CheckId.AS_CORRESPONDENCE) is Outcome.ERROR
    assert "not observed" in ev.as_errors[ISSUER]


@respx.mock
async def test_a_refused_metadata_candidate_is_not_absence_of_metadata():
    url = _mock_resource("a.example.com")
    async with Fetcher(_config(2)) as f:
        f._host_requests["a.example.com"] = 2
        checks, _ = await probe_oauth(f, url, _initial(url))

    for check_id in (CheckId.PRM_PRESENT, CheckId.PRM_RESOURCE_IDENTITY_MATCH,
                     CheckId.AS_CORRESPONDENCE):
        assert _outcome(checks, check_id) is Outcome.ERROR, check_id


@respx.mock
async def test_a_document_behind_a_withheld_candidate_is_not_scored():
    """robots.txt forbids the path-suffixed location and allows the root. A client reads the
    path-suffixed document first, we did not, so the root document is not what it would see
    and must not convict anyone."""
    host = "a.example.com"
    url = f"https://{host}/mcp"
    respx.get(f"https://{host}/robots.txt").mock(return_value=httpx.Response(
        200, text="User-agent: *\nDisallow: /.well-known/oauth-protected-resource/mcp\n"))
    respx.get(f"https://{host}/.well-known/oauth-protected-resource").mock(
        return_value=httpx.Response(200, json={"resource": f"https://{host}",
                                               "authorization_servers": [ISSUER]}))
    async with Fetcher(_config(30)) as f:
        checks, _ = await probe_oauth(f, url, _initial(url))

    assert _outcome(checks, CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.ERROR


def _record(endpoint: str, url: str, when: datetime, **kw) -> dict:
    return {"endpoint_id": endpoint, "url": url, "label": "mcp", "ok": kw.get("ok", False),
            "status": kw.get("status"), "headers": {}, "body_b64": kw.get("body_b64", ""),
            "error_kind": kw.get("error_kind", "none"),
            "error_detail": kw.get("error_detail", ""), "fetched_at": when.isoformat()}


async def test_replay_answers_a_stored_refusal_only_from_an_earlier_document():
    t0 = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    refusal = {"error_kind": "out_of_scope",
               "error_detail": "host has already received 30 requests this pass"}
    success = {"ok": True, "status": 200, "body_b64": "eyJpc3N1ZXIiOiJ4In0="}
    artifacts = [
        _record("early", AS_URL, t0 - timedelta(minutes=1), **refusal),
        _record("first", AS_URL, t0, **success),
        _record("later", AS_URL, t0 + timedelta(minutes=1), **refusal),
    ]
    replay = ReplayFetcher(artifacts)

    replay.bind("later")
    answered = await replay.fetch(AS_URL)
    assert answered.status == 200 and answered.reused

    replay.bind("early")
    refused = await replay.fetch(AS_URL)
    assert is_ceiling_refusal(refused), (
        "a refusal that preceded the first retrieval could not have been answered live")


def test_a_redirect_off_the_web_is_not_mistaken_for_the_ceiling():
    redirect = FetchResult(url="https://x.example", ok=False,
                           error_kind=ErrorKind.OUT_OF_SCOPE,
                           error_detail="redirect to 'http', not https")
    assert not is_ceiling_refusal(redirect)


@respx.mock
async def test_a_live_run_with_reuse_rescores_to_identical_verdicts(tmp_path):
    """R8: a reused document is stored as such, so the replay reproduces the live verdict."""
    _mock_issuer()
    urls = [_mock_resource(h) for h in ("a.example.com", "b.example.net", "c.example.io")]
    endpoints = [Endpoint(endpoint_id=endpoint_id(u), url=u, kind=EndpointKind.MCP_REMOTE,
                          source="t", apex_domain=apex_domain(u)) for u in urls]
    config = _config(3)
    source = RunStore(tmp_path, "live")
    source.write_corpus(endpoints)
    live = await Runner(source, config).run(endpoints, Modality.OAUTH_METADATA)
    assert any(r.reused for r in [
        FetchResult(url=a["url"], ok=a["ok"], reused=a.get("reused", False))
        for a in source.read_artifacts()]), "the scenario never exercised reuse"
    assert all(_outcome(r.checks, CheckId.AS_CORRESPONDENCE) is Outcome.PASS for r in live)

    replayed = await rescore(source, RunStore(tmp_path, "replayed"), config)
    assert compare_reports(live, replayed) == []


async def test_a_bare_403_without_metadata_is_not_applicable_rather_than_convicted():
    url = "https://a.example.com/mcp"
    with respx.mock(assert_all_called=False) as router:
        router.get(url__regex=r"https://a\.example\.com/.*").mock(
            return_value=httpx.Response(404))
        async with Fetcher(_config(30)) as f:
            checks, ev = await probe_oauth(f, url, _initial(url, status=403))

    assert not ev.requires_authorization
    assert _outcome(checks, CheckId.PRM_PRESENT) is Outcome.NOT_APPLICABLE


async def test_a_403_carrying_a_bearer_challenge_is_still_a_challenge():
    url = "https://a.example.com/mcp"
    with respx.mock(assert_all_called=False) as router:
        router.get(url__regex=r"https://a\.example\.com/.*").mock(
            return_value=httpx.Response(404))
        async with Fetcher(_config(30)) as f:
            checks, ev = await probe_oauth(
                f, url, _initial(url, status=403,
                                 headers={"www-authenticate": 'Bearer error="insufficient_scope"'}))

    assert ev.requires_authorization
    assert _outcome(checks, CheckId.PRM_PRESENT) is Outcome.FAIL_UNIMPLEMENTED


async def test_metadata_a_stored_run_never_requested_is_not_observed_or_answered_from_it():
    """A legacy run sometimes stopped short of a request the corrected instrument makes.
    Re-scoring treats that request as a ceiling refusal at the endpoint's own probe time:
    answered from the run's earlier copy, otherwise not observed, never fetched."""
    import pytest

    from agentidprobe.replay import ArtefactMissing

    t0 = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    success = {"ok": True, "status": 200, "body_b64": "eyJpc3N1ZXIiOiJ4In0="}
    artifacts = [
        _record("first", AS_URL, t0, **success),
        _record("late", "https://late.example/mcp", t0 + timedelta(minutes=5), status=401),
        _record("early", "https://early.example/mcp", t0 - timedelta(minutes=5), status=401),
    ]
    lenient = ReplayFetcher(artifacts, unrequested_metadata_not_observed=True)
    lenient.bind("late")
    assert (await lenient.fetch(AS_URL)).reused
    lenient.bind("early")
    assert is_ceiling_refusal(await lenient.fetch(AS_URL))
    assert (lenient.unrequested_answered, lenient.unrequested_not_observed) == (1, 1)

    strict = ReplayFetcher(artifacts)
    strict.bind("late")
    with pytest.raises(ArtefactMissing):
        await strict.fetch(AS_URL)
