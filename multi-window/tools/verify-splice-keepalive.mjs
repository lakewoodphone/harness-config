// verify-splice-keepalive.mjs - controlled proof for the "it just says thinking" streaming fix.
//
// Two independent checks, because the two halves of the claim are different:
//
//   A. SOCKET-OPTION PROOF. The real `splice()` source is read out of multi-window/dshw-proxy.mjs,
//      compiled with stub sockets, and asserted to call setKeepAlive(true, 15000) and setNoDelay()
//      on BOTH legs. This is the mechanism that turns a silently-dropped flow (no FIN) into a close.
//      A negative control runs the same harness on the pre-fix splice and asserts it sets neither.
//
//   B. CLOSE+RECONNECT PROOF. A real proxy process (isolated ports, fake engine) serves a spliced
//      stream; the engine-side socket is killed mid-stream, and the client must observe a close
//      promptly and be able to reconnect - it must not hang.
//
// A true packet-level silent drop cannot be staged on loopback without a packet filter, so the
// silent-drop half is proved at the socket-option level (A) and the close/reconnect half end-to-end
// (B). Run: node multi-window/tools/verify-splice-keepalive.mjs
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import os from 'node:os'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const here = path.dirname(fileURLToPath(import.meta.url))
const proxyPath = path.join(here, '..', 'dshw-proxy.mjs')
const source = fs.readFileSync(proxyPath, 'utf8')
let failures = 0
const pass = (m) => console.log('  PASS  ' + m)
const fail = (m) => { failures++; console.log('  FAIL  ' + m) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/* ── A. socket-option proof ──────────────────────────────────────────────────────────────── */

function extractFunction(src, name) {
  const start = src.indexOf('function ' + name + '(')
  if (start < 0) throw new Error('function ' + name + ' not found')
  let depth = 0
  for (let i = src.indexOf('{', start); i < src.length; i++) {
    if (src[i] === '{') depth++
    else if (src[i] === '}') { depth--; if (depth === 0) return src.slice(start, i + 1) }
  }
  throw new Error('unbalanced braces extracting ' + name)
}

class Stub {
  constructor() { this.calls = [] }
  setKeepAlive(...a) { this.calls.push(['setKeepAlive', ...a]); return this }
  setNoDelay(...a) { this.calls.push(['setNoDelay', ...a]); return this }
  write() { return true }
  pipe() { return this }
  on() { return this }
  destroy() { return this }
}

function runSpliceOn(src) {
  const fnSrc = extractFunction(src, 'splice')
  const made = []
  const netStub = { connect() { const s = new Stub(); made.push(s); return s } }
  const stats = { spliced: 0 }
  const factory = new Function('net', 'enginePort', 'stats', 'rewriteHead', 'return (' + fnSrc + ')')
  const splice = factory(netStub, 3599, stats, () => Buffer.alloc(0))
  const client = new Stub()
  splice(client, { head: Buffer.from('GET / HTTP/1.1\r\n\r\n'), parsed: false })
  return { client, upstream: made[0], stats }
}

function assertKeepalive(legs, label) {
  for (const [name, s] of Object.entries(legs)) {
    const ka = s.calls.find((c) => c[0] === 'setKeepAlive')
    const nd = s.calls.find((c) => c[0] === 'setNoDelay')
    if (ka && ka[1] === true && ka[2] === 15000) pass(`${label}: ${name} leg setKeepAlive(true, 15000)`)
    else fail(`${label}: ${name} leg missing setKeepAlive(true, 15000) (calls: ${JSON.stringify(s.calls)})`)
    if (nd) pass(`${label}: ${name} leg setNoDelay(true)`)
    else fail(`${label}: ${name} leg missing setNoDelay(true)`)
  }
}

console.log('A. socket-option proof on the real splice() source')
{
  const r = runSpliceOn(source)
  assert.ok(r.stats.spliced === 1, 'splice counted the stream')
  assertKeepalive({ client: r.client, upstream: r.upstream }, 'fixed')

  // Negative control: remove the keepalive loop from the source and show the harness notices.
  const before = source.replace(/  for \(const s of \[client, upstream\]\) \{[\s\S]*?\n  \}\n/, '')
  if (before === source) fail('negative control could not remove the keepalive block')
  else {
    const old = runSpliceOn(before)
    const anyKa = [old.client, old.upstream].some((s) => s.calls.some((c) => c[0] === 'setKeepAlive'))
    if (!anyKa) pass('negative control: pre-fix splice sets no keepalive (harness discriminates)')
    else fail('negative control: pre-fix splice unexpectedly set keepalive')
  }
}

/* ── B. real proxy: killed stream closes the client, and the client can reconnect ─────────── */

const BASE = 3590
const ENGINE = 3599
const logFile = path.join(os.tmpdir(), `verify-splice-${process.pid}.log`)
const pidFile = path.join(os.tmpdir(), `verify-splice-${process.pid}.pid`)
const lockFile = path.join(os.tmpdir(), `verify-splice-${process.pid}.lock`)

async function waitForListen(port, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const ok = await new Promise((resolve) => {
      const s = net.connect(port, '127.0.0.1')
      s.once('connect', () => { s.destroy(); resolve(true) })
      s.once('error', () => resolve(false))
    })
    if (ok) return true
    await sleep(100)
  }
  return false
}

