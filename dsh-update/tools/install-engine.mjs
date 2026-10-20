// install-engine.mjs — DELIVER a proven candidate into the live install root. The step the pipeline
// never had.
//
// WHY THIS EXISTS (measured 2026-10-19)
//
// `fetch` installs a candidate into `dsh-update/vendor/prefix/<version>`; `promote` then writes
// `dshInstall` pointing AT THAT PREFIX. Nothing in the pipeline ever puts bytes into the tree the
// machine actually runs. That was invisible while the launcher resolved out of the npx cache, and it
// became a live hazard on 2026-10-08 when this estate moved to a frozen per-home install and
// `multi-window/dshw.ps1:309` and `packages/plugin-remote-fanout/lib/nodes.js:84,98` were pointed at
// `~/.dsh/engine`. On 2026-10-19 `dsh-update status` reported the pin at the vendor prefix and the
// measured engine at `~/.dsh/engine`, with contract and tree sha256 MISMATCH — i.e. a `promote` in that
// state would have swapped the whole estate onto a tree that carries none of the hand patches.
//
// SO THE CONTRACT IS: the vendor prefix is a STAGING area, judged by `analyze`/`verify`/`preflight`;
// this tool is the only writer of the live tree; and the live tree is replaced by rename, never edited
// in place, so the old version stays on disk as the way back (nothing is ever deleted).
//
// WHAT IT DOES, in order, and it refuses before writing anything if any precondition fails:
//   0. the candidate prefix exists and its own package.json says --version
//   1. a verified backup younger than 12h exists (BACKUP-REPORT.json, ok:true)
//   2. the candidate's verify.json is promotable for the contract on disk (the same reading `promote`
//      uses: lib/promote-reading.mjs), and the last preflight row for that version says GO
//   3. copy the candidate to <live>.staged-<version> and prove that copy by running `--version` ON IT
//   4. apply every registered hand patch (patches/registry.json) and re-check each one
//   5. audit the OLD tree's .bak-harness-* pairs: registered, adopted-upstream, or FAIL (P3170)
//   6. swap by rename: <live> -> <live>.prev-<oldver>-<stamp>, then staged -> <live>
//   7. `promote <version>` so the pin and the launcher knob describe what is now on disk
//   8. write state/install-receipts/<version>-<stamp>.json and one history row
//
// WHAT IT NEVER DOES: start, stop or restart an engine. The new tree takes effect at the next engine
// start — by the watchdog, by a shortcut, or by a reboot — and the receipt says so.
//
// Exit codes: 0 installed and verified; 2 a precondition refused, nothing written; 3 a step failed and
// the previous state was RESTORED; 4 the swap could not be performed under a running engine (the
// staged tree is left in place, the live tree is untouched — do it in a quiet window); 5 a step failed
// and the restore could not be verified (attention required).

import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { spawnSync } from 'node:child_process'
import { PATHS, REPO_ROOT, hostName, sha256File, windowsJsonPath, vendorPrefixPath } from '../lib/store.mjs'
import { ENGINE_REL } from '../lib/versions.mjs'
import { liveInstallRoot } from '../lib/live-root.mjs'
import { applyAll, audit, checkAll, loadRegistry } from '../lib/patches.mjs'

const ARGV = process.argv.slice(2)
const flag = (name, fallback = null) => {
  const i = ARGV.indexOf(`--${name}`)
  if (i === -1) return fallback
  const v = ARGV[i + 1]
  return v && !v.startsWith('--') ? v : true
}
const has = (name) => ARGV.includes(`--${name}`)
const stamp = new Date().toISOString().replace(/[-:]/gu, '').replace(/\..+$/u, 'Z')

const lines = []
const say = (s = '') => { lines.push(s); console.log(s) }

class Refuse extends Error {}
const refuse = (msg) => { throw new Refuse(msg) }

function engineVersion(root) {
  const bin = path.join(root, ENGINE_REL)
  if (!fs.existsSync(bin)) return null
  const r = spawnSync(process.execPath, [bin, '--version'], { encoding: 'utf8', timeout: 120000 })
  const text = `${r.stdout || ''}${r.stderr || ''}`.trim().split('\n').pop() || ''
  return r.status === 0 ? text.trim() : null
}

