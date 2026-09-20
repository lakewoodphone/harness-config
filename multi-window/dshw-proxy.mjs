// dshw-proxy.mjs — one process, N loopback ORIGINS in front of the single engine,
// plus a cache for the one RPC that is slow enough to look like an empty window.
//
// TWO JOBS, both measured on ZABZ-YOGA on 2026-09-18.
//
// ── 1. WHY THE ORIGINS EXIST ────────────────────────────────────────────────────────────────────
//   * A DSH window's "which session am I on" lives in localStorage["dsh.sessions.current"],
//     keyed BY ORIGIN (dsh-api-session-controller/lib/client.js:3058). Different port =>
//     different origin => an independent session slot, independent of every other window.
//   * The engine binds 127.0.0.1:3099 ONLY (netstat: `127.0.0.1:3099 LISTENING 4416`), so
//     127.0.0.2.. are unreachable; and the /api browser-trust fence 403s `w1.localhost`
//     (proved: 403 forbidden) while it ACCEPTS any `127.0.0.1:<port>` (proved: 401, i.e. fence
//     passed, only auth missing). A loopback PORT alias is therefore the only origin trick that
//     needs no engine config change and no engine restart.
//   * With per-window origins available, all windows can share ONE `--user-data-dir`, i.e. ONE
//     browser process tree. Measured 2026-09-18: seven legacy windows on seven private profiles
//     cost 9 processes and 692-1064 MB EACH (mean ~892 MB), because the browser, GPU, crashpad,
//     network and utility layers are duplicated per profile. One shared profile pays those nine
//     processes ONCE and adds roughly one renderer per window.
//
// ── 2. WHY THIS IS NO LONGER A RAW SPLICE ───────────────────────────────────────────────────────
//   `POST /api/session/list` measured 8.5-42 s against the live engine (three calls: 25371 ms,
//   25069 ms, 31357 ms; a fourth 8568 ms), returning 679 rows / 1.46 MB. The cause is scale, not
//   load: dsh-session-persistence-jsonl's listArtifacts() walks EVERY session directory on EVERY
//   call - 681 dirs, one stat() and one zstd header read each. Reproduced in plain node, that scan
//   alone is 5900 ms (2723 ms reading the first zstd line of 681 files, 3127 ms of stat()), so the
//   engine's 25-30 s is that same walk inside its own async pipeline with no cache anywhere.
//   Meanwhile the client has NO loading state: dsh-client-ui-workspace renders the workspace tree
//   from the workspace list (fast) and the session rows from this call, so for those 25-30 s a
//   newly opened window shows its workspace with ZERO session rows and the composer placeholder
//   "Choose a workspace to start" (dsh-client-ui-conversation/lib/client.js:13805). Reproduced
//   live in Playwright against a fresh origin: 0 rows, then 6 rows + "Show 51 more sessions" once
//   the response landed ~27 s later.
//
//   The engine serves the owner's live work and must not be restarted, and its client bundles are
//   shipped inside it, so the fix has to live here: this proxy caches ONE response and re-labels
//   it with each caller's own rpcId. Every window after the first gets the list immediately, and
//   `dshw ensure` (already a 1-minute task) keeps the cache warm so even the first window after a
//   reboot is fast.
//
// ── HOW THE REQUEST SHAPE WAS ESTABLISHED (not guessed) ─────────────────────────────────────────
//   client  dsh-client-connection/lib/client.js:6194-6216  createWebConnectionRpc.call
//           POST <origin>/api/<endpoint>, content-type: application/json
//           { type: "client-request", rpcId: <uuid>, method: <endpoint>, payload: {...} }
//           -> { type: "server-response", rpcId: <same>, result: { ok: true, value: ... } }
//           and it THROWS on `full.rpcId !== rpcId` - which is why a cached reply must be
//           re-labelled rather than replayed verbatim.
//   host    dsh-client-connection/lib/index.js:635-664  rpcFetchHandler
//           non-POST, or a path that is not exactly an endpoint -> 404 "not found"
//           (this is why a GET to /api/session/list answers 404 - a verb error, not a symptom)
//   payload dsh-api-gateway/lib/index.js remoteRequest: must be { args: { ... } }, and
//           dsh-api-session-controller declares the one parameter as "reserved empty list
//           request", so the accepted body is {"args":{"_request":{}}}.
//
// Usage: node dshw-proxy.mjs [--base 3200] [--count 24] [--target 3099] [--ttl 15000] [--log f] [--pidfile f]
import net from 'node:net'
import http from 'node:http'
import zlib from 'node:zlib'
import fs from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt
}

