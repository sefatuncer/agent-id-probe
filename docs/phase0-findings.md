# Phase 0 — Kill-test findings

**Date:** 27 July 2026 · **Source:** Reviewer B live pilot (full sweep of the official MCP registry plus a funnel pilot over 500 domains) · **Cost:** none

> **On this translation.** This document was written in Turkish on 27 July 2026 and translated
> on 13 August 2026. Every figure, quotation, table shape and dated correction note is carried
> over unchanged. It is the dated record of the pilot and is **not** corrected retroactively;
> where a later decision superseded something here, the existing inline note says so and the
> note itself has been preserved rather than folded into the text.

---

## 1. Corpus (kill-test arm i)

### MCP — **PASSED**

`registry.modelcontextprotocol.io/v0/servers` — no authentication, cursor pagination, free.

| Measure | Value |
|---|---|
| Total records (all versions) | 59,902 |
| Unique servers | 18,747 |
| Unique servers carrying `remotes` | 9,276 (49.5%) |
| Remote / package-only (stdio) by version | 20,986 / 38,198 (**65% stdio**) |
| Unique remote URLs | 10,393 |
| Unique hosts | 7,421 |
| **Unique registrable domains** | **5,154** |

The threshold was ≥1,500 → **passes comfortably.**

Other free sources (all worked without a key): Smithery `registry.smithery.ai` 7,418 servers / 3,941 remote · Glama public REST 61,437 · PulseMCP 22,252 but returns 403/410, fragile.

### A2A — **FAILED**

Three independent pieces of evidence show that public A2A deployment is close to non-existent:
- Our own sweep: 43 high-likelihood enterprise hosts (Google, Salesforce, Atlassian, SAP, Okta) → **2 cards**, both unsigned
- OpenClaw Experiment 055 (April 2026): 50 agents *advertising* A2A support → valid cards **0–2**, responses to an A2A task request **0** — confirmed at `a2aproject/A2A` issue #1755, *"Active A2A Outbound Probing"*
- ~~AgentHermes: 500 businesses across 27 sectors → zero `agent-card.json`~~ — **removed 28 July 2026: source not found.** No publication or dataset supporting the "500 businesses / zero cards" statistic could be confirmed. The conclusion already stands on the two independent items above, and a third support that cannot be verified casts doubt on the ones that can

**Recovery:** probing the MCP remote origins for `/.well-known/agent-card.json` produced **25 valid cards (5.3%)** across 472 reachable origins → scaling to 5,154 domains gives roughly 270. Below the threshold but not zero. **A2A can exist only as something derived from the MCP corpus** — and that derivation is itself an original methodological contribution. The cards found belong to long-tail projects (namewhisper.ai, brainonbnb.com) rather than enterprises, so any generalisation claim has to be narrowed accordingly.

---

## 2. Live funnel pilot (n=500, one URL per domain)

| Stage | n | Rate |
|---|---|---|
| Reachable | 472 | 94.4% |
| MCP `initialize` succeeded | 251 | 53.2% |
| 401/403 (authorization required) | 179 | 37.9% |
| `WWW-Authenticate` header | 147 | 31.1% |
| **RFC 9728 protected-resource metadata** | **173** | **36.7%** |
| Declaring `authorization_servers` | 166 | 35.2% |
| A2A card found | 32 | 6.8% |
| Valid A2A card | 25 | 5.3% |
| **Cryptographically signed card** | **1** | **0.2%** |

---

## 3. Scoop risk (kill-test arm iii) — **FAILED**

| Study | What it did | Effect |
|---|---|---|
| arXiv **2605.22333** | 7,973 live remote MCP servers, **40.55% with no authentication**, an OAuth flaw taxonomy, 9 CVEs | Stages 1 and 2 of the funnel are **already published**. Our 37.9% is the other face of the same measurement |
| arXiv **2607.11086** (MCPZoo) | 64,611 servers, ecosystem scale | A claim to superior scale is impossible |
| arXiv **2603.07473** | *"Give Them an Inch…: Caller Identity Confusion in MCP-Based AI Systems"* | **⚠️ WITHDRAWN by its authors on 21 July 2026.** Cannot count as prior art — see below |

---

**⚠️ Correction (28 July 2026): 2603.07473 was withdrawn.** Version 2 was withdrawn by its
authors on 21 July 2026. The reason verbatim:

> *"Withdrawal due to some flaws in experimental methodology and unresolved ethical issues in
> data collection. We need to redesign the experiments and obtain proper ethical clearance
> before resubmission."*

Two consequences follow:

