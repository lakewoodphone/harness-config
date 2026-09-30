/**
 * The conversation thread, end to end.
 *
 * WHAT THIS FILE PROVES, AND WHAT IT DOES NOT
 *
 * A remote child cannot be a continuable child (the provider contract gives
 * `prepareContinuable` no capability — see lib/mailbox.js for the measurement), and
 * `dsh --profile headless` has no `--resume`, so a child process cannot be re-entered
 * with a follow-up. This proves the channel that IS available: a durable mailbox on
 * the child's node, carried by the dispatch and read back by the parent.
 *
 * PROVEN HERE:
 *   - the child is told where to write, and the path is on the CHILD's node;
 *   - a message the child writes while it works reaches the parent's report, even
 *     when the child's final message is missing;
 *   - a second dispatch on the same thread reads everything said before it, which is
 *     what makes a multi-turn conversation possible across processes;
 *   - the parent may write to the child before dispatch, and the child is told to read it.
 *
 * NOT PROVEN HERE, and not claimed anywhere: steering a child mid-turn. Nothing in
 * the runtime can do that for a remote child, and a test that pretended otherwise
 * would be the most expensive kind of green.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { RemoteOneShotProvider } from '../lib/provider.js';
import { markers } from '../lib/remote-script.js';
import { appendMessage, mailboxPaths, parseMailboxManifest, readTranscript } from '../lib/mailbox.js';

const REMOTE = { command: 'dsh', profile: 'headless', shell: 'powershell' };
const signal = () => new AbortController().signal;
const textOf = (result) => result.output.map((b) => b.text).join('\n');

/**
 * A framed one-shot answer, built with the SAME marker builder the transport uses,
 * so this file cannot drift from the real frame format. (`/FANOUT_BEGIN_<nonce>/` is
 * not enough on its own: the twin helpers `FANOUT_TRANSPORT_HOST` and
 * `FANOUT_TRANSPORT_CWD` carry the same nonce and the parser needs the host line to
 * prove the location.)
 */
function frame(script, { host = 'ZABZ-YOGA', cwd = 'C:\\Users\\ezabz', answer = 'CHILD_OK', exit = 0 } = {}) {
  const nonce = /FANOUT_BEGIN_([0-9a-f]+)/.exec(script)?.[1] ?? '';
  const m = markers(nonce);
  return [`${m.host}${host}`, `${m.cwd}${cwd}`, m.begin, answer, m.end, `${m.exit}${exit}`].join('\n');
}

/**
 * A transport that PLAYS THE CHILD: before answering, it reads the mailbox path out
 * of the task it was handed and writes messages there exactly as a real child would.
 */
function childSimulatingTransport(outcome, { onChild = () => {} } = {}) {
  let calls = 0;
  return {
    calls: () => calls,
    describe: () => 'simulated child transport',
    start(request) {
      calls += 1;
      // Read the mailbox from the machine-readable manifest, which is the same bytes
      // the child receives. Parsing the surrounding prose is unreliable because the task
      // is flattened to one line before it is handed over.
      const manifest = parseMailboxManifest(request.script);
      assert.ok(manifest !== null, 'the task handed to the child must carry a mailbox manifest');
      onChild({ outbox: manifest.outbox, thread: manifest.thread, script: request.script, call: calls });
      const stdout = outcome.stdout !== undefined ? outcome.stdout : frame(request.script, outcome);
      return { done: Promise.resolve({ ms: 5, exitCode: 0, ok: true, stderr: '', ...outcome, stdout }), kill: () => {} };
    },
  };
}

