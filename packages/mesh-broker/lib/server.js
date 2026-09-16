/**
 * The broker's HTTP surface: exactly the three verbs §2.2 freezes, plus a liveness route.
 *
 *   POST /place   { "task": { kind, children, worktreeGiB, prefer, exclude } }  ->  200 placement
 *   POST /done    { "lease": "...", "ok": true }                                 ->  200 release report
 *   GET  /nodes[?fresh=1]                                                        ->  200 every reading + its age
 *   GET  /healthz                                                                ->  200 the broker's own liveness
 *
 * WHAT IS NOT HERE, ON PURPOSE
 * No authentication of its own: the broker sits on the authority behind the same tailnet
 * publication as everything else, and §2.2 defines it as a plain HTTP service on the
 * authority. No persistence: there is no file this server writes, so there is nothing to
 * fsync, nothing to corrupt, and nothing that can be believed after it is false. And no
 * error path on /place - a malformed body, an unreadable node and an internal fault all
 * come back 200 with a node and a position, because §2.2 says a placement exists for every
 * request.
 */

import http from 'node:http';

export const DEFAULT_PORT = 3091;
export const DEFAULT_HOST = '127.0.0.1';
export const MAX_REQUEST_BYTES = 64 * 1024;

/** Read a request body with a hard cap. Never rejects; a truncated body is the caller's problem. */
function readBody(request, limit = MAX_REQUEST_BYTES) {
  return new Promise((resolve) => {
    const chunks = [];
    let size = 0;
    request.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) {
        chunks.length = 0;
        return;
      }
      chunks.push(chunk);
    });
    request.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    request.on('error', () => resolve(''));
    request.on('aborted', () => resolve(''));
  });
}

function sendJson(response, status, payload) {
  const body = `${JSON.stringify(payload, null, 2)}\n`;
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  response.end(body);
}

/**
 * @param {object} options
 * @param {ReturnType<import('./broker.js').createBroker>} options.broker
 * @param {(line:string) => void} [options.logger]
 */
export function createBrokerServer(options) {
  const { broker } = options;
  const logger = typeof options.logger === 'function' ? options.logger : () => {};
  const startedAt = Date.now();

  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url ?? '/', 'http://broker.invalid');
    const method = request.method ?? 'GET';
    try {
      if (url.pathname === '/place') {
        if (method !== 'POST') {
          sendJson(response, 405, { error: `POST /place, not ${method} /place`, at: new Date().toISOString() });
          return;
        }
        const raw = await readBody(request);
        let body = null;
        try {
          body = raw.length === 0 ? null : JSON.parse(raw);
        } catch {
          body = raw; // normalizeTask reports the parse failure in the rationale and still places
        }
        const placement = await broker.place(body);
        logger(`place -> ${placement.node} position=${placement.position} tier=${placement.tier} ${placement.kind} children=${placement.children} lease=${placement.lease}`);
        sendJson(response, 200, placement);
        return;
      }
      if (url.pathname === '/done') {
        if (method !== 'POST') {
          sendJson(response, 405, { error: `POST /done, not ${method} /done`, at: new Date().toISOString() });
          return;
        }
        const raw = await readBody(request);
        let body = null;
        try {
          body = raw.length === 0 ? null : JSON.parse(raw);
        } catch {
          body = raw;
        }
        const report = broker.done(body);
        logger(`done -> lease=${report.lease ?? '(none)'} released=${report.released}`);
        sendJson(response, 200, report);
        return;
      }
      if (url.pathname === '/nodes') {
        if (method !== 'GET') {
          sendJson(response, 405, { error: `GET /nodes, not ${method} /nodes`, at: new Date().toISOString() });
          return;
        }
        const fresh = url.searchParams.get('fresh') === '1' || url.searchParams.get('fresh') === 'true';
        const report = await broker.nodes({ fresh });
        sendJson(response, 200, report);
        return;
      }
      if (url.pathname === '/healthz' || url.pathname === '/mesh/broker/health') {
        const status = broker.status();
        sendJson(response, 200, { ok: true, ...status, processUptimeSec: Math.round((Date.now() - startedAt) / 1000) });
        return;
      }
      if (url.pathname === '/' || url.pathname === '/mesh/broker') {
        sendJson(response, 200, {
          service: 'mesh-broker',
          schema: 1,
          verbs: ['POST /place', 'POST /done', 'GET /nodes[?fresh=1]', 'GET /healthz'],
          contract: 'docs/mesh/71-mesh-program.md §2.2 (frozen)',
          at: new Date().toISOString(),
        });
        return;
      }
      sendJson(response, 404, { error: `no route for ${method} ${url.pathname}`, at: new Date().toISOString() });
    } catch (error) {
      // Last-resort net. /place must never take this path, and if it ever does the answer
      // still names a node rather than returning a 5xx.
      const message = error instanceof Error ? error.message : String(error);
      logger(`unhandled error on ${method} ${url.pathname}: ${message}`);
      if (url.pathname === '/place') {
        const placement = await broker.place({ task: { kind: 'oneShot', children: 1 } }).catch(() => null);
        if (placement !== null) {
          placement.rationale.unshift(`http-layer fault (${message}) - answered with a placement rather than a 5xx (the broker never refuses)`);
          sendJson(response, 200, placement);
          return;
        }
      }
      sendJson(response, 500, { error: message, at: new Date().toISOString() });
    }
  });

  // A placement must stay answerable while an old keep-alive socket lingers.
  server.keepAliveTimeout = 30_000;
  server.headersTimeout = 35_000;
  return server;
}

/** Listen and resolve with the real address, so port 0 in a test gives the real port back. */
export function listen(server, { host = DEFAULT_HOST, port = DEFAULT_PORT } = {}) {
  return new Promise((resolve, reject) => {
    const onError = (error) => {
      server.removeListener('listening', onListening);
      reject(error);
    };
    const onListening = () => {
      server.removeListener('error', onError);
      const address = server.address();
      resolve({ host, port: typeof address === 'object' && address !== null ? address.port : port, url: `http://${host}:${typeof address === 'object' && address !== null ? address.port : port}` });
    };
    server.once('error', onError);
    server.once('listening', onListening);
    server.listen(port, host);
  });
}
