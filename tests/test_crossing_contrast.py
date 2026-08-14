"""The crossing population is compared to the rest, rather than assumed to differ.

Section 6.5 called the split between the two populations "the sharpest way to state the
result" and printed it without a test. The bound it did carry is a bound on the *level* of
an observed zero, which is a different quantity from the *contrast* the sentence claimed.

The implementation is checked against two published 2x2 tables before it is trusted on the
study's own, because an exact test written from scratch that is wrong is worse than no test
at all: it would put a number behind the same unsupported sentence.
"""
from __future__ import annotations

import pytest

from agentidprobe.analysis import fisher_exact_2x2


def test_matches_fishers_tea_tasting_example():
    """The lady tasting tea: 3 of 4 correct each way. Two-sided p = 0.4857."""
    result = fisher_exact_2x2(3, 1, 1, 3)
    assert result["p_value"] == pytest.approx(0.4857, abs=5e-4)


def test_matches_a_strongly_associated_table():
    """[[1, 9], [11, 3]], where both tails are needed.

    Two-sided p = 0.0027595, which is P(0) + P(1) + P(9) + P(10) over the hypergeometric
    with margins (10, 14; 12, 12): (91 + 3640 + 3640 + 91) / C(24, 12). A one-sided
    implementation returns half of it, so this table is here to catch that.
    """
    result = fisher_exact_2x2(1, 9, 11, 3)
    assert result["p_value"] == pytest.approx(0.0027595, abs=5e-7)


def test_a_table_with_identical_rates_is_maximally_unsurprising():
    result = fisher_exact_2x2(10, 90, 10, 90)
    assert result["p_value"] == pytest.approx(1.0)


def test_the_test_is_symmetric_under_row_exchange():
    """Swapping the rows names a different population, not a different association."""
    a = fisher_exact_2x2(0, 202, 12, 1767)
    b = fisher_exact_2x2(12, 1767, 0, 202)
    assert a["p_value"] == pytest.approx(b["p_value"])


def test_the_studys_own_table_does_not_support_a_contrast():
    """0 of 202 crossing against 12 of 1,799 elsewhere.

    This is the shape of the manuscript's own data. Twelve positives spread over about two
    thousand issuers put roughly one in eight of them in a subset of two hundred by chance,
    so a subset holding none of them is close to what independence predicts. The zero is
    real and its level is bounded elsewhere; what fails is the claim that the two
    populations differ.
    """
    result = fisher_exact_2x2(0, 202, 12, 1787)
    assert result["rate_row1"] == 0.0
    assert result["rate_row2"] == pytest.approx(12 / 1799, abs=1e-4)
    assert result["p_value"] > 0.30, (
        "if this ever drops below a conventional threshold the manuscript may state a "
        "contrast; until then Section 6.5 reports a level"
    )


def test_an_empty_margin_returns_no_p_value_rather_than_a_wrong_one():
    """No issuer publishes anywhere: there is nothing to contrast, and no zero to divide."""
    result = fisher_exact_2x2(0, 202, 0, 1787)
    assert result["p_value"] is None
    assert "undefined" in result["method"]


def test_the_two_sided_tail_keeps_the_mirror_table():
    """Floating point can drop an equally extreme table and halve the p-value.

    A symmetric table makes the failure visible: every arrangement is its own mirror, so a
    tail that loses them cannot reach 1.0.
    """
    assert fisher_exact_2x2(5, 5, 5, 5)["p_value"] == pytest.approx(1.0)
    assert fisher_exact_2x2(2, 2, 2, 2)["p_value"] == pytest.approx(1.0)
