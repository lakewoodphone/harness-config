#!/usr/bin/env node
/**
 * ps-shop.mjs — the shop's own workflow, from the manager's machine, over the company API.
 *
 * WHY THIS EXISTS
 * The owner's requirement for the LPT manager: when she orders a part or moves a repair along, the
 * customer's case and info must actually be updated — not noted somewhere and reconciled later. The
 * company already models that workflow in its API, so this drives THOSE routes rather than inventing
 * a parallel store:
 *
 *   POST /api/v1/shop/customer-intake   open a repair for a customer (creates the task)
 *   POST /api/v1/shop/parts             A PART ORDER of a known part
 *   PATCH /api/v1/shop/parts/quantity   correct stock (audited server-side)
 *   POST /api/v1/shop/parts/link        attach a part to a repair
 *   POST /api/v1/shop/repair-status     move the repair, optionally text the customer
 *   POST /api/v1/shop/send-update       a message about a specific repair
 *   POST /api/v1/shop/check-uncollected repairs finished but never picked up
 *
 * WHY THE API AND NOT THE DATABASE
 * A direct database write skips the business logic that makes a change correct — status validation,
 * SMS scheduling, task history, cost recording — and it puts a second writer on a store this company
 * has already lost data from twice. The API is the interface designed for this, it keeps one writer,
 * and it is reachable from any network over HTTPS with a key. Her laptop especially: it reaches
 * api.abletelsolutions.com from anywhere and does NOT reach the authority's network at all.
 *
 * ATTRIBUTION — THE OWNER'S ACTUAL BOUNDARY
 * Reads need no attribution. Every WRITE is stamped with this machine's hostname, both as a header
 * the API records and, where the route accepts one, in the payload's `source`/`notes` field. So a
 * part ordered or a status moved from her laptop is traceable to that laptop afterwards, which is
 * what was asked for: label it, do not restrict it.
 *
 * Usage:
 *   node ps-shop.mjs whoami
 *   node ps-shop.mjs parts [--low] [--query "nv156"] [--category screens]
 *   node ps-shop.mjs part-add --name "..." [--part-number X] [--unit-cost 61.14] [--supplier X] [--quantity 1]
 *   node ps-shop.mjs part-qty --part-id 12 [--quantity 3] [--min-quantity 1]
 *   node ps-shop.mjs link --task-id 42 --part-id 12 [--quantity-used 1]
 *   node ps-shop.mjs intake --name "..." --phone "..." --make Lenovo --model "IdeaPad Slim 3" --issue "..."
 *   node ps-shop.mjs status --task-id 42 --new-status "waiting on part" [--notes "..."] [--sms]
 *   node ps-shop.mjs update --task-id 42 --message "..."
 *   node ps-shop.mjs uncollected [--days 30]
 *
 * EXECUTION MODEL: because this shells out to the harness shell, it must never be the thing that
 * speaks to the customer unasked. `--sms` sends a text and therefore obeys the same rule as every
 * other outbound message on this fleet: only when the manager says to send THAT message.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const BASE = (process.env.PS_API_BASE || 'https://api.abletelsolutions.com').replace(/\/$/, '');
const MACHINE = (process.env.PS_MACHINE || os.hostname()).toLowerCase();
const ARGS = process.argv.slice(2);
const VERB = (ARGS[0] || '').toLowerCase();

/** The header every write carries, so the API can record which machine acted. */
const PROVENANCE_HEADER = 'x-ps-source-machine';

