import assert from 'node:assert/strict';
import test from 'node:test';

import { BrokerError, BROKER_UNREACHABLE } from '../lib/broker-client.js';
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
  assert.match(transport.seen[0].script, /--profile'? '?headless'? '/);
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
  assert.match(taskLine, /'--profile' 'headless' /);
  assert.match(taskLine, /line one line two'$/);
  assert.equal(/[\r\n]/.test(taskLine), false);
  await run.dispose();
});

test('the provider refuses to mount without a RESOLVABLE invocation, not merely without two paths', () => {
  assert.throws(() => new RemoteOneShotProvider({ name: 'x', transport: { start() {} }, remote: { dshBin: 'b' } }), /a fixed target needs an invocation/);
  assert.throws(() => new RemoteOneShotProvider({ name: 'x', transport: { start() {} }, remote: { nodeExe: 'n' } }), /a fixed target needs an invocation/);
  assert.throws(() => new RemoteOneShotProvider({ name: 'x', transport: { start() {} }, remote: {} }), /a fixed target needs an invocation/);
  assert.throws(() => new RemoteOneShotProvider({ transport: { start() {} }, remote: REMOTE }), /provider `name` is required/);
  // An executor alone IS a complete invocation — the node's own wrapper is the
  // preferred form, so a config that names only it must mount.
  const executorOnly = new RemoteOneShotProvider({ name: 'x', transport: { start() {} }, remote: { command: 'dsh', shell: 'posix' } });
  assert.equal(executorOnly.remote.command, 'dsh');
});

// ---------------------------------------------------------------------------
// WHICH INVOCATION RAN, AND WHAT HAPPENS WHEN IT CANNOT
// (`docs/mesh/102-linux-dispatch.md` — the defect: a node with a working `dsh`
// executor was dispatched through an interpreter path that did not exist.)
// ---------------------------------------------------------------------------

const POSIX_EXECUTOR_NODE = {
  command: 'dsh',
  credentialEnvFiles: ['/etc/dsh-worker.env'],
  shell: 'posix',
  cwd: '/home/zabz/code',
  profile: 'headless',
};

test('the EXECUTOR is used when the node has one, and the report says so', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 12, host: 'zabz-tech-linux', cwd: '/home/zabz/code', answer: 'MESH-HOST: zabz-tech-linux\nCHILD_OK' });
  const placer = fakePlacer({
    transport,
    placement: { node: 'zabz-tech-linux', ssh: 'linux-pc-ts', hosts: ['zabz-tech-linux'], facts: POSIX_EXECUTOR_NODE, source: 'fixed' },
  });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', placer });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;

  assert.equal(result.stopReason, 'completed');
  const script = transport.seen[0].script;
  assert.match(script, /^dsh --profile headless /m, 'the wrapper is invoked by name');
  assert.doesNotMatch(script, /node-v24/, 'no interpreter path sneaks in front of the wrapper');
  assert.equal(transport.seen.length, 1, 'one invocation, no retry when the executor works');
  assert.match(textOf(result), /invocation     = dsh --profile <profile> <task> \[executor\]/);
  assert.match(textOf(result), /credential     = the executor sources \/etc\/dsh-worker\.env itself/);
  await run.dispose();
});

