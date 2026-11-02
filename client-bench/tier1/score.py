"""Score the Tier-1 client bench from the server's request logs.

Every driver writes, per (implementation, case), the requests the loopback server received
while the SDK's own authorization flow ran (raw/*.jsonl). This file is the only place an
outcome is decided, so the six SDKs are scored by one rule rather than six:

- A, B: **use** if the flow reached an authorization endpoint, **reject** if it did not.
- C1: the count of shipped files naming ``protected_resources`` (unchanged from 10 August),
  with the flow's behaviour when the field lists the requested resource kept as the control.
- C2: which of the two authorization servers' endpoints the flow reached.
- C3: whether the flow proceeds when ``protected_resources`` omits the requested resource.
- D: **accept** if the authorization code reached a token endpoint, **reject** if not.

A rejection only means something if the same flow succeeds when nothing is wrong. Each series
therefore has a control (A1 for A, B and C; D1 for D), and when the control did not get as far
as the series needs, every cell of that series is ``not_exercised`` with the control's error
as the reason, never a rejection (CASE-MATRIX.md, recording rule 1).

Usage:  python score.py            # scores raw/, writes results.jsonl beside this file
        python score.py raw-run1   # scores an earlier run, writes raw-run1/results.jsonl
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent

REQUIRED = {
    "A1": "use", "A2": "reject", "A3": "reject", "A4": "reject", "A5": "reject",
    "A6": "reject", "A7": "reject", "B1": "use", "B2": "reject",
    "D1": "accept", "D2": "reject", "D3": "reject", "D4": "accept", "D5": "reject",
    "D6": "accept",
}
LABELS = {
    "A1": "identical", "A2": "proper ancestor", "A3": "sibling", "A4": "cross-origin",
    "A5": "absent", "A6": "trailing slash", "A7": "case-differing path",
}


def is_proper_ancestor(adopted: str, requested: str) -> bool:
    """True when ``adopted`` names a strict path ancestor of ``requested`` on the same origin.

    Only this direction widens the audience of the token the client asks for. A trailing-slash
    or case variant (A6, A7) is a different identifier, not a broader one, so adopting it is
    recorded in ``adopted_document_identifier`` but not here.
    """
    from urllib.parse import urlsplit
    a, r = urlsplit(adopted), urlsplit(requested)
    if (a.scheme.lower(), a.netloc.lower()) != (r.scheme.lower(), r.netloc.lower()):
        return False
    prefix = (a.path or "/").rstrip("/") + "/"
    return a.path != r.path and r.path.startswith(prefix)
AUTHORIZE = re.compile(r"^/(root|as-first|as-second)/authorize$")
TOKEN = re.compile(r"^/(root|as-first|as-second)/token$")


def observe(raw: dict) -> dict:
    """What the server saw: the authorization endpoint, the resource, whether a code was redeemed.

    "Reached" means an authorization server the protected-resource document names. Reaching
    the root issuer means the client discarded the document and fell back to treating the
    origin as its authorization server, which is not a use of the document (the first run
    counted it as one: CASE-MATRIX.md, correction during the run).
    """
    every = [e for e in raw["log"] if AUTHORIZE.match(e["path"])]
    authorize = [e for e in every if AUTHORIZE.match(e["path"]).group(1) != "root"]
    token = [e for e in raw["log"] if TOKEN.match(e["path"])
             and (e.get("form") or {}).get("grant_type") == "authorization_code"]
    return {
        "fell_back_to_origin": any(AUTHORIZE.match(e["path"]).group(1) == "root" for e in every),
        "reached_authorize": bool(authorize),
        "authorize_as": AUTHORIZE.match(authorize[0]["path"]).group(1) if authorize else None,
        "authorize_resource": authorize[0]["query"].get("resource") if authorize else None,
        "token_called": bool(token),
        "token_resource": (token[0].get("form") or {}).get("resource") if token else None,
    }


def sdk_error(raw: dict) -> str | None:
    return raw.get("finish_error") or raw.get("connect_error") or raw.get("error")


def score_impl(raws: dict[str, dict]) -> list[dict]:
    any_raw = next(iter(raws.values()))
    base = {k: any_raw[k] for k in ("implementation", "package", "version")}
    base["level"] = any_raw.get("level", "flow")
    seen = {cid: observe(r) for cid, r in raws.items()}
    out = []

    def record(cid: str, series: str, **fields) -> None:
        raw = raws.get(cid, {})
        out.append({**base, "series": series, "case_id": cid,
                    "sdk_error": sdk_error(raw) if raw else None,
                    "callback_channel": raw.get("callback_channel"),
                    "run_at": raw.get("run_at"), **fields})

    def not_exercised(cid: str, series: str, reason: str) -> None:
        record(cid, series, outcome="not_exercised", conformant=None, detail=reason)

    # Driver-declared gaps come first: a case the driver could not put to the SDK at all.
    declared = {cid for cid, r in raws.items() if r.get("outcome") == "not_exercised"}

    a1 = seen.get("A1")
    flow_ok = a1 is not None and a1["reached_authorize"] and "A1" not in declared
    flow_reason = ("control A1 never reached an authorization endpoint: "
                   + str(sdk_error(raws["A1"]) if "A1" in raws else "A1 missing"))

    for cid in ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "B1", "B2"]:
        series = cid[0]
        if cid in declared:
            not_exercised(cid, series, raws[cid].get("detail", "declared by the driver"))
            continue
        if cid not in raws or not flow_ok:
            not_exercised(cid, series, flow_reason)
            continue
        s = seen[cid]
        observed = "use" if s["reached_authorize"] else "reject"
        requested = raws[cid]["requested_identifier"]
        adopted = s["authorize_resource"] if s["reached_authorize"] else None
        fields = {"required": REQUIRED[cid], "observed": observed,
                  "conformant": observed == REQUIRED[cid],
                  "authorize_resource": s["authorize_resource"],
                  "token_resource": s["token_resource"],
                  "fell_back_to_origin": s["fell_back_to_origin"],
                  "detail": "" if s["reached_authorize"] else (
                      "document not used: the flow fell back to the origin as authorization server"
                      if s["fell_back_to_origin"] else (sdk_error(raws[cid]) or ""))}
        if series == "A":
            other = observed == "use" and adopted not in (None, requested)
            fields |= {"case_label": LABELS[cid], "requested_identifier": requested,
                       "adopted_identifier": adopted,
                       "adopted_document_identifier": other,
                       "audience_widened": other and is_proper_ancestor(adopted, requested)}
        record(cid, series, **fields)

    # C1: the source count, with the flow's behaviour as the control for C3.
    c1 = raws.get("C1", {})
    occurrences = c1.get("c1_source_occurrences")
    record("C1", "C", strength="descriptive", source_occurrences=occurrences,
           schema_knows_field=(occurrences or 0) > 0,
           flow_proceeds=seen["C1"]["reached_authorize"] if "C1" in seen else None,
           detail="files of the shipped package naming protected_resources")

    for cid in ("C2", "C3"):
        if cid in declared:
            not_exercised(cid, "C", raws[cid].get("detail", "declared by the driver"))
            continue
        if cid not in raws or not flow_ok:
            not_exercised(cid, "C", flow_reason)
            continue
        s = seen[cid]
        if cid == "C2":
            chosen = {"as-first": "first", "as-second": "second"}.get(s["authorize_as"])
            record(cid, "C", strength="descriptive", observed=chosen or "neither",
                   chosen=chosen, detail="" if chosen else (sdk_error(raws[cid]) or ""))
        else:
            record(cid, "C", strength="descriptive",
                   observed="proceeds" if s["reached_authorize"] else "stops",
                   detail="" if s["reached_authorize"] else (sdk_error(raws[cid]) or ""))

    d1 = seen.get("D1")
    d_ok = d1 is not None and d1["token_called"] and "D1" not in declared
    d_reason = ("control D1 never redeemed its code: "
                + str(sdk_error(raws["D1"]) if "D1" in raws else "D1 missing"))
    for cid in ["D1", "D2", "D3", "D4", "D5", "D6"]:
        if cid in declared:
            not_exercised(cid, "D", raws[cid].get("detail", "declared by the driver"))
            continue
        if cid not in raws or not d_ok:
            not_exercised(cid, "D", d_reason)
            continue
        s = seen[cid]
        if not s["reached_authorize"]:
            not_exercised(cid, "D", "the flow never reached the authorization endpoint: "
                          + str(sdk_error(raws[cid])))
            continue
        observed = "accept" if s["token_called"] else "reject"
        record(cid, "D", required=REQUIRED[cid], observed=observed,
               conformant=observed == REQUIRED[cid],
               detail="" if s["token_called"] else (sdk_error(raws[cid]) or ""))
    return out


def main() -> int:
    # Optional: a directory holding another run's raw logs (e.g. raw-run1); its scores are
    # written beside them, so every run is scored by the same rule.
    raw_dir = HERE / (sys.argv[1] if len(sys.argv) > 1 else "raw")
    out = HERE / "results.jsonl" if raw_dir.name == "raw" else raw_dir / "results.jsonl"
    raws: dict[str, dict[str, dict]] = {}
    for path in sorted(raw_dir.glob("*.jsonl")):
        if path.name == "results.jsonl":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                raws.setdefault(r["implementation"], {})[r["case_id"]] = r
    results = [rec for impl in raws for rec in score_impl(raws[impl])]
    out.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in results), encoding="utf-8")
    for impl in raws:
        cells = {r["case_id"]: r for r in results if r["implementation"] == impl}
        def show(c: dict) -> str:
            if c.get("outcome") == "not_exercised":
                return "NE"
            return str(c.get("observed") or c.get("source_occurrences"))

        row = " ".join(
            f"{cid}:{show(c)}" + ("" if c.get("conformant") in (None, True) else "!")
            for cid, c in cells.items())
        print(f"{impl:22} {row}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
