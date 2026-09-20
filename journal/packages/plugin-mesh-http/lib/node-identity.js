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
 *
 * ---------------------------------------------------------------------------
 * TWO MEASURED DEFECTS FIXED HERE (2026-09-17, `docs/mesh/93-transport-concurrency.md` §5)
 *
 * 1. A DEGRADED READ WAS CACHED FOR THE LIFE OF THE PROCESS.
 *    `readTailnet()` was memoised on first call and never re-read. On ZABZ-YOGA, engine pid 4880
 *    started at 08:51:07 and `tailscale-ipn` started at 08:51:59 — 52 seconds LATER. The engine's
 *    boot read therefore saw `Self.DNSName: ""` (tailscaled was up, the netmap was not complete),
 *    and because a read that *succeeds* with an empty DNSName is indistinguishable from a good one
 *    as far as the cache was concerned, the engine reported
 *    `node: "zabz-yoga"`, `fqdn: ""` — while stating `nodeSource: "tailscale status --json
 *    Self.DNSName"`, a source that had not produced that value. A fresh process on the same
 *    machine, reading the same file, returned `zabz-yoga-1.tail93e6e6.ts.net` at 13:06Z.
 *    So: a GOOD read is still cached for the process life (a tailnet name does not change under a
 *    running engine), and a DEGRADED read is not — it is retried, rate-limited, until it heals.
 *
 * 2. THE REPORTED SOURCE NAMED A FIELD THAT HAD NOT SUPPLIED THE VALUE.
 *    `node` fell back to `Self.HostName` while `nodeSource` still said `Self.DNSName`. That is the
 *    failure class this whole program exists to stop: a field that names its provenance and lies.
 *    `nodeSource` is now one of exactly three literals, and it is the one that produced `node`.
 *
 * WHAT IS DELIBERATELY *NOT* DONE: `MagicDNSSuffix` IS NOT USED TO CONSTRUCT A NAME.
 * `tailscale status --json` carries `MagicDNSSuffix` (`tail93e6e6.ts.net`, measured 2026-09-17),
 * and `Self.HostName` (`zabz-yoga`), so `"<HostName>.<MagicDNSSuffix>"` looks like a cheap way to
 * fill in a missing DNSName. It is WRONG on this fleet: that machine's real label is
 * `zabz-yoga-1`, not `zabz-yoga`. Constructing the name would produce a plausible, well-formed and
 * incorrect node identity — the exact hazard `71` §2.6 records for `-Exclude "zabz-yoga"`. A name
 * that cannot be read is reported as absent (`fqdn: null`, `identityDegraded: true`) so the broker
 * can refuse to place work on it, not guessed into existence.
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
 * One place where a tailnet reading becomes a name, so the contract invariant `node ===
 * fqdn.split(".")[0]` (`72` §2.1) holds no matter what shape a reader returned. An empty or
 * whitespace `fqdn` is `null`, and the label is always DERIVED from the fqdn rather than trusted
 * from the reading — a `node` field that disagreed with its own fqdn is exactly the class of
 * defect this file was rewritten to remove.
 */
export function normalizeTailnet(raw) {
  const input = raw ?? {};
  const trimmed = typeof input.fqdn === 'string' ? input.fqdn.trim().replace(/\.$/, '') : null;
  const fqdn = trimmed === null || trimmed === '' ? null : trimmed;
  return {
    fqdn,
    node: labelFromDnsName(fqdn),
    hostName: typeof input.hostName === 'string' && input.hostName.trim() !== '' ? input.hostName.trim() : null,
    magicDnsSuffix: typeof input.magicDnsSuffix === 'string' ? input.magicDnsSuffix : null,
    emptyDnsName: fqdn === null && typeof input.hostName === 'string' && input.hostName.trim() !== '',
    error: input.error ?? null,
  };
}

/**
 * Read this node's tailnet name once. Pure with respect to its input, so a test can drive it.
 *
 * `emptyDnsName` is the distinction that defect (1) above turns on: tailscale answered, and it
 * answered a `Self` with no usable `DNSName`. That is a DEGRADED reading, not a good one, and the
 * caller must be able to tell.
 */
