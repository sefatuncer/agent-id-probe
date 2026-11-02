# Tier-1 client bench — results

**Run 2 November 2026.** Cases fixed in `../CASE-MATRIX.md` (frozen 10 August 2026, amended
2 November 2026 before anything below was installed). One record per (implementation, case) in
`results.jsonl`; the server's request logs in `raw/` (second run) and `raw-run1/` (first run).
This supersedes `../RESULTS.md`, the function-level run of 10 August over three releases.

## Population

Every SDK the MCP project lists as Tier 1, at its latest release on 2 November 2026, plus the
latest release of the TypeScript v1 line. This is the project's own tiering, not a sample of
the clients in use, so the reportable form stays *"of the seven tested, k"*.

| Column | Package | Release | Image (digest in `raw/images.txt`) |
|---|---|---|---|
| TS v1 | `@modelcontextprotocol/sdk` (npm) | 1.32.2 | `node:24.21.0-trixie` |
| TS | `@modelcontextprotocol/client` (npm) | 2.4.0 | `node:24.21.0-trixie` |
| Python | `mcp` (PyPI) | 2.3.0 | `python:3.13-trixie` |
| C# | `ModelContextProtocol` (NuGet) | 2.3.0 | `mcr.microsoft.com/dotnet/sdk:10.0.401-resolute` |
| Go | `github.com/modelcontextprotocol/go-sdk` | v1.8.0 | `golang:1.27.1-trixie` |
| Rust | `rmcp` (crates.io) | 3.8.0 | `rust:1.98.1-trixie` |
| Ruby | `mcp` (RubyGems) | 1.8.2 | `ruby:3.4.11-trixie` |

## Method

`run.sh` starts one loopback server (`fake/server.mjs`) that plays the protected resource and
the authorization servers `/as-first` and `/as-second`, and approves every request. Each SDK
then runs in its own container sharing that server's network namespace, so every request goes
to `127.0.0.1` and nothing leaves the host except package downloads. Every container is
limited to two CPUs (the server to half of one).

Each driver (`ts/`, `python/`, `csharp/`, `go/`, `rust/`, `ruby/`) runs the SDK's **own**
authorization flow and plays only the user agent: it requests the authorization URL the SDK
produced, reads the redirect without following it, and hands the code, state and `iss` back
through whatever callback interface the SDK offers. **No outcome is decided by a driver.**
`score.py` reads the server's request log for each case:

- **A, B — use / reject.** *Use* means the flow reached the authorization endpoint of a server
  the document names. *Reject* with an asterisk means the client discarded the document and fell
  back to treating the resource's origin as its authorization server, the 2025-03-26 behaviour.
- **and adopt.** The authorization request carried the document's `resource` instead of the
  requested identifier. On A2 that identifier is broader (`audience_widened`).
- **C1** counts shipped files naming `protected_resources`; **C2** records which of two
  authorization servers the flow reached; **C3** whether it proceeds when the server's metadata
  lists other resources and not the requested one.
- **D — accept / reject.** *Accept* means the authorization code reached a token endpoint, the
  moment MCP 2026-07-28 names ("before transmitting the authorization code").

A1 is the control for A, B and C, and D1 for D. Had a control failed, its series would be
`not_exercised`. None did.

## Results

Bold marks a departure from the "required" column fixed in `../CASE-MATRIX.md`.

| Case | Document or response | Required | TS v1 | TS | Python | C# | Go | Rust | Ruby |
|---|---|---|---|---|---|---|---|---|---|
| A1 | `resource` identical | use | use | use | use | use | use | use | use |
| **A2** | `resource` a proper ancestor | reject | **use and adopt** | **use and adopt** | **use and adopt** | **use and adopt** | reject* | **use and adopt** | **use and adopt** |
| A3 | sibling path | reject | reject | reject | reject | reject | reject* | reject | reject |
| A4 | cross-origin | reject | reject | reject | reject | reject | reject* | reject | reject |
| A5 | `resource` absent | reject | reject* | reject* | reject* | reject | reject* | reject | **use** |
| A6 | trailing slash only | reject | reject | reject | **use and adopt** | **use and adopt** | reject* | reject | reject |
| A7 | path differing in case | reject | reject | reject | reject | **use and adopt** | reject* | reject | reject |
| B1 | AS `issuer` matches discovery URL | use | use | use | use | use | use | use | use |
| B2 | AS `issuer` names another origin | reject | **use** | reject | reject | reject | reject | reject | reject |
| C1 | files naming `protected_resources` | — | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| C2 | two `authorization_servers` | — | first | first | first | first | first | first | first |
| C3 | AS lists other resources only | — | proceeds | proceeds | proceeds | proceeds | proceeds | proceeds | proceeds |
| D1 | `iss` correct, advertised | accept | accept | accept | accept | accept | accept | accept | accept |
| D2 | `iss` wrong, advertised | reject | **accept** | reject | reject | reject | reject | reject | reject |
| D3 | `iss` absent, advertised | reject | **accept** | reject | reject | reject | reject | reject | reject |
| D4 | `iss` correct, not advertised | accept | accept | accept | accept | accept | **reject** | accept | accept |
| D5 | `iss` wrong, not advertised | reject | **accept** | reject | reject | reject | reject | reject | reject |
| D6 | `iss` absent, not advertised | accept | accept | accept | accept | accept | accept | accept | accept |

