#!/usr/bin/env python3
"""Re-derive a sample of MUST-level failures from the stored bytes, independently.

Section 5.8 of the paper reports how many of this instrument's failing verdicts are false
positives. Answering that needs a check the instrument cannot pass by construction, and
`rescore --verify` is not it: replay runs the same code over the same bytes, so agreement is
guaranteed and proves determinism rather than correctness. It is decision rule R8's leg 2 and
it answers a different question.

So the rules are re-implemented here, from the specification sentences rather than from
`checks_oauth.py`, and run against the stored evidence. Where the two implementations
disagree, one of them is wrong, and the disagreement is printed with everything needed to
decide which. That is the audit the paper promises; the census produced 1,521 failures and no
one is reading 1,521 verdicts, so it is taken over a seeded random sample and the sampling is
part of the reported method rather than a footnote to it.

The independence is real but partial, and the limit is stated rather than implied: both
implementations read the same stored document, so a defect in *fetching* -- the wrong URL
requested, a redirect followed that should not have been -- is invisible to both. What this
catches is a misapplied rule, which is what a false positive in this study means.

    python scripts/audit_failures.py --run-id census1 --sample 100

Writes `docs/failure-audit-<run-id>.json`. Deterministic: same run, same seed, same sample.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentidprobe.models import Outcome  # noqa: E402
from agentidprobe.store import RunStore  # noqa: E402

# Fixed so the sample is a property of the run and not of the day it was audited. Written into
# the output, so a reader can reproduce the same hundred verdicts.
SEED = 20260806

FAILING = {Outcome.FAIL_UNIMPLEMENTED, Outcome.FAIL_MISIMPLEMENTED}


def _strip_default_port(url: str) -> str:
    """RFC 3986 6.2.3: an explicit default port is equivalent to none."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port and not ((parts.scheme == "https" and parts.port == 443)
                           or (parts.scheme == "http" and parts.port == 80)):
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), host, parts.path, parts.query, parts.fragment))


def _identifier_from_metadata_url(url: str) -> set[str]:
    """The resource identifiers RFC 9728 3.1 permits a metadata URL to have been built from.

    3.1 inserts `/.well-known/oauth-protected-resource` between the host and the path, so the
    inverse is to remove it. The mapping is lossy in exactly one way -- an identifier with a
    trailing slash and one without produce the same metadata URL -- so this returns the set,
    and a declared value matching any member is conformant. Written from the clause; the
    instrument's own version lives in `config.identifier_from_metadata_url`.
    """
    prefix = "/.well-known/oauth-protected-resource"
    parts = urlsplit(_strip_default_port(url))
    if not parts.path.startswith(prefix):
        return set()
    remainder = parts.path[len(prefix):]
    base = urlunsplit((parts.scheme, parts.netloc, remainder, "", ""))
    return {base, base + "/"} if not base.endswith("/") else {base, base.rstrip("/")}


def _check_c05(report, evidence: dict, artefacts: dict) -> tuple[bool, str]:
    """C05 fails when an authorizing endpoint serves no protected-resource metadata.

    Warranted only if no candidate location answered with a usable document. Re-derived from
    the raw artefacts rather than from the verdict, which is the point.
    """
    for artefact in artefacts.get(report.endpoint.endpoint_id, []):
        label = (artefact.get("label") or "").lower()
        if "protected-resource" not in label and "prm" not in label:
            continue
        if artefact.get("status") == 200:
            return False, f"a candidate location answered 200: {artefact.get('url')}"
    return True, "no candidate protected-resource location answered 200"


def _check_c12(report, evidence: dict, artefacts: dict) -> tuple[bool, str]:
    """RFC 9728 3.3, both of its rules.

    The clause has two halves and the auditor's first version implemented one. Where the
    client constructed the well-known URL itself, the expected identifier is recovered by
    removing the suffix again. Where the document was reached through the `WWW-Authenticate`
    hint, the client did not construct anything, so 3.3's second paragraph compares against
    the URL it actually requested -- the endpoint.

    Auditing only the first rule reported 15 false positives against the instrument, every
    one of them an endpoint whose metadata came from the hint. The instrument was right and
    the audit was incomplete, which is the failure mode an independent implementation is
    most prone to: it is written from the same reading twice unless the second reading is
    made to cover the whole clause.
    """
    declared = evidence.get("declared_resource")
    prm_url = evidence.get("prm_url")
    # RFC 9728 3.2 makes `resource` REQUIRED, so a document without it fails 3.3 by having
    # nothing to compare. Decidable, and it was being filed as undecidable.
    if declared is None and prm_url:
        return True, "the retrieved metadata omits the REQUIRED `resource` member (3.2)"
    if declared is None or not prm_url:
        return None, "no declared resource or metadata URL stored"

    if evidence.get("prm_from_hint"):
        expected = _canonical(report.endpoint.url)
        return _canonical(declared) != expected, (
            f"reached through the WWW-Authenticate hint, so 3.3 paragraph 2 applies: "
            f"declared {declared!r} against requested {report.endpoint.url!r}"
        )

    permitted = _identifier_from_metadata_url(prm_url)
    if not permitted:
        return None, f"metadata URL not in the 3.1 form: {prm_url}"
    return declared not in permitted, (
        f"declared {declared!r}; 3.1 inverse of {prm_url!r} permits {sorted(permitted)!r}"
    )


