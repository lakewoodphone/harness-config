/**
 * Dispatcher-side placement: decide where a child runs from MEASUREMENTS TAKEN
 * HERE, so that no single machine — the broker included — can stop a dispatch.
 *
 * ── THE DEFECT THIS EXISTS TO REMOVE ────────────────────────────────────────
 *
 * Measured 2026-10-09, twice, from ZABZ-YOGA, with the owner watching:
 *
 *   Error: remote-ssh: broker-unreachable: the placement broker could not be
 *   reached at secratary-ts:http://localhost:3091/place — ssh exited 255:
 *   ssh: connect to host secratary.tail93e6e6.ts.net port 22: Connection timed out
 *
 * At that exact moment `zabz-yoga-1` and `zabz-tech` both answered
 * `GET /mesh/health` in 0.13 s and 0.20 s with `maxConcurrent: 12` and 8, zero
 * in flight, and zero queued. Two healthy workers, one unreachable control
 * plane, and **the entire fan-out plane dead** — `subagent` (the mesh provider)
 * could not start a single child. This is pain `P2858` reproduced verbatim, and
 * it is not an outage: it is the architecture. `lib/placement.js` is written so
 * that a broker that cannot be reached is *a reported error rather than a
 * default*, and `lib/broker-client.js` hard-wires both the machine it is
 * reached on (`sshTarget: 'secratary-ts'`) and the URL it is reached at
 * (`http://localhost:3091`, loopback-only). One process on one machine is
 * therefore the only thing that can ever say where work goes.
 *
 * ── WHAT REPLACES IT ────────────────────────────────────────────────────────
 *
 * Every node on this mesh already answers two routes on its own engine, reached
 * over the tailnet with no ssh and no intermediary
 * (`packages/plugin-mesh-http/README.md`):
 *
 *   GET  /mesh/health   — unauthenticated, and it publishes the node's own
 *                         concurrency decision, its binding term, its sources,
 *                         its in-flight count, its queue, and whether it holds
 *                         a usable secret.
 *   POST /mesh/run      — the dispatch itself, HMAC-signed.
 *
 * So a dispatcher can SEE the whole mesh by asking each node directly, and rank
 * the answers itself. The broker keeps its value — one shared view, leases that
 * survive a dispatcher's death, cross-node accounting — and loses its
 * veto: it becomes an OPTIMISATION that can be missing. This module is the
 * measurement half of that, and it is deliberately a pure function over
 * observations so it can be tested without a network, a mesh, or a child.
 *
 * ── THE RULES IT KEEPS, WHICH ARE THE HARNESS'S OWN ─────────────────────────
 *
 *   * **A reading that could not be made never changes a decision.** A node that
 *     did not answer is recorded as unreachable and is NOT scored as full, busy,
 *     or bad. Absence of evidence is not evidence of absence.
 *   * **Queue, never amputate.** A candidate with fewer free slots than the
 *     child needs is still a candidate, with a positive `position`. There is no
 *     path in this file that returns "refuse".
 *   * **Never exclude everything.** `rankCandidates` yields rather than emptying
 *     the list, and says in its rationale that it yielded.
 *   * **Every decision carries its arithmetic.** `rationale` names each node,
 *     its free slots, and the term that decided its order, so a placement can be
 *     explained afterwards rather than believed.
 */

/**
 * The transport preference order. `v2` is the node's own HTTP route (it needs no
 * ssh and no login session, which is why it is first); `v1` is
 * `ssh <node> dsh --profile headless`, which needs no shared secret. Either one
 * alone is enough to dispatch, which is the whole point.
 */
export const TRANSPORTS = Object.freeze(['v2', 'v1']);

/** No candidate could be placed. The caller turns this into a reported condition, never a local default. */
export const NO_CANDIDATE = 'no-candidate';

/** `health.concurrency.limit`, else `health.limits.maxConcurrent`, else null. Never a guess. */
function readFreeSlots(health) {
  const fromConcurrency = health?.concurrency?.limit;
  if (Number.isFinite(fromConcurrency)) return Number(fromConcurrency);
  const fromLimits = health?.limits?.maxConcurrent;
  if (Number.isFinite(fromLimits)) return Number(fromLimits);
  return null;
}