export function readTailnet({ timeoutMs = 5000, exec = execFileSync } = {}) {
  try {
    const raw = exec('tailscale', ['status', '--json'], {
      encoding: 'utf8',
      timeout: timeoutMs,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    const parsed = JSON.parse(raw);
    return normalizeTailnet({
      fqdn: typeof parsed?.Self?.DNSName === 'string' ? parsed.Self.DNSName : null,
      hostName: typeof parsed?.Self?.HostName === 'string' ? parsed.Self.HostName : null,
      magicDnsSuffix: typeof parsed?.MagicDNSSuffix === 'string' ? parsed.MagicDNSSuffix : null,
      error: null,
    });
  } catch (error) {
    return normalizeTailnet({ error: `${error?.code ?? error?.message ?? error}` });
  }
}

/** The three literals `nodeSource` may ever be. A fourth would be a field naming a source again. */
export const NODE_SOURCES = Object.freeze({
  override: 'MESH_NODE_NAME',
  tailscale: 'tailscale status --json Self.DNSName',
  hostname: 'os.hostname()',
});

/**
 * @param {object} [options]
 * @param {string} [options.nodeNameOverride] `MESH_NODE_NAME`, for a node whose tailnet label
 *   differs from what the roster calls it — set explicitly, never inferred.
 * @param {(() => object)} [options.tailnetReader] injectable, for tests.
 * @param {number} [options.degradedRetryMs] how often a DEGRADED tailnet reading is retried.
 *   A good reading is cached for the life of the process; a degraded one is not, because caching
 *   it is defect (1). 15 s bounds the cost at four `tailscale status` subprocesses a minute on a
 *   node that genuinely has no tailscale, and heals a node whose tailscaled was late to start.
 * @param {() => number} [options.nowMs] injectable clock, for tests.
 */
export function createNodeIdentity({
  nodeNameOverride,
  tailnetReader = () => readTailnet(),
  degradedRetryMs = 15000,
  nowMs = () => Date.now(),
} = {}) {
  const host = os.hostname();
  const override = typeof nodeNameOverride === 'string' && nodeNameOverride.trim() !== ''
    ? nodeNameOverride.trim()
    : null;
  let cache = null;
  let readAtMs = 0;
  let reads = 0;

  const read = () => {
    const now = nowMs();
    if (cache !== null) {
      if (cache.fqdn !== null) return cache;                       // good: cached for the process
      if (now - readAtMs < degradedRetryMs) return cache;          // degraded: rate-limited retry
    }
    cache = normalizeTailnet(tailnetReader());
    readAtMs = now;
    reads += 1;
    return cache;
  };

  return {
    /** The one name a proof of location should be compared against, and where it came from. */
    node() {
      if (override !== null) return { node: override, source: NODE_SOURCES.override };
      const t = read();
      if (t.node) return { node: t.node, source: NODE_SOURCES.tailscale };
      return { node: host, source: NODE_SOURCES.hostname };
    },
    host() {
      return host;
    },
    fqdn() {
      return read().fqdn;
    },
    /** The raw reading, for a CLI that wants to explain itself. Never a name, only a source. */
    tailnetState() {
      const t = read();
      return { ...t, reads };
    },
    /**
     * One object for the response body and for the log line.
     *
     * `identityDegraded` is the honest half of the fix: a node whose tailnet name could not be read
     * still SERVES (refusing would take a node with no tailscale CLI out of the mesh entirely), but
     * it says so, and says why, so the dispatcher can decline to place work on a name it cannot
     * corroborate. `node === fqdn.split(".")[0]` holds by construction whenever `fqdn` is present.
     */
    describe() {
      const chosen = this.node();
      const t = read();
      const fqdn = t.fqdn ?? null;
      let identityDegraded = false;
      let identityReason = null;
      if (override !== null) {
        const label = labelFromDnsName(fqdn);
        if (label !== null && label !== override) {
          identityDegraded = true;
          identityReason = `MESH_NODE_NAME "${override}" disagrees with this machine's tailnet label "${label}"`;
        }
      } else if (fqdn === null) {
        identityDegraded = true;
        identityReason = t.error !== null
          ? `tailscale could not be read (${t.error}); node falls back to os.hostname() "${host}", which may not be this node's roster label`
          : `tailscale reported no Self.DNSName (${t.emptyDnsName ? 'netmap not complete' : 'field absent'}); node falls back to os.hostname() "${host}", which may not be this node's roster label`;
      }
      return {
        host,
        node: chosen.node,
        nodeSource: chosen.source,
        fqdn,
        fqdnSource: fqdn === null ? null : NODE_SOURCES.tailscale,
        identityDegraded,
        identityReason,
        platform: process.platform,
      };
    },
  };
}