// Opens one spliced stream and resolves `closed` with 'close' or 'hung'.
function splicedClient(hangMs = 6000) {
  const s = net.connect(BASE, '127.0.0.1')
  const chunks = []
  let resolveClosed
  const closed = new Promise((r) => { resolveClosed = r })
  const t = setTimeout(() => resolveClosed('hung'), hangMs)
  s.on('data', (d) => chunks.push(d))
  s.on('error', () => { })
  s.on('close', () => { clearTimeout(t); resolveClosed('close') })
  s.on('connect', () => s.write('GET /stream HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n'))
  return { s, chunks, closed }
}
const hello = (c) => Buffer.concat(c.chunks).toString().includes('ENGINE-HELLO')

console.log('B. real proxy: kill the engine socket mid-stream, expect client close + reconnect')
let proxy = null
let engine = null
try {
  const engineSockets = []
  engine = net.createServer((sock) => { engineSockets.push(sock); sock.write('ENGINE-HELLO\n') })
  await new Promise((res, rej) => { engine.once('error', rej); engine.listen(ENGINE, '127.0.0.1', res) })
  pass(`fake engine listening on :${ENGINE}`)

  proxy = spawn(process.execPath, [proxyPath,
    '--base', String(BASE), '--count', '1', '--target', String(ENGINE),
    '--ttl', '15000', '--pidfile', pidFile, '--log', logFile, '--lock', lockFile,
  ], { stdio: 'ignore' })
  if (!await waitForListen(BASE)) throw new Error('proxy never listened on ' + BASE)
  pass(`fixed proxy listening on :${BASE}`)

  const first = splicedClient()
  for (let i = 0; i < 30 && !hello(first); i++) await sleep(100)
  if (hello(first)) pass('client received bytes through the splice')
  else fail('client did not receive the spliced hello: ' + JSON.stringify(Buffer.concat(first.chunks).toString()))

  const killedAt = Date.now()
  for (const s of engineSockets) s.destroy()
  pass(`killed ${engineSockets.length} engine-side socket(s) mid-stream`)

  const outcome = await first.closed
  if (outcome === 'close') pass(`client observed close ~${Date.now() - killedAt} ms after the kill (did not hang)`)
  else fail('client HUNG after the engine socket died')

  const again = splicedClient()
  for (let i = 0; i < 30 && !hello(again); i++) await sleep(100)
  if (hello(again)) pass('client reconnected and was served again')
  else fail('client could not reconnect: ' + JSON.stringify(Buffer.concat(again.chunks).toString()))
} catch (e) {
  fail('exception: ' + (e && e.stack ? e.stack : e))
} finally {
  if (engine) engine.close()
  if (proxy) proxy.kill()
  for (const f of [logFile, pidFile, lockFile]) { try { fs.unlinkSync(f) } catch { } }
}

console.log(failures === 0 ? '\nRESULT: all splice-keepalive checks passed' : `\nRESULT: ${failures} check(s) FAILED`)
process.exit(failures === 0 ? 0 : 1)
