# Specification Mapping Table

**Status: v1 — 27 July 2026.** Written before data collection.

This table is the paper's tautology defence. The ground truth of every check is a
**published specification sentence**, not the authors' opinion. Under `docs/decision-rules.md`
R1 a check may report a failure only if it can point to a sentence at MUST level; that rule is
enforced by machine in `models.py`.

**Verification status:** ✅ quotation verified verbatim · ⚠️ quotation still to be confirmed
(mandatory before the first run)

---

## Modality 1 — Signed document (A2A Agent Card, did:web)

| ID | Check | Spec | Section | Strength | Status |
|---|---|---|---|---|---|
| **C01** | Is an identity document served at all | A2A | Agent Discovery | **SHOULD** | ✅ |
| **C02** | Does the document carry a JWS signature | A2A | §4.4.7 / §8.4 | **MAY** (OPTIONAL for the publisher) | ⚠️ |
| **C03** | Does `kid`/`jku`/did:web resolve to a key | A2A + RFC 7515 | §8.4 | **MUST** (if a signature is present) | ⚠️ |
| **C04** | Does the signature actually verify | A2A + RFC 7515 + RFC 8785 | §8.4 | **MUST** (if a signature is present) | ⚠️ |

**⚠️ Why these were downgraded (28 July 2026).** The ✅ marks on C02/C03/C04 had been set
**without verbatim verification** of the quoted sentences from a2a-protocol.org §8.4; in an
independent confirmation round the page truncates §8.4 and the sentences could not be
verified. The mark stays ⚠️ until it is earned.

**In measurement terms this is a cheap problem and should be resolved as one:** the signed-card
population was **1** in the pilot, and **~10 (95% CI [2, 58])** is expected in the full corpus.
No statistic survives that n. Decision: **the depth of FUNNEL_SIGNED (C03/C04/C15) is frozen**,
C01/C02 are reported as a one-paragraph prevalence statistic, and no funnel figure is drawn.
The quotation-verification burden thereby falls to C01, which is already ✅.

