/**
 * The roster loader.
 *
 *   node --test test/config.test.mjs
 *
 * A roster with no node is the one condition under which the never-refuse rule has nothing
 * honest to say, so it is a startup failure with a reason rather than a runtime surprise.
 * The same goes for a MIS-KEYED node: §2.1's `node` is the Tailscale DNS label, and a row
 * keyed on the host name or the ssh alias reads a node it will never find, leaving the mesh
 * working with one node quietly absent (amendment to §2.1, 2026-09-17).
 */

import { strict as assert } from 'node:assert';
import test from 'node:test';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { DEFAULT_CACHE_TTL_MS, DEFAULT_FLEET_CONCURRENT_LEASE_CAP, DEFAULT_READ_TIMEOUT_MS, DEFAULT_REQUEST_ID_TTL_MS, DEFAULT_RETRY_READ_TIMEOUT_MS, dnsLabel, loadConfig, normalizeDispatch, validateConfig } from '../lib/config.js';
import { MAX_REQUEST_ID_ENTRIES, REQUEST_ID_TTL_MS } from '../lib/broker.js';
import { FLEET_CONCURRENT_LEASE_CAP } from '../lib/scoring.js';

const scratchFile = (contents) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'mesh-broker-config-'));
  const file = path.join(dir, 'nodes.json');
  writeFileSync(file, contents);
  return { dir, file };
};

const node = (over = {}) => ({ node: 'zabz-tech', baseUrl: 'https://zabz-tech.tail93e6e6.ts.net', fqdn: 'zabz-tech.tail93e6e6.ts.net', ...over });

test('the shipped roster is valid, names five nodes, and reads like the program describes them', () => {
  const config = loadConfig(fileURLToPath(new URL('../nodes.json', import.meta.url)));
  // FIVE, not four: `lakewooechsmini` was added 2026-09-18 (nodes.json carries the
  // measurement that restored it), and this assertion had gone stale against the roster it
  // claims to check. A roster-count test that is not updated when the roster changes is a
  // test that fails for the wrong reason, so it is repaired here rather than worked around.
  assert.equal(config.nodes.length, 5);
  assert.deepEqual(
    config.nodes.map((entry) => entry.node).sort(),
    ['lakewooechsmini', 'secratary', 'zabz-tech', 'zabz-tech-linux', 'zabz-yoga-1'].sort(),
  );
  const laptop = config.nodes.find((entry) => entry.node === 'zabz-yoga-1');
  assert.equal(laptop.baseUrl, 'https://zabz-yoga-1.tail93e6e6.ts.net', 'the DNS label really is zabz-yoga-1');
  assert.equal(laptop.fqdn, 'zabz-yoga-1.tail93e6e6.ts.net');
  assert.equal(laptop.location, 'home');
  assert.equal(config.cacheTtlMs, DEFAULT_CACHE_TTL_MS);
  assert.equal(config.readTimeoutMs, DEFAULT_READ_TIMEOUT_MS);
});

test('I1/I6 the roster carries the retry, requestId and fleet-cap keys, and their defaults match the broker constants', () => {
  const config = loadConfig(fileURLToPath(new URL('../nodes.json', import.meta.url)));
  assert.equal(config.retryTimeoutMs, DEFAULT_RETRY_READ_TIMEOUT_MS);
  assert.equal(config.requestIdTtlMs, DEFAULT_REQUEST_ID_TTL_MS);
  assert.equal(config.fleetConcurrentLeaseCap, DEFAULT_FLEET_CONCURRENT_LEASE_CAP);
  // No drift between the roster defaults and the numbers the broker actually applies.
  assert.equal(config.requestIdTtlMs, REQUEST_ID_TTL_MS);
  assert.equal(config.fleetConcurrentLeaseCap, FLEET_CONCURRENT_LEASE_CAP);
  assert.equal(MAX_REQUEST_ID_ENTRIES, 256);

  const overridden = validateConfig({ nodes: [node()], retryTimeoutMs: 9000, requestIdTtlMs: 60_000, fleetConcurrentLeaseCap: 2 });
  assert.equal(overridden.retryTimeoutMs, 9000);
  assert.equal(overridden.requestIdTtlMs, 60_000);
  assert.equal(overridden.fleetConcurrentLeaseCap, 2);
  const junk = validateConfig({ nodes: [node()], retryTimeoutMs: -1, requestIdTtlMs: 'soon', fleetConcurrentLeaseCap: 0 });
  assert.equal(junk.retryTimeoutMs, DEFAULT_RETRY_READ_TIMEOUT_MS, 'a non-positive retry budget falls back to the default');
  assert.equal(junk.requestIdTtlMs, DEFAULT_REQUEST_ID_TTL_MS);
  assert.equal(junk.fleetConcurrentLeaseCap, DEFAULT_FLEET_CONCURRENT_LEASE_CAP);
});

