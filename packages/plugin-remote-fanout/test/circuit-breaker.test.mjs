import assert from 'node:assert/strict';
import test from 'node:test';

import { createCircuitBreaker } from '../lib/circuit-breaker.js';

/** A deterministic clock the test advances by hand. */
function fakeClock(start = 1_000_000) {
  const clock = { t: start };
  return { now: () => clock.t, advance: (ms) => { clock.t += ms; }, at: () => clock.t, clock };
}

const nodeSnapshot = (breaker, node) => breaker.snapshot().nodes[node];

test('a new node is closed until the failure threshold is reached', () => {
  const time = fakeClock();
  const breaker = createCircuitBreaker({ now: time.now, failureThreshold: 3, cooldownMs: 60000 });

  assert.equal(breaker.state('node-a'), 'closed');
  assert.equal(breaker.allow('node-a'), true);

  breaker.recordFailure('node-a');
  breaker.recordFailure('node-a');
  assert.equal(breaker.state('node-a'), 'closed', 'two failures must not trip a threshold of three');
  assert.deepEqual(nodeSnapshot(breaker, 'node-a'), {
    state: 'closed', consecutiveFailures: 2, openedAt: 0, sleepingMs: 0, lastKind: 'transport',
  });

  breaker.recordFailure('node-a');
  assert.equal(breaker.state('node-a'), 'open');
  assert.deepEqual(nodeSnapshot(breaker, 'node-a'), {
    state: 'open', consecutiveFailures: 3, openedAt: time.at(), sleepingMs: 60000, lastKind: 'transport',
  });
});

test('an open circuit refuses work and sleeps until the cooldown elapses', () => {
  const time = fakeClock();
  const breaker = createCircuitBreaker({ now: time.now, failureThreshold: 1, cooldownMs: 30000 });
  breaker.recordFailure('node-a');

  assert.equal(breaker.allow('node-a'), false);
  assert.equal(breaker.state('node-a'), 'open');
  assert.equal(breaker.sleepUntil('node-a'), time.at() + 30000);

  time.advance(29999);
  assert.equal(breaker.allow('node-a'), false, 'still cooling one ms before the cooldown ends');
  assert.equal(breaker.sleepUntil('node-a'), time.at() + 1);
});

test('a success while closed resets the consecutive-failure count', () => {
  const time = fakeClock();
  const breaker = createCircuitBreaker({ now: time.now, failureThreshold: 3 });
  breaker.recordFailure('node-a');
  breaker.recordFailure('node-a');
  breaker.recordSuccess('node-a');
  assert.equal(breaker.state('node-a'), 'closed');
  assert.equal(nodeSnapshot(breaker, 'node-a').consecutiveFailures, 0, 'a success must clear the streak');
  breaker.recordFailure('node-a');
  breaker.recordFailure('node-a');
  assert.equal(breaker.state('node-a'), 'closed', 'the count must restart after the success');
});

test('an open circuit half-opens once the cooldown passes, and closes after a success', () => {
  const time = fakeClock();
  const breaker = createCircuitBreaker({ now: time.now, failureThreshold: 2, cooldownMs: 10000, halfOpenSuccesses: 1 });
  breaker.recordFailure('node-a');
  breaker.recordFailure('node-a');
  assert.equal(breaker.state('node-a'), 'open');

  time.advance(10000);
  assert.equal(breaker.state('node-a'), 'half-open');
  assert.equal(breaker.allow('node-a'), true);
  assert.equal(breaker.sleepUntil('node-a'), 0);
  assert.deepEqual(nodeSnapshot(breaker, 'node-a'), {
    state: 'half-open', consecutiveFailures: 2, openedAt: time.at() - 10000, sleepingMs: 0, lastKind: 'transport',
  });

  breaker.recordSuccess('node-a');
  assert.equal(breaker.state('node-a'), 'closed');
  assert.deepEqual(nodeSnapshot(breaker, 'node-a'), {
    state: 'closed', consecutiveFailures: 0, openedAt: 0, sleepingMs: 0, lastKind: undefined,
  });
});

