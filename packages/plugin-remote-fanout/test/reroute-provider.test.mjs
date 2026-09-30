/**
 * The provider's half of the reroute: it must ASK for a different node, not hope for one.
 *
 * MEASURED 2026-09-30: the placer re-offered the node that had just failed and the
 * provider had to notice and skip it. That works by luck, not by design — and a reroute
 * that lands back on a dead node wastes the remaining attempt on the same wall.
 *
 * So the provider now passes every node it has already tried as `excludeNodes` on the
 * next `acquire`, and the broker honours that list (mesh-broker/test/reroute.test.mjs
 * pins the broker's side). This file pins the provider's side: what it asks for, and
 * what it says when it does not get it.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { RemoteOneShotProvider } from '../lib/provider.js';
import { markers } from '../lib/remote-script.js';

const REMOTE = { command: 'dsh', profile: 'headless', shell: 'powershell' };
const signal = () => new AbortController().signal;
const textOf = (result) => result.output.map((b) => b.text).join('\n');

/** A framed answer for a script, using the transport's own marker builder. */
function frame(script, { host = 'ZABZ-YOGA', answer = 'MESH-HOST: ZABZ-YOGA\nOK', exit = 0 } = {}) {
  const nonce = /FANOUT_BEGIN_([0-9a-f]+)/.exec(script)?.[1] ?? '';
  const m = markers(nonce);
  return [`${m.host}${host}`, `${m.cwd}C:\\work`, m.begin, answer, m.end, `${m.exit}${exit}`].join('\n');
}

/**
 * A placer that hands out the nodes it is told to and RECORDS every ask, so a test can
 * assert what the provider requested rather than only what it ended up doing.
 */
function recordingPlacer(nodes, { outcomeFor } = {}) {
  const asks = [];
  let index = 0;
  const build = (nodeName) => ({
    source: 'broker',
    node: nodeName,
    hosts: [nodeName.toUpperCase()],
    position: 0,
    tier: 'fits',
    score: 10,
    lease: `lease-${nodeName}`,
    facts: { command: 'dsh', profile: 'headless', shell: 'powershell', cwd: 'C:\\work' },
    pressure: null,
    pressureDecision: null,
    transport: {
      describe: () => `ssh to ${nodeName}`,
      start(request) {
        const outcome = outcomeFor(nodeName);
        return {
          done: Promise.resolve({
            ms: 3,
            exitCode: 0,
            stderr: '',
            ...outcome,
            // The recorded host must MATCH the node the placement named, or the provider
            // rightly fails the run as a wrong-machine run — which is a different test.
            stdout: outcome.stdout ?? frame(request.script, { ...outcome, host: nodeName.toUpperCase() }),
          }),
          kill: () => {},
        };
      },
    },
  });
  return {
    kind: 'broker',
    asks,
    describe: () => 'recording placer',
    explain: () => 'recording placer',
    async acquire(options = {}) {
      asks.push(options);
      const requested = options.excludeNodes ?? [];
      // Honour the exclusion the way the broker does: prefer a node that is not on it.
      const preferred = nodes.filter((n) => !requested.includes(n));
      const chosen = (preferred.length > 0 ? preferred : nodes)[0];
      void index;
      return build(chosen);
    },
    async waitForSlot() { return { waited: false, waitedMs: 0 }; },
    async release() { return { released: true, ok: true }; },
    transportFor(placement) { return placement.transport; },
  };
}

test('a reroute asks for a node that is NOT the one that just failed', async () => {
  const placer = recordingPlacer(['node-a', 'node-b'], {
    // node-a refuses the session outright (a hard ssh refusal = node-specific).
    outcomeFor: (node) => (node === 'node-a'
      ? { exitCode: 255, stderr: 'ssh: connect to host node-a port 22: Connection refused', stdout: '' }
      : { answer: 'MESH-HOST: NODE-B\nSECOND NODE DID THE WORK' }),  });
  const provider = new RemoteOneShotProvider({
    name: 'remote-ssh',
    placer,
    remote: REMOTE,
    mailboxRoot: false,
    retryPolicy: { backoffMs: 1, rerouteBackoffMs: 1 },
  });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'work' }], signal: signal() });
  const result = await run.result;
  const text = textOf(result);

  assert.equal(result.stopReason, 'completed');
  assert.match(text, /SECOND NODE DID THE WORK/, 'the retry on the other node produced the result');

  // THE PROPERTY UNDER TEST: the second ask named node-a as one it must not return to.
  assert.equal(placer.asks.length, 2, 'one ask per attempt');
  assert.deepEqual(placer.asks[0].excludeNodes, [], 'the first ask excludes nothing — nothing has failed yet');
  assert.deepEqual(placer.asks[1].excludeNodes, ['node-a'], 'the reroute excludes the node that just failed');

  // And the ledger says what happened, in the child's own report.
  assert.match(text, /attempt 1 = node "node-a" — node-specific/);
  assert.match(text, /REROUTING IN \d+ ms/);
  assert.match(text, /attempt 2 = node "node-b"/);
  await run.dispose();
});

test('when the exclusion cannot be honoured the report says so instead of implying a fresh node', async () => {
  // The honest failure: every node has already failed, so the exclusion names them all
  // and the placer has nowhere else to go. The reroute then lands back on a node it had
  // ruled out — and the parent must be TOLD, because the same node is likely to fail the
  // same way and the caller should not read this as a healthy retry.
  const placer = recordingPlacer(['only-node'], {
    outcomeFor: () => ({ exitCode: 255, stderr: 'ssh: Permission denied (publickey)', stdout: '' }),
  });
  const provider = new RemoteOneShotProvider({
    name: 'remote-ssh',
    placer,
    remote: REMOTE,
    mailboxRoot: false,
    retryPolicy: { backoffMs: 1, rerouteBackoffMs: 1 },
  });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'work' }], signal: signal() });
  const result = await run.result;
  const text = textOf(result);

  // It exhausted its attempts rather than looping, and each attempt is on the record.
  assert.equal(placer.asks.length, 3, 'the attempt budget is bounded at three');
  assert.match(text, /attempt 1 = node "only-node"/);
  assert.match(text, /attempt 2 = node "only-node"/);
  assert.match(text, /re-offered|excluded/);
  assert.notEqual(result.stopReason, 'completed', 'a child that never launched must not be reported as a success');
  await run.dispose();
});
