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

Plus the public registry API used to build the corpus
(`registry.modelcontextprotocol.io`), which is a documented, keyless, read-only endpoint
intended to be queried.

`registry.smithery.ai` was queried by default until 2026-07-30 and is now opt-in
(`--include-smithery`), which is a change to this scope statement and not only to the data.
Smithery contributed no usable endpoints once a defect was fixed that had been reading its
`homepage` field as an MCP endpoint — that field is a project page, and it had been supplying
some 85% of the corpus as garbage, `github.com` sixty-six times over. The remaining reason to
query it, a capture–recapture population estimate, has been withdrawn as unsound. What was left
was several hundred paginated requests to a third party in exchange for no measurement, and this
section does not license that: every request we send has to buy an observation.

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

### 6.1 The cost of this policy is large, specific, and known in advance

Measured on 30 July 2026, while capturing the real-deployment control fixtures:

| Platform | `robots.txt` | Consequence |
|---|---|---|
| **Okta** (tenant, e.g. `*.okta.com`) | `User-agent: * ` / `Disallow: /` | **Every Okta tenant is excluded.** No verdict about any of them is observable |
| **Auth0** (tenant, e.g. `login.auth0.com`) | `User-agent: * ` / `Disallow: /` | **Every Auth0 tenant is excluded.** (The apex `auth0.com` permits crawling but serves no metadata — 404 — so it is a marketing site, not an authorization server) |
| Google, Microsoft Entra, GitHub, GitLab | permit the well-known paths | Observable; captured as controls |

Two of the most widely deployed hosted identity platforms are therefore **invisible to this
instrument by our own choice**, and this is disclosed here rather than discovered later for
three reasons:

1. It is not a defect and will not be "fixed". R4 forbids writing our politeness policy up as
   the operator's failure, and overriding a blanket `Disallow` because we judge our request
   harmless is precisely the reasoning this section exists to refuse.
2. **It biases the study's own headline.** Issuer concentration is a quantity we report, and
   MCP servers are more likely to delegate to a hosted platform than to run their own
   authorization server. The issuers we cannot see are disproportionately the ones that
   matter, so every rate conditioned on observed issuer documents (C13, C16–C18) is
   conditioned on a **non-random** subset. That belongs in Limitations, and it is written
   there — not left as an unexplained gap between "declared" and "observed" denominators.
3. **No control fixture for either platform can exist.** A reviewer comparing the control set
   against the list of large IdPs will notice the two absences; the reason is recorded in
   `scripts/capture_deployment_controls.py` next to the evidence rather than in prose alone.

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

- Per measured host, **nominally 7 requests** across the whole run: `robots.txt` **twice**
  (the measurement runs in two passes and each opens its own client), the endpoint itself,
  two protected-resource metadata candidates, a `WWW-Authenticate`-hinted location, and one
  agent-card probe at the origin.
- **Worst case 21**, because a URL that times out is retried at most three times
  (`max_retries = 2`) with exponential backoff. Operators are owed the worst case, not the
  nominal one.
- Per **declared issuer** host: `robots.txt` plus at most three well-known candidates, so
  **nominally 4**.
- **A hard per-host ceiling of 30 requests per pass** (`RatePolicy.max_requests_per_host`),
  counting redirect hops, retries and `robots.txt`. The issuer cap below bounds *issuers*,
  and an adversarial review measured the difference: ten declared issuers may be ten paths
  or ports on one machine, which produced 31 requests nominally, 91 with retries and 121
  with a redirect chain — and because the cap was per endpoint with nothing accumulating
  across them, 200 endpoints naming one popular issuer delivered 401 requests to it. Since
  issuer concentration is one of this study's own reported quantities, the most-named host is
  by construction the most-hit host, so an aggregate bound is not optional.
- **Redirects are re-gated on every hop.** Until 30 July 2026 the opt-out list, `robots.txt`
  and the scheme check ran once against the URL we chose, and up to three redirects then went
  wherever the response pointed: a declared issuer answering `302` to
  `http://127.0.0.1:8080` produced exactly that request. A hop is now followed only to an
  `https` URL with a public registrable domain, and every gate is re-applied. Where the issuer is co-hosted with the
  resource — which MCP explicitly permits (*"it may be hosted with the resource server"*) —
  those requests land on the same host and add to the figures above.
- **At most 10 declared issuers are looked up for any one endpoint**
  (`RatePolicy.max_issuers_fetched_per_endpoint`), and only where the issuer is an `https`
  URL with a public registrable domain. This bound was added on 29 July 2026 and the
  paragraph it replaced was **false**: `authorization_servers` is an arbitrary-length list
  written by the measured party, the code iterated all of it, and nothing stopped a
  document that declared two hundred issuers from commanding six hundred requests aimed
  wherever it chose. The same defect accepted plain `http`, loopback and RFC 1918 targets.
  Issuers we decline to request are recorded as declared and never contacted, and that
  decision is scored as our uncertainty, never as the operator's non-conformance.
