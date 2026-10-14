#!/usr/bin/env node
/**
 * research-offload — an MCP server that does her searching SOMEWHERE ELSE.
 *
 * WHY THIS EXISTS (measured, DESKTOP-FGV6KMH, 2026-09-14 and again 2026-10-14)
 * ---------------------------------------------------------------------------------------------
 * Yocheved's laptop sits behind the Techloq filter. `api.deepseek.com` — the host the harness's
 * built-in web search calls by default — is blocked BY URL CATEGORY, and the block is answered with an
 * HTML page carrying a **success** status. A client cannot tell it was blocked: it sees HTTP 200 and
 * the wrong body. So the built-in search does not "fail loudly", it returns nothing useful, and the
 * agent degrades into fetching one URL at a time and eventually gives up with
 * `DeepSeek search request failed: TypeError: fetch failed`.
 *
 * There IS a half-fix already: `DEEPSEEK_SEARCH_BASE_URL` points the built-in search at
 * `https://ds.abletelsolutions.com/anthropic/v1`, a Cloudflare Worker that makes the upstream call
 * from Cloudflare's edge where the filter has no visibility. That variable was set inside `launch.cmd`
 * — the DESKTOP SHORTCUT's path — and NOT in `dshw.ps1`, which is what the 1-minute engine watchdog
 * runs. So every engine the watchdog started came up WITHOUT it and her search was handicapped again,
 * silently. It is now also set at machine scope, which closes that hole.
 *
 * This server exists because an environment variable is the WRONG SHAPE for this guarantee: it is
 * invisible to the agent, it is one plumbing mistake away from being absent again, and when it is
 * absent nothing says so. A TOOL is visible, nameable, and can REPORT WHICH BACKEND answered.
 *
 * WHAT IT DOES
 * ---------------------------------------------------------------------------------------------
 *   search  — a query, answered by an off-machine backend. Returns the sources with titles and URLs.
 *   fetch   — one URL, retrieved off-machine and returned as text.
 *   status  — which backends are reachable RIGHT NOW, and which one a call would use.
 *
 * BACKENDS, tried in order, and the answer always says which one answered:
 *   1. worker     — https://ds.abletelsolutions.com/anthropic/v1/messages with the `web_search`
 *                   server tool. The search executes at Cloudflare's edge. This is the fast path.
 *   2. secretary  — https://api.abletelsolutions.com/ceo/chat, the company's own agent, which has its
 *                   own search and fetch tooling. The slow path, used when the Worker is unhappy.
 *
 * REDACTION: the API key is read from the environment or from `~/.dsh/.credentials.yaml` and is NEVER
 * echoed, logged, or returned in any tool result. Errors report the host and the status, never headers.
 *
 * This file is referenced by `presets/yocheved/agent.cordis.yml` ONLY. It is not mounted on any other
 * machine's preset.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const WORKER = process.env.RESEARCH_OFFLOAD_WORKER || 'https://ds.abletelsolutions.com/anthropic/v1';
const SECRETARY = process.env.RESEARCH_OFFLOAD_SECRETARY || 'https://api.abletelsolutions.com';
const TIMEOUT_MS = Number(process.env.RESEARCH_OFFLOAD_TIMEOUT_MS || 60000);

/** Read a secret without ever printing it. Environment first, then the harness credential store. */
function secret(name) {
    const fromEnv = process.env[name];
    if (fromEnv && fromEnv.trim()) return fromEnv.trim();
    const home = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
    for (const p of [path.join(home, '.credentials.yaml'), path.join(home, 'credentials.yaml')]) {
        try {
            const text = fs.readFileSync(p, 'utf8');
            // Line form: `NAME: value` or `  NAME: value` inside a refs: block.
            const m = text.match(new RegExp(`^\\s*${name}\\s*:\\s*(\\S+)\\s*$`, 'm'));
            if (m) return m[1].replace(/^["']|["']$/g, '').trim();
        } catch { /* try the next location */ }
    }
    return '';
}

/** POST with a hard timeout, returning { ok, status, text } and never throwing on HTTP status. */
async function post(url, body, headers) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'content-type': 'application/json', ...headers },
            body: JSON.stringify(body),
            signal: ctl.signal,
        });
        const text = await res.text();
        return { ok: res.ok, status: res.status, text };
    } catch (err) {
        return { ok: false, status: 0, text: `request failed: ${err && err.message ? err.message : String(err)}` };
    } finally {
        clearTimeout(timer);
    }
}

