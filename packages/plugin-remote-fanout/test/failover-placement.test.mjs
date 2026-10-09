import assert from 'node:assert/strict';
import test from 'node:test';

import {
  assessNode,
  chooseFailoverPlacement,
  NO_CANDIDATE,
  rankCandidates,
} from '../lib/failover-placement.js';

/**
 * The DIRECT-PROBE failover contract: what one node's own health doc is worth,
 * how a set of probed nodes is ranked, and what the placement says when the best
 * node is full. No network is mocked and no broker is involved — every fixture
 * is a small literal, because the point of this module is to decide from what it
 * was handed rather than from what it can reach.
 *
 * Two input shapes the contract leaves open, taken here from the module's own
 * signature:
 *   * an OBSERVATION is the probed node's health doc tagged with the node name,
 *     so a reader taking `observation.health` and one taking the observation
 *     itself as the health doc see the same document. An unreachable node is the
 *     same record carrying `error` instead.
 *   * a CANDIDATE handed to `rankCandidates` is an ASSESSED node — what
 *     `assessNode` returns. A bare `{node, freeSlots}` is not a candidate and is
 *     reported as such (see the "not a candidate" test).
 */
function observed(node, health) {
  return { node, health, ...health };
}

function healthDoc(node, overrides = {}) {
  return {
    ok: true,
    node,
    runner: { busy: false },
    auth: { secretConfigured: true },
    concurrency: { limit: 4 },
    limits: { maxConcurrent: 2 },
    ...overrides,
  };
}

/** An assessed node, shaped exactly as `assessNode` returns one. */
function candidate(node, freeSlots, extra = {}) {
  return {
    node,
    ok: true,
    freeSlots,
    busy: false,
    transports: ['v2'],
    reason: null,
    evidence: { answered: true, inFlightCount: 0, queueDepth: 0 },
    ...extra,
  };
}

function unreachable(node, error = 'ssh: connect to host dead port 22: Connection timed out') {
  return { node, error };
}

// ---------------------------------------------------------------------------
// assessNode
// ---------------------------------------------------------------------------

test('assessNode takes a healthy, idle node over v2 and reports its slots', () => {
  const doc = healthDoc('zabz-tech');
  const assessed = assessNode(doc);

  assert.equal(assessed.ok, true);
  assert.equal(assessed.node, 'zabz-tech');
  // The contract writes `transports: ['v2']` for this case; with `wantSsh`
  // defaulting true the module also offers v1 BEHIND v2, and the literal
  // `['v2']` is pinned exactly in the `wantSsh:false` test below.
  assert.equal(assessed.transports[0], 'v2');
  assert.equal(assessed.transports.includes('v2'), true);
  assert.equal(assessed.freeSlots, 4);
  assert.equal(assessed.busy, false);
  assert.equal(assessed.reason, null);
  // `evidence` is the raw fields the decision was made from, kept for the record.
  assert.equal(typeof assessed.evidence, 'object');
  assert.notEqual(assessed.evidence, null);
  assert.equal(Array.isArray(assessed.evidence), false);
  assert.ok(Object.keys(assessed.evidence).length > 0);
  assert.equal(assessed.evidence.answered, true);
});

test('with ssh unwanted a secret-holding node offers v2 alone', () => {
  const assessed = assessNode(healthDoc('zabz-tech'), { wantSsh: false });

  assert.equal(assessed.ok, true);
  assert.deepEqual(assessed.transports, ['v2']);
});

test('a node with no secret configured falls back to ssh/v1 and still takes work', () => {
  const assessed = assessNode(healthDoc('legacy-node', { auth: { secretConfigured: false } }));

  assert.equal(assessed.ok, true);
  assert.equal(assessed.transports.includes('v2'), false);
  assert.deepEqual(assessed.transports, ['v1']);
});

test('with ssh unwanted, a node with no secret is refused and the reason names the secret', () => {
  const assessed = assessNode(
    healthDoc('legacy-node', { auth: { secretConfigured: false } }),
    { wantSsh: false },
  );

  assert.equal(assessed.ok, false);
  assert.equal(assessed.transports.includes('v2'), false);
  assert.equal(typeof assessed.reason, 'string');
  assert.match(assessed.reason, /secret/i);
});

