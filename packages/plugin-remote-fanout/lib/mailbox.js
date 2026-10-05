/**
 * The child mailbox: a durable two-way channel between a parent agent and a child
 * that runs as a separate process on another machine.
 *
 * ── WHY THIS EXISTS, AND WHAT IT CANNOT DO ──────────────────────────────────
 *
 * The owner's requirement is continuous back-and-forth between a parent and its
 * children. The shipped runtime cannot provide it in-process, and this file is the
 * honest consequence of two measurements rather than a design preference:
 *
 *   1. `SubagentProvider.prepareContinuable` is documented as "DATA, never a
 *      capability" (`dsh-subagent/lib/types/types.d.ts:360-375`): it may only say
 *      whether the child session is seeded with parent history. The continuation
 *      manager itself owns identity reservation, composition, Agent creation,
 *      prompt delivery, cold resume, ownership and disposal — so a remote child,
 *      which has no in-process Agent for the manager to own, can never be a
 *      continuable child. `dsh-subagent/README.md:170` names this gap.
 *      The tempting workaround — implementing `prepareContinuable()` and returning
 *      an empty spec — passes both gates and then makes the manager compose the
 *      child LOCALLY while the parent believes the mesh placed it. A silent
 *      wrong-machine run is worse than a loud refusal, so it is not done.
 *
 *   2. `dsh --profile headless` accepts ONE task positional and nothing else
 *      (`dsh-headless/lib/startup.js:21`, read 2026-09-30): there is no `--resume`
 *      for that profile, so a child process cannot be re-entered with a follow-up.
 *      Each dispatch is a fresh process by construction.
 *
 * So the conversation is carried by the thing that DOES survive between processes:
 * the filesystem, on the node where the child runs. The parent writes a message
 * before dispatch; the child reads it and writes its replies; the parent collects
 * them afterwards and the transcript persists, so the NEXT dispatch on that thread
 * reads what the previous child said. That is a real conversation across turns —
 * not a promise of live steering, which nothing here can deliver.
 *
 * ── WHAT THAT MEANS OPERATIONALLY, STATED PLAINLY ───────────────────────────
 *
 *   WORKS:      parent → child before and after a dispatch;
 *               child → parent at any point during its own turn;
 *               parent → child follow-up dispatched on the same thread, with the
 *               child reading everything said so far;
 *               a multi-turn thread that survives a parent crash, because the
 *               transcript is on disk on the child's node.
 *
 *   DOES NOT:   interrupting a child mid-turn, or a parent answering a question
 *               while its child waits on it inside one turn. When no session is
 *               open there is no live process to steer, and `send_message` cannot
 *               reach a remote child (P2822). A child that needs an answer should
 *               ask in its transcript and END ITS TURN; the next dispatch on the
 *               thread carries the answer.
 *
 * ── THE FORMAT ──────────────────────────────────────────────────────────────
 *
 * One JSON object per line, append-only, so a partially written transcript is
 * still readable up to its last complete line — which matters because the writer
 * is a child process that can be killed at any moment (that is the whole subject
 * of the sibling transport work). Every record carries:
 *
 *   { at, from: 'parent'|'child', kind: 'brief'|'note'|'question'|'answer'|'progress'|'report', text, seq }
 *
 * `seq` is assigned on the read side in file order, never written by the sender,
 * so two writers cannot disagree about ordering.
 *
 * Everything in this module is pure except `appendMessage`/`readTranscript`, which
 * take the file path explicitly and do nothing else. That keeps the protocol
 * testable without a mesh, a network or a child.
 */

import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

/** The three files one conversation thread consists of. */
export const INBOX_NAME = 'inbox.jsonl';
export const OUTBOX_NAME = 'outbox.jsonl';
export const TRANSCRIPT_NAME = 'transcript.jsonl';

/** The markers the generated remote program can tee, if a caller wires them up. */
export const MAILBOX_DIR_ENV = 'MESH_MAILBOX_DIR';

