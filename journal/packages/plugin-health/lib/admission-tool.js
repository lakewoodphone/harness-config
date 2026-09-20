/**
 * The `admission_governor` tool — the governor from the model side.
 *
 * The shell entry point is `bin/governor.mjs`; both it and this tool call the
 * same protocol module in `lib/governor.js`, so a hand-run `gov acquire` and an
 * agent's request cannot disagree about the rules.
 *
 * THE CONTRACT THE MODEL SEES, AND WHY IT IS SHAPED THIS WAY
 *   * `acquire` answers GRANTED or QUEUED-with-a-position. It never answers
 *     "no". An agent that is told to wait is given the arithmetic behind the
 *     budget so it can decide for itself whether to wait or to proceed anyway —
 *     that is the owner's rule ("a queue is acceptable; a smaller cap on what an
 *     agent can do is not") expressed in the interface.
 *   * A granted lease must be RENEWED while the work runs and RELEASED when it
 *     ends. The tool says so in the result text every time, because a lease that
 *     is never released shrinks the budget for everyone until it expires.
 *   * `status` is read-only and never reaps, so an agent checking the state of
 *     the world cannot disturb it.
 */

import os from 'node:os';
import path from 'node:path';

import { acquire, governorRoot, release, renew, status, TTL_MS_DEFAULT } from './governor.js';

const DESCRIPTION = 'Admission control for heavy work on this host. Before starting a fleet, a burst of shell '
  + 'commands, or any set of jobs that each cost a process, ask this governor for a slot: `acquire` returns GRANTED '
  + 'with a lease id, or QUEUED with your position — it never refuses. The budget is derived from measured memory '
  + 'headroom (one heavy tool call costs roughly a runner process plus a shell, ~160 MB) and is floored so it cannot '
  + 'fall to zero. While the granted work runs, call `renew` with the lease id before it expires (default 120 s); when '
  + 'the work finishes call `release`, or the slot stays taken until the lease expires. `status` shows the budget, '
  + 'every holder with its pid and age, the queue, and the arithmetic behind the number.';

const OUTPUT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    state: { type: 'string' },
    action: { type: 'string' },
    message: { type: 'string' },
    leaseId: { type: 'string' },
    slot: { type: 'integer' },
    expiresInMs: { type: 'integer' },
    position: { type: 'integer' },
    budget: { type: 'integer' },
    inUse: { type: 'integer' },
    free: { type: 'integer' },
    waiters: { type: 'integer' },
    headroomLow: { type: 'boolean' },
    derivation: { type: 'string' },
    holders: { type: 'array', items: { type: 'string' } },
    deadLeases: { type: 'array', items: { type: 'string' } },
  },
  required: ['state', 'action', 'message'],
};

/**
 * Register the tool into the calling context's tool layer.
 *
 * @param {object} ctx - a context with `tools`
 * @param {object} [options]
 * @param {string} [options.root] lease directory; defaults to `$DSH_HOME/governor`
 * @param {object} [options.budget] budget overrides (perSlotBytes/maxSlots/minSlots)
 * @param {string} [options.toolName]
 * @returns {() => void} disposer
 */
