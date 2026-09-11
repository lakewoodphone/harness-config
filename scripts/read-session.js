#!/usr/bin/env node
/**
 * read-session.js — read a DSH session transcript from disk.
 *
 * WHY THIS EXISTS
 * The owner says "pull up that session and keep working". Doing that by hand took
 * reverse-engineering: the transcript is `session.v3.jsonl.zstd`, and it is NOT a
 * single zstd stream. It is one frame per appended event (~1,354 frames for a
 * 2.4 MB session), so `zstdDecompressSync(buffer)` silently returns only the
 * first 202-byte header frame and looks like an empty session. That cost real time
 * once; this file makes it cost nothing.
 *
 * USAGE
 *   node read-session.js --list [--project <substr>]        list sessions, newest first
 *   node read-session.js --tail <id|latest> [--lines 80]    the flow: prompts, replies, tool calls
 *   node read-session.js --raw  <id|latest> > out.jsonl     full transcript as plain JSONL
 *   node read-session.js --grep <id|latest> <regex>         matching events, compact
 *
 * <id> may be a session id, any unique prefix, or a substring like `d772db00`.
 * Transcripts live in $DSH_HOME/sessions/<slugified-cwd>/<session-id>/session.v3.jsonl.zstd
 * with per-session metadata in $DSH_HOME/storages/session_projcache/sessions/<id>.json
 * (which is where the title and the running preset live — the transcript's own header
 * records only the preset the session *started* with, and the two can differ after a
 * preset change, so prefer the projcache value).
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');

const DSH_HOME = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
const SESSIONS = path.join(DSH_HOME, 'sessions');
const PROJCACHE = path.join(DSH_HOME, 'storages', 'session_projcache', 'sessions');
const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

/** Decode every appended zstd frame, not just the first. */
function decodeAllFrames(file) {
  const buf = fs.readFileSync(file);
  const offsets = [];
  let i = 0;
  while ((i = buf.indexOf(ZSTD_MAGIC, i)) !== -1) { offsets.push(i); i += 4; }
  offsets.push(buf.length);
  const parts = [];
  let failed = 0;
  for (let k = 0; k < offsets.length - 1; k++) {
    let ok = false;
    // Try the tight frame first and widen on failure: a magic sequence can occur
    // by chance inside compressed data, and a widened window resynchronises.
    for (let j = k + 1; j < Math.min(k + 6, offsets.length); j++) {
      try {
        parts.push(zlib.zstdDecompressSync(buf.slice(offsets[k], offsets[j])));
        k = j - 1;
        ok = true;
        break;
      } catch (e) { /* widen */ }
    }
    if (!ok) failed++;
  }
  return { text: Buffer.concat(parts).toString('utf8'), frames: offsets.length - 1, failed };
}

function listSessions(filter) {
  if (!fs.existsSync(SESSIONS)) { console.error('no sessions dir at ' + SESSIONS); return; }
  const rows = [];
  for (const project of fs.readdirSync(SESSIONS)) {
    const dir = path.join(SESSIONS, project);
    if (!fs.statSync(dir).isDirectory()) continue;
    if (filter && !project.toLowerCase().includes(filter.toLowerCase())) continue;
    for (const s of fs.readdirSync(dir)) {
      const f = path.join(dir, s, 'session.v3.jsonl.zstd');
      if (!fs.existsSync(f)) continue;
      const st = fs.statSync(f);
      rows.push({ id: s.replace(/^session-/, ''), mtime: st.mtime, size: st.size, file: f });
    }
  }
  rows.sort((a, b) => b.mtime - a.mtime);
  for (const r of rows) {
    console.log(`${r.mtime.toISOString()}  ${String(Math.round(r.size / 1024)).padStart(8)} KB  ${r.id}`);
  }
}

function findSession(idOrSub) {
  if (!fs.existsSync(SESSIONS)) throw new Error('no sessions dir at ' + SESSIONS);
  const all = [];
  for (const project of fs.readdirSync(SESSIONS)) {
    const dir = path.join(SESSIONS, project);
    if (!fs.statSync(dir).isDirectory()) continue;
    for (const s of fs.readdirSync(dir)) {
      const f = path.join(dir, s, 'session.v3.jsonl.zstd');
      if (fs.existsSync(f)) all.push({ id: s.replace(/^session-/, ''), file: f, mtime: fs.statSync(f).mtimeMs });
    }
  }
  all.sort((a, b) => b.mtime - a.mtime);
  if (!idOrSub || idOrSub === 'latest') return all[0];
  const hits = all.filter((s) => s.id.startsWith(idOrSub) || s.id.includes(idOrSub));
  if (!hits.length) throw new Error('no session matching ' + idOrSub);
  if (hits.length > 1) console.error(`note: ${hits.length} matches, using the newest: ${hits[0].id}`);
  return hits[0];
}

