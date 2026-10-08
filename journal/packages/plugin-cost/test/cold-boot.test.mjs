/**
 * COLD BOOT: the generated artifacts must load with `DSH_HOME` UNSET.
 *
 * WHY THIS FILE EXISTS. On 2026-09-17 the engine would not start at all — the owner rebooted
 * at 21:31 and DSH never came back. The generated `lib/guard.js` built its module anchor as
 * `DSH_HOME` **else `USERPROFILE`**, so with `DSH_HOME` unset — the NORMAL case, because the
 * variable is documented as an optional override — the anchor became
 * `C:\Users\ezabz\profiles\web\package.json` instead of
 * `C:\Users\ezabz\.dsh\profiles\web\package.json`. `@deepseek-ai/schemastery` does not resolve
 * from there, the plugin tree failed to load, and the engine exited 1. The rebuild that armed
 * the fault was at 10:45; it detonated at the next cold boot, 21:31, eleven hours later. The
 * full record is `docs/incidents/2026-09-17-dsh-engine-boot-failure/`; Appendix B of that
 * report is the DYNAMIC half of this file, verbatim.
 *
 * TWO HALVES, AND THEY CATCH DIFFERENT THINGS:
 *
 *   STATIC — `requireAnchor()` read straight out of the artifact.
 *     Catches a generator that has been changed back to a fallback without the `.dsh` segment,
 *     on ANY machine, including one with no DSH installed, because the anchor is computed and
 *     compared rather than merely loaded. This is the half that goes red against the OLD
 *     generator (proved, see the incident README). It also catches a hand-edited artifact whose
 *     anchor has drifted from the generator's.
 *
 *   DYNAMIC — Appendix B exactly: import the artifact in a child process with `DSH_HOME`
 *     cleared, and require `LOADED`.
 *     Catches a bad anchor by its real effect, which is the only way to catch an anchor that
 *     looks right and resolves wrong. `lib/guard.js` is the DISCRIMINATOR: it is the file that
 *     requires the bare package `@deepseek-ai/schemastery`. `lib/index.js` requires only `node:`
 *     builtins, and those resolve from ANY anchor — so its load is a check that this change did
 *     not break the other artifact, not a check of the fallback.
 *
 * The dynamic half is skipped ONLY when this machine cannot resolve `@deepseek-ai/schemastery`
 * from the real profile anchor at all (no DSH profile here). A skip is printed loudly with the
 * path it looked at; it is never silent, because an empty result is not evidence of health.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * AND A THIRD HALF, ADDED 2026-09-28: THE GUARD MUST RESOLVE NO PACKAGE AT LOAD.
 *
 * The 2026-09-17 incident was one anchor being wrong. This one is worse in kind: the guard row
 * had a STATIC `import Schema from '@deepseek-ai/schemastery'` bound at module scope through that
 * anchor, so if `<DSH_HOME>/profiles/node_modules` was not there at the instant the entry was
 * imported — and on a candidate engine it was there only about half the time, four consecutive
 * boots of ONE unchanged home failing twice — the row failed to import, the engine reported the
 * bare string `failed to import`, and the money ceiling was silently absent. A protective plugin
 * may not have a load-time dependency on a directory it does not own, so the guard now resolves
 * `node:` builtins only while loading and probes for the schema class lazily at mount.
 *
 *   PACKAGES — every specifier the generated file requires at load is a `node:` builtin. This is
 *     machine-independent and goes red the moment someone reintroduces a bare import.
 *   BARREN — `lib/guard.js` is imported in a child whose `DSH_HOME` is an EMPTY directory: no
 *     profile, no `profiles/node_modules`, nothing. `LOADED` is the assertion, and against the
 *     2026-09-28 shape this is `FAILED: MODULE_NOT_FOUND` for `@deepseek-ai/schemastery` — the
 *     engine's own death, reproduced on demand.
 *
 * Usage: node test/cold-boot.test.mjs
 */
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join, normalize } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

/** The two generated artifacts that carry `requireAnchor()`. Both must be right. */
const ARTIFACTS = ['lib/guard.js', 'lib/index.js'];

/** The artifact whose load actually proves the fallback (it needs a bare package). */
const DISCRIMINATOR = 'lib/guard.js';

/** The bare package the anchor exists to resolve. `src/guard-entry.mjs` requires it. */
const BARE_PACKAGE = '@deepseek-ai/schemastery';

/**
 * The OLD fallback, verbatim: `USERPROFILE` used AS the DSH home, one segment short.
 * This is the literal shape that made the engine unbootable, and its absence from the
 * generated files is the point of the static half.
 */