export function registerAdmissionGovernor(ctx, options = {}) {
  const dshHome = options.dshHome ?? process.env.DSH_HOME ?? path.join(os.homedir(), '.dsh');
  const root = options.root ?? governorRoot(dshHome);
  const budgetOptions = options.budget ?? {};
  const toolName = options.toolName || 'admission_governor';

  const definition = {
    name: toolName,
    description: DESCRIPTION,
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        action: {
          type: 'string',
          enum: ['status', 'acquire', 'renew', 'release'],
          description: 'status (read-only view), acquire (ask for a slot), renew (extend a held lease), release (give it back).',
        },
        kind: { type: 'string', description: 'What the work is, e.g. "agent-fleet" or "build". Shown to every other caller.' },
        note: { type: 'string', description: 'Why it is running. Shown to every other caller, so keep it short and specific.' },
        ttlMs: { type: 'integer', description: `How long the lease is valid before it must be renewed. Default ${TTL_MS_DEFAULT} ms.` },
        id: { type: 'string', description: 'The lease id returned by acquire. Required for renew and release.' },
      },
      required: ['action'],
    },
    output: {
      schema: OUTPUT_SCHEMA,
      render(args, value) {
        // Never a blank card: every outcome, including a refusal-shaped one, is
        // rendered as a sentence.
        const lines = [typeof value?.message === 'string' && value.message.length > 0 ? value.message : 'admission_governor: no message'];
        if (typeof value?.derivation === 'string') lines.push(`budget: ${value.derivation}`);
        if (Array.isArray(value?.holders) && value.holders.length > 0) lines.push(`holders: ${value.holders.join('; ')}`);
        return [{ type: 'text', text: lines.join('\n') }];
      },
    },
    async execute(args) {
      const action = typeof args?.action === 'string' ? args.action : 'status';
      const ttlMs = Number.isFinite(args?.ttlMs) && args.ttlMs > 0 ? args.ttlMs : TTL_MS_DEFAULT;

      if (action === 'status') {
        const view = status({ root, ...budgetOptions, reapFirst: false });
        return {
          state: view.free > 0 ? 'free' : 'full',
          action,
          message: `${view.inUse} of ${view.budget} slot(s) in use, ${view.free} free, ${view.waiters} waiting on ${view.host}`
            + (view.headroomLow ? ' (memory headroom is low; the budget is at its floor)' : ''),
          budget: view.budget,
          inUse: view.inUse,
          free: view.free,
          waiters: view.waiters,
          headroomLow: view.headroomLow,
          derivation: view.derivation,
          holders: view.holders.map((holder) => `slot ${holder.slot} pid ${holder.pid} ${holder.kind} held ${Math.round(holder.heldMs / 1000)}s`),
          deadLeases: view.deadLeases.map((dead) => `slot ${dead.slot} pid ${dead.pid} expired ${Math.round((dead.expiredForMs ?? 0) / 1000)}s ago`),
        };
      }

      if (action === 'acquire') {
        const outcome = acquire({
          root,
          ...budgetOptions,
          kind: typeof args?.kind === 'string' ? args.kind : 'agent',
          note: typeof args?.note === 'string' ? args.note : '',
          ttlMs,
        });
        if (outcome.state === 'granted') {
          return {
            state: 'granted',
            action,
            message: `GRANTED slot ${outcome.lease.slot}; lease ${outcome.lease.id} is valid for ${Math.round(ttlMs / 1000)}s.`
              + ` Renew it with action=renew id=${outcome.lease.id} before then, and release it with action=release when the work ends.`,
            leaseId: outcome.lease.id,
            slot: outcome.lease.slot,
            expiresInMs: ttlMs,
            budget: outcome.budget.budget,
            derivation: outcome.budget.arithmetic,
          };
        }
        const view = status({ root, ...budgetOptions, reapFirst: false });
        return {
          state: 'queued',
          action,
          message: `QUEUED: all ${outcome.budget.budget} slot(s) are held. You are number ${outcome.position + 1} in line`
            + ` (${outcome.active} active, ${outcome.waiters} waiting). Nothing was refused — start your work anyway if it can wait,`
            + ' or use fewer concurrent shells, or wait a few seconds and ask again.',
          position: outcome.position + 1,
          budget: outcome.budget.budget,
          inUse: outcome.active,
          free: 0,
          waiters: view.waiters,
          derivation: outcome.budget.arithmetic,
          holders: view.holders.map((holder) => `slot ${holder.slot} pid ${holder.pid} ${holder.kind} held ${Math.round(holder.heldMs / 1000)}s`),
        };
      }

      if (action === 'renew') {
        if (typeof args?.id !== 'string') {
          return { state: 'error', action, message: 'renew needs the lease id returned by acquire (action=renew id=<leaseId>).' };
        }
        const document = renew(root, args.id, ttlMs);
        if (document === undefined) {
          return { state: 'lost', action, message: `No lease with id ${args.id} is held — it expired or was released. Acquire a new slot; do not assume the old one is still yours.` };
        }
        return {
          state: 'renewed',
          action,
          message: `RENEWED slot ${document.slot}; valid until ${new Date(document.expiresAt).toISOString()}.`,
          leaseId: document.id,
          slot: document.slot,
          expiresInMs: Math.max(0, document.expiresAt - Date.now()),
        };
      }

      if (action === 'release') {
        if (typeof args?.id !== 'string') {
          return { state: 'error', action, message: 'release needs the lease id returned by acquire (action=release id=<leaseId>).' };
        }
        const outcome = release(root, args.id);
        return {
          state: outcome.released ? 'released' : 'not-held',
          action,
          message: outcome.released
            ? `RELEASED slot ${outcome.slot}; the next caller can take it.`
            : `No lease with id ${args.id} was held; nothing to release.`,
        };
      }

      return { state: 'error', action, message: `Unknown action ${JSON.stringify(action)}; use status, acquire, renew or release.` };
    },
  };

  return ctx.tools.register(definition);
}
