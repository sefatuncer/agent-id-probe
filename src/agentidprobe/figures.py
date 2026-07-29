"""Figures 1 and 2, written against a synthetic fixture before any measurement exists.

Why this module exists now rather than after the run
----------------------------------------------------
Decision rule R11 closes the candidate-headline list before collection, so that the number
carrying the paper cannot be chosen for how good it looks. A figure is the same move with a
different surface. Axis limits, the cut between "top issuers" and "everyone else", whether a
category is drawn or folded away -- each is a degree of freedom, and each is invisible in
the finished plot. Choosing them with the data already on screen is exactly the manoeuvre
R11 exists to prevent, and it would undo R11 without ever contradicting it.

So the figures are drawn first, against `synthetic_population()` below, and the commit that
adds them predates the first live request. What the measurement is allowed to change is the
values; what it is not allowed to change is which quantity is plotted, in what unit, against
what denominator, with what cut.

What keeps them honest afterwards
---------------------------------
* **Figure 2 computes nothing.** Every plotted quantity comes from `analysis.py` --
  `build_delegation_graph`, `DelegationGraph.concentration`, `cluster_robust_proportion`.
  `figure2_data()` returns precisely what the renderer draws, and `tests/test_figures.py`
  asserts those values against `analysis.py`'s own output. A figure that disagrees with the
  statistics section is therefore a test failure rather than a reader's discovery.
* **Figure 1 names checks by `CheckId` member, never by string.** C06 and C10 were deleted
  in July and lived on in a hand-written table until two people happened to read both. An
  edge labelled with a deleted check now raises `AttributeError` at import.
* **The numbers are written out beside the plots.** `render_all` drops a
  `figure-data.json` next to the PDFs, so the prose can cite the same file the figure was
  built from instead of a number retyped from a picture.

matplotlib is an optional extra (`pip install .[figures]`). `analysis.py` is
standard-library only on purpose, and importing this module must not quietly change that,
so matplotlib is imported inside the render functions and nowhere else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analysis import (
    DelegationGraph,
    ProportionEstimate,
    build_delegation_graph,
    cluster_robust_proportion,
    cross_check_feasibility,
)
from .collectors import apex_domain, endpoint_id
from .models import CheckId, Endpoint, EndpointKind, EndpointReport, Modality

# ---------------------------------------------------------------------------
# Presentation constants, fixed here so no renderer picks them per dataset
# ---------------------------------------------------------------------------

# Print, not screen. Elsevier's single-column width is ~90 mm and double is ~190 mm; both
# figures are drawn at double width because both carry text that does not survive being
# reduced to 90 mm.
FIG_WIDTH_IN = 7.48        # 190 mm
FIG1_HEIGHT_IN = 8.40
FIG2_HEIGHT_IN = 3.40

# Greyscale with a single accent. A journal figure is read on paper and photocopied, and
# the categorical-palette machinery for screens does not apply: lightness separation is the
# encoding that survives both greyscale and every form of colour vision deficiency, because
# it does not depend on hue at all. The accent is used exactly twice -- for the edge RFC
# 9728 declares out of scope, and for the cross-operator share -- and both times it is
# redundant with a label, so nothing is carried by colour alone.
INK = "#1a1a1a"
INK_MUTED = "#5c5c5c"
RULE = "#b0b0b0"
SURFACE = "#ffffff"
FILL_LIGHT = "#e4e4e4"
FILL_MID = "#b8b8b8"
FILL_DARK = "#7a7a7a"
ACCENT = "#b3472e"         # ~4.6:1 on white, and distinctly darker than FILL_MID in grey

# How many issuers get their own bar in Figure 2a before the tail is folded into one
# "all other issuers" row. Frozen here, before the distribution is known: choosing it later
# is choosing how concentrated the ecosystem looks.
TOP_K = 10


def _rc() -> dict[str, Any]:
    """rcParams pinned so two machines produce the same file.

    `pdf.fonttype = 42` embeds TrueType rather than Type 3, which Elsevier requires and
    which also makes the text selectable and searchable in the submitted PDF. DejaVu ships
    with matplotlib, so the figure does not depend on a font the reader happens to have.
    """
    return {
        "font.family": "DejaVu Sans",
        "font.size": 8.0,
        "axes.titlesize": 9.0,
        "axes.labelsize": 8.0,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "legend.fontsize": 7.5,
        "axes.edgecolor": RULE,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.hashsalt": "agent-id-probe",
    }


def _save(fig, out_dir: Path, stem: str, formats: tuple[str, ...]) -> list[Path]:
    written: list[Path] = []
    for fmt in formats:
        path = out_dir / f"{stem}.{fmt}"
        # No creation date in the PDF: a byte-identical rebuild is worth more than a
        # timestamp nobody reads, and R8's whole claim is about rebuilding things.
        metadata = {"CreationDate": None} if fmt == "pdf" else None
        fig.savefig(path, format=fmt, dpi=300, bbox_inches="tight",
                    metadata=metadata, pad_inches=0.02)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# Figure 1 -- the discovery chain, schematic, no data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChainStep:
    """One node of the discovery chain and the edge that reaches it.

    `binds` is the field the paper argues from and the reason this is a figure rather than a
    paragraph: every edge in this chain is governed by a clause, and the clauses bind
    different parties -- resource server, authorization server, and, at the one step that
    decides who the client trusts, nobody at all.
    """

    node: str
    detail: str
    edge: str
    clause: str
    binds: str
    checks: tuple[CheckId, ...] = ()
    out_of_scope: bool = False


# Referencing CheckId members rather than the strings "C05", "C12" is deliberate: see the
# module docstring. The clause text is quoted, not paraphrased, so that a reader can grep
# for it in the RFC.
CHAIN: tuple[ChainStep, ...] = (
    ChainStep(
        node="MCP client",
        detail="holds no prior knowledge of this resource",
        edge="", clause="", binds="",
    ),
    ChainStep(
        node="Resource server",
        detail="https://example.org/mcp",
        edge="1.  request  →  401 + WWW-Authenticate: resource_metadata",
        clause="MCP Authorization (2025-06-18 MUST; 2025-11-25 one of several routes)",
        binds="resource server",
        checks=(CheckId.WWW_AUTH_RESOURCE_METADATA,),
    ),
    ChainStep(
        node="Protected-resource metadata",
        detail="/.well-known/oauth-protected-resource/mcp\n(root form tried as well)",
        edge="2.  fetch protected-resource metadata",
        clause="RFC 9728 §3.1 (path-inserted well-known URI); §3.3 `resource` MUST be "
              "identical to the resource identifier",
        binds="resource server",
        checks=(CheckId.PRM_PRESENT, CheckId.PRM_RESOURCE_IDENTITY_MATCH),
    ),
    ChainStep(
        node="authorization_servers: [ iss₁, iss₂, … ]",
        detail="a list, with no stated relation to the resource",
        edge="3.  read the declared issuers",
        clause="MCP: the list MUST contain at least one entry",
        binds="resource server",
        checks=(CheckId.PRM_PRESENT,),
    ),
    ChainStep(
        node="The client selects one issuer  ‡",
        detail="no clause governs this edge",
        edge="4.  choose",
        clause="RFC 9728 §7.6 — out of scope; MCP delegates the choice to the client unchanged",
        binds="nobody",
        out_of_scope=True,
    ),
    ChainStep(
        node="Authorization-server metadata",
        detail="/.well-known/oauth-authorization-server\n(openid-configuration tried as well)",
        edge="5.  fetch authorization-server metadata",
        clause="RFC 8414 §3.3: `issuer` MUST be identical to the issuer requested",
        binds="authorization server",
        checks=(CheckId.AS_CORRESPONDENCE,),
    ),
    ChainStep(
        node="Token request",
        detail="the client now trusts an issuer it could not verify",
        edge="6.  authorize",
        clause="RFC 9207 §3: support for `iss` MUST be advertised in that metadata; "
              "RFC 9728 §4 `protected_resources` is OPTIONAL",
        binds="authorization server",
        # C14 was listed here until 29 July 2026, under a clause string citing RFC 9207 and
        # RFC 9728 §4 -- neither of which says anything about PKCE. The figure was asserting
        # an anchor the instrument did not have, and no test related `ChainStep` to
        # `SPEC_ANCHOR_SUMMARY`, which is why it survived. `test_figures.py` now closes that.
        checks=(CheckId.ISS_PARAMETER_DECLARED, CheckId.PROTECTED_RESOURCES_DECLARED),
    ),
)


def figure1_discovery_chain(out_dir: Path, formats: tuple[str, ...] = ("pdf", "png")) -> list[Path]:
    """Draw the chain, its clauses, and the party each clause binds.

    Contains no measurement. It is in this module rather than in a drawing program because
    its labels are generated from `CheckId` and from quoted clause text held in one place,
    which is the only way the figure and the instrument stay in agreement as the instrument
    changes.
    """
    import textwrap

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    with plt.rc_context(_rc()):
        fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, FIG1_HEIGHT_IN))
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.axis("off")

        n = len(CHAIN)
        # The chain occupies the upper region; the quoted clauses live in a footnote block
        # below it. Putting them inside the node box was the first draft, and a four-line
        # quotation does not fit in a node: it overflowed into the box beneath it and into
        # the annotation column, so the figure's two most important sentences were the
        # least readable thing in it. Down here they have the full width.
        top, bottom = 95.0, 26.0
        slot = (top - bottom) / n
        box_x, box_w = 10.0, 38.0
        box_h = slot * 0.78
        ann_x = box_x + box_w + 4.0

        centres: list[float] = []
        for i, step in enumerate(CHAIN):
            centre = top - slot * (i + 0.5)
            centres.append(centre)
            emphasised = step.out_of_scope

            ax.add_patch(FancyBboxPatch(
                (box_x, centre - box_h / 2), box_w, box_h,
                boxstyle="round,pad=0.5,rounding_size=1.0",
                linewidth=1.4 if emphasised else 0.9,
                edgecolor=ACCENT if emphasised else RULE,
                facecolor=FILL_LIGHT if emphasised else SURFACE,
                linestyle="--" if emphasised else "-",
                zorder=3,
            ))
            ax.text(box_x + 1.8, centre + box_h / 2 - 1.5, step.node,
                    fontsize=8.0, fontweight="bold",
                    color=ACCENT if emphasised else INK, va="top", zorder=4)
            if step.detail:
                ax.text(box_x + 1.8, centre + box_h / 2 - 3.8, step.detail,
                        fontsize=6.8, color=INK_MUTED, va="top", linespacing=1.4, zorder=4)

            if i == 0:
                continue

            prev = centres[i - 1]
            arrow_x = box_x + box_w / 2
            ax.add_patch(FancyArrowPatch(
                (arrow_x, prev - box_h / 2 - 0.3), (arrow_x, centre + box_h / 2 + 0.3),
                arrowstyle="-|>", mutation_scale=10,
                linewidth=1.5 if step.out_of_scope else 1.0,
                linestyle="--" if step.out_of_scope else "-",
                color=ACCENT if step.out_of_scope else INK_MUTED, zorder=2,
            ))

            # The annotation column, aligned to the top of the box the edge arrives at.
            # `binds` sits on its own line because it is the column a reader should be
            # able to scan by itself -- read straight down, it is the paper's argument.
            # The clause is wrapped to a fixed character count rather than left to
            # matplotlib's `wrap`, so the line breaks are the same on every machine.
            y = centre + box_h / 2 + 0.4
            ax.text(ann_x, y, step.edge, fontsize=7.5, fontweight="bold",
                    color=ACCENT if step.out_of_scope else INK, va="top")
            clause = textwrap.fill(step.clause, width=66)
            ax.text(ann_x, y - 2.6, clause, fontsize=6.6, color=INK_MUTED,
                    va="top", linespacing=1.4)
            binds_y = y - 2.6 - 2.2 * (clause.count("\n") + 1)
            ax.text(ann_x, binds_y,
                    f"binds: {step.binds}"
                    + (f"     [{', '.join(c.value for c in step.checks)}]"
                       if step.checks else ""),
                    fontsize=6.6, color=ACCENT if step.binds == "nobody" else INK_MUTED,
                    fontweight="bold" if step.binds == "nobody" else "normal", va="top")

        # The mitigation RFC 9728 §7.6 itself proposes, drawn as what it is: a back edge
        # that exists only when the issuer chose to publish the list -- which is why the
        # study measures whether anybody did. It is marked rather than labelled in place;
        # a rotated caption in the left margin overprinted three of the boxes.
        # Routed through the left margin as three straight segments rather than as an arc.
        # An arc between two boxes in the same column has nowhere to bulge except across
        # the boxes between them, and it crossed three of them.
        lane = box_x - 6.0
        dash = (0, (3, 2))
        ax.plot([box_x, lane], [centres[5], centres[5]], color=INK_MUTED,
                linewidth=1.0, linestyle=dash, zorder=1)
        ax.plot([lane, lane], [centres[5], centres[2]], color=INK_MUTED,
                linewidth=1.0, linestyle=dash, zorder=1)
        ax.add_patch(FancyArrowPatch(
            (lane, centres[2]), (box_x - 0.3, centres[2]),
            arrowstyle="-|>", mutation_scale=9, linewidth=1.0, linestyle=dash,
            color=INK_MUTED, zorder=1,
        ))
        ax.text(lane, (centres[2] + centres[5]) / 2, "†",
                fontsize=10.0, color=INK_MUTED, va="center", ha="center",
                bbox={"boxstyle": "square,pad=0.25", "facecolor": SURFACE,
                      "edgecolor": "none"})

        ax.add_patch(FancyBboxPatch(
            (box_x - 9.5, 1.5), 100 - box_x + 1.5, 19.5,
            boxstyle="round,pad=0.4,rounding_size=1.0",
            linewidth=0.7, edgecolor=RULE, facecolor=SURFACE, zorder=1,
        ))
        ax.text(box_x - 7.9, 19.4,
                "‡   RFC 9728 §7.6, the clause that governs the selection step:",
                fontsize=7.0, fontweight="bold", color=ACCENT, va="top")
        ax.text(box_x - 7.9, 16.6,
                "“Secure determination of appropriate authorization servers to use with a "
                "protected resource for all use cases\n"
                "is out of scope for this specification.”     "
                "“… an attacker may be able to act as an adversary-in-the-middle\n"
                "proxy to a valid authorization server without it being detected.”",
                fontsize=6.8, color=INK, va="top", linespacing=1.5)
        ax.text(box_x - 7.9, 8.6,
                "†   The only mitigation §7.6 proposes: cross-check the resource's issuer "
                "list against the issuer's resource list.",
                fontsize=7.0, fontweight="bold", color=INK_MUTED, va="top")
        ax.text(box_x - 7.9, 5.9,
                "Possible only where the authorization server publishes "
                "`protected_resources` (RFC 9728 §4), which is OPTIONAL — "
                f"[{CheckId.PROTECTED_RESOURCES_DECLARED.value}].\n"
                "Whether anybody does is the quantity this study reports.",
                fontsize=6.8, color=INK_MUTED, va="top", linespacing=1.5)

        ax.text(box_x - 9.5, 99.3,
                "Figure 1.  The discovery chain from a client's first request to its token "
                "request, and the party each clause binds.",
                fontsize=8.0, fontweight="bold", va="top")

        return _save(fig, out_dir, "fig1-discovery-chain", formats)


# ---------------------------------------------------------------------------
# Figure 2 -- delegation topology
# ---------------------------------------------------------------------------

def figure2_data(reports: list[EndpointReport]) -> dict:
    """Everything Figure 2 draws, as numbers, computed only by `analysis.py`.

    Returned rather than plotted-and-forgotten so the test suite can assert that the
    picture and the statistics section rest on the same values, and so the prose can cite
    `figure-data.json` instead of a number read off a chart.
    """
    graph: DelegationGraph = build_delegation_graph(reports)
    concentration = graph.concentration()
    cross: ProportionEstimate = cluster_robust_proportion(graph.cross_operator_clusters())

    total_edges = sum(graph.issuer_counts.values())
    ranked = sorted(graph.issuer_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    head = ranked[:TOP_K]
    tail = ranked[TOP_K:]

    return {
        "issuers": concentration["issuers"],
        "declared_edges": total_edges,
        "concentration": concentration,
        "top_issuers": [
            {"issuer": issuer, "count": count,
             "share": (count / total_edges) if total_edges else 0.0}
            for issuer, count in head
        ],
        "tail": {
            "issuers": len(tail),
            "count": sum(c for _, c in tail),
            "share": (sum(c for _, c in tail) / total_edges) if total_edges else 0.0,
        },
        "relation": {
            "same_operator": graph.same_operator,
            "cross_operator": graph.cross_operator,
            "unknown_operator": graph.unknown_operator,
            "total": graph.total,
        },
        "cross_operator_rate": cross.as_record(),
        "shared_across_apexes": len(graph.shared_across_apexes),
        "cross_check": cross_check_feasibility(reports),
    }


def _issuer_label(issuer: str) -> str:
    """Display only. The identity plotted is the issuer URL; this shortens it to fit.

    Issuer hosts are published, public configuration, and naming them is the difference
    between a concentration figure and a rumour about one. Nothing here is anonymised.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(issuer)
    label = parts.netloc or issuer
    path = parts.path.rstrip("/")
    if path:
        label += path if len(path) <= 18 else path[:17] + "…"
    return label if len(label) <= 34 else label[:33] + "…"


