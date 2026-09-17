/**
 * Unit tests for the mesh HTTP transport's pure and bounded halves.
 *
 * WHAT THESE PROVE, AND WHAT THEY CANNOT
 * They prove the parts that decide whether a request is served at all: the MAC scheme and its
 * replay ledger, bounded intake, the one-run-at-a-time slot, the timeout, and the exact wire
 * contract of a refusal. They cannot prove the transport, because the transport is a real engine
 * on a real node answering a real dispatcher — that is `bin/mesh-dispatch.mjs` against a live
 * node, and it is recorded in docs/mesh/83-http-transport.md §6.
 */

import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { MeshAuth, newNonce, sign, signatureMatches } from '../lib/auth.js';
import { IntakeError, isJsonContentType, parseJsonObject, readBoundedBody } from '../lib/body.js';
import { createMeshHttp, defaultSecretFile, locateDshBin, VERSION } from '../lib/index.js';
import { deriveConcurrencyLimit } from '../lib/concurrency.js';
import { createNodeIdentity, labelFromDnsName } from '../lib/node-identity.js';
import { childArgv, composeTask, OneShotRunner } from '../lib/runner.js';
import { forgetSecret, loadSecret, parseEnvText } from '../lib/secret.js';

const SECRET = 'o2-test-secret-0123456789abcdef';
const HERE = process.cwd();

/** A secret file on disk, outside the repo, with the shape `/etc/dsh-mesh.env` has. */
function secretFile({ value = SECRET, key = 'MESH_HTTP_SECRET' } = {}) {
  const dir = mkdtempSync(path.join(tmpdir(), 'mesh-http-test-'));
  const file = path.join(dir, 'dsh-mesh.env');
  writeFileSync(file, `# mesh transport v2 shared secret\n${key}=${value}\n`, { mode: 0o600 });
  return { dir, file };
}

// ---------------------------------------------------------------------------
// the MAC
// ---------------------------------------------------------------------------

test('a signed body verifies; a body altered by one byte does not', () => {
  const { dir, file } = secretFile();
  const auth = new MeshAuth({ resolveSecret: () => loadSecret(file) });
  const body = Buffer.from(JSON.stringify({ prompt: 'say hi' }), 'utf8');
  const headers = MeshAuth.headersFor({ secret: SECRET, body });
  assert.deepEqual(auth.verify({ headers, body }), { ok: true, timestampMs: Number(headers['x-mesh-timestamp']) * 1000 });

  const tampered = Buffer.from(JSON.stringify({ prompt: 'say hi.' }), 'utf8');
  const verdict = auth.verify({ headers, body: tampered });
  assert.equal(verdict.ok, false);
  assert.equal(verdict.status, 401);
  assert.equal(verdict.reason, 'bad-signature');
  assert.equal(verdict.authenticated, false);
  rmSync(dir, { recursive: true, force: true });
});

test('a timestamp outside the window is refused even with a correct MAC', () => {
  const { dir, file } = secretFile();
  const now = 1_800_000_000_000;
  const auth = new MeshAuth({ resolveSecret: () => loadSecret(file), skewSeconds: 120, nowMs: () => now });
  const body = Buffer.from('{"prompt":"x"}', 'utf8');
  const stale = MeshAuth.headersFor({ secret: SECRET, body, timestamp: Math.floor(now / 1000) - 121 });
  const verdict = auth.verify({ headers: stale, body });
  assert.equal(verdict.reason, 'outside-window');
  // one second inside the window is accepted, so the bound is where it says it is
  const fresh = MeshAuth.headersFor({ secret: SECRET, body, timestamp: Math.floor(now / 1000) - 119 });
  assert.equal(auth.verify({ headers: fresh, body }).ok, true);
  rmSync(dir, { recursive: true, force: true });
});

test('a replayed request is refused even though its MAC is valid — the window is not a replay hole', () => {
  const { dir, file } = secretFile();
  const auth = new MeshAuth({ resolveSecret: () => loadSecret(file) });
  const body = Buffer.from('{"prompt":"x"}', 'utf8');
  const headers = MeshAuth.headersFor({ secret: SECRET, body, nonce: newNonce() });
  assert.equal(auth.verify({ headers, body }).ok, true);
  const second = auth.verify({ headers, body });
  assert.equal(second.ok, false);
  assert.equal(second.reason, 'replayed');
  // `authenticated: true` on a replay refusal: the caller DID hold the secret, so a dispatcher
  // must not treat this the way it treats "this node has no route".
  assert.equal(second.authenticated, true);
  rmSync(dir, { recursive: true, force: true });
});

