/**
 * contract.mjs — describe an installed DSH tree as `contract.json`.
 *
 * Half of the dsh-update pipeline: this module answers "what IS installed here?" with enough
 * structure that two versions can be diffed mechanically. It never decides whether a difference
 * matters — that is `diff.mjs`'s job — and it never evaluates engine expressions.
 *
 * WHAT IS AUTHORITATIVE AND WHAT IS ADVISORY (SPEC.md §Evidence tiers)
 * ------------------------------------------------------------------
 * AUTHORITATIVE: `package.json` (name, version, exports, bin, dsh, dependencies), file presence
 * and sha256, and the directory that actually exists on disk. These are read, not inferred.
 *
 * ADVISORY: settings keys, service names, tool names and exported symbols, recovered by regex
 * from built JavaScript. Best-effort by construction, so every array carries the pattern that
 * produced it in `advisoryPatterns`, and `provenance` marks it ADVISORY. A `BREAKS` finding may
 * never rest on these alone.
 *
 * WHY `exportSubpaths` IS DERIVED FROM `exports` AND NOTHING ELSE
 * --------------------------------------------------------------
 * A subpath is resolvable exactly when Node's resolver says it is, and for a package with an
 * `exports` field the `exports` keys are that answer. `main`/`module` are a *fallback that only
 * applies when `exports` is absent*, and they can disagree with reality — so their use is
 * recorded as a note, never silently substituted. `files` in package.json is a *publish* list and
 * is deliberately NOT used: it names globs, not resolvable subpaths.
 *
 * Usage:
 *   node lib/contract.mjs <installRoot> [--out <path>] [--max-files-per-package N]
 */
import { createHash } from 'node:crypto';
import {
  existsSync, lstatSync, mkdirSync, readdirSync, readFileSync, realpathSync, statSync, writeFileSync,
} from 'node:fs';
import { open } from 'node:fs/promises';
import { hostname } from 'node:os';
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

const SCHEMA_VERSION = 1;
const DEFAULT_MAX_FILES_PER_PACKAGE = 2000;
const HASH_SIZE_LIMIT_BYTES = 2 * 1024 * 1024; // files over this are sized, not hashed
const HASH_CONCURRENCY = 8;
const SCOPE_DIR = join('node_modules', '@deepseek-ai');

// ── advisory patterns ────────────────────────────────────────────────────────────────────────
// Every regex below is declared as a named constant, reported verbatim in `advisoryPatterns`, and
// kept deliberately narrow: a pattern that fires on the wrong construct produces a plausible,
// wrong list, which is worse than an empty one.
const PATTERNS = {
  settingsKeys:
    'top-level keys of the object literal assigned to a `const Config = <z>.object({ ... })` '
    + '(brace-depth balanced scan; identifier and quoted keys at depth 1) in lib/*.js',
  serviceNames:
    'string elements of `const inject = [ ... ]` (the cordis service names a plugin declares it '
    + 'requires) in lib/*.js',
  toolNames:
    'string literal of the `name:` property in a `defineTool({ ... })` call in lib/*.js; a '
    + 'non-literal (`name: toolName`) is skipped, never guessed',
  symbols:
    'names in a top-level `export { a, b as c }` list plus `export const|function|class|let X` '
    + 'declarations in lib/*.js',
};

// ── small helpers ────────────────────────────────────────────────────────────────────────────
const toPosix = (p) => p.split(sep).join('/');

/** Stable key order so two contract.json files diff by content, not by key insertion order. */
function sortObject(value) {
  if (Array.isArray(value)) return value;
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map((k) => [k, sortObject(value[k])]));
  }
  return value;
}

function readJsonFile(file) {
  const text = readFileSync(file, 'utf8');
  return JSON.parse(text);
}

async function sha256File(file) {
  const fh = await open(file, 'r');
  try {
    const hash = createHash('sha256');
    // Bounded read: never load a whole file into memory, and never the whole tree at once.
    const buf = Buffer.allocUnsafe(256 * 1024);
    for (;;) {
      const { bytesRead } = await fh.read(buf, 0, buf.length, null);
      if (bytesRead === 0) break;
      hash.update(buf.subarray(0, bytesRead));
    }
    return hash.digest('hex');
  } finally {
    await fh.close();
  }
}