/**
 * Read ONE node's health document and say what it can take.
 *
 * Total by construction: every input shape returns an object and nothing throws,
 * because this runs inside a dispatch path where an exception would be a lost
 * turn. A node that answered `ok:false`, or did not answer at all, is reported
 * with `ok:false` and a reason — never as full, and never as healthy.
 *
 * @param {object|null|undefined} health the parsed `GET /mesh/health` body, or nothing
 * @param {{wantV2?: boolean, wantSsh?: boolean}} [options]
 * @returns {{ok: boolean, node: string|null, transports: string[], freeSlots: number|null,
 *            busy: boolean, reason: string|null, evidence: object}}
 */
export function assessNode(health, { wantV2 = true, wantSsh = true } = {}) {
  let doc;
  try {
    doc = health !== null && typeof health === 'object' ? health : null;
  } catch {
    doc = null;
  }
  if (doc === null) {
    return {
      ok: false,
      node: null,
      transports: [],
      freeSlots: null,
      busy: false,
      reason: 'no health document — this node did not answer',
      evidence: { answered: false },
    };
  }

  // Everything below reads a field off a document that arrived over the
  // network. A getter that throws, a proxy that traps, a `node` that is a
  // Symbol — none of those may escape into the dispatch path as an exception,
  // because the caller is deciding where to send work and a thrown read would
  // become a lost child. Measured 2026-10-09 by an adversarial test fork:
  // `assessNode({ get ok() { throw … } })` threw out of the module. This block
  // is why it no longer can.
  let node = null;
  let secretConfigured = false;
  let busy = false;
  let freeSlots = null;
  let evidence;
  try {
    node = typeof doc.node === 'string' && doc.node.trim() !== '' ? doc.node : null;
    secretConfigured = doc.auth?.secretConfigured === true;
    busy = doc.runner?.busy === true;
    freeSlots = readFreeSlots(doc);
    evidence = {
      answered: true,
      ok: doc.ok === true,
      node,
      service: doc.service ?? null,
      version: doc.version ?? null,
      secretConfigured,
      secretPath: doc.auth?.secretPath ?? null,
      busy,
      freeSlots,
      queueDepth: doc.runner?.queueDepth ?? null,
      inFlightCount: doc.runner?.inFlightCount ?? null,
      concurrencyNote: doc.concurrency?.note ?? null,
      identityDegraded: doc.identityDegraded === true,
    };
  } catch (error) {
    return {
      ok: false,
      node: null,
      transports: [],
      freeSlots: null,
      busy: false,
      reason: `the health document could not be read (${String(error?.message ?? error)}) — treated as "this node did not answer", never as a node that is full`,
      evidence: { answered: true, unreadable: true },
    };
  }

  if (evidence.ok !== true) {
    return { ok: false, node, transports: [], freeSlots, busy, reason: 'the node answered ok:false', evidence };
  }

  const transports = [];
  if (wantV2 && secretConfigured) transports.push('v2');
  if (wantSsh) transports.push('v1');

  if (transports.length === 0) {
    const why = !wantV2 && !wantSsh
      ? 'this caller asked for no transport at all'
      : 'no usable transport: the v2 route has no secret configured on this node and ssh was not offered';
    return { ok: false, node, transports: [], freeSlots, busy, reason: why, evidence };
  }

  if (busy === true) {
    return { ok: false, node, transports, freeSlots, busy, reason: 'the node reports runner.busy — it is already running a turn', evidence };
  }

  return { ok: true, node, transports, freeSlots, busy, reason: null, evidence };
}

/** The first line of a rationale for one candidate, in the harness's own units. */
function describeTerm(name, value) {
  return `${name}: ${value === null || value === undefined ? 'not measured' : value}`;
}

