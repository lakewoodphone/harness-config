/**
 * Resolve a usable `yaml` implementation from the installed DSH tree, plus the custom tag
 * that makes `--dump-config` output parse without noise.
 *
 * WHY THIS IS NOT A BARE `import 'yaml'`
 * -------------------------------------
 * `scripts/merge-settings.mjs` learned this the hard way (2026-09-14): a bare `require('yaml')`
 * can resolve to a *different* package that happens to share the name and has no `parse`, and
 * the failure was `TypeError: YAML.parse is not a function`. So candidates are probed in a
 * fixed order, each one is shape-validated, and the first usable one wins. This module is the
 * same approach, verbatim, with one fix: `merge-settings.mjs` uses `readdirSync` without
 * importing it from `node:fs`, so its npx-cache probing branch cannot execute. Here it is
 * imported.
 *
 * WHY THE CUSTOM TAG
 * ------------------
 * The dump is a YAML sequence of maps whose values include `!!js <expression>` — raw JavaScript
 * that the *engine* evaluates at boot, and that we must only ever describe. `yaml@2.9.0` parses
 * the document successfully but emits a `TAG_RESOLVE_FAILED` warning for every `!!js` scalar and
 * resolves the value to `undefined`. A `TAG_RESOLVE_FAILED` storm hides real parse problems, and
 * `undefined` loses the only thing that matters about the field: that it is an expression and
 * which expression it is. Supplying our own resolver keeps the source text and silences the
 * warning.
 *
 * The tag is registered under the *standard* URI `tag:yaml.org,2002:js`, so `!!js` (the short
 * form the engine emits) resolves through it. Values come back as `{ __js: "<source text>" }`,
 * which is a value no YAML document can produce by accident and which is therefore safe to
 * detect downstream without ambiguity.
 *
 * Usage:
 *   import { YAML } from './yaml.mjs';       // resolved implementation, js tag applied
 *   import { loadYaml } from './yaml.mjs';   // the resolver itself, for re-probing
 *   node lib/yaml.mjs                        // prints the resolved module path (diagnostic)
 */