/** The kinds a record may carry. A closed set, so a reader can trust the field. */
export const MESSAGE_KINDS = Object.freeze(['brief', 'note', 'question', 'answer', 'progress', 'report']);

/** The joiner for the path flavour the CHILD's node uses, not this process's. */
function joinerFor(separator) {
  if (separator === '/') return path.posix.join;
  if (separator === '\\') return path.win32.join;
  return path.join;
}

/** Default location when the caller names none: under the child's own work root. */
export function defaultMailboxRoot(cwd, separator) {
  const base = typeof cwd === 'string' && cwd.trim() !== '' ? cwd : '.';
  return joinerFor(separator)(base, '.dsh-mesh-mailboxes');
}

/**
 * The mailbox for one thread. Either derive it from a fixed directory name (a
 * caller that has already created one, e.g. over ssh) or from a root plus a thread.
 *
 * @param {{ dir?: string, root?: string, thread?: string }} spec
 */
export function mailboxPaths(spec = {}) {
  /**
   * ── WHOSE SEPARATOR ────────────────────────────────────────────────────────
   * The mailbox is on the CHILD's node, so its separator has to be the child's,
   * not this process's. Before this, a Windows dispatcher derived the path with
   * `path.join`, which on Windows turns a POSIX node's `/home/zabz` into
   * `\home\zabz` — a path that does not exist on that node and that the child
   * would have created as a literal backslash-named directory in its cwd.
   * `spec.separator` is how a caller that KNOWS the target platform says so; when
   * it is absent the behaviour is exactly what it always was, so nothing changes
   * for a dispatcher and a child on the same platform.
   */
  const join = joinerFor(spec.separator);
  if (typeof spec.dir === 'string' && spec.dir.trim() !== '') {
    const dir = spec.dir;
    return {
      dir,
      inbox: join(dir, INBOX_NAME),
      outbox: join(dir, OUTBOX_NAME),
      transcript: join(dir, TRANSCRIPT_NAME),
    };
  }
  if (typeof spec.root !== 'string' || spec.root.trim() === '') {
    throw new Error('remote-fanout mailbox: either `dir` or `root` is required');
  }
  if (typeof spec.thread !== 'string' || spec.thread.trim() === '') {
    throw new Error('remote-fanout mailbox: `thread` is required when deriving from a root');
  }
  // A thread name becomes a directory, so it must not be able to escape the root.
  //
  // REFUSED, NOT SANITISED. Silently rewriting `../../etc` into `______etc` would put
  // the message somewhere the caller did not name, and — worse — would map two
  // different thread names onto the SAME directory, merging two conversations into
  // one. A thread name is caller input that reaches here from a model, so an illegal
  // one is an error the caller must see, not something this function quietly fixes.
  if (!/^[A-Za-z0-9._-]+$/.test(spec.thread) || spec.thread === '.' || spec.thread === '..') {
    throw new Error(`remote-fanout mailbox: thread name ${JSON.stringify(spec.thread)} is not usable — it may contain only letters, digits, dot, underscore and hyphen, and may not be "." or ".."`);
  }
  if (spec.thread.includes('..')) {
    throw new Error(`remote-fanout mailbox: thread name ${JSON.stringify(spec.thread)} contains ".." — a thread can name a conversation but never a different directory`);
  }
  const dir = join(spec.root, spec.thread);
  return {
    dir,
    inbox: join(dir, INBOX_NAME),
    outbox: join(dir, OUTBOX_NAME),
    transcript: join(dir, TRANSCRIPT_NAME),
  };
}

/**
 * One line of the protocol. Pure: no clock of its own, no id, no sequence — the
 * caller supplies the time so a test can be deterministic, and the reader assigns
 * `seq` so two writers never disagree about order.
 */
