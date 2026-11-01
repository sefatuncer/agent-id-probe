"""The per-interval coverage calibration (scripts/coverage_calibrated.py).

Section 4.5 prints a coverage range for the published intervals and says which of them fall
short. These tests hold the script's model to what its docstring claims, and the committed
result to what the manuscript is allowed to read off it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "docs" / "coverage-calibrated.json"


def _load() -> Any:
    path = ROOT / "scripts" / "coverage_calibrated.py"
    spec = importlib.util.spec_from_file_location("agentidprobe_coverage_calibrated", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CAL = _load()


def test_icc_is_zero_where_no_group_has_two_members():
    assert CAL.anova_icc([(1, 1), (0, 1), (1, 1), (0, 1)]) == 0.0


def test_icc_of_groups_that_agree_completely_is_clamped_below_one():
    groups = [(5, 5), (0, 5), (5, 5), (0, 5), (5, 5)]
    assert CAL.anova_icc(groups) == 0.999


def test_icc_of_identical_group_rates_is_clamped_at_zero():
    # Every group at the overall rate leaves no between-group variance, and the estimate goes
    # negative; a negative ICC is noise around independence.
    assert CAL.anova_icc([(2, 4), (2, 4), (2, 4)]) == 0.0


def _task(layout, p, icc, alternative, trials=600, seed=7):
    return {"key": "t", "p_hat": p, "icc": icc, "layout": layout,
            "alternative": alternative, "trials": trials, "seed": seed}


def test_independent_singletons_cover_near_the_nominal_level():
    result = CAL.simulate(_task([(1, True)] * 400, p=0.3, icc=0.0, alternative=False))
    assert 0.92 <= result["coverage"] <= 0.98


def test_ignoring_the_dependence_undercovers_and_clustering_on_it_repairs_it():
    # Twenty groups of ten whose members are each published as their own cluster: the
    # published interval treats 200 observations as independent, the dependence-clustered one
    # knows there are twenty groups.
    result = CAL.simulate(_task([(10, True)] * 20, p=0.4, icc=0.5, alternative=True))
    assert result["coverage"] < 0.75
    assert result["coverage_dependence_clustered"] > result["coverage"] + 0.15


def test_simulation_is_reproducible_from_its_seed():
    task = _task([(3, False)] * 50, p=0.2, icc=0.3, alternative=False, trials=200)
    assert CAL.simulate(task) == CAL.simulate(task)


# -- the committed result -----------------------------------------------------------------

def _result() -> dict:
    return json.loads(RESULT.read_text(encoding="utf-8"))


def test_the_published_ranges_are_what_the_rows_say():
    data = _result()
    simulated = [row for row in data["intervals"] if row.get("coverage") is not None]
    at_estimate = [row["coverage"] for row in simulated]
    assert data["coverage_at_estimated_icc"] == [min(at_estimate), max(at_estimate)]
    grid = [c for row in simulated for c in row["coverage_by_icc"].values()]
    assert data["coverage_over_icc_grid"] == [min(grid), max(grid)]
    assert data["below_090_at_estimated_icc"] == sorted(
        row["key"] for row in simulated if row["coverage"] < 0.90)
    assert [float(k) for k in simulated[0]["coverage_by_icc"]] == data["icc_grid"]


def test_every_row_is_simulated_or_says_why_not():
    for row in _result()["intervals"]:
        if row.get("coverage") is None:
            assert row["coverage_note"].startswith("not simulated: ")
        else:
            assert 0.0 <= row["coverage"] <= 1.0


def test_c05_is_not_simulated_on_a_grouping_its_own_outcome_defines():
    rows = {row["key"]: row for row in _result()["intervals"]}
    assert rows["c05-apex"]["coverage"] is None
    assert "fingerprint" in rows["c05-apex"]["coverage_note"]
    # The same check on a grouping its outcome does not define is simulated.
    assert rows["c05-implementation"]["coverage"] is not None


def test_the_result_carries_no_domain_or_url():
    domain = re.compile(r"\b[a-z0-9-]+\.[a-z]{2,}\b", re.IGNORECASE)

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    offending = [s for s in strings(_result()) if "://" in s or domain.search(s)]
    assert not offending, offending
