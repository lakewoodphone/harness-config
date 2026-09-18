/**
 * The host row that mounts the spend guard (`dsh-plugin-cost/guard`).
 *
 * ONE row, and it is deliberately a SEPARATE module path from the cost surfaces
 * in `lib/index.js`, because a Cordis loader entry resolves a module, not a
 * named export of one: two entries naming the same module would mount the same
 * plugin twice, and a second guard in one process would count every request
 * twice. The guard and `/cost` share the price card and the fold through the
 * generated sources (`scripts/build.mjs` concatenates `src/cost-core.mjs` and
 * `src/session-log.mjs` into both files), so the split is of the ENTRY, not of
 * the arithmetic.
 *
 * A loader entry can be disabled by id without editing this file
 * (`{ id: 'spend-guard', disabled: true }`); `settings/base.yaml` carries the
 * limits, so an operator changes a ceiling without a rebuild.
 */
import Schema from '@deepseek-ai/schemastery';

/** The Cordis plugin name. */
const name = 'spend-guard';

/**
 * No hard dependencies. The guard reads the session firehose, the agent
 * registry and the settings provider with `ctx.get()` behind absence checks, so
 * a profile that has none of them still mounts and still enforces the money
 * cap — and a missing optional service can never stop an engine booting.
 */
const inject = [];

/** One guard instance per process. Built at activation so limits come from config. */
let instance;

/**
 * Mount the guard.
 * @param {object} ctx the mounted plugin context
 * @param {object} config the composition row's config, merged with settings by
 *   the settings provider before this runs
 */
function apply(ctx, config = {}) {
  if (instance !== undefined) {
    // Reachable only if a composition mounts this module twice. Said out loud
    // rather than left to double-count.
    if (ctx.logger !== undefined && typeof ctx.logger.warn === 'function') {
      ctx.logger.warn('spend-guard: a second guard instance was mounted; the first one stays authoritative and this one only reports its own state');
    }
  }
  const guard = createGuard({
    core: { PRICING, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome },
    Schema,
  });
  if (instance === undefined) instance = guard;
  guard.apply(ctx, config);
}
