/**
 * Tests for the retry/reroute policy.
 *
 * The policy exists because a failed dispatch used to be terminal. The half of it
 * that matters most is not "retry" — it is the list of failures that must NEVER be
 * retried, because the child may already have committed a branch or spent money.
 * So every test here that asserts a retry is paired with one that asserts the
 * refusal to retry.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_RETRY_POLICY,
  classifyFailure,
  childNeverStarted,
  describeAttempt,
  describeRetryPolicy,
  fallbackHarvest,
  planFor,
  resolveHarvest,
} from '../lib/retry-plan.js';

const outcome = (extra = {}) => ({ exitCode: 0, ms: 1, stdout: '', stderr: '', ...extra });
const parsed = (extra = {}) => ({ framed: true, host: 'ZABZ-YOGA', answer: 'MESH-HOST: ZABZ-YOGA\nOK', ...extra });

test('a clean run is not a failure at all', () => {
  assert.equal(classifyFailure({ outcome: outcome(), parsed: parsed() }), 'none');
});

test('THE ANTI-DUPLICATION RULE: a child that started is never re-dispatched', () => {
  // Every shape where evidence says the child began.
  const started = [
    { outcome: outcome({ exitCode: 1, stderr: 'boom' }), parsed: parsed(), startedEvidence: true },
    { outcome: outcome({ exitCode: 255, stderr: 'Connection timed out' }), parsed: { framed: false, answer: '' }, startedEvidence: true },
    { outcome: outcome({ timedOut: true }), parsed: { framed: false, answer: '' } },
    { outcome: outcome({ exitCode: -1 }), parsed: { framed: true, answer: 'MESH-HOST: H\nwork done' }, startedEvidence: true },
  ];
  for (const input of started) {
    const klass = classifyFailure(input);
    assert.equal(klass, 'child-ran-transport-fault', `expected harvest-not-retry for ${JSON.stringify(input.outcome)}`);
    const plan = planFor(klass, 0, {});
    assert.equal(plan.action, 'harvest');
    assert.equal(plan.delayMs, 0);
  }
});

test('a child that never launched and a healthy node is the one retry worth having', () => {
  assert.equal(childNeverStarted(outcome({ spawnError: 'ENOENT' }), undefined), true);
  assert.equal(classifyFailure({ outcome: outcome({ spawnError: 'spawn ssh ENOENT' }) }), 'transient-same-node');
  assert.equal(classifyFailure({ outcome: outcome({ exitCode: 127, stderr: 'sh: 1: dsh: not found' }), parsed: { framed: false } }), 'transient-same-node');
  assert.equal(planFor('transient-same-node', 0, { random: () => 0.5 }).action, 'retry');
});

test('a node-specific fault reroutes instead of retrying into the same wall', () => {
  for (const stderr of ['Permission denied (publickey)', 'Host key verification failed', 'Connection refused', 'kex_exchange_identification: read: Connection reset']) {
    assert.equal(
      classifyFailure({ outcome: outcome({ exitCode: 255, stderr }) }),
      'node-specific',
      `expected node-specific for: ${stderr}`,
    );
  }
  const plan = planFor('node-specific', 0, { random: () => 0.5 });
  assert.equal(plan.action, 'reroute');
  // The reroute delay must outlive the broker's 15 s capacity cache, or the new
  // placement is ranked against the reading that just failed.
  assert.ok(plan.delayMs >= 10_000, `reroute delay ${plan.delayMs} ms does not outlive the broker cache`);
});

test('a child that started and then DIED reroutes to another node; only a transport fault is harvested', () => {
  // The shape that cost a night (2026-10-08). The child started, its own code
  // raised, and it exited 1 with no frame and NO transport fault. The process is
  // gone, so "it may have done work, harvest it" protected nothing — and because
  // that was the answer, one broken node absorbed every dispatch in the fleet
  // while a verified-good node sat idle, and every session silently went local.
  const diedOnItsOwn = outcome({
    exitCode: 1,
    stderr: "PermissionError: [Errno 13] Permission denied: 'C:\\\\x\\\\mcp-launcher.log'\n  sys.exit(main())",
  });
  assert.equal(classifyFailure({ outcome: diedOnItsOwn, parsed: { framed: false } }), 'node-specific');
  assert.equal(planFor('node-specific', 0, { random: () => 0.5 }).action, 'reroute');

  // The other shape, and it must NOT move: the transport died mid-run, so the
  // child's last moment was never captured and it may still be working.
  const transportDied = outcome({ exitCode: 255, stderr: 'Read from remote host x: Connection reset' });
  assert.equal(classifyFailure({ outcome: transportDied, parsed: { framed: false } }), 'child-ran-transport-fault');
  assert.equal(planFor('child-ran-transport-fault', 0, {}).action, 'harvest');
});

test('the budget is bounded and says why it stopped', () => {
  const exhausted = planFor('transient-same-node', DEFAULT_RETRY_POLICY.maxAttempts - 1, {});
  assert.equal(exhausted.action, 'fail');
  assert.match(exhausted.reason, /transport attempts are spent/);

  const overCeiling = planFor('transient-same-node', 0, { elapsedMs: DEFAULT_RETRY_POLICY.totalCeilingMs + 1 });
  assert.equal(overCeiling.action, 'fail');
  assert.match(overCeiling.reason, /retry ceiling/);

  // The node budget is separate from the attempt budget: two nodes is the limit.
  const noMoreNodes = planFor('node-specific', 0, { distinctNodes: DEFAULT_RETRY_POLICY.maxDistinctNodes });
  assert.equal(noMoreNodes.action, 'retry', 'with the node budget spent it must retry the current node rather than another reroute');
});

test('a response the child itself decided is structural and is never re-run', () => {
  // A credential error with a frame and an answer: the child ran, the outcome is
  // its own, and re-running it would spend money twice for the same answer.
  assert.equal(
    classifyFailure({ outcome: outcome({ exitCode: 3 }), parsed: parsed({ answer: 'MESH-HOST: H\nMISSING_CREDENTIAL' }) }),
    'structural',
  );
  // A local cancellation is the caller's decision, not a fault.
  assert.equal(classifyFailure({ outcome: outcome(), parsed: parsed(), aborted: true }), 'structural');
  // A genuine wrong-machine run is a protocol fault: report it, never re-run it.
  assert.equal(classifyFailure({ outcome: outcome(), parsed: parsed(), hostMismatch: true }), 'structural');
  assert.equal(planFor('structural', 0, {}).action, 'fail');
});

test('harvest costs no budget: it is recovery, not a retry', () => {
  // Even with every budget spent, a started child is still harvested.
  const plan = planFor('child-ran-transport-fault', DEFAULT_RETRY_POLICY.maxAttempts, { elapsedMs: DEFAULT_RETRY_POLICY.totalCeilingMs * 2 });
  assert.equal(plan.action, 'harvest');
});

test('fallbackHarvest always returns something a reader can act on', () => {
  const empty = fallbackHarvest(undefined, undefined, {});
  assert.notEqual(empty.text, '', 'an empty result would be a silent failure');
  assert.equal(empty.complete, false);
  assert.match(empty.text, /exit=none/);

  const partial = fallbackHarvest(
    outcome({ exitCode: 255, stderr: 'Connection reset by peer', stdout: 'half a report' }),
    { framed: false, answer: '' },
    {},
  );
  assert.equal(partial.complete, false);
  assert.match(partial.text, /half a report/);
  assert.match(partial.text, /Connection reset by peer/);
  assert.ok(partial.parts.some((p) => p.source === 'stdout-tail'));
  assert.ok(partial.parts.some((p) => p.source === 'stderr-tail'));
});

test('the harvest is bounded, and says so when it truncated', () => {
  const huge = 'x'.repeat(50_000);
  const { text, parts } = fallbackHarvest(outcome({ stdout: huge }), { framed: false }, { maxBytes: 100 });
  assert.ok(text.length < 2_000, `salvage should be bounded, got ${text.length} chars`);
  const tail = parts.find((p) => p.source === 'stdout-tail');
  assert.match(tail.text, /truncated/);
});

test('resolveHarvest prefers the transport implementation and falls back safely', () => {
  const real = () => ({ text: 'from the transport', complete: true, parts: [] });
  assert.equal(resolveHarvest(real), real);
  assert.equal(resolveHarvest(undefined), fallbackHarvest);
  assert.equal(resolveHarvest(null), fallbackHarvest);
  assert.equal(resolveHarvest('not a function'), fallbackHarvest);
});

test('every classification maps to an action a caller can act on', () => {
  const seen = new Set();
  for (const klass of ['none', 'transient-same-node', 'node-specific', 'reroute-only', 'structural', 'child-ran-transport-fault']) {
    const plan = planFor(klass, 0, {});
    seen.add(plan.action);
    assert.ok(['accept', 'retry', 'reroute', 'harvest', 'fail'].includes(plan.action), `unknown action ${plan.action}`);
    assert.equal(typeof plan.reason, 'string');
    assert.ok(plan.reason.length > 0, `${klass} produced no reason`);
  }
  assert.deepEqual([...seen].sort(), ['accept', 'fail', 'harvest', 'reroute', 'retry']);
});

test('the reporting lines name the node, the verdict and the action', () => {
  const line = describeAttempt(2, { node: 'zabz-tech-linux', classification: 'node-specific', action: 'reroute', detail: 'child not-started', delayMs: 15_000, startedEvidence: false });
  assert.match(line, /attempt 2/);
  assert.match(line, /zabz-tech-linux/);
  assert.match(line, /node-specific/);
  assert.match(line, /child not-started/);
  assert.match(line, /rerouting in 15000 ms/i);

  const policyLine = describeRetryPolicy({});
  assert.match(policyLine, /NEVER re-dispatched/);
  assert.match(policyLine, /3 transport attempt/);
});

// ── THE WRAPPER'S MARKERS ARE NOT THE CHILD'S WORK ──────────────────────────────
// Measured 2026-10-28 14:49Z, ZABZ-TECH. A mesh child died in its MCP/TLS init
// (`getaddrinfo ENOTFOUND mcp.jina.ai`, `dsh: TRANSPORT: DeepSeek Messages transport
// failed`) having taken no step at all. Its stdout was the wrapper's own block and
// nothing else. Because `emittedMarkers` matched `FANOUT_BEGIN`/`FANOUT_TRANSPORT_HOST=`,
// and because `framed` was true, it was classified `structural` — "the child ran and its
// outcome is its own" — so the delegation was spent and never rerouted.
//
// FANOUT_BEGIN / FANOUT_TRANSPORT_HOST / FANOUT_END are printed by remote-script.js
// BEFORE the child is launched. Only `MESH-HOST:` is the child's own word.

const deadBeforeFirstStep = {
  exitCode: 1,
  ms: 149_334,
  stdout: 'FANOUT_TRANSPORT_HOST_4e6b29cf=ZABZ-TECH\nFANOUT_TRANSPORT_CWD_4e6b29cf=C:\\Users\\ezabz\nFANOUT_BEGIN_4e6b29cf\n\nFANOUT_END_4e6b29cf=1\n',
  stderr: 'Error: getaddrinfo ENOTFOUND mcp.jina.ai\n  at fetchWithMcpHeaders (mcp-remote/dist/chunk-UZ6Y4QJH.js)\n',
};

test('a child that died before its first step is rerouted, not filed as a decided outcome', () => {
  // The frame is present and empty — remote-script wrote it around nothing.
  const klass = classifyFailure({ outcome: deadBeforeFirstStep, parsed: { framed: true, host: 'ZABZ-TECH', answer: '' } });
  assert.equal(klass, 'node-specific', 'wrapper markers and an empty frame must not read as the child having worked');

  const plan = planFor(klass, 0, { random: () => 0.5 });
  assert.equal(plan.action, 'reroute');
  assert.ok(plan.delayMs >= 10_000, 'reroute must outlive the broker capacity cache');
  assert.doesNotMatch(plan.reason, /decided work/, 'this child decided nothing');
});

test('but a child that DID answer keeps its answer, whatever its exit code', () => {
  const klass = classifyFailure({
    outcome: { ...deadBeforeFirstStep, stdout: 'MESH-HOST: zabz-tech\n\nFANOUT_END_x=1\n' },
    parsed: { framed: true, host: 'ZABZ-TECH', answer: 'MESH-HOST: zabz-tech\nI could not finish: the repo is dirty.' },
  });
  assert.equal(klass, 'structural');
  assert.equal(planFor(klass, 0, {}).action, 'fail');
});

test('a child that started and then died unanswered is still harvested, never re-run', () => {
  // startedEvidence is the independent proof that the child began, and it outranks
  // the absence of an answer — this is the anti-duplication rule and it must hold.
  const klass = classifyFailure({
    outcome: deadBeforeFirstStep,
    parsed: { framed: true, host: 'ZABZ-TECH', answer: '' },
    startedEvidence: true,
  });
  assert.equal(klass, 'child-ran-transport-fault');
  assert.equal(planFor(klass, 0, {}).action, 'harvest');
});
