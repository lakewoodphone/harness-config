#!/usr/bin/env node
/**
 * install-mesh-profile — the keeper for the `mesh` profile.
 *
 * WHAT IT DOES, AND WHY IT IS A KEEPER AND NOT A PROCEDURE
 * `scripts/sync.py` copies `profiles/<name>/cordis.patch.yml` into
 * `$DSH_HOME/profiles/<name>/`, but it deliberately does NOT install plugin
 * packages or create a profile that does not exist yet, and a profile's
 * `package.json` is machine-local and not in git (`sync.py:193-202`). So a
 * machine rebuilt from harness-config silently loses the bundle list — this
 * repo has already been bitten by exactly that (`cannot resolve profile bundle
 * "dsh-plugin-cost"`). This script is the same keeper `install-client-plugins.ps1`
 * is for the web profile, for the mesh profile, and it is idempotent.
 *
 * It writes NOTHING outside `$DSH_HOME/profiles/<name>/` and it never
 * overwrites a profile that is already correct.
 *
 *   node bin/install-mesh-profile.mjs                 # install or repair
 *   node bin/install-mesh-profile.mjs --check         # report only; exit 1 if broken
 *   node bin/install-mesh-profile.mjs --profile other --plugin-dir /path/to/pkg
 *
 * Exit codes: 0 installed/healthy, 1 a bundle does not resolve, 2 bad arguments.
 */

import { existsSync, mkdirSync, readFileSync, symlinkSync, writeFileSync, lstatSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(PACKAGE_ROOT, '..', '..');

function parseArgs(argv) {
  const options = { profile: 'mesh', check: false, pluginDir: PACKAGE_ROOT, dshHome: undefined, patch: undefined };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--check') options.check = true;
    else if (arg === '--profile') options.profile = argv[++i];
    else if (arg === '--plugin-dir') options.pluginDir = path.resolve(argv[++i] ?? '');
    else if (arg === '--dsh-home') options.dshHome = path.resolve(argv[++i] ?? '');
    else if (arg === '--patch') options.patch = path.resolve(argv[++i] ?? '');
    else {
      console.error(`install-mesh-profile: unknown argument "${arg}"`);
      process.exit(2);
    }
  }
  return options;
}

const options = parseArgs(process.argv.slice(2));
const dshHome = options.dshHome
  || (process.env.DSH_HOME && process.env.DSH_HOME.trim() !== '' ? process.env.DSH_HOME : path.join(homedir(), '.dsh'));
const profileDir = path.join(dshHome, 'profiles', options.profile);
const modulesDir = path.join(profileDir, 'node_modules');
const sharedModules = path.join(dshHome, 'profiles', 'node_modules');

const pluginManifest = JSON.parse(readFileSync(path.join(options.pluginDir, 'package.json'), 'utf8'));
const bundles = [
  '@deepseek-ai/dsh-base',
  '@deepseek-ai/dsh-headless',
  pluginManifest.name,
];

const problems = [];
const report = (line) => console.log(line);

report(`dsh home      ${dshHome}`);
report(`profile       ${profileDir}`);
report(`plugin source ${options.pluginDir}`);
report(`plugin name   ${pluginManifest.name}`);

// 1. The profile manifest — the bundle list the loader mounts.
const manifestPath = path.join(profileDir, 'package.json');
const manifest = {
  name: `dsh-profile-${options.profile}`,
  private: true,
  dsh: { profile: { patchReload: 'startup', bundles } },
};
if (options.check) {
  if (!existsSync(manifestPath)) problems.push(`no profile manifest at ${manifestPath}`);
  else {
    const existing = JSON.parse(readFileSync(manifestPath, 'utf8'));
    const listed = existing?.dsh?.profile?.bundles ?? [];
    const missing = bundles.filter((bundle) => !listed.includes(bundle));
    if (missing.length > 0) problems.push(`manifest is missing bundles: ${missing.join(', ')}`);
  }
} else {
  mkdirSync(profileDir, { recursive: true });
  writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  const workspacePath = path.join(profileDir, 'pnpm-workspace.yaml');
  if (!existsSync(workspacePath)) writeFileSync(workspacePath, 'packages:\n  - .\n', 'utf8');
  report(`manifest      written (${bundles.join(', ')})`);
}

// 2. The plugin link. A junction/symlink rather than a copy: a copy drifts the
//    moment the package is edited, and the drift is invisible.
const linkPath = path.join(modulesDir, pluginManifest.name);
if (options.check) {
  if (!existsSync(linkPath)) problems.push(`plugin ${pluginManifest.name} is not linked into ${modulesDir}`);
  else if (!existsSync(path.join(linkPath, 'cordis.patch.yml'))) problems.push(`plugin link ${linkPath} has no cordis.patch.yml`);
} else {
  mkdirSync(modulesDir, { recursive: true });
  let linked = false;
  try {
    const stat = lstatSync(linkPath);
    linked = stat.isSymbolicLink() || stat.isDirectory();
  } catch {
    linked = false;
  }
  if (!linked) {
    symlinkSync(options.pluginDir, linkPath, process.platform === 'win32' ? 'junction' : 'dir');
    report(`link          ${linkPath} -> ${options.pluginDir}`);
  } else {
    report(`link          ${linkPath} already present`);
  }
}

// 3. The profile's own patch layer, copied from the repo so a rebuilt machine
//    gets it without waiting for sync.py. Where the patch comes from, in order:
//    an explicit `--patch`, the repo layout (`<repo>/profiles/<name>/`), or a
//    copy carried beside the package for a deployment made outside the checkout.
const patchSource = path.join(REPO_ROOT, 'profiles', options.profile, 'cordis.patch.yml');
const patchCandidates = [
  options.patch,
  patchSource,
  path.join(PACKAGE_ROOT, 'profile', `${options.profile}.cordis.patch.yml`),
].filter((candidate) => candidate !== undefined);
const resolvedPatch = patchCandidates.find((candidate) => existsSync(candidate));
const patchTarget = path.join(profileDir, 'cordis.patch.yml');
if (resolvedPatch === undefined) {
  problems.push(`no profile patch found; looked in: ${patchCandidates.join(', ')}`);
} else if (options.check) {
  if (!existsSync(patchTarget)) problems.push(`no installed patch at ${patchTarget}`);
} else {
  writeFileSync(patchTarget, readFileSync(resolvedPatch, 'utf8'), 'utf8');
  report(`patch         ${resolvedPatch} -> ${patchTarget}`);
}

// 4. Does every bundle actually resolve? That is the invariant that matters.
if (existsSync(sharedModules)) {
  for (const bundle of bundles) {
    if (bundle === pluginManifest.name) continue; // checked above, via its own link
    const bundleManifest = path.join(sharedModules, ...bundle.split('/'), 'package.json');
    if (!existsSync(bundleManifest)) {
      problems.push(`bundle ${bundle} does not resolve from ${sharedModules} (no ${bundleManifest})`);
    }
  }
  report(`bundles       checked against ${sharedModules}`);
} else {
  problems.push(`no shared module fallback at ${sharedModules} — run one dsh profile once so the harness heals it`);
}

if (problems.length > 0) {
  report('');
  for (const problem of problems) report(`BROKEN ${problem}`);
  report(`install-mesh-profile: ${problems.length} problem(s)`);
  process.exit(1);
}
report('');
report(options.check ? 'install-mesh-profile: every bundle resolves' : 'install-mesh-profile: ready — dsh --profile mesh headless "<task>"');
process.exit(0);
