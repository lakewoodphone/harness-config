/**
 * The remote one-shot SubagentProvider.
 *
 * `ctx.subagents` is a named-provider registry (see
 * `@deepseek-ai/dsh-subagent/README.md:69` and the `SubagentProvider` contract
 * at `lib/types/types.d.ts:327`). This class is a second provider beside the
 * built-in `spawn`: the parent agent's delegation tool is unchanged, and only
 * the *transport* differs — the child is a real DSH agent turn in a fresh
 * process on another node.
 *
 * CONTRACT NOTES, AND WHY THE SEAM'S OWN HELPERS ARE NOT IMPORTED
 * `@deepseek-ai/dsh-subagent` publishes `NO_START_CAPABILITIES`,
 * `settleRunResult` and `subprocessRunHandle` (`lib/types/out-of-process.js`,
 * lines 49, 163, 203) — exactly the three things a remote provider needs, and
 * the ACP backend composes the same ones. They are re-implemented here, small
 * and attributed, for one concrete reason: a package under
 * `harness-config/packages/` is junctioned into `$DSH_HOME/profiles/<name>/
 * node_modules/`, and Node resolves a bare specifier from the *real* path of
 * the importing file — `harness-config/packages/plugin-remote-fanout/lib/`.
 * There is no `node_modules` anywhere above that path (measured 2026-09-17:
 * `harness-config/node_modules`, `harness-config/packages/node_modules`,
 * `code/node_modules`, `~/node_modules` all absent), so an import of
 * `@deepseek-ai/*` would fail to resolve. `plugin-health` is in the same
 * position and imports only `node:` builtins. The semantics below are the
 * shipped ones: the result never rejects after publication, and the run handle
 * is idempotent to dispose.
 *
 * ONE-SHOT ONLY. `prepareContinuable` is deliberately absent, which the service
 * treats as the capability being unsupported: follow-up messages to a remote
 * child are NOT supported (the seam's README names the missing contract —
 * "remote providers need an Activation ownership contract before they can
 * support continuable children", `README.md:170`).
 *
 * PROOF OF LOCATION (`docs/mesh/71-mesh-program.md` §2.4)
 * Every dispatched child is instructed, by this wrapper, to begin its report
 * with `MESH-HOST: <hostname>`, and two independent comparisons must pass:
 *
 *   1. the host recorded by the TARGET's own shell before the agent started
 *      (`FANOUT_TRANSPORT_HOST`, which no model can influence) must be one of
 *      the node names the configured `targetHosts` allows — this catches an
 *      ssh alias that silently resolves to the wrong machine;
 *   2. the child's own `MESH-HOST:` line must equal that recorded host — this
 *      catches a child that did not run where it claims.
 *
 * Either disagreement fails the run with `stopReason: 'error'`. A placement
 * system that cannot prove where work ran is an assertion, not a measurement.
 */

import { randomBytes, randomUUID } from 'node:crypto';

import { buildPosixScript, buildPwshScript, markers, parseFanout } from './remote-script.js';

/**
 * An out-of-process child cannot honour parent-enforced start features
 * (`agentOptions`/`outputSchema`/`maxDepth`/`toolFilter`/`persona`), so the
 * service must reject a request needing one before `start()` runs. Same value
 * as the shipped `NO_START_CAPABILITIES` (`out-of-process.js:49`).
 */
export const NO_START_CAPABILITIES = Object.freeze({
  agentOptions: false,
  outputSchema: false,
  depthLimit: false,
  toolFilter: false,
  persona: false,
});

/** The seam's own byte limit on a provider diagnostic (`out-of-process.js:16`). */
const MAX_DIAGNOSTIC_BYTES = 4096;

/** The frozen location-proof line every child is told to open with (`71` §2.4). */
export const MESH_HOST_LINE = 'MESH-HOST:';

