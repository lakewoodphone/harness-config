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

test('a second run while one is in flight is refused with a position, not queued and not run', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'mesh-http-run-'));
  // A child that takes long enough to overlap: node -e "setTimeout(()=>{},400)"
  const runner = new OneShotRunner({
    nodeExe: process.execPath,
    dshBin: '--eval', // ignored: the argv is [nodeExe, '--eval'? no] — see below
    profile: 'headless',
    maxOutputBytes: 4096,
    artifactDir: dir,
    log: () => {},
  });
  // The runner builds [nodeExe, dshBin, '--profile', profile, 'headless', task]; to make a real
  // sleep we would have to fork a real dsh. Instead drive the slot directly: the property under
  // test is the slot, and it is the same object the handler consults.
  runner.inFlight = { requestId: 'held', startedAtMs: Date.now(), startedAt: new Date().toISOString(), timeoutMs: 1000 };
  const refused = await runner.run({ task: 't', cwd: HERE, timeoutMs: 1000, requestId: 'second', host: 'H' });
  assert.equal(refused.ok, false);
  assert.equal(refused.status, 429);
  assert.equal(refused.reason, 'node-busy');
  assert.equal(runner.stats.refusedBusy, 1);
  assert.equal(runner.view().busy, true);
  runner.inFlight = null;
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

  const identity = createNodeIdentity({ tailnetReader: () => ({ fqdn: 'zabz-tech.tail93e6e6.ts.net', node: 'zabz-tech', hostName: 'zabz-tech', error: null }) });
  const described = identity.describe();
  assert.equal(described.node, 'zabz-tech');
  assert.equal(described.fqdn, 'zabz-tech.tail93e6e6.ts.net');
  assert.equal(described.host, identity.host());

  const override = createNodeIdentity({ nodeNameOverride: 'explicit-name', tailnetReader: () => ({ fqdn: null, node: null, hostName: null, error: 'not installed' }) });
  assert.equal(override.describe().node, 'explicit-name');
  assert.equal(override.describe().nodeSource, 'MESH_NODE_NAME');
});

// ---------------------------------------------------------------------------
// the route, end to end, over a real HTTP socket
// ---------------------------------------------------------------------------

/** Mount exactly what the engine mounts, on a plain node:http server. */
async function withRoute(config, fn) {
  const mount = createMeshHttp({ config, log: () => {} });
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
    assert.equal(body.limits.oneRunAtATime, true);
    assert.equal(body.runner.busy, false);
    assert.equal(typeof body.host, 'string');
  });
  rmSync(dir, { recursive: true, force: true });
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
