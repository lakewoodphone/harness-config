/**
 * The four parent-facing mesh child tools (R5, D2/D3).
 *
 * WHAT THEY ARE FOR
 * The engine cannot address a mesh child — it has no `localAgent`, so there is no
 * `send_message`, no `interrupt_agent`, no child row and an empty Subagents UI
 * (see `docs/mesh/120-continuable-mesh-children.md`; the native fix is an engine
 * Activation-ownership contract, deliberately not redone here). These four tools
 * are the plugin's own control surface over the durable child record in
 * `lib/child-registry.js`:
 *
 *   mesh_children   list children from the registry — node, state, age, lease,
 *                   last host, and where the answer will land
 *   mesh_message    append a message to the child's inbox ON THE TARGET over ssh
 *   mesh_interrupt  write a stop request to the same inbox
 *   mesh_collect    read the child's outbox from the target over ssh
 *
 * THE MAILBOX IS DURABLE; DELIVERY IS NOT INSTANT. A one-shot child reads its
 * inbox only at the checkpoints it actually reaches, so every answer says so
 * plainly instead of implying a live channel. The outbox is the reverse: the
 * child appends to it on the TARGET, so `mesh_collect` still works after the ssh
 * transport that ran the child has died — which is the whole point (P2538b).
 *
 * HERMETIC BY CONSTRUCTION. Nothing here builds an ssh command line by hand:
 * `meshToolDefinitions` takes a `runRemote({ ssh, shell, script })` function, so
 * the whole tool layer is exercised in tests against a fake that touches no node.
 * The default builds a fresh `createSshTransport` per call, targeting the ssh
 * destination recorded for the child.
 */

import { psQuote, shQuote } from './remote-script.js';
import { createSshTransport } from './ssh-transport.js';

/** The directory part of a target path, for `mkdir -p`/`New-Item`. */
function splitDir(file) {
  const text = String(file ?? '');
  const at = Math.max(text.lastIndexOf('/'), text.lastIndexOf('\\'));
  return at <= 0 ? text : text.slice(0, at);
}

/**
 * Quote a target path for the POSIX shell. A path the provider left as a shell
 * expression (`$HOME/...`, when the placement did not name a DSH_HOME) stays
 * unquoted so the TARGET expands it, exactly as the child's own preamble does;
 * a literal path is single-quoted.
 */
function posixPathWord(value) {
  const text = String(value ?? '');
  if (!text.includes('$')) return shQuote(text);
  return `"${text.replace(/(["\\])/g, '\\$1')}"`;
}

/** The PowerShell twin of {@link posixPathWord}. */
function psPathWord(value) {
  const text = String(value ?? '');
  if (!text.includes('$')) return psQuote(text);
  return `"${text.replace(/(["`])/g, '`$1')}"`;
}

/** The program that appends one JSON line to a file on the target. */
export function appendLineCommand({ shell, file, line }) {
  const dir = splitDir(file);
  if (shell === 'powershell') {
    return `$fanoutDir = ${psPathWord(dir)}; New-Item -ItemType Directory -Force -Path $fanoutDir | Out-Null; `
      + `Add-Content -LiteralPath ${psPathWord(file)} -Value ${psQuote(line)}`;
  }
  return `mkdir -p ${posixPathWord(dir)} && printf '%s\\n' ${shQuote(line)} >> ${posixPathWord(file)}`;
}

/** The program that prints a file from the target, or nothing when it is absent. */
export function readOutboxCommand({ shell, file }) {
  if (shell === 'powershell') {
    return `if (Test-Path -LiteralPath ${psPathWord(file)}) { Get-Content -LiteralPath ${psPathWord(file)} -Raw }`;
  }
  return `if [ -f ${posixPathWord(file)} ]; then cat ${posixPathWord(file)}; fi`;
}

/** The shell of a child record, narrowed to the two this plugin speaks. */
const shellOf = (record) => (record?.shell === 'powershell' ? 'powershell' : 'posix');

/** One registry row projected for the model, with absent fields omitted. */
function projectChild(record, atMs) {
  const created = Date.parse(record?.createdAt ?? '');
  const row = { id: String(record?.id ?? '') };
  if (record?.node !== undefined && record.node !== null) row.node = String(record.node);
  if (record?.state !== undefined && record.state !== null) row.state = String(record.state);
  if (record?.lease !== undefined && record.lease !== null) row.lease = String(record.lease);
  const host = record?.host ?? record?.reportedHost;
  if (host !== undefined && host !== null) row.host = String(host);
  if (record?.ssh !== undefined && record.ssh !== null) row.ssh = String(record.ssh);
  if (record?.inbox !== undefined && record.inbox !== null) row.inbox = String(record.inbox);
  if (record?.outbox !== undefined && record.outbox !== null) row.outbox = String(record.outbox);
  if (Number.isFinite(created) && Number.isFinite(atMs)) row.ageMs = Math.max(0, atMs - created);
  return row;
}

