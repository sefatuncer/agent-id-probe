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
import contextvars
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from .checks_oauth import probe_oauth
from .checks_signed import probe_signed
from .collectors import apex_domain, classify_hosting, endpoint_id
from .config import PROBE_VERSION, MeasurementConfig
from .fetcher import ErrorKind, Fetcher, FetchResult
from .models import (
    CheckResult,
    Endpoint,
    EndpointKind,
    EndpointReport,
    Modality,
    Outcome,
)
from .replay import ArtefactMissing, ReplayFetcher
from .store import RunStore

AGENT_CARD_PATH = "/.well-known/agent-card.json"


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def rehearsal_slice(endpoints: list, size: int) -> list:
    """A deterministic, apex-spread subset for the narrow-slice rehearsal (ETHICS.md §11.3).

    Written on 30 July 2026, immediately before the rehearsal, because `--limit N` was the
    only way to take a subset and it takes the *first* N in corpus order. That order is the
    registry's pagination order, which is broadly newest-first — and recency correlates with
    operational maturity, which correlates with sitting behind a WAF, which is the block rate
    the rehearsal exists to measure. A first-N slice would therefore have produced a
    misleadingly low block rate and cleared the run on it. The one number the rehearsal must
    get right is the one `--limit` would have biased.

    Two properties, in order of importance:

    **One endpoint per apex first.** Bulk publishers list hundreds of endpoints under a single
    apex, so a naive sample of 200 can be a handful of operators. Since the rehearsal is
    measuring how *hosts* respond to us, it takes one endpoint per apex before taking a second
    from any, which also keeps the per-host request count at its minimum for a rehearsal --
    fewer requests per operator, more operators, at no cost.

    **Deterministic and independent of registry order.** Selection is by `endpoint_id`, which
    is already a SHA-256 prefix of the URL: uniform, stable across runs, and unrelated to when
    a server was registered. So the slice is reproducible without storing a seed, and the same
    corpus yields the same slice on a re-run -- which R8's determinism requirement needs, and
    which `random.sample` would not give.
    """
    if size <= 0 or size >= len(endpoints):
        return list(endpoints)

    by_apex: dict[str, list] = {}
    for endpoint in endpoints:
        # Endpoints with no resolvable apex form their own group each: they are the case where
        # we cannot tell one operator from another, and folding them together would let a
        # single unresolvable host crowd out the rest of them.
        key = endpoint.apex_domain or f"?{endpoint.endpoint_id}"
        by_apex.setdefault(key, []).append(endpoint)
    for group in by_apex.values():
        group.sort(key=lambda e: e.endpoint_id)

    chosen: list = []
    depth = 0
    while len(chosen) < size:
        layer = [group[depth] for group in by_apex.values() if len(group) > depth]
        if not layer:
            break
        layer.sort(key=lambda e: e.endpoint_id)
        chosen.extend(layer[: size - len(chosen)])
        depth += 1
    return chosen


