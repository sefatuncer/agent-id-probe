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
decide which. That is the audit the paper promises. It was first taken over a seeded random
sample, since no one reads some fifteen hundred verdicts by hand, and since 3 October 2026 it
runs over every failure (`--all`), which a machine does in seconds; the sample remains for
comparison with the earlier record.

The independence is partial, and the limit is stated rather than implied. This is a second
implementation by the instrument's own author, and both implementations read the same stored
document, so a defect in *fetching* -- the wrong URL requested, a redirect followed that
should not have been -- is invisible to both. What this catches is a misapplied rule, which is
what a false positive in this study means.

Revision history, because a referee found it in the docstrings rather than in the paper and
an auditor revised toward its instrument is a weaker auditor than the paper said (H2-M3):

* version 1 (August 2026) implemented only the first paragraph of RFC 9728 3.3 for C12 and
  reported 15 false positives, all on the WWW-Authenticate hint path. The second paragraph
  was added after the clause was re-read, which also made the auditor agree with the
  instrument on those 15. C13 at first audited only a returned mismatch and was extended to
  an issuer serving no metadata.
* version 2 (3 October 2026) repairs two defects the referee found by running it. The C05 arm
  skipped every artefact whose label did not contain "protected-resource" or "prm"; census
  artefacts are labelled only "mcp" and "card", so it read nothing and returned "agree" for
  all 525 C05 failures. It now selects candidates by URL and decides both failure branches.
  And C12 and C13 compared the declared value raw while the instrument canonicalises both
  sides, so the auditor was stricter than the rule it audits and could not see a false
  positive that rule's strictness produced. Both sides are now canonicalised as RFC 3986 and
  the instrument's frozen policy (R9.2) permit. No reading was changed to match the
  instrument: version 1's three C13 disagreements are reported, not removed. The rule
  amended the same day, that a ceiling refusal is answered from a document the run already
  held, is implemented here from its text, so that the audit reads the evidence the rule
  admits.

    python scripts/audit_failures.py --run-id census2 --all

Writes `docs/failure-audit-<run-id>.json`. Deterministic: same run, same seed, same sample.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import base64  # noqa: E402

from agentidprobe.models import Outcome  # noqa: E402
from agentidprobe.store import RunStore  # noqa: E402

AUDITOR_VERSION = 2

# Our own access policy withheld these, so they are not observations of the host (R4).
_NOT_OBSERVED = {"robots_disallowed", "opted_out"}
_CEILING = "host has already received"

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


def _prm_candidates(resource: str, evidence: dict) -> list[str]:
    """The locations a client consults, in order, written from the clauses.

    RFC 9728 3.1 inserts the well-known suffix between host and path after removing a
    terminating slash, and MCP 2025-11-25 has a client fall back to the root form. A
    WWW-Authenticate hint, when the probe followed it, comes first.
    """
    prefix = "/.well-known/oauth-protected-resource"
    parts = urlsplit(resource)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.rstrip("/")
    candidates = [f"{origin}{prefix}{path}"] if path else []
    candidates.append(f"{origin}{prefix}")
    hint = evidence.get("hinted_url_declared")
    if hint and not evidence.get("hint_rejected_reason"):
        candidates.insert(0, hint)
    return list(dict.fromkeys(candidates))


