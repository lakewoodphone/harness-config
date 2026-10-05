#!/usr/bin/env node
/**
 * stage-home.mjs — build a STAGED DSH home that a candidate engine can actually boot on.
 *
 * WHY THIS EXISTS
 * ---------------
 * `dsh-update/tools/switch-engine.ps1` is the one command that switches the engine and the config
 * together, and it refuses unless the staged home already carries the MIGRATED config
 * (PRECONDITION 2, `switch-engine.ps1:1101-1138`). That predicate is precise and greppable:
 *
 *   * at least one `<StagedHome>\.agent-presets\*\agent.cordis.yml`, and
 *   * at least one `<StagedHome>\profiles\*\cordis.patch.yml`, and
 *   * those preset files together name `@deepseek-ai/dsh-workflow-ptc` at least once and
 *     `@deepseek-ai/dsh-workflow-worker-thread` ZERO times, and
 *   * those profile patches together name `@deepseek-ai/dsh-agent-preset-registry` at least once
 *     and `@deepseek-ai/dsh-agent-presets` ZERO times.
 *
 * Nothing in the repo BUILT such a home: it was assembled by hand and by test fixtures, which is
 * exactly the class of artefact that silently rots. This module is the builder.
 *
 * WHAT IT REFUSES TO DO
 * ---------------------
 * The two coupled package names are NOT written down anywhere in this file as the answer. They are
 * READ from the candidate prefix (`<candidate>/node_modules/@deepseek-ai/`), per slot, at run time.
 * A slot that is ambiguous — both names present, or neither — is a REFUSAL, not a guess: composing
 * a row whose package is missing fails at mount, and a row naming a package that is present but
 * wrong fails silently and expensively later. Same for an unreadable directory: an empty read is a
 * refusal, never a silent success.
 *
 * WHAT IS CONFIG AND WHAT IS STATE
 * --------------------------------
 * A staged home is CONFIG, not state. It carries the composition surface — `profiles/*` minus
 * `node_modules`, `.agent-presets/**`, `settings.yaml` — and NOT `sessions/`, `storages/`,
 * `attachments/`, `.credentials.yaml`, `metrics/`, `health/`. Two reasons, both measured elsewhere
 * in this repo: a staged `sessions/` made gate G8 compare the candidate against a staged corpus
 * instead of the operator's real 1,256 logs (`tests/guards/state-home.mjs`), and a recursive copy
 * that follows the junctions inside `profiles/node_modules` measured **127,970 files / 1.0 GB** for
 * a tree whose real content is 884 KB (`tests/switch/README-rework.md`). So `node_modules` is
 * skipped BY NAME, at every depth, and so are the state directories.
 *
 * HOW THE GENERATED PRESET ROWS REACH THE COMPOSITION (the decision, and why)
 * --------------------------------------------------------------------------
 * `scripts/make-preset-rows.mjs` emits the three `preset-<name>` rows, and `FINDINGS.md` item 2
 * records the trap: a profile's patch layers are its BUNDLES' `dsh.bundle.patch` files (in
 * `dsh.profile.bundles` order) and then the profile's own `cordis.patch.yml`
 * (`@deepseek-ai/dsh-app-boot/lib/index.js:462-475`) — **a second loose file in the profile
 * directory is not one of those layers and is therefore never read**. Measured by running
 * `--dump-config` on a staged home that carried `profiles/web/presets.generated.patch.yml`:
 * our rows were absent from the composed tree. (Composing the same file through `--patch` DOES
 * produce them, which is why the standalone artefact exists at all.)
 *
 * Three wirings were available and only one is usable from a builder that may not edit the
 * candidate prefix:
 *
 *   1. a launcher `--patch` argument — not this module's to add; nothing in the repo passes one
 *      (`scripts/sync.py` and `multi-window/dshw.ps1` searched, no match).
 *   2. a bundle that declares the file — would require writing into
 *      `<candidate>/node_modules/@deepseek-ai/dsh-web-app/package.json`, i.e. mutating a fetched
 *      install. Refused: the staged copy is supposed to be the thing under test, not the install.
 *   3. **FOLD the same rows into `profiles/<profile>/cordis.patch.yml`, inside a MARKED MANAGED
 *      BLOCK** — the layer the engine already loads, and the convention this repo established for
 *      exactly this problem (`scripts/make-preset-rows.mjs --install` does it for the repo copy; a
 *      cross-repo agreement test lives in `dsh-update/tests/preset-rows/verify-managed-block.mjs`).
 *
 * This module takes (3). `insert:` with no `id` does `data.push(...insert)` in the engine's own
 * patch algorithm, so a row inserted from the profile layer is byte-for-byte the same row as one
 * inserted from a `--patch` layer: the mechanism is provably equivalent, not merely similar. The
 * block is derived from the converter's OUTPUT (not re-derived from the presets), so the two cannot
 * disagree, and the block's markers are the converter's own regexes.
 *
 * THE `default` ROW IS DELIBERATELY NOT TOUCHED
 * ---------------------------------------------
 * `FINDINGS.md` "What this does NOT settle" item 1: 0.1.7's `agent-preset-registry` row carries
 * `config.default`, and it is shipped by `dsh-web-app`'s own patch, so it is PATCHED rather than
 * authored. Making `zabz` the default is a separate, deliberate change to that row's `config`, and
 * silently rewriting it here would be this module deciding a policy question under cover of a
 * mechanical migration. It is recorded as an open row (`config.defaultIsNotOurs`) instead.
 *
 * Usage:
 *   node dsh-update/lib/stage-home.mjs --from <configHome> --candidate <prefix> --out <dir>
 *                                     [--profile web] [--check] [--json]
 *
 *   --from       the home to take the config surface from (default: $DSH_HOME, else ~/.dsh).
 *                READ ONLY — this module never writes a byte into it.
 *   --candidate  the npm prefix holding the candidate engine (`<prefix>/node_modules/@deepseek-ai`).
 *   --out        the staged home to build. With --check it is compared against, never written.
 *   --profile    the profile whose patch layer receives the preset rows (default: web).
 *   --check      write NOTHING; exit non-zero when the committed staged home would differ, and
 *                still run the real assertion over the COMMITTED tree.
 *   --json       print exactly one JSON object on stdout (progress goes to stderr).
 *
 * Exit codes: 0 ok, 1 refusal or drift, 2 usage error.
 */
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, readlinkSync, rmSync, statSync,
  symlinkSync, writeFileSync,
} from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { PARSE_OPTIONS, YAML, yamlResolvedFrom } from './yaml.mjs';

const MODULE_DIR = dirname(fileURLToPath(import.meta.url));
/** `dsh-update/lib` -> repo root. Used to find the converter and the repo `presets/` copy. */
const REPO_ROOT = resolve(MODULE_DIR, '..', '..');
const CONVERTER = join(REPO_ROOT, 'scripts', 'make-preset-rows.mjs');

const PRESET_DIR_NAME = '.agent-presets';
const PRESET_FILE_NAME = 'agent.cordis.yml';
const MANIFEST_NAME = 'STAGED-HOME.json';
const MANIFEST_SCHEMA = 1;

/**
 * The provenance line inside the manifest. A staged tree is a COPY; without this, a file found in
 * it has no age and no source, and "where did this byte come from" is unanswerable — which is the
 * failure mode this whole pipeline exists to avoid. It is the ONLY non-hash field in the manifest
 * that varies between runs, and `--check` therefore compares manifests with it removed.
 */
const provenance = (when) => ({
  generator: 'dsh-update/lib/stage-home.mjs',
  generatedAt: when,
});

// ── the coupled slots ────────────────────────────────────────────────────────────────────────
/**
 * A "slot" is one version-coupled position in our config for which the two sides of the version
 * line use DIFFERENT package names. The names are never hardcoded as an answer: every name in the
 * `names` list is probed against the candidate prefix, and the slot is decidable only when exactly
 * one of them is installed.
 *
 * `newName` is which side of the line the name belongs to — `modern` names exist on 0.1.7+,
 * `legacy` names on the 0.1.5 line — and it decides which of the two source shapes the builder
 * emits. `fileKind`/`glob` say where the source text lives in the home.
 */
const SLOTS = [
  {
    id: 'workflow-runtime',
    description: 'the workflow runtime row our agent presets mount',
    // `modernName` is WHICH name is the modern one — positional truth, not "the first in the list".
    // The registry slot is the proof that position is not truth: the two names for it happen to be
    // listed legacy-first, and a `names[0] === side` test therefore classified the MODERN registry
    // package as the legacy one and made the assertion look for the removed name inside our own
    // rewritten file. Measured 2026-10-05 on the 0.1.7-rc.2 candidate.
    modernName: '@deepseek-ai/dsh-workflow-ptc',
    names: ['@deepseek-ai/dsh-workflow-ptc', '@deepseek-ai/dsh-workflow-worker-thread'],
    fileKind: 'preset',
  },
  {
    id: 'preset-registry',
    description: 'the package that registers agent presets on the composition root',
    modernName: '@deepseek-ai/dsh-agent-preset-registry',
    names: ['@deepseek-ai/dsh-agent-presets', '@deepseek-ai/dsh-agent-preset-registry'],
    fileKind: 'profilePatch',
  },
  {
    id: 'preset-row',
    description: 'the plugin row id a preset definition mounts as',
    modernName: '@deepseek-ai/dsh-agent-preset',
    // The row `name` used by our emitted preset rows. On 0.1.5 the preset is a DIRECTORY read by
    // `dsh-agent-presets` and there is no `dsh-agent-preset` row to name at all, so this slot is
    // undecidable on that side and the caller refuses rather than inventing a name.
    names: ['@deepseek-ai/dsh-agent-preset'],
    fileKind: 'presetRow',
  },
];

const pkgDirName = (name) => name.split('/')[1];

/**
 * Decide every slot from the candidate prefix's OWN directory listing.
 *
 * Returns `{ ok, decisions, problems }`. A problem is never downgraded to a guess: this function
 * has no default branch that "assumes modern".
 */
export function detectSlots(candidateNodeModules) {
  const api = join(candidateNodeModules, '@deepseek-ai');
  const decisions = [];
  const problems = [];

  let entries;
  try {
    entries = readdirSync(api, { withFileTypes: true });
  } catch (e) {
    problems.push(`cannot read the candidate's package directory ${api}: ${e.message}. A staged `
      + 'home cannot be built without knowing which names the candidate actually provides, and an '
      + 'unreadable directory is not an answer.');
    return { ok: false, decisions, problems, api, installedCount: 0 };
  }
  const installed = new Set(entries.filter((e) => e.isDirectory()).map((e) => e.name));
  if (installed.size === 0) {
    problems.push(`${api} lists no packages at all — that is a refusal, not an empty candidate`);
    return { ok: false, decisions, problems, api, installedCount: 0 };
  }

  for (const slot of SLOTS) {
    const present = slot.names.filter((name) => installed.has(pkgDirName(name)));
    const raw = {
      id: slot.id,
      description: slot.description,
      candidates: slot.names,
      present,
      decides: null,
      side: null,
      refused: null,
    };
    if (present.length === 1) {
      raw.decides = present[0];
      raw.side = present[0] === slot.modernName ? 'modern' : 'legacy';
    } else if (present.length === 0) {
      raw.refused = `the candidate provides NONE of ${slot.names.join(', ')} `
        + `(checked ${installed.size} package directories under ${api})`;
    } else {
      raw.refused = `the candidate provides MORE THAN ONE of ${slot.names.join(', ')} `
        + `(${present.join(', ')}) — both sides of the version line are installed, so which one this `
        + 'slot means cannot be decided from here';
    }
    if (raw.refused) problems.push(`[${slot.id}] ${raw.refused}`);
    decisions.push(raw);
  }

  const byId = Object.fromEntries(decisions.map((d) => [d.id, d]));
  // The row id is a hard requirement for the modern side; on the legacy side there is no such row
  // and the builder refuses explicitly rather than emitting a row naming a package that is absent.
  if (!problems.length && byId['preset-row'].side === 'legacy') {
    problems.push('[preset-row] the candidate is on the 0.1.5 side: it reads presets from the '
      + `${PRESET_DIR_NAME} DIRECTORY and provides no '@deepseek-ai/dsh-agent-preset' ROW plugin, so `
      + 'there is nothing for the generated preset rows to mount as. Refusing to emit rows that '
      + 'name an absent package. (This is a deliberate gap, not an oversight — see docs/STAGE-HOME.md.)');
  }

  return {
    ok: problems.length === 0,
    decisions,
    problems,
    api,
    installedCount: installed.size,
  };
}