test('an unsigned or malformed request never reaches the body parser', () => {
  const { dir, file } = secretFile();
  const auth = new MeshAuth({ resolveSecret: () => loadSecret(file) });
  const body = Buffer.from('{"prompt":"x"}', 'utf8');
  for (const [name, headers] of [
    ['no headers at all', {}],
    ['timestamp only', { 'x-mesh-timestamp': '1800000000' }],
    ['nonce missing', { 'x-mesh-timestamp': '1800000000', 'x-mesh-signature': 'a'.repeat(64) }],
    ['signature not hex', { 'x-mesh-timestamp': '1800000000', 'x-mesh-nonce': 'abcdefgh', 'x-mesh-signature': 'zz'.repeat(32) }],
    ['timestamp not a number', { 'x-mesh-timestamp': 'now', 'x-mesh-nonce': 'abcdefgh', 'x-mesh-signature': 'a'.repeat(64) }],
  ]) {
    const verdict = auth.verify({ headers, body });
    assert.equal(verdict.ok, false, name);
    assert.equal(verdict.status, 401, name);
  }
  rmSync(dir, { recursive: true, force: true });
});

test('a node with no secret refuses with 503, not 401 — "no route/secret" is not "wrong signature"', () => {
  const auth = new MeshAuth({ resolveSecret: () => loadSecret(path.join(tmpdir(), 'definitely-not-here', 'dsh-mesh.env')) });
  const body = Buffer.from('{}', 'utf8');
  const headers = MeshAuth.headersFor({ secret: SECRET, body });
  const verdict = auth.verify({ headers, body });
  assert.equal(verdict.status, 503);
  assert.equal(verdict.reason, 'node-has-no-secret');
});

test('the signature comparison is constant-time and length-checked first', () => {
  assert.equal(signatureMatches('ab'.repeat(32), 'ab'.repeat(32)), true);
  assert.equal(signatureMatches('ab'.repeat(32), 'ab'.repeat(31)), false);
  assert.equal(signatureMatches('ab'.repeat(32), 'AB'.repeat(32)), false, 'uppercase hex is not accepted');
  assert.equal(signatureMatches('ab'.repeat(32), undefined), false);
});

test('the signed message is the protocol tag, the timestamp, the nonce and the raw bytes', () => {
  const body = Buffer.from('{"a":1}', 'utf8');
  const expected = sign({ secret: 'k', timestamp: '1800000000', nonce: 'abcdefgh', body });
  const reordered = sign({ secret: 'k', timestamp: '1800000001', nonce: 'abcdefgh', body });
  assert.notEqual(expected, reordered, 'the timestamp is inside the MAC');
  assert.notEqual(expected, sign({ secret: 'k', timestamp: '1800000000', nonce: 'abcdefgi', body }), 'the nonce is inside the MAC');
  assert.notEqual(expected, sign({ secret: 'k', timestamp: '1800000000', nonce: 'abcdefgh', body: Buffer.from('{"a": 1}', 'utf8') }),
    'the body is signed byte-for-byte, so re-serialising it must break the MAC');
});

// ---------------------------------------------------------------------------
// the secret file
// ---------------------------------------------------------------------------

test('the secret file is KEY=VALUE with comments; a short secret is not a secret', () => {
  const parsed = parseEnvText('# c\nMESH_HTTP_SECRET="a-long-enough-secret-value"\nOTHER=1\n');
  assert.equal(parsed.get('MESH_HTTP_SECRET'), 'a-long-enough-secret-value');
  assert.equal(parsed.get('OTHER'), '1');

  const { dir, file } = secretFile({ value: 'short' });
  assert.equal(loadSecret(file).ok, false);
  assert.match(loadSecret(file).reason, /shorter than 16 bytes/);
  rmSync(dir, { recursive: true, force: true });
});

test('the secret is re-read when the file changes, so rotation needs no engine restart', () => {
  const { dir, file } = secretFile();
  forgetSecret();
  const first = loadSecret(file);
  assert.equal(first.ok, true);
  assert.equal(loadSecret(file).reads, 1, 'an unchanged file is read once');

  // a different length changes the file's identity, which is what the cache keys on
  writeFileSync(file, 'MESH_HTTP_SECRET=o2-rotated-secret-0123456789\n', { mode: 0o600 });
  const second = loadSecret(file);
  assert.equal(second.ok, true);
  assert.equal(second.secret, 'o2-rotated-secret-0123456789');
  assert.equal(second.reads, 2);
  rmSync(dir, { recursive: true, force: true });
});

test('the default secret path is outside every repository, per platform', () => {
  assert.equal(defaultSecretFile('win32'), 'C:/ProgramData/dsh-mesh.env');
  assert.equal(defaultSecretFile('linux'), '/etc/dsh-mesh.env');
  assert.equal(defaultSecretFile('darwin'), '/etc/dsh-mesh.env');
});

// ---------------------------------------------------------------------------
// bounded intake
// ---------------------------------------------------------------------------

test('a body over the ceiling is refused with 413, before it is parsed or verified', async () => {
  const big = Buffer.alloc(2048, 0x61);
  const request = (async function* () { yield big; })();
  request.headers = { 'content-length': String(big.byteLength) };
  request.resume = () => {};
  await assert.rejects(() => readBoundedBody(request, 1024), (error) => error instanceof IntakeError && error.status === 413);
});