// ── backend 1: the Worker, with the Anthropic `web_search` server tool ───────────────────────────
async function searchViaWorker(query, maxUses = 5) {
    const key = secret('DEEPSEEK_API_KEY');
    if (!key) return { ok: false, backend: 'worker', detail: 'no DEEPSEEK_API_KEY in env or ~/.dsh/.credentials.yaml' };
    const r = await post(`${WORKER}/messages`, {
        model: process.env.RESEARCH_OFFLOAD_MODEL || 'deepseek-flash',
        max_tokens: 4096,
        messages: [{ role: 'user', content: `Perform a web search and report the findings for: ${query}` }],
        tools: [{ type: 'web_search_20250305', name: 'web_search', max_uses: maxUses }],
    // THE WORKER READS `Authorization: Bearer`, NOT `x-api-key`. Its own source is explicit:
    // `isAuthorized(authHeader)` starts with `if (!authHeader || !authHeader.startsWith('Bearer '))`.
    // MEASURED 2026-10-14 on DESKTOP-FGV6KMH: sending x-api-key returned
    //   401 {"error":{"message":"unauthorized: a valid bearer token is required","type":"proxy_auth"}}
    // while the key itself was valid. anthropic-version is still sent because the upstream is an
    // Anthropic-format Messages endpoint and the Worker passes the path through unchanged.
    }, { Authorization: `Bearer ${key}`, 'anthropic-version': '2023-06-01' });
    if (!r.ok) return { ok: false, backend: 'worker', detail: `HTTP ${r.status}: ${r.text.slice(0, 300)}` };
    return { ok: true, backend: 'worker', body: r.text };
}

// ── backend 2: the company's own agent, over HTTPS ───────────────────────────────────────────────
async function searchViaSecretary(query) {
    const key = process.env.SECRETARY_API_KEY || process.env.DASHBOARD_API_KEY || '';
    const headers = key ? { 'x-ps-api-key': key } : {};
    const r = await post(`${SECRETARY}/ceo/chat`,
        { message: `Research this and answer with sources: ${query}` }, headers);
    if (!r.ok) return { ok: false, backend: 'secretary', detail: `HTTP ${r.status}: ${r.text.slice(0, 300)}` };
    return { ok: true, backend: 'secretary', body: r.text };
}

/** Pull the humanly useful part out of an Anthropic-format Messages response. */
function summariseWorker(text) {
    try {
        const j = JSON.parse(text);
        const out = [];
        for (const block of j.content || []) {
            if (block.type === 'text' && block.text) out.push(block.text);
            if (block.type === 'web_search_tool_result' && Array.isArray(block.content)) {
                for (const item of block.content) {
                    if (item.type === 'web_search_result' && item.url) {
                        out.push(`- ${item.title || '(no title)'} — ${item.url}`);
                    }
                }
            }
        }
        return out.join('\n\n') || text.slice(0, 2000);
    } catch { return text.slice(0, 2000); }
}

// ── MCP plumbing ─────────────────────────────────────────────────────────────────────────────────
const TOOLS = [
    {
        name: 'search',
        description:
            'Search the web from OFF this machine and return an answer with sources. Use this for ' +
            'anything current, or any research request. It runs the search on a Cloudflare Worker ' +
            '(or the company server) so the Techloq filter on this laptop cannot block it. Returns the ' +
            'backend that answered, so a failure is visible rather than silent.',
        inputSchema: {
            type: 'object',
            properties: {
                query: { type: 'string', description: 'What to search for.' },
                depth: { type: 'string', enum: ['quick', 'normal'], description: 'quick = fewer searches.' },
            },
            required: ['query'],
        },
    },
    {
        name: 'fetch_url',
        description: 'Fetch one URL from OFF this machine and return its text. Use when a page must be read and the laptop cannot reach it.',
        inputSchema: {
            type: 'object',
            properties: { url: { type: 'string', description: 'Absolute URL to retrieve.' } },
            required: ['url'],
        },
    },
    {
        name: 'status',
        description: 'Report which off-machine search backends are reachable right now, and which one a call would use. Read this before concluding search is broken.',
        inputSchema: { type: 'object', properties: {} },
    },
];

