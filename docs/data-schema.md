# Data Schema — `agent-id-probe`

What a published run contains, field by field, and the three things that will silently
corrupt your numbers if you do not know them.

Every field below is read out of the code that writes it (`src/agentidprobe/store.py`,
`models.py`, `checks_oauth.py`, `checks_signed.py`, `collectors.py`). Every example record
is cut from the committed demonstration run in `results/runs/example/` and
`data/raw/example/`; elisions are marked `…`. That run is synthetic — hand-built over
RFC 2606 `example.org` hosts, regenerable with `scripts/make_example_run.py`, and no real
endpoint was contacted to produce it. It exists so this document can point at real bytes.

Outcome semantics are governed by `docs/decision-rules.md` (rules R1–R11), which was
frozen before the main measurement run. Where a field encodes a rule, the rule number is
cited.

---

## 1. The four files

A run is identified by a `run_id` (default `%Y%m%dT%H%M%SZ`, e.g. `20260728T221500Z`) and
writes into two trees under the project root (`--root`, default `.`):

| Path | Written by | Write mode | Expected lines |
|---|---|---|---|
| `results/runs/<id>/manifest.json` | `collect`, `rescore` | truncate + rewrite | 1 (single-line JSON object) |
| `results/runs/<id>/corpus.jsonl` | `collect` | truncate + rewrite | one per collected endpoint |
| `results/runs/<id>/reports.jsonl` | `probe`, `rescore` | **append-only** | **≥** one per (endpoint, modality) — see §3 |
| `data/raw/<id>/artifacts.jsonl` | `probe` | **append-only** | one per HTTP response, many per endpoint |

Notes that matter before you parse anything:

- **`probe` does not write a manifest.** Only `collect` and `rescore` call
  `RunStore.write_manifest`. A run directory whose manifest says `"stage": "collect"` may
  still contain a complete `reports.jsonl`. (The committed example run says
  `"stage": "probe"` because its generator script writes one explicitly.)
- **JSON key order differs between files.** `corpus.jsonl` is emitted by Pydantic in
  field-declaration order; `manifest.json`, `reports.jsonl` and `artifacts.jsonl` go
  through `RunStore._dump`, which uses `sort_keys=True, ensure_ascii=False`. Do not rely
  on key order for anything.
- **A run killed mid-write can leave one unparseable trailing line.** Every reader in
  `store.py` except `read_corpus` skips malformed lines rather than aborting; the next
  append closes the torn line with a newline first, so it costs at most that one record.
- **Only the two `.jsonl` files under `results/runs/` are joinable by `endpoint_id`.**
  Agent-card endpoints are *derived at probe time* (`derive_card_endpoints`, one card
  candidate per distinct origin in the OAuth corpus) and are **never written to
  `corpus.jsonl`**. If you left-join `reports.jsonl` onto `corpus.jsonl` you will drop the
  entire signed-document modality. Each report embeds its own full `endpoint` object; use
  that.

---

## 2. `results/runs/<id>/manifest.json`

One JSON object, one line. Provenance for the run: without it a set of JSONL files is not
reproducible, because `probe_version` alone does not say where the requests came from.

| Field | Type | Meaning |
|---|---|---|
| `run_context.run_id` | string | Run identifier; matches the directory name |
| `run_context.vantage_point` | string | Where the run originated, e.g. `residential-TR`, `offline-replay`, `synthetic`. Free text supplied via `--vantage-point`; default `unspecified` |
| `run_context.dns_resolver` | string \| null | Resolver used. Never set by the CLI; present for runs configured programmatically |
| `run_context.probe_git_commit` | string \| null | `git rev-parse HEAD` of the probe at run time, or null if git was unavailable |
| `run_context.started_at` | string (ISO 8601) | When the run began |
| `probe_version` | string | `PROBE_VERSION` of the writing code (`0.1.0`) |
| `written_at` | string (ISO 8601, UTC) | When the manifest itself was written |
| `stage` | string | `collect`, `rescore`, or `probe` (the example generator only) |

### Keys added by `collect`

| Field | Type | Meaning |
|---|---|---|
| `sources` | array of objects | One `CollectionStats` record per registry queried — see table below |
| `endpoints` | integer | Size of the merged corpus after de-duplication by `endpoint_id` |
| `unique_apex_domains` | integer | Distinct non-null `apex_domain` values in the corpus |
| `capture_recapture` | object \| null | Lincoln–Petersen/Chapman population estimate across two registries; null when only one registry was queried |

`sources[]` (`CollectionStats.as_dict()`):

| Field | Type | Meaning |
|---|---|---|
| `source` | string | Collector name: `mcp-official-registry` or `smithery` |
| `records_seen` | integer | Registry records iterated |
| `remote_urls_seen` | integer | Candidate remote-transport URLs extracted from those records |
| `endpoints_kept` | integer | Unique endpoints kept after the two drop filters below |
| `unique_apex_domains` | integer | Distinct apex domains among the kept endpoints |
| `dropped_no_apex` | integer | URLs whose host yielded no eTLD+1 (IP literals, unknown suffixes). **Watch this counter** — a high value means the public-suffix snapshot is missing real TLDs and endpoints are being lost silently |
| `dropped_not_https` | integer | URLs not beginning `https://`; plain HTTP cannot carry a meaningful identity claim |
| `pages_fetched` | integer | Registry pages retrieved |
| `errors` | array of strings | Pagination and parse failures — **read this, see §5 trap 2** |

`capture_recapture`: `n_a`, `n_b` (integers, per-registry endpoint counts), `overlap`
(integer), `estimate` (integer or null), and either `estimator: "Chapman"` or, when the
overlap is zero, `note: "no overlap; the registries do not sample a shared population"`.

### Keys added by `rescore`

| Field | Type | Meaning |
|---|---|---|
| `rescored_from` | string | `run_id` of the source run |
| `rescore_probe_version` | string | Probe version that performed the replay |
| `reports_in` | integer | Reports read from the source run |
| `reports_out` | integer | Reports produced. **`reports_out < reports_in` means some endpoints had no stored response for their own URL and were skipped** |

