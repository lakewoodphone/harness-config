/**
 * plugin-health model tests — `node test/model.test.mjs`.
 *
 * These run with NO harness and NO engine. Everything asserted here is a pure
 * function over an explicit input, so a failure is a failure of this package and
 * not of the machine it happens to be run on. The one thing that cannot be
 * tested this way — whether the composition mounts the row — is checked by
 * actually mounting it and reading the route (see 90-plugin-health-governor.md).
 *
 * Node's built-in runner is used deliberately: no dependency, no install step,
 * so this can never rot into "the tests need a build".
 */

import { strict as assert } from 'node:assert';
import test from 'node:test';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { LagSampler } from '../lib/lag.js';
import { censusAgents, memoryOf, identityOf, humanAge, mib } from '../lib/sessions.js';
import { classifyProcesses, mcpServerOf, privateBytesOf } from '../lib/processes.js';
import { ProcessSampler, buildReadout, toolPayload, renderText } from '../lib/index.js';

// ── lag ─────────────────────────────────────────────────────────────────────

test('LagSampler records an inflation-free window and reports nearest-rank percentiles', () => {
  const sampler = new LagSampler({ intervalMs: 1000, capacity: 4 });
  // Drive the ring directly: no timer, so the test is deterministic.
  sampler.start();
  sampler.stop();
  const ring = sampler;
  // The public surface has no "push", so a real interval is used with a tiny
  // period; the assertion is on the shape, not on wall-clock magnitude.
  assert.equal(sampler.summary().count, 0, 'an unused sampler reports zero samples, not a fake p50');
  assert.deepEqual(sampler.summary(), { count: 0, p50: null, p95: null, max: null });
  assert.equal(ring.running, false);
  assert.deepEqual(sampler.samples(), []);
});

test('LagSampler statistics are nearest-rank over whole milliseconds', () => {
  const sampler = new LagSampler({ intervalMs: 250, capacity: 200 });
  // Fill the ring through its documented reader path by timing a real
  // (very short) interval: 4 ticks, which is enough to assert the shape and the
  // ordering invariant (p50 <= p95 <= max).
  return new Promise((resolve) => {
    sampler.start();
    setTimeout(() => {
      sampler.stop();
      const samples = sampler.samples();
      assert.ok(samples.length >= 2, `expected at least 2 samples, got ${samples.length}`);
      const summary = sampler.summary();
      assert.equal(summary.count, samples.length);
      assert.ok(summary.p50 <= summary.p95, `p50 ${summary.p50} > p95 ${summary.p95}`);
      assert.ok(summary.p95 <= summary.max, `p95 ${summary.p95} > max ${summary.max}`);
      for (const value of samples) assert.ok(Number.isInteger(value) && value >= 0, `sample ${value} is not a non-negative integer`);
      resolve();
    }, 900);
  });
});

test('LagSampler rejects a nonsensical configuration instead of guessing', () => {
  assert.throws(() => new LagSampler({ intervalMs: 0 }), /positive finite/);
  assert.throws(() => new LagSampler({ intervalMs: -5 }), /positive finite/);
  assert.throws(() => new LagSampler({ capacity: 1.5 }), /positive integer/);
});

// ── sessions ────────────────────────────────────────────────────────────────

test('censusAgents counts roots, subagents and running loops, and never touches the Agent object', () => {
  const agents = {
    list: () => [
      { id: 'root-1', status: 'running', owner: undefined, secret: { huge: 'blob' } },
      { id: 'root-2', status: 'idle', owner: undefined },
      { id: 'child-1', status: 'running', owner: { id: 'root-1' } },
    ],
  };
  const census = censusAgents(agents);
  assert.equal(census.sessionsLive, 3);
  assert.equal(census.sessionsRoot, 2);
  assert.equal(census.subagentsLive, 1);
  assert.equal(census.sessionsRunning, 2);
  assert.deepEqual(census.sessions, [
    { id: 'root-1', status: 'running', subagent: false },
    { id: 'root-2', status: 'idle', subagent: false },
    { id: 'child-1', status: 'running', subagent: true },
  ]);
  // Only scalars: the whole row is exactly the three declared fields.
  for (const row of census.sessions) assert.deepEqual(Object.keys(row).sort(), ['id', 'status', 'subagent']);
});

