// live-root.mjs — WHERE THE ENGINE ACTUALLY LIVES, IN ONE PLACE.
//
// WHY THIS EXISTS (measured 2026-10-19, ZABZ-YOGA + ZABZ-TECH)
//
// `promote` has only ever written `dshInstall` = `dsh-update/vendor/prefix/<version>` — the STAGING
// directory. That was correct while the launcher resolved its binary out of the npx cache, because the
// vendored prefix was the only pinned tree. It stopped being correct on 2026-10-08, when this estate
// moved to a frozen per-home install at `~/.dsh/engine` and three independent things were pointed at
// it: `multi-window/dshw.ps1:309` probes it before the npx cache,
// `packages/plugin-remote-fanout/lib/nodes.js:84,98` spells it as the bin for mesh children, and both
// machines' running engines load it (measured: YOGA pid 11640, TECH pid 8068 — `... .dsh\engine\
// node_modules\@deepseek-ai\dsh\lib\bin.js web --port 3099`).
//
// So on 2026-10-19 `dsh-update status` printed PIN 0.2.0-rc.2 at the vendor prefix and ENGINE 0.2.0-rc.2
// at `~/.dsh/engine`, with contract and tree sha256 MISMATCH. A `promote` in that state would have
// written `dshInstall` to the vendor prefix and swapped, at the next boot, to an install tree that
// carries none of the hand patches. That is the seam this module closes: the pin, the launcher knob and
// the delivery step now resolve the live root the same way, and the vendor prefix keeps its one job —
// staging candidates for `fetch`/`analyze`/`verify`.
//
// THE RULE: one install root per machine. `~/.dsh/engine` unless something explicitly says otherwise.
// An explicit override is honoured (`DSH_LIVE_INSTALL`, or a `dshInstall` already set in windows.json
// that is NOT under `vendor/prefix`), because a machine in the middle of a migration may legitimately
// point somewhere else — but the choice is recorded, never inferred from whatever happens to exist.

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { PATHS, vendorPrefixPath, windowsJsonPath } from './store.mjs'
import { ENGINE_REL } from './versions.mjs'

/** Read the launcher config's `dshInstall`, defensively. Never throws. */
export function configuredInstallRoot() {
  try {
    const file = windowsJsonPath()
    if (!fs.existsSync(file)) return null
    const cfg = JSON.parse(fs.readFileSync(file, 'utf8'))
    const v = cfg && typeof cfg.dshInstall === 'string' ? cfg.dshInstall.trim() : ''
    return v || null
  } catch {
    return null
  }
}

function hasEngine(root) {
  return !!root && fs.existsSync(path.join(root, ENGINE_REL))
}

function isStagingPath(root) {
  if (!root) return false
  const norm = path.resolve(root).toLowerCase()
  const stage = path.resolve(PATHS.prefixRoot).toLowerCase()
  return norm === stage || norm.startsWith(stage + path.sep)
}

/**
 * The live install root for this machine.
 *
 * Order (each step is a fact, not a guess; the source is returned so every caller can print it):
 *   1. $env:DSH_LIVE_INSTALL            explicit override, must contain an engine
 *   2. windows.json `dshInstall`        if it is set and is NOT the staging area, must contain an engine
 *   3. <home>/.dsh/engine               the estate's frozen per-home install, if it contains an engine
 *   4. null                             nothing is installed where the estate runs its engine
 *
 * The version is accepted for callers that need a fallback to staging, but a fallback to staging is
 * NEVER returned from here: returning the staging path is what produced the seam. If this returns null
 * the caller must refuse rather than guess.
 */
export function liveInstallRoot() {
  const env = process.env.DSH_LIVE_INSTALL && String(process.env.DSH_LIVE_INSTALL).trim()
  if (env) {
    const root = path.resolve(env)
    return { root, source: '$env:DSH_LIVE_INSTALL', present: hasEngine(root) }
  }
  const cfg = configuredInstallRoot()
  if (cfg && !isStagingPath(cfg)) {
    const root = path.resolve(cfg)
    return { root, source: `dshInstall in ${path.basename(windowsJsonPath())}`, present: hasEngine(root) }
  }
  const home = path.join(os.homedir(), '.dsh', 'engine')
  if (hasEngine(home)) {
    return { root: home, source: 'the frozen per-home install <home>/.dsh/engine', present: true }
  }
  return { root: null, source: 'nothing installed at <home>/.dsh/engine, no DSH_LIVE_INSTALL, dshInstall absent or pointing at staging', present: false }
}

/** The engine binary inside a root, or null. */
export function engineBin(root) {
  return root ? path.join(root, ENGINE_REL) : null
}

/** Staging path for a candidate version — what `fetch` writes and `analyze`/`verify` judge. */
export { vendorPrefixPath }
