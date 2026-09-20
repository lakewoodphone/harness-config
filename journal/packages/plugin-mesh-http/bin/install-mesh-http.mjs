#!/usr/bin/env node
/**
 * install-mesh-http — put this plugin into a DSH profile so the node's engine mounts it.
 *
 * WHAT IT TOUCHES, AND NOTHING ELSE
 *   <DSH_HOME>/profiles/<profile>/node_modules/dsh-plugin-mesh-http   a junction to this checkout
 *   <DSH_HOME>/profiles/<profile>/package.json                        one name added to `dsh.profile.bundles`
 *
 * It writes NOTHING else: not the engine, not a running process, not any other profile, and not
 * the repository it links to. `--check` changes nothing at all.
 *
 * THE RULE THAT MATTERS, INHERITED FROM `install-client-plugins.ps1`
 * **Never name a bundle you have not just proved resolves.** The loader mounts every name in
 * `dsh.profile.bundles`, and one unresolvable name stops the engine booting at all — measured on
 * ZABZ-TECH once already, twenty minutes to diagnose because every process-level signal looked
 * fine. So this installer resolves the junction FIRST, verifies the package's own manifest through
 * it, and only then edits the bundle list. The old package.json is kept beside it.
 *
 * A JUNCTION AND NOT A COPY. A copy drifts silently the moment the package is edited; a junction
 * makes this checkout the only copy. Junctions rather than symlinks because Windows grants symlink
 * creation only to an elevated shell or Developer Mode.
 *
 * A RESTART IS REQUIRED AFTER THIS for a resident engine: a mounted bundle cannot hot-load (P210).
 * That is a fact about the harness, not a choice this script makes, and it is printed at the end so
 * a caller cannot forget it.
 */

import { existsSync, copyFileSync, lstatSync, mkdirSync, readFileSync, readlinkSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PACKAGE_NAME = 'dsh-plugin-mesh-http';
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = path.resolve(HERE, '..');

function parse(argv) {
  const flags = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (!argv[i].startsWith('--')) continue;
    const [key, inline] = argv[i].slice(2).split('=');
    if (inline !== undefined) flags[key] = inline;
    else if (argv[i + 1] !== undefined && !argv[i + 1].startsWith('--')) flags[key] = argv[++i];
    else flags[key] = true;
  }
  return flags;
}

const flags = parse(process.argv.slice(2));
const dshHome = process.env.DSH_HOME ?? path.join(homedir(), '.dsh');
const profileName = String(flags.profile ?? 'web');
const profileDir = path.join(dshHome, 'profiles', profileName);
const manifestPath = path.join(profileDir, 'package.json');
const linkPath = path.join(profileDir, 'node_modules', PACKAGE_NAME);
const checkOnly = flags.check === true;
const remove = flags.remove === true;

const report = { package: PACKAGE_NAME, source: SOURCE, dshHome, profile: profileDir, checkOnly, remove };
const fail = (reason) => {
  process.stdout.write(`${JSON.stringify({ ...report, ok: false, reason }, null, 2)}\n`);
  process.exit(1);
};

// --- 1. the profile must exist -------------------------------------------------------------
if (!existsSync(manifestPath)) fail(`no profile manifest at ${manifestPath} — is DSH installed, and is "${profileName}" the right profile?`);
if (!existsSync(path.join(SOURCE, 'package.json'))) fail(`this package has no package.json at ${SOURCE}`);

// --- 2. what is there now ------------------------------------------------------------------
const current = (() => {
  if (!existsSync(linkPath)) return { kind: 'absent' };
  const stat = lstatSync(linkPath);
  if (!stat.isSymbolicLink()) return { kind: 'directory-or-file' };
  let target = null;
  try { target = readlinkSync(linkPath); } catch { target = null; }
  return { kind: 'link', target, pointsHere: path.resolve(path.dirname(linkPath), target ?? '') === SOURCE };
})();
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const bundles = Array.isArray(manifest?.dsh?.profile?.bundles) ? manifest.dsh.profile.bundles : [];
const listed = bundles.includes(PACKAGE_NAME);
report.current = current;
report.bundleListed = listed;
report.bundleCount = bundles.length;