def sample_per_host(endpoints: list, cap: int) -> tuple[list, dict[str, int]]:
    """Bound how many endpoints on one hostname are measured. Returns (sampled, excluded).

    Written on 30 July 2026, after the narrow-slice rehearsal showed the census could not
    run as configured. The corpus is 10,653 endpoints on 7,681 hostnames, but the shape is
    extremely uneven: `gateway.pipeworx.io` alone carries 1,281 of them, and 2,015 endpoints
    sit on the 11 hostnames with more than 30 each.

    `RatePolicy.max_requests_per_host` caps one host at 30 requests per pass, which is the
    right promise to a third party who never consented to being probed. But an endpoint
    costs two to six requests, so on the largest host the ceiling is spent after roughly
    five to fifteen endpoints and the remaining ~1,270 come back `OUT_OF_SCOPE` with
    `reachable=False` -- which the kill switch reads as failure. Around a fifth of the
    corpus would have been recorded as unreachable because of our own configuration, the
    abort would have fired, and its message would have blamed the ecosystem.

    Raising the ceiling is the wrong repair: it would send one operator some 7,700 requests,
    which is what the ceiling was added to prevent. So the endpoints are sampled instead of
    being attempted and lost, and the difference matters in three ways.

    * **The unmeasured ones are named.** They leave as a counted, reported exclusion with a
      reason, not as several thousand indistinguishable errors. Every denominator rule in
      this instrument exists to stop our own policy moving a published rate silently.
    * **It costs almost nothing.** A thousand registry listings on one hostname are one
      deployment answering a thousand times; R10.2b's implementation fingerprint already
      treats them as one cluster, and the primary unit of analysis is the apex.
    * **It is the kinder option.** Fewer requests reach the operator than the ceiling alone
      would have allowed, because we stop asking rather than asking and being refused.

    What it costs is a claim: at the endpoint unit this is a census of hostnames and a
    sample within the large ones, and the paper has to say so. The frame is not lost -- the
    full corpus is written to `corpus.jsonl` before this runs -- so the sampling fraction is
    recoverable by anyone who reads the artefact.

    Selection is by `endpoint_id` (a SHA-256 prefix of the URL) for the same reason the
    rehearsal slice uses it: deterministic, independent of registry order, reproducible
    without a stored seed, which R8 requires.
    """
    if cap <= 0:
        return list(endpoints), {}

    by_host: dict[str, list] = {}
    for endpoint in endpoints:
        host = urlsplit(endpoint.url).hostname or urlsplit(endpoint.url).netloc
        by_host.setdefault(host, []).append(endpoint)

    sampled: list = []
    excluded: dict[str, int] = {}
    for host, group in by_host.items():
        if len(group) <= cap:
            sampled.extend(group)
            continue
        group.sort(key=lambda e: e.endpoint_id)
        sampled.extend(group[:cap])
        excluded[host] = len(group) - cap

    # Corpus order is otherwise preserved, so a run without large hosts is unchanged.
    order = {e.endpoint_id: i for i, e in enumerate(endpoints)}
    sampled.sort(key=lambda e: order[e.endpoint_id])
    return sampled, excluded


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
    endpoint: Endpoint, modality: Modality, fetched: FetchResult, checks, run_id: str,
    evidence: dict | None = None,
) -> EndpointReport:
    return EndpointReport(
        endpoint=endpoint,
        modality=modality,
        evidence=evidence or {},
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
        opted_out=fetched.error_kind is ErrorKind.OPTED_OUT,
        checks=list(checks),
        probed_at=fetched.fetched_at,
        run_id=run_id,
    )


def _error_report(
    endpoint: Endpoint, modality: Modality, run_id: str, exc: BaseException
) -> EndpointReport:
    """A report for an endpoint whose probe raised, so that it stays in the ledger.

    An unexpected exception is a fault in the instrument, not an observation of the operator,
    so every check it would have emitted is `ERROR` under R4 and the endpoint leaves every
    denominator — the same treatment as a block or a robots exclusion. What it must not do is
    leave the record, which is what happened before this existed.
    """
    from .models import FUNNELS, NormativeStrength

    detail = f"not observed: the probe raised {type(exc).__name__}: {exc}"[:500]
    checks = [
        CheckResult(check_id=check, outcome=Outcome.ERROR,
                    normative_strength=NormativeStrength.MUST, detail=detail)
        for _, check in FUNNELS[modality][1:] if check is not None
    ]
    return EndpointReport(
        endpoint=endpoint, modality=modality, reachable=False,
        checks=checks, probed_at=datetime.now(UTC), run_id=run_id,
    )