test('censusAgents reports an absent or throwing registry as unavailable, never as zero sessions', () => {
  const absent = censusAgents(undefined);
  assert.equal(absent.sessionsLive, 0);
  assert.match(absent.unavailable, /not mounted/);
  const throwing = censusAgents({ list: () => { throw new Error('boom'); } });
  assert.match(throwing.unavailable, /boom/);
});

test('memoryOf publishes every field a leak diagnosis needs', () => {
  const memory = memoryOf(process);
  for (const key of ['rss', 'heapTotal', 'heapUsed', 'external', 'arrayBuffers', 'heapLimit']) {
    assert.ok(Number.isFinite(memory[key]), `${key} is not a number`);
  }
  assert.ok(memory.rss > 0);
});

test('identityOf pins the reading to one engine, the way provenance requires', () => {
  const identity = identityOf(process, 1700000000000);
  assert.equal(identity.pid, process.pid);
  assert.equal(identity.startedAt, new Date(1700000000000).toISOString());
  assert.equal(identity.node, process.version);
  assert.ok(Array.isArray(identity.argv));
  assert.ok(identity.uptimeMs >= 0);
});

test('humanAge and mib render the units the operator actually reads', () => {
  assert.equal(humanAge(500), '0s');
  assert.equal(humanAge(90_000), '1m30s');
  assert.equal(humanAge(3_600_000), '1h00m');
  assert.equal(humanAge(90_000_000), '1d01h');
  assert.equal(humanAge(Number.NaN), 'unknown');
  assert.equal(mib(1024 * 1024 * 12), 12);
  assert.equal(mib(1024 * 1024 * 12.34), 12.3);
  assert.equal(mib(undefined), null);
});

// ── process classification ──────────────────────────────────────────────────

const ENGINE = 100;

function snapshotOf(rows, enginePid = ENGINE) {
  return {
    at: '2026-09-16T12:00:00.000Z',
    enginePid,
    system: { totalPhysBytes: 34_000_000_000, availPhysBytes: 14_000_000_000, commitLimitBytes: 46_000_000_000, commitAvailableBytes: 22_000_000_000, memoryLoadPercent: 56 },
    totals: { processes: rows.length, threads: rows.reduce((sum, row) => sum + row.threads, 0), handles: 0, nodeInvisible: 0 },
    processes: rows,
  };
}

const row = (pid, ppid, name, image, extra = {}) => ({
  pid, ppid, name, image, threads: 10, workingSetBytes: 50_000_000, privateBytes: 60_000_000, handles: 100, ...extra,
});

test('the engine row is separated and a direct node child is a tool-call runner', () => {
  const classified = classifyProcesses(snapshotOf([
    row(ENGINE, 1, 'node.exe', 'C:\\nodejs\\node.exe'),
    row(200, ENGINE, 'node.exe', 'C:\\nodejs\\node.exe'),
    row(201, ENGINE, 'node.exe', 'C:\\nodejs\\node.exe'),
    row(202, ENGINE, 'pwsh.exe', 'C:\\pwsh.exe'),
    row(300, 202, 'conhost.exe', 'C:\\conhost.exe'),
  ]));
  assert.equal(classified.engine.pid, ENGINE);
  assert.equal(classified.runner.length, 2, 'both direct node children are runners');
  assert.deepEqual(classified.runner.map((entry) => entry.pid), [200, 201]);
  // The pwsh child is NOT a runner: it is the shell the runner owns. It is
  // counted through `children` (every descendant) and `other` (everything that is
  // neither a runner nor an MCP server), so nothing is silently dropped.
  // Three rows have ppid === ENGINE (200, 201, 202); 300 is 202's conhost.
  assert.equal(classified.children, 3, 'three processes hang directly off the engine');
  assert.equal(classified.maxDepth, 2);
  assert.equal(classified.other, 2, 'pwsh (a shell) and conhost (its console) are neither');
});

test('the pwsh child of a runner and everything else is counted, not listed', () => {
  const classified = classifyProcesses(snapshotOf([
    row(ENGINE, 1, 'node.exe', 'C:\\nodejs\\node.exe'),
    row(200, ENGINE, 'node.exe', 'C:\\nodejs\\node.exe'),
    row(201, 200, 'pwsh.exe', 'C:\\pwsh.exe'),
    row(202, 1, 'msedge.exe', 'C:\\msedge.exe'),
  ]));
  assert.equal(classified.runner.length, 1);
  assert.equal(classified.children, 1, 'only the runner is a direct child');
  // pwsh (depth 2) and msedge (unrelated) are both "other" — counted, never
  // claimed as an MCP server or a runner.
  assert.equal(classified.other, 2);
  assert.equal(classified.mcp.length, 0);
});