/** Bounded-concurrency map — the only reason a 78-package hash does not serialise on I/O. */
async function mapLimit(items, limit, worker) {
  const results = new Array(items.length);
  let next = 0;
  const runners = Array.from({ length: Math.min(limit, items.length || 1) }, async () => {
    for (;;) {
      const i = next;
      next += 1;
      if (i >= items.length) return;
      results[i] = await worker(items[i], i);
    }
  });
  await Promise.all(runners);
  return results;
}

// ── exports → exportSubpaths ─────────────────────────────────────────────────────────────────
/**
 * Derive the resolvable subpath list from a package.json `exports` value.
 *
 * `exports` has four legal shapes and all four are handled:
 *   - a string            → sugar for the single subpath `"."`
 *   - an object           → keys are subpaths *unless* every key is a condition (`import`,
 *                           `require`, `default`, `browser`, `node`, `types`, `import.default`…),
 *                           in which case it too is sugar for `"."`
 *   - an array of conditions (or of objects) → sugar for `"."`
 *   - absent/`null`       → caller falls back to `main`/`module`
 */
/**
 * Node's own rule: inside `exports`, a key is a SUBPATH if it is `"."` or starts with `"./"`;
 * anything else is a CONDITION. So an object whose keys are all bare words (`import`, `default`,
 * `types`, …) is sugar for `"."`, while `{ "./list-agents": … }` is a real subpath map.
 *
 * Getting this wrong is expensive in exactly the way this pipeline exists to prevent: a
 * subpath map misread as a condition map collapses `./list-agents` into `"."`, so a removed
 * subpath looks present and B2 never fires.
 */
function isConditionObject(obj) {
  const keys = Object.keys(obj);
  if (keys.length === 0) return false;
  return keys.some((k) => k !== '.' && !k.startsWith('./'));
}

export function exportSubpathsFrom(exportsValue, pkg = {}) {
  const notes = [];
  let keys = null;

  if (typeof exportsValue === 'string') {
    keys = ['.'];
    notes.push('exports is a bare string, which is sugar for the "." subpath only');
  } else if (Array.isArray(exportsValue)) {
    keys = ['.'];
    notes.push('exports is an array of conditions, which is sugar for the "." subpath only');
  } else if (exportsValue && typeof exportsValue === 'object') {
    const own = Object.keys(exportsValue);
    if (own.length === 0) {
      keys = [];
      notes.push('exports is an empty object, so nothing is resolvable except package.json');
    } else if (isConditionObject(exportsValue)) {
      keys = ['.'];
      notes.push('exports is a single condition map, which is sugar for the "." subpath only');
    } else {
      keys = own;
    }
  }

  if (keys === null) {
    // No `exports`: fall back to main/module presence, and SAY SO.
    const hasMain = typeof pkg.main === 'string' && pkg.main.length > 0;
    const hasModule = typeof pkg.module === 'string' && pkg.module.length > 0;
    keys = ['.'];
    notes.push(
      `exports is absent; "." recorded from ${hasMain ? 'main' : (hasModule ? 'module' : 'neither main nor module')} `
      + 'presence — this is a fallback, not the resolver\'s own answer',
    );
  }

  const subpaths = new Set(keys);
  // `./package.json` is always resolvable and is named by this deployment, so it is always
  // recorded — marked in `notes` when the package did not enumerate it itself.
  if (!subpaths.has('./package.json')) {
    subpaths.add('./package.json');
    notes.push('"./package.json" added: always resolvable, not enumerated in exports');
  }
  if (keys.length > 0 && !subpaths.has('.')) {
    notes.push('exports is present but does NOT declare "." — the package root is not importable');
  }

  return { exportSubpaths: [...subpaths], notes };
}

