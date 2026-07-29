"""Decision rule R8 leg 1: the conformance fixture pack, and the guard that enforces it.

R8 names a directory. Until this module existed, that directory did not: the fixtures were
inline dictionaries spread through `test_checks_oauth.py` and `test_checks_signed.py`, and a
frozen rule pointed at a path nobody could open. That is the exact class of defect this
project has already been burned by three times -- a document and the thing it describes
drifting apart while both look authoritative -- so the fix is not to soften the rule but to
build what it names.

R8 leg 1, verbatim (docs/decision-rules.md):

    "Conformance fixture suite. For every MUST-level check there is at least one
     known-conforming and one known-violating fixture derived from the specification text
     (tests/fixtures/). If the instrument cannot classify these correctly, no data is
     collected. Edge cases (trailing slash, case, same host different path) stand as
     separate fixtures."

Three design decisions are worth stating, because each rules out a cheaper alternative that
would have quietly failed to do the job.

**The fixtures are data, not code.** A reviewer checking whether this instrument measures
what the RFC says must be able to open one file and see the document served, the URL it was
served from, the sentence it is judged against, and the verdict expected -- without reading
Python, and without trusting that a helper function three modules away does not smuggle in
an assumption. Each file carries its own quotation, its own `verification` status copied
from docs/spec-mapping.md, and its own prose statement of what defect it prevents. That also
makes the pack auditable against the RFC by someone who does not run it at all.

**There is no manifest.** The obvious index file -- one JSON listing every fixture and the
check it covers -- would be a second copy of a fact the directory already states, and every
second copy in this repository has drifted from its original: the README listed two deleted
checks, a retracted arXiv identifier survived two revisions, and spec-mapping.md asserted an
RFC 8414 field that does not exist. Fixtures are discovered by globbing, so a file that
exists is in the pack and a file that does not cannot be listed. The one thing a manifest
would genuinely provide -- "which checks must be covered" -- is derived from the check
modules' own syntax tree instead (`must_level_failable_checks`), which is a source that
cannot go stale relative to the code because it *is* the code.

**The coverage test is the point.** Loading fixtures and asserting outcomes only proves the
fixtures that exist are classified correctly; it says nothing about the check nobody wrote a
fixture for, which is precisely the case R8 exists to forbid. `test_must_level_check_has_a_*`
below fails when a MUST-level check lacks either case, so adding a failing check to the
instrument without adding its two fixtures breaks the build. That is what turns R8 leg 1
from a description into an enforced rule.

The suite never touches the network: every document is served by respx and pyproject sets a
30-second per-test timeout so an accidental live call fails fast instead of hanging.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
import respx

from agentidprobe.checks_oauth import probe_oauth
from agentidprobe.checks_signed import probe_signed
from agentidprobe.config import MeasurementConfig, RatePolicy
from agentidprobe.fetcher import Fetcher, FetchResult
from agentidprobe.models import CheckId, CheckResult, Outcome, TlsInfo

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

FAST = MeasurementConfig(
    rate=RatePolicy(per_host_requests_per_second=1000.0, max_retries=0, backoff_base_s=0.0)
)

SCHEMA = "agent-id-probe/conformance-fixture/1"

# Which case a fixture may claim, and the verdicts that claim commits it to. A fixture
# labelled "violating" whose expected outcome is PASS is not a fixture, it is a typo with
# authority, and it would sit in the pack looking like evidence.
CASE_OUTCOMES: dict[str, frozenset[Outcome]] = {
    "conforming": frozenset({Outcome.PASS}),
    "violating": frozenset({Outcome.FAIL_UNIMPLEMENTED, Outcome.FAIL_MISIMPLEMENTED}),
    # R6. Not a third kind of conformance: the class exists because the instrument cannot
    # decide, and R8 wants that recorded rather than rounded to whichever side is convenient.
    "undecidable": frozenset({Outcome.UNSPECIFIED}),
}

# The edge cases R8's last sentence names. Each must stand as its own fixture, identified by
# the relation the R9.3 taxonomy assigns it, so that "we tested the near-misses" is a fact
# about the directory rather than a claim in prose.
REQUIRED_EDGE_RELATIONS: tuple[str, ...] = (
    "trailing_slash_only",
    "case_path_only",
    "same_host_different_path",
)


def _load_catalogue_module() -> Any:
    """Import `scripts/gen_catalogue.py`, which already recovers every emission site.

    Imported by path rather than duplicated: the AST walk it performs has to cope with
    emissions inside `for cid in (...)` loops, with wrapper functions that reach the
    constructor one hop away, and with spec URLs bound to module constants. A second
    implementation here would be a second thing to keep right, and the two would disagree
    exactly when it mattered.
    """
    path = ROOT / "scripts" / "gen_catalogue.py"
    spec = importlib.util.spec_from_file_location("agentidprobe_gen_catalogue", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution because `@dataclass` resolves annotations through
    # `sys.modules[cls.__module__]`, and a module that is not there yet resolves to None.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MUST_FAILABLE: dict[CheckId, frozenset[Outcome]] = (
    _load_catalogue_module().must_level_failable_checks()
)


def _load_fixtures() -> list[tuple[str, dict]]:
    files = sorted(FIXTURE_DIR.glob("*.json"))
    assert files, f"decision rule R8 leg 1 names {FIXTURE_DIR}, which holds no fixtures"
    return [(path.stem, json.loads(path.read_text(encoding="utf-8"))) for path in files]


FIXTURES: list[tuple[str, dict]] = _load_fixtures()
FIXTURE_IDS: list[str] = [name for name, _ in FIXTURES]
FIXTURE_DATA: list[dict] = [fixture for _, fixture in FIXTURES]


# --- driving the instrument ---------------------------------------------------


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _response(spec: dict) -> httpx.Response:
    status = spec.get("status", 200)
    headers = spec.get("headers", {})
    if "json" in spec:
        return httpx.Response(status, json=spec["json"], headers=headers)
    if "text" in spec:
        return httpx.Response(status, text=spec["text"], headers=headers)
    return httpx.Response(status, headers=headers)


def _install_routes(router: respx.MockRouter, fixture: dict) -> None:
    """Serve the fixture's documents, and robots.txt for every origin it touches.

    robots.txt is answered 404 by default rather than listed in each fixture. It is
    instrument plumbing, not specification content: the fetcher reads it before any
    well-known path, so requiring every fixture to declare it would add a line of noise to
    thirty files to say the same thing. A fixture that is *about* robots states it
    explicitly under `robots`, which is the only case where the answer carries meaning.
    """
    origins = {_origin(fixture["endpoint"]["url"])}
    origins.update(_origin(doc["url"]) for doc in fixture.get("documents", []))
    declared_robots = fixture.get("robots", {})
    for origin in sorted(origins):
        body = declared_robots.get(origin)
        response = (
            httpx.Response(200, text=body) if body is not None else httpx.Response(404)
        )
        router.get(f"{origin}/robots.txt").mock(return_value=response)
    for document in fixture.get("documents", []):
        router.get(document["url"]).mock(return_value=_response(document))


async def _run(fixture: dict) -> tuple[list[CheckResult], Any]:
    endpoint = fixture["endpoint"]
    served = endpoint["response"]
    # `assert_all_called` is off deliberately. Several fixtures list a location the probe
    # will only reach if an earlier candidate fails -- MCP's root fallback is exactly that
    # shape -- so demanding every route be hit would forbid describing the alternatives a
    # conforming client is required to try.
    with respx.mock(assert_all_called=False) as router:
        _install_routes(router, fixture)
        async with Fetcher(FAST) as fetcher:
            if fixture["modality"] == "oauth_metadata":
                initial = FetchResult(
                    url=endpoint["url"],
                    ok=True,
                    status=served.get("status", 401),
                    headers=served.get("headers", {}),
                    tls=TlsInfo(**served["tls"]) if "tls" in served else None,
                )
                return await probe_oauth(fetcher, endpoint["url"], initial)

            body = json.dumps(served["json"]).encode() if "json" in served else b""
            fetched = FetchResult(
                url=endpoint["url"], ok=True, status=served.get("status", 200), body=body
            )
            return await probe_signed(fetcher, endpoint["url"], fetched)


def _outcome(checks: list[CheckResult], check: CheckId) -> Outcome:
    for result in checks:
        if result.check_id is check:
            return result.outcome
    raise AssertionError(f"{check.value} was never emitted for this fixture")


# --- the pack, exercised against the real check functions ---------------------


@pytest.mark.parametrize("fixture", FIXTURE_DATA, ids=FIXTURE_IDS)
async def test_instrument_classifies_the_fixture(fixture: dict) -> None:
    """R8's measurement: 100% accuracy on the pack, or no data is collected."""
    checks, evidence = await _run(fixture)

    for check_value, expected in fixture["expect"]["checks"].items():
        actual = _outcome(checks, CheckId(check_value))
        assert actual is Outcome(expected), (
            f"{fixture['id']}: {check_value} expected {expected}, got {actual.value}"
        )

    for field, expected in fixture["expect"].get("evidence", {}).items():
        actual_value = getattr(evidence, field)
        assert actual_value == expected, (
            f"{fixture['id']}: evidence.{field} expected {expected!r}, got {actual_value!r}"
        )