export function encodeMessage({ at, from, kind, text }) {
  if (from !== 'parent' && from !== 'child') {
    throw new Error(`remote-fanout mailbox: "from" must be parent or child, got ${JSON.stringify(from)}`);
  }
  if (!MESSAGE_KINDS.includes(kind)) {
    throw new Error(`remote-fanout mailbox: unknown kind ${JSON.stringify(kind)}; expected one of ${MESSAGE_KINDS.join(', ')}`);
  }
  const body = String(text ?? '').replace(/\r\n/g, '\n');
  if (body.trim() === '') {
    throw new Error('remote-fanout mailbox: an empty message would be indistinguishable from a lost one');
  }
  return `${JSON.stringify({
    at: typeof at === 'string' && at !== '' ? at : new Date().toISOString(),
    from,
    kind,
    // Newlines are legal inside a JSON string but they make the file harder to read
    // by eye; the transcript is meant to be read by a human when something is wrong.
    text: body,
  })}\n`;
}

/**
 * Read a transcript, tolerating a truncated final line.
 *
 * A child process can be killed mid-write, and the sibling work on the transport
 * exists precisely because that happens. A reader that throws on a half-written
 * line would turn "the child was killed" into "the transcript is corrupt and
 * therefore useless" — which discards everything the child DID manage to say.
 */
export function parseTranscript(text) {
  const messages = [];
  const warnings = [];
  const lines = String(text ?? '').split('\n');
  lines.forEach((line, index) => {
    if (line.trim() === '') return;
    let record;
    try {
      record = JSON.parse(line);
    } catch {
      warnings.push(`line ${index + 1} is not complete JSON (a writer was interrupted here); it is skipped, and every earlier line is kept`);
      return;
    }
    if (record === null || typeof record !== 'object') {
      warnings.push(`line ${index + 1} is not an object; skipped`);
      return;
    }
    if (record.from !== 'parent' && record.from !== 'child') {
      warnings.push(`line ${index + 1} has from=${JSON.stringify(record.from)}; skipped`);
      return;
    }
    messages.push({
      seq: messages.length + 1,
      at: typeof record.at === 'string' ? record.at : null,
      from: record.from,
      kind: MESSAGE_KINDS.includes(record.kind) ? record.kind : 'note',
      text: typeof record.text === 'string' ? record.text : '',
      origin: record.origin ?? null,
    });
  });
  return { messages, warnings };
}

/** Append one record to a jsonl file, creating the directory if it does not exist. */
export function appendMessage(file, record) {
  const line = encodeMessage(record);
  mkdirSync(path.dirname(file), { recursive: true });
  appendFileSync(file, line, 'utf8');
  return { file, line };
}

/** Read a jsonl file that may not exist yet. Never throws on absence. */
export function readTranscript(file) {
  if (!existsSync(file)) return { messages: [], warnings: [], exists: false };
  let text;
  try {
    text = readFileSync(file, 'utf8');
  } catch (error) {
    return { messages: [], warnings: [`could not read ${file}: ${String(error?.message ?? error)}`], exists: true };
  }
  return { ...parseTranscript(text), exists: true };
}

/**
 * The whole conversation for one thread, assembled from all three files.
 *
 * WHY THE TRANSCRIPT HAS TO BE ONE OF THEM. `inbox` and `outbox` are each rewritten
 * by the next turn, so they hold only the CURRENT turn's messages; the transcript is
 * the append-only history that `mergeThread` builds. A reader that skipped it would
 * show the newest turn and silently lose the ones before it — measured: a
 * three-message conversation reported as two.
 *
 * De-duplication is by the record's own identity (time, author, kind, text), so a
 * message present in both the transcript and its writer's file is reported once.
 * Identical text from the same author at the same instant is indistinguishable from a
 * duplicate, which is the right trade: a conversation is not a place to count repeats.
 */