### Real record

```json
{"cases": [{"demonstrates": "everything matches", "url": "https://conforming.example.org/mcp"}, …],
 "endpoints": 4,
 "note": "Hand-built demonstration data over RFC 2606 example.org hosts. No real endpoint was contacted. Regenerate with scripts/make_example_run.py.",
 "probe_version": "0.1.0",
 "run_context": {"dns_resolver": null, "probe_git_commit": null, "run_id": "example",
                 "started_at": "2026-07-28T22:28:38.141472Z", "vantage_point": "synthetic"},
 "stage": "probe", "synthetic": true,
 "written_at": "2026-07-28T22:28:38.141472+00:00"}
```

(`cases`, `note` and `synthetic` are specific to the demonstration run's generator.)

---

## 3. `results/runs/<id>/corpus.jsonl`

The population, before any of it is contacted. One `Endpoint` per line.

| Field | Type | Meaning |
|---|---|---|
| `endpoint_id` | string | First 16 hex characters of `sha256(url)`. Deterministic from the URL, so the same URL carries the same id in every run |
| `url` | string | Canonical endpoint URL as the registry published it |
| `kind` | enum | `mcp_remote` · `a2a_agent_card` · `did_web` |
| `source` | string | Which free registry surfaced it. `+`-joined when several did (`mcp-official-registry+smithery`) — that overlap is what makes the capture–recapture estimate possible. `derived:mcp-origin` for agent-card candidates, `synthetic-example` in the demonstration run |
| `source_url` | string \| null | For derived agent-card endpoints, the MCP endpoint whose origin produced this candidate. Null otherwise |
| `apex_domain` | string \| null | eTLD+1 of the host. **See §5 trap 3.** Null when the host is an IP literal or its suffix is not in the bundled public-suffix snapshot (such endpoints are dropped at collection and counted in `dropped_no_apex`) |
| `publisher_namespace` | string \| null | Reverse-DNS namespace the registry itself verified before accepting publication (`io.github.someone`), lower-cased. Externally supplied clustering arm under R10.2b — not something this project invented |
| `asn` | string \| null | **Declared but never collected. Always null.** R10.2 forbids an uncollected arm from feeding any decision rule |
| `country` | string \| null | **Declared but never collected. Always null.** |
| `hosting` | enum | `hosted_platform` · `self_hosted` · `unknown`. Derived from a hand-written suffix list, so under R10.3 it is a **label only** and may not be used as a cluster variable |
| `registry_listed` | boolean | True when a registry listed it; false for derived card candidates |
| `first_seen` | string (ISO 8601) \| null | Collection timestamp |
| `last_seen` | string (ISO 8601) \| null | Collection timestamp |

### Real record

```json
{"endpoint_id":"d7dcb9dfe6d3c2ce","url":"https://mismatch.example.org/mcp","kind":"mcp_remote",
 "source":"synthetic-example","source_url":null,"apex_domain":"example.org",
 "publisher_namespace":null,"asn":null,"country":null,"hosting":"unknown",
 "registry_listed":false,"first_seen":null,"last_seen":null}
```

---

## 4. `results/runs/<id>/reports.jsonl`

One scored verdict per (endpoint, modality). This is the analysis file.

| Field | Type | Meaning |
|---|---|---|
| `endpoint` | object | Full copy of the `Endpoint` record (§3). Self-contained — do not rely on a join to `corpus.jsonl` |
| `modality` | enum | `oauth_metadata` (MCP authorization, checks C05/C07/C08/C09/C11–C18) or `signed_document` (A2A card / did:web, checks C01–C04/C15). **The two funnels are scored over disjoint denominators**; merging them counts composition as failure |
| `reachable` | boolean | The host answered and was not classified as an access block. A block is *not* unreachability: the host answered, a WAF did |
| `http_status` | integer \| null | Status of the endpoint's own response. Null on transport failure |
| `final_url` | string \| null | URL after manually following redirects |
| `redirect_chain` | array of strings | Every URL requested, in order, **including the initial one**. A single-element chain means no redirect |
| `tls` | object \| null | See below. Null when the transport exposed no TLS object or the handshake failed |
| `elapsed_ms` | float \| null | Wall-clock time for the endpoint fetch including retries |
| `server_header` | string \| null | `Server` response header of the endpoint. Feeds the R10.2b fingerprint |
| `robots_allowed` | boolean | False when `robots.txt` disallowed the endpoint URL. **Leaves every denominator** (§7) |
| `opted_out` | boolean | True when the operator is on `docs/opt-out.txt`. **Leaves every denominator** (§7) |
| `raw_artifact_path` | string \| null | **Always null. No code path sets it.** Raw artefacts are joined by `endpoint_id`, not by this field |
| `checks` | array of objects | The verdicts. See §4.2 |
| `evidence` | object | The structured observations the verdicts were computed from. Modality-specific; see §6 |
| `probed_at` | string (ISO 8601) | `fetched_at` of the endpoint's own response |
| `run_id` | string | Run that produced this verdict. After `rescore` this is the *destination* run id |

### 4.1 `tls`

| Field | Type | Meaning |
|---|---|---|
| `version` | string \| null | Negotiated protocol, e.g. `TLSv1.3` |
| `cert_sha256` | string \| null | SHA-256 of the DER leaf certificate. A sensitivity clustering arm under R10.2b |
| `issuer_cn` | string \| null | Certificate issuer common name |
| `not_after` | string (ISO 8601) \| null | Certificate expiry |
| `chain_valid` | boolean \| null | See caveat |
| `san_match` | boolean \| null | See caveat |

**Caveat, load-bearing if you compute a TLS failure rate.** `chain_valid` and `san_match`
are set to `true` whenever a handshake completed, because the client verifies both and a
completed handshake therefore implies both. A *failed* handshake produces no response at
all: `tls` is null and the fetch carries `error_kind: "tls"`. So these two fields are
never `false` in practice, and C11 `fail_misimplemented` is in practice reachable only via
the separate non-HTTPS-scheme branch. TLS failures are visible in
`artifacts.jsonl.error_kind`, not here.

### 4.2 `checks[]`

| Field | Type | Meaning |
|---|---|---|
| `check_id` | enum | `C01`–`C05`, `C07`–`C09`, `C11`–`C18`. **`C06` and `C10` do not exist** — both were removed on 2026-07-28 because no code path emitted them |
| `outcome` | enum | `pass` · `fail_unimplemented` · `fail_misimplemented` · `unspecified` · `not_applicable` · `error`. **See §5** |
| `normative_strength` | enum | `must` · `should` · `may` · `silent` — how hard the cited specification sentence pushes |
| `spec_ref` | string | The clause the verdict rests on, quoted or cited. May be `""` for purely operational outcomes (an `error` for a blocked host cites nothing) |
| `spec_url` | string | URL of that specification. May be `""` |
| `spec_version` | string | **Always `""`.** R7 originally scored each endpoint against the revision it declares; reading that declaration requires an MCP `initialize` handshake, which was deliberately cut. Every endpoint is therefore scored against the most permissive frozen revision, and this field is never populated |
| `observed_value` | string \| null | What was actually seen, rendered for humans. Format varies per check |
| `detail` | string | Why the outcome is what it is |
| `evidence_sha256` | string \| null | SHA-256 of the response body the verdict rests on. **Join key into `artifacts.jsonl.body_sha256`.** Only populated by checks that recorded one (C01 pass, C05 misimplemented) |

The check catalogue:

| ID | Question | Modality | Anchor strength |
|---|---|---|---|
| C01 | Is an identity document served at all? | signed | should |
| C02 | Does it carry a JWS signature? | signed | may — **descriptive only** |
| C03 | Does `jku` / `kid` / `did:web` resolve to a usable key? | signed | must |
| C04 | Does the signature verify (RFC 7515 over the RFC 8785 payload)? | signed | must |
| C05 | Is RFC 9728 protected-resource metadata reachable, with a non-empty `authorization_servers`? | oauth | must |
| C07 | Does the 401 carry `WWW-Authenticate: … resource_metadata`? | oauth | should |
| C08 | Is DPoP / mTLS sender-constraining declared? | oauth | may — **descriptive only** |
| C09 | Is a `revocation_endpoint` declared? | oauth | may — **descriptive only** |
| C11 | Is the endpoint's own TLS valid? | oauth | must |
| C12 | Is the declared `resource` identical to the expected resource identifier? | oauth | must |
| C13 | Does each declared issuer actually return that issuer? | oauth | must |
| C14 | Is `code_challenge_methods_supported` declared? | oauth | must |
| C15 | Are `alg` and key size acceptable? | signed | must |
| C16 | Does the issuer advertise RFC 9207 `iss` support? | oauth | should — **descriptive only** |
| C17 | Can a client bootstrap credentials without a human (CIMD or RFC 7591)? | oauth | should — **descriptive only** |
| C18 | Does the issuer publish RFC 9728 §4 `protected_resources`? | oauth | may — **descriptive only** |

The two funnel orders, over disjoint denominators:

- `oauth_metadata`: reachable → C05 → C12 → C13 → C14
- `signed_document`: reachable → C01 → C02 → C03 → C04

### 4.3 Real record (trimmed)

The `mismatch.example.org` endpoint — a server that publishes protected-resource metadata
naming a resource identifier that is not its own:

```json
{"checks": [
   {"check_id": "C07", "outcome": "unspecified", "normative_strength": "should",
    "spec_ref": "MCP Authorization, discovery", "spec_url": "https://modelcontextprotocol.io/…",
    "observed_value": null, "detail": "", "evidence_sha256": null, "spec_version": ""},
   {"check_id": "C05", "outcome": "pass", "normative_strength": "must",
    "observed_value": "https://mismatch.example.org/.well-known/oauth-protected-resource/mcp",
    "spec_ref": "RFC 9728 3.2", …},
   {"check_id": "C12", "outcome": "fail_misimplemented", "normative_strength": "must",
    "observed_value": "https://somewhere-else.example.org/mcp (unrelated_host)",
    "detail": "expected https://mismatch.example.org/mcp from https://mismatch.example.org/.well-known/oauth-protected-resource/mcp",
    "spec_ref": "RFC 9728 3.3: the resource value returned MUST be identical", …},
   {"check_id": "C13", "outcome": "pass", "normative_strength": "must", …},
   {"check_id": "C16", "outcome": "pass",  "observed_value": "1/1 observed, 1/1 declared", …},
   {"check_id": "C17", "outcome": "unspecified", "observed_value": "0/1 observed, 0/1 declared", …},
   {"check_id": "C18", "outcome": "unspecified",
    "observed_value": "listed=0/1 observed, 1 declared; empty_list=0; cross_check_passes=0", …},
   {"check_id": "C08", "outcome": "unspecified", "observed_value": "0/1", …},
   {"check_id": "C09", "outcome": "pass", "observed_value": "1/1", …},
   {"check_id": "C14", "outcome": "pass", "normative_strength": "must", …}],
 "endpoint": {"endpoint_id": "d7dcb9dfe6d3c2ce", "url": "https://mismatch.example.org/mcp", …},
 "evidence": { … see §6 … },
 "modality": "oauth_metadata", "http_status": 401, "reachable": true,
 "final_url": "https://mismatch.example.org/mcp",
 "redirect_chain": ["https://mismatch.example.org/mcp"],
 "elapsed_ms": 0.29630000062752515, "server_header": null, "tls": null,
 "robots_allowed": true, "opted_out": false, "raw_artifact_path": null,
 "probed_at": "2026-07-28T22:28:38.078402Z", "run_id": "example"}
```

Note that C12 fails while C13 passes: the resource lies about its own identity, and the
issuer it names is perfectly well-behaved. That combination is the paper's subject.

---

## 5. Outcome semantics — read this before computing any rate

Six outcomes. Two of them are findings, one is a normative result, and three of them must
leave your denominator.

| Outcome | Means | In numerator? | In denominator? | Rule |
|---|---|---|---|---|
| `pass` | The condition the specification states held | yes | yes | — |
| `fail_unimplemented` | The mechanism is **absent**: HTTP 404/410, a required member missing, no metadata at any candidate location | yes | yes | R3 |
| `fail_misimplemented` | The mechanism is **present and violates a MUST**: HTTP 200 with a body that is not a JSON object, a declared value that is not identical to the expected one | yes | yes | R3, R9.3 |
| `unspecified` | **Not a failure.** Either the specification does not settle the question, or the instrument cannot separate two honest readings of it | no | yes | **R6** |
| `not_applicable` | The check does not apply to this endpoint — composition, not conformance | no | **no** | R1, denominator rules |
| `error` | Transport failure, access block, or a document our own politeness policy stopped us from requesting | no | **no** | **R4**, R5 |

### `unspecified` is a result, not a gap

This is the outcome most likely to be misread as a soft failure. It is not. It is emitted
in three distinct situations, and in the paper it is the **normative output to the
standards bodies** (A2A, MCP, IETF OAuth WG) rather than a verdict about any operator:

1. **The specification does not settle it.** C07 is the cleanest case: MCP `2025-06-18`
   makes the `WWW-Authenticate` header a MUST, `2025-11-25` requires *one of* two discovery
   mechanisms. A server with a working well-known URI and no header is fully conforming
   under the current revision, so C07 cannot penalise (R7).
2. **The instrument cannot separate two readings (R6).** C12 with
   `resource_relation: "trailing_slash_only"` is the worked example. RFC 9728 §3.1 strips a
   terminating slash *before* inserting the well-known suffix, so `https://h/mcp` and
   `https://h/mcp/` are served from the same metadata URL. Reversing that mapping yields a
   two-element set, not a value: a server whose real identifier is `/mcp/` conforms by
   echoing `/mcp/`, and one whose identifier is `/mcp` violates §3.3 by doing exactly the
   same thing. Penalising a class we cannot distinguish would be choosing the threshold in
   our own favour, so it routes to `unspecified`. C13 has no such problem — the issuer
   string is read literally out of the resource's own `authorization_servers` array — so a
   trailing-slash difference there **is** `fail_misimplemented`. The asymmetry is forced by
   the specifications, not chosen. R9.5 requires the C12 rate to be published twice, with
   this class counted both ways.
3. **A descriptive check found something less than universal.** C08, C09, C16, C17, C18
   emit `pass` only when every observed issuer declares the feature, `unspecified`
   otherwise. Under R1 they cannot say anything stronger.

### `not_applicable` is composition

An MCP endpoint that never opted into authorization scores `not_applicable` on C05, C12,
C13 and C14 — authorization is OPTIONAL in MCP, so its silence is not non-conformance.
A card with no `signatures` member scores `not_applicable` on C03, C04 and C15. Carrying
these in the denominator while they cannot appear in the numerator counts composition as
failure. On the phase-0 pilot that is the difference between "36.7% publish
protected-resource metadata" and "96.6% of the endpoints that require authorization publish
it" — from the same data.

### `error` is never a finding

`error` means we did not observe the origin: a 429, a WAF interstitial, an ambiguous 403, a
TLS handshake rejection, a DNS failure, or a document `robots.txt` told us not to fetch.
Counting these as failures would bias the result *in the direction of the property being
measured*, because mature deployments are the ones behind WAFs. Under R5 a single-run
`error` is provisional: it is confirmed only by reproducing across at least two runs ≥24 h
apart, and unconfirmed errors are reported separately.

### Two structural guarantees

- **A `fail_*` with `normative_strength != "must"` is impossible by construction.**
  `CheckResult.model_post_init` raises `ValueError` on it and the model is `frozen=True`, so
  neither assignment nor `model_copy(update=…)` can slip past. If you find such a record,
  the file was not written by this tool.
- **The six descriptive-only checks — C02, C08, C09, C16, C17, C18 — can never carry a
  `fail_*` outcome**, regardless of strength. Same validator (R1).

The converse does **not** hold: `normative_strength: "must"` with `outcome: "unspecified"`
is normal and correct (C13 under R6/R9.3 is exactly that).

When two observations for one check disagree, R2 precedence applies, most permissive first:

```
error > not_applicable > unspecified > fail_misimplemented > fail_unimplemented > pass
```

---

## 6. The `evidence` block

`checks[]` records what was decided. `evidence` records what it was decided *from*. It is
what makes the resource → issuer graph — the study's headline figure — buildable without a
second scan of several thousand third-party hosts, and what makes re-scoring cheap.

### 6.1 `modality: "oauth_metadata"`

| Field | Type | Meaning |
|---|---|---|
| `implementation_fingerprint` | string \| null | R10.2b cluster key. `sha256(JCS({prm_keys, prm_types, as_keys, server}))`. **Null when no PRM document was retrieved.** See below |
| `implementation_fingerprint_no_server` | string \| null | The same hash with `server` forced to `""`. R10.2b requires the clustering to be reported both with and without the one hand-made input |
| `requires_authorization` | boolean | The endpoint answered 401 or 403. **This is the gate**: false means every OAuth check is `not_applicable` |
| `www_authenticate` | string \| null | Raw `WWW-Authenticate` header of the endpoint response |
| `prm_url` | string \| null | Which candidate location actually served the protected-resource metadata |
| `prm_from_hint` | boolean | True when that location came from the `WWW-Authenticate` hint rather than a constructed well-known URI |
| `hinted_url_declared` | string \| null | The `resource_metadata=` value as declared, **whether or not it was followed** |
| `hint_rejected_reason` | string \| null | Why a declared hint was recorded but not followed; null when followed or absent. See below |
| `prm_scope_covers_endpoint` | boolean \| null | Descriptive (R9.1): did the document we found actually cover this endpoint's path, or did we fall back to the root form? RFC 9728 §7.6 puts this selection question out of scope, so it never penalises |
| `prm_document` | object \| null | The parsed PRM document verbatim |
| `declared_resource` | string \| null | The document's `resource` member, if it is a string |
| `expected_resource` | string \| null | What §3.3 says it should have been. **Derived from the URL the document came from, not from the endpoint URL** — see below |
| `resource_relation` | string \| null | How `declared_resource` misses `expected_resource`. Nine buckets, below |
| `authorization_servers` | array of strings | Declared issuers that survived validation: string, `http`/`https` scheme, non-empty authority |
| `malformed_authorization_servers` | array of strings | Entries that did not, stored as Python `repr()` so the malformation is visible. A bare string here used to be iterated character by character, turning one issuer into fifteen single-letter ones |
| `as_documents` | object | `issuer → parsed authorization-server metadata document`, for every issuer that answered |
| `as_errors` | object | `issuer → why no document was obtained`. The key `"<malformed>"` is used when `authorization_servers` was present but not a list |
| `as_issuer_relations` | object | `issuer → relation` between the `issuer` value the document returned and the issuer string the resource declared. Same nine buckets, plus `"absent"` when the document's `issuer` member is missing or not a string |
| `robots_excluded_urls` | array of strings | PRM candidate URLs we did not request because `robots.txt` disallowed them or the operator opted out. **Non-empty with no PRM found ⇒ C05/C12/C13/C14 are all `error`, not failures** — absence we were not allowed to look for is not absence |

**`expected_resource` (R9.1).** RFC 9728 §3.3 does not compare against the endpoint URL the
client started from. It compares against "the protected resource's resource identifier value
into which the well-known URI path suffix was inserted to create the URL used to retrieve
the metadata". So:

| Document served from | `expected_resource` |
|---|---|
| `https://h/.well-known/oauth-protected-resource/p` | `https://h/p` |
| `https://h/.well-known/oauth-protected-resource` (root form) | `https://h` |
| a followed `WWW-Authenticate` hint | the URL the client requested of the resource (§3.3 ¶2) |

This is not cosmetic. Before the rule was written down, the expected value was derived once
from the raw endpoint URL; measured against eight large live MCP endpoints, that instrument
reported a 75% C12 violation rate where the correct rule reports 25%. The entire difference
was instrument error, and it was the paper's headline number.

Both sides are canonicalised before comparison (R9.2): fragment dropped, default port
dropped, scheme and host lower-cased, root path `/` equated with the empty path. **Path and
query are not lower-cased** — RFC 3986 §6.2.2.1 declares them case-sensitive, so `/MCP` and
`/mcp` are genuinely different paths.

**`resource_relation` / `as_issuer_relations` — the nine buckets.** `unrelated_host` is a
named category, never a fall-through: the paper's rhetorical punch (two unrelated resources
naming the same issuer) must not be produced by an `else` branch that also swallows port
differences.