- At most 1 request per second per host, with a global concurrency cap.
- A per-host failure budget (3 consecutive failures) drops a host that is failing.
- **At most 25 endpoints on any one hostname are measured at all**
  (`Scope.max_endpoints_per_host`, decision rule R10.6). The corpus is far more concentrated
  than the request ceiling assumed: 2,015 of 10,653 endpoints sit on eleven hostnames, and
  one carries 1,281. Without this rule the instrument would have attempted every one of them,
  spent the 30-request ceiling after a handful, and recorded the rest as failures of the
  operator rather than limits of ours. Sampling means **fewer** requests reach that operator
  than the ceiling alone permitted, because we stop asking rather than asking and being
  refused. The endpoints not sampled are counted per hostname, written to `sampling.json`,
  and reported — a decision of ours never gets to look like an observation of theirs.
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
  >
  > **Neither opt-outs nor robots exclusions feed this counter**, and the second half of
  > that was measured rather than assumed. The rehearsal on 30 July 2026 found 30 of 198
  > endpoints unreachable, **17 of them because of `robots.txt`** — our own politeness was
  > 8.6 of the 15.2 percentage points the switch was reading. The threshold above is defined
  > over endpoints that were *unreachable or blocked*, and a robots exclusion is neither: we
  > reached the host, read its rules, and chose not to ask. Since Okta and Auth0 both serve
  > `Disallow: /` (§6.1), leaving it in place would have let a stratum of hosted identity
  > platforms abort the census while the abort message blamed our reception — an inversion
  > of the exact thing this rule exists to detect. Both exclusions are counted and reported
  > separately instead.
- The run is supervised. It is not scheduled to execute unattended.

## 11. Preconditions — the run does not start until all are true

1. [x] The repository is public and the `INFO_URL` in `config.py` resolves.
   > Closed on 29 July 2026. It was `https://github.com/<org>/agent-id-probe` — a literal
   > placeholder — until then, so every request would have carried a dead link and no
   > operator could have found out who was contacting them or asked us to stop. It now
   > points at <https://github.com/sefatuncer/agent-id-probe>, which is public.
2. [x] The page at that URL describes the study, lists the requests, and carries the opt-out
   address.
   > `README.md` opens with that block, addressed to an operator who has just found our
   > `User-Agent` in their logs: what we requested, why, and the one line that stops it.
3. [ ] A narrow slice (~200 endpoints) has been run and its block rate, error budget, and
   rate-limit behaviour reviewed.
4. [x] `docs/decision-rules.md` is frozen **and committed**, and the instrument passes its
   conformance fixtures.
   > Both halves were unmet on 28 July and the box was wrongly ticked then. Both are now
   > met, and the record of how matters more than the tick.
   >
   > *Committed:* commit `a1408d1` (29 July 2026) carries the rules and the amendment log,
   > so "frozen before collection" now has a timestamp behind it rather than an assertion.
   >
   > *Fixtures:* `tests/fixtures/` exists — 41 self-describing JSON fixtures, each quoting
   > the specification sentence it derives from, driven over the real check functions by
   > `tests/test_conformance_pack.py`. Coverage is not asserted by hand: the set of checks
   > R8 leg 1 binds is recovered from the abstract syntax tree of `checks_oauth.py` and
   > `checks_signed.py` by `scripts/gen_catalogue.py:must_level_failable_checks()`, and a
   > parametrised test fails if any of them lacks either a conforming or a violating
   > fixture. Seven checks qualify (C03, C04, C05, C11, C12, C13, C15) and all seven
   > have both, so the C03/C04/C15 exemption contemplated here was not needed. C14 was
   > the eighth until 29 July 2026, when reading its anchor showed it could not convict
   > anybody; it left the set automatically, because the set is derived from the code.
   >
   > *Controls (30 July 2026):* five of the 41 are **not** synthetic. Thirty-six use RFC 2606
   > hosts, which means that until then the instrument had never been shown to **acquit** a
   > real, correct deployment — and the defect that moved a headline from 75% to 25% was
   > caught by hand-checking eight live endpoints, not by the fixture pack. Google, a Microsoft
   > Entra tenant, Entra `/common`, GitHub Actions and GitLab are now captured verbatim by
   > `scripts/capture_deployment_controls.py`, with every candidate URL recorded. Okta and
   > Auth0 are absent for the reason given in §6.1, which is a finding rather than an omission.
   >
   > Two caveats belong on the record rather than in a passing grade. **C11's violating
   > branches cannot occur in the field**: a refused handshake surfaces as a transport
   > error, which R4 makes an `ERROR`, and the collectors drop non-HTTPS URLs before
   > probing. Its fixtures are therefore synthetic and a "C11 violation rate" is
   > structurally zero — it must be reported as a property of the instrument, never as a
   > property of the ecosystem. And the C03/C04 fixtures pin **instrument behaviour** while
   > carrying an explicit `verification` field recording that their anchors (A2A §8.4, and
   > RFC 7515 §5.2 for the signature-failure clause) are still unconfirmed against the source
   > text, matching the ⚠️ rows in `docs/spec-mapping.md`. A fixture cannot certify an anchor
   > nobody has checked. C15 left this caveat on 30 July 2026: rather than demote it whole, its
   > three conditions were read separately, and the one that survived — RFC 7518 §3.3's
   > 2048-bit floor, *"A key of size 2048 bits or larger MUST be used with these algorithms"* —
   > is verbatim-verified and carries the check alone. The two that did not (`none` and `HS*`,
   > which RFC 7518 §3.6 and RFC 8725 do not reach in the way the check assumed) now score
   > `UNSPECIFIED`.
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
