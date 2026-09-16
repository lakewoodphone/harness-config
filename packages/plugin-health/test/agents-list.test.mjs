/**
 * Tests for the `list_agents` deadline + cache — `node --test test/agents-list.test.mjs`.
 *
 * Every case here is a behaviour the shipped tool does not have, and the failure
 * mode it exists to remove:
 *   * a second call inside the TTL must not re-scan;
 *   * two CONCURRENT calls must produce exactly one scan;
 *   * a scan that outlives the deadline must return (cached or explicit), not hang;
 *   * an empty listing must render as visible text, never as a blank card;
 *   * the definition must declare `timeoutMs`, or the shipped timeout policy
 *     passes the call straight through and there is no cancellation at all.
 *
 * The engine is never started here. The service calls are stubs, so a failure is
 * a failure of this package.
 */

import { strict as assert } from 'node:assert';
import test from 'node:test';

import {
  ListingCache,
  resolveScope,
  projectListing,
  renderListing,
  registerListAgents,
  listingStats,
} from '../lib/agents-list.js';

const child = (id, overrides = {}) => ({ kind: 'child', id, label: `label ${id}`, mode: 'continuable', ...overrides });

// ── the cache ───────────────────────────────────────────────────────────────

test('a listing inside the TTL is served without a second scan', async () => {
  const cache = new ListingCache({ ttlMs: 5000 });
  let scans = 0;
  const load = async () => { scans += 1; return ['a']; };
  const first = await cache.resolve('children', load);
  const second = await cache.resolve('children', load);
  assert.equal(scans, 1, 'the second call re-scanned');
  assert.equal(first.cached, false);
  assert.equal(second.cached, true);
  assert.deepEqual(second.value, ['a']);
  assert.ok(second.ageMs >= 0);
});

test('a listing past the TTL scans again', async () => {
  const cache = new ListingCache({ ttlMs: 1 });
  let scans = 0;
  const load = async () => { scans += 1; return [scans]; };
  await cache.resolve('children', load);
  await new Promise((resolve) => setTimeout(resolve, 20));
  const second = await cache.resolve('children', load);
  assert.equal(scans, 2);
  assert.equal(second.cached, false);
  assert.deepEqual(second.value, [2]);
});

test('a TTL of zero always re-scans, which is how the raw cost is measured', async () => {
  const cache = new ListingCache({ ttlMs: 0 });
  let scans = 0;
  const load = async () => { scans += 1; return []; };
  await cache.resolve('children', load);
  await cache.resolve('children', load);
  assert.equal(scans, 2);
});

test('concurrent callers coalesce onto ONE scan — the case that used to cost N scans', async () => {
  const cache = new ListingCache({ ttlMs: 5000 });
  let scans = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const load = async () => { scans += 1; await gate; return ['shared']; };
  const inFlight = Promise.all([
    cache.resolve('children', load),
    cache.resolve('children', load),
    cache.resolve('children', load),
  ]);
  release();
  const results = await inFlight;
  assert.equal(scans, 1, `three concurrent callers caused ${scans} scans`);
  for (const result of results) assert.deepEqual(result.value, ['shared']);
  assert.equal(results.filter((result) => result.coalesced).length, 2, 'the later two should be marked coalesced');
  assert.equal(cache.inFlight('children'), false, 'the flight must be cleared when it settles');
});

test('a failed scan does not poison the cache or leave a stuck flight', async () => {
  const cache = new ListingCache({ ttlMs: 5000 });
  await assert.rejects(() => cache.resolve('children', async () => { throw new Error('scan failed'); }), /scan failed/);
  assert.equal(cache.inFlight('children'), false);
  assert.equal(cache.peek('children'), undefined, 'a failure must not be cached as a value');
});

test('the two scopes are cached separately', async () => {
  const cache = new ListingCache({ ttlMs: 5000 });
  let scans = 0;
  const load = async (tag) => { scans += 1; return [tag]; };
  await cache.resolve('children', () => load('c'));
  await cache.resolve('descendants', () => load('d'));
  assert.equal(scans, 2);
  assert.deepEqual(cache.peek('children').value, ['c']);
  assert.deepEqual(cache.peek('descendants').value, ['d']);
});

// ── the projection and the rendering ────────────────────────────────────────