test('§2.1 naming: the shipped roster obeys node == fqdn.split(".")[0] on every row', () => {
  const config = loadConfig(fileURLToPath(new URL('../nodes.json', import.meta.url)));
  for (const entry of config.nodes) {
    assert.equal(entry.node, dnsLabel(entry.fqdn), `${entry.node} must be the DNS label of ${entry.fqdn}`);
    assert.equal(entry.baseUrl, `https://${entry.fqdn}`, `${entry.node}'s baseUrl is its own gate`);
  }
  assert.equal(dnsLabel('zabz-yoga-1.tail93e6e6.ts.net'), 'zabz-yoga-1');
  assert.equal(dnsLabel(null), null);
});

test('§2.1 naming: a roster keyed on the HOST NAME or the ssh alias is refused at startup, loudly', () => {
  // The two live traps, as measured 2026-09-16: the laptop's host name is `zabz-yoga` while
  // its DNS name is `zabz-yoga-1`; the Linux box's ssh alias is `linux-pc` while its DNS
  // name is `zabz-tech-linux`. Both used to key a roster row and silently read nothing.
  assert.throws(
    () => validateConfig({ nodes: [node({ node: 'zabz-yoga', fqdn: 'zabz-yoga-1.tail93e6e6.ts.net', baseUrl: 'https://zabz-yoga-1.tail93e6e6.ts.net' })] }),
    /does not match the first label of its own fqdn/,
  );
  assert.throws(
    () => validateConfig({ nodes: [node({ node: 'linux-pc', fqdn: 'zabz-tech-linux.tail93e6e6.ts.net', baseUrl: 'https://zabz-tech-linux.tail93e6e6.ts.net' })] }),
    /does not match the first label of its own fqdn/,
  );
  // And a row with no fqdn at all cannot be checked, so it is refused rather than trusted.
  assert.throws(() => validateConfig({ nodes: [{ node: 'zabz-tech', baseUrl: 'https://zabz-tech.tail93e6e6.ts.net' }] }), /needs its fqdn/);
  // The correct spelling passes.
  assert.equal(validateConfig({ nodes: [node()] }).nodes[0].node, 'zabz-tech');
});

