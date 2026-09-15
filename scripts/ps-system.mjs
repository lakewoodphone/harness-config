#!/usr/bin/env node
/**
 * ps-system.mjs — read the company's own system from a manager's machine.
 *
 * WHY THIS EXISTS
 * The manager's assistant should not be blind to the company it works for. It needs to read the
 * owner's harness sessions, the archive coverage, and (later) logged events, so it can answer "what
 * did we decide about X", "who handled this customer", "has anyone hit this problem before" -- the
 * questions a manager actually asks. A manager whose assistant cannot see the company's own history is
 * a crippled manager.
 *
 * WHAT IT IS, AND WHAT IT DELIBERATELY IS NOT
 * It is a thin, READ-ONLY client over the authority's existing HTTP API. It does not open the database,
 * it does not write, and it adds no new endpoint. Anything it can see is something the owner's own
 * dashboard can already see with the same credential.
 *
 * ATTRIBUTION
 * Reads need no attribution. Anything that WRITES from a manager's machine must carry its origin, and
 * the archive already guarantees that for the one thing that writes automatically: the ingest keys
 * every row on `source_machine`, which is `os.hostname()` of the machine that sent it. So the owner's
 * sessions are `zabz-yoga` / `zabz-tech` / `secratary` and hers are `desktop-fgv6kmh` /
 * `lakewooechsmini`, and the two can never be confused -- by construction, not by convention.
 *
 * CONFIGURATION
 *   PS_API_BASE   default https://api.abletelsolutions.com
 *   PS_API_KEY    the dashboard API key, sent as `x-ps-api-key`
 * Both are read from this machine's environment first, then from a repo `.env`.
 *
 * Usage:
 *   node ps-system.mjs stats                     # archive coverage, per machine
 *   node ps-system.mjs search "screen repair"     # search archived session rows
 *   node ps-system.mjs search "battery" --machine lakewooechsmini
 *   node ps-system.mjs sessions [--machine X] [--limit 20]
 *   node ps-system.mjs whoami                     # which machine this is, and what it can reach
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const BASE = (process.env.PS_API_BASE || 'https://api.abletelsolutions.com').replace(/\/$/, '');

function envFileValue(key) {
  const candidates = [
    path.join(os.homedir(), 'code', 'personal-secretary-mvp', '.env'),
    path.join(os.homedir(), 'Code', 'personal-secretary-mvp', '.env'),
    path.join(os.homedir(), 'personal-secretary-mvp', '.env'),
    // The harness-config checkout, which is where this script lives and therefore the one place a
    // machine can keep a credential that is definitely present when the script runs.
    //
    // NOTE, learned the hard way (2026-09-15): the token must NOT live in `~/.dsh/.env`. The harness
    // REFUSES TO BOOT while any launch-environment key is set there -- it aborts with 'only the
    // launching environment may set DSH_SESSION_INGEST_TOKEN'. Writing it there took her engine
    // offline entirely and looked, from the outside, exactly like a launcher fault.
    path.join(os.homedir(), 'code', 'harness-config', '.env'),
    path.join(os.homedir(), '.dsh', '.env'),
  ];
  for (const f of candidates) {
    try {
      const line = fs.readFileSync(f, 'utf8').split('\n').find((l) => l.replace(/^\uFEFF/, '').startsWith(key + '='));
      if (line) return line.replace(/^\uFEFF/, '').slice(key.length + 1).trim().replace(/^["']|["']$/g, '');
    } catch { /* next */ }
  }
  return '';
}
/**
 * Resolve the authority credential.
 *
 * TWO keys are accepted by `_require_dsh_session_access` on the authority, and they are NOT the same
 * secret: the dashboard key (`x-ps-api-key`) and the session-ingest token
 * (`x-ps-dsh-session-ingest-token`). Both authorise the session/company READ endpoints.
 *
 * Her machines carry only the ingest token, which is deliberate -- it is the narrowest credential
 * that grants the read this client needs, and it is already present because the session shipper uses
 * it. So resolve either one, and send whichever was found under its own header name. Sending an
 * ingest token as `x-ps-api-key` returns 401, which looks like "the server is down" and is not.
 */
const KEY_SOURCES = [
  { env: 'PS_API_KEY', header: 'x-ps-api-key' },
  { env: 'DASHBOARD_API_KEY', header: 'x-ps-api-key' },
  { env: 'DSH_SESSION_INGEST_TOKEN', header: 'x-ps-dsh-session-ingest-token' },
];

function resolveKey() {
  for (const s of KEY_SOURCES) {
    const fromEnv = String(process.env[s.env] || '').trim();
    if (fromEnv) return { secret: fromEnv, header: s.header, source: `env ${s.env}` };
  }
  for (const s of KEY_SOURCES) {
    const fromFile = envFileValue(s.env);
    if (fromFile) return { secret: fromFile, header: s.header, source: `.env ${s.env}` };
  }
  return null;
}
const CRED = resolveKey();
const KEY = CRED?.secret ?? '';
const ARGS = process.argv.slice(2);
const VERB = (ARGS[0] || 'stats').toLowerCase();
const opt = (f, d) => { const i = ARGS.indexOf(f); return i === -1 ? d : ARGS[i + 1]; };
const MACHINE = opt('--machine', '');
const LIMIT = Number(opt('--limit', 20));

async function get(pathname, params = {}) {
  const url = new URL(BASE + pathname);
  for (const [k, v] of Object.entries(params)) if (v !== '' && v != null) url.searchParams.set(k, String(v));
  const res = await fetch(url, {
    headers: { [CRED.header]: KEY, accept: 'application/json' },
    signal: AbortSignal.timeout(60000),
  });
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* leave null */ }
  if (!res.ok) {
    // A 401 here is almost always "wrong header for this token", not a server fault, so say so.
    const hint = res.status === 401
      ? `\n           the credential found in ${CRED.source} was sent as "${CRED.header}" and rejected.`
      : '';
    throw new Error(`${res.status} ${text.slice(0, 200)}${hint}`);
  }
  return json;
}

