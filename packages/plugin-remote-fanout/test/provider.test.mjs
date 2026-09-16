import assert from 'node:assert/strict';
import test from 'node:test';

import { NO_START_CAPABILITIES, RemoteOneShotProvider, extractMeshHost, sameNode } from '../lib/provider.js';
import { markers } from '../lib/remote-script.js';

const REMOTE = {
  nodeExe: 'C:\\Program Files\\nodejs\\node.exe',
  dshBin: 'C:\\cache\\node_modules\\@deepseek-ai\\dsh\\lib\\bin.js',
  profile: 'headless',
  dshHome: 'C:\\tmp\\child-home',
  cwd: 'C:\\Users\\ezabz',
  shell: 'powershell',
};

/** Frame `answer` with the nonce the provider actually put in the script. */
function frame(script, { host = 'ZABZ-YOGA', cwd = 'C:\\Users\\ezabz', answer = 'CHILD_OK', exit = 0 } = {}) {
  const nonce = /FANOUT_BEGIN_([0-9a-f]+)/.exec(script)?.[1] ?? '';
  const m = markers(nonce);
  return [`${m.host}${host}`, `${m.cwd}${cwd}`, m.begin, answer, m.end, `${m.exit}${exit}`].join('\n');
}

/**
 * A transport double. `outcome` may supply raw `stdout` (to test the unframed
 * path); otherwise the double frames `answer` with the run's own nonce.
 */
function fakeTransport(outcome, hooks = {}) {
  const transport = {
    seen: [],
    describe: () => 'fake transport to nowhere',
    start(request) {
      transport.seen.push(request);
      hooks.onStart?.(request);
      const stdout = outcome.stdout !== undefined ? outcome.stdout : frame(request.script, outcome);
      return {
        done: Promise.resolve({ ...outcome, stdout, stderr: outcome.stderr ?? '' }),
        kill: (reason) => hooks.onKill?.(reason),
      };
    },
  };
  return transport;
}

const textOf = (result) => result.output.map((block) => block.text).join('');
const signal = () => new AbortController().signal;

test('a completed run reports the node the TARGET shell recorded, and the child message', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1234, answer: 'MESH-HOST: ZABZ-YOGA\nCHILD_HOST=ZABZ-YOGA\nTOKEN=REMOTE-CHILD-1' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'hostname' }], signal: signal() });
  const result = await run.result;

  assert.equal(result.stopReason, 'completed');
  assert.equal(result.diagnostic, undefined);
  assert.equal(run.localAgent, undefined);
  assert.match(run.id, /^remote-[0-9a-f-]{36}$/);
  assert.match(textOf(result), /^MESH-HOST: ZABZ-YOGA/);
  assert.match(textOf(result), /transport host = ZABZ-YOGA/);
  assert.match(textOf(result), /target profile = headless \(DSH_HOME C:\\tmp\\child-home\)/);
  assert.match(textOf(result), /CHILD_HOST=ZABZ-YOGA/);
  assert.match(textOf(result), /TOKEN=REMOTE-CHILD-1/);
  assert.equal(transport.seen.length, 1);
  assert.equal(transport.seen[0].shell, 'powershell');
  assert.match(transport.seen[0].script, /--profile 'headless' '/);
  assert.match(transport.seen[0].script, /hostname/);
  await run.dispose();
});

test('a remote turn that exits non-zero settles as error with a diagnostic, never a rejection', async () => {
  const transport = fakeTransport({ ok: false, exitCode: 1, ms: 500, stderr: 'dsh: error: no credentials' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'error');
  assert.match(result.diagnostic, /exited 1/);
  assert.match(result.diagnostic, /no credentials/);
  await run.dispose();
});

test('an ssh client that cannot be launched settles as error naming the transport', async () => {
  const transport = fakeTransport({ ok: false, spawnError: 'spawn ssh ENOENT', ms: 3, stdout: '' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'error');
  assert.match(result.diagnostic, /could not launch the ssh transport \(fake transport to nowhere\): spawn ssh ENOENT/);
  await run.dispose();
});

test('exit 0 without the completion frame is an error, not an empty success', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 12, stdout: 'Error: dsh: cannot resolve profile bundle "x"\n' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'error');
  assert.match(result.diagnostic, /printed no completion frame/);
  assert.match(textOf(result), /raw stdout follows/);
  await run.dispose();
});

test('an already-aborted request is rejected before anything is published', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1 });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE });
  const controller = new AbortController();
  controller.abort('stop');
  await assert.rejects(
    () => provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: controller.signal }),
    /cancelled before the remote child started/,
  );
  assert.equal(transport.seen.length, 0);
});

test('aborting mid-flight kills the ssh client and settles as aborted', async () => {
  let killReason;
  let release;
  const transport = {
    describe: () => 'fake',
    start: () => ({ done: new Promise((resolve) => { release = resolve; }), kill: (reason) => { killReason = reason; } }),
  };
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE });
  const controller = new AbortController();
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: controller.signal });
  controller.abort('parent went away');
  release({ ok: false, exitCode: undefined, ms: 5, stdout: '', stderr: '' });
  const result = await run.result;
  assert.equal(killReason, 'aborted');
  assert.equal(result.stopReason, 'aborted');
  await run.dispose();
});

