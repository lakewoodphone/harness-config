// session-list-ab.mjs — verify the pooled session-list patch WITHOUT restarting the engine.
//
// Runs the real store class from the engine's own package against the real session root, prints the
// time and a checksum of the returned artifact id set, so the patched and unpatched versions can be
// compared for both SPEED and CORRECTNESS (identical id set = the patch changed nothing observable).
//
// Lives in the engine root on purpose: bare imports (@deepseek-ai/*) resolve through
// <engine>/node_modules from the importing file's location.
//
// Usage: node session-list-ab.mjs <sessionsRoot> <patched|unpatched>
import { performance } from 'node:perf_hooks'
import { createHash } from 'node:crypto'
import path from 'node:path'
import os from 'node:os'

const root = process.argv[2] || path.join(os.homedir(), '.dsh', 'sessions')
const which = (process.argv[3] || 'patched').toLowerCase()

const target = which === 'unpatched'
  ? './unpatched-store.mjs'
  : '@deepseek-ai/dsh-session-persistence-jsonl'

const started = performance.now()
let mod
try {
  mod = await import(target)
} catch (e) {
  console.log(JSON.stringify({ which, ok: false, stage: 'import', error: String(e && e.message || e) }))
  process.exit(1)
}
const JsonlSessionPersistence = mod.default ?? mod.JsonlSessionPersistence
if (typeof JsonlSessionPersistence !== 'function') {
  console.log(JSON.stringify({ which, ok: false, stage: 'export', keys: Object.keys(mod) }))
  process.exit(1)
}

// A minimal stand-in for the cordis context: the constructor only needs something to install its
// tracker against, and nothing in the list path talks to the engine.
const noop = () => undefined
const ctx = new Proxy({}, {
  get(t, k) {
    if (k === 'name') return 'ab-test'
    if (typeof k === 'symbol') return undefined
    return new Proxy(noop, { get: () => noop, apply: () => undefined })
  },
})

let store
try {
  store = new JsonlSessionPersistence(ctx, { root, compression: 'zstd' })
} catch (e) {
  console.log(JSON.stringify({ which, ok: false, stage: 'construct', error: String(e && e.message || e) }))
  process.exit(1)
}

const t0 = performance.now()
let artifacts
try {
  artifacts = await store.listArtifacts()
} catch (e) {
  console.log(JSON.stringify({ which, ok: false, stage: 'listArtifacts', error: String(e && e.message || e) }))
  process.exit(1)
}
const listMs = performance.now() - t0

const ids = artifacts.map((a) => a.header?.id).filter(Boolean).sort()
const digest = createHash('sha256').update(ids.join('\n')).digest('hex').slice(0, 16)

// a second call, to show whether the second walk is cheaper (memo/OS cache) or the same
const t1 = performance.now()
const again = await store.listArtifacts()
const secondMs = performance.now() - t1

console.log(JSON.stringify({
  which,
  ok: true,
  root,
  count: artifacts.length,
  secondCount: again.length,
  listMs: Math.round(listMs),
  secondMs: Math.round(secondMs),
  idDigest: digest,
  startupMs: Math.round(t0 - started),
  missingIds: artifacts.filter((a) => !a.header?.id).length,
  missingSourceVersion: artifacts.filter((a) => a.sourceVersion === undefined).length,
}, null, 1))
