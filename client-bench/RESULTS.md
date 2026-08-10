# Client bench — results

**Run 10 August 2026.** Cases fixed in `CASE-MATRIX.md` before the bench ran. Raw records in
`results.jsonl`, one per (implementation, case).

**Three implementations tested.** This is a convenience sample of what installs without an
account, so the reportable form is *"of the three tested, k"* and never *"most clients"*.

| Implementation | Version | How obtained |
|---|---|---|
| `@modelcontextprotocol/sdk` (the v1 line) | 1.30.0 | npm |
| `@modelcontextprotocol/client` (the v2 line) | 2.0.0 | npm |
| `mcp` (Python) | 2.0.0 | pip |

---

## A — RFC 9728 §3.3: is "identical" implemented as identical?

Requested identifier throughout: `http://127.0.0.1:PORT/tenant-a/mcp`.

| Case | PRM `resource` | Required | v1 1.30.0 | v2 2.0.0 | python 2.0.0 |
|---|---|---|---|---|---|
| A1 | identical | use | use ✓ | use ✓ | use ✓ |
| **A2** | **proper ancestor `…/`** | **reject** | **use ✗** | **use ✗** | **use ✗** |
| A3 | sibling | reject | reject ✓ | reject ✓ | reject ✓ |
| A4 | cross-origin | reject | reject ✓ | reject ✓ | reject ✓ |
| A5 | absent | reject | reject ✓ | reject ✓ | **use ✗** |
| A6 | trailing slash | reject | reject ✓ | reject ✓ | **use ✗** |
| A7 | case-differing path | reject | reject ✓ | reject ✓ | reject ✓ |

**Two things are true at once and both must be said.**

1. **The attack RFC 9728 §7.6 actually names is blocked.** No implementation lets a metadata
   document redirect the token audience to an attacker's host or to a sibling resource. A3 and
   A4 fail closed everywhere.
2. **The MUST is nonetheless not implemented, and the deviation has a direction.** All three
   accept a `resource` that is a *proper ancestor* of the requested identifier, and each then
   **adopts** it — `adopted_identifier` in the records is `…/`, not the requested path. That
   value becomes the RFC 8707 `resource` parameter on the authorization and token requests, so
   a resource server declaring `resource: "https://host/"` while living at
   `https://host/tenant-a/mcp` causes the client to request a token scoped to the whole origin.
   The tolerance is one-way: it admits *broader* identifiers only.

The Python SDK is the most permissive of the three: it also skips the comparison entirely when
the document omits `resource` (A5), though RFC 9728 §2 makes that member REQUIRED, and it
accepts a trailing-slash variant (A6).

**What this does not establish.** Whether A2 is *exploitable* depends on something no bench can
see: whether the sibling resource server validates the token audience strictly. The honest
phrase is "widens the attack surface", not "is exploitable".

## B — RFC 8414 §3.3: the issuer check the specification does restate

| Case | AS metadata `issuer` | Required | v1 1.30.0 | v2 2.0.0 |
|---|---|---|---|---|
| B1 | matches discovery URL | use | use ✓ | use ✓ |
| **B2** | **names a different origin** | **reject** | **use ✗** | reject ✓ |

v2 throws `IssuerMismatchError`. **v1 performs no comparison at all** — verified in the shipped
source, not inferred from the bench: `Issuer mismatch`, `expectedIssuer`, `IssuerMismatch` and
`issuer !==` each occur **zero** times in `@modelcontextprotocol/sdk/dist`, and `issuer` is used
only to build URLs.

## C — `protected_resources`, RFC 9728 §4 and §7.6 (descriptive only)

No clause obliges a client to read this field, so **nothing here is non-conformance.** It
decides whether the census's C18 rate means anything.

| Implementation | Occurrences in shipped source | Schema knows the field |
|---|---|---|
| `@modelcontextprotocol/sdk` 1.30.0 | **0** | no |
| `@modelcontextprotocol/client` 2.0.0 | **0** | no |
| `mcp` 2.0.0 (Python) | **0** | no |

With several authorization servers named, all take `authorization_servers[0]` unconditionally.

**This is the bench's most decisive result.** RFC 9728 §7.6 declares secure authorization-server
selection out of scope, names the attack it enables, and offers exactly one mitigation: the
cross-check that §4's `protected_resources` makes possible. MCP forwards the decision to the
client by name. The census measured that `\headline{c18-rate}` of observed issuers publish the
field. The bench measures whether anyone would look, and the answer is nobody. **The chain is
empty at every link.**

## D — RFC 9207 `iss`, a client MUST under MCP revision 2026-07-28

| Case | `iss` | advertised | Required | v1 1.30.0 | v2 2.0.0 |
|---|---|---|---|---|---|
| D1 | correct | true | accept | *no function* | accept ✓ |
| D2 | wrong | true | reject | *no function* | reject ✓ |
| D3 | absent | true | reject | *no function* | reject ✓ |
| D4 | correct | — | accept | *no function* | accept ✓ |
| D5 | wrong | — | reject | *no function* | reject ✓ |
| D6 | absent | — | accept | *no function* | accept ✓ |

**v2 matches the specification's four-row table exactly, six rows for six.** v1 exports no such
function; the absence *is* the answer for that line, recorded as `not_exercised` with the reason
rather than as a pass.

The v1→v2 delta is the interesting part: the mix-up defence arrived between two releases of one
package. Any application still on the v1 line has none. **How much of the installed base that
is, this bench cannot see, and no sentence here may imply it.**

---

## Two corrections made during the run

Both were caught because a result contradicted an independently verified document, and both
would have been false accusations against named vendors. Recording them because the same class
of error is what this project's rules exist to catch.

1. **The D-series first reported v2 accepting a wrong `iss` on three rows.** The driver called
   `validateAuthorizationResponseIssuer(params, metadata)`; the real signature is a single
   destructured object, `{ iss, expectedIssuer, issParameterSupported }`
   (`dist/index.cjs:337`). Every row therefore destructured `iss` to `undefined` and the
   function took its "nothing to compare" path. Corrected against the shipped source; v2 is
   conformant on all six rows.
2. **The C-series first reported both SDKs "parsing" `protected_resources`,** because the key
   survived into the returned object. The schemas do not strip unknown keys, so survival
   measured nothing. A control key that appears in no schema was added; it survives too. The
   claim now rests on the source count, which is zero.

## Scope and limits

- **No prevalence claim.** Three implementations, chosen for installing without an account.
- **Closed-source clients are invisible** — Claude Desktop, Cursor, ChatGPT connectors and
  other proprietary hosts plausibly carry most real MCP traffic. This is the most serious
  external-validity limit and belongs in the same paragraph as any result.
- **No harm is demonstrated.** The bench observes capability, never incidence. No real client,
  no real server, no real token.
- **Perishable.** D changed between two releases of one package. Every row carries a version
  and a date because a sentence without them will be false soon.
- **Not a headline.** R11's candidate list is frozen and this is not on it. The bench closes a
  named construct-validity gap; it is not a result of the census.

## ⚠️ Disclosure decision required before publication

A2 (all three implementations) and B2 (v1) are security-relevant deviations from MUST-level
clauses in **named vendors' code**. Unlike the census this touches no third-party system, so
there is no Menlo analysis to redo — but there is a disclosure decision, most cheaply an
upstream issue on each repository, which also timestamps the observation.

**This has not been done and is not the bench's call to make.**
