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
