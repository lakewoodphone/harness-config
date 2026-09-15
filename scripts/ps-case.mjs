#!/usr/bin/env node
/**
 * ps-case.mjs — create and update a customer's case file, so work done on her machine actually lands
 * where the shop keeps its records.
 *
 * THE REQUIREMENT (owner, 2026-09-15): "when she orders stuff and does things, the customers case
 * files and info should be updated and all". The company's shop API already models the WORKFLOW (intake,
 * parts, status, SMS) and `ps-shop.mjs` drives it. What was missing is the RECORD: nothing wrote the
 * case file or its sync record, so an intake created a task with no case document and an order updated
 * nothing a human would later read.
 *
 * THE TWO FORMATS, read from the real files rather than invented:
 *   docs/customer-operations/cases/<slug>.md
 *       A markdown case file: bold Status/Customer/Work header lines, then a `## Timeline` of dated
 *       bullets. This is the document a person opens.
 *   docs/customer-operations/sync-records/<caseId>-<date>.json
 *       A machine record (`recordType: customer-case-sync-record`) carrying customer, device,
 *       references (contactId, taskId) and workflow state. This is what the system links on.
 *
 * WHY HERE AND NOT IN THE API
 * These are files in lpt-hub, which is the repository her machines already have and her key can already
 * push to. Writing them where the shop's records actually live is the point; inventing a parallel store
 * would be the same mistake the API exists to avoid. `ps-shop.mjs` moves the WORKFLOW, this moves the
 * DOCUMENT, and the two are meant to be used together.
 *
 * ATTRIBUTION: every write appends `[from <hostname>]` to the timestamped timeline entry it adds, and
 * the sync record carries `source`. That is the owner's rule for her machines -- labelled, not
 * restricted -- so a case touched from her laptop says so, and a git commit made by the hourly
 * repo-sync carries the same machine tag.
 *
 * Usage:
 *   node ps-case.mjs open --name "..." --phone "..." --device "..." --issue "..." [--slug x] [--task-id N] [--contact-id N]
 *   node ps-case.mjs note --case <slug> --text "..."            # append a dated timeline entry
 *   node ps-case.mjs status --case <slug> --status "SOURCED" [--note "..."]
 *   node ps-case.mjs show --case <slug>
 *   node ps-case.mjs list [--limit 10]
 *
 * Options: --root <lpt-hub path>  (default: search the usual places), --json
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const ARGS = process.argv.slice(2);
const VERB = (ARGS[0] || '').toLowerCase();
const MACHINE = (process.env.PS_MACHINE || os.hostname()).toLowerCase();
const JSON_OUT = ARGS.includes('--json');
const opt = (f, d) => { const i = ARGS.indexOf(f); return i === -1 ? d : ARGS[i + 1]; };
const dateOnly = () => new Date().toISOString().slice(0, 10);
const fullStamp = () => new Date().toISOString().replace('T', ' ').slice(0, 16) + 'Z';

/** Find the lpt-hub checkout: it is where the shop's records live. */
function findRoot() {
  const explicit = opt('--root');
  const cands = explicit ? [path.resolve(explicit)] : [
    path.join(os.homedir(), 'code', 'lpt-hub'),
    path.join(os.homedir(), 'Code', 'lpt-hub'),
    path.join(os.homedir(), 'lpt-hub'),
  ];
  for (const c of cands) {
    if (fs.existsSync(path.join(c, 'docs', 'customer-operations'))) return c;
  }
  return null;
}

function slugify(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48);
}

function ensureDirs(root) {
  const cases = path.join(root, 'docs', 'customer-operations', 'cases');
  const sync = path.join(root, 'docs', 'customer-operations', 'sync-records');
  fs.mkdirSync(cases, { recursive: true });
  fs.mkdirSync(sync, { recursive: true });
  return { cases, sync };
}

function casePath(root, slug) {
  const dir = path.join(root, 'docs', 'customer-operations', 'cases');
  if (fs.existsSync(path.join(dir, `${slug}.md`))) return path.join(dir, `${slug}.md`);
  // A case file may carry a date suffix; accept that too.
  const hit = fs.existsSync(dir) ? fs.readdirSync(dir).find((f) => f.startsWith(slug) && f.endsWith('.md')) : null;
  return hit ? path.join(dir, hit) : path.join(dir, `${slug}.md`);
}

