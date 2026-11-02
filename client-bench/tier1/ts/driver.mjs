/**
 * TypeScript arm of the Tier-1 client bench (CASE-MATRIX.md, amendment of 2 November 2026).
 *
 * Each case runs the SDK's own authorization flow the way an application does: a Client over
 * the Streamable HTTP transport with an OAuth provider, a connect that meets a 401, the SDK's
 * redirect to the authorization endpoint, and `finishAuth` with what the redirect carried. The
 * driver plays the user agent and nothing else. It decides no outcome: it writes the server's
 * request log beside whatever the SDK threw, and score.py reads the log.
 *
 * Usage (inside the container sharing the bench server's network namespace):
 *   node driver.mjs > ../raw/ts.jsonl
 */

import { readFileSync, readdirSync } from 'node:fs'

const BENCH = process.env.BENCH_ORIGIN ?? 'http://127.0.0.1:8765'
const REQUESTED = `${BENCH}/tenant-a/mcp`
const REDIRECT = 'http://127.0.0.1:8766/callback'
const CASE_TIMEOUT_MS = 20000

const versionOf = (pkg) => JSON.parse(readFileSync(`node_modules/${pkg}/package.json`, 'utf8')).version

/** Files of the installed package naming `needle`, source maps excluded (the C1 count). */
const sourceOccurrences = (pkg, needle) => {
  let hits = 0
  const walk = (dir) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = `${dir}/${e.name}`
      if (e.isDirectory()) { walk(p); continue }
      if (e.name.endsWith('.map')) continue
      try { if (readFileSync(p, 'utf8').includes(needle)) hits++ } catch { /* binary */ }
    }
  }
  walk(`node_modules/${pkg}`)
  return hits
}

const v1Client = await import('@modelcontextprotocol/sdk/client/index.js')
const v1Http = await import('@modelcontextprotocol/sdk/client/streamableHttp.js')
const v2 = await import('@modelcontextprotocol/client')

const IMPLS = [
  {
    id: 'typescript-sdk-v1', pkg: '@modelcontextprotocol/sdk',
    // C1 is counted over the package and the one it builds on, where the schemas live.
    sourcePkgs: ['@modelcontextprotocol/sdk'],
    Client: v1Client.Client, Transport: v1Http.StreamableHTTPClientTransport,
    // v1's finishAuth takes the code alone: its callback interface has no channel for iss.
    finish: (t, params) => t.finishAuth(params.get('code')),
    callbackChannel: 'code only',
  },
  {
    id: 'typescript-sdk', pkg: '@modelcontextprotocol/client',
    sourcePkgs: ['@modelcontextprotocol/client', '@modelcontextprotocol/core'],
    Client: v2.Client, Transport: v2.StreamableHTTPClientTransport,
    // v2 reads code and iss from the callback's query parameters.
    finish: (t, params) => t.finishAuth(params),
    callbackChannel: 'callback query parameters (code, iss)',
  },
]

/** An in-memory provider: what an application supplies, with no persisted state between cases. */
class BenchProvider {
  constructor () {
    this._client = undefined
    this._tokens = undefined
    this._verifier = undefined
    this.authorizationUrl = null
    this.callback = null
  }

  get redirectUrl () { return REDIRECT }
  get clientMetadata () {
    return {
      client_name: 'tier1-bench', redirect_uris: [REDIRECT],
      grant_types: ['authorization_code', 'refresh_token'], response_types: ['code'],
      token_endpoint_auth_method: 'none', scope: 'mcp',
    }
  }

  clientInformation () { return this._client }
  saveClientInformation (info) { this._client = info }
  tokens () { return this._tokens }
  saveTokens (tokens) { this._tokens = tokens }
  saveCodeVerifier (v) { this._verifier = v }
  codeVerifier () { return this._verifier }
  // Persisted with the verifier, as v2's migration guide asks (SEP-2352), so the callback leg
  // can bind the code to the authorization server that minted it. v1 never calls these.
  saveDiscoveryState (s) { this._discovery = s }
  discoveryState () { return this._discovery }

  // The user agent: follow the SDK's authorization URL one hop and keep the redirect.
  async redirectToAuthorization (url) {
    this.authorizationUrl = String(url)
    const res = await fetch(url, { redirect: 'manual' })
    this.callback = res.headers.get('location')
  }
}

const errText = (e) => (e ? `${e.constructor?.name ?? 'Error'}: ${e.message ?? e}`.slice(0, 300) : null)

const withTimeout = (p) => Promise.race([
  p, new Promise((_, rej) => setTimeout(() => rej(new Error('bench timeout')), CASE_TIMEOUT_MS)),
])

const caseIds = await (await fetch(`${BENCH}/__cases`)).json()

for (const impl of IMPLS) {
  const version = versionOf(impl.pkg)
  const c1Count = impl.sourcePkgs.reduce((n, p) => n + sourceOccurrences(p, 'protected_resources'), 0)

  for (const caseId of caseIds) {
    await fetch(`${BENCH}/__case?id=${caseId}`, { method: 'POST' })
    const provider = new BenchProvider()
    const transport = new impl.Transport(new URL(REQUESTED), { authProvider: provider })
    const client = new impl.Client({ name: 'tier1-bench', version: '0' })
    let connectError = null, finishError = null
    try {
      await withTimeout(client.connect(transport))
    } catch (e) { connectError = e }
    if (provider.callback) {
      try {
        await withTimeout(impl.finish(transport, new URL(provider.callback).searchParams))
      } catch (e) { finishError = e }
    }
    try { await transport.close() } catch { /* already closed */ }
    const { log } = await (await fetch(`${BENCH}/__log`)).json()

    console.log(JSON.stringify({
      implementation: impl.id, package: impl.pkg, version, level: 'flow', case_id: caseId,
      requested_identifier: REQUESTED, callback_channel: impl.callbackChannel,
      authorization_url: provider.authorizationUrl, callback: provider.callback,
      connect_error: errText(connectError), finish_error: errText(finishError),
      c1_source_occurrences: caseId === 'C1' ? c1Count : undefined,
      log, run_at: new Date().toISOString(),
    }))
  }
}
