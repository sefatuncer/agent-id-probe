"""Measurement orchestration.

Two populations are probed, and the second is *derived* from the first. Public A2A
Agent Cards barely exist as an independently enumerable population — the phase-0 pilot
found two cards across forty-three likely corporate hosts — but probing the origins of
known MCP endpoints for `/.well-known/agent-card.json` surfaced twenty-five. So the
signed-document corpus is constructed from the OAuth corpus, and that derivation is
itself reported rather than hidden: it is the only way we know of to assemble a
non-trivial sample of deployed agent cards.

Each (endpoint, modality) pair produces one report, so an MCP endpoint and the agent
card served by its origin are separate units with separate denominators. Mixing them
would let one funnel's composition leak into the other's failure rate.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from .checks_oauth import probe_oauth
from .checks_signed import probe_signed
from .collectors import apex_domain, classify_hosting, endpoint_id
from .config import PROBE_VERSION, MeasurementConfig
from .fetcher import ErrorKind, Fetcher, FetchResult
from .models import (
    Endpoint,
    EndpointKind,
    EndpointReport,
    Modality,
)
from .store import RunStore

AGENT_CARD_PATH = "/.well-known/agent-card.json"


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def derive_card_endpoints(endpoints: list[Endpoint]) -> list[Endpoint]:
    """One agent-card candidate per distinct origin in the OAuth corpus."""
    now = datetime.now(UTC)
    derived: dict[str, Endpoint] = {}
    for endpoint in endpoints:
        card_url = origin_of(endpoint.url) + AGENT_CARD_PATH
        eid = endpoint_id(card_url)
        if eid in derived:
            continue
        derived[eid] = Endpoint(
            endpoint_id=eid,
            url=card_url,
            kind=EndpointKind.A2A_AGENT_CARD,
            source="derived:mcp-origin",
            source_url=endpoint.url,
            apex_domain=apex_domain(card_url),
            hosting=classify_hosting(card_url),
            registry_listed=False,
            first_seen=now,
            last_seen=now,
        )
    return list(derived.values())


def _report_from(
    endpoint: Endpoint, modality: Modality, fetched: FetchResult, checks, run_id: str
) -> EndpointReport:
    return EndpointReport(
        endpoint=endpoint,
        modality=modality,
        # A block is not unreachability: the host answered, a WAF did. Keeping them
        # apart matters because blocks correlate with the maturity we are measuring.
        reachable=fetched.status is not None and fetched.error_kind is not ErrorKind.BLOCKED,
        http_status=fetched.status,
        final_url=fetched.final_url,
        redirect_chain=fetched.redirect_chain,
        tls=fetched.tls,
        elapsed_ms=fetched.elapsed_ms,
        server_header=fetched.headers.get("server"),
        robots_allowed=fetched.error_kind is not ErrorKind.ROBOTS_DISALLOWED,
        checks=list(checks),
        probed_at=fetched.fetched_at,
        run_id=run_id,
    )


class Runner:
    def __init__(self, store: RunStore, config: MeasurementConfig) -> None:
        self.store = store
        self.config = config

    async def _probe_one(
        self, fetcher: Fetcher, endpoint: Endpoint, modality: Modality
    ) -> EndpointReport:
        fetched = await fetcher.fetch(endpoint.url)
        label = "mcp-endpoint" if modality is Modality.OAUTH_METADATA else "agent-card"
        self.store.append_artifact(endpoint.endpoint_id, label, fetched)

        if modality is Modality.OAUTH_METADATA:
            checks, _ = await probe_oauth(fetcher, endpoint.url, fetched)
        else:
            checks, _ = await probe_signed(fetcher, endpoint.url, fetched)

        report = _report_from(endpoint, modality, fetched, checks, self.store.run_id)
        self.store.append_report(report)
        return report

    async def run(
        self,
        endpoints: list[Endpoint],
        modality: Modality,
        *,
        resume: bool = True,
        progress_every: int = 50,
    ) -> list[EndpointReport]:
        done = self.store.completed_endpoint_ids() if resume else set()
        pending = [e for e in endpoints if e.endpoint_id not in done]
        if done:
            print(f"[{modality.value}] resuming: {len(done)} already scored, "
                  f"{len(pending)} to go")

        reports: list[EndpointReport] = []
        completed = 0

        async with Fetcher(self.config) as fetcher:
            # The fetcher already caps global concurrency and enforces one request per
            # host per second; a task per endpoint is safe and keeps slow hosts from
            # blocking the rest.
            async def worker(endpoint: Endpoint) -> EndpointReport | None:
                nonlocal completed
                try:
                    report = await self._probe_one(fetcher, endpoint, modality)
                except Exception as exc:  # noqa: BLE001 - one bad host must not end the run
                    print(f"  ! {endpoint.url}: {type(exc).__name__}: {exc}")
                    return None
                finally:
                    completed += 1
                    if progress_every and completed % progress_every == 0:
                        print(f"  [{modality.value}] {completed}/{len(pending)}")
                return report

            results = await asyncio.gather(*(worker(e) for e in pending))

        reports.extend(r for r in results if r is not None)
        return reports


def summarise(reports: list[EndpointReport]) -> dict:
    """A quick, human-readable shape of the run. The paper's numbers come from the
    analysis module reading the stored reports, not from this."""
    from .models import FUNNELS, Outcome

    by_modality: dict[str, dict] = {}
    for modality, stages in FUNNELS.items():
        subset = [r for r in reports if r.modality is modality]
        if not subset:
            continue
        rows: list[dict] = []
        eligible = [r for r in subset if r.reachable]
        rows.append({"stage": "reachable", "n": len(eligible), "of": len(subset)})
        for label, check in stages[1:]:
            passed = [r for r in eligible if r.outcome_of(check) is Outcome.PASS]
            rows.append({"stage": label, "n": len(passed), "of": len(eligible)})
            eligible = passed
        by_modality[modality.value] = {"total": len(subset), "funnel": rows}
    return {"probe_version": PROBE_VERSION, "modalities": by_modality}