test('a caller that lies about its length is cut off by the running total', async () => {
  const request = (async function* () {
    for (let i = 0; i < 8; i += 1) yield Buffer.alloc(1024, 0x61);
  })();
  request.headers = {}; // no content-length, so only the running total can stop it
  request.complete = true;
  request.resume = () => {};
  await assert.rejects(() => readBoundedBody(request, 2048), (error) => error.status === 413);
});

test('content type must be JSON with at most a utf-8 charset', () => {
  assert.equal(isJsonContentType('application/json'), true);
  assert.equal(isJsonContentType('application/json; charset=UTF-8'), true);
  assert.equal(isJsonContentType('application/json; charset=utf-16'), false);
  assert.equal(isJsonContentType('text/plain'), false);
  assert.equal(isJsonContentType(undefined), false);
});

test('a verified body that is not a JSON object is a 400, never a crash', () => {
  assert.throws(() => parseJsonObject(Buffer.from('not json', 'utf8')), (error) => error.status === 400);
  assert.throws(() => parseJsonObject(Buffer.from('[1,2]', 'utf8')), (error) => error.reason === 'body-not-an-object');
  assert.deepEqual(parseJsonObject(Buffer.from('{"prompt":"x"}', 'utf8')), { prompt: 'x' });
});

// ---------------------------------------------------------------------------
// the runner: one at a time, bounded, and it refuses rather than crashes
// ---------------------------------------------------------------------------

test('the task carries the MESH-HOST instruction and the child command is a fixed argv', () => {
  const task = composeTask({ prompt: 'do the thing', host: 'ZABZ-TECH' });
  assert.match(task, /^You are running on the node "ZABZ-TECH"\./);
  assert.match(task, /MESH-HOST: ZABZ-TECH/);
  assert.match(task, /do the thing$/);
  assert.deepEqual(
    childArgv({ nodeExe: 'node', dshBin: '/x/bin.js', profile: 'headless', task: 't' }),
    ['node', '/x/bin.js', '--profile', 'headless', 'headless', 't'],
    'the argv is exactly node, bin.js, --profile, <profile>, <subcommand>, task — no shell');
  assert.deepEqual(
    childArgv({ nodeExe: 'node', dshBin: '/x/bin.js', profile: 'mesh', task: 'a "quoted" $task; rm -rf /' }),
    ['node', '/x/bin.js', '--profile', 'mesh', 'headless', 'a "quoted" $task; rm -rf /'],
    'the task is one argv entry: a shell would have to be invoked for it to mean anything');
});

test('a request beyond the limit is QUEUED with a visible position and served in arrival order', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'mesh-http-queue-'));
  // A real child that takes long enough to overlap: four requests, one slot.
  const child = path.join(dir, 'slow-dsh.mjs');
  writeFileSync(child, 'setTimeout(()=>{process.stdout.write("MESH-HOST: T\\nDONE\\n")},300);\n', 'utf8');
  const runner = new OneShotRunner({
    nodeExe: process.execPath,
    dshBin: child,
    profile: 'headless',
    maxOutputBytes: 4096,
    artifactDir: dir,
    log: () => {},
    maxConcurrent: 1,
    maxQueueWaitMs: 20000,
  });
  const pending = [1, 2, 3, 4].map((i) => runner.run({ task: `t${i}`, cwd: HERE, timeoutMs: 10000, requestId: `r${i}`, host: 'H' }));
  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.equal(runner.active, 1, 'exactly one child is running, from the runner\'s own accounting');
  assert.equal(runner.inFlight.size, 1);
  assert.deepEqual(runner.view().queue.map((entry) => entry.position), [1, 2, 3],
    'the three waiting requests hold positions 1, 2 and 3');
  assert.equal(runner.view().busy, true);
  const results = await Promise.all(pending);
  assert.deepEqual(results.map((r) => r.queue.position), [0, 1, 2, 3],
    'the first was admitted immediately (position 0) and the rest kept the position they were given');
  assert.deepEqual(results.map((r) => r.ok), [true, true, true, true], 'NOTHING was refused');
  assert.ok(results.every((r) => r.queue.limit === 1), 'every answer names the limit it faced');
  assert.ok(results.slice(1).every((r) => r.queue.waitedMs > 0), 'a queued run reports how long it waited');
  assert.equal(runner.stats.queued, 3);
  assert.equal(runner.stats.queuePeak, 3);
  assert.equal(runner.stats.refusedBusy, 0);
  assert.equal(runner.stats.completed, 4);
  assert.equal(runner.active, 0, 'every slot was returned');
  assert.equal(runner.queue.length, 0);
  rmSync(dir, { recursive: true, force: true });
});