/** A read-only probe used by the tests and by `--json` to describe a candidate without building. */
export function candidateSlots(candidatePrefix) {
  return detectSlots(join(candidatePrefix, 'node_modules'));
}

/**
 * `--slots-from <file>` — a JSON file listing the package names a candidate provides.
 *
 * WHY THIS EXISTS: proving the refusal paths needs a candidate that provides neither name, or both,
 * and that cannot be done against a real fetched install without either editing it (forbidden) or
 * downloading two more versions. The complete set of prefixes fetched here is known, and building a
 * frozen list of every installed name from one of them is not the same thing as injecting an
 * ANSWER: the slot names are still probed against the list, so a fixture that lists the modern name
 * really does decide modern, and one that lists neither really does refuse.
 *
 * Accepted shapes: `["pkg", ...]` or `{"packages": [...]}` or the raw readdir form
 * `[{"name": "pkg", "isDirectory": true}, ...]`.
 */
function slotListFromFile(file) {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(file, 'utf8'));
  } catch (e) {
    throw new Error(`cannot read --slots-from ${file}: ${e.message}`);
  }
  const list = Array.isArray(parsed) ? parsed : parsed?.packages;
  if (!Array.isArray(list)) {
    throw new Error(`--slots-from ${file} is not a list of package names (or { "packages": [...] })`);
  }
  const names = list
    .map((entry) => (typeof entry === 'string' ? entry : entry?.name))
    .filter((name) => typeof name === 'string' && name.length > 0);
  if (names.length === 0) throw new Error(`--slots-from ${file} contained no usable package name`);
  return names;
}

/** detectSlots(), but over an injected name list instead of a directory. Same decision rules. */
function detectSlotsFromList(names, label) {
  const installed = new Set(names);
  const decisions = [];
  const problems = [];
  for (const slot of SLOTS) {
    const present = slot.names.filter((name) => installed.has(pkgDirName(name)));
    const raw = { id: slot.id, description: slot.description, candidates: slot.names, present, decides: null, side: null, refused: null };
    if (present.length === 1) {
      raw.decides = present[0];
      raw.side = present[0] === slot.modernName ? 'modern' : 'legacy';
    } else if (present.length === 0) {
      raw.refused = `the candidate provides NONE of ${slot.names.join(', ')} (${label})`;
    } else {
      raw.refused = `the candidate provides MORE THAN ONE of ${slot.names.join(', ')} (${present.join(', ')}) — ${label}`;
    }
    if (raw.refused) problems.push(`[${slot.id}] ${raw.refused}`);
    decisions.push(raw);
  }
  const byId = Object.fromEntries(decisions.map((d) => [d.id, d]));
  if (!problems.length && byId['preset-row'].side === 'legacy') {
    problems.push('[preset-row] the candidate is on the 0.1.5 side (injected name list)');
  }
  return { ok: problems.length === 0, decisions, problems, api: label, installedCount: installed.size };
}

// ── the copy surface ─────────────────────────────────────────────────────────────────────────
/**
 * State that must NEVER be copied into a staged home. Every entry here is named in
 * `dsh-update/STATE-COMPAT.md` or in `tests/guards/state-home.mjs` as something whose presence
 * changes what a gate MEANS (a staged `sessions/` makes G8 read the wrong corpus) or leaks a
 * secret (`.credentials.yaml`).
 */
const STATE_EXCLUDES = new Set([
  'sessions', 'storages', 'attachments', 'metrics', 'health', '.credentials.yaml', 'node_modules',
]);
/**
 * Files in a profile directory that are OUR surface and are copied. A WHITELIST rather than "copy
 * everything except node_modules", because `profiles/<name>/` in the live home is full of
 * `cordis.patch.yml.bak-*` and `package.json.bak-*` — 30 of them, measured 2026-10-05 — and a
 * staged home that carries a directory of timestamped backups invites a future reader to compare
 * against the wrong generation.
 */
const PROFILE_FILES = ['cordis.yml', 'cordis.patch.yml', 'package.json', 'pnpm-workspace.yaml'];

const isBackup = (name) => /\.bak(-|$)/.test(name) || name.endsWith('.pre-sync');

/** Recursively copy a tree, skipping `node_modules` and state by NAME at every depth. */
function copyTreeSkipping(skipped, srcDir, dstDir) {
  const copied = [];
  const skippedEntries = [];
  const stack = [[srcDir, dstDir]];
  while (stack.length > 0) {
    const [src, dst] = stack.pop();
    let entries;
    try {
      entries = readdirSync(src, { withFileTypes: true });
    } catch (e) {
      throw new Error(`cannot read ${src}: ${e.message}`);
    }
    mkdirSync(dst, { recursive: true });
    for (const entry of entries) {
      const from = join(src, entry.name);
      const to = join(dst, entry.name);
      if (entry.isDirectory()) {
        if (skipped.has(entry.name)) {
          skippedEntries.push(from);
          continue;
        }
        stack.push([from, to]);
      } else if (entry.isFile()) {
        if (skipped.has(entry.name)) {
          skippedEntries.push(from);
          continue;
        }
        copyFileSync(from, to);
        copied.push(to);
      }
      // Symlinks and other node types are neither followed nor copied: following a junction under
      // profiles/node_modules is the measured 127,970-file trap, and a builder that silently
      // dropped the branch is how that trap comes back.
    }
  }
  return { copied, skippedEntries };
}

/**
 * Recreate a profile's out-of-tree module ANCHOR as LINKS, without following a single one.
 *
 * WHY THIS IS NOT "COPYING node_modules", WHICH THE MODULE OTHERWISE REFUSES TO DO.
 * The measured trap is a RECURSIVE copy: junctions inside `profiles/node_modules` expand to
 * 127,970 files / 1.0 GB for 884 KB of real content. This does the opposite — it walks the anchor
 * with `lstat` (never `stat`), reproduces every symlink/junction as a link to the SAME target, and
 * recurses only into REAL directories, skipping `node_modules` and `.pnpm` by name at every depth.
 *
 * WHY IT IS NEEDED AT ALL, measured 2026-10-05: with the anchor absent, the candidate composed the
 * staged home to **185 rows** and said why in its own stderr —
 *
 *     dsh: skipping profile bundle "dsh-plugin-attention": cannot resolve … from the dsh
 *     installation or <staged>/profiles/web
 *
 * nine times, and then `patch: entry "remote-fanout" not found` and `"tool-subagent-remote" not
 * found`. `profiles/web/package.json` names eleven bundles and nine of them are junctions into
 * `packages/*`; a staged profile without that anchor composes a DIFFERENT tree from the live one,
 * so a boot proof against it would be a proof about the wrong composition. Recreating nine links
 * costs nothing and restores the composition exactly.
 */
function linkTreeSkipping(skipped, srcDir, dstDir, depth, out) {
  let entries;
  try {
    entries = readdirSync(srcDir, { withFileTypes: true });
  } catch (e) {
    out.problems.push(`cannot read ${srcDir}: ${e.message}`);
    return;
  }
  mkdirSync(dstDir, { recursive: true });
  for (const entry of entries) {
    const from = join(srcDir, entry.name);
    const to = join(dstDir, entry.name);
    let link = null;
    try {
      link = readlinkSync(from);
    } catch {
      link = null;
    }
    if (link !== null) {
      let target = link;
      // A RELATIVE link must keep its meaning after the move. A junction's `readlink` returns the
      // absolute target with a `\\?\` prefix on Windows; that is reproduced as-is because a
      // junction's target is absolute by construction.
      try {
        makeLink(target, to, from, out);
      } catch (e) {
        out.problems.push(`cannot recreate the link ${from} -> ${target}: ${e.message}`);
      }
      continue;
    }
    if (entry.isDirectory()) {
      if (depth > 0 && skipped.has(entry.name)) {
        out.skipped.push({ path: to, why: 'node_modules/.pnpm inside the anchor (not followed)' });
        continue;
      }
      if (depth >= 1) continue; // one level of real directories only; their contents are the trap
      linkTreeSkipping(skipped, from, to, depth + 1, out);
      continue;
    }
    if (entry.isFile()) {
      copyFileSync(from, to);
      out.copied.push(to);
    }
  }
}

/**
 * Create one link, matching the kind the source used. On Windows a directory link is a JUNCTION,
 * and `symlinkSync(target, path, 'junction')` is Node's own way to say so; on POSIX the type flag
 * is ignored and a plain symlink is created.
 */
function makeLink(target, to, from, out) {
  let isDirectory = false;
  try {
    isDirectory = statSync(target).isDirectory();
  } catch {
    isDirectory = false;
  }
  try {
    symlinkSync(target, to, isDirectory ? 'junction' : 'file');
  } catch (e) {
    if (e.code === 'EEXIST') return;
    throw e;
  }
  out.links.push({ path: to, target, kind: isDirectory ? 'junction' : 'file' });
}

// ── the version-coupled rewrite ──────────────────────────────────────────────────────────────
/**
 * Per-character YAML line classification: `#` comment, or YAML scalar.
 *
 * WHY ONE CHARACTER AT A TIME, AND WHY QUOTES MATTER. A comment is a `#` at the start of a line or
 * after whitespace — but NOT inside a quoted scalar, which is where these files keep every value
 * that matters. `scripts/check-version-coupled-config.py`'s `mask_comments` documents this and
 * honours YAML's `''` doubling; the first version of this module did not, and the miss was
 * measurable: `profiles/mesh/cordis.patch.yml:93` is
 *
 *     name: '@deepseek-ai/dsh-agent-preset-registry'
 *
 * — a real row, whose FIRST `#` at index 0 put the reader into comment state, after which every
 * quoted reference on that line was counted as prose. Measured 2026-10-05: `mesh` reported
 * `1 row still names the REMOVED '@deepseek-ai/dsh-agent-preset-registry' outside a comment`, i.e.
 * the modern name counted as the removed one, because the row's own `#` began the line's comment
 * region. A quote-aware scan fixes the class, not the instance. It is deliberately MORE
 * conservative than the Python masker (which resets quote state at each newline): here an
 * unterminated quote swallows the rest of the FILE, so nothing after it can be counted as code and
 * a stray apostrophe can never hide a real row.
 */
function scanLineMask(line) {
  const inComment = new Array(line.length).fill(false);
  let state = null;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (state !== null) {
      if (state === "'" && ch === "'") {
        if (line[i + 1] === "'") i += 1; // YAML `''` escape stays inside the scalar
        else state = null;
        continue;
      }
      if (state === '"' && ch === '\\') { i += 1; continue; }
      if (state === '"' && ch === '"') state = null;
      continue;
    }
    if (ch === "'" || ch === '"') { state = ch; continue; }
    if (ch === '#') {
      const prev = i === 0 ? '' : line[i - 1];
      if (i === 0 || prev === ' ' || prev === '\t' || prev === '\r') {
        for (let k = i; k < line.length; k += 1) inComment[k] = true;
        break;
      }
    }
  }
  return inComment;
}