# --- the pack's own integrity -------------------------------------------------


@pytest.mark.parametrize("fixture", FIXTURE_DATA, ids=FIXTURE_IDS)
def test_fixture_is_well_formed(fixture: dict) -> None:
    assert fixture["schema"] == SCHEMA
    assert fixture["modality"] in ("oauth_metadata", "signed_document")
    assert fixture["rationale"].strip(), "a fixture with no stated purpose cannot be reviewed"
    assert fixture["exercises"], "a fixture must say which check it is evidence about"

    # `CheckId(...)` and `Outcome(...)` raise on an unknown member, which is the whole
    # assertion: a fixture may only name checks and verdicts the instrument declares, so a
    # renamed check leaves a broken fixture rather than a silently ignored one.
    for check_value, case in fixture["exercises"].items():
        CheckId(check_value)
        assert case in CASE_OUTCOMES, f"unknown case {case!r}"

    for check_value, outcome in fixture["expect"]["checks"].items():
        CheckId(check_value)
        Outcome(outcome)

    for entry in fixture["spec"]:
        for field in ("source", "section", "url", "quote", "verification"):
            assert entry[field].strip(), f"spec entry is missing {field}"


@pytest.mark.parametrize("fixture", FIXTURE_DATA, ids=FIXTURE_IDS)
def test_fixture_id_matches_its_filename(fixture: dict) -> None:
    """Discovery is by glob, so the filename is the identity. A file whose `id` disagrees
    would be referred to in a report by a name that opens nothing."""
    assert (FIXTURE_DIR / f"{fixture['id']}.json").exists()