def _json_object(record: dict) -> dict | None:
    try:
        value = json.loads(base64.b64decode(record.get("body_b64") or "").decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _withheld(record: dict) -> bool:
    kind = record.get("error_kind", "none")
    return kind in _NOT_OBSERVED or (
        kind == "out_of_scope" and (record.get("error_detail") or "").startswith(_CEILING)
        and not record.get("reused"))


def _challenged(report, evidence: dict) -> bool:
    """RFC 6750 3: a 401, or a 403 carrying WWW-Authenticate, is a challenge."""
    return report.http_status == 401 or (
        report.http_status == 403 and bool(evidence.get("www_authenticate")))


_FIRST_SUCCESS: dict[str, dict] = {}


def _index_first_success(artefacts: dict) -> None:
    """The run's earliest successful response to each well-known URL, for the rule dated
    2026-10-03 that a ceiling refusal is answered from a document the run already held.
    Written here from the rule's text, not imported from the instrument."""
    _FIRST_SUCCESS.clear()
    for records in artefacts.values():
        for record in records:
            url = record.get("url", "")
            if (record.get("status") == 200 and record.get("error_kind", "none") == "none"
                    and "/.well-known/" in urlsplit(url).path):
                held = _FIRST_SUCCESS.get(url)
                if held is None or record["fetched_at"] < held["fetched_at"]:
                    _FIRST_SUCCESS[url] = record


def _answered(record: dict) -> dict:
    """A ceiling refusal answered by the run's earlier copy of the same document, if any."""
    if (record.get("error_kind") == "out_of_scope"
            and (record.get("error_detail") or "").startswith(_CEILING)):
        first = _FIRST_SUCCESS.get(record.get("url", ""))
        if first is not None and first["fetched_at"] < record["fetched_at"]:
            return first
    return record


def _check_c05(report, evidence: dict, artefacts: dict) -> tuple[bool | None, str]:
    """MCP: a server that challenges MUST publish RFC 9728 metadata, naming at least one
    authorization server.

    Decided from the raw artefacts, located by URL. Version 1 located them by a label the
    census never wrote and so decided nothing.
    """
    records: dict[str, dict] = {}
    for artefact in artefacts.get(report.endpoint.endpoint_id, []):
        records.setdefault(artefact.get("url", ""), artefact)
    malformed = False
    withheld: list[str] = []
    for url in _prm_candidates(report.endpoint.url, evidence):
        record = records.get(url)
        if record is None:
            continue
        record = _answered(record)
        if _withheld(record):
            withheld.append(url)
            continue
        if record.get("status") != 200:
            continue
        document = _json_object(record)
        if document is None:
            malformed = True
            continue
        if withheld:
            return None, f"a document answered at {url}, but {withheld[0]} before it was withheld"
        servers = document.get("authorization_servers")
        named = isinstance(servers, list) and any(
            isinstance(server, str) and urlsplit(server).scheme in ("https", "http")
            and urlsplit(server).netloc for server in servers)
        return (not named), (
            f"{url} serves a document whose authorization_servers "
            + ("names an authorization server" if named else "is absent, empty or malformed"))
    if withheld:
        return None, f"candidate(s) withheld by the access policy: {'; '.join(withheld)}"
    if malformed:
        return True, "a candidate answered 200, but no candidate served a JSON object (R3)"
    if not _challenged(report, evidence):
        return None, "the endpoint did not challenge, so C05 should not have applied"
    return True, "no candidate location answered 200"


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
    # Version 2: both sides canonicalised. Comparing the declared value raw made the auditor
    # stricter than the rule it audits (R9.2), so it could never report a false positive that
    # the rule's strictness produced.
    return _canonical(declared) not in {_canonical(p) for p in permitted}, (
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
        # Version 2: canonicalised on both sides, for the reason given in `_check_c12`.
        if not isinstance(returned, str) or _canonical(returned) != _canonical(identifier):
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
    _index_first_success(artefacts)

    population = [
        (report, check) for report in reports for check in report.checks
        if check.outcome in FAILING and check.check_id.value in CHECKS
    ]
    rng = random.Random(SEED)
    sample = (population if sample_size >= len(population)
              else rng.sample(population, sample_size))

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
        "auditor_version": AUDITOR_VERSION,
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
        "undecidable_cases": undecidable,
    }


_URL = re.compile(r"""https?://[^\s'",;)]+""")
# A bare host name, which a reason can carry without a scheme.
_HOST = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", re.IGNORECASE)


def redact(result: dict) -> dict:
    """The audit record without any endpoint or issuer URL, for publication."""
    def clean(entry: dict) -> dict:
        return {"check": entry["check"], "instrument": entry["instrument"],
                "reason": _HOST.sub("<host>", _URL.sub("<url>", entry.get("reason", "")))}
    return {**result, "redacted": True,
            "findings": [clean(e) for e in result["findings"]],
            "undecidable_cases": [clean(e) for e in result["undecidable_cases"]]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sample", type=int, default=100)
    parser.add_argument("--all", action="store_true",
                        help="audit every failing verdict instead of a seeded sample")
    args = parser.parse_args()

    result = audit(args.run_id, 10**9 if args.all else args.sample)
    suffix = "-all" if args.all else ""
    # The full record names the endpoints behind each disagreement, so it stays beside the run
    # it audits, which is not published. The repository carries the same record with every URL
    # removed: the ethics record limits publication to aggregates, and a finding names a
    # deployment the paper does not.
    local = RunStore(ROOT, args.run_id).run_dir / f"failure-audit{suffix}.json"
    local.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    out = ROOT / "docs" / f"failure-audit-{args.run_id}{suffix}.json"
    out.write_text(json.dumps(redact(result), indent=2) + "\n", encoding="utf-8")

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