test('an executor that cannot be launched falls back to the interpreter pair ONCE, and the report names both', async () => {
  // First run: the wrapper is not there (exit 127, "not found"). Second: the
  // interpreter answers. This is the shape that must not kill the child.
  const outcomes = [
    // A real failed launch prints NOTHING framed: the shell could not find the
    // command, so no transport line and no marker were ever written.
    { ok: false, exitCode: 127, ms: 30, stdout: '', stderr: 'sh: 1: dsh: not found\n' },
    { ok: true, exitCode: 0, ms: 900, host: 'zabz-tech-linux', cwd: '/home/zabz/code', answer: 'MESH-HOST: zabz-tech-linux\nCHILD_OK' },
  ];
  let call = 0;
  const transport = {
    seen: [],
    describe: () => 'fake transport to nowhere',
    start(request) {
      transport.seen.push(request);
      const outcome = outcomes[Math.min(call, outcomes.length - 1)];
      call += 1;
      const stdout = outcome.stdout !== undefined ? outcome.stdout : frame(request.script, outcome);
      return { done: Promise.resolve({ ...outcome, stdout, stderr: outcome.stderr ?? '' }), kill: () => {} };
    },
  };
  const placer = fakePlacer({
    transport,
    placement: {
      node: 'zabz-tech-linux',
      ssh: 'linux-pc-ts',
      hosts: ['zabz-tech-linux'],
      source: 'fixed',
      facts: { ...POSIX_EXECUTOR_NODE, driver: '/usr/local/bin/node', bin: '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js' },
    },
  });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', placer });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;

  assert.equal(result.stopReason, 'completed', 'the fallback saves the child rather than failing it');
  assert.equal(transport.seen.length, 2, 'exactly one retry');
  assert.match(transport.seen[0].script, /^dsh --profile headless /m);
  assert.match(transport.seen[1].script, /^\/usr\/local\/bin\/node \/home\/zabz\/dsh-engine\/node_modules\/@deepseek-ai\/dsh\/lib\/bin\.js --profile headless /m);
  // The fallback sources exactly what the executor would have sourced.
  assert.match(transport.seen[1].script, /set -a; \. '\/etc\/dsh-worker\.env'; set \+a/);
  assert.match(textOf(result), /invocation     = .*\[interpreter, fell back from the executor form after it could not be launched\]/);
  await run.dispose();
});

test('a credential error is NOT retried — a child that ran and failed keeps its own outcome', async () => {
  const transport = fakeTransport({ ok: false, exitCode: 1, ms: 700, stderr: 'dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official"' });
  const placer = fakePlacer({
    transport,
    placement: {
      node: 'zabz-tech-linux',
      ssh: 'linux-pc-ts',
      hosts: ['zabz-tech-linux'],
      source: 'fixed',
      facts: { ...POSIX_EXECUTOR_NODE, driver: '/usr/local/bin/node', bin: '/x/bin.js' },
    },
  });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', placer });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'error');
  assert.equal(transport.seen.length, 1, 'one attempt: this is the child failing, not the launcher');
  assert.match(result.diagnostic, /exited 1/);
  await run.dispose();
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

/**
 * CHANGED 2026-09-30, deliberately, with the reason on the record.
 *
 * This used to be `stopReason: 'error'`: a child that omitted its `MESH-HOST:`
 * line had its whole run discarded. That was measured discarding real work — a
 * child whose answer was sitting in the transcript and which the transport had
 * independently located. The rule now distinguishes two different things:
 *
 *   a MISSING line        the child's location is unproven  -> warn, keep the work
 *   a DISAGREEING line    the child ran somewhere else      -> fail (see below)
 *
 * The unproven case is still reported loudly, in the report header and in the
 * diagnostic; what it no longer does is throw the child's message away. The
 * neighbouring test ('a child that reports the right node but a different
 * MESH-HOST still disagrees') proves the real disagreement still fails.
 */
test('a child that omits MESH-HOST is unproven and warned about — its work is NOT discarded', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1, answer: 'CHILD_OK' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE, targetHosts: ['ZABZ-YOGA'] });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  const text = result.output.map((b) => b.text).join('\n');
  // 1. the run is not thrown away
  assert.equal(result.stopReason, 'completed');
  // 2. the child's own message survives
  assert.match(text, /CHILD_OK/);
  // 3. the unproven location is stated unmistakably, not buried
  assert.match(text, /did not open its report with "MESH-HOST: <hostname>"/);
  assert.match(text, /location is unproven/);
  await run.dispose();
});

test('a transport that lands on an unexpected machine fails the run', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1, host: 'ZABZ-YOGA', answer: 'MESH-HOST: ZABZ-YOGA\nCHILD_OK' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE, targetHosts: ['ZABZ-TECH'] });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'error');
  assert.match(result.diagnostic, /is not one of the hostnames the placement named/);
  await run.dispose();
});

test('with no configured target hosts the report says the check was not made', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1, host: 'ZABZ-YOGA', answer: 'MESH-HOST: ZABZ-YOGA\nCHILD_OK' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'completed');
  assert.match(textOf(result), /location check = not verified against a host list/);
  await run.dispose();
});

// ---------------------------------------------------------------------------
// PLACEMENT (`docs/mesh/92-provider-placement.md`)
//
// The provider's target is no longer a row in a profile: it is what the live
// broker answered. These are the behaviour-bearing tests for that, driven by a
// placer double so they are deterministic and cost no node.
// ---------------------------------------------------------------------------

