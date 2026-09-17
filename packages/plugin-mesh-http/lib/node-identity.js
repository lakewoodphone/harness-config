/**
 * Who this node is — decided HERE, never taken from the caller.
 *
 * This is the load-bearing half of the mesh's proof of location (`docs/mesh/71-mesh-program.md`
 * §2.4). The dispatcher compares the host the child reported against the node the broker named,
 * and that comparison only means something if the identity came from the machine that ran the
 * work. So the route:
 *
 *   * ignores any `host`, `node`, `meshHost` or `X-Forwarded-Host` the caller sent, and
 *   * answers with a name it derived from its own OS, its own tailnet membership, or its own
 *     explicitly configured `MESH_NODE_NAME`.
 *
 * THREE NAMES, AND WHY ALL THREE ARE REPORTED
 * The fleet's node names are Tailscale DNS labels — `zabz-yoga-1`, not `zabz-yoga` (`72` §2.1:
 * the invariant is `node === fqdn.split(".")[0]`) — while the same machine's `os.hostname()` is
 * `ZABZ-YOGA`. The dispatcher's `MESH-HOST:` check accepts either, because the child reports the
 * shell's own hostname, but a router keyed on one and a proof keyed on the other is exactly how
 * a node gets dispatched into a lookup miss. So all three travel:
 *
 *   host  os.hostname()            — what a child's own `hostname` prints
 *   node  the tailnet DNS label    — the name the broker and the gate use
 *   fqdn  the full tailnet name    — when tailscale can name this machine
 *
 * An absent tailscale CLI is reported as `null`, never guessed from the hostname: a guessed
 * node name would make the broker's arithmetic look authoritative while being wrong.
 */

import { execFileSync } from 'node:child_process';
import os from 'node:os';

/** Strip the trailing dot tailscale writes, and the tailnet domain: `x.y.ts.net.` -> `x`. */
export function labelFromDnsName(dnsName) {
  if (typeof dnsName !== 'string') return null;
  const trimmed = dnsName.trim().replace(/\.$/, '');
  if (trimmed === '') return null;
  const first = trimmed.split('.')[0];
  return first === '' ? null : first;
}

/**
 * Read this node's tailnet name once. Cached for the life of the process: a machine does not
 * change its tailnet DNS name while an engine is running, and a per-request `tailscale status`
 * would put a 60-200 ms subprocess in the path of every dispatch.
 */
export function readTailnet({ timeoutMs = 5000 } = {}) {
  try {
    const raw = execFileSync('tailscale', ['status', '--json'], {
      encoding: 'utf8',
      timeout: timeoutMs,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    const parsed = JSON.parse(raw);
    const fqdn = typeof parsed?.Self?.DNSName === 'string' ? parsed.Self.DNSName.replace(/\.$/, '') : null;
    return {
      fqdn,
      node: labelFromDnsName(fqdn) ?? (typeof parsed?.Self?.HostName === 'string' ? parsed.Self.HostName : null),
      hostName: typeof parsed?.Self?.HostName === 'string' ? parsed.Self.HostName : null,
      error: null,
    };
  } catch (error) {
    return { fqdn: null, node: null, hostName: null, error: `${error?.code ?? error?.message ?? error}` };
  }
}

/**
 * @param {object} [options]
 * @param {string} [options.nodeNameOverride] `MESH_NODE_NAME`, for a node whose tailnet label
 *   differs from what the roster calls it — set explicitly, never inferred.
 * @param {(() => object)} [options.tailnetReader] injectable, for tests.
 */
export function createNodeIdentity({ nodeNameOverride, tailnetReader = () => readTailnet() } = {}) {
  const host = os.hostname();
  let tailnet = null;
  const read = () => {
    if (tailnet === null) tailnet = tailnetReader();
    return tailnet;
  };
  return {
    /** The one name a proof of location should be compared against, and where it came from. */
    node() {
      const override = typeof nodeNameOverride === 'string' && nodeNameOverride.trim() !== '' ? nodeNameOverride.trim() : null;
      if (override !== null) return { node: override, source: 'MESH_NODE_NAME' };
      const t = read();
      if (t.node) return { node: t.node, source: 'tailscale status --json Self.DNSName' };
      return { node: host, source: `os.hostname() (tailscale unavailable: ${t.error})` };
    },
    host() {
      return host;
    },
    fqdn() {
      return read().fqdn;
    },
    /** One object for the response body and for the log line. */
    describe() {
      const chosen = this.node();
      return {
        host,
        node: chosen.node,
        nodeSource: chosen.source,
        fqdn: this.fqdn(),
        platform: process.platform,
      };
    },
  };
}
