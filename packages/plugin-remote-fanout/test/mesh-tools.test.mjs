import assert from 'node:assert/strict';
import { mkdtempSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { createChildRegistry } from '../lib/child-registry.js';
import { meshToolDefinitions, registerMeshTools } from '../lib/mesh-tools.js';

const tempDir = () => mkdtempSync(path.join(os.tmpdir(), 'fanout-tools-'));

/**
 * A registry with one live child, plus a fake `runRemote` that records every ssh
 * program and answers reads with a canned outbox. Nothing here touches a node:
 * the whole point of the tool layer is that it can be exercised hermetically.
 */
function harness({ outbox = '', fail = false } = {}) {
  const registry = createChildRegistry({ dir: tempDir() });
  registry.create('remote-1', {
    node: 'zabz-tech',
    ssh: 'desktop-ts',
    shell: 'posix',
    dshHome: '/home/zabz/.dsh',
    lease: 'lease-1',
    inbox: '/home/zabz/.dsh/mesh/children/remote-1/inbox.jsonl',
    outbox: '/home/zabz/.dsh/mesh/children/remote-1/outbox.jsonl',
    state: 'running',
    createdAt: new Date(Date.now() - 60_000).toISOString(),
    updatedAt: new Date(Date.now() - 60_000).toISOString(),
    host: 'ZABZ-TECH',
  });
  const calls = [];
  const runRemote = async (request) => {
    calls.push(request);
    if (fail) return { ok: false, exitCode: 255, stdout: '', stderr: 'ssh: connect: Connection refused' };
    return { ok: true, exitCode: 0, stdout: outbox, stderr: '' };
  };
  const definitions = meshToolDefinitions({ registry, runRemote });
  const tool = (name) => definitions.find((definition) => definition.name === name);
  return { registry, calls, definitions, tool };
}

test('four tools are defined with the mesh_ names, and each renders text', () => {
  const { definitions } = harness();
  assert.deepEqual(definitions.map((d) => d.name).sort(), ['mesh_children', 'mesh_collect', 'mesh_interrupt', 'mesh_message']);
  for (const definition of definitions) {
    assert.equal(typeof definition.execute, 'function');
    assert.equal(typeof definition.output.render, 'function');
  }
});

test('mesh_children lists node, state, age, lease, last host and where the answer lands', async () => {
  const { tool } = harness();
  const rows = await tool('mesh_children').execute({}, {});
  assert.equal(rows.children.length, 1);
  const row = rows.children[0];
  assert.equal(row.id, 'remote-1');
  assert.equal(row.node, 'zabz-tech');
  assert.equal(row.state, 'running');
  assert.equal(row.lease, 'lease-1');
  assert.equal(row.host, 'ZABZ-TECH');
  assert.match(row.outbox, /remote-1\/outbox\.jsonl$/);
  assert.ok(row.ageMs >= 59_000, `ageMs should be about a minute, was ${row.ageMs}`);
  const text = tool('mesh_children').output.render({}, rows).map((b) => b.text).join('\n');
  assert.match(text, /remote-1/);
  assert.match(text, /answer lands in .*outbox\.jsonl/);
});

test('mesh_children filters by state and parent, and never renders a blank card', async () => {
  const { tool, registry } = harness();
  registry.create('remote-2', { node: 'secratary', state: 'settled', parentSessionId: 'parent-9' });
  const settled = await tool('mesh_children').execute({ state: 'settled' }, {});
  assert.deepEqual(settled.children.map((r) => r.id), ['remote-2']);
  const byParent = await tool('mesh_children').execute({ parentSessionId: 'parent-9' }, {});
  assert.deepEqual(byParent.children.map((r) => r.id), ['remote-2']);
  const none = await tool('mesh_children').execute({ state: 'nope' }, {});
  const text = tool('mesh_children').output.render({}, none).map((b) => b.text).join('\n');
  assert.notEqual(text.trim(), '');
  assert.match(text, /no mesh children/i);
});

test('mesh_message appends to the target inbox over ssh and says it is read at the next checkpoint', async () => {
  const { tool, calls } = harness();
  const result = await tool('mesh_message').execute({ child_id: 'remote-1', message: 'please widen the sweep' }, {});
  assert.equal(result.delivered, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].ssh, 'desktop-ts');
  assert.equal(calls[0].shell, 'posix');
  assert.match(calls[0].script, /\/home\/zabz\/\.dsh\/mesh\/children\/remote-1\/inbox\.jsonl/);
  assert.match(calls[0].script, /please widen the sweep/);
  assert.match(calls[0].script, /mkdir -p/);
  assert.match(result.message, /next checkpoint/i);
  assert.match(result.message, /not instant/i);
});

test('mesh_message reports a delivery that did not happen instead of claiming success', async () => {
  const { tool } = harness({ fail: true });
  const result = await tool('mesh_message').execute({ child_id: 'remote-1', message: 'x' }, {});
  assert.equal(result.delivered, false);
  assert.match(result.message, /not delivered/i);
  assert.match(result.message, /Connection refused/);
});

test('mesh_interrupt writes a stop request to the same inbox and marks the registry', async () => {
  const { tool, calls, registry } = harness();
  const result = await tool('mesh_interrupt').execute({ child_id: 'remote-1', reason: 'parent needs the node' }, {});
  assert.equal(result.requested, true);
  assert.equal(calls.length, 1);
  assert.match(calls[0].script, /inbox\.jsonl/);
  assert.match(calls[0].script, /stop/);
  assert.match(calls[0].script, /parent needs the node/);
  assert.equal(registry.get('remote-1').state, 'stopping');
});

test('mesh_collect reads the child outbox from the target and works with no live transport', async () => {
  const { tool, calls } = harness({ outbox: 'progress 1\nprogress 2\nDONE=SWEPT-THE-LOG\n' });
  const result = await tool('mesh_collect').execute({ child_id: 'remote-1' }, {});
  assert.equal(result.ok, true);
  assert.equal(calls.length, 1);
  assert.match(calls[0].script, /outbox\.jsonl/);
  assert.deepEqual(result.lines, ['progress 1', 'progress 2', 'DONE=SWEPT-THE-LOG']);
  assert.match(result.text, /DONE=SWEPT-THE-LOG/);
});

test('an unknown child is a legible refusal, never a crash', async () => {
  const { tool } = harness();
  const message = await tool('mesh_message').execute({ child_id: 'nope', message: 'x' }, {});
  assert.equal(message.delivered, false);
  assert.match(message.message, /no record for child "nope"/i);
  const collected = await tool('mesh_collect').execute({ child_id: 'nope' }, {});
  assert.equal(collected.ok, false);
  assert.match(collected.text, /no record for child "nope"/i);
});

test('registerMeshTools registers all four into the tools service and disposes them', () => {
  const registered = [];
  const ctx = { tools: { register: (definition) => { registered.push(definition.name); return () => {}; } } };
  const { registry } = harness();
  const dispose = registerMeshTools(ctx, { registry, runRemote: async () => ({ ok: true, exitCode: 0, stdout: '' }) });
  assert.deepEqual(registered.sort(), ['mesh_children', 'mesh_collect', 'mesh_interrupt', 'mesh_message']);
  assert.equal(typeof dispose, 'function');
  assert.doesNotThrow(() => dispose());
});