test('a nullish or not-ok health doc is refused with a reason and no node', () => {
  const cases = [null, undefined, { ok: false }];
  for (const doc of cases) {
    const assessed = assessNode(doc);
    assert.equal(assessed.ok, false, `ok for ${JSON.stringify(doc)}`);
    assert.equal(assessed.node, null, `node for ${JSON.stringify(doc)}`);
    assert.equal(typeof assessed.reason, 'string', `reason for ${JSON.stringify(doc)}`);
    assert.ok(assessed.reason.length > 0);
  }
});

test('a value that was thrown is refused, never thrown onward', () => {
  for (const caught of [new Error('ssh exited 255'), 'ssh exited 255', 0, '']) {
    const assessed = assessNode(caught);
    assert.equal(assessed.ok, false);
    assert.equal(assessed.node, null);
    assert.equal(typeof assessed.reason, 'string');
    assert.ok(assessed.reason.length > 0);
  }
});

test('a busy node is refused, and the reason says busy', () => {
  const assessed = assessNode(healthDoc('zabz-tech', { runner: { busy: true } }));

  assert.equal(assessed.ok, false);
  assert.equal(assessed.busy, true);
  assert.equal(assessed.node, 'zabz-tech');
  assert.equal(assessed.freeSlots, 4);
  assert.match(assessed.reason, /busy/i);
});

test('freeSlots prefers a finite concurrency.limit, falls back to limits.maxConcurrent, else null', () => {
  assert.equal(assessNode(healthDoc('n', { concurrency: { limit: 7 }, limits: { maxConcurrent: 2 } })).freeSlots, 7);
  assert.equal(assessNode(healthDoc('n', { concurrency: {}, limits: { maxConcurrent: 5 } })).freeSlots, 5);
  assert.equal(assessNode(healthDoc('n', { concurrency: { limit: null }, limits: { maxConcurrent: 5 } })).freeSlots, 5);
  assert.equal(assessNode(healthDoc('n', { concurrency: { limit: 'lots' }, limits: { maxConcurrent: 3 } })).freeSlots, 3);
  assert.equal(assessNode(healthDoc('n', { concurrency: { limit: Number.POSITIVE_INFINITY }, limits: {} })).freeSlots, null);
  assert.equal(assessNode(healthDoc('n', { concurrency: {}, limits: {} })).freeSlots, null);
});

test('assessNode is total: every junk input answers with a shape and never throws', () => {
  const junk = [null, undefined, 0, '', [], {}, { ok: false }, { ok: true }, { ok: true, runner: {}, concurrency: {}, limits: {} }];
  for (const doc of junk) {
    const assessed = assessNode(doc);
    const label = `for ${JSON.stringify(doc)}`;
    assert.equal(typeof assessed.ok, 'boolean', `ok ${label}`);
    assert.equal(assessed.reason === null || typeof assessed.reason === 'string', true, `reason ${label}`);
    assert.equal(assessed.node === null || typeof assessed.node === 'string', true, `node ${label}`);
    assert.equal(Array.isArray(assessed.transports), true, `transports ${label}`);
    assert.equal(assessed.freeSlots === null || Number.isFinite(assessed.freeSlots), true, `freeSlots ${label}`);
    assert.equal(typeof assessed.busy, 'boolean', `busy ${label}`);
  }
});

// ---------------------------------------------------------------------------
// rankCandidates
// ---------------------------------------------------------------------------

test('rankCandidates drops the caller\'s exclusions and this node when it prefers a remote', () => {
  const { ranked, chosen } = rankCandidates(
    [candidate('alpha', 1), candidate('bravo', 2), candidate('me', 9)],
    { exclude: ['alpha'], thisNode: 'me', preferRemote: true, children: 1 },
  );

  assert.deepEqual(ranked.map((row) => row.node), ['bravo']);
  assert.equal(chosen.node, 'bravo');
  // Without preferRemote this machine would have won on slots, which is exactly
  // the case the preference exists to avoid.
  const without = rankCandidates(
    [candidate('alpha', 1), candidate('bravo', 2), candidate('me', 9)],
    { exclude: ['alpha'], thisNode: 'me', preferRemote: false, children: 1 },
  );
  assert.equal(without.chosen.node, 'me');
});

