"""The thesis is about the crossing population, so it has to be measured on it.

The paper argues the delegation surface is narrow and, where it is entered, unevidenced.
Both halves were reported over populations the sentence is not about: the topology rate over
declarations, the evidence rates over every issuer named. Three referees independently asked
for the intersection. On the census it turns out to matter in both directions -- C18 over the
crossing issuers is 0/202 rather than 12/2050, and concentration over crossing edges at the
registrable-domain unit is HHI 0.131 with a top-10 share of 74.4%, against 0.005 and 18.5%
over all edges. The published sentence "dispersed rather than concentrated" is true of the
population it was computed on and false of the population it was written about.

These tests fix the parts a future change could quietly break: which edges count as crossing,
which unit the concentration is taken at, and that an endpoint is counted once however many
issuers it declares.
"""

from datetime import UTC, datetime

from agentidprobe.analysis import exposure_analysis
from agentidprobe.models import (
    Endpoint,
    EndpointKind,
    EndpointReport,
    Modality,
)


def _report(endpoint_id: str, apex: str, issuers: list[str]) -> EndpointReport:
    return EndpointReport(
        endpoint=Endpoint(endpoint_id=endpoint_id, url=f"https://{apex}/mcp",
                          kind=EndpointKind.MCP_REMOTE, source="t", apex_domain=apex),
        modality=Modality.OAUTH_METADATA,
        reachable=True,
        robots_allowed=True,
        checks=[],
        evidence={"authorization_servers": issuers, "as_documents": {}},
        probed_at=datetime.now(UTC),
        run_id="r1",
    )


def test_an_issuer_inside_the_resource_domain_is_not_crossing():
    reports = [_report("a", "example.org", ["https://example.org/auth"])]
    result = exposure_analysis(reports)
    assert result["declaring_endpoints"] == 1
    assert result["exposed_endpoints"] == 0
    assert result["crossing_edges"] == 0


def test_an_issuer_outside_the_resource_domain_is_crossing():
    reports = [_report("a", "example.org", ["https://issuer.example.net/auth"])]
    result = exposure_analysis(reports)
    assert result["exposed_endpoints"] == 1
    assert result["exposed_apexes"] == 1
    assert result["crossing_edges"] == 1
    assert result["crossing_issuers"] == 1


def test_an_endpoint_is_exposed_once_however_many_issuers_it_declares():
    """The endpoint unit answers "how many deployments are exposed", not "how many edges"."""
    reports = [_report("a", "example.org", [
        "https://example.org/auth",          # inside
        "https://one.example.net/auth",      # crossing
        "https://two.example.net/auth",      # crossing
    ])]
    result = exposure_analysis(reports)
    assert result["exposed_endpoints"] == 1
    assert result["crossing_edges"] == 2


def test_endpoints_that_declare_nothing_are_outside_the_denominator():
    reports = [
        _report("a", "example.org", ["https://issuer.example.net/auth"]),
        _report("b", "other.org", []),
    ]
    result = exposure_analysis(reports)
    assert result["declaring_endpoints"] == 1
    assert result["exposed_endpoints"] == 1


def test_concentration_is_reported_at_three_issuer_units():
    """One registrable domain appeared four times in the published top ten, so dispersion at
    the URL unit is partly an artefact of identifier granularity. Three units, always."""
    reports = [
        _report("a", "one.org", ["https://a.issuer.example.net/auth"]),
        _report("b", "two.org", ["https://b.issuer.example.net/auth"]),
        _report("c", "three.org", ["https://c.issuer.example.net/auth"]),
    ]
    result = exposure_analysis(reports)
    by_unit = result["concentration_crossing"]
    assert set(by_unit) == {"url", "host", "registrable_domain"}
    # Three distinct URLs and hosts, but one registrable domain: the unit decides the answer.
    assert by_unit["url"]["issuers"] == 3
    assert by_unit["host"]["issuers"] == 3
    assert by_unit["registrable_domain"]["issuers"] == 1
    assert by_unit["registrable_domain"]["hhi"] == 1.0
    assert by_unit["url"]["hhi"] < by_unit["registrable_domain"]["hhi"]


def test_crossing_concentration_excludes_self_edges():
    """Self-edges cannot answer the question the related-work comparison asks, which is about
    reliance on infrastructure the resource does not operate."""
    reports = [
        _report("a", "one.org", ["https://one.org/auth"]),
        _report("b", "two.org", ["https://two.org/auth"]),
        _report("c", "three.org", ["https://shared.example.net/auth"]),
    ]
    result = exposure_analysis(reports)
    assert result["concentration_by_unit"]["url"]["edges"] == 3
    assert result["concentration_crossing"]["url"]["edges"] == 1


def test_rates_carry_the_cluster_count_and_design_effect():
    """Decision rule R10.4: no rate is published without m, and Table 5 omitted deff and
    n_eff until three referees asked for them."""
    reports = [_report("a", "example.org", ["https://issuer.example.net/auth"])]
    result = exposure_analysis(reports)
    for key in ("c16_all", "c18_all", "c16_crossing", "c18_crossing"):
        record = result[key]
        assert {"k", "n", "m", "p_hat", "ci_lo", "ci_hi", "deff", "n_eff"} <= set(record)