1. **It cannot count as prior art.** This table used to list it as something that *"refutes the
   claim of no prior work single-handedly"*. A withdrawn paper cannot do that. The positioning
   has to be rewritten: published and standing work on identity confusion is **less** than we
   thought. It should still be cited in the paper **together with the withdrawal note**;
   dropping it silently will not escape a referee working the same area.
2. **A live warning for our own ethics section.** The stated reason for withdrawal is exactly
   the risk we are exposed to: unresolved ethical issues in data collection. A paper in the
   same area, in the same year, in the same method family was withdrawn for it. That is why
   `docs/ETHICS.md` is a precondition of the run rather than a writing task after it.

## 4. DECISION: continue, but with a reframing

The original frame ("internet-scale measurement of whether agent identity is verifiable) is
**cut at both ends**: the entry stages are scooped and the exit stage has n = 1.

**The only untouched area that survives and shows variance:** the **issuer ↔ resource ↔
audience triple consistency** across the 166 endpoints declaring `authorization_servers`. The
specification sentences here are at MUST level and mechanically checkable:

> RFC 9728: *"The `resource` value returned **MUST** be identical to the protected resource's resource identifier... If these values are not identical, the data contained in the response **MUST NOT** be used."*
>
> RFC 8414, Section 3.3: the `issuer` identity **MUST**.

Prior work settled the question *"is there authorization"*. **None of it asked whether a
declared trust relationship is internally consistent and cryptographically bound.**

**New headline:** not "nothing is verified" but **"identity metadata is widespread (36.7%),
the cryptographic binding is absent (0.2%), and the consistency of the declared bindings has
not been measured."**

**Positioning rule:** stages 1 and 2 will be labelled **replication** in the paper explicitly,
and not sold as a contribution. The weight of the paper goes to audience and issuer binding.

---

## 5. Instrument corrections (Reviewer A — mandatory BEFORE collection)

**Four checks exposed to the "this is the authors' rubric" objection:** C02 (`signatures` is OPTIONAL in A2A), C08 (DPoP/mTLS not mandatory), C09 (no specification demands a status list), C10 ("organisational trust root" is defined in no specification; **C10 was later deleted outright**). → To be removed from the funnel or reported as an UNSPECIFIED finding.

> **What happened afterwards (28 July 2026):** three of these four became descriptive and
> **C10 was deleted outright** — there was no specification sentence to anchor it to, and
> defining one ourselves would have been the very thing this design exists to make impossible.
> This document is the dated record of the pilot and is not corrected retroactively; for the
> instrument's current state, `check-catalogue.md` is the single source.

**Checks to add:**
| ID | Check | Specification anchor |
|---|---|---|
| **C12** | PRM `resource` identity match | RFC 9728 — **MUST**, mechanical, the highest likelihood of misimplementation (money finding) |
| **C13** | `authorization_servers` ↔ AS `issuer` correspondence | RFC 8414, Section 3.3 MUST + RFC 9728, Section 7.6 |
| C11 | TLS validity | RFC 9728 MUST + BCP 195; MCP "MUST be served over HTTPS" |
| C14 | PKCE declaration (`code_challenge_methods_supported`) | MCP specification MUST |
| C15 | `alg` and key strength, `kid` resolution | RFC 7518, BCP 195 |

**C05 measurement defect:** `allowed_paths` holds only the root form, while the specification also defines the path-suffixed form (`/.well-known/oauth-protected-resource/mcp`) **and** the `WWW-Authenticate: resource_metadata` path. Left uncorrected, the failure rate inflates artificially.

**C07 is unmeasurable:** the RFC 8707 obligation is on the *client*; a passive probe cannot see it. Converted into C12.

**The funnel will be split in two:** Funnel-M (MCP: reachable → C05 → C12 → C13 → C06/C14 — *C06 was
deleted on 28 July, C14 became descriptive and left the funnel on 29 July, so this funnel ends
at C13 today*) and Funnel-A (A2A/did:web: reachable → C01 → C02 → C03 → C04). A single funnel would eliminate a legitimate endpoint using OAuth-only identity at a stage the specification never asked it to enter, so most of the waterfall would be **composition** rather than failure.

---

## 6. The eight decision rules to write now (making the post-hoc accusation structurally impossible)

1. **Normative-strength rule:** a check may return `FAIL_*` only if its `spec_ref` points at a **MUST/SHALL** sentence. SHOULD → UNSPECIFIED. MAY or silence → NOT_APPLICABLE. → a `CheckResult.normative_strength` field will be added and the rule enforced by machine.
2. **Precedence:** ERROR > NOT_APPLICABLE > UNSPECIFIED > FAIL_MISIMPLEMENTED > FAIL_UNIMPLEMENTED > PASS
3. 200 with malformed JSON = MISIMPLEMENTED; 404 = UNIMPLEMENTED. Without exception.
4. 403/429/WAF/Cloudflare challenge = **ERROR**, never UNIMPLEMENTED.
5. An ERROR becomes final only after `max_retries` is exhausted and the same result appears in ≥2 runs at least 24 hours apart.
6. If two reasonable readings of the specification give different verdicts → automatically **UNSPECIFIED**.
7. **Version pinning:** `CheckResult.spec_version`. An endpoint is scored against the MCP revision it declares (2025-11-25 ≠ 2025-06-18).
8. Two-coder Cohen's kappa for the MISIMPLEMENTED/UNSPECIFIED boundary on a stratified sample of n≈100, declared in advance.

---

## 7. Home IP — a measurement-validity risk (new, serious)

In the pilot 28 of 500 (5.6%) never answered, and PulseMCP returned 403/410. **Blocking may correlate with the property being measured:** mature and enterprise endpoints sit behind WAFs, so the sample drifts systematically toward amateur endpoints. That every A2A card found is long-tail supports the suspicion.

**Free mitigation:** a second run from the co-author's **MSKÜ network** (the ULAKBİM AS is recognised as academic), running the same sample from two networks and **reporting the difference in block rate**. That difference is a publishable validity measurement in its own right and gives the co-author a natural, low-cost contribution.

---

## 8. The next decisive test (go/no-go)

### ⚠️ The old criterion is void — changed on 28 July 2026, and not silently

It used to read: *"Measure issuer ↔ resource ↔ audience triple consistency across the ~166
endpoints declaring `authorization_servers`. Variance between 2% and 90% → continue; stuck at
0% or 100% → stop."* It is unusable for three separate reasons:

1. **`audience` is not measured.** `spec-mapping.md` states plainly that token audience
   validation cannot be observed passively. A frozen criterion was referring to a measurement
   that does not exist.
2. **A point estimate was compared against a threshold, with no allowance for uncertainty.**
   At n = 166 with k = 3 → p̂ = 1.8% → "below the threshold, stop". But the 95% CI is
   [0.6%, 5.2%] and contains 5%. Computed: if the true violation rate is 1%, this rule kills
   the project **wrongly with probability 19%**; at 0.5% it is **43.5%**. A 1% rate over the
   full corpus means about 17 endpoints, which is more than enough for a paper.
3. **It was looking at the wrong arm.** The current frame rests on the **delegation
   distribution** rather than on a violation rate. Even if C12/C13 came back 99% PASS, the
   finding "N resources delegate to M issuers, X% cross-operator, the top-1 issuer carries Y%
   of the corpus" still stands.

**One more thing has to go on the record.** The kill test in `ARASTIRMA-PLANI.md`, Section 5
read *"signed/verifiable rate across 100 endpoints between 2% and 90%… if it is 0% everywhere
→ KILL"* and carried the note *"not negotiable"*. The pilot returned **0.2%**, which is
**below** the threshold. The project was not killed; the decisive measurement was moved from
the signed-document arm to the OAuth arm. That pivot is defensible — the signature funnel is
dead and the OAuth funnel is untouched — but **nowhere was it written down that the criterion
had fired.** The project's whole identity rests on R1–R8 making post-hoc impossible, and
silently changing target once a criterion fires is precisely the move that defence forbids.
The record is entered here as it stands. The paper says the same thing: **the signature
modality fell at its own pre-declared threshold and was therefore reduced to a descriptive
result, and the measurement weight moved to the OAuth modality.**

### The new criterion (frozen 28 July 2026, before the data)

The interim go/no-go gate is **removed.** The reason is item (2) above: the only effect of an
interim decision at n = 166 is to manufacture a risk of killing the project wrongly. The
narrow-slice run is for **ethical and operational** validation (block rate, per-host error
budget, rate policy, User-Agent reachability), not for a statistical decision.

The full corpus is run (roughly 1,700 endpoints declaring `authorization_servers` are
expected) and **a stop decision is taken only under this condition:**

> If the **entire cluster-robust 95% confidence interval** for the cross-operator delegation
> rate falls within [0, 2%] → the paper drops to a measurement note and the target venue is
> lowered.

An interval, not a point estimate. Cluster-robust rather than naive Wilson (R10.4), because
under clustering the true coverage of the naive interval is not 95% but somewhere between 45%
and 82% depending on the scenario.

**The measurement itself cannot be reduced to the C12/C13 violation rate.** The headline
quantities are: issuer concentration (HHI, top-k share) · cross-operator delegation rate under
three pre-declared proxies (apex, ASN, certificate) · multi-tenant issuers with no tenant
separation · the share of authorization servers for which the RFC 9728, Section 7.6
cross-check is actually possible.