/**
 * Rank assessed candidates best-first.
 *
 * THE ORDER IS DELIBERATELY THE SIMPLEST THING THAT CAN BE EXPLAINED:
 * more free slots wins; a tie is broken by fewer things in flight; a further tie
 * by whether the node has a v2 route (fewer moving parts). Nothing here uses a
 * per-node unit cost, because — measured 2026-09-18 in
 * `docs/mesh/111-placement-design.md` §2 — **only the laptop has a calibrated
 * cost per turn**, and ranking remote nodes on a unit measured on a different
 * machine would be arithmetic on someone else's units. Capacity is honest;
 * invented precision is not.
 *
 * NEVER EXCLUDES EVERYTHING. `exclude` and `preferRemote` are HINTS. When they
 * would empty the list, the best excluded node is returned anyway and the
 * rationale says the hint yielded — which is the mesh's own never-refuse rule,
 * and is what stops a stale exclusion list from becoming an outage.
 *
 * @param {Array<{node: string|null, ok: boolean, freeSlots: number|null, busy: boolean,
 *                transports: string[], reason: string|null, evidence: object}>} candidates
 * @param {{exclude?: string[], thisNode?: string|null, children?: number, preferRemote?: boolean}} [options]
 */
export function rankCandidates(candidates, { exclude = [], thisNode = null, children = 1, preferRemote = false } = {}) {
  const list = Array.isArray(candidates) ? candidates : [];
  const wanted = Number.isFinite(children) && children > 0 ? Number(children) : 1;
  const excludedNames = new Set((Array.isArray(exclude) ? exclude : []).filter((n) => typeof n === 'string' && n !== ''));

  const rationale = [];
  const eligible = [];
  const held = [];

  for (const candidate of list) {
    if (candidate === null || typeof candidate !== 'object') continue;
    const name = candidate.node;
    if (candidate.ok !== true) {
      rationale.push(`not a candidate: ${name ?? '(unnamed)'} — ${candidate.reason ?? 'no reason given'}`);
      continue;
    }
    const why = [];
    if (name !== null && excludedNames.has(name)) why.push(`excluded by the caller`);
    if (preferRemote === true && thisNode !== null && name === thisNode) why.push(`left out by prefer-remote (this machine)`);

    const scored = {
      node: name,
      score: Number.isFinite(candidate.freeSlots) ? Number(candidate.freeSlots) : 0,
      terms: {
        freeSlots: candidate.freeSlots ?? null,
        children: wanted,
        v2: Array.isArray(candidate.transports) && candidate.transports.includes('v2'),
        inFlightCount: candidate.evidence?.inFlightCount ?? null,
        queueDepth: candidate.evidence?.queueDepth ?? null,
      },
      freeSlots: candidate.freeSlots ?? null,
      transports: Array.isArray(candidate.transports) ? [...candidate.transports] : [],
      rationale: [],
    };
    if (why.length > 0) {
      held.push({ scored, why: why.join(' and ') });
      rationale.push(`held back: ${name ?? '(unnamed)'} — ${why.join(' and ')} (${describeTerm('freeSlots', candidate.freeSlots)})`);
    } else {
      eligible.push(scored);
    }
  }

  const byQuality = (a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    const ai = Number.isFinite(a.terms.inFlightCount) ? a.terms.inFlightCount : 0;
    const bi = Number.isFinite(b.terms.inFlightCount) ? b.terms.inFlightCount : 0;
    if (ai !== bi) return ai - bi;
    if (a.terms.v2 !== b.terms.v2) return a.terms.v2 ? -1 : 1;
    return String(a.node ?? '').localeCompare(String(b.node ?? ''));
  };

  let ranked = eligible.sort(byQuality);

  if (ranked.length === 0 && held.length > 0) {
    // THE HINT YIELDS. A caller's exclusion list is a preference; an empty mesh
    // is an outage. The mesh's own rule is queue-never-amputate, so the best
    // held-back candidate is returned, and this line is how a reader learns the
    // placement was a yield rather than a choice.
    ranked = held.map((h) => h.scored).sort(byQuality);
    rationale.push(
      `EVERY candidate was excluded by a hint (${held.length}), so the hint YIELDED and ${ranked[0]?.node ?? '(none)'} was returned anyway: `
      + `an exclusion is a preference and an empty mesh is an outage (never-refuse)`,
    );
  }

  for (const entry of ranked) {
    entry.rationale = [
      `${entry.node ?? '(unnamed)'}: ${describeTerm('freeSlots', entry.freeSlots)} vs ${wanted} child(ren) — `
      + (Number.isFinite(entry.freeSlots) && entry.freeSlots >= wanted ? 'fits' : 'short, so this will QUEUE rather than be refused'),
      `transports ${entry.transports.join('>') || 'none'}`,
    ];
  }

  if (ranked.length === 0 && held.length === 0) {
    rationale.push('there were no assessed candidates at all — nothing answered, or nothing was asked');
  }

  return { ranked, chosen: ranked[0] ?? null, rationale };
}

