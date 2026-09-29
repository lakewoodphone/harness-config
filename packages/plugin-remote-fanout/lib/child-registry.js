/**
 * The durable child registry — one JSON file per mesh child (R3, D2).
 *
 * WHY THIS EXISTS AT ALL
 * The engine gives an out-of-process child no `localAgent`: `list_agents` shows
 * nothing, `send_message`/`interrupt_agent` cannot address it, and the Subagents
 * UI is empty. The native fix is an engine Activation-ownership contract, which
 * is written up with file and function names in
 * `docs/mesh/120-continuable-mesh-children.md` and is deliberately NOT redone
 * here. This registry is the plugin's own durable identity for a child instead:
 * it lives under `$DSH_HOME/mesh/children/`, survives the process that wrote it,
 * and is what `mesh_children`/`mesh_message`/`mesh_interrupt`/`mesh_collect`
 * read. It is also how work survives a severed transport (P2538b): the child's
 * outbox path is recorded before the child starts, so the answer can be
 * collected long after the ssh client that ran it has died.
 *
 * SHAPE
 *   * One file per child: `<safe-id>.json`.
 *   * Atomic writes: a temp file in the same directory, then a rename. A reader
 *     never sees a half-written record, and a crash leaves no usable partial.
 *   * NEVER throws. A registry that cannot be written is a warning and an
 *     in-memory answer; it must not be able to change a child's outcome (R4).
 *   * Dependency-free: `node:fs`, `node:path`, `node:os` only, so it is
 *     unit-testable against a temp directory with nothing else mounted.
 *
 * API: `create(id, patch)`, `patch(id, patch)`, `get(id)`, `list(filter)`, plus
 * the `inboxPath(id)`/`outboxPath(id)` helpers and the exported pure
 * `meshChildPaths` (re-exported from `remote-script.js`).
 */

import { mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export { meshChildPaths } from './remote-script.js';

/** Where the per-child records live for one DSH_HOME. */
export function defaultChildRegistryDir(dshHome) {
  const home = typeof dshHome === 'string' && dshHome.trim() !== ''
    ? dshHome
    : (process.env.DSH_HOME || path.join(os.homedir(), '.dsh'));
  return path.join(home, 'mesh', 'children');
}

/** Keep a child id usable as a file name without ever throwing on a bad one. */
function safeId(id) {
  return String(id ?? 'child').replace(/[^A-Za-z0-9._-]/g, '_').slice(0, 160) || 'child';
}

/** Apply a `list(filter)` filter: an object of exact field matches, or a function. */
function applyFilter(records, filter) {
  if (filter === undefined || filter === null) return records;
  if (typeof filter === 'function') return records.filter(filter);
  const entries = Object.entries(filter);
  if (entries.length === 0) return records;
  return records.filter((record) => entries.every(([key, value]) => record?.[key] === value));
}

/**
 * Build one registry over one directory.
 *
 * @param {object} [options]
 * @param {string} [options.dir] the children directory (default `$DSH_HOME/mesh/children`)
 * @param {object} [options.logger] only `warn` is used, and only on a failed write
 * @param {() => string} [options.now] clock injection for deterministic tests
 */
export function createChildRegistry({ dir, logger, now } = {}) {
  const root = typeof dir === 'string' && dir.trim() !== '' ? dir : defaultChildRegistryDir();
  const clock = typeof now === 'function' ? now : () => new Date().toISOString();
  let counter = 0;

  const fileFor = (id) => path.join(root, `${safeId(id)}.json`);

  /** Read one record, or undefined. A corrupt file reads as absent, never as an error. */
  const read = (id) => {
    try {
      const parsed = JSON.parse(readFileSync(fileFor(id), 'utf8'));
      return parsed !== null && typeof parsed === 'object' ? parsed : undefined;
    } catch {
      return undefined;
    }
  };

  /** Atomic write. Returns whether the record is durable; never throws. */
  const write = (record) => {
    try {
      mkdirSync(root, { recursive: true });
      counter += 1;
      const target = fileFor(record.id);
      const temp = `${target}.tmp-${process.pid}-${counter}`;
      writeFileSync(temp, `${JSON.stringify(record)}\n`, 'utf8');
      renameSync(temp, target);
      return true;
    } catch (error) {
      logger?.warn?.(`remote-fanout: the child registry could not write ${record?.id}: ${String(error?.message ?? error)}`);
      return false;
    }
  };

  /**
   * The single merge primitive behind both `create` and `patch`. `create` and
   * `patch` are the same operation on purpose: a patch that arrives after a
   * restart (or for a record whose create was lost) must still produce a record
   * rather than being silently dropped. `createdAt` is written exactly once.
   */
  const merge = (id, patch) => {
    const existing = read(id);
    const at = clock();
    const record = {
      ...(existing ?? {}),
      ...(patch ?? {}),
      id: existing?.id ?? String(id ?? patch?.id ?? ''),
      createdAt: existing?.createdAt ?? patch?.createdAt ?? at,
      updatedAt: at,
    };
    write(record);
    return record;
  };

  return {
    /** The directory these records live in. */
    dir: root,

    /** Seed a child record. Never throws; returns the merged record even if the write failed. */
    create(id, patch) {
      return merge(id, patch);
    },

    /** Merge a patch into a record, creating it if this is the first word. Never throws. */
    patch(id, patch) {
      return merge(id, patch);
    },

    /** One record, or undefined. */
    get(id) {
      return read(id);
    },

    /**
     * Every record, filtered by exact field matches (`{ state: 'running' }`) or a
     * predicate. Sorted oldest first so a listing reads in the order children
     * were created. A corrupt record is skipped, never thrown.
     */
    list(filter) {
      let names;
      try {
        names = readdirSync(root);
      } catch {
        return [];
      }
      const records = [];
      for (const name of names) {
        if (!name.endsWith('.json') || name.includes('.tmp')) continue;
        try {
          const parsed = JSON.parse(readFileSync(path.join(root, name), 'utf8'));
          if (parsed !== null && typeof parsed === 'object') records.push(parsed);
        } catch {
          // A corrupt record is a row this registry cannot speak for; skipping it
          // is the only honest option and it is not a reason to fail a listing.
        }
      }
      return applyFilter(records, filter)
        .sort((a, b) => String(a.createdAt ?? '').localeCompare(String(b.createdAt ?? ''))
          || String(a.id ?? '').localeCompare(String(b.id ?? '')));
    },

    /** The child's inbox path ON THE TARGET, or undefined when it was not recorded. */
    inboxPath(id) {
      return read(id)?.inbox;
    },

    /** The child's outbox path ON THE TARGET, or undefined when it was not recorded. */
    outboxPath(id) {
      return read(id)?.outbox;
    },
  };
}
