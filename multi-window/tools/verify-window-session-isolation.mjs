#!/usr/bin/env node
// verify-window-session-isolation.mjs — do two DSH windows with no session share ONE session?
//
// THE COMPLAINT (owner, 2026-10-14): with two or three DSH windows open that have no session yet,
// typing in one turns ALL of them into that session and they all show the same words.
//
// THE MECHANISM THIS MEASURES. A DSH window's "which session am I on" is
// `localStorage["dsh.sessions.current"]`, keyed by ORIGIN (one loopback port per window slot, see
// docs/multi-window/MEMORY-AND-SESSION-LIST.md §"the origin is the window"). A window that has no
// session yet asks the Workspace service for a blank one, and
// `@deepseek-ai/dsh-client-ui-workspace/lib/client.js` `reuseOrCreateBlank()` scans the WHOLE
// session catalog for any row with `blank: true` in the target workspace and reuses it
// (`sessions.create({ workspaceId, sessionId })`). Nothing in that scan belongs to the calling
// window, so the second and third windows adopt the FIRST window's blank, and when the owner types
// in one of them every window is rendering the same session.
//
// WHAT IT PRINTS, and why that is the evidence: the session pointer each window persisted. It is
// the same value the Workspace service restores and the Session area renders, so two windows with
// the SAME id are two windows displaying one session — the complaint. Two DIFFERENT ids are the
// fixed state. The `snapshot` subcommand is the catalog census the pointer is checked against.
//
// Usage:
//   node verify-window-session-isolation.mjs snapshot
//   node verify-window-session-isolation.mjs windows [--count 3] [--reload] [--send "text"]
//   node verify-window-session-isolation.mjs archive <sessionId> [<sessionId> ...]
//
// Options (all subcommands):
//   --url-file <path>   default ~/.dsh/multi-window/live-url.txt (the tokenized engine URL)
//   --url <url>         use this URL instead of the file (it must carry the launch token)
//   --origin-port <n>   keep the token but present it on another loopback origin — a window SLOT
//                       (3200+slot through dshw-proxy.mjs), which is the owner's real path
//   --port <n>          default 3099 — the origin used for the raw RPC (snapshot/archive)
//   --playwright <p>    path to a node_modules tree that has `playwright` (default the mcp tools)
//
// The launch token is never printed: it is read from the URL file and used as-is.

import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'

const argv = process.argv.slice(2)
const command = argv[0] ?? 'windows'

function flag(name, fallback) {
  const i = argv.indexOf(`--${name}`)
  return i === -1 ? fallback : argv[i + 1]
}
const has = (name) => argv.includes(`--${name}`)

const port = Number(flag('port', '3099'))
const urlFile = flag('url-file', path.join(homedir(), '.dsh', 'multi-window', 'live-url.txt'))
const explicitUrl = flag('url', undefined)
const playwrightRoot = flag('playwright', path.join(homedir(), '.dsh', 'tools', 'mcp'))

const launchUrl = explicitUrl ?? readFileSync(urlFile, 'utf8').trim()
const originPort = flag('origin-port', undefined)
/** The URL one window opens. `--origin-port` keeps the token and moves it onto a slot origin. */
function windowUrl(index) {
  const url = new URL(launchUrl)
  if (originPort !== undefined) url.port = String(Number(originPort) + index)
  return url.href
}
const launchToken = new URL(launchUrl).searchParams.get('token')
if (launchToken === null || launchToken === '') throw new Error(`no launch token in ${explicitUrl ? '--url' : urlFile}`)

const origin = `http://127.0.0.1:${String(port)}`