test('N simultaneous callers cannot all take the same free slot (the admission is synchronous)', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'mesh-http-race-'));
  const child = path.join(dir, 'slow-dsh.mjs');
  writeFileSync(child, 'setTimeout(()=>{process.stdout.write("done\\n")},250);\n', 'utf8');
  const runner = new OneShotRunner({
    nodeExe: process.execPath, dshBin: child, profile: 'headless', maxOutputBytes: 4096,
    artifactDir: dir, log: () => {}, maxConcurrent: 2, maxQueueWaitMs: 20000,
  });
  const pending = [1, 2, 3, 4, 5, 6].map((i) => runner.run({ task: `t${i}`, cwd: HERE, timeoutMs: 10000, requestId: `r${i}`, host: 'H' }));
  await new Promise((resolve) => setTimeout(resolve, 60));
  assert.equal(runner.active, 2, 'the ceiling held: six callers, two slots, two running');
  assert.equal(runner.queue.length, 4);
  await Promise.all(pending);
  assert.ok(runner.stats.maxInFlightSeen <= 2, `never more than the limit ran at once (saw ${runner.stats.maxInFlightSeen})`);
  assert.equal(runner.stats.completed, 6);
  rmSync(dir, { recursive: true, force: true });
});

test('refuseWhenFull restores the v0.1.0 behaviour: 429 with a position, never a queue', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'mesh-http-refuse-'));
  const child = path.join(dir, 'slow-dsh.mjs');
  writeFileSync(child, 'setTimeout(()=>{process.stdout.write("done\\n")},250);\n', 'utf8');
  const runner = new OneShotRunner({
    nodeExe: process.execPath, dshBin: child, profile: 'headless', maxOutputBytes: 4096,
    artifactDir: dir, log: () => {}, maxConcurrent: 1, refuseWhenFull: true,
  });
  const first = runner.run({ task: 'a', cwd: HERE, timeoutMs: 10000, requestId: 'first', host: 'H' });
  const refused = await runner.run({ task: 'b', cwd: HERE, timeoutMs: 10000, requestId: 'second', host: 'H' });
  assert.equal(refused.ok, false);
  assert.equal(refused.status, 429);
  assert.equal(refused.reason, 'node-busy');
  assert.equal(refused.queue.position, 1, 'even a refusal carries the position it would have held');
  assert.equal(runner.stats.refusedBusy, 1);
  assert.equal(runner.queue.length, 0, 'a refusal is not a queue');
  assert.equal(runner.view().busy, true);
  await first;
  assert.equal(runner.active, 0);
  rmSync(dir, { recursive: true, force: true });
});

test('a queued request whose wait exceeds the node budget is refused, naming the queue', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'mesh-http-qexp-'));
  const child = path.join(dir, 'slow-dsh.mjs');
  writeFileSync(child, 'setTimeout(()=>{process.stdout.write("done\\n")},700);\n', 'utf8');
  const runner = new OneShotRunner({
    nodeExe: process.execPath, dshBin: child, profile: 'headless', maxOutputBytes: 4096,
    artifactDir: dir, log: () => {}, maxConcurrent: 1, maxQueueWaitMs: 120,
  });
  const first = runner.run({ task: 'a', cwd: HERE, timeoutMs: 10000, requestId: 'first', host: 'H' });
  const expired = await runner.run({ task: 'b', cwd: HERE, timeoutMs: 10000, requestId: 'second', host: 'H' });
  assert.equal(expired.status, 429);
  assert.equal(expired.reason, 'node-queue-wait-exceeded',
    'the only remaining 429 is a WAIT budget, not a capacity refusal');
  assert.equal(expired.queue.position, 1);
  assert.equal(runner.stats.refusedQueueWait, 1);
  await first;
  assert.equal(runner.stats.completed, 1, 'the first one still ran');
  assert.equal(runner.active, 0);
  rmSync(dir, { recursive: true, force: true });
});

test('a run whose child cannot be spawned answers with a spawn error, and releases the slot', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'mesh-http-run2-'));
  const runner = new OneShotRunner({
    nodeExe: process.execPath,
    dshBin: '/definitely/not/a/real/entrypoint.js',
    profile: 'headless',
    maxOutputBytes: 4096,
    artifactDir: dir,
    log: () => {},
  });
  const result = await runner.run({ task: 't', cwd: HERE, timeoutMs: 5000, requestId: 'spawnfail', host: 'H' });
  assert.equal(result.ok, true, 'the run completed; the CHILD failed, which is the answer');
  assert.notEqual(result.exitCode, 0);
  assert.equal(runner.busy(), false, 'the slot is released even when the child fails');
  rmSync(dir, { recursive: true, force: true });
});

// ---------------------------------------------------------------------------
// the node's own identity
// ---------------------------------------------------------------------------

test('the node name comes from the tailnet label, never from the caller', () => {
  assert.equal(labelFromDnsName('zabz-yoga-1.tail93e6e6.ts.net.'), 'zabz-yoga-1');
  assert.equal(labelFromDnsName('zabz-tech.tail93e6e6.ts.net'), 'zabz-tech');
  assert.equal(labelFromDnsName(null), null);
  assert.equal(labelFromDnsName(''), null, 'an empty DNSName is not a label');

  const identity = createNodeIdentity({ tailnetReader: () => ({ fqdn: 'zabz-tech.tail93e6e6.ts.net', node: 'zabz-tech', hostName: 'zabz-tech', error: null }) });
  const described = identity.describe();
  assert.equal(described.node, 'zabz-tech');
  assert.equal(described.fqdn, 'zabz-tech.tail93e6e6.ts.net');
  assert.equal(described.host, identity.host());
  assert.equal(described.identityDegraded, false);
  assert.equal(described.node, described.fqdn.split('.')[0], 'the contract invariant 71 §2.1 holds');

  const override = createNodeIdentity({ nodeNameOverride: 'explicit-name', tailnetReader: () => ({ fqdn: null, node: null, hostName: null, error: 'not installed' }) });
  assert.equal(override.describe().node, 'explicit-name');
  assert.equal(override.describe().nodeSource, 'MESH_NODE_NAME');
});