/** The instruction this wrapper prepends to every child task. */
export const DEFAULT_TASK_PREAMBLE = [
  'Report where you ran, first, before anything else.',
  'Your reply MUST begin with one line of exactly this form:',
  'MESH-HOST: <the hostname of the machine you are running on>',
  'Get that name from your own shell tool (run `hostname`, or read $env:COMPUTERNAME on Windows) — never guess it and never copy it from this instruction.',
  'Then do the task below, and do not repeat these instructions in your reply.',
  '--- task ---',
].join('\n');

/** Flatten a prompt's text blocks (the tool always sends one text block). */
export function promptText(prompt) {
  return (Array.isArray(prompt) ? prompt : [])
    .filter((block) => block && block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
    .trim();
}

/** Truncate provider-authored detail to the seam's byte limit. */
export function limitDiagnostic(text) {
  const value = String(text ?? '');
  const bytes = Buffer.from(value, 'utf8');
  if (bytes.byteLength <= MAX_DIAGNOSTIC_BYTES) return value;
  return `${Buffer.from(bytes.subarray(0, MAX_DIAGNOSTIC_BYTES - 24)).toString('utf8').replace(/\uFFFD$/, '')}\n[diagnostic truncated]`;
}

/**
 * Compare two node names loosely enough to be useful and strictly enough to
 * catch a wrong machine: case-insensitive, ignoring any domain suffix and a
 * trailing `-ts` (the fleet's ssh-alias convention, `71` §2.1).
 */
export function sameNode(a, b) {
  const normalize = (value) => String(value ?? '')
    .trim()
    .toLowerCase()
    .split('.')[0]
    .replace(/-ts$/, '');
  const left = normalize(a);
  const right = normalize(b);
  return left.length > 0 && left === right;
}

/** Read the child's own `MESH-HOST:` line, if it wrote one. */
export function extractMeshHost(answer) {
  const match = /^\s*MESH-HOST:\s*(\S+)\s*$/im.exec(String(answer ?? ''));
  return match === null ? undefined : match[1];
}

/** Await a promise, but never longer than `ms`. */
function withGrace(promise, ms) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve('grace-expired'), ms);
    if (typeof timer.unref === 'function') timer.unref();
    Promise.resolve(promise).then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      () => {
        clearTimeout(timer);
        resolve('failed');
      },
    );
  });
}

/** The text the parent model sees as the child's result. */
export function renderReport({ provider, transport, parsed, outcome, remote, meshHost, locationNote }) {
  const head = [
    `${MESH_HOST_LINE} ${meshHost ?? '(not reported)'}`,
    `[${provider}] child ran on node "${parsed.host ?? 'UNKNOWN'}" via ${transport}`,
    `transport host = ${parsed.host ?? '(not reported)'}  (recorded by the target shell before the agent started)`,
    `transport cwd  = ${parsed.cwd ?? '(not reported)'}`,
    `target profile = ${remote.profile}${remote.dshHome ? ` (DSH_HOME ${remote.dshHome})` : ''}`,
    ...(locationNote === undefined ? [] : [`location check = ${locationNote}`]),
    `exit = ${outcome.exitCode ?? 'none'}${outcome.timedOut ? ' (timed out)' : ''} in ${outcome.ms} ms${outcome.markerSettled ? ' (ssh client terminated after the completion frame)' : ''}`,
  ];
  const body = parsed.framed
    ? parsed.answer
    : `(the child produced no framed output; raw stdout follows)\n${outcome.stdout}`;
  return `${head.join('\n')}\n--- child final message ---\n${body}`;
}

