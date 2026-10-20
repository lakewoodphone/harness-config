// Bootstrap dsh-update state on a machine the pipeline has never run on (ZABZ-YOGA).
//
// WHY THIS IS NEEDED: `promote` needs a previous pin to succeed, and `snapshot` describes the PINNED engine.
// YOGA has been running ~/.dsh/engine since 2026-09-30 and dsh-update has never recorded it, so there is no
// pin at all. This writes the initial pin FOR WHAT IS ACTUALLY RUNNING, from measurement, and refuses if a
// pin already exists (it is never allowed to overwrite history).
const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const root = 'C:/Users/ezabz/code/harness-config/dsh-update'
const pinPath = path.join(root, 'state/pin.json')
const liveRoot = path.join(os.homedir(), '.dsh', 'engine')
const binRel = 'node_modules/@deepseek-ai/dsh/lib/bin.js'
const bin = path.join(liveRoot, binRel)

if (fs.existsSync(pinPath)) {
  console.log('pin already exists — nothing to bootstrap:', JSON.stringify(JSON.parse(fs.readFileSync(pinPath, 'utf8')).version))
  process.exit(0)
}
if (!fs.existsSync(bin)) {
  console.error('REFUSED: no engine at', bin)
  process.exit(2)
}
const r = spawnSync(process.execPath, [bin, '--version'], { encoding: 'utf8', timeout: 120000 })
const version = `${r.stdout || ''}${r.stderr || ''}`.trim().split('\n').pop().trim()
if (r.status !== 0 || !version) {
  console.error('REFUSED: the live engine did not report a version:', version)
  process.exit(2)
}
fs.mkdirSync(path.dirname(pinPath), { recursive: true })
const pin = {
  version,
  installRoot: liveRoot,
  enginePath: bin,
  managed: true,
  pinnedAt: new Date().toISOString(),
  by: `${os.hostname().toUpperCase()} (bootstrap: no pin existed; recorded from the running install)`,
  contractSha256: null,
  treeSha256: null,
  predecessor: null,
  verifyReading: null,
}
fs.writeFileSync(pinPath, JSON.stringify(pin, null, 2) + '\n', 'utf8')
fs.appendFileSync(
  path.join(root, 'state/history/events.tsv'),
  [new Date().toISOString(), os.hostname().toUpperCase(), 'pin-bootstrap', version, '', 'ok',
    `no pin existed; recorded the running install at ${liveRoot} (engine ${version}) so snapshot/promote have a base`].join('\t') + '\n',
  'utf8',
)
console.log('bootstrap pin written:', version, '->', liveRoot)