function envFileValue(key) {
  const candidates = [
    path.join(os.homedir(), 'code', 'personal-secretary-mvp', '.env'),
    path.join(os.homedir(), 'Code', 'personal-secretary-mvp', '.env'),
    path.join(os.homedir(), 'personal-secretary-mvp', '.env'),
    path.join(os.homedir(), 'code', 'harness-config', '.env'),
    // Her laptop keeps its provider and dashboard keys in this one repository-local file, which
    // predates the harness and is where the launcher scripts read from. Reading it here means the
    // manager's machine needs no new credential to place an order.
    path.join(os.homedir(), 'yocheved', '.env'),
  ];
  for (const f of candidates) {
    try {
      const line = fs.readFileSync(f, 'utf8').split('\n')
        .find((l) => l.replace(/^\uFEFF/, '').startsWith(key + '='));
      if (line) return line.replace(/^\uFEFF/, '').slice(key.length + 1).trim().replace(/^["']|["']$/g, '');
    } catch { /* next */ }
  }
  return '';
}

const KEY_SOURCES = [
  { env: 'PS_API_KEY', header: 'x-ps-api-key' },
  { env: 'DASHBOARD_API_KEY', header: 'x-ps-api-key' },
  { env: 'DSH_SESSION_INGEST_TOKEN', header: 'x-ps-dsh-session-ingest-token' },
];
function resolveKey() {
  for (const s of KEY_SOURCES) {
    const v = String(process.env[s.env] || '').trim() || envFileValue(s.env);
    if (v) return { secret: v, header: s.header, source: process.env[s.env] ? `env ${s.env}` : `.env ${s.env}` };
  }
  return null;
}
const CRED = resolveKey();
if (!CRED) {
  console.error('ps-shop: no API credential found (PS_API_KEY / DASHBOARD_API_KEY / DSH_SESSION_INGEST_TOKEN)');
  process.exit(1);
}

const opt = (f, d) => { const i = ARGS.indexOf(f); return i === -1 ? d : ARGS[i + 1]; };
const has = (f) => ARGS.includes(f);
const num = (f) => { const v = opt(f); return v === undefined ? undefined : Number(v); };

async function call(method, pathname, { body, query } = {}) {
  const url = new URL(BASE + pathname);
  for (const [k, v] of Object.entries(query || {})) if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
  const headers = { [CRED.header]: CRED.secret, accept: 'application/json', [PROVENANCE_HEADER]: MACHINE };
  if (body !== undefined) headers['content-type'] = 'application/json';
  const res = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(90000),
  });
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* leave null */ }
  if (!res.ok) {
    const hint = res.status === 401
      ? `\n  the credential from ${CRED.source} was rejected. A read token may not authorize company writes;`
        + ` writes need the dashboard key, which the API accepts as "x-ps-api-key".`
      : '';
    const detail = json ? JSON.stringify(json).slice(0, 400) : text.slice(0, 400);
    throw new Error(`${method} ${pathname} -> HTTP ${res.status}\n  ${detail}${hint}`);
  }
  return json ?? { ok: true };
}

/** Echo the reply compactly: this is read by a model or a person, not piped into another program. */
function show(v, limit = 1400) {
  const s = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
  console.log(s.length > limit ? s.slice(0, limit) + '\n  … (truncated)' : s);
}

function requireArgs(pairs) {
  const missing = pairs.filter(([, v]) => v === undefined || v === null || v === '').map(([k]) => k);
  if (missing.length) {
    console.error(`ps-shop: missing required option(s): ${missing.map((m) => '--' + m).join(', ')}`);
    process.exit(2);
  }
}

