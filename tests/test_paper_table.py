"""Table 1 of the paper cannot drift away from the instrument it describes.

The paper carries no supplementary material, so Table 1 — one row per check, its
specification anchor, the heaviest verdict that anchor permits, and the party the anchor
binds — is the entire tautology defence a reader gets to see. It is generated from the code
by `scripts/gen_catalogue.py --table1` rather than written, and these tests hold the two
columns a human does assert against what the instrument actually emits.

The reason is not hypothetical. The hand-maintained version of this exact table drifted
twice: `README.md` listed C06 and C10 for days after both were deleted from `CheckId`, and
decision rule R1's consequence list named the deleted C10 while omitting C16, C17 and C18 —
the three checks the headline candidates rest on. Both survived a human reading the prose,
and both were found only when someone compared the text against the code. A table in a
published paper gets no such second reading.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from agentidprobe.models import (
    CLIENT_BOUND_BUT_FAILABLE,
    DESCRIPTIVE_ONLY,
    SPEC_ANCHOR_SUMMARY,
    BoundParty,
    CheckId,
    NormativeStrength,
)

ROOT = Path(__file__).resolve().parents[1]


def _load_catalogue_module() -> Any:
    path = ROOT / "scripts" / "gen_catalogue.py"
    spec = importlib.util.spec_from_file_location("agentidprobe_gen_catalogue_table", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GEN = _load_catalogue_module()
EMISSIONS = [e for path in GEN.SOURCES for e in GEN._emissions(path)]


def _sites(check: CheckId) -> list:
    return [e for e in EMISSIONS if e.check == check.name]


# ---------------------------------------------------------------------------
# The row set is the instrument's, not an author's
# ---------------------------------------------------------------------------

def test_every_live_check_has_exactly_one_row_and_no_dead_one_has_any():
    """The C06/C10 defect, in the column that would reach a reviewer."""
    assert set(SPEC_ANCHOR_SUMMARY) == set(CheckId)


def test_the_rendered_table_has_one_row_per_check():
    rendered = GEN.render_paper_table1()
    body = [ln for ln in rendered.strip().split("\n")[2:] if ln.strip()]
    assert len(body) == len(list(CheckId))
    for check, line in zip(CheckId, body, strict=True):
        assert line.startswith(f"| {check.value} |"), line


def test_the_table_is_deterministic():
    assert GEN.render_paper_table1() == GEN.render_paper_table1()


# ---------------------------------------------------------------------------
# The clause label must name a clause the code really cites
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("check", list(CheckId), ids=lambda c: c.value)
def test_the_clause_label_matches_an_anchor_the_code_emits(check: CheckId):
    """A short label is still a claim about which sentence authorises the check.

    Table 1 abbreviates, because the verbatim sentences are quoted in §2 where each is
    argued and repeating them would print the same text in the manuscript twice. What the
    abbreviation may not do is name a specification the instrument never cites, so every
    document identifier in the label — `RFC 9728`, `A2A`, `MCP` — has to appear in some
    `spec_ref` or `spec_url` recorded at one of that check's emission sites.
    """
    label, _ = SPEC_ANCHOR_SUMMARY[check]
    sites = _sites(check)
    assert sites, f"{check.value} has no emission site at all"

    haystack = " ".join(f"{e.spec_ref} {e.spec_url}" for e in sites).lower()
    tokens = []
    for part in label.replace(";", " ").split():
        if part.upper().startswith("RFC"):
            continue
        if part.isdigit() and len(part) == 4:          # the number after "RFC"
            tokens.append(f"rfc{part}")
            tokens.append(f"rfc {part}")
        elif part in ("A2A", "MCP"):
            tokens.append(part.lower())
    assert tokens, f"{check.value}: label {label!r} names no document"
    for token in tokens:
        assert token.replace(" ", "") in haystack.replace(" ", ""), (
            f"{check.value}: label cites {token!r} but no emission site does. "
            f"Sites cite: {sorted({e.spec_ref for e in sites})}"
        )


# ---------------------------------------------------------------------------
# R1, in the column that states whose obligation it is
# ---------------------------------------------------------------------------

def test_a_client_bound_anchor_cannot_convict_an_operator():
    """The rule C16 was made descriptive-only to satisfy, applied to every check.

    A sentence binding the *client* states an obligation a passive probe cannot observe.
    Reporting its absence as the server's failure is scoring one party for another's
    obligation — the objection that `models.DESCRIPTIVE_ONLY` records for C16 in as many
    words. Any check anchored to a client-binding sentence must therefore be
    descriptive-only, and the one that is not is named explicitly so it cannot hide.
    """
    offenders = {
        check for check, (_, party) in SPEC_ANCHOR_SUMMARY.items()
        if party is BoundParty.CLIENT and check not in DESCRIPTIVE_ONLY
    }
    assert offenders == set(CLIENT_BOUND_BUT_FAILABLE), (
        "a check anchored to a client-binding sentence became failable without being "
        f"recorded: {sorted(c.value for c in offenders - CLIENT_BOUND_BUT_FAILABLE)}"
    )


def test_no_client_bound_check_is_failable_at_all():
    """The guard, after the case it was opened for was closed.

    `CLIENT_BOUND_BUT_FAILABLE` held C14 for one day: it reported a failure against the
    authorization server while citing "MCP clients MUST refuse to proceed". Reading the
    primary text settled it — RFC 8414 §2 marks the element OPTIONAL, RFC 9700 §2.1.1 sets
    publishing it at RECOMMENDED and permits an unobservable alternative — and C14 became
    descriptive.

    The set stays in the code, empty, because this was the *second* time: MCP's Resource
    Indicators clause was rejected as unmeasurable for the identical reason and C07 was
    rewritten for it, and C14 was the same shape unnoticed. An empty assertion here makes
    the third instance fail a build rather than reach a reviewer.
    """
    assert CLIENT_BOUND_BUT_FAILABLE == frozenset()


def test_the_heaviest_outcome_column_is_derived_not_asserted():
    """R1 applied, not restated.

    If this column were typed by hand it would be a claim about the instrument rather than
    a description of it — and the claim is exactly what a sceptical reviewer opens the
    table to test.
    """
    for check in CheckId:
        strength = GEN._strongest_strength(_sites(check))
        cell = GEN._heaviest_outcome(check, strength)
        if check in DESCRIPTIVE_ONLY:
            assert cell == "descriptive only"
        elif strength == NormativeStrength.MUST.value:
            assert cell == "`FAIL_*`"
        elif strength == NormativeStrength.SHOULD.value:
            assert cell == "`UNSPECIFIED`"
        else:
            assert cell == "`NOT_APPLICABLE`"


def test_every_failable_check_is_anchored_to_a_must():
    """The two derivations of "can this check convict" must agree.

    `must_level_failable_checks()` reads the reachable outcomes at each call site; the
    heaviest-outcome column reads the strengths. They are independent walks over the same
    tree, so a disagreement means one of them is wrong — and both feed published claims,
    one the conformance pack and one Table 1.
    """
    failable = set(GEN.must_level_failable_checks())
    for check in failable:
        assert GEN._strongest_strength(_sites(check)) == NormativeStrength.MUST.value
        assert check not in DESCRIPTIVE_ONLY
    for check in DESCRIPTIVE_ONLY:
        assert check not in failable
