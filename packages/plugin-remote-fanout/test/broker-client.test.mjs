import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { writeSync } from 'node:fs';
import test from 'node:test';

import { BROKER_UNPARSABLE, BROKER_UNREACHABLE, createBrokerClient } from '../lib/broker-client.js';

/**
 * A spawn double. The client redirects stdout/stderr to FILES (never pipes —
 * the Win32-OpenSSH measurement in `lib/ssh-transport.js`), so the fake writes
 * into the very descriptors it was handed and then emits `close`, which is the
 * order the real ssh client produces.
 */
function fakeSpawn({ stdout = '', stderr = '', code = 0, throwError, seen } = {}) {
  return (exe, argv, options) => {
    seen?.push({ exe, argv });
    if (throwError !== undefined) throw new Error(throwError);
    const child = new EventEmitter();
    child.kill = () => {};
    setImmediate(() => {
      try { if (stdout !== '') writeSync(options.stdio[1], stdout); } catch { /* closed */ }
      try { if (stderr !== '') writeSync(options.stdio[2], stderr); } catch { /* closed */ }
      child.emit('close', code);
    });
    return child;
  };
}

/** A child that is accepted by ssh and never answers: the hard timeout fires and kills it. */
function hangSpawn() {
  return () => {
    const child = new EventEmitter();
    child.kill = () => setImmediate(() => child.emit('close', null));
    return child;
  };
}

/**
 * Retry tests must not sleep for real. These two options are read by the fixed client;
 * the unfixed one ignores them, which is exactly what makes the "before" run honest.
 */
const NO_WAIT = { retryBaseMs: 0, sleep: async () => {} };

const ONESHOT = { kind: 'oneShot', children: 1, worktreeGiB: 0, prefer: null, exclude: [] };

const PLACEMENT = {
  node: 'zabz-tech',
  position: 0,
  lease: 'mu4q576o-test-lease',
  score: 16,
  eligible: 4,
  tier: 'fits',
  blockedBy: [],
  queue: [],
  rationale: ['chosen from 4 configured node(s): 0 unreachable, 0 excluded by the caller; tier=fits; chosen zabz-tech'],
  at: '2026-09-17T13:06:39.210Z',
  expiresAt: '2026-09-17T13:21:39.210Z',
  leaseTtlSec: 900,
};

