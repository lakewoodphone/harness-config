/**
 * dsh-plugin-context-awareness — the agent can see its own context.
 *
 * WHY THIS EXISTS
 * The engine has a token meter, three context projections and a `/cost` command, and the
 * AGENT could read none of them. So an agent's belief about its own context was a GUESS,
 * and the guess has a measurable direction: it is pessimistic, it fires early, and it is
 * acted on. Measured in this estate's own transcripts, sessions stop coherent work, announce
 * a limit, and propose a fresh window at a fraction of the real occupancy — because the
 * only context fact the agent owned was the instruction saying *"it does not tell you when
 * either happened"* (`presets/zabz` rule 8, now corrected). An unobservable lossy event plus
 * an instruction that says it is silent is a recipe for pre-emptive panic, and pre-emptive
 * panic is a defect with a cost: work is dropped mid-piece, and the restart the panic asks
 * for does not save the context it fears (a new session pays a fresh prefix).
 *
 * The evidence that this is worth fixing is not only ours:
 *   * Claude Code tells the model plainly — "This session is being continued from a previous
 *     conversation that ran out of context" — and injects a standing reminder that older
 *     messages will be summarised automatically. It conceals the mechanic from the USER, not
 *     from the model.
 *   * arXiv 2610.20116 (2026-10) measured the alternative: summaries that do not declare what
 *     they removed produce CONFIDENT errors, because the agent cannot tell which of its
 *     beliefs rest on material it no longer has. Declaring the removal lifted planted-fact
 *     recall by 22-42 points on lightweight models.
 *   * arXiv 2606.22528 measured the cost on rules: in-context constraints were honoured 100%
 *     of the time, 70% after a compaction dropped them.
 *
 * WHAT IT DOES — three surfaces, no new service
 *   1. `context_status` tool: the exact number on demand, in the engine's own units.
 *   2. A `CONTEXT ...` notice when the band changes, once per band, plus one orientation on
 *      the first measurable step of a session.
 *   3. A `COMPACTED ...` notice after the engine records `compaction/summary` or
 *      `compaction/prune`, stating what survives, what can be lost, what to do, and — the
 *      part that ends the panic — that nothing was destroyed and where the transcript is.
 *
 * WHERE THE NUMBER COMES FROM
 * `ctx.tokenMeter.measure(session)` — the engine's own pricing of its own request image, the
 * same number the browser meter shows. There is deliberately NO second fold here: a plugin
 * that re-derives token pressure is the drift defect this estate has paid for twice. If the
 * meter is absent or throws, the notice SAYS SO rather than inventing a number.
 *
 * WHY THE HOST PLANE
 * Blindness is a property of the engine, not of one persona: a subagent on the mesh and a
 * session on any other preset have the same missing sense. One host row sees every session in
 * the process, state is keyed by Session (so two windows never share a band), and it publishes
 * no service — nothing to collide with, no isolate realm, nothing a preset can starve.
 *
 * HOW IT FAILS
 * Quietly, and only in the direction of silence. Every listener is wrapped: a defect here can
 * lose a notice, and must never lose a tool result or fail a boot. The tool registration runs
 * in an `ctx.inject(['tools'])` child fibre, so an absent registry waits rather than breaking
 * the profile.
 */

import { randomUUID } from 'node:crypto';

export const name = 'context-awareness';

/** Band upper bounds as fractions of the window. Index i is `BAND_NAMES[i]`. */
const DEFAULT_BANDS = [0.35, 0.55, 0.70];
const BAND_NAMES = ['comfortable', 'working', 'tightening', 'critical'];
/** Fallback window when no route has reported one. The engine's own default is 1e6. */
const DEFAULT_WINDOW = 1_000_000;
/** The zabz preset compacts at thresholdRatio 0.7; stated so the agent can do the arithmetic. */
const DEFAULT_THRESHOLD_RATIO = 0.7;

// ── pure helpers (exported for test/logic.test.mjs) ─────────────────────────────

