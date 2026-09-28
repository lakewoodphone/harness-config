#!/usr/bin/env node
/**
 * consumed.mjs — describe what THIS DEPLOYMENT depends on, for the dsh-update pipeline.
 *
 * WHAT THIS IS
 * ------------
 * `dsh-update` compares a candidate DSH install (contract.json) against what we actually name,
 * and reports the differences that matter. This module produces the second half of that
 * comparison: `consumed.json` — an exhaustive, line-accurate inventory of every upstream artifact
 * this deployment names by exact string.
 *
 * The pipeline's whole risk is SILENT loss: a renamed cordis service, a deleted export subpath, a
 * patch that stops matching a row id, or a settings key the engine no longer accepts all fail
 * without an error. None of them can be detected unless we first know exactly what we named. So
 * completeness beats elegance here, and every entry carries the real file and line that produced
 * it — synthesized locations would make the finding unfalsifiable.
 *
 * WHAT IT IS NOT
 * --------------
 * It is not a description of the installed tree (that is `contract.mjs`) and it is not a diff.
 * It only ever reads files. It never runs `dsh`, never touches a running engine, never writes
 * outside `dsh-update/` and the path given to `--out`, and never deletes anything.
 *
 * USAGE
 *   node lib/consumed.mjs [--root <harnessConfigRoot>] [--dsh-home <path>] [--out <path>]
 * Prints consumed.json on stdout and exits 0. On failure: a diagnostic on stderr, non-zero exit.
 *
 * PROVENANCE / HONESTY RULES APPLIED HERE
 *   * Every `file`/`line` is read from the file; nothing is inferred or interpolated.
 *   * A file that cannot be parsed is recorded in `notes` and the scan continues — one unparsable
 *     file must never zero the inventory.
 *   * Every gap that is a real gap is written into `notes`. An empty `notes` with missing data
 *     would be a lie; a populated `notes` is the honest artifact.
 */
import { readdirSync, readFileSync, statSync, existsSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve, relative, sep, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

// ── arguments ────────────────────────────────────────────────────────────────────────────────
function parseArgs(list) {
  const out = { root: null, dshHome: null, out: null, problems: [] };
  for (let i = 0; i < list.length; i++) {
    const a = list[i];
    const eq = a.indexOf('=');
    const key = eq >= 0 ? a.slice(0, eq) : a;
    const inline = eq >= 0 ? a.slice(eq + 1) : null;
    const take = () => (inline !== null ? inline : (list[++i] ?? null));
    if (key === '--root') out.root = take();
    else if (key === '--dsh-home' || key === '--dshHome') out.dshHome = take();
    else if (key === '--out') out.out = take();
    else if (key === '--help' || key === '-h') { out.help = true; }
    else out.problems.push(`unrecognized argument: ${a}`);
  }
  return out;
}

const ARGS = parseArgs(process.argv.slice(2));
if (ARGS.help) {
  process.stdout.write(
    'usage: node lib/consumed.mjs [--root <harnessConfigRoot>] [--dsh-home <path>] [--out <path>]\n'
    + 'prints consumed.json on stdout\n',
  );
  process.exit(0);
}

/**
 * Default `--root` is the harness-config checkout that OWNS this module (`<root>/dsh-update/lib`),
 * which makes a standalone run correct on any machine; the spec's absolute path is the fallback.
 */
const CONFIG_ROOT = resolve(ARGS.root ?? process.env.DSH_CONFIG_ROOT ?? join(HERE, '..', '..'));
const DSH_HOME = resolve(
  ARGS.dshHome ?? process.env.DSH_HOME ?? join(process.env.USERPROFILE ?? process.env.HOME ?? '', '.dsh'),
);
const OUT_PATH = ARGS.out ? resolve(ARGS.out) : null;

/** Accumulated, de-duplicated limitations. Populated only by things that actually happened. */
const NOTES = [];
const noteSet = new Set();
function note(msg) {
  if (noteSet.has(msg)) return;
  noteSet.add(msg);
  NOTES.push(msg);
}
for (const p of ARGS.problems) note(p);

// ── YAML ─────────────────────────────────────────────────────────────────────────────────────
/**
 * A usable `yaml` implementation is resolved two ways, in order:
 *   1. `./yaml.mjs` beside this file, if another agent has landed it (it is a peer module in this
 *      pipeline, not a dependency of this one);
 *   2. this module's own copy of the probing approach from `scripts/merge-settings.mjs`, for when
 *      that file is absent — a bare `require('yaml')` is unsafe because the name can resolve to a
 *      different package that has no `parse` (measured 2026-09-14, merge-settings.mjs:35-37).
 * Either way the `!!js` tag matters: composition rows here carry `!!js <expression>`, and a plain
 * `YAML.parse` resolves them to `undefined` while emitting `TAG_RESOLVE_FAILED` per scalar. The
 * wrapper keeps the source text, so a value that matters is provably NOT silently lost.
 */
const JS_TAG_URI = 'tag:yaml.org,2002:js';
const jsTag = {
  tag: JS_TAG_URI,
  resolve: (v) => ({ __js: v }),
  identify: (v) => Boolean(v) && typeof v === 'object' && typeof v.__js === 'string',
  stringify: (item) => item.__js,
};
const isJs = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v)
  && typeof v.__js === 'string' && Object.keys(v).length === 1;

function loadYamlInline() {
  const candidates = [];
  const push = (p) => { if (p) candidates.push(p); };
  if (process.env.DSH_INSTALL) push(join(process.env.DSH_INSTALL, 'node_modules'));
  if (process.env.DSH_HOME) {
    push(join(process.env.DSH_HOME, 'profiles', 'web', 'node_modules'));
    push(join(process.env.DSH_HOME, 'profiles', 'node_modules'));
  }
  for (const rel of ['node_modules', '../node_modules', '../../node_modules']) push(join(process.cwd(), rel));
  const locals = [process.env.LOCALAPPDATA];
  if (process.env.USERPROFILE) locals.push(join(process.env.USERPROFILE, 'AppData', 'Local'));
  for (const local of locals) {
    if (!local) continue;
    const npx = join(local, 'npm-cache', '_npx');
    if (!existsSync(npx)) continue;
    try { for (const d of readdirSync(npx)) push(join(npx, d, 'node_modules')); } catch { /* unreadable depth is not fatal */ }
  }
  const seen = new Set();
  const problems = [];
  for (const base of candidates) {
    if (!base || seen.has(base)) continue;
    seen.add(base);
    if (!existsSync(join(base, 'yaml', 'package.json'))) continue;
    try {
      const req = createRequire(join(base, 'noop.js'));
      const mod = req('yaml');
      const impl = mod?.default ?? mod;
      if (typeof impl?.parse === 'function' && typeof impl?.stringify === 'function') return impl;
      problems.push(`${base} -> yaml has no parse/stringify`);
    } catch (e) { problems.push(`${base} -> ${e.message}`); }
  }
  throw new Error(`cannot resolve a usable "yaml" package. Tried: ${[...seen].join(', ')}`
    + (problems.length ? ` | rejected: ${problems.join('; ')}` : ''));
}

let YAML_IMPL = null;
{
  let peer = null;
  try {
    peer = await import(new URL('./yaml.mjs', import.meta.url).href);
  } catch (e) {
    note(`lib/yaml.mjs is not importable (${e.message}); this module used its own copy of the `
      + 'merge-settings.mjs loadYaml() probing approach instead');
  }
  if (peer && typeof peer.YAML?.parse === 'function') {
    YAML_IMPL = peer.YAML;
  } else {
    if (peer) note('lib/yaml.mjs exists but exports no usable YAML implementation; used the inline probing copy');
    try {
      YAML_IMPL = loadYamlInline();
    } catch (e) {
      note(`no usable "yaml" implementation found (${e.message}) — composition/settings files were `
        + 'scanned line-by-line only, so YAML structure was not independently validated');
    }
  }
}

