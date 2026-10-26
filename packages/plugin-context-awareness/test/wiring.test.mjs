/**
 * The WIRING half of dsh-plugin-context-awareness — the listeners, not the prose.
 *
 * The engine's real event loop is not mocked here; a fake `ctx` drives the two listeners and
 * the tool closure with the exact shapes the engine passes (`session/event(session, event)`,
 * `tools/post-execute(exec, result, next)`, `execute(args, run)`). What this proves:
 *
 *   * a notice is ATTACHED and preserved alongside every downstream context;
 *   * it fires once (orientation), then only on a band change, then again after a compaction;
 *   * the compaction notice survives an unreadable meter instead of inventing a number;
 *   * the tool answers from the same reading, and refuses to invent one.
 *
 * What it cannot prove — and does not claim — is that the engine delivers `additionalContexts`
 * to the model. That was measured in a live session: the notice rendered at 208,587 of 1,000,000.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { apply } from '../lib/index.js';

const NEXT = async () => ({ kind: 'enter', additionalContexts: [] });

/** A ctx that records what the plugin installs and lets the test drive it. */
function makeCtx({ occupancy = 200000, window = 1_000_000, meterThrows = false } = {}) {
  const handlers = new Map();
  const registered = [];
  const state = { occupancy, meterThrows };

  const ctx = {
    on(event, handler) {
      handlers.set(event, [...(handlers.get(event) ?? []), handler]);
      return () => {};
    },
    get(service) {
      if (service !== 'tokenMeter') return undefined;
      return {
        measure() {
          if (state.meterThrows) throw new Error('meter exploded');
          return { totalTokens: state.occupancy, baseline: { kind: 'usage' } };
        },
      };
    },
    inject(_deps, body) {
      body(ctx);
    },
    effect(fn) {
      fn();
      return () => {};
    },
    tools: {
      register(definition) {
        registered.push(definition);
        return () => {};
      },
    },
  };

  const fire = async (event, session, payload) => {
    for (const handler of handlers.get(event) ?? []) await handler(session, payload);
  };

  const step = async (session) => {
    const downstream = { kind: 'enter', additionalContexts: [{ marker: 'downstream' }] };
    let captured;
    for (const handler of handlers.get('tools/post-execute') ?? []) {
      captured = await handler({ agent: { session } }, {}, async () => downstream);
    }
    return captured;
  };

  return { ctx, state, registered, fire, step, handlers };
}

const sessionWith = (window = 1_000_000) => ({ requestHeader: () => ({ config: { contextWindow: window } }) });

test('orientation is attached once, and never at the cost of the downstream contexts', async () => {
  const { ctx, step } = makeCtx({ occupancy: 208587 });
  const session = sessionWith();
  apply(ctx, {});

  const first = await step(session);
  assert.equal(first.kind, 'enter');
  assert.equal(first.additionalContexts.length, 2, 'the notice is prepended, the downstream context kept');
  const notice = first.additionalContexts[0];
  assert.equal(notice.source.kind, 'context-awareness');
  assert.match(notice.content[0].text, /208,587 of 1,000,000/);
  assert.match(notice.content[0].text, /band comfortable/);
  assert.equal(first.additionalContexts[1].marker, 'downstream');

  const second = await step(session);
  assert.equal(second.additionalContexts.length, 1, 'no second orientation, no band change');
  assert.equal(second.additionalContexts[0].marker, 'downstream');
});

test('a band change speaks once, and a lower band does not speak again', async () => {
  const { ctx, state, step } = makeCtx({ occupancy: 100000 });
  const session = sessionWith();
  apply(ctx, {});
  await step(session);

  state.occupancy = 630000; // 63% -> tightening
  const tightened = await step(session);
  assert.equal(tightened.additionalContexts.length, 2);
  assert.match(tightened.additionalContexts[0].content[0].text, /band tightening; compaction fires near 700,000/);

  state.occupancy = 640000; // same band
  const same = await step(session);
  assert.equal(same.additionalContexts.length, 1);

  state.occupancy = 720000; // critical
  const critical = await step(session);
  assert.match(critical.additionalContexts[0].content[0].text, /band critical/);
  assert.match(critical.additionalContexts[0].content[0].text, /Do not restart the session to "save" context/);
});

test('a compaction is announced with what survived, what is at risk, and where the transcript is', async () => {
  const { ctx, state, fire, step } = makeCtx({ occupancy: 600000 });
  const session = sessionWith();
  apply(ctx, {});
  await step(session);

  state.occupancy = 41000;
  await fire('session/event', session, { type: 'compaction/summary', data: { shadowedTokenCount: 288000 } });

  const after = await step(session);
  const text = after.additionalContexts[0].content[0].text;
  assert.match(text, /^COMPACTED/);
  assert.match(text, /288,000 tokens/);
  assert.match(text, /Nothing was destroyed/);
  assert.match(text, /ps_search what=sessions/);

  const next = await step(session);
  assert.equal(next.additionalContexts.length, 1, 'the compaction notice is announced once, not every step');
});