const OLD_FALLBACK = /:\s*\(process\.env\.USERPROFILE \|\| process\.env\.HOME \|\| ''\)/;

let checks = 0;
let failures = 0;
let skipped = 0;
const check = (name, condition, detail) => {
  checks += 1;
  if (condition) console.log(`  ok    ${name}`);
  else {
    failures += 1;
    console.log(`  FAIL  ${name}${detail === undefined ? '' : ` — ${detail}`}`);
  }
};

/**
 * Pull `requireAnchor()` out of a generated file and run it with `DSH_HOME` cleared.
 *
 * The function is plain — it reads `process` and nothing else — so it can be evaluated without
 * the module it lives in. The ambient `DSH_HOME` is restored afterwards whatever happens.
 */
function anchorFrom(relative) {
  const source = readFileSync(join(ROOT, relative), 'utf8');
  const match = source.match(/function requireAnchor\(\) \{[\s\S]*?\n\}/);
  if (match === null) return { found: false, source };
  const saved = process.env.DSH_HOME;
  try {
    delete process.env.DSH_HOME;
    const anchor = new Function(`${match[0]}\nreturn requireAnchor();`)();
    return { found: true, body: match[0], anchor, source };
  } finally {
    if (saved === undefined) delete process.env.DSH_HOME;
    else process.env.DSH_HOME = saved;
  }
}

/** Run Appendix B's command for one artifact, with `DSH_HOME` deleted from the child's env. */
function loadWithoutDshHome(relative) {
  const url = pathToFileURL(join(ROOT, relative)).href;
  const script = `import(${JSON.stringify(url)}).then(() => console.log('LOADED')).catch((e) => console.log('FAILED: ' + e.code));`;
  const env = { ...process.env };
  delete env.DSH_HOME;
  const run = spawnSync(process.execPath, ['--input-type=module', '-e', script], {
    env,
    encoding: 'utf8',
    timeout: 120000,
  });
  return {
    url,
    command: `Remove-Item Env:DSH_HOME; node --input-type=module -e "import('${url}').then(()=>console.log('LOADED')).catch(e=>console.log('FAILED: '+e.code))"`,
    out: `${run.stdout ?? ''}${run.stderr ?? ''}`.trim(),
    status: run.status,
  };
}

/**
 * Import one artifact in a child whose `DSH_HOME` is an EMPTY directory.
 *
 * This is the load-path regression test: a module that resolves a bare package at load dies here
 * with `MODULE_NOT_FOUND`, which is exactly what the engine reported as
 * `spend-guard (dsh-plugin-cost/guard): failed to import`.
 */
function loadInBarrenHome(relative, home) {
  const url = pathToFileURL(join(ROOT, relative)).href;
  const script = `import(${JSON.stringify(url)}).then(() => console.log('LOADED')).catch((e) => console.log('FAILED: ' + e.code + ' ' + String(e.message).split('\\n')[0]));`;
  const env = { ...process.env, DSH_HOME: home };
  const run = spawnSync(process.execPath, ['--input-type=module', '-e', script], {
    env,
    encoding: 'utf8',
    timeout: 120000,
  });
  return {
    url,
    command: `$env:DSH_HOME='${home}'; node --input-type=module -e "import('${url}').then(()=>console.log('LOADED')).catch(e=>console.log('FAILED: '+e.code))"`,
    out: `${run.stdout ?? ''}${run.stderr ?? ''}`.trim(),
    status: run.status,
  };
}

/** Every `require('...')` specifier in a generated artifact. */
function requiredSpecifiers(relative) {
  const source = readFileSync(join(ROOT, relative), 'utf8');
  const found = [];
  const pattern = /require\('([^']+)'\)/g;
  let match = pattern.exec(source);
  while (match !== null) {
    found.push(match[1]);
    match = pattern.exec(source);
  }
  return found;
}

console.log('');
console.log('cold boot: the generated artifacts must load with DSH_HOME UNSET');
console.log(`  ambient DSH_HOME: ${process.env.DSH_HOME === undefined ? '(not set)' : process.env.DSH_HOME}`);
console.log('  every check below clears it — a fix that only works with the variable set is not a fix');

// The real profile anchor, derived the way the rest of this package derives it
// (`src/session-log.mjs`: `process.env.DSH_HOME ?? join(homedir(), '.dsh')`).
const expectedAnchor = join(homedir(), '.dsh', 'profiles', 'web', 'package.json');
const base = process.env.USERPROFILE || process.env.HOME || '';
const baseIsHomedir = base !== '' && normalize(base) === normalize(homedir());
console.log(`  real profile anchor: ${expectedAnchor}`);

