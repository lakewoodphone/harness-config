/**
 * The spend guard's own checks, runnable with no engine and no side effects.
 *
 * Two kinds of claim are tested here, and they are different in strength:
 *
 *   THE POLICY — thresholds, boundaries, the unpriced bound, the dearest rate,
 *   fail-closed, the UTC roll, the concurrency cap. These are exact assertions
 *   on pure functions, and they are the whole arithmetic the guard enforces.
 *
 *   THE WIRING — that `agent/pre-step` is handed a `{kind:'reject'}` at the
 *   ceiling and a notice below it, and that `session/event` feeds the counter.
 *   These run against a fake Cordis context that records listeners, because
 *   what is being tested is which listener returns what, not that the engine
 *   calls it. That the ENGINE turns a reject into a durably `blocked` turn with
 *   nothing billed is proved by measurement, not here: it is a property of
 *   `dsh-agent-loop/lib/index.js:937-947` (reject returns before `step/start`)
 *   and of the live demonstration recorded in docs/mesh/101-spend-guard-installed.md.
 *
 * Every check uses an isolated state file and an isolated sessions root: this
 * test CANNOT touch the owner's counters, and it does not read a real session
 * log.
 *
 * Usage: node test/guard.test.mjs
 */
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { PRICING, MICRO, indexRoutes, costOf, normalizeUsage } from '../src/cost-core.mjs';
import { readSessionLog, dshHome } from '../src/session-log.mjs';
import { createGuard, decide, resolveLimits, dearestRates, utcDayStart, DEFAULTS } from '../src/guard.mjs';

let checks = 0;
let failures = 0;
const check = (name, condition, detail) => {
  checks += 1;
  if (condition) console.log(`  ok    ${name}`);
  else {
    failures += 1;
    console.log(`  FAIL  ${name}${detail === undefined ? '' : ` — ${detail}`}`);
  }
};

/** Micro-USD limits for the installed defaults and for one scratch policy. */
const L = (warn, fanout, ceiling) => ({ warnMicro: Math.round(warn * MICRO), fanoutMicro: Math.round(fanout * MICRO), ceilingMicro: Math.round(ceiling * MICRO) });
const REAL = L(DEFAULTS.warnUsd, DEFAULTS.fanoutUsd, DEFAULTS.ceilingUsd);
const SCRATCH = L(0.01, 0.02, 0.03);

/** A fake Cordis context that records listeners and effects like the real one. */
function fakeCtx(services = {}) {
  const listeners = { 'session/event': [], 'agent/pre-step': [] };
  const effects = [];
  return {
    logger: { lines: [], info(line) { this.lines.push(`info ${line}`); }, warn(line) { this.lines.push(`warn ${line}`); } },
    get(name) { return services[name]; },
    on(name, handler) { (listeners[name] = listeners[name] || []).push(handler); },
    effect(fn) { effects.push(fn); },
    listeners,
    effects,
  };
}

/** Fire one session/event and return nothing: the listener has no return value. */
function emitUsage(ctx, usage, { model = 'deepseek-flash', provider = 'deepseek-official', at = Date.now() } = {}) {
  const event = { type: 'assistant/message', seq: 1, time: at, data: { usage, message: { source: { provider, model } } } };
  for (const listener of ctx.listeners['session/event']) listener({ id: 'fake-session' }, event);
  return event;
}

/** Fire one agent/pre-step and return the decision. */
async function firePreStep(ctx, { agent = { id: 'fake-agent' }, step = 1, turn = 1, messages = [] } = {}) {
  const payload = { agent, messages, turn, step, signal: { aborted: false } };
  let handed = 0;
  const next = async () => {
    handed += 1;
    return { kind: 'enter', messages: payload.messages };
  };
  for (const listener of ctx.listeners['agent/pre-step']) {
    const decision = await listener(payload, next);
    if (decision !== undefined) return { decision, handed };
  }
  return { decision: await next(), handed };
}

/**
 * A usage sample worth roughly `usd` on the flash card AT THE OFF-PEAK RATE.
 *
 * The rate this sample is built from is the off-peak one, so anything pricing it must use an
 * off-peak instant or it is charged double — see PINNED_AT in the wiring section.
 */
function usageForUsd(usd) {
  const cacheReadTokens = Math.round((usd * 1e6) / PRICING.routes[0].rates.hitPer1M);
  return { inputTokens: 0, cacheReadTokens, outputTokens: 0, totalTokens: cacheReadTokens };
}

