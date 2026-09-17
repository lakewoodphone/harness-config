import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildPosixScript,
  buildPwshScript,
  invocationFor,
  markers,
  parseFanout,
  psQuote,
  shQuote,
  shellWord,
  shouldRetryWithFallback,
  singleLine,
} from '../lib/remote-script.js';
import { NODES, resolveNodeInvocation } from '../lib/nodes.js';

test('psQuote doubles single quotes and never leaves a bare one', () => {
  assert.equal(psQuote("it's"), "'it''s'");
  assert.equal(psQuote('C:\\Program Files\\nodejs\\node.exe'), "'C:\\Program Files\\nodejs\\node.exe'");
});

test('shQuote closes and reopens around a single quote', () => {
  assert.equal(shQuote("it's"), "'it'\\''s'");
});

test('singleLine collapses newlines and runs of whitespace', () => {
  assert.equal(singleLine('  a\nb\r\n\n c  '), 'a b c');
});

test('the pwsh script sets DSH_HOME, frames the answer, and propagates the exit code', () => {
  const script = buildPwshScript({
    driver: 'C:\\Program Files\\nodejs\\node.exe',
    bin: 'C:\\cache\\dsh\\lib\\bin.js',
    profile: 'headless',
    dshHome: 'C:\\tmp\\child-home',
    cwd: 'C:\\Users\\ezabz',
    task: "read it's file",
    nonce: 'abcd1234',
  });
  assert.match(script, /\$env:DSH_HOME = 'C:\\tmp\\child-home'/);
  assert.match(script, /Set-Location -LiteralPath 'C:\\Users\\ezabz'/);
  assert.match(script, /FANOUT_TRANSPORT_HOST_abcd1234=/);
  assert.match(script, /FANOUT_BEGIN_abcd1234/);
  assert.match(script, /^& 'C:\\Program Files\\nodejs\\node\.exe' 'C:\\cache\\dsh\\lib\\bin\.js' '--profile' 'headless' 'read it''s file'$/m);
  assert.match(script, /\[Environment\]::Exit\(\$fanoutExit\)/);
});