/**
 * True when a YAML scalar that starts at `start` is NOT terminated on its own line. Both the
 * rewrite and the counter refuse to touch such a scalar: an unterminated quote makes the rest of
 * the file ambiguous, and "I could not tell whether this is a row or prose" must not resolve to
 * "rewrite it and hope".
 */
function scalarSpansLines(line, start) {
  let state = null;
  for (let i = start; i < line.length; i += 1) {
    const ch = line[i];
    if (state === null) { if (ch === "'" || ch === '"') state = ch; }
    else if (state === "'" && ch === "'") { if (line[i + 1] === "'") i += 1; else state = null; }
    else if (state === '"' && ch === '\\') i += 1;
    else if (state === '"' && ch === '"') state = null;
  }
  return state !== null;
}

function lineParts(line) {
  const mask = scanLineMask(line);
  let commentAt = -1;
  for (let i = 0; i < mask.length; i += 1) {
    if (mask[i]) { commentAt = i; break; }
  }
  const code = commentAt === -1 ? line : line.slice(0, commentAt);
  const comment = commentAt === -1 ? '' : line.slice(commentAt);
  return { code, comment };
}

/**
 * Count occurrences of `needle`, split into code (a YAML scalar) and comment (`#` prose).
 *
 * Both counts are reported, because "zero outside comments" is the claim switch-engine's
 * PRECONDITION 2 makes and "N inside comments" is what makes that claim auditable rather than
 * lucky — and because `scripts/check-version-coupled-config.py` says the same thing in its own
 * header: COMMENTS ARE NOT DEPENDENCIES, and a scanner that forgets it invents a finding on a good
 * engine.
 */
export function countRefs(text, needle) {
  let code = 0;
  let comment = 0;
  for (const line of text.split(/\r?\n/)) {
    const { code: codePart, comment: commentPart } = lineParts(line);
    code += codePart.split(needle).length - 1;
    comment += commentPart.split(needle).length - 1;
  }
  return { code, comment, total: code + comment };
}

/**
 * Rewrite a name to its candidate-side equivalent.
 *
 * WHERE, AND WHERE NOT — this is a deliberate split, not a convenience:
 *
 *   * CODE (a YAML scalar: a row's `name:`, a `plugins` entry, an expression) is always rewritten.
 *     It is the thing that either resolves against the candidate or fails to.
 *   * In a COMMENT the line's LEADING `#` prose is left alone (it is history: "`X` was REMOVED in
 *     0.1.7" stops being true if you rewrite it), but an occurrence INSIDE a `'…'`-quoted scalar
 *     that the comment text names is REWRITTEN. That split exists because of a measured case:
 *     `profiles/mesh/cordis.patch.yml:86` says the engine this machine runs provides
 *     `'@deepseek-ai/dsh-agent-presets'`, while line 93 below it is the commented-OUT row that names
 *     the modern package. Leaving the comment alone would leave `switch-engine`'s own
 *     `Count-Pattern` — which is a plain substring count over the whole file, comments included —
 *     reporting a removed name and refusing the switch it was given.
 *   * A scalar that does not terminate on its own line is NEVER rewritten (see `scalarSpansLines`).
 */
function rewriteRefs(text, from, to) {
  let changed = 0;
  const out = text.split(/\r?\n/).map((line) => {
    const { code, comment } = lineParts(line);
    let lineChanged = 0;
    let nextCode = code;
    if (code.includes(from)) {
      lineChanged += code.split(from).length - 1;
      nextCode = code.split(from).join(to);
    }
    let nextComment = comment;
    // A QUOTED name inside the comment text is retargeted too. Where a comment says "the engine this
    // machine RUNS provides `X`" that prose is history and stays; where it carries the old ROW (a
    // commented-out `name: '@deepseek-ai/…'`) the quoted name is the thing that must not survive as
    // the removed package. Both quote characters are handled — these files use `'` for YAML scalars
    // and `` ` `` for prose — and a scalar that runs past the end of its line is skipped.
    if (!scalarSpansLines(line, code.length)) {
      for (const quote of ["'", '"', '`']) {
        if (!nextComment.includes(`${quote}${from}`)) continue;
        lineChanged += nextComment.split(`${quote}${from}`).length - 1;
        nextComment = nextComment.split(`${quote}${from}`).join(`${quote}${to}`);
      }
    }
    if (lineChanged === 0) return line;
    changed += lineChanged;
    return nextCode + nextComment;
  }).join('\n');
  return { text: out, changed };
}

// ── the managed block (the converter's own convention, matched by its own regexes) ───────────
const BLOCK_ID = 'preset-rows';
const MARKER_BEGIN = `# <<< ${BLOCK_ID}: BEGIN managed block — written by `
  + 'scripts/make-preset-rows.mjs, do not hand-edit <<<';
const MARKER_END = `# <<< ${BLOCK_ID}: END managed block <<<`;
const MARKER_BEGIN_RE = /^#\s*<<<\s*preset-rows:\s*BEGIN managed block\b/;
const MARKER_END_RE = /^#\s*<<<\s*preset-rows:\s*END managed block\b/;
/**
 * The exact provenance comment the converter writes into its own block. It exists so a reader of
 * the staged patch layer can tell "this block came from the converter, unchanged" from "somebody
 * edited it here". A mismatch is a REFUSAL, not a warning: the block is generated, and a
 * hand-edited generated block is the failure this whole mechanism is designed to make loud.
 */
// THE CONVERTER SPELLS ITS PROVENANCE LINE TWO WAYS, AND ONLY ONE OF THEM MATCHED HERE.
//
//   `--install` mode (scripts/make-preset-rows.mjs:386):
//     # Written by `node scripts/make-preset-rows.mjs --install`; `--check` fails when ...
//   file mode (scripts/make-preset-rows.mjs:304):
//     # Written by `scripts/make-preset-rows.mjs`. Edit that converter, not this file; `--check`
//
// The old value here was the SECOND verbatim, so a block produced by the FIRST did not match: measured
// 2026-10-05, that single `node ` inside the backticks made this tool REFUSE to splice over the repo's own
// converter-generated block, with "a block without that line was hand-edited, and installing over it would
// hide that". Neither was true — the block WAS generated by the converter, and the refusal hid nothing but
// a spelling. A guard that rejects the tool's own output is worse than no guard, because it looks like
// diligence while blocking the correct action.
//
// Matching on the converter's FILENAME accepts both spellings and nothing else: the check exists to avoid
// silently overwriting a HAND-EDITED block, and a body line naming the converter is the converter's own
// statement of origin. Every call site reads `.includes(ORIGIN_LINE)`.
const ORIGIN_LINE = 'make-preset-rows.mjs';

const indent = (lines) => lines.map((line) => (line.length > 0 ? `  ${line}` : line));
const eolOf = (text) => (text.includes('\r\n') ? '\r\n' : '\n');
const sha256 = (text) => createHash('sha256').update(text, 'utf8').digest('hex');

// ── `!!js` in a FLOW emission ────────────────────────────────────────────────────────────────
// WHY THIS IS RE-IMPLEMENTED RATHER THAN CALLED. `scripts/make-preset-rows.mjs` has a
// `--print-block` mode that does exactly this, but it takes its presets from `--presets-dir`; the
// rows this module must wire are the ones generated from the STAGED `.agent-presets`, and calling
// `--print-block` against that directory would re-run the converter a second time over the same
// source. Worse, it would put the composition in two places that can disagree. So the emission is
// done here, from the converter's OWN OUTPUT, and `tests/stage-home/` proves the result is
// byte-identical to `--print-block` for the same input. If that proof ever fails, the wiring is
// wrong even though the rows would still compose.
//
// The measured hazard being worked around (FINDINGS.md, 2026-09-28): `YAML.stringify(value, {
// customTags })` writes `!!js undefined` for every expression — `jsTag.stringify` is called once
// with the `{ __js }` wrapper and its return value is DISCARDED. So the wrapper is swapped for a
// unique sentinel STRING, `stringify` runs, and the sentinel is substituted back to
// `!!js <source text>` textually. Only that keeps the expression byte-identical to the source.
const SENTINEL_PREFIX = '__DSH_JSEXPR_';
const FLOW_LINE_WIDTH = 160;
const PLAIN_UNSAFE_FIRST = /^[\s\-?:,[\]{}#&*!|>'"%@`]/;
const PLAIN_RESERVED = /^(?:true|false|null|yes|no|on|off|~|y|n|True|False|Null|TRUE|FALSE|NULL|Yes|No|On|Off|YES|NO|ON|OFF|Y|N)$/;
/** Characters that may not appear in a plain scalar inside a flow collection (YAML 1.2 §7.3.3). */
const FLOW_INDICATORS = /[,[\]{}]/;

const isJsValue = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v)
  && typeof v.__js === 'string';

function plainSafe(text, style = 'flow') {
  if (typeof text !== 'string' || text.length === 0) return false;
  if (/[\n\r\t]/.test(text)) return false;
  if (/^\s|\s$/.test(text)) return false;
  if (PLAIN_UNSAFE_FIRST.test(text)) return false;
  if (text.includes(': ') || text.endsWith(':') || text.includes(' #')) return false;
  if (style === 'flow' && FLOW_INDICATORS.test(text)) return false;
  if (PLAIN_RESERVED.test(text)) return false;
  return true;
}

const singleQuote = (text) => `'${text.replace(/'/g, "''")}'`;

/**
 * Whether a `!!js` source text can be written as a PLAIN scalar in a flow collection.
 *
 * Re-exported because a CORRECT emission is not always a byte-identical one: an expression carrying
 * a flow indicator (`,` `[` `]` `{` `}`) is single-quoted, and inside a single-quoted YAML scalar an
 * inner `'` is doubled — so
 *   `process.getBuiltinModule('node:url').fileURLToPath(new URL('skills/', baseUrl))`
 * legitimately reaches the file with every `'` doubled. The VALUE is identical and the round-trip
 * check proves it; the BYTES are not, and any test that demands they are is testing the wrong thing.
 */
export const isPlainSafeFlow = (text) => plainSafe(text, 'flow');

function replaceJsWithSentinels(node, exprs) {
  if (isJsValue(node)) {
    const index = exprs.push(node.__js) - 1;
    return `${SENTINEL_PREFIX}${String(index).padStart(4, '0')}__`;
  }
  if (Array.isArray(node)) return node.map((child) => replaceJsWithSentinels(child, exprs));
  if (node && typeof node === 'object') {
    return Object.fromEntries(Object.entries(node).map(([k, v]) => [k, replaceJsWithSentinels(v, exprs)]));
  }
  return node;
}

function restoreJsText(yamlText, exprs) {
  let text = yamlText;
  for (let i = exprs.length - 1; i >= 0; i -= 1) {
    const sentinel = `${SENTINEL_PREFIX}${String(i).padStart(4, '0')}__`;
    const pattern = new RegExp(`!!str ${sentinel}|'${sentinel}'|"${sentinel}"|${sentinel}`, 'g');
    text = text.replace(pattern, `!!js ${plainSafe(exprs[i]) ? exprs[i] : singleQuote(exprs[i])}`);
  }
  return text;
}

/** Every `!!js` source text in a parsed value, in document order — the parity check's input. */
export function collectJsTexts(node, acc = []) {
  if (isJsValue(node)) acc.push(node.__js);
  else if (Array.isArray(node)) node.forEach((child) => collectJsTexts(child, acc));
  else if (node && typeof node === 'object') Object.values(node).forEach((child) => collectJsTexts(child, acc));
  return acc;
}