// ── advisory extraction ──────────────────────────────────────────────────────────────────────
/** Read the top-level keys of `const <alias> = <z>.object({ ... })` with a depth-balanced scan. */
function extractConfigKeys(src) {
  const keys = new Set();
  const decl = /const\s+Config\s*=\s*[A-Za-z_$][\w$]*\.object\s*\(\s*\{/g;
  for (const m of src.matchAll(decl)) {
    const start = m.index + m[0].length - 1; // at the `{`
    let depth = 0;
    let i = start;
    for (; i < src.length; i += 1) {
      const c = src[i];
      if (c === '{') depth += 1;
      else if (c === '}') {
        depth -= 1;
        if (depth === 0) break;
      } else if (c === '`' || c === '"' || c === "'") {
        // Skip a quoted region wholesale so a brace inside it cannot move the depth. The outer
        // loop's own `i += 1` advances past the closing quote, so this must NOT also do it —
        // doing both skips a character and desynchronises the scan.
        const q = c;
        i += 1;
        while (i < src.length && src[i] !== q) i += src[i] === '\\' ? 2 : 1;
      }
    }
    const body = src.slice(start + 1, i);
    // Depth 1 only: a nested `z.object({ ... })` describes a sub-object, not a settings key.
    let d = 0;
    for (let j = 0; j < body.length; j += 1) {
      const c = body[j];
      if (c === '{' || c === '[') { d += 1; continue; }
      if (c === '}' || c === ']') { d -= 1; continue; }
      if (c === '"' || c === "'" || c === '`') {
        // Same rule as above: leave `j` ON the closing quote; the loop's `j += 1` moves past it.
        const q = c;
        j += 1;
        while (j < body.length && body[j] !== q) j += body[j] === '\\' ? 2 : 1;
        continue;
      }
      if (d !== 0) continue;
      const key = /^([A-Za-z_$][\w$]*|"[^"]+"|'[^']+')\s*:/.exec(body.slice(j, j + 200));
      if (key) {
        keys.add(key[1].replace(/^['"]|['"]$/g, ''));
        // Advance to the VALUE's first character. Without this the scan re-tests inside the key
        // and records its substrings — `backgroundMode` yields `ackgroundMode`, `epth`, `ame` —
        // which is a plausible-looking, wrong list. That is the failure mode this whole module
        // exists to avoid, so the advance is load-bearing, not an optimisation.
        j += key[0].length - 1;
      }
    }
  }
  return [...keys].sort();
}

function extractInjectServices(src) {
  const names = new Set();
  const re = /const\s+inject\s*=\s*\[([^\]]*)\]/g;
  for (const m of src.matchAll(re)) {
    for (const s of m[1].matchAll(/["']([^"']+)["']/g)) names.add(s[1]);
  }
  return [...names].sort();
}

function extractToolNames(src) {
  const names = new Set();
  const re = /defineTool\s*\(\s*\{[\s\S]{0,400}?\bname\s*:\s*(["'])([^"']+)\1/g;
  for (const m of src.matchAll(re)) names.add(m[2]);
  return [...names].sort();
}

function extractSymbols(src) {
  const names = new Set();
  const re = /\bexport\s*\{([^}]*)\}/g;
  for (const m of src.matchAll(re)) {
    for (const part of m[1].split(',')) {
      const spec = part.trim();
      if (!spec) continue;
      const alias = /\bas\s+([A-Za-z_$][\w$]*)$/.exec(spec);
      names.add(alias ? alias[1] : spec.replace(/^type\s+/, '').trim());
    }
  }
  const declRe = /\bexport\s+(?:const|let|var|function|class|async\s+function)\s+([A-Za-z_$][\w$]*)/g;
  for (const m of src.matchAll(declRe)) names.add(m[1]);
  return [...names].filter(Boolean).sort();
}

/**
 * Run the four advisory extractors over one package's own built JavaScript.
 *
 * The scan set is `lib/**\/*.js` plus any top-level `*.js`: that is where every package in this
 * tree puts its compiled entry point and its `Config`/`inject` declarations. A package with no
 * such file yields empty arrays and an `advisoryPatterns` entry saying the scan found no input —
 * never a silent empty list.
 */
function advisoryFor(pkgDirAbs, libFiles) {
  const scan = libFiles.filter((f) => f.rel.startsWith('lib/') || !f.rel.includes('/'));
  const jsScan = scan.filter((f) => f.rel.endsWith('.js') || f.rel.endsWith('.mjs'));
  const settingsKeys = new Set();
  const serviceNames = new Set();
  const toolNames = new Set();
  const symbols = new Set();
  const scanned = [];
  for (const f of jsScan.slice(0, 400)) {
    let src;
    try {
      src = readFileSync(join(pkgDirAbs, f.rel.split('/').join(sep)), 'utf8');
    } catch {
      continue;
    }
    scanned.push(f.rel);
    for (const k of extractConfigKeys(src)) settingsKeys.add(k);
    for (const s of extractInjectServices(src)) serviceNames.add(s);
    for (const t of extractToolNames(src)) toolNames.add(t);
    for (const y of extractSymbols(src)) symbols.add(y);
  }
  const advisoryPatterns = { ...PATTERNS };
  if (jsScan.length === 0) {
    advisoryPatterns.settingsKeys = 'not attempted: no lib/*.js or top-level *.js in this package';
    advisoryPatterns.serviceNames = advisoryPatterns.settingsKeys;
    advisoryPatterns.toolNames = advisoryPatterns.settingsKeys;
    advisoryPatterns.symbols = advisoryPatterns.settingsKeys;
  }
  return {
    settingsKeys: [...settingsKeys].sort(),
    serviceNames: [...serviceNames].sort(),
    toolNames: [...toolNames].sort(),
    symbols: [...symbols].sort(),
    advisoryPatterns,
    filesScanned: scanned.length,
  };
}

// ── file walk ────────────────────────────────────────────────────────────────────────────────
/**
 * Walk one package's own files, breadth-first over directories, skipping every nested
 * `node_modules/`. Returns `{ rel, abs, bytes }` for files only — no directory entries — with a
 * hard cap on how many are visited so a pathological package cannot run away.
 */
function walkPackageFiles(pkgDirAbs, cap) {
  const out = [];
  let truncated = false;
  const queue = [''];
  while (queue.length > 0) {
    const relDir = queue.shift();
    const absDir = relDir ? join(pkgDirAbs, relDir.split('/').join(sep)) : pkgDirAbs;
    let entries;
    try {
      entries = readdirSync(absDir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const rel = relDir ? `${relDir}/${entry.name}` : entry.name;
      if (entry.isSymbolicLink()) {
        // A symlink inside a package is described by its size, not followed: following it would
        // let a link to a directory escape the package and make this walk unbounded.
        let st;
        try { st = statSync(join(absDir, entry.name)); } catch { continue; }
        if (st.isDirectory()) continue;
        out.push({ rel, abs: join(absDir, entry.name), bytes: st.size });
      } else if (entry.isDirectory()) {
        if (entry.name === 'node_modules') continue; // nested installs are their own packages
        queue.push(rel);
      } else if (entry.isFile()) {
        let st;
        try { st = statSync(join(absDir, entry.name)); } catch { continue; }
        out.push({ rel, abs: join(absDir, entry.name), bytes: st.size });
      }
      if (out.length > cap) { truncated = true; break; }
    }
    if (truncated) break;
  }
  out.sort((a, b) => (a.rel < b.rel ? -1 : a.rel > b.rel ? 1 : 0));
  return { files: out, truncated };
}

// ── package description ──────────────────────────────────────────────────────────────────────
async function describePackage(name, scopeDirAbs, installRoot, opts) {
  const dirAbs = join(scopeDirAbs, name);
  const dir = toPosix(relative(installRoot, dirAbs));
  const notes = [];
  const pkg = {
    name,
    present: true,
    manifestReadable: false,
    version: null,
    dir,
    realDir: dir,
    symlinked: false,
    exportSubpaths: [],
    exportsRaw: null,
    exportsAbsent: true,
    main: null,
    module: null,
    bin: null,
    repository: null,
    dsh: {},
    dependencies: {},
    peerDependencies: {},
    files: {},
    filesTruncated: false,
    fileCount: 0,
    settingsKeys: [],
    serviceNames: [],
    toolNames: [],
    symbols: [],
    advisoryPatterns: {},
    provenance: {
      manifest: 'AUTHORITATIVE',
      exportSubpaths: 'AUTHORITATIVE',
      settingsKeys: 'ADVISORY',
      serviceNames: 'ADVISORY',
      toolNames: 'ADVISORY',
      symbols: 'ADVISORY',
    },
    notes,
  };

  // Symlinked package directory: record where it really points.
  try {
    const lst = lstatSync(dirAbs);
    if (lst.isSymbolicLink()) {
      const real = realpathSync(dirAbs);
      pkg.symlinked = true;
      pkg.realDir = toPosix(relative(installRoot, real));
      if (pkg.realDir.startsWith('..')) pkg.realDir = toPosix(real); // outside the root: absolute
      notes.push(`symlinked package directory; realpath = ${real}`);
      if (realpathSync(installRoot) !== installRoot && real.startsWith(realpathSync(installRoot))) {
        pkg.realDir = toPosix(relative(realpathSync(installRoot), real));
      }
    }
  } catch (e) {
    notes.push(`lstat failed: ${e.message}`);
  }

  const manifestPath = join(dirAbs, 'package.json');
  if (!existsSync(manifestPath)) {
    notes.push('no readable package.json: the directory exists but the manifest does not');
    pkg.manifestReadable = false;
  } else {
    try {
      const manifest = readJsonFile(manifestPath);
      pkg.manifestName = manifest.name ?? null;
      pkg.version = manifest.version ?? null;
      pkg.manifestReadable = true;
      if (!pkg.version) notes.push('package.json has no "version" field');
      if (manifest.name && manifest.name !== name) {
        notes.push(`manifest name "${manifest.name}" differs from directory name "${name}"`);
      }
      pkg.main = typeof manifest.main === 'string' ? manifest.main : null;
      pkg.module = typeof manifest.module === 'string' ? manifest.module : null;
      pkg.bin = manifest.bin ?? null;
      pkg.repository = repositoryStringOf(manifest);
      pkg.dsh = manifest.dsh ?? {};
      pkg.dependencies = manifest.dependencies ?? {};
      pkg.peerDependencies = manifest.peerDependencies ?? {};
      pkg.types = manifest.types ?? manifest.typings ?? null;

      const hasExports = Object.prototype.hasOwnProperty.call(manifest, 'exports')
        && manifest.exports !== undefined && manifest.exports !== null;
      pkg.exportsAbsent = !hasExports;
      pkg.exportsRaw = hasExports ? manifest.exports : null;
      const derived = exportSubpathsFrom(hasExports ? manifest.exports : undefined, manifest);
      pkg.exportSubpaths = derived.exportSubpaths;
      for (const n of derived.notes) notes.push(n);
    } catch (e) {
      pkg.manifestReadable = false;
      notes.push(`package.json is present but unreadable/unparseable: ${e.message}`);
      notes.push('exportSubpaths stays [] and version stays null on purpose: on a manifest that '
        + 'cannot be read they are UNKNOWN, and a guessed value here is exactly the confident-wrong '
        + 'reading this pipeline exists to prevent. The file list below is still read.');
    }
  }

  // Files: walk first, then hash with bounded concurrency.
  const walked = walkPackageFiles(dirAbs, opts.maxFilesPerPackage);
  pkg.filesTruncated = walked.truncated;
  const kept = walked.files.slice(0, opts.maxFilesPerPackage);
  if (walked.truncated) {
    notes.push(`filesTruncated: capped at --max-files-per-package=${opts.maxFilesPerPackage}; `
      + `${walked.files.length - kept.length} further entries were not recorded (sizes unknown)`);
  }
  pkg.fileCount = kept.length;

  const large = kept.filter((f) => f.bytes > HASH_SIZE_LIMIT_BYTES);
  const hashable = kept.filter((f) => f.bytes <= HASH_SIZE_LIMIT_BYTES);
  if (large.length > 0) {
    notes.push(`${large.length} file(s) over ${HASH_SIZE_LIMIT_BYTES} bytes were sized but NOT hashed `
      + `(sha256: null): ${large.slice(0, 5).map((f) => f.rel).join(', ')}`
      + `${large.length > 5 ? ', …' : ''}`);
  }

  const hashed = await mapLimit(hashable, HASH_CONCURRENCY, async (f) => {
    try {
      return await sha256File(f.abs);
    } catch (e) {
      notes.push(`could not hash ${f.rel}: ${e.message}`);
      return null;
    }
  });
  const hashByRel = new Map(hashable.map((f, i) => [f.rel, hashed[i]]));
  const files = {};
  for (const f of kept) {
    files[f.rel] = { bytes: f.bytes, sha256: hashByRel.get(f.rel) ?? null };
  }
  pkg.files = files;

  // Advisory extraction runs over the files we just walked, so its input set is the same one
  // recorded in `files` — no second, differently-scoped scan.
  const advisory = advisoryFor(dirAbs, kept);
  pkg.settingsKeys = advisory.settingsKeys;
  pkg.serviceNames = advisory.serviceNames;
  pkg.toolNames = advisory.toolNames;
  pkg.symbols = advisory.symbols;
  pkg.advisoryPatterns = advisory.advisoryPatterns;
  if (advisory.filesScanned === 0) {
    notes.push('advisory extraction scanned no JavaScript files, so all four advisory arrays are '
      + 'empty because nothing was read, not because nothing is there');
  } else {
    notes.push(`advisory extraction scanned ${advisory.filesScanned} JavaScript file(s)`);
  }
  return pkg;
}

// ── top-level `dsh` block ────────────────────────────────────────────────────────────────────
function describeDshPackage(pkg) {
  if (!pkg) {
    return {
      name: '@deepseek-ai/dsh',
      present: false,
      note: '@deepseek-ai/dsh is not installed under <installRoot>/node_modules',
    };
  }
  return {
    name: '@deepseek-ai/dsh',
    version: pkg.version,
    dir: pkg.dir,
    bin: pkg.bin,
    exports: pkg.exportsRaw,
    exportSubpaths: pkg.exportSubpaths,
    main: pkg.main,
    repository: pkg.repository,
    dsh: pkg.dsh,
    dependencies: pkg.dependencies,
    peerDependencies: pkg.peerDependencies,
    provenance: { manifest: 'AUTHORITATIVE', exportSubpaths: 'AUTHORITATIVE', dsh: 'AUTHORITATIVE' },
  };
}

/** The repository field of a real manifest, normalized to the string the spec shows. */
function repositoryStringOf(manifest) {
  const r = manifest?.repository;
  if (typeof r === 'string') return r;
  if (r && typeof r === 'object') return r.url ?? null;
  return null;
}

// ── main ─────────────────────────────────────────────────────────────────────────────────────
export function parseArgs(argv) {
  const args = { installRoot: null, out: null, maxFilesPerPackage: DEFAULT_MAX_FILES_PER_PACKAGE };
  const rest = [...argv];
  while (rest.length > 0) {
    const a = rest.shift();
    if (a === '--out') { args.out = rest.shift() ?? null; if (!args.out) throw new Error('--out needs a path'); }
    else if (a === '--max-files-per-package') {
      const n = Number(rest.shift());
      if (!Number.isInteger(n) || n <= 0) throw new Error('--max-files-per-package needs a positive integer');
      args.maxFilesPerPackage = n;
    } else if (a === '-h' || a === '--help') { args.help = true; }
    else if (a.startsWith('--')) throw new Error(`unknown option ${a}`);
    else if (args.installRoot === null) args.installRoot = a;
    else throw new Error(`unexpected extra argument ${a}`);
  }
  return args;
}

const USAGE = 'usage: node lib/contract.mjs <installRoot> [--out <path>] [--max-files-per-package N]';

export async function buildContract(installRoot, options = {}) {
  const opts = {
    maxFilesPerPackage: options.maxFilesPerPackage ?? DEFAULT_MAX_FILES_PER_PACKAGE,
  };
  const started = Date.now();
  const notes = [];

  const absRoot = resolve(installRoot);
  if (!existsSync(absRoot)) throw new Error(`installRoot does not exist: ${absRoot}`);
  if (!statSync(absRoot).isDirectory()) throw new Error(`installRoot is not a directory: ${absRoot}`);

  const scopeDirAbs = join(absRoot, SCOPE_DIR);
  if (!existsSync(scopeDirAbs)) {
    throw new Error(
      `no ${SCOPE_DIR.replace(/\\/g, '/')} under ${absRoot} — this is not an npm prefix containing `
      + 'the DSH scope. An empty packages map would be a refusal, not a contract, so this is fatal.',
    );
  }

  const names = readdirSync(scopeDirAbs, { withFileTypes: true })
    .filter((e) => e.isDirectory() || e.isSymbolicLink())
    .map((e) => e.name)
    .sort();
  notes.push(`enumerated ${names.length} entries under ${toPosix(relative(absRoot, scopeDirAbs))}`);

  const packages = {};
  for (const name of names) {
    // Sequential per package, bounded-concurrency within: the hash pool is the only I/O fan-out,
    // so memory stays flat no matter how many packages there are.
    // eslint-disable-next-line no-await-in-loop
    const pkg = await describePackage(name, scopeDirAbs, absRoot, opts);
    packages[`@deepseek-ai/${name}`] = pkg;
  }

  const present = Object.values(packages).filter((p) => p.manifestName !== undefined
    || p.version !== null || p.exportsRaw !== null);
  const manifestless = Object.entries(packages)
    .filter(([, p]) => p.version === null && p.exportsRaw === null)
    .map(([k]) => k);
  if (manifestless.length > 0) {
    notes.push(`${manifestless.length} package(s) exist but carry no readable manifest: `
      + `${manifestless.slice(0, 10).join(', ')}${manifestless.length > 10 ? ', …' : ''}`);
  }

  const symlinked = Object.entries(packages).filter(([, p]) => p.symlinked).map(([k]) => k);
  if (symlinked.length > 0) notes.push(`${symlinked.length} package(s) are symlinks: ${symlinked.join(', ')}`);

  const dshPkg = packages['@deepseek-ai/dsh'] ?? null;
  const dsh = describeDshPackage(dshPkg);
  if (dsh && dsh.dsh && Object.keys(dsh.dsh).length > 0 && !('configTrees' in dsh.dsh)) {
    notes.push('@deepseek-ai/dsh has a `dsh` block but no `configTrees` key');
  }

  const untruncated = Object.values(packages).filter((p) => !p.filesTruncated).length;
  notes.push(`file hashing: ${untruncated}/${Object.keys(packages).length} packages fully enumerated; `
    + `files over ${HASH_SIZE_LIMIT_BYTES} bytes recorded by size with sha256: null`);

  const elapsedMs = Date.now() - started;
  notes.push(`elapsedMs ${elapsedMs}`);

  const artifact = {
    schemaVersion: SCHEMA_VERSION,
    generatedAt: new Date().toISOString(),
    host: hostname(),
    installRoot: absRoot,
    dsh,
    packages: sortObject(packages),
    packageCount: Object.keys(packages).length,
    packagesWithManifest: present.length,
    elapsedMs,
    notes,
  };
  return artifact;
}

async function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (e) {
    process.stderr.write(`contract.mjs: ${e.message}\n${USAGE}\n`);
    process.exit(2);
    return;
  }
  if (args.help || !args.installRoot) {
    process.stderr.write(`${USAGE}\n`);
    process.exit(args.help ? 0 : 2);
    return;
  }
  let artifact;
  try {
    artifact = await buildContract(args.installRoot, { maxFilesPerPackage: args.maxFilesPerPackage });
  } catch (e) {
    process.stderr.write(`contract.mjs: ${e.message}\n`);
    process.exit(1);
    return;
  }
  const text = `${JSON.stringify(artifact, null, 2)}\n`;
  if (args.out) {
    const outAbs = isAbsolute(args.out) ? args.out : resolve(process.cwd(), args.out);
    mkdirSync(dirname(outAbs), { recursive: true });
    writeFileSync(outAbs, text, 'utf8');
    process.stderr.write(`contract.mjs: wrote ${outAbs} `
      + `(${artifact.packageCount} packages, ${artifact.elapsedMs} ms)\n`);
  } else {
    process.stdout.write(text);
  }
  process.exit(0);
}

const invokedDirectly = Boolean(process.argv[1])
  && import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedDirectly) {
  main().catch((e) => {
    process.stderr.write(`contract.mjs: unexpected failure: ${e?.stack ?? e}\n`);
    process.exit(1);
  });
}
