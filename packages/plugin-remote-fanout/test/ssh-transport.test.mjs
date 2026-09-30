import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { createSshTransport, capStreamText, encodePwshCommand, remoteArgv } from '../lib/ssh-transport.js';
import { markers, parseFanout } from '../lib/remote-script.js';

const tmpDir = os.tmpdir();
const leftoverStreamFiles = () => readdirSync(tmpDir).filter((name) => /^fanout-[0-9a-f]{12}\.(out|err)$/.test(name));

test('a PowerShell script is delivered as an encoded command, never as raw argv', () => {
  const argv = remoteArgv('powershell', "Write-Output 'hi there'");
  assert.deepEqual(argv.slice(0, 4), ['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand']);
  const decoded = Buffer.from(argv[4], 'base64').toString('utf16le');
  assert.equal(decoded, "Write-Output 'hi there'");
  assert.equal(argv.length, 5);
});

test('a POSIX script goes on stdin and the remote argv contains no script text', () => {
  const argv = remoteArgv('posix', 'echo hi');
  assert.deepEqual(argv, ['sh', '-s']);
  assert.equal(encodePwshCommand('x').length > 0, true);
});

test('the transport refuses to be built without a target', () => {
  assert.throws(() => createSshTransport({}), /`target` is required/);
});

test('both streams are captured from files, the exit code is reported, and no temp file is left', async () => {
  const before = leftoverStreamFiles().length;
  // A fake ssh client: node ignores the arguments the transport appends, which
  // is exactly the shape the real client receives (target + remote argv).
  const clientScript = 'process.stdout.write("FANOUT_TRANSPORT_HOST_deadbeef=FAKE-NODE\\n");'
    + 'process.stderr.write("reasoning noise\\n");'
    + 'process.exit(3);';
  const transport = createSshTransport({ sshExe: process.execPath, sshArgs: ['-e', clientScript], target: 'ignored' });
  const handle = transport.start({ shell: 'powershell', script: 'never parsed', timeoutMs: 20000 });
  const outcome = await handle.done;

  assert.equal(outcome.ok, false);
  assert.equal(outcome.exitCode, 3);
  assert.match(outcome.stdout, /FANOUT_TRANSPORT_HOST_deadbeef=FAKE-NODE/);
  assert.match(outcome.stderr, /reasoning noise/);
  assert.equal(outcome.timedOut, false);
  assert.equal(outcome.spawnError, undefined);
  assert.equal(leftoverStreamFiles().length, before, 'the temp stream files must be removed');
});

test('output is capped at maxOutputBytes and the cap is reported', async () => {
  const clientScript = 'process.stdout.write("x".repeat(50000));';
  const transport = createSshTransport({ sshExe: process.execPath, sshArgs: ['-e', clientScript], target: 'ignored', maxOutputBytes: 100 });
  const handle = transport.start({ shell: 'powershell', script: 'x', timeoutMs: 20000 });
  const outcome = await handle.done;
  assert.equal(outcome.stdout.length, 100);
  assert.equal(outcome.truncated, true);
});

test('a client that never exits is killed at the bound and reported as a timeout', async () => {
  const clientScript = 'setTimeout(() => {}, 60000);';
  const transport = createSshTransport({ sshExe: process.execPath, sshArgs: ['-e', clientScript], target: 'ignored' });
  const handle = transport.start({ shell: 'powershell', script: 'x', timeoutMs: 1500 });
  const outcome = await handle.done;
  assert.equal(outcome.timedOut, true);
  assert.equal(outcome.killed, 'timeout');
  assert.ok(outcome.ms >= 1400 && outcome.ms < 20000, `unexpected duration ${outcome.ms}`);
});

test('a client that cannot be launched reports a spawn error instead of throwing', async () => {
  const transport = createSshTransport({ sshExe: path.join(tmpDir, 'definitely-not-a-real-binary-1e7f6d'), target: 'ignored' });
  const handle = transport.start({ shell: 'powershell', script: 'x', timeoutMs: 5000 });
  const outcome = await handle.done;
  assert.equal(outcome.ok, false);
  assert.match(String(outcome.spawnError), /ENOENT|not found|no such file/i);
});

test('a client that never exits is settled by the completion frame, not by its own exit', async () => {
  // The fake client prints a complete frame and then hangs forever — exactly
  // what a Windows ssh client was measured doing after a native child ran.
  const clientScript = 'const out = process.stdout;'
    + 'out.write("FANOUT_BEGIN_ab\\nCHILD_OK\\nFANOUT_END_ab\\nFANOUT_EXIT_ab=0\\n");'
    + 'setTimeout(() => {}, 60000);';
  const transport = createSshTransport({ sshExe: process.execPath, sshArgs: ['-e', clientScript], target: 'ignored' });
  const started = Date.now();
  const handle = transport.start({ shell: 'powershell', script: 'x', timeoutMs: 30000, completeMarker: 'FANOUT_EXIT_ab=' });
  const outcome = await handle.done;
  assert.equal(outcome.markerSettled, true);
  assert.equal(outcome.timedOut, false);
  assert.equal(outcome.exitCode, 0);
  assert.match(outcome.stdout, /FANOUT_EXIT_ab=0/);
  assert.ok(Date.now() - started < 5000, 'the frame should settle the run in well under the timeout');
});

