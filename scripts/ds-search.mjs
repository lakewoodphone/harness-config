#!/usr/bin/env node
// ds-search.mjs — DeepSeek's OWN Search and Fetch API, as one command any session can call.
//
// WHY THIS EXISTS (measured 2026-10-19, on the authority, with the estate's existing key)
//
//   POST https://api.deepseek.com/v1/tools/search  {"query":"…","count":N}   -> 200, 0.63 s
//   POST https://api.deepseek.com/v1/tools/fetch   {"url":"…"}               -> 200, 0.34 s
//
// The response carries title, url, site_name, date, authority, rerank_score, summary and snippet per
// result; `fetch` returns the page as markdown. `count` controls the number of results (2 -> 2, 5 -> 5,
// measured). Billing, from the vendor's own guide: a request is billable only when it returns HTTP 200
// AND produces a result; through DeepSeek Harness the server-side tool calls are free until
// 00:00 Beijing on 2026-11-01, and per-request billing starts then. So this is a real, cheap, currently
// free surface — and the estate has been reaching the web through a full auxiliary model turn per
// query instead (`dsh-base`'s `web-search-deepseek`, whose own README says DeepSeek exposes no
// dedicated search endpoint; that sentence is now false).
//
// WHAT IT IS NOT: a replacement for `esearch`/`ps_search` (our own corpora — DeepSeek cannot see them)
// and not yet a replacement for jina/firecrawl, whose index coverage is measured and DeepSeek's is not.
// It is the cheapest good default for "search the live web" and "read this page".
//
// USAGE
//   node scripts/ds-search.mjs search "query" [--count 5] [--json]
//   node scripts/ds-search.mjs fetch <url> [--max-chars 4000] [--json]
//
// KEY: $env:DEEPSEEK_API_KEY, else the `deepseek` entry in <home>/.dsh/.credentials.yaml. The value is
// never printed, never logged, and never included in an error message.
//
// EXIT: 0 ok · 2 usage · 3 no key · 4 the API refused or failed (status printed) · 5 a real negative
// (search returned zero results, or fetch returned no content) — a refusal is not an empty success.

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const BASE = process.env.DS_SEARCH_BASE || 'https://api.deepseek.com'
const ARGV = process.argv.slice(2)
const cmd = ARGV[0]

function flag(name, fallback = null) {
  const i = ARGV.indexOf(`--${name}`)
  if (i === -1) return fallback
  const v = ARGV[i + 1]
  return v && !v.startsWith('--') ? v : true
}
const has = (n) => ARGV.includes(`--${n}`)

