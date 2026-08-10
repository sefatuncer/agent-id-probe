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