// ---------------------------------------------------------------------------
// the route, end to end, over a real HTTP socket
// ---------------------------------------------------------------------------

/** Mount exactly what the engine mounts, on a plain node:http server. */
async function withRoute(config, fn) {
  // `capacityUrl: ''` by default: the declared-ceiling read is a loopback HTTP call to THIS
  // machine's gate, and a unit test that depends on whatever gate happens to be running is not a
  // unit test. The tests that exercise it inject a stub instead.
  const mount = createMeshHttp({ config: { capacityUrl: '', ...config }, log: () => {} });
  const server = createServer((req, res) => mount.handler(req, res));
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  try {
    return await fn({ mount, base: `http://127.0.0.1:${port}` });
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

async function post(base, body, headers) {
  const response = await fetch(`${base}/mesh/run`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body,
  });
  return { status: response.status, json: await response.json().catch(() => undefined) };
}

test('GET /mesh/health reports the route, the version, the limits and whether a secret exists', async () => {
  const { dir, file } = secretFile();
  await withRoute({ secretFile: file, artifactDir: dir }, async ({ base }) => {
    const response = await fetch(`${base}/mesh/health`);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.service, 'mesh-http');
    assert.equal(body.version, VERSION);
    assert.equal(body.auth.secretConfigured, true);
    assert.equal(typeof body.host, 'string');
    // The ceiling is published WITH its arithmetic, so a reader can check the number instead of
    // trusting it. `limit` is derived from this machine, so it is asserted as a shape, not a value.
    assert.equal(typeof body.limits.maxConcurrent, 'number');
    assert.ok(body.limits.maxConcurrent >= 1);
    assert.equal(body.limits.oneRunAtATime, body.limits.maxConcurrent === 1,
      'the v0.1.0 field stays TRUE exactly when the derived ceiling is 1, and never lies');
    assert.equal(typeof body.limits.maxQueueWaitSec, 'number');
    assert.equal(body.limits.refuseWhenFull, false);
    assert.equal(body.concurrency.limit, body.limits.maxConcurrent);
    assert.equal(typeof body.concurrency.terms.cpu, 'number');
    assert.equal(typeof body.concurrency.inputs.logicalCpus, 'number');
    assert.match(body.concurrency.sources.commitPerTurnMiB, /84-calibration/);
    assert.match(body.concurrency.note, /term binds/);
    assert.equal(body.runner.busy, false);
    assert.equal(body.runner.limit, body.limits.maxConcurrent);
    assert.equal(body.runner.inFlightCount, 0);
    assert.equal(body.runner.queueDepth, 0);
  });
  rmSync(dir, { recursive: true, force: true });
});

test('the ceiling is derived from the given machine, by a pure function, and every term is cited', () => {
  // The measured inputs from docs/mesh/93-transport-concurrency.md §4, 2026-09-17.
  const tech = deriveConcurrencyLimit({
    logicalCpus: 32, totalMiB: 65173, availableMiB: 53616, declaredMax: 12, availableSource: 'test',
  });
  assert.equal(tech.terms.cpu, 8, 'floor(32 × 0.42 / 1.68) = 8');
  assert.equal(tech.terms.mem, 113, 'floor((53616 − 7821) / 403)');
  assert.equal(tech.terms.declared, 12);
  assert.equal(tech.limit, 8);
  assert.equal(tech.terms.binding, 'cpu');
  assert.match(tech.sources.cpuPerTurn, /84-calibration/);

  // A four-core authority: the CPU term binds hard, which is the row that matters for safety.
  const authority = deriveConcurrencyLimit({
    logicalCpus: 4, totalMiB: 8192, availableMiB: 3000, declaredMax: 12, availableSource: 'test',
  });
  assert.equal(authority.terms.cpu, 1);
  assert.equal(authority.limit, 1, '8 children on 4 cores is the 2× oversubscription 84 §6.2 records');

  // The declared ceiling is a CAP, never the source: a big node is held to what it published.
  const big = deriveConcurrencyLimit({
    logicalCpus: 128, totalMiB: 262144, availableMiB: 200000, declaredMax: 12, availableSource: 'test',
  });
  assert.equal(big.terms.cpu, 32);
  assert.equal(big.limit, 12);
  assert.equal(big.terms.binding, 'declared');

  // Fail soft: without the contract, or without a memory reading, it is still a derived number.
  const noContract = deriveConcurrencyLimit({ logicalCpus: 32, availableMiB: 53616, totalMiB: 65173, availableSource: 'test' });
  assert.equal(noContract.limit, 8);
  assert.match(noContract.note, /Unavailable inputs: declared/);
  const noMemory = deriveConcurrencyLimit({ logicalCpus: 32, declaredMax: 12, availableSource: 'test' });
  assert.equal(noMemory.limit, 8);
  assert.equal(noMemory.terms.mem, null);

  // A misconfigured ceiling can never exceed the governor's own ceiling on this host.
  const absurd = deriveConcurrencyLimit({ logicalCpus: 128, totalMiB: 262144, availableMiB: 200000, declaredMax: 9999, availableSource: 'test' });
  assert.equal(absurd.limit, 24);
  assert.equal(absurd.terms.binding, 'hard');
});