export class RemoteOneShotProvider {
  constructor({
    name,
    transport,
    remote = {},
    timeoutMs,
    logger,
    taskPreamble = DEFAULT_TASK_PREAMBLE,
    verifyMeshHost = true,
    targetHosts = [],
  } = {}) {
    if (typeof name !== 'string' || name.trim() === '') throw new Error('remote-fanout: provider `name` is required');
    if (transport === undefined || typeof transport.start !== 'function') throw new Error('remote-fanout: a transport with start() is required');
    if (typeof remote.nodeExe !== 'string' || remote.nodeExe === '') throw new Error('remote-fanout: `remoteNodeExe` is required — the target node\'s node interpreter');
    if (typeof remote.dshBin !== 'string' || remote.dshBin === '') throw new Error('remote-fanout: `remoteDshBin` is required — the target node\'s @deepseek-ai/dsh/lib/bin.js');
    this.name = name;
    this.capabilities = NO_START_CAPABILITIES;
    this.inheritsParentContext = false;
    this.transport = transport;
    this.remote = {
      nodeExe: remote.nodeExe,
      dshBin: remote.dshBin,
      profile: remote.profile ?? 'headless',
      dshHome: remote.dshHome,
      cwd: remote.cwd,
      shell: remote.shell === 'posix' ? 'posix' : 'powershell',
    };
    this.timeoutMs = Number.isFinite(timeoutMs) && timeoutMs > 0 ? timeoutMs : undefined;
    this.logger = logger;
    this.taskPreamble = typeof taskPreamble === 'string' ? taskPreamble : '';
    this.verifyMeshHost = verifyMeshHost !== false;
    this.targetHosts = (Array.isArray(targetHosts) ? targetHosts : []).map(String).filter((value) => value !== '');
  }