export function collectThread(paths, { includeTranscript = true } = {}) {
  const seen = new Set();
  const messages = [];
  const warnings = [];
  const parts = [
    ...(includeTranscript ? [['transcript', paths.transcript]] : []),
    ['inbox', paths.inbox],
    ['outbox', paths.outbox],
  ];
  for (const [source, file] of parts) {
    if (typeof file !== 'string') continue;
    const read = readTranscript(file);
    warnings.push(...read.warnings.map((w) => `${source}: ${w}`));
    for (const message of read.messages) {
      const key = `${message.at ?? ''}|${message.from}|${message.kind}|${message.text}`;
      if (seen.has(key)) continue;
      seen.add(key);
      messages.push({ ...message, file: source });
    }
  }
  // Time order, with a stable tiebreak so two messages written in the same second do
  // not swap places between reads.
  messages.sort((a, b) => String(a.at ?? '').localeCompare(String(b.at ?? '')));
  return {
    messages: messages.map((message, index) => ({ ...message, seq: index + 1 })),
    warnings,
  };
}

/**
 * Merge both writers' files into the canonical transcript, APPENDING what is new.
 *
 * Idempotent across turns. That property is the whole point: the transcript is the
 * durable history of a thread, while `inbox` and `outbox` are the two writers' own
 * files and the next turn overwrites neither but does re-use both. So this reads the
 * transcript that exists, appends only messages it has not recorded yet, and leaves
 * the rest alone. Running it twice adds nothing.
 *
 * (The first version rebuilt the file from the two writers every time, which is
 * idempotent within one turn and destroyed history across turns — measured: a
 * three-message conversation came back as two.)
 */
export function mergeThread(paths) {
  const existing = readTranscript(paths.transcript);
  const seen = new Set(existing.messages.map((message) => recordKey(message)));
  const incoming = collectThread(paths, { includeTranscript: false });
  const added = [];
  for (const message of incoming.messages) {
    const key = recordKey(message);
    if (seen.has(key)) continue;
    seen.add(key);
    added.push(message);
  }
  if (added.length > 0) {
    mkdirSync(paths.dir, { recursive: true });
    const body = added
      .map((message) => JSON.stringify({ at: message.at, from: message.from, kind: message.kind, text: message.text }))
      .join('\n');
    appendFileSync(paths.transcript, `${body}\n`, 'utf8');
  }
  const after = readTranscript(paths.transcript);
  return {
    messages: after.messages,
    warnings: [...existing.warnings, ...incoming.warnings, ...after.warnings],
    added: added.length,
  };
}

/** The identity of one message, for de-duplication across turns and sources. */
function recordKey(message) {
  return `${message.at ?? ''}|${message.from}|${message.kind}|${message.text}`;
}

/** The prefix of the quote-free machine-readable manifest line. */
export const MANIFEST_B64_PREFIX = 'MESH_MAILBOX_B64=';

/**
 * The quote-free spelling of the same manifest.
 *
 * ── WHY THERE ARE NOW TWO, AND THE MEASUREMENT THAT FORCED THE SECOND ───────
 * The JSON manifest is the machine-readable line, and JSON is made of `"`. The
 * child reaches the node through a shell that gets a vote on the bytes: on a
 * Windows node the target runs Windows PowerShell 5.1, which splices a native
 * argument into a command line the C runtime re-parses, and a bare `"` is
 * consumed as a quote-toggle. Measured through the real transport on ZABZ-TECH
 * 2026-10-05 (`node -e` echoing `process.argv`):
 *
 *   handed  MESH_MAILBOX={"dir":"C:/x"}      child received MESH_MAILBOX={dir:C:/x}
 *
 * i.e. invalid JSON, on every dispatch to every Windows node — this line was
 * never readable by the child it was written for, and the child was
 * simultaneously told to reply with a JSON example that had lost its own quotes.
 *
 * `remote-script.js` now escapes native arguments, which fixes the JSON line too.
 * This second spelling exists so the manifest does not DEPEND on that fix, or on
 * any future change to how a shell quotes: the base64url alphabet is
 * `A-Z a-z 0-9 - _`, which contains no quote, no backslash and no whitespace, so
 * it is byte-identical in the generated program, in the child's argv, and in this
 * file. `parseMailboxManifest` reads it first and the JSON form as a fallback.
 */
export function encodeManifestToken(manifest) {
  return `${MANIFEST_B64_PREFIX}${Buffer.from(JSON.stringify(manifest), 'utf8').toString('base64url')}`;
}