| Bucket | Meaning | C12 | C13 |
|---|---|---|---|
| `identical` | Equal after canonicalisation | `pass` | `pass` |
| `template_placeholder` | The value is the other with whole path segments replaced by `{…}` placeholders — a template, not a URI (R9.6) | **`unspecified`** | **`unspecified`** |
| `trailing_slash_only` | Differ only by a terminating slash | **`unspecified`** (R9.4) | `fail_misimplemented` |
| `case_path_only` | Equal ignoring case, but the difference is in the path or query | `fail_misimplemented` | `fail_misimplemented` |
| `scheme_only` | Same host, different scheme | `fail_misimplemented` | `fail_misimplemented` |
| `port_only` | Same host, genuinely different port (defaults already normalised away) | `fail_misimplemented` | `fail_misimplemented` |
| `same_host_different_path` | Same scheme, host and port; different path | `fail_misimplemented` | `fail_misimplemented` |
| `related_host` | One host is a sub-domain of the other | `fail_misimplemented` | `fail_misimplemented` |
| `unrelated_host` | Different registrable hosts, no sub-domain relation | `fail_misimplemented` | `fail_misimplemented` |

Within one host the most severe differing component is named, most severe first: scheme →
port → path.

**`implementation_fingerprint` (R10.2b) — what goes in, and what deliberately does not.**
Endpoints are not independent; they run on a handful of SDKs and platforms, and a rate
reported as though they were overstates its own precision. The cluster key is:

