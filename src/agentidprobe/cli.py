"""Command line entry point.

Seven verbs, matching the things a reviewer needs to be able to redo:

    collect    build the corpus from free registries
    probe      run the measurement, resumable
    summarise  read stored reports and print the funnels
    analyse    execute decision rule R11 and write the headline transcript
    rescore    re-score stored artefacts with no network (decision rule R8, leg 2)
    figures    render Figures 1 and 2, from a run or from the synthetic fixture
    dry-run    probe a handful of endpoints and print everything, no persistence

`probe` is deliberately resumable and deliberately slow. One request per host per
second against a few thousand hosts takes hours; that is the price of not degrading the
systems being measured.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from .collectors import (
    McpOfficialRegistry,
    SmitheryRegistry,
    merge_endpoints,
)
from .config import DEFAULT_CONFIG, PROBE_VERSION
from .fetcher import Fetcher
from .models import Modality, RunContext
from .replay import compare_reports
from .runner import (
    Runner,
    derive_card_endpoints,
    rehearsal_slice,
    rescore,
    sample_per_host,
    summarise,
)
from .store import RunStore


def _git_commit(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001 - provenance is nice to have, not required to run
        return None


def _default_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


async def _cmd_collect(args: argparse.Namespace) -> int:
    root = Path(args.root)
    store = RunStore(root, args.run_id)

    async with Fetcher(DEFAULT_CONFIG) as fetcher:
        official = McpOfficialRegistry(fetcher, max_pages=args.max_pages)
        official_endpoints = await official.collect()
        print(json.dumps(official.stats.as_dict(), indent=2))

        smithery_endpoints = []
        smithery_stats = None
        if args.include_smithery:
            smithery = SmitheryRegistry(fetcher, max_pages=args.max_pages)
            smithery_endpoints = await smithery.collect()
            smithery_stats = smithery.stats.as_dict()
            print(json.dumps(smithery_stats, indent=2))

    endpoints = merge_endpoints(official_endpoints, smithery_endpoints)
    store.write_corpus(endpoints)

    apexes = {e.apex_domain for e in endpoints if e.apex_domain}
    store.write_manifest(
        RunContext(
            run_id=args.run_id,
            vantage_point=args.vantage_point,
            probe_git_commit=_git_commit(root),
            started_at=datetime.now(UTC),
        ),
        extra={
            "stage": "collect",
            "sources": [official.stats.as_dict()] + ([smithery_stats] if smithery_stats else []),
            "endpoints": len(endpoints),
            "unique_apex_domains": len(apexes),
        },
    )
    print(f"\ncorpus: {len(endpoints)} endpoints across {len(apexes)} apex domains")
    print(f"written to {store.corpus_path}")

    # A truncated corpus is not a small corpus, it is the wrong population, and every rate
    # computed from it is conditioned on however far pagination happened to get. The manifest
    # has recorded `TRUNCATED` since 28 July 2026 and that was not enough: the exit code was 0,
    # so `probe` ran next and produced a clean-looking dataset over roughly three thousand of
    # some sixty thousand records. The paper's claim is a *census* of the frame, so the census
    # failing has to stop the pipeline rather than annotate it.
    truncated = [e for e in official.stats.errors + (smithery_stats or {}).get("errors", [])
                 if e.startswith("TRUNCATED")]
    if truncated:
        print("\nCOLLECTION INCOMPLETE -- refusing to report this as a census:", file=sys.stderr)
        for message in truncated:
            print(f"  {message}", file=sys.stderr)
        print("  Raise --max-pages and re-run. The corpus written above is a partial frame; "
              "probing it would produce rates conditioned on where pagination stopped.",
              file=sys.stderr)
        return 2
    return 0


async def _cmd_probe(args: argparse.Namespace) -> int:
    root = Path(args.root)
    store = RunStore(root, args.run_id)
    endpoints = store.read_corpus()
    if not endpoints:
        print(f"no corpus at {store.corpus_path}; run `collect` first", file=sys.stderr)
        return 2

    if args.limit:
        endpoints = endpoints[: args.limit]
    if args.sample:
        # Not `--limit`. See `rehearsal_slice`: corpus order is registry pagination order,
        # which correlates with the very property the rehearsal measures.
        endpoints = rehearsal_slice(endpoints, args.sample)
        print(f"rehearsal slice: {len(endpoints)} endpoints, one per apex before two from any")

    # The frame is the corpus on disk; this is the sample drawn from it. Reported here and
    # written to the manifest, because an exclusion nobody can count is an exclusion nobody
    # can check -- see `sample_per_host` for why the alternative was silent data loss.
    frame_size = len(endpoints)
    endpoints, not_sampled = sample_per_host(
        endpoints, DEFAULT_CONFIG.scope.max_endpoints_per_host)
    if not_sampled:
        dropped = sum(not_sampled.values())
        print(f"per-host sampling: {len(endpoints)}/{frame_size} endpoints measured; "
              f"{dropped} not sampled on {len(not_sampled)} hostname(s) over the "
              f"{DEFAULT_CONFIG.scope.max_endpoints_per_host}-endpoint cap")
        for host, count in sorted(not_sampled.items(), key=lambda kv: -kv[1])[:5]:
            print(f"    {host}: {count} not sampled")
    # Written whether or not anything was excluded, so that "no file" means "this run
    # predates the rule" rather than "nothing was dropped" -- two states the exclusion
    # ledger in the results section must not confuse.
    (store.run_dir / "sampling.json").write_text(
        json.dumps({
            "rule": "sample_per_host",
            "max_endpoints_per_host": DEFAULT_CONFIG.scope.max_endpoints_per_host,
            "frame_endpoints": frame_size,
            "sampled_endpoints": len(endpoints),
            "not_sampled_total": sum(not_sampled.values()),
            "not_sampled_by_host": dict(sorted(not_sampled.items())),
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    runner = Runner(store, DEFAULT_CONFIG)
    print(f"probing {len(endpoints)} MCP endpoints "
          f"(1 req/host/s, {DEFAULT_CONFIG.rate.global_concurrency} concurrent)")
    oauth_reports = await runner.run(endpoints, Modality.OAUTH_METADATA, resume=not args.no_resume)

    signed_reports = []
    if not args.skip_cards:
        cards = derive_card_endpoints(endpoints)
        print(f"\nprobing {len(cards)} derived agent-card locations")
        signed_reports = await runner.run(
            cards, Modality.SIGNED_DOCUMENT, resume=not args.no_resume
        )

    print("\n" + json.dumps(summarise(oauth_reports + signed_reports), indent=2))
    print(f"\nreports: {store.reports_path}\nraw artefacts: {store.artifacts_path}")
    return 0


def _cmd_summarise(args: argparse.Namespace) -> int:
    store = RunStore(Path(args.root), args.run_id)
    reports = store.read_reports()
    if not reports:
        print(f"no reports at {store.reports_path}", file=sys.stderr)
        return 2
    print(json.dumps(summarise(reports), indent=2))
    return 0


def _cmd_analyse(args: argparse.Namespace) -> int:
    """Execute decision rule R11 and write the transcript beside the run.

    Until 29 July 2026 this command did not exist and `analysis.py` had no caller outside
    the figures module: `select_headline` -- the function that picks what the paper leads
    with, and through R11.4 what it is called -- was reachable only from its own unit test.
    A selection rule nobody can run is a paragraph, not a rule.

    The transcript is written to disk rather than printed alone because R11.2 has to be an
    event with a record. Reading a summary and forming a view is what R11 exists to stop.
    """
    from .analysis import analyse

    store = RunStore(Path(args.root), args.run_id)
    reports = store.read_reports()
    if not reports:
        print(f"no reports at {store.reports_path}", file=sys.stderr)
        return 2

    result = analyse(reports, conf=args.conf)
    destination = store.run_dir / "analysis.json"
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")

    print(f"headline: {result['headline']['selected']}")
    print(f"  because {result['headline']['reason']}\n")
    for candidate in result["candidates"]:
        estimate = candidate["estimate"]
        verdict = "passed" if candidate["variance_test"]["passed"] else "FAILED"
        print(f"  rank {candidate['rank']}  {candidate['label']}")
        print(f"      {estimate['p_hat']:.1%} "
              f"[{estimate['ci_lo']:.1%}, {estimate['ci_hi']:.1%}] "
              f"n={estimate['n']} m={estimate['m']} ({candidate['denominator']}) "
              f"-- variance test {verdict}")
    print(f"\nwritten to {destination}")
    return 0


def _cmd_figures(args: argparse.Namespace) -> int:
    """Render Figures 1 and 2, from a stored run or from the synthetic fixture.

    `--synthetic` exists so that the figures can be produced with no measurement at all.
    That is not a convenience: it is how a reader checks the claim in `figures.py` that
    the plots were designed before the data, since the fixture run and the real run
    produce the same figure with different numbers in it.
    """
    try:
        from .figures import render_all, synthetic_population
    except ImportError as exc:                        # pragma: no cover - env-dependent
        print(f"figures need the optional extra: pip install '.[figures]'  ({exc})",
              file=sys.stderr)
        return 2

    root = Path(args.root)
    if args.synthetic:
        reports = synthetic_population()
        out_dir = Path(args.out) if args.out else root / "results" / "figures" / "synthetic"
    else:
        if not args.run_id:
            print("give --run-id, or --synthetic to draw from the fixture", file=sys.stderr)
            return 2
        reports = RunStore(root, args.run_id).read_reports()
        if not reports:
            print(f"no reports for run {args.run_id}", file=sys.stderr)
            return 2
        out_dir = Path(args.out) if args.out else root / "results" / "figures" / args.run_id

    result = render_all(reports, out_dir, formats=tuple(args.format.split(",")),
                        synthetic=args.synthetic)
    for path in result["written"]:
        print(path)
    print(out_dir / "figure-data.json")
    return 0


async def _cmd_rescore(args: argparse.Namespace) -> int:
    """Decision rule R8, leg 2, as a command a reviewer can run in one line.

    Re-scores a stored run entirely from saved artefacts. `--verify` additionally asserts
    that the verdicts are unchanged, which is what makes R8 a checkable property rather
    than a promise in a document.
    """
    root = Path(args.root)
    source = RunStore(root, args.run_id)
    stored = source.read_reports()
    if not stored:
        print(f"no reports at {source.reports_path}", file=sys.stderr)
        return 2
    if not source.artifacts_path.exists():
        print(f"no raw artefacts at {source.artifacts_path}; this run cannot be "
              f"re-scored offline", file=sys.stderr)
        return 2

    destination = RunStore(root, args.into or f"{args.run_id}-rescored")
    print(f"re-scoring {len(stored)} reports from stored artefacts "
          f"(no network) into {destination.run_dir}")
    rescored = await rescore(source, destination, DEFAULT_CONFIG)

    destination.write_manifest(
        RunContext(
            run_id=destination.run_id,
            vantage_point="offline-replay",
            probe_git_commit=_git_commit(root),
            started_at=datetime.now(UTC),
        ),
        extra={
            "stage": "rescore",
            "rescored_from": args.run_id,
            "rescore_probe_version": PROBE_VERSION,
            "reports_in": len(stored),
            "reports_out": len(rescored),
        },
    )

    if not args.verify:
        print(f"\n{len(rescored)} reports written to {destination.reports_path}")
        return 0

    differences = compare_reports(stored, rescored)
    if not differences:
        print(f"\nR8 replay determinism: {len(rescored)} reports, verdicts identical.")
        return 0
    print(f"\nR8 replay determinism FAILED: {len(differences)} difference(s)", file=sys.stderr)
    for line in differences[:50]:
        print(f"  {line}", file=sys.stderr)
    if len(differences) > 50:
        print(f"  ... and {len(differences) - 50} more", file=sys.stderr)
    return 1


async def _cmd_dry_run(args: argparse.Namespace) -> int:
    """Probe a few URLs and print the verdicts. Nothing is written; this exists so the
    instrument can be sanity-checked against real hosts before a wide run."""
    from .checks_oauth import probe_oauth

    async with Fetcher(DEFAULT_CONFIG) as fetcher:
        for url in args.urls:
            fetched = await fetcher.fetch(url)
            print(f"\n=== {url}")
            print(f"  status={fetched.status} error={fetched.error_kind.value} "
                  f"elapsed={fetched.elapsed_ms:.0f}ms" if fetched.elapsed_ms
                  else f"  status={fetched.status} error={fetched.error_kind.value}")
            checks, evidence = await probe_oauth(fetcher, url, fetched)
            for check in checks:
                print(f"  {check.check_id.value} {check.outcome.value:<20} "
                      f"{check.observed_value or check.detail}")
            if evidence.authorization_servers:
                print(f"  declared issuers: {evidence.authorization_servers}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-id-probe", description=__doc__)
    parser.add_argument("--version", action="version", version=PROBE_VERSION)
    parser.add_argument("--root", default=".", help="project root for data/ and results/")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="build the corpus from free registries")
    collect.add_argument("--run-id", default=_default_run_id())
    # 5,000 pages x 100 records is 500,000, roughly eight times the registry's present size.
    # The old default of 500 was a trial-run number that had become the census default: at
    # 100 records a page it caps the corpus at 50,000 against some 60,000 records, so the
    # documented behaviour of the flag was to truncate the population the study is about.
    # A ceiling this loose cannot fire on the real registry, and if the registry ever grows
    # past it the run now exits non-zero rather than quietly reporting a partial frame.
    collect.add_argument(
        "--max-pages", type=int, default=5000,
        help="pagination ceiling per registry (default 5000 = 500k records; the run fails "
             "rather than truncating if it is reached)")
    # Smithery is opt-in as of 30 July 2026, inverting `--official-only`. It contributed zero
    # usable endpoints once the `homepage`-as-endpoint defect was fixed -- that field was a
    # project page, not an MCP endpoint, and it had been supplying 85% of the corpus as
    # garbage -- and the capture-recapture estimate that was the other reason to query it has
    # been withdrawn. Querying a second registry by default now means sending requests to a
    # third party for no measurement, which docs/ETHICS.md §3 does not permit.
    collect.add_argument(
        "--include-smithery", action="store_true",
        help="also query registry.smithery.ai (opt-in: it yields no remote endpoints)")
    collect.add_argument("--vantage-point", default="unspecified",
                         help="where the run originates, e.g. residential-TR")
    collect.set_defaults(func=lambda a: asyncio.run(_cmd_collect(a)))

    probe = sub.add_parser("probe", help="run the measurement over a collected corpus")
    probe.add_argument("--run-id", required=True)
    probe.add_argument("--limit", type=int, default=0,
                       help="probe only the first N endpoints, in corpus order")
    probe.add_argument(
        "--sample", type=int, default=0,
        help="probe a deterministic, apex-spread slice of N endpoints (ETHICS.md 11.3). "
             "Use this for the narrow-slice rehearsal, not --limit: corpus order is registry "
             "order, which is broadly newest-first and so correlates with WAF presence -- the "
             "block rate the rehearsal exists to measure")
    probe.add_argument("--skip-cards", action="store_true")
    probe.add_argument("--no-resume", action="store_true")
    probe.set_defaults(func=lambda a: asyncio.run(_cmd_probe(a)))

    summary = sub.add_parser("summarise", help="print funnels from stored reports")
    summary.add_argument("--run-id", required=True)
    summary.set_defaults(func=_cmd_summarise)

    rescore_cmd = sub.add_parser(
        "rescore", help="re-score a stored run from saved artefacts, with no network")
    rescore_cmd.add_argument("--run-id", required=True)
    rescore_cmd.add_argument("--into", default=None,
                             help="destination run id (default: <run-id>-rescored). The "
                                  "source run is never overwritten")
    rescore_cmd.add_argument("--verify", action="store_true",
                             help="fail with exit 1 if any verdict changed (decision rule R8)")
    rescore_cmd.set_defaults(func=lambda a: asyncio.run(_cmd_rescore(a)))

    analyse_cmd = sub.add_parser(
        "analyse", help="execute decision rule R11 and write the headline transcript")
    analyse_cmd.add_argument("--run-id", required=True)
    analyse_cmd.add_argument("--conf", type=float, default=0.95)
    analyse_cmd.set_defaults(func=_cmd_analyse)

    figures_cmd = sub.add_parser(
        "figures", help="render Figures 1 and 2 (needs the optional 'figures' extra)")
    figures_cmd.add_argument("--run-id", default=None)
    figures_cmd.add_argument("--synthetic", action="store_true",
                             help="draw from the synthetic fixture instead of a run")
    figures_cmd.add_argument("--out", default=None)
    figures_cmd.add_argument("--format", default="pdf,png",
                             help="comma-separated: pdf, png, svg")
    figures_cmd.set_defaults(func=_cmd_figures)

    dry = sub.add_parser("dry-run", help="probe a few URLs and print verdicts, no writes")
    dry.add_argument("urls", nargs="+")
    dry.set_defaults(func=lambda a: asyncio.run(_cmd_dry_run(a)))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
