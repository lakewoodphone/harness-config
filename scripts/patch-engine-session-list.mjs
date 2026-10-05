#!/usr/bin/env node
/**
 * patch-engine-session-list.mjs — make the engine's session walk pooled instead of sequential.
 *
 * WHY (measured 2026-10-05 on ZABZ-YOGA)
 *   `POST /api/session/list` over 1064 sessions took 219223 ms in the proxy's own refresh log and
 *   641532 ms in a later one, while every other RPC answered in 14-330 ms. The same filesystem work
 *   done by `multi-window/tools/replicate-list-scan.mjs` with no engine is 6797 ms. The gap is not
 *   the disk: it is that the walk is three STRICTLY SEQUENTIAL await chains of ~1068 iterations
 *   each (`listGenerations`, `listArtifacts`, `checkRootEncoding`), i.e. ~7500-10000 awaited
 *   round-trips, and the engine's measured median event-loop lag is 73 ms (p95 1258 ms) because one
 *   loop is shared with 15 concurrent agent generations. 7000 x 73 ms = 511 s, which is exactly the
 *   observed range.
 *
 *   Pooling the per-directory work overlaps those waits. Order is preserved, the duplicate-id check
 *   and the encoding-mismatch check are preserved, and nothing is skipped: this is a pure
 *   efficiency change, with no capability removed and no data touched.
 *
 * USAGE
 *   node patch-engine-session-list.mjs --check     # patched? patchable? (exit 0 / 2 / 3)
 *   node patch-engine-session-list.mjs --apply     # backup, patch, syntax-check, write
 *   node patch-engine-session-list.mjs --restore   # restore the newest backup
 *
 *   Pool width: DSH_LIST_CONCURRENCY (default 32) is read at run time by the patched engine, so the
 *   width can be tuned without re-patching.
 *
 * NOTE: the running engine keeps the old code in memory. This takes effect at the next engine start.
 */
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { execFileSync } from 'node:child_process'

const MARKER = 'harness-patch:session-list-pool'
const TARGET = process.argv[2] && !process.argv[2].startsWith('--')
  ? process.argv[2]
  : path.join(os.homedir(), '.dsh', 'engine', 'node_modules', '@deepseek-ai',
      'dsh-session-persistence-jsonl', 'lib', 'index.js')

const mode = process.argv.includes('--apply') ? 'apply'
  : process.argv.includes('--restore') ? 'restore'
  : 'check'

if (!fs.existsSync(TARGET)) {
  console.error(`TARGET NOT FOUND: ${TARGET}`)
  process.exit(4)
}

/** Find one `async NAME(...) {` method and the line that closes it at the same indent. */
function locate(src, name) {
  const re = new RegExp('\\n([ \\t]*)async ' + name + '\\(([^)]*)\\) \\{')
  const m = re.exec(src)
  if (!m) return { ok: false, reason: `method ${name} not found` }
  const indent = m[1]
  const start = m.index + 1
  const bodyStart = m.index + m[0].length
  const cm = new RegExp('\\n' + indent + '\\}').exec(src.slice(bodyStart))
  if (!cm) return { ok: false, reason: `closing brace of ${name} not found` }
  const end = bodyStart + cm.index + cm[0].length
  return { ok: true, indent, start, end, old: src.slice(start, end) }
}

