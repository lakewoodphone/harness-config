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
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * WHY THERE IS NO `import Schema from '@deepseek-ai/schemastery'` HERE ANY MORE
 * (2026-09-28)
 *
 * A protective plugin must not be able to fail at LOAD time because of where it
 * looks for a library. The guard is the money ceiling: an engine that boots with
 * this row absent is worse than an engine with no guard at all, because the
 * operator believes he is protected.
 *
 * Up to this revision the entry carried a static `import Schema from
 * '@deepseek-ai/schemastery'`, which the generator bound as
 * `const Schema = require('@deepseek-ai/schemastery')` at MODULE SCOPE through a
 * hand-rolled anchor at `<DSH_HOME>/profiles/web/package.json`. That made the
 * row's ability to LOAD depend on `<DSH_HOME>/profiles/node_modules` existing at
 * the instant the entry was imported — a directory this plugin does not own, does
 * not write, and cannot see. Measured 2026-09-28 on a candidate engine
 * (`0.1.7-rc.2`): four consecutive boots of ONE staged home produced
 * `spend-guard (dsh-plugin-cost/guard): failed to import` twice and none twice,
 * with the legacy `settings.yaml` present or absent making no difference at all.
 * The engine's whole diagnostic is that one line: `entry.fiber === undefined`
 * (`dsh-app-boot/lib/index.js` `inactiveEntries`) renders as the literal string
 * "failed to import", and the loader's own `ctx.logger.error(error)` for that
 * entry reaches no sink in this deployment (`cordis-plugin-loader/lib/index.js`
 * `_init`). The reason was therefore invisible, and the operator's protection was
 * silently absent about half the time.
 *
 * THE FIX IS STRUCTURAL, NOT A RACE. `lib/guard.js` now resolves NOTHING but
 * `node:` builtins at load time (`node:fs`, `node:os`, `node:path`, `node:zlib`),
 * which resolve from ANY anchor, so no state of the DSH home can stop this module
 * from importing. The schema class is not needed to import the module and is not
 * needed to ENFORCE a ceiling — it is needed only to register the settings
 * namespace — so it is resolved lazily, inside `apply()`, at mount, where a
 * failure is a reported DEGRADED mode rather than a missing guard.
 *
 * The resolution itself is multi-root with shape validation, because the single
 * hard-coded anchor is exactly what broke (the shape of `loadYaml()` in
 * `scripts/merge-settings.mjs`): several candidate roots are probed in order, the
 * resolved value must carry the methods `policySchema()` actually uses, and what
 * was tried is reported. `DSH_SPEND_GUARD_SCHEMA_ROOTS` replaces the candidate
 * list, which is how a test or an operator forces the degraded path on purpose.
 */

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

/** The one bare package the settings registration needs. Nothing else is resolved. */
const SCHEMA_PACKAGE = '@deepseek-ai/schemastery';

/** Environment override that REPLACES the candidate roots (`;`-separated). */
const SCHEMA_ROOTS_ENV = 'DSH_SPEND_GUARD_SCHEMA_ROOTS';

/** The members `policySchema()` calls on the schema class, and nothing else. */
const SCHEMA_METHODS = ['object', 'number', 'string', 'boolean', 'union'];

/**
 * Join one path segment onto a base, without importing `node:path`.
 *
 * Self-contained on purpose: this runs while the module is deciding whether it
 * can be configured at all, so it may not depend on anything that could be the
 * thing that is broken.
 * @param {string} base a directory
 * @param {string} leaf a file or directory name
 * @returns {string} the joined path
 */
function childPath(base, leaf) {
  const sep = base.indexOf('\\') >= 0 ? '\\' : '/';
  return base.replace(/[\\/]+$/, '') + sep + leaf;
}

/**
 * `createRequire`, without an import.
 *
 * Node 20.16/22.3 added `process.getBuiltinModule`, which returns a builtin
 * without a module load — so on the Node versions this deployment runs there is
 * nothing to resolve and nothing to fail. On anything older, the GENERATED file
 * already holds a module-scope `createRequire` (the anchor emitter in
 * `scripts/build.mjs` imports it), and `typeof` on an identifier the
 * concatenation did not bind is `'undefined'` rather than a `ReferenceError`.
 * @returns {Function|undefined} a `createRequire`, or undefined
 */
function schemaCreateRequire() {
  if (typeof process !== 'undefined' && typeof process.getBuiltinModule === 'function') {
    const api = process.getBuiltinModule('node:module');
    if (api !== undefined && api !== null && typeof api.createRequire === 'function') return api.createRequire;
  }
  if (typeof createRequire === 'function') return createRequire;
  return undefined;
}

/**
 * The candidate directories to resolve the schema package from, best first.
 *
 * `<home>/profiles/node_modules` is first because that is the only directory in
 * this deployment where a bare `@deepseek-ai/*` name actually exists (the profile
 * is `pnpm`-shaped and the engine's own install is linked in there). The rest are
 * the places Node itself would walk, plus the engine install when the launcher
 * exports it. A root that does not exist is not an error: it is an attempt.
 * @param {string} home the DSH home
 * @returns {string[]} absolute candidate roots, in probe order
 */