test('an explicit maxConcurrent is honoured, and is clamped to the hard ceiling', async () => {
  const { dir, file } = secretFile();
  await withRoute({ secretFile: file, artifactDir: dir, maxConcurrent: 3 }, async ({ base, mount }) => {
    assert.equal(mount.runner.maxConcurrent, 3);
    const body = await (await fetch(`${base}/mesh/health`)).json();
    assert.equal(body.limits.maxConcurrent, 3);
    assert.equal(body.limits.oneRunAtATime, false);
    assert.equal(body.concurrency.forced, 3);
    assert.match(body.concurrency.note, /forces 3/);
  });
  rmSync(dir, { recursive: true, force: true });
  const { dir: dir2, file: file2 } = secretFile();
  await withRoute({ secretFile: file2, artifactDir: dir2, maxConcurrent: 999, hardCeiling: 24 }, async ({ mount }) => {
    assert.equal(mount.runner.maxConcurrent, 24, 'nothing may exceed the governor\'s ceiling');
  });
  rmSync(dir2, { recursive: true, force: true });
});

test('a boot-time tailnet read that returned no DNSName is retried, not cached for ever', () => {
  // MEASURED, 2026-09-17: on ZABZ-YOGA engine pid 4880 started 08:51:07 and `tailscale-ipn`
  // started 08:51:59, so the boot read saw an empty Self.DNSName. Caching that made the engine
  // report node "zabz-yoga" and fqdn "" for the rest of its life, while claiming
  // nodeSource "tailscale status --json Self.DNSName" — a source that had not produced the value.
  let call = 0;
  const reader = () => {
    call += 1;
    if (call === 1) return { fqdn: '', node: null, hostName: 'zabz-yoga', error: null, emptyDnsName: true };
    return { fqdn: 'zabz-yoga-1.tail93e6e6.ts.net', node: 'zabz-yoga-1', hostName: 'zabz-yoga', error: null };
  };
  let clock = 0;
  const identity = createNodeIdentity({ tailnetReader: reader, degradedRetryMs: 15000, nowMs: () => clock });

  const degraded = identity.describe();
  assert.equal(degraded.fqdn, null, 'an empty DNSName is null, not the empty string');
  assert.equal(degraded.nodeSource, 'os.hostname()', 'the source must not name a field that did not supply it');
  assert.equal(degraded.identityDegraded, true);
  assert.match(degraded.identityReason, /no Self\.DNSName/);
  assert.equal(call, 1);

  // Within the retry interval it does not fork a subprocess per request...
  clock = 1000;
  identity.describe();
  assert.equal(call, 1, 'a degraded read is rate-limited, not re-read per request');

  // ...and after it, it heals without a restart.
  clock = 20000;
  const healed = identity.describe();
  assert.equal(healed.node, 'zabz-yoga-1');
  assert.equal(healed.fqdn, 'zabz-yoga-1.tail93e6e6.ts.net');
  assert.equal(healed.identityDegraded, false);
  assert.equal(healed.node, healed.fqdn.split('.')[0]);
  assert.equal(call, 2);

  // A GOOD read is still cached for the life of the process: a tailnet name does not change.
  clock = 400000;
  identity.describe();
  assert.equal(call, 2, 'a good read is not re-read');
});

test('a name tailscale cannot supply is never GUESSED from MagicDNSSuffix and the hostname', () => {
  // zabz-yoga's real label is `zabz-yoga-1` while its HostName is `zabz-yoga`, so
  // "<HostName>.<MagicDNSSuffix>" would produce a plausible, well-formed and WRONG identity.
  const guessedWouldBe = `zabz-yoga.tail93e6e6.ts.net`;
  const identity = createNodeIdentity({
    tailnetReader: () => ({ fqdn: null, node: null, hostName: 'zabz-yoga', magicDnsSuffix: 'tail93e6e6.ts.net', error: null, emptyDnsName: true }),
  });
  const described = identity.describe();
  assert.equal(described.fqdn, null);
  assert.notEqual(described.fqdn, guessedWouldBe);
  assert.equal(described.host, described.node, 'the honest fallback is os.hostname(), labelled as such');
  assert.equal(described.nodeSource, 'os.hostname()');
  assert.equal(described.identityDegraded, true, 'and the caller is told it cannot be corroborated');
});