/** The same patch entries, re-emitted in FLOW style — the shape a flow-collection patch file needs. */
export function entriesToFlowLines(entries) {
  const exprs = [];
  const wrapped = replaceJsWithSentinels(entries, exprs);
  return wrapped.map((entry) => restoreJsText(YAML.stringify(entry, {
    flow: true,
    aliasDuplicateObjects: false,
    lineWidth: FLOW_LINE_WIDTH,
  }), exprs).replace(/\n$/, ''));
}

/**
 * Build the managed-block body from the converter's OWN output.
 *
 * NOT re-derived from the presets: the converter is the single source of truth for what the rows
 * are — including the `!!js` handling `YAML.stringify` cannot do, measured and recorded in
 * FINDINGS.md — so taking its output as the input is the only way the two artefacts cannot drift.
 *
 * WHY THE BODY IS RE-EMITTED IN FLOW STYLE. The standalone artefact is a BLOCK sequence (`- insert:`
 * at column 0); a profile's `cordis.patch.yml` is one FLOW collection (`[ { … }, … ]`), and a block
 * collection inside a flow collection is a parse error — measured against the real file and
 * recorded in the converter's own commentary. So the parsed entries are re-emitted in flow style
 * with `!!js` kept as source text. The two forms are then proved to hold the SAME patch entries by
 * parsing both, which is the strongest claim a different serialisation allows.
 */
