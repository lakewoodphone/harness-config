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
 * WHERE THE CHILD RUNS IS ASKED FOR, NOT CONFIGURED (`docs/mesh/92-provider-placement.md`)
 * The provider holds a *placer*. Before each child it asks the live placement
 * broker (`POST /place`, over ssh, loopback-only on the authority) which node
 * should take this child, and it dispatches there; when the child settles it
 * releases the lease (`POST /done`). The placer is the ONLY source of a node:
 * this class has no default target, and a broker it cannot reach is a reported
 * `broker-unreachable` failure rather than a fallback. A fixed target still
 * exists as `createFixedPlacer` — an explicit, hand-set, loudly-logged opt-in
 * (`MESH_TARGET_NODE`), never the automatic path.
 *
 * A QUEUED CHILD IS NOT A RUNNING CHILD
 * `POST /place` answers `position > 0` when the mesh has accepted jobs ahead of
 * this one. That placement is surfaced, never swallowed: the ledger records it,
 * the engine log names it, and the child's report carries it. The child WAITS —
 * and while it waits it has not been published to the registry, so no surface
 * can show a waiting agent as a running one, which is the failure mode this
 * whole seam is arranged to avoid. The wait is bounded (`queueWaitMs`) and when
 * it expires the child is dispatched anyway: the broker's own rule is queue,
 * never amputate.
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
 *      the hostnames the PLACED node is allowed to be — this catches an ssh
 *      alias that silently resolves to the wrong machine, and, since
 *      2026-09-17, it is the check that proves the broker's answer was honoured:
 *      the allowed set is the set attached to the node the broker named, not a
 *      static list for one configured target;
 *   2. the child's own `MESH-HOST:` line must equal that recorded host — this
 *      catches a child that did not run where it claims.
 *
 * Either disagreement fails the run with `stopReason: 'error'`. A placement
 * system that cannot prove where work ran is an assertion, not a measurement.
 */

import { randomBytes, randomUUID } from 'node:crypto';

import { createFixedPlacer } from './placement.js';
import {
  CRITICAL_COMMIT_PHYSICAL_PCT,
  HIGH_COMMIT_PHYSICAL_PCT,
  REFUSE_AVAILABLE_FLOOR_BYTES,
  defaultProbeDir,
  defaultSnapshotFile,
  pressureCheckLine,
  pressureLine,
} from './pressure.js';
import {
  buildPosixScript,
  buildPwshScript,
  invocationFor,
  markers,
  parseFanout,
  shouldRetryWithFallback,
} from './remote-script.js';

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

/**
 * The command line the run actually carried, as a reader can check it. This is
 * put in the child's own report because the whole defect was that the report
 * said "ran on node X" while the invocation it used could not have run there.
 */
export function describeInvocation(invocation) {
  if (invocation === undefined || invocation === null) return '(none)';
  return [invocation.command, ...(invocation.argvPrefix ?? []), '--profile', '<profile>', '<task>'].join(' ');
}

/**
 * The interpreter form of the same node facts, for the one-shot retry after an
 * executor could not be launched. `undefined` when the node has no interpreter
 * pair, or when the pair would produce the SAME command as the attempt that just
 * failed (a row whose executor IS its driver path must not be retried with
 * itself).
 */