/**
 * The instructions the child is given, as text appended to its task.
 *
 * The child runs on another machine with no knowledge of this protocol beyond what
 * this text says, so the text has to be complete and concrete: where the mailbox
 * is, what to do at the start, and — the part that matters most for a report that
 * has to survive — to WRITE BEFORE ITS TURN ENDS, because the transport can kill
 * the process after the work is done (journal L3188) and a message only written at
 * the very end is a message that can be lost with it.
 */
export function childInstructions(paths, { thread } = {}) {
  // ── THE MACHINE-READABLE LINE ─────────────────────────────────────────────
  // The task text is flattened to ONE line before it reaches the child, so a reader
  // (or a test) cannot reliably find the mailbox by parsing the prose around it. The
  // single JSON line is self-delimiting and survives that flattening, so the path can
  // be recovered from the exact bytes the child was handed — and the base64url line
  // beside it survives the shell as well, for the reason recorded above.
  const manifest = {
    dir: paths.dir,
    inbox: paths.inbox,
    outbox: paths.outbox,
    transcript: paths.transcript,
    ...(typeof thread === 'string' && thread !== '' ? { thread } : {}),
  };
  const lines = [
    // OPENS WITH `=`, NOT `---`. It opened with `---` until 2026-10-05, and that
    // single character was the whole of a live outage: `dsh --profile headless`
    // parses its task with commander, a value starting with `-` is classified as
    // an OPTION, and every mailbox dispatch therefore died with
    //   error: unknown option '--- mesh mailbox (read this before the task) --- …'
    // exit 1 and no final message, which the parent reports as "the remote
    // one-shot exited 1 and produced no final message". The transport now emits a
    // double `--` separator so ANY task is a positional (`remote-script.js`), and
    // this header is the second layer: a dispatcher that ever loses that
    // separator still cannot hand the CLI an option-shaped task, because the
    // first byte of every mailbox brief is this line.
    '=== mesh mailbox (read this before the task) ===',
    `MESH_MAILBOX=${JSON.stringify(manifest)}`,
    encodeManifestToken(manifest),
    'You are a child agent on a separate machine. Your parent is not reachable in-process:',
    'to say anything to it, WRITE TO FILES. The mailbox for this conversation is:',
    `  directory: ${paths.dir}`,
    `  inbox     (your parent writes here; read it first): ${paths.inbox}`,
    `  outbox    (you write here): ${paths.outbox}`,
  ];
  if (typeof thread === 'string' && thread !== '') lines.push(`  thread id: ${thread}`);
  lines.push(
    'BEFORE you start the task: read the inbox file if it exists and act on anything in it.',
    'WHILE you work: append a line to the outbox whenever you learn something your parent would',
    'want before you finish — a finding, a decision, a question you cannot answer yourself.',
    'Each line must be one JSON object on its own line, exactly:',
    '  {"at":"<ISO-8601 time>","from":"child","kind":"progress","text":"<what you learned>"}',
    'Use kind "question" for something you need answered, and "report" for your final answer.',
    'DO NOT WAIT FOR A REPLY. Your parent cannot answer you while you are running. If you need an',
    'answer, write the question to the outbox and END YOUR TURN — the answer arrives when you are',
    'dispatched again on this same thread.',
    'WRITE AS YOU GO, NOT AT THE END. If the transport loses your final message, everything already',
    'in the outbox is recovered; a report written only at the very end is a report that can vanish.',
    '--- task ---',
  );
  return lines.join('\n');
}

/** Fold the mailbox section into a task. Kept as a function rather than a template
 * so both the one-shot preamble and any future dispatch shape compose the same way.
 */
export function withMailbox(task, paths, options = {}) {
  return `${childInstructions(paths, options)}\n${String(task ?? '')}`;
}