```
sha256( JCS( {
  "prm_keys":  sorted top-level member names of the PRM document,
  "prm_types": the JSON type of each, in that same order,
  "as_keys":   sorted top-level member names of the FIRST observed AS document, [] if none,
  "server":    the `Server` header's product family, lower-cased, version stripped
} ) )
```

- **No value ever enters the hash.** Only member names, JSON types, and the server family.
  That is the whole point: hashing the document would key on whichever serialiser and proxy
  happened to be in the path, and stripping host-specific values back out again would
  require a hand-written list of which fields those are — the author-supplied rubric this
  instrument exists to avoid.
- The type vocabulary produced by the code is `boolean`, `number`, `string`, `null`,
  `array`, and `object<k:type,…>` (recursive). **Arrays do not describe their elements**:
  `[]` and `["read"]` are the same member with different contents, and letting contents
  change the shape split one SDK into two clusters.
- `server` is the product name with the version removed — `nginx/1.24.0` and `nginx/1.25.3`
  both become `nginx`. It is the single hand-made input, which is why the `_no_server`
  variant exists and why R10.2b requires both to be reported.
- Only the **first** observed AS document contributes `as_keys`. There is no `as_types`.

**`hint_rejected_reason`.** A `WWW-Authenticate: resource_metadata` value is
attacker-controlled input from the host being measured. It is honoured only within the
resource's own registrable domain: following it anywhere would send requests
`docs/ETHICS.md` §3 does not list, and would let one hostile or misconfigured endpoint
inject arbitrary edges into the resource → issuer graph. The recorded reasons are:

