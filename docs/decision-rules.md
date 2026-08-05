# Decision Rules

**Status: FROZEN — before the main measurement run. Amendments are in the log below.**

The purpose is to make the accusation "you chose the result afterwards" (post-hoc / HARKing)
structurally impossible. Most of the rules are machine-enforced in `models.py`; the two that
cannot be (R5, R7) are stated in the run protocol.

## The scope of the freeze — an honest statement

These rules were frozen **before the main measurement run**, but **not before all data.** An
exploratory pilot of n=500 was run on 27 July 2026 (`phase0-findings.md`) and it affected the
*design* of the instrument directly: C05's candidate URL set was corrected, C11–C15 were
added, C07 was found unmeasurable and rewritten, and the funnel was split in two. That is a
normal and legitimate pilot→calibration loop, but the sentence "the rules were written
without seeing data" **would have been false and has been removed.**

The binding statement is this:

1. Pilot data **is not reported as a result.** No number from the pilot appears in the paper
   as a finding; everything is measured again in the main run with the corrected instrument.
   The pilot is described only as the justification for instrument development, explicitly
   labelled "pilot".
2. **None** of the rules below may be changed after the data of the main run has been seen.
3. Every amendment is written into the log at the top of this file with a date and a commit.
   An amendment without a log entry is void.

## Amendment log

**Commit `85faf3b` (29 July 2026) covers the rows below dated 2026-07-28 and the first
2026-07-29 batch.** Until that date none of these rules had been committed — that is, the
phrase "frozen before the data" had no timestamp behind it, only an assertion. Rows added
after it are covered by the commit that introduces them, which is the same guarantee: no row
in this log postdates the commit that carries it.

*The hashes in this file were rewritten once, on 29 July 2026, before the repository was
first published. Nothing about the content changed; commit message trailers were removed and
every hash therefore moved. The references here point at the published history, which is the
only one a reader can check.*

