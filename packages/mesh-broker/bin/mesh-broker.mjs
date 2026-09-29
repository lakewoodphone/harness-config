#!/usr/bin/env node
/**
 * `mesh-broker` — the mesh broker from a shell (docs/mesh/71-mesh-program.md §2.2).
 *
 * USAGE
 *   node bin/mesh-broker.mjs [--port 3091] [--host 127.0.0.1] [--config nodes.json]
 *                            [--timeout-ms 1500] [--cache-ttl-ms 15000] [--lease-ttl-ms 900000]
 *
 * Env fallbacks (so a systemd unit needs no arguments if it does not want them):
 *   MESH_BROKER_PORT, MESH_BROKER_HOST, MESH_BROKER_CONFIG, MESH_BROKER_READ_TIMEOUT_MS,
 *   MESH_BROKER_CACHE_TTL_MS, MESH_BROKER_LEASE_TTL_MS
 *
 * WHAT IT PRINTS IS THE PROVENANCE: the roster it will consult, the cache TTL, the read
 * timeout, the lease TTL, and the port it actually bound. A broker that starts silently is a
 * broker whose roster nobody can check.
 *
 * It writes no files, holds nothing on disk, and can be killed at any moment.
 */

import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createBroker, DEFAULT_CACHE_TTL_MS, REQUEST_ID_TTL_MS } from '../lib/broker.js';
import { loadConfig, DEFAULT_READ_TIMEOUT_MS, DEFAULT_LEASE_TTL_MS, DEFAULT_RETRY_READ_TIMEOUT_MS, DEFAULT_REQUEST_ID_TTL_MS, DEFAULT_FLEET_CONCURRENT_LEASE_CAP } from '../lib/config.js';
import { createBrokerServer, listen, DEFAULT_PORT, DEFAULT_HOST } from '../lib/server.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = path.resolve(HERE, '..');

function parseArgs(argv) {
  const flags = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[index + 1];
    if (next === undefined || next.startsWith('--')) {
      flags[key] = true;
    } else {
      flags[key] = next;
      index += 1;
    }
  }
  return flags;
}

const number = (value, fallback) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};

const usage = () => [
  'mesh-broker — where should this work run? (never refuses; queues instead)',
  '',
  '  POST /place   { "task": { "kind": "oneShot"|"fleet", "children": 6, "worktreeGiB": 2,',
  '                          "prefer": "home"|"office"|null, "exclude": ["node"] } }',
  '  POST /done    { "lease": "...", "ok": true }',
  '  GET  /nodes[?fresh=1]',
  '  GET  /healthz',
  '',
  '  --port <n>            default 3091 (MESH_BROKER_PORT)',
  '  --host <addr>         default 127.0.0.1 (MESH_BROKER_HOST)',
  '  --config <path>       the roster, default <package>/nodes.json (MESH_BROKER_CONFIG)',
  '  --timeout-ms <n>      per-node read timeout, default 1500',
  '  --cache-ttl-ms <n>    how long a capacity reading may be reused, default 15000',
  '  --lease-ttl-ms <n>    lease TTL, default 900000 (15 min)',
  '',
].join('\n');