function meta(id) {
  const p = path.join(PROJCACHE, `session-${id}.json`);
  if (!fs.existsSync(p)) return null;
  try {
    const j = JSON.parse(fs.readFileSync(p, 'utf8'));
    const rows = (j.record && j.record.rows) || {};
    const val = (k) => (rows[k] ? rows[k].val : undefined);
    return {
      preset: val('agentPreset'),
      title: val('title'),
      turns: val('sessionStats') && val('sessionStats').turns,
      started: j.record && j.record.identity ? new Date(j.record.identity.createdAt).toISOString() : undefined,
      cwd: j.record && j.record.identity ? j.record.identity.cwd : undefined,
    };
  } catch (e) { return null; }
}

function clip(s, n) {
  s = String(s == null ? '' : s).replace(/\s+/g, ' ');
  return s.length > n ? s.slice(0, n) + `…[${s.length}ch]` : s;
}

/** Condense one transcript event into a line a human (or an agent) can read. */
function describe(e) {
  const d = e.data || e;
  switch (e.type) {
    case 'user/message': {
      const t = d.text || (Array.isArray(d.content) ? d.content.map((c) => c.text || '').join(' ') : '') || JSON.stringify(d);
      return 'USER: ' + clip(t, 900);
    }
    case 'assistant/message': {
      // The payload nests the model message one level down on some events
      // ({turn, step, message:{role, content}}) and flat on others. Read both,
      // or the reply prints as an empty line and the transcript looks broken.
      const msg = d.message || d;
      const parts = [];
      const content = Array.isArray(msg.content) ? msg.content : null;
      if (content) {
        for (const c of content) {
          if (c.type === 'text') parts.push(clip(c.text, 900));
          else if (c.type === 'tool-call') parts.push(`[call ${c.name} ${clip(c.arguments, 300)}]`);
          else if (c.type === 'reasoning') parts.push(`[reasoning ${clip(c.text, 200)}]`);
          else parts.push('[' + c.type + ']');
        }
      } else if (msg.text) parts.push(clip(msg.text, 900));
      return 'ASSISTANT: ' + parts.join(' | ');
    }
    case 'tool/call': return '  CALL ' + (d.toolName || d.name) + ' ' + clip(typeof d.arguments === 'string' ? d.arguments : JSON.stringify(d.arguments), 400);
    case 'tool/result': return '  RESULT ' + clip(typeof d.result === 'string' ? d.result : JSON.stringify(d.result || d.content), 400);
    case 'turn/start': return '--- TURN START';
    case 'turn/end': return '--- TURN END';
    case 'todo/write': return '  TODO ' + clip(JSON.stringify(d.todos || d), 500);
    case 'deliverables/presented': return '  PRESENT ' + clip(JSON.stringify(d.files || d), 300);
    case 'agent-preset/selected': return 'PRESET ' + clip(JSON.stringify(d), 200);
    default: return null;
  }
}

const KEEP = new Set(['user/message', 'assistant/message', 'tool/call', 'tool/result', 'turn/start',
  'turn/end', 'todo/write', 'deliverables/presented', 'agent-preset/selected']);

function main() {
  const argv = process.argv.slice(2);
  const flag = (name, def) => {
    const i = argv.indexOf(name);
    return i === -1 ? def : argv[i + 1];
  };
  if (argv.includes('--list') || argv.length === 0) {
    listSessions(argv.includes('--project') ? flag('--project') : undefined);
    return 0;
  }
  const idArg = (argv.includes('--tail') || argv.includes('--raw') || argv.includes('--grep') || argv.includes('--meta'))
    ? (argv[argv.findIndex((a) => a.startsWith('--')) + 1] || 'latest')
    : argv[0];
  const s = findSession(idArg);
  const m = meta(s.id);
  if (argv.includes('--meta')) {
    console.log(JSON.stringify({ id: s.id, file: s.file, ...(m || {}) }, null, 2));
    return 0;
  }
  const { text, frames, failed } = decodeAllFrames(s.file);
  const events = text.split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch (e) { return null; } }).filter(Boolean);

  if (argv.includes('--raw')) { process.stdout.write(text); return 0; }

  if (argv.includes('--grep')) {
    const i = argv.indexOf('--grep');
    const re = new RegExp(argv[i + 2] || argv[i + 1], 'i');
    let n = 0;
    for (const e of events) {
      const line = describe(e);
      if (line && re.test(line)) { console.log(line); n++; }
      else if (!line && re.test(JSON.stringify(e))) { console.log(clip(JSON.stringify(e), 500)); n++; }
    }
    console.error(`${n} matching events of ${events.length}`);
    return 0;
  }

  // default: --tail
  const limit = parseInt(flag('--lines', '80'), 10);
  console.error(`session ${s.id}  frames=${frames} failed=${failed} events=${events.length}`);
  if (m) console.error(`preset=${m.preset}  turns=${m.turns}  started=${m.started}  title=${m.title || '(untitled)'}`);
  const rows = events.map((e, i) => ({ i, t: e.type, s: KEEP.has(e.type) ? describe(e) : null })).filter((r) => r.s);
  for (const r of rows.slice(-limit)) console.log(r.i + ' ' + r.s);
  return 0;
}

try {
  process.exit(main());
} catch (err) {
  console.error('error: ' + err.message);
  process.exit(1);
}
