/**
 * The roster loader.
 *
 * A node roster is configuration, and it is the only thing the broker reads from disk. It
 * is validated at startup and the process FAILS LOUDLY on a bad roster - because "no node
 * to place on" is the one condition under which the never-refuse rule has nothing honest to
 * say, and the place to discover that is at boot, not inside a placement decision.
 *
 * THE NAMING INVARIANT (§2.1, corrected 2026-09-16 23:31Z)
 * A node's `node` is its **Tailscale DNS label** - `Self.DNSName` minus the domain - and
 * `mesh-capacity-probe.ps1` enforces `node == fqdn.split(".")[0]` on every node. It is NOT
 * the host name and NOT the ssh alias: measured on 2026-09-16, the laptop's
 * `Self.HostName` is `zabz-yoga` while its `Self.DNSName` (the name the gate answers under
 * and the only name `mesh-health.ps1` can resolve) is `zabz-yoga-1`, and
 * `zabz-yoga.tail93e6e6.ts.net` does not resolve at all; the Linux box is
 * `zabz-tech-linux`, not `linux-pc`. A roster keyed on the host name reads a node it will
 * never find, and the failure is a mesh that works with one node quietly absent - the same
 * class of bug as the `accepts.fleet` change that made `zabz-tech-linux` look
 * fleet-incapable. So this loader refuses such a roster at boot, with the reason.
 */

import { readFileSync } from 'node:fs';

export const DEFAULT_CACHE_TTL_MS = 15_000;
export const DEFAULT_READ_TIMEOUT_MS = 1_500;
export const DEFAULT_LEASE_TTL_MS = 900_000;

const positiveNumber = (value, fallback) => (Number.isFinite(value) && value > 0 ? value : fallback);

/**
 * The default ceiling on how many children one node may carry at once.
 *
 * FOUR, and the number is chosen from a measurement rather than taste: on 2026-09-18
 * five children on one node pushed that node's sshd handshake to 8 s (against a 10 s
 * dispatch timeout) and lost a child. Four leaves that handshake the headroom it needs
 * on the weakest machine in the roster, and the placement broker still spreads work when
 * other nodes have room. A row may raise or lower it; a row that sets 0 or nonsense gets
 * the default, never "unlimited", because "unlimited" is the defect this exists to fix.
 */
export const DEFAULT_MAX_CHILDREN_PER_NODE = 4;

/** Read a per-node children cap. Absent or nonsense means the default, never unlimited. */
export const childrenCap = (value, fallback = DEFAULT_MAX_CHILDREN_PER_NODE) => (
  Number.isInteger(value) && value > 0 ? value : fallback
);

/** The Tailscale DNS label of an fqdn: the part the gate names itself with. */
export function dnsLabel(fqdn) {
  return typeof fqdn === 'string' && fqdn.length > 0 ? fqdn.split('.')[0] : null;
}

/**
 * The per-node v1 transport capability (AMENDMENT 4, owner-approved 2026-09-17).
 *
 * The three states are deliberately distinct, because conflating them is how a broker
 * silently places work that cannot be done:
 *   true   - MEASURED to accept `ssh <alias> dsh --profile headless`;
 *   false  - MEASURED to be unable to (the failure is named in `evidence`);
 *   null   - never measured. Not a claim that it works and not a claim that it does not.
 *
 * `null` is what a roster entry with no `dispatch` field means, so a test fixture or an
 * older roster keeps working - and the broker says "unmeasured" in the rationale rather
 * than pretending either answer.
 */
export function normalizeDispatch(raw) {
  const entry = raw === null || typeof raw !== 'object' || Array.isArray(raw) ? {} : raw;
  const v1 = entry.v1 === true ? true : entry.v1 === false ? false : null;
  return {
    v1,
    measuredAt: typeof entry.measuredAt === 'string' && entry.measuredAt.length > 0 ? entry.measuredAt : null,
    evidence: typeof entry.evidence === 'string' && entry.evidence.length > 0 ? entry.evidence : null,
  };
}