const base = Number(arg('base', 3200))
const count = Number(arg('count', 24))
const enginePort = Number(arg('target', 3099))
const ttlMs = Number(arg('ttl', 15000))
const logFile = arg('log', path.join(process.env.TEMP || '.', 'dshw-origins.log'))
const pidFile = arg('pidfile', '')

const log = (m) => {
  try { fs.appendFileSync(logFile, `[${new Date().toISOString()}] ${m}\n`) } catch { }
}

log(`start pid=${process.pid} base=${base} count=${count} target=127.0.0.1:${enginePort} ttl=${ttlMs}ms`)

const LIST_PATH = '/api/session/list'

/** The cache holds ONE session/list response - the newest we have seen. */
const cache = { text: null, rpcId: null, at: 0, filling: null }
let authCookie = null // learned from any window's own request; used only by the prewarm hook

const stats = { spliced: 0, served: 0, filled: 0, cold: 0, prewarm: 0, prewarmSkipped: 0, errors: 0 }

/**
 * WHICH WINDOWS ARE OPEN - and the proxy is the only thing that can tell.
 *
 * Measured 2026-09-18: in a SHARED profile only the FIRST window's URL appears in any process
 * command line. The browser root (pid 27072) carried `--app=http://127.0.0.1:3200/`, and the second
 * window - opened into the same profile and therefore handed to the same browser process - exists
 * only as an anonymous `--type=renderer` child with no URL at all. So a process scan can find one
 * window per profile, which in shared mode means it can find exactly one window in total.
 *
 * What IS per-window is the alias port. A live window keeps a streaming connection open on its own
 * origin (`$events` / `session/follow`), so counting live connections per port is an exact, not
 * heuristic, answer to "is this slot open". Verified on the two windows this was measured with:
 * ports 3200 and 3201 each held 2 established connections, both owned by the shared browser
 * process. `dshw new` and `dshw restore` depend on this, because a count that always reads zero
 * makes `new` re-open the same slot forever and makes `restore` duplicate every window.
 */
const portState = new Map() // port -> { live, lastSeen }
const portOf = (p) => {
  let s = portState.get(p)
  if (!s) { s = { live: 0, lastSeen: 0 }; portState.set(p, s) }
  return s
}

/**
 * The ports that currently have a live window.
 *
 * `excludePort` is NOT an optimisation. The launcher and `doctor` discover liveness by calling
 * /__dshw/open ON ONE OF THESE PORTS, and that request is itself a connection on that port - so
 * without excluding it the probe reports its own socket as a window. Measured 2026-09-18: with
 * every window closed, /__dshw/stats still reported `openPorts:[3200]`, which is the base port the
 * launcher probes, and slot 1 would therefore have read as permanently open and never been reused.
 */
function openPortList(excludePort) {
  const out = []
  for (const [p, s] of portState) {
    const live = s.live - (p === excludePort ? 1 : 0)
    if (live > 0) out.push(p)
  }
  return out.sort((a, b) => a - b)
}