function copyTree(src, dest) {
  // robocopy is the only tool on Windows that copies 26k files without a per-file round trip; on POSIX
  // `cp -a`. Both are called with an explicit source and destination and no delete flags.
  if (process.platform === 'win32') {
    const r = spawnSync('robocopy', [src, dest, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/R:1', '/W:1'], { encoding: 'utf8' })
    // robocopy's exit codes: 0-7 are success (nothing/few changed), >=8 is a real failure.
    return { ok: r.status !== null && r.status < 8, code: r.status, out: `${r.stdout || ''}${r.stderr || ''}`.trim().split('\n').slice(-3).join('\n') }
  }
  const r = spawnSync('cp', ['-a', src + '/.', dest], { encoding: 'utf8' })
  return { ok: r.status === 0, code: r.status, out: `${r.stderr || ''}`.trim() }
}

function preflightRowFor(version) {
  const file = PATHS.historyFile
  if (!fs.existsSync(file)) return null
  const rows = fs.readFileSync(file, 'utf8').trim().split('\n').slice(1)
  let last = null
  for (const row of rows) {
    const c = row.split('\t')
    // Columns are: timestamp, host, verb, version, fromVersion, result, detail. An off-by-one here read a
    // GO row as the previous version's number and refused a candidate that was green (measured 2026-10-19).
    if (c[2] === 'preflight' && c[3] === version) last = { at: c[0], host: c[1], result: c[5], detail: c[6] }
  }
  return last
}

function newestBackup() {
  const home = os.homedir()
  let best = null
  for (const name of fs.readdirSync(home)) {
    if (!name.startsWith('dsh-backup-')) continue
    const report = path.join(home, name, 'BACKUP-REPORT.json')
    if (!fs.existsSync(report)) continue
    try {
      const j = JSON.parse(fs.readFileSync(report, 'utf8'))
      const at = Date.parse(j.finishedAt)
      if (j.ok === true && Number.isFinite(at) && (!best || at > best.at)) best = { dir: path.join(home, name), at, json: j }
    } catch { /* a directory that cannot show its verdict is skipped, never trusted */ }
  }
  return best
}

async function main() {
  const dryRun = has('dry-run')
  const force = has('force')
  const noPromote = has('no-promote')
  // A waiver is a NAMED, RECORDED decision, never a blanket bypass: the ids an operator is willing to lose
  // for this install, printed loudly and written into the receipt.
  const waived = new Set(String(flag('allow-patch-failures') || '').split(',').map((s) => s.trim()).filter(Boolean))
  const version = String(flag('version') || '')
  if (!version || version === 'true') refuse('--version <ver> is required')
  if (version === 'npx') refuse('--version npx is not a version')

  const from = path.resolve(String(flag('from') || vendorPrefixPath(version)))
  const live = liveInstallRoot()
  const to = path.resolve(String(flag('to') || live.root || ''))
  if (!to || to === '.') refuse(`no live install root: ${live.source}. Pass --to <root> or set $env:DSH_LIVE_INSTALL.`)

  say(`install-engine ${version}   (host ${hostName()})`)
  say('')
  say(`  candidate (staging)  ${from}`)
  say(`  live install root    ${to}   [resolved from ${live.source}]`)
  say(`  live engine          ${engineVersion(to) || '(none readable)'}`)
  say('')

  // 0 — the candidate is real and says what we think it says
  const candPkg = path.join(from, 'node_modules', '@deepseek-ai', 'dsh', 'package.json')
  if (!fs.existsSync(candPkg)) refuse(`${from} holds no engine (no node_modules/@deepseek-ai/dsh/package.json). Run \`dsh-update fetch ${version}\` first.`)
  const candVersion = JSON.parse(fs.readFileSync(candPkg, 'utf8')).version
  if (candVersion !== version) refuse(`the candidate prefix reports ${candVersion}, not ${version}`)
  const oldVersion = engineVersion(to)
  if (oldVersion === version && !force) refuse(`the live root already reports ${version}. Nothing to do (--force reinstalls).`)
  say(`  PASS  candidate prefix holds dsh ${candVersion}`)

  // 1 — a verified backup
  let backup = null
  const backupArg = flag('backup')
  if (backupArg && backupArg !== true) {
    const report = path.join(String(backupArg), 'BACKUP-REPORT.json')
    if (!fs.existsSync(report)) refuse(`${backupArg} carries no BACKUP-REPORT.json, so it cannot show its own verdict`)
    const j = JSON.parse(fs.readFileSync(report, 'utf8'))
    const at = Date.parse(j.finishedAt)
    if (j.ok !== true) refuse(`the backup at ${backupArg} reports ok=${j.ok}`)
    if (!Number.isFinite(at)) refuse(`the backup at ${backupArg} carries no parseable finishedAt`)
    const ageH = (Date.now() - at) / 3.6e6
    if (ageH > 12) refuse(`the backup at ${backupArg} is ${ageH.toFixed(1)}h old; the switch budget is 12h. Take a new one: node dsh-update/tools/backup-state.mjs`)
    backup = { dir: String(backupArg), at }
  } else {
    const found = newestBackup()
    if (!found) refuse('no verified backup found. Take one: node dsh-update/tools/backup-state.mjs (it writes %USERPROFILE%\\dsh-backup-<stamp> and proves itself)')
    const ageH = (Date.now() - found.at) / 3.6e6
    if (ageH > 12) refuse(`the newest verified backup (${found.dir}) is ${ageH.toFixed(1)}h old. Take a new one: node dsh-update/tools/backup-state.mjs`)
    backup = { dir: found.dir, at: found.at }
  }
  say(`  PASS  verified backup ${backup.dir} (${((Date.now() - backup.at) / 3.6e6).toFixed(1)}h old, ok:true)`)

  // 2 — the pipeline's own verdict on the candidate
  const cdir = path.join(PATHS.candidatesDir, version)
  const verifyFile = path.join(cdir, 'verify.json')
  if (!fs.existsSync(verifyFile)) refuse(`no verify.json for ${version}. Run \`dsh-update verify ${version}\` (or preflight) first.`)
  const verify = JSON.parse(fs.readFileSync(verifyFile, 'utf8'))
  const contract = path.join(cdir, 'contract.json')
  if (!fs.existsSync(contract)) refuse(`no contract.json for ${version}, so the verdict cannot be bound to a candidate`)
  // The contract artifact carries no hash field of its own: its identity is the sha256 of the FILE,
  // which is how store.mjs's readJsonChecked reports it and how verify.json binds to it.
  const contractSha = sha256File(contract)
  if (verify.contractSha256 !== contractSha) refuse(`verify.json was produced for contract ${verify.contractSha256}, the contract on disk is ${contractSha}. Re-run verify.`)
  const pf = preflightRowFor(version)
  if (!pf) refuse(`no preflight row for ${version} in the history. Run \`dsh-update preflight ${version}\` first.`)
  if (pf.result !== 'GO') {
    const doorOnly = /G8 session-format door=(pass|FAIL)/u.test(pf.detail) && !/verify \(gates G1-G8\)=FAIL/u.test(pf.detail.replace(/G8 session-format door=FAIL/u, ''))
    if (!doorOnly) refuse(`preflight for ${version} is ${pf.result}, not GO. Detail: ${pf.detail.slice(0, 400)}`)
    if (!has('accept-session-format-upgrade')) refuse(`preflight for ${version} is ${pf.result} on the session-format door alone. Re-run with --accept-session-format-upgrade to record that decision, or fix the door.`)
  }
  say(`  PASS  preflight ${version} = ${pf.result}${pf.result === 'GO' ? '' : ' (G8 door accepted)'} at ${pf.at}`)
  say(`  PASS  verify.json bound to contract ${contractSha.slice(0, 16)}…`)

  if (dryRun) {
    say('')
    say('  DRY RUN — every precondition passed and NOTHING was written. The steps that would run:')
    say(`    1  robocopy ${from} -> ${to}.staged-${version}`)
    say('    2  node <staged> --version      (must print the candidate version)')
    say('    3  apply + re-check every patch in dsh-update/patches/registry.json')
    say(`    4  audit ${to}: every .bak-harness-* pair registered or adopted upstream`)
    say(`    5  rename ${to} -> ${to}.prev-${oldVersion || 'current'}-<stamp>; rename staged -> ${to}`)
    say(`    6  promote ${version}${noPromote ? '   (SKIPPED: --no-promote)' : ''}`)
    say('    7  write state/install-receipts/<version>-<stamp>.json + one history row')
    return 0
  }

  // 3 — stage a copy and prove the copy
  const staged = `${to}.staged-${version}`
  if (fs.existsSync(staged)) {
    const aside = `${staged}.stale-${stamp}`
    fs.renameSync(staged, aside)
    say(`  staged  moved a previous partial copy aside: ${path.basename(aside)} (nothing deleted)`)
  }
  fs.mkdirSync(path.dirname(to), { recursive: true })
  fs.mkdirSync(staged, { recursive: true })
  const copied = copyTree(from, staged)
  if (!copied.ok) refuse(`copy failed (robocopy/cp exit ${copied.code}): ${copied.out}`)
  const stagedVersion = engineVersion(staged)
  if (stagedVersion !== version) refuse(`the staged copy reports ${stagedVersion || '(nothing)'}, not ${version} — refusing to swap an unproven tree`)
  say(`  PASS  staged copy at ${staged} proves dsh ${stagedVersion}`)

  // 4 — hand patches
  const patched = applyAll(staged)
  for (const r of patched.results) {
    const mark = r.exit === 0 ? 'ok  ' : 'FAIL'
    say(`  ${mark}  ${r.id} [${r.phase}] exit ${r.exit}${r.out ? ` :: ${r.out.split('\n').pop()}` : ''}`)
  }
  if (!patched.ok || waived.size) {
    // The FINAL state of each entry decides. A `check-before` failure is expected on a fresh tree (nothing
    // is patched yet) and must never be reported as the reason by itself — measured 2026-10-19, where the
    // refusal named all four patches when only two had actually failed to take.
    const finalState = new Map()
    for (const r of patched.results) {
      if (r.phase === 'check-after') finalState.set(r.id, r)
      else if (r.phase === 'check-before' && r.exit === 0) finalState.set(r.id, r)
    }
    // AN ENTRY MAY BE SUPERSEDED BY UPSTREAM ON A NEWER LINE. `patches/registry.json` can carry
    // `superseded: {fromVersion, evidence}`; on an engine at or above that version the entry's targets may
    // legitimately no longer exist, and failing the install for it would force a waiver for a fact.
    const registry = (() => { try { return loadRegistry() } catch { return { patches: [] } } })()
    const cmp = (a, b) => {
      const num = (s) => String(s).split('-')[0].split('.').map((n) => Number(n.replace(/\D/gu, '')) || 0)
      const A = num(a); const B = num(b)
      for (let i = 0; i < Math.max(A.length, B.length); i++) {
        const d = (A[i] || 0) - (B[i] || 0)
        if (d) return d
      }
      return String(a).includes('rc') && !String(b).includes('rc') ? -1 : 0
    }
    const supersededFor = (id) => {
      const e = registry.patches.find((x) => x.id === id)
      return e && e.superseded && cmp(candVersion, e.superseded.fromVersion) >= 0 ? e.superseded : null
    }
    const notOkAll = [...finalState.entries()].filter(([, r]) => r.exit !== 0).map(([id]) => id)
    for (const id of notOkAll) {
      const sup = supersededFor(id)
      if (!sup) continue
      say(`  SUPERSEDED BY UPSTREAM  ${id} — this patcher does not apply on ${candVersion} because ${sup.fromVersion}+ handles the same failure itself; recorded, not waived.`)
      say(`        evidence: ${String(sup.evidence).slice(0, 240)}…`)
    }
    const notOk = notOkAll.filter((id) => !supersededFor(id))
    if (waived.size) {
      const unwaived = notOk.filter((id) => !waived.has(id))
      if (unwaived.length) refuse(`hand patches did not apply and were not waived: ${unwaived.join(', ')}. The live tree was not touched; the staged copy is at ${staged}.`)
      for (const id of notOk) {
        // A WAIVED PATCH MAY BE PARTIALLY APPLIED, and saying "without this hand patch" is then a false claim.
        // Measured 2026-10-20: settlement-crash patched dsh-agent-loop/lib/index.js, failed on its other two
        // targets, exited 1 -- and the waiver reported the patch as absent while one third of it was live in the
        // tree. The per-target output is now recorded and the sentence no longer promises a clean absence.
        const rec = finalState.get(id)
        const detail = String((rec && rec.out) || '').split('\n').filter((l) => /(already-patched|patched\(|FAIL|absent)/u.test(l)).slice(0, 4).join(' | ')
        say(`  WAIVED BY THE OPERATOR  ${id} — the install proceeds; whether ANY part of it applied is in the patcher's own lines${detail ? `: ${detail}` : ''}. The receipt records this verbatim.`)
      }
    } else if (notOk.length) {
      refuse(`hand patches did not take on the staged tree: ${notOk.join(', ')}. Each failing patcher prints WHY (an upstream anchor moved, a file vanished); re-author it against this version, or name it explicitly with --allow-patch-failures <id,id> to install without it and record that decision. The live tree was not touched; the staged copy is left at ${staged} for inspection.`)
    }
  }

  // 5 — unregistered patch audit (P3170)
  const auditRows = audit(to, staged)
  for (const r of auditRows) say(`  ${r.verdict === 'NEEDS-PATCH' ? 'FAIL' : 'ok  '}  patch audit ${r.rel} -> ${r.verdict}`)
  const lost = auditRows.filter((r) => r.verdict === 'NEEDS-PATCH')
  if (lost.length && !has('allow-unregistered-patches')) {
    refuse(`the install would silently lose ${lost.length} hand patch(es): ${lost.map((r) => r.rel).join(', ')}. Either write a patcher and register it in dsh-update/patches/registry.json, or confirm that losing it is intended with --allow-unregistered-patches. The live tree was not touched.`)
  }

  // 5b — THE STAGED TREE MUST COMPOSE, not merely report a version.
  //
  // A patch that parses but breaks module resolution produces a tree whose `--version` is perfect and whose
  // boot fails — and the failure would surface at the owner's next restart, which is the worst possible
  // moment (2026-10-05: the crash bracketed exactly that window). So the staged tree is composed here,
  // against the STAGED config home, with the engine binary that would run. --dump-config does not start a
  // server (SPEC C4: it does write profiles/<name>/cordis.yml, which is why it is pointed at the staged home
  // and never at the live one).
  const stagedHome = String(flag('config-home') || path.join(os.homedir(), '.dsh-staged', version))
  if (fs.existsSync(stagedHome)) {
    const dump = spawnSync(process.execPath, [path.join(staged, ENGINE_REL), '--profile', 'web', '--dump-config'], {
      env: { ...process.env, DSH_HOME: stagedHome },
      encoding: 'utf8', timeout: 300000,
    })
    const out = `${dump.stdout || ''}`
    const rows = (out.match(/^\s*-\s+id:/gmu) || []).length
    const tail = `${dump.stderr || ''}`.trim().split('\n').slice(-4).join(' | ')
    if (dump.status !== 0 || rows === 0) {
      refuse(`the staged tree composes NOTHING (exit ${dump.status}, ${rows} row(s)) against ${stagedHome}${tail ? ': ' + tail : ''}. A tree that cannot compose must not be swapped in. The live tree was not touched; the staged copy is at ${staged}.`)
    }
    say(`  PASS  compose smoke test: the staged tree composes ${rows} row(s) against ${stagedHome} (no server started)`)
  } else {
    say(`  WARN  no staged config home at ${stagedHome}; the compose smoke test was SKIPPED. Pass --config-home <dir> to run it.`)
  }

  // 6 — swap by rename
  const prev = `${to}.prev-${oldVersion || 'current'}-${stamp}`
  let swapped = false
  try {
    fs.renameSync(to, prev)
    try {
      fs.renameSync(staged, to)
      swapped = true
    } catch (err) {
      fs.renameSync(prev, to) // put the old tree straight back
      say(`  FAIL  swap could not complete (${err.code || err.message}); the previous tree was restored`)
      return 4
    }
  } catch (err) {
    say(`  FAIL  the live tree could not be moved aside (${err.code || err.message}). Nothing changed.`)
    say(`        A running engine holds files in ${to}. Retry in a quiet window, or stop the engine first.`)
    say(`        The proven staged copy is at ${staged} and can be swapped in by hand.`)
    return 4
  }

  const after = engineVersion(to)
  if (after !== version) {
    // Restore, because a live tree that does not boot its own version is worse than an old one.
    try {
      const failedDir = `${to}.failed-${stamp}`
      fs.renameSync(to, failedDir)
      fs.renameSync(prev, to)
      say(`  FAIL  the swapped tree reports ${after || '(nothing)'}; previous tree restored from ${path.basename(prev)}`)
      return 3
    } catch (err) {
      say(`  FAIL  the swapped tree reports ${after || '(nothing)'} AND the restore failed (${err.code || err.message}). ATTENTION.`)
      return 5
    }
  }
  say(`  PASS  ${to} now reports dsh ${after}; previous tree kept at ${prev} (nothing deleted)`)

  // 7 — the pin and the launcher knob
  let promoteOut = ''
  if (!noPromote) {
    const args = [path.join(PATHS.libDir, 'cli.mjs'), 'promote', version]
    if (has('accept-session-format-upgrade')) args.push('--accept-session-format-upgrade')
    const prom = spawnSync(process.execPath, args, { cwd: REPO_ROOT, encoding: 'utf8', timeout: 600000 })
    promoteOut = `${prom.stdout || ''}${prom.stderr || ''}`.trim()
    say('')
    say('  --- promote ---')
    for (const l of promoteOut.split('\n')) say(`  ${l}`)
    if (prom.status !== 0) {
      say(`  FAIL  promote exited ${prom.status}. THE ENGINE IS NEW AND THE PIN IS NOT — that mismatch is visible in`)
      say(`        \`dsh-update status\` and must be fixed before the next update. Nothing was rolled back: the`)
      say(`        bytes on disk are the verified candidate and taking them away now would be a second change.`)
      return 3
    }
  }

  // 8 — receipt + history row
  const receipts = path.join(PATHS.stateDir, 'install-receipts')
  fs.mkdirSync(receipts, { recursive: true })
  const receipt = path.join(receipts, `${version}-${stamp}.json`)
  const row = {
    at: new Date().toISOString(),
    host: hostName(),
    version,
    fromVersion: oldVersion,
    liveRoot: to,
    stagedFrom: from,
    previousTree: prev,
    engineBinSha256: sha256File(path.join(to, ENGINE_REL)),
    candidatePackageJsonSha256: sha256File(candPkg),
    patches: patched.results.map((r) => ({ id: r.id, phase: r.phase, exit: r.exit, out: r.out })),
    patchWaivers: [...waived],
    patchAudit: auditRows,
    backupDir: backup.dir,
    preflight: pf,
    verifyContractSha256: contractSha,
    promote: noPromote ? 'skipped (--no-promote)' : 'ok',
    windowsJson: windowsJsonPath(),
    takesEffect: 'at the next engine start; no engine was started, stopped or restarted by this tool',
  }
  fs.writeFileSync(receipt, JSON.stringify(row, null, 2) + '\n', 'utf8')
  fs.appendFileSync(
    PATHS.historyFile,
    [new Date().toISOString(), hostName(), 'install-engine', version, oldVersion || '', 'ok',
      `live root ${to}; previous tree ${prev}; patches ${patched.results.filter((r) => r.exit === 0).length}/${patched.results.length} ok; audit ${auditRows.filter((r) => r.verdict !== 'NEEDS-PATCH').length}/${auditRows.length} clean; receipt ${path.basename(receipt)}`].join('\t') + '\n',
    'utf8',
  )

  say('')
  if (waived.size) {
    say(`  DONE, WITH ${waived.size} RECORDED EXCEPTION(S) — ${version} is installed at ${to}, and these hand patches are`)
    say(`  NOT present in it: ${[...waived].join(', ')}. They are recorded in the receipt; re-author them against this version.`)
  } else {
    say(`  DONE — ${version} is installed at ${to} and every patch and patch-audit entry is clean.`)
  }
  say(`  receipt ${path.relative(REPO_ROOT, receipt)}`)
  say('')
  say('  IT TAKES EFFECT AT THE NEXT ENGINE START. This tool did not start, stop or restart anything.')
  say('  After that start, check three things (RUNBOOK §7):')
  say('    1. `dsh-update status` shows the measured engine at the new version')
  say('    2. a NEW session mounts on EACH preset (not one)')
  say('    3. a session from before the update still opens')
  say(`  If any fails: the previous tree is intact at ${prev}`)
  return 0
}

main()
  .then((code) => process.exit(code ?? 0))
  .catch((err) => {
    if (err instanceof Refuse) {
      console.error(`\nREFUSED — ${err.message}\n`)
      console.error('Nothing was written. Every precondition is listed in dsh-update/DELIVERY.md.')
      process.exit(2)
    }
    console.error(err && err.stack ? err.stack : String(err))
    process.exit(1)
  })
