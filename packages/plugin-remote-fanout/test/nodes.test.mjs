/**
 * The node table's own contract (`docs/mesh/102-linux-dispatch.md`).
 *
 * WHY THIS FILE EXISTS, IN ONE SENTENCE: the roster said `zabz-tech-linux` could
 * take v1 work, the machine could, and the dispatcher could not — it named an
 * interpreter path that did not exist and bypassed the wrapper that supplies the
 * credential, so a child placed there died before it ran and the whole mesh read
 * the failure as "that node is broken".
 *
 * So these tests are not about the table's contents; they are about the two
 * questions the table has to answer for a node that is CLAIMED to take work:
 *
 *   1. is the invocation RESOLVABLE at all — an executor, or both halves of an
 *      interpreter pair? (a version-stamped path that rots fails here)
 *   2. does the invocation CARRY ITS CREDENTIAL SOURCE — because on a node
 *      provisioned with a worker env file, "the interpreter inherits the
 *      environment" is not a credential, it is a wish.
 *
 * The roster lives in `packages/mesh-broker/nodes.json` and is read, never
 * edited, from here: it is the file that decides whether the broker will place
 * work on a node, and a table that disagrees with it is the defect itself.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  DEFAULT_WORKER_ENV_FILES,
  NODES,
  invocationForNode,
  nodeNames,
  normalizeNodeFacts,
  resolveNodeInvocation,
} from '../lib/nodes.js';

/** The broker's roster, as deployed in this tree. Read-only on purpose. */
const ROSTER_PATH = new URL('../../mesh-broker/nodes.json', import.meta.url);
const ROSTER = JSON.parse(readFileSync(ROSTER_PATH, 'utf8'));
const rosterNodes = Array.isArray(ROSTER) ? ROSTER : (ROSTER.nodes ?? []);

/** The node name the broker uses: `node === fqdn.split('.')[0]`. */
const rosterName = (entry) => entry.node ?? entry.name ?? String(entry.fqdn ?? '').split('.')[0];

/**
 * Which roster rows make a v1 CAPABILITY CLAIM: `dispatch.v1 === true`, or a row
 * that carries no `dispatch` block at all (the unmeasured state, measured 2026-09-17
 * on `secratary`: `dispatch.v1: null` while the broker still places work there).
 * An explicit `false` is a deliberate "do not place here yet" and is not a claim.
 */
function claimsV1(entry) {
  const flag = entry.dispatch?.v1;
  if (flag === true) return true;
  if (flag === false) return false;
  return entry.dispatch === undefined || entry.dispatch === null;
}

/** A fingerprint of the invocation: the resolver's output, minus prose. */
const formOf = (facts) => {
  const resolved = resolveNodeInvocation(facts);
  if (resolved === undefined) return undefined;
  return {
    form: resolved.form,
    command: resolved.command,
    argvPrefix: resolved.argvPrefix ?? null,
    credentialEnvFiles: resolved.credentialEnvFiles,
  };
};

/** The invocation a row resolves to TODAY — used to prove a test can fail. */
function executionFormFor(node) {
  const facts = NODES[node];
  return formOf({ ...facts, driver: undefined, nodeExe: undefined, bin: undefined, dshBin: undefined });
}

// ---------------------------------------------------------------------------
// 1. Every node that is CLAIMED to take v1 work has a resolvable invocation
// ---------------------------------------------------------------------------

test('every node this roster claims can take v1 work has a resolvable invocation', () => {
  const claimed = rosterNodes.filter(claimsV1);
  assert.ok(claimed.length > 0, 'the roster was read and no node claims v1 work — the reader is wrong, not the roster');
  const problems = [];
  for (const entry of claimed) {
    const name = rosterName(entry);
    const facts = NODES[name];
    if (facts === undefined) {
      problems.push(`${name}: claims v1 work but is not in the dispatcher table at all`);
      continue;
    }
    if (invocationForNode(name) === undefined) {
      problems.push(`${name}: no resolvable invocation (needs \`command\`, or both \`driver\` and \`bin\`)`);
    }
  }
  assert.deepEqual(problems, [], `a node the broker will place work on cannot be invoked:\n  ${problems.join('\n  ')}`);
});

// ---------------------------------------------------------------------------
// 2. Every v1 node's invocation declares where its credential comes from
// ---------------------------------------------------------------------------

