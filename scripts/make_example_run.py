"""Generate the committed example run under `results/runs/example/`.

The repository ships one tiny, fully synthetic run so that three things are possible
without contacting anybody:

  * a reader can see what the output files actually look like before running anything,
  * `docs/data-schema.md` has real records to point at rather than described ones,
  * `agent-id-probe rescore --run-id example --verify` can run in CI, which turns decision
    rule R8 from a sentence in a document into a build step.

Every host below is under `example.org`, reserved by RFC 2606 precisely so that synthetic
data cannot be mistaken for a measurement of somebody's real deployment. The endpoints are
hand-built to cover the interesting verdicts rather than the common ones: a conforming
server, a resource-identifier mismatch, an issuer that does not answer, and an open server
that never opted into authorization at all.

Run with:  python scripts/make_example_run.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentidprobe.collectors import apex_domain, endpoint_id  # noqa: E402
from agentidprobe.config import MeasurementConfig, RatePolicy  # noqa: E402
from agentidprobe.models import Endpoint, EndpointKind, Modality, RunContext  # noqa: E402
from agentidprobe.runner import Runner, summarise  # noqa: E402
from agentidprobe.store import RunStore  # noqa: E402

FAST = MeasurementConfig(
    rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0)
)

# (endpoint url, what it demonstrates)
CASES = [
    ("https://conforming.example.org/mcp", "everything matches"),
    ("https://mismatch.example.org/mcp", "PRM names a different resource (C12 fails)"),
    ("https://deadissuer.example.org/mcp", "declared issuer serves no metadata (C13 fails)"),
    ("https://open.example.org/mcp", "no authorization at all (checks not applicable)"),
]


def _mock() -> None:
    for host in ("conforming", "mismatch", "deadissuer", "open", "auth"):
        respx.get(f"https://{host}.example.org/robots.txt").mock(
            return_value=httpx.Response(404))
    respx.get(url__regex=r"https://\w+\.example\.org/\.well-known/agent-card\.json").mock(
        return_value=httpx.Response(404))
    respx.get(url__regex=r"https://\w+\.example\.org/\.well-known/agent\.json").mock(
        return_value=httpx.Response(404))

    issuer = "https://auth.example.org"
    as_doc = {
        "issuer": issuer,
        "code_challenge_methods_supported": ["S256"],
        "revocation_endpoint": f"{issuer}/revoke",
        "authorization_response_iss_parameter_supported": True,
    }
    respx.get(f"{issuer}/.well-known/oauth-authorization-server").mock(
        return_value=httpx.Response(200, json=as_doc))

    # 1. Fully conforming.
    respx.get("https://conforming.example.org/mcp").mock(return_value=httpx.Response(401))
    respx.get("https://conforming.example.org/.well-known/oauth-protected-resource/mcp").mock(
        return_value=httpx.Response(200, json={
            "resource": "https://conforming.example.org/mcp",
            "authorization_servers": [issuer]}))

    # 2. Declares a resource identifier that is not its own.
    respx.get("https://mismatch.example.org/mcp").mock(return_value=httpx.Response(401))
    respx.get("https://mismatch.example.org/.well-known/oauth-protected-resource/mcp").mock(
        return_value=httpx.Response(200, json={
            "resource": "https://somewhere-else.example.org/mcp",
            "authorization_servers": [issuer]}))

    # 3. Names an issuer that publishes nothing.
    respx.get("https://deadissuer.example.org/mcp").mock(return_value=httpx.Response(401))
    respx.get("https://deadissuer.example.org/.well-known/oauth-protected-resource/mcp").mock(
        return_value=httpx.Response(200, json={
            "resource": "https://deadissuer.example.org/mcp",
            "authorization_servers": ["https://gone.example.org"]}))
    respx.get("https://gone.example.org/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url__regex=r"https://gone\.example\.org/.*").mock(
        return_value=httpx.Response(404))

    # 4. Open server: authorization is OPTIONAL in MCP, so nothing here is a failure.
    respx.get("https://open.example.org/mcp").mock(
        return_value=httpx.Response(200, json={"ok": True}))


@respx.mock
async def build() -> None:
    store = RunStore(ROOT, "example")
    for path in (store.reports_path, store.artifacts_path, store.corpus_path):
        path.unlink(missing_ok=True)

    endpoints = [
        Endpoint(endpoint_id=endpoint_id(url), url=url, kind=EndpointKind.MCP_REMOTE,
                 source="synthetic-example", apex_domain=apex_domain(url),
                 registry_listed=False)
        for url, _ in CASES
    ]
    store.write_corpus(endpoints)

    _mock()
    reports = await Runner(store, FAST).run(endpoints, Modality.OAUTH_METADATA,
                                            progress_every=0)

    store.write_manifest(
        RunContext(run_id="example", vantage_point="synthetic",
                   probe_git_commit=None, started_at=datetime.now(UTC)),
        extra={
            "stage": "probe",
            "synthetic": True,
            "note": "Hand-built demonstration data over RFC 2606 example.org hosts. "
                    "No real endpoint was contacted. Regenerate with "
                    "scripts/make_example_run.py.",
            "cases": [{"url": u, "demonstrates": d} for u, d in CASES],
            "endpoints": len(endpoints),
        },
    )

    print(f"{len(reports)} reports -> {store.reports_path}")
    print(f"{len(store.read_artifacts())} artefacts -> {store.artifacts_path}")
    for report in reports:
        verdicts = " ".join(f"{c.check_id.value}={c.outcome.value}" for c in report.checks)
        print(f"  {report.endpoint.url}\n    {verdicts}")
    print()
    import json
    print(json.dumps(summarise(reports), indent=2))


if __name__ == "__main__":
    asyncio.run(build())