test('scope defaults to children and accepts only descendants as the alternative', () => {
  assert.equal(resolveScope({}), 'children');
  assert.equal(resolveScope({ scope: 'children' }), 'children');
  assert.equal(resolveScope({ scope: 'descendants' }), 'descendants');
  assert.equal(resolveScope({ scope: 'nonsense' }), 'children');
  assert.equal(resolveScope(null), 'children');
});

test('a one-shot child is dropped and a diagnostic is kept, exactly as the shipped tool does', () => {
  const entries = [
    child('a'),
    { kind: 'child', id: 'b', label: 'one shot', mode: 'one-shot' },
    { kind: 'diagnostic', id: 'c', reason: 'corrupt' },
  ];
  const rows = projectListing(undefined, entries, 'children');
  assert.deepEqual(rows.map((row) => row.id), ['a', 'c']);
  assert.equal(rows[0].kind, 'child');
  assert.equal(rows[1].kind, 'diagnostic');
  assert.equal(rows[1].reason, 'corrupt');
});

test('status comes from the live registry, and ready means storage only', () => {
  const agents = {
    get: (id) => ({ a: { status: 'running' }, b: { status: 'idle' } }[id]),
  };
  const rows = projectListing(agents, [child('a'), child('b'), child('c')], 'children');
  assert.deepEqual(rows.map((row) => row.status), ['running', 'idle', 'ready']);
});

test('descendants carry their position and children do not', () => {
  const entries = [child('a', { parentId: 'p', depth: 1 }), child('b', { parentId: 'a', depth: 2 })];
  const descendants = projectListing(undefined, entries, 'descendants');
  assert.deepEqual(descendants.map((row) => [row.parent, row.depth]), [['p', 1], ['a', 2]]);
  const children = projectListing(undefined, entries, 'children');
  assert.equal('parent' in children[0], false);
  assert.equal('depth' in children[0], false);
});

test('an empty listing renders visible text, never an empty string', () => {
  const blocks = renderListing({}, []);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].type, 'text');
  assert.equal(blocks[0].text, '(no subagents)');
  assert.ok(blocks[0].text.length > 0);
});

test('a timed-out listing renders a sentence, not a blank', () => {
  const blocks = renderListing({ scope: 'children' }, [{ kind: 'diagnostic', id: 'list_agents', reason: 'unavailable' }]);
  assert.ok(blocks[0].text.includes('unavailable'));
  assert.ok(blocks[0].text.trim().length > 0);
});

test('the rendered rows keep the shipped format', () => {
  const blocks = renderListing({ scope: 'descendants' }, [
    { kind: 'child', id: 'x', status: 'running', label: 'mine', parent: 'root', depth: 1 },
  ]);
  assert.equal(blocks[0].text, 'x [running] parent=root depth=1 — mine');
});

// ── the registered tool ─────────────────────────────────────────────────────

/** Register the tool against stub services and return its definition. */
function mountTool({ subagents, agents = {}, options = {} } = {}) {
  let captured;
  const services = { subagents, agents };
  // The real registration is `ctx.tools.register(...)`, so the stub must expose
  // `tools` as a property exactly as Cordis exposes a service.
  const tools = { register: (definition) => { captured = definition; return () => {}; } };
  const ctx = {
    tools,
    get: (name) => (name === 'tools' ? tools : services[name]),
    effect: (fn) => { fn(); },
    logger: { warn: () => {}, info: () => {} },
  };
  registerListAgents(ctx, { cacheMs: 0, ...options });
  return { definition: captured, ctx };
}

test('the registered definition keeps the name, declares a JSON-Schema parameter and a timeout', () => {
  const { definition } = mountTool({ subagents: { listChildren: async () => [] } });
  assert.equal(definition.name, 'list_agents');
  // Raw JSON Schema, not the author DSL: `tools.register` passes `parameters`
  // through to the wire schema unchanged.
  assert.equal(definition.parameters.type, 'object');
  assert.deepEqual(definition.parameters.properties.scope.enum, ['children', 'descendants']);
  assert.equal(typeof definition.output.render, 'function');
  assert.equal(definition.output.schema.type, 'array');
  // THE POINT OF THIS TEST: without `timeoutMs` the shipped policy at
  // dsh-tool-call-timeout-policy/lib/index.js:123-124 returns next() and never
  // arms a deadline, which is why the original could hang forever.
  assert.ok(Number.isFinite(definition.timeoutMs), 'the definition must declare timeoutMs');
  assert.ok(definition.timeoutMs > 5000, 'the hard backstop must sit behind the cooperative deadline');
});

