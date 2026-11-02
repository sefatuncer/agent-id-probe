# Client bench — case matrix

**Frozen 10 August 2026, before the bench was run.**

This file plays the role `docs/decision-rules.md` plays for the census: it fixes what counts
as conformant *before* any implementation is observed, so that a surprising result cannot be
absorbed by redefining the expectation. Every row's "required" column is derived from quoted
specification text, never from what an implementation happens to do.

The same rule as the census applies here: **a row may record non-conformance only where a
specification places an RFC 2119 MUST on the party being observed.** Where the obligation is
weaker, the row records behaviour and says so.

## What is being observed

MCP clients, not servers. The census measures what a resource server publishes; this measures
whether a client would act on it. It is a convenience sample of installable implementations
and **carries no prevalence claim** — the reportable form is "of the *N* tested, *k*", never
"most clients".

## Pinned implementations

| Package | Version | Obtained |
|---|---|---|
| `@modelcontextprotocol/sdk` | 1.30.0 | npm, no account |
| `@modelcontextprotocol/client` | 2.0.0 | npm, no account |

Node v24.15.0. Every row carries the version, because finding (c) changed between two releases
of one package and any sentence without a version will be false within a month.

## The normative text

**RFC 9728, Section 3.3** — the clause the `resource` cases test:

> "The `resource` value returned **MUST** be identical to the protected resource's resource
> identifier value into which the well-known URI path suffix was inserted to create the URL
> used to retrieve the metadata. If these values are not identical, the data contained in the
> response **MUST NOT** be used."

One word carries it: **identical**. Not "compatible", not "same origin", not "an ancestor of".

**RFC 8414, Section 3.3** — the clause the issuer cases test:

> "The `issuer` value returned **MUST** be identical to the authorization server's issuer
> identifier value into which the well-known URI string was inserted to create the URL used
> to retrieve the metadata. If these values are not identical, the data contained in the
> response **MUST NOT** be used."

**RFC 9728, Section 4** defines `protected_resources` in authorization-server metadata, and
**Section 7.6** offers the cross-check it enables as the *sole* mitigation for a problem it
declares out of scope. Neither clause obliges a client to read the field, so **C-series rows
below are descriptive and cannot record non-conformance.** This mirrors the census's
`DESCRIPTIVE_ONLY` treatment of C18.

**RFC 9207, Section 2.4** plus MCP revision 2026-07-28, which makes the check a client MUST:

> "On receiving the authorization response, MCP clients **MUST** apply the validation in
> RFC 9207 Section 2.4 before transmitting the authorization code to any token endpoint."

## A-series — PRM `resource` against the requested identifier

Requested identifier in every row: `http://127.0.0.1:PORT/tenant-a/mcp`.

| ID | PRM `resource` | Required by RFC 9728 §3.3 | Strength |
|---|---|---|---|
| A1 | `…/tenant-a/mcp` | **use** — identical | MUST |
| A2 | `…/` | **reject** — not identical (proper ancestor) | MUST |
| A3 | `…/tenant-b/mcp` | **reject** — not identical (sibling) | MUST |
| A4 | `http://attacker.example/mcp` | **reject** — not identical (cross-origin) | MUST |
| A5 | *absent* | **reject** — §2 makes `resource` REQUIRED, so the document is malformed | MUST |
| A6 | `…/tenant-a/mcp/` | **reject** — not identical (trailing slash) | MUST |
| A7 | `…/TENANT-A/mcp` | **reject** — RFC 3986 §6.2.2.1 makes only scheme and host case-insensitive | MUST |

**A2 is the row that matters.** A tolerance admitting only *broader* identifiers lets a
resource server widen the audience of the token the client requests. A1 and A4 failing closed
would not exonerate an implementation that admits A2.

Recorded per row: accepted or rejected, and **which identifier the client adopted** when it
accepted. Adoption is the part with teeth — a client that accepts A2 and then requests a token
for `…/` has had its audience chosen by the server.

## B-series — authorization-server metadata `issuer`

| ID | AS metadata `issuer` | Required by RFC 8414 §3.3 | Strength |
|---|---|---|---|
| B1 | matches the discovery URL | **use** | MUST |
| B2 | names a different origin | **reject** | MUST |

MCP restates this one as a worked example with an attacker in it, and restates RFC 9728 §3.3
nowhere. Whether implementations mirror that asymmetry is the question B answers alongside A.

## C-series — `protected_resources` (descriptive only)

| ID | Observation | Strength |
|---|---|---|
| C1 | Is `protected_resources` present in the AS metadata schema the client parses? | none — descriptive |
| C2 | With several entries in `authorization_servers`, which does the client choose? | none — descriptive |

No clause obliges a client to read the field, so a negative here is **not** non-conformance.
It is evidence about whether §7.6's only mitigation is consumed, which is what makes the
census's C18 rate meaningful or moot.