test('a failure while half-open re-opens the circuit with a fresh cooldown', () => {
  const time = fakeClock();
  const breaker = createCircuitBreaker({ now: time.now, failureThreshold: 1, cooldownMs: 5000 });
  breaker.recordFailure('node-a');
  time.advance(5000);
  assert.equal(breaker.state('node-a'), 'half-open');

  breaker.recordFailure('node-a');
  assert.equal(breaker.state('node-a'), 'open');
  assert.equal(breaker.sleepUntil('node-a'), time.at() + 5000);
  assert.equal(nodeSnapshot(breaker, 'node-a').consecutiveFailures, 2);
});

test('halfOpenSuccesses=2 needs two probe successes to close', () => {
  const time = fakeClock();
  const breaker = createCircuitBreaker({ now: time.now, failureThreshold: 1, cooldownMs: 1000, halfOpenSuccesses: 2 });
  breaker.recordFailure('node-a');
  time.advance(1000);
  assert.equal(breaker.state('node-a'), 'half-open');

  breaker.recordSuccess('node-a');
  assert.equal(breaker.state('node-a'), 'half-open', 'one success is not enough when two are required');
  breaker.recordSuccess('node-a');
  assert.equal(breaker.state('node-a'), 'closed');
});

test("'structural' failures never trip the circuit", () => {
  const time = fakeClock();
  const breaker = createCircuitBreaker({ now: time.now, failureThreshold: 2, cooldownMs: 60000 });

  for (let i = 0; i < 10; i += 1) breaker.recordFailure('node-a', { kind: 'structural' });
  assert.equal(breaker.state('node-a'), 'closed', 'a child that ran and answered wrongly is not a transport failure');
  assert.equal(breaker.allow('node-a'), true);
  assert.equal(breaker.sleepUntil('node-a'), 0);
  assert.equal(nodeSnapshot(breaker, 'node-a').consecutiveFailures, 0);
  assert.equal(nodeSnapshot(breaker, 'node-a').lastKind, 'structural');

  // A structural failure must not open a half-open circuit either.
  breaker.recordFailure('node-a');
  breaker.recordFailure('node-a');
  assert.equal(breaker.state('node-a'), 'open');
  time.advance(60000);
  assert.equal(breaker.state('node-a'), 'half-open');
  breaker.recordFailure('node-a', { kind: 'structural' });
  assert.equal(breaker.state('node-a'), 'half-open', 'a wrong answer must not reopen the wire');
});

test('transport-class kinds are counted and recorded, and a bare failure defaults to transport', () => {
  const time = fakeClock();
  const breaker = createCircuitBreaker({ now: time.now, failureThreshold: 1 });
  breaker.recordFailure('node-a', { kind: 'timeout' });
  assert.equal(breaker.state('node-a'), 'open');
  assert.equal(nodeSnapshot(breaker, 'node-a').lastKind, 'timeout');

  time.advance(60000);
  breaker.recordSuccess('node-a');
  breaker.recordFailure('node-a');
  assert.equal(breaker.state('node-a'), 'open');
  assert.equal(nodeSnapshot(breaker, 'node-a').lastKind, 'transport');
});

test('nodes are independent and snapshot covers each one', () => {
  const time = fakeClock();
  const breaker = createCircuitBreaker({ now: time.now, failureThreshold: 1, cooldownMs: 1000 });
  breaker.recordFailure('node-a');
  breaker.recordSuccess('node-b');
  const snapshot = breaker.snapshot();
  assert.deepEqual(Object.keys(snapshot.nodes).sort(), ['node-a', 'node-b']);
  assert.equal(snapshot.nodes['node-a'].state, 'open');
  assert.equal(snapshot.nodes['node-b'].state, 'closed');
  assert.equal(breaker.allow('node-b'), true);
});