export function blockFromGenerated(generatedText) {
  const problems = [];
  const header = [];
  const blockBody = [];
  let seenEntry = false;
  for (const line of generatedText.split(/\r?\n/)) {
    if (!seenEntry && (line.startsWith('#') || line === '')) {
      header.push(line);
      continue;
    }
    seenEntry = true;
    blockBody.push(line);
  }
  while (blockBody.length > 0 && blockBody[blockBody.length - 1] === '') blockBody.pop();

  if (!header.some((l) => l.includes(ORIGIN_LINE))) {
    problems.push(
      `the converter's output does not carry its own provenance line (expected a line containing `
      + `"${ORIGIN_LINE}"). Refusing to install rows whose origin cannot be stated.`,
    );
  }
  if (!header.some((l) => l.includes('GENERATED'))) {
    problems.push('the converter\'s output does not say GENERATED — it is not the artefact this '
      + 'module is willing to install');
  }
  if (blockBody.length === 0) problems.push('the converter\'s output carries no patch entries');

  let parsed = null;
  try {
    parsed = YAML.parse(generatedText, PARSE_OPTIONS);
  } catch (e) {
    problems.push(`the converter's output does not parse: ${e.message}`);
  }
  if (parsed !== null && !Array.isArray(parsed)) {
    problems.push('the converter\'s output is not a top-level YAML sequence of patch entries');
  }
  // The artefact's top-level sequence IS the patch-entry list the block must carry — the converter
  // writes one `- insert:` entry per preset. `!!js` expressions survive here as `{ __js }` wrappers,
  // which is exactly the input the flow emission below needs. The artefact's BLOCK text cannot be
  // reused directly (a block collection inside a flow collection is a parse error), so the entries
  // are re-emitted; the parity check below is what makes "the same entries" a claim instead of an
  // assumption.
  const entries = Array.isArray(parsed) ? parsed : [];
  const rowIds = entries
    .flatMap((entry) => (Array.isArray(entry?.insert) ? entry.insert : []))
    .filter((row) => row && typeof row === 'object' && typeof row.id === 'string')
    .map((row) => row.id);
  if (entries.length === 0) problems.push('the converter\'s output parsed to an empty entry list');
  if (rowIds.length === 0) {
    problems.push(`the converter's output carries ${entries.length} patch entry(ies) but no inserted `
      + 'row id; this module will not install rows it cannot name');
  }
  if (problems.length > 0) return { ok: false, problems, lines: [], entries, rowIds, rows: [], exprs: 0 };

  // THE BLOCK CARRIES THE ARTEFACT'S OWN PROVENANCE COMMENTS, PREPENDED.
  //
  // WHY: the committed block must be able to say where it came from — `spliceManagedBlock` refuses
  // to overwrite a block that does not carry `ORIGIN_LINE`, because a generated block without it was
  // hand-edited. The generated artefact carries those lines in its file HEADER (`# Written by …`,
  // `#   presets/<name>/agent.cordis.yml  rows=N  sha256=…`), and they are exactly what a reader of
  // the staged patch needs to re-derive the rows. So the header's provenance lines become the block's
  // leading comment lines, which is also the shape the converter's own repo-side block has.
  const headerComments = header.filter((line) => line.includes(ORIGIN_LINE)
    || /#\s+presets[/\\]/.test(line));

  // The flow emission, then its own proof: re-parse the body wrapped as a flow sequence and require
  // it to hold the same entries as the artefact, `!!js` source text included.
  let lines;
  const exprs = collectJsTexts(entries);
  try {
    lines = [...headerComments, ...entriesToFlowLines(entries).flatMap((text) => `${text},`.split('\n'))];
  } catch (e) {
    return { ok: false, problems: [`could not re-emit the entries in flow style: ${e.message}`], entries, rowIds, exprs: 0 };
  }
  if (/!!js +undefined\b/.test(lines.join('\n'))) {
    problems.push('the flow emission contains `!!js undefined` — an expression was lost in emission');
  }
  let flowParsed = null;
  try {
    flowParsed = YAML.parse(`[\n${lines.join('\n')}\n]\n`, PARSE_OPTIONS);
  } catch (e) {
    problems.push(`the flow block body does not parse: ${e.message}`);
  }
  if (Array.isArray(flowParsed)) {
    if (flowParsed.length !== entries.length) {
      problems.push(`the flow block body holds ${flowParsed.length} patch entry(ies) but the `
        + `artefact's body holds ${entries.length}; the emission is not the artefact`);
    }
    const flowRows = flowParsed.flatMap((entry) => (Array.isArray(entry?.insert) ? entry.insert : []))
      .filter((row) => row && typeof row === 'object' && typeof row.id === 'string')
      .map((row) => row.id);
    if (flowRows.join(',') !== rowIds.join(',')) {
      problems.push(`the flow emission's rows (${flowRows.join(',')}) are not the artefact's rows `
        + `(${rowIds.join(',')})`);
    }
    const emitted = collectJsTexts(flowParsed);
    if (emitted.length !== exprs.length) {
      problems.push(`${exprs.length} \`!!js\` expression(s) were carried but ${emitted.length} were `
        + 'read back from the flow body');
    }
    for (let i = 0; i < Math.min(emitted.length, exprs.length); i += 1) {
      if (emitted[i] !== exprs[i]) {
        problems.push(`expression ${i + 1} changed in the flow emission: `
          + `${JSON.stringify(exprs[i])} -> ${JSON.stringify(emitted[i])}`);
      }
    }
    // `!!js` source text that is plain-safe in flow style must survive byte-identically.
    const bodyText = lines.join('\n');
    const notByteIdentical = exprs.filter((e) => plainSafe(e) && !bodyText.includes(e));
    if (notByteIdentical.length > 0) {
      problems.push(`${notByteIdentical.length} plain-safe expression(s) are not byte-identical in `
        + `the flow body: ${notByteIdentical.slice(0, 3).map(JSON.stringify).join(', ')}`);
    }
  }
  return { ok: problems.length === 0, problems, lines, entries, rowIds, exprs: exprs.length, blockLines: blockBody.length };
}

/**
 * Splice the managed block into a profile patch file.
 *
 * The file is ONE YAML FLOW collection (`[ { … }, { … } ]`), so the block goes before the final
 * `]`, exactly where the converter puts it in the repo copy. `mode` is `append` (no markers),
 * `replace` (markers present) or `noop` (already byte-identical). Everything the splice does is
 * proved before it is returned: the text outside the block region must be byte-identical, the
 * result must parse, and the entry count must be `present - oldBlock + newBlock`.
 */
export function spliceManagedBlock(text, bodyLines) {
  const problems = [];
  const eol = eolOf(text);
  const lines = text.split(eol);
  const blockLines = indent([MARKER_BEGIN, ...bodyLines, MARKER_END]);
  const findMarkers = (ls) => {
    const begins = [];
    const ends = [];
    ls.forEach((line, i) => {
      const trimmed = line.trim();
      if (MARKER_BEGIN_RE.test(trimmed)) begins.push(i);
      if (MARKER_END_RE.test(trimmed)) ends.push(i);
    });
    return { begins, ends };
  };

  let current;
  try {
    current = YAML.parse(text, PARSE_OPTIONS);
  } catch (e) {
    return { problems: [`the target profile patch does not parse: ${e.message}`] };
  }
  if (!Array.isArray(current) || current.length === 0) {
    return {
      problems: [`the target profile patch is not a non-empty top-level YAML sequence (got `
        + `${current === null ? 'null' : Array.isArray(current) ? 'empty sequence' : typeof current}); `
        + 'a profile patch file is a flow sequence of patch entries'],
    };
  }

  const { begins, ends } = findMarkers(lines);
  let mode;
  let oldBegin = null;
  let oldEnd = null;
  if (begins.length === 0 && ends.length === 0) {
    mode = 'append';
    const closing = lines.reduce((acc, line, i) => (line.trim() === ']' ? i : acc), -1);
    if (closing < 0) {
      return { problems: ['no final `]` line found, so the block has nowhere to be appended'] };
    }
    oldEnd = closing - 1;
  } else if (begins.length === 1 && ends.length === 1 && begins[0] < ends[0]) {
    mode = 'replace';
    oldBegin = begins[0];
    oldEnd = ends[0];
  } else {
    return {
      problems: [`the \`${BLOCK_ID}\` markers are unbalanced or duplicated (BEGIN ${begins.length}, `
        + `END ${ends.length}). Refusing to guess which region is ours; fix the markers by hand `
        + '(or remove both) and run again.'],
    };
  }

  const oldBody = oldBegin === null ? [] : lines.slice(oldBegin + 1, oldEnd);
  /**
   * How many top-level patch entries the COMMITTED block owns, for the `replace` case's comparison.
   *
   * DERIVED FROM THE BODY'S OWN ENTRY LINES, not from `YAML.parse(oldBody).length`. The block body
   * is a flow collection's interior whose first line is `{` — the opening brace is not repeated, so
   * `YAML.parse` reads the whole body as ONE entry however many entries it holds. Counting lines that
   * begin an entry at a flow-collection boundary is the one reading that does not depend on that
   * grouping: every entry line is either the first line of the body or a line whose previous line
   * ended at depth 0.
   *
   * DEPTH IS CLAMPED AT ZERO, and `i` is advanced on every path. Both are required: an entry line
   * ends at depth 0 (`… }] },`), so the trailing characters walk it negative, and a negative depth
   * then swallows the `depth === 0` test below and every following line for ever. The first version
   * of this helper never terminated and the test suite had to be killed at the 600 s cap (measured
   * 2026-10-05).
   */
  const countBlockEntries = (body) => {
    let depth = 0;
    let count = 0;
    for (const line of body) {
      const trimmed = line.trim();
      if (trimmed.length === 0 || trimmed.startsWith('#')) continue;
      if (depth === 0) count += 1;
      let i = 0;
      while (i < line.length) {
        const ch = line[i];
        if (ch === "'") {
          i += 1;
          while (i < line.length) {
            if (line[i] === "'") {
              if (line[i + 1] === "'") i += 2; else { i += 1; break; }
            } else i += 1;
          }
          continue;
        }
        if (ch === '"') {
          i += 1;
          while (i < line.length && line[i] !== '"') { i += line[i] === '\\' ? 2 : 1; }
          i += 1;
          continue;
        }
        if (ch === '[' || ch === '{') depth += 1;
        else if (ch === ']' || ch === '}') depth = Math.max(0, depth - 1);
        else if (ch === ',') { /* a separator never changes depth; kept explicit for readers */ }
        i += 1;
      }
    }
    return count;
  };
  let oldCount = null;
  if (oldBegin !== null) {
    try {
      const parsed = YAML.parse(`[\n${oldBody.join('\n')}\n]\n`, PARSE_OPTIONS);
      if (!Array.isArray(parsed)) throw new Error('not a sequence');
      oldCount = countBlockEntries(oldBody);
      if (oldCount === 0) throw new Error('no entry line found in the block body');
    } catch {
      return {
        problems: ['the lines between the markers do not parse as a flow sequence of patch entries. '
          + 'Repair the block by hand, or delete both marker lines and run again to write it fresh.'],
      };
    }
    if (!oldBody.some((l) => l.includes(ORIGIN_LINE))) {
      return {
        problems: [`the committed \`${BLOCK_ID}\` block does not carry the converter's provenance `
          + `line (a line containing "${ORIGIN_LINE}"). This block is generated; a block without `
          + 'that line was hand-edited, and installing over it would hide that. Refusing.'],
      };
    }
  }

  const nextLines = mode === 'append'
    ? [...lines.slice(0, oldEnd + 1), '', ...blockLines, ...lines.slice(oldEnd + 1)]
    : [...lines.slice(0, oldBegin), ...blockLines, ...lines.slice(oldEnd + 1)];
  const next = nextLines.join(eol);
  if (next === text) {
    return { mode: 'noop', text, eol, currentEntries: current.length, blockEntries: bodyLines.length };
  }

  const outsideOf = (all, begin, end) => (begin === null
    ? all.join(eol)
    : [...all.slice(0, begin), ...all.slice(end + 1)].join(eol));
  const regionStart = mode === 'append' ? oldEnd + 1 : oldBegin;
  const regionLength = blockLines.length + (mode === 'append' ? 1 : 0);
  const nextEnd = regionStart + regionLength - 1;
  const before = outsideOf(lines, oldBegin, oldEnd);
  const after = outsideOf(nextLines, regionStart, nextEnd);
  if (sha256(before) !== sha256(after)) {
    return { problems: ['internal check failed: the text outside the block would change; nothing was written'] };
  }

  let composed;
  try {
    composed = YAML.parse(next, PARSE_OPTIONS);
  } catch (e) {
    return { problems: [`the result would not parse, so it was not written: ${e.message}`] };
  }
  if (!Array.isArray(composed)) {
    return { problems: ['internal check failed: the result did not parse to a sequence; nothing was written'] };
  }
  // THE ENTRY-COUNT CHECK IS NOT `current.length - old + bodyLines.length`, AND THE REASON IS
  // MEASURED. A profile patch entry may insert a row whose `config` nests its own row list, and
  // `YAML.parse` counts that whole entry as ONE top-level element while the block body counts it
  // WITH its nested rows. The first implementation of this compared `current.length` against
  // `composed.length` and refused a CORRECT splice as "7 vs 1331" on the real
  // `~/.dsh/profiles/web/cordis.patch.yml` (2026-10-05). What is checked instead is the only thing
  // that can be checked honestly here: the bytes OUTSIDE the block are identical (proved above by
  // sha256), the result still parses, and the block's generated entries are exactly where the block
  // was spliced — they start at index `before` and there are `bodyLines.length` of them, while every
  // other top-level entry is unchanged.
  // THE ENTRY COUNT IS NOT A SIMPLE FORMULA, AND BOTH FAILURES OF THIS CHECK WERE MEASURED.
  //
  //   2026-10-05, attempt 1 — `current.length + bodyLines.length` was compared. The real file has 4
  //   top-level entries and the block had 1,327 body lines, so a CORRECT splice was refused as
  //   "7 vs 1331". A count of LINES is not a count of ENTRIES.
  //   2026-10-05, attempt 2 — the same file, with `bodyLines.length` still used: "expected 4 already
  //   in the file plus 1327 generated". The block's body is ONE flow collection whose entries are
  //   `… }, { … }, { … }`; because the opening `{` is not repeated on its own line the parser reads
  //   the whole joined body as ONE top-level element.
  //
  // The honest checks are therefore: the text outside the block is byte-identical (sha256, above);
  // the result parses to a sequence; the entries that were already in the file are unchanged and in
  // place; and every generated entry appears in the result, compared as data. Nothing here depends
  // on knowing how the YAML parser chooses to group the block.
  const sameEntry = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  let generatedEntries;
  try {
    generatedEntries = YAML.parse(`[\n${bodyLines.join('\n')}\n]\n`, PARSE_OPTIONS);
  } catch (e) {
    return {
      problems: [`the generated block does not parse on its own (${e.message}); nothing was written`],
    };
  }
  if (!Array.isArray(generatedEntries) || generatedEntries.length === 0) {
    return {
      problems: ['internal check failed: the generated block does not parse to a non-empty '
        + 'sequence of patch entries; nothing was written'],
    };
  }
  if (mode === 'append') {
    const beforeEntries = composed.slice(0, current.length);
    if (!sameEntry(beforeEntries, current)) {
      return {
        problems: ['internal check failed: the entries that were already in the file are not the '
          + 'same entries, in the same order, after the splice; nothing was written'],
      };
    }
  } else {
    // `replace` mode: the block's own lines are the only thing that moved, so compare everything
    // ELSE. The block contributes `generatedEntries.length` top-level entries wherever the parser
    // chooses to group them, which is exactly why the comparison is done on the parsed data.
    const outsideEntries = [];
    for (let i = 0, j = 0; i < composed.length; i += 1) {
      if (j < generatedEntries.length && sameEntry(composed[i], generatedEntries[j])) {
        j += 1;
        continue;
      }
      outsideEntries.push(composed[i]);
    }
    const expectedOutside = current.slice(0, current.length - (oldCount ?? 0));
    if (!sameEntry(outsideEntries, expectedOutside)) {
      return {
        problems: ['internal check failed: the entries outside the block are not the same entries, '
          + 'in the same order, after the splice; nothing was written'],
      };
    }
  }
  let contributed = 0;
  for (const entry of generatedEntries) {
    if (!composed.some((c) => sameEntry(c, entry))) {
      const id = entry?.insert?.[0]?.id ?? '(unknown id)';
      return {
        problems: [`internal check failed: the generated entry '${id}' is not in the composed `
          + 'result; nothing was written'],
      };
    }
    contributed += 1;
  }
  return {
    mode,
    text: next,
    eol,
    currentEntries: current.length,
    generatedEntries: contributed,
    blockLines: bodyLines.length,
    expectedEntries: composed.length,
    outsideSha: sha256(after),
  };
}

// ── the real assertion (run in BOTH build and --check mode) ──────────────────────────────────
/**
 * Assert the SWITCH-ENGINE PRECONDITION 2 predicate over a staged home, reproduced literally:
 * preset files and profile patches must exist, must name the candidate's package per slot, and
 * must not name the removed one outside a comment.
 *
 * `slots` is the detection result, so the names checked are the candidate's own — this function
 * never contains the answer.
 */
export function assertStagedHome(outDir, slots) {
  const checks = [];
  const problems = [];
  const modern = Object.fromEntries(slots.decisions.map((d) => [d.id, d.side === 'modern' ? d.decides : null]));
  const legacy = Object.fromEntries(slots.decisions.map((d) => [d.id, d.side === 'legacy' ? d.decides : null]));

  const presetFiles = listPresetFiles(outDir);
  const patchFiles = listProfilePatches(outDir);
  if (presetFiles.length === 0) problems.push(`no preset file exists at ${outDir}\\${PRESET_DIR_NAME}\\*\\${PRESET_FILE_NAME}`);
  if (patchFiles.length === 0) problems.push(`no profile patch exists at ${outDir}\\profiles\\*\\cordis.patch.yml`);

  // ── the workflow runtime slot, over the preset files ────────────────────────────────────────
  // THE REMOVED NAME COMES FROM THE SLOT'S OWN NAME LIST, never from a literal in this file. The
  // list is `[modern, legacy]` by construction, so the name the candidate did NOT provide is the
  // one that must not appear — and if BOTH are absent the slot is undecidable and the caller never
  // gets here (the detection refuses first).
  const ptc = modern['workflow-runtime'] ?? '@deepseek-ai/dsh-workflow-ptc';
  const oldPtc = legacy['workflow-runtime']
    ?? slotOtherName('workflow-runtime', ptc);
  let ptcRows = 0;
  let oldPtcCode = 0;
  let oldPtcComment = 0;
  for (const file of presetFiles) {
    const text = readFileSync(file, 'utf8');
    ptcRows += countRefs(text, ptc).code;
    if (oldPtc) {
      const old = countRefs(text, oldPtc);
      oldPtcCode += old.code;
      oldPtcComment += old.comment;
    }
  }
  if (ptcRows === 0) problems.push(`no preset names '${ptc}' as a composition row`);
  if (oldPtc && oldPtcCode > 0) {
    problems.push(`${oldPtcCode} preset row(s) still name the REMOVED '${oldPtc}' outside a comment`);
  }

  // ── the preset registry slot, over the profile patches ─────────────────────────────────────
  const reg = modern['preset-registry'] ?? '@deepseek-ai/dsh-agent-preset-registry';
  const oldReg = legacy['preset-registry'] ?? slotOtherName('preset-registry', reg);
  let regRows = 0;
  let oldRegCode = 0;
  let oldRegComment = 0;
  for (const file of patchFiles) {
    const text = readFileSync(file, 'utf8');
    regRows += countRefs(text, reg).code;
    if (oldReg) {
      const old = countRefs(text, oldReg);
      oldRegCode += old.code;
      oldRegComment += old.comment;
    }
  }
  if (regRows === 0) problems.push(`no profile patch names '${reg}' as a composition row`);
  if (oldReg && oldRegCode > 0) {
    problems.push(`${oldRegCode} profile patch row(s) still name the REMOVED '${oldReg}' outside a comment`);
  }

  // ── the preset ROWS really reached the layer the engine loads ──────────────────────────────
  const profilePatches = Object.fromEntries(patchFiles.map((f) => [f, readFileSync(f, 'utf8')]));
  const rowProblems = assertPresetRowsReachComposition(outDir, profilePatches);
  problems.push(...rowProblems);

  checks.push(
    { check: 'preset files present', value: presetFiles.length, ok: presetFiles.length > 0 },
    { check: `preset rows naming ${ptc}`, value: ptcRows, ok: ptcRows > 0 },
    { check: `preset rows naming the removed ${oldPtc ?? '(none on this side)'} (outside comments)`, value: oldPtcCode, ok: oldPtcCode === 0 },
    { check: `the removed ${oldPtc ?? '(none on this side)'} inside comments (not a dependency)`, value: oldPtcComment, ok: true },
    { check: 'profile patches present', value: patchFiles.length, ok: patchFiles.length > 0 },
    { check: `profile patch rows naming ${reg}`, value: regRows, ok: regRows > 0 },
    { check: `profile patch rows naming the removed ${oldReg ?? '(none on this side)'} (outside comments)`, value: oldRegCode, ok: oldRegCode === 0 },
    { check: `the removed ${oldReg ?? '(none on this side)'} inside comments (not a dependency)`, value: oldRegComment, ok: true },
  );
  return {
    ok: problems.length === 0,
    problems,
    checks,
    presetFiles,
    patchFiles,
    counts: { ptcRows, oldPtcCode, oldPtcComment, regRows, oldRegCode, oldRegComment },
    names: { workflowRuntime: ptc, removedWorkflowRuntime: oldPtc, presetRegistry: reg, removedPresetRegistry: oldReg },
  };
}

/** The other name in a slot's own candidate list — the one this candidate does NOT provide. */
function slotOtherName(slotId, provided) {
  const slot = SLOTS.find((s) => s.id === slotId);
  if (!slot) return null;
  const others = slot.names.filter((name) => name !== provided);
  return others.length === 1 ? others[0] : (others[0] ?? null);
}

/**
 * The rows must sit in a layer the ENGINE LOADS — the profile's own `cordis.patch.yml` — not in a
 * loose file beside it (FINDINGS.md item 2). This checks the generated block is inside a real
 * profile patch and that its entries are `insert:` entries with a non-empty `plugins` array.
 */
function assertPresetRowsReachComposition(outDir, patchTexts) {
  const problems = [];
  const wanted = expectedPresetIds(outDir);
  const found = [];
  for (const [file, text] of Object.entries(patchTexts)) {
    let parsed;
    try {
      parsed = YAML.parse(text, PARSE_OPTIONS);
    } catch (e) {
      problems.push(`${relative(outDir, file)} does not parse: ${e.message}`);
      continue;
    }
    if (!Array.isArray(parsed)) continue;
    const ids = parsed.flatMap((entry) => (Array.isArray(entry?.insert) ? entry.insert : []))
      .filter((row) => typeof row?.id === 'string' && row.id.startsWith('preset-'))
      .map((row) => row.id);
    for (const id of ids) found.push({ id, file: relative(outDir, file) });
  }
  if (wanted.length === 0) {
    problems.push(`no ${PRESET_FILE_NAME} under ${outDir}\\${PRESET_DIR_NAME}\\* — there is nothing to `
      + 'convert into rows, which is a refusal rather than an empty success');
    return problems;
  }
  const foundIds = new Set(found.map((f) => f.id));
  const missing = wanted.filter((id) => !foundIds.has(id));
  if (missing.length > 0) {
    problems.push(`${missing.length} preset row(s) are NOT in any profile patch layer the engine `
      + `loads: ${missing.join(', ')}. Present: ${[...foundIds].join(', ') || '(none)'}. A loose file `
      + 'in the profile directory is not one of the layers (`@deepseek-ai/dsh-app-boot` `profile.js`: '
      + 'bundles first, then the profile\'s own cordis.patch.yml).');
  }
  // Every row must carry a non-empty plugin list, or it registers a preset with no capability.
  for (const [file, text] of Object.entries(patchTexts)) {
    let parsed;
    try {
      parsed = YAML.parse(text, PARSE_OPTIONS);
    } catch { continue; }
    if (!Array.isArray(parsed)) continue;
    for (const entry of parsed) {
      for (const row of (Array.isArray(entry?.insert) ? entry.insert : [])) {
        if (typeof row?.id !== 'string' || !row.id.startsWith('preset-')) continue;
        const plugins = row?.config?.plugins;
        if (!Array.isArray(plugins) || plugins.length === 0) {
          problems.push(`${row.id} in ${relative(outDir, file)} has no config.plugins array — a `
            + 'preset row with no plugins mounts as an empty agent');
        }
        if (row.name !== '@deepseek-ai/dsh-agent-preset') {
          problems.push(`${row.id} in ${relative(outDir, file)} names '${row.name}' as its plugin, not `
            + "'@deepseek-ai/dsh-agent-preset'");
        }
      }
    }
  }
  return problems;
}

/** The `preset-<name>` ids the staged presets imply, from the staged preset directories. */
function expectedPresetIds(outDir) {
  return listPresetFiles(outDir)
    .map((file) => file.split(sep))
    .map((parts) => parts[parts.length - 2])
    .sort()
    .map((name) => `preset-${name}`);
}

function listPresetFiles(outDir) {
  const root = join(outDir, PRESET_DIR_NAME);
  let entries = [];
  try {
    entries = readdirSync(root, { withFileTypes: true });
  } catch {
    return [];
  }
  return entries
    .filter((e) => e.isDirectory())
    .map((e) => join(root, e.name, PRESET_FILE_NAME))
    .filter((f) => existsSync(f))
    .sort();
}

function listProfilePatches(outDir) {
  const root = join(outDir, 'profiles');
  let entries = [];
  try {
    entries = readdirSync(root, { withFileTypes: true });
  } catch {
    return [];
  }
  return entries
    .filter((e) => e.isDirectory())
    .map((e) => join(root, e.name, 'cordis.patch.yml'))
    .filter((f) => existsSync(f))
    .sort();
}

// ── the build ────────────────────────────────────────────────────────────────────────────────
function walkFiles(dir, acc = []) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return acc;
  }
  for (const entry of entries) {
    const p = join(dir, entry.name);
    if (entry.isDirectory()) walkFiles(p, acc);
    else if (entry.isFile()) acc.push(p);
  }
  return acc;
}

