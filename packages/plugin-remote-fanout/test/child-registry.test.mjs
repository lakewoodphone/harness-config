import assert from 'node:assert/strict';
import { mkdtempSync, readdirSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { createChildRegistry, meshChildPaths } from '../lib/child-registry.js';

const tempDir = () => mkdtempSync(path.join(os.tmpdir(), 'fanout-registry-'));

test('create() records the child identity, and patch() merges without losing earlier fields', () => {
  const registry = createChildRegistry({ dir: tempDir() });
  const created = registry.create('remote-1', { node: 'zabz-tech', ssh: 'desktop-ts', lease: 'L1', state: 'dispatching' });
  assert.equal(created.id, 'remote-1');
  assert.equal(created.node, 'zabz-tech');
  assert.equal(created.createdAt, created.updatedAt);

  const patched = registry.patch('remote-1', { state: 'settled', host: 'ZABZ-TECH', stopReason: 'completed' });
  assert.equal(patched.state, 'settled');
  assert.equal(patched.node, 'zabz-tech', 'a patch must not drop fields it did not name');
  assert.equal(patched.lease, 'L1');
  assert.equal(patched.createdAt, created.createdAt, 'createdAt is written once');
  assert.notEqual(patched.updatedAt, undefined);

  assert.deepEqual(registry.get('remote-1'), patched);
  assert.equal(registry.get('nobody'), undefined);
});

test('patch() creates a record for an id it has never seen — a patch after a restart is not lost', () => {
  const registry = createChildRegistry({ dir: tempDir() });
  const record = registry.patch('remote-ghost', { state: 'settled', node: 'secratary' });
  assert.equal(record.id, 'remote-ghost');
  assert.equal(record.state, 'settled');
  assert.equal(registry.get('remote-ghost').node, 'secratary');
});

test('list() filters by field and sorts oldest first', () => {
  const registry = createChildRegistry({ dir: tempDir() });
  registry.create('a', { node: 'n1', state: 'running' });
  registry.create('b', { node: 'n2', state: 'settled' });
  registry.create('c', { node: 'n1', state: 'settled' });

  assert.deepEqual(registry.list().map((r) => r.id), ['a', 'b', 'c']);
  assert.deepEqual(registry.list({ state: 'settled' }).map((r) => r.id), ['b', 'c']);
  assert.deepEqual(registry.list({ node: 'n1' }).map((r) => r.id), ['a', 'c']);
  assert.deepEqual(registry.list({ node: 'n1', state: 'running' }).map((r) => r.id), ['a']);
  assert.deepEqual(registry.list({ node: 'absent' }), []);
});

test('the registry survives a restart: a second instance on the same directory reads the same records', () => {
  const dir = tempDir();
  const first = createChildRegistry({ dir });
  first.create('remote-persist', {
    node: 'zabz-yoga',
    ssh: 'laptop-ts',
    lease: 'lease-7',
    inbox: '/home/zabz/.dsh/mesh/children/remote-persist/inbox.jsonl',
    outbox: '/home/zabz/.dsh/mesh/children/remote-persist/outbox.jsonl',
    state: 'dispatching',
  });
  first.patch('remote-persist', { state: 'running', host: 'ZABZ-YOGA' });

  // A fresh process, a fresh instance, the same DSH_HOME directory.
  const second = createChildRegistry({ dir });
  const record = second.get('remote-persist');
  assert.equal(record.node, 'zabz-yoga');
  assert.equal(record.state, 'running');
  assert.equal(record.host, 'ZABZ-YOGA');
  assert.equal(record.lease, 'lease-7');
  assert.match(record.outbox, /outbox\.jsonl$/);
});

test('writes are atomic and leave no temp file behind', () => {
  const dir = tempDir();
  const registry = createChildRegistry({ dir });
  registry.create('remote-atomic', { state: 'one' });
  registry.patch('remote-atomic', { state: 'two' });
  registry.patch('remote-atomic', { state: 'three' });
  const leftovers = readdirSync(dir).filter((name) => name.includes('.tmp'));
  assert.deepEqual(leftovers, [], 'a crashed reader must never see a half-written record');
  assert.deepEqual(readdirSync(dir), ['remote-atomic.json']);
});

test('the registry NEVER throws — an unwritable directory returns the record and admits nothing is durable', () => {
  const dir = tempDir();
  const blocked = path.join(dir, 'not-a-directory');
  writeFileSync(blocked, 'this is a file, not a children directory');
  const registry = createChildRegistry({ dir: blocked });
  assert.doesNotThrow(() => registry.create('remote-x', { node: 'n' }));
  assert.doesNotThrow(() => registry.patch('remote-x', { state: 'settled' }));
  assert.doesNotThrow(() => registry.list());
  assert.equal(registry.get('remote-x'), undefined, 'nothing was durable, and it says so by returning nothing');
});

test('inboxPath()/outboxPath() return the recorded target paths, and meshChildPaths derives them', () => {
  const registry = createChildRegistry({ dir: tempDir() });
  const paths = meshChildPaths({ dshHome: '/home/zabz/.dsh', id: 'remote-p', shell: 'posix' });
  registry.create('remote-p', { inbox: paths.inbox, outbox: paths.outbox });
  assert.equal(registry.inboxPath('remote-p'), paths.inbox);
  assert.equal(registry.outboxPath('remote-p'), paths.outbox);
  assert.equal(registry.inboxPath('absent'), undefined);
  assert.equal(registry.outboxPath('absent'), undefined);
  assert.equal(paths.dir, '/home/zabz/.dsh/mesh/children/remote-p');
});
