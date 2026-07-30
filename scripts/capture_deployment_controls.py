"""Capture real authorization-server metadata as conformance fixtures (negative controls).

Every fixture in `tests/fixtures/` before this script existed used an RFC 2606 synthetic
host, which means the pack proved the instrument *convicts* what the specifications forbid
and never once proved it *acquits* a real, correctly configured deployment. That gap is not
theoretical: the defect that moved C12's violation rate from 75% to 25% was found by hand-
checking eight live endpoints, not by the fixture pack, because a pack built entirely from
documents the authors wrote cannot contain a surprise the authors did not think of.

So this script fetches the metadata that large identity providers publish, verbatim, and
writes it into the pack as fixtures whose expected verdict is PASS. A control that fails is
either a real finding about that provider or a false-positive generator in the instrument,
and both are things this study must know before it points the instrument at 5,000 hosts.

Design notes:

**It fetches through `agentidprobe.fetcher.Fetcher`, not `httpx`.** The documents therefore
arrive through the same code path, the same User-Agent and the same politeness gates that
will score them. That is how the run discovered that Okta and Auth0 tenants serve a blanket
`User-agent: * / Disallow: /` -- recorded in the report below and in docs/ETHICS.md, because
it means those two platforms are unobservable to this instrument by our own policy, and no
control fixture for them can exist.

**Every candidate location is captured, not just the one that answered.** The instrument
tries the RFC 8414 form before the OpenID Connect Discovery form, and which one answers
changes the document it scores. A fixture serving only the successful URL would quietly
skip the candidate walk and pass for the wrong reason.

**It never edits a document.** The bytes go into the fixture as parsed, and the fixture
records the SHA-256 of the response body so a reviewer can tell a stale capture from an
edited one. Documents drift -- providers add members -- so re-running this is expected to
report differences and does not assert their absence.

    python scripts/capture_deployment_controls.py --report      # fetch and print, write nothing
    python scripts/capture_deployment_controls.py --write       # regenerate the fixtures
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentidprobe.config import (  # noqa: E402
    MeasurementConfig,
    as_metadata_candidate_urls,
)
from agentidprobe.fetcher import Fetcher  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures"

# The date the documents in the committed fixtures were retrieved. Passed in rather than
# read from the clock so that re-running the script does not silently re-date documents it
# did not change.
CAPTURE_DATE = "2026-07-30"


@dataclass(frozen=True)
class Control:
    slug: str
    provider: str
    # The issuer string a protected resource would put in `authorization_servers`.
    issuer: str
    title: str
    note: str
    # Checks the *real bytes* drive, and the case each is claimed to demonstrate.
    exercises: dict[str, str]
    expect: dict[str, str]


CONTROLS: tuple[Control, ...] = (
    Control(
        slug="control-google-real-deployment",
        provider="Google",
        issuer="https://accounts.google.com",
        title="Google's authorization-server metadata is acquitted",
        note=(
            "Google serves both well-known forms and the two documents differ in member "
            "count, so which one the instrument scores depends on its own candidate order. "
            "Both echo the issuer exactly."
        ),
        exercises={"C13": "conforming"},
        expect={"C13": "pass"},
    ),
    Control(
        slug="control-microsoft-entra-tenant-real-deployment",
        provider="Microsoft Entra ID (single tenant)",
        issuer=(
            "https://login.microsoftonline.com/"
            "9188040d-6c67-4c5b-b112-36a304b66dad/v2.0"
        ),
        title="A tenant-specific Microsoft Entra issuer is acquitted",
        note=(
            "The tenant GUID is the publicly documented identifier of the Microsoft account "
            "consumer tenant, so no private tenant is named here. This is the control that "
            "makes the templated `/common` document below a statement about that document "
            "rather than about the provider: the same host, asked for a concrete issuer, "
            "echoes it back byte for byte."
        ),
        exercises={"C13": "conforming"},
        expect={"C13": "pass"},
    ),
    Control(
        slug="control-microsoft-entra-common-template-issuer",
        provider="Microsoft Entra ID (tenant-independent)",
        issuer="https://login.microsoftonline.com/common/v2.0",
        title="A tenant-independent Entra document returns a templated issuer",
        note=(
            "The document returns `https://login.microsoftonline.com/{tenantid}/v2.0`, a "
            "literal RFC 6570 placeholder. Decision rule R9.6: this is `template_placeholder` "
            "and UNSPECIFIED, not a MUST violation -- see the rule for the argument."
        ),
        exercises={"C13": "undecidable"},
        expect={"C13": "unspecified"},
    ),
    Control(
        slug="control-github-actions-real-deployment",
        provider="GitHub Actions OIDC",
        issuer="https://token.actions.githubusercontent.com",
        title="GitHub's workload-identity issuer is acquitted",
        note=(
            "A seven-member document -- the smallest real one captured. It advertises none "
            "of C16, C17 or C18, which is what makes it useful: a minimal conforming "
            "deployment must still pass the decisive check."
        ),
        exercises={"C13": "conforming"},
        expect={"C13": "pass"},
    ),
    Control(
        slug="control-gitlab-real-deployment",
        provider="GitLab.com",
        issuer="https://gitlab.com",
        title="GitLab.com's authorization-server metadata is acquitted",
        note=(
            "Served from behind Cloudflare, so this control also exercises the R4 block "
            "classifier against an origin that answers normally through a CDN."
        ),
        exercises={"C13": "conforming"},
        expect={"C13": "pass"},
    ),
)

# Providers that cannot have a control fixture, and why. Kept in the script rather than in
# prose because "we could not observe these" is a fact about the instrument that belongs
# next to the evidence, and because a reviewer will ask why the two most widely deployed
# hosted IdPs are missing from a list of negative controls.
UNOBSERVABLE = {
    "Okta": (
        "Okta tenants serve `User-agent: * / Disallow: /`; verified against a trial tenant "
        "on 2026-07-30. Our robots policy (ETHICS.md 6, R4) therefore excludes every Okta "
        "tenant, and the instrument records ERROR rather than any verdict."
    ),
    "Auth0": (
        "Auth0 tenants serve `User-agent: * / Disallow: /`; verified against login.auth0.com "
        "on 2026-07-30. The apex auth0.com allows crawling but serves no metadata document "
        "(404), so it is a marketing site rather than an authorization server."
    ),
}


async def capture() -> dict[str, dict]:
    """Fetch every candidate location for every control issuer."""
    captured: dict[str, dict] = {}
    async with Fetcher(MeasurementConfig()) as fetcher:
        for control in CONTROLS:
            documents = []
            for url in as_metadata_candidate_urls(control.issuer):
                result = await fetcher.fetch(url)
                parsed = None
                if result.body:
                    try:
                        parsed = json.loads(result.body.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        parsed = None
                documents.append({
                    "url": url,
                    "status": result.status,
                    "error_kind": str(result.error_kind),
                    "sha256": hashlib.sha256(result.body).hexdigest() if result.body else None,
                    "server": result.headers.get("server"),
                    "json": parsed if isinstance(parsed, dict) else None,
                })
            captured[control.slug] = {"documents": documents}
    return captured


def _resource_url(control: Control) -> str:
    """The synthetic protected resource that declares this control's issuer.

    Synthetic on purpose, and the fixture says so. What the control validates is the
    instrument's treatment of a real authorization server, which is reached through a
    resource declaration; inventing the resource keeps the capture to documents that
    identity providers publish for anyone to read, and keeps a third party's protected
    resource out of a test fixture.
    """
    return "https://resource.example.org/mcp"


def build(control: Control, captured: dict) -> dict:
    documents = captured["documents"]
    answered = next((d for d in documents if d["json"] is not None), None)
    if answered is None:
        raise SystemExit(f"{control.slug}: no candidate location returned a JSON object")

    resource = _resource_url(control)
    served = [
        {
            "url": "https://resource.example.org/.well-known/oauth-protected-resource/mcp",
            "status": 200,
            "json": {"resource": resource, "authorization_servers": [control.issuer]},
            "provenance": "synthetic: the resource declaration that reaches the issuer",
        }
    ]
    for document in documents:
        entry: dict = {"url": document["url"], "status": document["status"] or 404}
        if document["json"] is not None:
            entry["json"] = document["json"]
            entry["provenance"] = (
                f"captured verbatim {CAPTURE_DATE}; sha256 {document['sha256']}"
            )
        else:
            entry["provenance"] = (
                f"captured {CAPTURE_DATE}: this candidate location did not serve a JSON "
                f"object (status {document['status']}, error {document['error_kind']})"
            )
        served.append(entry)

    return {
        "schema": "agent-id-probe/conformance-fixture/1",
        "id": control.slug,
        "modality": "oauth_metadata",
        "title": control.title,
        "control": {
            "kind": "real_deployment",
            "provider": control.provider,
            "captured_at": CAPTURE_DATE,
            "captured_by": "scripts/capture_deployment_controls.py",
            "edited": False,
            "note": control.note,
            "documents": [
                {
                    "url": d["url"],
                    "status": d["status"],
                    "sha256": d["sha256"],
                    "server": d["server"],
                }
                for d in documents
            ],
        },
        "exercises": control.exercises,
        "decision_rules": ["R4", "R6", "R8", "R9"],
        "rationale": (
            "R8 leg 1 requires a conforming and a violating fixture per MUST-level check, "
            "and every fixture satisfying it used an RFC 2606 synthetic host -- so the pack "
            "demonstrated that the instrument convicts what the specifications forbid and "
            "never that it acquits a deployment that is real and correct. That asymmetry is "
            "how a false-positive generator survives a green test suite, and this repository "
            "has already shipped one: C12's expected value was derived from the wrong URL and "
            "reported a 75% violation rate until eight live endpoints were checked by hand. "
            "This fixture serves the metadata this provider actually publishes, unedited, and "
            "expects the verdict a correct instrument must reach. "
            + control.note
        ),
        "spec": [
            {
                "source": "RFC 8414",
                "section": "3.3",
                "url": "https://www.rfc-editor.org/rfc/rfc8414.html#section-3.3",
                "quote": (
                    "The \"issuer\" value returned MUST be identical to the authorization "
                    "server's issuer identifier value into which the well-known URI string "
                    "was inserted to create the URL used to retrieve the metadata.  If these "
                    "values are not identical, the data contained in the response MUST NOT "
                    "be used."
                ),
                "verification": (
                    "verbatim-verified against rfc-editor.org, 30 July 2026"
                ),
            },
            {
                "source": "RFC 8414",
                "section": "5",
                "url": "https://www.rfc-editor.org/rfc/rfc8414.html#section-5",
                "quote": (
                    "This backwards-compatible behavior should only be necessary when the "
                    "well-known URI suffix employed by the application is "
                    "\"openid-configuration\"."
                ),
                "verification": (
                    "verbatim-verified 30 July 2026; the sentence that makes the "
                    "openid-configuration fallback in `as_metadata_candidate_urls` a "
                    "specification requirement rather than a convenience, and every control "
                    "below except Google is reached through it"
                ),
            },
        ],
        "endpoint": {
            "url": resource,
            "response": {"status": 401, "headers": {}},
        },
        "documents": served,
        "expect": {
            "checks": {**control.expect, "C12": "pass", "C05": "pass"},
            "evidence": {"as_issuer_relations": {control.issuer: _relation_name(control)}},
        },
    }


def _relation_name(control: Control) -> str:
    return (
        "template_placeholder"
        if control.expect.get("C13") == "unspecified"
        else "identical"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the fixture files")
    parser.add_argument("--report", action="store_true", help="fetch and print only")
    args = parser.parse_args()
    if not (args.write or args.report):
        parser.error("choose --write or --report")

    captured = asyncio.run(capture())

    for control in CONTROLS:
        print(f"\n=== {control.provider}  ({control.slug})")
        for document in captured[control.slug]["documents"]:
            issuer = (document["json"] or {}).get("issuer")
            print(
                f"  {document['status'] or document['error_kind']:>18}  {document['url']}"
                + (f"\n{'':22}issuer={issuer!r}" if issuer else "")
            )

    print("\n=== not observable, so no control fixture exists")
    for provider, reason in UNOBSERVABLE.items():
        print(f"  {provider}: {reason}")

    if args.write:
        for control in CONTROLS:
            fixture = build(control, captured[control.slug])
            path = FIXTURE_DIR / f"{control.slug}.json"
            path.write_text(
                json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
