# agent-id-probe

Passive, spec-anchored measurement of identity and authorization metadata published by
deployed AI agent endpoints.

**Research question.** Deployed AI agents increasingly *claim* an identity — A2A Agent
Cards, MCP authorization metadata, `did:web` documents. This study asks whether that
claim is *verifiable*: does the published metadata support a cryptographic chain from an
observed endpoint back to an accountable, revocable actor?

**Why it matters.** The July 2026 Hugging Face incident involved more than 17,000 recorded
actions executed by an autonomous agent framework across a swarm of short-lived sandboxes.
Reconstructing that campaign was hard partly because those actions carried no verifiable
identity. Before proposing new agent-identity mechanisms, it is worth measuring what the
deployed ecosystem actually publishes today.

## Design rule

> Every check maps to a normative sentence in a published specification.

The ground truth is the spec text (A2A Agent Card, MCP Authorization, RFC 9728, RFC 8414,
RFC 8707, RFC 9449, `did:web`, IETF Token Status List, W3C VC 2.0) — never the authors'
judgement. See `docs/spec-mapping.md`. This is what keeps the instrument outside the
authors' control.

## The ten checks

| ID | Check | Funnel stage |
|----|-------|--------------|
| C01 | An identity document is served at all | ✔ |
| C02 | That document carries a JWS signature | |
| C03 | `jwks_uri` / `did:web` resolves to a usable key | ✔ |
| C04 | The signature actually verifies | ✔ |
| C05 | RFC 9728 protected-resource metadata present and valid | |
| C06 | RFC 8414 authorization-server metadata resolves and valid | |
| C07 | RFC 8707 resource indicators supported | |
| C08 | RFC 9449 DPoP or mTLS sender-constraining declared | |
| C09 | Revocation / status list declared and queryable | ✔ |
| C10 | Key chains to an organisational trust root | ✔ |

## Failure taxonomy

Every failure is classified as **unimplemented** (the mechanism is absent),
**misimplemented** (present but violating the spec), or **unspecified** (the spec does not
settle the question). The third class is feedback to standards bodies rather than to
deployments, and is reported separately.

## Ethics

This study is passive and read-only. It fetches documents that operators deliberately
publish at well-known locations. It does not authenticate, write, exploit, or attempt to
bypass any control. Rate limits, `robots.txt` handling, an identifying `User-Agent` and an
opt-out contact are enforced in `config.py`, not merely promised. Only aggregate results
are published. See `docs/ETHICS.md`.

## Cost

Zero. No paid API, no cloud account, no subscription. Runs on a single machine.

## Status

Phase 0 — feasibility ("kill test"). The project proceeds only if a sufficiently large and
*variable* public corpus exists. See `ARASTIRMA-PLANI.md` in the parent directory.

## Licence

Code Apache-2.0. Collected data and derived tables CC-BY-4.0.