/** Each guard is a string that MUST appear in the method we are about to replace. */
const METHODS = [
  {
    name: 'listGenerations',
    guards: ['resolveGenerationInDirectory(dir, signal)', 'if (selected !== void 0) sources.push(selected)'],
    body: (i) => `${i}async listGenerations(signal) {
${i}\t/* ${MARKER}: pooled per-directory generation selection (was one sequential await chain) */
${i}\tconst sources = [];
${i}\tconst dirs = [];
${i}\tfor (const project of await this.listProjectDirs(signal)) {
${i}\t\tfor (const dir of await this.listSessionDirs(project, signal)) {
${i}\t\t\tsignal?.throwIfAborted();
${i}\t\t\tdirs.push(dir);
${i}\t\t}
${i}\t}
${i}\tsignal?.throwIfAborted();
${i}\tconst width = Math.min(Math.max(1, Number(process.env.DSH_LIST_CONCURRENCY || 32) | 0), dirs.length || 1);
${i}\tconst selectedPerDir = new Array(dirs.length);
${i}\tlet cursor = 0;
${i}\tconst worker = async () => {
${i}\t\tfor (;;) {
${i}\t\t\tconst index = cursor++;
${i}\t\t\tif (index >= dirs.length) return;
${i}\t\t\tsignal?.throwIfAborted();
${i}\t\t\tselectedPerDir[index] = await this.resolveGenerationInDirectory(dirs[index], signal);
${i}\t\t}
${i}\t};
${i}\tawait Promise.all(Array.from({ length: width }, () => worker()));
${i}\tsignal?.throwIfAborted();
${i}\tfor (const selected of selectedPerDir) if (selected !== void 0) sources.push(selected);
${i}\treturn sources;
${i}}`,
  },
  {
    name: 'listArtifacts',
    guards: ['readGenerationHeader(selected, void 0, signal)', 'duplicate JSONL session id'],
    body: (i) => `${i}async listArtifacts(signal) {
${i}\t/* ${MARKER}: pooled header reads (was one sequential await chain over every session) */
${i}\tsignal?.throwIfAborted();
${i}\tawait this.ensureRootEncoding();
${i}\tsignal?.throwIfAborted();
${i}\tconst selectedList = await this.listGenerations(signal);
${i}\tconst width = Math.min(Math.max(1, Number(process.env.DSH_LIST_CONCURRENCY || 32) | 0), selectedList.length || 1);
${i}\tconst read = new Array(selectedList.length);
${i}\tlet cursor = 0;
${i}\tconst worker = async () => {
${i}\t\tfor (;;) {
${i}\t\t\tconst index = cursor++;
${i}\t\t\tif (index >= selectedList.length) return;
${i}\t\t\tsignal?.throwIfAborted();
${i}\t\t\tconst selected = selectedList[index];
${i}\t\t\tlet header;
${i}\t\t\ttry {
${i}\t\t\t\theader = await this.readGenerationHeader(selected, void 0, signal);
${i}\t\t\t} catch (error) {
${i}\t\t\t\tif (error instanceof SessionFormatUnsupportedError || error instanceof SessionPersistenceCorruptionError) continue;
${i}\t\t\t\tthrow error;
${i}\t\t\t}
${i}\t\t\tread[index] = header === void 0 ? void 0 : { header, selected };
${i}\t\t}
${i}\t};
${i}\tawait Promise.all(Array.from({ length: width }, () => worker()));
${i}\tsignal?.throwIfAborted();
${i}\tconst artifacts = [];
${i}\tconst ids = /* @__PURE__ */ new Set();
${i}\tfor (const entry of read) {
${i}\t\tif (entry === void 0) continue;
${i}\t\tif (ids.has(entry.header.id)) throw new Error(\`duplicate JSONL session id "\${entry.header.id}" appears in multiple project directories\`);
${i}\t\tids.add(entry.header.id);
${i}\t\tartifacts.push({
${i}\t\t\theader: entry.header,
${i}\t\t\tpath: entry.selected.sourcePath,
${i}\t\t\tsourceVersion: entry.selected.sourceVersion
${i}\t\t});
${i}\t}
${i}\tsignal?.throwIfAborted();
${i}\treturn artifacts;
${i}}`,
  },
  {
    name: 'checkRootEncoding',
    guards: ['findOppositeGenerationInDirectory(dir)'],
    body: (i) => `${i}async checkRootEncoding() {
${i}\t/* ${MARKER}: pooled encoding check (was one sequential readdir per session directory) */
${i}\tconst dirs = [];
${i}\tfor (const project of await this.listProjectDirs()) for (const dir of await this.listSessionDirs(project)) dirs.push(dir);
${i}\tconst width = Math.min(Math.max(1, Number(process.env.DSH_LIST_CONCURRENCY || 32) | 0), dirs.length || 1);
${i}\tlet cursor = 0;
${i}\tconst worker = async () => {
${i}\t\tfor (;;) {
${i}\t\t\tconst index = cursor++;
${i}\t\t\tif (index >= dirs.length) return;
${i}\t\t\tconst incompatible = await this.findOppositeGenerationInDirectory(dirs[index]);
${i}\t\t\tif (incompatible !== void 0) throw this.encodingMismatch(incompatible);
${i}\t\t}
${i}\t};
${i}\tawait Promise.all(Array.from({ length: width }, () => worker()));
${i}}`,
  },
]

