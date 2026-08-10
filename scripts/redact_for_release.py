#!/usr/bin/env python3
"""Remove response headers that are byproducts of measurement, before the data is published.

The raw artefact store keeps whole HTTP responses from hosts we do not control, because
decision rule R8's replay leg needs the bytes a verdict was derived from. A server is free to
put anything in a response, and 1,978 of them set a cookie on our unauthenticated request:
`_cfuvid`, `AWSALB`, Laravel `XSRF-TOKEN` values and similar. None is our credential and none
is any user's -- they are anonymous session identifiers minted for a bot that never
authenticated -- but none of them is evidence either. No check in this instrument reads a
cookie; the string does not appear in `src/agentidprobe` at all. Publishing them would ship
third-party session state that serves no scientific purpose, which the ethics statement's
scope sentence does not cover.

So they are removed for release, and the removal is *proved* not asserted: run
`rescore --run-id <id> --verify` against the redacted tree and R8 must still report every
verdict identical. If a redaction changed a verdict, that redaction removed evidence and the
verify step fails, which is exactly the guarantee R8 exists to give.

    python scripts/redact_for_release.py --run-id census2 --into ../release

Only the artefact store is rewritten. Reports carry the same headers under `evidence`, so they
are rewritten too, by the same rule.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

# Header names removed from every stored response. Lower-cased comparison.
#
# Deliberately short. A blanket "strip everything we do not read" would be safer against
# surprises and worse for the artefact: a reader auditing why an endpoint was classified as
# blocked needs the headers `classify_block` looked at, and a reader checking that we did not
# quietly drop evidence needs to see what else was there.
REDACT = frozenset({"set-cookie"})

PLACEHOLDER = "[redacted for release: see scripts/redact_for_release.py]"


def _redact_headers(headers: dict) -> tuple[dict, int]:
    removed = 0
    out = {}
    for key, value in headers.items():
        if key.lower() in REDACT:
            out[key] = PLACEHOLDER
            removed += 1
        else:
            out[key] = value
    return out, removed


def _redact_obj(obj, counter: list[int]):
    """Walk any nested structure and redact header maps wherever they appear."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key == "headers" and isinstance(value, dict):
                redacted, n = _redact_headers(value)
                counter[0] += n
                out[key] = redacted
            elif key.lower() in REDACT and isinstance(value, str):
                counter[0] += 1
                out[key] = PLACEHOLDER
            else:
                out[key] = _redact_obj(value, counter)
        return out
    if isinstance(obj, list):
        return [_redact_obj(v, counter) for v in obj]
    return obj


def _rewrite(src: pathlib.Path, dst: pathlib.Path) -> int:
    counter = [0]
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("r", encoding="utf-8") as fh_in, dst.open("w", encoding="utf-8") as fh_out:
        for line in fh_in:
            line = line.strip()
            if not line:
                continue
            fh_out.write(json.dumps(_redact_obj(json.loads(line), counter)) + "\n")
    return counter[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--into", required=True,
                    help="destination root; a probe tree is created under it")
    args = ap.parse_args()

    repo = pathlib.Path(__file__).resolve().parent.parent
    dest = pathlib.Path(args.into).resolve()
    run = args.run_id

    raw = pathlib.Path("data") / "raw" / run / "artifacts.jsonl"
    reports = pathlib.Path("results") / "runs" / run / "reports.jsonl"
    sources = {repo / raw: dest / raw, repo / reports: dest / reports}
    for src in sources:
        if not src.exists():
            print(f"missing: {src}", file=sys.stderr)
            return 2

    total = 0
    for src, dst in sources.items():
        removed = _rewrite(src, dst)
        total += removed
        print(f"  {src.relative_to(repo)} -> {removed:,} header(s) redacted")

    # Everything else in the run directory is copied unchanged: the corpus is the frame, the
    # manifest and sampling ledger are the provenance, and none of them holds a response.
    for name in ("corpus.jsonl", "manifest.json", "sampling.json", "analysis.json",
                 "reconciliation.json", "probe.log"):
        src = repo / "results" / "runs" / run / name
        if src.exists():
            shutil.copy2(src, dest / "results" / "runs" / run / name)

    print(f"\n{total:,} header values redacted into {dest}")
    print(f"Now prove nothing was lost:\n"
          f"  python -m agentidprobe.cli --root {dest} rescore --run-id {run} --verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