/** sha256 of every file in the staged tree, keyed by POSIX relative path, sorted. */
function treeHashes(outDir) {
  const files = walkFiles(outDir).sort();
  const hashes = {};
  for (const file of files) {
    const rel = relative(outDir, file).split(sep).join('/');
    if (rel === MANIFEST_NAME) continue;
    hashes[rel] = sha256(readFileSync(file, 'utf8'));
  }
  return hashes;
}

/**
 * Build the staged home into `outDir`.
 *
 * The ordering is not cosmetic: everything the ASSERTION reads is rewritten before the assertion
 * runs, and the assertion runs in both modes. A `--check` that skipped the assertion would be a
 * comparison without a standard.
 */
export function buildStagedHome(opts) {
  const out = {
    mode: opts.check ? 'check' : 'build',
    from: opts.from,
    candidate: opts.candidate,
    out: opts.out,
    profile: opts.profile,
    slots: null,
    copied: [],
    skipped: [],
    links: [],
    rewrites: [],
    block: null,
    assertion: null,
    manifest: null,
    problems: [],
    notes: [],
  };

  // ── 0. inputs ───────────────────────────────────────────────────────────────────────────────
  if (!existsSync(opts.from) || !statSync(opts.from).isDirectory()) {
    out.problems.push(`--from ${opts.from} is not a directory`);
    return out;
  }
  if (!existsSync(opts.candidate) || !statSync(opts.candidate).isDirectory()) {
    out.problems.push(`--candidate ${opts.candidate} is not a directory`);
    return out;
  }

  // ── 1. what the candidate actually provides ────────────────────────────────────────────────
  const slots = opts.slots
    ? detectSlotsFromList(opts.slots.names, opts.slots.label)
    : detectSlots(join(opts.candidate, 'node_modules'));
  out.slots = slots;
  if (!slots.ok) {
    out.problems.push(...slots.problems);
    return out;
  }
  const modernOf = Object.fromEntries(slots.decisions.map((d) => [d.id, d.decides]));

  // ── 2. copy the config surface ─────────────────────────────────────────────────────────────
  // In check mode the build goes to a scratch directory and is compared; the real `--out` is never
  // written. A comparison that writes first cannot report drift.
  const target = opts.stageDir;
  mkdirSync(target, { recursive: true });

  // ── WHERE THE PROFILE PATCH LAYERS COME FROM, AND WHY IT CAN DIFFER FROM `--from` ─────────────
  //
  // MEASURED 2026-10-05. Staging the profile layers from the live home produced a composed tree in which
  // our `agent-preset-registry` entry (intent `{config:{default:"zabz"}}`) DID NOT APPLY, and the row
  // stayed at the upstream default `standard`. The cause is that the two copies of
  // `profiles/web/cordis.patch.yml` have diverged badly:
  //
  //   repo  `profiles/web/cordis.patch.yml`   1624 lines, 45 patch entries, declares the registry target
  //   live  `~/.dsh/profiles/web/cordis.patch.yml`  252 lines,  4 patch entries, last written 2026-09-20
  //
  // The live copy is not a different design; it is TWO WEEKS STALE. `scripts/check-version-coupled-
  // config.py` refuses to publish the profiles scope while the running engine lacks the 0.1.7 names, and
  // this repo has named them in that file since about 2026-09-20 — so every repo-side profile change in
  // that window (mesh placement, prefer-remote, the dispatch-hop timeouts, the provider targetHosts
  // default) was correctly SKIPPED and never reached this machine. The repo is authoritative: it is what
  // `sync.py` publishes the moment the names resolve, which is exactly what the switch makes true.
  //
  // So the staged home must carry the layers that will actually run AFTER the switch, not the stale ones
  // it is replacing. `--profiles-from <dir>` names a directory of `<profile>/cordis.patch.yml` to take
  // them from instead of `--from`.
  //
  // ONLY PROFILES THIS MACHINE ALREADY HAS are taken, which mirrors `sync.py` exactly — it iterates the
  // repo's profiles and reports `profile <name>: not present on this machine -- skipped` for the rest.
  // Staging a profile that does not exist here would add one, and that is not this tool's job.
  const profilesRoot = opts.profilesFrom ?? join(opts.from, 'profiles');
  const profilesSrc = profilesRoot;
  if (!existsSync(profilesSrc)) {
    out.problems.push(`${profilesSrc} has no profiles\\ directory — there is no config surface to stage`);
    return out;
  }
  if (opts.profilesFrom) {
    const onMachine = new Set(readdirSync(join(opts.from, 'profiles'), { withFileTypes: true })
      .filter((e) => e.isDirectory()).map((e) => e.name));
    const notHere = [];
    const kept = [];
    for (const e of readdirSync(profilesSrc, { withFileTypes: true })) {
      if (!e.isDirectory()) continue;
      if (onMachine.has(e.name)) kept.push(e.name);
      else notHere.push(e.name);
    }
    out.notes.push(`--profiles-from ${profilesSrc}: ${kept.length} profile(s) taken (${kept.sort().join(', ')}); `
      + `${notHere.length} skipped as not present on this machine (${notHere.sort().join(', ') || 'none'}) — the same rule sync.py applies`);
    out.profilesFromNote = { source: profilesSrc, taken: kept.sort(), skipped: notHere.sort() };
  }
  // When the profiles root is a repository (not a home), take only the profiles this machine has.
  const allowedProfiles = opts.profilesFrom
    ? new Set(readdirSync(join(opts.from, 'profiles'), { withFileTypes: true })
      .filter((e) => e.isDirectory()).map((e) => e.name))
    : null;
  const wantedProfiles = readdirSync(profilesSrc, { withFileTypes: true })
    .filter((e) => e.isDirectory()).map((e) => e.name)
    .filter((n) => allowedProfiles === null || allowedProfiles.has(n))
    .sort();
  if (wantedProfiles.length === 0) {
    out.problems.push(`${profilesSrc} holds no profile directory — an empty read is a refusal`);
    return out;
  }
  if (!wantedProfiles.includes(opts.profile)) {
    out.problems.push(`--profile ${opts.profile} does not exist under ${profilesSrc} `
      + `(found: ${wantedProfiles.join(', ')})`);
    return out;
  }

  for (const name of wantedProfiles) {
    const dirSrc = join(profilesSrc, name);
    const dirDst = join(target, 'profiles', name);
    mkdirSync(dirDst, { recursive: true });
    let present = 0;
    for (const fileName of PROFILE_FILES) {
      const src = join(dirSrc, fileName);
      if (!existsSync(src)) continue;
      copyFileSync(src, join(dirDst, fileName));
      out.copied.push(relative(target, join(dirDst, fileName)).split(sep).join('/'));
      present += 1;
    }
    // Anything else in the profile directory is either state, a backup, or a loose patch file that
    // no layer loads. All three are recorded, so "why is X not in the staged home" has an answer.
    for (const entry of readdirSync(dirSrc, { withFileTypes: true })) {
      const src = join(dirSrc, entry.name);
      if (entry.isDirectory()) {
        if (STATE_EXCLUDES.has(entry.name)) out.skipped.push({ path: relative(target, src).split(sep).join('/'), why: 'state' });
        else out.skipped.push({ path: relative(target, src).split(sep).join('/'), why: 'not part of the profile config whitelist' });
        continue;
      }
      if (PROFILE_FILES.includes(entry.name)) continue;
      out.skipped.push({
        path: relative(target, src).split(sep).join('/'),
        why: isBackup(entry.name) ? 'backup file' : 'not part of the profile config whitelist',
      });
    }
    // The out-of-tree module ANCHOR: `profiles/<name>/node_modules`, where pnpm put the profile's
    // own plugin bundles. Nine of the eleven bundles `profiles/web/package.json` names are
    // junctions from here, so without it the candidate composes a DIFFERENT tree (measured 185
    // rows instead of 193, with nine `skipping profile bundle` lines). Recreated as LINKS only.
    const anchorSrc = join(dirSrc, 'node_modules');
    if (existsSync(anchorSrc)) {
      linkTreeSkipping(new Set(['node_modules', '.pnpm']), anchorSrc, join(dirDst, 'node_modules'), 0, out);
    }
  }

  // `profiles/node_modules` — the shared anchor the engine also resolves through, and the tree
  // whose junctions are the 127,970-file trap. Same treatment: links reproduced, nothing followed.
  const sharedAnchor = join(profilesSrc, 'node_modules');
  if (existsSync(sharedAnchor)) {
    linkTreeSkipping(new Set(['node_modules', '.pnpm']), sharedAnchor, join(target, 'profiles', 'node_modules'), 0, out);
  }

  const presetsSrc = join(opts.from, PRESET_DIR_NAME);
  if (existsSync(presetsSrc)) {
    try {
      const { copied, skippedEntries } = copyTreeSkipping(new Set(['node_modules']), presetsSrc, join(target, PRESET_DIR_NAME));
      out.copied.push(...copied.map((p) => relative(target, p).split(sep).join('/')));
      out.skipped.push(...skippedEntries.map((p) => ({
        path: relative(target, p).split(sep).join('/'), why: 'node_modules (measured 127,970-file junction trap)',
      })));
    } catch (e) {
      out.problems.push(`could not copy ${PRESET_DIR_NAME}: ${e.message}`);
      return out;
    }
  } else {
    out.notes.push(`${opts.from} has no ${PRESET_DIR_NAME}\\ directory; nothing to convert into preset rows`);
  }

  const settingsSrc = join(opts.from, 'settings.yaml');
  if (existsSync(settingsSrc)) {
    copyFileSync(settingsSrc, join(target, 'settings.yaml'));
    out.copied.push('settings.yaml');
  }

  // ── 3. rewrite the version-coupled names IN THE STAGED COPIES ONLY ─────────────────────────
  const presetFiles = listPresetFiles(target);
  for (const file of presetFiles) {
    const text = readFileSync(file, 'utf8');
    let next = text;
    for (const decision of slots.decisions) {
      const slot = SLOTS.find((s) => s.id === decision.id);
      if (slot.fileKind !== 'preset') continue;
      const to = modernOf[decision.id];
      for (const from of decision.candidates) {
        if (from === to) continue;
        const count = countRefs(next, from).code;
        if (count === 0) continue;
        const r = rewriteRefs(next, from, to);
        next = r.text;
        out.rewrites.push({ file: relative(target, file).split(sep).join('/'), slot: decision.id, from, to, count: r.changed });
      }
    }
    if (next !== text) writeFileSync(file, next, 'utf8');
  }
  const patchFiles = listProfilePatches(target);
  for (const file of patchFiles) {
    const text = readFileSync(file, 'utf8');
    let next = text;
    for (const decision of slots.decisions) {
      const slot = SLOTS.find((s) => s.id === decision.id);
      if (slot.fileKind === 'preset') continue;
      const to = modernOf[decision.id];
      for (const from of decision.candidates) {
        if (from === to) continue;
        const count = countRefs(next, from).code;
        if (count === 0) continue;
        const r = rewriteRefs(next, from, to);
        next = r.text;
        out.rewrites.push({ file: relative(target, file).split(sep).join('/'), slot: decision.id, from, to, count: r.changed });
      }
    }
    if (next !== text) writeFileSync(file, next, 'utf8');
  }

  // ── 4. the generated preset rows, wired into the layer the engine loads ───────────────────
  const profilePatch = join(target, 'profiles', opts.profile, 'cordis.patch.yml');
  if (!existsSync(profilePatch)) {
    out.problems.push(`the staged profile ${opts.profile} has no cordis.patch.yml, so there is no `
      + 'layer to wire the preset rows into');
    return out;
  }
  const generated = opts.generatedPath ?? join(target, 'profiles', opts.profile, 'presets.generated.patch.yml');
  // THE CONVERTER MUST READ THE **STAGED, REWRITTEN** PRESETS — NOT THE SOURCE THEY WERE COPIED FROM.
  //
  // DEFECT (measured 2026-10-05, found by `dsh-update analyze 0.2.0-rc.2`, not by any test here).
  // This passed `presetsSrc` — `--from`'s `.agent-presets`, i.e. the LIVE directory, still carrying the
  // pre-rewrite names — while the rewrite above had already been applied to the staged copies. So the
  // emitted `preset-*` rows carried a `workflow` row naming `@deepseek-ai/dsh-workflow-worker-thread`,
  // a package 0.1.7+ does not provide.
  //
  // WHY THAT WAS DANGEROUS AND WHY THE EXISTING ASSERTIONS MISSED IT. A composition row naming a package
  // that is not installed FAILS AT MOUNT, and inside a preset that breaks NEW SESSION CREATION — the
  // 2026-10-04 incident, whose symptom is the workspace picker bouncing back with
  // `agent-preset/invalid`. Nothing here noticed, because every assertion in this module that mentions
  // the preset rows counts occurrences in the `.agent-presets/*/agent.cordis.yml` FILES (which the
  // rewrite does fix, and which `switch-engine.ps1` precondition 2 also greps). The ROWS that the
  // candidate actually mounts live in the profile patch, and no assertion read them for a stale name.
  // On 0.1.7+ the `.agent-presets` directory is not read at all, so the files being correct proves
  // nothing about the rows — the grep was a proxy, and the proxy was green while the real thing was
  // broken.
  //
  // The staged copy is the rewritten one, and it is also what the switch installs, so reading it is both
  // the fix and the more honest subject.
  const stagedPresets = join(target, PRESET_DIR_NAME);
  const conv = runConverter(opts, stagedPresets, generated);
  out.converter = conv.summary;
  if (!conv.ok) {
    out.problems.push(...conv.problems);
    return out;
  }
  const block = blockFromGenerated(conv.text);
  if (!block.ok) {
    out.problems.push(...block.problems);
    return out;
  }
  out.block = { entries: block.entries.length, rowIds: block.rowIds, lines: block.lines.length, origin: 'make-preset-rows.mjs' };

  // THE ASSERTION THAT WOULD HAVE CAUGHT THE DEFECT ABOVE, so it cannot come back. Every generated row
  // must name only packages this candidate actually provides: a row naming an absent package fails to
  // MOUNT, and inside a preset that breaks new session creation. This reads the ROWS, which is what the
  // engine mounts — not the `.agent-presets` files, which on 0.1.7+ are not read at all.
  const blockText = block.lines.join('\n');
  const staleInRows = [];
  for (const decision of slots.decisions) {
    for (const from of decision.candidates) {
      if (from === modernOf[decision.id]) continue;
      const hits = countRefs(blockText, from).code;
      if (hits > 0) staleInRows.push(`${from} (${hits} row reference(s))`);
    }
  }
  if (staleInRows.length > 0) {
    out.problems.push(`the generated preset rows name a package this candidate does NOT provide: `
      + `${staleInRows.join(', ')}. A composition row naming an absent package fails at mount, and inside a `
      + 'preset that breaks new session creation. Refusing to splice them.');
    return out;
  }
  out.notes.push(`generated preset rows: ${block.entries.length} entr(ies) [${block.rowIds.join(', ')}]; no row names a package this candidate lacks`);

  const spliced = spliceManagedBlock(readFileSync(profilePatch, 'utf8'), block.lines);
  if (spliced.problems) {
    out.problems.push(...spliced.problems.map((p) => `${profilePatch}: ${p}`));
    return out;
  }
  if (spliced.mode !== 'noop') writeFileSync(profilePatch, spliced.text, 'utf8');
  out.block.mode = spliced.mode;
  out.block.patchEntries = {
    before: spliced.currentEntries,
    after: spliced.expectedEntries ?? spliced.currentEntries,
    generated: spliced.generatedEntries ?? null,
  };
  out.block.outsideSha = spliced.outsideSha ?? null;

  // ── 5. the real assertion, over the tree that was just built ───────────────────────────────
  const assertion = assertStagedHome(target, slots);
  out.assertion = assertion;
  if (!assertion.ok) {
    out.problems.push(...assertion.problems.map((p) => `assertion: ${p}`));
    return out;
  }

  // ── 6. the manifest ────────────────────────────────────────────────────────────────────────
  const hashes = treeHashes(target);
  const manifest = {
    schemaVersion: MANIFEST_SCHEMA,
    provenance: provenance(opts.now ?? new Date().toISOString()),
    source: opts.from,
    candidate: opts.candidate,
    profile: opts.profile,
    slots: slots.decisions.map((d) => ({ id: d.id, decides: d.decides, side: d.side })),
    excluded: {
      directories: [...STATE_EXCLUDES].sort(),
      profileFiles: PROFILE_FILES,
      note: 'a staged home is CONFIG, not state: sessions/, storages/, attachments/, metrics/, '
        + 'health/ and .credentials.yaml are never copied, and node_modules is skipped by name at '
        + 'every depth. The profile module ANCHOR is the one exception, and it is rebuilt as LINKS '
        + '(never followed): without it the candidate composes a different tree — measured 185 rows '
        + 'instead of 193, with nine `skipping profile bundle` lines on its own stderr.',
    },
    links: out.links.map((l) => ({
      path: relative(target, l.path).split(sep).join('/'),
      target: l.target,
      kind: l.kind,
    })),
    presetRows: out.block,
    // Recorded, NOT decided: making one of our presets the registry's default is a change to a row
    // the dsh-web-app bundle ships, and it is a separate deliberate change (FINDINGS.md item 1).
    openRows: [{
      id: 'config.defaultIsNotOurs',
      detail: 'the 0.1.7 agent-preset-registry row\'s `config.default` is shipped as `standard` by '
        + 'dsh-web-app\'s own patch layer. Our preset ROWS now compose, but a session that names no '
        + 'preset still gets `standard`; naming `zabz` as the default is a patch to a row we do not '
        + 'own and is deliberately not done here.',
    }],
    hashes,
  };
  writeFileSync(join(target, MANIFEST_NAME), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  out.manifest = { files: Object.keys(hashes).length, path: join(target, MANIFEST_NAME) };
  return out;
}

/** Run the existing converter; never rewrite it, never write its output anywhere but the stage. */
function runConverter(opts, presetsDir, outFile) {
  const problems = [];
  if (!existsSync(CONVERTER)) {
    return { ok: false, problems: [`the converter is missing: ${CONVERTER}`], summary: null };
  }
  if (!existsSync(presetsDir)) {
    return {
      ok: false,
      problems: [`there is no ${PRESET_DIR_NAME} directory to convert (${presetsDir} does not exist) — `
        + 'a 0.1.7+ candidate reads presets from ROWS, so with no presets there are no rows and a '
        + 'staged home with no preset rows is a refusal, not an empty success'],
      summary: null,
    };
  }
  const args = [CONVERTER, '--presets-dir', presetsDir, '--out', outFile];
  const run = spawnSync(process.execPath, args, {
    cwd: REPO_ROOT, encoding: 'utf8', timeout: 180000, maxBuffer: 64 * 1024 * 1024,
  });
  const summary = {
    command: [process.execPath, ...args].join(' '),
    exit: run.status,
    stdout: (run.stdout ?? '').trim(),
    stderr: (run.stderr ?? '').trim(),
  };
  if (run.error) {
    return { ok: false, problems: [`could not run the converter: ${run.error.message}`], summary };
  }
  if (run.status !== 0) {
    return {
      ok: false,
      problems: [`the converter exited ${run.status}: ${summary.stderr || summary.stdout || '<no output>'}`],
      summary,
    };
  }
  if (!existsSync(outFile)) {
    return { ok: false, problems: [`the converter exited 0 but wrote no file at ${outFile}`], summary };
  }
  const text = readFileSync(outFile, 'utf8');
  if (text.trim().length === 0) {
    return { ok: false, problems: [`the converter wrote an EMPTY file at ${outFile}`], summary };
  }
  return { ok: true, problems, summary, text };
}

// ── check mode ───────────────────────────────────────────────────────────────────────────────
/**
 * Compare a freshly built tree against the committed one, byte for byte, per file, plus presence
 * and absence in both directions. The manifest is compared with its `provenance` field removed:
 * the timestamp is a statement about when, and a `--check` that failed on the clock would be a
 * gate nobody could keep green.
 */
export function diffTrees(builtDir, committedDir) {
  const problems = [];
  if (!existsSync(committedDir) || !statSync(committedDir).isDirectory()) {
    return {
      problems: [`${committedDir} does not exist, so there is nothing committed to compare against. `
        + 'Run without --check to build it.'],
      differences: [],
    };
  }
  const built = treeHashes(builtDir);
  const committed = treeHashes(committedDir);
  const differences = [];
  for (const rel of Object.keys(built).sort()) {
    if (!(rel in committed)) {
      differences.push({ path: rel, kind: 'missing-in-committed' });
      continue;
    }
    if (built[rel] !== committed[rel]) {
      differences.push({ path: rel, kind: 'content-differs', built: built[rel].slice(0, 16), committed: committed[rel].slice(0, 16) });
    }
  }
  for (const rel of Object.keys(committed).sort()) {
    if (!(rel in built)) differences.push({ path: rel, kind: 'extra-in-committed' });
  }
  if (differences.length > 0) {
    problems.push(`the committed staged home and a freshly built one differ in ${differences.length} `
      + `file(s): ${differences.slice(0, 8).map((d) => `${d.path} (${d.kind})`).join('; ')}`
      + `${differences.length > 8 ? ` … and ${differences.length - 8} more` : ''}`);
  }
  return { problems, differences, builtFiles: Object.keys(built).length, committedFiles: Object.keys(committed).length };
}

// ── CLI ──────────────────────────────────────────────────────────────────────────────────────
const USAGE = 'usage: node dsh-update/lib/stage-home.mjs --from <configHome> --candidate <prefix> '
  + '--out <dir> [--profile web] [--check] [--json]';

export function parseArgs(argv) {
  const args = {
    from: process.env.DSH_HOME || join(process.env.USERPROFILE ?? process.env.HOME ?? '.', '.dsh'),
    candidate: null,
    out: null,
    profile: 'web',
    check: false,
    json: false,
    help: false,
    slotsFrom: null,
  };
  const rest = [...argv];
  while (rest.length > 0) {
    const a = rest.shift();
    const need = (label) => {
      const v = rest.shift();
      if (v === undefined) throw new Error(`${label} needs a value`);
      return v;
    };
    if (a === '--from') args.from = need('--from');
    else if (a === '--candidate') args.candidate = need('--candidate');
    else if (a === '--out') args.out = need('--out');
    else if (a === '--profile') args.profile = need('--profile');
    else if (a === '--profiles-from') args.profilesFrom = need('--profiles-from');
    else if (a === '--slots-from') args.slotsFrom = need('--slots-from');
    else if (a === '--check') args.check = true;
    else if (a === '--json') args.json = true;
    else if (a === '-h' || a === '--help') args.help = true;
    else throw new Error(`unknown argument ${a}`);
  }
  return args;
}

export async function main(argv = process.argv.slice(2), log = console.log, logErr = console.error) {
  let args;
  try {
    args = parseArgs(argv);
  } catch (e) {
    logErr(`stage-home.mjs: ${e.message}\n${USAGE}`);
    return 2;
  }
  if (args.help) {
    logErr(USAGE);
    return 0;
  }
  if (!args.candidate) { logErr(`stage-home.mjs: --candidate is required\n${USAGE}`); return 2; }
  if (!args.out) { logErr(`stage-home.mjs: --out is required\n${USAGE}`); return 2; }

  const from = resolve(args.from);
  const candidate = resolve(args.candidate);
  const committed = resolve(args.out);
  const say = args.json ? logErr : log;

  let slots = null;
  if (args.slotsFrom) {
    try {
      slots = { names: slotListFromFile(resolve(args.slotsFrom)), label: `injected by --slots-from ${resolve(args.slotsFrom)}` };
    } catch (e) {
      logErr(`stage-home.mjs: ${e.message}`);
      return 2;
    }
  }

  // The scratch directory the build goes to. In BUILD mode it IS the output; in CHECK mode it is a
  // sibling that is compared and then removed, so `--check` writes nothing into `--out`.
  const scratch = args.check ? `${committed}.stage-home-check-${process.pid}` : committed;
  if (args.check && existsSync(scratch)) {
    try { rmSync(scratch, { recursive: true, force: true }); } catch (e) {
      logErr(`stage-home.mjs: cannot clear the check scratch directory ${scratch}: ${e.message}`);
      return 1;
    }
  }

  let built;
  try {
    built = buildStagedHome({
      from, candidate, out: committed, stageDir: scratch, profile: args.profile,
      check: args.check, slots,
      profilesFrom: args.profilesFrom ? resolve(args.profilesFrom) : null,
    });
  } catch (e) {
    try { if (args.check) rmSync(scratch, { recursive: true, force: true }); } catch { /* best effort */ }
    logErr(`stage-home.mjs: unexpected failure: ${e?.stack ?? e}`);
    return 1;
  }

  const result = {
    tool: 'dsh-update/lib/stage-home.mjs',
    mode: built.mode,
    from, candidate, out: committed, profile: args.profile,
    slotDecisions: built.slots?.decisions ?? [],
    rewrites: built.rewrites,
    presetRowsBlock: built.block,
    assertion: built.assertion && {
      ok: built.assertion.ok,
      checks: built.assertion.checks,
      problems: built.assertion.problems,
      presetFiles: built.assertion.presetFiles?.length ?? 0,
      profilePatches: built.assertion.patchFiles?.length ?? 0,
    },
    manifest: built.manifest,
    copiedFiles: built.copied.length,
    links: built.links.length,
    skipped: built.skipped,
    converter: built.converter,
    notes: built.notes,
    problems: built.problems,
    drift: null,
  };

  if (built.problems.length > 0) {
    say(`stage-home: REFUSED — ${built.problems.length} problem(s); nothing was written${args.check ? '' : ' into --out that was not already there'}`);
    for (const p of built.problems) say(`  - ${p}`);
    if (args.check) {
      try { rmSync(scratch, { recursive: true, force: true }); } catch { /* best effort */ }
    }
    result.ok = false;
    if (args.json) log(JSON.stringify(result, null, 2));
    return 1;
  }

  if (args.check) {
    let diff;
    try {
      diff = diffTrees(scratch, committed);
    } catch (e) {
      logErr(`stage-home.mjs: comparison failed: ${e.message}`);
      try { rmSync(scratch, { recursive: true, force: true }); } catch { /* best effort */ }
      return 1;
    }
    // The assertion above ran against the freshly built SCRATCH tree. In --check mode the committed
    // tree is the thing that will be booted, so assert on IT as well — a comparison against the
    // wrong standard is not a gate.
    let committedAssertion = null;
    if (built.slots) {
      committedAssertion = assertStagedHome(committed, built.slots);
      result.assertion = {
        ok: committedAssertion.ok,
        target: 'the committed tree (--out)',
        checks: committedAssertion.checks,
        problems: committedAssertion.problems,
        presetFiles: committedAssertion.presetFiles.length,
        profilePatches: committedAssertion.patchFiles.length,
      };
    }
    try { rmSync(scratch, { recursive: true, force: true }); } catch { /* best effort */ }
    result.drift = diff.differences;
    result.builtFiles = diff.builtFiles;
    result.committedFiles = diff.committedFiles;

    const failures = [...diff.problems];
    if (committedAssertion && !committedAssertion.ok) {
      failures.push(...committedAssertion.problems.map((p) => `assertion on the committed tree: ${p}`));
    }
    if (failures.length > 0) {
      result.ok = false;
      say(`stage-home --check: DRIFT/FAIL — ${failures.length} problem(s)`);
      for (const f of failures) say(`  - ${f}`);
      if (args.json) log(JSON.stringify(result, null, 2));
      return 1;
    }
    result.ok = true;
    say(`stage-home --check: UP TO DATE — ${diff.committedFiles} file(s) match a fresh build; `
      + `${built.assertion.presetFiles.length} preset file(s), ${built.assertion.patchFiles.length} `
      + `profile patch(es); assertion PASS`);
    if (args.json) log(JSON.stringify(result, null, 2));
    return 0;
  }

  result.ok = true;
  say(`stage-home: built ${committed}`);
  say(`  from        : ${from}`);
  say(`  candidate   : ${candidate}`);
  for (const d of result.slotDecisions) {
    say(`  slot ${d.id.padEnd(17)}: ${d.side === 'modern' ? 'modern' : d.side} -> ${d.decides}`);
  }
  say(`  files       : ${result.copiedFiles} copied, ${result.links} link(s) recreated in the module `
    + `anchors, ${built.skipped.length} skipped (state/backups/node_modules)`);
  say(`  rewrites    : ${built.rewrites.length} version-coupled reference(s) retargeted in the STAGED copies`);
  say(`  preset rows : ${built.block.entries} entr(ies) [${built.block.rowIds.join(', ')}] spliced into `
    + `profiles/${args.profile}/cordis.patch.yml (${built.block.mode}: top-level patch entries `
    + `${built.block.patchEntries.before} -> ${built.block.patchEntries.after}, of which `
    + `${built.block.patchEntries.generated} generated; ${built.block.lines} line(s) between the markers)`);
  for (const c of built.assertion.checks) {
    say(`  assert ${c.ok ? 'ok  ' : 'FAIL'} ${c.check}: ${c.value}`);
  }
  say(`  assertion   : ${built.assertion.ok ? 'PASS' : 'FAIL'} (switch-engine PRECONDITION 2 predicate, `
    + 'reproduced literally)');
  if (built.manifest) say(`  manifest    : ${built.manifest.path} (${built.manifest.files} file hash(es))`);
  if (args.json) log(JSON.stringify(result, null, 2));
  return 0;
}

const invokedDirectly = Boolean(process.argv[1]) && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) {
  main()
    .then((code) => process.exit(code))
    .catch((e) => {
      process.stderr.write(`stage-home.mjs: unexpected failure: ${e?.stack ?? e}\n`);
      process.exit(1);
    });
}

/** Re-exported for the tests: the resolved yaml implementation, so a test can prove the same one. */
export const yamlInfo = yamlResolvedFrom();
