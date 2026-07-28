# Research Ethics Statement — `agent-id-probe`

**Status: binding. The measurement run does not start until every precondition in §11 is met.**

*This document is written in English because its audience is the operators of the endpoints
we contact. The `User-Agent` of every request we send points here. If you are an operator and
you want us to stop, see §7 — one line is enough, and we do not ask why.*

Last updated: 28 July 2026.

---

## 1. What this study does

`agent-id-probe` measures whether the identity and authorization metadata that deployed AI
agent endpoints *publish about themselves* is internally consistent with the specifications
that define it (RFC 9728, RFC 8414, the Model Context Protocol authorization specification,
and the A2A Agent Card specification).

It fetches documents that operators have deliberately published at well-known locations,
parses them, and compares declared values against each other. That is the whole method.

## 2. Menlo Report

We adopt the Menlo Report framework explicitly.

**Respect for Persons.** The study targets machines and published documents, not people. No
human subjects, no user accounts, no personal data sought. Where a fetched document happens
to contain personal data (an A2A card's `provider.organization`, a contact e-mail in
authorization-server metadata) it is minimised at analysis time and masked before
publication. Consent is not obtainable at this scale; in its place we accept a standing,
no-questions-asked opt-out (§7) and an identifying `User-Agent` on every request.

**Beneficence.** The expected benefit is a public, reproducible account of whether declared
trust relationships in the agent ecosystem can be verified at all, plus an open-source
instrument others can re-run. The expected harm is a handful of HTTP GETs per host. We bound
the harm explicitly in §4 and §10 rather than asserting it is small.

**Justice.** The corpus is a registry census, not a targeted selection. We do not
preferentially probe small operators who are less able to defend themselves, and we do not
exclude large ones. Findings are reported in aggregate; §8 governs the one place where that
tension is real.

**Respect for Law and Public Interest.** See §9. We accept the strictest available reading
of what we may access and stay well inside it.

## 3. Scope — exactly what is sent

This section is normative and mirrors `config.Scope` in code. If the code and this section
ever disagree, that is a bug in the code.

**Method:** `GET` only.

**Paths, and only these:**

```
/.well-known/oauth-protected-resource
/.well-known/oauth-protected-resource/<endpoint path>
/.well-known/oauth-authorization-server[/<issuer path>]
/<issuer path>/.well-known/oauth-authorization-server
/<issuer path>/.well-known/openid-configuration
/.well-known/agent-card.json
/.well-known/did.json
/.well-known/jwks.json
/robots.txt
```

Plus the public registry APIs used to build the corpus
(`registry.modelcontextprotocol.io`, `registry.smithery.ai`), which are documented,
keyless, read-only endpoints intended to be queried.

`/.well-known/agent.json`, the pre-v0.3 Agent Card alias, was listed here until
2026-07-29 and was never actually requested. It has been removed rather than implemented:
adding it would mean one more request against every origin in the corpus to find legacy
documents in a modality with roughly ten endpoints in it. The cost of that falls on
operators; the benefit does not exist. The consequence is a limitation, not a promise.

**A `WWW-Authenticate: resource_metadata` value is followed only when it is `https` and
stays within the resource's own registrable domain.** The header is input from the host
being measured. Following it anywhere it points sent requests to loopback and private
addresses from the measurement's own network — requests that appear nowhere in this list.

Plus one request to the endpoint URL as listed in the public registry, in order to observe
whether it answers `401` — which is the only way to learn whether authorization applies at
all.

**Rate:** at most 1 request per second per host, with a global concurrency cap.
`Retry-After` is honoured. A host that returns repeated failures exhausts a per-host failure
budget and is dropped for the remainder of the run.

**Identification:** every request carries a `User-Agent` naming the study and linking to the
public repository, which carries this document and the opt-out address.

## 4. What we deliberately do not do

- **No authentication is attempted.** No credentials are sent, guessed, or reused.
- **No OAuth flow is executed.** We never request a token, never visit an authorization
  endpoint, never redeem a code.
- **No dynamic client registration.** RFC 7591 registration would be a write on someone
  else's authorization server. We count whether a `registration_endpoint` is *declared*; we
  never call it.
- **No MCP method is invoked.** No `tools/call`, no `resources/read`. See §5 for the one
  handshake question that remains open.
- **No writes of any kind.**
- **No access control is bypassed, probed, or tested.** A `403` ends our interest in that
  host; we do not look for a way around it.