/**
 * Recover a mailbox manifest from the exact text handed to a child.
 *
 * Why this exists: the task is flattened to one line before it reaches the child, so
 * prose parsing around the path is unreliable, and a caller that wants to CONTINUE a
 * conversation needs the outbox path of the dispatch it is continuing. The manifest
 * line is self-delimiting, so this reads the same bytes the child read.
 *
 * Returns `null` when the text carries no mailbox — which is a legitimate state (a
 * dispatch with the mailbox switched off), not an error.
 */
export function parseMailboxManifest(text) {
  const source = String(text ?? '');
  // The quote-free spelling is tried FIRST: it is the one that survives a shell
  // that mangles quotes (see `encodeManifestToken`), so preferring it means a
  // reader gets the same answer from the generated program, from the child's argv,
  // and from a transcript that has been through both.
  const b64 = new RegExp(`${MANIFEST_B64_PREFIX}([A-Za-z0-9_-]+)`).exec(source);
  if (b64 !== null) {
    let parsed;
    try {
      parsed = JSON.parse(Buffer.from(b64[1], 'base64url').toString('utf8'));
    } catch {
      parsed = undefined;
    }
    if (isUsableManifest(parsed)) return normalizeManifest(parsed);
  }
  const match = /MESH_MAILBOX=(\{.*?\})(?=\s|$)/s.exec(source);
  if (match === null) return null;
  let parsed;
  try {
    parsed = JSON.parse(match[1]);
  } catch {
    return null;
  }
  return isUsableManifest(parsed) ? normalizeManifest(parsed) : null;
}

/** A manifest is usable when it names the three files a thread is made of. */
function isUsableManifest(parsed) {
  return parsed !== null && typeof parsed === 'object'
    && typeof parsed.dir === 'string'
    && typeof parsed.outbox === 'string'
    && typeof parsed.inbox === 'string';
}

function normalizeManifest(parsed) {
  return {
    dir: parsed.dir,
    inbox: parsed.inbox,
    outbox: parsed.outbox,
    transcript: typeof parsed.transcript === 'string' ? parsed.transcript : path.join(parsed.dir, TRANSCRIPT_NAME),
    thread: typeof parsed.thread === 'string' ? parsed.thread : null,
  };
}

/** A compact, human-readable rendering of a thread, for the parent's report. */
export function renderThread(collection, { limit = 40 } = {}) {
  const { messages, warnings } = collection;
  if (messages.length === 0) {
    return { text: 'the mailbox is empty — the child wrote nothing and the parent wrote nothing', count: 0, warnings };
  }
  const shown = messages.slice(-limit);
  const omitted = messages.length - shown.length;
  const body = shown.map((message) => {
    const who = message.from === 'parent' ? 'PARENT ->' : '<- CHILD ';
    const kind = message.kind.toUpperCase();
    const when = message.at ?? 'time unknown';
    return `${who} [${kind}] ${when}\n    ${String(message.text).replace(/\n/g, '\n    ')}`;
  }).join('\n');
  return {
    text: `${omitted > 0 ? `(${omitted} earlier message(s) omitted; ${messages.length} in the thread)\n` : ''}${body}`,
    count: messages.length,
    warnings,
  };
}

/** Every thread under a root, newest first — so a parent can find a conversation again. */
export function listThreads(root) {
  if (!existsSync(root)) return [];
  const entries = [];
  for (const name of readDirNames(root)) {
    const dir = path.join(root, name);
    const paths = { dir, inbox: path.join(dir, INBOX_NAME), outbox: path.join(dir, OUTBOX_NAME), transcript: path.join(dir, TRANSCRIPT_NAME) };
    const collected = collectThread(paths);
    const last = collected.messages[collected.messages.length - 1];
    entries.push({ thread: name, dir, messages: collected.messages.length, lastAt: last?.at ?? null, lastFrom: last?.from ?? null });
  }
  entries.sort((a, b) => String(b.lastAt ?? '').localeCompare(String(a.lastAt ?? '')));
  return entries;
}

function readDirNames(dir) {
  try {
    return readdirSync(dir, { withFileTypes: true }).filter((entry) => entry.isDirectory()).map((entry) => entry.name);
  } catch {
    return [];
  }
}
