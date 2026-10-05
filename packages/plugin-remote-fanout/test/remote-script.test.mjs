import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import {
  buildPosixScript,
  buildPwshScript,
  END_OF_OPTIONS,
  escapeForNativeArgv,
  TASK_SEPARATOR_WORDS,
  harvestOutput,
  invocationFor,
  markers,
  parseFanout,
  parseProgress,
  psQuote,
  shQuote,
  shellWord,
  shouldRetryWithFallback,
  singleLine,
} from '../lib/remote-script.js';
import { NODES, resolveNodeInvocation } from '../lib/nodes.js';

// The brief's own temp area; a test that needs a temp dir creates it here.
const TEST_TMP = process.env.MESHFIX_TRANSPORT_TMP ?? path.join(os.homedir(), 'code', '_meshfix', 'tmp', 'transport');

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
  assert.match(script, /^& 'C:\\Program Files\\nodejs\\node\.exe' 'C:\\cache\\dsh\\lib\\bin\.js' '--profile' 'headless' '--' '--' 'read it''s file'$/m);
  assert.match(script, /\[Environment\]::Exit\(\$fanoutExit\)/);
});

test('the pwsh script can invoke an executor by name too — a Windows node that grows one is not special-cased', () => {
  const script = buildPwshScript({ command: 'dsh.cmd', profile: 'headless', task: 'x', nonce: 'w1' });
  assert.match(script, /^& 'dsh\.cmd' '--profile' 'headless' '--' '--' 'x'$/m);
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
  assert.match(script, /^& 'C:\\Program Files\\nodejs\\node\.exe' 'C:\\cache\\dsh\\lib\\bin\.js' '--profile' 'headless' '--' '--' 'x'$/m);
});

// ---------------------------------------------------------------------------
// THE EXECUTOR FORM (`docs/mesh/102-linux-dispatch.md`) — the wrapper is
// invoked BY NAME, because it is the thing that sources the credential.
// ---------------------------------------------------------------------------