- **No vulnerability scanning.** We do not fuzz, enumerate, or fingerprint for weaknesses.
- **No registration of any domain we discover.** If the study finds that a declared issuer's
  domain has lapsed and is available, we report the *existence* of the class in aggregate and
  we do not register it, and we do not publish the name until the operator has been notified.

## 5. The one open question: MCP `initialize`

A proposed extension (task #24) would send an MCP `initialize` request to harvest
`serverInfo`. `initialize` is a JSON-RPC **POST**, it is the protocol's own handshake, and it
may allocate session state (`Mcp-Session-Id`) on the server.

That is not a write, but it is **not read-only either**, and this study has described itself
as passive. Two conditions therefore apply if it is ever enabled:

1. The description of the study changes everywhere, including the paper: not *"passive,
   read-only"* but **"read-only, apart from the protocol's own handshake; no method is
   invoked"**. Claiming passivity while sending POSTs would put every other statement in this
   document in doubt.
2. If the server returns a session id, the session is closed immediately with the `DELETE`
   the MCP specification defines for that purpose. We do not leave sessions to expire.

As of this version, `initialize` is **not enabled**.

## 6. `robots.txt`

We honour `robots.txt`, and we are aware this is unusual for `/.well-known/` paths — RFC 8615
defines those locations precisely so that machines may retrieve them, and a crawler directive
is arguably not addressed to us.

We honour it anyway, because the cost of being wrong in the other direction is higher.

The consequence is measured rather than hidden: endpoints excluded by `robots.txt` leave the
study **entirely** — they are removed from every denominator, and the count of exclusions is
reported. Otherwise our own politeness policy would move the published rate. The same rule
applies when an operator's `robots.txt` blocks an issuer's metadata: we record that we could
not observe it, and we never write it up as that operator's specification violation.

## 7. Identification and opt-out

- Every request carries an identifying `User-Agent` with a live URL.
- That URL describes the study, lists the exact requests we send, gives the date range, and
  carries a contact address.
- **Opt-out is one message and takes no justification.** We remove the host, we do not ask
  why, and we do not probe it again in any future run.
- The opt-out list is **`docs/opt-out.txt`**, committed to the public repository so the
  exclusion is auditable rather than merely promised.
- A domain entry also excludes its subdomains: a request to opt out is about an operator,
  not about one hostname.
- **The gate is in the fetcher, not in corpus filtering**, and it is checked before
  anything else — including before we read `robots.txt`. An operator who has asked not to
  be measured is not contacted at all. Enforcing it there means no call path can route
  around it: not a declared `jwks_uri`, not a `WWW-Authenticate` hint, not a redirect.
- Opted-out endpoints are removed from every denominator and the count is reported in the
  paper.

## 8. Publication policy

There is a real tension here between reproducibility and not exposing individual endpoints,
and we resolve it explicitly rather than leaving it to taste:

- **The corpus is published** — the list of endpoint URLs, with the collection date. These
  come from a public registry and publishing them adds no exposure.
- **Aggregate results are published** with the paper.
- **Per-endpoint verdicts are not published with the paper.** They are released only after
  the disclosure window in §9 has closed.
- **No endpoint is named in the text as an example of a failure** unless its operator has
  been notified and has not objected.
- Personal data encountered in fetched documents is masked before publication (KVKK / GDPR:
  the lawful basis is legitimate interest in publicly published documents; personal data is
  not sought, and is minimised where it appears).

## 9. Responsible disclosure

**What counts as reportable:** a declared issuer that does not resolve or does not identify
itself consistently (the client's discovery chain is broken); a resource identifier mismatch
that a conforming client must refuse to use; a declared issuer whose domain has lapsed.

**Who is notified.** Individual notification of ~1,700 endpoints is not achievable, and
pretending otherwise would be worse than saying so. So notification is tiered:

1. Where the endpoint publishes RFC 9116 `security.txt`, it is notified individually. This is
   automated and cheap.
2. Otherwise, findings are aggregated by the implementation cluster they belong to (R10.2)
   and reported to the SDK maintainer, hosting platform, or registry operator responsible for
   that cluster. *The clustering that the statistics require is also the disclosure
   mechanism* — the same grouping that makes the numbers defensible makes notification
   tractable.
3. Systemic and specification-level findings go to the relevant bodies: the MCP maintainers,
   the A2A project, and the IETF OAuth working group. Specification ambiguities — the
   `UNSPECIFIED` catalogue — are a deliverable of this study, not a by-product.

**Window:** 90 days between notification and publication of per-endpoint detail.

## 10. Harm assessment and stopping rules

The realistic worst case is that a fragile endpoint is disturbed by our requests. Bounds:

- Per host, **nominally 7 requests** across the whole run: `robots.txt` **twice** (the
  measurement runs in two passes and each opens its own client), the endpoint itself, two
  protected-resource metadata candidates, a `WWW-Authenticate`-hinted location, and one
  agent-card probe at the origin.
- **Up to 10** where a declared authorization server is hosted on the same host as the
  resource — which MCP explicitly permits ("it may be hosted with the resource server") —
  because up to three further well-known candidates are then tried against that same host.
- **Worst case 21, or 30 in the co-hosted case**, because a URL that times out is retried
  at most three times (`max_retries = 2`) with exponential backoff. Operators are owed the
  worst case, not the nominal one.
- At most 1 request per second per host, with a global concurrency cap.
- A per-host failure budget (3 consecutive failures) drops a host that is failing.
- **Global stopping rule, with the actual number:** after the first **50** endpoints, if
  the cumulative fraction of endpoints that were unreachable or blocked exceeds **25%**,
  the run aborts and is investigated before resuming. Implemented in `Runner`
  (`AbortPolicy` in `config.py`), not merely stated here — a kill switch without a number
  in code is not a kill switch, and one that cannot fire during the rehearsal is not one
  either: the threshold was 200, which is the size of the rehearsal itself.
  > The per-host budget protects one operator at a time and is blind to a run that has gone
  > wrong as a whole: a rate policy too aggressive in practice, a `User-Agent` everything
  > rejects, a broken vantage point. Those look acceptable host by host and unmistakable in
  > aggregate. Past that threshold the measurement is describing our own reception rather
  > than the ecosystem, and continuing would collect data we could not defend.
- The run is supervised. It is not scheduled to execute unattended.

## 11. Preconditions — the run does not start until all are true

1. [ ] The repository is public and the `INFO_URL` in `config.py` resolves. **Today it is a
   placeholder (`https://github.com/<org>/agent-id-probe`).** Until it resolves, every
   request we send carries a dead link, which defeats the entire identification and opt-out
   basis of this document. This is the hardest precondition here.
2. [ ] The page at that URL describes the study, lists the requests, and carries the opt-out
   address.
3. [ ] A narrow slice (~200 endpoints) has been run and its block rate, error budget, and
   rate-limit behaviour reviewed.
4. [ ] `docs/decision-rules.md` is frozen **and committed**, and the instrument passes its
   conformance fixtures.
   > Both halves are currently unmet and the box was wrongly ticked. The rules exist only
   > in an uncommitted working tree, so "frozen before collection" is an assertion with no
   > timestamp behind it. And decision rule R8 names `tests/fixtures/` specifically; that
   > directory does not exist. Conformance cases for the reported MUST-level checks
   > (C05, C12, C13, C14) are present as inline tests, but C03, C04 and C15 have none —
   > those belong to the terminated signed-document arm, so the resolution is either to
   > build their fixtures or to write the exemption into R8 explicitly. Until one of those
   > is done, this box stays unticked.
5. [ ] The ethics-board determination in §12 has been requested.
6. [x] The opt-out list (`docs/opt-out.txt`) exists and is enforced in the fetcher.
7. [x] The global abort threshold is set in code (`AbortPolicy`), not only in this document.

## 12. Institutional review

No human subjects are involved and no personal data is sought, so this study does not
constitute human-subjects research and formal IRB approval is not required.

We nonetheless **request a written determination to that effect** from the Muğla Sıtkı Koçman
University ethics board. It is free, it does not put anyone on the critical path, and
*"our ethics board confirmed this is not human-subjects research"* is a materially stronger
answer to a reviewer than *"we decided it wasn't."* Measurement venues increasingly ask.

A closely related study in this exact area — arXiv 2603.07473, on caller identity confusion
in MCP — was **withdrawn by its authors in July 2026** citing *"unresolved ethical issues in
data collection"* and the need to *"obtain proper ethical clearance before resubmission."*
That is the risk this section exists to retire, and it is the reason this document is a
precondition for the run rather than a section written up afterwards.

## 13. Vantage point disclosure

The measurement is performed from a **residential connection in Türkiye**. This is disclosed
because it is a threat to validity, not merely a detail: blocking correlates with the
property being measured, since mature and enterprise deployments are the ones behind WAFs.
Consequences, mitigations, and the resulting bounds on the estimates are reported in the
paper's Limitations section, and blocked responses are never scored as specification
failures (decision rule R4).
