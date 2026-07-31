"""Decision rule R5, tested rather than asserted.

R5 spent the project as prose: it is quoted in `decision-rules.md`, cited in three source
comments and two other tests, and nothing executed it. The failure mode that makes it worth
testing rather than trusting is not that the classification is hard -- it is that the obvious
implementation gets the *unit* wrong and the *denominator* wrong in the same way this
repository has already been caught four times, by counting our own politeness policy as
something an operator did.
"""

from datetime import UTC, datetime, timedelta

import pytest
import respx

from agentidprobe.checks_oauth import probe_oauth
from agentidprobe.cli import main
from agentidprobe.collectors import apex_domain, endpoint_id
from agentidprobe.config import MeasurementConfig, RatePolicy
from agentidprobe.fetcher import ErrorKind, Fetcher, FetchResult
from agentidprobe.models import (
    CheckId,
    CheckResult,
    Endpoint,
    EndpointKind,
    EndpointReport,
    Modality,
    NormativeStrength,
    Outcome,
    RunContext,
)
from agentidprobe.reconcile import (
    INSTRUMENT_MARKER,
    MIN_SEPARATION_HOURS,
    POLICY_MARKERS,
    REACHABILITY_UNIT,
    Reconciliation,
    RunSide,
    reconcile_runs,
)
from agentidprobe.store import RunStore

DAY_ONE = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
DAY_TWO = DAY_ONE + timedelta(hours=25)

FAST = MeasurementConfig(
    rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0)
)


def _endpoint(url: str) -> Endpoint:
    return Endpoint(endpoint_id=endpoint_id(url), url=url, kind=EndpointKind.MCP_REMOTE,
                    source="t", apex_domain=apex_domain(url))


def _report(url: str, *, at: datetime, run_id: str, reachable: bool = True,
            checks: dict[CheckId, tuple[Outcome, str]] | None = None,
            opted_out: bool = False, robots_allowed: bool = True) -> EndpointReport:
    return EndpointReport(
        endpoint=_endpoint(url),
        modality=Modality.OAUTH_METADATA,
        reachable=reachable,
        opted_out=opted_out,
        robots_allowed=robots_allowed,
        checks=[
            CheckResult(check_id=cid, outcome=outcome,
                        normative_strength=NormativeStrength.MUST, detail=detail)
            for cid, (outcome, detail) in (checks or {}).items()
        ],
        probed_at=at,
        run_id=run_id,
    )


def _unit(result: dict, url: str, unit: str) -> dict:
    eid = endpoint_id(url)
    for entry in result["units"]:
        if entry["endpoint_id"] == eid and entry["unit"] == unit:
            return entry
    raise AssertionError(f"no {unit} unit for {url} in the transcript")


def _sides(run_one: list[EndpointReport], run_two: list[EndpointReport]) -> tuple:
    return RunSide("r1", run_one), RunSide("r2", run_two)


# --- what R5 actually classifies ----------------------------------------------