test('an unsigned POST is refused 401 and never runs anything', async () => {
  const { dir, file } = secretFile();
  await withRoute({ secretFile: file, artifactDir: dir }, async ({ base, mount }) => {
    const response = await post(base, JSON.stringify({ prompt: 'x' }), {});
    assert.equal(response.status, 401);
    assert.equal(response.json.reason, 'bad-timestamp-header', 'the first missing header is named');
    assert.equal(response.json.authenticated, false);
    assert.equal(mount.runner.stats.started, 0, 'nothing ran');
  });
  rmSync(dir, { recursive: true, force: true });
});

test('a bad method and a bad content type are refused before the body is read', async () => {
  const { dir, file } = secretFile();
  await withRoute({ secretFile: file, artifactDir: dir }, async ({ base }) => {
    const get = await fetch(`${base}/mesh/run`);
    assert.equal(get.status, 405);
    assert.equal(get.headers.get('allow'), 'POST');
    const wrongType = await fetch(`${base}/mesh/run`, { method: 'POST', headers: { 'content-type': 'text/plain' }, body: 'x' });
    assert.equal(wrongType.status, 415);
  });
  rmSync(dir, { recursive: true, force: true });
});

test('a correctly signed request with an empty prompt is refused 400', async () => {
  const { dir, file } = secretFile();
  await withRoute({ secretFile: file, artifactDir: dir }, async ({ base }) => {
    const body = JSON.stringify({ prompt: '   ' });
    const response = await post(base, body, MeshAuth.headersFor({ secret: SECRET, body: Buffer.from(body, 'utf8') }));
    assert.equal(response.status, 400);
    assert.equal(response.json.reason, 'prompt-required');
  });
  rmSync(dir, { recursive: true, force: true });
});

test('a prompt over the ceiling is refused 413 with the reason the ceiling exists', async () => {
  const { dir, file } = secretFile();
  await withRoute({ secretFile: file, artifactDir: dir, maxPromptChars: 100 }, async ({ base }) => {
    const body = JSON.stringify({ prompt: 'y'.repeat(200) });
    const response = await post(base, body, MeshAuth.headersFor({ secret: SECRET, body: Buffer.from(body, 'utf8') }));
    assert.equal(response.status, 413);
    assert.equal(response.json.reason, 'prompt-too-large');
    assert.match(response.json.detail, /argv/);
  });
  rmSync(dir, { recursive: true, force: true });
});

test('a caller may not choose the working directory unless the node allows it', async () => {
  const { dir, file } = secretFile();
  await withRoute({ secretFile: file, artifactDir: dir, cwd: HERE }, async ({ base }) => {
    const body = JSON.stringify({ prompt: 'x', workdir: 'C:/' });
    const response = await post(base, body, MeshAuth.headersFor({ secret: SECRET, body: Buffer.from(body, 'utf8') }));
    assert.equal(response.status, 403);
    assert.equal(response.json.reason, 'workdir-not-allowed');
  });
  rmSync(dir, { recursive: true, force: true });
});

test('a signed request runs the child and answers with its own name, its output and its exit code', async () => {
  const { dir, file } = secretFile();
  // A real child process, but a harmless stand-in for `dsh`: the runner is given a tiny module as
  // the node entry point, so this proves the route's OWN contract — status, response shape, the
  // hostname it measured, the child's own stdout, its exit code, and that the slot is released —
  // without booting a DSH agent inside a unit test. The real dispatch is
  // `bin/mesh-dispatch.mjs` against a live node (docs/mesh/83-http-transport.md §6).
  const child = path.join(dir, 'fake-dsh.mjs');
  writeFileSync(child, [
    'process.stdout.write("MESH-HOST: TEST-CHILD\\nCHILD_OK\\n");',
    'process.stderr.write("child said something on stderr\\n");',
    'process.exit(0);',
  ].join('\n'), 'utf8');
  const previous = process.env.MESH_LOCAL_DSH_BIN;
  process.env.MESH_LOCAL_DSH_BIN = child;
  try {
    await withRoute({ secretFile: file, artifactDir: dir, cwd: HERE }, async ({ base, mount }) => {
      const body = JSON.stringify({ prompt: 'x' });
      const headers = MeshAuth.headersFor({ secret: SECRET, body: Buffer.from(body, 'utf8') });
      const response = await post(base, body, headers);
      assert.equal(response.status, 200);
      const answer = response.json;
      assert.equal(answer.ok, true);
      assert.equal(answer.exitCode, 0);
      assert.equal(answer.timedOut, false);
      assert.match(answer.stdout, /MESH-HOST: TEST-CHILD/);
      assert.match(answer.stderr, /stderr/);
      assert.equal(typeof answer.host, 'string');
      assert.equal(typeof answer.node, 'string');
      assert.ok(answer.ms >= 0);
      assert.match(answer.requestId, /^local-[a-z0-9]+$/, 'no request id was supplied, so the route minted one');
      assert.equal(mount.runner.busy(), false, 'the slot is released when the run finishes');
      assert.equal(mount.runner.stats.completed, 1);
    });
  } finally {
    if (previous === undefined) delete process.env.MESH_LOCAL_DSH_BIN;
    else process.env.MESH_LOCAL_DSH_BIN = previous;
    rmSync(dir, { recursive: true, force: true });
  }
});