/** Wait until the guard's async start (restore + seed) has finished. */
async function settle(guard) {
  for (let i = 0; i < 200; i += 1) {
    if (guard.guardState().started) return true;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  return false;
}

const scratch = mkdtempSync(join(tmpdir(), 'spend-guard-test-'));
const emptySessions = mkdtempSync(join(tmpdir(), 'spend-guard-sessions-'));

try {
  console.log('spend-guard: the policy');
  check('the defaults are the protective ones $35 / $80 / $150 and 12 agents', DEFAULTS.warnUsd === 35 && DEFAULTS.fanoutUsd === 80 && DEFAULTS.ceilingUsd === 150 && DEFAULTS.concurrencyCap === 12, JSON.stringify(DEFAULTS));
  check('at zero spend the verdict is ok', decide(0, REAL).verdict === 'ok');
  check('one micro below warn is still ok', decide(REAL.warnMicro - 1, REAL).verdict === 'ok');
  check('warn is inclusive at the threshold', decide(REAL.warnMicro, REAL).verdict === 'warn');
  check('one micro below fan-out is still warn', decide(REAL.fanoutMicro - 1, REAL).verdict === 'warn');
  check('fan-out is inclusive at the threshold', decide(REAL.fanoutMicro, REAL).verdict === 'fanout');
  check('one micro below the ceiling is still fan-out', decide(REAL.ceilingMicro - 1, REAL).verdict === 'fanout');
  check('the ceiling is inclusive and rejects', decide(REAL.ceilingMicro, REAL).verdict === 'reject');
  check('the ceiling rejects with the daily-ceiling reason', decide(REAL.ceilingMicro, REAL).rejectReason === 'daily ceiling');
  check('a spend past the ceiling still rejects', decide(REAL.ceilingMicro * 100, REAL).verdict === 'reject');
  check('the three thresholds are strictly ordered', DEFAULTS.warnUsd < DEFAULTS.fanoutUsd && DEFAULTS.fanoutUsd < DEFAULTS.ceilingUsd);
  check('the scratch policy used below is also usable', decide(SCRATCH.warnMicro, SCRATCH).verdict === 'warn');

  console.log('spend-guard: configuration resolution fails closed');
  check('a non-number ceiling falls back to the default, never to zero', resolveLimits({ ceilingUsd: 'lots' }).ceilingUsd === DEFAULTS.ceilingUsd);
  check('a negative warn falls back to the default', resolveLimits({ warnUsd: -1 }).warnUsd === DEFAULTS.warnUsd);
  check('fail-closed is the default', resolveLimits({}).onInternalError === 'closed');
  check("fail-open must be asked for by name", resolveLimits({ onInternalError: 'open' }).onInternalError === 'open');
  check('any other onInternalError value is closed', resolveLimits({ onInternalError: 'yes' }).onInternalError === 'closed');
  check('an unknown key is reported, not ignored', resolveLimits({ ceilingUsd: 150, wibble: 1 }).unknownKeys.join(',') === 'wibble');
  check('the concurrency cap has a default of 12', resolveLimits({}).concurrencyCap === 12);
  check('a zero concurrency cap disables the cap rather than refusing every step', resolveLimits({ concurrencyCap: 0 }).concurrencyCap === 0);

  console.log('spend-guard: the day and the unpriced bound');
  check('the UTC day rolls at 00:00Z', utcDayStart(Date.UTC(2026, 8, 17, 23, 59)) === Date.UTC(2026, 8, 17) && utcDayStart(Date.UTC(2026, 8, 18, 0, 1)) === Date.UTC(2026, 8, 18));
  const dear = dearestRates();
  check('the dearest card rate is not zero, so an unpriced route can be bounded', dear.missPer1M > 0 && dear.hitPer1M > 0 && dear.outputPer1M > 0, JSON.stringify(dear));
  check('the dearest rate is deepseek-v4-pro at its peak multiplier', dear.model === 'deepseek-v4-pro' && dear.multiplier === 2, `${dear.provider}/${dear.model} x${dear.multiplier}`);
  check('the dearest output rate is exactly 2x the card rate', dear.outputPer1M === PRICING.routes[1].rates.outputPer1M * 2, `${dear.outputPer1M} vs ${PRICING.routes[1].rates.outputPer1M * 2}`);

  console.log('spend-guard: the mounted guard, against an isolated state file');
  const probe = createGuard({
    core: { PRICING, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome },
    readdir: async () => [],
    stat: async () => ({ mtimeMs: 0 }),
  });
  check('an unpriced route is charged at the dearest rate, not zero', probe.priceSample({ inputTokens: 1000, cacheReadTokens: 0, outputTokens: 0, totalTokens: 1000 }, { provider: 'deepseek-official', model: 'no-such-model' }, Date.now()).micro > 0);
  check('an unpriced route is flagged as unpriced', probe.priceSample({ inputTokens: 1000, cacheReadTokens: 0, outputTokens: 0, totalTokens: 1000 }, { provider: 'deepseek-official', model: 'no-such-model' }, Date.now()).priced === false);
  check('a carded route is priced exactly, with no bound applied', probe.priceSample({ inputTokens: 1000, cacheReadTokens: 0, outputTokens: 0, totalTokens: 1000 }, { provider: 'deepseek-official', model: 'deepseek-flash' }, Date.UTC(2026, 8, 17, 12, 0)).micro === Math.round(1000 * 0.15));
  check('a malformed usage sample is refused, not priced', probe.priceSample({ inputTokens: 'many', outputTokens: 1 }, { provider: 'deepseek-official', model: 'deepseek-flash' }, Date.now()).micro === 0);
  check('a missing price core refuses to construct', (() => { try { createGuard({}); return false; } catch { return true; } })());

  // ── the wiring: warn -> fan-out -> reject, then the concurrency cap ───────
  const running = [];
  const services = { agents: { list: () => running } };
  const ctx = fakeCtx(services);
  // A PINNED, OFF-PEAK CLOCK: this section is otherwise TIME-OF-DAY DEPENDENT.
  //
  // The guard prices a sample at the EVENT's own instant, and the flash card doubles every rate
  // for 01:00-04:00 and 06:00-10:00 UTC, Monday to Friday. `usageForUsd` builds its sample from
  // the OFF-PEAK rate, so during UTC peak every sample below is charged twice:
  // `usageForUsd(0.015)` becomes $0.0300 and lands exactly on this section's $0.03 ceiling, so
  // the WARN assertions see `{kind:'reject'}`. Measured 2026-09-17: the same suite was green at
  // 14:47Z (off-peak — that is the run H461 recorded as "verify.mjs green") and red at 01:56Z
  // (peak), with no change to src/guard.mjs between them. `deps.now` is a documented override
  // (src/guard.mjs:227 `const clock = deps.now || (() => Date.now())`), so the clock is pinned
  // rather than the assertions weakened or the suite left to pass only in the afternoon.
  // 2026-09-17T12:00Z is off-peak on the card in pricing.json (Thursday, outside both windows).
  const PINNED_AT = Date.UTC(2026, 8, 17, 12, 0);
  const guard = createGuard({
    core: { PRICING, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome },
    readdir: async () => [],
    stat: async () => ({ mtimeMs: 0 }),
    now: () => PINNED_AT,
  });
  guard.apply(ctx, {
    warnUsd: 0.01,
    fanoutUsd: 0.02,
    ceilingUsd: 0.03,
    concurrencyCap: 12,
    seedFromLogs: false,
    stateFile: join(scratch, 'day.json'),
    sessionsRoot: emptySessions,
  });
  check('the guard finished starting (restore + seed) in the test harness', await settle(guard));
  check('the guard registered one session/event listener', ctx.listeners['session/event'].length === 1);
  check('the guard registered one agent/pre-step listener', ctx.listeners['agent/pre-step'].length === 1);
  check('the guard registered its disposer as an effect', ctx.effects.length === 1);

  const at = PINNED_AT;
  running.push({ id: 'other-agent', status: 'idle' });
  let fired = await firePreStep(ctx);
  check('with no spend the step is admitted with no notice', fired.decision.kind === 'enter' && fired.decision.messages.length === 0, JSON.stringify(fired.decision.messages));

  emitUsage(ctx, usageForUsd(0.015), { at });
  check('a live usage sample moved the counter above the warn threshold', guard.guardState().micro > SCRATCH.warnMicro, `${guard.guardState().micro} <= ${SCRATCH.warnMicro}`);

  fired = await firePreStep(ctx);
  check('the WARN behaviour appends exactly one notice to the step', fired.decision.kind === 'enter' && fired.decision.messages.length === 1, JSON.stringify(fired.decision));
  check('the warn notice names the spend and the ceiling', /spend-guard:/.test(fired.decision.messages[0].content[0].text) && /warn threshold/.test(fired.decision.messages[0].content[0].text), fired.decision.messages[0].content[0].text);
  fired = await firePreStep(ctx);
  check('the notice is not repeated on every following step', fired.decision.messages.length === 0);

  emitUsage(ctx, usageForUsd(0.01), { at: at + 1 });
  check('spend is now past the fan-out threshold', guard.guardState().micro > SCRATCH.fanoutMicro, `${guard.guardState().micro} <= ${SCRATCH.fanoutMicro}`);
  fired = await firePreStep(ctx);
  check('the FAN-OUT behaviour admits the step with a notice', fired.decision.kind === 'enter' && fired.decision.messages.length === 1);
  check('the fan-out notice refuses new subagents and workflows', /no new subagents or workflows/.test(fired.decision.messages[0].content[0].text), fired.decision.messages[0].content[0].text);

  emitUsage(ctx, usageForUsd(0.01), { at: at + 2 });
  check('spend is now at or past the ceiling', guard.guardState().micro >= SCRATCH.ceilingMicro, `${guard.guardState().micro} vs ${SCRATCH.ceilingMicro}`);
  fired = await firePreStep(ctx);
  check('the CEILING behaviour rejects the step', fired.decision.kind === 'reject', JSON.stringify(fired.decision));
  check('a rejected step never calls next(), so nothing downstream can bill it', fired.handed === 0, `next() was called ${fired.handed} time(s)`);
  check('the reject reason is the daily ceiling', guard.guardState().lastVerdict === 'reject');
  check('the guard said why, in its own log', ctx.logger.lines.some((line) => /daily ceiling reached/.test(line) && /refusing step/.test(line)), ctx.logger.lines.join(' | '));

  console.log('spend-guard: the concurrency cap, on its own policy');
  const running2 = [];
  const setAgents = (count) => {
    running2.length = 0;
    for (let i = 0; i < count; i += 1) running2.push({ id: `agent-${i}`, status: 'running' });
  };
  const ctx2 = fakeCtx({ agents: { list: () => running2 } });
  const guard2 = createGuard({ core: { PRICING, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome } });
  guard2.apply(ctx2, { ceilingUsd: 150, warnUsd: 35, fanoutUsd: 80, concurrencyCap: 3, seedFromLogs: false, stateFile: join(scratch, 'day2.json'), sessionsRoot: emptySessions });
  await settle(guard2);
  setAgents(3);
  fired = await firePreStep(ctx2, { agent: { id: 'new-agent' } });
  check('a NEW agent is refused at the concurrency cap with no money spent', fired.decision.kind === 'reject' && guard2.guardState().micro === 0, JSON.stringify(fired.decision));
  check('the concurrency reject never calls next()', fired.handed === 0);
  check('the guard names the concurrency cap in its log', ctx2.logger.lines.some((line) => /concurrency cap reached/.test(line)), ctx2.logger.lines.join(' | '));
  fired = await firePreStep(ctx2, { agent: { id: 'agent-1' } });
  check('an agent already generating is never refused by the concurrency cap', fired.decision.kind === 'enter', JSON.stringify(fired.decision));
  setAgents(2);
  fired = await firePreStep(ctx2, { agent: { id: 'new-agent-2' } });
  check('within one of the cap the step is admitted with a warning notice', fired.decision.kind === 'enter' && fired.decision.messages.length === 1 && /cap is 3/.test(fired.decision.messages[0].content[0].text), JSON.stringify(fired.decision.messages));
  setAgents(1);
  fired = await firePreStep(ctx2, { agent: { id: 'new-agent-3' } });
  check('below the cap the step is admitted with no notice at all', fired.decision.kind === 'enter' && fired.decision.messages.length === 0, JSON.stringify(fired.decision.messages));
  setAgents(2);
  fired = await firePreStep(ctx2, { agent: { id: 'another-new-agent' } });
  check('crossing back up into the warning re-arms the notice', fired.decision.messages.length === 1, JSON.stringify(fired.decision.messages));
  fired = await firePreStep(ctx2, { agent: { id: 'agent-1' } });
  check('an agent that IS one of the running ones is not warned about its own load', fired.decision.messages.length === 0);

  console.log('spend-guard: fail closed');
  const ctx3 = fakeCtx({ agents: { list: () => { throw new Error('the agents service is broken'); } } });
  const guard3 = createGuard({ core: { PRICING, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome } });
  guard3.apply(ctx3, { seedFromLogs: false, stateFile: join(scratch, 'day3.json'), sessionsRoot: emptySessions });
  await settle(guard3);
  fired = await firePreStep(ctx3);
  check('an internal error REJECTS the step when onInternalError is closed (the default)', fired.decision.kind === 'reject', JSON.stringify(fired.decision));
  check('the internal error never calls next()', fired.handed === 0);
  check('the failure is said out loud, not swallowed', ctx3.logger.lines.some((line) => /INTERNAL ERROR/.test(line)), ctx3.logger.lines.join(' | '));

  const ctx4 = fakeCtx({ agents: { list: () => { throw new Error('the agents service is broken'); } } });
  const guard4 = createGuard({ core: { PRICING, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome } });
  guard4.apply(ctx4, { seedFromLogs: false, onInternalError: 'open', stateFile: join(scratch, 'day4.json'), sessionsRoot: emptySessions });
  await settle(guard4);
  fired = await firePreStep(ctx4);
  check('fail-open allows the step only when it was asked for by name', fired.decision.kind === 'enter' && fired.handed === 1, JSON.stringify(fired.decision));

  console.log('spend-guard: the seed is a scan, and the counter is the live stream');
  const seedCalls = [];
  const ctx5 = fakeCtx({ agents: { list: () => [] } });
  const guard5 = createGuard({
    core: { PRICING, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome },
    readdir: async (path) =>
      path.endsWith('sessions')
        ? [{ name: '--C-Users-ezabz-code--', isDirectory: () => true }]
        : [{ name: 'session-test-1', isDirectory: () => true }],
    stat: async () => ({ mtimeMs: Date.now() }),
    readSessionLog: (file) => {
      seedCalls.push(file);
      return [{ type: 'assistant/message', time: Date.now(), data: { usage: { inputTokens: 0, cacheReadTokens: 100000, outputTokens: 0, totalTokens: 100000 }, message: { source: { provider: 'deepseek-official', model: 'deepseek-flash' } } } }];
    },
  });
  guard5.apply(ctx5, { seedFromLogs: true, stateFile: join(scratch, 'day5.json'), sessionsRoot: join(scratch, 'sessions') });
  await settle(guard5);
  const seeded = guard5.guardState();
  check('the seed read the durable log exactly once', seedCalls.length === 1, `${seedCalls.length} read(s)`);
  check('the seed priced the request it found', seeded.micro > 0 && seeded.seedRequests === 1, JSON.stringify({ micro: seeded.micro, seedRequests: seeded.seedRequests }));
  check('the seed recorded the watermark from the event it priced', seeded.watermarkMs > 0);
  check('the seed leaving the day non-zero does NOT put the guard past a real ceiling', seeded.micro < REAL.ceilingMicro);

  console.log('spend-guard: the state file survives a restart without double counting');
  const dayPath = join(scratch, 'day6.json');
  const ctx6 = fakeCtx({ agents: { list: () => [] } });
  const guard6 = createGuard({ core: { PRICING, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome }, readdir: async () => [], stat: async () => ({ mtimeMs: 0 }) });
  guard6.apply(ctx6, { seedFromLogs: false, stateFile: dayPath, sessionsRoot: emptySessions });
  await settle(guard6);
  emitUsage(ctx6, usageForUsd(0.004), { at: Date.now() });
  await new Promise((resolve) => setTimeout(resolve, 60));
  const before = guard6.guardState().micro;
  const ctx7 = fakeCtx({ agents: { list: () => [] } });
  const guard7 = createGuard({ core: { PRICING, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome }, readdir: async () => [], stat: async () => ({ mtimeMs: 0 }) });
  guard7.apply(ctx7, { seedFromLogs: false, stateFile: dayPath, sessionsRoot: emptySessions });
  await settle(guard7);
  check('a restart resumes the day from the state file', guard7.guardState().micro === before, `${guard7.guardState().micro} vs ${before}`);
  check('the resumed watermark stops the same request being counted twice', guard7.guardState().watermarkMs === guard6.guardState().watermarkMs);
  emitUsage(ctx7, usageForUsd(0.001), { at: guard7.guardState().watermarkMs - 1000 });
  check('an event at or before the watermark is ignored', guard7.guardState().micro === before, `${guard7.guardState().micro} vs ${before}`);

  console.log('spend-guard: no price card means no enforcement');
  const noCard = createGuard({ core: { PRICING: { routes: [] }, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome } });
  const ctx8 = fakeCtx({});
  check('a card with no routes refuses to mount rather than pricing everything at zero', (() => { try { noCard.apply(ctx8, {}); return false; } catch { return true; } })());
} finally {
  rmSync(scratch, { recursive: true, force: true });
  rmSync(emptySessions, { recursive: true, force: true });
}

console.log('');
console.log(failures === 0 ? `guard: ${checks}/${checks} checks passed` : `guard: ${checks - failures}/${checks} checks passed — ${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