| Value | Condition |
|---|---|
| `scheme is '<s>', not https` | Hint URL is not HTTPS |
| `no host` | Hint URL has no authority |
| `host '<h>' has no registrable domain` | Loopback, RFC 1918 literal, bare IP, special-use TLD |
| `points at '<a>', not the resource's own '<b>'` | Cross-domain hint |
| `null` | The hint was followed, or none was declared |

The declared value is always preserved in `hinted_url_declared` even when rejected.

**Real evidence block**, from `mismatch.example.org` (the C12 failure):

```json
{"implementation_fingerprint": "ddf008b53b3af3646ad58b26ffb38cedd788fa462173abece512e2b1f01e546a",
 "implementation_fingerprint_no_server": "ddf008b53b3af3646ad58b26ffb38cedd788fa462173abece512e2b1f01e546a",
 "requires_authorization": true, "www_authenticate": null,
 "prm_url": "https://mismatch.example.org/.well-known/oauth-protected-resource/mcp",
 "prm_from_hint": false, "hinted_url_declared": null, "hint_rejected_reason": null,
 "prm_scope_covers_endpoint": true,
 "prm_document": {"authorization_servers": ["https://auth.example.org"],
                  "resource": "https://somewhere-else.example.org/mcp"},
 "declared_resource": "https://somewhere-else.example.org/mcp",
 "expected_resource": "https://mismatch.example.org/mcp",
 "resource_relation": "unrelated_host",
 "authorization_servers": ["https://auth.example.org"],
 "malformed_authorization_servers": [],
 "as_documents": {"https://auth.example.org": {"authorization_response_iss_parameter_supported": true,
                   "code_challenge_methods_supported": ["S256"], "issuer": "https://auth.example.org",
                   "revocation_endpoint": "https://auth.example.org/revoke"}},
 "as_errors": {}, "as_issuer_relations": {"https://auth.example.org": "identical"},
 "robots_excluded_urls": []}
```