// Can this machine resolve the bare package at all? If not, the dynamic half is not a test of
// anything and must say so rather than pass vacuously.
let resolvable;
try {
  resolvable = createRequire(expectedAnchor).resolve(BARE_PACKAGE);
} catch {
  resolvable = undefined;
}
console.log(
  resolvable === undefined
    ? `  bare package: ${BARE_PACKAGE} -> NOT RESOLVABLE here (dynamic half will be SKIPPED)`
    : `  bare package: ${BARE_PACKAGE} -> ${resolvable}`,
);

// ── STATIC: the emitted anchor ──────────────────────────────────────────────
for (const artifact of ARTIFACTS) {
  const result = anchorFrom(artifact);
  check(`${artifact}: emits a requireAnchor() to inspect`, result.found);
  if (!result.found) continue;

  const segments = String(result.anchor).split(/[\\/]/);
  check(
    `${artifact}: the unset-DSH_HOME anchor carries the .dsh segment`,
    segments.includes('.dsh'),
    `anchor was ${result.anchor}`,
  );
  check(
    `${artifact}: the anchor ends .dsh/profiles/web/package.json`,
    /\.dsh[\\/]profiles[\\/]web[\\/]package\.json$/.test(String(result.anchor)),
    `anchor was ${result.anchor}`,
  );
  check(
    `${artifact}: the old fallback (USERPROFILE with no .dsh) is gone`,
    !OLD_FALLBACK.test(result.body),
    'the generated fallback is the 2026-09-17 shape, which made the engine unbootable',
  );
  if (baseIsHomedir) {
    check(
      `${artifact}: the anchor is exactly this machine's real profile`,
      normalize(String(result.anchor)) === normalize(expectedAnchor),
      `expected ${expectedAnchor}, got ${result.anchor}`,
    );
  } else {
    checks += 1;
    console.log(`  ok    ${artifact}: anchor-vs-homedir equality not applicable (USERPROFILE/HOME ${base} != homedir ${homedir()})`);
  }
}

// ── DYNAMIC: Appendix B, run ────────────────────────────────────────────────
if (resolvable === undefined) {
  skipped += 1;
  console.log(`  SKIP  dynamic cold boot: ${BARE_PACKAGE} does not resolve from ${expectedAnchor} on this machine`);
  console.log('        (no DSH profile here — the static half above still ran and is machine-independent)');
} else {
  for (const artifact of ARTIFACTS) {
    const run = loadWithoutDshHome(artifact);
    const loaded = run.out.includes('LOADED');
    check(
      `${artifact}: loads with DSH_HOME cleared${artifact === DISCRIMINATOR ? ' (the discriminator)' : ''}`,
      loaded,
      `child said: ${run.out.split('\n').slice(-3).join(' | ')}`,
    );
    console.log(`        ${run.command}`);
    console.log(`        -> ${run.out.split('\n').slice(-3).join(' | ')}`);
  }
}

// ── PACKAGES: nothing but `node:` builtins is resolved while these files load ───
console.log('');
console.log('load path: the guard must resolve no package while it is being imported');
for (const artifact of ARTIFACTS) {
  const specifiers = requiredSpecifiers(artifact);
  const bare = specifiers.filter((specifier) => !specifier.startsWith('node:'));
  check(
    `${artifact}: every require() is a node: builtin (${specifiers.length} found)`,
    bare.length === 0,
    `bare specifier(s) resolved at load: ${bare.join(', ')} — this is the 2026-09-28 failure mode: the row cannot import when <DSH_HOME>/profiles/node_modules is not there yet`,
  );
}

// ── BARREN: import in a child whose DSH_HOME cannot provide anything ───────────
const barrenHome = mkdtempSync(join(tmpdir(), 'dsh-cold-boot-barren-'));
try {
  console.log(`  barren home: ${barrenHome} (no profile, no node_modules, nothing)`);
  const run = loadInBarrenHome(DISCRIMINATOR, barrenHome);
  check(
    `${DISCRIMINATOR}: loads with DSH_HOME an empty directory (the 2026-09-28 failure mode)`,
    run.out.includes('LOADED'),
    `child said: ${run.out.split('\n').slice(-3).join(' | ')}`,
  );
  console.log(`        ${run.command}`);
  console.log(`        -> ${run.out.split('\n').slice(-3).join(' | ')}`);
} finally {
  rmSync(barrenHome, { recursive: true, force: true });
}

console.log('');
console.log(
  `${checks} check(s), ${failures} failure(s)${skipped > 0 ? `, ${skipped} skipped section` : ''}`,
);
console.log(failures === 0 ? 'cold boot OK' : 'cold boot FAILED');
process.exit(failures === 0 ? 0 : 1);