test('END TO END: a message the child writes while it works reaches the parent', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'fanout-thread-'));
  try {
    const transport = childSimulatingTransport(
      { answer: 'MESH-HOST: ZABZ-YOGA\nFINAL ANSWER' },
      {
        onChild({ outbox }) {
          // The child reports progress and asks a question BEFORE it finishes.
          appendMessage(outbox, { at: '2026-09-30T20:00:01Z', from: 'child', kind: 'progress', text: 'parsed the log; the failure is at line 82' });
          appendMessage(outbox, { at: '2026-09-30T20:00:02Z', from: 'child', kind: 'question', text: 'should I restart the engine or leave it to the idle window?' });
        },
      },
    );
    const provider = new RemoteOneShotProvider({
      name: 'remote-ssh', transport, remote: REMOTE, mailboxRoot: root, threadId: 'ticket-73890',
    });
    const run = await provider.start({ prompt: [{ type: 'text', text: 'diagnose the crash' }], signal: signal() });
    const result = await run.result;
    const text = textOf(result);

    assert.equal(result.stopReason, 'completed');
    // 1. The parent SEES the conversation.
    assert.match(text, /conversation thread \(2 message\(s\)/);
    assert.match(text, /parsed the log; the failure is at line 82/);
    assert.match(text, /should I restart the engine/);
    assert.match(text, /<- CHILD/);
    // 2. The count is stated in the header, so it is visible without scrolling.
    assert.match(text, /mailbox\s+= 2 message\(s\) in the thread/);
    // 3. And the thread lives where the next dispatch can find it.
    const paths = mailboxPaths({ root, thread: 'ticket-73890' });
    assert.ok(existsSync(paths.outbox), 'the child wrote to the mailbox on its own node');
    await run.dispose();
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('END TO END: a second dispatch on the same thread reads everything said before it', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'fanout-thread-'));
  try {
    const paths = mailboxPaths({ root, thread: 'shared-thread' });

    // ── TURN ONE: the child asks a question and ends its turn ────────────────
    const turnOne = childSimulatingTransport(
      { answer: 'MESH-HOST: ZABZ-YOGA\nturn one done, but I need a decision' },
      {
        onChild({ outbox }) {
          appendMessage(outbox, { at: '2026-09-30T20:00:01Z', from: 'child', kind: 'question', text: 'WHICH KEY SHOULD I USE?' });
        },
      },
    );
    const providerOne = new RemoteOneShotProvider({ name: 'remote-ssh', transport: turnOne, remote: REMOTE, mailboxRoot: root, threadId: 'shared-thread' });
    const runOne = await providerOne.start({ prompt: [{ type: 'text', text: 'investigate' }], signal: signal() });
    const resultOne = await runOne.result;
    assert.match(textOf(resultOne), /WHICH KEY SHOULD I USE\?/);
    await runOne.dispose();

    // ── THE PARENT ANSWERS, into the child's inbox ───────────────────────────
    appendMessage(paths.inbox, { at: '2026-09-30T20:05:00Z', from: 'parent', kind: 'answer', text: 'use ha-mesh-key, never id_rsa_linux_pc' });

    // ── TURN TWO: a NEW dispatch, which must be told to read the thread ──────
    let secondTask;
    const turnTwo = childSimulatingTransport(
      { answer: 'MESH-HOST: ZABZ-YOGA\nturn two done with the key the parent named' },
      {
        onChild({ outbox, script }) {
          // Capture the task so the test can assert what turn two was TOLD...
          secondTask = script;
          // ...and have this child actually SAY something, or there is no third
          // message to find and the assertion below would be testing the test.
          appendMessage(outbox, { at: '2026-09-30T20:10:00Z', from: 'child', kind: 'report', text: 'TURN TWO DID THE WORK' });
        },
      },
    );
    const providerTwo = new RemoteOneShotProvider({ name: 'remote-ssh', transport: turnTwo, remote: REMOTE, mailboxRoot: root, threadId: 'shared-thread' });
    const runTwo = await providerTwo.start({ prompt: [{ type: 'text', text: 'continue' }], signal: signal() });
    const resultTwo = await runTwo.result;
    await runTwo.dispose();

    // The second child is told to read the inbox, which is what carries the answer.
    assert.match(secondTask, /read the inbox file if it exists/i);
    assert.match(secondTask, /shared-thread/);
    // And the parent's report shows the WHOLE conversation — both turns, in order.
    const text = textOf(resultTwo);
    assert.match(text, /WHICH KEY SHOULD I USE\?/, 'the previous turn is still readable');
    assert.match(text, /use ha-mesh-key, never id_rsa_linux_pc/, 'the parent\'s answer is in the thread');
    assert.match(text, /PARENT ->/);
    assert.ok(
      text.indexOf('WHICH KEY SHOULD I USE?') < text.indexOf('use ha-mesh-key'),
      'the thread is in time order: question then answer',
    );
    // Making a conversation of it: three messages across two dispatches, in order,
    // with the earlier turn's words still readable after the later turn rewrote the
    // two writer files it originally lived in.
    assert.match(text, /conversation thread \(3 message\(s\)/);
    assert.match(text, /TURN TWO DID THE WORK/);
    assert.ok(
      text.indexOf('WHICH KEY SHOULD I USE?') < text.indexOf('TURN TWO DID THE WORK'),
      'the turns stay in order: turn one, then the answer, then turn two',
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the thread survives a child that dies with no final message — what was written early is kept', async () => {
  // This is the case the mailbox exists for. The transport can kill a child after its
  // work is done (journal L3188) and its final message is lost; a progress line written
  // earlier survives, and it is the difference between a lost workstream and a partial one.
  const root = mkdtempSync(path.join(tmpdir(), 'fanout-thread-'));
  try {
    const transport = childSimulatingTransport(
      // The exact production shape: the opening frame is written, then the process dies
      // with -1 and no answer.
      { ok: false, exitCode: -1, stdout: '' },
      {
        onChild({ outbox, script }) {
          appendMessage(outbox, { at: '2026-09-30T20:00:01Z', from: 'child', kind: 'progress', text: 'FOUND THE ROOT CAUSE: the settlement watcher has no catch' });
          // the closing frame is never written — the process is gone
          void script;
        },
      },
    );
    // The child dies before the frame closes, so the transport returns the raw bytes.
    transport.start = ((original) => function start(request) {
      const handle = original.call(this, request);
      const manifest = parseMailboxManifest(request.script);
      const nonce = request.script.match(/FANOUT_BEGIN_([0-9a-f]+)/)?.[1] ?? '';
      appendMessage(manifest.outbox, { at: '2026-09-30T20:00:01Z', from: 'child', kind: 'progress', text: 'FOUND THE ROOT CAUSE: the settlement watcher has no catch' });
      return {
        done: Promise.resolve({ ms: 900, ok: false, exitCode: -1, stderr: '', stdout: `FANOUT_TRANSPORT_HOST_Z=ZABZ-YOGA\nFANOUT_BEGIN_${nonce}\n` }),
        kill: handle.kill,
      };
    })(transport.start);

    const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE, mailboxRoot: root, threadId: 'crash-thread', retryPolicy: { backoffMs: 1 } });
    const run = await provider.start({ prompt: [{ type: 'text', text: 'work' }], signal: signal() });
    const result = await run.result;
    const text = textOf(result);

    assert.equal(transport.calls(), 1, 'a child that started is never re-dispatched');
    assert.match(text, /ORPHANED/);
    // The child's early message is in the report even though its final message never came.
    assert.match(text, /FOUND THE ROOT CAUSE/);
    assert.match(text, /conversation thread \(1 message/);
    // And it is still on disk for whoever picks the thread up next.
    const paths = mailboxPaths({ root, thread: 'crash-thread' });
    const persisted = readTranscript(paths.outbox);
    assert.equal(persisted.exists, true);
    assert.match(persisted.messages[0].text, /FOUND THE ROOT CAUSE/);
    await run.dispose();
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('with the mailbox switched off the dispatch carries no mailbox text and no thread section', async () => {
  // A caller must be able to say "do not do this" — and when it does, the task and the
  // report are exactly what they were before the mailbox existed. This is the control
  // for the whole feature: it is what proves the mailbox is OPT-IN rather than
  // something every dispatch now silently carries.
  //
  // The transport here is inline rather than `childSimulatingTransport`, because that
  // helper ASSERTS a mailbox manifest and this test is the one case where there must
  // not be one.
  const root = mkdtempSync(path.join(tmpdir(), 'fanout-thread-'));
  try {
    let task;
    const transport = {
      describe: () => 'inline transport',
      start(request) {
        task = request.script;
        const stdout = frame(request.script, { answer: 'MESH-HOST: ZABZ-YOGA\nplain' });
        return { done: Promise.resolve({ ms: 5, exitCode: 0, ok: true, stderr: '', stdout }), kill: () => {} };
      },
    };
    const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE, mailboxRoot: false });
    const run = await provider.start({ prompt: [{ type: 'text', text: 'plain task' }], signal: signal() });
    const result = await run.result;
    const text = textOf(result);
    assert.doesNotMatch(task, /mesh mailbox/i, 'the child must not be told about a mailbox that does not exist');
    assert.equal(parseMailboxManifest(task), null, 'no manifest, so nothing can be parsed out and continued by mistake');
    assert.doesNotMatch(text, /conversation thread/);
    assert.doesNotMatch(text, /^mailbox\s+=/m);
    assert.equal(result.stopReason, 'completed');
    await run.dispose();
    // And nothing was written anywhere: the off switch is honoured on disk too, not
    // merely in the text.
    assert.deepEqual(readdirSync(root), [], 'a switched-off mailbox must not create a directory');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the mailbox is placed on the CHILD node path, never this machine\'s default', async () => {
  // The path is derived from the placed node's own recorded working directory. A path
  // from the parent's machine would name a directory the child cannot write to, and the
  // whole channel would fail silently.
  const root = mkdtempSync(path.join(tmpdir(), 'fanout-thread-'));
  try {
    const transport = childSimulatingTransport({ answer: 'MESH-HOST: ZABZ-YOGA\nok' });
    let task;
    const original = transport.start;
    transport.start = function start(request) { task = request.script; return original.call(this, request); };
    const provider = new RemoteOneShotProvider({ name: 'remote-ssh', transport, remote: REMOTE, mailboxRoot: root });
    const run = await provider.start({ prompt: [{ type: 'text', text: 'x' }], signal: signal() });
    await run.result;
    // The named directory is the one the caller configured, not a parent-side default.
    assert.ok(task.includes(root), `the child must be told the configured root, got:\n${task.split('\n').slice(0, 8).join('\n')}`);
    // And the thread id is the run's own id when the caller names none.
    assert.match(task, /thread id: remote-[0-9a-f-]{36}/);
    await run.dispose();
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

