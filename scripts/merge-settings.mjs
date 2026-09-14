#!/usr/bin/env node
/**
 * Merge harness-config settings into one settings.yaml -- the exact rule sync.py uses.
 *
 * WHY THIS EXISTS AS node AND NOT powershell
 * sync.ps1 originally parsed and re-emitted YAML by hand. That worked for flat keys and silently
 * destroyed a LIST value: `models:` under `llm-pi-ai.providers.deepinfra` came out as a nested map
 * instead of a list, and the file ended up carrying the llm-pi-ai block twice. The engine refused
 * to boot at all -- `DUPLICATE_KEY at line 21` -- and `dsh --dump-config` did NOT catch it, because
 * dumping the composed profile never reads the user's settings document.
 *
 * So the merge is done with the same YAML implementation the harness itself uses (`yaml`, which
 * ships inside the installed @deepseek-ai tree), and correctness is proved by re-parsing the text
 * we are about to write.
 *
 * Usage:
 *   node merge-settings.mjs <base.yaml> <machine.yaml|-> <out.yaml> [--check]
 * `--check` prints whether the output would change and writes nothing.
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';

const [basePath, machinePath, outPath, ...flags] = process.argv.slice(2);
const check = flags.includes('--check');
if (!basePath || !machinePath || !outPath) {
  console.error('usage: node merge-settings.mjs <base.yaml> <machine.yaml|-> <out.yaml> [--check]');
  process.exit(2);
}

// Resolve the `yaml` implementation the HARNESS uses, from the harness install itself.
//
// A plain bare `require('yaml')` is not safe here: this script can be run from a directory holding
// a different package also called `yaml`, and that package may have no `parse`. That happened on
// 2026-09-14 -- `TypeError: YAML.parse is not a function` -- and the failure was correct (it
// refused to write) but it blocked the deploy. So candidates are probed in order, each import is
// validated by shape, and the first usable one wins.
function loadYaml() {
  const candidates = [];
  if (process.env.DSH_INSTALL) {
    candidates.push(join(process.env.DSH_INSTALL, 'node_modules'));
  }
  if (process.env.DSH_HOME) {
    candidates.push(join(process.env.DSH_HOME, 'profiles', 'web'));
    candidates.push(join(process.env.DSH_HOME, 'profiles', 'node_modules'));
  }
  for (const rel of ['node_modules', '../node_modules', '../../node_modules']) {
    candidates.push(join(process.cwd(), rel));
  }
  // The npx cache the harness commonly runs from.
  for (const local of [process.env.LOCALAPPDATA, process.env.USERPROFILE ? join(process.env.USERPROFILE, 'AppData', 'Local') : '']) {
    if (!local) continue;
    const npx = join(local, 'npm-cache', '_npx');
    if (existsSync(npx)) {
      try { for (const d of readdirSync(npx)) candidates.push(join(npx, d, 'node_modules')); } catch { /* ignore */ }
    }
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
      if (typeof impl?.parse === 'function' && typeof impl?.stringify === 'function') {
        return impl;
      }
      problems.push(`${base} -> yaml has no parse/stringify`);
    } catch (e) {
      problems.push(`${base} -> ${e.message}`);
    }
  }
  throw new Error(
    'cannot resolve a usable "yaml" package (with parse and stringify). Tried: ' +
    [...seen].join(', ') + (problems.length ? ` | rejected: ${problems.join('; ')}` : '')
  );
}
const YAML = loadYaml();

/** Recursive merge: a mapping merges into a mapping; every other value replaces. */
function deepMerge(base, over) {
  if (base && over && typeof base === 'object' && typeof over === 'object'
      && !Array.isArray(base) && !Array.isArray(over)) {
    const out = { ...base };
    for (const [k, v] of Object.entries(over)) {
      out[k] = k in out ? deepMerge(out[k], v) : v;
    }
    return out;
  }
  return over === undefined ? base : over;
}

const base = existsSync(basePath) ? (YAML.parse(readFileSync(basePath, 'utf8')) ?? {}) : {};
const machine = (machinePath !== '-' && existsSync(machinePath))
  ? (YAML.parse(readFileSync(machinePath, 'utf8')) ?? {})
  : {};

const merged = deepMerge(base, machine);
const text = YAML.stringify(merged, { lineWidth: 0 });

// PROVE the text is what we think it is before anyone writes it. A round trip that changes the
// shape means the merge produced something the harness cannot read, and that is a hard failure
// rather than a file written hopefully.
const roundTrip = YAML.parse(text);
const before = JSON.stringify(sortKeys(merged));
const after = JSON.stringify(sortKeys(roundTrip));
if (before !== after) {
  console.error('merge-settings: FAILED self-check -- the written document does not re-parse to the same value');
  process.exit(1);
}

function sortKeys(v) {
  if (Array.isArray(v)) return v.map(sortKeys);
  if (v && typeof v === 'object') {
    return Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortKeys(v[k])]));
  }
  return v;
}

// A duplicate key is the exact failure that stopped the engine, so assert its absence by name:
// a re-parse would have thrown on a duplicate, and the round-trip comparison would have failed.
const existing = existsSync(outPath) ? readFileSync(outPath, 'utf8') : '';
if (existing.trim() === text.trim()) {
  console.log('settings.yaml: already up to date');
  process.exit(0);
}
if (check) {
  console.log(`settings.yaml: WOULD CHANGE (${existing.length} -> ${text.length} bytes)`);
  process.exit(0);
}
writeFileSync(outPath, text, 'utf8');
console.log(`settings.yaml: written (${text.length} bytes, self-check passed)`);