@pytest.mark.parametrize("fixture", FIXTURE_DATA, ids=FIXTURE_IDS)
def test_claimed_case_matches_the_expected_verdict(fixture: dict) -> None:
    """The label and the expectation must agree, checked without running anything.

    A fixture is evidence only if the two halves of it say the same thing. If a file
    labelled "violating" expected a PASS, the coverage test below would count the check as
    covered and the pack would certify an instrument that convicts nobody.
    """
    for check_value, case in fixture["exercises"].items():
        expected = fixture["expect"]["checks"].get(check_value)
        assert expected is not None, (
            f"{fixture['id']} claims to exercise {check_value} but states no expectation"
        )
        assert Outcome(expected) in CASE_OUTCOMES[case], (
            f"{fixture['id']}: a {case!r} fixture cannot expect {expected!r}"
        )


@pytest.mark.parametrize("fixture", FIXTURE_DATA, ids=FIXTURE_IDS)
def test_a_violating_fixture_quotes_a_must(fixture: dict) -> None:
    """Decision rule R1 in the fixture layer.

    `CheckResult` already refuses a failing verdict without a MUST-level anchor, which
    protects the instrument. Nothing protected the *fixtures*: a file asserting that some
    deployment violates a specification, citing a sentence that only recommends, would be
    the authors' rubric wearing an RFC's clothes -- and it is the fixture pack, not the
    code, that a reviewer reads to decide whether the instrument is tautological.
    """
    if not any(case == "violating" for case in fixture["exercises"].values()):
        return
    quotes = [entry["quote"] for entry in fixture["spec"]]
    assert any("MUST" in quote for quote in quotes), (
        f"{fixture['id']} asserts a violation but quotes no MUST-level sentence"
    )


def test_fixture_ids_are_unique() -> None:
    assert len(set(FIXTURE_IDS)) == len(FIXTURE_IDS)


# --- R8 leg 1, enforced -------------------------------------------------------


def _fixtures_for(check: CheckId, case: str) -> list[str]:
    return [
        fixture["id"]
        for fixture in FIXTURE_DATA
        if fixture["exercises"].get(check.value) == case
    ]


