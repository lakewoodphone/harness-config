// patches.mjs — THE CHECKED-IN PATCH REGISTRY, AND THE ONE THING THAT WAS MISSING (P3170).
//
// P3170, filed 2026-10-13, is the class this closes: a fix living inside the engine's npm tree is
// invisible to `dsh-update` and is silently lost by the next engine install. `dsh-update` has always
// tracked patches to the *cordis composition* (SPEC.md B3/B4, G2/G6 check `patchedRowIds`) and never a
// patch to a *package file*. Measured on ZABZ-YOGA 2026-10-19, the live tree carries hand patches in at
// least these packages, each with its own `.bak-harness-*` sibling as evidence:
//
//   dsh-llm-deepseek/lib/index.js                     (MESHFIX: malformed tool input)
//   dsh-subagent/lib/index.js                         (MESHFIX: settlement crash)
//   dsh-web-frontend/dist/assets/vendor-*.js          (currency: single-dollar math off)
//   dsh-client-ui-workspace/lib/client.js             (blank-window isolation)
//   dsh-session-persistence-jsonl/lib/index.js        (v4 sibling preference; UNREGISTERED)
//   dsh-client-ui-primitives/lib/StateDot.module.css  (UNREGISTERED)
//
// Four of those six have a real patcher (three in `scripts/`, one in `multi-window/tools/`) and are in
// `patches/registry.json`. The other two do not, and this module's `audit()` makes that impossible to
// forget: it refuses to let an install claim success while the OLD tree carries a `.bak-harness-*` pair
// whose live file the NEW tree does not already match. Either the patch is registered, or upstream has
// adopted it byte-for-byte, or the install FAILS with the file named.
//
// Design rules, from the estate's own history:
//   * every entry runs its patcher in `--check` mode first, so an already-applied patch is a pass, not
//     a re-patch (the patchers are idempotent and say `already-patched`);
//   * a nonzero exit is never swallowed — a patch that cannot be applied fails the install;
//   * nothing here writes outside the tree it is given.

import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { REPO_ROOT } from './store.mjs'

const REGISTRY = path.join(REPO_ROOT, 'dsh-update', 'patches', 'registry.json')

export function loadRegistry() {
  const raw = fs.readFileSync(REGISTRY, 'utf8')
  const reg = JSON.parse(raw)
  if (!Array.isArray(reg.patches)) throw new Error(`${REGISTRY}: no patches array`)
  return reg
}

/** Resolve the `{root}` / `{runtime}` placeholders in an entry's argv for a given tree. */
function argvFor(entry, treeRoot, mode) {
  const runtime = path.join(treeRoot, 'node_modules', '@deepseek-ai')
  return [...entry[mode]].map((a) => a.split('{root}').join(treeRoot).split('{runtime}').join(runtime))
}

/**
 * Which executable does this entry actually mean, on THIS platform?
 *
 * MEASURED 2026-10-20 on `zabz-tech-linux`: every patcher exited `-1` and the install refused, because the registry
 * spells the interpreter `python` and that box has only `python3` — `spawnSync` returns status null on ENOENT, which
 * surfaced as an opaque -1. The same spelling works on the Windows machines (where `python` exists) and is wrong on
 * every Linux node. `node` is resolved to the interpreter running THIS process, so it is always the same Node that
 * runs the pipeline, on any host.
 */
function resolveExe(name) {
  if (name === 'node') return process.execPath
  if (name === 'python' || name === 'python3') {
    const candidates = process.platform === 'win32' ? ['python', 'python3'] : ['python3', 'python']
    for (const c of candidates) {
      const r = spawnSync(c, ['--version'], { encoding: 'utf8', timeout: 20000 })
      if (r.status === 0) return c
    }
    return candidates[0]
  }
  return name
}

function runOne(entry, treeRoot, mode) {
  const argv = argvFor(entry, treeRoot, mode)
  const exe = resolveExe(argv.shift())
  const r = spawnSync(exe, argv, { cwd: REPO_ROOT, encoding: 'utf8', timeout: 180000 })
  const out = `${r.stdout || ''}${r.stderr || ''}`.trim()
  // status is null when the process could not be spawned at all (ENOENT/EACCES). Say that, instead of "-1", which
  // sent a reader looking for a patcher bug rather than a missing interpreter.
  const code = r.status === null ? -1 : r.status
  const why = r.status === null ? ` [spawn failed: ${exe}: ${r.error?.code ?? r.error?.message ?? 'unknown'}]` : ''
  return { id: entry.id, mode, exit: code, out: `${out.split('\n').slice(-6).join('\n')}${why}`.trim() }
}

/** Does every registered patch report present in this tree? Read-only. */
export function checkAll(treeRoot, registry = loadRegistry()) {
  const results = []
  for (const entry of registry.patches) {
    if (entry.kind === 'informational') continue
    results.push(runOne(entry, treeRoot, 'check'))
  }
  return results
}

/**
 * Apply every registered patch to a tree that is NOT live yet, then re-check.
 * Returns { ok, results } — ok is true only when every `check` exits 0 after the apply.
 */
export function applyAll(treeRoot, registry = loadRegistry()) {
  const results = []
  for (const entry of registry.patches) {
    if (entry.kind === 'informational') continue
    const before = runOne(entry, treeRoot, 'check')
    results.push({ ...before, phase: 'check-before' })
    if (before.exit === 0) continue
    const applied = runOne(entry, treeRoot, 'apply')
    results.push({ ...applied, phase: 'apply' })
    const after = runOne(entry, treeRoot, 'check')
    results.push({ ...after, phase: 'check-after' })
  }
  const after = results.filter((r) => r.phase === 'check-after' || (r.phase === 'check-before' && r.exit === 0))
  const ok = after.every((r) => r.exit === 0)
  return { ok, results }
}

/**
 * Every `.bak-harness-*` sibling in the OLD tree is a hand patch somebody applied. For each one decide:
 *   registered      — a registry entry covers that file, so the apply above is the carry-forward
 *   upstream        — the new tree's file already equals the OLD PATCHED file byte for byte
 *   NEEDS-PATCH     — neither; the fix would be silently lost, which is P3170
 */
export function audit(oldRoot, newRoot, registry = loadRegistry()) {
  const covered = new Set(
    registry.patches.filter((e) => e.covers).flatMap((e) => e.covers.map((g) => g.toLowerCase())),
  )
  const findings = []
  const walk = (dir) => {
    let entries = []
    try { entries = fs.readdirSync(dir, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      const p = path.join(dir, e.name)
      if (e.isDirectory()) walk(p)
      else if (e.name.includes('.bak-harness')) findings.push(p)
    }
  }
  walk(path.join(oldRoot, 'node_modules'))
  const seen = new Set()
  const rows = []
  for (const bak of findings) {
    const live = bak.slice(0, bak.indexOf('.bak-harness'))
    const rel = path.relative(oldRoot, live)
    if (seen.has(rel.toLowerCase())) continue
    seen.add(rel.toLowerCase())
    const newFile = path.join(newRoot, rel)
    const coveredBy = [...covered].find((g) => rel.toLowerCase().includes(g))
    let verdict = 'NEEDS-PATCH'
    if (coveredBy) verdict = 'registered'
    else if (fs.existsSync(newFile) && fs.existsSync(live) &&
             fs.readFileSync(newFile).equals(fs.readFileSync(live))) verdict = 'upstream'
    rows.push({ rel, verdict, bak: path.basename(bak) })
  }
  return rows
}
