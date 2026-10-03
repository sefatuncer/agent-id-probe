"""Fixes from the final review of 3 October 2026, each pinned so that reverting it fails.

The review ran a mutation pass over the day's corrections and found six that no test held:
the failure audit's protected-resource arm, the redaction of the published audit, the exact
zero bound, the served-under sensitivity, the order in which a withheld candidate and a
malformed document are judged, and the refusal detail the sampling weights read. It also
found three defects in the corrections themselves, which are pinned here as well: a replay
aligned to the wrong attempt of a resumed probe, an issuer denominator that still counted
issuers our own policy never asked, and an issuer loop that scored a document behind a
location it had withheld.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import respx

from agentidprobe.analysis import (
    _zero_bound_by_domain,
    ceiling_refused,
    issuer_documents,
    served_under_sensitivity,
)
from agentidprobe.checks_oauth import probe_oauth
from agentidprobe.config import MeasurementConfig, RatePolicy
from agentidprobe.fetcher import ErrorKind, Fetcher, FetchResult, is_ceiling_refusal
from agentidprobe.models import (
    CheckId,
    CheckResult,
    Endpoint,
    EndpointKind,
    EndpointReport,
    Modality,
    NormativeStrength,
    Outcome,
)
from agentidprobe.replay import ReplayFetcher

ROOT = Path(__file__).resolve().parents[1]
FAST = MeasurementConfig(rate=RatePolicy(
    per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0))


def _audit_module():
    spec = importlib.util.spec_from_file_location("audit_failures",
                                                  ROOT / "scripts" / "audit_failures.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_failures"] = module
    spec.loader.exec_module(module)
    return module


def _report(url: str, checks, evidence=None, status=401) -> EndpointReport:
    return EndpointReport(
        endpoint=Endpoint(endpoint_id=url[-12:], url=url, kind=EndpointKind.MCP_REMOTE,
                          source="t", apex_domain="example.com"),
        modality=Modality.OAUTH_METADATA, reachable=True, http_status=status,
        checks=checks, evidence=evidence or {}, probed_at=datetime.now(UTC), run_id="r")


def _check(check_id, outcome, **kw):
    return CheckResult(check_id=check_id, outcome=outcome,
                       normative_strength=NormativeStrength.MUST, **kw)


# --- the audit -------------------------------------------------------------------------

def test_the_audit_reads_protected_resource_candidates_by_url():
    """Version 1 skipped every artefact whose label lacked "prm" and so read nothing."""
    audit = _audit_module()
    url = "https://a.example.com/mcp"
    prm = "https://a.example.com/.well-known/oauth-protected-resource/mcp"
    body = base64.b64encode(json.dumps({"resource": url,
                                        "authorization_servers": []}).encode()).decode()
    artefacts = {"e": [{"url": prm, "label": "mcp", "status": 200, "body_b64": body,
                        "error_kind": "none", "fetched_at": "2026-08-07T12:00:00+00:00"}]}
    audit._index_first_success(artefacts)
    report = _report(url, []).model_copy(
        update={"endpoint": _report(url, []).endpoint.model_copy(update={"endpoint_id": "e"})})
    verdict, reason = audit._check_c05(report, {}, artefacts)
    assert verdict is True and "absent, empty or malformed" in reason


def test_the_published_audit_names_nobody():
    audit = _audit_module()
    record = {"findings": [{"check": "C13", "instrument": "fail_unimplemented",
                            "endpoint": "https://secret.example.com/mcp",
                            "reason": "requested 'https://issuer.example.net', returned x"}],
              "undecidable_cases": []}
    published = json.dumps(audit.redact(record))
    assert "example.com" not in published and "example.net" not in published


# --- analysis --------------------------------------------------------------------------

def test_the_zero_bound_is_the_exact_binomial_over_the_domains_read():
    docs = {f"https://i{i}.domain{i % 7}.org": {} for i in range(30)}
    bound = _zero_bound_by_domain(docs, lambda d: False)
    assert bound["m"] == 7
    assert math.isclose(bound["upper_exact"], 1 - 0.05 ** (1 / 7))
    assert not math.isclose(bound["upper_exact"], 3 / 7)


def test_the_served_under_reading_moves_hint_documents_both_ways_and_counts_strictly():
    hinted = {"prm_from_hint": True,
              "prm_url": "https://h.example.com/.well-known/oauth-protected-resource"}
    failing = _report("https://h.example.com/mcp",
                      [_check(CheckId.PRM_RESOURCE_IDENTITY_MATCH, Outcome.FAIL_MISIMPLEMENTED)],
                      {**hinted, "declared_resource": "https://h.example.com"})
    passing = _report("https://h.example.com/other/mcp",
                      [_check(CheckId.PRM_RESOURCE_IDENTITY_MATCH, Outcome.PASS)],
                      {**hinted, "declared_resource": "https://h.example.com/other/mcp"})
    result = served_under_sensitivity([failing, passing])
    assert (result["fail_to_pass"], result["pass_to_fail"]) == (1, 1)
    assert result["to_or_from_unspecified"] == 0


def test_an_issuer_our_policy_never_asked_leaves_the_declared_denominator():
    """E2. robots.txt kept us from asking `blocked`, `dead` was asked and served nothing."""
    evidence = {"authorization_servers": ["https://blocked.example", "https://dead.example",
                                          "https://live.example"],
                "as_documents": {"https://live.example": {"issuer": "https://live.example"}},
                "as_errors": {
                    "https://blocked.example": "authorization server metadata not observed (R4)",
                    "https://dead.example": "metadata not retrievable at any well-known location"}}
    declared = issuer_documents([_report("https://r.example.com/mcp", [], evidence)], "declared")
    assert set(declared) == {"https://dead.example", "https://live.example"}
    assert declared["https://dead.example"] is None


def test_a_refused_first_request_marks_the_endpoint_as_never_asked():
    """The sampling weights read this from the stored report, so it must be written there."""
    url = "https://a.example.com/mcp"
    refused = FetchResult(url=url, ok=False, error_kind=ErrorKind.OUT_OF_SCOPE,
                          error_detail="host has already received 30 requests this pass")

    async def run():
        async with Fetcher(FAST) as f:
            return await probe_oauth(f, url, refused)

    import asyncio
    checks, _ = asyncio.run(run())
    assert ceiling_refused(_report(url, checks, status=None))


# --- checks ----------------------------------------------------------------------------

@respx.mock
async def test_a_withheld_candidate_is_judged_before_a_malformed_one():
    """The path form answers HTML and our ceiling refuses the root form. The root form, which
    we did not ask, may hold the real document, so this is not observed, not misimplemented."""
    host = "a.example.com"
    url = f"https://{host}/mcp"
    respx.get(f"https://{host}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(f"https://{host}/.well-known/oauth-protected-resource/mcp").mock(
        return_value=httpx.Response(200, text="<html>app</html>",
                                    headers={"content-type": "text/html"}))
    ceiling = MeasurementConfig(rate=RatePolicy(
        per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0,
        max_requests_per_host=2))
    async with Fetcher(ceiling) as f:
        checks, _ = await probe_oauth(f, url, FetchResult(url=url, ok=True, status=401))
    assert next(c.outcome for c in checks
                if c.check_id is CheckId.PRM_PRESENT) is Outcome.ERROR


@respx.mock
async def test_an_issuer_document_behind_a_withheld_location_is_not_scored():
    """D6. robots.txt forbids the RFC 8414 location and the OpenID location answers."""
    host, issuer = "a.example.com", "https://auth.example.net"
    url = f"https://{host}/mcp"
    respx.get(f"https://{host}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(f"https://{host}/.well-known/oauth-protected-resource/mcp").mock(
        return_value=httpx.Response(200, json={"resource": url,
                                               "authorization_servers": [issuer]}))
    respx.get(f"{issuer}/robots.txt").mock(return_value=httpx.Response(
        200, text="User-agent: *\nDisallow: /.well-known/oauth-authorization-server\n"))
    respx.get(f"{issuer}/.well-known/openid-configuration").mock(
        return_value=httpx.Response(200, json={"issuer": "https://someone-else.example"}))
    async with Fetcher(FAST) as f:
        checks, _ = await probe_oauth(f, url, FetchResult(url=url, ok=True, status=401))
    assert next(c.outcome for c in checks
                if c.check_id is CheckId.AS_CORRESPONDENCE) is Outcome.ERROR


# --- replay ----------------------------------------------------------------------------

def _rec(endpoint, url, when, **kw):
    return {"endpoint_id": endpoint, "url": url, "label": "mcp", "ok": kw.get("ok", False),
            "status": kw.get("status"), "headers": {}, "body_b64": kw.get("body_b64", ""),
            "error_kind": kw.get("error_kind", "none"), "error_detail": "",
            "fetched_at": when.isoformat(), **({"artifact_schema": kw["schema"]}
                                               if "schema" in kw else {})}


async def test_replay_aligns_a_resumed_endpoint_to_its_last_attempt():
    """E1. The report of a resumed probe comes from its last attempt."""
    t = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    url, prm = "https://a.example.com/mcp", "https://a.example.com/.well-known/oauth-protected-resource/mcp"
    artifacts = [
        _rec("e", url, t, status=401, ok=True),
        _rec("e", prm, t + timedelta(seconds=1), error_kind="dns"),
        _rec("e", url, t + timedelta(hours=2), status=401, ok=True),
        _rec("e", prm, t + timedelta(hours=2, seconds=1), status=200, ok=True,
             body_b64="e30="),
    ]
    replay = ReplayFetcher(artifacts)
    replay.bind("e", url)
    await replay.fetch(url)
    assert (await replay.fetch(prm)).status == 200


async def test_a_schema_two_refusal_is_the_live_outcome_and_is_not_re_decided():
    """E1c. A live run records every reuse it made; replay must not answer more."""
    t = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    as_url = "https://auth.example.org/.well-known/oauth-authorization-server"
    artifacts = [
        _rec("first", as_url, t, status=200, ok=True, body_b64="e30=", schema=2),
        {**_rec("later", as_url, t + timedelta(minutes=1), error_kind="out_of_scope",
                schema=2),
         "error_detail": "host has already received 30 requests this pass"},
    ]
    replay = ReplayFetcher(artifacts, unrequested_metadata_not_observed=True)
    assert not replay.legacy
    replay.bind("later")
    assert is_ceiling_refusal(await replay.fetch(as_url))