And the same block for the dead-issuer case, which is what a broken delegation looks like:

```json
{"authorization_servers": ["https://gone.example.org"],
 "as_documents": {}, "as_issuer_relations": {},
 "as_errors": {"https://gone.example.org": "metadata not retrievable at any well-known location"},
 "declared_resource": "https://deadissuer.example.org/mcp",
 "expected_resource": "https://deadissuer.example.org/mcp",
 "resource_relation": "identical", …}
```

### 6.2 `modality: "signed_document"`

| Field | Type | Meaning |
|---|---|---|
| `document` | object \| null | The parsed Agent Card verbatim. Null when nothing usable was served |
| `document_url` | string | The card URL that was requested |
| `signatures` | array of objects | The card's `signatures` members that are objects (JWS JSON-serialisation form: `protected`, `signature`, optionally `header`) |
| `protected_headers` | array of objects | Each signature's decoded protected header, in signature order. Signatures with an undecodable header are absent here but counted in the C03 verdict |
| `key_sources` | array of strings | Where each key came from, prefixed by mechanism: `jku:<url>` or `did:web:<url>`. Resolution order is `jku`, then a `did:web` in `kid`, then a `did:web` in `provider.did` |
| `algs` | array of strings | The `alg` value of each signature whose header decoded |
| `verified_count` | integer | How many signatures verified against a resolved key over the RFC 8785 payload |
| `canonicalization_note` | string \| null | Set when canonicalisation of the card failed or was ambiguous. An ambiguity routes C03/C04 to `unspecified` (R6); an outright failure is a `fail_misimplemented` on C03 |

Two things the code deliberately does **not** do, both of which would distort the headline
binary (does any cryptographic verification path close?):

- A signature under `none`, under a symmetric algorithm alongside a published public key
  set, or under an RSA key shorter than 2048 bits is **never attempted**. Anyone holding
  the published material could produce it, so counting it as a cryptographic binding would
  inflate the number. It surfaces as C15 `fail_misimplemented`, and `verified_count` stays
  at 0.
- A key that could not be fetched is not a verdict about the operator. When no key
  resolved, C04 is `not_applicable` — "the signature cannot be judged" — never a failure.
  If the key location was specifically *blocked*, C03 additionally becomes `error` rather
  than `fail_unimplemented` (R4). C04 is only `error` when the card fetch itself was
  blocked, in which case every signed-document check is.

*(The committed example run contains no signed-document reports — the derived card
locations all return 404. The field list above is read from `SignedEvidence.as_record`.)*

---

## 7. `data/raw/<id>/artifacts.jsonl`

Every document that was fetched, verbatim, alongside the verdict derived from it. This is
the infrastructure behind decision rule R8: any result can be re-scored without touching
the network.

**One line per HTTP response**, not per endpoint. A single OAuth endpoint typically
produces 2–6 lines: its own response, each protected-resource-metadata candidate tried,
and up to three authorization-server metadata candidates per declared issuer. Signed-document
endpoints add `jku` and `did:web` fetches. **`robots.txt` requests are not recorded** —
they bypass the capture hook — and neither are registry requests made during `collect`,
which happen outside any endpoint context.

| Field | Type | Meaning |
|---|---|---|
| `artifact_schema` | integer | Record format version. Currently `1` |
| `endpoint_id` | string | Which endpoint's probe caused this fetch. **Join key to `reports.jsonl → endpoint.endpoint_id`** |
| `label` | string | `mcp` for the OAuth pass, `card` for the signed-document pass |
| `url` | string | URL requested |
| `ok` | boolean | False when the response was classified as an access block or the transport failed |
| `final_url` | string \| null | URL after redirects |
| `redirect_chain` | array of strings | Every URL requested, in order, including the first |
| `status` | integer \| null | HTTP status. Null on transport failure, on a robots exclusion, and on an opt-out |
| `headers` | object | Response headers, lower-cased names |
| `tls` | object \| null | Same shape as §4.1. **Stored because a check reads it**: while it was omitted, a re-scoring pass saw `tls is None` and turned every live C11 `pass` into `fail_unimplemented` — a field a check consults and this record drops is not an omission, it is R8 being false |
| `body_b64` | string | Base64 of the response body, capped at 5 MiB (`max_response_bytes`). Empty string when there was no body |
| `body_sha256` | string \| null | SHA-256 of exactly those stored bytes. **Null when the body is empty.** Join key to `checks[].evidence_sha256` |
| `elapsed_ms` | float \| null | Wall-clock time for this fetch |
| `error_kind` | enum | `none` · `timeout` · `dns` · `tls` · `connection` · `blocked` · `too_large` · `robots_disallowed` · `opted_out` · `other` |
| `error_detail` | string | Human-readable detail; `""` when there was no error |
| `fetched_at` | string (ISO 8601) | When this response arrived |