/** Parse with the `!!js` tag preserved and warnings captured, never thrown. */
function parseYamlSafe(text) {
  if (!YAML_IMPL) return { value: null, warnings: ['no yaml implementation'], error: null };
  const warnings = [];
  try {
    const doc = YAML_IMPL.parseDocument(text, {
      customTags: [jsTag],
      onWarning: (w) => warnings.push(String(w?.message ?? w)),
    });
    const errors = (doc?.errors ?? []).map((e) => String(e?.message ?? e));
    if (errors.length) return { value: null, warnings, error: errors.join(' | ') };
    return { value: doc.toJS(), warnings, error: null };
  } catch (e) {
    return { value: null, warnings, error: e.message };
  }
}

// ── file walking ─────────────────────────────────────────────────────────────────────────────
const SKIP_DIRS = new Set([
  'node_modules', '.git', '__pycache__', '.pytest_cache', '_scratch', '.dsh-module-fallback',
  'dist', 'build', '.venv', 'venv', '.mypy_cache', '.ruff_cache',
]);
const SKIP_FRAGMENTS = [
  '/journal/entries/', '/dsh-update/state/', '/dsh-update/vendor/', '/_dsh-tmp/',
];
const SKIP_FILE = [/\.bak-/, /\.pre-sync$/, /\.zabz-bak$/, /\.orig$/, /\.rej$/];

const WALK_CAP = 20000;
const walkState = { files: 0, truncated: false };

const fwd = (p) => p.split(sep).join('/');

function walkDir(absDir, exts, acc) {
  if (walkState.truncated) return;
  let entries;
  try { entries = readdirSync(absDir, { withFileTypes: true }); } catch { return; }
  entries.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  for (const e of entries) {
    if (walkState.truncated) return;
    const abs = join(absDir, e.name);
    const afwd = fwd(abs);
    if (e.isDirectory()) {
      if (SKIP_DIRS.has(e.name)) continue;
      if (SKIP_FRAGMENTS.some((f) => afwd.includes(f))) continue;
      walkDir(abs, exts, acc);
    } else if (e.isFile()) {
      if (walkState.files >= WALK_CAP) {
        walkState.truncated = true;
        note(`the file walk hit its hard cap of ${WALK_CAP} files, so the inventory beyond that `
          + `point is INCOMPLETE. This is a limitation of the module's own walk, not of the input.`);
        return;
      }
      if (SKIP_FRAGMENTS.some((f) => afwd.includes(f))) continue;
      if (SKIP_FILE.some((re) => re.test(e.name))) continue;
      if (exts && !exts.includes(extOf(e.name))) continue;
      walkState.files++;
      acc.add(abs);
    }
  }
}

function extOf(name) {
  const i = name.lastIndexOf('.');
  return i < 0 ? '' : name.slice(i).toLowerCase();
}

function within(parent, child) {
  const p = resolve(parent).toLowerCase();
  const c = resolve(child).toLowerCase();
  return c === p || c.startsWith(p + sep.toLowerCase());
}

/** The path recorded in an entry: relative to `--root` when it lives there, absolute otherwise. */
function fileFor(abs) {
  if (within(CONFIG_ROOT, abs)) return fwd(relative(CONFIG_ROOT, abs));
  return abs;
}

const COLLECTED = new Set();
{
  const yml = ['.yml', '.yaml'];
  const roots = [
    [join(CONFIG_ROOT, 'presets'), yml],
    [join(CONFIG_ROOT, 'profiles'), ['.yml', '.yaml', '.json']],
    [join(CONFIG_ROOT, 'settings'), yml],
    [join(CONFIG_ROOT, 'packages'), ['.js', '.mjs', '.cjs', '.json', '.yml', '.yaml', '.sh', '.ps1', '.py']],
    [join(CONFIG_ROOT, 'scripts'), ['.mjs', '.js', '.py', '.ps1', '.sh']],
    [join(CONFIG_ROOT, 'multi-window'), null],
    [join(DSH_HOME, '.agent-presets'), ['.yml', '.yaml', '.js', '.mjs', '.json']],
  ];
  for (const [abs, exts] of roots) if (existsSync(abs)) walkDir(abs, exts, COLLECTED);

  // The LIVE profile files. Exactly these three names per profile, by name — the .bak-* copies
  // beside them are history, not configuration, and pnpm-lock.yaml is not read.
  const profilesDir = join(DSH_HOME, 'profiles');
  if (existsSync(profilesDir)) {
    let subs = [];
    try { subs = readdirSync(profilesDir, { withFileTypes: true }).filter((e) => e.isDirectory()); } catch { /* unreadable */ }
    for (const s of subs) {
      for (const name of ['package.json', 'cordis.yml', 'cordis.patch.yml']) {
        const abs = join(profilesDir, s.name, name);
        if (existsSync(abs) && statSync(abs).isFile()) COLLECTED.add(abs);
      }
    }
  } else {
    note(`the live profile directory ${profilesDir} does not exist, so the live profile's own `
      + 'bundles, composition rows and patch targets are NOT in this inventory (input-data gap)');
  }

  const liveSettings = join(DSH_HOME, 'settings.yaml');
  if (existsSync(liveSettings)) COLLECTED.add(liveSettings);
  else note(`the merged live settings document ${liveSettings} does not exist, so the settings the `
    + 'engine actually reads are NOT in this inventory (input-data gap)');
}

// ── line access ──────────────────────────────────────────────────────────────────────────────
const LINE_CACHE = new Map();
function linesOf(abs) {
  if (LINE_CACHE.has(abs)) return LINE_CACHE.get(abs);
  let value;
  try { value = readFileSync(abs, 'utf8').split(/\r?\n/); } catch (e) {
    note(`could not read ${fileFor(abs)}: ${e.message} — its references are missing from this inventory (code limitation)`);
    value = [];
  }
  LINE_CACHE.set(abs, value);
  return value;
}

/**
 * Remove a trailing comment from a line without touching quoted strings, so a `#` inside a quoted
 * scalar survives and a documented example inside a comment does not become a reference.
 * PowerShell/shell/Python/YAML use `#`; JS/TS uses `//`.
 */
function stripComment(line, ext) {
  const js = ext === '.js' || ext === '.mjs' || ext === '.cjs';
  let inS = false, inD = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inS) { if (c === "'") { if (line[i + 1] === "'" && ext !== '.py') { i++; continue; } inS = false; } continue; }
    if (inD) { if (c === '\\' && ext !== '.ps1') { i++; continue; } if (c === '"') inD = false; continue; }
    if (c === "'") { inS = true; continue; }
    if (c === '"') { inD = true; continue; }
    if (c === '#' && ext !== '.py') return line.slice(0, i);
    if (c === '#' && ext === '.py') return line.slice(0, i);
    if (js && c === '/' && line[i + 1] === '/') return line.slice(0, i);
  }
  return line;
}

/** A `-` prefix at the same indent as a sequence item, and the item's inline `key: value`. */
const SEQ_ITEM = /^(\s*)-\s+(\S.*)$/;
const MAP_KEY = /^(\s*)([A-Za-z_][\w.-]*)\s*:\s*(.*)$/;
const BLOCK_SCALAR = /^(\s*)(?:-\s+)?[A-Za-z_][\w.-]*\s*:\s*[|>][-+]?\d*\s*$/;

