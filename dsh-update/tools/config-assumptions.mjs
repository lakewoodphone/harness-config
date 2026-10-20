// config-assumptions.mjs — the class of breakage that no gate in this pipeline could see, until 2026-10-19.
//
// WHAT HAPPENED, measurably, and it took the owner's machine down twice in twenty minutes.
//
// 1. `webRuntime` -> `webStartup`. Our web patch restated the `connection` row's config with
//    `trustedHosts: !!js ctx.webRuntime.trustedHosts`. 0.2.1's own row injects `[webStartup]`; 0.2.0's
//    injected `[webRuntime]` (both read from `--dump-default-config`, 2026-10-19). On 0.2.1 the loader threw
//    `cannot get property "webRuntime" without inject`, `dsh-client-connection` (a REQUIRED plugin) failed to
//    activate, and the client UI showed twenty entries "pending (waiting for service: remoteAccess)".
//    `patch-effect` said SAFE and `verify` said G2 fine: they compare our patch's config VALUES, and a value
//    that is a `!!js` expression is compared as source text against our own intent, never evaluated against
//    the candidate's injection surface.
//
// 2. `{{cwd}}`. Our presets' persona suffix carried `{{cwd}}`. 0.2.1 registers only `provider` and `model` as
//    prompt variables, so every turn died with `unknown prompt variable "{{cwd}}" in section
//    "deployment:persona-suffix"`. Nothing static looked at prompt tokens at all.
//
// This tool checks both assumptions against a specific candidate install, statically and quickly:
//   A. every `ctx.<name>` our patch expressions reference must be in that row's `inject` list in the
//      candidate's own default tree;
//   B. every `{{token}}` in our patch/preset text must be one the candidate registers as a prompt variable.
//
// It is a REPORT, not a gate (exit 1 on a finding so a caller can gate on it). Wire it into `preflight` when
// someone has the appetite to change the gated path; until then it is the step DELIVERY.md §2 says to run.
//
//   node dsh-update/tools/config-assumptions.mjs --engine <root> [--home <configHome>] [--json]
//
// Exit: 0 no findings · 1 findings (each printed with file:line) · 2 usage/missing input.

import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { spawnSync } from 'node:child_process'

const ARGV = process.argv.slice(2)
const flag = (n, d = null) => { const i = ARGV.indexOf(`--${n}`); if (i === -1) return d; const v = ARGV[i + 1]; return v && !v.startsWith('--') ? v : true }
const has = (n) => ARGV.includes(`--${n}`)

// The prompt variables 0.2.1 registers, measured from its own failure message on 2026-10-19. Anything else a
// config names is either a variable this line does not have, or a token that will fail a turn.
// THE SET IS AN ASSUMPTION OF ITS OWN, so it is keyed by the version it was MEASURED on and the tool
// refuses to judge a version it has no row for. The first version of this file carried one set for every
// engine, which is the same class of mistake it exists to catch: "provider, model" was read off a 0.2.1
// failure message and would have been applied to 0.3 silently. `MEASURED` says how each row was obtained;
// update it only from a real reading (the engine's own `unknown prompt variable ... registered variables:`
// error names the set, which is how 0.2.1 was measured).
const PROMPT_VARS_BY_VERSION = new Map([
  ['0.2.0-rc.2', new Set(['provider', 'model'])],
  ['0.2.1-rc.2', new Set(['provider', 'model'])],
])
const promptVarSetFor = (v) => {
  if (PROMPT_VARS_BY_VERSION.has(v)) return PROMPT_VARS_BY_VERSION.get(v)
  const series = [...PROMPT_VARS_BY_VERSION.keys()].find((k) => v.startsWith(k.split('-')[0] + '.'))
  return series ? PROMPT_VARS_BY_VERSION.get(series) : null
}