/** Validate and normalise band bounds: strictly increasing fractions inside (0, 1). */
export function normalizeBands(value) {
  const bands = value === undefined ? DEFAULT_BANDS.slice() : value;
  if (!Array.isArray(bands) || bands.length === 0) {
    throw new Error('context-awareness: `bands` must be a non-empty array of fractions');
  }
  const out = [];
  for (const raw of bands) {
    const n = Number(raw);
    if (!Number.isFinite(n) || n <= 0 || n >= 1) {
      throw new Error(`context-awareness: invalid band bound ${JSON.stringify(raw)} — every bound must be a fraction strictly between 0 and 1`);
    }
    if (out.length > 0 && n <= out[out.length - 1]) {
      throw new Error(`context-awareness: band bounds must be strictly increasing (got ${out.join(', ')} then ${n})`);
    }
    out.push(n);
  }
  return out;
}

/** The band index for a ratio; the last index when the ratio exceeds every bound. */
export function bandIndexFor(ratio, bands) {
  if (!Number.isFinite(ratio) || ratio < 0) return 0;
  for (let i = 0; i < bands.length; i += 1) if (ratio < bands[i]) return i;
  return bands.length;
}

export function bandNameFor(index) {
  return BAND_NAMES[Math.min(index, BAND_NAMES.length - 1)];
}

/** Group with commas: 1234567 -> "1,234,567". Locale-free so every host renders it alike. */
export function formatTokens(value) {
  const n = Math.round(Number(value) || 0);
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/** Whole-percent occupancy, clamped to 0..100 for display (never the raw ratio). */
export function percentOf(tokens, window) {
  if (!Number.isFinite(tokens) || !Number.isFinite(window) || window <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((tokens / window) * 100)));
}

/** One marked, frozen message the loop can carry. Mirrors `createUserMessage` from dsh-llm. */
export function noticeMessage(text, summary) {
  return deepFreeze({
    role: 'user',
    id: randomUUID(),
    content: [{ type: 'text', text }],
    source: { kind: 'context-awareness', form: 'notice', summary },
  });
}

export function deepFreeze(value) {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const key of Object.keys(value)) deepFreeze(value[key]);
  }
  return value;
}

/** The reading, as the agent sees it: occupancy, band, and the compaction point. */
export function describeReading({ tokens, window, band, thresholdRatio, exact, basis }) {
  const pct = percentOf(tokens, window);
  const fireAt = Math.round((Number(thresholdRatio) || DEFAULT_THRESHOLD_RATIO) * window);
  return {
    tokens: Math.round(tokens),
    window: Math.round(window),
    percent: pct,
    band,
    fireAt,
    exact: exact === true,
    basis: basis ?? 'unknown',
  };
}

// ── texts ──────────────────────────────────────────────────────────────────────
// Written to be read ONCE by a model that is mid-task. Every sentence either states a
// measured number or tells it what to do; none of them praise, hedge or narrate.

export function orientationText(reading) {
  return [
    `CONTEXT — this session can see its own context usage now.`,
    `${formatTokens(reading.tokens)} of ${formatTokens(reading.window)} tokens (${reading.percent}%) · band ${reading.band} · compaction fires near ${formatTokens(reading.fireAt)}`,
    '`context_status` returns the live numbers at any time. Call it instead of guessing.',
    '',
    'Because this replaces a guess with a reading:',
    '- Never announce that your context is spent, and never stop, restart or propose a new window because you fear the limit. If you need to know, read it.',
    '- Compaction is survivable by design. The checkpoint is a summary, the repository and the journal are untouched, and the full transcript is searchable (`ps_search what=sessions`, `scripts/sessions.mjs`).',
    '- Anything expensive to lose — a decision, a path, a number, a rule — goes into a file or the journal when you get it, not at the end.',
    reading.exact ? '' : '(The number above is estimated from the request surface; the next provider usage sample confirms it.)',
  ].filter((line) => line !== '').join('\n');
}

