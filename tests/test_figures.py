"""The figures must agree with the statistics, and must not need the data to exist.

Two things are being defended here.

The first is that Figure 2 is a *view* of `analysis.py` and not a second implementation of
it. A figure that recomputes its own numbers will eventually disagree with the results
section, and the disagreement will be found by a reader rather than by a build. So every
assertion below compares `figure2_data()` against `analysis.py` called directly, on the
same input.

The second is that the figures were drawn before the measurement. That claim is only
worth something if it is checkable, so the renderers are exercised here against
`synthetic_population()` -- no run directory, no network, no stored artefacts. If the
figures could not be produced without data, the claim would be unfalsifiable.
"""

from __future__ import annotations

import json

import pytest

from agentidprobe.analysis import (
    HEADLINE_CANDIDATES,
    MAX_HEADLINE_HALF_WIDTH,
    VARIANCE_CEILING,
    VARIANCE_FLOOR,
    build_delegation_graph,
    cluster_robust_proportion,
    cross_check_feasibility,
    headline_candidates,
    passes_variance_test,
    select_headline,
)
from agentidprobe.figures import (
    CHAIN,
    TOP_K,
    figure2_data,
    figure3_data,
    render_all,
    synthetic_population,
)
from agentidprobe.models import CheckId

matplotlib = pytest.importorskip(
    "matplotlib",
    reason="rendering needs the optional 'figures' extra: pip install '.[figures]'",
)


# ---------------------------------------------------------------------------
# Figure 2 reports what analysis.py computes, and nothing else
# ---------------------------------------------------------------------------

def test_figure2_matches_the_analysis_layer_exactly():
    reports = synthetic_population()
    data = figure2_data(reports)

    graph = build_delegation_graph(reports)
    concentration = graph.concentration()
    cross = cluster_robust_proportion(graph.cross_operator_clusters())

    assert data["concentration"] == concentration
    assert data["issuers"] == concentration["issuers"]
    assert data["relation"] == {
        "same_operator": graph.same_operator,
        "cross_operator": graph.cross_operator,
        "unknown_operator": graph.unknown_operator,
        "total": graph.total,
    }
    assert data["cross_operator_rate"] == cross.as_record()
    assert data["cross_check"] == cross_check_feasibility(reports)
    assert data["shared_across_apexes"] == len(graph.shared_across_apexes)


def test_the_bars_and_the_tail_account_for_every_declared_edge():
    """Nothing may be dropped between the graph and the picture.

    The first draft of Figure 2a hid the largest segment in the figure behind an opaque
    annotation box, which is undetectable by eye: an occluded bar looks exactly like a
    short one. Shares are asserted to sum to 1 so that a segment silently going missing
    fails the build instead.
    """
    data = figure2_data(synthetic_population())

    plotted = sum(entry["share"] for entry in data["top_issuers"]) + data["tail"]["share"]
    assert plotted == pytest.approx(1.0)

    counted = sum(e["count"] for e in data["top_issuers"]) + data["tail"]["count"]
    assert counted == data["declared_edges"]
    assert len(data["top_issuers"]) <= TOP_K
    assert data["tail"]["issuers"] == data["issuers"] - len(data["top_issuers"])


def test_relation_buckets_partition_the_edges():
    data = figure2_data(synthetic_population())
    rel = data["relation"]
    assert rel["same_operator"] + rel["cross_operator"] + rel["unknown_operator"] == rel["total"]


def test_empty_population_does_not_explode():
    """An empty or all-blocked run must still produce a figure.

    R4 makes access blocks an ERROR rather than a finding, so a run that is blocked
    everywhere is a real possibility, and the renderer discovering that on the day of the
    run would be the worst possible time.
    """
    data = figure2_data([])
    assert data["issuers"] == 0
    assert data["declared_edges"] == 0
    assert data["concentration"]["hhi"] is None
    assert data["relation"]["total"] == 0


# ---------------------------------------------------------------------------
# Figure 1 cannot name a check that does not exist
# ---------------------------------------------------------------------------

def test_figure1_only_cites_live_checks():
    """The C06/C10 defect, as a test.

    Both were deleted from `CheckId` in July and survived in a hand-written table for
    days. `CHAIN` holds `CheckId` members rather than strings, so a deleted check breaks
    at import; this asserts the property directly as well, because the import-time
    guarantee is easy to lose to a refactor that reintroduces strings.
    """
    for step in CHAIN:
        for check in step.checks:
            assert isinstance(check, CheckId)
            assert check in set(CheckId)


