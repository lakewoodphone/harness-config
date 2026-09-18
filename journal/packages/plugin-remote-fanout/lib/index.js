/**
 * dsh-plugin-remote-fanout — one agent, running on one node, fanning children
 * out to whichever node the mesh says should take them.
 *
 * WHAT THIS IS
 * A host-plane row (like `dsh-plugin-health`) plus a second model-facing
 * delegation tool. The row registers a `SubagentProvider` on the existing
 * `ctx.subagents` named-provider registry under its own name; the tool row
 * (`@deepseek-ai/dsh-tool-subagent`, `provider: <that name>`, `toolName:
 * `subagent_remote`) is what lets a parent agent choose it. The built-in
 * `spawn` provider is untouched, so a parent may delegate locally or remotely
 * and the difference is visible in which tool it calls.
 *
 * WHERE THE CHILD RUNS
 * The provider asks the placement broker (`POST /place`), one placement per
 * child, and dispatches to the node it names (`docs/mesh/92-provider-placement.md`).
 * `placement: 'fixed'` is the explicit, hand-set, loudly-logged opt-in that
 * restores the old one-node behaviour; it is never chosen automatically, and a
 * broker that cannot be reached is a reported failure rather than a default.
 *
 * WHAT IT DOES NOT DO
 * It does not move work that the parent is *already* doing, it does not invent a
 * placement policy of its own (the broker ranks, this asks, per child), and it
 * does not support continuable children: `prepareContinuable` is absent, so
 * follow-up messages to a remote child are rejected by the seam. One-shot
 * fan-out is what a fleet is.
 *
 * WHY THE CONFIG IS NOT OPTIONAL
 * In `fixed` mode `target`, `remoteNodeExe` and `remoteDshBin` name the node and
 * the two paths that must exist on it, and a profile that mounts this bundle
 * without them fails loudly at boot rather than silently delegating nowhere. In
 * `broker` mode the per-node paths come from `lib/nodes.js`, keyed by the name
 * the broker uses, because the parent's own platform is not a fact about the
 * target (measured 2026-09-16: a Windows parent dispatching to the Linux
 * authority with a locally-inferred shell produced
 * `bash: line 1: powershell: command not found`, exit 127).
 */

import { createBrokerClient } from './broker-client.js';
import { createPlacementLedger, createNodePlacer } from './placement.js';
import { RemoteOneShotProvider } from './provider.js';
import { createSshTransport } from './ssh-transport.js';

const name = 'remote-fanout';
const inject = ['subagents'];

/**
 * Which placement a row means, decided in ONE place and in the package rather
 * than in a deployment file, because the rule is about behaviour and not about
 * a machine:
 *
 *   `placement: 'fixed'`  an explicit opt-in, in the row
 *   `placement: 'broker'` an explicit choice, in the row
 *   `MESH_PLACEMENT`      the same two values, from the engine's environment
 *   `MESH_TARGET_NODE` set BY HAND → fixed, and it is logged as such
 *   nothing at all        → **broker**
 *
 * The last line is the whole point: the automatic path asks the broker, and the
 * one-node behaviour exists only when a human asked for it. A row that names a
 * `target` does NOT select fixed mode — that value is the fallback's fallback,
 * and reading it as a mode switch is what made one node look like a mesh.
 */
export function resolvePlacementMode(config = {}, env = process.env) {
  const configured = config.placement ?? env.MESH_PLACEMENT;
  if (configured === 'fixed') return 'fixed';
  if (configured === 'broker') return 'broker';
  if (typeof env.MESH_TARGET_NODE === 'string' && env.MESH_TARGET_NODE.trim() !== '') return 'fixed';
  return 'broker';
}

/**
 * Install the provider.
 *
 * @param config.providerName    registry name (default `remote-ssh`)
 * @param config.placement       `broker` (default) or `fixed` — `fixed` restores the one-node behaviour and says so
 * @param config.target          ssh destination of the worker node (REQUIRED in `fixed` mode; ignored in `broker` mode)
 * @param config.sshExe          ssh client (default `ssh`)
 * @param config.sshArgs         extra ssh argv, e.g. `['-o','BatchMode=yes']`
 * @param config.remoteShell     `powershell` (default) or `posix` — fixed mode only; broker mode takes the shell from the placed node
 * @param config.remoteNodeExe   node interpreter path ON THE TARGET (fixed mode only)
 * @param config.remoteDshBin    `@deepseek-ai/dsh/lib/bin.js` path ON THE TARGET (fixed mode only)
 * @param config.remoteProfile   DSH profile to boot on the target (default `headless`)
 * @param config.remoteHome      optional DSH_HOME for the child process (default: the target's own home, which is what `71` §2.3 freezes)
 * @param config.remoteCwd       optional working directory on the target (fixed mode only)
 * @param config.timeoutMs       bound on one remote turn (default 900000)
 * @param config.maxOutputBytes  bound on retained stdout/stderr (default 200000)
 * @param config.targetHosts     hostnames the target may resolve to (`71` §2.4); in broker mode the placed node's own list is used
 * @param config.verifyMeshHost  require the child's own `MESH-HOST:` line to match the recorded host (default true)
 * @param config.taskPreamble    the instruction prepended to every child task (default: the MESH-HOST instruction)
 * @param config.brokerSsh       ssh destination of the machine the broker runs on (default `secratary-ts`)
 * @param config.brokerUrl       the broker's loopback base URL (default `http://localhost:3091`)
 * @param config.brokerSshExe    ssh client used for broker calls (default: `sshExe`)
 * @param config.brokerTimeoutMs bound on one broker call (default 30000)
 * @param config.queueWaitMs     how long a queued child waits for a free slot before being dispatched anyway (default 120000)
 * @param config.queuePollMs     how often a queued child re-reads `GET /nodes` (default 5000)
 * @param config.prefer          `home` | `office` | null — passed to the broker, which treats it as a tie-breaker only
 * @param config.exclude         node names to tell the broker to avoid (a caller hint; it yields to never-refuse)
 */