test('the pwsh script can invoke an executor by name too — a Windows node that grows one is not special-cased', () => {
  const script = buildPwshScript({ command: 'dsh.cmd', profile: 'headless', task: 'x', nonce: 'w1' });
  assert.match(script, /^& 'dsh\.cmd' '--profile' 'headless' 'x'$/m);
  assert.match(script, /# invocation form: executor/);
});

test('the posix script is a sh program with the same frame', () => {
  const script = buildPosixScript({
    driver: '/home/zabz/.local/node/bin/node',
    bin: '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js',
    profile: 'headless',
    dshHome: '/home/zabz/.dsh-worker',
    cwd: '/home/zabz/code',
    task: 'hostname',
    nonce: 'ff00',
  });
  assert.match(script, /export DSH_HOME='\/home\/zabz\/\.dsh-worker'/);
  assert.match(script, /^cd '\/home\/zabz\/code'$/m);
  assert.match(script, /FANOUT_BEGIN_ff00/);
  assert.match(script, /exit \$fanout_exit/);
  // The interpreter form, named as such in the generated program so a reader of
  // a captured script knows which form ran (the defect's whole cost was that
  // nobody could tell).
  assert.match(script, /# invocation form: interpreter/);
});

test('the pre-2026-09-17 field names still build: `nodeExe`/`dshBin` are read, never required', () => {
  const script = buildPwshScript({
    nodeExe: 'C:\\Program Files\\nodejs\\node.exe',
    dshBin: 'C:\\cache\\dsh\\lib\\bin.js',
    profile: 'headless',
    task: 'x',
    nonce: 'n1',
  });
  assert.match(script, /^& 'C:\\Program Files\\nodejs\\node\.exe' 'C:\\cache\\dsh\\lib\\bin\.js' '--profile' 'headless' 'x'$/m);
});

// ---------------------------------------------------------------------------
// THE EXECUTOR FORM (`docs/mesh/102-linux-dispatch.md`) — the wrapper is
// invoked BY NAME, because it is the thing that sources the credential.
// ---------------------------------------------------------------------------

test('a node with an executor is invoked by name, and carries its credential source', () => {
  const spec = { command: 'dsh', credentialEnvFiles: ['/etc/dsh-worker.env'], shell: 'posix', cwd: '/home/zabz/code' };
  const script = buildPosixScript({ ...spec, profile: 'headless', task: 'hostname', nonce: 'e1' });
  assert.match(script, /^dsh --profile headless 'hostname'$/m, 'the wrapper is invoked by name, with no interpreter path in front of it');
  assert.match(script, /# invocation form: executor/);
  // The wrapper sources the env file itself, so the script must NOT source it
  // again — one credential path, not two.
  assert.doesNotMatch(script, /set -a/);
});

test('the interpreter fallback sources the worker credential file before it runs', () => {
  const script = buildPosixScript({
    driver: '/usr/local/bin/node',
    bin: '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js',
    credentialEnvFiles: ['/etc/dsh-worker.env'],
    profile: 'headless',
    task: 'hostname',
    nonce: 'e2',
  });
  const lines = script.split('\n');
  const sourceAt = lines.findIndex((line) => line.includes(". '/etc/dsh-worker.env'"));
  const runAt = lines.findIndex((line) => line.startsWith('/usr/local/bin/node'));
  assert.notEqual(sourceAt, -1, 'the credential file must be sourced');
  assert.match(lines[sourceAt], /set -a/);
  assert.ok(sourceAt < runAt, 'the credential must be exported BEFORE the child is launched');
});

test('the fallback retry fires only for "this invocation could not be launched"', () => {
  const notFound = { exitCode: 127, stderr: 'sh: 6: /home/zabz/.local/node-v24.12.0-linux-x64/bin/node: not found\n' };
  assert.equal(shouldRetryWithFallback(notFound, { framed: false }), true);
  assert.equal(shouldRetryWithFallback({ spawnError: 'spawn ssh ENOENT' }, { framed: false }), true);
  // Everything else is the child's own outcome and must never be re-run.
  assert.equal(shouldRetryWithFallback({ exitCode: 1, stderr: 'dsh: MISSING_CREDENTIAL: llm-deepseek' }, { framed: false }), false, 'a credential error is not a missing command');
  assert.equal(shouldRetryWithFallback({ exitCode: 1, stderr: 'MODEL_REFUSED' }, { framed: true }), false);
  assert.equal(shouldRetryWithFallback({ exitCode: 0, stderr: '', framed: true }, { framed: true }), false);
  assert.equal(shouldRetryWithFallback({ exitCode: 127, timedOut: true }, { framed: false }), false, 'a timeout is not a missing command');
  assert.equal(shouldRetryWithFallback({ exitCode: 127, killed: 'aborted', stderr: 'x: not found' }, { framed: false }), false, 'a cancelled run must not be retried');
  assert.equal(shouldRetryWithFallback({ exitCode: 127, stderr: 'x: not found' }, { framed: true }), false, 'a framed run that exited 127 is the child talking, not the launcher failing');
});

test('a spec with neither an executor nor a complete pair refuses to build a script', () => {
  assert.throws(() => buildPosixScript({ nodeExe: '/usr/bin/node', profile: 'headless', task: 'x' }), /no invocation for this node/);
  assert.throws(() => buildPosixScript({ profile: 'headless', task: 'x' }), /no invocation for this node/);
});

test('invocationFor reads the shipped linux row into the executor form, in one step', () => {
  const resolved = invocationFor(NODES['zabz-tech-linux']);
  assert.equal(resolved.form, 'executor');
  assert.equal(invocationFor({ ...NODES['zabz-tech-linux'], command: undefined }).form, 'interpreter');
  assert.equal(invocationFor({ invocation: { form: 'executor', command: 'x' } }).command, 'x', 'a resolved invocation is passed through untouched');
  assert.equal(invocationFor({ shell: 'posix', driver: '/usr/bin/node', bin: '/x/bin.js' }).form, 'interpreter');
  assert.equal(resolveNodeInvocation({ shell: 'posix', driver: '/usr/bin/node', bin: '/x/bin.js' }).form, 'interpreter');
});

test('shellWord emits names and paths bare and quotes anything else', () => {
  assert.equal(shellWord('dsh'), 'dsh');
  assert.equal(shellWord('/usr/local/bin/node'), '/usr/local/bin/node');
  assert.equal(shellWord('--profile'), '--profile');
  assert.equal(shellWord("it's"), `'it'\\''s'`);
  assert.equal(shellWord('a b'), "'a b'");
});

test('parseFanout reads the transport facts, the answer, and the exit code', () => {
  const nonce = 'abcd1234';
  const m = markers(nonce);
  const stdout = [
    'Windows PowerShell',
    'Copyright (C) Microsoft Corporation. All rights reserved.',
    `${m.host}ZABZ-YOGA`,
    `${m.cwd}C:\\Users\\ezabz`,
    m.begin,
    'CHILD_HOST=ZABZ-YOGA',
    'CHILD_FILE=LAPTOP-MARKER',
    'TOKEN=REMOTE-CHILD-1',
    m.end,
    `${m.exit}0`,
  ].join('\r\n');
  const parsed = parseFanout(stdout, nonce);
  assert.equal(parsed.host, 'ZABZ-YOGA');
  assert.equal(parsed.cwd, 'C:\\Users\\ezabz');
  assert.equal(parsed.exitCode, 0);
  assert.equal(parsed.framed, true);
  assert.equal(parsed.answer, 'CHILD_HOST=ZABZ-YOGA\nCHILD_FILE=LAPTOP-MARKER\nTOKEN=REMOTE-CHILD-1');
});

test('parseFanout refuses to frame a run whose markers never arrived', () => {
  const parsed = parseFanout('Error: dsh: cannot resolve profile bundle "x"\n', 'abcd1234');
  assert.equal(parsed.framed, false);
  assert.equal(parsed.answer, '');
  assert.equal(parsed.host, undefined);
});

test('a child that prints the marker words itself cannot truncate the frame', () => {
  const nonce = 'abcd1234';
  const m = markers(nonce);
  const stdout = [m.begin, 'FANOUT_END', 'still inside', m.end, `${m.exit}0`].join('\n');
  const parsed = parseFanout(stdout, nonce);
  assert.equal(parsed.answer, 'FANOUT_END\nstill inside');
});