test('place() asks the live broker through one ssh and parses the placement', async () => {
  const seen = [];
  const client = createBrokerClient({
    sshTarget: 'secratary-ts',
    url: 'http://localhost:3091',
    spawnImpl: fakeSpawn({ stdout: JSON.stringify(PLACEMENT), seen }),
  });
  const placement = await client.place({ kind: 'oneShot', children: 1, worktreeGiB: 0, prefer: null, exclude: [] });

  assert.equal(placement.node, 'zabz-tech');
  assert.equal(placement.position, 0);
  assert.equal(placement.lease, 'mu4q576o-test-lease');
  assert.equal(placement.rationale.length, 1);

  assert.equal(seen.length, 1);
  // The transport is ssh to the authority, and the remote command is a curl
  // against the broker's LOOPBACK url — the client never opens a socket itself.
  assert.equal(seen[0].exe, 'ssh');
  assert.deepEqual(seen[0].argv.slice(0, 4), ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8']);
  assert.equal(seen[0].argv[4], 'secratary-ts');
  assert.match(seen[0].argv[5], /^curl -s -S -XPOST http:\/\/localhost:3091\/place /);
  assert.match(seen[0].argv[5], /"kind":"oneShot"/);
  // I1: a place body carries a requestId, so the broker can memoize the request.
  assert.match(seen[0].argv[5], /"requestId":"[^"]+"/);
  assert.equal(typeof placement.requestId, 'string');
  assert.equal(placement.attempts, 1);
});

test('an ssh that cannot reach the authority is broker-unreachable, and the message names where', async () => {
  const client = createBrokerClient({
    sshTarget: 'secratary-ts',
    ...NO_WAIT,
    spawnImpl: fakeSpawn({ code: 255, stderr: 'ssh: connect to host secratary-ts port 22: Connection timed out' }),
  });
  await assert.rejects(
    () => client.place(ONESHOT),
    (error) => {
      assert.equal(error.code, BROKER_UNREACHABLE);
      assert.match(error.message, /could not be reached at secratary-ts:http:\/\/localhost:3091\/place/);
      assert.match(error.message, /ssh exited 255/);
      assert.match(error.message, /Connection timed out/);
      return true;
    },
  );
});

test('an ssh client that will not launch is broker-unreachable, not a silent default', async () => {
  const client = createBrokerClient({ ...NO_WAIT, spawnImpl: fakeSpawn({ throwError: 'spawn ssh ENOENT' }) });
  await assert.rejects(
    () => client.place(ONESHOT),
    (error) => {
      assert.equal(error.code, BROKER_UNREACHABLE);
      assert.match(error.message, /spawn ssh ENOENT/);
      return true;
    },
  );
});

test('a broker answer that is not a placement is broker-unparsable, with the body kept', async () => {
  const cases = [
    { stdout: 'not json at all', match: /answered something that is not JSON/ },
    { stdout: JSON.stringify({ ...PLACEMENT, node: undefined }), match: /without naming a node/ },
    { stdout: JSON.stringify({ ...PLACEMENT, lease: undefined }), match: /without issuing a lease/ },
    { stdout: JSON.stringify({ ...PLACEMENT, position: 'soon' }), match: /not a queue position/ },
    { stdout: JSON.stringify({ ...PLACEMENT, rationale: [] }), match: /without a rationale — that is a bug in the decision, not a warning/ },
  ];
  for (const scenario of cases) {
    const client = createBrokerClient({ ...NO_WAIT, spawnImpl: fakeSpawn(scenario) });
    await assert.rejects(
      () => client.place(ONESHOT),
      (error) => {
        assert.equal(error.code, BROKER_UNPARSABLE);
        assert.match(error.message, scenario.match);
        return true;
      },
    );
  }
});

test('a body containing a single quote is refused rather than escaped, and nothing is spawned', async () => {
  const seen = [];
  const client = createBrokerClient({ ...NO_WAIT, spawnImpl: fakeSpawn({ seen }) });
  await assert.rejects(
    () => client.place({ kind: 'oneShot', children: 1, worktreeGiB: 0, prefer: "it's", exclude: [] }),
    (error) => {
      assert.equal(error.code, BROKER_UNPARSABLE);
      assert.match(error.message, /single quote/);
      return true;
    },
  );
  assert.equal(seen.length, 0);
});

test('done() releases the lease and nodes() reads the mesh with fresh=1', async () => {
  const seen = [];
  const answers = [
    JSON.stringify({ ok: true, released: true, lease: 'L', node: 'zabz-tech', state: 'running', heldMs: 1234, reason: null, at: 'now' }),
    JSON.stringify({ schema: 1, at: 'now', nodes: [{ node: 'zabz-tech', state: 'ok', slots: 18, freeSlots: 16 }] }),
  ];
  let call = 0;
  const client = createBrokerClient({
    ...NO_WAIT,
    spawnImpl: (exe, argv, options) => {
      seen.push({ exe, argv });
      const body = answers[Math.min(call, answers.length - 1)];
      call += 1;
      return fakeSpawn({ stdout: body })(exe, argv, options);
    },
  });

  const done = await client.done('L', true);
  assert.equal(done.released, true);
  assert.match(seen[0].argv[5], /-XPOST http:\/\/localhost:3091\/done /);
  assert.match(seen[0].argv[5], /"lease":"L"/);

  const nodes = await client.nodes({ fresh: true });
  assert.equal(nodes.nodes[0].freeSlots, 16);
  assert.match(seen[1].argv[5], /-XGET http:\/\/localhost:3091\/nodes\?fresh=1/);
});

test('the client refuses to be built without a destination for the machine the broker runs on', () => {
  assert.throws(() => createBrokerClient({ sshTarget: '' }), /needs `sshTarget`/);
});

test('describe() says exactly how the broker is reached', () => {
  const client = createBrokerClient({ sshTarget: 'secratary-ts', url: 'http://localhost:3091' });
  assert.equal(client.describe(), 'broker http://localhost:3091 over ssh secratary-ts');
});

// ─────────────────────────────────────────────────────────────────────────────
// I2/I1 — bounded retry, one requestId, honest attempt accounting
// (docs/mesh/126-placement-hardening.md). Codes are asserted as literals, not
// imports, so the same test file runs unchanged against the unfixed client and
// fails there on the behaviour rather than on a missing export.
// ─────────────────────────────────────────────────────────────────────────────

test('I2 a transient transport failure is retried and the placement succeeds on the second attempt, under the SAME requestId', async () => {
  const curls = [];
  let calls = 0;
  const client = createBrokerClient({
    sshTarget: 'secratary-ts',
    ...NO_WAIT,
    spawnImpl: (exe, argv, options) => {
      calls += 1;
      curls.push(argv[5]);
      if (calls === 1) {
        return fakeSpawn({ code: 255, stderr: 'ssh: connect to host secratary-ts port 22: Connection timed out' })(exe, argv, options);
      }
      return fakeSpawn({ stdout: JSON.stringify(PLACEMENT) })(exe, argv, options);
    },
  });
  const placement = await client.place(ONESHOT, { requestId: 'fixed-request-id' });

  assert.equal(calls, 2, 'the transport failure was retried exactly once');
  assert.equal(placement.node, 'zabz-tech');
  assert.equal(placement.attempts, 2, 'the response records how many attempts were made');
  assert.equal(placement.requestId, 'fixed-request-id');
  assert.ok(curls[0].includes('"requestId":"fixed-request-id"'));
  assert.ok(curls[1].includes('"requestId":"fixed-request-id"'), 'both attempts carry the SAME idempotency key');
});

test('I1 two place() calls with different requestIds send different keys', async () => {
  const curls = [];
  const client = createBrokerClient({
    ...NO_WAIT,
    spawnImpl: (exe, argv, options) => {
      curls.push(argv[5]);
      return fakeSpawn({ stdout: JSON.stringify(PLACEMENT) })(exe, argv, options);
    },
  });
  const first = await client.place(ONESHOT, { requestId: 'one' });
  const second = await client.place(ONESHOT, { requestId: 'two' });
  assert.equal(first.requestId, 'one');
  assert.equal(second.requestId, 'two');
  assert.ok(curls[0].includes('"requestId":"one"'));
  assert.ok(curls[1].includes('"requestId":"two"'));
  assert.notEqual(first.requestId, second.requestId);
});

test('I3 a timeout and a refusal produce DIFFERENT codes and different text, each stating its attempts', async () => {
  const timingOut = createBrokerClient({ sshTarget: 'secratary-ts', timeoutMs: 25, ...NO_WAIT, spawnImpl: hangSpawn() });
  const refusing = createBrokerClient({
    sshTarget: 'secratary-ts',
    ...NO_WAIT,
    spawnImpl: fakeSpawn({ code: 255, stderr: 'ssh: connect to host secratary-ts port 22: Connection refused' }),
  });
  const timeoutError = await timingOut.place(ONESHOT).then(() => null, (error) => error);
  const refusalError = await refusing.place(ONESHOT).then(() => null, (error) => error);

  assert.ok(timeoutError !== null && refusalError !== null, 'both calls failed, as intended');
  assert.notEqual(timeoutError.code, refusalError.code, 'a timeout and a refusal must not share one code');
  assert.equal(timeoutError.code, 'broker-timeout');
  assert.equal(refusalError.code, 'broker-unreachable');
  assert.notEqual(timeoutError.message, refusalError.message);
  assert.match(timeoutError.message, /MAY have landed/);
  assert.match(timeoutError.message, /3 of 3 attempt\(s\) were made/);
  assert.match(refusalError.message, /could not be reached/);
  assert.match(refusalError.message, /3 of 3 attempt\(s\) were made/);
});

test('I2 a 5xx is retried and ends as broker-error; a 4xx is answered once and NOT retried', async () => {
  let fiveCalls = 0;
  const five = createBrokerClient({
    sshTarget: 'secratary-ts',
    ...NO_WAIT,
    spawnImpl: (exe, argv, options) => {
      fiveCalls += 1;
      return fakeSpawn({ stdout: '{"error":"the authority is restarting"}\n503' })(exe, argv, options);
    },
  });
  const fiveError = await five.place(ONESHOT).then(() => null, (error) => error);
  assert.equal(fiveError.code, 'broker-error');
  assert.match(fiveError.message, /HTTP 503/);
  assert.match(fiveError.message, /3 of 3 attempt\(s\) were made/);
  assert.equal(fiveCalls, 3, 'a 5xx is a server error and is retried to the bound');

  let fourCalls = 0;
  const four = createBrokerClient({
    sshTarget: 'secratary-ts',
    ...NO_WAIT,
    spawnImpl: (exe, argv, options) => {
      fourCalls += 1;
      return fakeSpawn({ stdout: '{"error":"POST /place, not GET /place"}\n405' })(exe, argv, options);
    },
  });
  const fourError = await four.place(ONESHOT).then(() => null, (error) => error);
  assert.equal(fourError.code, 'broker-error');
  assert.match(fourError.message, /HTTP 405/);
  assert.match(fourError.message, /not retried/);
  assert.equal(fourCalls, 1, 'a 4xx is a client error and is never retried');
});

test('I2 nodes() is retried on a transport failure too', async () => {
  let calls = 0;
  const client = createBrokerClient({
    ...NO_WAIT,
    spawnImpl: (exe, argv, options) => {
      calls += 1;
      if (calls === 1) return fakeSpawn({ code: 255, stderr: 'ssh: connect timed out' })(exe, argv, options);
      return fakeSpawn({ stdout: JSON.stringify({ schema: 1, at: 'now', nodes: [{ node: 'zabz-tech', state: 'ok', slots: 18, freeSlots: 16 }] }) })(exe, argv, options);
    },
  });
  const report = await client.nodes({ fresh: true });
  assert.equal(calls, 2);
  assert.equal(report.nodes[0].freeSlots, 16);
  assert.equal(report.attempts, 2);
});