test('a child that exits non-zero is reported as a failed answer, not a route failure', async () => {
  const { dir, file } = secretFile();
  const child = path.join(dir, 'failing-dsh.mjs');
  writeFileSync(child, 'process.stderr.write("child refused\\n");process.exit(3);\n', 'utf8');
  const previous = process.env.MESH_LOCAL_DSH_BIN;
  process.env.MESH_LOCAL_DSH_BIN = child;
  try {
    await withRoute({ secretFile: file, artifactDir: dir, cwd: HERE }, async ({ base }) => {
      const body = JSON.stringify({ prompt: 'x' });
      const response = await post(base, body, MeshAuth.headersFor({ secret: SECRET, body: Buffer.from(body, 'utf8') }));
      assert.equal(response.status, 200, 'the route worked; the CHILD failed, and the exit code says so');
      assert.equal(response.json.ok, false);
      assert.equal(response.json.exitCode, 3);
      assert.match(response.json.stderr, /child refused/);
    });
  } finally {
    if (previous === undefined) delete process.env.MESH_LOCAL_DSH_BIN;
    else process.env.MESH_LOCAL_DSH_BIN = previous;
    rmSync(dir, { recursive: true, force: true });
  }
});

test('a child that outlives the timeout is killed and reported as a 504', async () => {
  const { dir, file } = secretFile();
  const child = path.join(dir, 'slow-dsh.mjs');
  writeFileSync(child, 'process.stdout.write("starting\\n");setTimeout(()=>{}, 60000);\n', 'utf8');
  const previous = process.env.MESH_LOCAL_DSH_BIN;
  process.env.MESH_LOCAL_DSH_BIN = child;
  try {
    await withRoute({ secretFile: file, artifactDir: dir, cwd: HERE, defaultTimeoutSec: 1, maxTimeoutSec: 2 }, async ({ base, mount }) => {
      const body = JSON.stringify({ prompt: 'x' });
      const started = Date.now();
      const response = await post(base, body, MeshAuth.headersFor({ secret: SECRET, body: Buffer.from(body, 'utf8') }));
      assert.equal(response.status, 504);
      assert.equal(response.json.timedOut, true);
      assert.ok(Date.now() - started < 15_000, 'the bound is a wall clock, not a hope');
      assert.equal(mount.runner.busy(), false);
      assert.equal(mount.runner.stats.timedOut, 1);
    });
  } finally {
    if (previous === undefined) delete process.env.MESH_LOCAL_DSH_BIN;
    else process.env.MESH_LOCAL_DSH_BIN = previous;
    rmSync(dir, { recursive: true, force: true });
  }
});

test('the identity in a response is the node\'s own, even when the caller claims otherwise', async () => {
  const { dir, file } = secretFile();
  await withRoute({ secretFile: file, artifactDir: dir, cwd: HERE }, async ({ base, mount }) => {
    const body = JSON.stringify({ prompt: 'x', meshHost: 'a-node-that-does-not-exist', workdir: '/tmp' });
    const headers = MeshAuth.headersFor({ secret: SECRET, body: Buffer.from(body, 'utf8') });
    const response = await post(base, body, headers);
    const answer = response.json;
    assert.equal(answer.host, mount.readout().host, 'the response names this machine, not the caller\'s claim');
    assert.notEqual(answer.host, 'a-node-that-does-not-exist');
  });
  rmSync(dir, { recursive: true, force: true });
});

test('the dsh entry point is located from the environment, and absent is reported as absent', () => {
  const nothing = { existsSync: () => false, readdirSync: () => [] };
  assert.equal(locateDshBin(undefined, { env: {}, fs: nothing }), undefined);
  const found = locateDshBin('/explicit/bin.js', { env: {}, fs: { existsSync: (p) => p === '/explicit/bin.js', readdirSync: () => [] } });
  assert.equal(found, '/explicit/bin.js');
  const fromEnv = locateDshBin(undefined, { env: { MESH_LOCAL_DSH_BIN: '/env/bin.js' }, fs: { existsSync: (p) => p === '/env/bin.js', readdirSync: () => [] } });
  assert.equal(fromEnv, '/env/bin.js');
  // An unreadable cache directory is not a fault: it just means this node has no npx cache.
  const throwing = { existsSync: () => false, readdirSync: () => { throw new Error('ENOENT'); } };
  assert.equal(locateDshBin(undefined, { env: {}, fs: throwing }), undefined);
  const expected = path.join('/cache', 'npm-cache', '_npx', 'abc', 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js');
  const cache = locateDshBin(undefined, {
    env: { LOCALAPPDATA: '/cache' },
    fs: { existsSync: (p) => p === expected, readdirSync: () => ['abc'] },
  });
  assert.equal(cache, expected);
});
