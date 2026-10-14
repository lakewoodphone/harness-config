#!/usr/bin/env node
// patch-window-blank-isolation.mjs — keep the DSH client's per-window blank-session fix applied.
//
// WHY A SCRIPT AND NOT A HAND EDIT. The fix lives in an npm-installed file inside the engine
// (`~/.dsh/engine/node_modules/@deepseek-ai/dsh-client-ui-workspace/lib/client.js`), and
// `dsh-update` replaces that tree — `dsh-update` tracks *cordis composition* patches
// (`cordis.patch.yml` rows) and has no registry for a hand patch to a package file, so a file edit
// silently disappears on the next engine update. This script is the registry: it re-applies the
// patch idempotently, and `--check` says whether the running install still carries it.
//
// WHY THE PATCH EXISTS. `reuseOrCreateBlank()` scanned the WHOLE session catalog for a row with
// `blank: true` in the target workspace and reused it, so a second DSH window with no session yet
// adopted the FIRST window's blank and both rendered one conversation — the owner's complaint of
// 2026-10-14 ("when I talk in one, they all turn into that session"). The patch confines reuse to
// the blank this window slot created, recorded in localStorage `dsh.sessions.ownedBlank` (per
// origin, exactly like `dsh.sessions.current`), and refuses to restore a blank the window does not
// own — which also detaches an already-doubled window on its next reload.
//
// Usage:
//   node patch-window-blank-isolation.mjs --check     # exit 0 = applied, 4 = absent, 5 = unverifiable
//   node patch-window-blank-isolation.mjs --apply     # idempotent; refuses on an unknown upstream
//   node patch-window-blank-isolation.mjs --revert    # restore the upstream text (rollback door)
//
// Options: --engine <dir> (default ~/.dsh/engine), --backup-dir <dir> (default beside the file)

import { copyFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'

const argv = process.argv.slice(2)
const has = (name) => argv.includes(`--${name}`)
const flag = (name, fallback) => {
  const index = argv.indexOf(`--${name}`)
  return index === -1 ? fallback : argv[index + 1]
}

const engine = flag('engine', path.join(homedir(), '.dsh', 'engine'))
const target = path.join(engine, 'node_modules', '@deepseek-ai', 'dsh-client-ui-workspace', 'lib', 'client.js')
const MARKER = 'window-blank-isolation'

/** One source line as `[indentLevel, text]`; the file is tab-indented generated code. */
const line = ([level, text]) => `${'\t'.repeat(level)}${text}`
const block = (lines) => lines.map(line).join('\n')

// ── the patch: three anchored replacements, each with its upstream text spelled out ──────────────
const PATCHES = [
  {
    name: 'blank-ownership helpers',
    anchor: [
      [2, '/** Implements Workspace archive and directory UI operations. */'],
      [2, 'var UiWorkspaceService = class extends _deepseek_ai_cordis.Service {']
    ],
    replacement: [
      [2, '/**'],
      [2, `* Local patch (${MARKER}, harness-config 2026-10-14): WHICH BLANK SESSION THIS WINDOW`],
      [2, '* SLOT OWNS. Upstream `reuseOrCreateBlank()` adopts any blank row of the workspace, so two'],
      [2, '* windows with no session yet adopt the SAME one and both render one conversation. The record'],
      [2, '* is per-ORIGIN localStorage, exactly like `dsh.sessions.current` (one loopback port per window'],
      [2, '* slot, docs/multi-window/MEMORY-AND-SESSION-LIST.md), so a window keeps its own blank across'],
      [2, '* reloads while a new window slot starts empty.'],
      [2, '*/'],
      [2, 'const OWNED_BLANK_KEY = "dsh.sessions.ownedBlank";'],
      [2, '/**'],
      [2, '* Read the blank this window slot owns.'],
      [2, '* @param fallback - this window\'s own saved selection, used only when the host has no'],
      [2, '*   localStorage at all, which preserves upstream\'s reload behaviour there.'],
      [2, '* @returns the owned blank Session id, or absence.'],
      [2, '*/'],
      [2, 'function readOwnedBlank(fallback) {'],
      [3, 'try {'],
      [4, 'if (typeof localStorage === "undefined") return fallback;'],
      [4, 'return localStorage.getItem(OWNED_BLANK_KEY) ?? void 0;'],
      [3, '} catch {'],
      [4, 'return fallback;'],
      [3, '}'],
      [2, '}'],
      [2, '/**'],
      [2, '* Record the blank this window slot owns, so a reload reuses it.'],
      [2, '* @param sessionId - blank Session id to own.'],
      [2, '*/'],
      [2, 'function writeOwnedBlank(sessionId) {'],
      [3, 'try {'],
      [4, 'if (typeof localStorage !== "undefined") localStorage.setItem(OWNED_BLANK_KEY, sessionId);'],
      [3, '} catch {}'],
      [2, '}'],
      [2, '/** Implements Workspace archive and directory UI operations. */'],
      [2, 'var UiWorkspaceService = class extends _deepseek_ai_cordis.Service {']
    ]
  },
  {
    name: 'reuse only the owned blank',
    anchor: [
      [3, 'reuseOrCreateBlank(workspace) {'],
      [4, 'const archived = this.workspaces.list.getSnapshot().archivedSessionIds;'],
      [4, 'const sessions = this.sessions.list.getSnapshot();'],
      [4, 'for (const id of sessions.ids) {'],
      [5, 'const summary = sessions.byId[id];'],
      [5, 'if (summary === void 0 || !summary.blank || summary.cwd !== workspace.path || !workspace.sessionIds.includes(id) || archived.includes(id)) continue;'],
      [5, 'return this.reuseBlank(workspace.workspaceId, id);'],
      [4, '}'],
      [4, 'return this.sessions.create({ workspaceId: workspace.workspaceId });'],
      [3, '}']
    ],
    replacement: [
      [3, 'reuseOrCreateBlank(workspace) {'],
      [4, 'const archived = this.workspaces.list.getSnapshot().archivedSessionIds;'],
      [4, 'const sessions = this.sessions.list.getSnapshot();'],
      [4, `const owned = this.ownedBlankId(); // local patch (${MARKER}): never another window's blank`],
      [4, 'if (owned !== void 0) {'],
      [5, 'const summary = sessions.byId[owned];'],
      [5, 'if (summary !== void 0 && summary.blank && summary.cwd === workspace.path && workspace.sessionIds.includes(owned) && !archived.includes(owned)) return this.claimBlank(this.reuseBlank(workspace.workspaceId, owned));'],
      [4, '}'],
      [4, 'return this.claimBlank(this.sessions.create({ workspaceId: workspace.workspaceId }));'],
      [3, '}'],
      [3, '/**'],
      [3, `* Local patch (${MARKER}): the blank Session this window slot created, never another`],
      [3, "* window's."],
      [3, '* @returns the owned blank Session id, or absence.'],
      [3, '*/'],
      [3, 'ownedBlankId() {'],
      [4, 'return readOwnedBlank(this.selection.getSnapshot().sessionId);'],
      [3, '}'],
      [3, '/**'],
      [3, `* Local patch (${MARKER}): record the blank this window owns as soon as its creation`],
      [3, '* resolves, so a reload reuses that blank instead of leaving it behind and making another.'],
      [3, '* @param opening - pending blank creation or adoption.'],
      [3, '* @returns the same Session id.'],
      [3, '*/'],
      [3, 'claimBlank(opening) {'],
      [4, 'return opening.then((sessionId) => {'],
      [5, 'writeOwnedBlank(sessionId);'],
      [5, 'return sessionId;'],
      [4, '});'],
      [3, '}']
    ]
  },
  {
    name: 'do not restore an unowned blank',
    anchor: [
      [4, 'if (summary !== void 0 && (!summary.blank || workspace === void 0)) {']
    ],
    replacement: [
      [4, `// local patch (${MARKER}): a blank this window does not own is another window's`],
      [4, 'const foreignBlank = summary !== void 0 && summary.blank && summary.id !== this.ownedBlankId();'],
      [4, 'if (summary !== void 0 && !foreignBlank && (!summary.blank || workspace === void 0)) {']
    ]
  },
  {
    name: 'do not adopt an unowned blank',
    anchor: [
      [4, 'if (summary !== void 0 && workspace !== void 0 && summary.cwd === workspace.path && !workspaces.archivedSessionIds.includes(summary.id)) sessionId = await this.reuseBlank(workspace.workspaceId, summary.id);']
    ],
    replacement: [
      [4, 'if (summary !== void 0 && !foreignBlank && workspace !== void 0 && summary.cwd === workspace.path && !workspaces.archivedSessionIds.includes(summary.id)) sessionId = await this.reuseBlank(workspace.workspaceId, summary.id);']
    ]
  }
]

const APPLIED_MARKERS = [`const OWNED_BLANK_KEY = "dsh.sessions.ownedBlank";`]

function readTarget() {
  if (!existsSync(target)) {
    console.error(`REFUSED: no client bundle at ${target} (engine tree moved? use --engine)`)
    process.exit(5)
  }
  return readFileSync(target, 'utf8')
}

function status() {
  const text = readTarget()
  const present = APPLIED_MARKERS.every((marker) => text.includes(marker))
  const upstream = PATCHES.filter((patch) => text.includes(block(patch.anchor))).map((patch) => patch.name)
  return { present, upstream }
}

function check() {
  const { present, upstream } = status()
  if (present) {
    console.log(`APPLIED: ${MARKER} is present in ${target}`)
    process.exit(0)
  }
  console.log(`ABSENT: ${MARKER} is NOT in ${target}`)
  console.log(`  upstream anchors that would still match: ${upstream.length === 0 ? 'none' : upstream.join(', ')}`)
  process.exit(4)
}

function apply() {
  if (status().present) {
    console.log(`ALREADY APPLIED: ${MARKER}`)
    return
  }
  let text = readTarget()
  const backup = `${target}.bak-harness-${new Date().toISOString().replace(/[-:]/gu, '').replace(/\..+$/u, 'Z')}`
  copyFileSync(target, backup)
  for (const patch of PATCHES) {
    const anchor = block(patch.anchor)
    const occurrences = text.split(anchor).length - 1
    if (occurrences !== 1) {
      console.error(`REFUSED: anchor '${patch.name}' matches ${String(occurrences)} times, expected 1.`)
      console.error('  The upstream bundle changed. Read the new code and update this script — do NOT force it.')
      process.exit(5)
    }
    text = text.replace(anchor, block(patch.replacement))
    console.log(`applied: ${patch.name}`)
  }
  writeFileSync(target, text)
  console.log(`wrote ${target} (backup ${path.basename(backup)})`)
  console.log('the engine serves the client bundle per request, keyed on mtime — no restart is needed; a window must reload')
}

function revert() {
  let text = readTarget()
  for (const patch of PATCHES.slice().reverse()) {
    const replacement = block(patch.replacement)
    if (!text.includes(replacement)) {
      console.error(`REFUSED: '${patch.name}' is not present verbatim; nothing reverted.`)
      process.exit(5)
    }
    text = text.replace(replacement, block(patch.anchor))
  }
  writeFileSync(target, text)
  console.log(`reverted ${target} to the upstream text`)
}

if (has('check')) check()
else if (has('apply')) apply()
else if (has('revert')) revert()
else {
  console.error('usage: patch-window-blank-isolation.mjs --check | --apply | --revert [--engine <dir>]')
  process.exit(1)
}
