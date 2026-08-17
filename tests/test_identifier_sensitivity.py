"""What the identifier comparison policy forgives, pinned one transformation at a time.

Section 4.4 reports the two identifier checks under three readings of *identical*, because
RFC 8414 Section 4 asks for equality code point by code point while the instrument first
applies the equivalences RFC 3986 Section 6.2 declares. The census answer is that the policy
buys under three points and does not move the ordering, and that the whole of the gap comes
from default ports and the empty path rather than from case.

That last part is a claim about which transformation does the work, and a rate over a whole
corpus cannot support it. These fixtures fire one equivalence each.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentidprobe.analysis import identifier_comparison_sensitivity
from agentidprobe.models import Endpoint, EndpointReport, Modality

READINGS = ("strict", "published", "scheme_host_case")


def _report(declared: str, expected: str, eid: str = "e1") -> EndpointReport:
    """One report carrying a single resource-identifier pair as its evidence."""
    return EndpointReport(
        endpoint=Endpoint(
            endpoint_id=eid, url=declared, kind="mcp_remote", source="test",
            apex_domain="example.com",
            first_seen=datetime(2026, 7, 30, tzinfo=UTC),
            last_seen=datetime(2026, 7, 30, tzinfo=UTC),
        ),
        modality=Modality.OAUTH_METADATA,
        reachable=True,
        http_status=401,
        checks=[],
        evidence={"declared_resource": declared, "expected_resource": expected},
        probed_at=datetime(2026, 7, 30, tzinfo=UTC),
        run_id="test",
    )


def _matches(declared: str, expected: str) -> dict[str, int]:
    result = identifier_comparison_sensitivity([_report(declared, expected)])
    return {name: result[name]["resource_match"] for name in READINGS}


def test_every_reading_is_reported():
    result = identifier_comparison_sensitivity([_report("https://a.example/mcp",
                                                        "https://a.example/mcp")])
    assert set(result) == set(READINGS)
    for row in result.values():
        assert row["resource_total"] == 1


def test_identical_strings_match_under_every_reading():
    assert _matches("https://a.example/mcp", "https://a.example/mcp") == dict.fromkeys(READINGS, 1)


def test_a_default_port_is_forgiven_only_by_the_published_rule():
    """The first of the two transformations the census gap is made of."""
    got = _matches("https://a.example:443/mcp", "https://a.example/mcp")
    assert got == {"strict": 0, "published": 1, "scheme_host_case": 0}


def test_an_empty_path_against_a_bare_slash_is_forgiven_only_by_the_published_rule():
    """The second. RFC 3986 6.2.3 lists these two among four URIs it declares equivalent."""
    got = _matches("https://a.example/", "https://a.example")
    assert got == {"strict": 0, "published": 1, "scheme_host_case": 0}


def test_host_case_is_forgiven_by_both_normalising_readings():
    """RFC 3986 6.2.2.1 makes this one mandatory, which is why the third reading keeps it.

    No pair in the census differs by case alone, so this transformation contributes nothing
    to the measured gap. The fixture exists to show the third reading is not simply strict
    under another name.
    """
    got = _matches("https://A.EXAMPLE/mcp", "https://a.example/mcp")
    assert got == {"strict": 0, "published": 1, "scheme_host_case": 1}


def test_path_case_is_forgiven_by_no_reading():
    """`/MCP` and `/mcp` really are different resources and the policy says so."""
    assert _matches("https://a.example/MCP", "https://a.example/mcp") == dict.fromkeys(READINGS, 0)


def test_a_different_host_is_forgiven_by_no_reading():
    assert _matches("https://b.example/mcp", "https://a.example/mcp") == dict.fromkeys(READINGS, 0)


def test_issuer_pairs_are_counted_from_the_authorization_server_documents():
    """The issuer side reads a different evidence field, so it needs its own fixture."""
    report = _report("https://a.example/mcp", "https://a.example/mcp")
    report.evidence["as_documents"] = {
        "https://idp.example": {"issuer": "https://idp.example"},
        "https://other.example": {"issuer": "https://other.example:443"},
        "https://third.example": {"issuer": "https://elsewhere.example"},
    }
    result = identifier_comparison_sensitivity([report])
    assert result["strict"]["issuer_total"] == 3
    assert result["strict"]["issuer_match"] == 1
    assert result["published"]["issuer_match"] == 2       # the default port is forgiven
    assert result["scheme_host_case"]["issuer_match"] == 1


def test_a_pair_missing_either_side_is_not_counted():
    """A rate over pairs that do not exist would be an artefact of the denominator."""
    report = _report("https://a.example/mcp", "https://a.example/mcp")
    report.evidence["expected_resource"] = None
    result = identifier_comparison_sensitivity([report])
    assert result["published"]["resource_total"] == 0
    assert result["published"]["resource_rate"] is None


def test_the_published_reading_is_never_stricter_than_byte_equality():
    """The invariant behind reporting a single gap: normalising can only add matches.

    If this ever fails the gap in Section 4.4 could be negative, and a policy that turned
    matching pairs into mismatches would be a defect rather than a forgiveness.
    """
    pairs = [
        ("https://a.example:443/mcp", "https://a.example/mcp"),
        ("https://a.example/", "https://a.example"),
        ("https://A.example/mcp", "https://a.example/mcp"),
        ("https://a.example/MCP", "https://a.example/mcp"),
        ("https://a.example/mcp?x=1", "https://a.example/mcp?x=1"),
        ("https://b.example/mcp", "https://a.example/mcp"),
    ]
    reports = [_report(d, e, eid=f"e{i}") for i, (d, e) in enumerate(pairs)]
    result = identifier_comparison_sensitivity(reports)
    assert result["published"]["resource_match"] >= result["strict"]["resource_match"]
    assert result["published"]["resource_match"] >= result["scheme_host_case"]["resource_match"]
    assert result["scheme_host_case"]["resource_match"] >= result["strict"]["resource_match"]


@pytest.mark.parametrize("reading", READINGS)
def test_rates_agree_with_their_own_counts(reading):
    pairs = [("https://a.example/mcp", "https://a.example/mcp"),
             ("https://b.example/mcp", "https://a.example/mcp")]
    reports = [_report(d, e, eid=f"e{i}") for i, (d, e) in enumerate(pairs)]
    row = identifier_comparison_sensitivity(reports)[reading]
    assert row["resource_rate"] == pytest.approx(row["resource_match"] / row["resource_total"])