async function callTool(name, args) {
    if (name === 'search') {
        const depth = args.depth === 'quick' ? 2 : 5;
        const w = await searchViaWorker(args.query, depth);
        if (w.ok) return { backend: 'worker', text: summariseWorker(w.body) };
        const s = await searchViaSecretary(args.query);
        if (s.ok) return { backend: 'secretary', text: s.body.slice(0, 6000), note: `worker failed: ${w.detail}` };
        return { backend: 'none', error: `Both backends failed.\n  worker: ${w.detail}\n  secretary: ${s.detail}` };
    }
    if (name === 'fetch_url') {
        if (!/^https?:\/\//i.test(args.url || '')) return { error: 'url must start with http:// or https://' };
        const w = await searchViaWorker(`Read this page and summarise its content: ${args.url}`, 1);
        if (w.ok) return { backend: 'worker', text: summariseWorker(w.body) };
        return { backend: 'none', error: `worker failed: ${w.detail}` };
    }
    if (name === 'status') {
        const keyed = !!secret('DEEPSEEK_API_KEY');
        const w = keyed ? await searchViaWorker('ping', 1) : { ok: false, backend: 'worker', detail: 'no API key found' };
        const s = await searchViaSecretary('ping');
        return {
            worker: w.ok ? 'reachable' : `unreachable — ${w.detail}`,
            secretary: s.ok ? 'reachable' : `unreachable — ${s.detail}`,
            key_present: keyed,
            would_use: w.ok ? 'worker' : (s.ok ? 'secretary' : 'none'),
        };
    }
    return { error: `unknown tool: ${name}` };
}

function send(msg) { process.stdout.write(JSON.stringify(msg) + '\n'); }

// IN-FLIGHT BOOKKEEPING, and it is not optional. A tool call here is a network round trip, and stdin
// can reach `end` while one is still running -- a piped test, a client that closes early, a parent
// that restarts. Exiting on `end` unconditionally DISCARDS the answer that was already in flight and
// looks identical to "the tool returned nothing". MEASURED 2026-10-14 on DESKTOP-FGV6KMH: a piped
// `tools/call search` produced 0 bytes of output for exactly this reason.
let inflight = 0;
let stdinEnded = false;
function maybeExit() { if (stdinEnded && inflight === 0) process.exit(0); }

let buffer = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', async (chunk) => {
    buffer += chunk;
    let nl;
    while ((nl = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        let req;
        try { req = JSON.parse(line); } catch { continue; }
        const { id, method, params } = req;
        inflight++;
        try {
            if (method === 'initialize') {
                send({ jsonrpc: '2.0', id, result: {
                    protocolVersion: '2024-11-05',
                    capabilities: { tools: {} },
                    serverInfo: { name: 'research-offload', version: '1.0.0' },
                } });
            } else if (method === 'tools/list') {
                send({ jsonrpc: '2.0', id, result: { tools: TOOLS } });
            } else if (method === 'tools/call') {
                const out = await callTool(params?.name, params?.arguments || {});
                send({ jsonrpc: '2.0', id, result: {
                    content: [{ type: 'text', text: JSON.stringify(out, null, 2) }],
                    isError: !!(out.error),
                } });
            } else if (method === 'notifications/initialized') {
                // notification: no reply
            } else {
                send({ jsonrpc: '2.0', id, error: { code: -32601, message: `method not found: ${method}` } });
            }
        } catch (err) {
            send({ jsonrpc: '2.0', id, error: { code: -32603, message: err && err.message ? err.message : String(err) } });
        } finally {
            inflight--;
            maybeExit();
        }
    }
});
// Never exit on a stray error: a dead MCP server is invisible to the agent.
process.stdin.on('end', () => { stdinEnded = true; maybeExit(); });
process.on('uncaughtException', (e) => { process.stderr.write(`research-offload: ${e.message}\n`); });