def figure2_delegation(
    data: dict, out_dir: Path, formats: tuple[str, ...] = ("pdf", "png"),
) -> list[Path]:
    """(a) which issuers the population names, (b) whether they belong to somebody else.

    Both panels are percentages of the same denominator, on one x axis each. There is no
    second y scale anywhere in this figure: a bar chart with a cumulative curve on a twin
    axis was the first draft, and a twin axis lets a reader take away whichever of two
    incompatible scales they happened to read. The cumulative quantities are printed as
    text instead, which is what they were for.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with plt.rc_context(_rc()):
        fig, (ax_a, ax_b) = plt.subplots(
            1, 2, figsize=(FIG_WIDTH_IN, FIG2_HEIGHT_IN),
            gridspec_kw={"width_ratios": [1.15, 1.0], "wspace": 0.42},
        )

        # ---- (a) issuer concentration -------------------------------------------------
        rows = [(_issuer_label(e["issuer"]), e["share"], e["count"]) for e in data["top_issuers"]]
        tail = data["tail"]
        if tail["issuers"]:
            rows.append((f"all other issuers (n={tail['issuers']})", tail["share"], tail["count"]))

        ys = list(range(len(rows)))[::-1]
        for y, (label, share, count) in zip(ys, rows, strict=True):
            is_tail = label.startswith("all other issuers")
            ax_a.barh(y, share * 100.0, height=0.68,
                      color=FILL_LIGHT if is_tail else FILL_DARK,
                      edgecolor=SURFACE, linewidth=1.2, zorder=3)
            ax_a.text(share * 100.0 + 1.2, y, f"{share * 100:.1f}%  ({count})",
                      va="center", fontsize=6.8, color=INK_MUTED, zorder=4)

        ax_a.set_yticks(ys)
        ax_a.set_yticklabels([r[0] for r in rows], fontsize=6.8)
        ax_a.set_xlabel("share of declared resource → issuer edges (%)")
        ax_a.set_xlim(0, max([r[1] for r in rows] + [0.0]) * 100.0 * 1.38 + 4)
        ax_a.grid(axis="x", color=RULE, linewidth=0.5, alpha=0.55, zorder=0)
        ax_a.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax_a.spines[side].set_visible(False)
        ax_a.tick_params(axis="y", length=0)

        c = data["concentration"]
        ax_a.set_title(
            f"(a)  {data['issuers']} distinct issuers named by "
            f"{data['declared_edges']} declarations",
            loc="left", fontsize=8.0, fontweight="bold", pad=20)
        if c["hhi"] is not None:
            # Above the axes, not inside them. Inside, this box sat on top of the "all
            # other issuers" bar and hid the largest segment in the figure behind an
            # opaque white rectangle -- the one defect a reader could not have detected,
            # because an occluded bar looks exactly like a short one.
            ax_a.text(
                0.0, 1.015,
                f"HHI {c['hhi']:.3f}   ·   effective issuers "
                f"{c['effective_issuers']:.1f}   ·   "
                f"top 1 {c['top1_share'] * 100:.0f}%   ·   "
                f"top 3 {c['top3_share'] * 100:.0f}%   ·   "
                f"top 5 {c['top5_share'] * 100:.0f}%",
                transform=ax_a.transAxes, ha="left", va="bottom",
                fontsize=6.8, color=INK_MUTED,
            )

        # ---- (b) who operates them ----------------------------------------------------
        rel = data["relation"]
        total = rel["total"] or 1
        segments = [
            ("same operator", rel["same_operator"], FILL_LIGHT, None),
            ("cross operator", rel["cross_operator"], ACCENT, None),
            ("apex unresolved", rel["unknown_operator"], FILL_MID, "///"),
        ]
        left = 0.0
        for label, count, colour, hatch in segments:
            width = count / total * 100.0
            if width <= 0:
                continue
            ax_b.barh(0.95, width, left=left, height=0.40, color=colour, hatch=hatch,
                      edgecolor=SURFACE, linewidth=1.6, label=f"{label}  ({count})", zorder=3)
            if width >= 9.0:
                ax_b.text(left + width / 2, 0.95, f"{width:.0f}%", ha="center", va="center",
                          fontsize=7.0, color=SURFACE if colour == ACCENT else INK,
                          fontweight="bold", zorder=4)
            left += width

        # The same quantity as an interval, directly beneath the segment it belongs to, on
        # the same axis. R10.4's cluster-robust interval is the published one; the naive
        # interval is drawn behind it because the gap between them is the size of the
        # mistake this study would have made by treating endpoints as independent.
        est = data["cross_operator_rate"]
        y_ci = 0.42
        ax_b.plot([est["naive_ci_lo"] * 100, est["naive_ci_hi"] * 100], [y_ci, y_ci],
                  color=RULE, linewidth=5.0, solid_capstyle="butt", zorder=2,
                  label="naive 95% CI (endpoints independent)")
        ax_b.plot([est["ci_lo"] * 100, est["ci_hi"] * 100], [y_ci, y_ci],
                  color=INK, linewidth=1.8, solid_capstyle="butt", zorder=3,
                  label=f"cluster-robust 95% CI (m={est['m']} apexes)")
        for bound in ("ci_lo", "ci_hi"):
            ax_b.plot([est[bound] * 100] * 2, [y_ci - 0.085, y_ci + 0.085],
                      color=INK, linewidth=1.8, solid_capstyle="butt", zorder=3)
        ax_b.plot([est["p_hat"] * 100], [y_ci], marker="o", markersize=5.5,
                  color=ACCENT, markeredgecolor=SURFACE, markeredgewidth=1.0, zorder=4)
        ax_b.text(est["p_hat"] * 100, y_ci - 0.15,
                  f"cross-operator  {est['p_hat'] * 100:.1f}%  "
                  f"[{est['ci_lo'] * 100:.1f}, {est['ci_hi'] * 100:.1f}]",
                  ha="center", va="top", fontsize=6.8, color=INK)

        ax_b.set_ylim(0.05, 1.30)
        ax_b.set_xlim(0, 100)
        ax_b.set_yticks([])
        ax_b.set_xlabel("share of declared edges (%)")
        ax_b.grid(axis="x", color=RULE, linewidth=0.5, alpha=0.55, zorder=0)
        ax_b.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax_b.spines[side].set_visible(False)
        ax_b.set_title("(b)  does the issuer belong to the resource's operator?",
                       loc="left", fontsize=8.0, fontweight="bold", pad=20)
        ax_b.legend(loc="upper left", bbox_to_anchor=(0.0, -0.26), frameon=False,
                    ncol=2, handlelength=1.8, columnspacing=1.2, borderaxespad=0)

        return _save(fig, out_dir, "fig2-delegation", formats)


# ---------------------------------------------------------------------------
# The synthetic fixture
# ---------------------------------------------------------------------------

def synthetic_population(n_apexes: int = 60) -> list[EndpointReport]:
    """A fixture, not a measurement, and the output file says so in a field of its own.

    The shape -- a few issuers carrying most of the population, a long tail of self-hosted
    ones -- is a guess at what the ecosystem looks like, made before seeing it, and it
    exists to exercise the renderers rather than to predict anything. If the real
    distribution turns out flat, Figure 2 will simply be a flat figure.

    On the host names. The shared issuers use `example.com` and `example.net`, reserved by
    RFC 2606. The tenants cannot: RFC 2606 reserves exactly three registrable names, so a
    population built from them has **one apex**, `example.org`, and a fixture with one
    cluster exercises none of the clustering this figure exists to show -- the first draft
    silently reported a 100% cross-operator rate for that reason. RFC 6761's reserved TLDs
    (`.test`, `.invalid`, `.example`) are not in the public suffix list, so `apex_domain()`
    returns `None` for them and every edge lands in "apex unresolved" instead. Hence
    `tenantNN-example.org`: distinct registrable names, never resolved, never contacted by
    anything in this repository, and the only strings here that are not RFC-reserved.

    `apex_domain` is computed by the same function the analysis uses rather than assigned,
    so the fixture cannot disagree with the code about what an apex is -- which is exactly
    how the first draft went wrong.
    """
    shared = [
        "https://idp-a.example.com",
        "https://idp-b.example.com",
        "https://idp-c.example.net",
        "https://idp-d.example.net",
    ]
    reports: list[EndpointReport] = []
    probed_at = datetime(2026, 7, 29, tzinfo=UTC)

    for i in range(n_apexes):
        apex = f"tenant{i:02d}-example.org"
        url = f"https://{apex}/mcp"
        # A deterministic, deliberately skewed assignment: the first issuer takes a third
        # of the population, the next two take a fifth each, the rest self-host.
        if i % 3 == 0:
            issuers = [shared[0]]
        elif i % 5 == 0:
            issuers = [shared[1], shared[2]]
        elif i % 7 == 0:
            issuers = [shared[3]]
        else:
            issuers = [f"https://auth.{apex}"]

        reports.append(EndpointReport(
            endpoint=Endpoint(endpoint_id=endpoint_id(url), url=url,
                              apex_domain=apex_domain(url),
                              kind=EndpointKind.MCP_REMOTE, source="synthetic-fixture"),
            modality=Modality.OAUTH_METADATA,
            reachable=True,
            http_status=401,
            evidence={
                "declared_resource": url,
                "authorization_servers": issuers,
                "as_documents": {
                    issuer: {
                        "issuer": issuer,
                        # Only some issuers publish the §7.6 cross-check list, and only some
                        # of those list this resource. Both are the empirical questions.
                        **({"protected_resources": [url]} if i % 4 == 0 else {}),
                        **({"protected_resources": []} if i % 4 == 1 else {}),
                    }
                    for issuer in issuers
                },
            },
            probed_at=probed_at,
            run_id="synthetic",
        ))
    return reports


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_all(
    reports: list[EndpointReport],
    out_dir: Path,
    formats: tuple[str, ...] = ("pdf", "png"),
    *, synthetic: bool = False,
) -> dict:
    """Render both figures and write the numbers beside them."""
    out_dir.mkdir(parents=True, exist_ok=True)
    data = figure2_data(reports)
    written = figure1_discovery_chain(out_dir, formats)
    written += figure2_delegation(data, out_dir, formats)

    payload = {
        "figure2": data,
        "endpoints": len(reports),
        # Loud, in the file itself. A synthetic figure that escapes into a draft and is
        # read as a measurement is the single worst thing this module could cause.
        "source": "SYNTHETIC FIXTURE -- NOT A MEASUREMENT" if synthetic else "measurement",
    }
    (out_dir / "figure-data.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"written": [str(p) for p in written], "data": payload}