| Date | Rule | Amendment | Rationale |
|---|---|---|---|
| 2026-08-05 | **R10.4** | **Logged, not amended.** The rule's stated coverage range is **20%–88%**, and at `m = 300` clusters sharing an SDK default it is **20%**. The row below dated 2026-07-30 records it as 45%–82%, which was the last figure this log ever gave | The range was corrected in the rule's body on 30 July, hours after that row was written, when `scripts/wilson_coverage_under_clustering.py` replaced an estimate nobody had run with a seeded simulation over seven scenarios. **No row recorded the correction.** The body has been machine-locked to `docs/wilson-coverage.json` ever since — `tests/test_analysis.py` fails if the rule text, the `analysis.py` docstring and the committed simulation output disagree — so the number a reader gets is right and was never in doubt. What was wrong is that a frozen document's text moved and its audit trail did not, which is the precise defect the row below complains of in the other direction: there, the *code* was ahead of the pre-registration. A pre-registration whose body can drift ahead of its own changelog cannot be verified by reading it, and reading it is the only thing a reviewer can do. The correction understates the earlier figure's error: the published lower bound was **25 points** too optimistic |
| 2026-08-05 | **R1 / R7** | **C03 and C04 become `DESCRIPTIVE_ONLY`**; `SPEC_A2A` pinned from `/latest/` to `v0.3.0` | Their anchor was *"A2A §8.4"*, and **A2A v0.3.0 — the revision R7 pins — has no §8.4, no §4.4.7, no reference to RFC 8785, and no RFC 2119 keyword anywhere about card signatures**; `AgentCardSignature` is §5.5.6 and defines a data structure. Those sections exist in v1.0, which R7 does not admit, and `/latest/` now serves v1.0, so every stored C01–C04 verdict cited a document this study does not score. This also resolves the standing ⚠️ from 28 July: §8.4 could not be verified because it does not exist in the pinned revision, and no round had asked *which* revision was being searched. RFC 7515 §5.2 cannot substitute — it binds the party validating a JWS, not the publisher. Precedent: C14, 29 July. **C15 keeps its MUST**: RFC 7518 §3.3's 2048-bit floor binds the signer. The R8 coverage set fell from seven checks to five on its own, being AST-derived |
| 2026-07-31 | **R5** | **Implemented, not amended.** The classification and the ≥24 h check now execute as `agent-id-probe reconcile`, which writes `reconciliation.json` beside the later run. R5 keeps its 📋 marker: no code can make the second run happen. Three additions the rule's one sentence does not settle, fixed here before any data: (a) the unit is **both** `reachable` and each check outcome, counted in **separate tables**; (b) errors caused by **our own policy** — opt-out, `robots.txt`, the per-host ceiling — are a third class, never "persistent"; (c) a unit scored in only one run is **`unreconciled`**, not transient | R5 was prose in this file, cited by three source comments and two tests, and executed by nothing. The nearest thing in the repository was `replay.compare_reports`, which compares a run against its own re-score — R8's leg 2, where both sides come from the same bytes and every error reproduces by construction. Each addition prevents a measured error: on the two rehearsal runs the policy class holds **17 of 30** unreachable endpoints, all `robots.txt`, so without (b) the confirmed-error count reads **30 instead of 13** and our politeness policy is published as a stable property of third-party deployments — the same inversion as the kill-switch and per-host-ceiling defects above. Without (c) the 16 endpoints present in only one of those runs would have counted as errors that recovered. The interval is measured from `probed_at` and never from the manifest: `probe` writes no manifest, and `rescore` writes a **fresh** one over copied verdicts, so a replay taken a day later would otherwise present as a second run in which every error recurred |
| 2026-07-30 | **R10.7** | **New** — protected-resource metadata is requested for **every reachable endpoint**, not only for those that answered 401/403 | The rehearsal found that a challenge was the only entry into the OAuth funnel, and that the group it excluded was **larger than the denominator**: 50 endpoints challenged, 59 answered `405`/`406`, and 32 answered 200. Asking those groups directly (`docs/method-gate-probe.json`) found **27 endpoints declaring an authorization server** in a document at a well-known path while the instrument recorded them as not using authorization. Membership in the excluded group is decided by a framework's middleware order — a selection whose direction cannot be signed. Verdicts are unchanged and C05 can still only convict an endpoint that challenged; defining the denominator as "challenged **or** publishes metadata" is circular for C05 and is refused. What grows is the population carrying C12/C13, whose denominator is documents read rather than posture inferred: 36 → ~64 in the rehearsal |
| 2026-07-30 | **R10.6** | **New** — endpoints on one hostname are **sampled**, at most 25, chosen deterministically by `endpoint_id`; the remainder is a named, counted exclusion. **R10.5 is qualified**: the census claim stays exact at the hostname, apex and implementation units and is no longer exact at the endpoint unit | Found by the narrow-slice rehearsal, before the census. The 30-request per-host ceiling and the shape of the corpus are incompatible: 2,015 of 10,653 endpoints sit on eleven hostnames, one of which carries 1,281. At two to six requests each the ceiling was spent after a handful, the rest returned `OUT_OF_SCOPE` with `reachable=False`, and about a fifth of the corpus would have been counted as unreachable — enough to trip the abort and blame the ecosystem for our own configuration. Raising the ceiling would have sent one operator some 7,700 requests, which is what it was added to prevent. Sampling costs a claim (at the endpoint unit this is a census of hostnames and a sample within the large ones) and the paper states it; the frame is preserved in `corpus.jsonl`, so the sampling fraction stays checkable |
| 2026-07-30 | **R4 / ETHICS §10** | Robots-excluded endpoints **leave the kill switch's failure counter**, and are counted separately | The same rehearsal measured it rather than arguing it: 17 of 198 endpoints were excluded by `robots.txt`, which was 8.6 of the 15.2 percentage points the switch was reading. §10 defines its threshold over endpoints that were *"unreachable or blocked"*, and a robots exclusion is neither — we reached the host, read its rules, and chose not to ask. Identical in form to the opt-out fix of 29 July, on the branch that was missed then. With Okta and Auth0 both serving `Disallow: /` (ETHICS §6.1), a stratum heavy in hosted identity platforms could have aborted the census on a property of the ecosystem |
| 2026-07-30 | **R4 / R5** | A transport failure on the endpoint fetch now scores **`ERROR`**, not `NOT_APPLICABLE` | Found in the pre-flight `dry-run`. With no response there is no 401, so every MUST stage took the composition branch and recorded *"authorization is OPTIONAL in MCP and this endpoint did not require it"* against a host we never reached. R5 makes `ERROR` the set the second run reconciles; `NOT_APPLICABLE` is not in it, so a transiently-failing endpoint would have been booked as one that does not use authorization and the confirmation run would never have been pointed at it. No rate moves — both outcomes leave every denominator — but the stored record now says what happened |
| 2026-07-27 | R1–R8 | Initial freeze (commit `7d865d5`) | After the pilot, before the main run |
| 2026-07-28 | R8 | Human coders + Cohen's kappa → fixture suite + replay determinism (commit `df1613b`) | Kappa is the instrument of designs that score a rubric; this instrument is mechanical and there is no subjectivity to measure |
| 2026-07-28 | **R9** | **New** — identifier comparison policy | Three-agent review: C12's expected value was derived wrongly and C12/C13 had opposite strictness. Running without a written comparison policy would have left the headline violation rate to an unwritten judgement call |
| 2026-07-28 | **R10** | **New** — unit of analysis and cluster definition | The same review: endpoints are not independent, and choosing the cluster definition after the data is open to the objection "you chose the clustering that gave you the CI you wanted" |
| 2026-07-28 | R7 | The revision set was pinned by date | The phrase "the most permissive revision in force" silently swallowed a revision released on the day of the run |
| 2026-07-28 | **C16–C18 + R11** | **New** — three descriptive checks (RFC 9207 `iss` advertisement, client bootstrap, RFC 9728 §4 `protected_resources`) and the headline selection rule | All three are read from the authorization-server metadata document that is **already fetched**, at zero additional network cost. Which of them will carry the paper cannot be known before the data is seen; declaring the candidates in advance and binding the choice to a rule is the only honest alternative to looking at the data and making the most striking number the headline |
| 2026-07-28 | **R10.2** | **The primary unit of analysis was changed**: "SHA-256 of the normalised PRM byte form" → **the apex domain**. The old definition was not implementable | "Host-specific fields" required a hand-written list (refuting the rule's own claim that it "cannot be the authors' rubric"); it had no resolution (m≈3–8 → R10.4 impossible); it was sensitive to the serialiser; and it was never in the code |
| 2026-07-28 | **R10.2b** | **New** — a value-free implementation fingerprint (key names + JSON types + `server` family) | It actually delivers the property R10.2 claimed but could not: no value enters the hash |
| 2026-07-28 | **R10.1** | It was written down that changing the unit also changes **the denominator** (1 endpoint per apex/implementation), and the representative-endpoint rule was fixed (the smallest `endpoint_id`) | Changing only the clustering did not change the point estimate; a bulk publisher with 300 listings would still have determined the headline |
| 2026-07-28 | **Go/no-go** | The old criterion **was declared void** and a new one written (`phase0-findings.md` §8) | It rested on an unmeasured quantity (`audience`); it compared a point estimate against a threshold; and it looked at a dead arm |
| 2026-07-28 | **C06, C10** | **Deleted** | Both were defined, documented and **emitted by no code path**. C06 was also redundant with C13; C10 had no specification sentence to anchor to |
| 2026-07-28 | **C08, C09, C11** | **Made to emit** | They were in the same state; their data was already being fetched. The actual contents of the `DESCRIPTIVE_ONLY` set changed |
| 2026-07-29 | **R7** | Downgraded ⚙️ → 📋; the "the only way is `initialize`" rationale **was corrected because it was wrong**; the 2025-03-26 default was put on record | `spec_version` is never set. `MCP-Protocol-Version` does offer an inference channel (MUST 400), but it is a probe, it costs an extra request, and it is swallowed by 401 |
| 2026-07-29 | **C16/C17/C18 denominator** | Only the *observed* issuer was counted; now **observed and declared** are recorded together | An unreachable issuer pushed C16 to PASS — and C16 is R11.1's **rank-1 headline candidate**, with R11.3 already warning that it "may sit at 100%" |
| 2026-07-29 | **C18** | An empty `protected_resources` **no longer counts** as "publishes"; `empty_list` is reported separately | An empty list makes no cross-check possible. It was inflating the **rank-2 headline candidate** |
| 2026-07-29 | **R10.4** | **Variance floor**: a published interval may not fall below the simple-random-sample variance | The between-cluster estimator did not count within-cluster binomial variance; `n_eff` could exceed `n` by a factor of 313, and at `n=1000` an interval of `49.9% [49.7%–50.1%]` was publishable. A zero-width guard was added to the bootstrap |
| 2026-07-29 | **Scope** | A `WWW-Authenticate` hint is followed only when it is `https` **and** within the resource's own apex | The hint is input under the control of the host being measured; the `startswith("http")` check sent requests to loopback and RFC 1918 and wrote an attacker's issuer into the victim's graph |
| 2026-07-29 | **Scope** | `/.well-known/agent.json` **was removed** | It was on the list and was never requested. Adding it would have meant an extra request against ~5,000 origins; a false scope statement was unacceptable |
| 2026-07-29 | **`AbortPolicy`** | Threshold 200 → **50** endpoints | At 200 it never armed during the narrow-slice rehearsal — and the point of the rehearsal is to try out the full run |
| 2026-07-29 | **R9.3** | The outcome table's five bottom rows were **missing their C13 cell** and are now filled in as `FAIL_MISIMPLEMENTED` | The header declares four columns; `scheme_only`, `port_only`, `same_host_different_path`, `related_host` and `unrelated_host` supplied three. Rendered, the basis text fell into the C13 column, so **C13's verdict was unstated for five of the eight relation classes** — in the table that defines the study's decisive measurement. A transcription defect rather than a change of rule: `checks_oauth.py` has always exempted only `trailing_slash_only`, and only for C12 (`_R6_UNSPECIFIED_C12`), so the filled-in cells state what the instrument already did |
| 2026-07-29 | **Preamble** | "the two that cannot be machine-enforced (R5, R8)" → **(R5, R7)** | R8 carries ⚙️ and R7 was downgraded to 📋 on 29 July; the preamble was never updated with its own amendment, so the document contradicted its own markers |
| 2026-07-29 | **R1** | The `DESCRIPTIVE_ONLY` consequence list was corrected against `models.py`: **C10 removed, C16/C17/C18 added** | The list named a check deleted on 28 July and omitted the three that R11's first, second and fifth headline candidates rest on. R1 itself is machine-enforced and was always correct; the prose beside it was not, and the prose is what a reviewer reads |
| 2026-07-29 | **R1 / C14** | **C14 moved to `DESCRIPTIVE_ONLY`** and its anchor re-pointed from the MCP client sentence to RFC 9700 §2.1.1 + RFC 8414 §2 | C14 reported `FAIL_UNIMPLEMENTED` against the authorization server while citing *"MCP clients **MUST** refuse to proceed"* — a sentence binding the client. Reading the primary text settled it: RFC 8414 §2 marks `code_challenge_methods_supported` **OPTIONAL**, and RFC 9700 (BCP 240) §2.1.1 — the only text bridging *"Authorization servers MUST support PKCE"* to advertising it — sets that bridge at **RECOMMENDED** and adds *"Authorization servers **MAY** instead provide a deployment-specific way"*, which a passive prober cannot observe. So an absent element is not evidence that any authorization-server MUST was violated. The one server-binding MUST that exists (MCP 2025-11-25, *"Authorization servers providing OpenID Connect Discovery 1.0 MUST include…"*) is absent from 2025-06-18, which R7 makes the governing revision, and binds only the OIDC subset, which the instrument does not distinguish. The precedent was already here: MCP's Resource Indicators clause was rejected as unmeasurable for the identical reason and C07 was rewritten for it |
| 2026-07-29 | **Funnel** | **`FUNNEL_OAUTH` now ends at C13**; it has four stages | A descriptive check cannot be a funnel stage that narrows on `PASS`: `runner.summarise()` would keep a non-advertising endpoint in the denominator and never in the numerator, which is the composition-as-failure error that produced the 36.7% vs 96.6% gap. The funnel now terminates where the paper's thesis does, at issuer correspondence |
| 2026-07-29 | **C14 aggregation** | "any declared issuer advertised it" → **all declared issuers**, matching C16–C18 | C14 was the only funnel-stage check with an undeclared aggregation rule, and it used the most permissive one available. C13 four hundred lines away rejects exactly that reasoning: *"a resource that names five issuers of which four are dead is the thesis in miniature."* R11.5 fixed this for C16–C18 and had no C14 row |
| 2026-07-29 | **C16 bound party** | Recorded as binding the **client**; corrected to the **authorization server** | RFC 9207 §3 — *"the authorization server MUST indicate its support for the `iss` parameter"* — is the sentence governing what C16 observes; RFC 9700 §2.1's REQUIRED binds the client and is the motivation, not the anchor. The paper's §2 already said this. C16 stays descriptive: RFC 9207 §3's MUST is conditional on supporting the parameter, so an absent flag means "does not support", which nothing forbids. Found by the Figure 1 ↔ Table 1 cross-check, not by reading |
| 2026-07-30 | **Frame / Glama** | **Evaluated and cut.** `glama.ai` also removed from `Scope.unmetered_hosts` | Job #7's 15-minute gate, decided on the evidence. The API is free, keyless and cursor-paginated, so access was never the obstacle: across **500 records, 280 tagged `hosting:remote-capable`**, its eleven fields contain **no remote endpoint URL** — `url` is a glama.ai catalogue page and `repository` is a source repository. Wiring it in would have repeated the Smithery defect exactly, and worse for being server-specific: every derived endpoint would have looked plausible and resolved to one apex. The negative result is kept in the code (`GLAMA_CUT_REASON`) and in the paper, because it is a fact about the frame rather than a failed experiment — **of the three public MCP registries, only `registry.modelcontextprotocol.io` publishes remote endpoint URLs**, which is a ceiling on what any registry-framed study of this ecosystem can observe. The `unmetered_hosts` removal matters separately: that exemption lifts the per-host request ceiling for registries we paginate, and `glama.ai` can appear in the corpus as a *measured* platform host, which is the case the ceiling exists for |
| 2026-07-30 | **R11.5 / D8** | `analysis.py` now **excludes `as_not_fetched` issuers from both issuer denominators**, and reports what it excluded (`withheld_issuers` in the analysis record) | `issuer_documents()` read `authorization_servers` and never consulted `as_not_fetched`, so an issuer the instrument **deliberately never contacted** — not a public HTTPS host, or past the ten-per-endpoint cap — arrived as `None` and was scored *"does not advertise"*. The rate that absorbed it is **C16, R11.1's rank-1 headline candidate**: the paper's leading number moved with our own request policy, and in the direction that makes the ecosystem look worse the harder we throttle. R4 exists to forbid exactly that. The identical defect was found and fixed inside `checks_oauth.py` on 29 July for the per-endpoint verdict, and the analysis layer — which computes the number that gets published — was not fixed with it. An issuer withheld by one endpoint but observed via another stays in, because the exclusion is a property of the issuer across the corpus |
| 2026-07-30 | **R8 / R10.2 / D10** | The **public-suffix list is recorded in every manifest** (library, version, snapshot SHA-256, private-section flag) | The list was pinned against the network (`suffix_list_urls=()`) but not against the dependency: `tldextract>=5.1,<6.0` admits any patch release and each ships its own snapshot. It decides two things that reach the paper — the **primary unit of analysis** under R10.2, hence the cluster count and every interval; and **which hosts are contacted**, since an issuer with no registrable domain is never requested and, after the D8 fix, leaves the denominator. R8 leg 2's promise of byte-identical replay was therefore inheriting an unrecorded dependency, because replay re-derives apexes even though it does not re-fetch. Written on all manifests, not only `collect`'s |
| 2026-07-30 | **D7** | The issuer filter's **accepting** direction is now pinned: nine legitimate-but-unusual issuer shapes (port, path, deep sub-domain, punycode IDN, trailing slash, mixed case, multi-label suffix, query) | The filter had tests for everything it must refuse and none for what it must accept, so an implementation that also rejected a port-carrying or IDN issuer would have passed the whole suite. The implementation turned out to be correct — this was a coverage gap, not a live defect — but it became more dangerous the same day: with D8 fixed, a withheld issuer *leaves* the denominator instead of scoring badly, so over-rejection no longer shows up as a poor rate. It shows up as a smaller population, which is precisely what a study of an under-deployed mechanism expects to see |
| 2026-07-30 | **Frame / `collect`** | Three changes so that a census is one: `--max-pages` default **500 → 5000**; a truncated collection now **exits non-zero** instead of returning 0; `capture_recapture_estimate` **deleted**; Smithery moved from opt-out to **opt-in** | The default ceiling was a trial-run number that had become the census default — 500 pages × 100 records caps the corpus at 50,000 against a registry holding some 60,000, so the tool's *documented default* was to truncate the population the paper is about. `TRUNCATED` had been written to the manifest since 28 July and nothing read it: the exit code was 0, so `probe` ran next over a partial frame and produced a clean-looking dataset whose every rate was conditioned on where pagination stopped. **Capture–recapture** was deleted because it needs a closed population and independent samples and has neither — Smithery indexes largely what the official registry publishes, and servers are registered and withdrawn continuously; the decision to drop it had already been recorded while the live code kept computing it into every manifest. **Smithery** became opt-in for an ethics reason as much as a data one: after the `homepage`-as-endpoint defect was fixed it yields zero endpoints, so querying it by default meant several hundred paginated requests to a third party in exchange for no measurement, which `ETHICS.md` §3 does not license |
| 2026-07-30 | **R9.7 / C15** | **C15 was split, not demoted.** `none` and `HS*` lose their MUST and are recorded as `UNSPECIFIED`; **RSA < 2048 keeps it**, re-anchored to RFC 7518 §3.3. BCP 195 removed from the anchor entirely | The roadmap called for demoting C15 outright on the ground that its anchor was too weak for MUST. Reading the primary text showed that was true of two conditions out of three. **`none`:** every MUST in RFC 7518 §3.6 binds an implementation *accepting* an unsecured JWS — *"Implementations that support Unsecured JWSs **MUST NOT** accept such objects as valid unless…"* — and nothing forbids publishing one. **`HS*` against a published JWKS:** §3.2 sets a minimum key *size* and says nothing about publishing the key; the document that would forbid it is **RFC 8725**, and it does not reach, because RFC 8725 is a BCP about **JWTs** while an A2A card signature is a detached JWS over a JCS payload with no claims set — which settles the question left open for referee #3. **BCP 195 is a TLS document** and had no business in a JWS algorithm anchor, yet appeared in every C15 verdict. **RSA < 2048 survives intact:** RFC 7518 §3.3, *"A key of size 2048 bits or larger **MUST** be used with these algorithms"*, binds the signer and is observable from the published key set. Demoting wholesale would have discarded a correctly anchored measurement to tidy up two badly anchored ones. Security behaviour is unchanged: verification is still never *attempted* under non-creditable material, since declining to credit a signature and convicting its publisher are separate acts and only the second needs a MUST |
| 2026-07-30 | **C04** | A card whose signatures were all **skipped** as non-creditable now scores `UNSPECIFIED`, not `FAIL_MISIMPLEMENTED`; the failing branch gained **A2A §8.4** as its publisher-binding anchor | Exposed by the C15 split. The old branch emitted a MUST-level failure with the detail *"key resolved but no signature verified over the JCS payload"* — **a false statement**, and demonstrably so for an undersized RSA key, where the signature verifies perfectly and the defect is the key length. We had not observed a verification failure; we had declined to look, which R6 assigns to `UNSPECIFIED`. Separately, the failing branch cited only RFC 7515 §5.2, whose MUSTs tell a *verifier* to reject an invalid JWS — the same objection that demoted two thirds of C15 would have applied to C04's headline failure |
| 2026-07-30 | **R10.5** | **New** — what the intervals are uncertainty *about*, given a census frame; and a rate offered as a **description of the snapshot is published as a count with no interval** | The corpus is a complete enumeration, so sampling error is zero and an unexplained interval reads as sampling error — the easiest attack surface in the paper. The three real sources are named (the enumerated unit is not the unit of variation; the frame moves; one read is noisy), and the constraint that descriptive counts carry no interval is new and binding |
| 2026-07-30 | **R10.4** | The **variance floor was written into the rule's body**; the coverage range was made consistent at 45%–82% | The floor was announced in this log on 29 July and implemented in `analysis.py` the same day, but the rule's text never stated it — the code was ahead of the pre-registration, which is exactly what makes a pre-registration unverifiable. The coverage figure appeared as both 45% and 46% in different places |
| 2026-07-30 | **R10.3** | Rewritten: of the three "observed signals" it named, **the PRM hash had been withdrawn by R10.2 and ASN is not collected** | The rule pointed at three cluster signals of which one was live. The PRM-hash clustering was deleted on 28 July and this rule kept citing it; ASN is uncollected, which R10.2's own closing sentence forbids from feeding any decision. The operative cluster variables are apex (R10.2) and the value-free fingerprint (R10.2b) |
| 2026-07-30 | **R9.6** | **New** — `template_placeholder` is a ninth relation class and is `UNSPECIFIED` in **both** C12 and C13 | The first real authorization-server metadata ever run through the instrument produced it. Microsoft's tenant-independent document returns `"issuer": "https://login.microsoftonline.com/{tenantid}/v2.0"`, a literal RFC 6570 placeholder, which the taxonomy classified as `same_host_different_path` → **`FAIL_MISIMPLEMENTED`**: a MUST-level violation published against the largest identity provider on the internet, in the check that is half the decisive measurement, weighted by an issuer concentration this study reports. It is not a violation — RFC 8414 §2 requires the `issuer` to be a **URL**, RFC 3986 §2 admits no braces, and Microsoft documents the endpoint as tenant-independent with substitution prescribed *instead of* exact match — so §3.3's comparison is ill-posed rather than failed, and R6 assigns that to us. The same host's tenant-specific document echoes its issuer byte for byte (captured as a control), which is what makes this a statement about one document rather than about the provider |
| 2026-07-30 | **R9.3 / R9.5** | The taxonomy has **nine** classes, not eight; `template_placeholder` does **not** enter the R9.5 sensitivity pair | The pair exists for classes where a defensible reading would convict; here no reading convicts, because the compared value is not an identifier. Counted and reported as its own quantity instead |
| 2026-07-30 | **C16 anchor** | Section reference corrected **§3 → §2.3**; `spec_url` now deep-links | RFC 9207 **§3 contains no MUST** — it defines the parameter and its false-by-default and nothing else. The sentence C16 is about is in **§2.3**: *"The server **MUST** indicate its support for the `iss` parameter by setting the metadata parameter `authorization_response_iss_parameter_supported` … to true."* Both the emitted `spec_ref` and the 2026-07-29 amendment row cited §3, and **every stored verdict carries the reference**, so a reviewer following it from the data landed on a section stating no obligation — the identical defect that pinned `SPEC_MCP` to a dated revision. The strength stays `SHOULD`, and the corrected citation is *why*: §2.3's MUST is conditioned on *"Authorization servers supporting this specification"*, so an absent flag means "does not support", which nothing forbids |
| 2026-07-30 | **C18 aggregation** | Endpoint-level verdict `any observed issuer` → **all observed issuers**, which is what the 2026-07-29 row already claimed | That row recorded C14 being changed to *"all declared issuers, **matching C16–C18**"*, but C18 was `if listed` — the document described a rule the code did not run, in R11.1's rank-2 headline candidate. The denominator stays `observed` rather than `declared` because R11.5 fixes it there for C18 alone. Affects only the secondary number: R11.5 makes the headline C18 rate per-issuer, computed in `analysis.py` from the stored documents, and that was already correct |
| 2026-07-30 | **R8 leg 1** | **Real-deployment negative controls added** to `tests/fixtures/` (five providers, documents captured verbatim, provenance and SHA-256 recorded) | All thirty prior fixtures used RFC 2606 synthetic hosts, so the pack proved the instrument **convicts** what the specifications forbid and never once that it **acquits** a deployment that is real and correct. A false-positive generator survives that suite untouched, and this repository has shipped one: C12's expected value was reconstructed from the wrong URL and reported a 75% violation rate, caught by hand-checking eight live endpoints rather than by any test. The controls found R9.6 on their first run. A control may claim `conforming` or `undecidable` and **never** `violating` — enforced by a test — because a control is the only fixture that names an identifiable third party |
| 2026-07-30 | **Scope / R4** | Recorded: **Okta and Auth0 tenants serve `User-agent: * / Disallow: /`**, so no verdict about either platform is observable to this instrument | Verified live against a trial Okta tenant and `login.auth0.com` on 2026-07-30. Our own robots policy (`ETHICS.md` §6) therefore excludes two of the most widely deployed hosted identity platforms; they leave every denominator as `ERROR` rather than scoring. This is not a defect to fix — R4 forbids writing our politeness policy up as the operator's failure — but it biases **issuer concentration** against exactly the platforms MCP servers are most likely to delegate to, and no control fixture for either can exist. Belongs in Limitations, and is written there |
| 2026-07-29 | **R7 revision set** | **MCP revision 2026-07-28 added** to the frozen set, and `draft-mcguinness-oauth-rfc9728bis-01` declared as a sensitivity arm | A revision shipped the day before the run — the exact event R7 was written to catch. It states *"Authorization servers should return the `iss` parameter per RFC 9207, and clients must validate it before redeeming a code"*, which makes C16 the ecosystem's newly-mandated control rather than a curiosity and lowers R11.3's "C16 may stick at 100%" risk; and it **formally deprecates Dynamic Client Registration in favour of CIMD**, which is C17's population. Separately, the rfc9728bis draft would relax the identical-match rule C12 and R9 rest on to same-origin plus path-prefix. It is not adopted, so the frozen anchor holds, but a rule this study depends on being under active revision must be declared rather than discovered by a reviewer |
| 2026-07-29 | **Request scope** | Declared issuers are fetched only over `https` to a public registrable domain, and **at most 10 per endpoint** | `authorization_servers` is an arbitrary-length list written by the measured party; the loop iterated all of it at up to three candidate URLs each, with no host restriction. A document declaring 200 issuers commanded 600 requests aimed wherever it chose, and plain HTTP, loopback and RFC 1918 targets were accepted — from a residential line. The bounds published in `README.md` and `ETHICS.md` §10 were therefore false and have been rewritten to what the code enforces. Issuers we decline to request are recorded as declared and scored as our uncertainty (R6), never as the operator's non-conformance (R4) |
| 2026-07-29 | **Spec URLs** | `SPEC_MCP` pinned from `/latest/` to the dated **2025-06-18** revision; every fixture repinned | R7 freezes the revision set by date precisely so a specification published on the day of the run cannot be swallowed silently — and `/latest/` now resolves to **2026-07-28**, outside the frozen set, which moved the authorization text onto sub-pages. Every stored verdict records this URL, so an unpinned anchor meant a reviewer following the link from the data found a page without the quoted sentence |
| 2026-07-28 | **R9.2–R9.5** | **Corrected the same day** — `trailing_slash_only` was downgraded from `FAIL` to `UNSPECIFIED` in C12; `case_only` was split in two and the path/query difference made `FAIL`; RFC 3986 §6.2.2.1/§6.2.3 and RFC 9728 §6 were added as anchors | The second review round showed that the first version of R9 **contradicted its own test suite**: two documents served from the same metadata URL received opposite verdicts. The §3.1 mapping is lossy, so the back-derivation is not single-valued. Detail in R9.4 |

---

## R1 — Normative strength rule ⚙️ *(machine-enforced)*

A check may return `FAIL_UNIMPLEMENTED` or `FAIL_MISIMPLEMENTED` only if its `spec_ref`
points at a sentence at **MUST / SHALL** level.

| Specification strength | Heaviest permitted outcome |
|---|---|
| MUST / SHALL | `FAIL_*` |
| SHOULD | `UNSPECIFIED` |
| MAY / silent | `NOT_APPLICABLE` |

`CheckResult.model_post_init` validates this and raises `ValueError` on violation.

**Consequence:** C02 (A2A `signatures` OPTIONAL), C08 (DPoP/mTLS not mandatory), C09 (no
specification requires an agent identity to be revocable), C16 (RFC 9700 §2.1 makes the
mix-up defence REQUIRED of the *client*, whom a passive probe cannot observe), C17 (MCP
permits a registration ladder that ends at "prompt the user"), C18 (RFC 9728 §4 is
OPTIONAL) **cannot report a failure by definition**. They are in the `DESCRIPTIVE_ONLY`
set; they are reported as prevalence statistics and are not made funnel stages.

This list is the exact contents of `DESCRIPTIVE_ONLY` in `models.py` and must stay that
way: until 29 July 2026 it named C10, deleted on 28 July, and omitted C16, C17 and C18 —
the three checks R11's first, second and fifth headline candidates are built on. A reviewer
checking R1 against the code found one phantom and three absences in the rule that decides
which checks are allowed to penalise anybody.

---

## R2 — Outcome precedence ⚙️

When several observations for one check conflict:

```
ERROR > NOT_APPLICABLE > UNSPECIFIED > FAIL_MISIMPLEMENTED > FAIL_UNIMPLEMENTED > PASS
```

Applied by `resolve_precedence()`. Rationale: we never report something we cannot know as a
violation.

---

## R3 — Malformed document vs. missing document

| Observation | Outcome |
|---|---|
| HTTP 200 + JSON that does not conform to the specification or cannot be parsed | `FAIL_MISIMPLEMENTED` |
| HTTP 404 / 410 | `FAIL_UNIMPLEMENTED` |

No exceptions. There is no "broken but well-intentioned" category.

---

## R4 — A block is not a finding

403, 429, a WAF/Cloudflare interstitial, a CAPTCHA, a TLS handshake refusal → **`ERROR`**,
never `FAIL_UNIMPLEMENTED`.

This is critical: counting blocked responses as failures produces a bias correlated with
exactly the property we are measuring (mature and enterprise endpoints are the ones behind
WAFs). The block-detection heuristic lives in `fetcher.py` and is fixed before collection.

---

## R5 — When an ERROR becomes final 📋 *(run protocol)*

An `ERROR` becomes final only when, after `max_retries` is exhausted, it produces the same
result in **at least 2 separate runs ≥24 hours apart**. Single-run ERRORs are reported
separately in the analysis and removed from the denominator.

**Executed by `agent-id-probe reconcile --run-id <a> --against <b>`**, which writes
`reconciliation.json` beside the later run and exits non-zero when the two runs are closer
together than 24 hours. The marker stays 📋 because the part that cannot be machine-enforced
is the part that matters: no code can make the second run happen a day later. What code does
is classify and check.

Four things the sentence above does not settle, fixed before the census rather than while
reading its output:

* **The unit is both levels.** `runner.summarise()` drops errors twice — the first funnel
  stage on `reachable`, every later stage on that stage's check outcome — and they are not
  the same set. Both are reconciled, and they are **counted in separate tables**: an
  unreachable endpoint contributes one reachability unit *and* one unit per check, so a
  single total would multiply it by six and call the result an error count.
* **Our own exclusions are a third class, never "persistent".** An opt-out, a `robots.txt`
  exclusion and the per-host request ceiling all produce `ERROR` and all three reproduce in
  run 2 with near-certainty, so on outcome alone they are indistinguishable from a host that
  is genuinely and stably unreachable. On the two rehearsal runs this class holds **17 of the
  30** unreachable endpoints — every one of them `robots.txt` — so counting it would report
  **30 confirmed errors instead of 13**. R5 also has nothing to reconcile there: it confirms
  an error by re-asking, and for an opted-out operator re-asking is the promise being broken.
  A block (`ErrorKind.BLOCKED`) is deliberately *not* in this class: a WAF is the operator's
  infrastructure answering, and whether it is stable across a day is exactly what R5
  establishes.
* **"Not scored in both runs" is not "recovered".** An endpoint the corpus no longer
  contains, one the per-host sample dropped (R10.6), or one the kill switch never reached is
  reported as `unreconciled`. Sixteen of the rehearsal's endpoints are in this state. Calling
  them transient would count our own truncated run as evidence that hosts recovered.
* **The interval comes from `probed_at`, never from the manifest.** `probe` writes no
  manifest, so the `started_at` in a probed run's directory is `collect`'s — in
  `results/runs/slice2/` it is byte-identical to `slice`'s and still says `"run_id": "slice"`.
  `rescore` is worse: it writes a fresh manifest stamped with the current time over verdicts
  copied from stored bytes, so a replay taken a day after its source would present as two
  runs 25 hours apart in which every error recurred.

---

## R6 — Our own uncertainty is UNSPECIFIED ⚙️

If two reasonable readings of the specification produce different verdicts for one
observation, the outcome is automatically `UNSPECIFIED` — not our preference.

Known example: the exclusion of fields carrying default values from RFC 8785 JCS
canonicalisation is not settled in the A2A specification. This class is therefore a candidate
for producing a false `FAIL_MISIMPLEMENTED` in C04 and is routed to `UNSPECIFIED` from the
outset.

`UNSPECIFIED` findings are the paper's **normative contribution**: they are returned to the
standards bodies (A2A, MCP, OpenID Foundation, IETF OAuth WG) as a catalogue of ambiguous
clauses.

---

## R7 — Version pinning 📋 *(run protocol — the ⚙️ marker was dropped on 29 July 2026)*

> **⚠️ One branch of this rule is not implementable in the current design, and we are
> obliged to write that down.**
>
> R7 says "every endpoint is scored against the specification revision it declares" and
> claimed `⚙️`, machine-enforced. **`CheckResult.spec_version` is set nowhere.**
>
> **⚠️ The first version of this note said "the only way to learn it is `initialize`". That
> was wrong, and verifiably wrong** (corrected 29 July 2026). MCP Streamable HTTP carries
> the identical sentence in both frozen revisions:
>
> > *"If the server receives a request with an invalid or unsupported
> > `MCP-Protocol-Version`, it **MUST** respond with `400 Bad Request`."*
>
> So an **inference channel does exist**: send requests with different version headers and
> see whether a 400 comes back. Our reason for not using it is not impossibility, but
> these: (a) it is a **probe**, not a *reading of a declaration* — the specification does
> not ask the server to advertise a version, we infer it; (b) one extra request per
> endpoint per revision, that is ~5,000 further requests to third parties; (c) the decision
> population is the endpoints that return 401, and if the authorization check runs before
> the version check the answer is 401 and nothing is learned — the same argument that cut
> #24 applies here too.
>
> **Consequence:** because no declaration is read, every endpoint is scored against the
> **most permissive** revision of the frozen set below. Doubt favours the deployment.
>
> **And this has a cost, which is written into Limitations.** The same section also says:
>
> > *"if the server does **not** receive an `MCP-Protocol-Version` header … the server
> > **SHOULD** assume protocol version `2025-03-26`."*
>
> Our probe does not send that header, so a conforming server processes our request as
> **2025-03-26** — a revision that is **not** in the frozen scoring set. Sending the header
> is not a fix but worse: a server that does not support it returns **400** as the MUST
> requires, and breaks the measurement. This asymmetry is on record; because scoring uses
> the most permissive revision, the direction again favours the deployment.
>
> The only visible effect of this is C07: because its normative strength depends on the
> revision (2025-06-18 MUST, 2025-11-25 "one of"), a declaration that cannot be read drops
> it permanently to the permissive reading and C07 cannot penalise. `spec-mapping.md`
> already records it this way.

---

### R7 (the rule text)

Every endpoint is scored against **the specification revision it declares**
(`CheckResult.spec_version`). MCP 2025-11-25 and 2025-06-18 have different requirements;
mixing revisions means measuring specification change rather than the ecosystem.

If there is no declaration: the endpoint is scored not against the latest revision in force
on the measurement date but against **the most permissive revision in force**. Doubt favours
the deployment.

**The revision set is pinned by date.** The phrase "revision in force" silently swallows a
revision published on the day of the run and effectively voids the freeze. The scoring base
of this study is: **MCP `2025-06-18` and `2025-11-25`; the published versions of RFC 9728,
RFC 8414 and RFC 8707; A2A v0.3.** No revision published after this set enters scoring; if a
new revision appears within the measurement window it is named in Limitations, not added to
the rule.

---

## R8 — Instrument validity: fixture suite + replay determinism ⚙️

*This rule was rewritten on 28 July 2026. Its previous version required two independent human
coders and Cohen's kappa. That is the validity instrument of a design that **scores a
rubric**, and it does not fit ours: the checks here are mechanical (`declared == expected`)
and contain no human judgement, so inter-rater reliability is not a quantity there is
anything to measure. Reporting kappa would present a subjectivity that does not exist as
though it did.*

The validity of a mechanical conformance instrument rests on three legs:

1. **Conformance fixture suite.** For every MUST-level check there is at least one
   **known-conforming** and one **known-violating** fixture derived from the specification
   text (`tests/fixtures/`). If the instrument cannot classify these correctly, no data is
   collected. Edge cases (trailing slash, case, same host different path) stand as separate
   fixtures.
2. **Replay determinism.** The same raw artefact, rescored without touching the network,
   must produce a **bit-identical** verdict. Because every raw response is stored, this is
   tested automatically (`test_replay_determinism`).
3. **Machine enforcement of R1.** `CheckResult.model_post_init` refuses to let a check
   without a MUST anchor report a failure. That is the only door subjectivity could enter
   through, and it is shut.

**Measurement:** 100% accuracy on the fixture suite plus replay determinism. If either fails,
the instrument is fixed and all data is rescored (which is free, because the raw data is
stored).

---

---

## R9 — Identifier comparison policy ⚙️ *(machine-enforced)*

C12 and C13 are the paper's decisive measurement, and both reduce to the question "are these
two URIs identical". How that comparison is made determines the headline violation rate
directly. The policy is fixed here, before the main run.

### R9.1 — The expected value is derived from **the URL the document came from**

> RFC 9728 §3.3: *"The `resource` value returned **MUST** be identical to the protected
> resource's resource identifier value **into which the well-known URI path suffix was
> inserted to create the URL used to retrieve the metadata**."*
>
> RFC 9728 §3.1, **including the conditional clause** (if that condition is dropped, the
> rule reads as though it applied to the root form as well): *"**If the resource identifier
> value contains a path or query component**, any terminating slash (/) following the host
> component **MUST** be removed before inserting `/.well-known/` and the well-known URI path
> suffix between the host component and the path and/or query components."*

The expected value **cannot** be derived from the endpoint's raw URL — it depends on which
candidate location the document came from:

| Where the document came from | Expected `resource` value |
|---|---|
| `https://h/.well-known/oauth-protected-resource/p` | `https://h/p` |
| `https://h/.well-known/oauth-protected-resource` (root) | `https://h` |
| `WWW-Authenticate: resource_metadata=...` hint | **the URL the client sent to the resource server** (RFC 9728 §3.3 ¶2) |

The rule is **literal and admits no exception**: the expected value is always derived from
the URL the document came from. If the fallback landed on the root form while the endpoint
URL carries a path (e.g. endpoint `https://h/sse`, document served from the root,
`resource: "https://h"`), that is **not a C12 failure** — the document is internally
consistent, and MCP explicitly mandates the fallback to the root form:

> MCP Authorization: *"clients … **MUST** fall back to constructing and requesting the
> well-known URIs in the order listed above"* (path-suffixed first, then root).

Whether that document actually covers the path-carrying endpoint is a separate question,
recorded **descriptively** as `prm_scope_covers_endpoint`; it carries no penalty. RFC 9728
§7.6 has already put this choice explicitly out of scope (*"out of scope for this
specification"*), so deriving a MUST-level violation from it would contradict R1.

**Rationale (why this rule was needed):** before the correction the expected value was
produced once from the raw endpoint URL. Measured on 8 large live MCP endpoints: the C12
violation rate came out at **75%**, and **25%** under the correct rule. The difference was
entirely instrument error.

### R9.2 — Canonicalisation is applied to **both sides**

Before comparison, **both sides** receive only the normalisations RFC 3986 declares
equivalent:

| Operation | Basis (verbatim) |
|---|---|
| The fragment is dropped | RFC 8707: an identifier contains no fragment |
| The scheme's default port is dropped (`:443`/`:80`) | RFC 3986 §6.2.3 scheme-based normalisation |
| Scheme and host are lowercased | RFC 3986 §6.2.2.1: *"the **scheme and host** are case-insensitive and therefore should be normalized to lowercase"* |
| The root path `/` and the empty path are equated | RFC 3986 §6.2.3: *"the following four URIs are equivalent: `http://example.com` / `http://example.com/` / …"* |

**Path and query are not lowercased.** The same RFC 3986 §6.2.2.1 sentence continues: *"The
other generic syntax components are assumed to be **case-sensitive** unless specifically
defined otherwise by the scheme."* Lowercasing the whole URI would forgive `/MCP` against
`/mcp`; those are different paths.

Applying it to one side only drops a conforming server into the heaviest bucket of the
taxonomy.

### R9.2b — The strictness rule has **two** anchors, and both are cited

Quoting RFC 8414 §4 for C13 while skipping RFC 9728's identical rule for C12 would be
asymmetric, and it would be the natural target of the objection "you chose the threshold in
your own favour". Both are written down:

> RFC 9728 **§6 "String Operations"**: *"Unicode Normalization **MUST NOT** be applied at any
> point… Comparisons between the two strings **MUST** be performed as a Unicode
> code-point-to-code-point equality comparison."*
>
> RFC 8414 **§4**: the same three-step procedure, in identical wording.

So in both checks the comparison is **code-point equality**; the normalisations in R9.2 are
not an exception to that rule but RFC 3986's definition of *what the compared value is*.

### R9.3 — Taxonomy of the remaining difference and its outcome mapping

The difference remaining **after** canonicalisation is classified as follows and produces
these outcomes:

| Relation | C12 | C13 | Basis |
|---|---|---|---|
| `identical` | `PASS` | `PASS` | — |
| `template_placeholder` | **`UNSPECIFIED`** | **`UNSPECIFIED`** | **R9.6 — the compared value is not a URI, so §3.3's comparison is ill-posed rather than failed** |
| `trailing_slash_only` | **`UNSPECIFIED`** | `FAIL_MISIMPLEMENTED` | **R9.4 — the asymmetry comes from the specification, not from a choice** |
| `case_path_only` | `FAIL_MISIMPLEMENTED` | `FAIL_MISIMPLEMENTED` | RFC 3986 §6.2.2.1: path/query are **case-sensitive**; `/MCP` ≠ `/mcp` |
| `scheme_only` | `FAIL_MISIMPLEMENTED` | `FAIL_MISIMPLEMENTED` | §3.3; also MCP *"endpoints **MUST** be served over HTTPS"* |
| `port_only` | `FAIL_MISIMPLEMENTED` | `FAIL_MISIMPLEMENTED` | §3.3 (default ports were already dropped in R9.2; only a real port difference lands here) |
| `same_host_different_path` | `FAIL_MISIMPLEMENTED` | `FAIL_MISIMPLEMENTED` | §3.3 |
| `related_host` | `FAIL_MISIMPLEMENTED` | `FAIL_MISIMPLEMENTED` | §3.3 |
| `unrelated_host` | `FAIL_MISIMPLEMENTED` | `FAIL_MISIMPLEMENTED` | §3.3 |

**Ordering:** within the same host the heaviest component is named — scheme → port → path. On
a different host, `related_host` if there is a sub/parent domain relationship,
`unrelated_host` otherwise.

`unrelated_host` **cannot be a fall-through bucket.** Every distinguishable class of
difference gets its own name; the paper's rhetorical punch (*"an unrelated resource declares
the same issuer"*) cannot come out of an `else` branch. Before the correction,
`https://a.com:443/mcp` vs `https://a.com/mcp` — that is, a fully conforming server — fell
into the `unrelated_host` bucket.

### R9.4 — C12 and C13 use the same taxonomy but diverge on `trailing_slash_only`

**This divergence is not a preference but a difference in measurability.**

**In C12 the expected value is not observed but back-derived — and the derivation is lossy.**
Because RFC 9728 §3.1 removes the terminating slash **before** inserting the well-known
suffix, `https://h/mcp` and `https://h/mcp/` are served from the **same** metadata URL. What
is back-derived from the URL the document came from is therefore not a *value* but **a
two-element set**:

- A server whose real identifier is `/mcp/` echoes `/mcp/` and **fully conforms** to §3.3.
- A server whose real identifier is `/mcp` echoes `/mcp/` and **violates** §3.3.

The instrument **cannot tell these two apart**. Penalising a class it cannot distinguish is a
direct violation of R6 ("our own uncertainty is UNSPECIFIED") — and it would add an
undecidable mass to the headline violation rate. That was the easiest target for the
objection "you chose the threshold in favour of the result".

**C13 has no such problem.** The left-hand side of the comparison — the issuer string — is
**read literally** from the resource's own `authorization_servers` array. No back-derivation,
no loss. RFC 8414 §3.3 requires identity against an observed value and §4 says code-point
equality: a trailing-slash difference is **a real, mechanically detectable MUST violation**
and it does in fact break the client's discovery chain.

*(Note: a slash difference at the root level — `https://h` ↔ `https://h/` — is eliminated by
the canonicalisation in R9.2 in both checks; RFC 3986 §6.2.3 already declares them
equivalent. R9.4 concerns only the slash difference in **path-carrying** identifiers.)*

### R9.5 — Pre-declared sensitivity pair

The C12 rate is reported as **two numbers**: the case where `trailing_slash_only` counts as
UNSPECIFIED (the headline, R9.3) and the case where it counts as a violation (the strict
arm). The difference between them is visible in the paper; a reader can apply their own
reading. **The headline is the UNSPECIFIED one** — because the strict arm counts as a
violation a class the instrument cannot distinguish.

Classes such as `case_path_only` and `port_only` do not enter the sensitivity pair: they are
real differences remaining after canonicalisation, not ambiguity.

### R9.7 — "Not creditable" and "forbidden" are different findings, and only one convicts

**Added 30 July 2026.** C15 rested on *"RFC 7518 / BCP 195"* for three conditions and the
citation supported one. The rule generalises past C15, because the same confusion is available
anywhere the instrument declines to credit something:

| Condition | Anchor | Binds | Verdict |
|---|---|---|---|
| RSA key < 2048 bits | RFC 7518 **§3.3**: *"A key of size 2048 bits or larger **MUST** be used with these algorithms."* | the **signer** | `FAIL_MISIMPLEMENTED` |
| `alg: none` | RFC 7518 §3.6's MUSTs bind an implementation *accepting* an unsecured JWS | the **verifier** | `UNSPECIFIED` |
| `HS*` against a published JWKS | §3.2 sets a key *size*, not a publication rule; RFC 8725 would forbid it but governs **JWTs** | nobody we observe | `UNSPECIFIED` |

Three things this settles:

**BCP 195 was the wrong document.** It is about TLS. It appeared in the `spec_ref` of every C15
verdict, pass or fail, and nothing in the suite ever read that string.

**RFC 8725 cannot be borrowed.** It is a BCP about JSON Web *Tokens*; an A2A agent-card
signature is a detached JWS over a JCS-canonicalised card with no claims set. This is the
question that was outstanding with referee #3, and the answer is that the detached-JWS
distinction does break the borrowing.

**Declining to credit is not convicting.** Verification is still never *attempted* under `none`
or a published symmetric key — a signature anyone can forge is not evidence of a binding, and
crediting it would inflate C04. That decision is about what may count as evidence *for* us. It
required no MUST. Writing a MUST-level failure against the publisher is a different act, and it
did.

The immediate consequence was a false statement, which is why the rule is worth stating rather
than just fixing: with `none` and `HS*` no longer failing C15, the skipped-verification path
reached C04's failing branch, which reports *"key resolved but no signature verified over the
JCS payload"*. For an undersized RSA key that sentence is simply untrue — the signature
verifies, and the defect is the key length. Nothing had observed a verification failure; we had
declined to look. R6 sends that to `UNSPECIFIED`, and C04's remaining failing branch now cites
**A2A §8.4** (*a signed card MUST be verifiable against a discoverable key*) alongside RFC 7515
§5.2, because §5.2 on its own binds the verifier and would have fallen to this same objection.

### R9.6 — A templated identifier is its own class, and it is `UNSPECIFIED` in both checks

**Added 30 July 2026, from a live document rather than from reasoning.** The first real
authorization-server metadata ever run through this instrument produced it. Microsoft's
tenant-independent document at
`login.microsoftonline.com/common/v2.0/.well-known/openid-configuration` answers:

```json
"issuer": "https://login.microsoftonline.com/{tenantid}/v2.0"
```

Compared as a URI that is `same_host_different_path`, which R9.3 maps to
`FAIL_MISIMPLEMENTED`. So the instrument, unamended, would have published **a MUST-level
violation against the largest identity provider on the internet** — and C13 is half the
decisive measurement, while issuer concentration is a quantity this study reports, which means
the largest providers weight the result most.

**Why this is not a violation.** RFC 8414 §3.3 compares the returned value against *"the
authorization server's **issuer identifier** value into which the well-known URI string was
inserted"*. Two things have to hold for that comparison to have a left-hand side, and neither
does:

1. **The returned value is not a URI.** RFC 8414 §2 defines `issuer` as *"the authorization
   server's issuer identifier, which is a **URL**"*, and RFC 3986 §2 admits neither `{` nor
   `}` anywhere in the URI grammar. So the document is not conforming authorization-server
   metadata — but it is also not a *mismatched identifier*, which is the only thing §3.3
   knows how to be violated by.
2. **The publisher does not claim it is one.** Microsoft documents the endpoint as
   tenant-independent: *"Microsoft Entra ID exposes tenant-independent versions of the OIDC
   document … These endpoints return an issuer value, which is a template parametrized by the
   `tenantid`"*, and prescribes substitution **instead of** the exact match OpenID Connect
   Core requires. It is metadata for a *family* of issuers, served at the location RFC 8414
   reserves for one.

**And the provider is measurably not misimplementing.** The control fixtures capture the same
host answering for a concrete tenant
(`/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0/`) and it echoes its issuer byte for byte. The
templated document is a separate, deliberate artefact, not a broken one.

**So R6 applies:** our own inability to decide is `UNSPECIFIED`, and R9.3's rule that *every
distinguishable class gets its own name* gives it `template_placeholder` rather than letting it
fall into a heavier bucket. This is the same construction that produced `trailing_slash_only`,
with one difference: `trailing_slash_only` is ambiguous because **our reconstruction** of the
expected value is lossy, so R9.4 confines it to C12. Here the ambiguity is in **the document**,
so it applies to C12 and C13 alike.

**Detection is syntactic and vendor-neutral**, which is not a stylistic choice: a host
allowlist would be the hand-written rubric R10.2 was rewritten to eliminate, and it would make
the rule silently wrong for every other multi-tenant platform. The test is that the value is a
template *of the identifier that was requested* — same scheme, authority and query, the same
number of path segments, differing only in whole segments that are `{…}` placeholders standing
in for non-empty segments. A value carrying a brace that is **not** such a template keeps its
ordinary relation and its ordinary verdict, because then the two differ in more than the
parametrised part. Both directions are pinned in `tests/test_checks_oauth.py`: a forgiving rule
needs its refusals tested harder than its acceptances, since every case it wrongly forgives is
a violation the study stops reporting.

**What is reported.** Not a violation count but a count of this class, and the attribution
matters: the party that turned a documented template into a broken discovery chain is **the
resource server that named it in `authorization_servers`**, not the provider. A conforming MCP
client reaching that document *must discard it* (§3.3: *"the data contained in the response
**MUST NOT** be used"*), and the only way to use it is a vendor-specific substitution rule that
no MCP revision mentions. That is a concrete, citable harm — reachable without accusing anyone
of non-conformance — and the paper's §8 has been short of exactly one of those.

---

## R10 — Unit of analysis and cluster definition ⚙️

Endpoints are not independent: they run on a handful of SDKs, hosting platforms and bulk
publishers. Choosing the cluster definition after the data is open to the objection "you
chose the clustering that gave you the confidence interval you wanted", and it erases
everything R1–R8 gained.

### R10.1 — Three units, all three reported for every headline rate

No rate is published as a single number. Each is given in three units **in the same table**:

1. **per endpoint** — each endpoint is one observation; the interval is clustered by apex
2. **per apex domain (eTLD+1)** — **1 endpoint** per apex · **primary unit (R10.2)**
3. **per implementation cluster** — **1 endpoint** per fingerprint (R10.2b)

**When the unit changes, the denominator changes too, not only the interval.** In 2 and 3 the
population is narrowed first; otherwise a bulk publisher with 300 listings would still
determine the point estimate, and only the confidence interval would notice. Which endpoint
represents an apex is **fixed in advance: the smallest `endpoint_id`.** It is an arbitrary
rule, but an arbitrary rule declared in advance is better than a defensible rule chosen
afterwards.

**The known bias of the apex, written down now.** The private section of the public suffix
list is kept off, so `a.vercel.app` and `b.vercel.app` count as the same apex. One platform
tenant delegating to another tenant's issuer therefore looks like the **same operator** → the
cross-operator rate is **under**estimated. The direction is conservative (it does not inflate
the finding), but a reviewer will find it if it is not written down.

### R10.2 — Primary unit of analysis: the apex domain

**Primary unit = the apex domain (eTLD+1), at most 1 endpoint per apex.** It is the only unit
that is fully observed, deterministic, already collected, and independently auditable by a
reader.

> **⚠️ This rule was changed on 28 July 2026, on the same day.** Its first version defined
> the primary cluster as *"the SHA-256 of the byte form of the PRM document after
> host-specific values have been replaced by placeholders"*. It **was not implementable** for
> four independent reasons and fell in the second review round:
>
> 1. *"Which fields are host-specific"* is a human decision — that is, a hand-written list.
>    In the same sentence the rule said it *"requires no hand-written list and therefore
>    cannot be the authors' rubric"*; it refuted itself, and R10.3's prohibition applied to
>    it too.
> 2. **No resolution.** A conforming PRM document is typically 2–4 keys. With the values
>    removed, thousands of endpoints collapse into a handful of hashes, `m ≈ 3–8`, and
>    R10.4's `t(m-1)`-based interval widens to unusable. R10.2 made R10.4 effectively
>    impossible.
> 3. **Over-fragile at the same time.** The byte form is a property of the *serialiser*, not
>    of the producer: the same SDK emits different bytes behind Cloudflare Workers and
>    directly → one producer splits into several clusters. It clustered both too little and
>    too much.
> 4. It was never in the code.

### R10.2b — Implementation cluster (sensitivity arm): a value-free fingerprint

The secondary clustering is derived from a deterministic fingerprint that **contains no
values**:

```
fingerprint = SHA-256( JCS( {
  "prm_keys":  <PRM top-level member names, sorted>,
  "prm_types": <JSON type of each member, in the same order>,      # "string" | "array<string>" | ...
  "as_keys":   <member names of the first observed AS metadata, sorted>,   # [] if not observed
  "server":    <`server` header of the PRM response, lowercased, "" if absent>
} ) )
```

**No value ever enters** → no placeholder list is needed → the "authors' rubric" objection is
structurally closed. This is the property the first version of R10.2 *claimed* but could not
deliver. The key set plus the types survives re-serialisation while still separating
different SDKs. The `server` header is the one hand-made decision; **both variants, with and
without it, are reported together.**

**Other sensitivity arms** (all reported separately): the registry publisher namespace
(`io.github.<user>/…`, verified by the registry via DNS/OAuth) · ASN · TLS certificate hash ·
the declared issuer.

**An arm that cannot be collected cannot carry a criterion.** ASN and certificate comparison
are not in the code at present. Until they are collected these are *reported* as sensitivity
arms and can be the input to no decision rule — go/no-go included. This prevents a repeat of
the mistake that voided the old go/no-go criterion (resting on an unmeasured quantity).

`serverInfo` is **not** a cluster variable: endpoints that require OAuth answer 401 to
`initialize` as well, so it cannot be obtained for the decisive population.

### R10.3 — A hand-written platform list cannot be a cluster variable

`_KNOWN_PLATFORM_SUFFIXES` is for **labelling** only, never for clustering: a list of
platform suffixes written by the authors is the authors' rubric, which is the objection
R10.2 was rewritten to eliminate.

The hosting class is derived from observed signals. **Amended 30 July 2026:** this rule named
three, of which two do not exist. The *PRM hash* was the clustering deleted by R10.2 on
28 July, so it survived here as a reference to a rule that had been withdrawn; and *ASN* is
not collected at all, which R10.2's own closing sentence forbids from feeding any decision.
What remains and is real is the **shared TLS certificate**, collected but not compared, and
therefore also a sensitivity arm rather than an input. The operative cluster variables are
the two in R10.2 and R10.2b — apex domain and the value-free implementation fingerprint — and
this rule now says so instead of pointing at three signals of which one was live.

### R10.4 — Uncertainty is reported against the number of clusters

The cluster-robust confidence interval for a rate is `t(m-1)`-based because `m` is small;
when `m < 30` it is also given by a wild cluster bootstrap-t (Rademacher). Every rate is
written with `m` (the number of clusters), DEFF and `n_eff` beside it. The naive Wilson
interval is **not published on its own**: under clustering its real coverage is not 95% but
**20%–88%**, depending on the scenario — at `m = 300` clusters with a shared SDK default it is
**20%**. The figure is produced by `scripts/wilson_coverage_under_clustering.py`, seeded, over a
grid that deliberately includes the friendly shapes; `tests/test_analysis.py` holds the quoted
range against what the script computes.

**The variance floor.** *(Written into the body 30 July 2026. The floor was announced in the
amendment log on 29 July and implemented in `analysis.py` the same day, but the rule's own
text never stated it — so for a day the code was ahead of the pre-registration, which is
precisely the direction that makes a pre-registration unverifiable.)*

A published interval **may not be narrower than the simple-random-sample interval for the
same `k` and `n`.** Clustering may only widen. The between-cluster estimator omitted
within-cluster binomial variance, so `n_eff` could exceed `n` — by a factor of 313 in the case
found — and at `n = 1000` an interval of `49.9% [49.7%–50.1%]` was publishable. Equality
guards are not sufficient here and the first attempt used one: a `var == 0.0` test is passed
by a single endpoint's worth of drift. The floor is therefore a floor and not a special case,
and the bootstrap carries a zero-width guard for the same reason.

### R10.5 — What the intervals are uncertainty *about*, given that the corpus is a census

**New, 30 July 2026, written before the data.** The corpus is a complete enumeration of the
registry frame at one instant, not a sample drawn from it. Sampling error over a complete
enumeration is zero, so reporting a confidence interval requires saying what varies — and
leaving that unstated would let the intervals be read as sampling error, which would be the
single easiest thing in this paper to attack.

None of the three sources of uncertainty reported is sampling error:

1. **The enumerated unit is not the unit of variation.** What varies independently is
   implementations and operators, not endpoints: an SDK's default document is reproduced by
   every deployment using it, and a bulk publisher's hundreds of listings are one
   configuration decision recorded many times. Even with every endpoint in hand the number of
   independent realisations is `m`, not `n`. This is why R10.1 reports three units and why
   R10.4 prints `m`, DEFF and `n_eff` beside every rate: they are the quantity, not
   diagnostics of it.
2. **The frame moves.** Endpoints are registered and withdrawn continuously, so the snapshot
   is one realisation of a process. The estimand is the process's propensity.
3. **One read of the frame is noisy.** Blocking, rate limiting and transient outages mean the
   observed value is a noisy measurement even of the instant it describes — which is what R5's
   two runs at ≥24 hours exist to bound.

**Two binding consequences:**

- A quantity offered as a **description of the snapshot** — *"`k` of `n` endpoints in this
  snapshot declared an issuer they do not operate"* — is published as a count with **no
  interval**. There is nothing to be uncertain about, and attaching one would misrepresent
  what was measured.
- An interval is attached only to a rate offered as an estimate of a propensity, and it
  licenses **no** generalisation beyond the frame. Uncertainty about registered endpoints is
  not uncertainty about deployed ones; the frame's relationship to the ecosystem is a
  limitation, not an interval.

**Qualified by R10.6 the same day.** The census claim above is exact at the hostname, apex and
implementation units and **no longer exact at the endpoint unit**: R10.6 caps the endpoints
measured on any one hostname at 25. Every hostname in the frame is still enumerated, so
point 1 above is untouched — the unit that varies is the operator, not the listing, and the
capped hostnames are precisely those where the extra listings carry no extra realisation. But
the first binding consequence has to be read with that in mind: an endpoint count is a count
over the sample, the sampling fraction is recorded in `sampling.json` and derivable from
`corpus.jsonl`, and a rate at the endpoint unit is reported with the exclusion beside it.

---

### R10.7 — Protected-resource metadata is looked for whether or not the endpoint challenged

**New, 30 July 2026, written before the census and after the narrow-slice rehearsal.**

The metadata locations in RFC 9728 §3.1 are requested for **every reachable endpoint**, not
only for those answering 401 or 403. The verdicts do not change: an endpoint that neither
challenged nor publishes metadata remains `NOT_APPLICABLE`, and **C05 can still only convict
an endpoint that challenged**. What changes is what is observed before that conclusion is
drawn.

**The defect this repairs.** Until now `probe_oauth` returned before issuing any request
unless the endpoint answered 401 or 403, so a challenge was the only entry into the OAuth
funnel. The rehearsal measured what that discarded, over 164 reachable endpoints:

| Answer to our GET | n | Publish protected-resource metadata |
|---|---|---|
| 401 / 403 — challenged | 50 | **37** (the control: this is the group the instrument already saw) |
| 405 / 406 — method-gated | 59 | **11** |
| 200 — served | 32 | **16** |

`405 Method Not Allowed` is what a server returns when it routes on HTTP method before it
consults authorization, so our GET never reached the layer under measurement. The
undetermined group was **larger than the denominator**, and membership in it was decided by a
framework's middleware order rather than by anything about authorization — a selection whose
direction cannot be signed. **27 endpoints were declaring an authorization server, in a
document at a well-known path, while the instrument recorded them as endpoints that do not
use authorization and never looked.** Evidence: `docs/method-gate-probe.json`, produced by
`scripts/measure_method_gate.py`.

**Why this does not manufacture the result.** The tempting repair — define the denominator as
"challenged **or** publishes metadata" — is circular for C05, whose numerator is *publishes
metadata*; it would drive that rate up mechanically. It is refused. C05's denominator stays
the endpoints that challenged. The population that grows is the one carrying **C12 and C13**,
whose denominator is *documents we have read* rather than a posture we inferred, and which
are therefore immune to this bias in a way C05 is not. In the rehearsal that population goes
from 36 to roughly 64.

**What it costs.** Two extra requests against endpoints that turn out to publish nothing, at
paths already declared in `ETHICS.md` §3 and already requested against other endpoints. No
POST, no protocol interaction, no authorization attempt — the passive claim is unaffected,
which is the distinction that made this measurable at all where job #24's `initialize` harvest
was not.

---

### R10.6 — Endpoints on one hostname are sampled, and the remainder is a named exclusion

**New, 30 July 2026, written before the census and after the narrow-slice rehearsal.**

At most **25** endpoints per hostname are measured, chosen by ascending `endpoint_id` — a
SHA-256 prefix of the URL, so the choice is deterministic, independent of registry pagination
order, and reproducible without a stored seed, as R8 requires. Endpoints beyond the cap are
**not attempted**. They are counted per hostname, written to `sampling.json`, and reported in
the exclusion ledger as *not sampled*: a decision of ours, never an observation of an operator.

**Why the rule exists.** `RatePolicy.max_requests_per_host` caps one host at 30 requests per
pass, which is the promise this study makes to third parties who never consented to being
probed. The rehearsal showed that promise and the corpus are incompatible as configured:
10,653 endpoints sit on 7,681 hostnames, but 2,015 of them are on the eleven hostnames with
more than thirty each, and `gateway.pipeworx.io` alone carries 1,281. An endpoint costs two to
six requests, so the ceiling is spent after a handful and every endpoint after that returns
`OUT_OF_SCOPE` with `reachable=False`. Roughly a fifth of the corpus would have been recorded
as unreachable, the abort would very likely have fired, and its message would have attributed
our own configuration to the ecosystem.

**Why not simply raise the ceiling.** It would deliver one operator some 7,700 requests, which
is the outcome the ceiling was introduced to prevent. Sampling sends *fewer* requests than the
ceiling alone would have allowed, because the instrument stops asking rather than asking and
being refused.

**What it costs, stated plainly.** At the endpoint unit this is a census of hostnames and a
sample within the large ones. The paper says so rather than describing the result as a census
without qualification. Nothing is hidden: `corpus.jsonl` is written before sampling and holds
the complete frame, so any reader can recompute the fraction. At the apex and implementation
units — R10.2 and R10.2b, and the primary unit is the apex — the rule changes nothing, because
a thousand registry listings answering from one hostname are one deployment and one
configuration decision, which is the premise R10.1 was built on.

---

---

## R11 — Headline selection rule ⚙️ *(written before the data)*

We have several candidate headline quantities, and which of them will carry the paper
**cannot be known before the data is seen**. Looking at the data and making the most striking
number the headline is the classic post-hoc move that would erase everything R1–R10 gained.
The choice is therefore bound to a rule **now**, by the ranking and criterion below.

### R11.1 — The candidate list is closed

The paper reports **all** of the following quantities. Nothing may be added to the list after
collection:

| Rank | Quantity | Normative anchor | Why this rank |
|---|---|---|---|
| **1** | **C16** — how many declared issuers advertise support for RFC 9207 `iss` | RFC 9700 (BCP 240) §2.1: *"When an OAuth client can interact with more than one authorization server, a defense against mix-up attacks … is **REQUIRED**"* + RFC 9207 §2.3: the server **MUST** advertise its support | The strongest anchor. The obligation is the client's, but its **availability** is observed on the server side; with no advertisement a conforming client must assume `false`, so the defence is effectively absent |
| **2** | **C18** — how many authorization servers publish `protected_resources`, and whether the cross-check passes for those that do | RFC 9728 §4 (OPTIONAL) + the §7.6 cross-check recommendation | The deployed availability of the only mitigation §7.6 recommends |
| **3** | Issuer concentration + cross-operator delegation rate | None — pure topology | Needs no anchor, cannot be a rubric, variance is close to guaranteed |
| **4** | **C12/C13** conformance rates | RFC 9728 §3.3, RFC 8414 §3.3 (MUST) | The anchor is strong, but the variance may be low and it is open to contamination by known SDK bugs (the R10 stratification is mandatory) |
| **5** | **C17** — availability of client-identity bootstrap | The MCP registration ladder (SHOULD) | The weakest anchor; it makes a section, not a headline |

### R11.2 — Selection criterion

> The headline is **the highest-ranked candidate that passes the variance test**.
>
> **Variance test:** the quantity's cluster-robust 95% confidence interval (R10.4) must lie
> entirely within neither `[0, 2%]` nor `[98%, 100%]`. That is, neither a "nobody has it" nor
> an "everybody has it" result can be the headline — both are one-sentence findings.
>
> If no candidate passes: the headline becomes **the rank-3 topology** (it is not a
> proportion and is therefore not subject to the variance test), and the conformance numbers
> are given as a secondary result.

### R11.3 — The anticipated risk, written down now

There is a serious chance that **C16 fails the variance test**: if the population of declared
issuers concentrates in mature IdPs such as Auth0/Okta/Entra/Clerk and all of them support
`iss`, the rate may sit at 100%. This prediction is on record **before the data**; if it
happens, the rule drops C16 from the headline and that drop is reported in the paper as **a
predicted outcome**, not quietly buried.

Symmetrically: C16 cannot be the headline if it comes out near 0% either — but in that case
the finding is a one-sentence yet strong result, *"the defence BCP 240 counts as REQUIRED is
available nowhere in the ecosystem"*, and it is told together with the rank-3 topology.

### R11.4 — The title is fixed after the measurement

The paper's title may not contain a measurement result (such as *"Cannot Verify"* or
*"Nobody Implements"*) before the headline is determined. Title candidates are kept in the
plan and chosen after the measurement. This follows from R11.2.

### R11.5 — Unit, denominator and aggregation rule for every candidate ⚙️

R11.1 ranks the candidates but did not say **in which unit and against which denominator**
they are measured. That was the side window of the door R11 exists to close: the code
computes C16 all-or-nothing at endpoint level while the R11.1 text describes an issuer rate,
and the two can diverge arbitrarily — an endpoint that declares 5 issuers of which 4 support
it is 80% at issuer level and 0% at endpoint level. Left to the moment of analysis, the
choice becomes post-hoc. It is fixed here, before the data.

| Candidate | Unit | Denominator | If an endpoint declares several issuers |
|---|---|---|---|
| **C16** | unique **declared** issuer | **declared.** An unreachable issuer counts as "does not advertise" — a client cannot use a defence it cannot reach | one observation per issuer; the "endpoint whose issuers all support it" rate is given as a **secondary** number |
| **C17** | unique declared issuer | declared | same |
| **C18** | unique **observed** issuer | observed. `cross_check_possible` **does not count an empty list**; `empty_list` is reported as a separate number | same |
| **Topology** | apex domain | — (not a rate) | — |
| **C12/C13** | the three units of R10.1 | R10.1 | — |

**The variance test (R11.2) is applied at issuer level**, to the cluster-robust interval
clustered by the issuer's apex.

**The alternative denominator (observed ↔ declared) is a pre-declared sensitivity pair** and
is reported in exactly the same form as R9.5: both numbers are printed, and which of them is
the headline has been chosen **now**, in the table above.

**Cross-operator proxy: apex only.** ASN and the TLS certificate were declared as sensitivity
arms; ASN is not collected at all, and the certificate is collected but not compared. Under
**R10.2b** — *"an arm that cannot be collected cannot carry a criterion"* — neither can be the
input to any result, and therefore **neither is promised either.** *(Cited as R10.2 until
30 July 2026. The sentence is in R10.2b; R10.2 is the apex-domain rule and says nothing about
uncollected arms, so a reader checking the reference found the wrong rule.)*

---

## R12 — Reporting commitment ⚙️ *(before the data)*

The instrument collects quantities that no document gives a destination to. **A field that is
collected but has no declared destination is by definition a free parameter:** if it turns
out useless in the analysis it drops quietly, and if it is useful it appears as an
"additional finding". This is the side window of the door R11 closes, and it is closed the
same way — the list **cannot be extended after** collection.

| Quantity | Where it is reported |
|---|---|
| C12/C13 outcomes, in three units | §5 (Results), main table |
| C16 · C17 · C18 (with the R11.5 denominators) | §5, in the R11.1 ranking |
| Issuer concentration (HHI, top-k), the delegation graph | §5, Figure 1 |
| Cross-operator delegation rate (apex proxy) | §5 |
| `shared_across_apexes` — two or more unrelated apexes declaring the same issuer URL | §5 |
| **Distribution of `hint_rejected_reason`** | **§5, its own subsection** — see below |
| Distribution of the `resource_relation` taxonomy (the nine buckets of R9.3) | §6 (Failure classes) |
| Distribution of `as_issuer_relations` | §6 |
| `empty_list` (C18) | §6 |
| Count of `malformed_authorization_servers` | §6 |
| `prm_scope_covers_endpoint` | §6, descriptive |
| `excluded_robots` · `excluded_opt_out` · `excluded_crossed_origin` | §4 (Methodology), denominator table |
| `dropped_no_apex` · `dropped_not_https` · `TRUNCATED` warnings | §4 |
| Block rate, Manski bounds | §4 and §9 |
| Number of `implementation_fingerprint` clusters, the `_no_server` arm | §4, cluster structure table |
| Distribution of `publisher_namespace` | §4, sampling frame structure |
| `robots_excluded_urls` (the URL list) | **dataset only**; a count in the paper |
| Raw artefacts | dataset only |

**Why `hint_rejected_reason` deserves its own subsection:** the number of endpoints whose
`WWW-Authenticate` points outside their own apex — or at loopback or RFC 1918 — is **a direct
observation of the attack surface RFC 9728 §7.6 names.** It is the quantity closest to the
paper's anchor, and the instrument already collects it. Not reporting it would mean ignoring
a finding that was measured and stored.

---

## Denominator rules

- Endpoints excluded by `robots.txt` are **removed from the denominator entirely**.
  Otherwise our own ethics policy biases the result.
- A document found after a cross-origin redirect is **not attributed** to the original host
  (`EndpointReport.crossed_origin()`). It is reported separately.
- The two funnels (`FUNNEL_OAUTH`, `FUNNEL_SIGNED`) are reported over **disjoint
  denominators**. A single funnel would count an endpoint that never entered a modality as
  "failing" — and that is composition, not failure.

## Funnel invariant

The applicable set of every stage must be a **subset** of the `PASS` set of the previous
stage. (Not the order of check IDs — that would make adding a legitimate stage impossible.)