test('dispose is idempotent and cancels a run still in flight without rejecting', async () => {
  let killed = 0;
  const transport = {
    describe: () => 'fake',
    start: () => ({ done: new Promise(() => {}), kill: () => { killed += 1; } }),
  };
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  await run.dispose();
  await run.dispose();
  assert.equal(killed, 1);
});

test('the advertisement is honest: no capabilities, no parent context, one-shot only', () => {
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport: { start() {} }, remote: REMOTE });
  assert.deepEqual(provider.capabilities, NO_START_CAPABILITIES);
  assert.equal(provider.inheritsParentContext, false);
  assert.equal(provider.prepareContinuable, undefined);
  assert.equal(provider.name, 'remote-ssh');
});

test('a multi-line prompt is collapsed to one argv word on the target', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1 });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'line one\r\nline two' }], signal: signal() });
  await run.result;
  const script = transport.seen[0].script;
  const taskLine = script.split('\n').find((line) => line.includes('--profile'));
  assert.match(taskLine, /--profile 'headless' '/);
  assert.match(taskLine, /line one line two'$/);
  assert.equal(/[\r\n]/.test(taskLine), false);
  await run.dispose();
});

test('the provider refuses to mount without a node and a dsh binary', () => {
  assert.throws(() => new RemoteOneShotProvider({ name: 'x', transport: { start() {} }, remote: { dshBin: 'b' } }), /`remoteNodeExe` is required/);
  assert.throws(() => new RemoteOneShotProvider({ name: 'x', transport: { start() {} }, remote: { nodeExe: 'n' } }), /`remoteDshBin` is required/);
  assert.throws(() => new RemoteOneShotProvider({ transport: { start() {} }, remote: REMOTE }), /provider `name` is required/);
});

// ---------------------------------------------------------------------------
// The location proof (`docs/mesh/71-mesh-program.md` §2.4)
// ---------------------------------------------------------------------------

test('sameNode forgives case, a domain suffix and the -ts alias convention — and nothing else', () => {
  assert.equal(sameNode('ZABZ-TECH', 'zabz-tech'), true);
  assert.equal(sameNode('zabz-tech.tail93e6e6.ts.net', 'zabz-tech'), true);
  assert.equal(sameNode('desktop-ts', 'desktop'), true);
  assert.equal(sameNode('ZABZ-YOGA', 'ZABZ-TECH'), false);
  assert.equal(sameNode('', 'zabz-tech'), false);
});

test('extractMeshHost reads only the frozen line, and only at the start of a line', () => {
  assert.equal(extractMeshHost('MESH-HOST: zabz-tech\nCHILD_OK'), 'zabz-tech');
  assert.equal(extractMeshHost('preamble\n  MESH-HOST:   ZABZ-YOGA  \nrest'), 'ZABZ-YOGA');
  assert.equal(extractMeshHost('the child said MESH-HOST: zabz-tech inline'), undefined);
  assert.equal(extractMeshHost(''), undefined);
});

test('the child task carries the MESH-HOST instruction and the original prompt', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1, answer: 'MESH-HOST: ZABZ-YOGA\nCHILD_OK' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE, targetHosts: ['ZABZ-YOGA'] });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'Do the thing.' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'completed');
  assert.match(transport.seen[0].script, /MESH-HOST:/);
  assert.match(transport.seen[0].script, /Do the thing\./);
  assert.match(textOf(result), /^MESH-HOST: ZABZ-YOGA/);
  await run.dispose();
});

test('a child that reports the wrong host fails the run', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1, host: 'ZABZ-TECH', answer: 'MESH-HOST: ZABZ-YOGA\nCHILD_OK' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE, targetHosts: ['ZABZ-TECH'] });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'error');
  assert.match(result.diagnostic, /location disagreement: the child claims MESH-HOST ZABZ-YOGA but the target shell recorded ZABZ-TECH/);
  await run.dispose();
});

test('a child that omits MESH-HOST is an unproven location, not a success', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1, answer: 'CHILD_OK' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE, targetHosts: ['ZABZ-YOGA'] });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'error');
  assert.match(result.diagnostic, /did not begin its report with "MESH-HOST: <hostname>"/);
  await run.dispose();
});

test('a transport that lands on an unexpected machine fails the run', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1, host: 'ZABZ-YOGA', answer: 'MESH-HOST: ZABZ-YOGA\nCHILD_OK' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE, targetHosts: ['ZABZ-TECH'] });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'error');
  assert.match(result.diagnostic, /is not one of the configured target hosts for this provider/);
  await run.dispose();
});

test('with no configured target hosts the report says the check was not made', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1, host: 'ZABZ-YOGA', answer: 'MESH-HOST: ZABZ-YOGA\nCHILD_OK' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'completed');
  assert.match(textOf(result), /location check = not verified against a configured target host/);
  await run.dispose();
});