test('every v1 node\'s invocation declares its credential source, and an interpreter-only POSIX row says where the credential is', () => {
  const problems = [];
  for (const entry of rosterNodes.filter(claimsV1)) {
    const name = rosterName(entry);
    const resolved = invocationForNode(name);
    if (resolved === undefined) continue; // reported by the test above
    if (typeof resolved.credentialSource !== 'string' || resolved.credentialSource === '') {
      problems.push(`${name}: the invocation declares no credential source`);
      continue;
    }
    if (/^UNKNOWN/.test(resolved.credentialSource)) {
      problems.push(`${name}: ${resolved.credentialSource}`);
      continue;
    }
    // The interpreter form on a POSIX node is the shape that killed the linux
    // child: an explicit `node <bin.js>` pair inherits an environment that does
    // NOT contain the worker credential (`env`, `bash -lc` and `bash -c` all
    // measured empty of DEEPSEEK_API_KEY on `zabz-tech-linux`). It is allowed
    // only when the row records a file to source, or when the row was CHECKED
    // and has none (a `!`-prefixed entry is that positive record).
    if (resolved.form === 'interpreter' && NODES[name]?.shell === 'posix') {
      const declared = NODES[name].credentialEnvFiles ?? [];
      const saysNone = declared.some((file) => String(file).startsWith('!'));
      if (resolved.credentialEnvFiles.length === 0 && !saysNone) {
        problems.push(`${name}: an interpreter-only POSIX row with no credential file declared and no record that it was checked for one — either name the file, or record \`!none\` to say it was checked`);
      }
    }
  }
  assert.deepEqual(problems, [], `a node that takes v1 work does not say where its credential comes from:\n  ${problems.join('\n  ')}`);
});

// ---------------------------------------------------------------------------
// 3. The two forms, on the nodes that actually exist
// ---------------------------------------------------------------------------

test('`zabz-tech-linux` uses the EXECUTOR form, because that is what sources the worker credential', () => {
  const resolved = invocationForNode('zabz-tech-linux');
  assert.equal(resolved.form, 'executor');
  assert.equal(resolved.command, 'dsh');
  assert.deepEqual(resolved.credentialEnvFiles, ['/etc/dsh-worker.env']);
  assert.match(resolved.credentialSource, /sources \/etc\/dsh-worker\.env/);
  // The interpreter pair must still be there as the fallback, and it must be a
  // path without a version in it — a version-stamped path is the thing that rotted.
  assert.equal(resolved.driver, '/usr/local/bin/node');
  assert.doesNotMatch(resolved.driver, /node-v\d|v\d+\.\d+\.\d+/, 'the fallback interpreter must not carry a version stamp');
  assert.equal(resolved.bin, '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js');
});

test('the Windows nodes and the two executor-less POSIX nodes use the INTERPRETER form', () => {
  for (const node of ['zabz-tech', 'zabz-yoga-1', 'secratary', 'lakewooechsmini']) {
    assert.equal(invocationForNode(node).form, 'interpreter', `${node} should not prefer a wrapper it does not have`);
  }
  // The two POSIX nodes with no executor were CHECKED, and the table says so
  // rather than leaving the question unanswered.
  for (const node of ['secratary', 'lakewooechsmini']) {
    assert.ok(
      NODES[node].credentialEnvFiles === undefined || NODES[node].credentialEnvFiles.some((f) => String(f).startsWith('!')),
      `${node} must record that it was checked for a worker env file`,
    );
  }
});

// ---------------------------------------------------------------------------
// 4. The resolver itself, including the two paths that used to be silent
// ---------------------------------------------------------------------------

test('the resolver prefers an executor over an interpreter pair, and falls back cleanly', () => {
  const both = { shell: 'posix', command: 'dsh', driver: '/usr/bin/node', bin: '/x/bin.js', credentialEnvFiles: ['/etc/dsh-worker.env'] };
  assert.equal(resolveNodeInvocation(both).form, 'executor');
  assert.equal(resolveNodeInvocation({ ...both, command: undefined }).form, 'interpreter');
  // An incomplete pair is not an invocation, however it is spelled: this is the
  // shape `{ remoteNodeExe }`-and-nothing-else had, and it must not resolve.
  assert.equal(resolveNodeInvocation({ nodeExe: 'C:/n.exe' }), undefined);
  assert.equal(resolveNodeInvocation({ dshBin: '/x/bin.js' }), undefined);
  assert.equal(resolveNodeInvocation(undefined), undefined);
  // A bare interpreter is still usable — a path is not the same as a decision,
  // and a Windows node needs no credential file to name.
  assert.equal(resolveNodeInvocation({ shell: 'powershell', driver: 'C:/Program Files/nodejs/node.exe', bin: 'C:/x/bin.js' }).credentialEnvFiles.length, 0);
});

