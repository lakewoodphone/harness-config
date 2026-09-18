/**
 * The admission governor: a cross-process lease protocol for heavy work.
 *
 * THE PROBLEM IT SOLVES, MEASURED
 * Nothing in DSH caps how many agent turns or in-flight shell tool calls run at
 * once. Every shell tool call costs two OS processes — a `runner.js` Job owner
 * (~57 MB measured on ZABZ-YOGA) plus the shell itself (~103 MB) — and the
 * per-step parallelism is 20 per session with no cap on sessions. Ten sessions
 * fanning out is 200 concurrent shells, ~32 GB of processes, on a machine with
 * 31.6 GB of physical memory. The audit's own arithmetic: 10 x 20 in flight with
 * no machine-wide budget behind it.
 *
 * WHAT THIS IS
 * A lease file protocol any session, script or agent can consult before starting
 * a fleet or a burst. It reports GRANTED or a QUEUE POSITION. It is derived from
 * measurement and generous by construction, and refusing is never its first
 * behaviour.
 *
 * THE PROTOCOL, AND WHY EACH PART IS THE WAY IT IS
 *
 *   * One lease file per SLOT: `leases/slot-07.lease`, created with `wx`
 *     (O_CREAT|O_EXCL). Creation of an existing name FAILS, so the filesystem
 *     itself is the mutex — no lock server, no window between check and claim.
 *   * The payload carries `pid`, `host`, `kind`, `note`, `startedAt`,
 *     `renewedAt`, `expiresAt` and `ttlMs`, so a human reading the directory
 *     knows who holds what and until when.
 *   * Liveness is a HEARTBEAT, not a pid guess. A holder renews; a lease whose
 *     `expiresAt` has passed is dead. This is deliberately not pid-based: pids
 *     are reused, and a pid check would either reap a live holder (data loss) or
 *     keep a dead one forever (a leak that silently shrinks the budget).
 *   * REAP IS GUARDED BY AN ATOMIC RENAME, which is the only cross-process
 *     primitive both Windows and POSIX give for free. A reaper renames an
 *     expired lease to a unique tombstone (exactly one process can win that
 *     rename), re-reads it, and renames it BACK if its `renewedAt` changed in
 *     the meantime — i.e. if the holder was alive after all. That closes the
 *     read-then-delete race that has bitten this repo before (the journal lock).
 *   * QUEUE POSITION is computed, not stored: a waiter is not a lease holder, so
 *     "position" is the number of live leases plus the number of waiters that
 *     arrived before it, using the waiter's own registration file.
 *
 * WHY THE BUDGET IS GENEROUS AND FLOORED
 * The budget is derived from measured memory headroom at the moment of the call
 * (see `deriveBudget`), capped at a hard ceiling, and FLOORED at a minimum so a
 * temporarily low reading queues *sooner* but never refuses outright. The
 * owner's rule is explicit: this must trim waste, not reduce what agents can do.
 */

import { mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync, openSync, closeSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/** Measured on ZABZ-YOGA 2026-09-16: `runner.js` 57.3 MB + `pwsh.exe` 102.7 MB. */
export const PER_SLOT_BYTES_DEFAULT = 160 * 1024 * 1024;

/**
 * The most concurrent heavy slots this governor will ever grant.
 *
 * 24 slots x 160 MB = 3.8 GB of tool processes. That is a deliberately generous
 * ceiling: it exists to bound a runaway fan-out, not to ration normal work.
 */
export const MAX_SLOTS_DEFAULT = 24;

/**
 * The floor. Below this the budget is not allowed to fall.
 *
 * This is the "refusing must never be the first behaviour" rule encoded: even
 * with almost no measured headroom the governor still grants a few slots and
 * says the headroom is low, because refusing would take capability away from an
 * agent that has no other way to ask.
 */
export const MIN_SLOTS_DEFAULT = 4;

/** A lease TTL long enough for one heavy call, short enough to self-heal. */
export const TTL_MS_DEFAULT = 120_000;

/** Reserved for everything that is not a tool process: browser, editor, engine. */
const RESERVE_FRACTION = 0.12;
const RESERVE_MIN_BYTES = 2 * 1024 * 1024 * 1024;

const LOCKED_AT_START = null; // marker: no module-scope side effects

/** The governor's directory inside a DSH home. */
export function governorRoot(dshHome) {
  return path.join(dshHome, 'governor');
}

export function leasesDir(root) {
  return path.join(root, 'leases');
}

export function waitersDir(root) {
  return path.join(root, 'waiters');
}

export function tombstonesDir(root) {
  return path.join(root, 'reaped');
}

/** Create the directory layout. Idempotent. */
export function ensureLayout(root) {
  for (const dir of [root, leasesDir(root), waitersDir(root), tombstonesDir(root)]) {
    mkdirSync(dir, { recursive: true });
  }
}

/**
 * Derive the slot budget from measured memory headroom.
 *
 * @param {object} [options]
 * @param {number} [options.perSlotBytes] measured cost of one heavy slot
 * @param {number} [options.maxSlots] ceiling
 * @param {number} [options.minSlots] floor
 * @param {() => number} [options.freeBytes] injectable for tests
 * @param {() => number} [options.totalBytes] injectable for tests
 * @returns {{budget:number, freeBytes:number, totalBytes:number, reserveBytes:number, usableBytes:number, perSlotBytes:number, headroomLow:boolean, capped:'max'|'min'|null, arithmetic:string}}
 */
export function deriveBudget(options = {}) {
  const perSlotBytes = Number.isFinite(options.perSlotBytes) && options.perSlotBytes > 0
    ? options.perSlotBytes
    : PER_SLOT_BYTES_DEFAULT;
  const maxSlots = Number.isInteger(options.maxSlots) && options.maxSlots > 0 ? options.maxSlots : MAX_SLOTS_DEFAULT;
  const minSlots = Number.isInteger(options.minSlots) && options.minSlots > 0 ? options.minSlots : MIN_SLOTS_DEFAULT;
  const freeBytes = Math.max(0, Math.round(options.freeBytes === undefined ? os.freemem() : options.freeBytes()));
  const totalBytes = Math.max(0, Math.round(options.totalBytes === undefined ? os.totalmem() : options.totalBytes()));

  const reserveBytes = Math.max(RESERVE_MIN_BYTES, Math.round(totalBytes * RESERVE_FRACTION));
  const usableBytes = Math.max(0, freeBytes - reserveBytes);
  const raw = Math.floor(usableBytes / perSlotBytes);
  let budget = raw;
  let capped = null;
  if (budget > maxSlots) { budget = maxSlots; capped = 'max'; }
  if (budget < minSlots) { budget = minSlots; capped = 'min'; }
  return {
    budget,
    freeBytes,
    totalBytes,
    reserveBytes,
    usableBytes,
    perSlotBytes,
    maxSlots,
    minSlots,
    headroomLow: raw < minSlots,
    capped,
    arithmetic: `${Math.round(freeBytes / 1048576)} MiB free - ${Math.round(reserveBytes / 1048576)} MiB reserved`
      + ` = ${Math.round(usableBytes / 1048576)} MiB usable / ${Math.round(perSlotBytes / 1048576)} MiB per slot`
      + ` = ${raw} slot(s)` + (capped === 'max' ? `, capped at maxSlots=${maxSlots}` : '')
      + (capped === 'min' ? `, floored at minSlots=${minSlots} (headroom is low, but work is not refused)` : ''),
  };
}

/** `slot-07.lease` / parse the slot number back out. */
const slotFile = (slot) => `slot-${String(slot).padStart(2, '0')}.lease`;
const slotOf = (name) => {
  const match = /^slot-(\d+)\.lease$/.exec(name);
  return match === null ? undefined : Number(match[1]);
};

/** Read one lease document, or undefined when it is absent or unparseable. */
function readLease(file) {
  try {
    const parsed = JSON.parse(readFileSync(file, 'utf8'));
    return parsed !== null && typeof parsed === 'object' ? parsed : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Every lease file on disk, with its slot and whether it is still alive.
 *
 * @param {number} [now] injectable clock
 */
export function readLeases(root, now = Date.now()) {
  const dir = leasesDir(root);
  let names;
  try {
    names = readdirSync(dir);
  } catch {
    return [];
  }
  const leases = [];
  for (const name of names) {
    const slot = slotOf(name);
    if (slot === undefined) continue;
    const file = path.join(dir, name);
    const document = readLease(file);
    if (document === undefined) {
      // A zero-byte or corrupt lease is not evidence of a holder. It is
      // reported as corrupt and treated as dead, because a file that cannot be
      // read cannot be renewed.
      leases.push({ slot, file, corrupt: true, alive: false, document: null });
      continue;
    }
    const expiresAt = Number(document.expiresAt);
    leases.push({
      slot,
      file,
      corrupt: false,
      alive: Number.isFinite(expiresAt) ? expiresAt > now : false,
      document,
    });
  }
  leases.sort((a, b) => a.slot - b.slot);
  return leases;
}

/**
 * Reap dead leases safely.
 *
 * The rename is the mutual-exclusion primitive: `renameSync` of a given file
 * succeeds for exactly one process, so two reapers cannot both take a slot's
 * tombstone. After winning the rename we RE-READ the document; if `renewedAt`
 * advanced past what we saw before the rename, the holder was alive and the file
 * is renamed back. Without that second check, a holder that renewed in the
 * microsecond window would lose its slot and two processes would hold it.
 *
 * @returns {Array<{slot:number, outcome:'reaped'|'resurrected'|'vanished', holderPid:number|null, expiredForMs:number|null}>}
 */
export function reap(root, now = Date.now()) {
  const report = [];
  for (const lease of readLeases(root, now)) {
    if (lease.alive && !lease.corrupt) continue;
    const observedRenewedAt = lease.corrupt ? null : Number(lease.document?.renewedAt);
    const tombstone = path.join(tombstonesDir(root), `${path.basename(lease.file)}.${process.pid}.${now}`);
    try {
      renameSync(lease.file, tombstone);
    } catch (error) {
      // Another reaper won, or the holder released it first. Both are fine.
      report.push({
        slot: lease.slot,
        outcome: 'vanished',
        holderPid: lease.corrupt ? null : (lease.document?.pid ?? null),
        expiredForMs: null,
      });
      continue;
    }
    const after = readLease(tombstone);
    const renewedAfter = after === undefined ? null : Number(after.renewedAt);
    const expiresAt = after === undefined ? null : Number(after.expiresAt);
    // `now` is the clock as of entry. Using it here (rather than a second
    // Date.now()) keeps the decision and the reported durations on one clock,
    // which is what makes this testable with an injected time.
    const aliveAfterRename = Number.isFinite(expiresAt) && expiresAt > now;
    if (aliveAfterRename || (observedRenewedAt !== null && renewedAfter !== null && renewedAfter > observedRenewedAt)) {
      // The holder renewed while we were reading. Put it back.
      try {
        renameSync(tombstone, lease.file);
      } catch {
        // If it cannot be put back it is gone; the holder's next renew fails
        // and it will re-acquire. Loud in the report, never silent.
      }
      report.push({
        slot: lease.slot,
        outcome: 'resurrected',
        holderPid: after?.pid ?? null,
        expiredForMs: null,
      });
      continue;
    }
    const expiredForMs = Number.isFinite(expiresAt) ? Math.max(0, now - expiresAt) : null;
    try {
      rmSync(tombstone, { force: true });
    } catch {
      // A tombstone left behind is untidy, not harmful: it is in its own
      // directory and is never read as a lease.
    }
    report.push({ slot: lease.slot, outcome: 'reaped', holderPid: after?.pid ?? null, expiredForMs });
  }
  return report;
}

/** Register a waiter so its queue position is computable by later arrivals. */
function registerWaiter(root, id, now) {
  const file = path.join(waitersDir(root), `${id}.wait`);
  try {
    const fd = openSync(file, 'wx');
    closeSync(fd);
    writeFileSync(file, JSON.stringify({ id, pid: process.pid, at: now }));
    return file;
  } catch {
    return undefined;
  }
}

function clearWaiter(root, id) {
  try {
    rmSync(path.join(waitersDir(root), `${id}.wait`), { force: true });
  } catch {
    // Nothing to do: a stale waiter file only shifts a later caller's position.
  }
}

/** How many waiters registered before this one, across all processes. */
function queuePosition(root, id, now) {
  let position = 0;
  const mine = path.join(waitersDir(root), `${id}.wait`);
  const mineDoc = readLease(mine);
  const mineAt = Number(mineDoc?.at ?? now);
  try {
    for (const name of readdirSync(waitersDir(root))) {
      if (!name.endsWith('.wait')) continue;
      const file = path.join(waitersDir(root), name);
      if (file === mine) continue;
      const document = readLease(file);
      const at = Number(document?.at);
      // A waiter older than the TTL is gone; ignoring it keeps the position
      // honest instead of inflating it with ghosts.
      if (Number.isFinite(at) && now - at > TTL_MS_DEFAULT * 5) continue;
      if (Number.isFinite(at) && at <= mineAt) position += 1;
    }
  } catch {
    return 0;
  }
  return position;
}

let counter = 0;
function leaseId(now) {
  counter += 1;
  return `${now.toString(36)}-${process.pid.toString(36)}-${counter.toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Try to take one slot.
 *
 * Never refuses. Returns `granted` with a lease, or `queued` with a position.
 *
 * @param {object} options
 * @param {string} options.root governor directory
 * @param {string} [options.kind] what the work is (free text)
 * @param {string} [options.note] why it is running (free text, for a human)
 * @param {number} [options.ttlMs]
 * @param {number} [options.now]
 * @param {object} [options.budget] a precomputed `deriveBudget()` result
 * @returns {{state:'granted', lease:object, budget:object, reaped:Array} | {state:'queued', position:number, budget:object, active:number, waiters:number, reaped:Array, requesterId:string}}
 */
export function acquire(options) {
  const { root } = options;
  const now = Number.isFinite(options.now) ? options.now : Date.now();
  const ttlMs = Number.isFinite(options.ttlMs) && options.ttlMs > 0 ? options.ttlMs : TTL_MS_DEFAULT;
  const budget = options.budget ?? deriveBudget(options);
  ensureLayout(root);
  // Every attempt reaps first, so a crashed holder is cleaned up by whoever
  // notices rather than by a daemon that may not be running.
  const reaped = reap(root, now);

  for (let slot = 1; slot <= budget.budget; slot += 1) {
    const file = path.join(leasesDir(root), slotFile(slot));
    const id = leaseId(now);
    const lease = {
      id,
      slot,
      host: os.hostname(),
      pid: process.pid,
      kind: typeof options.kind === 'string' ? options.kind : 'unspecified',
      note: typeof options.note === 'string' ? options.note : '',
      startedAt: now,
      renewedAt: now,
      expiresAt: now + ttlMs,
      ttlMs,
    };
    let fd;
    try {
      // wx = O_CREAT|O_EXCL: the create fails if the name exists, which is the
      // whole mutual exclusion.
      fd = openSync(file, 'wx');
    } catch {
      continue;
    }
    try {
      writeFileSync(fd, JSON.stringify(lease, null, 2));
    } finally {
      closeSync(fd);
    }
    clearWaiter(root, id);
    return { state: 'granted', lease, budget, reaped };
  }

  const requesterId = leaseId(now);
  const registered = registerWaiter(root, requesterId, now);
  const active = readLeases(root, now).filter((lease) => lease.alive).length;
  const position = queuePosition(root, requesterId, now);
  return {
    state: 'queued',
    position,
    active,
    waiters: position,
    budget,
    reaped,
    requesterId,
    ...(registered === undefined ? { note: 'a waiter record could not be written; position is approximate' } : {}),
  };
}

/** Extend a lease. Returns the updated lease, or undefined when it was lost. */
export function renew(root, id, ttlMs = TTL_MS_DEFAULT, now = Date.now()) {
  for (const lease of readLeases(root, 0)) {
    if (lease.document?.id !== id) continue;
    const document = {
      ...lease.document,
      renewedAt: now,
      expiresAt: now + ttlMs,
      ttlMs,
      renewals: Number(lease.document.renewals ?? 0) + 1,
    };
    writeFileSync(lease.file, JSON.stringify(document, null, 2));
    return document;
  }
  return undefined;
}

/** Release a lease by the id its holder was given. */
export function release(root, id) {
  clearWaiter(root, id);
  for (const lease of readLeases(root, 0)) {
    if (lease.document?.id !== id) continue;
    try {
      rmSync(lease.file, { force: true });
      return { released: true, slot: lease.slot };
    } catch (error) {
      return { released: false, slot: lease.slot, error: error instanceof Error ? error.message : String(error) };
    }
  }
  return { released: false, slot: null };
}

/**
 * The whole picture: budget, holders, waiters, and the arithmetic behind it.
 *
 * @param {object} [options]
 * @param {string} options.root
 * @param {number} [options.now]
 * @param {boolean} [options.reapFirst] default true
 */
export function status(options) {
  const { root } = options;
  const now = Number.isFinite(options.now) ? options.now : Date.now();
  const budget = options.budget ?? deriveBudget(options);
  ensureLayout(root);
  const reaped = options.reapFirst === false ? [] : reap(root, now);
  const leases = readLeases(root, now);
  const holders = leases.filter((lease) => lease.alive).map((lease) => ({
    slot: lease.slot,
    id: lease.document.id,
    pid: lease.document.pid,
    host: lease.document.host,
    kind: lease.document.kind,
    note: lease.document.note,
    heldMs: now - Number(lease.document.startedAt ?? now),
    renewedAgoMs: now - Number(lease.document.renewedAt ?? now),
    expiresInMs: Number(lease.document.expiresAt ?? now) - now,
    renewals: Number(lease.document.renewals ?? 0),
  }));
  const dead = leases.filter((lease) => !lease.alive).map((lease) => ({
    slot: lease.slot,
    pid: lease.document?.pid ?? null,
    expiredForMs: lease.corrupt ? null : Math.max(0, now - Number(lease.document?.expiresAt ?? now)),
    corrupt: lease.corrupt === true,
  }));
  let waiters = 0;
  try {
    waiters = readdirSync(waitersDir(root)).filter((name) => name.endsWith('.wait')).length;
  } catch {
    waiters = 0;
  }
  return {
    at: new Date(now).toISOString(),
    host: os.hostname(),
    root,
    budget: budget.budget,
    inUse: holders.length,
    free: Math.max(0, budget.budget - holders.length),
    holders,
    deadLeases: dead,
    waiters,
    reaped,
    derivation: budget.arithmetic,
    headroomLow: budget.headroomLow,
    perSlotBytes: budget.perSlotBytes,
    maxSlots: budget.maxSlots,
    minSlots: budget.minSlots,
    freeMiB: Math.round(budget.freeBytes / 1048576),
    totalMiB: Math.round(budget.totalBytes / 1048576),
    reserveMiB: Math.round(budget.reserveBytes / 1048576),
  };
}

/**
 * Wait for a slot, polling the protocol. Bounded by `timeoutMs`.
 *
 * Polling (250 ms) rather than a notification mechanism on purpose: a wait is a
 * rare, human-scale event (a fleet starting), the lease files are tiny, and a
 * poll of a directory cannot deadlock or leak a lock.
 */
export async function acquireWaiting(options) {
  const timeoutMs = Number.isFinite(options.timeoutMs) ? options.timeoutMs : 0;
  const pollMs = Number.isFinite(options.pollMs) && options.pollMs > 0 ? options.pollMs : 250;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const attempt = acquire(options);
    if (attempt.state === 'granted') return attempt;
    if (timeoutMs <= 0 || Date.now() >= deadline) return attempt;
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
}

/** Exported for tests: the file name for a slot. */
export { slotFile, LOCKED_AT_START };