function fail(msg, hint) {
  console.error('ps-system: ' + msg);
  if (hint) console.error('           ' + hint);
  process.exit(1);
}

/** Print a compact, readable summary rather than raw JSON -- this is read by a person or a model. */
function table(rows, columns) {
  if (!rows || !rows.length) { console.log('  (no rows)'); return; }
  const widths = columns.map((c) => Math.max(c.label.length, ...rows.map((r) => String(c.get(r) ?? '').length)));
  console.log('  ' + columns.map((c, i) => c.label.padEnd(widths[i])).join('  '));
  console.log('  ' + widths.map((w) => '-'.repeat(w)).join('  '));
  for (const r of rows) console.log('  ' + columns.map((c, i) => String(c.get(r) ?? '').slice(0, 120).padEnd(widths[i])).join('  '));
}

async function main() {
  if (!CRED) fail('no API credential found',
    'set PS_API_KEY, DASHBOARD_API_KEY or DSH_SESSION_INGEST_TOKEN in the environment or in a repo .env');

  if (VERB === 'whoami') {
    const me = os.hostname().toLowerCase();
    console.log(`  this machine : ${me}`);
    console.log(`  api base     : ${BASE}`);
    console.log(`  credential   : ${CRED.source} (${KEY.length} chars, sent as ${CRED.header})`);
    const s = await get('/api/v1/owner/dsh-sessions/stats');
    const rows = s.by_machine || s.machines || [];
    const mine = Array.isArray(rows) ? rows.find((m) => String(m.source_machine || m.machine).toLowerCase() === me) : null;
    console.log(`  my archived  : ${mine ? JSON.stringify(mine) : `nothing yet under "${me}"`}`);
    if (Array.isArray(rows) && rows.length) {
      console.log(`  fleet sees   : ${rows.length} machine(s) -- ${rows.map((m) => m.source_machine || m.machine).join(', ')}`);
    }
    console.log('  attribution  : anything that writes from here is tagged with this hostname');
    return;
  }

  if (VERB === 'stats') {
    const s = await get('/api/v1/owner/dsh-sessions/stats');
    console.log('  archive coverage');
    const rows = s.by_machine || s.machines || [];
    if (Array.isArray(rows) && rows.length) {
      table(rows, [
        { label: 'machine', get: (r) => r.source_machine || r.machine },
        { label: 'sessions', get: (r) => r.sessions || r.session_count },
        { label: 'events', get: (r) => r.events || r.event_count },
      ]);
    } else {
      console.log('  ' + JSON.stringify(s).slice(0, 400));
    }
    return;
  }

  if (VERB === 'sessions' || VERB === 'list') {
    // CORRECTION: an earlier version of this verb ran a `*` query and the authority answered 500 --
    // `*` is not a valid FTS5 MATCH expression. There is genuinely NO sessions-list endpoint (the
    // authority exposes only /stats, /search and /ingest), so this verb cannot list sessions and
    // must not pretend to. What it CAN answer honestly is coverage: how many sessions and events
    // exist per machine, and how recent the newest one is. To look inside a session, search it.
    const s = await get('/api/v1/owner/dsh-sessions/stats');
    const all = s.by_machine || s.machines || [];
    const rows = MACHINE ? all.filter((m) => String(m.source_machine || m.machine).toLowerCase() === MACHINE.toLowerCase()) : all;
    console.log(`  archived sessions${MACHINE ? ' on ' + MACHINE : ' (all machines)'}: ${rows.length} machine(s)`);
    table(rows, [
      { label: 'machine', get: (r) => r.source_machine || r.machine },
      { label: 'sessions', get: (r) => r.sessions || r.session_count },
      { label: 'events', get: (r) => r.events || r.event_count },
      { label: 'latest', get: (r) => String(r.latest || '').slice(0, 19) },
    ]);
    console.log(`  to read inside a session:  ps-system search "<words>"${MACHINE ? ' --machine ' + MACHINE : ''}`);
    return;
  }

  if (VERB === 'search') {
    const q = ARGS[1];
    if (!q) fail('search needs a query', 'node ps-system.mjs search "phone screen"');
    const r = await get('/api/v1/owner/dsh-sessions/search', { query: q, source_machine: MACHINE, limit: LIMIT });
    const results = r.results || [];
    console.log(`  query: ${q}${MACHINE ? '   machine: ' + MACHINE : '   (all machines)'}   found: ${r.count ?? results.length}`);
    // The endpoint returns { source_machine, session_id, ordinal, snippet, cwd, updated_at, event_count }.
    // `snippet` is SQLite's snippet() with '[' ']' around each match and '…' between fragments.
    table(results, [
      { label: 'machine', get: (x) => x.source_machine },
      { label: 'session', get: (x) => String(x.session_id || '').slice(0, 8) },
      { label: 'at', get: (x) => String(x.updated_at || '').slice(0, 16) },
      { label: 'excerpt', get: (x) => String(x.snippet ?? x.excerpt ?? x.raw ?? '').replace(/\s+/g, ' ').trim() },
    ]);
    if (!results.length && r.hint) console.log('  hint: ' + r.hint);
    return;
  }

  fail(`unknown command "${VERB}"`, 'stats | search <query> [--machine H] | sessions | whoami');
}

main().catch((e) => { console.error('ps-system: ' + e.message); process.exit(1); });