function keyFromCredentials() {
  const home = process.env.DSH_HOME || path.join(os.homedir(), '.dsh')
  const file = path.join(home, '.credentials.yaml')
  if (!fs.existsSync(file)) return null
  const text = fs.readFileSync(file, 'utf8')
  // EXACT-KEY ALLOW-LIST, never a name pattern (AGENTS.md §6.2: a name-pattern mask has already leaked a
  // live key on this estate, because the secret sat in a field whose name did not match the pattern).
  // The measured shape of this file (2026-10-19) is nested — `records:` holds `DEEPSEEK_API_KEY: <value>`
  // at an indent — so the key is matched wherever it appears, and nothing else is read.
  for (const line of text.split(/\r?\n/)) {
    const m = /^\s*DEEPSEEK_API_KEY\s*:\s*(.+?)\s*$/u.exec(line)
    if (m && m[1] && !/^[|>[]/u.test(m[1])) return m[1].replace(/^['"]|['"]$/gu, '')
  }
  return null
}

function resolveKey() {
  const env = process.env.DEEPSEEK_API_KEY && process.env.DEEPSEEK_API_KEY.trim()
  if (env) return { key: env, from: '$DEEPSEEK_API_KEY' }
  const k = keyFromCredentials()
  if (k) return { key: k, from: '<dsh home>/.credentials.yaml (deepseek block)' }
  return { key: null, from: null }
}

async function call(pathName, body, timeoutMs = 30000) {
  const { key, from } = resolveKey()
  if (!key) throw new ExitError(3, 'ds-search: no DeepSeek key. Set $env:DEEPSEEK_API_KEY or put one in <home>/.dsh/.credentials.yaml under an exact `DEEPSEEK_API_KEY` key')
  // node:https with agent:false, not global fetch: measured 2026-10-19 on Windows/node 24, a fetch()
  // followed by process.exit() crashed the runtime on exit (`Assertion failed: !(handle->flags &
  // UV_HANDLE_CLOSING), src\win\async.c:76`, exit 0xC0000409) because the keep-alive socket was still
  // closing. A CLI whose exit code is garbage cannot be used in a guard. This path has no socket left
  // to close, and it also returns immediately instead of waiting out undici's keep-alive window.
  const url = new URL(`${BASE}${pathName}`)
  const payload = JSON.stringify(body)
  const { status, text } = await new Promise((resolve, reject) => {
    const req = https.request(
      {
        hostname: url.hostname, port: url.port || 443, path: url.pathname, method: 'POST', agent: false,
        headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload), Connection: 'close' },
      },
      (res) => {
        const chunks = []
        res.on('data', (c) => chunks.push(c))
        res.on('end', () => resolve({ status: res.statusCode || 0, text: Buffer.concat(chunks).toString('utf8') }))
      },
    )
    req.setTimeout(timeoutMs, () => { req.destroy(new Error(`timeout after ${timeoutMs} ms`)) })
    req.on('error', reject)
    req.end(payload)
  }).catch((err) => {
    throw new ExitError(4, `ds-search: the request did not complete (${err.message}) — key from ${from}`)
  })
  if (status !== 200) throw new ExitError(4, `ds-search: HTTP ${status} from ${pathName} — ${text.slice(0, 400)}`)
  try { return JSON.parse(text) } catch {
    throw new ExitError(4, `ds-search: HTTP 200 but the body is not JSON — ${text.slice(0, 200)}`)
  }
}

function renderSearch(d, query) {
  const rs = Array.isArray(d.results) ? d.results : []
  const out = [`search "${query}" — ${rs.length} result(s)`]
  rs.forEach((r, i) => {
    const when = r.date ? `  ${String(r.date).slice(0, 10)}` : ''
    const auth = r.authority ? `  authority=${r.authority}` : ''
    out.push('', `${i + 1}. ${r.title || '(no title)'}${when}${auth}`, `   ${r.url}`)
    if (r.site_name) out.push(`   ${r.site_name}`)
    const body = (r.summary || r.snippet || '').replace(/\s+/gu, ' ').trim()
    if (body) out.push(`   ${body.slice(0, 400)}`)
  })
  return out.join('\n')
}

async function main() {
  if (cmd === 'search') {
    const query = ARGV[1]
    if (!query || query.startsWith('--')) { console.error('usage: ds-search.mjs search "query" [--count 5] [--json]'); process.exit(2) }
    const count = Math.max(1, Math.min(10, Number(flag('count', 5)) || 5))
    const d = await call('/v1/tools/search', { query, count })
    if (has('json')) { console.log(JSON.stringify(d, null, 2)); return 0 }
    const rs = Array.isArray(d.results) ? d.results : []
    if (!rs.length) { console.error(`ds-search: HTTP 200 and ZERO results for "${query}" — a real negative, not an error`); process.exit(5) }
    console.log(renderSearch(d, query))
    return 0
  }
  if (cmd === 'fetch') {
    const url = ARGV[1]
    if (!url || url.startsWith('--')) { console.error('usage: ds-search.mjs fetch <url> [--max-chars 4000] [--json]'); process.exit(2) }
    const d = await call('/v1/tools/fetch', { url }, 45000)
    if (has('json')) { console.log(JSON.stringify(d, null, 2)); return 0 }
    const content = typeof d.content === 'string' ? d.content : ''
    if (!content.trim()) { console.error(`ds-search: HTTP 200 and NO content for ${url} — a real negative, not an error`); process.exit(5) }
    const max = Number(flag('max-chars', 4000)) || 4000
    console.log(content.length > max ? `${content.slice(0, max)}\n…[${content.length - max} more chars; --max-chars to raise]` : content)
    return 0
  }
  console.error('usage: ds-search.mjs search "query" [--count N] [--json] | fetch <url> [--max-chars N] [--json]')
  return 2
}

main().then((c) => process.exit(c ?? 0)).catch((e) => { console.error(`ds-search: ${e && e.message ? e.message : String(e)}`); process.exit(4) })