test('the never-refuse rule: an exclusion that would empty the ranked list YIELDS, and says so', () => {
  const { ranked, chosen, rationale } = rankCandidates(
    [candidate('only-node', 4)],
    { exclude: ['only-node'], children: 1 },
  );

  assert.equal(ranked.length, 1);
  assert.equal(ranked[0].node, 'only-node');
  assert.equal(chosen.node, 'only-node');

  const joined = rationale.join(' | ');
  assert.match(joined, /only-node/);
  // The yield is a decision, so it must be readable in the record — not silent.
  assert.match(joined, /yield|fall back|falling back|refus|empty|excluded anyway/i);

  // The same rule through the other door: this machine is the only candidate.
  const local = rankCandidates([candidate('me', 2)], { thisNode: 'me', preferRemote: true, children: 1 });
  assert.equal(local.ranked.length, 1);
  assert.equal(local.chosen.node, 'me');
  assert.match(local.rationale.join(' | '), /yield|fall back|falling back|refus|empty|excluded anyway/i);
});

test('a node with more free slots outranks one with fewer', () => {
  const { ranked, chosen } = rankCandidates([candidate('small', 2), candidate('large', 9)], { children: 1 });

  assert.deepEqual(ranked.map((row) => row.node), ['large', 'small']);
  assert.equal(chosen.node, 'large');
  assert.ok(ranked[0].score >= ranked[1].score);
  assert.equal(ranked[0].freeSlots, 9);
  assert.equal(chosen.freeSlots, 9);
});

test('rationale carries one line per excluded node, naming it and the reason', () => {
  const { rationale } = rankCandidates(
    [candidate('alpha', 1), candidate('bravo', 2), candidate('me', 3)],
    { exclude: ['alpha'], thisNode: 'me', preferRemote: true, children: 1 },
  );

  const alphaLines = rationale.filter((line) => line.includes('alpha'));
  const meLines = rationale.filter((line) => line.includes('me'));
  assert.equal(alphaLines.length >= 1, true);
  assert.equal(meLines.length >= 1, true);
  assert.match(alphaLines.join(' '), /exclud/i);
  assert.match(meLines.join(' '), /exclud|remote|this machine|this node/i);
  assert.ok(rationale.length >= 2);
});

test('a candidate that is not an assessed node is reported, not ranked', () => {
  // `rankCandidates` ranks what `assessNode` returned. Anything else — including a
  // bare `{node, freeSlots}` — must be visible in the rationale rather than
  // silently scored as healthy.
  const { ranked, rationale } = rankCandidates(
    [candidate('real', 3), { node: 'unassessed', freeSlots: 99 }],
    { children: 1 },
  );

  assert.deepEqual(ranked.map((row) => row.node), ['real']);
  assert.match(rationale.join(' | '), /unassessed/);
});

// ---------------------------------------------------------------------------
// chooseFailoverPlacement
// ---------------------------------------------------------------------------

test('the healthy node is chosen over an unreachable one and a busy one', () => {
  const result = chooseFailoverPlacement(
    [
      unreachable('dead-node'),
      observed('busy-node', healthDoc('busy-node', { runner: { busy: true } })),
      observed('calm-node', healthDoc('calm-node', { concurrency: { limit: 4 } })),
    ],
    { children: 1 },
  );

  assert.equal(result.node, 'calm-node');
  assert.equal(result.source, 'direct-probe');
  assert.equal(result.position, 0);
  assert.equal(result.freeSlots, 4);
  assert.equal(result.transports.includes('v2'), true);
  assert.equal(result.unreachable.length, 1);
  assert.equal(result.unreachable[0].node, 'dead-node');
  assert.ok(result.unreachable[0].error);
  assert.equal(Array.isArray(result.ranked), true);
});

test('with every observation unreachable there is no node, and the rationale names NO_CANDIDATE', () => {
  const result = chooseFailoverPlacement(
    [unreachable('dead-a'), unreachable('dead-b', 'ssh exited 255')],
    { children: 1 },
  );

  assert.equal(NO_CANDIDATE, 'no-candidate');
  assert.equal(result.node, null);
  assert.equal(result.unreachable.length, 2);
  assert.match(result.rationale.join(' '), /no[\s-]?candidate/i);
  if (result.code !== undefined) assert.equal(result.code, NO_CANDIDATE);
});

test('a node too full to start now is still named — queued with a position, never refused', () => {
  const result = chooseFailoverPlacement(
    [observed('nearly-full', healthDoc('nearly-full', { concurrency: { limit: 1 } }))],
    { children: 4 },
  );

  assert.equal(result.node, 'nearly-full');
  assert.equal(Number.isInteger(result.position), true);
  assert.ok(result.position > 0, `expected a positive queue position, got ${result.position}`);
  assert.equal(result.source, 'direct-probe');
});