test('the per-node v1 transport capability keeps "measured broken" and "unmeasured" apart', () => {
  assert.deepEqual(normalizeDispatch(undefined), { v1: null, measuredAt: null, evidence: null }, 'no field means unmeasured, never false');
  assert.deepEqual(normalizeDispatch({ v1: true, measuredAt: '2026-09-16', evidence: 'three child turns completed' }), { v1: true, measuredAt: '2026-09-16', evidence: 'three child turns completed' });
  assert.equal(normalizeDispatch({ v1: false }).v1, false);
  assert.equal(normalizeDispatch({ v1: 'yes' }).v1, null, 'anything that is not true|false is unmeasured');

  const config = loadConfig(fileURLToPath(new URL('../nodes.json', import.meta.url)));
  const byName = Object.fromEntries(config.nodes.map((entry) => [entry.node, entry]));
  assert.equal(byName['zabz-tech'].dispatch.v1, true, 'measured working: S6 ran children there');
  assert.equal(byName['zabz-yoga-1'].dispatch.v1, true, 'measured working again: S6 fixed the reparse-point trust and a full dispatch to it completed exit 0');
  assert.ok(byName['zabz-yoga-1'].dispatch.evidence.includes('reparse-point'));
  assert.equal(byName['secratary'].dispatch.v1, null, 'unmeasured stays unmeasured - not a claim in either direction');
  // RESTORED TO true 2026-09-17 (docs/mesh/104-node-enabled.md). The `false` this assertion
  // carried from 2026-09-17T14:00Z was correct and is not being quietly flipped: it answered the
  // question "can a child placed here run, through the invocation the dispatcher ACTUALLY runs",
  // and then that invocation was corrected - `plugin-remote-fanout/lib/nodes.js` invokes the
  // node's `dsh` executor by name (which sources `/etc/dsh-worker.env` itself) instead of the
  // explicit `nodeExe` + `bin.js` pair that named a path which does not exist on the machine.
  // Both conditions the false row named are therefore met, and the restoring measurement is a
  // real child through the whole dispatcher: `MESH-HOST: zabz-tech-linux`, exit 0.
  assert.equal(
    byName['zabz-tech-linux'].dispatch.v1,
    true,
    'measured 2026-09-17: the dispatcher row was corrected to invoke the `dsh` executor by name, and a real child dispatched through `mesh-run` returned MESH-HOST: zabz-tech-linux with childHosts ["zabz-tech-linux"], disagreements [] and exit 0 - where the same command before the fix exited 1 with `sh: 6: /home/zabz/.local/node-v24.12.0-linux-x64/bin/node: not found`. The evidence field carries every command and its result',
  );
  assert.ok(byName['zabz-tech-linux'].dispatch.evidence.includes('no Node runtime yet'), 'the evidence names the stale note it corrects');
  assert.ok(byName['zabz-tech-linux'].dispatch.evidence.includes('MESH-HOST: zabz-tech-linux'), 'and carries the live dispatch that restored the flag');
  assert.ok(byName['zabz-tech-linux'].dispatch.evidence.includes('SET BACK TO false'), 'and what would revoke it again - a capability is a dated measurement in both directions');
  assert.ok(byName['zabz-tech-linux'].dispatch.evidence.includes("command: 'dsh'"), 'and names the corrected invocation - the executor by name, not an interpreter pair');
});

test('an empty roster is refused with a reason, at startup, not at placement time', () => {
  assert.throws(() => validateConfig({ nodes: [] }), /non-empty array/);
  assert.throws(() => validateConfig({}), /non-empty array/);
  assert.throws(() => validateConfig(null), /must be a JSON object/);
});

test('a bad node entry is refused with the reason and the node named', () => {
  assert.throws(() => validateConfig({ nodes: [{ node: '', baseUrl: 'https://x' }] }), /non-empty string/);
  assert.throws(() => validateConfig({ nodes: [{ node: 'a' }] }), /absolute http\(s\) baseUrl/);
  assert.throws(() => validateConfig({ nodes: [{ node: 'a', baseUrl: 'ftp://x' }] }), /absolute http\(s\) baseUrl/);
  assert.throws(
    () => validateConfig({ nodes: [node(), node()] }),
    /appears twice/,
  );
});

test('a missing or unparseable roster file fails loudly', () => {
  const missing = path.join(tmpdir(), 'mesh-broker-does-not-exist', 'nodes.json');
  assert.throws(() => loadConfig(missing), /cannot read the roster/);
  const { dir, file } = scratchFile('{ not json');
  try {
    assert.throws(() => loadConfig(file), /not valid JSON/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('unknown extras on a node are kept off the object, and a switched-off node is marked', () => {
  const config = validateConfig({
    nodes: [{ node: 'lakewooechsmini', baseUrl: 'https://lakewooechsmini.tail93e6e6.ts.net/', fqdn: 'lakewooechsmini.tail93e6e6.ts.net', excluded: true, whatever: 1 }],
  });
  assert.equal(config.nodes[0].baseUrl, 'https://lakewooechsmini.tail93e6e6.ts.net', 'trailing slash trimmed');
  assert.equal(config.nodes[0].excluded, true);
  assert.equal(config.nodes[0].index, 0);
});