const CHILD_ROW_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    id: { type: 'string' },
    node: { type: 'string' },
    state: { type: 'string' },
    lease: { type: 'string' },
    host: { type: 'string' },
    ssh: { type: 'string' },
    inbox: { type: 'string' },
    outbox: { type: 'string' },
    ageMs: { type: 'number' },
  },
  required: ['id'],
};

const TEXT_BLOCK = (text) => [{ type: 'text', text }];

const CHILDREN_DESCRIPTION = 'List the mesh children this engine has dispatched (a durable child registry, not the engine\'s '
  + 'in-process agent list — a remote child has no local agent, so `list_agents` cannot see it). Each row names the node, the '
  + 'state, the age, the broker lease, the last host the transport actually proved, and where the child\'s answer will land '
  + '(its outbox on the target). Use `mesh_collect` to read that outbox; it works even after the ssh transport that ran the '
  + 'child has died.';

const MESSAGE_DESCRIPTION = 'Send a message to a mesh child\'s durable inbox ON THE TARGET NODE. This is a mailbox, not a live '
  + 'channel: a one-shot child reads it only at the next checkpoint it actually reaches, so delivery is not instant and a child '
  + 'already past its last checkpoint will never read it. The result says plainly whether the write reached the target.';

const INTERRUPT_DESCRIPTION = 'Ask a mesh child to stop by writing a stop request to its durable inbox ON THE TARGET NODE. It '
  + 'is obeyed at the child\'s next checkpoint, not instantly — a one-shot child between checkpoints keeps running until it '
  + 'reaches one, and a child already finished will never read it. The result says whether the write reached the target.';

const COLLECT_DESCRIPTION = 'Read a mesh child\'s outbox from the target node over ssh. This is the durable half of a mesh '
  + 'child: the child appends progress and, contractually, its final answer there, so collection works after the transport that '
  + 'ran the child has died. Returns the lines written so far; an empty outbox means the child has not reached a checkpoint yet.';

/** A refusal that names the missing record and sends nothing. */
function unknownChild(childId, registry) {
  const known = registry.list().map((record) => record.id).filter(Boolean);
  return {
    message: `no record for child "${childId}" in the mesh child registry — nothing was sent`
      + (known.length > 0 ? ` (known children: ${known.join(', ')})` : ' (the registry is empty)'),
  };
}

/** Deliver one line to one target file, mapping every failure to a sentence. */
async function deliver({ record, file, line, runRemote }) {
  if (typeof record.ssh !== 'string' || record.ssh === '') {
    return { ok: false, error: `child "${record.id}" has no recorded ssh destination` };
  }
  const shell = shellOf(record);
  const script = appendLineCommand({ shell, file, line });
  try {
    const outcome = await runRemote({ ssh: record.ssh, shell, script, childId: record.id });
    if (outcome?.ok === true) return { ok: true, outcome };
    const error = String(outcome?.stderr ?? '').trim()
      || String(outcome?.spawnError ?? '').trim()
      || `ssh to ${record.ssh} exited ${outcome?.exitCode ?? 'without a code'}`;
    return { ok: false, error, outcome };
  } catch (error) {
    return { ok: false, error: String(error?.message ?? error) };
  }
}

/** The default remote runner: a fresh ssh transport per call, per child. */
function defaultRunRemote(options = {}) {
  const { sshExe, sshArgs, timeoutMs } = options;
  return async ({ ssh, shell, script }) => {
    const transport = createSshTransport({ sshExe, sshArgs, target: ssh, timeoutMs });
    const handle = transport.start({ shell, script, timeoutMs });
    const outcome = await handle.done;
    return {
      ok: outcome.ok === true && outcome.spawnError === undefined,
      exitCode: outcome.exitCode,
      stdout: outcome.stdout ?? '',
      stderr: outcome.stderr ?? '',
      spawnError: outcome.spawnError,
      timedOut: outcome.timedOut === true,
      ms: outcome.ms,
    };
  };
}

/**
 * Build the four tool definitions without touching a context, so they can be
 * called directly in tests.
 *
 * @param {object} options
 * @param {object} options.registry the child registry (required)
 * @param {(request: {ssh: string, shell: string, script: string, childId: string}) => Promise<object>} [options.runRemote]
 * @param {() => number} [options.now] clock injection for `ageMs`
 */
