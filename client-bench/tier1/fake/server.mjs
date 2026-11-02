/**
 * Loopback protected resource + authorization servers for the Tier-1 client bench.
 *
 * Every SDK is driven against this one server, and every cell is decided from the requests it
 * *receives* (CASE-MATRIX.md, amendment of 2 November 2026). Drivers only select a case, run
 * their SDK's own authorization flow, and fetch the log; no driver decides an outcome.
 *
 * Control API (bench-only, never contacted by an SDK):
 *   GET  /__cases          the case ids, in matrix order
 *   POST /__case?id=A2     select a case and clear the log
 *   GET  /__log            requests received since the case was selected
 *
 * No dependencies beyond Node itself. Listens on 127.0.0.1 only.
 */

import { createServer } from 'node:http'

const PORT = Number(process.env.BENCH_PORT ?? 8765)
const ORIGIN = `http://127.0.0.1:${PORT}`
const RESOURCE_PATH = '/tenant-a/mcp'
const REQUESTED = `${ORIGIN}${RESOURCE_PATH}`
const ATTACKER = 'http://attacker.example'

// Authorization servers by id. The id is also the path prefix of its endpoints, so the log
// shows which one a flow reached. "root" has the root issuer; the others are path issuers.
const issuerOf = (asId) => (asId === 'root' ? ORIGIN : `${ORIGIN}/${asId}`)

// --- the cases, exactly as CASE-MATRIX.md fixes them --------------------------------------
// Each case is a patch on the default world: PRM names the requested identifier and the root
// authorization server, which publishes a correct issuer and no RFC 9207 advertisement.
const CASES = {
  A1: { prmResource: REQUESTED },
  A2: { prmResource: `${ORIGIN}/` },
  A3: { prmResource: `${ORIGIN}/tenant-b/mcp` },
  A4: { prmResource: `${ATTACKER}/mcp` },
  A5: { omitResource: true },
  A6: { prmResource: `${REQUESTED}/` },
  A7: { prmResource: `${ORIGIN}/TENANT-A/mcp` },
  B1: {},
  B2: { issuerOverride: ATTACKER },
  // C1's flow is the control for C3: the field is present and lists the requested resource.
  C1: { protectedResources: [REQUESTED] },
  C2: { authServers: ['as-first', 'as-second'] },
  C3: { protectedResources: [`${ORIGIN}/tenant-b/mcp`] },
  D1: { iss: 'correct', issSupported: true },
  D2: { iss: 'wrong', issSupported: true },
  D3: { iss: 'absent', issSupported: true },
  D4: { iss: 'correct' },
  D5: { iss: 'wrong' },
  D6: { iss: 'absent' },
}

let caseId = 'A1'
let world = {}
let log = []

const selectCase = (id) => {
  caseId = id
  // The document names "as-first", a path issuer only the document points to. The first run
  // named the root issuer, which is also where a client lands when it discards the document
  // and falls back to treating the origin as its authorization server, so a discarded
  // document and a used one looked alike (A5). Reaching "as-first" now shows the document was
  // used; reaching "root" shows the fallback.
  world = {
    prmResource: REQUESTED, omitResource: false, authServers: ['as-first'],
    issuerOverride: null, protectedResources: undefined,
    iss: 'correct', issSupported: undefined,
    ...CASES[id],
  }
  log = []
}
selectCase('A1')

const asMetadata = (asId) => {
  const base = asId === 'root' ? `${ORIGIN}/root` : `${ORIGIN}/${asId}`
  const doc = {
    issuer: world.issuerOverride ?? issuerOf(asId),
    authorization_endpoint: `${base}/authorize`,
    token_endpoint: `${base}/token`,
    registration_endpoint: `${base}/register`,
    response_types_supported: ['code'],
    grant_types_supported: ['authorization_code', 'refresh_token'],
    code_challenge_methods_supported: ['S256'],
    token_endpoint_auth_methods_supported: ['none', 'client_secret_post', 'client_secret_basic'],
    scopes_supported: ['mcp'],
  }
  if (world.issSupported !== undefined) {
    doc.authorization_response_iss_parameter_supported = world.issSupported
  }
  if (world.protectedResources !== undefined) doc.protected_resources = world.protectedResources
  return doc
}

const prmDocument = () => {
  const doc = {
    authorization_servers: world.authServers.map(issuerOf),
    bearer_methods_supported: ['header'],
    scopes_supported: ['mcp'],
  }
  if (!world.omitResource) doc.resource = world.prmResource
  return doc
}

// Which authorization server a well-known metadata path names. RFC 8414 inserts the
// well-known segment before the issuer's path; OpenID Connect Discovery appends it.
const AS_IDS = ['as-first', 'as-second']
const asFromWellKnown = (path) => {
  for (const prefix of ['/.well-known/oauth-authorization-server', '/.well-known/openid-configuration']) {
    if (path === prefix || path === `${prefix}/`) return 'root'
    for (const id of AS_IDS) if (path === `${prefix}/${id}`) return id
  }
  for (const id of AS_IDS) if (path === `/${id}/.well-known/openid-configuration`) return id
  return null
}