test('an unreadable meter is reported, never guessed at, and still announces the compaction', async () => {
  const { ctx, state, fire, step } = makeCtx({ occupancy: 100000 });
  const session = sessionWith();
  apply(ctx, {});

  state.meterThrows = true;
  const first = await step(session);
  assert.match(first.additionalContexts[0].content[0].text, /cannot read its own context usage: the token meter threw/);
  assert.match(first.additionalContexts[0].content[0].text, /do not announce a limit/);

  await fire('session/event', session, { type: 'compaction/summary', data: { shadowedTokenCount: 5000 } });
  const after = await step(session);
  const text = after.additionalContexts[0].content[0].text;
  assert.match(text, /^COMPACTED/);
  assert.doesNotMatch(text, /The engine replaced/, 'no arithmetic when there is no reading to do it with');
});

test('a blocked downstream decision keeps its feedback and still gains the notice', async () => {
  const { ctx, handlers } = makeCtx({ occupancy: 100000 });
  const session = sessionWith();
  apply(ctx, {});
  const handler = (handlers.get('tools/post-execute') ?? [])[0];
  const result = await handler({ agent: { session } }, {}, async () => ({ kind: 'block', feedback: 'denied' }));
  assert.equal(result.kind, 'block');
  assert.equal(result.feedback, 'denied');
  assert.equal(result.additionalContexts.length, 1);
  assert.equal(result.additionalContexts[0].source.kind, 'context-awareness');
});

test('the window comes from the route, not from a hardcoded server default', async () => {
  const { ctx, step } = makeCtx({ occupancy: 400000, window: 792576 });
  const session = { requestHeader: () => ({ config: { contextWindow: 792576 } }) };
  apply(ctx, {});
  const first = await step(session);
  assert.match(first.additionalContexts[0].content[0].text, /400,000 of 792,576 tokens \(50%\)/);
  assert.match(first.additionalContexts[0].content[0].text, /compaction fires near 554,803/, 'the fire point follows the configured 0.7, per route');
});

test('context_status answers from the same reading, and counts compactions', async () => {
  const { ctx, registered, fire, step } = makeCtx({ occupancy: 630000 });
  const session = sessionWith();
  apply(ctx, {});
  await step(session);

  const tool = registered.find((definition) => definition.name === 'context_status');
  assert.ok(tool, 'the tool is registered');
  const fresh = await tool.execute({}, { agent: { session } });
  assert.equal(fresh.available, true);
  assert.equal(fresh.tokens, 630000);
  assert.equal(fresh.percent, 63);
  assert.equal(fresh.band, 'tightening');
  assert.equal(fresh.compactions, 0);
  assert.match(fresh.message, /No compaction has happened in this session\./);

  await fire('session/event', session, { type: 'compaction/prune', data: { shadowedTokenCount: 1000 } });
  const after = await tool.execute({}, { agent: { session } });
  assert.equal(after.compactions, 1);
  assert.match(after.message, /1 compaction\(s\) in this session/);
});

test('context_status refuses to invent a number when the meter is gone', async () => {
  const registered = [];
  const lonely = {
    on: () => () => {},
    get: () => undefined, // no tokenMeter in this profile
    inject: (_deps, body) => body(lonely),
    effect: (fn) => fn(),
    tools: { register: (definition) => { registered.push(definition); return () => {}; } },
  };
  apply(lonely, {});
  const tool = registered.find((definition) => definition.name === 'context_status');
  assert.ok(tool, 'the tool is still registered — an unreadable meter is not a reason to vanish');
  const answer = await tool.execute({}, { agent: { session: sessionWith() } });
  assert.equal(answer.available, false);
  assert.match(answer.message, /token meter/);
  assert.match(answer.message, /Do not guess at a number/);
});

test('disabled means silent: no listeners, no tool', async () => {
  const { ctx, handlers, registered } = makeCtx();
  apply(ctx, { enabled: false });
  assert.equal(handlers.size, 0);
  assert.equal(registered.length, 0);
});

test('a session with no agent is ignored rather than thrown', async () => {
  const { ctx, handlers } = makeCtx();
  apply(ctx, {});
  const handler = (handlers.get('tools/post-execute') ?? [])[0];
  const result = await handler({}, {}, NEXT);
  assert.deepEqual(result, { kind: 'enter', additionalContexts: [] });
});
