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
});

test('an ssh that cannot reach the authority is broker-unreachable, and the message names where', async () => {
  const client = createBrokerClient({
    sshTarget: 'secratary-ts',
    spawnImpl: fakeSpawn({ code: 255, stderr: 'ssh: connect to host secratary-ts port 22: Connection timed out' }),
  });
  await assert.rejects(
    () => client.place({ kind: 'oneShot', children: 1, worktreeGiB: 0, prefer: null, exclude: [] }),
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
  const client = createBrokerClient({ spawnImpl: fakeSpawn({ throwError: 'spawn ssh ENOENT' }) });
  await assert.rejects(
    () => client.place({ kind: 'oneShot', children: 1, worktreeGiB: 0, prefer: null, exclude: [] }),
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
    const client = createBrokerClient({ spawnImpl: fakeSpawn(scenario) });
    await assert.rejects(
      () => client.place({ kind: 'oneShot', children: 1, worktreeGiB: 0, prefer: null, exclude: [] }),
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
  const client = createBrokerClient({ spawnImpl: fakeSpawn({ seen }) });
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
