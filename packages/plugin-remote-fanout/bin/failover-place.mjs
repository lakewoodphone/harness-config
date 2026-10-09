#!/usr/bin/env node
/**
 * failover-place — ask the LIVE mesh where a child should run, with no broker.
 *
 * This is the instrument that shows dispatcher-side placement working against
 * the real fleet. It reads every node directly (`GET /mesh/health` and
 * `GET /mesh/capacity` over the tailnet), ranks the answers with
 * `lib/failover-placement.js`, and prints the decision with its arithmetic.
 *
 * It dispatches NOTHING. It is read-only against the network and writes nothing
 * anywhere, so it is safe to run at any time, including while the owner works.
 *
 * USAGE
 *   node bin/failover-place.mjs [--children N] [--node A,B] [--json]
 *                               [--exclude X,Y] [--prefer-remote] [--tailnet SUFFIX]
 *
 * EXITS
 *   0  a placement was chosen
 *   1  no candidate (the mesh is genuinely unusable — every node unreachable)
 *   2  bad arguments
 */

import { chooseFailoverPlacement, NO_CANDIDATE } from '../lib/failover-placement.js';
import { probeMesh, DEFAULT_TAILNET } from '../lib/node-probes.js';
import { NODES } from '../lib/nodes.js';
import { localNodeName } from '../lib/pressure.js';

function parse(argv) {
  const out = { flags: {} };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const [key, inline] = arg.slice(2).split('=');
    if (inline !== undefined) out.flags[key] = inline;
    else if (argv[i + 1] !== undefined && !argv[i + 1].startsWith('--')) out.flags[key] = argv[++i];
    else out.flags[key] = true;
  }
  return out;
}

const { flags } = parse(process.argv.slice(2));
const json = flags.json === true;
const children = flags.children !== undefined ? Number(flags.children) : 1;
if (!Number.isFinite(children) || children < 1) {
  console.error(`failover-place: --children must be a positive number (got ${flags.children})`);
  process.exit(2);
}

const nodes = typeof flags.node === 'string' && flags.node !== ''
  ? flags.node.split(',').map((s) => s.trim()).filter(Boolean)
  : Object.keys(NODES);
const exclude = typeof flags.exclude === 'string' && flags.exclude !== ''
  ? flags.exclude.split(',').map((s) => s.trim()).filter(Boolean)
  : [];
const tailnet = typeof flags.tailnet === 'string' && flags.tailnet !== '' ? flags.tailnet : DEFAULT_TAILNET;
const thisNode = localNodeName() ?? null;

const started = Date.now();
const probe = await probeMesh({ nodes, tailnet });

const placement = chooseFailoverPlacement(probe.observations, {
  exclude,
  thisNode,
  children,
  preferRemote: flags['prefer-remote'] === true,
});

const out = {
  askedAt: probe.at,
  tookMs: Date.now() - started,
  thisNode,
  tailnet,
  children,
  nodesAsked: nodes,
  reached: probe.reached,
  unreachable: probe.unreachable,
  chosen: placement.node,
  transports: placement.transports,
  freeSlots: placement.freeSlots,
  position: placement.position,
  source: placement.source,
  code: placement.code,
  ranked: placement.ranked.map((r) => ({ node: r.node, score: r.score, freeSlots: r.freeSlots, transports: r.transports, terms: r.terms })),
  rationale: placement.rationale,
  perNode: probe.observations.map((o) => ({
    node: o.node,
    ms: o.ms ?? null,
    error: o.error ?? null,
    health: o.health === null ? null : {
      node: o.health.node,
      host: o.health.host,
      ok: o.health.ok,
      secretConfigured: o.health.auth?.secretConfigured ?? null,
      secretFingerprint: o.health.auth?.secretFingerprint ?? null,
      busy: o.health.runner?.busy ?? null,
      inFlightCount: o.health.runner?.inFlightCount ?? null,
      queueDepth: o.health.runner?.queueDepth ?? null,
      concurrencyLimit: o.health.concurrency?.limit ?? null,
      limitsMaxConcurrent: o.health.limits?.maxConcurrent ?? null,
      note: o.health.concurrency?.note ?? null,
      identityDegraded: o.health.identityDegraded ?? null,
      identityReason: o.health.identityReason ?? null,
    },
    capacity: o.capacity === null || o.capacity === undefined ? null : {
      node: o.capacity.node,
      fqdn: o.capacity.fqdn,
      cpuLogical: o.capacity.cpu?.logical ?? null,
      memFreeMiB: o.capacity.mem?.freeMiB ?? null,
      diskFreeGiB: o.capacity.disk?.freeGiB ?? null,
      loopsRunning: o.capacity.agents?.loopsRunning ?? null,
      sessionsLive: o.capacity.agents?.sessionsLive ?? null,
      maxChildren: o.capacity.accepts?.maxChildren ?? null,
    },
    capacityError: o.capacityError ?? null,
  })),
};

if (json) {
  console.log(JSON.stringify(out, null, 2));
} else {
  console.log(`failover-place — ${out.askedAt} (${out.tookMs} ms, ${out.nodesAsked.length} node(s) asked from ${thisNode ?? 'an unnamed host'})`);
  console.log('');
  console.log(`  reached      ${out.reached.length ? out.reached.join(', ') : '(none)'}`);
  console.log(`  unreachable  ${out.unreachable.length ? out.unreachable.map((u) => `${u.node} (${u.error})`).join(', ') : '(none)'}`);
  console.log('');
  for (const r of out.ranked) {
    console.log(`  candidate  ${String(r.node).padEnd(20)} freeSlots=${String(r.freeSlots).padEnd(5)} transports=${r.transports.join('>') || '-'}`);
  }
  console.log('');
  console.log(`  CHOSEN       ${out.chosen ?? '(none)'}`);
  console.log(`  transports   ${out.transports.join(' > ') || '-'}`);
  console.log(`  position     ${out.position} ${out.position === 0 ? '(start now)' : '(queued)'}`);
  console.log(`  source       ${out.source}${out.code ? ` code=${out.code}` : ''}`);
  console.log('');
  for (const line of out.rationale) console.log(`  · ${line}`);
}

process.exit(out.chosen === null ? (out.code === NO_CANDIDATE ? 1 : 1) : 0);
