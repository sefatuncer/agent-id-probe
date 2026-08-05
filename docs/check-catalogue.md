<!-- GENERATED - do not edit by hand, run scripts/gen_catalogue.py -->

# Check catalogue

**GENERATED - do not edit by hand, run `scripts/gen_catalogue.py`.**
CI runs `python scripts/gen_catalogue.py --check` and fails the build if this file
and the code disagree.

Every row is recovered from the instrument itself: `CheckId`, `FUNNELS` and
`DESCRIPTIVE_ONLY` from `src/agentidprobe/models.py`, and every emission site from
the abstract syntax tree of the check modules. Nothing here is maintained by hand,
because the hand-maintained version drifted: it once listed two checks that had been
deleted from the code and omitted eight that were running.

Reading the columns:

- **Funnel** - the funnel this check is a stage of (`models.FUNNELS`). A check with
  no funnel is still measured and reported; it is simply not a funnel stage.
- **Strength** - every `NormativeStrength` the check is emitted with. More than one
  means different code paths cite different clauses. Decision rule R1 constrains only
  the paths that report a failure, so an `error` or `not_applicable` path may carry a
  strength it never uses.
- **Descriptive-only** - membership of `models.DESCRIPTIVE_ONLY`. These can never
  report a failure: `CheckResult.model_post_init` raises if one tries.
- **Spec anchor** - the `spec_ref` text passed at the call site, verbatim. A blank
  cell means no code path cites a clause, which for a check that can fail is a defect.
- **Emitted in** - source file and number of call sites.