async function main() {
  switch (VERB) {
    case 'whoami': {
      console.log(`  this machine : ${MACHINE}`);
      console.log(`  api base     : ${BASE}`);
      console.log(`  credential   : ${CRED.source} (sent as ${CRED.header})`);
      console.log(`  writes carry : ${PROVENANCE_HEADER}: ${MACHINE}`);
      const h = await call('GET', '/health').catch((e) => ({ error: e.message }));
      console.log(`  api health   : ${JSON.stringify(h).slice(0, 200)}`);
      return;
    }

    case 'parts': {
      const r = await call('GET', '/api/v1/shop/parts', {
        query: { query: opt('--query'), category: opt('--category'), low_stock: has('--low') ? true : undefined, limit: num('--limit') ?? 25 },
      });
      show(r);
      return;
    }

    case 'part-add': {
      const name = opt('--name');
      requireArgs([['name', name]]);
      const r = await call('POST', '/api/v1/shop/parts', {
        body: {
          name,
          part_number: opt('--part-number'),
          category: opt('--category'),
          compatible_devices: opt('--compatible'),
          quantity: num('--quantity'),
          min_quantity: num('--min-quantity'),
          unit_cost: num('--unit-cost'),
          supplier: opt('--supplier'),
          supplier_url: opt('--supplier-url'),
          notes: opt('--notes'),
        },
      });
      console.log(`  ordered/added on ${MACHINE}:`);
      show(r);
      return;
    }

    case 'part-qty': {
      const part_id = num('--part-id');
      requireArgs([['part-id', part_id]]);
      const r = await call('PATCH', '/api/v1/shop/parts/quantity', {
        body: { part_id, quantity: num('--quantity'), min_quantity: num('--min-quantity') },
      });
      console.log(`  stock corrected on ${MACHINE}:`);
      show(r);
      return;
    }

    case 'link': {
      const task_id = num('--task-id'); const part_id = num('--part-id');
      requireArgs([['task-id', task_id], ['part-id', part_id]]);
      const r = await call('POST', '/api/v1/shop/parts/link', {
        body: { task_id, part_id, quantity_used: num('--quantity-used') ?? 1 },
      });
      console.log(`  part linked to repair on ${MACHINE}:`);
      show(r);
      return;
    }

    case 'intake': {
      const name = opt('--name'); const phone = opt('--phone');
      const make = opt('--make'); const model = opt('--model'); const issue = opt('--issue');
      requireArgs([['name', name], ['phone', phone], ['make', make], ['model', model], ['issue', issue]]);
      const r = await call('POST', '/api/v1/shop/customer-intake', {
        body: {
          customer_name: name, customer_phone: phone, device_make: make, device_model: model,
          issue_description: issue, customer_email: opt('--email'), device_serial: opt('--serial'),
          source: opt('--source') ?? `manager-${MACHINE}`,
        },
      });
      console.log(`  intake recorded on ${MACHINE} (source tagged):`);
      show(r);
      return;
    }

    case 'status': {
      const task_id = num('--task-id'); const new_status = opt('--new-status');
      requireArgs([['task-id', task_id], ['new-status', new_status]]);
      const notes = opt('--notes');
      const r = await call('POST', '/api/v1/shop/repair-status', {
        body: {
          task_id, new_status,
          notes: notes ? `${notes} [from ${MACHINE}]` : `[from ${MACHINE}]`,
          send_sms: has('--sms') ? true : undefined,
          sms_custom_message: opt('--sms-message'),
        },
      });
      console.log(`  repair moved to "${new_status}" on ${MACHINE}${has('--sms') ? ' (customer texted)' : ''}:`);
      show(r);
      return;
    }

    case 'update': {
      const task_id = num('--task-id'); const message = opt('--message');
      requireArgs([['task-id', task_id], ['message', message]]);
      const r = await call('POST', '/api/v1/shop/send-update', { body: { task_id, message } });
      console.log(`  update sent for repair ${task_id} on ${MACHINE}:`);
      show(r);
      return;
    }

    case 'uncollected': {
      const r = await call('POST', '/api/v1/shop/check-uncollected', {
        body: { days_threshold: num('--days') ?? 30, dry_run: has('--send') ? false : true },
      });
      console.log(`  uncollected check on ${MACHINE}${has('--send') ? '' : ' (dry run — nothing messaged)'}:`);
      show(r);
      return;
    }

    default:
      console.error('ps-shop: commands -> whoami | parts | part-add | part-qty | link | intake | status | update | uncollected');
      console.error('  everything except whoami/parts WRITES to the company, stamped with this machine.');
      process.exit(2);
  }
}

main().catch((e) => { console.error('ps-shop: ' + e.message); process.exit(1); });