class Runner:
    def __init__(self, store: RunStore, config: MeasurementConfig) -> None:
        self.store = store
        self.config = config
        self._aborted = False
        self._abort_reason: str | None = None
        self._seen = 0
        self._failed = 0
        self._skipped = 0
        # Counted, not folded away: the exclusions our own policy caused are a number the
        # paper reports, not a silence.
        self._robots_excluded = 0
        self._not_sampled = 0

    def _observe_outcome(self, report: EndpointReport) -> None:
        """The global kill switch of docs/ETHICS.md 10.

        The per-host failure budget protects individual operators but is blind to a run
        that has gone wrong as a whole — a rate policy that turns out to be too aggressive,
        a User-Agent everything rejects, a broken vantage point. Those look fine host by
        host and unmistakable in aggregate. Past the threshold the measurement is
        describing our own reception rather than the ecosystem, so it stops rather than
        collecting thousands more endpoints of undefendable data.
        """
        if report.opted_out:
            # An operator who asked to be left alone is not evidence that the run is going
            # badly. Counting them here would let the opt-out list itself trip the abort.
            return
        if not report.robots_allowed:
            # The same argument, on the branch that was missed when the opt-out one was
            # added on 29 July 2026. A robots exclusion is not an endpoint we failed to
            # reach: we reached the host, read its rules, and chose not to ask. ETHICS.md 10
            # defines this threshold over endpoints that were "unreachable or blocked", and
            # a robots exclusion is neither.
            #
            # Measured in the narrow-slice rehearsal on 30 July 2026 rather than argued:
            # 30 of 198 endpoints were unreachable, 17 of them because of robots.txt. Our
            # own politeness policy was 8.6 of the 15.2 percentage points the kill switch
            # was reading -- more than half. Since Okta and Auth0 both serve `Disallow: /`
            # (ETHICS.md 6.1), a stratum heavy in hosted identity platforms could abort the
            # census on a property of the ecosystem while the abort message blamed our
            # reception. That inversion is the exact failure this threshold exists to catch,
            # so letting it fire that way would have been worse than not having it.
            self._robots_excluded += 1
            return
        self._seen += 1
        if not report.reachable:
            self._failed += 1
        policy = self.config.abort
        if self._aborted or self._seen < policy.min_endpoints_before_abort:
            return
        fraction = self._failed / self._seen
        if fraction > policy.max_failure_fraction:
            self._aborted = True
            self._abort_reason = (
                f"aborted after {self._seen} endpoints: {fraction:.1%} unreachable or "
                f"blocked, above the {policy.max_failure_fraction:.0%} ceiling"
            )
            print(f"  !! {self._abort_reason}")

    async def _probe_one(
        self, fetcher: Fetcher, endpoint: Endpoint, modality: Modality
    ) -> EndpointReport:
        fetched = await fetcher.fetch(endpoint.url)

        if modality is Modality.OAUTH_METADATA:
            checks, evidence = await probe_oauth(fetcher, endpoint.url, fetched)
            # The server header comes from the endpoint response, so the R10.2b
            # fingerprint is assembled here where both halves are in hand.
            record = evidence.as_record(fetched.headers.get("server"))
        else:
            checks, evidence = await probe_signed(fetcher, endpoint.url, fetched)
            record = evidence.as_record()

        report = _report_from(
            endpoint, modality, fetched, checks, self.store.run_id, evidence=record,
        )
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

        # Which endpoint a fetch belongs to is only known here, and the checks fetch
        # documents of their own. A context variable keeps the label correct while
        # endpoints are probed concurrently.
        current: contextvars.ContextVar[tuple[str, str]] = contextvars.ContextVar("current")

        def capture(result: FetchResult) -> None:
            try:
                endpoint_id, label = current.get()
            except LookupError:      # a fetch outside any endpoint (e.g. collection)
                return
            self.store.append_artifact(endpoint_id, label, result)

        async with Fetcher(self.config, on_fetch=capture) as fetcher:
            # The fetcher already caps global concurrency and enforces one request per
            # host per second; a task per endpoint is safe and keeps slow hosts from
            # blocking the rest.
            # A queue with a fixed pool, not `asyncio.gather` over every endpoint.
            # gather() creates a task per endpoint immediately, so all of them run their
            # abort check on the first pass through the event loop -- before any result
            # exists and therefore before the flag can ever be set. Measured on 250
            # synthetic endpoints with a suspending transport: the switch tripped at 200
            # and spared exactly zero requests. Only work that has not started yet can be
            # cancelled, so only work that has not been created yet can be skipped.
            queue: asyncio.Queue[Endpoint] = asyncio.Queue()
            for endpoint in pending:
                queue.put_nowait(endpoint)
            results: list[EndpointReport] = []
            label = "mcp" if modality is Modality.OAUTH_METADATA else "card"

            async def worker() -> None:
                nonlocal completed
                while True:
                    try:
                        endpoint = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    if self._aborted:
                        self._skipped += 1
                        queue.task_done()
                        continue
                    current.set((endpoint.endpoint_id, label))
                    try:
                        report = await self._probe_one(fetcher, endpoint, modality)
                        self._observe_outcome(report)
                        results.append(report)
                    except Exception as exc:  # noqa: BLE001 - one bad host must not end the run
                        # Keeping the run alive is right; letting the endpoint disappear is
                        # not, and until 30 July 2026 that is what happened -- no report was
                        # written, so the endpoint was absent from `reports.jsonl` entirely.
                        # Not counted, not excluded, not errored: simply not there, with one
                        # printed line as the only trace. Every denominator in `summarise`
                        # is computed over the reports, so a dropped endpoint shrinks the
                        # total silently, which is the failure mode the denominator rules
                        # exist to prevent.
                        #
                        # Demonstrated rather than theorised: regenerating the synthetic
                        # example run after R10.7 turned four reports into three, because
                        # one case's mock did not describe a request the instrument had
                        # newly begun to make. Nothing failed. Only R8's replay check
                        # noticed, and only because it compares against stored artefacts.
                        report = _error_report(endpoint, modality, self.store.run_id, exc)
                        self.store.append_report(report)
                        self._observe_outcome(report)
                        results.append(report)
                        print(f"  ! {endpoint.url}: {type(exc).__name__}: {exc}")
                    finally:
                        completed += 1
                        queue.task_done()
                        if progress_every and completed % progress_every == 0:
                            print(f"  [{modality.value}] {completed}/{len(pending)}")

            pool = min(self.config.rate.global_concurrency, max(1, len(pending)))
            await asyncio.gather(*(worker() for _ in range(pool)))

        if self._aborted:
            print(f"  !! {self._abort_reason}; {self._skipped} endpoint(s) never contacted")
        reports.extend(results)
        return reports