function apply(ctx, config = {}) {
  const providerName = typeof config.providerName === 'string' && config.providerName !== ''
    ? config.providerName
    : 'remote-ssh';
  const mode = resolvePlacementMode(config);

  const ledger = createPlacementLedger({ logger: ctx.logger });

  let placer;
  if (mode === 'fixed') {
    const transport = createSshTransport({
      sshExe: config.sshExe,
      sshArgs: config.sshArgs,
      target: config.target,
      timeoutMs: config.timeoutMs,
      maxOutputBytes: config.maxOutputBytes,
    });
    ctx.logger?.warn?.(
      `remote-fanout: FIXED-TARGET mode is on — every child goes to "${config.target}" through ${transport.describe()} and the placement broker is NOT consulted. `
      + 'This is the opt-in fallback (MESH_TARGET_NODE / placement: fixed), not the default.',
    );
    const provider = new RemoteOneShotProvider({
      name: providerName,
      transport,
      remote: {
        command: config.remoteCommand,
        credentialEnvFiles: config.remoteCredentialEnvFiles,
        nodeExe: config.remoteNodeExe,
        dshBin: config.remoteDshBin,
        profile: config.remoteProfile,
        dshHome: config.remoteHome,
        cwd: config.remoteCwd,
        shell: config.remoteShell,
      },
      timeoutMs: config.timeoutMs,
      logger: ctx.logger,
      taskPreamble: config.taskPreamble,
      verifyMeshHost: config.verifyMeshHost,
      targetHosts: config.targetHosts,
      ledger,
    });
    placer = provider.placer;
    ctx.subagents.registerProvider(provider);
    ctx.logger?.info?.(
      `remote-fanout: provider "${providerName}" registered in FIXED-TARGET mode → ${transport.describe()} `
      + `(profile ${config.remoteProfile ?? 'headless'}${config.remoteHome ? `, DSH_HOME ${config.remoteHome}` : ''}; `
      + `target hosts ${provider.targetHosts.length > 0 ? provider.targetHosts.join(', ') : 'NOT CHECKED'})`,
    );
    return;
  }

  const broker = createBrokerClient({
    sshExe: config.brokerSshExe ?? config.sshExe,
    sshArgs: config.brokerSshArgs,
    sshTarget: config.brokerSsh,
    url: config.brokerUrl,
    timeoutMs: config.brokerTimeoutMs,
    logger: ctx.logger,
  });
  placer = createNodePlacer({
    broker,
    logger: ctx.logger,
    ledger,
    remoteProfile: config.remoteProfile,
    remoteHome: config.remoteHome,
    timeoutMs: config.timeoutMs,
    maxOutputBytes: config.maxOutputBytes,
    sshExe: config.sshExe,
    sshArgs: config.sshArgs,
    queueWaitMs: config.queueWaitMs,
    queuePollMs: config.queuePollMs,
    prefer: config.prefer ?? null,
    exclude: Array.isArray(config.exclude) ? config.exclude : [],
  });

  const provider = new RemoteOneShotProvider({
    name: providerName,
    placer,
    timeoutMs: config.timeoutMs,
    logger: ctx.logger,
    taskPreamble: config.taskPreamble,
    verifyMeshHost: config.verifyMeshHost,
    targetHosts: config.targetHosts,
    ledger,
  });

  ctx.subagents.registerProvider(provider);
  ctx.logger?.info?.(
    `remote-fanout: provider "${providerName}" registered in BROKER mode → ${placer.describe()} `
    + `(one placement per child; profile ${config.remoteProfile ?? 'headless'}${config.remoteHome ? `, DSH_HOME ${config.remoteHome}` : ''}; `
    + `queue wait ${config.queueWaitMs ?? 120000} ms; ledger ${ledger.dir})`,
  );
}

export { name, inject, apply };
