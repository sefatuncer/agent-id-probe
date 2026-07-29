# agent-id-probe

> ### Did this reach you from a `User-Agent` in your logs?
>
> **What it is.** An academic measurement study of whether the identity and authorization
> metadata that AI agent endpoints publish about themselves is internally consistent with
> the specifications that define it (RFC 9728, RFC 8414, MCP Authorization, A2A Agent
> Card). No commercial use, no paid infrastructure.
>
> **Why your host.** Your endpoint is listed in a public MCP registry
> (`registry.modelcontextprotocol.io`). We did not discover it by scanning.
>
> **Exactly what we sent** — `GET` only, nothing else, ever:
>
> ```
> /robots.txt
> <your registry-listed endpoint URL>              (to observe whether it answers 401)
> /.well-known/oauth-protected-resource[/<path>]
> /.well-known/oauth-authorization-server[/<path>]  (only if your metadata declared it)
> /<issuer path>/.well-known/openid-configuration   (only if your metadata declared it)
> /.well-known/agent-card.json
> /.well-known/did.json          ·   /.well-known/jwks.json
> ```
>
> A `WWW-Authenticate: resource_metadata` value is followed only when it is `https` and
> stays within your own registrable domain.
>
> Nominally **6 requests across the entire study**; worst case 18 including timeouts and
> retries; at most **1 request per second** per host. `Retry-After` is honoured.
>
> **What we never do.** No authentication. No credentials. No OAuth flow, no token request,
> no dynamic client registration. No MCP method call. No POST, PUT, PATCH or DELETE. No
> writes of any kind. No vulnerability scanning, fuzzing, or access-control probing. A
> `403` ends our interest in your host.
>
> **Origin:** a residential connection in Türkiye.
>
> #### 🚫 To be excluded
>
> Email **tuncersefa@gmail.com** or open an issue. **One line is enough — we do not ask
> why.** You are removed from every current and future run along with all your subdomains,
> and the exclusion is committed publicly to [`docs/opt-out.txt`](docs/opt-out.txt) so it
> is auditable rather than merely promised. It is enforced in the fetcher before anything
> else is read, including your `robots.txt`.
>
> We honour `robots.txt`; endpoints it excludes leave the study entirely.
>
> Full policy: [`docs/ETHICS.md`](docs/ETHICS.md) · Sefa Tuncer & Enis Karaarslan,
> Muğla Sıtkı Koçman University

---

Passive, spec-anchored measurement of identity and authorization metadata published by
deployed AI agent endpoints.

**Research question.** RFC 9728 §7.6 places the secure determination of which authorization
server belongs to a protected resource explicitly *outside* the specification's scope, names
the resulting attack, and offers one mitigation. MCP passes that decision to the client
unchanged. This study measures the decision surface that actually creates: how many
resources delegate to how many issuers, and how much of that delegation a client can verify
from what the ecosystem publishes.

## Design rule

> Every check maps to a normative sentence in a published specification.

The ground truth is the spec text — never the authors' judgement. A check may report a
failure only when it can point at a MUST; anything weaker is recorded as `unspecified`,
which is feedback to the standards body rather than to the deployment. That rule is
enforced in `CheckResult.model_post_init`, not merely promised, so a check with a SHOULD
anchor *cannot* be made to fail. See [`docs/spec-mapping.md`](docs/spec-mapping.md) and
[`docs/decision-rules.md`](docs/decision-rules.md).

## Install

Python 3.11+ is the only requirement. No account, no API key, no cloud service.

```bash
git clone https://github.com/sefatuncer/agent-id-probe && cd agent-id-probe
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q                                          # fully mocked, no network
```

Everything, including the statistics, is standard library plus a short list of pinned
dependencies; there is no scientific stack to install. Rendering the paper's two figures
is the one exception and is an optional extra:

```bash
pip install -e ".[dev,figures]"                    # adds matplotlib, nothing else
```

## Quickstart

