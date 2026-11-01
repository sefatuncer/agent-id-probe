"""Table 10 at the issuer unit (1 November 2026).

The bounded rates are issuer-level, and until this date the unobserved share bounding them was
an endpoint share. These tests pin the two things the change has to get right: which never-asked
issuer counts as missing for a reason that is not ours, and that a row's b is an issuer share.
"""

import json
import math

from agentidprobe.analysis import issuer_manski_rows, unasked_issuer_reasons


def _artifact(url: str, kind: str) -> str:
    return json.dumps({"url": url, "error_kind": kind})


def test_robots_refusal_is_ours_and_an_access_block_is_not():
    well_known = "/.well-known/oauth-authorization-server"
    lines = [
        _artifact("https://idp.example.org" + well_known, "robots_disallowed"),
        _artifact("https://waf.example.net" + well_known, "blocked"),
        _artifact("https://waf.example.net/mcp", "none"),
        "",
    ]
    reasons = unasked_issuer_reasons(
        lines,
        ["https://idp.example.org", "https://waf.example.net/tenant", "https://quiet.example.com"])
    assert reasons == {
        "https://idp.example.org": "ours",
        "https://waf.example.net/tenant": "not ours",
        # Nothing in the fetch log: the reason is not invented.
        "https://quiet.example.com": "unknown",
    }


def test_our_refusal_wins_when_a_host_shows_both():
    """If robots.txt stopped the metadata request, a block met elsewhere on the host is not why
    the issuer went unasked."""
    lines = [
        {"url": "https://both.example.org/robots.txt", "error_kind": "blocked"},
        {"url": "https://both.example.org/.well-known/openid-configuration",
         "error_kind": "robots_disallowed"},
    ]
    assert unasked_issuer_reasons(lines, ["https://both.example.org"]) == {
        "https://both.example.org": "ours"}


def test_rows_count_issuers_and_widen_monotonically():
    rows = issuer_manski_rows(
        p_hat=0.06, n=2000,
        unseen_endpoints={"operator": 900, "policy": 2200, "frame": 4000},
        known_unrated={"operator": 2, "policy": 57, "frame": 57},
        issuers_per_endpoint=0.3)
    one = rows["operator"]["one_per_endpoint"]
    assert one["unobserved"] == 902
    assert math.isclose(one["b"], 902 / 2902)
    assert math.isclose(one["hi"] - one["lo"], one["b"])
    observed = rows["operator"]["observed_rate"]
    assert observed["unobserved"] == round(0.3 * 900) + 2
    # The stated upper assumption is never narrower than the observed-rate one, and every
    # wider definition of the unobserved population gives a wider row.
    for name in ("operator", "policy", "frame"):
        assert rows[name]["one_per_endpoint"]["b"] >= rows[name]["observed_rate"]["b"]
    for assumption in ("observed_rate", "one_per_endpoint"):
        widths = [rows[name][assumption]["b"] for name in ("operator", "policy", "frame")]
        assert widths == sorted(widths)


def test_nothing_unseen_collapses_to_the_estimate():
    rows = issuer_manski_rows(
        p_hat=0.25, n=400,
        unseen_endpoints={"operator": 0, "policy": 0, "frame": 0},
        known_unrated={"operator": 0, "policy": 0, "frame": 0},
        issuers_per_endpoint=0.3)
    for row in rows.values():
        for assumption in ("observed_rate", "one_per_endpoint"):
            assert row[assumption]["b"] == 0.0
            assert math.isclose(row[assumption]["lo"], 0.25)
            assert math.isclose(row[assumption]["hi"], 0.25)