async def rescore(
    source: RunStore, destination: RunStore, config: MeasurementConfig
) -> list[EndpointReport]:
    """Recompute every verdict from stored artefacts, with no network access at all.

    This is decision rule R8's second leg executed rather than asserted. The checks are the
    same functions the live run used; only the fetcher is swapped, so a difference between
    the two runs is a difference in the instrument and nothing else.

    Writing to a separate store is not caution, it is a requirement: overwriting the
    original would destroy the very thing being compared against.
    """
    corpus = {e.endpoint_id: e for e in source.read_corpus()}
    stored = source.read_reports()
    artifacts = source.read_artifacts()
    # The checks read policy off the fetcher (the per-endpoint issuer cap, for one), so a
    # replay under a different configuration is scoring under different rules than the run
    # it claims to reproduce. `config` was accepted here and dropped on the floor.
    fetcher = ReplayFetcher(artifacts, config=config)

    destination.write_corpus(list(corpus.values()))
    out: list[EndpointReport] = []

    for report in stored:
        endpoint = corpus.get(report.endpoint.endpoint_id, report.endpoint)
        fetcher.bind(endpoint.endpoint_id)
        try:
            initial = await fetcher.fetch(endpoint.url)
        except ArtefactMissing:
            # The endpoint's own response was never stored, so there is nothing to
            # recompute from. Skipping it and saying so is honest; inventing a verdict is
            # not.
            print(f"  ! {endpoint.url}: no stored response, skipped")
            continue

        if report.modality is Modality.OAUTH_METADATA:
            checks, evidence = await probe_oauth(fetcher, endpoint.url, initial)
            record = evidence.as_record(initial.headers.get("server"))
        else:
            checks, evidence = await probe_signed(fetcher, endpoint.url, initial)
            record = evidence.as_record()

        rescored = _report_from(
            endpoint, report.modality, initial, checks, destination.run_id, evidence=record,
        )
        destination.append_report(rescored)
        out.append(rescored)

    return out