/**
 * Insert or replace a bold header line, so Status can be moved without rewriting the document.
 *
 * TWO REAL FORMS EXIST IN THE REPO and both must be handled, which I got wrong on the first attempt
 * and saw as a DUPLICATE Status line in the output:
 *     **Status: OPEN — intake 2026-09-15**      <- the form the case files actually use
 *     **Status:** SOURCED                        <- the form my writer produced
 * A replacer that only knows one of them silently ADDS a second header rather than moving the first,
 * and a case file with two contradictory statuses is worse than one with none.
 */
function setHeaderLine(text, label, value) {
  const re = new RegExp(`^\\*\\*${label}:\\*\\*.*$|^\\*\\*${label}: .*\\*\\*$`, 'm');
  const line = `**${label}: ${value}**`;
  if (re.test(text)) return text.replace(re, line);
  // No such header yet: put it after the H1 and any existing header block.
  const lines = text.split('\n');
  const h1 = lines.findIndex((l) => l.startsWith('# '));
  if (h1 === -1) return `${line}\n${text}`;
  let insertAt = h1 + 1;
  while (insertAt < lines.length && (lines[insertAt].startsWith('**') || lines[insertAt].trim() === '')) insertAt += 1;
  lines.splice(insertAt, 0, line);
  return lines.join('\n');
}