test('an unchecked POSIX interpreter row is reported as an UNKNOWN credential, not as a working one', () => {
  const resolved = resolveNodeInvocation({ shell: 'posix', driver: '/usr/bin/node', bin: '/x/bin.js' });
  assert.match(resolved.credentialSource, /^UNKNOWN/);
  // ...and the same row, once checked and found empty, is honest instead.
  const checked = resolveNodeInvocation({ shell: 'posix', driver: '/usr/bin/node', bin: '/x/bin.js', credentialEnvFiles: ['!none'] });
  assert.match(checked.credentialSource, /dispatching process environment/);
  assert.deepEqual(checked.credentialEnvFiles, [], 'the `!` marker is a record, never a file to source');
});

test('every node in the table resolves — none is a row that cannot be dispatched', () => {
  for (const node of nodeNames()) {
    assert.notEqual(invocationForNode(node), undefined, `${node} has no invocation`);
  }
  assert.deepEqual(nodeNames(), ['zabz-tech', 'zabz-yoga-1', 'zabz-tech-linux', 'secratary', 'lakewooechsmini']);
});

test('the default worker env file list is the one the wrapper reads', () => {
  assert.deepEqual([...DEFAULT_WORKER_ENV_FILES], ['/etc/dsh-worker.env']);
});

test('the two field spellings are read through one normaliser, so an older row is not silently unresolvable', () => {
  assert.equal(normalizeNodeFacts({ nodeExe: '/n', dshBin: '/b' }).driver, '/n');
  assert.equal(normalizeNodeFacts({ nodeExe: '/n', dshBin: '/b' }).bin, '/b');
  assert.equal(normalizeNodeFacts({ driver: '/d', bin: '/b' }).driver, '/d');
  assert.equal(normalizeNodeFacts({ driver: '/d', nodeExe: '/n', bin: '/b' }).driver, '/d', 'the current name wins when both are present');
  assert.equal(normalizeNodeFacts(undefined), undefined);
});

// ---------------------------------------------------------------------------
// 5. THIS TEST IS NOT VACUOUS — it fails on the invocation that broke the node
// ---------------------------------------------------------------------------

test('the check above would have caught the shipped invocation: an interpreter-only linux row is a failing row', () => {
  // The row as it was: a version-stamped interpreter path, no executor, no
  // credential file. Every assertion here is the assertion that would have fired.
  const shipped = {
    ssh: 'linux-pc-ts',
    hosts: ['zabz-tech-linux'],
    shell: 'posix',
    nodeExe: '/home/zabz/.local/node-v24.12.0-linux-x64/bin/node',
    dshBin: '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js',
    cwd: '/home/zabz/code',
  };
  const resolved = resolveNodeInvocation(shipped);
  assert.equal(resolved.form, 'interpreter', 'the shipped row had no executor — that is the defect, reproduced');
  assert.match(resolved.driver, /node-v24\.12\.0-linux-x64/, 'and its interpreter carried a version stamp, which is what rotted');
  assert.match(resolved.credentialSource, /^UNKNOWN/, 'and nothing in the row said where the credential comes from');
  // The credential-source assertion of §2, applied to that row, is a failure:
  const posixInterpreterWithNoCredential =
    resolved.form === 'interpreter' && shipped.shell === 'posix' && resolved.credentialEnvFiles.length === 0;
  assert.equal(posixInterpreterWithNoCredential, true, 'the shipped row is exactly the row the credential check rejects');
});

test('the executor form is a different invocation from the interpreter form — the equivalence that hid the defect is gone', () => {
  const executor = executionFormFor('zabz-tech-linux');
  const interpreter = formOf({
    shell: 'posix',
    driver: NODES['zabz-tech-linux'].driver,
    bin: NODES['zabz-tech-linux'].bin,
  });
  assert.equal(executor.form, 'executor');
  assert.equal(interpreter.form, 'interpreter');
  assert.notDeepEqual(executor, interpreter, 'the wrapper and the interpreter pair must not be treated as the same invocation');
});
