/**
 * A stub gate: a tiny HTTP server that answers `GET /mesh/capacity` with a §2.1 document.
 *
 * WHY THIS EXISTS
 * Stream S1 adds the real route to scripts/phone-gate.py, and while it is being written (and
 * on any node where it is not deployed) the broker must still be testable end to end. The
 * brief for S5 says exactly this: "for your tests use a local stub server that serves that
 * schema". The same server is exposed as `mesh-stub-gate` so a human or another stream can
 * reproduce a placement against controlled numbers without waiting for S1.
 *
 * It is also how the acceptance test in §4 item 2 is run: "Repeat with that node's capacity
 * forced to 0" is `gate.setCapacity({ freeMiB: 0 })` here.
 */

import http from 'node:http';

/** `?? fallback` would turn an explicit null (a real §2.1 state) into the default. */
const pick = (overrides, key, fallback) => (overrides[key] === undefined ? fallback : overrides[key]);

/** The §2.1 sample shape, with the numbers from docs/mesh/71-mesh-program.md. */
export function capacityDocument(overrides = {}) {
  const node = overrides.node ?? 'stub-node';
  const freeMiB = pick(overrides, 'freeMiB', 17575);
  const inUse = pick(overrides, 'inUse', 2);
  const budgetSlots = pick(overrides, 'budgetSlots', 24);
  const engineDown = overrides.engineDown === true;
  const doc = {
    schema: 1,
    node,
    fqdn: overrides.fqdn ?? `${node}.example.invalid`,
    at: overrides.at ?? new Date().toISOString(),
    cpu: {
      logical: pick(overrides, 'logical', 22),
      // Default to a real 16 physical / 22 logical shape (this laptop) so a fixture that does
      // not care about cores still gets a sane core term: floor(16 * 0.75) = 12, which is not
      // the binding term when a fixture is testing the memory arithmetic.
      physical: pick(overrides, 'physical', 16),
      load1: pick(overrides, 'load1', 0.42),
    },
    mem: {
      totalMiB: pick(overrides, 'totalMiB', 32373),
      freeMiB,
      swapUsedPct: pick(overrides, 'swapUsedPct', 0),
    },
    disk: {
      workRoot: pick(overrides, 'workRoot', 'C:/Users/ezabz/code'),
      freeGiB: pick(overrides, 'diskGiB', 236),
    },
    // §2.1: if the engine is down, agents and governor are null and accepts.oneShot is
    // still true, because a headless run needs no engine.
    agents: engineDown ? null : { loopsRunning: pick(overrides, 'loopsRunning', 0), sessionsLive: pick(overrides, 'sessionsLive', 1) },
    governor: engineDown ? null : { budgetSlots, inUse, queued: pick(overrides, 'governorQueued', 0) },
    accepts: {
      oneShot: pick(overrides, 'acceptsOneShot', true),
      fleet: pick(overrides, 'acceptsFleet', true),
      maxChildren: pick(overrides, 'maxChildren', 12),
      reason: overrides.acceptsReason ?? null,
    },
  };
  if (overrides.extra !== undefined && overrides.extra !== null) Object.assign(doc, overrides.extra);
  return doc;
}

/**
 * A `mem.freeMiB` that makes §2.2's arithmetic land on exactly `slots` (before governor.inUse).
 * floor((freeMiB - 3885) / 160) = slots  ->  freeMiB = 3885 + slots * 160.
 */
export function freeMiBForSlots(slots) {
  return 3885 + Math.max(0, slots) * 160;
}

/**
 * Start a stub on port 0 (never a fixed port - the brief, and the only way two test runs can
 * never collide).
 *
 * @returns {Promise<{node:string, port:number, url:string, capacity:object, setCapacity:Function,
 *                    setEngineDown:Function, requests:Function, close:Function, server:http.Server}>}
 */
export function startStubGate(overrides = {}) {
  // The stub's whole state is one flat override object: `capacityDocument()` is the only
  // place the §2.1 shape is written, so `setCapacity({ freeMiB: 0 })` is exactly the
  // "force a node's capacity to zero" move the acceptance test needs.
  let state = { ...overrides };
  let requests = 0;
  const render = () => capacityDocument(state);
  const server = http.createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://stub.invalid');
    if (request.method === 'GET' && url.pathname === '/mesh/capacity') {
      requests += 1;
      const body = JSON.stringify(render());
      response.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) });
      response.end(body);
      return;
    }
    response.writeHead(404, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ error: 'stub gate: only GET /mesh/capacity' }));
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({
        get node() {
          return state.node ?? 'stub-node';
        },
        port,
        url: `http://127.0.0.1:${port}`,
        get capacity() {
          return render();
        },
        setCapacity(patch) {
          state = { ...state, ...patch };
          return render();
        },
        setEngineDown(down) {
          state = { ...state, engineDown: down === true };
          return render();
        },
        requests: () => requests,
        close: () => new Promise((done) => server.close(() => done())),
        server,
      });
    });
  });
}