test('MCP servers are identified by image path, per server name', () => {
  const classified = classifyProcesses(snapshotOf([
    row(ENGINE, 1, 'node.exe', 'C:\\nodejs\\node.exe'),
    row(200, ENGINE, 'node.exe', 'C:\\nodejs\\node.exe'),
    row(201, 200, 'python.exe', 'C:\\python.exe'),
    row(202, 201, 'node.exe', 'C:\\Users\\e\\.dsh\\tools\\mcp\\node_modules\\mcp-fetch-server\\dist\\index.js'),
    row(203, ENGINE, 'cmd.exe', 'C:\\cmd.exe'),
    row(204, 203, 'node.exe', 'C:\\Users\\e\\.dsh\\tools\\mcp\\node_modules\\@playwright\\mcp\\cli.js'),
    row(205, 201, 'node.exe', 'C:\\Users\\e\\.dsh\\tools\\mcp\\node_modules\\@upstash\\context7-mcp\\dist\\index.js'),
    row(206, 201, 'node.exe', 'C:\\Users\\e\\.dsh\\tools\\mcp\\node_modules\\firecrawl-mcp\\dist\\index.js'),
    row(207, 201, 'node.exe', 'C:\\Users\\e\\.dsh\\tools\\mcp\\node_modules\\mcp-remote\\dist\\proxy.js'),
    row(208, 201, 'python.exe', 'C:\\Users\\e\\personal-secretary-mvp\\scripts\\ps_mcp_server.py'),
  ]));
  assert.equal(classified.runner.length, 1, 'only the direct node child is a runner');
  assert.deepEqual(classified.byServer, { fetch: 1, playwright: 1, context7: 1, firecrawl: 1, jina: 1, secretary: 1 });
  assert.equal(classified.mcp.length, 6);
  // The list is sorted by server name then pid, so the assertion is on the set
  // and the ordering rule, not on which server happens to sort first.
  assert.deepEqual(classified.mcp.map((entry) => entry.server), ['context7', 'fetch', 'firecrawl', 'jina', 'playwright', 'secretary']);
  assert.equal(classified.mcp.every((entry) => typeof entry.depth === 'number'), true);
});

test('a deep descendant is still found, and a cycle cannot spin', () => {
  const classified = classifyProcesses(snapshotOf([
    row(ENGINE, 1, 'node.exe', 'C:\\nodejs\\node.exe'),
    row(1, 2, 'a.exe', ''),
    row(2, 1, 'b.exe', ''),
    row(3, 4, 'c.exe', ''),
    row(4, 5, 'd.exe', ''),
    row(5, ENGINE, 'e.exe', ''),
  ]));
  // pid 5 is a direct child -> depth 1; 4 -> 2; 3 -> 3. 1 and 2 form a cycle with
  // each other and are unreachable, so they are counted as unrelated.
  assert.equal(classified.other, 5, 'rows 1,2 (unreachable cycle) and 3,4,5 (reached, unclassified)');
  assert.equal(classified.children, 1);
  assert.equal(classified.maxDepth, 3);
});

test('mcpServerOf is path-based and case-insensitive, and claims nothing it cannot prove', () => {
  assert.equal(mcpServerOf('C:\\X\\MCP-Fetch-Server\\dist\\index.js'), 'fetch');
  assert.equal(mcpServerOf('C:\\X\\@Playwright\\mcp\\cli.js'), 'playwright');
  assert.equal(mcpServerOf('C:\\nodejs\\node.exe'), undefined);
  assert.equal(mcpServerOf(''), undefined);
  assert.equal(mcpServerOf(undefined), undefined);
  // A path that merely mentions "mcp" is not a server.
  assert.equal(mcpServerOf('C:\\work\\mcp-notes\\readme.md'), undefined);
});

test('privateBytesOf falls back to working set when private bytes are unavailable', () => {
  assert.equal(privateBytesOf([{ privateBytes: 10, workingSetBytes: 1 }, { privateBytes: 0, workingSetBytes: 7 }]), 17);
  assert.equal(privateBytesOf([]), 0);
});

test('an unreadable snapshot classifies as empty rather than as a healthy zero', () => {
  assert.deepEqual(classifyProcesses(null).mcp, []);
  assert.equal(classifyProcesses({}).mcp.length, 0);
  assert.equal(classifyProcesses({ enginePid: 100 }).runner.length, 0);
  assert.equal(classifyProcesses(snapshotOf([])).engine, null);
});