### Real record

```json
{"artifact_schema": 1, "endpoint_id": "d7dcb9dfe6d3c2ce", "label": "mcp",
 "url": "https://mismatch.example.org/.well-known/oauth-protected-resource/mcp",
 "final_url": "https://mismatch.example.org/.well-known/oauth-protected-resource/mcp",
 "redirect_chain": ["https://mismatch.example.org/.well-known/oauth-protected-resource/mcp"],
 "ok": true, "status": 200,
 "headers": {"content-length": "106", "content-type": "application/json"},
 "tls": null,
 "body_b64": "eyJyZXNvdXJjZSI6Imh0dHBzOi8vc29tZXdoZXJlLWVsc2UuZXhhbXBsZS5vcmcvbWNwIiwiYXV0aG9yaXphdGlvbl9zZXJ2ZXJzIjpbImh0dHBzOi8vYXV0aC5leGFtcGxlLm9yZyJdfQ==",
 "body_sha256": "b9f1e5652162f3ac1f5fe8f2102ddadae83c0af88d94eacf0f7178f73bc725a0",
 "elapsed_ms": 15.724200005934108, "error_kind": "none", "error_detail": "",
 "fetched_at": "2026-07-28T22:28:38.097925+00:00"}
```

---

## 8. Re-scoring: recovering and verifying the bytes

Recover the original document and check it against the stored digest:

```python
import base64, hashlib, json

with open("data/raw/example/artifacts.jsonl", encoding="utf-8") as fh:
    for line in fh:
        rec  = json.loads(line)
        body = base64.b64decode(rec["body_b64"])
        assert rec["body_sha256"] == (hashlib.sha256(body).hexdigest() if body else None)
```

On the record above this yields, exactly:

```
{"resource":"https://somewhere-else.example.org/mcp","authorization_servers":["https://auth.example.org"]}
b9f1e5652162f3ac1f5fe8f2102ddadae83c0af88d94eacf0f7178f73bc725a0
```

`RunStore.read_artifacts()` does the decode for you and adds a `body` key holding the raw
bytes, leaving `body_b64` in place.

### Replaying a whole run

```
agent-id-probe rescore --run-id example --verify
```

What it does:

1. Reads `corpus.jsonl`, `reports.jsonl` and `artifacts.jsonl` from the source run.
2. Substitutes `ReplayFetcher` for `Fetcher`. The check functions are **the same functions
   the live run used** — only the fetcher differs, so any difference between the two runs is
   a difference in the instrument and nothing else. A replay that quietly falls back to the
   network is not a replay: `ReplayFetcher` raises `ArtefactMissing` on a miss. Repeated
   fetches of the same URL under one endpoint replay in their original order.
3. Writes a **new** run, `<id>-rescored` by default or wherever `--into` points. The source
   is never overwritten — overwriting it would destroy the thing being compared against.
4. With `--verify`, diffs the two sets keyed on `(endpoint_id, modality)` and compares
   `reachable` plus every check's outcome. `probed_at` and `run_id` are excluded: they record
   *when* a verdict was computed, not what it was. Any difference is printed and the command
   exits 1.

An endpoint whose own response was never stored is skipped with a printed warning rather
than given an invented verdict — which is why `reports_out < reports_in` in the rescore
manifest is meaningful and should be checked.

This is what makes R8 a build step rather than a promise. It also makes an instrument defect
found after collection cost a local re-run instead of a second scan of several thousand
third-party hosts.

---

## 9. Exclusions — what leaves the denominator, and why

`agent-id-probe summarise --run-id <id>` reads the stored reports and prints the funnels.
The shape is `{"probe_version": …, "modalities": {<modality>: {…}}}`, one entry per modality
present in the file.

| Key | Meaning |
|---|---|
| `total` | Reports for this modality after de-duplication |
| `in_scope` | `total` minus the three exclusions below. **This is the base of every funnel denominator** |
| `excluded_opt_out` | `opted_out == true`. The operator is on `docs/opt-out.txt` and asked not to be measured. Kept in the corpus so the exclusion is auditable, removed from every denominator, and counted in the paper |
| `excluded_robots` | `robots_allowed == false` (and not opted out). **This is our own politeness policy, not an observation of the origin.** Leaving these in would let our ethics policy move the published rate |
| `excluded_crossed_origin` | The endpoint's `final_url` authority differs from its requested authority after a redirect. The document describes whoever answered, not the host we asked about, so attributing the verdict to the original endpoint would be a silent misattribution. Reported separately |
| `funnel` | Ordered stages, below |

Each `funnel[]` row:

| Key | Meaning |
|---|---|
| `stage` | Human-readable stage name (the funnel orders are in §4.2) |
| `n` | How many passed |
| `eligible` | The denominator **for this stage**: the previous stage's pass set, minus this stage's `not_applicable` and `error` |
| `excluded.not_applicable` | Dropped as composition (R1) |
| `excluded.error` | Dropped as unobserved (R4/R5) |

The funnel invariant: each stage's eligible pool is a subset of the previous stage's pass
set. Rates are therefore conditional — "of the endpoints that got this far", never "of all
endpoints" — and the `eligible` column is the number you must divide by.

Real output for the committed example run:

