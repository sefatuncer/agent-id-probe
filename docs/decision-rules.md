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

`_KNOWN_PLATFORM_SUFFIXES` is for **labelling** only. The hosting class is derived from
observed signals (shared certificate, ASN, PRM hash).

### R10.4 — Uncertainty is reported against the number of clusters

The cluster-robust confidence interval for a rate is `t(m-1)`-based because `m` is small;
when `m < 30` it is also given by a wild cluster bootstrap-t (Rademacher). Every rate is
written with `m` (the number of clusters), DEFF and `n_eff` beside it. The naive Wilson
interval is **not published on its own**: under clustering its real coverage is not 95% but
45%–82%, depending on the scenario.

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
| **1** | **C16** — how many declared issuers advertise support for RFC 9207 `iss` | RFC 9700 (BCP 240) §2.1: *"When an OAuth client can interact with more than one authorization server, a defense against mix-up attacks … is **REQUIRED**"* + RFC 9207 §3: the server **MUST** advertise its support | The strongest anchor. The obligation is the client's, but its **availability** is observed on the server side; with no advertisement a conforming client must assume `false`, so the defence is effectively absent |
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
R10.2 an arm that cannot be collected can be the input to no result — and therefore **it is
not promised either.**

### R11.4 — The title is fixed after the measurement

The paper's title may not contain a measurement result (such as *"Cannot Verify"* or
*"Nobody Implements"*) before the headline is determined. Title candidates are kept in the
plan and chosen after the measurement. This follows from R11.2.

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
| Distribution of the `resource_relation` taxonomy (the eight buckets of R9.3) | §6 (Failure classes) |
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