function schemaRoots(home) {
  const override = typeof process !== 'undefined' ? process.env[SCHEMA_ROOTS_ENV] : undefined;
  if (typeof override === 'string' && override.trim().length > 0) {
    return override
      .split(';')
      .map((entry) => entry.trim())
      .filter((entry) => entry.length > 0);
  }
  const profiles = childPath(home, 'profiles');
  const web = childPath(profiles, 'web');
  const roots = [
    childPath(profiles, 'node_modules'),
    childPath(web, 'node_modules'),
    web,
    profiles,
    childPath(home, 'node_modules'),
  ];
  // `pnpm` and Windows both take either separator; normalise so the strings are
  // unique in the report rather than listing one directory twice.
  const install = typeof process !== 'undefined' ? process.env.DSH_INSTALL : undefined;
  if (typeof install === 'string' && install.length > 0) roots.push(childPath(install, 'node_modules'));
  const seen = new Set();
  return roots.filter((root) => {
    const key = root.replace(/[\\/]+/g, '/').toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * Shape test: can `policySchema()` be called with this value?
 *
 * A resolved module that is the wrong package, a stub, or a namespace with the
 * methods missing is REJECTED, never used hopefully — that is the difference
 * between a probe and a guess.
 * @param {unknown} candidate the resolved module, or its `default`
 * @returns {boolean} true when every method `policySchema()` uses is a function
 */
function isSchemaClass(candidate) {
  if (candidate === undefined || candidate === null) return false;
  for (const method of SCHEMA_METHODS) if (typeof candidate[method] !== 'function') return false;
  return true;
}

/**
 * Resolve the schema class lazily, from several roots, with validation.
 *
 * NEVER THROWS. A failure here is a DEGRADED mode, not a reason to leave the
 * money ceilings unenforced: the guard's own `DEFAULTS` and the row's `config`
 * already carry every limit, so the only thing lost is the ability to read a
 * `spend-guard:` block out of `settings.yaml`.
 * @param {string} home the DSH home
 * @returns {{Schema:unknown, mode:string, package:string, root:string, roots:string[], attempts:string[]}}
 */
function resolveSchema(home) {
  const roots = schemaRoots(home);
  const attempts = [];
  const create = schemaCreateRequire();
  if (create === undefined) {
    return {
      Schema: undefined,
      mode: 'unavailable',
      package: SCHEMA_PACKAGE,
      root: '',
      roots,
      attempts: ['no createRequire in this runtime (Node < 20.16 and no module-scope binding)'],
    };
  }
  for (const root of roots) {
    try {
      const req = create(childPath(root, 'noop.js'));
      const loaded = req(SCHEMA_PACKAGE);
      const impl = isSchemaClass(loaded) ? loaded : isSchemaClass(loaded === null || loaded === undefined ? undefined : loaded.default) ? loaded.default : undefined;
      if (impl === undefined) {
        attempts.push(`${root} -> resolved, but the module has no ${SCHEMA_METHODS.join('/')}`);
        continue;
      }
      return { Schema: impl, mode: 'loaded', package: SCHEMA_PACKAGE, root, roots, attempts };
    } catch (error) {
      attempts.push(`${root} -> ${error instanceof Error ? error.message.split('\n')[0] : String(error)}`);
    }
  }
  return { Schema: undefined, mode: 'unavailable', package: SCHEMA_PACKAGE, root: '', roots, attempts };
}

/**
 * Mount the guard.
 *
 * The schema resolution happens HERE and not at module scope, which is what makes
 * this row unbreakable at load: by the time this runs, the module has already
 * imported and the guard is already on the money path.
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
  const schema = resolveSchema(dshHome());
  if (schema.mode === 'unavailable') {
    // LOUD, and it names what was tried. A guard enforcing the coded defaults is
    // acceptable; a guard doing it invisibly is the failure this file exists to
    // prevent.
    const line =
      `spend-guard: DEGRADED — could not resolve ${SCHEMA_PACKAGE}, so a "spend-guard:" block in settings.yaml is NOT applied. ` +
      `The row config plus the coded DEFAULTS are in force and the ceilings ARE enforced. Tried: ${schema.attempts.join(' | ')}`;
    if (ctx.logger !== undefined && typeof ctx.logger.warn === 'function') ctx.logger.warn(line);
    else if (ctx.logger !== undefined && typeof ctx.logger.error === 'function') ctx.logger.error(line);
    else if (typeof console !== 'undefined' && typeof console.error === 'function') console.error(line);
    // AND TO STDERR, because `ctx.logger` is a DEAD END in this deployment:
    // measured 2026-09-28, neither the loader's `ctx.logger.error` for a failed
    // entry nor this guard's own `ctx.logger.info`/`warn` appears in the engine's
    // captured stderr, or anywhere in its home. Once per boot, and only in this
    // mode, so it cannot become noise.
    if (typeof process !== 'undefined' && process.stderr !== undefined && typeof process.stderr.write === 'function') {
      process.stderr.write(`${line}\n`);
    }
  } else if (schema.root !== schema.roots[0]) {
    // Not an error, but a resolution through a root that was not the expected one
    // means the anchor moved, and a later session should be able to see that.
    const line = `spend-guard: the settings schema library resolved from ${schema.root} (first candidate was ${schema.roots[0]})`;
    if (ctx.logger !== undefined && typeof ctx.logger.info === 'function') ctx.logger.info(line);
  }
  const guard = createGuard({
    core: { PRICING, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome },
    Schema: schema.Schema,
    schemaResolution: schema,
  });
  if (instance === undefined) instance = guard;
  guard.apply(ctx, config);
}