```bash
# 1. Build a corpus from free, keyless public registries.
agent-id-probe collect --run-id trial --max-pages 5 --vantage-point residential-TR

# 2. Sanity-check the instrument against one host. Writes nothing.
agent-id-probe dry-run https://example.com/mcp

# 3. Measure. Resumable, deliberately slow: one request per host per second.
#    This contacts third parties — read docs/ETHICS.md first.
agent-id-probe probe --run-id trial --limit 50

# 4. Funnels.
agent-id-probe summarise --run-id trial

# 5. Re-score stored artefacts offline (decision rule R8). Exits non-zero if any verdict
#    moved. A committed synthetic run ships with the repository, so this works on a fresh
#    clone before you have measured anything:
agent-id-probe --root . rescore --run-id example --verify

# 6. Draw Figures 1 and 2. `--synthetic` needs no measurement at all: the figures were
#    designed against a fixture before any data existed, and this is how you check that.
agent-id-probe figures --synthetic
```

## What a run produces

| Path | Contents |
|---|---|
| `results/runs/<id>/manifest.json` | run context, collection stats, provenance commit |
| `results/runs/<id>/corpus.jsonl` | one endpoint per line |
| `results/runs/<id>/reports.jsonl` | one verdict record per (endpoint, modality) |
| `data/raw/<id>/artifacts.jsonl` | every fetched document, verbatim |

`reports.jsonl` is append-only: an endpoint probed twice appears twice, and readers must
keep the last record per `(endpoint_id, modality)`. `RunStore.read_reports()` does this;
a naive line-by-line parse double-counts.

Check `manifest.json` → `sources[].errors` before using any rate: a line beginning
`TRUNCATED:` means the corpus is incomplete and nothing computed from it is a census.

## The checks

The instrument is 16 checks across two modalities, scored in **separate funnels** — an
endpoint using OAuth-only identity must not be counted as failing a signature check it was
never required to satisfy. The authoritative list is the `CheckId` enum in
`src/agentidprobe/models.py`, and every entry in it is emitted by a code path (there is a
test that fails if one is not).

**The catalogue is [`docs/check-catalogue.md`](docs/check-catalogue.md), and it is
generated from the code** — every check, its modality, the strength of the specification
sentence it rests on, whether it can report a failure at all, and the code paths that emit
it. `scripts/gen_catalogue.py --check` fails the build if it drifts, and it flags any
`CheckId` that no code path emits.

That machinery exists because the table it replaced was wrong. It listed C06 and C10, both
of which had been deleted from the instrument, and omitted the eight checks that had been
added — which is to say it advertised two measurements the study does not make. A
hand-maintained duplicate of a generated document is the last place that failure can
recur, so this section no longer contains one.

Why C06 and C10 were deleted, rather than implemented: both were declared, documented, and
emitted by no code path, and C10 ("the key chains to an organisational trust root") had no
specification sentence to anchor to. Defining one would have been the authors' rubric,
which is the objection this design exists to make impossible. See `models.py` and
[`docs/spec-mapping.md`](docs/spec-mapping.md).

## Outcome taxonomy

`pass` · `fail_unimplemented` (the mechanism is absent) · `fail_misimplemented` (present but
violating a MUST) · `unspecified` (the spec does not settle it, or the instrument cannot
separate two readings) · `not_applicable` (composition, not failure — leaves the
denominator) · `error` (transport or access block — **never** a finding, leaves the
denominator).

The last three matter as much as the first three. Counting an endpoint that never opted
into authorization as an OAuth failure measures composition; counting a WAF page as a
specification violation writes a finding against an operator who was never observed, and
biases the result in exactly the direction of the property being measured.

## Reproducing

- Decision rules are frozen before the main run and every amendment is logged with a date
  and a commit in [`docs/decision-rules.md`](docs/decision-rules.md).
- All raw responses are stored, so any verdict can be re-scored offline after an instrument
  fix — free, local, deterministic.
- The pilot that shaped the instrument is documented as a pilot in
  [`docs/phase0-findings.md`](docs/phase0-findings.md); none of its numbers are reported as
  results.

## Ethics

Passive and read-only. No authentication, no writes, no exploitation, no bypass attempts.
Rate limiting, `robots.txt`, an identifying `User-Agent`, an enforced opt-out list and a
global abort threshold live in `config.py` and `runner.py` — in code, not in prose. Only
aggregate results are published, and per-endpoint detail only after the disclosure window.
See [`docs/ETHICS.md`](docs/ETHICS.md).

## Cost

Zero. No paid API, no cloud account, no subscription. Runs on a single machine.

## Licence

Code [Apache-2.0](LICENSE). Collected data and derived tables
[CC BY 4.0](LICENSE-DATA).
