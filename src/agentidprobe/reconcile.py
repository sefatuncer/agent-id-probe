"""Decision rule R5: an ERROR becomes final only by recurring across two runs.

R5 decides which of a census's errors are observations and which are noise:

    An `ERROR` becomes final only when, after `max_retries` is exhausted, it produces the
    same result in **at least 2 separate runs >=24 hours apart**. Single-run ERRORs are
    reported separately in the analysis and removed from the denominator.

Until this module existed the rule had no implementation, and the function that looked most
like one was `replay.compare_reports` -- which compares a run against its own no-network
re-score. That is R8's second leg and it asks a different question: whether the *instrument*
is deterministic. Both sides of that comparison are derived from the same bytes, fetched at
the same instant, so a replay reproduces every error perfectly. Reading its output as R5
would have confirmed every error in the census, including the ones that were a host being
briefly down. R5 asks whether the *remote system* did the same thing a day later, which
nothing in this repository could answer.

**Two units, counted in separate tables.** An `EndpointReport` carries one `reachable` flag
and many `CheckResult`s, and `runner.summarise()` drops errors at both levels: the first
funnel stage removes `not reachable`, and every later stage removes that stage's check-level
`ERROR`. They are not the same set. An endpoint whose own fetch timed out is unreachable and
errors on every check; an endpoint that answered but whose authorization-server document
timed out is `reachable=True` with `ERROR` on C13 alone. Reconciling only checks would leave
the largest exclusion in the study unreconciled, and reconciling only reachability would miss
every error that happens one document deeper. So both are classified, and they are reported
in separate tables rather than one total, because an unreachable endpoint contributes one
reachability unit *and* one unit per check -- summing them would multiply the same endpoint
by six and call it an error count.

**The interval comes from `probed_at` and never from the manifest**, which is the one place
this module could have produced a false confirmation rather than a wrong count. `probe` does
not write a manifest at all -- only `collect` and `rescore` do -- so the `started_at` sitting
in a probed run's directory is the time the *corpus was collected*. In `results/runs/slice2/`
it is byte-identical to `slice`'s and still says `"run_id": "slice"`, because the corpus was
copied along with it.

`rescore` is the dangerous case. It writes a fresh manifest stamped `datetime.now(UTC)` while
reproducing every stored verdict exactly, so a replay taken a day after its source would
present as two runs 24 hours apart in which every error recurred -- R5 confirming an entire
census against a dataset containing one observation. `probed_at` is copied from the stored
artefact, so on that same pair it reads 0.0 hours and finalises nothing.

R5 keeps its 'run protocol' marker regardless: no code can make the second run happen.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import NamedTuple

from .config import PROBE_VERSION
from .models import EndpointReport, Outcome

MIN_SEPARATION_HOURS = 24.0

# `reachable` is a report field, not a check, so it needs a unit name of its own. Cannot
# collide with a check id: those are all "C" followed by digits.
REACHABILITY_UNIT = "reachable"


class Reconciliation(StrEnum):
    """What two runs jointly say about one error."""

    PERSISTENT = "persistent"              # errored in both runs: final under R5
    TRANSIENT = "transient"                # errored in one, observed in the other
    POLICY_EXCLUDED = "policy_excluded"    # at least one run's error is our own politeness
    INSTRUMENT_FAULT = "instrument_fault"  # at least one run's error is our probe crashing
    UNRECONCILED = "unreconciled"          # not scored in both runs: R5 cannot rule


class ErrorSource(StrEnum):
    OBSERVED = "observed"      # the remote system is what we failed to get through to
    OUR_POLICY = "our_policy"  # we chose not to ask
    INSTRUMENT = "instrument"  # the probe raised


# Substrings the instrument writes into `CheckResult.detail` when *we* are the reason no
# observation exists. Matched as text because only two of the three have a structured field:
# `EndpointReport` records `opted_out` and `robots_allowed`, and nothing at all records that
# a fetch was refused by the per-host request ceiling or by a redirect leaving the public web
# (`ErrorKind.OUT_OF_SCOPE`). That gap is noted in the module's defect list rather than
# papered over; `tests/test_reconcile.py` drives the real check functions and asserts every
# marker below still appears in what they emit, so rewording a detail string breaks a test
# instead of silently reclassifying our own exclusions as an operator's persistent failure.
POLICY_MARKERS: dict[str, str] = {
    "operator's request": "ErrorKind.OPTED_OUT",
    "excluded by robots.txt": "ErrorKind.ROBOTS_DISALLOWED",
    "out_of_scope": "ErrorKind.OUT_OF_SCOPE: per-host ceiling, or a redirect off the web",
}

# `runner._error_report`: the probe itself raised, so nothing about the operator was
# observed. Kept apart from POLICY_MARKERS because the remedy is different -- one is a
# promise being kept, the other is a bug in this instrument.
INSTRUMENT_MARKER = "the probe raised"


class RunSide(NamedTuple):
    """One run's stored reports, and the vantage point it was collected from.

    There is deliberately no `started_at` field. The only start time on disk is the
    manifest's, and taking it would mean measuring R5's interval from when the corpus was
    collected or -- for a replay -- from when the re-scoring was run. See the module
    docstring: that is how this rule confirms a census it never re-measured. The timestamps
    that answer R5 are on the reports themselves.
    """

    run_id: str
    reports: list[EndpointReport]
    vantage_point: str | None = None


@dataclass(frozen=True)
class _Observation:
    errored: bool
    outcome: str
    detail: str


def _as_utc(moment: datetime | None) -> datetime | None:
    # Subtracting a naive datetime from an aware one raises TypeError. Every report this
    # tool writes is aware, but a hand-built record is not, and R5 must not fall over on the
    # arithmetic when it has the two observations it needs.
    if moment is None:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _error_source(detail: str) -> ErrorSource:
    lowered = (detail or "").lower()
    if INSTRUMENT_MARKER in lowered:
        return ErrorSource.INSTRUMENT
    if any(marker in lowered for marker in POLICY_MARKERS):
        return ErrorSource.OUR_POLICY
    return ErrorSource.OBSERVED


def _observations(report: EndpointReport) -> dict[str, _Observation]:
    """Every R5 unit this report carries: reachability, then one per check."""
    if report.reachable:
        reachability = _Observation(False, "reachable", "")
    elif report.opted_out:
        reachability = _Observation(
            True, "unreachable", "not observed: excluded at the operator's request")
    elif not report.robots_allowed:
        reachability = _Observation(
            True, "unreachable", "not observed: excluded by robots.txt")
    else:
        # No field distinguishes a per-host-ceiling refusal from a host that was down, so the
        # reason is recovered from the checks written for the same fetch, which do carry it.
        # When the endpoint is unreachable every check shares one reason string, so joining
        # them cannot mix two causes together.
        joined = " ".join(c.detail for c in report.checks if c.detail)[:300]
        reachability = _Observation(True, "unreachable", joined)

    units = {REACHABILITY_UNIT: reachability}
    for check in report.checks:
        units[check.check_id.value] = _Observation(
            check.outcome is Outcome.ERROR, check.outcome.value, check.detail)
    return units


def _classify(
    earlier: _Observation | None, later: _Observation | None
) -> tuple[Reconciliation, str]:
    """Apply R5 to one unit. Order of the branches is the argument, so it is written out.

    **Our own exclusions are neither persistent nor transient**, and this is the decision in
    this module that changes what the paper is allowed to say. An opt-out, a robots.txt
    exclusion and the per-host request ceiling all produce `ERROR`, and all three reproduce
    in run 2 with near-certainty: the opt-out list is ours and frozen, robots.txt rarely
    changes overnight, and the ceiling is deterministic given the same corpus. Classified on
    outcome alone they would land in PERSISTENT -- the bucket the paper describes as errors
    *confirmed* by a second census -- and our politeness policy would be published as a
    stable property of other people's deployments.

    That inversion is not hypothetical here. The narrow-slice rehearsal on 30 July 2026
    measured 30 of 198 endpoints unreachable and 17 of those were robots.txt, so more than
    half of the kill switch's failure rate was our own policy; the per-host ceiling had
    booked roughly a fifth of the corpus as unreachable before `sample_per_host` was written;
    and defect D8 had our throttle pushing the leading headline candidate downward. Each was
    the same mistake, and R5 is where it would surface next -- as a confirmed error count.

    R5 also has nothing to reconcile in these cases. It confirms an error by *re-asking*, and
    for an opted-out operator re-asking is the promise being broken. So the third bucket is
    not a hedge, it is the accurate statement: no observation was made, in at least one of
    the two runs, by our choice. It is counted separately and never summed with the rest.

    A block (`ErrorKind.BLOCKED`) is deliberately *not* in that bucket. A WAF interstitial is
    the operator's infrastructure answering, and whether it is stable across a day is exactly
    what R5 exists to establish -- a 429 under load and a permanent ban are different
    findings. R4 already keeps both out of every denominator, so classifying them changes no
    published rate; folding them in with our own exclusions would hide a real property of the
    deployment instead.
    """
    if earlier is None or later is None:
        missing = "the later run" if later is None else "the earlier run"
        return (Reconciliation.UNRECONCILED,
                f"scored in only one run: no verdict in {missing}, so R5's two "
                f"observations do not exist")

    sources = [_error_source(o.detail) for o in (earlier, later) if o.errored]

    if ErrorSource.OUR_POLICY in sources:
        return (Reconciliation.POLICY_EXCLUDED,
                "our own politeness policy, not an observation of the operator: "
                "R5 has nothing to reconcile and this is not a confirmed error")
    if ErrorSource.INSTRUMENT in sources:
        return (Reconciliation.INSTRUMENT_FAULT,
                "the probe raised in at least one run: a defect in this instrument, "
                "not an error attributable to the endpoint")
    if earlier.errored and later.errored:
        return (Reconciliation.PERSISTENT,
                "errored in both runs")
    recovered = "later" if earlier.errored else "earlier"
    return (Reconciliation.TRANSIENT,
            f"errored in one run and was observed in the other "
            f"({recovered} run: {(later if earlier.errored else earlier).outcome})")


def _empty_counts() -> dict[str, int]:
    # Every class present in every table, so a transcript has a stable shape and two of them
    # can be diffed. A key that appears only when non-zero reads as a schema change.
    return {member.value: 0 for member in Reconciliation}


def _observation_window(side: RunSide) -> tuple[datetime | None, datetime | None]:
    """When this run actually looked: the first and last `probed_at` it recorded.

    Both are reported, because a census takes hours and "the runs are 25 hours apart" is a
    statement about two intervals, not two instants. A reader who can see the two windows can
    see whether they overlap; one given a single number cannot.
    """
    stamps = [_as_utc(r.probed_at) for r in side.reports if r.probed_at is not None]
    return (min(stamps), max(stamps)) if stamps else (None, None)


def reconcile_runs(
    run_a: RunSide, run_b: RunSide, *, min_hours: float = MIN_SEPARATION_HOURS
) -> dict:
    """Classify every ERROR in two runs as persistent, transient, or not R5's to judge.

    Returns the transcript that `agent-id-probe reconcile` writes beside the run. Argument
    order does not matter: the runs are ordered by when they observed, and which one was
    earlier is recorded rather than assumed.
    """
    window_a, window_b = _observation_window(run_a), _observation_window(run_b)
    if window_a[0] is not None and window_b[0] is not None and window_b[0] < window_a[0]:
        run_a, run_b = run_b, run_a
        window_a, window_b = window_b, window_a
    earlier, later = run_a, run_b
    start_a, start_b = window_a[0], window_b[0]

    separation_hours = None
    if start_a is not None and start_b is not None:
        separation_hours = abs((start_b - start_a).total_seconds()) / 3600.0
    separation_ok = separation_hours is not None and separation_hours >= min_hours

    def indexed(side: RunSide) -> dict[tuple[str, str], EndpointReport]:
        return {(r.endpoint.endpoint_id, r.modality.value): r for r in side.reports}

    reports_a, reports_b = indexed(earlier), indexed(later)
    urls = {k: r.endpoint.url for k, r in (reports_b | reports_a).items()}

    # Per-endpoint, not per-unit: the gap between two observations of the same endpoint is a
    # property of when it was probed, and counting it once per check would weight endpoints
    # by how many checks they happen to carry.
    gaps: list[float] = []
    for key in reports_a.keys() & reports_b.keys():
        first, second = _as_utc(reports_a[key].probed_at), _as_utc(reports_b[key].probed_at)
        if first is not None and second is not None:
            gaps.append(abs((second - first).total_seconds()) / 3600.0)

    obs_a = {(k, unit): o for k, r in reports_a.items() for unit, o in _observations(r).items()}
    obs_b = {(k, unit): o for k, r in reports_b.items() for unit, o in _observations(r).items()}

    counts = {"reachability": _empty_counts(), "checks": _empty_counts()}
    by_check: dict[str, dict[str, int]] = {}
    units: list[dict] = []
    differing_reason = 0

    for (endpoint_key, unit) in sorted(obs_a.keys() | obs_b.keys()):
        before, after = obs_a.get((endpoint_key, unit)), obs_b.get((endpoint_key, unit))
        # R5 governs errors and nothing else. A unit that errored in neither run is not an
        # unreconciled error, it is a measurement, and putting it in this ledger would bury
        # the errors under the whole census.
        if not ((before is not None and before.errored) or (after is not None and after.errored)):
            continue

        classification, reason = _classify(before, after)
        table = "reachability" if unit == REACHABILITY_UNIT else "checks"
        counts[table][classification.value] += 1
        if table == "checks":
            by_check.setdefault(unit, _empty_counts())[classification.value] += 1
        if (classification is Reconciliation.PERSISTENT
                and before is not None and after is not None
                and before.detail != after.detail):
            differing_reason += 1

        units.append({
            "endpoint_id": endpoint_key[0],
            "url": urls.get(endpoint_key, ""),
            "modality": endpoint_key[1],
            "unit": unit,
            "classification": classification.value,
            "reason": reason,
            "earlier": None if before is None else {
                "outcome": before.outcome, "detail": before.detail},
            "later": None if after is None else {
                "outcome": after.outcome, "detail": after.detail},
        })

    notes: list[str] = []
    if separation_hours is None:
        notes.append(
            "The interval between these runs could not be determined, so R5's precondition "
            "is unverified and no ERROR here is final.")
    elif not separation_ok:
        notes.append(
            f"The runs are {separation_hours:.1f} h apart, below the {min_hours:g} h R5 "
            f"requires. No ERROR in this dataset is final; the classifications below "
            f"describe what the two runs saw, not what R5 confirms.")
    if gaps and separation_ok and min(gaps) < min_hours:
        notes.append(
            f"The runs are {separation_hours:.1f} h apart but the closest pair of "
            f"observations is {min(gaps):.1f} h apart: a census takes hours, so endpoints "
            f"probed late in the earlier run and early in the later one are re-asked sooner "
            f"than the run-level separation suggests.")
    unreconciled = counts["reachability"][Reconciliation.UNRECONCILED.value] + \
        counts["checks"][Reconciliation.UNRECONCILED.value]
    if unreconciled:
        notes.append(
            f"{unreconciled} unit(s) were scored in only one of the two runs -- an endpoint "
            f"the corpus or the per-host sample no longer contains, or one the kill switch "
            f"never reached. R5 cannot rule on them and they are not counted as either "
            f"confirmed or transient.")
    policy_excluded = counts["reachability"][Reconciliation.POLICY_EXCLUDED.value] + \
        counts["checks"][Reconciliation.POLICY_EXCLUDED.value]
    if policy_excluded:
        notes.append(
            f"{policy_excluded} unit(s) are our own exclusions (opt-out, robots.txt, the "
            f"per-host request ceiling). They are reported here and must not be added to the "
            f"persistent count: they are not observations of any operator.")
    if differing_reason:
        notes.append(
            f"{differing_reason} persistent unit(s) errored in both runs for different "
            f"recorded reasons. The denominator effect is identical -- the endpoint was not "
            f"observed either time -- but the cause was not the same one twice.")
    if (earlier.vantage_point and later.vantage_point
            and earlier.vantage_point != later.vantage_point):
        notes.append(
            f"The runs originate from different vantage points "
            f"({earlier.vantage_point} -> {later.vantage_point}). An error that changes "
            f"between them is a property of the path as much as of the origin.")

    return {
        "rule": "R5",
        "probe_version": PROBE_VERSION,
        "runs": {
            "earlier": {"run_id": earlier.run_id, "reports": len(earlier.reports),
                        "first_observation": start_a.isoformat() if start_a else None,
                        "last_observation": window_a[1].isoformat() if window_a[1] else None,
                        "vantage_point": earlier.vantage_point},
            "later": {"run_id": later.run_id, "reports": len(later.reports),
                      "first_observation": start_b.isoformat() if start_b else None,
                      "last_observation": window_b[1].isoformat() if window_b[1] else None,
                      "vantage_point": later.vantage_point},
        },
        "separation": {
            "hours": separation_hours,
            "required_hours": min_hours,
            "satisfied": separation_ok,
            "measured_from": "probed_at on the reports, never the manifest: `probe` writes "
                             "no manifest and `rescore` writes a fresh one over copied "
                             "verdicts",
            "per_endpoint_hours": {
                "n": len(gaps),
                "min": min(gaps) if gaps else None,
                "median": statistics.median(gaps) if gaps else None,
                "max": max(gaps) if gaps else None,
            },
        },
        # False whenever the 24-hour precondition is unmet, so that a reader who takes only
        # this line away cannot come away with a finalised error count R5 does not support.
        "final_errors_established": separation_ok,
        "counts": {"reachability": counts["reachability"], "checks": counts["checks"],
                   "by_check": dict(sorted(by_check.items()))},
        "notes": notes,
        "units": units,
    }
