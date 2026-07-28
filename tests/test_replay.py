"""Decision rule R8, leg 2: a stored run must re-score to identical verdicts, offline.

The existing `test_replay_determinism` called a check twice in one process, which shows
that a function is deterministic — a much weaker claim than the one R8 makes. What matters
is that the *stored artefacts* carry everything the verdict rested on, and that is a
property of `store.append_artifact`, not of the checks. It was false until 2026-07-28: TLS
details were never written, so C11 turned every live PASS into FAIL_UNIMPLEMENTED on replay.
"""

import httpx
import pytest
import respx

from agentidprobe.config import MeasurementConfig, RatePolicy
from agentidprobe.models import CheckId, Modality, Outcome
from agentidprobe.replay import ArtefactMissing, ReplayFetcher, compare_reports
from agentidprobe.runner import Runner, rescore
from agentidprobe.store import RunStore

FAST = MeasurementConfig(
    rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0)
)

RESOURCE = "https://replay-example.org/mcp"
PRM_URL = "https://replay-example.org/.well-known/oauth-protected-resource/mcp"
ISSUER = "https://auth.replay-example.org"
AS_URL = "https://auth.replay-example.org/.well-known/oauth-authorization-server"


def _endpoint(url: str = RESOURCE):
    from agentidprobe.collectors import apex_domain, endpoint_id
    from agentidprobe.models import Endpoint, EndpointKind
    return Endpoint(endpoint_id=endpoint_id(url), url=url, kind=EndpointKind.MCP_REMOTE,
                    source="t", apex_domain=apex_domain(url))


def _mock_a_conforming_endpoint() -> None:
    for host in ("https://replay-example.org", "https://auth.replay-example.org"):
        respx.get(f"{host}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(RESOURCE).mock(return_value=httpx.Response(401))
    respx.get(PRM_URL).mock(return_value=httpx.Response(
        200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}))
    respx.get(AS_URL).mock(return_value=httpx.Response(
        200, json={"issuer": ISSUER, "code_challenge_methods_supported": ["S256"],
                   "revocation_endpoint": f"{ISSUER}/revoke"}))
    respx.get(url__regex=r"https://replay-example\.org/\.well-known/agent-card\.json").mock(
        return_value=httpx.Response(404))


@respx.mock
async def test_a_stored_run_rescores_to_identical_verdicts(tmp_path):
    _mock_a_conforming_endpoint()
    source = RunStore(tmp_path, "live")
    source.write_corpus([_endpoint()])
    live = await Runner(source, FAST).run([_endpoint()], Modality.OAUTH_METADATA)
    assert live, "the live run produced nothing to compare against"

    destination = RunStore(tmp_path, "replayed")
    replayed = await rescore(source, destination, FAST)

    assert len(replayed) == len(live)
    assert compare_reports(live, replayed) == []


@respx.mock
async def test_replay_reaches_the_documents_the_checks_fetched_not_just_the_endpoint(tmp_path):
    """C12 and C13 rest on the protected-resource document and the issuer's metadata, both
    fetched inside the checks. If those were not stored, replay would fall back to
    "no metadata at any candidate location" and every conforming endpoint would come back
    as FAIL_UNIMPLEMENTED."""
    _mock_a_conforming_endpoint()
    source = RunStore(tmp_path, "live")
    source.write_corpus([_endpoint()])
    live = await Runner(source, FAST).run([_endpoint()], Modality.OAUTH_METADATA)
    assert live[0].outcome_of(CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.PASS

    replayed = await rescore(source, RunStore(tmp_path, "replayed"), FAST)
    assert replayed[0].outcome_of(CheckId.PRM_RESOURCE_IDENTITY_MATCH) is Outcome.PASS
    assert replayed[0].outcome_of(CheckId.AS_CORRESPONDENCE) is Outcome.PASS
    assert replayed[0].evidence["as_documents"][ISSUER]["issuer"] == ISSUER


@respx.mock
async def test_tls_survives_the_round_trip_so_c11_does_not_flip(tmp_path):
    """The concrete defect this module was written to expose. `tls` was absent from the
    artefact record, so a re-scored C11 saw `tls is None` and reported FAIL_UNIMPLEMENTED
    against endpoints that had passed live."""
    from agentidprobe.fetcher import FetchResult
    from agentidprobe.models import TlsInfo

    store = RunStore(tmp_path, "r1")
    store.append_artifact("e1", "mcp", FetchResult(
        url=RESOURCE, ok=True, status=401,
        tls=TlsInfo(version="TLSv1.3", chain_valid=True, san_match=True,
                    cert_sha256="ab" * 32),
    ))
    record = store.read_artifacts("e1")[0]
    assert record["tls"] is not None
    assert record["tls"]["chain_valid"] is True

    fetcher = ReplayFetcher([record])
    fetcher.bind("e1")
    restored = await fetcher.fetch(RESOURCE)
    assert restored.tls is not None
    assert restored.tls.chain_valid is True
    assert restored.tls.cert_sha256 == "ab" * 32


async def test_a_missing_artefact_raises_rather_than_going_to_the_network():
    """A replay that silently re-fetches is not a replay: it would make a failed
    reproduction look like a successful one."""
    fetcher = ReplayFetcher([])
    fetcher.bind("e1")
    with pytest.raises(ArtefactMissing):
        await fetcher.fetch("https://nothing-stored-example.org/mcp")


async def test_repeated_fetches_of_one_url_replay_in_the_original_order():
    """A retry that failed and then succeeded must replay as failure-then-success, or the
    re-scored verdict is computed from a history that never happened."""
    records = [
        {
            "endpoint_id": "e1", "url": RESOURCE, "status": status, "ok": True,
            "headers": {}, "body_b64": "", "error_kind": "none", "error_detail": "",
            "fetched_at": "2026-07-28T00:00:00+00:00", "redirect_chain": [],
            "final_url": None, "elapsed_ms": 1.0, "tls": None,
        }
        for status in (500, 200)
    ]
    fetcher = ReplayFetcher(records)
    fetcher.bind("e1")
    assert (await fetcher.fetch(RESOURCE)).status == 500
    assert (await fetcher.fetch(RESOURCE)).status == 200
    # Past the end the last stored response repeats rather than raising: the queue is
    # exhausted, not missing, and a check that loops one extra time must not turn a
    # successful replay into a spurious R8 failure.
    assert (await fetcher.fetch(RESOURCE)).status == 200


def test_compare_reports_names_the_check_that_changed():
    """`--verify` has to say *what* diverged, not merely that something did — otherwise a
    failed R8 check is a dead end rather than a bug report."""
    from datetime import UTC, datetime

    from agentidprobe.models import CheckResult, EndpointReport, NormativeStrength

    def report(outcome):
        return EndpointReport(
            endpoint=_endpoint(), modality=Modality.OAUTH_METADATA, reachable=True,
            checks=[CheckResult(check_id=CheckId.PRM_RESOURCE_IDENTITY_MATCH,
                                outcome=outcome,
                                normative_strength=NormativeStrength.MUST,
                                spec_ref="RFC 9728 3.3")],
            probed_at=datetime.now(UTC), run_id="r",
        )

    differences = compare_reports([report(Outcome.PASS)],
                                  [report(Outcome.FAIL_MISIMPLEMENTED)])
    assert len(differences) == 1
    assert "C12" in differences[0]
    assert "pass -> fail_misimplemented" in differences[0]
    assert compare_reports([report(Outcome.PASS)], [report(Outcome.PASS)]) == []