**C01 — the location is normative, publishing is not mandatory.**
> *"The standard path is `https://{agent-server-domain}/.well-known/agent-card.json`"*
> — [A2A Agent Discovery](https://a2a-protocol.org/latest/topics/agent-discovery/)

Not serving a card is not a violation → a C01 failure is `UNSPECIFIED`, not `FAIL_*`.
`/.well-known/agent.json` is the pre-v0.3 alias; where it is found it is recorded with a
version note.

**C02 — the obligation is on the verifier, not the publisher.**
> *"Verifiers **SHOULD** verify at least one signature before trusting an Agent Card."*
> — [A2A Specification §8.4](https://a2a-protocol.org/latest/specification/)

The `signatures` field is **OPTIONAL**. Counting an unsigned card as a "failure" would be the
authors' own rubric. → `DESCRIPTIVE_ONLY`. It is reported as prevalence (**1** of 25 cards in
the pilot was signed) and cannot penalise as a funnel stage.

**C04 — canonicalisation ambiguity triggers R6.**
> *"the Agent Card content **MUST** be canonicalized using the JSON Canonicalization Scheme
> (JCS) as defined in RFC 8785"* — A2A §8.4. The `signatures` field and fields carrying
> default values **MUST** be excluded from the signed payload.

Excluding fields that carry default values is ambiguous in practice → under R6, mismatches in
this class are automatically `UNSPECIFIED`, not `FAIL_MISIMPLEMENTED`.

**⚠️ A verified gap (the paper's normative contribution):** the A2A specification contains
**no normative statement about a signed card's freshness, its `exp`/`nbf`, or key revocation.**
This is the source of why C09 and C10 count as opinion, and it is the cleanest example in the
`UNSPECIFIED` catalogue.

---

## Modality 2 — OAuth metadata (MCP)

| ID | Check | Spec | Strength | Status |
|---|---|---|---|---|
| **C05** | Is protected-resource metadata reachable | MCP Authorization | **MUST** (if authorization is used) | ✅ |
| ~~C06~~ | ~~Does AS metadata resolve and is it valid~~ | — | **DELETED 28 July 2026** | — |
| **C07** | Does the 401 carry `WWW-Authenticate: resource_metadata` | MCP Authorization | **revision-dependent** (see below) | ✅ |
| **C12** | Is the PRM `resource` value identical to the resource identifier | RFC 9728 §3.3 | **MUST** | ✅ |
| **C13** | Does the declared issuer actually return that issuer | RFC 8414 §3.3 | **MUST** | ✅ |
| **C14** | Is `code_challenge_methods_supported` declared | RFC 9700 §2.1.1; RFC 8414 §2 | RECOMMENDED / OPTIONAL → **descriptive only** | ✅ |

**Precondition — authorization is optional.**
> *"Authorization is **OPTIONAL** for MCP implementations."*
> — [MCP Authorization, revision 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)

C05 therefore **cannot be applied unconditionally**: it applies only to endpoints that return
401/403, that is, endpoints that have opted in to authorization. On an open server the absence
of PRM is not a violation but `NOT_APPLICABLE`. In the pilot, **179 (37.9%)** of 472 reachable
endpoints met this condition → that, and not 472, is C05's real denominator.

**C05 — mandatory if authorization is used.**
> *"MCP servers **MUST** implement OAuth 2.0 Protected Resource Metadata (RFC9728). MCP
> clients **MUST** use OAuth 2.0 Protected Resource Metadata for authorization server
> discovery."*
>
> *"The Protected Resource Metadata document returned by the MCP server **MUST** include the
> `authorization_servers` field containing at least one authorization server."*

Discovery runs by two routes: the `WWW-Authenticate` header **or** the well-known URI; the
well-known comes in two forms (path-suffixed and root). `config.prm_candidate_urls()` produces
both — trying only the root form would produce **artificial failures** on correctly configured
servers.

**C07 — ⚠️ closed, but with an unexpected result: the normative strength depends on the revision.**

Confirming this item produced two different answers, and **both are correct** — because they
come from two different MCP revisions:

| Revision | Verbatim text | C07's strength |
|---|---|---|
| **2025-06-18** | *"MCP servers **MUST** use the HTTP header `WWW-Authenticate` when returning a `401 Unauthorized`"* | **MUST** → `FAIL_*` possible |
| **2025-11-25** | *"MCP servers **MUST** implement **one of the following** discovery mechanisms … 1. WWW-Authenticate Header … 2. Well-Known URI"* | the header alone is **not** mandatory → at most `UNSPECIFIED` |

So a server with no `WWW-Authenticate` header but a working well-known is **fully conforming**
under the current revision. R7 (version pinning) exists for exactly this case: an endpoint is
scored against the revision it declares; where there is no declaration, the **most permissive
revision in force** applies → 2025-11-25 → C07 cannot penalise.

**This is the cleanest example of why R7 is necessary, and it should enter the paper in this
form.** Recording C07 as a plain "MUST" would write a violation against every server that is
correctly configured under 2025-11-25 — that is, we would report a specification change as an
ecosystem fault.

**C12 — the strongest addition (candidate for the money finding).**
> *"The `resource` value returned **MUST** be identical to the protected resource's resource
> identifier... If these values are not identical, the data contained in the response **MUST
> NOT** be used."* — [RFC 9728 §3.3](https://www.rfc-editor.org/rfc/rfc9728.html)

MUST-level, mechanically checkable, and in the pilot (n=500) 166 endpoints declare
`authorization_servers` → ~1,700 expected in the full corpus. **This is the project's decisive
check.**

**⚠️ How C12's expected value is derived — critical.** What RFC 9728 §3.3 compares is **not**
the endpoint's raw URL but *"the resource identifier value into which the well-known URI
path suffix was inserted to create the URL used to retrieve the metadata"* — that is, the
identifier derived back from the location the document **came from**. §3.1 further says
*"**If the resource identifier value contains a path or query component**, any terminating
slash (/) following the host component **MUST** be removed before inserting `/.well-known/`
and the well-known URI path suffix between the host component and the path and/or query
components."* Together these two sentences fully determine the derivation, and the rule is
frozen as **R9.1**.

The conditional is quoted rather than elided on purpose, and this document elided it until
29 July 2026. R9.1 states why in as many words: dropped, the sentence reads as though the
slash rule also governed the root form, which it does not. A truncation that makes a MUST
look broader than it is belongs in no document, and least of all in the one a reviewer opens
to check that the instrument's ground truth is the specification rather than the authors.

The distinction is not cosmetic: before the correction the instrument derived the expected
value once from the raw endpoint URL and reported **75%** violations across 8 large live MCP
endpoints; under the correct rule, **25%**. The difference was entirely instrument error, and
it was directly the paper's headline number.

**C13 — issuer identity.**
> RFC 8414 §3.3, verbatim: *"The `issuer` value returned **MUST** be identical to **the
> authorization server's** issuer identifier value into which the well-known URI string was
> inserted to create the URL used to retrieve the metadata."*
>
> RFC 8414 §4, verbatim: *"Comparisons between the two strings **MUST** be performed as a
> Unicode code-point-to-code-point equality comparison."* — Unicode normalisation is not
> applied. This **forbids** forgiving a trailing slash (R9.4).

**⚠️ The obligation in C13 falls on the authorization server, not the MCP server.** RFC 8414
§3.3 binds Auth0, Okta, and Keycloak. C13's unit of analysis is therefore **the issuer, not the
endpoint**: the 166 endpoints probably declare between 10 and 40 distinct issuers, and a C13
violation is not a finding that "the agent ecosystem is broken" but that "this IdP product has
a bug". Under R10.1, C13 is reported both per endpoint and **per unique issuer**, and in the
paper the endpoint-level form is written as *"the declared AS did not identify itself
consistently, so the client's discovery chain is broken"* — that is an observation on the
resource side and is legitimately endpoint-scoped.

**RFC 9728 §7.6 cannot be used as an anchor.** The earlier record gave C13's basis as
"RFC 8414 §3.3 + RFC 9728 §7.6". §7.6 cannot carry a penalty, because its verbatim text is
this:

> *"Secure determination of appropriate authorization servers to use with a protected
> resource for all use cases is **out of scope for this specification**."*
>
> *"…lists in the protected resource metadata and authorization server metadata **should**
> be cross-checked against one another for consistency…"* — lower-case `should`, **not** an
> RFC 2119 keyword.

Under R1, at most `UNSPECIFIED` follows from this. §7.6 is quoted in the paper as
**motivation**, not as **norm** — and as motivation it is extremely strong (see below).

**C14 — descriptive, and the demotion is the clearest illustration of R1 in this document.**

C14 was anchored to this sentence and reported a MUST-level failure against the authorization
server on the strength of it:

> *"If `code_challenge_methods_supported` is absent, the authorization server does not support
> PKCE and MCP clients **MUST** refuse to proceed."*
> — MCP Authorization, revision 2025-11-25, Security Considerations

Read again: the obligation is the **client's**. The justification recorded here was that "the
declaration is observed on the server side at no cost", which is an argument about observation
cost and not about anchoring — it licenses *collecting* the datum, which remains worth doing,
and never *penalising* its absence. That is the same argument R1 rejects for C16, and the same
one that got MCP's Resource Indicators clause ruled out of scope in the table below.

The sentences that actually govern publication of the element bind the authorization server and
sit below MUST:

> *"`code_challenge_methods_supported` — **OPTIONAL.** JSON array containing a list of Proof Key
> for Code Exchange (PKCE) [RFC7636] code challenge methods supported by this authorization
> server. … If omitted, the authorization server does not support PKCE."*
> — RFC 8414 §2

> *"Authorization servers **MUST** provide a way to detect their support for PKCE. It is
> **RECOMMENDED** for authorization servers to publish the element
> `code_challenge_methods_supported` in their Authorization Server Metadata [RFC8414] … 
> Authorization servers **MAY** instead provide a deployment-specific way to ensure or determine
> PKCE support by the authorization server."*
> — RFC 9700 (BCP 240) §2.1.1

RFC 9700's genuine server-binding MUST — *"provide a way to detect"* — is **unfalsifiable by
this instrument**, because the permitted alternative is a deployment-specific mechanism no
external prober can see. So an absent element is not even evidence that *that* MUST was broken.

One server-binding MUST to publish the element does exist: *"Authorization servers providing
OpenID Connect Discovery 1.0 **MUST** include `code_challenge_methods_supported` in their
metadata to ensure MCP compatibility"* (MCP 2025-11-25). It does not rescue the check. It is
absent from revision 2025-06-18, which R7 makes the governing revision; it binds only servers
serving OIDC Discovery metadata, while the instrument tries the RFC 8414 form first; and the
instrument does not record which candidate answered, so the two populations cannot be
separated. C14 is therefore reported as prevalence, like C16–C18.

---

## What cannot be measured, and is therefore out of scope

| What | Why passive measurement cannot see it |
|---|---|
| RFC 8707 resource indicators | *"MCP **clients** MUST implement Resource Indicators"* — the obligation is on the client. The server cannot be observed from outside. **C07 was rewritten for this reason.** |
| Token audience validation | *"MCP servers MUST validate that access tokens were issued specifically for them"* — server-internal behaviour; verifying it would require an authentication attempt, which is outside the ethical scope |
| Card capability ↔ scope consistency | No specification requires this consistency → checking it would be the authors' own rubric. Removed from the plan; the reason will be stated in the paper |

---

## Descriptive checks (never report a failure)

| ID | Check | Why `DESCRIPTIVE_ONLY` |
|---|---|---|
| C02 | Is the card signed | OPTIONAL for the publisher in A2A |
| C08 | Is DPoP / mTLS declared | Neither MCP nor RFC 9449 requires it |
| C09 | Is `revocation_endpoint` declared | No specification asks that an agent identity be revocable |
| **C16** | Is RFC 9207 `iss` support declared | RFC 9207 **§2.3** does bind the **server** — *"The server **MUST** indicate its support for the `iss` parameter by setting the metadata parameter … to true"* — but **conditionally**, on *"Authorization servers supporting this specification"*. An absent flag therefore means "does not support", which nothing forbids. (This row said the obligation was on the client until 30 July 2026; the amendment of 29 July had already corrected the bound party to the server and this table was not updated with it. The section number was also wrong everywhere — **§3**, which contains no MUST at all.) |
| **C17** | Can a client identity be bootstrapped (CIMD ∨ DCR) | The MCP registration ladder ends at "ask the user"; none of it is mandatory |
| **C18** | Is `protected_resources` published | **OPTIONAL** in RFC 9728 §4 |

These are reported in the paper as **prevalence statistics** and as part of the `UNSPECIFIED`
catalogue. They are not made funnel stages. That C09 has **no** specification counterpart is
itself the finding: in the agent identity ecosystem, revocation is a feature nobody requires.

> **⚠️ C06 and C10 were deleted (28 July 2026).** Both were defined in the enum and in this
> table but **were emitted on no code path.** A paper that lists a measurement it does not
> perform hands the reviewer the cheapest possible way to kill it. C06 was also redundant:
> C13 already fetches and parses the AS document, and a document that cannot be parsed falls
> onto the failure path there. C10 had no specification sentence to anchor to —
> "organisational trust root" is defined in no specification, and defining it would be the
> authors' own rubric, which is the objection that killed this project's previous three
> framings. C08, C09, and C11 were in the same position and **were made emittable**; the data
> for all three was already being fetched. `tests/test_models.py` now verifies by machine that
> every `CheckId` is emitted on some code path.

---

## Auxiliary checks

| ID | Check | Spec | Strength |
|---|---|---|---|
| **C11** | Is the endpoint's own TLS valid | RFC 9728 + BCP 195; MCP: *"All authorization server endpoints **MUST** be served over HTTPS"* | **MUST** |
| **C15** | `alg` / key strength / `kid` resolution | RFC 7518, BCP 195 | **MUST** (`none`, `HS*` against a public JWKS, RSA < 2048) |

---

## Not measured but ought to be — absent from the plan

**The deployed availability of the RFC 9728 §7.6 cross-check.** §7.6 proposes a single
mitigation: that the issuer list declared by the resource and the resource list declared by the
AS be validated against each other.

> **⚠️ Correction (28 July 2026).** This paragraph previously said *"RFC 8414 defines no such
> field, so the mitigation is impossible"*. **That was wrong.** RFC 9728 **§4** defines the
> field, verbatim:
>
> > *"this specification defines the authorization server metadata parameter
> > `protected_resources`, which enables the authorization server to explicitly list the
> > protected resources. … **OPTIONAL.** JSON array containing a list of resource identifiers
> > for OAuth protected resources that can be used with this authorization server."*
>
> The field is registered in RFC 8414's *"OAuth Authorization Server Metadata"* registry. The
> mechanism therefore **exists**; what is missing is deployment. This correction does not
> weaken the finding, it **strengthens** it: "impossible" shows no variance and is close to a
> tautology, whereas *"the field is defined; how many issuers publish it"* is a real empirical
> quantity, and even a result of 0% is a measured outcome that can be taken to the IETF.

**The quantity to measure:** how many declared issuers publish `protected_resources` in their
AS metadata, and, among those that do, whether the list actually contains the resource (that
is, whether the cross-check *passes*, not merely whether it is *possible*). Because
`protected_resources` is **OPTIONAL**, R1 makes it `DESCRIPTIVE_ONLY` — its absence can never
be `FAIL_*`. The additional request cost is zero: the AS document is already fetched for C13
and is stored in `ev.as_documents`.

**Prevalence of `registration_endpoint` (RFC 7591).** If a declared AS is open to dynamic
client registration, an attacker can obtain a client of their own at the issuer the resource
trusts. Because it is OPTIONAL in RFC 8414, R1 makes it `DESCRIPTIVE_ONLY`, but it turns the
declared trust relationship from a descriptive statistic into a security-relevant quantity.
**Ethics: only the presence of the field is counted; no registration is attempted** — that
would be a write.

**Dead / takeover-able issuer.** Is the declared issuer's domain still registered (RDAP, free,
keyless)? If it is not, that is a trust-anchor takeover primitive. **Ethics: a domain found
this way is not registered.**

---

## To do — before the first run

- [x] ⚠️ Confirmation of C07 is complete → the normative strength turned out to be
      **revision-dependent**, recorded above.
- [ ] Record an access date, and a version tag where one exists, for every `spec_url` (R7).
- [ ] Determine how an endpoint's MCP revision declaration is to be read (2025-11-25 vs
      2025-06-18) — no longer optional, because C07's strength depends on it.
- [x] C06/C08/C09/C10/C11 resolved: C06 and C10 were **deleted**, C08/C09/C11 were **made
      emittable**. A machine guard was added
      (`test_every_declared_check_is_actually_emitted_somewhere`).