/** Is another proxy already serving this range? Binding a second one splits the range in two. */
function alreadyRunning() {
  return new Promise((resolve) => {
    const req = http.request(
      { host: '127.0.0.1', port: base, path: '/__dshw/stats', method: 'GET', timeout: 1500 },
      (res) => { res.resume(); resolve(res.statusCode === 200) },
    )
    req.on('timeout', () => { req.destroy(); resolve(false) })
    req.on('error', () => resolve(false))
    req.end()
  })
}

/**
 * A SECOND, ATOMIC GUARD, because reachability alone has a race: two instances starting within the
 * same instant both probe, both hear "nothing there", and both bind. `wx` is an atomic
 * create-if-absent, so only one of them can win. A lock whose pid is no longer alive is a crash
 * leftover and is taken over rather than honoured - otherwise one hard kill would wedge the proxy
 * forever, which is a worse failure than the one this prevents.
 */
function acquireLock(lockPath) {
  const alive = (pid) => { try { process.kill(pid, 0); return true } catch { return false } }
  try {
    fs.writeFileSync(lockPath, String(process.pid), { flag: 'wx' })
    return true
  } catch (e) {
    if (e.code !== 'EEXIST') return true
    let owner = NaN
    try { owner = Number(fs.readFileSync(lockPath, 'utf8').trim()) } catch { }
    if (Number.isFinite(owner) && owner > 0 && alive(owner)) return false
    try { fs.unlinkSync(lockPath); fs.writeFileSync(lockPath, String(process.pid), { flag: 'wx' }); return true } catch { return false }
  }
}

const lockPath = arg('lock', path.join(process.env.TEMP || '.', `dshw-proxy-${base}.lock`))

/**
 * Read one upstream request. Resolves `{ parsed: true, ... }` when the framing is fully
 * understood, and `{ parsed: false, head }` otherwise - and in BOTH cases the socket is
 * left paused with every byte so far inside `head`, so the caller can splice it upstream
 * without losing whatever arrived while this was deciding.
 */
function readRequest(client) {
  return new Promise((resolve) => {
    let buf = Buffer.alloc(0)
    const finish = (value) => {
      client.off('data', onData)
      client.off('error', onGone)
      client.off('close', onGone)
      client.pause() // pipe() resumes it; without this, bytes arriving before pipe() attaches are lost
      resolve(value)
    }
    const onGone = () => finish(null)
    const onData = (chunk) => {
      buf = Buffer.concat([buf, chunk])
      const end = buf.indexOf('\r\n\r\n')
      if (end === -1) {
        if (buf.length > 256 * 1024) finish({ parsed: false, head: buf })
        return
      }
      const lines = buf.subarray(0, end).toString('latin1').split('\r\n')
      const [method, rawTarget, version] = lines[0].split(' ')
      const headers = {}
      for (const line of lines.slice(1)) {
        const i = line.indexOf(':')
        if (i > 0) headers[line.slice(0, i).trim().toLowerCase()] = line.slice(i + 1).trim()
      }
      const bodyStart = end + 4
      const declared = Number(headers['content-length'] ?? '0')
      // Anything whose framing we do not fully understand is spliced, never interpreted.
      if (headers['transfer-encoding'] !== undefined || !Number.isFinite(declared)) {
        finish({ parsed: false, head: buf })
        return
      }
      if (buf.length - bodyStart >= declared) {
        finish({
          parsed: true, method, rawTarget, version, headers,
          headOnly: buf.subarray(0, bodyStart),
          body: buf.subarray(bodyStart, bodyStart + declared),
          extra: buf.subarray(bodyStart + declared),
          head: buf,
        })
      }
    }
    client.on('data', onData)
    client.on('error', onGone)
    client.on('close', onGone)
  })
}

function decompress(res, buf) {
  const enc = String(res.headers['content-encoding'] ?? '').toLowerCase()
  try {
    if (enc.includes('gzip')) return zlib.gunzipSync(buf)
    if (enc.includes('br')) return zlib.brotliDecompressSync(buf)
    if (enc.includes('deflate')) return zlib.inflateSync(buf)
  } catch { return null }
  return buf
}

