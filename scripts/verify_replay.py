#!/usr/bin/env python3
"""Run decision rule R8's replay leg against the published runs and record the outcome.

Written 10 August 2026, because the manuscript claimed *"both published runs re-score
bit-identically from their stored artefacts"* and nobody had ever run the command against
them. `rescore --verify` had only ever been pointed at the synthetic `example` run, which is
four reports of our own construction and cannot fail. The claim was true of the thing that had
been tested and untested of the thing it named.

It is very nearly true. census1 reproduces every one of its verdicts. census2 reproduces all
but one endpoint, where the live run stopped at the path-suffixed metadata candidate and the
replay walks one candidate further to the root form, which was therefore never stored. That is
one endpoint of 8,896, and the honest sentence says so rather than rounding it to "identical".

Output: docs/replay-verification.json, committed, and read by the manuscript's build so the
number in the paper cannot drift from the number the command produces. Same pattern as
docs/wilson-coverage.json and docs/failure-audit-*.json.

    python scripts/verify_replay.py
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from agentidprobe.config import DEFAULT_CONFIG  # noqa: E402
from agentidprobe.replay import compare_reports  # noqa: E402
from agentidprobe.runner import rescore  # noqa: E402
from agentidprobe.store import RunStore  # noqa: E402

RUNS = ("census1", "census2")


async def verify(run_id: str) -> dict:
    source = RunStore(REPO, run_id)
    stored = source.read_reports()
    if not stored:
        return {"run_id": run_id, "error": "no reports"}

    # Clear the scratch run *before* constructing the store: RunStore creates its directory on
    # construction, so removing it afterwards deletes the directory the re-score writes into.
    scratch = f"{run_id}-replayverify"
    shutil.rmtree(REPO / "results" / "runs" / scratch, ignore_errors=True)
    destination = RunStore(REPO, scratch)

    rescored = await rescore(source, destination, DEFAULT_CONFIG)
    differences = compare_reports(stored, rescored)

    # A missing endpoint and a changed verdict are different failures and are counted apart.
    # Rounding them together would hide which of the two happened, and only one of them means
    # the instrument scores differently than it did.
    absent = [d for d in differences if "absent after replay" in d]
    changed = [d for d in differences if "absent after replay" not in d]

    shutil.rmtree(destination.run_dir, ignore_errors=True)
    return {
        "run_id": run_id,
        "reports_in": len(stored),
        "reports_out": len(rescored),
        "verdicts_changed": len(changed),
        "endpoints_not_replayable": len(absent),
        "identical": not differences,
        "differences": differences[:20],
    }


async def main() -> int:
    results = [await verify(run) for run in RUNS]
    total_in = sum(r.get("reports_in", 0) for r in results)
    total_changed = sum(r.get("verdicts_changed", 0) for r in results)
    total_absent = sum(r.get("endpoints_not_replayable", 0) for r in results)

    record = {
        "generated_by": "scripts/verify_replay.py",
        "rule": "R8 leg 2: every verdict recomputed from stored bytes, no network",
        "runs": results,
        "totals": {
            "reports": total_in,
            "verdicts_changed": total_changed,
            "endpoints_not_replayable": total_absent,
            "reports_reproduced": total_in - total_changed - total_absent,
        },
    }
    out = REPO / "docs" / "replay-verification.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    for r in results:
        print(f"{r['run_id']}: {r.get('reports_in')} reports, "
              f"{r.get('verdicts_changed')} verdict(s) changed, "
              f"{r.get('endpoints_not_replayable')} endpoint(s) not replayable")
    print(f"\nwrote {out.relative_to(REPO)}")
    # A changed verdict means the instrument scores differently than it did, which is the
    # failure R8 exists to catch. A gap is a defect in the stored run, reported but not fatal
    # to the rule's claim about scoring.
    return 1 if total_changed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