const readBody = (req) => new Promise((resolve) => {
  let data = ''
  req.on('data', (c) => { data += c })
  req.on('end', () => resolve(data))
})

const server = createServer(async (req, res) => {
  const url = new URL(req.url, ORIGIN)
  const path = url.pathname
  const body = await readBody(req)
  const json = (obj, status = 200, headers = {}) => {
    res.writeHead(status, { 'content-type': 'application/json', ...headers })
    res.end(JSON.stringify(obj))
  }

  // --- control API, not logged --------------------------------------------------------
  if (path === '/__cases') return json(Object.keys(CASES))
  if (path === '/__case' && req.method === 'POST') {
    const id = url.searchParams.get('id')
    if (!(id in CASES)) return json({ error: `unknown case ${id}` }, 400)
    selectCase(id)
    return json({ case_id: id, requested: REQUESTED, origin: ORIGIN })
  }
  if (path === '/__log') return json({ case_id: caseId, requested: REQUESTED, log })

  const entry = {
    method: req.method, path, query: Object.fromEntries(url.searchParams),
    form: req.headers['content-type']?.includes('application/x-www-form-urlencoded')
      ? Object.fromEntries(new URLSearchParams(body)) : undefined,
    json_body: req.headers['content-type']?.includes('application/json') && body
      ? (() => { try { return JSON.parse(body) } catch { return body.slice(0, 500) } })()
      : undefined,
    authorization: req.headers.authorization ? req.headers.authorization.slice(0, 20) : undefined,
    at: Date.now(),
  }
  log.push(entry)

  // --- protected-resource metadata, path-suffixed and root forms ----------------------
  if (path.startsWith('/.well-known/oauth-protected-resource')) return json(prmDocument())

  // --- authorization-server metadata --------------------------------------------------
  const asId = asFromWellKnown(path)
  if (asId) return json(asMetadata(asId))

  // --- authorization-server endpoints -------------------------------------------------
  const m = path.match(/^\/(root|as-first|as-second)\/(authorize|token|register)$/)
  if (m) {
    const [, id, endpoint] = m
    if (endpoint === 'register') {
      const meta = entry.json_body && typeof entry.json_body === 'object' ? entry.json_body : {}
      return json({
        ...meta,
        client_id: `bench-client-${id}`,
        client_id_issued_at: Math.floor(Date.now() / 1000),
        token_endpoint_auth_method: 'none',
      }, 201)
    }
    if (endpoint === 'authorize') {
      const redirect = url.searchParams.get('redirect_uri')
      if (!redirect) return json({ error: 'invalid_request' }, 400)
      const back = new URL(redirect)
      back.searchParams.set('code', `code-${caseId}-${id}`)
      const state = url.searchParams.get('state')
      if (state !== null) back.searchParams.set('state', state)
      if (world.iss === 'correct') back.searchParams.set('iss', issuerOf(id))
      if (world.iss === 'wrong') back.searchParams.set('iss', ATTACKER)
      res.writeHead(302, { location: back.toString() })
      return res.end()
    }
    // token
    return json({
      access_token: `token-${caseId}-${id}`, token_type: 'Bearer', expires_in: 3600,
      refresh_token: `refresh-${caseId}-${id}`, scope: 'mcp',
    })
  }

  // --- the protected resource ---------------------------------------------------------
  if (path === RESOURCE_PATH) {
    if (req.headers.authorization?.startsWith('Bearer token-')) {
      // Enough of MCP for a client to finish connecting once it holds a token. Nothing the
      // bench records depends on what happens after the token request.
      let msg = null
      try { msg = JSON.parse(body) } catch { /* GET or notification */ }
      if (req.method === 'POST' && msg?.method === 'initialize') {
        return json({
          jsonrpc: '2.0', id: msg.id,
          result: {
            protocolVersion: msg.params?.protocolVersion ?? '2025-06-18',
            capabilities: {}, serverInfo: { name: 'bench', version: '0' },
          },
        }, 200, { 'mcp-session-id': 'bench-session' })
      }
      if (req.method === 'POST' && msg && msg.id !== undefined) {
        return json({ jsonrpc: '2.0', id: msg.id, result: {} })
      }
      res.writeHead(req.method === 'GET' ? 405 : 202).end()
      return
    }
    res.writeHead(401, {
      'www-authenticate':
        `Bearer resource_metadata="${ORIGIN}/.well-known/oauth-protected-resource${RESOURCE_PATH}", scope="mcp"`,
    })
    return res.end()
  }

  res.writeHead(404).end()
})

server.listen(PORT, '127.0.0.1', () => console.log(`bench server on ${ORIGIN}`))