## D-series — RFC 9207 `iss` (MCP 2026-07-28 client MUST)

| ID | `iss` in response | `authorization_response_iss_parameter_supported` | Required | Strength |
|---|---|---|---|---|
| D1 | correct | true | **accept** | MUST |
| D2 | wrong | true | **reject** | MUST |
| D3 | absent | true | **reject** | MUST |
| D4 | correct | absent | **accept** | MUST |
| D5 | wrong | absent | **reject** — a present `iss` is compared regardless of advertisement | MUST |
| D6 | absent | absent | **accept** — nothing to compare | MUST |

## Recording rules

1. **A row that cannot be exercised is recorded as `not_exercised` with the reason.** It is
   never silently dropped and never counted as a pass. The census learned this the hard way:
   an endpoint that vanished from the report shrank every denominator in silence.
2. **The absence of an exported function is a finding, not an error.** v1 exporting no
   `validateAuthorizationResponseIssuer` is the D-series answer for v1, not a failure to test it.
3. Output is JSONL, one record per (implementation, case), in the shape the probe already
   uses, so the same replay discipline applies.
4. **No claim about closed-source clients.** Claude Desktop, Cursor, ChatGPT connectors and
   other proprietary hosts are invisible to this method and plausibly carry most real MCP
   traffic. This is the bench's most serious external-validity limit and must be stated in the
   same paragraph as any result.

## Amendment, 2 November 2026: the Tier-1 run

Written before any implementation below was installed or run. The cases above and their
"required" columns are unchanged.

**Population.** Every SDK the MCP project lists as Tier 1 at modelcontextprotocol.io/docs/sdk,
read 1 November 2026: TypeScript, Python, C#, Go, Rust and Ruby. Each at its latest release on
2 November 2026, read from its registry that day, plus the latest release of the TypeScript v1
line, which a large share of installed applications still carries:

| SDK | Package | Release |
|---|---|---|
| TypeScript v1 line | `@modelcontextprotocol/sdk` (npm) | 1.32.2 |
| TypeScript | `@modelcontextprotocol/client` (npm) | 2.4.0 |
| Python | `mcp` (PyPI) | 2.3.0 |
| C# | `ModelContextProtocol` (NuGet) | 2.3.0 |
| Go | `github.com/modelcontextprotocol/go-sdk` | v1.8.0 |
| Rust | `rmcp` (crates.io) | 3.8.0 |
| Ruby | `mcp` (RubyGems) | 1.8.2 |

The population is defined by the project's own tiering, not by convenience, but it is still
not a sample of the clients in use, and the "of the *N* tested, *k*" form still applies.

**Method: the SDK's own authorization flow, observed from the server.** Each implementation's
client authorization flow is driven end to end against one loopback server that plays the
protected resource and the authorization servers and approves every request. The bench plays
the user agent: it requests the authorization URL the SDK produces, reads the redirect, and
hands back whatever the SDK's callback interface accepts. A cell is decided from the requests
the server *receives*, never from what the SDK returns:

- A and B: **use** if the flow reaches an authorization endpoint after being served the case's
  document, **reject** if it does not. The `resource` parameter on the authorization and token
  requests is recorded; where it differs from the requested identifier the server has chosen
  the token's audience.
- C2: which authorization server's endpoint the flow reaches.
- D: **accept** if the authorization code reaches a token endpoint, **reject** if it does not,
  which is the moment MCP 2026-07-28 names ("before transmitting the authorization code").
- C1: unchanged, the count of shipped files naming `protected_resources`.

Where a flow cannot be driven without a browser, or the callback interface has no channel for
a value the case varies, the cell records that, with the reason, as rule 1 requires. An SDK
whose callback interface cannot carry `iss` cannot apply RFC 9207 itself; its D cells are
recorded as observed, with that reason in the detail, since the obligation then falls on the
embedding application and no SDK-level check exists.

**One descriptive case added.**

| ID | Observation | Strength |
|---|---|---|
| C3 | The authorization server's metadata publishes `protected_resources` **without** the requested resource. Does the flow proceed? | none — descriptive |

C3 turns C1 from a source count into behaviour: a client that proceeds has not applied the
RFC 9728 §7.6 cross-check, though nothing obliges it to.

**Not observed: the token's audience.** Whether a token is accepted is decided by the server
this bench configures, so observing it would measure our own configuration.

**Correction during the run, 2 November 2026.** The first TypeScript run served a document
naming the root issuer, which is also where a client lands when it discards the document and
falls back to the 2025-03-26 behaviour of treating the resource's origin as its authorization
server. A5 therefore read "use" for both TypeScript lines although neither used the document:
the authorization request carried no `resource` at all. The document now names a path issuer
(`/as-first`) that only the document points to, so "use" means reaching that issuer and a
fallback is recorded as such. The required column is unchanged, and no cell had been reported.