/**
 * Blank out block comments and docstrings before anything else. Without this, prose in a
 * `<# … #>` help block or a `/** … *\/` doc comment ("prove it with: dsh --profile web
 * --dump-config") reads exactly like an invocation. Content is replaced with spaces so column
 * positions and indentation are unchanged.
 */
function maskBlocks(line, st, ext) {
  const js = ext === '.js' || ext === '.mjs' || ext === '.cjs';
  const ps = ext === '.ps1';
  const py = ext === '.py';
  let out = '';
  let i = 0;
  while (i < line.length) {
    if (st.delim) {
      const end = line.indexOf(st.delim, i);
      if (end < 0) { out += ' '.repeat(line.length - i); i = line.length; continue; }
      out += ' '.repeat(end + st.delim.length - i);
      i = end + st.delim.length;
      st.delim = null;
      continue;
    }
    if (js && line.startsWith('/*', i)) { st.delim = '*/'; out += '  '; i += 2; continue; }
    if (ps && line.startsWith('<#', i)) { st.delim = '#>'; out += '  '; i += 2; continue; }
    if (py && (line.startsWith('"""', i) || line.startsWith("'''", i))) {
      st.delim = line.slice(i, i + 3); out += '   '; i += 3; continue;
    }
    out += line[i];
    i++;
  }
  return out;
}

/**
 * The code view of a file: per line, the comment-stripped text, its indent, and whether the line
 * is inside a block scalar (block-scalar content is prose — the personas here are thousands of
 * words of it — and must never be read as YAML keys).
 */
function codeView(abs) {
  const raw = linesOf(abs);
  const ext = extOf(abs);
  const out = [];
  const block = { delim: null };
  let blockIndent = -1;
  for (let i = 0; i < raw.length; i++) {
    const line = raw[i];
    const masked = maskBlocks(line, block, ext);
    const code = stripComment(masked, ext).replace(/[ \t]+$/, '');
    const indent = code.length ? code.match(/^\s*/)[0].length : line.match(/^\s*/)[0].length;
    if (blockIndent >= 0) {
      if (code.trim() === '' || indent > blockIndent) {
        out.push({ n: i + 1, indent, code: '', raw: line, inBlock: true });
        continue;
      }
      blockIndent = -1;
    }
    out.push({ n: i + 1, indent, code, raw: line, inBlock: false });
    if (BLOCK_SCALAR.test(code)) blockIndent = code.match(/^\s*/)[0].length;
  }
  return out;
}