| ID | Enum member | Funnel | Strength | Descriptive-only | Spec anchor | Spec URL | Emitted in |
|---|---|---|---|---|---|---|---|
| C01 | `IDENTITY_METADATA_PUBLISHED` | `signed_document` | `should` | no | A2A agent discovery: the standard path is /.well-known/agent-card.json<br>A2A agent discovery | https://a2a-protocol.org/v0.3.0/topics/agent-discovery/ | `checks_signed.py` x4 |
| C02 | `CARD_SIGNED` | `signed_document` | `may` | yes | A2A 5.5.6: AgentCardSignature is a data structure; publishing one is optional and the revision states no duty to | https://a2a-protocol.org/v0.3.0/specification/ | `checks_signed.py` x4 |
| C03 | `KEY_RESOLVABLE` | `signed_document` | `may` | yes | RFC 8785 number formatting<br>RFC 8785<br>A2A 5.5.6: key located from the signature's own `jku`/`kid`/did:web, the revision naming no discovery duty<br>A2A v0.3.0 defines AgentCardSignature (5.5.6) without obliging the publisher to make the verification key discoverable | https://www.rfc-editor.org/rfc/rfc8785.html<br>https://a2a-protocol.org/v0.3.0/specification/ | `checks_signed.py` x9 |
| C04 | `SIGNATURE_VERIFIES` | `signed_document` | `may` | yes | RFC 8785 number formatting<br>RFC 7515 5.2 over the RFC 8785 canonical payload, canonicalisation being this instrument's choice and not A2A v0.3.0's<br>RFC 7515 5.2; verification not attempted, so no failure was observed<br>RFC 7515 5.2 binds the party validating a JWS, not the party publishing one; A2A v0.3.0 states no signature obligation for the publisher | https://www.rfc-editor.org/rfc/rfc8785.html<br>https://www.rfc-editor.org/rfc/rfc7515.html#section-5.2 | `checks_signed.py` x10 |
| C05 | `PRM_PRESENT` | `oauth_metadata` | `must` | no | RFC 9728 3.2<br>MCP: servers MUST implement RFC 9728<br>MCP: PRM MUST include authorization_servers with at least one entry | https://www.rfc-editor.org/rfc/rfc9728.html<br>https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization | `checks_oauth.py` x5 |
| C07 | `WWW_AUTH_RESOURCE_METADATA` | - | `should` | no | MCP Authorization, discovery | https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization | `checks_oauth.py` x1 |
| C08 | `SENDER_CONSTRAINED` | - | `may` | yes | RFC 9449 DPoP and mTLS sender-constraining are optional in MCP | https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization | `checks_oauth.py` x1 |
| C09 | `REVOCATION_DECLARED` | - | `may` | yes | RFC 7009 revocation is optional; no specification requires an agent identity to be revocable | https://www.rfc-editor.org/rfc/rfc8414.html | `checks_oauth.py` x1 |
| C11 | `TLS_VALID` | - | `must` | no | MCP: all authorization server endpoints MUST be served over HTTPS; BCP 195<br>MCP: endpoints MUST be served over HTTPS | https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization | `checks_oauth.py` x2 |
| C12 | `PRM_RESOURCE_IDENTITY_MATCH` | `oauth_metadata` | `must` | no | RFC 9728 3.3<br>RFC 9728 3.3: the resource value returned MUST be identical | https://www.rfc-editor.org/rfc/rfc9728.html | `checks_oauth.py` x2 |
| C13 | `AS_CORRESPONDENCE` | `oauth_metadata` | `must` | no | RFC 8414 3.3: issuer value MUST be identical to the issuer requested<br>RFC 8414 3<br>RFC 8414 3.3 | https://www.rfc-editor.org/rfc/rfc8414.html | `checks_oauth.py` x6 |
| C14 | `PKCE_DECLARED` | - | `should` | yes | MCP Authorization<br>RFC 9700 (BCP 240) 2.1.1: publishing code_challenge_methods_supported is RECOMMENDED, and an authorization server MAY instead provide a deployment-specific way to determine PKCE support; RFC 8414 2 marks the element OPTIONAL | https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization<br>https://www.rfc-editor.org/rfc/rfc9728.html<br>https://www.rfc-editor.org/rfc/rfc9700.html | `checks_oauth.py` x7 |
| C15 | `KEY_STRENGTH` | - | `must` | no | RFC 7518 3.3: a key of size 2048 bits or larger MUST be used with these algorithms<br>RFC 7518 3.6 binds the verifier, not the publisher, and RFC 8725's prohibitions govern JWTs rather than a detached JWS; recorded without penalty (R1, R6, R9.7) | https://www.rfc-editor.org/rfc/rfc7518.html#section-3.3<br>https://www.rfc-editor.org/rfc/rfc7518.html#section-3.6 | `checks_signed.py` x10 |
| C16 | `ISS_PARAMETER_DECLARED` | - | `should` | yes | RFC 9207 2.3: a server supporting the specification MUST indicate its support by setting authorization_response_iss_parameter_supported to true; RFC 9700 (BCP 240) 2.1 makes a mix-up defence REQUIRED of the client | https://www.rfc-editor.org/rfc/rfc9207.html#section-2.3 | `checks_oauth.py` x1 |
| C17 | `CLIENT_BOOTSTRAP_DECLARED` | - | `should` | yes | MCP: clients fall back to prompting the user when no registration mechanism is advertised | https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization | `checks_oauth.py` x1 |
| C18 | `PROTECTED_RESOURCES_DECLARED` | - | `may` | yes | RFC 9728 4: `protected_resources` is OPTIONAL; 7.6 recommends cross-checking the two lists but puts AS selection out of scope | https://www.rfc-editor.org/rfc/rfc9728.html | `checks_oauth.py` x1 |

## Funnel order

Two funnels scored over disjoint denominators (`models.FUNNELS`). An endpoint using
OAuth-only identity must not be counted as failing a signature check it was never
required to satisfy, so the two are never merged into one rate.

**`oauth_metadata`**

1. (no check) - reachable
2. `C05` - publishes protected-resource metadata
3. `C12` - resource identifier matches
4. `C13` - declared issuer corresponds

**`signed_document`**

1. (no check) - reachable
2. `C01` - publishes identity metadata
3. `C02` - carries a signature
4. `C03` - key resolvable
5. `C04` - signature verifies

## Integrity

- 16 checks declared in `CheckId`; 16 emitted by at least one code path.
- 65 emission sites across 2 modules.
- No check is declared without being emitted.