/** Append a dated bullet to `## Timeline`, creating the section if the document lacks one. */
function appendTimeline(text, entry) {
  const bullet = `- **${dateOnly()}:** ${entry}`;
  if (/^## Timeline\s*$/m.test(text)) {
    const idx = text.search(/^## Timeline\s*$/m);
    const after = text.indexOf('\n', idx) + 1;
    // Walk to the end of the timeline block (next `## ` heading or EOF).
    const rest = text.slice(after);
    const nextHeading = rest.search(/^## /m);
    const blockEnd = nextHeading === -1 ? text.length : after + nextHeading;
    const block = text.slice(after, blockEnd).replace(/\s*$/, '');
    return text.slice(0, after) + block + `\n${bullet}\n\n` + text.slice(blockEnd);
  }
  return `${text.replace(/\s*$/, '')}\n\n## Timeline\n${bullet}\n`;
}

function writeSyncRecord(root, { caseId, name, phone, device, issue, taskId, contactId }) {
  const { sync } = ensureDirs(root);
  const file = path.join(sync, `${caseId}-${dateOnly()}.json`);
  let existing = {};
  if (fs.existsSync(file)) { try { existing = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { existing = {}; } }
  const record = {
    recordType: 'customer-case-sync-record',
    version: 1,
    caseId,
    sourcePath: path.relative(root, file).split(path.sep).join('/'),
    customer: { name, phone },
    device: { summary: device },
    references: { contactId: contactId ?? existing?.references?.contactId ?? null, taskId: taskId ?? existing?.references?.taskId ?? null },
    workflow: existing.workflow ?? {
      customerState: 'real-interaction',
      ticketState: taskId ? 'ticket-created' : 'no-ticket',
      workOrderState: 'checked-in',
      contactPreference: 'sms',
    },
    operational: { internalSummary: issue },
    // The label the owner asked for: which machine produced this record.
    source: { machine: MACHINE, recordedAt: fullStamp(), tool: 'ps-case.mjs' },
  };
  fs.writeFileSync(file, JSON.stringify(record, null, 2) + '\n', 'utf8');
  return path.relative(root, file).split(path.sep).join('/');
}

function main() {
  const root = findRoot();
  if (!root) {
    console.error('ps-case: no lpt-hub checkout found.');
    console.error('  looked for: ~/code/lpt-hub, ~/Code/lpt-hub, ~/lpt-hub');
    console.error('  pass --root <path> if it lives elsewhere.');
    process.exit(1);
  }

  if (VERB === 'list') {
    const dir = path.join(root, 'docs', 'customer-operations', 'cases');
    const limit = Number(opt('--limit', 10));
    const files = fs.existsSync(dir)
      ? fs.readdirSync(dir).filter((f) => f.endsWith('.md'))
          .map((f) => ({ f, m: fs.statSync(path.join(dir, f)).mtimeMs }))
          .sort((a, b) => b.m - a.m).slice(0, limit)
      : [];
    if (JSON_OUT) { console.log(JSON.stringify(files.map((x) => x.f), null, 2)); return; }
    console.log(`  ${files.length} most recent case file(s) in ${path.relative(os.homedir(), dir)}`);
    for (const { f } of files) {
      const first = fs.readFileSync(path.join(dir, f), 'utf8').split('\n').find((l) => /^\*\*Status:/.test(l)) || '';
      console.log(`    ${f}${first ? '  ' + first.replace(/\*\*/g, '').slice(0, 70) : ''}`);
    }
    return;
  }

  if (VERB === 'show') {
    const slug = opt('--case');
    if (!slug) { console.error('ps-case show: needs --case <slug>'); process.exit(2); }
    const p = casePath(root, slug);
    if (!fs.existsSync(p)) { console.error(`ps-case: no case file matching "${slug}"`); process.exit(1); }
    console.log(fs.readFileSync(p, 'utf8'));
    return;
  }

  if (VERB === 'open') {
    const name = opt('--name'); const phone = opt('--phone');
    const device = opt('--device', ''); const issue = opt('--issue', '');
    if (!name || !phone) { console.error('ps-case open: needs --name and --phone'); process.exit(2); }
    const slug = opt('--slug') || `${slugify(name)}-${slugify(device || 'device')}-${dateOnly()}`;
    const { cases } = ensureDirs(root);
    const file = path.join(cases, `${slug}.md`);
    const taskId = opt('--task-id') ? Number(opt('--task-id')) : null;
    const contactId = opt('--contact-id') ? Number(opt('--contact-id')) : null;

    if (fs.existsSync(file)) {
      console.log(`ps-case: ${path.relative(root, file)} already exists -- appending instead of overwriting`);
    } else {
      const doc = [
        `# ${name}${device ? ' — ' + device : ''}`,
        '',
        `**Status: OPEN — intake ${dateOnly()}**`,
        `**Customer:** ${name} — ${phone}`,
        device ? `**Device:** ${device}` : null,
        `**Work:** ${issue || '(to be assessed)'}`,
        taskId ? `**Task:** ${taskId}` : null,
        '',
        '## Timeline',
        `- **${dateOnly()}:** Intake recorded from \`${MACHINE}\`. ${issue || ''}`.trim(),
        '',
      ].filter((l) => l !== null).join('\n');
      fs.writeFileSync(file, doc, 'utf8');
      console.log(`  wrote ${path.relative(root, file)}`);
    }
    const rel = writeSyncRecord(root, { caseId: slug, name, phone, device, issue, taskId, contactId });
    console.log(`  wrote ${rel}  (source.machine=${MACHINE})`);
    return;
  }

  if (VERB === 'note' || VERB === 'status') {
    const slug = opt('--case');
    if (!slug) { console.error(`ps-case ${VERB}: needs --case <slug>`); process.exit(2); }
    const p = casePath(root, slug);
    if (!fs.existsSync(p)) { console.error(`ps-case: no case file matching "${slug}"`); process.exit(1); }
    let text = fs.readFileSync(p, 'utf8');

    if (VERB === 'note') {
      const body = opt('--text');
      if (!body) { console.error('ps-case note: needs --text "..."'); process.exit(2); }
      text = appendTimeline(text, `${body} [from ${MACHINE}]`);
      fs.writeFileSync(p, text, 'utf8');
      console.log(`  appended to ${path.relative(root, p)}`);
      return;
    }

    const status = opt('--status');
    if (!status) { console.error('ps-case status: needs --status "..."'); process.exit(2); }
    const note = opt('--note');
    text = setHeaderLine(text, 'Status', `${status} (${dateOnly()}, from ${MACHINE})`);
    text = appendTimeline(text, `Status → **${status}**${note ? '. ' + note : ''} [from ${MACHINE}]`);
    fs.writeFileSync(p, text, 'utf8');
    console.log(`  ${path.relative(root, p)}: status "${status}" (labelled from ${MACHINE})`);
    return;
  }

  console.error('ps-case: commands -> list | show | open | note | status');
  console.error('  ps-case open   --name "..." --phone "..." --device "..." --issue "..."');
  console.error('  ps-case note   --case <slug> --text "..."');
  console.error('  ps-case status --case <slug> --status "SOURCED" [--note "..."]');
  process.exit(2);
}

main();