def test_figure1_agrees_with_table1_about_who_each_clause_binds():
    """The figure and the table are two views of one fact and must not disagree.

    They did. Figure 1's token-request step listed C14 under `binds: authorization server`
    with a clause string citing RFC 9207 and RFC 9728 §4 — neither of which mentions PKCE —
    while Table 1 recorded C14 as client-bound. Nothing related `ChainStep` to
    `SPEC_ANCHOR_SUMMARY`, so both could be wrong in different directions indefinitely.
    """
    from agentidprobe.models import SPEC_ANCHOR_SUMMARY

    for step in CHAIN:
        if step.out_of_scope or not step.checks:
            continue
        for check in step.checks:
            _, party = SPEC_ANCHOR_SUMMARY[check]
            assert party.value == step.binds, (
                f"{check.value} binds {party.value!r} in Table 1 but the figure puts it on "
                f"an edge that binds {step.binds!r}"
            )


def test_the_selection_step_is_the_one_edge_that_binds_nobody():
    """The figure's whole argument, asserted.

    If a future edit gives the selection step a binding party, or gives some other step
    none, the figure would be making a different claim than the paper. That is worth a
    test even though it reads like a tautology: it is the one assertion in this file that
    is about the argument rather than about the plumbing.
    """
    unbound = [step for step in CHAIN if step.binds == "nobody"]
    assert len(unbound) == 1
    assert unbound[0].out_of_scope
    assert not unbound[0].checks, "an out-of-scope edge cannot have a check anchored to it"

    for step in CHAIN[1:]:
        assert step.clause, f"{step.node} has an edge with no clause"
        assert step.binds, f"{step.node} has an edge that binds nothing"


# ---------------------------------------------------------------------------
# Both figures render with no measurement in existence
# ---------------------------------------------------------------------------

def test_renders_from_the_fixture_alone(tmp_path):
    result = render_all(synthetic_population(), tmp_path, formats=("pdf",), synthetic=True)

    written = [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in result["written"]]
    assert "fig1-discovery-chain.pdf" in written
    assert "fig2-delegation.pdf" in written
    for path in result["written"]:
        assert (tmp_path / path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]).stat().st_size > 4000

    sidecar = json.loads((tmp_path / "figure-data.json").read_text(encoding="utf-8"))
    assert sidecar["source"] == "SYNTHETIC FIXTURE -- NOT A MEASUREMENT"
    assert sidecar["figure2"] == result["data"]["figure2"]


def test_two_renders_of_the_same_input_are_byte_identical(tmp_path):
    """`_save` claims a rebuild produces the same file; this is that claim as a test.

    R8 leg 2 makes byte-identical re-scoring a checkable property of the verdicts. A figure
    that embedded a creation timestamp would be the one published artefact that could not
    be reproduced, and the claim in `_save` would have been decorative. It is not: the PDF
    backend writes a CreationDate unless it is explicitly suppressed.
    """
    import hashlib

    digests = []
    for run in ("first", "second"):
        render_all(synthetic_population(), tmp_path / run, formats=("pdf",), synthetic=True)
        digests.append({
            name: hashlib.sha256((tmp_path / run / name).read_bytes()).hexdigest()
            for name in ("fig1-discovery-chain.pdf", "fig2-delegation.pdf",
                         "figure3-headline-selection.pdf", "figure-data.json")
        })
    assert digests[0] == digests[1]


def test_a_synthetic_render_says_so_and_a_real_one_does_not(tmp_path):
    """The label is the only thing standing between a fixture figure and a draft.

    A synthetic figure that reaches a manuscript and is read as a measurement is the worst
    outcome this module could cause, so the marker is asserted in both directions.
    """
    render_all(synthetic_population(), tmp_path / "fake", formats=("pdf",), synthetic=True)
    render_all(synthetic_population(), tmp_path / "real", formats=("pdf",), synthetic=False)

    fake = json.loads((tmp_path / "fake" / "figure-data.json").read_text(encoding="utf-8"))
    real = json.loads((tmp_path / "real" / "figure-data.json").read_text(encoding="utf-8"))
    assert "SYNTHETIC" in fake["source"]
    assert real["source"] == "measurement"


def test_the_fixture_exercises_both_relation_buckets():
    """A fixture that only produces one bucket tests nothing about the figure.

    The first version assigned tenant apexes that `apex_domain()` resolved differently
    from the issuer hosts, so every edge landed in `cross_operator` and the stacked bar
    had one segment -- a green test over a figure that could not have shown a defect.
    """
    data = figure2_data(synthetic_population())
    assert data["relation"]["same_operator"] > 0
    assert data["relation"]["cross_operator"] > 0
    assert data["cross_operator_rate"]["m"] > 30, "too few clusters to exercise R10.4"
    assert 0.0 < data["cross_operator_rate"]["p_hat"] < 1.0