async function main() {
  const flags = parseArgs(process.argv.slice(2));
  if (flags.help === true) {
    process.stdout.write(usage());
    return 0;
  }
  const configPath = typeof flags.config === 'string'
    ? path.resolve(flags.config)
    : (process.env.MESH_BROKER_CONFIG ?? path.join(PACKAGE_ROOT, 'nodes.json'));
  let config;
  try {
    config = loadConfig(configPath);
  } catch (error) {
    process.stderr.write(`mesh-broker: ${error.message}\n`);
    return 1;
  }
  const port = number(flags.port ?? process.env.MESH_BROKER_PORT, DEFAULT_PORT);
  const host = typeof flags.host === 'string' ? flags.host : (process.env.MESH_BROKER_HOST ?? DEFAULT_HOST);
  const readTimeoutMs = number(flags['timeout-ms'] ?? process.env.MESH_BROKER_READ_TIMEOUT_MS, config.readTimeoutMs ?? DEFAULT_READ_TIMEOUT_MS);
  const cacheTtlMs = number(flags['cache-ttl-ms'] ?? process.env.MESH_BROKER_CACHE_TTL_MS, config.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS);
  const leaseTtlMs = number(flags['lease-ttl-ms'] ?? process.env.MESH_BROKER_LEASE_TTL_MS, config.leaseTtlMs ?? DEFAULT_LEASE_TTL_MS);
  // EVERY CONFIG KEY `loadConfig` PARSES MUST BE THREADED HERE, or the file's value is
  // silently ignored and the deployed binary runs on code defaults while the config
  // says otherwise — a drift that is invisible from both ends (pain P8). Measured
  // 2026-09-29: these three were parsed by `lib/config.js` and never passed, so
  // `nodes.json` could not change the retry budget, the request-id memo TTL or the
  // per-node fleet cap. Recorded in `docs/mesh/126-placement-hardening.md`.
  const retryTimeoutMs = number(flags['retry-ms'] ?? process.env.MESH_BROKER_RETRY_TIMEOUT_MS, config.retryTimeoutMs ?? DEFAULT_RETRY_READ_TIMEOUT_MS);
  const requestIdTtlMs = number(flags['request-id-ttl-ms'] ?? process.env.MESH_BROKER_REQUEST_ID_TTL_MS, config.requestIdTtlMs ?? DEFAULT_REQUEST_ID_TTL_MS);
  const fleetConcurrentLeaseCap = number(flags['fleet-cap'] ?? process.env.MESH_BROKER_FLEET_CAP, config.fleetConcurrentLeaseCap ?? DEFAULT_FLEET_CONCURRENT_LEASE_CAP);

  const broker = createBroker({
    nodes: config.nodes,
    cacheTtlMs,
    readTimeoutMs,
    retryTimeoutMs,
    requestIdTtlMs,
    fleetConcurrentLeaseCap,
    leaseTtlMs,
  });
  const log = (line) => process.stdout.write(`${new Date().toISOString()} ${line}\n`);
  const server = createBrokerServer({ broker, logger: (line) => log(`  ${line}`) });
  let bound;
  try {
    bound = await listen(server, { host, port });
  } catch (error) {
    process.stderr.write(`mesh-broker: cannot listen on ${host}:${port}: ${error.message}\n`);
    return 1;
  }

  log(`mesh-broker listening on ${bound.url}  (port ${bound.port})`);
  log(`  roster       ${configPath}`);
  for (const node of config.nodes) {
    log(`    ${node.node.padEnd(18)} ${node.baseUrl}/mesh/capacity${node.location === null ? '' : `   [${node.location}]`}${node.excluded === true ? '   [SWITCHED OFF]' : ''}`);
  }
  log(`  cache        capacity readings are reused for at most ${Math.round(cacheTtlMs / 1000)} s`);
  log(`  timeout      ${readTimeoutMs} ms per node read`);
  log(`  retry        ${retryTimeoutMs} ms for the ONE retry when a read misses the deadline`);
  log(`  request id   a replayed place request returns the same lease for ${Math.round(requestIdTtlMs / 1000)} s`);
  log(`  fleet cap    at most ${fleetConcurrentLeaseCap} concurrent fleet lease(s) per node, or the node's own accepts.maxChildren if smaller`);
  log(`  lease ttl    ${Math.round(leaseTtlMs / 1000)} s (a dead dispatcher is outlived, not waited for)`);
  log('  verbs        POST /place   POST /done   GET /nodes[?fresh=1]   GET /healthz');
  log('  state        none on disk: live leases and 15-second readings in memory only');

  const shutdown = (signal) => {
    log(`  ${signal}: closing the listener; live leases are simply forgotten (nothing is on disk to leak)`);
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 1000).unref();
  };
  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  return await new Promise(() => {});
}

main().then((code) => {
  if (typeof code === 'number') process.exit(code);
}).catch((error) => {
  process.stderr.write(`mesh-broker: fatal: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exit(1);
});
