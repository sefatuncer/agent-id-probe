/**
 * Drive published MCP client SDKs against a loopback resource server.
 *
 * The census measures what a resource server publishes. This measures whether a client would
 * act on it, which is the construct-validity gap Section 9.3 of the manuscript concedes. The
 * cases are fixed in CASE-MATRIX.md and were frozen before this file ran, for the same reason
 * decision-rules.md is frozen before the census: an expectation chosen after seeing the
 * behaviour is not an expectation.
 *
 * Nothing here touches a third party. A loopback server impersonates a non-conformant MCP
 * resource server and an authorization server; the SDKs' own exported discovery functions are
 * driven against it. There is no consent question and no Menlo analysis to redo.
 *
 * Output: results.jsonl, one record per (implementation, case).
 */

import { createServer } from 'node:http'
import { readFileSync, readdirSync, writeFileSync } from 'node:fs'

/**
 * Read the installed version from disk rather than from the package's own exports map.
 * `@modelcontextprotocol/client` does not export `./package.json`, and hard-coding the
 * version here would let a silent upgrade leave a stale string beside a fresh result --
 * which is precisely the failure the feasibility assessment warned about for finding (D).
 */
const installedVersion = (pkg) =>
  JSON.parse(readFileSync(`node_modules/${pkg}/package.json`, 'utf8')).version

/**
 * How many shipped files of `pkg` contain `needle`, excluding source maps.
 *
 * The independent signal behind the C-series: a field the package never mentions cannot be
 * acted on, whatever the parsed object happens to retain.
 */
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

// --- the implementations under test -------------------------------------------------
// Pinned, and the version is read from the installed package rather than typed here, so a
// silent upgrade cannot leave a stale version string beside a fresh result.
const V1 = await import('@modelcontextprotocol/sdk/client/auth.js')
const V2 = await import('@modelcontextprotocol/client')

const IMPLS = [
  {
    id: 'typescript-sdk',
    pkg: '@modelcontextprotocol/sdk',
    version: installedVersion('@modelcontextprotocol/sdk'),
    mod: V1,
  },
  {
    id: 'typescript-client',
    pkg: '@modelcontextprotocol/client',
    version: installedVersion('@modelcontextprotocol/client'),
    mod: V2,
  },
]

// --- the loopback resource + authorization server ------------------------------------
// `state` is what the current case wants served. One server, reconfigured per case, so the
// port stays stable and the requested identifier is the same string in every row.

const state = { prmResource: null, omitResource: false, issuer: null, authServers: null }

let PORT = 0
const ORIGIN = () => `http://127.0.0.1:${PORT}`
const RESOURCE_PATH = '/tenant-a/mcp'
const requested = () => `${ORIGIN()}${RESOURCE_PATH}`

const server = createServer((req, res) => {
  const url = new URL(req.url, ORIGIN())
  const json = (body, status = 200) => {
    res.writeHead(status, { 'content-type': 'application/json' })
    res.end(JSON.stringify(body))
  }

  // Protected-resource metadata. RFC 9728 §3.1 inserts the well-known suffix after the
  // authority, so both the path-suffixed and root forms are served.
  if (url.pathname.startsWith('/.well-known/oauth-protected-resource')) {
    const doc = {
      authorization_servers: state.authServers ?? [ORIGIN()],
      bearer_methods_supported: ['header'],
    }
    if (!state.omitResource) doc.resource = state.prmResource ?? requested()
    return json(doc)
  }

  // Authorization-server metadata, RFC 8414.
  if (url.pathname.startsWith('/.well-known/oauth-authorization-server')
      || url.pathname.startsWith('/.well-known/openid-configuration')) {
    return json({
      issuer: state.issuer ?? ORIGIN(),
      authorization_endpoint: `${ORIGIN()}/authorize`,
      token_endpoint: `${ORIGIN()}/token`,
      response_types_supported: ['code'],
      code_challenge_methods_supported: ['S256'],
      // Deliberately present so the C-series can distinguish "the server did not publish it"
      // from "the client does not parse it". The census's C18 measures the first; only this
      // bench can see the second.
      protected_resources: [requested()],
      // Control. The first run of this bench reported that both SDKs "parse"
      // protected_resources, because the key survived into the returned object -- but the
      // string appears in zero files of either package, so survival was measuring a
      // non-stripping schema, not comprehension. If this nonsense key survives too, then
      // survival proves nothing and the C1 row must say so.
      xx_control_key_not_in_any_schema: 'control',
    })
  }

  // The challenge that starts discovery.
  if (url.pathname === RESOURCE_PATH) {
    res.writeHead(401, {
      'www-authenticate':
        `Bearer resource_metadata="${ORIGIN()}/.well-known/oauth-protected-resource${RESOURCE_PATH}"`,
    })
    return res.end()
  }

  res.writeHead(404).end()
})

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
PORT = server.address().port