export function bandText(reading) {
  const head = `CONTEXT ${formatTokens(reading.tokens)} of ${formatTokens(reading.window)} (${reading.percent}%) — band ${reading.band}; compaction fires near ${formatTokens(reading.fireAt)}.`;
  if (reading.band === 'tightening') {
    return `${head}\nRoom remains. Finish the unit you are in, and write down anything expensive to lose now rather than later.`;
  }
  if (reading.band === 'critical') {
    return `${head}\nFinish a coherent piece and write the handoff before starting anything new. Do not restart the session to "save" context — a new session re-sends a fresh prefix and saves nothing you can measure.`;
  }
  return `${head}\nYou have room; keep working.`;
}

export function compactedText({ shadowedTokens, reading }) {
  const lines = [
    'COMPACTED — the span before this point is now a checkpoint: a summary, not a transcript.',
  ];
  if (Number.isFinite(shadowedTokens) && shadowedTokens > 0) {
    lines.push(`The engine replaced about ${formatTokens(shadowedTokens)} tokens of earlier history; context is now ${formatTokens(reading.tokens)} of ${formatTokens(reading.window)} (${reading.percent}%).`);
  }
  lines.push(
    'Kept: decisions, paths, and the numbers the summary chose to keep. At risk: exact strings, dropped detail, and the context that told look-alike values apart.',
    'So: re-read a file before editing it, and treat anything you know only from the checkpoint as unverified rather than proven.',
    'Nothing was destroyed — the full pre-compaction transcript is on disk and searchable (`ps_search what=sessions`), and the repository, journal and State files were never touched. Do not re-do work the checkpoint records, and do not restart the session.',
  );
  return lines.join('\n');
}

export function statusText({ reading, compactions, sinceCompactionMs }) {
  const lines = [
    `CONTEXT ${formatTokens(reading.tokens)} of ${formatTokens(reading.window)} tokens (${reading.percent}%), band ${reading.band}.`,
    `Compaction fires near ${formatTokens(reading.fireAt)} (${Math.round((Number(reading.thresholdRatio) || DEFAULT_THRESHOLD_RATIO) * 100)}% of the window); below that you have room and there is no reason to stop.`,
    `Reading basis: ${reading.exact ? 'provider usage sample (exact)' : `estimated from the request surface (${reading.basis})`}.`,
  ];
  if (compactions === 0) lines.push('No compaction has happened in this session.');
  else {
    lines.push(`${compactions} compaction(s) in this session; the last was ${Math.round((sinceCompactionMs ?? 0) / 1000)}s ago. The transcript before it is still on disk and searchable.`);
  }
  if (reading.band === 'critical') lines.push('At this band: write the handoff and close a coherent piece; do not start new work and do not restart to "save" context.');
  else if (reading.band === 'tightening') lines.push('At this band: keep working, and write down anything expensive to lose.');
  else lines.push('At this band: keep working. Do not announce a limit you have not read.');
  return lines.join('\n');
}

const TOOL_DESCRIPTION = 'Read this session\'s own context occupancy: tokens in use, the window, the percentage, the band, '
  + 'and when compaction will fire. Call it instead of guessing — especially before saying anything about your context, '
  + 'and before deciding to stop or restart for context reasons. Compaction in this harness is survivable: it replaces '
  + 'earlier history with a summary, leaves the repository and journal untouched, and keeps the full transcript on disk '
  + 'and searchable.';

const TOOL_OUTPUT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    message: { type: 'string' },
    tokens: { type: 'integer' },
    window: { type: 'integer' },
    percent: { type: 'integer' },
    band: { type: 'string' },
    fireAt: { type: 'integer' },
    exact: { type: 'boolean' },
    compactions: { type: 'integer' },
    available: { type: 'boolean' },
  },
  required: ['message', 'available'],
};

// ── plugin ─────────────────────────────────────────────────────────────────────

/**
 * Install the awareness surface.
 * @param {object} ctx - plugin context.
 * @param {object} [config] - optional overrides; every key has a working default.
 */
