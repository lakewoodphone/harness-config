/**
 * Import the plugin exactly as the profile loader will: by package name, with the
 * profile directory as the resolution root. This catches the failure mode that
 * "the file exists" does not — a package that is installed but whose `exports` map
 * or `dsh` manifest the loader cannot use.
 *
 * Usage: node test/profile-resolution.manual.mjs [<profileDir>]
 */
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { join, dirname } from 'node:path';
import { homedir } from 'node:os';
import { existsSync, readFileSync } from 'node:fs';

const profileDir = process.argv[2] ?? join(homedir(), '.dsh', 'profiles', 'web');
const require = createRequire(join(profileDir, 'noop.js'));

const manifestPath = require.resolve('dsh-plugin-cost/package.json');
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
console.log(`resolved manifest: ${manifestPath}`);
console.log(`  name=${manifest.name} version=${manifest.version}`);
console.log(`  dsh=${JSON.stringify(manifest.dsh)}`);

const hostPath = require.resolve('dsh-plugin-cost');
console.log(`resolved host entry: ${hostPath}`);
const host = await import(pathToFileURL(hostPath).href);
console.log(`  exports: ${Object.keys(host).join(', ')}`);
console.log(`  plugin shape: name=${typeof host.name} inject=${JSON.stringify(host.inject)} apply=${typeof host.apply}`);

// The browser half is resolved but NOT imported: it is a plain script that calls
// `window.__ModuleLoader__.load`, so importing it in Node throws on `window`. What
// matters here is that the loader can find the file; whether its contents work is
// test/client-smoke.mjs's job, where a fake browser scope supplies `window`.
const clientPath = require.resolve('dsh-plugin-cost/client');
console.log(`resolved client entry: ${clientPath}`);
const clientSource = readFileSync(clientPath, 'utf8');
const registersWithLoader = /window\.__ModuleLoader__\.load\(\s*\{/.test(clientSource);
const registersUnderItsOwnName = clientSource.includes(`id: '${manifest.name}'`);
const declaresOptionalSlots = clientSource.includes("'slots'") || clientSource.includes('"slots"');
console.log(`  registers with the module loader: ${registersWithLoader}`);
console.log(`  registers under its package name: ${registersUnderItsOwnName}`);

const sanity = {
  'host exports a plugin name': typeof host.name === 'string' && host.name.length > 0,
  'host declares its dependencies': Array.isArray(host.inject) && host.inject.includes('commands'),
  'host exports apply': typeof host.apply === 'function',
  'host exports costReport for direct use': typeof host.costReport === 'function',
  'client bundle resolves through the package exports map': existsSync(clientPath),
  'client bundle registers with the module loader': registersWithLoader,
  'client bundle registers under its own package name': registersUnderItsOwnName,
  'client bundle reads the slot service optionally': declaresOptionalSlots,
  'the dsh.client manifest names the web platform': manifest.dsh?.client?.platform === 'web',
  'the dsh.bundle manifest points at a real patch file': existsSync(join(dirname(manifestPath), manifest.dsh?.bundle?.patch ?? 'missing')),
};
let failed = 0;
for (const [label, ok] of Object.entries(sanity)) {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}`);
  if (!ok) failed += 1;
}
console.log(failed === 0 ? '\nprofile resolution OK' : `\n${failed} check(s) failed`);
process.exit(failed === 0 ? 0 : 1);