  /**
   * Establish one one-shot child on the target node. Fulfils only after the ssh
   * client is launched; the returned run's `result` then never rejects.
   */
  async start(request) {
    const task = promptText(request?.prompt);
    if (task === '') throw new Error(`${this.name}: the delegation prompt carries no text`);
    // The seam's rule for a pre-publication cancellation: reject and leave
    // nothing running, rather than publish a run the caller already gave up on.
    if (request?.signal?.aborted) throw new Error(`${this.name}: delegation was cancelled before the remote child started`);
    const childTask = this.taskPreamble === '' ? task : `${this.taskPreamble}\n${task}`;
    const nonce = randomBytes(4).toString('hex');
    const shell = this.remote.shell;
    const build = shell === 'posix' ? buildPosixScript : buildPwshScript;
    const script = build({ ...this.remote, task: childTask, nonce });
    const id = `remote-${randomUUID()}`;

    const controller = new AbortController();
    const parentSignal = request.signal;
    const forwardAbort = () => controller.abort(parentSignal?.reason);
    if (parentSignal) {
      if (parentSignal.aborted) forwardAbort();
      else parentSignal.addEventListener('abort', forwardAbort, { once: true });
    }

    let handle;
    let blocks = [];
    let diagnostic;
    let outcome;
    let parsed = { framed: false, host: undefined, cwd: undefined, answer: '', exitCode: undefined };

    const attempt = async () => {
      handle = this.transport.start({ shell, script, timeoutMs: this.timeoutMs, completeMarker: markers(nonce).exit });
      const onAbort = () => handle.kill('aborted');
      if (controller.signal.aborted) onAbort();
      else controller.signal.addEventListener('abort', onAbort, { once: true });
      try {
        outcome = await handle.done;
      } finally {
        controller.signal.removeEventListener('abort', onAbort);
      }
      parsed = parseFanout(outcome.stdout, nonce);
      const meshHost = this.verifyMeshHost ? extractMeshHost(parsed.answer) : undefined;
      const locationNote = this.#locationNote(parsed.host);
      blocks = [{
        type: 'text',
        text: renderReport({
          provider: this.name,
          transport: this.transport.describe(),
          parsed,
          outcome,
          remote: this.remote,
          meshHost,
          locationNote,
        }),
      }];
      this.logger?.info?.(`${this.name}: run ${id} on "${parsed.host ?? 'unknown'}" mesh-host="${meshHost ?? 'unreported'}" exit=${outcome.exitCode ?? 'none'}${outcome.timedOut ? ' timeout' : ''} in ${outcome.ms} ms`);
      // Cancellation that settled locally wins over whatever the process said:
      // the seam's rule for an out-of-process run.
      if (controller.signal.aborted) return { output: blocks, stopReason: 'aborted' };
      if (outcome.spawnError) {
        diagnostic = `could not launch the ssh transport (${this.transport.describe()}): ${outcome.spawnError}`;
        return { output: blocks, diagnostic, stopReason: 'error' };
      }
      if (outcome.timedOut) {
        diagnostic = `the remote turn did not finish within ${this.timeoutMs ?? 'the configured'} ms and the ssh client was killed`
          + (outcome.stderr.trim() === '' ? '' : `; remote stderr tail: ${outcome.stderr.trim().slice(-900)}`);
        return { output: blocks, diagnostic, stopReason: 'error' };
      }
      if (outcome.exitCode !== 0) {
        diagnostic = `the remote one-shot exited ${outcome.exitCode ?? 'without a code'}${parsed.answer ? '' : ' and produced no final message'}; stderr tail: ${outcome.stderr.trim().slice(-600)}`;
        return { output: blocks, diagnostic, stopReason: 'error' };
      }
      if (!parsed.framed) {
        diagnostic = `the remote process exited 0 but printed no completion frame — the target profile did not run (stderr tail: ${outcome.stderr.trim().slice(-600)})`;
        return { output: blocks, diagnostic, stopReason: 'error' };
      }

      // Proof of location (`71` §2.4). Both checks fail the run loudly.
      if (this.targetHosts.length > 0 && !this.targetHosts.some((host) => sameNode(host, parsed.host))) {
        diagnostic = `the transport reported host "${parsed.host ?? 'unknown'}", which is not one of the configured target hosts for this provider (${this.targetHosts.join(', ')}) — refusing to report work from an unverified node`;
        return { output: blocks, diagnostic, stopReason: 'error' };
      }
      if (this.verifyMeshHost) {
        if (meshHost === undefined) {
          diagnostic = `the child did not begin its report with "${MESH_HOST_LINE} <hostname>" — its location is unproven, so the run is not reported as complete`;
          return { output: blocks, diagnostic, stopReason: 'error' };
        }
        if (parsed.host !== undefined && !sameNode(meshHost, parsed.host)) {
          diagnostic = `location disagreement: the child claims MESH-HOST ${meshHost} but the target shell recorded ${parsed.host}`;
          return { output: blocks, diagnostic, stopReason: 'error' };
        }
      }
      if (parsed.answer === '') {
        diagnostic = 'the remote child finished with an empty final message';
        return { output: blocks, stopReason: 'completed' };
      }
      return { output: blocks, stopReason: 'completed' };
    };

    // Publication boundary. After this resolves the result NEVER rejects: a
    // transport fault is flattened into `stopReason: 'error'` with a diagnostic.
    const result = (async () => {
      try {
        return await attempt();
      } catch (error) {
        if (controller.signal.aborted) return { output: blocks, stopReason: 'aborted' };
        blocks = blocks.length > 0 ? blocks : [{ type: 'text', text: String(error?.message ?? error) }];
        return { output: blocks, diagnostic: limitDiagnostic(error?.message ?? error), stopReason: 'error' };
      }
    })();

    let disposal;
    return {
      id,
      localAgent: undefined,
      result,
      dispose() {
        if (disposal !== undefined) return disposal;
        if (parentSignal) parentSignal.removeEventListener('abort', forwardAbort);
        try {
          handle?.kill('disposed');
        } catch {
          // the ssh client is already gone
        }
        disposal = withGrace(handle?.done ?? Promise.resolve(), 5000).then(() => undefined);
        return disposal;
      },
    };
  }

  /** One line describing whether the recorded host could be checked at all. */
  #locationNote(host) {
    if (this.targetHosts.length === 0) return `not verified against a configured target host (host recorded: ${host ?? 'unknown'})`;
    return this.targetHosts.some((candidate) => sameNode(candidate, host))
      ? `matched configured target host (${this.targetHosts.join(', ')})`
      : 'MISMATCH';
  }
}
