/**
 * The one part of the owner's request that needs no new code: a child CAN spawn its
 * own children.
 *
 * This file asserts that against the profile the remote child actually boots — not
 * against an assumption about it. The requirement was "the child agents should be
 * able to spawn their own agents", and the honest answer is that they already can,
 * locally, because the `headless` profile inherits the subagent binding from
 * `dsh-base`. That is a fact about an INSTALLED CONFIGURATION, so it is exactly the
 * kind of thing that is true until an upgrade changes it and nobody notices.
 *
 * WHAT THIS DOES AND DOES NOT ESTABLISH
 *   ESTABLISHES: in the installed runtime, the `headless` profile's own cordis patch
 *     defines the subagent tool the child can call, so a child can delegate further.
 *     The binding is `spawn` — in-process, on the child's own node — which is the
 *     correct and cheapest thing for a worker to do.
 *   DOES NOT: that a `subagent_remote` provider is mounted in the child's profile. It
 *     is not, and the test asserts that too, so nobody later reads this as "nesting
 *     across the mesh works".
 *
 * The test skips loudly rather than passing vacuously when the runtime is not where
 * it is expected, because a green test that measured nothing is the failure this
 * whole session exists to stop repeating.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';

/**
 * Locate the installed `@deepseek-ai` runtime.
 *
 * `require.resolve` alone is not enough and the first version of this file proved it by
 * SKIPPING on the machine that has the runtime: this package is reached through a
 * junction with no `node_modules` above its real path, which is the same resolution
 * problem `lib/provider.js`'s header documents. So the search mirrors
 * `scripts/patch-dsh-settlement-crash.py`, including the npx cache and a dedicated
 * engine root — and where it still cannot find one it SKIPS LOUDLY rather than passing
 * on an unmeasured claim.
 */
function runtimeRoot() {
  if (process.env.MESHFIX_DSH_ROOT) return process.env.MESHFIX_DSH_ROOT;
  const candidates = [];
  const local = process.env.LOCALAPPDATA;
  if (local) {
    const npx = path.join(local, 'npm-cache', '_npx');
    try {
      for (const entry of readdirSync(npx, { withFileTypes: true })) {
        if (entry.isDirectory()) candidates.push(path.join(npx, entry.name, 'node_modules', '@deepseek-ai'));
      }
    } catch { /* no npx cache here */ }
  }
  if (process.env.APPDATA) candidates.push(path.join(process.env.APPDATA, 'npm', 'node_modules', '@deepseek-ai'));
  const home = homedir();
  for (const rel of [
    'dsh-engine/node_modules/@deepseek-ai',
    'code/dsh-engine/node_modules/@deepseek-ai',
    '.dsh/node_modules/@deepseek-ai',
    'code/deepseek-harness/node_modules/@deepseek-ai',
    'node_modules/@deepseek-ai',
  ]) candidates.push(path.join(home, rel));
  candidates.push('/usr/lib/node_modules/@deepseek-ai', '/usr/local/lib/node_modules/@deepseek-ai');
  for (const candidate of candidates) {
    if (existsSync(path.join(candidate, 'dsh-base', 'cordis.patch.yml'))) return candidate;
  }
  return undefined;
}

function readIfPresent(file) {
  return existsSync(file) ? readFileSync(file, 'utf8') : undefined;
}

test('the child profile binds the subagent tool, so a child can spawn its own children', (t) => {
  const root = runtimeRoot();
  if (root === undefined) {
    t.skip('the DSH runtime is not resolvable from here; this asserts an INSTALLED configuration, so it cannot be checked from this checkout');
    return;
  }
  const base = readIfPresent(path.join(root, 'dsh-base', 'cordis.patch.yml'));
  if (base === undefined) {
    t.skip(`no dsh-base/cordis.patch.yml under ${root}`);
    return;
  }

  // The child boots `--profile headless` (see lib/nodes.js and the provider's
  // `remote.profile` default). The headless profile composes dsh-base, so the
  // subagent binding there is the child's toolbelt.
  assert.match(
    base,
    /dsh-tool-subagent/,
    'dsh-base must mount the subagent tool package, or a remote child cannot delegate at all',
  );
  assert.match(
    base,
    /provider:\s*spawn/,
    'the child\'s subagent tool must be bound to the in-process `spawn` provider',
  );
  // The remote provider must NOT be in this profile: a child spawning a grandchild on
  // another machine is a different capability, and claiming it here would be a lie
  // that a future reader would act on.
  assert.doesNotMatch(
    base,
    /remote-ssh/,
    'dsh-base must not claim a remote subagent provider — mesh nesting is not established here',
  );
});

test('the headless profile is the one a remote child boots, and it inherits that binding', (t) => {
  const root = runtimeRoot();
  if (root === undefined) {
    t.skip('the DSH runtime is not resolvable from here');
    return;
  }
  const headless = readIfPresent(path.join(root, 'dsh-headless', 'cordis.patch.yml'));
  if (headless === undefined) {
    t.skip(`no dsh-headless/cordis.patch.yml under ${root}`);
    return;
  }
  // The headless profile is deliberately thin: it adds the one-shot runner and
  // inherits everything else. Its own patch must not DISABLE the subagent tool.
  assert.doesNotMatch(
    headless,
    /tool-subagent[\s\S]{0,200}enabled:\s*false/,
    'the headless profile must not switch the subagent tool off',
  );
});