def _canonical(url: str) -> str:
    """RFC 3986 6.2.2.1 and 6.2.3: scheme and host are case-insensitive, an empty path is
    equivalent to `/`, and a default port is equivalent to none."""
    parts = urlsplit(_strip_default_port(url))
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), (parts.netloc or "").lower(), path,
                       parts.query, parts.fragment))


def _check_c13(report, evidence: dict, artefacts: dict) -> tuple[bool, str]:
    """RFC 8414 3.3: the `issuer` value MUST be identical to the issuer requested."""
    # Two ways C13 fails, and auditing one of them left seven of twelve C13 cases
    # undecidable. The declared issuer may return metadata whose `issuer` is not the
    # requested one, and it may return no metadata at all -- a resource naming an issuer
    # that serves nothing. The second is the more common failure in this corpus and the
    # audit has to reach it, or the reported false-positive rate is computed over the half
    # of the population that happened to be easy.
    documents = evidence.get("as_documents") or {}
    errors = evidence.get("as_errors") or {}
    declared = evidence.get("authorization_servers") or []
    if declared and not documents:
        unreachable = [issuer for issuer in declared if issuer in errors]
        if len(unreachable) == len(declared):
            return True, (
                f"all {len(declared)} declared issuer(s) served no metadata: "
                + "; ".join(f"{k}: {v}" for k, v in list(errors.items())[:3])
            )
        return None, f"{len(unreachable)} of {len(declared)} declared issuers recorded errors"

    disagreements = []
    for requested, document in documents.items():
        if not isinstance(document, dict):
            continue
        returned = document.get("issuer")
        if returned is None:
            continue
        # The requested issuer is the identifier, not the metadata URL it was fetched from.
        identifier = requested
        for suffix in ("/.well-known/oauth-authorization-server",
                       "/.well-known/openid-configuration"):
            if identifier.endswith(suffix):
                identifier = identifier[: -len(suffix)]
        if returned != identifier:
            disagreements.append(f"requested {identifier!r}, returned {returned!r}")
    if not documents:
        return None, "no authorization-server document stored"
    return bool(disagreements), "; ".join(disagreements) or "every returned issuer identical"


CHECKS = {"C05": _check_c05, "C12": _check_c12, "C13": _check_c13}


def audit(run_id: str, sample_size: int, root: Path | None = None) -> dict:
    store = RunStore(root or ROOT, run_id)
    reports = store.read_reports()

    artefacts: dict[str, list[dict]] = {}
    raw = (root or ROOT) / "data" / "raw" / run_id / "artifacts.jsonl"
    if raw.exists():
        for line in raw.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            artefacts.setdefault(record.get("endpoint_id", ""), []).append(record)

    population = [
        (report, check) for report in reports for check in report.checks
        if check.outcome in FAILING and check.check_id.value in CHECKS
    ]
    rng = random.Random(SEED)
    sample = rng.sample(population, min(sample_size, len(population)))

    findings, undecidable = [], []
    by_check: dict[str, dict[str, int]] = {}
    for report, check in sample:
        name = check.check_id.value
        tally = by_check.setdefault(name, {"audited": 0, "agreed": 0, "disagreed": 0,
                                           "undecidable": 0})
        tally["audited"] += 1
        verdict, reason = CHECKS[name](report, report.evidence or {}, artefacts)
        entry = {
            "check": name, "endpoint": report.endpoint.url,
            "instrument": check.outcome.value, "reason": reason,
            "instrument_observed": str(check.observed_value or check.detail or ""),
        }
        if verdict is None:
            tally["undecidable"] += 1
            undecidable.append(entry)
        elif verdict:
            tally["agreed"] += 1
        else:
            tally["disagreed"] += 1
            findings.append(entry)

    return {
        "schema": "agent-id-probe/failure-audit/1",
        "run_id": run_id,
        "seed": SEED,
        "method": (
            "Each rule re-implemented from its specification sentence, independent of "
            "checks_oauth.py, and applied to the stored evidence and raw artefacts. Both "
            "implementations read the same stored document, so a fetching defect is invisible "
            "to both; what this detects is a misapplied rule."
        ),
        "population": len(population),
        "sampled": len(sample),
        "by_check": by_check,
        "false_positives": len(findings),
        "undecidable": len(undecidable),
        "findings": findings,
        "undecidable_cases": undecidable[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sample", type=int, default=100)
    args = parser.parse_args()

    result = audit(args.run_id, args.sample)
    out = ROOT / "docs" / f"failure-audit-{args.run_id}.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"population {result['population']:,} failing MUST-level verdicts")
    print(f"sampled    {result['sampled']} (seed {result['seed']})")
    for name, tally in sorted(result["by_check"].items()):
        print(f"  {name}: {tally['audited']:>3} audited, {tally['agreed']:>3} agreed, "
              f"{tally['disagreed']:>3} disagreed, {tally['undecidable']:>3} undecidable")
    print(f"false positives {result['false_positives']}, undecidable {result['undecidable']}")
    for finding in result["findings"][:10]:
        print(f"  ! {finding['check']} {finding['endpoint'][:60]}: {finding['reason'][:110]}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