export function meshToolDefinitions(options = {}) {
  const { registry, logger } = options;
  if (registry === undefined || typeof registry.list !== 'function' || typeof registry.get !== 'function') {
    throw new Error('mesh-tools: a child registry with get()/list() is required');
  }
  const runRemote = typeof options.runRemote === 'function' ? options.runRemote : defaultRunRemote(options);
  const clock = typeof options.now === 'function' ? options.now : () => Date.now();
  const at = () => new Date(clock()).toISOString();

  const childrenDefinition = {
    name: 'mesh_children',
    description: CHILDREN_DESCRIPTION,
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        state: { type: 'string', description: 'Only children in this state, e.g. dispatching, running, stopping, settled.' },
        parentSessionId: { type: 'string', description: 'Only children created by this parent session.' },
      },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: { children: { type: 'array', items: CHILD_ROW_SCHEMA } },
        required: ['children'],
      },
      render(_args, value) {
        const rows = Array.isArray(value?.children) ? value.children : [];
        if (rows.length === 0) return TEXT_BLOCK('no mesh children are recorded');
        return TEXT_BLOCK(rows.map((row) => {
          const age = Number.isFinite(row.ageMs) ? `${Math.round(row.ageMs / 1000)} s` : 'unknown';
          return `${row.id} [${row.state ?? 'unknown'}] node=${row.node ?? 'unknown'} lease=${row.lease ?? 'none'} `
            + `lastHost=${row.host ?? 'unreported'} age=${age} — answer lands in ${row.outbox ?? '(outbox not recorded)'}`;
        }).join('\n'));
      },
    },
    timeoutMs: 15_000,
    async execute(args) {
      const filter = {};
      if (typeof args?.state === 'string' && args.state !== '') filter.state = args.state;
      if (typeof args?.parentSessionId === 'string' && args.parentSessionId !== '') filter.parentSessionId = args.parentSessionId;
      const atMs = clock();
      return { children: registry.list(filter).map((record) => projectChild(record, atMs)) };
    },
  };

  const messageDefinition = {
    name: 'mesh_message',
    description: MESSAGE_DESCRIPTION,
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        child_id: { type: 'string', description: 'The child id, as `mesh_children` reports it (e.g. remote-<uuid>).' },
        message: { type: 'string', description: 'The text the child reads at its next checkpoint.' },
      },
      required: ['child_id', 'message'],
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          delivered: { type: 'boolean' },
          childId: { type: 'string' },
          inbox: { type: 'string' },
          message: { type: 'string' },
        },
        required: ['delivered', 'message'],
      },
      render(_args, value) {
        return TEXT_BLOCK(String(value?.message ?? 'mesh_message: no message'));
      },
    },
    timeoutMs: 30_000,
    async execute(args) {
      const childId = String(args?.child_id ?? '');
      const message = String(args?.message ?? '');
      const record = registry.get(childId);
      if (record === undefined) return { delivered: false, childId, ...unknownChild(childId, registry) };
      if (message.trim() === '') return { delivered: false, childId, message: 'mesh_message needs a non-empty message' };
      const inbox = record.inbox ?? registry.inboxPath?.(childId);
      if (typeof inbox !== 'string' || inbox === '') {
        return { delivered: false, childId, message: `child "${childId}" has no recorded inbox path — it predates the mailbox, so nothing was sent` };
      }
      const line = JSON.stringify({ type: 'message', childId, at: at(), body: message });
      const result = await deliver({ record, file: inbox, line, runRemote });
      if (!result.ok) {
        logger?.warn?.(`remote-fanout: mesh_message could not deliver to ${childId}: ${result.error}`);
        return { delivered: false, childId, inbox, message: `NOT delivered to ${inbox} on ${record.ssh ?? 'the target'}: ${result.error}` };
      }
      return {
        delivered: true,
        childId,
        inbox,
        message: `delivered to ${inbox} on ${record.ssh} — this is read at the child's next checkpoint, not instantly`,
      };
    },
  };

  const interruptDefinition = {
    name: 'mesh_interrupt',
    description: INTERRUPT_DESCRIPTION,
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        child_id: { type: 'string', description: 'The child id, as `mesh_children` reports it.' },
        reason: { type: 'string', description: 'Why the child is being asked to stop; shown to the child.' },
      },
      required: ['child_id'],
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          requested: { type: 'boolean' },
          childId: { type: 'string' },
          inbox: { type: 'string' },
          message: { type: 'string' },
        },
        required: ['requested', 'message'],
      },
      render(_args, value) {
        return TEXT_BLOCK(String(value?.message ?? 'mesh_interrupt: no message'));
      },
    },
    timeoutMs: 30_000,
    async execute(args) {
      const childId = String(args?.child_id ?? '');
      const reason = String(args?.reason ?? 'the parent asked this child to stop');
      const record = registry.get(childId);
      if (record === undefined) return { requested: false, childId, ...unknownChild(childId, registry) };
      const inbox = record.inbox ?? registry.inboxPath?.(childId);
      if (typeof inbox !== 'string' || inbox === '') {
        return { requested: false, childId, message: `child "${childId}" has no recorded inbox path — no stop request was written` };
      }
      const line = JSON.stringify({ type: 'stop', childId, at: at(), reason });
      const result = await deliver({ record, file: inbox, line, runRemote });
      if (!result.ok) {
        return { requested: false, childId, inbox, message: `stop request NOT delivered to ${inbox} on ${record.ssh ?? 'the target'}: ${result.error}` };
      }
      try {
        registry.patch(childId, { state: 'stopping', stopRequestedAt: at() });
      } catch {
        // The record is a courtesy here; the stop line is already on the target.
      }
      return {
        requested: true,
        childId,
        inbox,
        message: `stop request written to ${inbox} on ${record.ssh} — the child obeys it at its next checkpoint, not instantly`,
      };
    },
  };

  const collectDefinition = {
    name: 'mesh_collect',
    description: COLLECT_DESCRIPTION,
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        child_id: { type: 'string', description: 'The child id, as `mesh_children` reports it.' },
      },
      required: ['child_id'],
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean' },
          childId: { type: 'string' },
          node: { type: 'string' },
          ssh: { type: 'string' },
          outbox: { type: 'string' },
          lines: { type: 'array', items: { type: 'string' } },
          text: { type: 'string' },
        },
        required: ['ok', 'text'],
      },
      render(_args, value) {
        return TEXT_BLOCK(String(value?.text ?? 'mesh_collect: nothing to show'));
      },
    },
    timeoutMs: 30_000,
    async execute(args) {
      const childId = String(args?.child_id ?? '');
      const record = registry.get(childId);
      if (record === undefined) {
        const refusal = unknownChild(childId, registry);
        return { ok: false, childId, text: refusal.message };
      }
      const outbox = record.outbox ?? registry.outboxPath?.(childId);
      if (typeof outbox !== 'string' || outbox === '') {
        return { ok: false, childId, text: `child "${childId}" has no recorded outbox path — there is nowhere to collect from` };
      }
      if (typeof record.ssh !== 'string' || record.ssh === '') {
        return { ok: false, childId, outbox, text: `child "${childId}" has no recorded ssh destination, so its outbox at ${outbox} cannot be read` };
      }
      const shell = shellOf(record);
      const script = readOutboxCommand({ shell, file: outbox });
      let outcome;
      try {
        outcome = await runRemote({ ssh: record.ssh, shell, script, childId });
      } catch (error) {
        return { ok: false, childId, outbox, text: `could not read the outbox at ${outbox} on ${record.ssh}: ${String(error?.message ?? error)}` };
      }
      if (outcome?.ok !== true) {
        const why = String(outcome?.stderr ?? outcome?.spawnError ?? `ssh exited ${outcome?.exitCode ?? 'without a code'}`).trim();
        return { ok: false, childId, outbox, text: `could not read the outbox at ${outbox} on ${record.ssh}: ${why}` };
      }
      const lines = String(outcome.stdout ?? '').split(/\r?\n/).filter((line) => line.trim() !== '');
      try {
        registry.patch(childId, { state: 'collected', lastCollectedAt: at(), outboxLines: lines.length });
      } catch {
        // Collection succeeded; the record update is not worth failing for.
      }
      return {
        ok: true,
        childId,
        node: record.node,
        ssh: record.ssh,
        outbox,
        lines,
        text: lines.length === 0
          ? `the outbox for ${childId} at ${outbox} is empty — the child has not reached a checkpoint yet`
          : lines.join('\n'),
      };
    },
  };

  return [childrenDefinition, messageDefinition, interruptDefinition, collectDefinition];
}

/**
 * Register the four tools into the calling context's tool layer, the way this
 * package registers everything else: through the shipped service, disposing with
 * the scope.
 *
 * @returns {() => void} a disposer for all four registrations
 */
export function registerMeshTools(ctx, options = {}) {
  if (ctx?.tools === undefined || typeof ctx.tools.register !== 'function') {
    throw new Error('mesh-tools: the calling context has no tools service');
  }
  const disposers = meshToolDefinitions(options).map((definition) => ctx.tools.register(definition));
  return () => {
    for (const dispose of disposers) {
      try {
        dispose?.();
      } catch {
        // A disposal that fails must not stop the other three.
      }
    }
  };
}