/** One real session/list against the engine, using a cookie a window has already presented. */
function fetchList(cookie) {
  return new Promise((resolve) => {
    const started = Date.now()
    const rpcId = randomUUID()
    const body = JSON.stringify({
      type: 'client-request', rpcId, method: 'session/list',
      payload: { args: { _request: {} } },
    })
    const req = http.request({
      host: '127.0.0.1', port: enginePort, path: LIST_PATH, method: 'POST',
      headers: {
        'content-type': 'application/json',
        'content-length': Buffer.byteLength(body),
        // The original Host is what keeps the fence passing: /api accepts any 127.0.0.1:<port>.
        host: `127.0.0.1:${base}`,
        'accept-encoding': 'gzip',
        ...(cookie ? { cookie } : {}),
      },
    }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => {
        const raw = decompress(res, Buffer.concat(chunks))
        if (!raw) return resolve({ ok: false, reason: 'undecodable upstream body' })
        const text = raw.toString('utf8')
        let parsed
        try { parsed = JSON.parse(text) } catch { return resolve({ ok: false, reason: 'upstream body is not JSON' }) }
        if (parsed?.result?.ok !== true) {
          return resolve({ ok: false, reason: `upstream result not ok: ${JSON.stringify(parsed?.result?.error ?? {}).slice(0, 200)}` })
        }
        const items = parsed?.result?.value?.items
        cache.text = text
        cache.rpcId = rpcId
        cache.at = Date.now()
        stats.filled++
        resolve({ ok: true, rows: Array.isArray(items) ? items.length : undefined, ms: Date.now() - started })
      })
    })
    req.on('error', (e) => resolve({ ok: false, reason: e.message }))
    req.end(body)
  })
}

function refreshInBackground() {
  if (!authCookie) return null
  if (cache.filling) return cache.filling
  cache.filling = fetchList(authCookie).then((r) => {
    cache.filling = null
    log(r.ok ? `cache refresh ok rows=${r.rows} in ${r.ms} ms` : `cache refresh FAILED: ${r.reason}`)
    return r
  })
  return cache.filling
}

function send(client, status, headers, body) {
  const head = [`HTTP/1.1 ${status}`, ...Object.entries(headers).map(([k, v]) => `${k}: ${v}`), '', ''].join('\r\n')
  client.write(head, 'latin1')
  client.write(body)
  client.end()
}

function sendJson(client, status, value) {
  const buf = Buffer.from(JSON.stringify(value), 'utf8')
  send(client, status, {
    'content-type': 'application/json',
    'content-length': buf.length,
    'cache-control': 'no-store',
    connection: 'close',
  }, buf)
}

/** A cached reply is re-labelled with the caller's OWN rpcId: the client throws on a mismatch. */
function serveCached(client, callerRpcId) {
  let body = cache.text
  if (callerRpcId && cache.rpcId && cache.rpcId !== callerRpcId) {
    body = body.replace(`"rpcId":"${cache.rpcId}"`, `"rpcId":"${callerRpcId}"`)
  }
  const buf = Buffer.from(body, 'utf8')
  stats.served++
  send(client, '200 OK', {
    'content-type': 'application/json',
    'content-length': buf.length,
    'cache-control': 'no-store',
    connection: 'close',
  }, buf)
}

/**
 * THE CONNECTION ISOLATION THAT MAKES THE CACHE WORK AT ALL.
 *
 * Measured 2026-09-18: with a plain splice, `session/list` never reached the interceptor - the
 * proxy's own counter showed `spliced=19, cold=0` while the sidebar sat empty. The cause is
 * keep-alive connection reuse: the page's first requests open ~6 connections, each is handed to a
 * raw pipe because it is not session/list, and the browser then reuses one of those pipes for
 * session/list. A connection that has become a pipe can never be intercepted again, so the cache
 * could never fill.
 *
 * A request forwarded with `Connection: close` cannot be reused, so every request arrives on its
 * own connection and is parsed. Measured: `GET /` with `Connection: close` makes the engine answer
 * `Connection: close` and end the response, while `keep-alive` makes it answer
 * `Keep-Alive: timeout=5`. Upgrade requests are NEVER rewritten - a WebSocket upgrade needs
 * `Connection: Upgrade` intact - so they are spliced byte-for-byte.
 */