/** A placer double: it records the order of everything the provider does. */
function fakePlacer({ placement, transport, release, wait, waitResult } = {}) {
  const order = [];
  return {
    kind: 'broker',
    order,
    released: [],
    waits: [],
    describe: () => 'broker http://localhost:3091 over ssh secratary-ts',
    explain: () => 'placed by the broker — one placement per child',
    async acquire() {
      order.push('acquire');
      if (placement instanceof Error) throw placement;
      return {
        source: 'broker',
        node: 'zabz-tech',
        ssh: 'desktop-ts',
        hosts: ['ZABZ-TECH', 'zabz-tech'],
        position: 0,
        lease: 'mu4q576o-lease',
        tier: 'fits',
        score: 16,
        rationale: ['chosen from 4 configured node(s); tier=fits; chosen zabz-tech'],
        queue: [],
        at: '2026-09-17T13:06:39.210Z',
        facts: { ...REMOTE, cwd: 'C:/Users/ezabz' },
        ...placement,
      };
    },
    async waitForSlot(_placement, options) {
      order.push('waitForSlot');
      this.waits.push(options);
      const result = waitResult ?? { waited: false, waitedMs: 0, polls: [] };
      if (result.waited === true) {
        options?.onWait?.({ phase: 'queued', node: 'zabz-tech', position: _placement.position, queue: [], lease: _placement.lease });
        options?.onWait?.({ phase: 'queued-released', node: 'zabz-tech', position: _placement.position, waitedMs: result.waitedMs, note: 'a free slot appeared' });
      }
      return result;
    },
    transportFor() {
      order.push('transportFor');
      return transport;
    },
    async release(p, ok) {
      order.push(`release:${ok}`);
      this.released.push({ lease: p.lease, ok });
      return release ?? { released: true, ok: true, lease: p.lease, node: p.node };
    },
  };
}

test('the child is placed by the broker, dispatched to the named node, and the lease is released', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 42, host: 'ZABZ-TECH', answer: 'MESH-HOST: ZABZ-TECH\nCHILD_OK' });
  const placer = fakePlacer({ transport });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', placer });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;

  assert.equal(result.stopReason, 'completed');
  assert.match(textOf(result), /^MESH-HOST: ZABZ-TECH/);
  assert.match(textOf(result), /placement      = broker → node "zabz-tech", position 0/);
  assert.match(textOf(result), /lease          = /, 'the report still has the lease slot available for a release note');
  assert.match(textOf(result), /location check = matched the node the broker named \(zabz-tech\)/);
  // One placement, then the transport, then the release — in that order.
  assert.deepEqual(placer.order, ['acquire', 'waitForSlot', 'transportFor', 'release:true']);
  assert.deepEqual(placer.released, [{ lease: 'mu4q576o-lease', ok: true }]);
  assert.deepEqual(provider.counters, { placed: 1, queued: 0, released: 1, placementFailed: 0 });
  await run.dispose();
});

test('a queued placement is surfaced before the child is dispatched, and nothing runs while it waits', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 42, host: 'ZABZ-TECH', answer: 'MESH-HOST: ZABZ-TECH\nCHILD_OK' });
  const placer = fakePlacer({
    transport,
    placement: { position: 4, state: 'queued' },
    waitResult: { waited: true, waitedMs: 27_500, polls: [{ freeSlots: 0 }, { freeSlots: 1 }], timedOut: false, freedAt: '2026-09-17T13:07:07.000Z' },
  });
  const records = [];
  const provider = new RemoteOneShotProvider({
    name: 'remote-ssh',
    placer,
    ledger: { record: (id, patch) => { records.push({ id, ...patch }); return { ok: true }; }, get: () => records.at(-1) },
  });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;

  assert.equal(result.stopReason, 'completed');
  assert.match(textOf(result), /placement      = broker → node "zabz-tech", position 4 \(tier fits\), score 16, lease mu4q576o-lease/);
  assert.match(textOf(result), /QUEUED at position 4 and waited 27\.5 s until the broker reported a free slot/);
  // The queue is on the record BEFORE the dispatch, and the dispatch is on the record after.
  const states = records.map((record) => record.state).filter(Boolean);
  assert.deepEqual(states, ['dispatching', 'settled']);
  assert.equal(provider.counters.queued, 1);
  await run.dispose();
});