// --- case definitions, as fixed in CASE-MATRIX.md ------------------------------------

const A_CASES = [
  { id: 'A1', label: 'identical', resource: () => requested(), required: 'use' },
  { id: 'A2', label: 'proper ancestor', resource: () => `${ORIGIN()}/`, required: 'reject' },
  { id: 'A3', label: 'sibling', resource: () => `${ORIGIN()}/tenant-b/mcp`, required: 'reject' },
  { id: 'A4', label: 'cross-origin', resource: () => 'http://attacker.example/mcp', required: 'reject' },
  { id: 'A5', label: 'absent', resource: () => null, omit: true, required: 'reject' },
  { id: 'A6', label: 'trailing slash', resource: () => `${requested()}/`, required: 'reject' },
  { id: 'A7', label: 'case-differing path', resource: () => `${ORIGIN()}/TENANT-A/mcp`, required: 'reject' },
]

const D_CASES = [
  { id: 'D1', iss: 'correct', advertised: true, required: 'accept' },
  { id: 'D2', iss: 'wrong', advertised: true, required: 'reject' },
  { id: 'D3', iss: 'absent', advertised: true, required: 'reject' },
  { id: 'D4', iss: 'correct', advertised: undefined, required: 'accept' },
  { id: 'D5', iss: 'wrong', advertised: undefined, required: 'reject' },
  { id: 'D6', iss: 'absent', advertised: undefined, required: 'accept' },
]

const records = []
const emit = (r) => { records.push({ ...r, run_at: new Date().toISOString() }) }

/** A row that could not be exercised is recorded with its reason, never dropped. */
const notExercised = (impl, series, caseId, reason) => emit({
  implementation: impl.id, package: impl.pkg, version: impl.version,
  series, case_id: caseId, outcome: 'not_exercised', detail: reason,
})

// --- A-series: does the client treat "identical" as identical? -----------------------

for (const impl of IMPLS) {
  const selectResourceURL = impl.mod.selectResourceURL
  const discoverPRM = impl.mod.discoverOAuthProtectedResourceMetadata
  if (typeof selectResourceURL !== 'function' || typeof discoverPRM !== 'function') {
    for (const c of A_CASES) notExercised(impl, 'A', c.id, 'selectResourceURL or discoverOAuthProtectedResourceMetadata not exported')
    continue
  }

  for (const c of A_CASES) {
    state.omitResource = !!c.omit
    state.prmResource = c.omit ? null : c.resource()
    state.issuer = null
    state.authServers = null

    let prm = null, prmError = null
    try {
      prm = await discoverPRM(requested())
    } catch (e) { prmError = `${e.constructor.name}: ${e.message}` }

    if (prmError !== null && prm === null) {
      // A malformed document rejected at parse time is a rejection, which is what A5 requires.
      emit({
        implementation: impl.id, package: impl.pkg, version: impl.version,
        series: 'A', case_id: c.id, case_label: c.label,
        requested_identifier: requested(), declared_resource: state.prmResource,
        required: c.required, observed: 'reject', conformant: c.required === 'reject',
        adopted_identifier: null, detail: `rejected at parse: ${prmError}`,
      })
      continue
    }

    let observed, adopted = null, detail = ''
    try {
      const selected = await selectResourceURL(requested(), { }, prm)
      observed = 'use'
      adopted = selected ? String(selected) : null
    } catch (e) {
      observed = 'reject'
      detail = `${e.constructor.name}: ${e.message}`.slice(0, 200)
    }

    emit({
      implementation: impl.id, package: impl.pkg, version: impl.version,
      series: 'A', case_id: c.id, case_label: c.label,
      requested_identifier: requested(), declared_resource: state.prmResource,
      required: c.required, observed, conformant: observed === c.required,
      // The audience the client would then request a token for. When this differs from the
      // requested identifier, the server has chosen the token's audience.
      adopted_identifier: adopted,
      audience_widened: observed === 'use' && adopted !== null && adopted !== requested(),
      detail,
    })
  }
}

// --- B-series: the issuer check the specification does restate -----------------------

for (const impl of IMPLS) {
  const discoverAS = impl.mod.discoverAuthorizationServerMetadata
  if (typeof discoverAS !== 'function') {
    notExercised(impl, 'B', 'B1', 'discoverAuthorizationServerMetadata not exported')
    notExercised(impl, 'B', 'B2', 'discoverAuthorizationServerMetadata not exported')
    continue
  }
  state.omitResource = false
  state.prmResource = null

  for (const [caseId, issuer, required] of [
    ['B1', null, 'use'],
    ['B2', 'http://attacker.example', 'reject'],
  ]) {
    state.issuer = issuer
    let observed, detail = '', doc = null
    try {
      doc = await discoverAS(ORIGIN())
      observed = doc ? 'use' : 'reject'
      if (!doc) detail = 'returned undefined'
    } catch (e) {
      observed = 'reject'
      detail = `${e.constructor.name}: ${e.message}`.slice(0, 200)
    }
    emit({
      implementation: impl.id, package: impl.pkg, version: impl.version,
      series: 'B', case_id: caseId,
      declared_issuer: issuer ?? ORIGIN(), discovery_origin: ORIGIN(),
      required, observed, conformant: observed === required, detail,
    })
  }
}