function rewriteHead(req) {
  const upgrade = req.headers.upgrade !== undefined || /\bupgrade\b/i.test(req.headers.connection ?? '')
  if (upgrade) return req.head
  // `headOnly` ends exactly with the "\r\n\r\n" terminator (bodyStart = index of that marker + 4),
  // so the new header is inserted immediately BEFORE the terminator. Getting this wrong puts the
  // header into the body: a first attempt spliced at `lines.length - 1`, which produced
  // "...Host: x\r\n\r\nConnection: close" and the engine answered the navigation with a failure.
  let text = req.headOnly.toString('latin1').replace(/\r\nconnection:[^\r\n]*/gi, '')
  const at = text.length - 4
  text = text.slice(0, at) + '\r\nConnection: close' + text.slice(at)
  return Buffer.concat([
    Buffer.from(text, 'latin1'),
    req.body ?? Buffer.alloc(0),
    req.extra ?? Buffer.alloc(0),
  ])
}

function splice(client, req) {
  const upstream = net.connect({ host: '127.0.0.1', port: enginePort })
  const done = () => { client.destroy(); upstream.destroy() }
  upstream.on('error', done)
  // ── KEEPALIVE ON BOTH LEGS, AND WHY IT IS THE FIX FOR "IT JUST SAYS THINKING" ────────────────
  // Measured 2026-09-20 from the owner's own description: *"sometimes when I talk to you, it just
  // says thinking and I have to refresh the page, and I see that really you thought a lot and it
  // didn't stream in."* The engine had produced the text the whole time — a reload re-reads the
  // session and renders it — so the failure was in the LIVE STREAM, and this function is the live
  // stream's only middleman.
  //
  // A raw `pipe` pair has no idle detection of any kind: no `setTimeout`, no keepalive, nothing that
  // notices a path that has stopped forwarding bytes. The laptop's route to the office is a
  // Tailscale DERP relay (measured; `docs/mesh/113`), and a relay or NAT that drops a flow silently
  // sends no FIN — so the client's socket stays ESTABLISHED, its WebSocket never closes, no
  // reconnect is ever attempted, and the UI waits on a stream that will never deliver another byte.
  // The websocket is spliced byte-for-byte and NEVER rewritten (see `rewriteHead` above), so the
  // application cannot heartbeat it either; the only layer left that can notice is TCP.
  //
  // `setKeepAlive(true, 15000)` makes the kernel probe an idle connection after 15 s and, when the
  // probes go unanswered, close it — which is what turns a permanently-dead stream into a close
  // event the client can reconnect from. It changes nothing while bytes are flowing, and it is the
  // same reason every long-lived ssh hop in this repo carries ServerAliveInterval.
  for (const s of [client, upstream]) {
    try { s.setKeepAlive(true, 15000) } catch { /* not a TCP socket: leave it alone */ }
    try { s.setNoDelay(true) } catch { /* ditto */ }
  }
  upstream.write(req.parsed ? rewriteHead(req) : req.head)
  client.pipe(upstream)
  upstream.pipe(client)
  client.on('close', done)
  upstream.on('close', done)
  stats.spliced++
}

