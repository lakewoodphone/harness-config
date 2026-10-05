/**
 * Tests for the child mailbox — the durable two-way channel.
 *
 * The channel exists because the runtime cannot do better (see the module header):
 * a remote child cannot be a continuable child, and `dsh --profile headless` has no
 * `--resume`, so conversation is carried by files on the child's node. That makes
 * the FILE PROTOCOL the contract, and these tests are mostly about the ways a file
 * protocol fails:
 *
 *   - a writer killed mid-line must not destroy the lines before it (the child can
 *     be killed at any moment — that is the sibling transport work's whole subject);
 *   - two writers must not disagree about ordering;
 *   - a thread name must not be able to escape its root and write anywhere;
 *   - an empty message must be refused, because an empty message is
 *     indistinguishable from a lost one, which is the failure this system fears most.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import {
  MESSAGE_KINDS,
  appendMessage,
  childInstructions,
  collectThread,
  defaultMailboxRoot,
  encodeMessage,
  listThreads,
  mailboxPaths,
  mergeThread,
  parseTranscript,
  readTranscript,
  renderThread,
  withMailbox,
} from '../lib/mailbox.js';

function tempRoot() {
  return mkdtempSync(path.join(tmpdir(), 'fanout-mailbox-'));
}

test('a thread is three files under one directory, and the directory never escapes the root', () => {
  const root = tempRoot();
  try {
    const paths = mailboxPaths({ root, thread: 'ticket-73890' });
    assert.equal(path.dirname(paths.dir), root);
    assert.equal(path.basename(paths.inbox), 'inbox.jsonl');
    assert.equal(path.basename(paths.outbox), 'outbox.jsonl');
    assert.equal(path.basename(paths.transcript), 'transcript.jsonl');

    // A thread name is caller input that reaches here from a model. It must be able to
    // name a conversation and NOT able to choose a directory elsewhere. Refused rather
    // than sanitised: rewriting it would put the message somewhere the caller did not
    // name, and would fold two different threads into one directory.
    assert.throws(() => mailboxPaths({ root, thread: '../../etc/passwd' }), /not usable|contains "\.\."/);
    assert.throws(() => mailboxPaths({ root, thread: '..' }), /not usable/);
    assert.throws(() => mailboxPaths({ root, thread: 'sub/dir' }), /not usable/);
    assert.throws(() => mailboxPaths({ root, thread: 'a thread with spaces' }), /not usable/);
    // A legal name with dots inside it is fine.
    assert.equal(path.basename(mailboxPaths({ root, thread: 'ticket.73890-v2' }).dir), 'ticket.73890-v2');
    assert.throws(() => mailboxPaths({}), /either `dir` or `root`/);
    assert.throws(() => mailboxPaths({ root }), /`thread` is required/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('an explicit directory is taken as given, for a caller that already made one', () => {
  const paths = mailboxPaths({ dir: '/tmp/somewhere/mailbox-1' });
  assert.equal(paths.dir, '/tmp/somewhere/mailbox-1');
  assert.equal(paths.inbox, path.join('/tmp/somewhere/mailbox-1', 'inbox.jsonl'));
});

test('the default root hangs off the child work directory, not the process cwd', () => {
  // The child's cwd is where the work is; a parent's cwd is a different machine.
  assert.equal(defaultMailboxRoot('/home/zabz/work'), path.join('/home/zabz/work', '.dsh-mesh-mailboxes'));
  assert.equal(path.basename(defaultMailboxRoot(undefined)), '.dsh-mesh-mailboxes');
});

test('the encoding is one JSON object per line and refuses the shapes that lose information', () => {
  const line = encodeMessage({ at: '2026-09-30T20:00:00Z', from: 'child', kind: 'progress', text: 'found it' });
  assert.ok(line.endsWith('\n'), 'one message is one line');
  assert.deepEqual(JSON.parse(line), { at: '2026-09-30T20:00:00Z', from: 'child', kind: 'progress', text: 'found it' });

  assert.throws(() => encodeMessage({ from: 'parent', kind: 'progress', text: '   ' }), /empty message/);
  assert.throws(() => encodeMessage({ from: 'nobody', kind: 'progress', text: 'x' }), /must be parent or child/);
  assert.throws(() => encodeMessage({ from: 'parent', kind: 'shouting', text: 'x' }), /unknown kind/);
  assert.throws(() => encodeMessage({ from: 'parent', kind: 'progress', text: '' }), /empty message/);

  // A multi-paragraph message is legal and must survive the round trip intact.
  const multi = encodeMessage({ at: '2026-09-30T20:00:00Z', from: 'parent', kind: 'brief', text: 'line one\n\nline three' });
  assert.equal(JSON.parse(multi).text, 'line one\n\nline three');
});

test('a writer killed mid-line costs that line and NOT the lines before it', () => {
  // This is the property that makes the channel worth having: the child process can
  // be killed at any instant, and the parent must still recover what it said.
  const complete = [
    encodeMessage({ at: '2026-09-30T20:00:01Z', from: 'child', kind: 'progress', text: 'first finding' }),
    encodeMessage({ at: '2026-09-30T20:00:02Z', from: 'child', kind: 'progress', text: 'second finding' }),
  ].join('');
  const truncated = `${complete}{"at":"2026-09-30T20:00:03Z","from":"child","kind":"prog`;

  const { messages, warnings } = parseTranscript(truncated);
  assert.equal(messages.length, 2, 'both complete messages survive a truncated third');
  assert.equal(messages[0].text, 'first finding');
  assert.equal(messages[1].text, 'second finding');
  assert.equal(warnings.length, 1, 'and the damage is REPORTED, not silent');
  assert.match(warnings[0], /not complete JSON/);
  assert.deepEqual(messages.map((m) => m.seq), [1, 2], 'seq is assigned by the reader, in file order');
});

test('a record missing its fields degrades to something readable instead of vanishing', () => {
  const text = [
    JSON.stringify({ from: 'child', text: 'no at, no kind' }),
    JSON.stringify({ from: 'parent', kind: 'brief', text: 'complete' }),
    JSON.stringify({ from: 'martian', kind: 'brief', text: 'not a participant' }),
    'null',
  ].join('\n');
  const { messages, warnings } = parseTranscript(text);
  assert.equal(messages.length, 2, 'the two usable records are kept');
  assert.equal(messages[0].kind, 'note', 'an unknown kind becomes a note rather than being dropped');
  assert.equal(messages[0].at, null);
  assert.equal(messages[1].text, 'complete');
  assert.equal(warnings.length, 2, 'and the two unusable records are reported');
});

test('the round trip works, and reading a file that does not exist is not an error', () => {
  const root = tempRoot();
  try {
    const paths = mailboxPaths({ root, thread: 'round-trip' });
    assert.deepEqual(readTranscript(paths.inbox), { messages: [], warnings: [], exists: false });

    appendMessage(paths.inbox, { at: '2026-09-30T20:00:00Z', from: 'parent', kind: 'brief', text: 'do the thing' });
    appendMessage(paths.outbox, { at: '2026-09-30T20:00:01Z', from: 'child', kind: 'progress', text: 'doing it' });
    appendMessage(paths.outbox, { at: '2026-09-30T20:00:02Z', from: 'child', kind: 'report', text: 'done' });

    const read = readTranscript(paths.outbox);
    assert.equal(read.exists, true);
    assert.deepEqual(read.messages.map((m) => m.text), ['doing it', 'done']);

    const collected = collectThread({ transcript: path.join(paths.dir, 'absent.jsonl'), inbox: paths.inbox, outbox: paths.outbox });
    assert.deepEqual(
      collected.messages.map((m) => `${m.from}:${m.kind}`),
      ['parent:brief', 'child:progress', 'child:report'],
      'both directions are assembled in time order',
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('merging is idempotent: running it twice does not duplicate the conversation', () => {
  const root = tempRoot();
  try {
    const paths = mailboxPaths({ root, thread: 'idempotent' });
    appendMessage(paths.inbox, { at: '2026-09-30T20:00:00Z', from: 'parent', kind: 'brief', text: 'one' });
    appendMessage(paths.outbox, { at: '2026-09-30T20:00:01Z', from: 'child', kind: 'answer', text: 'two' });

    const first = mergeThread(paths);
    assert.equal(first.messages.length, 2);
    const second = mergeThread(paths);
    assert.equal(second.messages.length, 2, 'a second merge must not append the same messages again');

    // And the canonical transcript stands alone: collecting it finds the same thread.
    const viaTranscript = collectThread({ ...paths });
    const unique = new Set(viaTranscript.messages.map((m) => `${m.from}|${m.text}`));
    assert.equal(unique.size, 2, 'the transcript plus the two writers must not triple-count');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the child is told where the mailbox is, to write as it goes, and not to wait', () => {
  const paths = mailboxPaths({ dir: '/home/zabz/work/.dsh-mesh-mailboxes/thread-1' });
  const text = childInstructions(paths, { thread: 'thread-1' });

  assert.match(text, /MESH MAILBOX|mailbox/i, 'it must be findable in the instructions');
  assert.match(text, /read the inbox/i);
  assert.match(text, /WRITE AS YOU GO/, 'the reason the report survives is that it is written early');
  assert.match(text, /DO NOT WAIT FOR A REPLY/, 'the honest limit must be stated to the child');
  assert.match(text, /END YOUR TURN/);
  assert.match(text, /INBOX|inbox\.jsonl/);
  assert.match(text, /outbox\.jsonl/);
  // The literal record shape, so the child does not have to invent one.
  assert.match(text, /\{"at":"<ISO-8601 time>","from":"child","kind":"progress","text":"<what you learned>"\}/);
  // And the task still follows it.
  const combined = withMailbox('INVESTIGATE THE THING', paths, { thread: 'thread-1' });
  assert.match(combined, /INVESTIGATE THE THING/);
  assert.ok(combined.indexOf('mailbox') < combined.indexOf('INVESTIGATE THE THING'), 'instructions come first');
  assert.match(combined, /--- task ---/);
});

test('the rendering gives a reader the conversation, and says so when there is none', () => {
  const root = tempRoot();
  try {
    const paths = mailboxPaths({ root, thread: 'render' });
    const empty = renderThread(collectThread({ ...paths }));
    assert.equal(empty.count, 0);
    assert.match(empty.text, /mailbox is empty/);

    appendMessage(paths.inbox, { at: '2026-09-30T20:00:00Z', from: 'parent', kind: 'brief', text: 'question for you' });
    appendMessage(paths.outbox, { at: '2026-09-30T20:00:01Z', from: 'child', kind: 'question', text: 'which key?' });
    const rendered = renderThread(collectThread({ ...paths }));
    assert.equal(rendered.count, 2);
    assert.match(rendered.text, /PARENT ->/);
    assert.match(rendered.text, /<- CHILD/);
    assert.match(rendered.text, /BRIEF|QUESTION|PROGRESS|ANSWER|REPORT|NOTE/);
    assert.match(rendered.text, /which key\?/);

    // A long thread is bounded, and says what it left out rather than silently cutting.
    for (let i = 0; i < 60; i += 1) {
      appendMessage(paths.outbox, { at: `2026-09-30T21:${String(i).padStart(2, '0')}:00Z`, from: 'child', kind: 'progress', text: `note ${i}` });
    }
    const bounded = renderThread(collectThread({ ...paths }), { limit: 5 });
    assert.match(bounded.text, /earlier message\(s\) omitted/);
    assert.equal(bounded.count, 62);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a parent can find its threads again, newest first', () => {
  const root = tempRoot();
  try {
    const a = mailboxPaths({ root, thread: 'older' });
    const b = mailboxPaths({ root, thread: 'newer' });
    appendMessage(a.outbox, { at: '2026-09-30T20:00:00Z', from: 'child', kind: 'report', text: 'older work' });
    appendMessage(b.outbox, { at: '2026-09-30T22:00:00Z', from: 'child', kind: 'report', text: 'newer work' });

    const threads = listThreads(root);
    assert.deepEqual(threads.map((t) => t.thread), ['newer', 'older']);
    assert.equal(threads[0].messages, 1);
    assert.equal(threads[0].lastFrom, 'child');
    assert.equal(listThreads(path.join(root, 'does-not-exist')).length, 0, 'a missing root is empty, not an error');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the kinds are a closed set, so a reader can trust the label', () => {
  assert.deepEqual([...MESSAGE_KINDS].sort(), ['answer', 'brief', 'note', 'progress', 'question', 'report'].sort());
  // A child that wants to ask something and a child that is finishing have different
  // kinds, and both are legal; anything else is refused at write time.
  for (const kind of MESSAGE_KINDS) {
    assert.doesNotThrow(() => encodeMessage({ from: 'child', kind, text: 'x' }));
  }
});

test('appending creates the directory it needs, so a child cannot fail for want of a mkdir', () => {
  const root = tempRoot();
  try {
    const deep = path.join(root, 'a', 'b', 'c', 'inbox.jsonl');
    appendMessage(deep, { at: '2026-09-30T20:00:00Z', from: 'child', kind: 'note', text: 'written' });
    assert.match(readFileSync(deep, 'utf8'), /written/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a corrupt transcript is reported with its damage, never as an empty conversation', () => {
  // The distinction matters: "the child said nothing" and "the child's file is
  // unreadable" are different facts, and conflating them is how a lost report is
  // reported as a quiet child.
  const root = tempRoot();
  try {
    const paths = mailboxPaths({ root, thread: 'corrupt' });
    appendMessage(paths.outbox, { at: '2026-09-30T20:00:00Z', from: 'child', kind: 'progress', text: 'survives' });
    const truncated = readFileSync(paths.outbox, 'utf8') + '{"from":"child","kind":"prog';
    writeFileSync(paths.outbox, truncated, 'utf8');

    const collected = collectThread({ ...paths });
    assert.equal(collected.messages.length, 1, 'the complete line is kept');
    assert.ok(collected.warnings.length >= 1, 'and the truncation is reported');
    const rendered = renderThread(collected);
    assert.match(rendered.text, /survives/);
    assert.equal(rendered.warnings.length, collected.warnings.length, 'the rendering carries the warnings through');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// WHOSE SEPARATOR — 2026-10-05. The mailbox is on the CHILD's node, so a Windows
// dispatcher must not derive a POSIX node's path with `path.join`.
// ---------------------------------------------------------------------------

test('a POSIX target gets POSIX paths even when the dispatcher is Windows', async () => {
  const { defaultMailboxRoot, mailboxPaths } = await import('../lib/mailbox.js');
  const root = defaultMailboxRoot('/home/zabz', '/');
  assert.equal(root, '/home/zabz/.dsh-mesh-mailboxes');
  const paths = mailboxPaths({ root, thread: 't1', separator: '/' });
  assert.equal(paths.dir, '/home/zabz/.dsh-mesh-mailboxes/t1');
  assert.equal(paths.outbox, '/home/zabz/.dsh-mesh-mailboxes/t1/outbox.jsonl');
  assert.equal(paths.dir.includes('\\'), false);
  // A Windows target keeps backslashes...
  const win = mailboxPaths({ root: 'C:\\Users\\ezabz', thread: 't1', separator: '\\' });
  assert.equal(win.dir, 'C:\\Users\\ezabz\\t1');
  // ...and with no separator named, nothing changes from what it always was.
  assert.equal(defaultMailboxRoot('/home/zabz'), path.join('/home/zabz', '.dsh-mesh-mailboxes'));
});