export function apply(ctx, config = {}) {
  const settings = config ?? {};
  if (settings.enabled === false) return;

  const bands = normalizeBands(settings.bands);
  const thresholdRatio = Number(settings.thresholdRatio) > 0 ? Number(settings.thresholdRatio) : DEFAULT_THRESHOLD_RATIO;
  const toolName = typeof settings.toolName === 'string' && settings.toolName.length > 0 ? settings.toolName : 'context_status';
  const speakOnFirstStep = settings.speakOnFirstStep !== false;
  const configuredWindow = Number(settings.contextWindow) > 0 ? Number(settings.contextWindow) : undefined;

  /** Per-session bookkeeping; never shared between windows. */
  const sessions = new WeakMap();
  let warned = false;

  const stateFor = (session) => {
    let state = sessions.get(session);
    if (state === undefined) {
      state = {
        window: undefined,
        band: undefined,
        announced: false,
        compactions: 0,
        lastCompactionAt: undefined,
        pendingCompaction: undefined,
        lastReading: undefined,
      };
      sessions.set(session, state);
    }
    return state;
  };

  /** Never let a defect here reach the loop: report once, stay silent after. */
  const quiet = (where, error) => {
    if (warned) return;
    warned = true;
    try {
      console.warn(`context-awareness: ${where} failed and the notice was skipped — ${error?.message ?? error}`);
    } catch { /* a console that cannot write must not throw either */ }
  };

  const windowFor = (session, state) => {
    if (configuredWindow !== undefined) return configuredWindow;
    if (state.window !== undefined) return state.window;
    try {
      const header = session?.requestHeader?.();
      const fromHeader = Number(header?.config?.contextWindow);
      if (Number.isFinite(fromHeader) && fromHeader > 0) return fromHeader;
    } catch { /* fall through to the engine default */ }
    return DEFAULT_WINDOW;
  };

  const readOccupancy = (session) => {
    const meter = ctx.get?.('tokenMeter');
    if (meter === undefined || typeof meter.measure !== 'function') {
      return { error: 'the token meter (`tokenMeter`) is not mounted, so this session cannot see its own occupancy' };
    }
    // A meter that THROWS is a reading we do not have — not a reason to go silent. Silence is
    // the defect this plugin exists to remove, so a failure is reported to the agent as one.
    let measured;
    try {
      measured = meter.measure(session);
    } catch (error) {
      return { error: `the token meter threw while measuring this session (${error?.message ?? error})` };
    }
    const tokens = Number(measured?.totalTokens);
    if (!Number.isFinite(tokens)) return { error: 'the token meter returned no totalTokens for this session' };
    const basis = String(measured?.baseline?.kind ?? 'unknown');
    return { tokens, exact: basis === 'usage', basis };
  };

  const readingFor = (session, state) => {
    const occupancy = readOccupancy(session);
    if (occupancy.error !== undefined) return occupancy;
    const window = windowFor(session, state);
    const band = bandNameFor(bandIndexFor(occupancy.tokens / window, bands));
    const reading = { ...describeReading({ ...occupancy, window, band, thresholdRatio }), thresholdRatio };
    state.lastReading = reading;
    return reading;
  };

  const ownership = '`ps_search what=sessions` or `scripts/sessions.mjs show <id>`';

  // 1. Learn the window and notice compactions, from the durable event stream.
  ctx.on('session/event', (session, event) => {
    try {
      const state = stateFor(session);
      const type = event?.type;
      if (type === 'request/context') {
        const reported = Number(event?.data?.contextWindow);
        if (Number.isFinite(reported) && reported > 0) state.window = reported;
        return;
      }
      if (type === 'compaction/summary' || type === 'compaction/prune') {
        state.compactions += 1;
        state.lastCompactionAt = Date.now();
        state.pendingCompaction = {
          shadowedTokens: Number(event?.data?.shadowedTokenCount) || 0,
          kind: type,
        };
        // A compaction resets occupancy, so the next band change is worth speaking about again.
        state.band = undefined;
      }
    } catch (error) {
      quiet('session/event', error);
    }
  });

  // 2. Speak at a step boundary — after a tool result, where the model is about to think.
  ctx.on('tools/post-execute', async (exec, _result, next) => {
    const downstream = await next();
    let notice;
    try {
      notice = composeNotice(exec);
    } catch (error) {
      quiet('post-execute', error);
      return downstream;
    }
    if (notice === undefined) return downstream;
    const merged = [notice, ...(downstream?.additionalContexts ?? [])];
    if (downstream?.kind === 'block') {
      return { kind: 'block', feedback: downstream.feedback, additionalContexts: merged };
    }
    return { ...downstream, additionalContexts: merged };
  });

  function composeNotice(exec) {
    const session = exec?.agent?.session;
    if (session === undefined) return undefined;
    const state = stateFor(session);

    // A compaction outranks everything: it is the one event that changes what the agent knows.
    if (state.pendingCompaction !== undefined) {
      const pending = state.pendingCompaction;
      state.pendingCompaction = undefined;
      const reading = readingFor(session, state);
      if (reading.error !== undefined) {
        state.announced = true;
        return noticeMessage(
          compactedText({
            shadowedTokens: pending.shadowedTokens,
            reading: describeReading({ tokens: 0, window: windowFor(session, state), band: 'unknown', thresholdRatio, exact: false }),
          }).split('\n').filter((line) => !line.startsWith('The engine replaced')).join('\n'),
          'context compacted',
        );
      }
      state.band = bandNameFor(bandIndexFor(reading.tokens / reading.window, bands));
      state.announced = true;
      return noticeMessage(compactedText({ shadowedTokens: pending.shadowedTokens, reading }), 'context compacted');
    }

    const reading = readingFor(session, state);
    if (reading.error !== undefined) {
      if (!state.announced && speakOnFirstStep) {
        state.announced = true;
        return noticeMessage(
          `CONTEXT — this session cannot read its own context usage: ${reading.error}. `
          + 'So do not guess at it, do not announce a limit, and do not stop work for context reasons; '
          + `if you need to know, the transcript is searchable (${ownership}).`,
          'context unreadable',
        );
      }
      return undefined;
    }

    if (!state.announced) {
      if (!speakOnFirstStep) {
        state.announced = true;
        state.band = reading.band;
        return undefined;
      }
      state.announced = true;
      state.band = reading.band;
      return noticeMessage(orientationText(reading), `context ${reading.percent}% · ${reading.band}`);
    }

    if (state.band === undefined) {
      state.band = reading.band;
      return undefined;
    }

    const previous = BAND_NAMES.indexOf(state.band);
    const current = BAND_NAMES.indexOf(reading.band);
    if (current <= previous) {
      state.band = reading.band;
      return undefined;
    }
    state.band = reading.band;
    return noticeMessage(bandText(reading), `context ${reading.percent}% · ${reading.band}`);
  }

  // 3. The tool: the same reading, on demand, without waiting for a band change.
  if (ctx.inject === undefined) return;
  ctx.inject(['tools'], (toolCtx) => {
    try {
      toolCtx.effect(() => toolCtx.tools.register({
        name: toolName,
        description: TOOL_DESCRIPTION,
        parameters: { type: 'object', additionalProperties: false, properties: {} },
        output: {
          schema: TOOL_OUTPUT_SCHEMA,
          render(_args, value) {
            return [{ type: 'text', text: typeof value?.message === 'string' && value.message.length > 0 ? value.message : `${toolName}: no reading` }];
          },
        },
        async execute(_args, run) {
          const session = run?.agent?.session;
          if (session === undefined) {
            return { available: false, message: 'This call has no agent session, so there is no context to measure.' };
          }
          const state = stateFor(session);
          let reading;
          try {
            reading = readingFor(session, state);
          } catch (error) {
            return { available: false, message: `The context reading failed: ${error?.message ?? error}. Do not guess at a number; treat the window as unknown and keep working.` };
          }
          if (reading.error !== undefined) {
            return { available: false, message: `${reading.error}. Do not guess at a number. The transcript is searchable (${ownership}).` };
          }
          return {
            available: true,
            tokens: reading.tokens,
            window: reading.window,
            percent: reading.percent,
            band: reading.band,
            fireAt: reading.fireAt,
            exact: reading.exact,
            compactions: state.compactions,
            message: statusText({
              reading,
              compactions: state.compactions,
              sinceCompactionMs: state.lastCompactionAt === undefined ? undefined : Date.now() - state.lastCompactionAt,
            }),
          };
        },
      }));
    } catch (error) {
      quiet(`registering the ${toolName} tool`, error);
    }
  });
}