/** Parse and validate a roster object (already JSON-decoded). Throws with the reason. */
export function validateConfig(raw, source = 'config') {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error(`${source}: the roster must be a JSON object`);
  }
  if (!Array.isArray(raw.nodes) || raw.nodes.length === 0) {
    throw new Error(`${source}: "nodes" must be a non-empty array - with no node there is nothing to place on, and the broker must never answer a placement it cannot make`);
  }
  const seen = new Set();
  const nodes = raw.nodes.map((entry, index) => {
    if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) {
      throw new Error(`${source}: nodes[${index}] is not an object`);
    }
    const node = entry.node;
    if (typeof node !== 'string' || node.length === 0) {
      throw new Error(`${source}: nodes[${index}].node must be a non-empty string`);
    }
    if (seen.has(node)) throw new Error(`${source}: node "${node}" appears twice`);
    seen.add(node);
    if (typeof entry.baseUrl !== 'string' || !/^https?:\/\/[^\s/]+/.test(entry.baseUrl)) {
      throw new Error(`${source}: node "${node}" needs an absolute http(s) baseUrl (the gate's root, e.g. https://${node}.tail93e6e6.ts.net)`);
    }
    const fqdn = typeof entry.fqdn === 'string' && entry.fqdn.length > 0 ? entry.fqdn : null;
    if (fqdn === null) {
      throw new Error(`${source}: node "${node}" needs its fqdn (the Tailscale DNS name, e.g. ${node}.tail93e6e6.ts.net) - §2.1's naming invariant is "node == fqdn.split('.')[0]" and it cannot be checked without one`);
    }
    const label = dnsLabel(fqdn);
    if (label !== node) {
      throw new Error(`${source}: node "${node}" does not match the first label of its own fqdn "${fqdn}" (which is "${label}"). §2.1's node name is the Tailscale DNS label, not the host name and not the ssh alias: measured 2026-09-16, the laptop is "zabz-yoga-1" (not "zabz-yoga") and the Linux box is "zabz-tech-linux" (not "linux-pc"). Fix the roster row or the fqdn - a mis-keyed node is a node that silently never answers`);
    }
    return {
      node,
      baseUrl: entry.baseUrl.replace(/\/+$/, ''),
      fqdn,
      location: entry.location === 'home' || entry.location === 'office' ? entry.location : null,
      note: typeof entry.note === 'string' ? entry.note : null,
      // A node can be switched off in the roster without being deleted from it, so its
      // absence from placement is a configuration fact rather than a network accident.
      excluded: entry.excluded === true,
      // ── HOW MANY CHILDREN THIS NODE MAY CARRY AT ONCE ─────────────────────────
      // MEASURED 2026-09-18: five children were placed on one node because the broker
      // ranks by capacity and nothing capped how many a single node could be given.
      // That node's sshd handshake stretched from ~1.5 s to 8 s and one child was lost
      // to a connection timeout — the load that caused the loss was our own fan-out.
      //
      // The node's own `/mesh/capacity` document carries `accepts.maxChildren`, but the
      // broker only consults it to check that ONE task's children fit; it never limits
      // the SUM of what is already running there. And a capacity document can be stale
      // while the leases are not. So the cap is configuration, alongside `excluded`, and
      // it is enforced against the live lease count.
      maxChildren: childrenCap(entry.maxChildren, DEFAULT_MAX_CHILDREN_PER_NODE),
      dispatch: normalizeDispatch(entry.dispatch),
      // Amendment 5: an entry whose node may not exist yet — a configured-but-not-provisioned
      // elastic row. It is what lets `GET /nodes` tell `absent` from `unreachable`; the LIVE
      // roster sets it nowhere, because the elastic tier does not exist (76-broker.md §10.7).
      volatile: entry.volatile === true,
      index,
    };
  });
  return {
    schema: Number.isInteger(raw.schema) ? raw.schema : 1,
    nodes,
    cacheTtlMs: positiveNumber(raw.cacheTtlMs, DEFAULT_CACHE_TTL_MS),
    readTimeoutMs: positiveNumber(raw.readTimeoutMs, DEFAULT_READ_TIMEOUT_MS),
    leaseTtlMs: positiveNumber(raw.leaseTtlMs, DEFAULT_LEASE_TTL_MS),
    source,
  };
}

/** Read a roster from a path. Throws with the reason; the caller fails loudly. */
export function loadConfig(path) {
  let text;
  try {
    text = readFileSync(path, 'utf8');
  } catch (error) {
    throw new Error(`cannot read the roster at ${path}: ${error.message}`);
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error(`${path} is not valid JSON: ${error.message}`);
  }
  return validateConfig(parsed, path);
}