function startAll() {
for (let i = 0; i < count; i++) {
  const port = base + i
  const server = net.createServer(async (client) => {
    const st = portOf(port)
    st.live++
    st.lastSeen = Date.now()
    client.on('error', () => { })
    client.on('close', () => { st.live = Math.max(0, st.live - 1) })
    const req = await readRequest(client)
    if (!req) { client.destroy(); return }

    const isList = req.parsed && req.method === 'POST' && req.rawTarget === LIST_PATH
    const isPrewarm = req.parsed && req.method === 'GET' && req.rawTarget === '/__dshw/prewarm'
    const isStat = req.parsed && req.method === 'GET' && req.rawTarget === '/__dshw/stats'
    const isOpen = req.parsed && req.method === 'GET' && req.rawTarget === '/__dshw/open'

    // `open` before `splice`: it is one of ours, not a passthrough.
    if (isOpen) {
      const ports = openPortList(port)
      sendJson(client, '200 OK', { ports, live: Object.fromEntries(ports.map((p) => [p, portOf(p).live])) })
      return
    }

    if (!isList && !isPrewarm && !isStat) {
      if (req.parsed && /dsh-auth-/.test(req.headers.cookie ?? '')) authCookie = req.headers.cookie
      splice(client, req)
      return
    }

    if (/dsh-auth-/.test(req.headers.cookie ?? '')) authCookie = req.headers.cookie

    if (isStat) {
      sendJson(client, '200 OK', {
        ...stats,
        cached: cache.text !== null,
        ageMs: cache.text ? Date.now() - cache.at : null,
        rows: cache.text ? (cache.text.match(/"sessionId":/g) ?? []).length : null,
        hasAuth: authCookie !== null,
        openPorts: openPortList(port),
      })
      return
    }

    if (isPrewarm) {
      if (!authCookie) {
        stats.prewarmSkipped++
        sendJson(client, '200 OK', { ok: false, reason: 'no auth cookie seen from any window yet' })
        return
      }
      stats.prewarm++
      sendJson(client, '200 OK', await fetchList(authCookie))
      return
    }

    // POST /api/session/list
    let callerRpcId = null
    try { callerRpcId = JSON.parse(req.body.toString('utf8'))?.rpcId ?? null } catch { }

    if (cache.text !== null) {
      serveCached(client, callerRpcId)
      // STALE-WHILE-REVALIDATE: the caller never waits for the refresh, so the latency on this
      // path is the proxy's, not the 681-directory walk's.
      if (Date.now() - cache.at > ttlMs) refreshInBackground()
      return
    }

    // Cold: this caller pays the real cost, everyone after it does not.
    stats.cold++
    const upstream = http.request({
      host: '127.0.0.1', port: enginePort, path: LIST_PATH, method: 'POST',
      headers: {
        'content-type': 'application/json',
        'content-length': req.body.length,
        host: req.headers.host ?? `127.0.0.1:${port}`,
        'accept-encoding': 'gzip',
        ...(req.headers.cookie ? { cookie: req.headers.cookie } : {}),
      },
    }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', async () => {
        const raw = decompress(res, Buffer.concat(chunks))
        let result
        if (!raw) {
          stats.errors++
          result = { ok: false, error: { code: 'dshw/proxy', message: 'undecodable upstream body', details: {} } }
        } else {
          const text = raw.toString('utf8')
          try {
            const parsed = JSON.parse(text)
            result = parsed?.result
            if (result?.ok === true) {
              cache.text = text
              cache.rpcId = callerRpcId
              cache.at = Date.now()
              stats.filled++
              log(`cache filled rows=${Array.isArray(result?.value?.items) ? result.value.items.length : '?'}`)
            } else {
              stats.errors++
              log(`cache fill refused: upstream envelope ${JSON.stringify({
                hasResult: result !== undefined,
                ok: result?.ok,
                error: result?.error,
                envelopeKeys: parsed && typeof parsed === 'object' ? Object.keys(parsed) : typeof parsed,
                head: text.slice(0, 240),
              })}`)
              // SELF-HEAL. A caller's own request can fail while the SAME call succeeds from here -
              // observed 2026-09-18, where two windows' page-load calls both came back not-ok and
              // left `cold=2 filled=0`, so the cache stayed empty and every later window paid the
              // full walk. This caller is answered either way; the retry exists so ONE bad response
              // cannot leave the cache permanently cold.
              if (authCookie) {
                const retry = await fetchList(authCookie)
                if (retry.ok) {
                  log(`cache recovered by proxy-side refetch (rows=${retry.rows})`)
                  let body = cache.text
                  if (callerRpcId && cache.rpcId !== callerRpcId) {
                    body = body.replace(`"rpcId":"${cache.rpcId}"`, `"rpcId":"${callerRpcId}"`)
                  }
                  send(client, '200 OK', {
                    'content-type': 'application/json',
                    'content-length': Buffer.byteLength(body),
                    'cache-control': 'no-store',
                    connection: 'close',
                  }, Buffer.from(body, 'utf8'))
                  return
                }
              }
            }
          } catch (e) {
            stats.errors++
            result = { ok: false, error: { code: 'dshw/proxy', message: 'upstream body is not JSON', details: {} } }
          }
        }
        sendJson(client, '200 OK', { type: 'server-response', rpcId: callerRpcId, result })
      })
    })
    upstream.on('error', (e) => {
      stats.errors++
      sendJson(client, '200 OK', {
        type: 'server-response', rpcId: callerRpcId,
        result: { ok: false, error: { code: 'dshw/proxy', message: e.message, details: {} } },
      })
    })
    upstream.end(req.body)
  })
  // A PORT THAT IS STILL BEING RELEASED IS NOT A PORT WE HAVE LOST. Measured 2026-09-18: a
  // stop-then-start released 3200-3215 and left 3216-3223 briefly held, so a second instance bound
  // the lower half, reported EADDRINUSE for the upper half, and the launcher then declared the
  // proxy dead and started a third. Retrying the bind for a few seconds removes the race entirely.
  const listenWithRetry = (attempt = 0) => {
    server.once('error', (e) => {
      if (e.code === 'EADDRINUSE' && attempt < 20) {
        setTimeout(() => listenWithRetry(attempt + 1), 500)
        return
      }
      log(`port ${port}: LISTEN FAILED ${e.code} after ${attempt} retries`)
      process.exitCode = 2
    })
    server.listen(port, '127.0.0.1', () => log(`listening 127.0.0.1:${port} -> ${enginePort}`))
  }
  listenWithRetry()
}
}