def summarise(reports: list[EndpointReport]) -> dict:
    """A quick, human-readable shape of the run. The paper's numbers come from the
    analysis module reading the stored reports, not from this.

    The denominator rules are the load-bearing part, and getting them wrong inverts the
    result rather than perturbing it. An endpoint that never opted into authorization
    scores NOT_APPLICABLE on every OAuth check; carrying it in the denominator while it
    cannot appear in the numerator counts *composition* as failure. On the phase-0 pilot
    that is the difference between "36.7% publish protected-resource metadata" — which
    merely replicates prior work — and "96.6% of the endpoints that require authorization
    publish it", which is the finding the paper actually argues, from the same data.

    So each stage reports three quantities, and the excluded ones are named rather than
    folded away:
      * `n`         passed the stage
      * `eligible`  denominator after removing what the stage cannot apply to
      * `excluded`  why the rest left: not_applicable (R1/composition) and error (R4/R5)

    Blocked and robots-excluded endpoints leave the study entirely, per the denominator
    rules in docs/decision-rules.md.
    """
    from .models import FUNNELS, Outcome

    by_modality: dict[str, dict] = {}
    for modality, stages in FUNNELS.items():
        subset = [r for r in reports if r.modality is modality]
        if not subset:
            continue

        # Neither a robots exclusion nor an opt-out is an observation of anything, and
        # keeping either in the total would let our own policy move the published rate.
        # They are counted separately because they mean different things: one is a
        # convention we chose to honour, the other is an operator's explicit request.
        excluded_opt_out = len([r for r in subset if r.opted_out])
        in_scope = [r for r in subset if r.robots_allowed and not r.opted_out]
        excluded_robots = len(subset) - len(in_scope) - excluded_opt_out

        # A document reached after a cross-origin redirect describes whoever answered, not
        # the host we asked about, so attributing its verdict to the original endpoint is a
        # silent misattribution. The denominator rules require these to be reported
        # separately; the helper that detects them existed and was never called.
        crossed = [r for r in in_scope if r.crossed_origin()]
        in_scope = [r for r in in_scope if not r.crossed_origin()]

        rows: list[dict] = []
        eligible = [r for r in in_scope if r.reachable]
        rows.append({
            "stage": "reachable",
            "n": len(eligible),
            "eligible": len(in_scope),
            "excluded": {"not_applicable": 0, "error": len(in_scope) - len(eligible)},
        })

        for label, check in stages[1:]:
            n_a = [r for r in eligible if r.outcome_of(check) is Outcome.NOT_APPLICABLE]
            err = [r for r in eligible if r.outcome_of(check) is Outcome.ERROR]
            applicable = [r for r in eligible if r not in n_a and r not in err]
            passed = [r for r in applicable if r.outcome_of(check) is Outcome.PASS]
            rows.append({
                "stage": label,
                "n": len(passed),
                "eligible": len(applicable),
                "excluded": {"not_applicable": len(n_a), "error": len(err)},
            })
            # The funnel invariant: a stage may only narrow the previous stage's PASS set.
            eligible = passed

        by_modality[modality.value] = {
            "total": len(subset),
            "in_scope": len(in_scope),
            "excluded_robots": excluded_robots,
            "excluded_opt_out": excluded_opt_out,
            "excluded_crossed_origin": len(crossed),
            "funnel": rows,
        }
    return {"probe_version": PROBE_VERSION, "modalities": by_modality}