15 of 126 cells depart from the required column. None is left not exercised.

### A — RFC 9728 §3.3, "identical"

No release lets a document move the token's audience to another origin or a sibling path. Six
of seven accept a `resource` that is a proper ancestor of the requested identifier and then
send that broader identifier as the `resource` parameter of both the authorization and the
token request: `http://127.0.0.1:8765/` in five, `http://127.0.0.1:8765` without the slash in
Ruby. Go alone compares exactly (`oauthex/resource_meta.go`: `prm.Resource != resourceURL`)
and then falls back to the origin as authorization server.

Every rejection was checked against the SDK's own error message, so each is attributable to
the intended check and not to an unrelated failure: for example Python's `Protected resource
… does not match expected …`, Rust's `missing required resource field`, C#'s `Resource URI in
metadata () does not match the expected URI`.

### B — RFC 8414 §3.3

Only the TypeScript v1 line uses issuer metadata naming another origin.

### C — `protected_resources` (descriptive only)

No shipped file of any release names the field, every flow proceeds when the authorization
server's metadata lists other resources, and every release takes the first of two
authorization servers. Nothing obliges a client to read the field, so none of this is
non-conformance. It means the RFC 9728 §7.6 cross-check is not performed by any tested release.

### D — RFC 9207 under MCP 2026-07-28

- **TS v1.** The callback interface (`finishAuth(code)`) carries the code alone, so no `iss`
  reaches the SDK and the wrong and absent rows are accepted. The check then falls to the
  embedding application, as the amendment's method paragraph provides.
- **Go, D4.** A correct `iss` from an authorization server that does not advertise support is
  rejected by default (`authorization server does not advertise RFC 9207 iss parameter support
  but iss was received`). MCP 2026-07-28's table says to compare it: *"`false` or absent |
  present | Compare to the recorded issuer"*, and adds that this row *"applies the local-policy
  provision in RFC9207 Section 2.4"*. RFC 9207 §2.4 itself says clients *"SHOULD discard
  authorization responses with the `iss` parameter from authorization servers that do not
  indicate their support"*. Go follows the RFC's default and exposes `AcceptUnadvertisedIss`
  to follow MCP's table. The cell is a departure from the pre-specified column and is kept as
  one, but it **fails closed** and is not a security weakness.
- The other five releases match all six rows.

## Replication

`run.sh` was run twice. Scored by the same `score.py`, the 126 records of the two runs are
identical in every field except `run_at` (`python score.py raw-run1` rescored the first run).
After the Python driver was reformatted for the linter, its arm was run a third time and again
produced identical records; `raw/python.jsonl` is that run.

## Change from 10 August

The August run called exported discovery functions of three releases; this one drives the
complete flow of seven. The A2 finding holds. Python's A5, written in August from the 2.0.0
source as *use*, is observed in 2.3.0 as a discarded document. Python's B and D cells and every
C2 cell, not exercised in August, are now observed.

## Things a reader of the records should know

- **The default world sends a correct but unadvertised `iss`.** Outside the D cases the
  server's authorization endpoint includes `iss` without advertising it. A, B and C cells are
  decided before the callback, so this does not affect them, but it is why Go's flows outside
  D stop after the authorization endpoint and show no token request.
- **Undeclared Ruby dependencies.** `mcp` 1.8.2 needs `faraday`, `event_stream_parser` and
  (on Ruby 3.4) `base64` for its HTTP client and OAuth flow, and declares none of them. They
  are installed explicitly at pinned versions.
- **Rust leaves the flow to the application.** rmcp's `OAuthState` is driven step by step; the
  driver makes the unauthenticated request whose 401 carries the challenge and passes it in.
- **C# errors after the token.** C#'s records show a JSON error about a `DiscoverResult` after
  the token request. It comes from the minimal `initialize` answer of the bench's server and
  arises after every cell has been decided.
- **The token's audience is not observed.** Whether a token is accepted is decided by the
  server this bench configures, so observing it would measure our own configuration.

## Scope and limits

- **No prevalence claim.** Seven releases of one project's SDKs.
- **Closed-source clients are invisible.** Claude Desktop, Cursor, ChatGPT connectors and other
  proprietary hosts plausibly carry most real MCP traffic. This is the bench's most serious
  external-validity limit.
- **No harm is demonstrated.** Capability, not incidence: no real client, server or token.
- **Perishable.** Every record carries a version and a date.

## Disclosure

No maintainer was notified (`docs/ETHICS.md` §9, amended 1 October 2026).

## Reproducing

```sh
cd client-bench/tier1
./run.sh            # Docker running; on Windows Git Bash: MSYS_NO_PATHCONV=1 BENCH_DIR="$(pwd -W)" ./run.sh
python score.py     # re-score raw/ without running anything
```

First run on this machine: about ten minutes, most of it the Rust build and package downloads;
a rerun with caches about two minutes.