test('a wait that expires says so in the parent\'s own report — queue, never amputate', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 10, host: 'ZABZ-TECH', answer: 'MESH-HOST: ZABZ-TECH\nCHILD_OK' });
  const placer = fakePlacer({
    transport,
    placement: { position: 9 },
    waitResult: { waited: true, waitedMs: 120_000, polls: [], timedOut: true },
  });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', placer });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'completed');
  assert.match(textOf(result), /QUEUED at position 9 and waited 120\.0 s for a free slot, then dispatched anyway \(queue, never amputate\)/);
  await run.dispose();
});

test('a broker that cannot be reached REJECTS start() with the named error, and starts nothing', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 1 });
  const placer = fakePlacer({ transport, placement: new BrokerError(BROKER_UNREACHABLE, 'the placement broker could not be reached at secratary-ts:http://localhost:3091/place — ssh exited 255') });
  const records = [];
  const provider = new RemoteOneShotProvider({
    name: 'remote-ssh',
    placer,
    ledger: { record: (id, patch) => { records.push({ id, ...patch }); return { ok: true }; }, get: () => records.at(-1) },
  });
  await assert.rejects(
    () => provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() }),
    (error) => {
      assert.match(error.message, /remote-ssh: broker-unreachable:/);
      assert.match(error.message, /could not be reached at secratary-ts/);
      return true;
    },
  );
  // Nothing was dispatched, and there is no automatic fall back to a fixed node.
  assert.deepEqual(placer.order, ['acquire']);
  assert.equal(transport.seen.length, 0);
  assert.equal(records.at(-1).state, 'placement-failed');
  assert.equal(provider.counters.placementFailed, 1);
});

test('a child that lands on a machine the placement did not name fails the run', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 5, host: 'ZABZ-YOGA', answer: 'MESH-HOST: ZABZ-YOGA\nCHILD_OK' });
  const placer = fakePlacer({ transport });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', placer });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'error');
  assert.match(result.diagnostic, /not one of the hostnames the placement named \("zabz-tech" may be ZABZ-TECH, zabz-tech\)/);
  // The lease is released on a failed child too: a reservation nobody gives back
  // is a slot the mesh has lost until its TTL.
  assert.deepEqual(placer.released, [{ lease: 'mu4q576o-lease', ok: false }]);
  await run.dispose();
});

test('a child that reports the right node but a different MESH-HOST still disagrees', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 5, host: 'ZABZ-TECH', answer: 'MESH-HOST: ZABZ-YOGA\nCHILD_OK' });
  const placer = fakePlacer({ transport });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', placer });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'error');
  assert.match(result.diagnostic, /location disagreement: the child claims MESH-HOST ZABZ-YOGA but the target shell recorded ZABZ-TECH/);
  await run.dispose();
});

test('the placement is asked for BEFORE anything is published, and one acquire is one child', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 5, host: 'ZABZ-TECH', answer: 'MESH-HOST: ZABZ-TECH\nCHILD_OK' });
  const placer = fakePlacer({ transport });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', placer });
  const [a, b] = await Promise.all([
    provider.start({ prompt: [{ type: 'text', text: 'one' }], signal: signal() }),
    provider.start({ prompt: [{ type: 'text', text: 'two' }], signal: signal() }),
  ]);
  await Promise.all([a.result, b.result]);
  assert.equal(placer.order.filter((entry) => entry === 'acquire').length, 2, 'two children, two placements');
  assert.equal(placer.released.length, 2);
  assert.equal(provider.counters.placed, 2);
  await a.dispose();
  await b.dispose();
});

test('the fixed-target opt-in still works, and says loudly that the broker was not consulted', async () => {
  const transport = fakeTransport({ ok: true, exitCode: 0, ms: 5, host: 'ZABZ-YOGA', answer: 'MESH-HOST: ZABZ-YOGA\nCHILD_OK' });
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE, targetHosts: ['ZABZ-YOGA'] });
  assert.equal(provider.placementKind, 'fixed');
  assert.match(provider.describePlacement(), /FIXED TARGET .* the placement broker was NOT consulted/);
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  assert.equal(result.stopReason, 'completed');
  assert.match(textOf(result), /placement      = FIXED TARGET — "ZABZ-YOGA" from configuration, the broker was NOT consulted/);
  await run.dispose();
});