@pytest.mark.parametrize(
    "check", sorted(MUST_FAILABLE, key=lambda c: c.value), ids=lambda c: c.value
)
def test_must_level_check_has_a_conforming_fixture(check: CheckId) -> None:
    assert _fixtures_for(check, "conforming"), (
        f"{check.value} ({check.name}) can report a MUST-level failure but no fixture in "
        f"{FIXTURE_DIR.name}/ demonstrates the conforming case. Decision rule R8 leg 1 "
        f"forbids collecting data with that gap open."
    )


@pytest.mark.parametrize(
    "check", sorted(MUST_FAILABLE, key=lambda c: c.value), ids=lambda c: c.value
)
def test_must_level_check_has_a_violating_fixture(check: CheckId) -> None:
    assert _fixtures_for(check, "violating"), (
        f"{check.value} ({check.name}) can report a MUST-level failure but no fixture in "
        f"{FIXTURE_DIR.name}/ demonstrates it. An unfalsified check is an unvalidated one."
    )


def test_only_failable_checks_are_claimed_as_violated() -> None:
    """A fixture cannot claim to violate a check that is incapable of failing.

    C02, C08, C09 and C16-C18 are descriptive-only and `model_post_init` raises if one of
    them reports a failure, so a "violating" fixture aimed at them describes an outcome the
    instrument can never produce. C01 and C07 rest on SHOULD-level sentences and are in the
    same position. Catching it here rather than at run time keeps the pack from documenting
    a measurement that does not exist -- the C06/C10 defect, in fixture form.
    """
    for fixture in FIXTURE_DATA:
        for check_value, case in fixture["exercises"].items():
            if case != "violating":
                continue
            assert CheckId(check_value) in MUST_FAILABLE, (
                f"{fixture['id']} claims {check_value} is violated, but no code path emits "
                f"a failure for it"
            )


def test_r8_names_three_edge_cases_and_each_stands_as_its_own_fixture() -> None:
    """R8's closing sentence, read literally.

    Trailing slash, case, and same-host-different-path are the near-misses a coarse equality
    test either forgives or lumps together, and each of the three has already been scored
    wrongly at least once in this repository's history. The relation recorded in a fixture's
    expected evidence is what proves the case is present, because that relation is the R9.3
    taxonomy entry the instrument actually assigned.
    """
    observed: set[str] = set()
    for fixture in FIXTURE_DATA:
        evidence = fixture["expect"].get("evidence", {})
        relation = evidence.get("resource_relation")
        if isinstance(relation, str):
            observed.add(relation)
        observed.update(str(v) for v in evidence.get("as_issuer_relations", {}).values())

    missing = [name for name in REQUIRED_EDGE_RELATIONS if name not in observed]
    assert not missing, f"R8 requires a separate fixture for each of: {missing}"


def test_the_trailing_slash_asymmetry_is_pinned_on_both_sides() -> None:
    """R9.4, which is the single place where C12 and C13 are required to disagree.

    The same textual difference is UNSPECIFIED for C12 and a failure for C13, because C12's
    expected value is reconstructed from a lossy mapping (RFC 9728 3.1 strips the slash
    before inserting the well-known suffix, so two identifiers share one metadata URL) while
    C13 reads its left-hand side literally out of `authorization_servers`. Both halves are
    asserted together: pinning only one would let a later "consistency" fix collapse them
    and either forgive real violations or convict on an undecidable class, and the test
    suite once contained exactly that contradiction with no test to notice it.
    """
    c12_cases = {
        fixture["expect"]["checks"].get("C12")
        for fixture in FIXTURE_DATA
        if fixture["expect"].get("evidence", {}).get("resource_relation")
        == "trailing_slash_only"
    }
    c13_cases = {
        outcome
        for fixture in FIXTURE_DATA
        for issuer, relation in fixture["expect"]
        .get("evidence", {})
        .get("as_issuer_relations", {})
        .items()
        if relation == "trailing_slash_only"
        for outcome in [fixture["expect"]["checks"].get("C13")]
    }
    assert c12_cases == {Outcome.UNSPECIFIED.value}, (
        "R9.3/R9.4: a trailing-slash-only difference is our uncertainty in C12"
    )
    assert c13_cases == {Outcome.FAIL_MISIMPLEMENTED.value}, (
        "R9.3/R9.4: the same difference is an observed MUST violation in C13"
    )
