"""Command line entry point.

Four verbs, matching the four things a reviewer needs to be able to redo:

    collect    build the corpus from free registries
    probe      run the measurement, resumable
    summarise  read stored reports and print the funnels
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
    capture_recapture_estimate,
    merge_endpoints,
)
from .config import DEFAULT_CONFIG, PROBE_VERSION
from .fetcher import Fetcher
from .models import Modality, RunContext
from .replay import compare_reports
from .runner import Runner, derive_card_endpoints, rescore, summarise
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
        if not args.official_only:
            smithery = SmitheryRegistry(fetcher, max_pages=args.max_pages)
            smithery_endpoints = await smithery.collect()
            smithery_stats = smithery.stats.as_dict()
            print(json.dumps(smithery_stats, indent=2))

    endpoints = merge_endpoints(official_endpoints, smithery_endpoints)
    store.write_corpus(endpoints)

    apexes = {e.apex_domain for e in endpoints if e.apex_domain}
    recapture = (
        capture_recapture_estimate(official_endpoints, smithery_endpoints)
        if smithery_endpoints else None
    )
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
            "capture_recapture": recapture,
        },
    )
    print(f"\ncorpus: {len(endpoints)} endpoints across {len(apexes)} apex domains")
    if recapture:
        print(f"capture-recapture population estimate: {recapture}")
    print(f"written to {store.corpus_path}")
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
    collect.add_argument("--max-pages", type=int, default=500)
    collect.add_argument("--official-only", action="store_true")
    collect.add_argument("--vantage-point", default="unspecified",
                         help="where the run originates, e.g. residential-TR")
    collect.set_defaults(func=lambda a: asyncio.run(_cmd_collect(a)))

    probe = sub.add_parser("probe", help="run the measurement over a collected corpus")
    probe.add_argument("--run-id", required=True)
    probe.add_argument("--limit", type=int, default=0, help="probe only the first N endpoints")
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

    dry = sub.add_parser("dry-run", help="probe a few URLs and print verdicts, no writes")
    dry.add_argument("urls", nargs="+")
    dry.set_defaults(func=lambda a: asyncio.run(_cmd_dry_run(a)))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