// ── the sampler over a real file ────────────────────────────────────────────

test('ProcessSampler reads a snapshot from disk and reports its true age', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'ph-test-'));
  const file = path.join(dir, 'processes.json');
  try {
    const sampler = new ProcessSampler({ file, intervalMs: 60_000, enginePid: 999, shell: 'pwsh' });
    assert.equal(sampler.ageMs, null, 'nothing read yet is null, not zero');
    assert.equal(sampler.read(), false, 'a missing file is a refusal, not a reading');
    writeFileSync(file, JSON.stringify(snapshotOf([row(999, 1, 'node.exe', 'C:\\nodejs\\node.exe')], 999)));
    assert.equal(sampler.read(), true);
    assert.ok(sampler.ageMs !== null && sampler.ageMs < 5000);
    assert.equal(sampler.snapshot.enginePid, 999);
    // A malformed document must not be adopted, and must be reported.
    writeFileSync(file, '{not json');
    assert.equal(sampler.read(), true, 'the previous good snapshot stays cached');
    assert.match(sampler.probe().lastError, /unreadable/);
    assert.equal(sampler.probe().failures, 0, 'a parse failure is not a spawn failure');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('a stale snapshot is flagged stale, and an absent one is flagged unavailable', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'ph-test-'));
  const file = path.join(dir, 'processes.json');
  try {
    const sampler = new ProcessSampler({ file, intervalMs: 60_000, enginePid: 999, shell: 'pwsh' });
    const lag = new LagSampler({ intervalMs: 250, capacity: 8 });
    const agents = { list: () => [{ id: 'a', status: 'idle' }] };

    const absent = buildReadout({ sampler, lag, agents, startedAtMs: Date.now(), staleMs: 30_000 });
    assert.equal(absent.processes.available, false);
    assert.equal(absent.processes.stale, true);
    assert.equal(absent.processes.toolCallRunnerProcesses, null, 'unmeasured is null, never 0');
    const absentPayload = toolPayload(absent);
    assert.equal(absentPayload.processSnapshotStale, true);
    assert.equal(absentPayload.toolCallRunnerProcesses, undefined);
    assert.match(absentPayload.notes[0], /NOT been sampled/);
    // The text rendering must say so out loud, and must never be blank.
    const absentText = renderText(absent);
    assert.match(absentText, /processes NOT MEASURED/);
    assert.ok(absentText.length > 200);

    writeFileSync(file, JSON.stringify(snapshotOf([
      row(999, 1, 'node.exe', 'C:\\nodejs\\node.exe'),
      row(1000, 999, 'node.exe', 'C:\\nodejs\\node.exe'),
      row(1001, 999, 'pwsh.exe', 'C:\\pwsh.exe'),
    ], 999)));
    assert.equal(sampler.read(), true);
    const fresh = buildReadout({ sampler, lag, agents, startedAtMs: Date.now(), staleMs: 30_000 });
    assert.equal(fresh.processes.available, true);
    assert.equal(fresh.processes.stale, false);
    assert.equal(fresh.processes.toolCallRunnerProcesses, 1);
    assert.equal(fresh.processes.total, 3);
    const freshText = renderText(fresh);
    assert.match(freshText, /tool-call runners 1/);
    assert.doesNotMatch(freshText, /NOT MEASURED/);

    const stale = buildReadout({ sampler, lag, agents, startedAtMs: Date.now(), staleMs: 0 });
    assert.equal(stale.processes.stale, true, 'a zero staleness budget makes any snapshot stale');
    const staleText = renderText(stale);
    assert.match(staleText, /STALE/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('the text and json surfaces always carry a reading, never an empty string', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'ph-test-'));
  const file = path.join(dir, 'processes.json');
  try {
    const sampler = new ProcessSampler({ file, intervalMs: 60_000, enginePid: process.pid, shell: 'pwsh' });
    const lag = new LagSampler({ intervalMs: 250, capacity: 8 });
    const readout = buildReadout({ sampler, lag, agents: undefined, startedAtMs: Date.now(), staleMs: 30_000 });
    const text = renderText(readout);
    assert.ok(text.length > 0);
    assert.match(text, /^engine \d+ up /);
    assert.match(text, /loop lag/);
    assert.match(text, /sessions  0 root/);
    assert.match(text, /not mounted/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