def test_the_fixture_never_leaves_reserved_or_synthetic_names():
    """Nothing in the fixture may look like somebody's real deployment.

    RFC 2606 reserves only three registrable names, which is why the tenants use
    `tenantNN-example.org` rather than a reserved name -- see `synthetic_population`. This
    asserts the compromise stays inside the shape it was argued for, so no future edit
    reaches for a real host to make the picture look better.
    """
    for report in synthetic_population():
        host = report.endpoint.url.split("/")[2]
        assert host.endswith("-example.org"), host
        for issuer in report.evidence["authorization_servers"]:
            assert issuer.endswith(("example.com", "example.net", "-example.org")), issuer


# --- Figure 3: the R11.2 selection ---------------------------------------------


def test_figure3_computes_nothing_of_its_own():
    """The Figure 2 contract, applied to the figure that draws the headline decision.

    Every value must come from `analysis.py`, so that the picture cannot disagree with §5.6
    without breaking a test. This matters more here than for Figure 2: Figure 3 is not an
    illustration of the selection, it *is* the selection, and a figure that drew slightly
    different intervals from the transcript beside it would be the most damaging possible
    discrepancy in the paper.
    """
    reports = synthetic_population()
    data = figure3_data(reports)
    expected = headline_candidates(reports)
    winner, reason = select_headline(expected)

    assert data["headline"] == {"selected": winner, "reason": reason}
    assert len(data["candidates"]) == len(expected)
    for row, (label, estimate) in zip(data["candidates"], expected, strict=True):
        assert row["label"] == label
        assert row["estimate"] == estimate.as_record()
        assert row["passed"] == passes_variance_test(estimate).passed
        assert row["reason"] == passes_variance_test(estimate).reason


def test_figure3_draws_the_frozen_rank_order_and_not_a_sorted_one():
    """R11.1's order is the content, so sorting would be a claim the rule does not make.

    Ordering the rows by estimate would let the picture imply a ranking by size while the
    selection rule uses rank, and the two disagree in the fixture already: rank 4 has the
    largest rate and rank 1 comes first.
    """
    data = figure3_data(synthetic_population())
    assert [row["rank"] for row in data["candidates"]] == [
        rank for rank, _, _ in HEADLINE_CANDIDATES
    ]
    assert [row["denominator"] for row in data["candidates"]] == [
        denominator for _, _, denominator in HEADLINE_CANDIDATES
    ]


def test_figure3_bands_are_the_rule_not_literals():
    """The shaded regions are R11.2's thresholds, read from the module that enforces them.

    Hard-coding 2% and 98% in the renderer would let the figure keep drawing the old bands
    after the rule changed -- and a figure showing more generous bands than the rule applies
    is an argument that a rejected candidate should have won.
    """
    bands = figure3_data(synthetic_population())["bands"]
    assert bands["floor"] == VARIANCE_FLOOR
    assert bands["ceiling"] == VARIANCE_CEILING
    assert bands["max_half_width"] == MAX_HEADLINE_HALF_WIDTH


def test_the_synthetic_fixture_can_actually_exercise_figure3():
    """The guard for the defect that this figure was first written with.

    As built for Figure 2 the fixture carried no `checks` and none of the fields C16 and C17
    read, so three of the four candidates came out at `0.0% [0.0%, 0.0%]`, rank 4 at
    `n=0 m=0`, every candidate was rejected, and the code path that draws the winner never
    ran. The render was green and proved nothing -- the same failure the module docstring
    records for Figure 2's first draft, where every edge fell into one bucket and the
    cross-operator rate was 100%.

    A fixture that cannot show the thing under test is worse than no fixture, because it
    passes. So: every candidate must rest on a real denominator, the rates must not all be
    identical, and exactly one candidate must be selected so that the accent, the filled
    marker and the bold verdict are all exercised.
    """
    data = figure3_data(synthetic_population())
    rows = data["candidates"]

    for row in rows:
        assert row["estimate"]["n"] > 0, f"{row['label']} has an empty denominator"
        assert row["estimate"]["m"] > 0, f"{row['label']} has no clusters"

    rates = {row["estimate"]["p_hat"] for row in rows}
    assert len(rates) == len(rows), "the fixture gives candidates indistinguishable rates"

    selected = [row for row in rows if row["is_headline"]]
    assert len(selected) == 1, (
        "no candidate is selected, so the renderer's winner path is never executed"
    )
    assert selected[0]["passed"] is True


def test_figure3_selects_by_rank_among_the_survivors():
    """R11.2 in the data the figure draws: the winner is the highest-ranked passing candidate.

    Asserted against the rows rather than against `select_headline` alone, because the figure
    is what a reader audits the rule against, and "the marked row is the first one that
    passed" is the property they will check by eye.
    """
    rows = figure3_data(synthetic_population())["candidates"]
    survivors = [row for row in rows if row["passed"]]
    assert survivors, "fixture must leave at least one survivor"
    assert survivors[0]["is_headline"] is True
    for row in survivors[1:]:
        assert row["is_headline"] is False