// ── the connection RPC, exactly as the browser client sends it ───────────────────────────────────
// dsh-client-connection/lib/client.js `createWebConnectionRpc.call`:
//   POST <origin>/api/<method>, content-type: application/json
//   { type: "client-request", rpcId: <uuid>, method: <method>, payload: { args: { <param>: … } } }
//   -> { type: "server-response", rpcId: <same>, result: { ok, value | error } }
// Auth is the launch token exchanged for a signed cookie by a plain GET of the tokenized URL
// (dsh-client-connection/lib/index.js `BrowserAuth.authorizeIndex`: 303 + set-cookie).
let cookieHeader
async function authenticate() {
  if (cookieHeader !== undefined) return cookieHeader
  const res = await fetch(launchUrl, { redirect: 'manual' })
  const cookies = typeof res.headers.getSetCookie === 'function' ? res.headers.getSetCookie() : [res.headers.get('set-cookie') ?? '']
  cookieHeader = cookies
    .filter((line) => line !== '')
    .map((line) => line.split(';')[0])
    .join('; ')
  if (cookieHeader === '') throw new Error(`token exchange returned no cookie (HTTP ${String(res.status)})`)
  return cookieHeader
}

async function rpc(method, args) {
  const cookie = await authenticate()
  const rpcId = crypto.randomUUID()
  const res = await fetch(`${origin}/api/${method}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', cookie },
    body: JSON.stringify({ type: 'client-request', rpcId, method, payload: { args } })
  })
  const body = await res.json()
  if (body?.result?.ok !== true) throw new Error(`${method} failed: ${JSON.stringify(body?.result?.error ?? body)}`)
  return body.result.value
}

/** `session/list` answers `{ items: [...] }`; older shapes answered a bare array. */
function rowsOf(value) {
  if (Array.isArray(value)) return value
  if (Array.isArray(value?.items)) return value.items
  return []
}

async function catalog() {
  const value = await rpc('session/list', { _request: {} })
  return rowsOf(value)
}

// ── snapshot: the catalog census, with no window opened ──────────────────────────────────────────
async function snapshot() {
  const rows = await catalog()
  const blanks = rows.filter((row) => row.blank === true)
  console.log(JSON.stringify({
    origin,
    rows: rows.length,
    blankRows: blanks.length,
    blanks: blanks.map((row) => ({ sessionId: row.sessionId, cwd: row.cwd, updatedAt: row.updatedAt })),
    runningRows: rows.filter((row) => row.running === true).length
  }, null, 2))
}

// ── windows: N isolated browser contexts, each a window slot ─────────────────────────────────────
const require = createRequire(path.join(playwrightRoot, 'package.json'))
const { chromium } = require('playwright')

/**
 * The browser build to drive.
 *
 * MEASURED 2026-10-14 on ZABZ-YOGA: the installed playwright (`~/.dsh/tools/mcp/node_modules`)
 * is 1.64.0-alpha-2026-09-14 and wants `chromium_headless_shell-1244`, while the ms-playwright
 * cache tops out at **1243** — so a bare `chromium.launch()` dies with "Executable doesn't
 * exist". Passing the newest build that IS present is the difference between a working probe and
 * a false "the fix did not apply". `--executable <path>` overrides.
 * @returns an executable path, or undefined to let playwright resolve its own.
 */
function resolveExecutable() {
  const explicit = flag('executable', undefined)
  if (explicit !== undefined) return explicit
  const cache = process.env.LOCALAPPDATA !== undefined
    ? path.join(process.env.LOCALAPPDATA, 'ms-playwright')
    : path.join(homedir(), 'AppData', 'Local', 'ms-playwright')
  let names
  try {
    names = readdirSync(cache)
  } catch {
    return undefined
  }
  const builds = names
    .map((name) => ({ name, revision: /^chromium_headless_shell-(\d+)$/u.exec(name)?.[1] }))
    .filter((entry) => entry.revision !== undefined)
    .sort((left, right) => Number(right.revision) - Number(left.revision))
  for (const build of builds) {
    const exe = path.join(cache, build.name, 'chrome-headless-shell-win64', 'chrome-headless-shell.exe')
    if (existsSync(exe)) return exe
  }
  return undefined
}

/** Wait until this window has persisted a session pointer, then read it. */
async function pointerOf(page, timeoutMs = 240000) {
  const handle = await page.waitForFunction(() => {
    try {
      const raw = window.localStorage.getItem('dsh.sessions.current')
      if (raw === null) return null
      const value = JSON.parse(raw)
      return typeof value?.sessionId === 'string' && value.sessionId !== '' ? value : null
    } catch {
      return null
    }
  }, null, { timeout: timeoutMs, polling: 1000 })
  return await handle.jsonValue()
}

async function readWindow(page) {
  return await page.evaluate(() => {
    const raw = (key) => {
      try {
        return window.localStorage.getItem(key)
      } catch {
        return null
      }
    }
    const body = (document.body?.innerText ?? '').replace(/\s+/gu, ' ').trim()
    return {
      pointer: raw('dsh.sessions.current'),
      ownedBlank: raw('dsh.sessions.ownedBlank'),
      ui: body.slice(0, 160)
    }
  })
}

async function windows() {
  const count = Number(flag('count', '2'))
  const executablePath = resolveExecutable()
  const browser = await chromium.launch({ headless: true, ...executablePath === undefined ? {} : { executablePath } })
  const opened = []
  console.log(JSON.stringify({ stage: 'launch', executablePath: executablePath ?? 'playwright-default', url: origin }))
  try {
    for (let index = 1; index <= count; index += 1) {
      const context = await browser.newContext()
      const page = await context.newPage()
      await page.goto(windowUrl(index - 1), { waitUntil: 'domcontentloaded', timeout: 120000 })
      const pointer = await pointerOf(page)
      const read = await readWindow(page)
      opened.push({ index, context, page, sessionId: pointer.sessionId, ownedBlank: read.ownedBlank, ui: read.ui })
      console.log(JSON.stringify({
        window: index,
        stage: 'opened',
        sessionId: pointer.sessionId,
        ownedBlank: read.ownedBlank,
        ui: read.ui
      }))
    }

    if (has('send')) {
      const text = flag('send', 'window-isolation probe')
      const first = opened[0]
      const composer = first.page.locator('textarea, [contenteditable="true"]').first()
      await composer.waitFor({ timeout: 60000 })
      await composer.fill(text)
      await composer.press('Enter')
      await first.page.waitForTimeout(4000)
      const second = opened[1]
      if (second !== undefined) {
        const read = await readWindow(second.page)
        console.log(JSON.stringify({ window: 2, stage: 'after-send-in-window-1', showsSentText: read.ui.includes(text), ui: read.ui }))
      }
    }

    if (has('reload')) {
      const first = opened[0]
      await first.page.reload({ waitUntil: 'domcontentloaded', timeout: 120000 })
      const again = await pointerOf(first.page)
      console.log(JSON.stringify({
        window: 1,
        stage: 'after-reload',
        sessionId: again.sessionId,
        sameAsBeforeReload: again.sessionId === first.sessionId
      }))
    }

    const ids = opened.map((entry) => entry.sessionId)
    const distinct = new Set(ids)
    console.log(JSON.stringify({
      verdict: distinct.size === ids.length ? 'ISOLATED' : 'SHARED',
      distinct: distinct.size,
      windows: ids.length,
      ids
    }, null, 2))
    if (distinct.size !== ids.length) process.exitCode = 3
  } finally {
    for (const entry of opened) await entry.context.close()
    await browser.close()
  }
}

// ── archive: hide exact ids from the catalog (a blank nobody adopted is litter) ──────────────────
// The archive RPC's own client call is `remote.archiveSession({ sessionId })`
// (dsh-api-workspace-controller/lib/client.js `archiveSession`). On the wire the host method takes
// ONE parameter named `request`, so the args field is `{ request: { sessionId } }` — measured, not
// guessed: `{ sessionId }` is refused with `missing "request"; unexpected "sessionId"`.
async function archive(ids) {
  for (const sessionId of ids) {
    const value = await rpc('workspace/archiveSession', { request: { sessionId } })
    const archived = rowsOf(value?.archivedSessionIds === undefined ? value : { items: value.archivedSessionIds })
    console.log(JSON.stringify({ archived: sessionId, confirmedInArchiveSet: archived.includes(sessionId) }))
  }
  const rows = await catalog()
  console.log(JSON.stringify({ blankRows: rows.filter((row) => row.blank === true).length }, null, 2))
}

if (command === 'snapshot') await snapshot()
else if (command === 'windows') await windows()
else if (command === 'archive') await archive(argv.slice(1).filter((value) => !value.startsWith('--')))
else throw new Error(`unknown command '${command}'`)
