/**
 * `/cost` — price the current session in USD, per turn and in total.
 *
 * The handler reads the live session's own durable log rather than a projection,
 * because cost needs two facts the projections do not carry: the provider/model of
 * each billed attempt, and the wall-clock instant that decides the peak/off-peak
 * rate. Both are per-message facts in the log; neither survives into `tokenUsage`.
 *
 * A session the log cannot be found for returns an error rather than a guess.
 */
import { PRICING, indexRoutes, foldSession, totalSession, renderReport, formatUsd } from './cost-core.mjs';
import { findSessionLog, readSessionLog, dshHome } from './session-log.mjs';

const byKey = indexRoutes(PRICING);

const USAGE_TEXT = [
  'Usage: /cost [turns]',
  '',
  '  /cost         total, plus the most recent 8 turns',
  '  /cost 40      total, plus the most recent 40 turns',
  '  /cost all     total, plus every turn',
].join('\n');

/**
 * Build the report text for one session.
 * @param {string} sessionId
 * @param {string|undefined} cwd
 * @param {string} rawInput exact text after the command name
 * @returns {string} the report, or an explanation of why it cannot be produced
 */
export function costReport(sessionId, cwd, rawInput) {
  const argument = rawInput.trim().toLowerCase();
  let maxTurns = 8;
  if (argument === 'all') maxTurns = 0;
  else if (argument.length > 0) {
    const parsed = Number(argument);
    if (!Number.isInteger(parsed) || parsed < 1 || parsed > 500) return USAGE_TEXT;
    maxTurns = parsed;
  }

  const { file, candidates } = findSessionLog(sessionId, cwd);
  if (file === undefined) {
    return [
      `No session log on disk for ${sessionId}, so this session cannot be priced.`,
      `Looked in: ${dshHome()}`,
      ...candidates.map((path) => `  ${path}`),
      'The log is written per turn; an unpriced session is one whose log has not been flushed yet.',
    ].join('\n');
  }

  const events = readSessionLog(file);
  const folded = foldSession(events, byKey);
  const totals = totalSession(folded.rows, folded.gaps);

  const header = [
    `Session cost — ${sessionId}`,
    `  log   ${file}`,
    `  rates ${PRICING.routes.map((route) => `${route.provider}/${route.models[0]} ${route.rates.missPer1M}|${route.rates.hitPer1M}|${route.rates.outputPer1M}`).join('  ')}   (miss|hit|output USD per 1M, updated ${PRICING.updated})`,
  ].join('\n');

  const body = renderReport(totals, { title: '', maxTurns });
  return `${header}\n${body}`;
}

/**
 * Register `/cost` for every composed human-command adapter.
 * @param {object} commands the `commands` service from the mounted context
 * @param {object} sessions the `sessions` service from the mounted context
 * @returns {() => void} the disposer that unregisters the command
 */
export function registerCostCommand(commands, sessions) {
  return commands.register({
    name: 'cost',
    description: 'Price this session in USD, per turn and in total',
    handler: (invocation) => {
      try {
        const sessionId = String(invocation.agent.sessionId);
        const session = sessions.get(sessionId);
        const cwd = session?.header?.cwd;
        const text = costReport(sessionId, cwd, invocation.rawInput ?? '');
        return { kind: 'success', text };
      } catch (error) {
        return { kind: 'error', text: `Could not price this session: ${error.message}` };
      }
    },
  });
}

/**
 * Re-exported names that the concatenating build already declares in the same
 * module scope. These must stay single names — a second `const PRICING` in the
 * generated file is a redeclaration error, not a merge.
 */

/** The rate table the report cites, as loaded. */
export function pricingTable() {
  return PRICING;
}
