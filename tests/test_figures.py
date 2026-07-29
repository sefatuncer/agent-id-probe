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
    build_delegation_graph,
    cluster_robust_proportion,
    cross_check_feasibility,
)
from agentidprobe.figures import (
    CHAIN,
    TOP_K,
    figure2_data,
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
                         "figure-data.json")
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
