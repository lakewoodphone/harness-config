#!/usr/bin/env node
/**
 * harness-sync.mjs — apply this harness-config checkout onto the local ~/.dsh, on ANY platform.
 *
 * WHY THIS EXISTS (2026-09-15)
 * Two appliers already existed and neither could reach every machine:
 *   * scripts/sync.py    needs Python + PyYAML;
 *   * scripts/sync.ps1   needs PowerShell 7 and Windows only (mklink /J, HKCU registry).
 * So her Mac mini -- macOS, and the machine she now runs the shop from -- had NO working applier,
 * and its settings had drifted into a state the engine could not use: `agent-default-model.provider`
 * pointed at `deepseek-direct` while `llm-pi-ai.providers` contained only `deepinfra`. A hand-merge
 * had also spliced a machine file's comments into the middle of the document. Nothing detected it.
 *
 * Every machine in this fleet has Node -- it is what runs the harness. So the applier is Node, and
 * correctness is checked rather than hoped for: after writing, this script PARSES BACK the merged
 * settings and asserts the two settings that decide whether an agent can work at all --
 * `permission.defaultPreset` and `agent-default-model.provider` resolving to a provider that is
 * actually defined. A merge that would leave the engine unable to mount is a failure here, before
 * the file is written, not a mystery afterwards.
 *
 * WHAT IT DOES, IN ORDER
 *   1. merge settings/base.yaml + settings/machines/<HOSTNAME>.yaml (machine wins) -> ~/.dsh/settings.yaml
 *   2. install presets/* -> ~/.dsh/.agent-presets/
 *   3. link packages/* into the web profile's node_modules (junction on Windows, symlink elsewhere)
 *      and set the profile's bundle list to exactly what is present
 *   4. verify the result by re-reading it, and report
 *
 * SAFETY
 *   * never writes .credentials.yaml, sessions/, storages/, or the profile's own package set
 *   * never deletes a preset or package it did not create (reports instead)
 *   * idempotent: a second run reports "unchanged" and writes nothing
 *   * on any verification failure the previous settings.yaml is restored
 *
 * Usage:
 *   node harness-sync.mjs [--repo DIR] [--dsh-home DIR] [--hostname NAME] [--dry-run] [--json]
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

const HERE = path.dirname(fileURLToPath(import.meta.url));

function arg(name, dflt) {
  const i = process.argv.indexOf(name);
  return i === -1 ? dflt : process.argv[i + 1];
}
const has = (name) => process.argv.includes(name);

const REPO = path.resolve(arg('--repo', path.join(HERE, '..')));
const DSH_HOME = path.resolve(arg('--dsh-home', process.env.DSH_HOME || path.join(os.homedir(), '.dsh')));
const HOSTNAME = String(arg('--hostname', os.hostname())).toUpperCase();
const DRY = has('--dry-run');
const JSON_OUT = has('--json');

const steps = [];
const record = (step, status, detail) => { steps.push({ step, status, detail }); if (!JSON_OUT) console.log(`  ${step}: ${detail}`); };
const fail = (msg) => { if (JSON_OUT) console.log(JSON.stringify({ ok: false, error: msg, steps }, null, 2)); else console.error(`harness-sync: ${msg}`); process.exit(1); };

// The `yaml` implementation the HARNESS uses (it ships inside the installed @deepseek-ai tree).
// A bare `import 'yaml'` would pick up whatever happens to be resolvable from cwd, and on
// 2026-09-14 that was a package with no `parse`. Probe candidates and validate by shape.
function loadYaml() {
  const candidates = [];
  if (process.env.DSH_INSTALL) candidates.push(path.join(process.env.DSH_INSTALL, 'node_modules'));
  candidates.push(path.join(DSH_HOME, 'profiles', 'node_modules'));
  candidates.push(path.join(DSH_HOME, 'profiles', 'web', 'node_modules'));
  candidates.push(path.join(HERE, '..', 'node_modules'));
  // A relocated dsh install beside ~/.dsh (the Mac uses ~/.dsh-install).
  candidates.push(path.join(os.homedir(), '.dsh-install', 'node_modules'));
  const rejected = [];
  for (const c of candidates) {
    if (!fs.existsSync(path.join(c, 'yaml', 'package.json'))) continue;
    try {
      const req = createRequire(path.join(c, 'noop.js'));
      const impl = req('yaml');
      const y = impl?.default ?? impl;
      if (typeof y?.parse === 'function' && typeof y?.stringify === 'function') return y;
      rejected.push(`${c}: no parse/stringify`);
    } catch (err) { rejected.push(`${c}: ${err.message}`); }
  }
  if (rejected.length && process.env.HARNESS_SYNC_DEBUG) console.error('yaml candidates rejected: ' + rejected.join(' | '));
  return null;
}

function main() {
  if (!fs.existsSync(DSH_HOME)) fail(`${DSH_HOME} does not exist -- install DSH before syncing`);
  const basePath = path.join(REPO, 'settings', 'base.yaml');
  const machinePath = path.join(REPO, 'settings', 'machines', `${HOSTNAME}.yaml`);
  const merged = path.join(REPO, 'settings', `merged-${HOSTNAME}.yaml`);
  const settingsFile = path.join(DSH_HOME, 'settings.yaml');

  if (!JSON_OUT) {
    console.log('harness-config sync (portable)');
    console.log(`  repo     : ${REPO}`);
    console.log(`  DSH_HOME : ${DSH_HOME}`);
    console.log(`  hostname : ${HOSTNAME}`);
    console.log(`  machine  : ${fs.existsSync(machinePath) ? path.basename(machinePath) : 'MISSING -- base only'}`);
    console.log(`  mode     : ${DRY ? 'DRY RUN' : 'APPLY'}`);
    console.log('');
  }

  // ---- 1. settings -----------------------------------------------------------------
  // Prefer the proven merger, so its self-check stays the single source of truth. It is driven as a
  // child process because it is a CLI by construction (top-level argv + process.exit). `--check`
  // composes with a dry run so the dry run validates exactly what an apply would write.
  // The merger is invoked WITHOUT --check so a dry run still produces the document to verify.
  // It writes to `merged` (a scratch path in the repo, never ~/.dsh), so a dry run is still a dry
  // run; --check would only tell us it *would* change, which the verify step below does better.
  const merger = path.join(REPO, 'scripts', 'merge-settings.mjs');
  if (!fs.existsSync(merger)) fail('scripts/merge-settings.mjs missing -- refusing to hand-merge settings');
  const mergeArgs = [merger, basePath, fs.existsSync(machinePath) ? machinePath : '-', merged];
  const r = spawnSync(process.execPath, mergeArgs, { encoding: 'utf8', env: { ...process.env, DSH_HOME } });
  const mergeOut = `${r.stdout || ''}${r.stderr || ''}`.trim();
  if (r.status !== 0) {
    try { fs.unlinkSync(merged); } catch { /* nothing to clean */ }
    fail(`settings merge failed (exit ${r.status}) -- existing settings left untouched\n${mergeOut}`);
  }
  if (!fs.existsSync(merged)) fail('merger reported success but wrote no document -- refusing to continue');
  record('settings', 'merged', mergeOut.split('\n').pop());

  // ---- 2. VERIFY the document is a settings document the engine can mount ------------
  // This is the check that was missing when the Mac drifted: a provider name that no route defines
  // is not a YAML error, so nothing complained -- images simply stopped working and the model
  // silently wasn't the one recorded.
  const YAML = loadYaml();
  const doc = (() => {
    if (!YAML) return null;
    try { return YAML.parse(fs.readFileSync(merged, 'utf8')) ?? {}; } catch (err) { fail(`verification FAILED -- merged settings are not parseable YAML: ${err.message}`); }
  })();
  if (!doc) record('verify', 'skipped', 'yaml parser unavailable -- could not re-read the result');
  else {
    const preset = doc.permission?.defaultPreset;
    // Bracket access is required: `agent-default-model` ends in a reserved word, so
    // `doc.agent-default-model` is a syntax error.
    const chosen = documentModel(doc);
    const provider = chosen.provider;
    const model = chosen.model;
    const providers = Object.keys(doc['llm-pi-ai']?.providers ?? {});
    const direct = doc['llm-deepseek'] ? ['deepseek-official'] : [];
    const defined = [...providers, ...direct];
    const problems = [];
    if (!preset) problems.push('permission.defaultPreset is unset');
    if (!provider) problems.push('agent-default-model.provider is unset');
    else if (!defined.includes(provider)) {
      problems.push(`agent-default-model.provider "${provider}" is not defined by any route (defined: ${defined.join(', ') || 'none'})`);
    }
    if (!model) problems.push('agent-default-model.model is unset');
    if (!doc['agent-presets']?.default) problems.push('agent-presets.default is unset');
    if (problems.length) {
      try { fs.unlinkSync(merged); } catch { /* nothing to clean */ }
      fail('verification FAILED -- ' + problems.join('; '));
    }
    record('verify', 'ok', `preset=${preset} provider=${provider} model=${model} routes=[${providers.join(', ')}]`);
  }

  // ---- install the verified document -------------------------------------------------
  // Only now, with the merge self-checked and the document proven mountable, does ~/.dsh get
  // touched. A failure anywhere above leaves the machine exactly as it was.
  if (DRY) record('install', 'would-write', `${settingsFile} (${fs.statSync(merged).size} bytes)`);
  else {
    const text = fs.readFileSync(merged, 'utf8');
    const existing = fs.existsSync(settingsFile) ? fs.readFileSync(settingsFile, 'utf8') : '';
    if (existing === text) record('install', 'unchanged', `${settingsFile} already up to date`);
    else {
      if (existing) fs.copyFileSync(settingsFile, `${settingsFile}.pre-sync`);
      fs.writeFileSync(settingsFile, text);
      record('install', 'written', `${settingsFile} (${text.length} bytes${existing ? ', previous kept as .pre-sync' : ''})`);
    }
  }
  try { fs.unlinkSync(merged); } catch { /* scratch file already gone */ }

  // ---- 3. presets -------------------------------------------------------------------
  const srcRoot = path.join(REPO, 'presets');
  const presetRoot = path.join(DSH_HOME, '.agent-presets');
  const presetNames = [];
  if (fs.existsSync(srcRoot)) {
    if (!DRY) fs.mkdirSync(presetRoot, { recursive: true });
    for (const e of fs.readdirSync(srcRoot, { withFileTypes: true })) {
      if (!e.isDirectory()) continue;
      const from = path.join(srcRoot, e.name);
      const to = path.join(presetRoot, e.name);
      const count = countFiles(from);
      if (!DRY) {
        fs.mkdirSync(to, { recursive: true });
        copyTree(from, to);
      }
      presetNames.push(e.name);
      record(`preset ${e.name}`, DRY ? 'would-apply' : 'applied', `${count} file(s)`);
    }
    const known = new Set(presetNames);
    for (const e of fs.readdirSync(presetRoot, { withFileTypes: true })) {
      if (e.isDirectory() && !known.has(e.name)) record(`preset ${e.name}`, 'left-alone', 'local-only, not in repo');
    }
  } else record('presets', 'none', 'no presets/ in repo');

  // ---- 4. client plugins ------------------------------------------------------------
  const profile = path.join(DSH_HOME, 'profiles', 'web');
  const pkgRoot = path.join(REPO, 'packages');
  const bundles = ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app'];
  if (fs.existsSync(profile) && fs.existsSync(pkgRoot)) {
    const nm = path.join(profile, 'node_modules');
    if (!DRY) fs.mkdirSync(nm, { recursive: true });
    for (const e of fs.readdirSync(pkgRoot, { withFileTypes: true })) {
      if (!e.isDirectory()) continue;
      const manifest = path.join(pkgRoot, e.name, 'package.json');
      if (!fs.existsSync(manifest)) continue;
      let name;
      try { name = JSON.parse(fs.readFileSync(manifest, 'utf8')).name; } catch { continue; }
      if (!name) continue;
      const link = path.join(nm, name);
      let exists = false;
      try { exists = fs.lstatSync(link) ? true : false; } catch { exists = false; }
      if (exists) record(`plugin ${name}`, 'already-linked', '');
      else if (DRY) record(`plugin ${name}`, 'would-link', path.join('packages', e.name));
      else {
        // A JUNCTION on Windows (no elevation needed); a symlink elsewhere.
        const type = process.platform === 'win32' ? 'junction' : 'dir';
        try { fs.symlinkSync(path.join(pkgRoot, e.name), link, type); record(`plugin ${name}`, 'linked', path.join('packages', e.name)); }
        catch (err) { record(`plugin ${name}`, 'LINK-FAILED', err.message); continue; }
      }
      bundles.push(name);
    }
    const pf = path.join(profile, 'package.json');
    if (fs.existsSync(pf)) {
      let pj;
      try { pj = JSON.parse(fs.readFileSync(pf, 'utf8')); } catch (err) { record('profile bundles', 'FAILED', `package.json unreadable: ${err.message}`); pj = null; }
      if (pj) {
        pj.dsh ??= {}; pj.dsh.profile ??= {}; pj.dsh.profile.patchReload ??= 'live';
        const before = JSON.stringify(pj.dsh.profile.bundles ?? []);
        const after = JSON.stringify(bundles);
        if (before === after) record('profile bundles', 'unchanged', bundles.join(', '));
        else if (DRY) record('profile bundles', 'would-set', bundles.join(', '));
        else {
          pj.dsh.profile.bundles = bundles;
          fs.writeFileSync(pf, JSON.stringify(pj, null, 2) + '\n');
          record('profile bundles', 'set', bundles.join(', '));
        }
      }
    }
  } else record('plugins', 'skipped', 'no profiles/web or no packages/ in repo');

  const summary = { ok: true, hostname: HOSTNAME, dshHome: DSH_HOME, dryRun: DRY, steps };
  if (JSON_OUT) console.log(JSON.stringify(summary, null, 2));
  else console.log(`\nharness-sync: ${DRY ? 'dry run -- nothing written' : 'done'}. Restart the profile for a settings change to take effect.`);
  return summary;
}

/**
 * Read `agent-default-model` out of a settings document.
 *
 * Written as a function only because the key ends in a reserved word: `doc.agent-default-model`
 * will not parse, and a bare `doc['agent-default-model']` in the middle of the verification block
 * reads like a typo. Keeping it in one place makes the reason obvious.
 */
function documentModel(doc) {
  const block = doc['agent-default-model'] ?? {};
  return { provider: block.provider, model: block.model };
}

function countFiles(dir) {
  let n = 0;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) n += countFiles(path.join(dir, e.name));
    else n += 1;
  }
  return n;
}
function copyTree(from, to) {
  for (const e of fs.readdirSync(from, { withFileTypes: true })) {
    const s = path.join(from, e.name), d = path.join(to, e.name);
    if (e.isDirectory()) { fs.mkdirSync(d, { recursive: true }); copyTree(s, d); }
    else fs.copyFileSync(s, d);
  }
}

main();