if (pidFile) { try { fs.writeFileSync(pidFile, String(process.pid)) } catch { } }

// SINGLE INSTANCE, DECIDED BY REACHABILITY RATHER THAN BY A LOCK FILE. Measured 2026-09-18: two
// instances came up together and SPLIT THE RANGE between them (one held 3200-3215, the other
// 3216-3223), which looks healthy from any single port and is not. A proxy that can already answer
// on the base port means the range is served, so this one exits 0 rather than binding half of it.
alreadyRunning().then((busy) => {
  if (busy) {
    log(`another proxy already answers on :${base} - exiting without binding (single instance)`)
    process.exit(0)
  }
  if (!acquireLock(lockPath)) {
    log(`another proxy holds ${lockPath} and is alive - exiting without binding (single instance)`)
    process.exit(0)
  }
  log(`lock acquired: ${lockPath}`)
  startAll()
})

const releaseLock = () => { try { if (fs.readFileSync(lockPath, 'utf8').trim() === String(process.pid)) fs.unlinkSync(lockPath) } catch { } }
process.on('exit', releaseLock)

setInterval(() => {
  log(`stats spliced=${stats.spliced} served=${stats.served} cold=${stats.cold} filled=${stats.filled} ` +
      `prewarm=${stats.prewarm} skipped=${stats.prewarmSkipped} errors=${stats.errors} ` +
      `cacheAgeMs=${cache.text ? Date.now() - cache.at : 'none'}`)
}, 300000).unref?.()

const bye = () => { log('exit signal'); process.exit(0) }
process.on('SIGINT', bye)
process.on('SIGTERM', bye)
