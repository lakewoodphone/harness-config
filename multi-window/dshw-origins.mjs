// dshw-origins.mjs — one process, N loopback ORIGINS in front of the single engine.
//
// WHY THIS EXISTS (measured 2026-09-18, ZABZ-YOGA):
//   * A DSH window's "which session am I on" lives in localStorage["dsh.sessions.current"],
//     which is keyed BY ORIGIN (dsh-api-session-controller/lib/client.js:3058). Different port
//     => different origin => an independent session slot, independent of every other window.
//   * The engine binds 127.0.0.1:3099 ONLY (netstat: `127.0.0.1:3099 LISTENING 4416`), so
//     127.0.0.2.. are unreachable; and the /api browser-trust fence 403s `w1.localhost`
//     (proved: 403 forbidden) while it ACCEPTS any `127.0.0.1:<port>` (proved: 401, i.e. fence
//     passed, only auth missing). So a loopback PORT alias is the only origin trick that needs
//     no engine config change and no engine restart.
//   * With per-window origins available, all windows can share ONE `--user-data-dir`, i.e. ONE
//     browser process tree: measured 8 isolated windows = 72 processes / 7,149 MB, of which the
//     browser+GPU+crashpad+network layers are duplicated 8x (~894 MB and 9 processes per window).
//
// This proxy is a raw TCP splice: HTTP and the WebSocket upgrade both pass through untouched
// (the Host header keeps the alias port, which is what makes the origin distinct).
//
// Usage: node dshw-origins.mjs [--base 3200] [--count 16] [--target 3099] [--log <file>]
import net from 'node:net'
import fs from 'node:fs'
import path from 'node:path'

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt
}

const base = Number(arg('base', 3200))
const count = Number(arg('count', 16))
const target = Number(arg('target', 3099))
const logFile = arg('log', path.join(process.env.TEMP || '.', 'dshw-origins.log'))
const pidFile = arg('pidfile', '')

const log = (m) => {
  try { fs.appendFileSync(logFile, `[${new Date().toISOString()}] ${m}\n`) } catch { }
}
log(`start pid=${process.pid} base=${base} count=${count} target=127.0.0.1:${target}`)

let live = 0
let refused = 0
let bytesUp = 0
let bytesDown = 0

for (let i = 0; i < count; i++) {
  const port = base + i
  const server = net.createServer((client) => {
    live++
    const upstream = net.connect({ host: '127.0.0.1', port: target })
    upstream.on('error', (e) => { refused++; client.destroy() })
    client.on('error', () => upstream.destroy())
    client.on('data', (d) => { bytesUp += d.length })
    upstream.on('data', (d) => { bytesDown += d.length })
    client.pipe(upstream)
    upstream.pipe(client)
    const done = () => { client.destroy(); upstream.destroy(); live-- }
    client.on('close', done)
    upstream.on('close', done)
  })
  server.on('error', (e) => {
    log(`port ${port}: LISTEN FAILED ${e.code} (already in use?)`)
    process.exitCode = 2
  })
  server.listen(port, '127.0.0.1', () => log(`listening 127.0.0.1:${port} -> ${target}`))
}

if (pidFile) { try { fs.writeFileSync(pidFile, String(process.pid)) } catch { } }

setInterval(() => {
  if (live || refused) log(`stats live=${live} refused=${refused} up=${bytesUp}B down=${bytesDown}B`)
}, 60000).unref?.()

const bye = () => { log(`exit signal, live=${live}`); process.exit(0) }
process.on('SIGINT', bye)
process.on('SIGTERM', bye)
