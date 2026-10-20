// link-anchors.mjs — recreate the module anchors a staged DSH home needs, or the composition lies.
//
// WHY THIS EXISTS (measured 2026-10-19, ZABZ-TECH, against 0.2.1-rc.2)
//
// `lib/stage-home.mjs` copies 44 config files and deliberately skips `node_modules` ("3 skipped
// (state/backups/node_modules)"). That is fine for a settings migration and wrong for a composition
// test, because OUR OWN plugin bundles are resolved from the profile's anchors:
//
//   C:\Users\ezabz\.dsh-staged\0.2.1-rc.2> dsh --profile web --dump-config
//   dsh: skipping profile bundle "dsh-plugin-attention": cannot resolve profile bundle
//        "dsh-plugin-attention" from the dsh installation or ...\profiles\web
//
// The engine SKIPS an unresolvable bundle without failing (exit 0). The staged home therefore composed
// 410 rows instead of 421 and lost `remote-fanout`, `tool-subagent-remote` and `spend-guard`, so
// `patch-effect` reported BREAKS=3 and `verify` G2 reported "a patch target is not a row in the composed
// tree" — three findings about the 0.2.1 CANDIDATE that were entirely artifacts of the STAGING. Measured
// the moment both anchors existed: 421 rows, our ids present, 0 bundles skipped — on the same engine.
//
// THE RULE THIS ENFORCES: an isolated home that is used to JUDGE a composition must carry the same
// anchors the live home carries. Two anchors matter, and both are measured:
//   <home>/profiles/node_modules                  the shared anchor (187 entries on ZABZ-TECH)
//   <home>/profiles/<profile>/node_modules        the per-profile anchor the engine names in its error
//
// A junction is used on Windows and a symlink elsewhere; with --copy the tree is copied instead, for a
// test that must not depend on the live tree at all. Nothing is ever deleted, and an existing anchor is
// left alone unless --force is given (a real anchor is never replaced by a link).

import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'

const ARGV = process.argv.slice(2)
const flag = (n, d = null) => { const i = ARGV.indexOf(`--${n}`); if (i === -1) return d; const v = ARGV[i + 1]; return v && !v.startsWith('--') ? v : true }
const has = (n) => ARGV.includes(`--${n}`)

const staged = String(flag('staged') || '')
const from = String(flag('from') || process.env.DSH_LIVE_HOME || process.env.DSH_HOME || '')
if (!staged || !from) { console.error('usage: link-anchors.mjs --staged <stagedHome> --from <liveHome> [--copy] [--force]'); process.exit(2) }
if (!fs.existsSync(staged)) { console.error(`link-anchors: ${staged} does not exist`); process.exit(2) }
if (!fs.existsSync(from)) { console.error(`link-anchors: ${from} does not exist`); process.exit(2) }

function isReparse(p) {
  try { const st = fs.lstatSync(p); return st.isSymbolicLink() || (typeof st.isSymbolicLink === 'function' && st.isSymbolicLink()) } catch { return false }
}

function linkOrCopy(target, linkPath, { copy, force }) {
  const exists = fs.existsSync(linkPath) || isReparse(linkPath)
  if (exists && !force) return { path: linkPath, action: 'kept (already present)' }
  if (exists) fs.renameSync(linkPath, `${linkPath}.replaced-${new Date().toISOString().replace(/[-:]/gu, '').replace(/\..+$/u, 'Z')}`)
  if (copy) {
    fs.mkdirSync(linkPath, { recursive: true })
    const r = process.platform === 'win32'
      ? spawnSync('robocopy', [target, linkPath, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/R:1', '/W:1'], { encoding: 'utf8' })
      : spawnSync('cp', ['-a', target + '/.', linkPath], { encoding: 'utf8' })
    const ok = process.platform === 'win32' ? (r.status !== null && r.status < 8) : r.status === 0
    if (!ok) throw new Error(`copy failed for ${linkPath} (exit ${r.status})`)
    return { path: linkPath, action: 'copied' }
  }
  if (process.platform === 'win32') {
    const r = spawnSync('cmd', ['/c', 'mklink', '/J', linkPath, target], { encoding: 'utf8' })
    if (r.status !== 0) throw new Error(`mklink /J failed for ${linkPath}: ${(r.stderr || r.stdout || '').trim()}`)
    return { path: linkPath, action: 'junction' }
  }
  fs.symlinkSync(target, linkPath, 'dir')
  return { path: linkPath, action: 'symlink' }
}

const copy = has('copy')
const force = has('force')
const rows = []

const sharedSrc = path.join(from, 'profiles', 'node_modules')
const sharedDst = path.join(staged, 'profiles', 'node_modules')
if (fs.existsSync(sharedSrc)) {
  fs.mkdirSync(path.dirname(sharedDst), { recursive: true })
  rows.push(linkOrCopy(sharedSrc, sharedDst, { copy, force }))
} else {
  rows.push({ path: sharedDst, action: 'SKIPPED — the source home has no profiles/node_modules' })
}

const profilesDir = path.join(from, 'profiles')
if (fs.existsSync(profilesDir)) {
  for (const name of fs.readdirSync(profilesDir)) {
    const src = path.join(profilesDir, name, 'node_modules')
    if (!fs.existsSync(src)) continue
    const dst = path.join(staged, 'profiles', name, 'node_modules')
    fs.mkdirSync(path.dirname(dst), { recursive: true })
    rows.push(linkOrCopy(src, dst, { copy, force }))
  }
}

for (const r of rows) console.log(`  ${r.action.padEnd(24)} ${r.path}`)
console.log(`link-anchors: ${rows.filter((r) => !/SKIPPED/u.test(r.action)).length} anchor(s) present in ${staged}`)
