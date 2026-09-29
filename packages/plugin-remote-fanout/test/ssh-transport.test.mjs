import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { createSshTransport, encodePwshCommand, remoteArgv } from '../lib/ssh-transport.js';

const tmpDir = os.tmpdir();
const leftoverStreamFiles = () => readdirSync(tmpDir).filter((name) => /^fanout-[0-9a-f]{12}\.(out|err)$/.test(name));

test('a PowerShell script is delivered on stdin by default, and the encoded form is opt-in', () => {
  const argv = remoteArgv('powershell', "Write-Output 'hi there'");
  assert.deepEqual(argv, ['powershell', '-NoProfile', '-NonInteractive', '-Command', '-']);
  const encoded = remoteArgv('powershell', "Write-Output 'hi there'", { delivery: 'encoded' });
  assert.deepEqual(encoded.slice(0, 4), ['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand']);
  assert.equal(Buffer.from(encoded[4], 'base64').toString('utf16le'), "Write-Output 'hi there'");
  assert.equal(encoded.length, 5);
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
  // stdin is a pipe now (that is how the program is delivered); stdout and
  // stderr must still be the temp-file fds, never pipes.
  assert.match(source, /stdio: \[useStdin \? 'pipe' : 'ignore', outFd, errFd\]/);
  assert.equal(source.includes("'ignore', 'pipe', 'pipe'"), false);
});

// ── D4: THE ARGV CEILING ─────────────────────────────────────────────────────
// The old PowerShell delivery base64'd the whole program into argv
// (`-EncodedCommand`, ~2.67 chars of argv per char of task) and a 12000-char
// task produced an argv of 33859: spawn ENAMETOOLONG before the child started.
// The program now travels on STDIN for both shells, so the argv is fixed and
// does not grow with the task.
test('the PowerShell program travels on stdin, so the argv is constant and carries no task text', () => {
  const small = remoteArgv('powershell', "Write-Output 'hi'");
  const large = remoteArgv('powershell', 'X'.repeat(50000));
  assert.deepEqual(small, ['powershell', '-NoProfile', '-NonInteractive', '-Command', '-']);
  assert.deepEqual(large, small, 'argv must not grow with the program size');
  assert.equal(large.join(' ').includes('XXXX'), false, 'no program text may reach argv');
});

test('the explicit encoded delivery is still available, and a payload past the Windows cap is REFUSED', () => {
  const encoded = remoteArgv('powershell', 'x', { delivery: 'encoded' });
  assert.equal(encoded[3], '-EncodedCommand');
  assert.equal(Buffer.from(encoded[4], 'base64').toString('utf16le'), 'x');
  assert.throws(
    () => remoteArgv('powershell', 'x'.repeat(40000), { delivery: 'encoded' }),
    /too large for the transport|command line/i,
  );
});

test('a 12000-character program is delivered on stdin inside a short argv', async () => {
  const program = `# ${'brief '.repeat(2000)}\n[Console]::Out.WriteLine('FANOUT_EXIT_x=0')`;
  assert.ok(program.length > 12000, `precondition: program is ${program.length} chars`);
  const argv = remoteArgv('powershell', program);
  assert.ok(argv.join(' ').length < 200, `argv must stay tiny, was ${argv.join(' ').length}`);
  const clientScript = 'let s="";process.stdin.on("data",(d)=>{s+=d});process.stdin.on("end",()=>{process.stdout.write("STDIN="+s.length)});';
  const transport = createSshTransport({ sshExe: process.execPath, sshArgs: ['-e', clientScript], target: 'ignored' });
  const handle = transport.start({ shell: 'powershell', script: program, timeoutMs: 20000 });
  const outcome = await handle.done;
  assert.equal(outcome.exitCode, 0);
  assert.match(outcome.stdout, /STDIN=120\d\d/, 'the whole program must arrive on the remote stdin');
});

// ── D3: A SEVERED TRANSPORT KEEPS WHAT ARRIVED ───────────────────────────────
// P2538b: two of four children died with Connection reset and nothing survived
// because the answer was only ever held in the transport. This transport already
// reads its temp files on ANY settle (close, error, timeout), so whatever the
// target wrote before the cut is still returned — and it is the child's own
// outbox (mesh_collect) that is the durable copy. Guard the first half.
test('a client that dies mid-run still yields the bytes it wrote before the cut', async () => {
  const clientScript = 'process.stdout.write("FANOUT_TRANSPORT_HOST_dead00=NODE-A\\nPARTIAL=kept\\n");'
    + 'process.exit(255);';
  const transport = createSshTransport({ sshExe: process.execPath, sshArgs: ['-e', clientScript], target: 'ignored' });
  const handle = transport.start({ shell: 'powershell', script: 'x', timeoutMs: 20000 });
  const outcome = await handle.done;
  assert.equal(outcome.exitCode, 255);
  assert.match(outcome.stdout, /PARTIAL=kept/, 'a severed transport must not discard what already arrived');
  const { parseFanout } = await import('../lib/remote-script.js');
  assert.equal(parseFanout(outcome.stdout, 'dead00').host, 'NODE-A');
});