const src = fs.readFileSync(TARGET, 'utf8')
const alreadyPatched = src.includes(MARKER)

function build() {
  let out = src
  for (const method of METHODS) {
    const found = locate(out, method.name)
    if (!found.ok) return { ok: false, reason: found.reason }
    for (const guard of method.guards) {
      if (!found.old.includes(guard)) {
        return { ok: false, reason: `${method.name}: guard string not found — this engine version differs from the one the patch was written for (expected: ${guard})` }
      }
    }
    if (found.old.includes(MARKER)) continue // this method is already patched
    out = out.slice(0, found.start) + method.body(found.indent) + out.slice(found.end)
  }
  return { ok: true, text: out }
}

function syntaxCheck(file) {
  try {
    execFileSync(process.execPath, ['--check', file], { stdio: 'pipe' })
    return { ok: true }
  } catch (e) {
    return { ok: false, detail: String(e.stderr || e.message).slice(0, 600) }
  }
}

if (mode === 'check') {
  const unpatched = METHODS.filter((m) => { const f = locate(src, m.name); return f.ok && !f.old.includes(MARKER) }).map((m) => m.name)
  const missing = METHODS.filter((m) => !locate(src, m.name).ok).map((m) => m.name)
  console.log(`target    : ${TARGET}`)
  console.log(`bytes     : ${src.length}`)
  console.log(`marker    : ${alreadyPatched ? 'PRESENT (patched)' : 'absent'}`)
  console.log(`patchable : ${unpatched.length ? unpatched.join(', ') : '(none)'}`)
  console.log(`not found : ${missing.length ? missing.join(', ') : '(none)'}`)
  if (missing.length) { console.log('VERDICT   : UNPATCHABLE — engine version changed; re-derive the patch'); process.exit(3) }
  if (alreadyPatched && !unpatched.length) { console.log('VERDICT   : ALREADY PATCHED'); process.exit(2) }
  console.log('VERDICT   : READY TO PATCH')
  process.exit(0)
}

if (mode === 'restore') {
  const dir = path.dirname(TARGET)
  const base = path.basename(TARGET)
  const backups = fs.readdirSync(dir).filter((f) => f.startsWith(base + '.bak-harness-')).sort()
  if (!backups.length) { console.error('no backup found'); process.exit(4) }
  const newest = path.join(dir, backups[backups.length - 1])
  fs.copyFileSync(newest, TARGET)
  console.log(`restored ${TARGET} from ${newest}`)
  process.exit(0)
}

// --apply
if (alreadyPatched) {
  const stillUnpatched = METHODS.filter((m) => { const f = locate(src, m.name); return f.ok && !f.old.includes(MARKER) })
  if (!stillUnpatched.length) { console.log('ALREADY PATCHED — nothing to do'); process.exit(0) }
  console.log(`partial: patching ${stillUnpatched.map((m) => m.name).join(', ')}`)
}
const built = build()
if (!built.ok) { console.error(`REFUSING: ${built.reason}`); process.exit(3) }

const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const backup = `${TARGET}.bak-harness-${stamp}`
fs.copyFileSync(TARGET, backup)

// The verify copy needs a .mjs extension: `node --check` refuses to parse an unknown extension,
// and that refusal is indistinguishable from a real syntax error unless you read the message.
const tmp = `${TARGET}.patched-check.mjs`
fs.writeFileSync(tmp, built.text)
const check = syntaxCheck(tmp)
if (!check.ok) {
  fs.unlinkSync(tmp)
  console.error(`REFUSING: patched file does not parse:\n${check.detail}`)
  process.exit(5)
}
fs.renameSync(tmp, TARGET)
const after = syntaxCheck(TARGET)
console.log(`backup    : ${backup}`)
console.log(`patched   : ${TARGET}`)
console.log(`bytes     : ${src.length} -> ${built.text.length}`)
console.log(`parse     : ${after.ok ? 'OK (node --check)' : 'FAILED: ' + after.detail}`)
console.log(`marker x  : ${(built.text.match(/harness-patch:session-list-pool/g) || []).length}`)
console.log('NOTE      : the running engine keeps the old code; this applies at the next engine start.')
process.exit(after.ok ? 0 : 5)