function unquote(v) {
  let t = v.trim();
  const tail = /,\s*$/.exec(t);
  if (tail) t = t.slice(0, tail.index).trim();
  if ((t.startsWith("'") && t.endsWith("'") && t.length >= 2)) return t.slice(1, -1).replace(/''/g, "'");
  if ((t.startsWith('"') && t.endsWith('"') && t.length >= 2)) return t.slice(1, -1).replace(/\\"/g, '"');
  return t;
}

// ── roles ────────────────────────────────────────────────────────────────────────────────────
function roleOf(abs) {
  const af = fwd(abs);
  const base = af.slice(af.lastIndexOf('/') + 1);
  const inDsh = within(DSH_HOME, abs);
  if (/\/\.agent-presets\//.test(af) || /\/presets\//.test(af)) return 'preset';
  if (/\/profiles\//.test(af)) {
    if (base === 'cordis.patch.yml') return inDsh ? 'host-patch' : 'profile-patch';
    if (base === 'cordis.yml') return inDsh ? 'host-composition' : 'profile-composition';
    if (base === 'package.json') return 'profile-manifest';
    return 'profile-other';
  }
  if (/\/packages\//.test(af)) return base === 'cordis.patch.yml' ? 'bundle-patch' : 'package-source';
  if (/\/settings\//.test(af) || base === 'settings.yaml') return 'settings';
  if (/\/scripts\//.test(af)) return 'script';
  if (/\/multi-window\//.test(af)) return 'launcher';
  return 'other';
}

const COMPOSITION_ROLES = new Set([
  'preset', 'host-patch', 'profile-patch', 'host-composition', 'profile-composition', 'bundle-patch',
]);
const WHERE_OF = {
  preset: 'preset',
  'host-patch': 'host-patch',
  'host-composition': 'host-patch',
  'profile-patch': 'profile',
  'profile-composition': 'profile',
  'bundle-patch': 'profile',
};

// ── output accumulators ──────────────────────────────────────────────────────────────────────
const profileBundles = [];
const packageRefs = [];
const rowIds = [];
const isolateServices = [];
const settingsKeys = [];
const cliInvocations = [];
const pluginImports = [];
const patchRowTargets = [];

const seenEntry = new Set();
function pushOnce(bucket, key, obj) {
  if (seenEntry.has(key)) return;
  seenEntry.add(key);
  bucket.push(obj);
}

// ── package references ───────────────────────────────────────────────────────────────────────
// Both separators: `@deepseek-ai/dsh` in a POSIX path and `@deepseek-ai\dsh` in a Windows one.
const UPSTREAM_RE = /@deepseek-ai[\\/]([a-z0-9][a-z0-9.-]*)/g;
const OWN_RE = /(^|[^A-Za-z0-9_-])(dsh-plugin-[a-z0-9]+(?:-[a-z0-9]+)*)/g;
const PATH_SEGMENTS = new Set(['lib', 'src', 'dist', 'bin', 'node_modules', 'docs', 'test', 'tests']);

/** Split `pkg/subpath` into a package name and an EXPORT subpath (a path is not an export). */
function splitSubpath(afterName) {
  if (!afterName || (afterName[0] !== '/' && afterName[0] !== '\\')) return { subpath: '.' };
  const m = /^[\\/]([A-Za-z0-9._-]+)/.exec(afterName);
  if (!m) return { subpath: '.' };
  const seg = m[1];
  const deeper = afterName[m[0].length] === '/' || afterName[m[0].length] === '\\';
  if (deeper || seg.includes('.') || PATH_SEGMENTS.has(seg)) return { subpath: '.' };
  return { subpath: `/${seg}` };
}

/** Split one raw string (`@deepseek-ai/dsh-x/sub`, `dsh-plugin-y/sub`) into name and subpath. */
function refName(raw) {
  const um = /@deepseek-ai[\\/]([a-z0-9][a-z0-9.-]*)/.exec(raw);
  if (um) {
    return {
      name: `@deepseek-ai/${um[1]}`,
      subpath: splitSubpath(raw.slice(um.index + um[0].length)).subpath,
    };
  }
  const om = /(?:^|[^A-Za-z0-9_-])(dsh-plugin-[a-z0-9]+(?:-[a-z0-9]+)*)/.exec(raw);
  if (om) {
    return {
      name: om[1],
      subpath: splitSubpath(raw.slice(om.index + om[0].length)).subpath,
    };
  }
  return null;
}

function kindForRef(abs, role, lineText) {
  if (role === 'preset') return 'preset-row';
  if (role === 'host-patch' || role === 'profile-patch' || role === 'bundle-patch') return 'profile-row';
  if (role === 'host-composition' || role === 'profile-composition' || role === 'profile-other') return 'profile-row';
  if (role === 'profile-manifest') return 'profile-bundle';
  if (role === 'settings') return 'settings';
  if (role === 'script' || role === 'launcher') return 'script';
  if (role === 'package-source') {
    return /\b(?:import|require)\b/.test(lineText) ? 'plugin-import' : 'other';
  }
  return 'other';
}

function harvestPackageRefs(abs, role) {
  const file = fileFor(abs);
  const view = codeView(abs);
  for (const ln of view) {
    if (!ln.code) continue;
    UPSTREAM_RE.lastIndex = 0;
    let m;
    while ((m = UPSTREAM_RE.exec(ln.code))) {
      const name = `@deepseek-ai/${m[1]}`;
      const after = ln.code.slice(m.index + m[0].length);
      // A `@deepseek-ai/x.y` version-ish or a longer path segment is not a subpath export.
      const { subpath } = splitSubpath(after);
      const kind = kindForRef(abs, role, ln.code);
      pushOnce(packageRefs, `${file}:${ln.n}:${name}:${subpath}:${kind}`, {
        name, subpath, kind, file, line: ln.n,
      });
    }
    OWN_RE.lastIndex = 0;
    while ((m = OWN_RE.exec(ln.code))) {
      const name = m[2];
      const after = ln.code.slice(m.index + m[0].length);
      const { subpath } = splitSubpath(after);
      pushOnce(packageRefs, `${file}:${ln.n}:${name}:${subpath}:own-plugin`, {
        name, subpath, kind: 'own-plugin', file, line: ln.n,
      });
    }
  }
}

// ── composition files: row ids, names, isolate services, patch targets ───────────────────────
const ID_RE = /^(\s*)(?:-\s+)?id\s*:\s*(.+?)\s*$/;
const NAME_RE = /^(\s*)(?:-\s+)?name\s*:\s*(.+?)\s*$/;
const ISOLATE_RE = /^(\s*)isolate\s*:\s*(.*?)\s*$/;

function scanComposition(abs, role, where) {
  const file = fileFor(abs);
  const view = codeView(abs);
  const firstCode = view.find((l) => l.code.trim() !== '');
  const flow = Boolean(firstCode) && /^[\s]*[[{]/.test(firstCode.code);

  const record = (id, line, isTarget) => {
    pushOnce(rowIds, `row:${file}:${line}:${id}:${where}`, { id, file, line, where });
    if (isTarget) {
      const layer = role === 'host-patch' || role === 'host-composition' ? 'host' : 'profile';
      pushOnce(patchRowTargets, `patch:${file}:${line}:${id}:${layer}`, { id, file, line, layer });
    }
  };

  if (flow) {
    // A `[...]` flow document (profiles/*/cordis.patch.yml is exactly this). Flow entries are all
    // top-level, so every `id:` is an id-targeted patch entry; an `insert:` inside a flow document
    // would need richer handling and is reported rather than guessed at.
    const hasInsert = view.some((l) => /\binsert\s*:/.test(l.code));
    if (hasInsert) {
      note(`${file} is a flow-style YAML document that also contains an "insert:" — inserted rows `
        + 'are being counted as patch targets there, because a flow mapping gives no reliable block '
        + 'context to distinguish them (code limitation)');
    }
    const patchLayer = role === 'host-patch' || role === 'host-composition';
    for (const ln of view) {
      if (!ln.code) continue;
      for (const m of ln.code.matchAll(/(^|[\s,{])id\s*:\s*('([^']*)'|"([^"]*)"|([^,}\s]+))/g)) {
        const id = unquote(m[2]);
        if (!id) continue;
        const isTarget = patchLayer || role === 'profile-patch';
        record(id, ln.n, isTarget);
      }
      for (const m of ln.code.matchAll(/(^|[\s,{])name\s*:\s*('([^']*)'|"([^"]*)"|([^,}\s]+))/g)) {
        const nmv = unquote(m[2]);
        const ref = nmv ? refName(nmv) : null;
        if (!ref) continue;
        const kind = ref.name.startsWith('dsh-plugin-') ? 'own-plugin' : kindForRef(abs, role, ln.code);
        pushOnce(packageRefs, `${file}:${ln.n}:${ref.name}:${ref.subpath}:${kind}`, {
          name: ref.name, subpath: ref.subpath, kind, file, line: ln.n,
        });
      }
      for (const m of ln.code.matchAll(/isolate\s*:\s*\{([^}]*)\}/g)) {
        for (const part of m[1].split(',')) {
          const km = /^\s*([A-Za-z_][\w-]*)\s*:/.exec(part);
          if (km) pushOnce(isolateServices, `iso:${file}:${ln.n}:${km[1]}`, { service: km[1], file, line: ln.n });
        }
      }
    }
    return;
  }

  // Block style. `insert:` opens a nested sequence of rows that are ADDED, not targeted: an
  // inserted row is not a patch target (nothing can "stop applying" to a row we bring ourselves),
  // so those ids go to rowIds only. Every other entry carrying a top-level `id:` is a target.
  const insertRanges = [];
  for (const ln of view) {
    const im = /^(\s*)(?:-\s+)?insert\s*:\s*(.*?)\s*$/.exec(ln.code);
    if (im) insertRanges.push({ start: ln.n, indent: im[1].length });
  }
  const insideInsert = (lineNo, indent) => insertRanges.some((r) => lineNo > r.start && indent > r.indent);

  // `isolate:` blocks: every mapping key deeper than the `isolate:` line, down to the next dedent,
  // names a cordis SERVICE. Those keys are not row ids, and a row id is not a service key.
  const isolateBlocks = [];
  for (const ln of view) {
    const im = ISOLATE_RE.exec(ln.code);
    if (!im) continue;
    const indent = im[1].length;
    let end = view.length + 1;
    for (const other of view) {
      if (other.n <= ln.n) continue;
      if (other.inBlock || !other.code.trim()) continue;
      if (other.indent <= indent) { end = other.n; break; }
    }
    isolateBlocks.push({ start: ln.n, indent, end, inline: im[2] });
  }
  const isolateOwnerOf = (lineNo, indent) => isolateBlocks.find((b) => lineNo > b.start && lineNo < b.end && indent > b.indent) ?? null;

  for (const ln of view) {
    if (ln.inBlock || !ln.code.trim()) continue;
    const inIsolate = isolateOwnerOf(ln.n, ln.indent);
    if (inIsolate) {
      const km = /^(\s*)(?:(?:^|\s)-\s+)?([A-Za-z_][\w-]*)\s*:\s*(.*?)\s*$/.exec(ln.code);
      if (km && km[2] !== 'id') {
        pushOnce(isolateServices, `iso:${file}:${ln.n}:${km[2]}`, { service: km[2], file, line: ln.n });
        continue;
      }
    }
    const idm = ID_RE.exec(ln.code);
    if (idm) {
      const id = unquote(idm[2]);
      if (id) {
        const nested = insideInsert(ln.n, idm[1].length);
        const isTarget = !nested && (role === 'host-patch' || role === 'profile-patch');
        record(id, ln.n, isTarget);
      }
    }
    const nm = NAME_RE.exec(ln.code);
    if (nm) {
      const ref = refName(unquote(nm[2]));
      if (ref) {
        const kind = ref.name.startsWith('dsh-plugin-') ? 'own-plugin' : kindForRef(abs, role, ln.code);
        pushOnce(packageRefs, `${file}:${ln.n}:${ref.name}:${ref.subpath}:${kind}`, {
          name: ref.name, subpath: ref.subpath, kind, file, line: ln.n,
        });
      }
    }
    if (inIsolate && inIsolate.inline) {
      for (const part of inIsolate.inline.replace(/^\{|\}$/g, '').split(',')) {
        const km = /^\s*([A-Za-z_][\w-]*)\s*:/.exec(part);
        if (km) pushOnce(isolateServices, `iso:${file}:${ln.n}:${km[1]}`, { service: km[1], file, line: ln.n });
      }
    }
  }
}

// ── profile manifests (profileBundles) ───────────────────────────────────────────────────────
function scanProfileManifest(abs) {
  const file = fileFor(abs);
  const raw = linesOf(abs);
  const text = raw.join('\n');
  let doc;
  try { doc = JSON.parse(text); } catch (e) {
    note(`${file} could not be parsed as JSON (${e.message}) — its dsh.profile.bundles entries are `
      + 'MISSING from this inventory (input-data gap; the file is malformed)');
    return;
  }
  const bundles = doc?.dsh?.profile?.bundles;
  if (!Array.isArray(bundles)) return;
  for (const b of bundles) {
    if (typeof b !== 'string') continue;
    const line = raw.findIndex((l) => l.includes(`"${b}"`)) + 1;
    pushOnce(profileBundles, `bundle:${file}:${line}:${b}`, { name: b, source: 'profile', file, line });
  }
}

// ── settings keys ────────────────────────────────────────────────────────────────────────────
function parseScalar(v) {
  const t = v.trim();
  if (t === '') return undefined;
  if (/^[|>]/.test(t)) return undefined;
  if (/^[[{]/.test(t)) return undefined;
  const tail = /\s+#.*$/.exec(t);
  const s = tail ? t.slice(0, tail.index).trim() : t;
  if (/^".*"$/.test(s)) return s.slice(1, -1);
  if (/^'.*'$/.test(s)) return s.slice(1, -1).replace(/''/g, "'");
  if (/^-?\d+$/.test(s)) return Number(s);
  if (/^-?\d*\.\d+$/.test(s)) return Number(s);
  if (/^(?:true|false)$/i.test(s)) return s.toLowerCase() === 'true';
  if (/^(?:null|~)$/i.test(s)) return null;
  return s;
}

function scanSettings(abs) {
  const file = fileFor(abs);
  const view = codeView(abs);
  const stack = [];
  const path = () => stack.map((f) => (f.isArrayOwner ? `${f.seg}[]` : f.seg)).filter(Boolean).join('.');
  for (const ln of view) {
    if (ln.inBlock || !ln.code.trim()) continue;
    const seq = SEQ_ITEM.exec(ln.code);
    if (seq) {
      // A sequence item. Its own keys sit at `indent + 2` when the `-` is at the parent key's
      // indent (the style merge-settings.mjs emits) and at `indent + 2` when it is nested too —
      // so the item's mapping indent is always `-` column + 2.
      const dashIndent = ln.indent;
      const inline = MAP_KEY.exec(seq[2]);
      // The owner of this sequence is whichever KEY frame encloses the `-`: either at the same
      // indent (`models:` then `- id:` at the same column) or shallower (nested items).
      while (stack.length && stack[stack.length - 1].indent > dashIndent) stack.pop();
      if (stack.length) stack[stack.length - 1].isArrayOwner = true;
      if (!inline) continue; // a scalar item is a value, not a settings key
      while (stack.length && stack[stack.length - 1].indent >= dashIndent + 2) stack.pop();
      stack.push({ indent: dashIndent + 2, seg: inline[2], isArrayOwner: false });
      const value = parseScalar(inline[3]);
      if (value === undefined) continue;
      pushOnce(settingsKeys, `set:${file}:${ln.n}:${path()}`, { key: path(), value, file, line: ln.n });
      continue;
    }
    const map = MAP_KEY.exec(ln.code);
    if (!map) continue;
    const indent = ln.indent;
    while (stack.length && stack[stack.length - 1].indent >= indent) stack.pop();
    stack.push({ indent, seg: map[2], isArrayOwner: false });
    const value = parseScalar(map[3]);
    if (value === undefined) continue;
    pushOnce(settingsKeys, `set:${file}:${ln.n}:${path()}`, { key: path(), value, file, line: ln.n });
  }
}

// ── CLI invocations ──────────────────────────────────────────────────────────────────────────
const MATCHER_LINE = /\b(?:pgrep|pkill|findstr|Where-Object|Select-String|Get-CimInstance|assert)\b|\[regex\]|(?:-like|-match)\s|CommandLine\s/;
const BARE_TOKEN_OK = /^[-A-Za-z0-9_./\\:@=+*%]+$/;
const FLAG_OK = /^--?[A-Za-z][A-Za-z0-9-]*$/;
const WORD_TOKEN = /^[a-z][a-z0-9-]*$/;
const REDIRECT = /^(?:\d+|&)?[<>]|^\d+&?\d*$/;
const LAUNCHER_PROGRAM = /^(?:npx|node|node\.exe|sudo|env|run|call|exec|cmd|ssh|pwsh|powershell|bash|sh|zsh|Start-Process)$/;

/**
 * Is `at` a position where a COMMAND can start? This is the difference between
 * `/usr/local/bin/dsh --version` (a command) and `test -f /usr/local/bin/dsh` (a path argument),
 * both of which contain the same token.
 */
function commandStart(text, at) {
  const trimmed = text.slice(0, at).replace(/[ \t]+$/, '');
  if (trimmed === '') return true;
  const prevChar = trimmed[trimmed.length - 1];
  if (/[;&|(=+:$`@'"]/.test(prevChar)) return true;
  const word = /([^\s;&|()]+)$/.exec(trimmed);
  if (!word) return false;
  const w = word[1];
  if (w.includes('=')) return true; // `PATH=…`-style prefix, as `env -i PATH=… dsh …` uses
  return LAUNCHER_PROGRAM.test(w);
}

/** Skip a `$( … )` / `${ … }` / `$name` interpolation as one opaque token. */
function skipExpr(text, i) {
  if (text[i] !== '$') return i;
  const open = text[i + 1];
  if (open === '$' || open === undefined) return i;
  if (open === '(' || open === '{') {
    const close = open === '(' ? ')' : '}';
    let depth = 0;
    for (let j = i + 1; j < text.length; j++) {
      if (text[j] === open) depth++;
      else if (text[j] === close) { depth--; if (depth === 0) return j + 1; }
    }
    return text.length;
  }
  let j = i + 1;
  while (j < text.length && /[A-Za-z0-9_.:\-]/.test(text[j])) j++;
  return j;
}

function readQuoted(text, i) {
  const q = text[i];
  let j = i + 1;
  let out = '';
  while (j < text.length) {
    if (text[j] === '\\' && q === '"' && text[j + 1] !== undefined) { out += text[j + 1]; j += 2; continue; }
    if (text[j] === q) {
      if (q === "'" && text[j + 1] === "'") { out += "'"; j += 2; continue; }
      return { content: out, next: j + 1 };
    }
    out += text[j];
    j++;
  }
  return { content: out, next: text.length };
}

/**
 * Lex one line of code into positioned tokens.
 *
 * A position-aware lexer (rather than an anchor plus a scan from that offset) is what keeps a
 * quoted anchor honest: `@($npxCli, 'dsh', '--profile', $Profile)` must yield the tokens
 * `dsh`, `--profile` — scanning from the character after `dsh` instead lands on the CLOSING quote
 * of `'dsh'` and reads the rest of the line as one string, which is how `Cwd` and `npx-cli.js`
 * used to appear in an argv.
 *
 * `stop`/`open` mark brackets and separators so argv extraction can respect them without
 * re-lexing. An interpolated string is expanded into its literal inner tokens (only when it
 * contains a flag), because that is the one case where a command is genuinely built by
 * interpolation — `` "`"$($inv.bin)`" web --port … " ``.
 */
function lexLine(text) {
  const toks = [];
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (c === ' ' || c === '\t' || c === ',') { i++; continue; }
    if (c === ';' || c === '|' || c === '>' || c === '<' || c === ')' || c === ']' || c === '}') {
      toks.push({ v: c, start: i, end: i + 1, stop: true });
      i++;
      continue;
    }
    if (c === '(' || c === '[' || c === '{') {
      toks.push({ v: c, start: i, end: i + 1, open: true });
      i++;
      continue;
    }
    if (c === '$' && (text[i + 1] === '(' || text[i + 1] === '{')) {
      const end = skipExpr(text, i);
      toks.push({ v: text.slice(i, end), start: i, end, expr: true });
      i = end;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') {
      const { content, next } = readQuoted(text, i);
      const at = toks.length;
      toks.push({ v: content, start: i, end: next, quoted: true });
      // An interpolated string, or a string that literally spells out a `dsh …` command line, is
      // expanded into its literal inner tokens — but only when it carries a flag. That is the one
      // case where the command really is inside the string; prose in a string never has one.
      const inner = [];
      for (const part of content.split(/\$\([^)]*\)|\$\{[^}]*\}|\$[A-Za-z_][\w.:]*/g)) {
        for (const t of part.split(/[\s,;|&()\[\]{}<>`"']+/)) if (t) inner.push(t);
      }
      const spellsCommand = /^\s*dsh\s/.test(content);
      const interpolated = /\$[({]/.test(content);
      if (inner.some((t) => FLAG_OK.test(t)) && (interpolated || spellsCommand)) {
        for (const t of inner) toks.push({ v: t, start: i, end: next, quotedInner: true, from: at });
      }
      i = next;
      continue;
    }
    let j = i;
    while (j < text.length && !/[\s,;|&()\[\]{}<>"'`]/.test(text[j])) j++;
    if (j === i) { i++; continue; }
    toks.push({ v: text.slice(i, j), start: i, end: j });
    i = j;
  }
  return toks;
}

/**
 * Read an argv starting at token `k`. Returns [] when the tokens cannot be read as a command
 * line, which is what keeps prose, regexes and redirections out of the inventory.
 */
function argvFromTokens(toks, k) {
  const argv = [];
  let expectingValue = false;
  let depth = 0;
  for (; k < toks.length; k++) {
    const t = toks[k];
    if (t.stop) {
      if (t.v === ')' || t.v === ']' || t.v === '}') {
        if (depth <= 0) break;
        depth--;
        continue;
      }
      break;
    }
    if (t.open) { depth++; continue; }
    if (t.expr) continue;
    const raw = t.v;
    if (!BARE_TOKEN_OK.test(raw)) { expectingValue = false; continue; }
    if (REDIRECT.test(raw)) break;
    if (FLAG_OK.test(raw)) { argv.push(raw); expectingValue = true; continue; }
    if (argv.length === 0) {
      if (WORD_TOKEN.test(raw)) { argv.push(raw); expectingValue = false; continue; }
      return [];
    }
    if (expectingValue) { argv.push(raw); expectingValue = false; continue; }
    break;
  }
  return argv;
}

function scanCli(abs) {
  const file = fileFor(abs);
  const view = codeView(abs);
  for (const ln of view) {
    if (ln.inBlock || !ln.code.trim()) continue;
    if (MATCHER_LINE.test(ln.code)) continue;
    const text = ln.code;
    const toks = lexLine(text);
    let argv = [];

    // A candidate argv counts only if it carries a flag, or if the anchor sits at a command start.
    // Without the second gate a sentence in a string (`"dsh bin : $bin"`) reads as an invocation.
    const gate = (cand, at) => {
      if (!cand.length) return cand;
      if (cand.some((t) => FLAG_OK.test(t))) return cand;
      return commandStart(text, at) ? cand : [];
    };

    // 1. `dsh` as a command word: a whole token that IS the command (or a path ending in it).
    //    Token equality is what keeps `dsh-update`, `dshHomePath`, `dshw.ps1`, `DSH_HOME`,
    //    `$dshBin`, `~/.dsh`, `dsh-archive-import.py` and `…/@deepseek-ai/dsh/lib/bin.js` from
    //    ever producing an invocation. A QUOTED `'dsh'` counts only when flags follow it, which is
    //    what separates `@($npxCli, 'dsh', '--profile', …)` from `path.join(…, 'dsh', 'lib', …)`.
    for (let k = 0; k < toks.length && !argv.length; k++) {
      const t = toks[k];
      if (t.expr || t.stop || t.open || t.quotedInner) continue;
      let quoted = false;
      if (t.quoted) {
        if (toks[k + 1]?.from === k) continue; // expanded: read through its inner tokens instead
        const c = t.v.trim();
        if (!(c === 'dsh' || /^dsh\s/.test(c) || /[/\\]dsh$/.test(c))) continue;
        quoted = true;
      } else if (!(t.v === 'dsh' || /[/\\]dsh$/.test(t.v))) {
        continue;
      }
      const raw = argvFromTokens(toks, k + 1);
      if (!raw.length) continue;
      const hasFlag = raw.some((x) => FLAG_OK.test(x));
      // A quoted `'dsh'` is a command only when flags follow it; a bare one must also sit where a
      // command can start (`Get-Command dsh -ErrorAction …` does not) and must not be followed by
      // punctuation (`… no ssh, no scp, no dsh, no log write` is a sentence, not an invocation).
      if (quoted) {
        if (!hasFlag) continue;
      } else {
        if (!commandStart(text, t.start)) continue;
        if (t.end < text.length && !/\s/.test(text[t.end])) continue;
      }
      argv = raw;
    }

    // 2. A `bin.js` invocation (`node <bin.js> …`), which names no `dsh` token at all. When the
    //    token carrying it is a quoted string, it is only a command if it carries a flag — a
    //    string that merely mentions the path (`'…bin.js not found'`) is prose.
    if (!argv.length) {
      const k = toks.findIndex((t) => !t.expr && t.v.includes('bin.js'));
      if (k >= 0) {
        const before = text.slice(0, toks[k].start);
        const guard = /(?:node|\.bin|bin\.js|ExecStart|&|\$)/.test(before);
        if (guard) {
          let cand = gate(argvFromTokens(toks, k + 1), toks[k].start);
          if (cand.length && toks[k].quoted && !cand.some((t) => FLAG_OK.test(t))) cand = [];
          if (cand.length) argv = cand;
        }
      }
    }

    // 3. A PowerShell argument array: `-ArgumentList @($inv.bin, 'web', '--port', …)`.
    if (!argv.length) {
      const am = toks.findIndex((t) => t.v === '-ArgumentList' || t.v === '-Argument');
      if (am >= 0 && /\bbin\b/i.test(text)) {
        for (let k = am + 1; k < toks.length && k <= am + 10; k++) {
          if (!/bin/i.test(toks[k].v)) continue;
          const cand = gate(argvFromTokens(toks, k + 1), toks[k].start);
          if (cand.length) argv = cand;
          break;
        }
      }
    }

    // 4. The dsh bin held in a variable and used AS THE PROGRAM — `& node $dshBin --profile web
    //    --dump-config`, `@($DshBin, '--profile', $Profile)`, `"$node" "$dsh_bin" --version`.
    //    The variable must name dsh (`$dshBin`, `$dsh_bin`) or the line must name dsh, and it must
    //    not merely be a flag's VALUE (`fwd+=(--dsh-dir "$dsh_dir" …)` is a directory, not a
    //    program). Anchored on the first long flag.
    if (!argv.length) {
      const namesDshWord = /(?:^|[^A-Za-z0-9_.\\/-])dsh(?:[^A-Za-z0-9_-]|$)/.test(text) || text.includes('bin.js');
      const varRe = /(?:^|[^\w${])\$\{?[\w.]*(?:bin|dsh)[\w.]*\}?/i;
      for (let k = 0; k < toks.length; k++) {
        const t = toks[k];
        if (t.quotedInner || t.expr || t.stop || t.open) continue;
        const m = varRe.exec(t.v);
        if (!m) continue;
        if (t.quoted && t.v.trim() !== m[0].trim()) continue; // a sentence that merely uses one
        const prev = toks[k - 1];
        if (prev && !prev.quoted && /^-{1,2}[A-Za-z]/.test(prev.v)) continue; // a flag's value
        if (!/dsh/i.test(m[0]) && !namesDshWord) continue;
        const fm = toks.findIndex((x) => /^--[A-Za-z]/.test(x.v));
        if (fm < 0) continue;
        const cand = gate(argvFromTokens(toks, fm), toks[fm].start);
        if (cand.length) { argv = cand; break; }
      }
    }

    if (!argv.length) continue;
    pushOnce(cliInvocations, `cli:${file}:${ln.n}:${argv.join(' ')}`, { argv, file, line: ln.n });
  }
}

// ── plugin imports ───────────────────────────────────────────────────────────────────────────
const IMPORT_RE = /\b(?:import|export)\s*([^'"]*?)\s*from\s*['"]([^'"]+)['"]/g;
const SIDE_IMPORT_RE = /\bimport\s*['"]([^'"]+)['"]/g;
const REQUIRE_DECL_RE = /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*|\{[^}]*\})\s*=\s*[^;]*?require\s*\(\s*['"]([^'"]+)['"]\s*\)/;
const REQUIRE_ANY_RE = /\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)/;

function symbolsFromClause(clause) {
  const out = [];
  const c = clause.trim();
  if (!c) return out;
  const brake = /\{([^}]*)\}/.exec(c);
  if (brake) {
    for (const part of brake[1].split(',')) {
      const name = part.trim().split(/\s+as\s+/)[0].trim();
      if (name) out.push(name);
    }
  }
  const head = c.split('{')[0].replace(/,\s*$/, '').trim();
  if (/\*\s+as\s+/.test(head)) out.unshift('*');
  else if (head && /^[A-Za-z_$][\w$]*$/.test(head)) out.unshift('default');
  return out;
}

function scanPluginImports(abs) {
  const af = fwd(abs);
  const m = /\/packages\/([^/]+)\//.exec(af);
  if (!m) return;
  const pkg = m[1];
  const ext = extOf(abs);
  if (!['.js', '.mjs', '.cjs'].includes(ext)) return;
  const file = fileFor(abs);
  for (const ln of codeView(abs)) {
    if (ln.inBlock || !ln.code.trim()) continue;
    const record = (mod, symbols) => {
      if (!mod || mod.startsWith('node:')) return;
      // A module name built by interpolation (`require('${specifier}')` inside the generator that
      // concatenates src into lib) is not a name we depend on — the real dependency is captured
      // from the source file that does the importing.
      if (mod.includes('$')) return;
      const internal = mod.startsWith('.') || isAbsolute(mod);
      pushOnce(pluginImports, `imp:${file}:${ln.n}:${mod}:${symbols.join(',')}`, {
        package: pkg, module: mod, symbols, internal, file, line: ln.n,
      });
    };
    IMPORT_RE.lastIndex = 0;
    let im;
    while ((im = IMPORT_RE.exec(ln.code))) record(im[2], symbolsFromClause(im[1]));
    SIDE_IMPORT_RE.lastIndex = 0;
    let sm;
    while ((sm = SIDE_IMPORT_RE.exec(ln.code))) record(sm[1], []);
    const dm = REQUIRE_DECL_RE.exec(ln.code);
    if (dm) {
      const clause = dm[1];
      const symbols = clause.startsWith('{') ? symbolsFromClause(`x, ${clause}`) : ['default'];
      record(dm[2], symbols);
    } else {
      REQUIRE_ANY_RE.lastIndex = 0;
      let rm;
      while ((rm = REQUIRE_ANY_RE.exec(ln.code))) record(rm[1], ['*']);
    }
  }
}

// ── a manifest's own dependency strings are references too ───────────────────────────────────
function scanPackageManifestRefs(abs) {
  harvestPackageRefs(abs, 'package-source');
}

// ── drive ────────────────────────────────────────────────────────────────────────────────────
const compositionFiles = [];
const settingsFiles = [];
const yamlFilesToValidate = [];

for (const abs of [...COLLECTED].sort()) {
  const role = roleOf(abs);
  const ext = extOf(abs);
  if (COMPOSITION_ROLES.has(role)) {
    compositionFiles.push({ abs, role });
    if (ext === '.yml' || ext === '.yaml') yamlFilesToValidate.push(abs);
  } else if (role === 'settings') {
    settingsFiles.push(abs);
    if (ext === '.yml' || ext === '.yaml') yamlFilesToValidate.push(abs);
  }
  if (role === 'profile-manifest') scanProfileManifest(abs);
  if (abs.endsWith('package.json')) scanPackageManifestRefs(abs);
  if (COMPOSITION_ROLES.has(role) || role === 'package-source' || role === 'script' || role === 'launcher') {
    harvestPackageRefs(abs, role);
  }
  if (['.sh', '.ps1', '.py', '.js', '.mjs', '.cjs', '.cmd'].includes(ext)) scanCli(abs);
  if (role === 'package-source') scanPluginImports(abs);
}

for (const { abs, role } of compositionFiles) scanComposition(abs, role, WHERE_OF[role]);
for (const abs of settingsFiles) scanSettings(abs);

// Scripts that build a bundle list in code are a second, independent source of truth for the
// bundle names, and a lost one there is exactly as silent as a lost one in a manifest.
for (const abs of COLLECTED) {
  const role = roleOf(abs);
  if (role !== 'script' && role !== 'launcher' && role !== 'package-source') continue;
  if (!['.js', '.mjs', '.cjs', '.sh', '.ps1'].includes(extOf(abs))) continue;
  const file = fileFor(abs);
  for (const ln of codeView(abs)) {
    if (!ln.code.trim()) continue;
    for (const m of ln.code.matchAll(/['"](@deepseek-ai\/dsh-[a-z0-9.-]+|dsh-plugin-[a-z0-9-]+)['"]/g)) {
      pushOnce(profileBundles, `bundle:${file}:${ln.n}:${m[1]}:script`,
        { name: m[1], source: 'script', file, line: ln.n });
    }
  }
}

// ── independent validation of the parsed structure (the reason YAML is loaded at all) ────────
let yamlChecked = 0;
const nonStringIds = [];
const jsTagLosses = [];
for (const abs of yamlFilesToValidate) {
  const text = linesOf(abs).join('\n');
  const { value, warnings, error } = parseYamlSafe(text);
  if (error) {
    note(`${fileFor(abs)} failed to parse as YAML: ${error} — it was still scanned line-by-line, so `
      + 'its rows are in the inventory, but nothing independently validated that scan '
      + '(input-data gap: the file is not valid YAML)');
    continue;
  }
  yamlChecked++;
  if (warnings.length) {
    note(`${fileFor(abs)} parsed with ${warnings.length} non-fatal YAML warning(s), first: `
      + `${warnings[0]} (the !!js tag is preserved by this module's resolver, so tagged values are `
      + 'kept as source text rather than resolved to undefined)');
  }
  // The `!!js` tags are the one place where a "successful" parse can still be silently lossy: a
  // resolver-less parse turns every tagged scalar into undefined and nobody notices. Count the
  // tags in the raw text — code lines only, because the tag is *discussed* in the headers of these
  // very files — against the wrappers in the parsed tree, and say so when they disagree.
  const taggedInText = codeView(abs).filter((l) => !l.inBlock && l.code)
    .reduce((n, l) => n + (l.code.match(/!!js\b/g) ?? []).length, 0);
  let wrapped = 0;
  const walk = (v, depth) => {
    if (depth > 12 || v === null || typeof v !== 'object') return;
    if (Array.isArray(v)) { for (const it of v) walk(it, depth + 1); return; }
    if (isJs(v)) { wrapped++; return; }
    for (const [k, val] of Object.entries(v)) {
      if (k === 'id' && val !== undefined && !isJs(val) && typeof val !== 'string') {
        nonStringIds.push(`${fileFor(abs)}: id is ${typeof val}, not a string`);
      }
      walk(val, depth + 1);
    }
  };
  walk(value, 0);
  if (taggedInText !== wrapped) {
    jsTagLosses.push(`${fileFor(abs)}: ${taggedInText} "!!js" tag(s) in the text, ${wrapped} preserved by the parse`);
  }
}
if (jsTagLosses.length) {
  note(`"!!js" values did not survive parsing in ${jsTagLosses.length} file(s) — `
    + `${jsTagLosses[0]}. Any field read from a parsed tree rather than from the raw line would be `
    + 'undefined there (code/resolver limitation)');
}
if (nonStringIds.length) {
  note(`a row id was not a plain string in ${nonStringIds.length} place(s) (first: ${nonStringIds[0]}); `
    + 'this module reads ids from the raw line, so the inventory is unaffected, but a parser-based '
    + 'consumer would see a different value (input-data risk)');
}
if (yamlChecked === 0 && yamlFilesToValidate.length > 0) {
  note(`none of the ${yamlFilesToValidate.length} YAML files could be parsed, so the line-by-line `
    + 'scan was never independently validated (code limitation)');
}

// ── limitations that were actually observed in this inventory ────────────────────────────────
// Each one is derived from what the scan found, not asserted about the world, so it stays true if
// the data changes: a note that describes a gap nobody can see would be worse than no note.
{
  const external = [...new Set(pluginImports.filter((p) => !p.internal).map((p) => p.module))];
  const cordisish = external.filter((m) => m === '@deepseek-ai/cordis' || /^@deepseek-ai\/dsh-/.test(m));
  if (!cordisish.length) {
    note('no package under packages/* imports @deepseek-ai/cordis or any @deepseek-ai/dsh-* module: '
      + `the only non-relative modules imported are ${external.join(', ') || '(none)'}. Our plugins `
      + 'receive `ctx` by injection rather than by importing cordis, so this module observes no '
      + 'cordis/DSH host-API symbol surface for them, and B8 (plugin API drift) has nothing here to '
      + 'compare against (a gap in what this artifact can prove, not in the scan)');
  }
}

{
  // Comment-only mentions are not inventoried: a name that appears solely in a comment cannot be
  // resolved or imported by anything, so recording it would put unresolved entries into the
  // cross-reference. But it is also the only place some rows' real plugin is named, which B4
  // ("did the patched row change its plugin") would otherwise have to guess at.
  const commentMentions = [];
  for (const abs of COLLECTED) {
    const role = roleOf(abs);
    if (role !== 'host-patch' && role !== 'profile-patch' && role !== 'bundle-patch') continue;
    for (const ln of codeView(abs)) {
      if (ln.code.trim()) continue; // only fully-commented lines
      const m = /name:\s*'(@deepseek-ai\/[a-z0-9.-]+)'/.exec(ln.raw);
      if (m) commentMentions.push(`${fileFor(abs)}:${ln.n} names ${m[1]}`);
    }
  }
  if (commentMentions.length) {
    note(`comment-only mentions of upstream packages are NOT in packageRefs (${commentMentions.length} `
      + `found, first: ${commentMentions[0]}). Recording them would add references nothing can `
      + 'resolve, but it also means the plugin a patch row actually carries is documented only in '
      + 'prose here, so B4 (patch target changed plugin) gets no advisory input from this artifact '
      + '(deliberate code choice, with a real coverage cost)');
  }
}

{
  const heredocs = [];
  for (const abs of COLLECTED) {
    const ext = extOf(abs);
    if (!['.sh', '.ps1', '.py'].includes(ext)) continue;
    for (const ln of codeView(abs)) {
      if (/<<-?\s*['"]?[A-Za-z_]\w*/.test(ln.code)) { heredocs.push(`${fileFor(abs)}:${ln.n}`); continue; }
      if (ext === '.ps1' && /@["']\s*$/.test(ln.code)) heredocs.push(`${fileFor(abs)}:${ln.n}`);
    }
  }
  if (heredocs.length) {
    note(`shell heredocs and PowerShell here-strings are not modelled as prose (${heredocs.length} `
      + `opener(s) found, first: ${heredocs[0]}), so a command quoted inside a usage or help block `
      + 'can be reported as an invocation. A trailing-punctuation test removes the ones seen here, '
      + 'but a usage line spelled exactly like a command would still be kept (code limitation)');
  }
}

{
  // Commands documented in the presets' own skill markdown. These files are outside the scan roots
  // by design (the roots are code and configuration), so they are read here only to measure what
  // that choice costs — a documented command is a command a person WILL run.
  const skillMd = new Set();
  const skillsRoot = join(CONFIG_ROOT, 'presets');
  if (existsSync(skillsRoot)) {
    const mdFiles = new Set();
    for (const entry of readdirSync(skillsRoot, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      walkDir(join(skillsRoot, entry.name, 'skills'), ['.md'], mdFiles);
    }
    for (const abs of mdFiles) {
      const lines = linesOf(abs);
      for (let n = 0; n < lines.length; n++) {
        if (/dsh\s+(?:plugin|web|--profile|archive)\b/.test(stripComment(lines[n], '.md'))) {
          skillMd.add(`${fileFor(abs)}:${n + 1}`);
          break;
        }
      }
    }
  }
  if (skillMd.size) {
    note(`documented, but not inventoried: ${skillMd.size} \`dsh …\` command(s) appear in the `
      + `presets' own skill markdown, which is outside the scan roots (the roots are code and `
      + `configuration, not documentation). First: ${[...skillMd][0]}. B9 therefore sees the `
      + 'commands this deployment RUNS but not the ones its documentation tells a person to run '
      + '(input scope choice, with a real coverage cost)');
  }
}

{
  const hostPatch = join(DSH_HOME, 'cordis.patch.yml');
  const webPatch = join(DSH_HOME, 'profiles', 'web', 'cordis.patch.yml');
  if (!existsSync(hostPatch) && existsSync(webPatch)) {
    const documented = linesOf(webPatch).some((l) => l.includes('cordis.patch.yml')
      && l.includes('DSH_HOME'));
    note(`${hostPatch} does not exist on this machine, so the outermost patch layer the profile `
      + `patch names in its own composed-tree order${documented ? ' (that is where it is documented)' : ''} `
      + 'contributes nothing to this inventory. Nothing is lost — the layer is absent — but a '
      + 'comparison of layers should know it was looked for and not found (input-data gap)');
  }
}

// ── assemble ─────────────────────────────────────────────────────────────────────────────────

function byLoc(a, b) {
  return a.file < b.file ? -1 : a.file > b.file ? 1 : a.line - b.line;
}
for (const arr of [profileBundles, packageRefs, rowIds, isolateServices, settingsKeys, cliInvocations, pluginImports, patchRowTargets]) {
  arr.sort(byLoc);
}

const artifact = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  configRoot: CONFIG_ROOT,
  dshHome: DSH_HOME,
  profileBundles,
  packageRefs,
  rowIds,
  isolateServices,
  settingsKeys,
  cliInvocations,
  pluginImports,
  patchRowTargets,
  notes: NOTES,
};

const json = `${JSON.stringify(artifact, null, 2)}\n`;

if (OUT_PATH) {
  try {
    writeFileSync(OUT_PATH, json, 'utf8');
  } catch (e) {
    process.stderr.write(`consumed.mjs: cannot write --out ${OUT_PATH}: ${e.message}\n`);
    process.exit(3);
  }
}
process.stdout.write(json);
process.exit(0);