if (remove) {
  if (checkOnly) fail('--check and --remove are mutually exclusive');
  if (listed) {
    const next = { ...manifest, dsh: { ...manifest.dsh, profile: { ...manifest.dsh.profile, bundles: bundles.filter((name) => name !== PACKAGE_NAME) } } };
    copyFileSync(manifestPath, `${manifestPath}.bak-${Date.now()}`);
    writeFileSync(manifestPath, `${JSON.stringify(next, null, 2)}\n`, 'utf8');
    report.removedFromBundles = true;
  }
  if (existsSync(linkPath)) {
    try { rmSync(linkPath, { recursive: false, force: true }); report.junctionRemoved = true; }
    catch (error) { report.junctionRemoved = `failed: ${String(error?.message ?? error)}`; }
  }
  process.stdout.write(`${JSON.stringify({ ...report, ok: true, note: 'a resident engine keeps the mounted row until it restarts' }, null, 2)}\n`);
  process.exit(0);
}

// --- 3. establish the junction (skipped entirely under --check) ----------------------------
let linkState = current;
if (current.kind !== 'link' || current.pointsHere !== true) {
  if (checkOnly) {
    report.ok = false;
    process.stdout.write(`${JSON.stringify({ ...report, ok: false, reason: `the junction is ${current.kind}${current.pointsHere === false ? ` and points at ${current.target}` : ''}; run without --check to create it` }, null, 2)}\n`);
    process.exit(1);
  }
  mkdirSync(path.join(profileDir, 'node_modules'), { recursive: true });
  if (existsSync(linkPath)) rmSync(linkPath, { recursive: false, force: true });
  try {
    symlinkSync(SOURCE, linkPath, 'junction');
    linkState = { kind: 'link', target: SOURCE, pointsHere: true };
  } catch (error) {
    fail(`could not create the junction at ${linkPath} -> ${SOURCE} (${String(error?.message ?? error)}). On Windows a junction needs no elevation; a symlink does, which is why a junction is used.`);
  }
}
report.junction = linkState;

// --- 4. PROVE the bundle resolves THROUGH the junction, before naming it -------------------
const resolvedManifest = path.join(linkPath, 'package.json');
if (!existsSync(resolvedManifest)) {
  fail(`the junction at ${linkPath} does not resolve to a package with a package.json — naming it in the bundle list would stop the engine booting`);
}
const declared = JSON.parse(readFileSync(resolvedManifest, 'utf8'));
if (declared.name !== PACKAGE_NAME) fail(`the junction resolves to a package named "${declared.name}", not "${PACKAGE_NAME}"`);
if (declared?.dsh?.bundle?.patch === undefined) fail(`the package declares no dsh.bundle.patch, so the loader would treat it as a row rather than a bundle`);
report.resolved = { path: resolvedManifest, name: declared.name, version: declared.version, patch: declared.dsh.bundle.patch };

// --- 5. name it, once, with the manifest kept beside the old one --------------------------
if (!listed) {
  if (checkOnly) {
    process.stdout.write(`${JSON.stringify({ ...report, ok: false, reason: 'the package resolves but is not in dsh.profile.bundles, so the engine will not mount it' }, null, 2)}\n`);
    process.exit(1);
  }
  const next = { ...manifest, dsh: { ...manifest.dsh, profile: { ...manifest.dsh.profile, bundles: [...bundles, PACKAGE_NAME] } } };
  const backup = `${manifestPath}.bak-${Date.now()}`;
  copyFileSync(manifestPath, backup);
  writeFileSync(manifestPath, `${JSON.stringify(next, null, 2)}\n`, 'utf8');
  report.manifestBackup = backup;
  report.addedToBundles = true;
}

process.stdout.write(`${JSON.stringify({
  ...report,
  ok: true,
  nextStep: 'RESTART THE NODE\'S ENGINE for this to take effect (a mounted bundle cannot hot-load, P210). Say so before doing it, and check that nothing of the owner\'s is running there.',
  verifyAfterRestart: `node ${path.relative(process.cwd(), path.join(HERE, 'mesh-http.mjs'))} check`,
}, null, 2)}\n`);
process.exit(0);
