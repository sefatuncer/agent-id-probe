"""Does a 405 mean "no authorization", or only "not that HTTP method"?

Written on 30 July 2026, between the narrow-slice rehearsal and the census, to answer a
question the rehearsal raised and that cannot be answered after the census.

The instrument decides whether an endpoint uses authorization from one signal: whether the
endpoint answered our GET with 401 or 403. `probe_oauth` returns early when it did not, so
for every other endpoint the protected-resource metadata path is never even requested. The
rehearsal put numbers on what that discards:

    decisive denominator (401/403)       : 50
    answered, posture undetermined (405/6): 59

The undetermined group is larger than the denominator. And it is not a random slice of the
corpus: 405 Method Not Allowed is what a server returns when it routes on HTTP method before
it consults authorization, so the endpoints we drop are selected by their framework's
middleware order. If those endpoints publish protected-resource metadata at the same rate as
the 401 group, then C05's denominator is roughly half of what it should be and every rate
conditioned on it is measured over a biased subset.

This script asks the cheapest possible version of the question, and it asks it *passively*:
it requests only `/.well-known/oauth-protected-resource` in both forms — a path already
declared in ETHICS.md 3, already requested against other endpoints, and requiring no protocol
interaction, no POST, and no authorization attempt. That distinction is why this could be run
at all; job #24's `initialize` harvest was cut precisely because it would have broken the
passive claim.

Groups, reported separately because they mean different things:

  method_gated (405/406) -- the request never reached the authorization layer. The primary
      question.
  answered_200          -- the request was served. A 200 is weaker evidence of the same
      thing: the server answered *this* request without a challenge, but MCP's transport
      carries messages over POST, so it may still challenge one.

Output is written to docs/method-gate-probe.json and committed, so the decision it informs
has its evidence beside it rather than in a chat log.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentidprobe.config import DEFAULT_CONFIG, prm_candidate_urls  # noqa: E402
from agentidprobe.fetcher import ErrorKind, Fetcher  # noqa: E402
from agentidprobe.models import Modality  # noqa: E402
from agentidprobe.store import RunStore  # noqa: E402

RUN_ID = "slice2"


def _looks_like_prm(body: bytes) -> tuple[bool, list[str]]:
    """A PRM document is a JSON object; `authorization_servers` is what makes it decisive."""
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False, []
    if not isinstance(parsed, dict) or "resource" not in parsed:
        return False, []
    declared = parsed.get("authorization_servers")
    return True, [s for s in declared if isinstance(s, str)] if isinstance(declared, list) else []


async def main() -> int:
    store = RunStore(ROOT, RUN_ID)
    reports = [r for r in store.read_reports() if r.modality is Modality.OAUTH_METADATA]
    in_scope = [r for r in reports
                if r.robots_allowed and not r.opted_out and not r.crossed_origin() and r.reachable]

    groups = {
        "method_gated": [r for r in in_scope if r.http_status in (405, 406)],
        "answered_200": [r for r in in_scope if r.http_status == 200],
        # The control: endpoints we already know use authorization, re-measured by exactly
        # the same code path. Without it a low rate in the other groups is unreadable --
        # it could mean "they do not use authorization" or "this script is broken".
        "challenged_401": [r for r in in_scope if r.http_status in (401, 403)],
    }

    results: dict[str, dict] = {}
    async with Fetcher(DEFAULT_CONFIG) as fetcher:
        for name, group in groups.items():
            found: list[dict] = []
            excluded = 0
            for report in group:
                url = report.endpoint.url
                hit = None
                for candidate in prm_candidate_urls(url):
                    fetched = await fetcher.fetch(candidate)
                    if fetched.error_kind in (ErrorKind.OPTED_OUT, ErrorKind.ROBOTS_DISALLOWED):
                        excluded += 1
                        break
                    if fetched.status == 200:
                        is_prm, issuers = _looks_like_prm(fetched.body)
                        if is_prm:
                            hit = {"endpoint": url, "prm_url": candidate,
                                   "declares_issuers": len(issuers)}
                            break
                if hit:
                    found.append(hit)
            asked = len(group) - excluded
            results[name] = {
                "endpoints": len(group),
                "asked": asked,
                "excluded_by_our_policy": excluded,
                "publish_prm": len(found),
                "rate": round(len(found) / asked, 4) if asked else None,
                "declaring_at_least_one_issuer": sum(1 for f in found if f["declares_issuers"]),
                "hits": found,
            }
            print(f"{name:>16}: {len(found)}/{asked} publish protected-resource metadata")

    out = ROOT / "docs" / "method-gate-probe.json"
    out.write_text(json.dumps({"run_id": RUN_ID, "groups": results}, indent=2, sort_keys=True)
                   + "\n", encoding="utf-8")
    print(f"\nwritten to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