// ── RETRY AND THE ANTI-DUPLICATION RULE, END TO END ─────────────────────────
// The unit tests in retry-plan.test.mjs prove the CLASSIFIER. These two prove the
// provider actually acts on it, which is the part that failed in production.

/** A transport whose Nth call answers with the Nth scripted outcome. */
function sequencedTransport(outcomes, hooks = {}) {
  let calls = 0;
  const transport = {
    calls: () => calls,
    describe: () => 'sequenced transport to nowhere',
    start(request) {
      calls += 1;
      hooks.onStart?.(request, calls);
      const outcome = outcomes[Math.min(calls - 1, outcomes.length - 1)];
      const stdout = outcome.stdout !== undefined ? outcome.stdout : (outcome.spawnError ? '' : frame(request.script, outcome));
      return {
        done: Promise.resolve({ ms: 1, stderr: '', ...outcome, stdout }),
        kill: () => {},
      };
    },
  };
  return transport;
}

test('END TO END: a child that never launched is retried, and the retry is what the caller sees', async () => {
  const transport = sequencedTransport([
    // attempt 1: the ssh client could not even be spawned — provably nothing ran.
    { spawnError: 'spawn ssh ENOENT', exitCode: undefined },
    // attempt 2: a real child turn.
    { ok: true, exitCode: 0, answer: 'MESH-HOST: ZABZ-YOGA\nSECOND ATTEMPT DID THE WORK' },
  ]);
  let waitedMs = 0;
  const provider = new RemoteOneShotProvider({
    name: 'remote-ssh',
    transport,
    remote: REMOTE,
    // A test must not wait out the real backoff; the policy's NUMBERS are asserted
    // in retry-plan.test.mjs, and this test is about the wiring.
    retryPolicy: { backoffMs: 1, rerouteBackoffMs: 1 },
  });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  const text = textOf(result);
  // Count LOGICAL attempts from the report, not raw transport deliveries: one
  // attempt may legitimately deliver twice, because the executor is tried first
  // and the interpreter fallback re-delivers when the executor cannot launch.
  const logicalAttempts = (text.match(/^attempt \d+ = node/gm) ?? []).length;
  assert.equal(logicalAttempts, 2, 'the failed attempt must be followed by exactly one retry');
  assert.equal(result.stopReason, 'completed');
  assert.match(text, /SECOND ATTEMPT DID THE WORK/, 'the retry\'s answer is the result');
  // The attempt ledger must be readable without a log file.
  assert.match(text, /attempt 1 = node "[^"]*" — transient-same-node/);
  assert.match(text, /RETRYING IN \d+ ms/);
  assert.match(text, /attempt 2 = node/);
  assert.match(text, /retry budget\s+= 2 of 3 transport attempt\(s\), 1 of 2 distinct node\(s\)/, 'a retry on the SAME node must not be counted as a second node');
  await run.dispose();
});

test('END TO END: a child that STARTED is harvested, never re-dispatched', async () => {
  // The exact production shape measured on 2026-09-30: the opening frame AND its
  // host line were written, the child then worked, and the process died with -1
  // having written no answer and no closing frame. Re-running this would duplicate
  // whatever it already did, so the provider must harvest instead.
  const transport = sequencedTransport([{
    ok: false,
    exitCode: -1,
    stdout: 'FANOUT_TRANSPORT_HOST=ZABZ-YOGA\nFANOUT_TRANSPORT_CWD=C:\\work\nFANOUT_BEGIN\nPARTIAL REASONING THAT SURVIVED',
  }]);
  const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE, retryPolicy: { backoffMs: 1, rerouteBackoffMs: 1 } });
  const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
  const result = await run.result;
  const text = textOf(result);
  assert.equal(transport.calls(), 1, 'a started child must NEVER be re-dispatched — this is the duplicate-work guard');
  assert.match(text, /ORPHANED/, 'the report must say the child may have done work');
  assert.match(text, /PARTIAL REASONING THAT SURVIVED/, 'the salvage must carry what the child produced');
  assert.match(text, /child-ran-transport-fault/);
  assert.match(text, /harvesting, not re-dispatching/i);
  await run.dispose();
});