test('execute lists children through the service and projects them', async () => {
  const calls = [];
  const subagents = {
    listChildren: async (id, signal) => { calls.push({ id, aborted: signal?.aborted ?? false }); return [child('kid', { mode: 'continuable' })]; },
    listDescendants: async () => { throw new Error('descendants must not be called for the children scope'); },
  };
  const { definition } = mountTool({ subagents, agents: { get: () => ({ status: 'running' }) } });
  const rows = await definition.execute({}, { agent: { id: 'root' } });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].id, 'root');
  assert.deepEqual(rows, [{ kind: 'child', id: 'kid', label: 'label kid', status: 'running' }]);
});

test('execute refuses without a calling agent rather than inventing an empty list', async () => {
  const { definition } = mountTool({ subagents: { listChildren: async () => [] } });
  await assert.rejects(() => definition.execute({}, {}), /requires a calling agent/);
});

test('a scan that outlives the deadline returns an explicit diagnostic instead of hanging', async () => {
  const never = new Promise(() => {});
  const subagents = { listChildren: () => never };
  const { definition } = mountTool({ subagents, options: { deadlineMs: 150, maxDeadlineMs: 1000 } });
  const startedAt = Date.now();
  const rows = await definition.execute({}, { agent: { id: 'root' } });
  const elapsed = Date.now() - startedAt;
  assert.ok(elapsed < 3000, `the deadline did not fire promptly (${elapsed} ms)`);
  assert.deepEqual(rows, [{ kind: 'diagnostic', id: 'list_agents', reason: 'unavailable' }]);
  // And it renders as text, so the operator sees a sentence and not a blank.
  const blocks = definition.output.render({}, rows);
  assert.ok(blocks[0].text.length > 0);
  assert.match(blocks[0].text, /unavailable/);
});

test('a timed-out call serves the last known listing instead of nothing', async () => {
  let hang = false;
  const subagents = {
    listChildren: async () => (hang ? new Promise(() => {}) : [child('known')]),
  };
  const { definition } = mountTool({ subagents, options: { cacheMs: 1, deadlineMs: 150, maxDeadlineMs: 1000 } });
  const first = await definition.execute({}, { agent: { id: 'root' } });
  assert.deepEqual(first.map((row) => row.id), ['known']);
  // Past the TTL, and now the scan never finishes: the stale listing is the
  // honest answer, and it is strictly better than a blank.
  await new Promise((resolve) => setTimeout(resolve, 30));
  hang = true;
  const second = await definition.execute({}, { agent: { id: 'root' } });
  assert.deepEqual(second.map((row) => row.id), ['known']);
  assert.equal(listingStats.staleServes >= 1, true);
});

test('two calls inside the TTL cause exactly one scan and report it in the counters', async () => {
  let scans = 0;
  const subagents = { listChildren: async () => { scans += 1; return [child(`n${scans}`)]; } };
  const before = { ...listingStats };
  const { definition } = mountTool({ subagents, options: { cacheMs: 60_000 } });
  await definition.execute({}, { agent: { id: 'root' } });
  await definition.execute({}, { agent: { id: 'root' } });
  assert.equal(scans, 1, 'the second call re-scanned inside the TTL');
  assert.equal(listingStats.scans, before.scans + 1);
  assert.equal(listingStats.hits, before.hits + 1);
});

test('a listing with no subagents at all still renders as text', async () => {
  const subagents = { listChildren: async () => [] };
  const { definition } = mountTool({ subagents, options: { cacheMs: 0 } });
  const rows = await definition.execute({}, { agent: { id: 'root' } });
  assert.deepEqual(rows, []);
  const blocks = definition.output.render({}, rows);
  assert.equal(blocks[0].text, '(no subagents)');
});

test('an absent subagents service is reported as unavailable, not as an empty fleet', async () => {
  const { definition } = mountTool({ subagents: undefined });
  const rows = await definition.execute({}, { agent: { id: 'root' } });
  assert.deepEqual(rows, [{ kind: 'diagnostic', id: 'list_agents', reason: 'unavailable' }]);
  assert.equal(listingStats.failures >= 1, true);
});