import { readdirSync, existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

/** The tag URI the engine's `!!js` shorthand expands to. */
export const JS_TAG_URI = 'tag:yaml.org,2002:js';

/**
 * A `yaml` custom tag that preserves `!!js` source text instead of resolving it.
 *
 * `resolve` receives the scalar's string content; returning a wrapper rather than a value is
 * the whole point — nothing in this pipeline may *evaluate* engine expressions.
 * `identify` is what lets `stringify` round-trip the same wrapper back to `!!js`.
 */
export const jsTag = {
  tag: JS_TAG_URI,
  resolve: (v) => ({ __js: v }),
  identify: (v) => Boolean(v) && typeof v === 'object' && typeof v.__js === 'string',
  stringify: (item) => item.__js,
};

export const CUSTOM_TAGS = [jsTag];

/** Options every parse in this pipeline should use, so no caller forgets the tag. */
export const PARSE_OPTIONS = { customTags: CUSTOM_TAGS };

/** True when a parsed value is an unevaluated `!!js` expression wrapper. */
export function isJs(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
    && typeof value.__js === 'string';
}

/**
 * Candidate module roots, in the order `merge-settings.mjs` probes them.
 * Exported separately so a failure message can name exactly what was tried.
 */
export function yamlCandidateRoots() {
  const candidates = [];
  const push = (p) => { if (p) candidates.push(p); };

  if (process.env.DSH_INSTALL) push(join(process.env.DSH_INSTALL, 'node_modules'));
  if (process.env.DSH_HOME) {
    push(join(process.env.DSH_HOME, 'profiles', 'web', 'node_modules'));
    push(join(process.env.DSH_HOME, 'profiles', 'node_modules'));
  }
  for (const rel of ['node_modules', '../node_modules', '../../node_modules']) {
    push(join(process.cwd(), rel));
  }
  // The npx cache the harness commonly runs from — EVERY prefix, not just the first.
  const locals = [process.env.LOCALAPPDATA];
  if (process.env.USERPROFILE) locals.push(join(process.env.USERPROFILE, 'AppData', 'Local'));
  for (const local of locals) {
    if (!local) continue;
    const npx = join(local, 'npm-cache', '_npx');
    if (!existsSync(npx)) continue;
    try {
      for (const d of readdirSync(npx)) push(join(npx, d, 'node_modules'));
    } catch { /* an unreadable npx cache is not fatal; other candidates remain */ }
  }
  return candidates;
}

/**
 * Probe candidate roots in order and return the first `yaml` implementation that has both
 * `parse` and `stringify` as functions.
 *
 * Throws an Error whose message lists every root tried and why each was rejected — because the
 * one thing worse than failing to find `yaml` is failing without saying where you looked.
 */
export function loadYaml() {
  const seen = new Set();
  const problems = [];
  const considered = [];

  for (const base of yamlCandidateRoots()) {
    if (!base || seen.has(base)) continue;
    seen.add(base);
    considered.push(base);

    if (!existsSync(join(base, 'yaml', 'package.json'))) {
      problems.push(`${base} -> no yaml/package.json`);
      continue;
    }
    try {
      const req = createRequire(join(base, 'noop.js'));
      const mod = req('yaml');
      const impl = mod?.default ?? mod;
      if (typeof impl?.parse === 'function' && typeof impl?.stringify === 'function') {
        return impl;
      }
      problems.push(`${base} -> yaml has no parse/stringify (got ${typeof impl?.parse}/${typeof impl?.stringify})`);
    } catch (e) {
      problems.push(`${base} -> ${e.message}`);
    }
  }

  throw new Error(
    'cannot resolve a usable "yaml" package (with parse and stringify). Tried: '
    + [...seen].join(', ')
    + (problems.length ? ` | rejected: ${problems.join('; ')}` : ''),
  );
}

/**
 * Where the resolved `yaml` came from, for provenance. Best-effort: returns the root the
 * resolver actually used when it can be determined, else null.
 */
export function yamlResolvedFrom() {
  for (const base of yamlCandidateRoots()) {
    if (!base || !existsSync(join(base, 'yaml', 'package.json'))) continue;
    try {
      const req = createRequire(join(base, 'noop.js'));
      const mod = req('yaml');
      const impl = mod?.default ?? mod;
      if (typeof impl?.parse === 'function' && typeof impl?.stringify === 'function') {
        let version = null;
        try {
          version = JSON.parse(readFileSync(join(base, 'yaml', 'package.json'), 'utf8')).version ?? null;
        } catch { /* version is decorative here */ }
        return { root: join(base, 'yaml'), version };
      }
    } catch { /* keep probing */ }
  }
  return null;
}

/** The resolved implementation, with the `!!js` tag always applied at the call sites below. */
export const YAML = loadYaml();

/** Parse with the `!!js` tag applied. */
export function parseYaml(text, options = {}) {
  return YAML.parse(text, { ...PARSE_OPTIONS, ...options });
}

/** Parse and collect non-fatal warnings instead of letting them interleave with stdout. */
export function parseYamlWithWarnings(text, options = {}) {
  const warnings = [];
  const doc = YAML.parseDocument(text, {
    ...PARSE_OPTIONS,
    ...options,
    onWarning: (w) => warnings.push(String(w?.message ?? w)),
  });
  return { value: doc.toJS(), warnings, errors: doc.errors.map((e) => String(e?.message ?? e)) };
}

// ── standalone ────────────────────────────────────────────────────────────────────────────────
// `node lib/yaml.mjs` is the diagnostic: which yaml did we get, does the js tag work, and does a
// real `!!js` folded scalar survive as source text?
const invokedDirectly = Boolean(process.argv[1])
  && import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedDirectly) {
  try {
    const where = yamlResolvedFrom();
    const probe = parseYaml([
      'a: !!js process.platform === \'win32\'',
      'b: !!js >-',
      '  process.env.X ??',
      '  \'literal\'',
      'c: true',
    ].join('\n'));
    const ok = isJs(probe.a) && probe.a.__js === "process.platform === 'win32'";
    const okFolded = isJs(probe.b) && probe.b.__js.includes('process.env.X ??');
    const artifact = {
      resolvedFrom: where?.root ?? null,
      yamlVersion: where?.version ?? null,
      jsTag: JS_TAG_URI,
      probe: { literalTagScalar: probe.a, foldedTagScalar: probe.b, plainBoolean: probe.c },
      jsScalarPreserved: ok,
      jsFoldedScalarPreserved: okFolded,
    };
    process.stdout.write(`${JSON.stringify(artifact, null, 2)}\n`);
    process.exit(ok && okFolded ? 0 : 1);
  } catch (e) {
    process.stderr.write(`yaml.mjs: ${e.message}\n`);
    process.exit(1);
  }
}