def test_an_error_in_both_runs_is_persistent_and_one_in_a_single_run_is_not():
    """The rule itself: final only by recurrence, and the rest reported separately."""
    dead = "https://dead-example.org/mcp"
    flaky = "https://flaky-example.org/mcp"

    run_one = [
        _report(dead, at=DAY_ONE, run_id="r1", reachable=False,
                checks={CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")}),
        _report(flaky, at=DAY_ONE, run_id="r1", reachable=False,
                checks={CheckId.PRM_PRESENT: (Outcome.ERROR,
                                              "not observed: timeout (R4/R5)")}),
    ]
    run_two = [
        _report(dead, at=DAY_TWO, run_id="r2", reachable=False,
                checks={CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")}),
        _report(flaky, at=DAY_TWO, run_id="r2", reachable=True,
                checks={CheckId.PRM_PRESENT: (Outcome.PASS, "")}),
    ]

    result = reconcile_runs(*_sides(run_one, run_two))

    assert _unit(result, dead, "C05")["classification"] == Reconciliation.PERSISTENT
    assert _unit(result, dead, REACHABILITY_UNIT)["classification"] == Reconciliation.PERSISTENT
    assert _unit(result, flaky, "C05")["classification"] == Reconciliation.TRANSIENT
    assert _unit(result, flaky, REACHABILITY_UNIT)["classification"] == Reconciliation.TRANSIENT
    assert result["final_errors_established"] is True
    assert result["counts"]["checks"][Reconciliation.PERSISTENT] == 1
    assert result["counts"]["checks"][Reconciliation.TRANSIENT] == 1


def test_endpoints_that_never_errored_are_not_in_the_ledger():
    """R5 governs errors. A ledger that also lists every clean endpoint buries the
    errors it exists to settle, and would make `units` the size of the census."""
    clean = "https://fine-example.org/mcp"
    run_one = [_report(clean, at=DAY_ONE, run_id="r1",
                       checks={CheckId.PRM_PRESENT: (Outcome.PASS, "")})]
    run_two = [_report(clean, at=DAY_TWO, run_id="r2",
                       checks={CheckId.PRM_PRESENT: (Outcome.FAIL_UNIMPLEMENTED, "")})]

    result = reconcile_runs(*_sides(run_one, run_two))

    assert result["units"] == []
    assert sum(result["counts"]["checks"].values()) == 0


# --- the unit of comparison ---------------------------------------------------


def test_reachability_and_per_check_errors_are_reconciled_as_separate_units():
    """An `EndpointReport` has one `reachable` flag and many `CheckResult`s, and
    `summarise()` drops errors at both levels -- the first funnel stage on reachability,
    every later stage on that stage's check outcome.

    This endpoint answered both times, so it is reachable in both, but the
    authorization-server document behind it timed out in both. Reconciling reachability
    alone would report nothing wrong; the error that leaves C13's denominator lives one
    document deeper and is invisible at the endpoint level.
    """
    url = "https://answers-example.org/mcp"
    checks = {
        CheckId.PRM_PRESENT: (Outcome.PASS, ""),
        CheckId.AS_CORRESPONDENCE: (Outcome.ERROR, "not observed: timeout (R4/R5)"),
    }
    result = reconcile_runs(*_sides(
        [_report(url, at=DAY_ONE, run_id="r1", checks=checks)],
        [_report(url, at=DAY_TWO, run_id="r2", checks=checks)],
    ))

    assert _unit(result, url, "C13")["classification"] == Reconciliation.PERSISTENT
    with pytest.raises(AssertionError):
        _unit(result, url, REACHABILITY_UNIT)
    assert result["counts"]["reachability"][Reconciliation.PERSISTENT] == 0
    assert result["counts"]["by_check"]["C13"][Reconciliation.PERSISTENT] == 1


def test_the_two_unit_tables_are_kept_apart_so_they_cannot_be_summed():
    """An unreachable endpoint contributes one reachability unit and one unit per check.
    A single total would count the same endpoint six times and call it an error count."""
    url = "https://gone-example.org/mcp"
    checks = {cid: (Outcome.ERROR, "not observed: dns (R4/R5)")
              for cid in (CheckId.PRM_PRESENT, CheckId.PRM_RESOURCE_IDENTITY_MATCH,
                          CheckId.AS_CORRESPONDENCE)}
    result = reconcile_runs(*_sides(
        [_report(url, at=DAY_ONE, run_id="r1", reachable=False, checks=checks)],
        [_report(url, at=DAY_TWO, run_id="r2", reachable=False, checks=checks)],
    ))

    assert result["counts"]["reachability"][Reconciliation.PERSISTENT] == 1
    assert result["counts"]["checks"][Reconciliation.PERSISTENT] == 3
    assert "reachability" in result["counts"] and "checks" in result["counts"]
    assert "total" not in result["counts"], (
        "a combined total would multiply one unreachable endpoint by its check count"
    )


# --- our own policy is not an operator's persistent failure -------------------


@pytest.mark.parametrize(
    ("kwargs", "detail"),
    [
        ({"opted_out": True}, "not observed: excluded at the operator's request (ETHICS.md 7)"),
        ({"robots_allowed": False}, "not observed: excluded by robots.txt (R4, ETHICS.md 6)"),
        ({}, "not observed: out_of_scope (R4/R5)"),
    ],
    ids=["opt-out", "robots", "per-host ceiling"],
)
def test_our_own_exclusions_are_never_counted_as_confirmed_errors(kwargs, detail):
    """The classification that decides what the paper may say.

    All three reproduce in run 2 with near-certainty -- the opt-out list is ours and frozen,
    robots.txt rarely changes overnight, the request ceiling is deterministic -- so on
    outcome alone all three land in PERSISTENT, the bucket described as errors *confirmed by
    a second census*. The rehearsal on 30 July 2026 measured 17 of 30 unreachable endpoints
    as robots.txt exclusions, so this is more than half of that number, published as a
    stable property of other people's deployments.
    """
    url = "https://quiet-example.org/mcp"
    run_one = [_report(url, at=DAY_ONE, run_id="r1", reachable=False,
                       checks={CheckId.PRM_PRESENT: (Outcome.ERROR, detail)}, **kwargs)]
    run_two = [_report(url, at=DAY_TWO, run_id="r2", reachable=False,
                       checks={CheckId.PRM_PRESENT: (Outcome.ERROR, detail)}, **kwargs)]

    result = reconcile_runs(*_sides(run_one, run_two))

    for unit in (REACHABILITY_UNIT, "C05"):
        entry = _unit(result, url, unit)
        assert entry["classification"] == Reconciliation.POLICY_EXCLUDED, (
            f"{unit} recorded our own exclusion as {entry['classification']}"
        )
    assert result["counts"]["checks"][Reconciliation.PERSISTENT] == 0
    assert result["counts"]["reachability"][Reconciliation.PERSISTENT] == 0
    assert any("must not be added to the persistent count" in note
               for note in result["notes"])


def test_withholding_the_second_look_does_not_confirm_the_first_error():
    """A real transport failure in run 1 and our own exclusion in run 2.

    R5 confirms an error by re-asking. If the second run declined to ask, there is one
    observation, not two, and the run-1 error stays unconfirmed. Calling this PERSISTENT
    would let a robots.txt that appeared overnight finalise an error nobody re-measured.
    """
    url = "https://went-quiet-example.org/mcp"
    result = reconcile_runs(*_sides(
        [_report(url, at=DAY_ONE, run_id="r1", reachable=False,
                 checks={CheckId.PRM_PRESENT: (Outcome.ERROR,
                                               "not observed: timeout (R4/R5)")})],
        [_report(url, at=DAY_TWO, run_id="r2", reachable=False, robots_allowed=False,
                 checks={CheckId.PRM_PRESENT: (
                     Outcome.ERROR, "not observed: excluded by robots.txt (R4, ETHICS.md 6)")})],
    ))

    assert _unit(result, url, "C05")["classification"] == Reconciliation.POLICY_EXCLUDED
    assert result["counts"]["checks"][Reconciliation.PERSISTENT] == 0


def test_a_block_is_reconciled_rather_than_written_off_as_our_own_policy():
    """R4 keeps blocks out of every denominator, but a WAF is the operator's infrastructure
    answering, and whether it is stable across a day is exactly what R5 establishes: a 429
    under load and a permanent ban are different findings. Folding blocks in with our own
    exclusions would hide a real property of the deployment."""
    url = "https://waf-example.org/mcp"
    blocked = {CheckId.PRM_PRESENT: (Outcome.ERROR, "access block (R4)")}
    result = reconcile_runs(*_sides(
        [_report(url, at=DAY_ONE, run_id="r1", reachable=False, checks=blocked)],
        [_report(url, at=DAY_TWO, run_id="r2", reachable=False, checks=blocked)],
    ))

    assert _unit(result, url, "C05")["classification"] == Reconciliation.PERSISTENT


def test_a_crash_in_our_own_probe_is_not_an_error_attributable_to_the_endpoint():
    """`runner._error_report` writes ERROR on every check when the probe raises. Two runs
    of a deterministic bug reproduce it perfectly, which under a plain outcome comparison
    is indistinguishable from a host that is genuinely and persistently unreachable."""
    url = "https://crash-example.org/mcp"
    raised = {CheckId.PRM_PRESENT: (
        Outcome.ERROR, "not observed: the probe raised KeyError: 'issuer'")}
    result = reconcile_runs(*_sides(
        [_report(url, at=DAY_ONE, run_id="r1", reachable=False, checks=raised)],
        [_report(url, at=DAY_TWO, run_id="r2", reachable=False, checks=raised)],
    ))

    assert _unit(result, url, "C05")["classification"] == Reconciliation.INSTRUMENT_FAULT
    assert result["counts"]["checks"][Reconciliation.PERSISTENT] == 0


@respx.mock
async def test_the_policy_markers_are_the_strings_the_instrument_actually_writes():
    """The coupling this module rests on, locked so a reworded detail breaks a test.

    Two of the three exclusions have a structured field on `EndpointReport`; the per-host
    ceiling and the out-of-scope redirect have none, so they are recognised by the text the
    checks write. Text matching is silent when it stops matching -- and what it fails into
    is classifying our own exclusion as an operator's confirmed error, which is the one
    outcome this module exists to prevent.
    """
    config = MeasurementConfig(
        rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0),
        opted_out=frozenset({"quiet-example.org"}),
    )
    emitted: list[str] = []
    async with Fetcher(config) as f:
        initial = await f.fetch("https://quiet-example.org/mcp")
        checks, _ = await probe_oauth(f, "https://quiet-example.org/mcp", initial)
        emitted += [c.detail for c in checks]

        for kind in (ErrorKind.ROBOTS_DISALLOWED, ErrorKind.OUT_OF_SCOPE):
            fetched = FetchResult(url="https://x-example.org/mcp", ok=False,
                                  status=None, error_kind=kind)
            checks, _ = await probe_oauth(f, "https://x-example.org/mcp", fetched)
            emitted += [c.detail for c in checks]

    haystack = " ".join(emitted).lower()
    for marker, source in POLICY_MARKERS.items():
        assert marker in haystack, (
            f"reconcile.POLICY_MARKERS expects {marker!r} from {source}, and no check "
            f"emits it any more: our own exclusions would now be classified as the "
            f"operator's persistent errors"
        )

    from agentidprobe.runner import _error_report

    crashed = _error_report(_endpoint("https://crash-example.org/mcp"),
                            Modality.OAUTH_METADATA, "r1", KeyError("issuer"))
    assert INSTRUMENT_MARKER in " ".join(c.detail for c in crashed.checks).lower()


# --- R5's own precondition ----------------------------------------------------


def test_runs_closer_than_twenty_four_hours_finalise_nothing():
    """R5's interval is part of the rule, not advice. Two runs an hour apart measure the
    same outage twice; the classification is still worth recording, but nothing in it is
    final and the transcript has to say so where a skim-reader will see it."""
    url = "https://dead-example.org/mcp"
    checks = {CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")}
    soon = DAY_ONE + timedelta(hours=1)
    result = reconcile_runs(
        RunSide("r1", [_report(url, at=DAY_ONE, run_id="r1", reachable=False, checks=checks)]),
        RunSide("r2", [_report(url, at=soon, run_id="r2", reachable=False, checks=checks)]),
    )

    assert result["separation"]["satisfied"] is False
    assert result["final_errors_established"] is False
    assert any("No ERROR in this dataset is final" in note for note in result["notes"])
    # The classification still happened; it is the finality that is withheld.
    assert _unit(result, url, "C05")["classification"] == Reconciliation.PERSISTENT


def test_a_run_reconciled_against_its_own_replay_is_not_r5():
    """The distinction this module was written to draw. `rescore` reproduces a run from
    stored bytes, so every verdict -- including every error -- is identical by construction
    and `probed_at` is copied from the artefact. R8's comparison passing means the
    instrument is deterministic; passing it off as R5 would confirm the entire error set on
    evidence that contains no second observation at all."""
    url = "https://dead-example.org/mcp"
    checks = {CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")}
    original = _report(url, at=DAY_ONE, run_id="r1", reachable=False, checks=checks)
    replayed = _report(url, at=DAY_ONE, run_id="r1-rescored", reachable=False, checks=checks)

    result = reconcile_runs(RunSide("r1", [original]), RunSide("r1-rescored", [replayed]))

    assert result["separation"]["hours"] == 0.0
    assert result["final_errors_established"] is False


def test_the_interval_is_measured_from_when_the_runs_observed():
    """A census takes hours, so the transcript carries each run's observation window and not
    only the single number computed from it."""
    url = "https://dead-example.org/mcp"
    checks = {CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")}
    result = reconcile_runs(
        RunSide("r1", [_report(url, at=DAY_ONE, run_id="r1", reachable=False, checks=checks)]),
        RunSide("r2", [_report(url, at=DAY_TWO, run_id="r2", reachable=False, checks=checks)]),
    )

    assert result["separation"]["hours"] == pytest.approx(25.0)
    assert result["runs"]["earlier"]["first_observation"] == DAY_ONE.isoformat()
    assert result["runs"]["later"]["first_observation"] == DAY_TWO.isoformat()
    assert result["separation"]["per_endpoint_hours"]["n"] == 1


def test_a_replay_written_a_day_later_does_not_confirm_the_errors_it_copied(tmp_path):
    """The defect this module came closest to shipping, and the reason the interval is taken
    from `probed_at` rather than from the manifest.

    `probe` writes no manifest, so the `started_at` in a probed run's directory is `collect`'s
    -- in `results/runs/slice2/` it is byte-identical to `slice`'s and still says
    `"run_id": "slice"`. `rescore` is worse than stale: it writes a *fresh* manifest stamped
    with the current time while reproducing every stored verdict from the same bytes. Read
    from the manifest, a replay taken a day after its source is two runs 25 hours apart in
    which every single error recurred, and R5 would finalise an entire census that was
    measured once. `probed_at` is copied from the artefact, so the same pair reads 0.0 hours
    and finalises nothing.
    """
    import json

    url = "https://dead-example.org/mcp"
    checks = {CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")}
    _write_run(tmp_path, "r1",
               [_report(url, at=DAY_ONE, run_id="r1", reachable=False, checks=checks)], DAY_ONE)
    # A replay: verdicts and probe timestamps copied, manifest stamped a day later.
    _write_run(tmp_path, "r1-rescored",
               [_report(url, at=DAY_ONE, run_id="r1-rescored", reachable=False, checks=checks)],
               DAY_TWO)

    code = main(["--root", str(tmp_path), "reconcile",
                 "--run-id", "r1", "--against", "r1-rescored"])

    assert code == 1, "a replay was accepted as R5's second run"
    written = json.loads(
        (RunStore(tmp_path, "r1-rescored").run_dir / "reconciliation.json")
        .read_text(encoding="utf-8"))
    assert written["separation"]["hours"] == 0.0, (
        f"the interval was read from the manifest, not from the observations: "
        f"{written['separation']['hours']}"
    )
    assert written["final_errors_established"] is False


def test_the_argument_order_does_not_decide_which_run_came_first():
    url = "https://dead-example.org/mcp"
    checks = {CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")}
    later = RunSide("r2", [_report(url, at=DAY_TWO, run_id="r2", reachable=False,
                                   checks=checks)])
    earlier = RunSide("r1", [_report(url, at=DAY_ONE, run_id="r1", reachable=False,
                                     checks=checks)])

    backwards = reconcile_runs(later, earlier)

    assert backwards["runs"]["earlier"]["run_id"] == "r1"
    assert backwards["runs"]["later"]["run_id"] == "r2"
    assert backwards["separation"]["hours"] == pytest.approx(25.0)


def test_an_endpoint_missing_from_the_second_run_is_not_called_transient():
    """The case a naive implementation gets backwards. "Errored in run 1, no error in run 2"
    is true both when the endpoint recovered and when it was never re-asked -- because the
    corpus changed, the per-host sample dropped it, or the kill switch stopped the run
    before reaching it. Only the first is a transient error. Reporting the second as one
    would count our own truncated run as evidence that hosts recovered."""
    url = "https://vanished-example.org/mcp"
    result = reconcile_runs(*_sides(
        [_report(url, at=DAY_ONE, run_id="r1", reachable=False,
                 checks={CheckId.PRM_PRESENT: (Outcome.ERROR,
                                               "not observed: timeout (R4/R5)")})],
        [],
    ))

    entry = _unit(result, url, "C05")
    assert entry["classification"] == Reconciliation.UNRECONCILED
    assert entry["later"] is None
    assert result["counts"]["checks"][Reconciliation.TRANSIENT] == 0
    assert any("R5 cannot rule on them" in note for note in result["notes"])


def test_a_check_present_in_only_one_run_is_unreconciled_too():
    """The same argument one level down: the instrument may stop emitting a check for an
    endpoint whose shape changed, and the pairing must notice rather than treat an absent
    verdict as a non-error."""
    url = "https://shifted-example.org/mcp"
    result = reconcile_runs(*_sides(
        [_report(url, at=DAY_ONE, run_id="r1",
                 checks={CheckId.AS_CORRESPONDENCE: (Outcome.ERROR,
                                                     "not observed: timeout (R4/R5)")})],
        [_report(url, at=DAY_TWO, run_id="r2",
                 checks={CheckId.PRM_PRESENT: (Outcome.PASS, "")})],
    ))

    assert _unit(result, url, "C13")["classification"] == Reconciliation.UNRECONCILED


def test_two_errors_from_different_causes_are_reported_as_such():
    """"Produces the same result" is R5's wording. Both runs failed to observe the
    endpoint, so the denominator effect is identical and the unit is persistent -- but a
    DNS failure followed by a timeout is not the same cause twice, and a transcript that
    says only "confirmed" overstates what the two runs agree on."""
    url = "https://unstable-example.org/mcp"
    result = reconcile_runs(*_sides(
        [_report(url, at=DAY_ONE, run_id="r1", reachable=False,
                 checks={CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")})],
        [_report(url, at=DAY_TWO, run_id="r2", reachable=False,
                 checks={CheckId.PRM_PRESENT: (Outcome.ERROR,
                                               "not observed: timeout (R4/R5)")})],
    ))

    assert _unit(result, url, "C05")["classification"] == Reconciliation.PERSISTENT
    assert any("different" in note and "reasons" in note for note in result["notes"]), (
        "the transcript claimed a confirmation without saying the causes disagreed"
    )


def test_differing_vantage_points_are_recorded_rather_than_ignored():
    """A second run from another network is the study's answer to residential-IP bias, and
    an error that changes between two vantage points is a property of the path as much as
    of the origin. R5's arithmetic does not notice the difference, so the transcript must."""
    url = "https://blocked-example.org/mcp"
    checks = {CheckId.PRM_PRESENT: (Outcome.ERROR, "access block (R4)")}
    result = reconcile_runs(
        RunSide("r1", [_report(url, at=DAY_ONE, run_id="r1", reachable=False, checks=checks)],
                vantage_point="residential-TR"),
        RunSide("r2", [_report(url, at=DAY_TWO, run_id="r2", reachable=True,
                               checks={CheckId.PRM_PRESENT: (Outcome.PASS, "")})],
                vantage_point="msku-ulakbim"),
    )

    assert any("different vantage points" in note for note in result["notes"])


# --- the command ---------------------------------------------------------------


def _write_run(tmp_path, run_id: str, reports: list[EndpointReport],
               started_at: datetime) -> RunStore:
    store = RunStore(tmp_path, run_id)
    for report in reports:
        store.append_report(report)
    store.write_manifest(RunContext(run_id=run_id, vantage_point="test",
                                    started_at=started_at))
    return store


def test_reconcile_writes_a_transcript_beside_the_later_run(tmp_path):
    """R5 is a rule that has to leave a record. "We confirmed these errors across two runs"
    is a claim a reader is entitled to audit line by line, and a number that existed only
    in a terminal scrollback cannot be."""
    import json

    url = "https://dead-example.org/mcp"
    checks = {CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")}
    _write_run(tmp_path, "r1",
               [_report(url, at=DAY_ONE, run_id="r1", reachable=False, checks=checks)], DAY_ONE)
    later = _write_run(
        tmp_path, "r2",
        [_report(url, at=DAY_TWO, run_id="r2", reachable=False, checks=checks)], DAY_TWO)

    code = main(["--root", str(tmp_path), "reconcile", "--run-id", "r1", "--against", "r2"])

    assert code == 0
    transcript = later.run_dir / "reconciliation.json"
    assert transcript.exists(), "R5 ran and left nothing behind"
    written = json.loads(transcript.read_text(encoding="utf-8"))
    assert written["rule"] == "R5"
    assert written["final_errors_established"] is True
    assert written["counts"]["checks"][Reconciliation.PERSISTENT] == 1
    assert written["separation"]["hours"] == pytest.approx(25.0)
    assert written["runs"]["later"]["run_id"] == "r2"


def test_reconcile_exits_nonzero_when_the_runs_are_too_close_together(tmp_path):
    """The transcript is still written -- the record of an invalid reconciliation is worth
    keeping -- but the exit code stops a pipeline treating it as a confirmation."""
    import json

    url = "https://dead-example.org/mcp"
    checks = {CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")}
    soon = DAY_ONE + timedelta(hours=2)
    _write_run(tmp_path, "r1",
               [_report(url, at=DAY_ONE, run_id="r1", reachable=False, checks=checks)], DAY_ONE)
    _write_run(tmp_path, "r2",
               [_report(url, at=soon, run_id="r2", reachable=False, checks=checks)], soon)

    code = main(["--root", str(tmp_path), "reconcile", "--run-id", "r1", "--against", "r2"])

    assert code == 1
    written = json.loads(
        (RunStore(tmp_path, "r2").run_dir / "reconciliation.json").read_text(encoding="utf-8"))
    assert written["final_errors_established"] is False


def test_lowering_the_threshold_is_recorded_in_the_transcript(tmp_path):
    """`--min-hours` exists so a rehearsal can be reconciled the same day. A run that
    lowered R5's own threshold has to say so in the file rather than in the memory of
    whoever typed the command."""
    import json

    url = "https://dead-example.org/mcp"
    checks = {CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")}
    soon = DAY_ONE + timedelta(hours=2)
    _write_run(tmp_path, "r1",
               [_report(url, at=DAY_ONE, run_id="r1", reachable=False, checks=checks)], DAY_ONE)
    _write_run(tmp_path, "r2",
               [_report(url, at=soon, run_id="r2", reachable=False, checks=checks)], soon)

    code = main(["--root", str(tmp_path), "reconcile", "--run-id", "r1", "--against", "r2",
                 "--min-hours", "1"])

    assert code == 0
    written = json.loads(
        (RunStore(tmp_path, "r2").run_dir / "reconciliation.json").read_text(encoding="utf-8"))
    assert written["separation"]["required_hours"] == 1.0
    assert written["separation"]["required_hours"] != MIN_SEPARATION_HOURS


def test_reconcile_refuses_a_run_against_itself(tmp_path, capsys):
    """Which reproduces every error by construction and would report the whole error set
    as confirmed."""
    url = "https://dead-example.org/mcp"
    _write_run(tmp_path, "r1", [_report(
        url, at=DAY_ONE, run_id="r1", reachable=False,
        checks={CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")})], DAY_ONE)

    code = main(["--root", str(tmp_path), "reconcile", "--run-id", "r1", "--against", "r1"])

    assert code == 2
    assert "two separate runs" in capsys.readouterr().err


def test_reconcile_reports_a_missing_run_rather_than_reconciling_against_nothing(tmp_path):
    _write_run(tmp_path, "r1", [_report(
        "https://dead-example.org/mcp", at=DAY_ONE, run_id="r1", reachable=False,
        checks={CheckId.PRM_PRESENT: (Outcome.ERROR, "not observed: dns (R4/R5)")})], DAY_ONE)

    assert main(["--root", str(tmp_path), "reconcile",
                 "--run-id", "r1", "--against", "never-ran"]) == 2