/**
 * The whole decision, from raw observations to a placement.
 *
 * @param {Array<{node: string, health?: object|null, error?: string|null}>} observations
 *        one entry per node the caller tried to read. `error` present means the
 *        read failed and is recorded as unreachable — never scored.
 * @param {{exclude?: string[], thisNode?: string|null, children?: number,
 *          preferRemote?: boolean, wantV2?: boolean, wantSsh?: boolean}} [options]
 */
export function chooseFailoverPlacement(observations, options = {}) {
  const { wantV2 = true, wantSsh = true, children = 1 } = options;
  const list = Array.isArray(observations) ? observations : [];
  const unreachable = [];
  const assessed = [];
  const rationale = [];

  for (const observation of list) {
    if (observation === null || typeof observation !== 'object') continue;
    const name = typeof observation.node === 'string' ? observation.node : null;
    if (observation.error !== undefined && observation.error !== null && observation.error !== '') {
      unreachable.push({ node: name, error: String(observation.error) });
      rationale.push(`unreachable: ${name ?? '(unnamed)'} — ${String(observation.error)}`);
      continue;
    }
    const verdict = assessNode(observation.health ?? null, { wantV2, wantSsh });
    assessed.push({ ...verdict, node: verdict.node ?? name });
    if (verdict.ok !== true) rationale.push(`not usable: ${verdict.node ?? name ?? '(unnamed)'} — ${verdict.reason}`);
  }

  const { ranked, chosen, rationale: rankRationale } = rankCandidates(assessed, {
    exclude: options.exclude,
    thisNode: options.thisNode ?? null,
    children,
    preferRemote: options.preferRemote ?? false,
  });

  const wanted = Number.isFinite(children) && children > 0 ? Number(children) : 1;

  if (chosen === null) {
    return {
      node: null,
      transports: [],
      freeSlots: null,
      position: 0,
      source: 'direct-probe',
      code: NO_CANDIDATE,
      ranked,
      unreachable,
      rationale: [
        ...rationale,
        ...rankRationale,
        `NO CANDIDATE (${NO_CANDIDATE}): ${unreachable.length} node(s) unreachable, ${assessed.length} assessed, 0 placeable — `
        + 'nothing is dispatched and no local default is used, because a silent default is how a mesh of one machine looks like a mesh of five',
      ],
    };
  }

  const short = Number.isFinite(chosen.freeSlots) && chosen.freeSlots < wanted;
  // QUEUE, NEVER AMPUTATE. A node with too few slots is still the answer, with a
  // position that says how many children are ahead of it. The whole design of
  // this mesh is that work waits instead of being lost.
  const position = short ? Math.max(1, wanted - Math.max(0, chosen.freeSlots ?? 0)) : 0;

  return {
    node: chosen.node,
    transports: chosen.transports,
    freeSlots: chosen.freeSlots,
    position,
    source: 'direct-probe',
    code: null,
    ranked,
    unreachable,
    rationale: [
      ...rationale,
      ...rankRationale,
      `chosen ${chosen.node} with ${chosen.freeSlots ?? 'unmeasured'} free slot(s) for ${wanted} child(ren) -> position ${position} (${position === 0 ? 'start now' : 'queued'})`,
      `read directly from ${list.length} node(s) by this dispatcher; the placement broker was not needed and was not asked`,
    ],
  };
}
