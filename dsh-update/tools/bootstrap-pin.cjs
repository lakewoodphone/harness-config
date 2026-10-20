// Bootstrap dsh-update state on a machine the pipeline has never run on.
//
// Resolved from THIS FILE'S location, not from a hardcoded Windows path: the same script has to work on
// C:\Users\ezabz\... and on /home/zabz/code/harness-config. The live root is discovered by probe
// ($DSH_LIVE_INSTALL, then ~/.dsh/engine, then ~/dsh-engine), and it refuses rather than guessing.
//
// It writes the initial pin FOR WHAT IS ACTUALLY RUNNING, from measurement, refuses if a pin already exists
// (a pin is never overwritten — that is history), and appends one history row.
const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const ROOT = path.resolve(__dirname, '..')            // <repo>/dsh-update
const pinPath = path.join(ROOT, 'state', 'pin.json')
const binRel = path.join('node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js')

const candidates = []
if (process.env.DSH_LIVE_INSTALL) candidates.push({ root: process.env.DSH_LIVE_INSTALL, source: '$DSH_LIVE_INSTALL' })
candidates.push({ root: path.join(os.homedir(), '.dsh', 'engine'), source: '<home>/.dsh/engine' })
candidates.push({ root: path.join(os.homedir(), 'dsh-engine'), source: '<home>/dsh-engine' })

if (fs.existsSync(pinPath)) {
  const existing = JSON.parse(fs.readFileSync(pinPath, 'utf8'))
  console.log(`pin already exists (${existing.version} at ${existing.installRoot}) — nothing to bootstrap`)
  process.exit(0)
}

const found = candidates.find((c) => fs.existsSync(path.join(c.root, binRel)))
if (!found) {
  console.error('REFUSED: no engine found. Probed:', candidates.map((c) => `${c.source} (${c.root})`).join(', '))
  process.exit(2)
}
const liveRoot = path.resolve(found.root)
const bin = path.join(liveRoot, binRel)

const r = spawnSync(process.execPath, [bin, '--version'], { encoding: 'utf8', timeout: 120000 })
const version = `${r.stdout || ''}${r.stderr || ''}`.trim().split('\n').pop().trim()
if (r.status !== 0 || !version) {
  console.error('REFUSED: the live engine did not report a version:', version || `(exit ${r.status})`)
  process.exit(2)
}

fs.mkdirSync(path.dirname(pinPath), { recursive: true })
const pin = {
  version,
  installRoot: liveRoot,
  enginePath: bin,
  managed: true,
  pinnedAt: new Date().toISOString(),
  by: `${os.hostname().toUpperCase()} (bootstrap: no pin existed; recorded from the running install at ${found.source})`,
  contractSha256: null,
  treeSha256: null,
  predecessor: null,
  verifyReading: null,
}
fs.writeFileSync(pinPath, JSON.stringify(pin, null, 2) + '\n', 'utf8')
const history = path.join(ROOT, 'state', 'history', 'events.tsv')
fs.mkdirSync(path.dirname(history), { recursive: true })
if (!fs.existsSync(history)) fs.writeFileSync(history, 'timestamp\thost\tverb\tversion\tfromVersion\tresult\tdetail\n', 'utf8')
fs.appendFileSync(
  history,
  [new Date().toISOString(), os.hostname().toUpperCase(), 'pin-bootstrap', version, '', 'ok',
    `no pin existed; recorded the running install at ${liveRoot} via ${found.source}`].join('\t') + '\n',
  'utf8',
)
console.log(`bootstrap pin written: ${version} -> ${liveRoot} (via ${found.source})`)