// --- C-series: is §7.6's only mitigation even parsed? (descriptive) ------------------

for (const impl of IMPLS) {
  const discoverAS = impl.mod.discoverAuthorizationServerMetadata
  state.issuer = null
  state.authServers = null
  let parsed = null
  if (typeof discoverAS === 'function') {
    try { parsed = await discoverAS(ORIGIN()) } catch { /* recorded below as absent */ }
  }
  // Key survival alone does not show the schema knows the field: a non-stripping schema
  // keeps everything. The control key decides it. `source_occurrences` is the independent
  // signal -- if the string is absent from the shipped package, no code can act on it.
  const retained = parsed ? Object.hasOwn(parsed, 'protected_resources') : null
  const controlRetained = parsed ? Object.hasOwn(parsed, 'xx_control_key_not_in_any_schema') : null
  emit({
    implementation: impl.id, package: impl.pkg, version: impl.version,
    series: 'C', case_id: 'C1',
    strength: 'descriptive',
    served_protected_resources: true,
    key_retained: retained,
    control_key_retained: controlRetained,
    // Retention is evidence only when the control is stripped. Otherwise the schema keeps
    // every unknown key and tells us nothing.
    schema_knows_field: retained === true && controlRetained === false,
    source_occurrences: sourceOccurrences(impl.pkg, 'protected_resources'),
    detail: controlRetained
      ? 'schema retains unknown keys: retention is not evidence of comprehension'
      : 'schema strips unknown keys: retention would be evidence',
  })

  // C2: with several authorization servers named, which one is chosen?
  state.authServers = [`${ORIGIN()}/as-first`, `${ORIGIN()}/as-second`]
  state.omitResource = false
  state.prmResource = null
  let chosen = null, cdetail = ''
  try {
    const prm = await impl.mod.discoverOAuthProtectedResourceMetadata(requested())
    chosen = prm?.authorization_servers?.[0] ?? null
    cdetail = 'first array element, as read back from the parsed document'
  } catch (e) { cdetail = `${e.constructor.name}: ${e.message}`.slice(0, 200) }
  emit({
    implementation: impl.id, package: impl.pkg, version: impl.version,
    series: 'C', case_id: 'C2', strength: 'descriptive',
    servers_offered: state.authServers, chosen, detail: cdetail,
  })
  state.authServers = null
}

// --- D-series: RFC 9207 iss, a client MUST under MCP 2026-07-28 ----------------------

for (const impl of IMPLS) {
  const validate = impl.mod.validateAuthorizationResponseIssuer
  if (typeof validate !== 'function') {
    // Not an error. The absence IS the finding: no mix-up defence in this line.
    for (const c of D_CASES) {
      notExercised(impl, 'D', c.id,
        'validateAuthorizationResponseIssuer not exported: this line implements no RFC 9207 check')
    }
    continue
  }

  const issuer = ORIGIN()
  for (const c of D_CASES) {
    // The signature is a single destructured object, read from the shipped source rather
    // than assumed. The first run of this bench passed (URLSearchParams, metadata), so `iss`
    // destructured to undefined on every row, the function took its "nothing to compare"
    // path, and the bench recorded three MUST-level failures against a named vendor that the
    // implementation does not commit. Verified against
    // node_modules/@modelcontextprotocol/client/dist/index.cjs:337.
    const arg = { expectedIssuer: issuer }
    if (c.iss === 'correct') arg.iss = issuer
    if (c.iss === 'wrong') arg.iss = 'http://attacker.example'
    if (c.advertised !== undefined) arg.issParameterSupported = c.advertised

    let observed, detail = ''
    try {
      validate(arg)
      observed = 'accept'
    } catch (e) {
      observed = 'reject'
      detail = `${e.constructor.name}`
    }
    emit({
      implementation: impl.id, package: impl.pkg, version: impl.version,
      series: 'D', case_id: c.id,
      iss: c.iss, advertised: c.advertised ?? null,
      required: c.required, observed, conformant: observed === c.required, detail,
    })
  }
}

server.close()

writeFileSync('results.jsonl', records.map((r) => JSON.stringify(r)).join('\n') + '\n')
console.log(`wrote results.jsonl: ${records.length} records`)