const engineRoot = String(flag('engine') || path.join(os.homedir(), '.dsh', 'engine'))
const home = String(flag('home') || process.env.DSH_HOME || path.join(os.homedir(), '.dsh'))
const bin = path.join(engineRoot, 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js')
if (!fs.existsSync(bin)) { console.error(`config-assumptions: no engine at ${bin}`); process.exit(2) }
if (!fs.existsSync(home)) { console.error(`config-assumptions: no config home at ${home}`); process.exit(2) }

const version = (() => {
  const r = spawnSync(process.execPath, [bin, '--version'], { encoding: 'utf8', timeout: 120000 })
  return `${r.stdout || ''}`.trim().split('\n').pop() || 'unknown'
})()

const PROMPT_VARS = promptVarSetFor(version)
if (!PROMPT_VARS) {
  console.error(`config-assumptions: no MEASURED prompt-variable set for engine ${version}. Applying another version's set would be the same class of assumption this tool exists to catch. Measure it -- one turn that names an unknown variable prints "registered variables: ..." -- and add a row to PROMPT_VARS_BY_VERSION.`)
  process.exit(3)
}

// ── the candidate's own default tree: every row, its package and its inject list ──────────────────────
const dump = spawnSync(process.execPath, [bin, '--profile', 'web', '--dump-default-config'], {
  env: { ...process.env, DSH_HOME: home }, encoding: 'utf8', timeout: 180000, maxBuffer: 64 * 1024 * 1024,
})
if (dump.status !== 0) { console.error(`config-assumptions: --dump-default-config failed (exit ${dump.status}): ${(dump.stderr || '').slice(-300)}`); process.exit(2) }

// One state machine over the dump: a row starts at a column-0 `- id:`, its injection list is either inline
// (`inject: [a, b]`) or a column-4 block sequence. Anything at another indent closes the list.
const rows = new Map()
{
  const lines = `${dump.stdout || ''}`.split(/\r?\n/)
  let rid = null
  let inInject = false
  for (const line of lines) {
    const idm = /^-\s+id:\s*(.+?)\s*$/u.exec(line)
    if (idm) {
      rid = idm[1].replace(/^['"]|['"]$/gu, '')
      rows.set(rid, { id: rid, inject: [] })
      inInject = false
      continue
    }
    if (!rid) continue
    const inline = /^\s{2}inject:\s*\[(.*)\]\s*$/u.exec(line)
    if (inline) {
      for (const part of inline[1].split(',')) {
        const name = part.trim().replace(/^['"]|['"]$/gu, '')
        if (name) rows.get(rid).inject.push(name)
      }
      inInject = false
      continue
    }
    if (/^\s{2}inject:\s*$/u.test(line)) { inInject = true; continue }
    if (/^\s{2}\S/u.test(line) || /^-/u.test(line)) { inInject = false; continue }
    if (inInject) {
      const m = /^\s{4}-\s+([A-Za-z_][\w.-]*)\s*$/u.exec(line)
      if (m) rows.get(rid).inject.push(m[1])
    }
  }
}
// ── the files that carry OUR assumptions ─────────────────────────────────────────────────────────────
const files = []
const pushIf = (p) => { if (fs.existsSync(p) && fs.statSync(p).isFile()) files.push(p) }
pushIf(path.join(home, 'profiles', 'web', 'cordis.patch.yml'))
pushIf(path.join(home, 'profiles', 'mesh', 'cordis.patch.yml'))
pushIf(path.join(home, 'profiles', 'headless', 'cordis.patch.yml'))
const presetsDir = path.join(home, '.agent-presets')
if (fs.existsSync(presetsDir)) for (const d of fs.readdirSync(presetsDir)) pushIf(path.join(presetsDir, d, 'agent.cordis.yml'))

const findings = []
const stats = { files: files.length, ctxRefs: 0, promptTokens: 0, rowsInCandidate: rows.size }

for (const f of files) {
  const text = fs.readFileSync(f, 'utf8')
  const lines = text.split(/\r?\n/)
  let currentRow = null
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()
    if (trimmed.startsWith('#')) continue
    const idm = /(?:^|[\s{,])id:\s*['"]?([A-Za-z0-9_.:-]+)['"]?/u.exec(line)
    if (idm && !/config:/u.test(line)) currentRow = idm[1]

    // A — ctx.<service> references inside our expressions
    for (const m of line.matchAll(/ctx\.([A-Za-z_][\w]*)/gu)) {
      stats.ctxRefs += 1
      const svc = m[1]
      if (!currentRow) continue
      const row = rows.get(currentRow)
      if (!row) continue // a row that does not exist in the candidate is patch-effect's job, not this tool's
      if (!row.inject.includes(svc)) {
        findings.push({
          kind: 'inject', file: f, line: i + 1, row: currentRow, ref: `ctx.${svc}`,
          why: `row "${currentRow}" does not inject "${svc}" in ${version}; the loader throws "cannot get property \\"${svc}\\" without inject" and the plugin fails to activate`,
          injects: row.inject,
        })
      }
    }

    // B — prompt variable tokens
    for (const m of line.matchAll(/\{\{\s*([A-Za-z_][\w.-]*)\s*\}\}/gu)) {
      stats.promptTokens += 1
      const tok = m[1]
      if (!PROMPT_VARS.has(tok)) {
        findings.push({
          kind: 'prompt-var', file: f, line: i + 1, row: currentRow, ref: `{{${tok}}}`,
          why: `${version} registers only ${[...PROMPT_VARS].join(', ')} as prompt variables; a turn that assembles this section fails with "unknown prompt variable"`,
          injects: null,
        })
      }
    }
  }
}

if (has('json')) {
  console.log(JSON.stringify({ engine: engineRoot, version, home, stats, findings }, null, 2))
} else {
  console.log(`config-assumptions  (engine ${version} at ${engineRoot}; config ${home})`)
  console.log(`  ${stats.files} file(s), ${stats.ctxRefs} ctx.<service> reference(s), ${stats.promptTokens} prompt token(s), ${stats.rowsInCandidate} candidate row(s)`)
  if (!findings.length) {
    console.log('  PASS  every referenced service is injected by its row and every prompt token is one this line registers')
  } else {
    for (const f of findings) {
      console.log(`  FAIL  ${path.basename(f.file)}:${f.line}  row "${f.row}"  ${f.ref}`)
      console.log(`        ${f.why}`)
      if (f.injects) console.log(`        the row injects: ${f.injects.length ? f.injects.join(', ') : '(nothing)'}`)
    }
  }
}
process.exit(findings.length ? 1 : 0)
