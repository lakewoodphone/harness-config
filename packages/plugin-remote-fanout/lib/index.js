/**
 * dsh-plugin-remote-fanout — one agent, running on one node, fanning children
 * out to a different node.
 *
 * WHAT THIS IS
 * A host-plane row (like `dsh-plugin-health`) plus a second model-facing
 * delegation tool. The row registers a `SubagentProvider` on the existing
 * `ctx.subagents` named-provider registry under its own name; the tool row
 * (`@deepseek-ai/dsh-tool-subagent`, `provider: <that name>`, `toolName:
 * subagent_remote`) is what lets a parent agent choose it. The built-in
 * `spawn` provider is untouched, so a parent may delegate locally or remotely
 * and the difference is visible in which tool it calls.
 *
 * WHAT IT DOES NOT DO
 * It does not move work that the parent is *already* doing, it does not choose
 * a node (there is one `target` per plugin row — placement is a separate
 * decision service, see `docs/mesh/20-placement.md` §4), and it does not
 * support continuable children: `prepareContinuable` is absent, so
 * follow-up messages to a remote child are rejected by the seam. One-shot
 * fan-out is what a fleet is.
 *
 * WHY THE CONFIG IS NOT OPTIONAL
 * `target`, `remoteNodeExe` and `remoteDshBin` name the node and the two paths
 * that must exist on it. A profile that mounts this bundle without them fails
 * loudly at boot rather than silently delegating nowhere. The deployment-
 * specific values belong in the *profile's* `cordis.patch.yml` (machine-local),
 * not in this package's patch, because a patch replaces the targeted row's
 * whole config.
 */

import { RemoteOneShotProvider } from './provider.js';
import { createSshTransport } from './ssh-transport.js';

const name = 'remote-fanout';
const inject = ['subagents'];

/**
 * Install the provider.
 *
 * @param config.providerName    registry name (default `remote-ssh`)
 * @param config.target          ssh destination of the worker node (required)
 * @param config.sshExe          ssh client (default `ssh`)
 * @param config.sshArgs         extra ssh argv, e.g. `['-o','BatchMode=yes']`
 * @param config.remoteShell     `powershell` (default) or `posix`
 * @param config.remoteNodeExe   node interpreter path ON THE TARGET (required)
 * @param config.remoteDshBin    `@deepseek-ai/dsh/lib/bin.js` path ON THE TARGET (required)
 * @param config.remoteProfile   DSH profile to boot on the target (default `headless`)
 * @param config.remoteHome      optional DSH_HOME for the child process (default: the target's own home, which is what `71` §2.3 freezes)
 * @param config.remoteCwd       optional working directory on the target
 * @param config.timeoutMs       bound on one remote turn (default 900000)
 * @param config.maxOutputBytes  bound on retained stdout/stderr (default 200000)
 * @param config.targetHosts     hostnames the configured target is allowed to resolve to (`71` §2.4); empty means "recorded but not checked"
 * @param config.verifyMeshHost  require the child's own `MESH-HOST:` line to match the recorded host (default true)
 * @param config.taskPreamble    the instruction prepended to every child task (default: the MESH-HOST instruction)
 */
function apply(ctx, config = {}) {
  const providerName = typeof config.providerName === 'string' && config.providerName !== ''
    ? config.providerName
    : 'remote-ssh';

  const transport = createSshTransport({
    sshExe: config.sshExe,
    sshArgs: config.sshArgs,
    target: config.target,
    timeoutMs: config.timeoutMs,
    maxOutputBytes: config.maxOutputBytes,
  });

  const provider = new RemoteOneShotProvider({
    name: providerName,
    transport,
    remote: {
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
  });

  ctx.subagents.registerProvider(provider);
  ctx.logger?.info?.(
    `remote-fanout: provider "${providerName}" registered → ${transport.describe()} `
    + `(profile ${config.remoteProfile ?? 'headless'}${config.remoteHome ? `, DSH_HOME ${config.remoteHome}` : ''}; `
    + `target hosts ${provider.targetHosts.length > 0 ? provider.targetHosts.join(', ') : 'NOT CHECKED'})`,
  );
}

export { name, inject, apply };