export function fallbackInvocation(facts, primary) {
  if (facts === undefined || facts === null) return undefined;
  if (typeof facts.driver !== 'string' || facts.driver === '') return undefined;
  if (typeof facts.bin !== 'string' || facts.bin === '') return undefined;
  if (primary !== undefined && primary.command === facts.driver && (primary.argvPrefix ?? []).join(' ') === facts.bin) {
    return undefined;
  }
  return {
    form: 'interpreter',
    command: facts.driver,
    argvPrefix: [facts.bin],
    driver: facts.driver,
    bin: facts.bin,
    credentialEnvFiles: Array.isArray(facts.credentialEnvFiles)
      ? facts.credentialEnvFiles.filter((file) => !String(file).startsWith('!'))
      : [],
    credentialSource: 'the interpreter fallback — it inherits the environment the ssh session carries',
  };
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

/**
 * One line naming where the placement came from and whether the child had to
 * wait for it. This is what makes `position > 0` visible in the parent's own
 * transcript rather than only in a log file.
 */
export function placementNote(placement, wait) {
  if (placement === undefined || placement === null) return undefined;
  const head = placement.source === 'fixed'
    ? `FIXED TARGET — "${placement.node}" from configuration, the broker was NOT consulted`
    : `broker → node "${placement.node}"`;
  const parts = [head];
  if (placement.source !== 'fixed') {
    parts.push(`position ${placement.position}${placement.tier === null ? '' : ` (tier ${placement.tier})`}`);
    if (placement.score !== null && placement.score !== undefined) parts.push(`score ${placement.score}`);
    if (placement.lease !== undefined) parts.push(`lease ${placement.lease}`);
  }
  const note = parts.join(', ');
  if (wait?.waited !== true) return `${note} — started immediately`;
  const seconds = (wait.waitedMs / 1000).toFixed(1);
  return wait.timedOut
    ? `${note} — QUEUED at position ${placement.position} and waited ${seconds} s for a free slot, then dispatched anyway (queue, never amputate)`
    : `${note} — QUEUED at position ${placement.position} and waited ${seconds} s until the broker reported a free slot`;
}

/** The text the parent model sees as the child's result. */
export function renderReport({ provider, transport, parsed, outcome, remote, meshHost, locationNote, placementLine, leaseNote, pressureNote, pressureCheck, invocation }) {
  const head = [
    `${MESH_HOST_LINE} ${meshHost ?? '(not reported)'}`,
    `[${provider}] child ran on node "${parsed.host ?? 'UNKNOWN'}" via ${transport}`,
    ...(placementLine === undefined ? [] : [`placement      = ${placementLine}`]),
    ...(leaseNote === undefined ? [] : [`lease          = ${leaseNote}`]),
    // ── WHY THIS NODE (docs/mesh/109-pressure-routing.md §3.2) ───────────────
    // The line is only present when pressure MOVED the decision, so a healthy
    // machine's report is byte-for-byte what it was; and it is present whenever
    // it did move, so a change of behaviour is never silent.
    ...(pressureNote === undefined ? [] : [`pressure       = ${pressureNote}`]),
    ...(pressureCheck === undefined ? [] : [`pressure check = ${pressureCheck}`]),
    `transport host = ${parsed.host ?? '(not reported)'}  (recorded by the target shell before the agent started)`,
    `transport cwd  = ${parsed.cwd ?? '(not reported)'}`,
    `target profile = ${remote.profile}${remote.dshHome ? ` (DSH_HOME ${remote.dshHome})` : ''}`,
    // WHICH INVOCATION RAN — the fact whose absence let a broken command looked
    // like a broken node for a day (docs/mesh/102-linux-dispatch.md §1).
    ...(invocation === undefined || invocation.command === undefined
      ? []
      : [`invocation     = ${invocation.command} [${invocation.form}${invocation.fallbackFrom === undefined ? '' : `, fell back from the ${invocation.fallbackFrom} form after it could not be launched`}]`]),
    ...(invocation === undefined || invocation.credentialSource === undefined
      ? []
      : [`credential     = ${invocation.credentialSource}`]),
    ...(locationNote === undefined ? [] : [`location check = ${locationNote}`]),
    `exit = ${outcome.exitCode ?? 'none'}${outcome.timedOut ? ' (timed out)' : ''} in ${outcome.ms} ms${outcome.markerSettled ? ' (ssh client terminated after the completion frame)' : ''}`,
  ];
  const body = parsed.framed
    ? parsed.answer
    : `(the child produced no framed output; raw stdout follows)\n${outcome.stdout}`;
  return `${head.join('\n')}\n--- child final message ---\n${body}`;
}

/** The seam's rule for a provider diagnostic, reused for the release note. */
function leaseNoteFor(placement, release) {
  if (placement?.lease === undefined || placement?.lease === null || placement.lease === '') {
    return undefined;
  }
  if (release?.released === true) {
    return `${placement.lease} released to the broker with POST /done at settle (ok=${release.ok === false ? 'false' : 'true'})`;
  }
  if (release?.skipped !== undefined && release?.skipped !== null) {
    return `${placement.lease} not released: ${release.skipped}`;
  }
  return `${placement.lease} COULD NOT be released (${release?.code ?? 'broker-error'}: ${release?.error ?? 'unknown'}) — the broker reclaims it at its TTL`;
}

/** Put the release note in the header of a report, above the child's own message. */
function withLeaseNote(text, note) {
  if (note === undefined) return text;
  const marker = '\n--- child final message ---\n';
  const at = text.indexOf(marker);
  return at < 0 ? `${text}\nlease          = ${note}` : `${text.slice(0, at)}\nlease          = ${note}${text.slice(at)}`;
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
    placer,
    ledger,
  } = {}) {
    if (typeof name !== 'string' || name.trim() === '') throw new Error('remote-fanout: provider `name` is required');
    // WHAT IS REQUIRED OF A FIXED TARGET, AND WHY IT IS NOT TWO PATHS ANY MORE.
    // When `remote` is supplied at all it must carry a RESOLVABLE invocation:
    // either an executor (`remoteCommand`, the node's own `dsh` wrapper, which is
    // what sources the worker credential) or BOTH halves of the interpreter pair.
    // Naming one half of a pair is the config shape that produced a child which
    // died with `not found` on the target (measured 2026-09-17), so it is refused
    // here, at boot, where it can still be read. In broker mode no `remote` is
    // supplied and the placed node's own facts are used instead.
    if (remote !== undefined && Object.keys(remote).length > 0 && invocationFor(remote) === undefined) {
      throw new Error('remote-fanout: a fixed target needs an invocation — `remoteCommand` (an executor on the target\'s PATH, e.g. the mesh `dsh` wrapper) or BOTH `remoteNodeExe` and `remoteDshBin`');
    }
    if (placer === undefined && transport === undefined) {
      throw new Error('remote-fanout: a transport with start() is required');
    }
    if (placer === undefined) {
      if (typeof transport.start !== 'function') throw new Error('remote-fanout: a transport with start() is required');
      if (invocationFor(remote) === undefined) {
        throw new Error('remote-fanout: a fixed target needs an invocation — `remoteCommand` (an executor on the target\'s PATH, e.g. the mesh `dsh` wrapper) or BOTH `remoteNodeExe` and `remoteDshBin`');
      }
    }
    if (placer !== undefined && typeof placer.acquire !== 'function') throw new Error('remote-fanout: a `placer` needs an acquire() method');
    this.name = name;
    this.capabilities = NO_START_CAPABILITIES;
    this.inheritsParentContext = false;
    this.transport = transport;
    this.ledger = ledger;
    this.remote = {
      command: remote.command,
      credentialEnvFiles: Array.isArray(remote.credentialEnvFiles) ? remote.credentialEnvFiles : undefined,
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
    this.placer = placer ?? createFixedPlacer({ transport, remote: this.remote, targetHosts: this.targetHosts });
    /** Which kind of placer this provider runs on — `broker` or `fixed`. Reported at registration. */
    this.placementKind = this.placer.kind ?? 'unknown';
    /** How many children this provider has placed, queued and released — read by the proof scripts. */
    this.counters = { placed: 0, queued: 0, released: 0, placementFailed: 0 };
  }

  /** One line for the boot log: where children will go, and whether that is asked for. */
  describePlacement() {
    const line = this.placer.explain?.() ?? this.placer.describe?.() ?? 'unknown placement';
    // THE BOOT LINE NAMES THE PRESSURE GATE. A reader of the engine log must be
    // able to answer "was the local machine looked at at all?" without reading
    // this package's source (docs/mesh/109-pressure-routing.md §3.2).
    if (this.placer.kind !== 'broker') {
      return `${line}; local pressure is NOT consulted on a fixed target — this mode does not choose a node, a human did`;
    }
    return `${line}; local pressure IS consulted before every placement: `
      + `>= ${Math.round(HIGH_COMMIT_PHYSICAL_PCT * 100)} % of physical committed routes the child away from this machine, `
      + `>= ${Math.round(CRITICAL_COMMIT_PHYSICAL_PCT * 100)} % with less than ${Math.round(REFUSE_AVAILABLE_FLOOR_BYTES / 1048576)} MiB physical available refuses a local child outright `
      + `(snapshot ${defaultSnapshotFile()}, fallback probe ${defaultProbeDir()})`;
  }

  /** Write one placement/run event to the ledger and the log. Never throws. */
  #record(id, patch) {
    try {
      return this.ledger?.record(id, patch) ?? { ok: false, file: undefined };
    } catch (error) {
      this.logger?.warn?.(`remote-fanout: the placement ledger rejected a record for ${id}: ${String(error?.message ?? error)}`);
      return { ok: false, file: undefined };
    }
  }

  /**
   * Establish one one-shot child on the node the broker names. Fulfils only
   * after the ssh client is launched; the returned run's `result` then never
   * rejects.
   *
   * A placement that cannot be made REJECTS `start()`: nothing has been started,
   * so the honest shape is a pre-publication infrastructure failure the caller
   * sees — not a child that reports an error it never ran into.
   */
  async start(request) {
    const task = promptText(request?.prompt);
    if (task === '') throw new Error(`${this.name}: the delegation prompt carries no text`);
    // The seam's rule for a pre-publication cancellation: reject and leave
    // nothing running, rather than publish a run the caller already gave up on.
    if (request?.signal?.aborted) throw new Error(`${this.name}: delegation was cancelled before the remote child started`);
    const childTask = this.taskPreamble === '' ? task : `${this.taskPreamble}\n${task}`;
    const nonce = randomBytes(4).toString('hex');
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

    // ── PLACEMENT ────────────────────────────────────────────────────────────
    // Before the script is built, because the script carries the placed node's
    // OWN paths, and before publication, because publishing a run that has not
    // started is the failure mode.
    let placement;
    try {
      placement = await this.placer.acquire({ id, childIndex: this.counters.placed });
    } catch (error) {
      const code = error?.code ?? 'placement-failed';
      this.counters.placementFailed += 1;
      this.#record(id, {
        id,
        state: 'placement-failed',
        code,
        error: String(error?.message ?? error),
        failedAt: new Date().toISOString(),
      });
      this.logger?.warn?.(`remote-fanout: child ${id} could NOT be placed — ${code}: ${String(error?.message ?? error)}`);
      throw new Error(`${this.name}: ${code}: ${String(error?.message ?? error)}`);
    }
    this.counters.placed += 1;
    const placementHosts = placement.hosts?.length > 0 ? placement.hosts : this.targetHosts;
    const remoteFacts = placement.facts;

    // ── THE QUEUE ────────────────────────────────────────────────────────────
    const wait = await this.placer.waitForSlot(placement, {
      signal: controller.signal,
      onWait: (event) => {
        this.#record(id, { id, queueEvents: [...(this.ledger?.get?.(id)?.queueEvents ?? []), event] });
        if (event.phase === 'queued') {
          this.logger?.info?.(`remote-fanout: child ${id} is QUEUED at position ${event.position} on "${placement.node}" (lease ${placement.lease}) — it has not started, and it is not published as a running agent`);
        } else if (event.phase === 'queued-poll') {
          this.logger?.info?.(`remote-fanout: child ${id} still queued on "${placement.node}" — ${event.error ? `broker read failed (${event.error})` : `freeSlots ${event.freeSlots} after ${event.waitedMs} ms`}`);
        } else {
          this.logger?.info?.(`remote-fanout: child ${id} ${event.phase} on "${placement.node}" after ${event.waitedMs} ms — ${event.note}`);
        }
      },
    });
    // The wait result is the authoritative signal — a placer that reports it
    // waited is counted once, however it chose to announce the wait.
    if (wait.waited === true) this.counters.queued += 1;
    this.#record(id, {
      id,
      state: 'dispatching',
      waitedMs: wait.waitedMs,
      queueTimedOut: wait.timedOut === true,
      queueStartedAt: wait.freedAt,
      dispatchedAt: new Date().toISOString(),
    });

    const shell = remoteFacts.shell === 'posix' ? 'posix' : 'powershell';
    const transport = this.placer.transportFor(placement);

    /**
     * THE INVOCATION IS DECIDED HERE, PER RUN, FROM THE PLACED NODE'S OWN FACTS.
     *
     * `dsh --profile headless <task>` when the node has an executor — the mesh
     * wrapper, which resolves the interpreter AND sources the worker credential
     * file — and `node <bin.js> --profile headless <task>` only when it has no
     * executor. See `nodes.js` for the measurements behind that order and
     * `docs/mesh/102-linux-dispatch.md` for the per-node table.
     */
    let invocationContext = {};
    const runOnce = async (spec) => {
      const script = (shell === 'posix' ? buildPosixScript : buildPwshScript)({ ...spec, task: childTask, nonce });
      // `handle` is assigned SYNCHRONOUSLY, before the first await: `dispose()`
      // may be called before the transport settles, and a run the caller has
      // disposed must not be left running because the handle was still undefined.
      const started = transport.start({ shell, script, timeoutMs: this.timeoutMs, completeMarker: markers(nonce).exit });
      handle = started;
      const onAbort = () => started.kill('aborted');
      if (controller.signal.aborted) onAbort();
      else controller.signal.addEventListener('abort', onAbort, { once: true });
      let outcome;
      try {
        outcome = await started.done;
      } finally {
        controller.signal.removeEventListener('abort', onAbort);
      }
      return { handle: started, outcome, script, parsed: parseFanout(outcome.stdout, nonce) };
    };

    const attempt = async () => {
      const primary = invocationFor(remoteFacts);
      if (primary === undefined) {
        throw new Error(`remote-fanout: no invocation is recorded for node "${placement.node}" — it needs either an executor (\`command\`) or both a \`driver\` and a \`bin\``);
      }
      let run = await runOnce({ invocation: primary });
      invocationContext = { command: describeInvocation(primary), form: primary.form, credentialSource: primary.credentialSource, attempts: [primary.form] };
      outcome = run.outcome;
      parsed = run.parsed;
      this.logger?.info?.(`${this.name}: ${id} invoked on "${placement.node}" as ${invocationContext.command} (${primary.form}: ${primary.credentialSource})`);

      // THE FALLBACK, AND WHEN IT IS ALLOWED TO RUN. A wrapper that is present
      // is right, but a wrapper that has been removed — or a node provisioned
      // differently from the way its row was measured — must degrade to the
      // interpreter pair rather than kill the child. The retry is narrow: only
      // "this invocation could not be launched" qualifies (`shouldRetryWithFallback`),
      // so a wrong answer, a credential error or a timeout is never silently
      // re-run. The second run's evidence replaces nothing: both are reported.
      const fallback = fallbackInvocation(remoteFacts, primary);
      if (fallback !== undefined && shouldRetryWithFallback(outcome, parsed)) {
        this.logger?.warn?.(
          `${this.name}: ${id} could not launch ${invocationContext.command} on "${placement.node}" `
          + `(exit ${outcome.exitCode ?? 'none'}${outcome.spawnError ? `, ${outcome.spawnError}` : ''}) — retrying once with the interpreter fallback ${describeInvocation(fallback)}`,
        );
        run = await runOnce({ invocation: fallback });
        invocationContext.command = describeInvocation(fallback);
        invocationContext.form = fallback.form;
        invocationContext.credentialSource = fallback.credentialSource;
        invocationContext.fallbackFrom = primary.form;
        invocationContext.attempts.push(fallback.form);
        outcome = run.outcome;
        parsed = run.parsed;
      }
      handle = run.handle;

      const meshHost = this.verifyMeshHost ? extractMeshHost(parsed.answer) : undefined;      const locationNote = this.#locationNote(parsed.host, placement, placementHosts);
      blocks = [{
        type: 'text',
        text: renderReport({
          provider: this.name,
          transport: transport.describe(),
          parsed,
          outcome,
          remote: remoteFacts,
          meshHost,
          locationNote,
          placementLine: placementNote(placement, wait),
          pressureNote: pressureLine(placement, parsed.host),
          pressureCheck: pressureCheckLine(placement?.pressure, placement?.pressureDecision),
          invocation: invocationContext,
        }),
      }];
      this.logger?.info?.(`${this.name}: run ${id} on "${parsed.host ?? 'unknown'}" (placed on "${placement.node}") mesh-host="${meshHost ?? 'unreported'}" exit=${outcome.exitCode ?? 'none'}${outcome.timedOut ? ' timeout' : ''} in ${outcome.ms} ms`);
      // Cancellation that settled locally wins over whatever the process said:
      // the seam's rule for an out-of-process run.
      if (controller.signal.aborted) return { output: blocks, stopReason: 'aborted' };
      if (outcome.spawnError) {
        diagnostic = `could not launch the ssh transport (${transport.describe()}): ${outcome.spawnError}`;
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

      // Proof of location (`71` §2.4), now against the node the BROKER named.
      // Both checks fail the run loudly.
      if (placementHosts.length > 0 && !placementHosts.some((host) => sameNode(host, parsed.host))) {
        diagnostic = `the transport reported host "${parsed.host ?? 'unknown'}", which is not one of the hostnames the placement named ("${placement.node}" may be ${placementHosts.join(', ')}) — refusing to report work from a node the broker did not name`;
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
    // The lease is released on EVERY path — a completed child, a failed child, an
    // aborted child — because a reservation nobody gives back is a slot the mesh
    // has lost until its TTL. The release is recorded, and its own failure never
    // changes the child's outcome.
    const result = (async () => {
      let settled;
      try {
        settled = await attempt();
      } catch (error) {
        if (controller.signal.aborted) settled = { output: blocks, stopReason: 'aborted' };
        else {
          blocks = blocks.length > 0 ? blocks : [{ type: 'text', text: String(error?.message ?? error) }];
          settled = { output: blocks, diagnostic: limitDiagnostic(error?.message ?? error), stopReason: 'error' };
        }
      }
      const release = await this.placer.release(placement, settled.stopReason === 'completed');
      if (release?.released === true) this.counters.released += 1;
      if (blocks.length > 0 && typeof blocks[0].text === 'string') {
        blocks[0].text = withLeaseNote(blocks[0].text, leaseNoteFor(placement, release));
      }
      this.#record(id, {
        id,
        state: 'settled',
        stopReason: settled.stopReason,
        settledAt: new Date().toISOString(),
        leaseReleased: release?.released === true,
        leaseReleaseSkipped: release?.skipped ?? null,
        leaseReleaseError: release?.ok === false ? (release.error ?? 'unknown') : null,
        reportedHost: parsed.host ?? null,
        meshHost: this.verifyMeshHost ? extractMeshHost(parsed.answer) ?? null : null,
        invocation: invocationContext.command ?? null,
        invocationForm: invocationContext.form ?? null,
        invocationAttempts: invocationContext.attempts ?? null,
        exitCode: outcome?.exitCode ?? null,
        ms: outcome?.ms ?? null,
      });
      return settled;
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

  /**
   * One line describing whether the recorded host could be checked at all, and
   * against which node's allowed names it was checked.
   */
  #locationNote(host, placement, hosts) {
    const named = placement?.source === 'fixed' ? 'the configured fixed target' : `the node the broker named (${placement?.node ?? 'unknown'})`;
    if (hosts.length === 0) return `not verified against a host list (host recorded: ${host ?? 'unknown'}; ${named})`;
    return hosts.some((candidate) => sameNode(candidate, host))
      ? `matched ${named} — ${hosts.join(', ')}`
      : 'MISMATCH';
  }
}