test('a node with an executor is invoked by name, and carries its credential source', () => {
  const spec = { command: 'dsh', credentialEnvFiles: ['/etc/dsh-worker.env'], shell: 'posix', cwd: '/home/zabz/code' };
  const script = buildPosixScript({ ...spec, profile: 'headless', task: 'hostname', nonce: 'e1' });
  assert.match(script, /^dsh --profile headless -- -- 'hostname'$/m, 'the wrapper is invoked by name, with no interpreter path in front of it');
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

// ---------------------------------------------------------------------------
// harvestOutput — the salvage half of a failed run (F1/F2).
// ---------------------------------------------------------------------------

test('harvestOutput salvages the answer, both stream tails and the outcome, in that order', () => {
  const nonce = 'feed';
  const m = markers(nonce);
  const stdout = [m.begin, 'THE CHILD ANSWER', m.end, `${m.exit}0`].join('\n');
  const parsed = parseFanout(stdout, nonce);
  const outcome = { exitCode: 0, signal: undefined, timedOut: false, ms: 1234, stdout, stderr: 'some noise' };
  const harvested = harvestOutput(outcome, parsed);
  assert.equal(harvested.complete, true);
  assert.deepEqual(harvested.parts.map((part) => part.source), ['answer', 'stdout-tail', 'stderr-tail', 'outcome']);
  assert.match(harvested.text, /THE CHILD ANSWER/);
  assert.match(harvested.text, /raw stdout tail/);
  assert.match(harvested.text, /some noise/);
  assert.match(harvested.text, /exit=0, signal=none, timedOut=false, ms=1234/);
  const answerAt = harvested.text.indexOf('THE CHILD ANSWER');
  const stdoutAt = harvested.text.indexOf('--- raw stdout tail ---');
  const stderrAt = harvested.text.indexOf('--- raw stderr tail ---');
  const outcomeAt = harvested.text.indexOf('outcome: exit=');
  assert.ok(answerAt < stdoutAt && stdoutAt < stderrAt && stderrAt < outcomeAt, 'the parts must be ordered answer, stdout, stderr, summary');
});

test('harvestOutput with everything empty returns a non-empty explanation, not an empty string', () => {
  const harvested = harvestOutput({}, { framed: false });
  assert.equal(harvested.complete, false);
  assert.notEqual(harvested.text, '');
  assert.match(harvested.text, /no output was recovered/);
  assert.match(harvested.text, /exit=none/);
  assert.equal(harvested.parts.length, 1);
  assert.equal(harvested.parts[0].source, 'outcome');
});

test('harvestOutput is complete only when the child frame closed', () => {
  const unframed = harvestOutput({ stdout: 'raw bytes with no frame' }, { framed: false, answer: '' });
  assert.equal(unframed.complete, false);
  assert.match(unframed.text, /raw bytes with no frame/);
  const framed = harvestOutput({}, { framed: true, answer: 'ok' });
  assert.equal(framed.complete, true);
});

test('harvestOutput bounds each recovered tail to maxBytes', () => {
  const stdout = 'H'.repeat(100) + 'TAIL';
  const stderr = 'E'.repeat(100) + 'ERRTAIL';
  const harvested = harvestOutput({ stdout, stderr, exitCode: 255 }, { framed: false }, { maxBytes: 8 });
  const stdoutPart = harvested.parts.find((part) => part.source === 'stdout-tail');
  const stderrPart = harvested.parts.find((part) => part.source === 'stderr-tail');
  assert.equal(stdoutPart.text, 'HHHHTAIL');
  assert.equal(stdoutPart.truncated, true);
  assert.equal(stderrPart.text, 'EERRTAIL');
  assert.ok(
    harvested.parts.filter((part) => part.source.endsWith('-tail')).every((part) => Buffer.byteLength(part.text, 'utf8') <= 8),
    'no recovered stream tail may exceed maxBytes',
  );
});

test('harvestOutput never throws on undefined fields, bad options, or invalid UTF-8 boundaries', () => {
  for (const args of [
    [],
    [undefined, undefined],
    [null, null, null],
    [{}, {}, { maxBytes: 0 }],
    [{ exitCode: 255, stdout: Buffer.from([0x41, 0xc3]) }, { framed: false }, { maxBytes: 1 }],
    [{ stdout: Buffer.from('é', 'utf8').subarray(1) }, { framed: true, answer: Buffer.from('x') }],
  ]) {
    const harvested = harvestOutput(...args);
    assert.equal(typeof harvested.text, 'string');
    assert.ok(harvested.text.length > 0);
    assert.equal(typeof harvested.complete, 'boolean');
    assert.ok(Array.isArray(harvested.parts));
  }
  // A split multibyte sequence becomes a replacement character, not a throw.
  const split = harvestOutput({ stdout: Buffer.from([0x41, 0xc3]) }, { framed: false }, { maxBytes: 1 });
  assert.match(split.text, /\uFFFD|A/);
});

// ---------------------------------------------------------------------------
// THE PROGRESS LOG — the parent can tell a silent child from a working one.
// ---------------------------------------------------------------------------

test('the framed pwsh stdout is byte-identical when progressFile is not supplied', () => {
  const invocation = { form: 'executor', command: 'dsh', credentialSource: 'the wrapper sources the credential' };
  const expected = [
    '# generated by dsh-plugin-remote-fanout — one remote one-shot subagent turn',
    '# invocation form: executor — the wrapper sources the credential',
    "$ErrorActionPreference = 'Continue'",
    "$ProgressPreference = 'SilentlyContinue'",
    "[Console]::Out.WriteLine('FANOUT_TRANSPORT_HOST_n=' + $env:COMPUTERNAME)",
    "[Console]::Out.WriteLine('FANOUT_TRANSPORT_CWD_n=' + (Get-Location).Path)",
    "[Console]::Out.WriteLine('FANOUT_BEGIN_n')",
    "& 'dsh' '--profile' 'headless' '--' '--' 'x'",
    '$fanoutExit = $LASTEXITCODE',
    "[Console]::Out.WriteLine('FANOUT_END_n')",
    "[Console]::Out.WriteLine('FANOUT_EXIT_n=' + $fanoutExit)",
    '[Environment]::Exit($fanoutExit)',
  ].join('\n');
  const spec = { invocation, profile: 'headless', task: 'x', nonce: 'n' };
  assert.equal(buildPwshScript(spec), expected);
  assert.equal(buildPwshScript({ ...spec, progressFile: undefined }), expected);
  assert.doesNotMatch(expected, /FANOUT_PROGRESS|Tee-Object|fanoutProgress/);
});

test('the framed posix stdout is byte-identical when progressFile is not supplied', () => {
  const invocation = { form: 'executor', command: 'dsh', credentialSource: 'the wrapper' };
  const expected = [
    '# generated by dsh-plugin-remote-fanout — one remote one-shot subagent turn',
    '# invocation form: executor — the wrapper',
    `fanout_host=$(hostname)`,
    `printf '%s\\n' "FANOUT_TRANSPORT_HOST_n=$fanout_host"`,
    `printf '%s\\n' "FANOUT_TRANSPORT_CWD_n=$(pwd)"`,
    `printf '%s\\n' "FANOUT_BEGIN_n"`,
    `dsh --profile headless -- -- 'x'`,
    'fanout_exit=$?',
    `printf '%s\\n' "FANOUT_END_n"`,
    `printf '%s\\n' "FANOUT_EXIT_n=$fanout_exit"`,
    'exit $fanout_exit',
  ].join('\n');
  const spec = { invocation, profile: 'headless', task: 'x', nonce: 'n' };
  assert.equal(buildPosixScript(spec), expected);
  assert.equal(buildPosixScript({ ...spec, progressFile: undefined }), expected);
  assert.doesNotMatch(expected, /FANOUT_PROGRESS|tee -a|fanout_progress/);
});

test('the pwsh script starts, tees and closes the progress log when asked', () => {
  const progressPath = 'C:\\tmp\\fanout-progress.log';
  const script = buildPwshScript({ command: 'dsh', profile: 'headless', task: 'x', nonce: 'p1', progressFile: progressPath });
  assert.equal(script.includes(`$fanoutProgress = ${psQuote(progressPath)}`), true);
  assert.match(script, /FANOUT_PROGRESS:START host=/);
  assert.match(script, /FANOUT_PROGRESS:EXIT code=/);
  assert.match(script, /Add-Content -LiteralPath \$fanoutProgress/);
  assert.match(script, /Tee-Object -FilePath \$fanoutProgress -Append/);
  assert.match(script, /2>> \$fanoutProgress/);
  // The start line is written before the child, and the exit line after it.
  const startAt = script.indexOf('FANOUT_PROGRESS:START');
  const childAt = script.indexOf("& 'dsh'");
  const exitAt = script.indexOf('FANOUT_PROGRESS:EXIT');
  assert.ok(startAt < childAt && childAt < exitAt, 'start < child < exit in the generated program');
});

test('the posix script starts, tees both streams and closes the progress log when asked', () => {
  const progressPath = '/tmp/fanout-progress.log';
  const script = buildPosixScript({ command: 'dsh', profile: 'headless', task: 'x', nonce: 'p2', progressFile: progressPath });
  assert.equal(script.includes(`fanout_progress=${shQuote(progressPath)}`), true);
  assert.match(script, /FANOUT_PROGRESS:START host=/);
  assert.match(script, /FANOUT_PROGRESS:EXIT code=/);
  assert.match(script, /tee -a "\$fanout_progress"/);
  assert.match(script, /2>&1 1>&3/);
  const startAt = script.indexOf('FANOUT_PROGRESS:START');
  const childAt = script.indexOf('dsh --profile headless');
  const exitAt = script.indexOf('FANOUT_PROGRESS:EXIT');
  assert.ok(startAt < childAt && childAt < exitAt, 'start < child < exit in the generated program');
});

test('parseProgress reads the control lines and keeps only the child output as lines', () => {
  const log = [
    'FANOUT_PROGRESS:START host=ZABZ-YOGA pid=1234 at=2026-09-30T18:00:00Z',
    'child answer line 1',
    'child stderr line',
    'FANOUT_PROGRESS:EXIT code=0 at=2026-09-30T18:00:05Z',
  ].join('\r\n');
  const progress = parseProgress(log);
  assert.equal(progress.startedAt, '2026-09-30T18:00:00Z');
  assert.equal(progress.host, 'ZABZ-YOGA');
  assert.equal(progress.pid, 1234);
  assert.equal(progress.lastAt, '2026-09-30T18:00:05Z');
  assert.equal(progress.exit, 0);
  assert.deepEqual(progress.lines, ['child answer line 1', 'child stderr line']);
});

test('parseProgress never throws on an empty, partial or unknown log', () => {
  for (const input of [undefined, null, '', 'FANOUT_PROGRESS:START host=x', 'FANOUT_PROGRESS:UNKNOWN foo=bar\nchild']) {
    const progress = parseProgress(input);
    assert.ok(Array.isArray(progress.lines));
  }
  const partial = parseProgress('FANOUT_PROGRESS:START host=x pid=notanumber\nchild still talking');
  assert.equal(partial.host, 'x');
  assert.equal(partial.pid, 'notanumber');
  assert.deepEqual(partial.lines, ['child still talking']);
});

test('the generated posix program writes a parseable progress log and keeps the frame', { skip: process.platform === 'win32' }, () => {
  mkdirSync(TEST_TMP, { recursive: true });
  const dir = mkdtempSync(path.join(TEST_TMP, 'progress-'));
  try {
    const progressPath = path.join(dir, 'progress.log');
    const nonce = 'run1';
    const script = buildPosixScript({
      invocation: {
        form: 'interpreter',
        command: 'sh',
        argvPrefix: ['-c', 'printf "CHILD_LINE\\n"; printf "CHILD_ERR\\n" >&2; exit 4'],
        credentialSource: 'test',
      },
      profile: 'headless',
      task: 'hello',
      nonce,
      progressFile: progressPath,
    });
    const run = spawnSync('sh', ['-s'], { input: script, encoding: 'utf8', timeout: 15000 });
    assert.equal(run.status, 4, `expected the child's exit code, got ${run.status}: ${run.stderr}`);

    // The framed stdout contract still holds, and stdout still reaches the frame.
    const parsed = parseFanout(run.stdout, nonce);
    assert.equal(parsed.framed, true);
    assert.equal(parsed.exitCode, 4);
    assert.match(parsed.answer, /CHILD_LINE/);
    // stderr was tee'd, so it still reaches the transport too.
    assert.match(run.stderr, /CHILD_ERR/);

    // And the progress log carries the start, both streams, and the exit.
    const progress = parseProgress(readFileSync(progressPath, 'utf8'));
    assert.equal(progress.host, os.hostname());
    assert.equal(progress.exit, 4);
    assert.ok(progress.startedAt, 'the start line must carry a timestamp');
    assert.ok(progress.lastAt, 'the exit line must carry a timestamp');
    assert.ok(progress.lines.some((line) => line.includes('CHILD_LINE')), 'child stdout must be in the log');
    assert.ok(progress.lines.some((line) => line.includes('CHILD_ERR')), 'child stderr must be in the log');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('an unwritable progress log never fails the run', { skip: process.platform === 'win32' }, () => {
  const nonce = 'p3';
  const script = buildPosixScript({
    invocation: { form: 'interpreter', command: 'echo', credentialSource: 'test' },
    profile: 'headless',
    task: 'x',
    nonce,
    progressFile: '/proc/definitely-not-writable/progress.log',
  });
  const run = spawnSync('sh', ['-s'], { input: script, encoding: 'utf8', timeout: 15000 });
  assert.equal(run.status, 0, `the child must still run: ${run.stderr}`);
  const parsed = parseFanout(run.stdout, nonce);
  assert.equal(parsed.framed, true, 'the frame must still close when the log cannot be written');
  assert.equal(parsed.exitCode, 0);
});

// ---------------------------------------------------------------------------
// THE 2026-10-05 ARGUMENT-PARSING DEFECT — pinned so it cannot come back
// silently. Full incident: the mailbox preamble begins with `--- mesh mailbox`,
// so EVERY mailbox dispatch handed `dsh` a positional argument whose first
// character was `-`; the CLI read it as an option and died with
//   error: unknown option '--- mesh mailbox (read this before the task) --- …'
// exit 1, frame closed, answer empty — which the parent reports as "the remote
// one-shot exited 1 and produced no final message".
// ---------------------------------------------------------------------------

test('a task whose first character is `-` is never parsed as an option (both builders)', () => {
  const tasks = [
    '--- mesh mailbox (read this before the task) ---\nMESH_MAILBOX={"dir":"C:/x"}\n--- task ---\nhi',
    '--help',
    '- not a bullet, an argument',
  ];
  const sep = TASK_SEPARATOR_WORDS.map((w) => `'${w}'`).join(' ');
  for (const task of tasks) {
    const pwsh = buildPwshScript({ command: 'dsh', profile: 'headless', task, nonce: 'dash' });
    assert.match(pwsh, new RegExp(`^& 'dsh' '--profile' 'headless' ${sep} `, 'm'), `pwsh: ${task.slice(0, 20)}`);
    const posix = buildPosixScript({ command: 'dsh', profile: 'headless', task, nonce: 'dash' });
    assert.match(posix, new RegExp(`^dsh --profile headless ${TASK_SEPARATOR_WORDS.join(' ')} `, 'm'), `posix: ${task.slice(0, 20)}`);
  }
});

test('the task is fenced by TWO end-of-options words: the launcher eats exactly one', () => {
  // Measured 2026-10-05: `dsh` is a launcher whose own commander consumes a `--`,
  // and `dsh-headless` is a second commander that reads the task. One `--` is
  // therefore invisible to the program that needs it; two reach it.
  assert.deepEqual([...TASK_SEPARATOR_WORDS], ['--', '--']);
  const script = buildPwshScript({ command: 'dsh', profile: 'headless', task: 'x', nonce: 'n' });
  const line = script.split('\n').find((l) => l.startsWith('& '));
  assert.equal(line, "& 'dsh' '--profile' 'headless' '--' '--' 'x'");
  // Exactly two, immediately before the task: the third would be a positional.
  assert.equal(line.split("'--'").length - 1, 2);
  const posix = buildPosixScript({ command: 'dsh', profile: 'headless', task: 'x', nonce: 'n' });
  assert.match(posix, /^dsh --profile headless -- -- 'x'$/m);
});

test('a quote in a native argument is escaped, because Windows PowerShell 5.1 eats it unescaped', () => {
  // Measured 2026-10-05 through the real transport, node -e echoing process.argv:
  //   `has "double" quotes`  -> child got `has double quotes`
  //   the same value escaped -> child got `has "double" quotes`
  assert.equal(escapeForNativeArgv('has "double" quotes'), 'has \\"double\\" quotes');
  assert.equal(escapeForNativeArgv('MESH_MAILBOX={"dir":"C:/x"}'), 'MESH_MAILBOX={\\"dir\\":\\"C:/x\\"}');
  // The MSVCRT rule: a backslash run before a quote is doubled, and a trailing run
  // is doubled because the runtime appends the closing quote.
  assert.equal(escapeForNativeArgv('a\\"b'), 'a\\\\\\"b');
  assert.equal(escapeForNativeArgv('trailing\\'), 'trailing\\\\');
  // Nothing else is touched, so paths and flags pass through byte-identical.
  assert.equal(escapeForNativeArgv('C:/Program Files/nodejs/node.exe'), 'C:/Program Files/nodejs/node.exe');
  assert.equal(escapeForNativeArgv(END_OF_OPTIONS), '--');
});

test('the pwsh script carries the task escaped, and the task survives the shell round trip', () => {
  const task = 'Create "config.json" with {"a":1}';
  const script = buildPwshScript({ command: 'dsh', profile: 'headless', task, nonce: 'q' });
  const line = script.split('\n').find((l) => l.startsWith('& '));
  // The generated program must not contain an UNESCAPED double quote: PowerShell
  // splices the argument into the native command line and the C runtime would eat
  // it. Every `"` must therefore be preceded by the backslash the escape added.
  const separator = "'--' '--' ";
  const taskWord = line.slice(line.indexOf(separator) + separator.length);
  assert.equal(/(^|[^\\])"/.test(taskWord), false, 'no unescaped quote reaches the native command line');
  assert.match(taskWord, /\\"/);
  // And the word is exactly the escaped task, in PowerShell's literal quoting —
  // pinned as an equality so a second quoting layer cannot creep in.
  assert.equal(taskWord, psQuote(escapeForNativeArgv(task)));
});
test('the mailbox brief the transport prepends is not option-shaped either', async () => {
  // Second layer, measured: `dsh` reads a `-`-leading task as an option. The
  // separator above makes any task a positional; this pins the shipped brief so a
  // future wording cannot reintroduce the `---` opening that caused the outage.
  const { childInstructions, mailboxPaths } = await import('../lib/mailbox.js');
  const paths = mailboxPaths({ root: '/tmp/mb', thread: 't1' });
  const brief = childInstructions(paths, { thread: 't1' });
  assert.equal(brief.startsWith('-'), false, `brief must not start with "-": ${brief.slice(0, 30)}`);
  assert.match(brief, /^=== mesh mailbox/);
  // And the JSON manifest is still there, with its path lines intact. (The path
  // separator is the platform's — `path.join` is used — so this asserts the SHAPE,
  // not a POSIX-looking string.)
  assert.match(brief, /MESH_MAILBOX=\{"dir":".*[\\/]t1"/);
  assert.match(brief, /MESH_MAILBOX_B64=[A-Za-z0-9_-]+/);
});