```json
{"probe_version": "0.1.0",
 "modalities": {"oauth_metadata": {
   "total": 4, "in_scope": 4,
   "excluded_robots": 0, "excluded_opt_out": 0, "excluded_crossed_origin": 0,
   "funnel": [
     {"stage": "reachable",                             "n": 4, "eligible": 4, "excluded": {"not_applicable": 0, "error": 0}},
     {"stage": "publishes protected-resource metadata", "n": 3, "eligible": 3, "excluded": {"not_applicable": 1, "error": 0}},
     {"stage": "resource identifier matches",           "n": 2, "eligible": 3, "excluded": {"not_applicable": 0, "error": 0}},
     {"stage": "declared issuer corresponds",           "n": 1, "eligible": 2, "excluded": {"not_applicable": 0, "error": 0}},
     {"stage": "PKCE declared",                         "n": 1, "eligible": 1, "excluded": {"not_applicable": 0, "error": 0}}]}}}
```

Read it as: four endpoints, all reachable; one (`open.example.org`) never required
authorization and is `not_applicable` at the PRM stage, leaving three; all three publish
metadata; one of those three (`mismatch.example.org`) declares a resource identifier that is
not its own, leaving two; one of those two (`deadissuer.example.org`) names an issuer that
serves nothing, leaving one. Note that the funnel figure is not the source of the paper's
numbers — those come from the analysis reading the stored reports — but the denominator
rules encoded here are the same ones.

Two more rules that live outside `summarise`:

- **The two modalities are reported over disjoint denominators.** One combined funnel would
  count an endpoint that never entered a modality as failing it. That is composition, not
  non-conformance.
- **The primary unit of analysis is the apex domain, at most one endpoint per apex** (R10.2),
  with the representative fixed in advance as the smallest `endpoint_id`. Every headline
  rate is additionally reported per endpoint and per implementation cluster (R10.1), because
  changing the unit changes the denominator and not merely the interval.

---

## 10. Three traps that will corrupt your numbers

### Trap 1 — `reports.jsonl` is append-only: a re-probed endpoint appears twice

Re-probing with `--no-resume`, or reusing a run id, leaves **two records for the same
endpoint** in the file. The duplicate is invisible: both lines are well-formed, and both
parse. Counting both double-counts that endpoint in every rate you compute.

The correct read is **the last record per `(endpoint_id, modality)`**:

```python
latest = {}
for line in open("results/runs/<id>/reports.jsonl", encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    rec = json.loads(line)
    latest[(rec["endpoint"]["endpoint_id"], rec["modality"])] = rec
reports = list(latest.values())
```

`RunStore.read_reports()` does exactly this, and `summarise` and `rescore` both go through
it. A naive line-by-line `json.loads` over the file **counts re-probed endpoints twice.**
Note the key is the *pair*: one origin legitimately contributes one `oauth_metadata` report
and one `signed_document` report, and those are separate units with separate denominators.

### Trap 2 — `TRUNCATED:` in the manifest means the corpus is incomplete

`manifest.json → sources[].errors` may contain a line beginning `TRUNCATED:`, written
verbatim as:

```
TRUNCATED: pagination stopped at max_pages=<n> with more records available
(next cursor '<cursor>'). The corpus is incomplete.
```

It means the collector hit its `--max-pages` ceiling while the registry still had records —
typically a `--max-pages` set for a trial run and left in place for a full one. The official
MCP registry defaults to 30 records per page and caps at 100, so enumerating the full corpus
takes hundreds of pages.

**If this line is present, no rate computed from that corpus is a census.** It is a rate over
an arbitrary, pagination-ordered prefix of the population, and prefix order is not random.
The same array also carries non-truncation errors (HTTP failures, unparseable pages, a
repeated cursor); those bound completeness too, but only the `TRUNCATED:` prefix means "the
registry had more and we stopped asking". Check this field before quoting any denominator.

### Trap 3 — `apex_domain` merges platform tenants

`apex_domain` is computed with the public suffix list's **private section disabled**.
Consequently `a.vercel.app` and `b.vercel.app` share the apex `vercel.app`, as do tenants of
`onrender.com`, `fly.dev`, `workers.dev`, `run.app`, and every other platform whose suffix is
a PSL private entry.

- **For clustering this is correct**: those tenants really are not independent observations,
  and R10.2 wants them collapsed.
- **For the cross-operator delegation rate it is wrong in a specific direction**: one
  platform tenant delegating authorization to *another tenant's* issuer looks like the same
  operator, so `related_host` / `unrelated_host` never fires and the cross-operator rate is
  **under-estimated**.

The bias is conservative — it cannot inflate the finding — but it is real and it is
pre-registered in R10.1. If your analysis needs the true cross-operator figure, recompute the
host relation with the PSL private section enabled and report both.

**A fourth thing worth knowing**, though it is a limitation rather than a trap:
`apex_domain` returns null when the host's suffix is absent from the bundled PSL snapshot
(new gTLDs, `.example`, IP literals), and such endpoints are **dropped at collection**, not
carried with a null apex. The count is in `sources[].dropped_no_apex`. If that number is
large relative to `remote_urls_seen`, the corpus is missing a non-random slice of the
population and the snapshot needs refreshing.

---

## 11. Cross-file joins, in one place

| From | To | Key |
|---|---|---|
| `reports.jsonl` | `corpus.jsonl` | `endpoint.endpoint_id` → `endpoint_id`. **Incomplete by design**: derived agent-card endpoints are not in the corpus. Use the embedded `endpoint` object instead |
| `reports.jsonl` | `artifacts.jsonl` | `endpoint.endpoint_id` → `endpoint_id` (one-to-many) |
| `reports.jsonl` → a single check | `artifacts.jsonl` | `checks[].evidence_sha256` → `body_sha256`, where populated |
| `reports.jsonl` → the PRM document's own fetch | `artifacts.jsonl` | `evidence.prm_url` → `url`, within the same `endpoint_id` |
| `reports.jsonl` → an issuer's metadata fetch | `artifacts.jsonl` | keys of `evidence.as_documents` → the `url` prefix, within the same `endpoint_id` |
| resource → issuer graph | — | edge from `endpoint.url` (or `evidence.declared_resource`) to each entry of `evidence.authorization_servers`; edge attributes from `evidence.as_issuer_relations` and `evidence.as_errors` |