test('the framed stdout of a real client run parses end to end', async () => {
  // The real remote script is emitted by the builder; here the "client" is node
  // printing a canned frame so the two halves are wired together once.
  const stdout = [
    'FANOUT_TRANSPORT_HOST_cafebabe=ZABZ-YOGA',
    'FANOUT_TRANSPORT_CWD_cafebabe=C:\\Users\\ezabz',
    'FANOUT_BEGIN_cafebabe',
    'CHILD_OK',
    'FANOUT_END_cafebabe',
    'FANOUT_EXIT_cafebabe=0',
  ].join('\\n');
  const clientScript = `process.stdout.write(${JSON.stringify(stdout)});`;
  const transport = createSshTransport({ sshExe: process.execPath, sshArgs: ['-e', clientScript], target: 'ignored' });
  const handle = transport.start({ shell: 'powershell', script: 'x', timeoutMs: 20000 });
  const outcome = await handle.done;
  const { parseFanout } = await import('../lib/remote-script.js');
  const parsed = parseFanout(outcome.stdout.replace(/\\n/g, '\n'), 'cafebabe');
  assert.equal(parsed.host, 'ZABZ-YOGA');
  assert.equal(parsed.answer, 'CHILD_OK');
  assert.equal(parsed.exitCode, 0);
});

test('the transport never hands ssh a stdout PIPE — the measured hazard stays fixed', () => {
  const source = readFileSync(new URL('../lib/ssh-transport.js', import.meta.url), 'utf8');
  assert.match(source, /stdio: \[shell === 'posix' \? 'pipe' : 'ignore', outFd, errFd\]/);
  assert.equal(source.includes("'ignore', 'pipe', 'pipe'"), false);
});

// ---------------------------------------------------------------------------
// THE OUTPUT CAP KEEPS THE TAIL (the frame lives at the end of stdout).
// ---------------------------------------------------------------------------

test('capStreamText leaves a stream at or under the cap untouched', () => {
  const capped = capStreamText('short enough', 40);
  assert.equal(capped.text, 'short enough');
  assert.equal(capped.truncated, false);
});

test('a capped stream keeps the tail, so the completion frame still parses', () => {
  const nonce = 'c0ffee';
  const m = markers(nonce);
  const filler = 'A'.repeat(5000);
  const stdout = [m.begin, filler, m.end, `${m.exit}0`].join('\n');
  const capped = capStreamText(stdout, 1000);
  assert.equal(capped.truncated, true);
  assert.match(capped.text, /FANOUT_TRUNCATED/);
  // The opening markers are in the head and the closing markers in the tail, so
  // the frame the cap used to destroy now survives it.
  const parsed = parseFanout(capped.text, nonce);
  assert.equal(parsed.framed, true);
  assert.equal(parsed.exitCode, 0);
  assert.equal(parsed.host, undefined, 'this fixture carries no host marker');
});

test('a capped stream still ends with its closing marker line', () => {
  const nonce = 'beef';
  const m = markers(nonce);
  const stdout = [m.host + 'FAKE-NODE', m.begin, 'x'.repeat(4000), m.end, `${m.exit}7`].join('\n');
  const capped = capStreamText(stdout, 800);
  const lastLine = capped.text.split(/\r?\n/).filter((line) => line !== '').at(-1);
  assert.equal(lastLine, `${m.exit}7`);
  const parsed = parseFanout(capped.text, nonce);
  assert.equal(parsed.framed, true);
  assert.equal(parsed.exitCode, 7);
  assert.equal(parsed.host, 'FAKE-NODE');
});

test('the cap never splits a line that carries a frame marker', () => {
  const nonce = 'abc123';
  const m = markers(nonce);
  const filler = 'Q'.repeat(2000);
  const stdout = [
    `${m.host}FAKE-NODE`,
    `${m.cwd}/tmp`,
    m.begin,
    filler,
    m.end,
    `${m.exit}5`,
  ].join('\n');
  const completeMarkers = [m.host, m.cwd, m.begin, m.end, m.exit];
  for (let cap = 150; cap <= 900; cap += 7) {
    const capped = capStreamText(stdout, cap);
    if (!capped.truncated) continue;
    for (const line of capped.text.split(/\r?\n/)) {
      if (!line.startsWith('FANOUT_') || line.startsWith('FANOUT_TRUNCATED')) continue;
      assert.ok(
        completeMarkers.some((marker) => line === marker || line.startsWith(marker)),
        `cap ${cap} left a partial marker line: ${JSON.stringify(line)}`,
      );
    }
    // Once the budget can hold the opening frame in its head and the closing
    // frame in its tail, the frame must survive untouched in meaning.
    if (cap >= 400) {
      const parsed = parseFanout(capped.text, nonce);
      assert.equal(parsed.framed, true, `cap ${cap} must keep the frame`);
      assert.equal(parsed.exitCode, 5, `cap ${cap} must keep the exit marker`);
      assert.equal(parsed.host, 'FAKE-NODE', `cap ${cap} must keep the host marker`);
    }
  }
});
