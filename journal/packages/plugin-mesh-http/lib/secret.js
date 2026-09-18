/**
 * The shared secret, and only that.
 *
 * WHY IT IS A FILE AND NOT A CREDENTIAL REF
 * The route this secret authenticates is NOT behind the engine's cookie fence — that is the
 * whole point of transport v2 (`docs/mesh/66-dsh-remote-capability.md` §2e/§3.1). The engine
 * that serves it may also be restarted, reloaded, or running with a different DSH_HOME than
 * the dispatcher expects, so the one thing both ends must agree on cannot be engine state:
 * it is a file on the node's own disk, outside any repository, mode 0640, readable by the
 * account that runs the engine and by nothing else.
 *
 * WHY IT IS RE-READABLE WITHOUT A RESTART
 * An engine restart ends every live session on this fleet (P210, measured), so rotating the
 * secret must not require one. The file is read once and then re-read whenever its own
 * `mtime`/`size`/`ino` changes, which makes `mesh-http secret --rotate` take effect on the
 * next request instead of on the next restart. The reading carries its own provenance: the
 * path, the byte length of the value, and when it was read. The VALUE is never logged,
 * never returned, and never put in a response.
 *
 * WHAT THIS FILE DELIBERATELY DOES NOT DO
 * It does not create the file, does not fix its mode, and does not invent a secret. A node
 * with no secret answers 503 and says which path it looked in — an absent secret is an
 * absent capability, never an open door and never a silently generated one (a generated
 * secret would make the node look configured while no dispatcher could ever authenticate).
 */

import { readFileSync, statSync } from 'node:fs';

/** The value of `KEY=VALUE`-file parsing: the secret, or a reason there is none. */
const CACHE = new Map();

/** One `KEY=VALUE` line, `#` comments, optional single/double quotes around the value. */
export function parseEnvText(text) {
  const values = new Map();
  for (const rawLine of String(text).split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line === '' || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (value.length >= 2) {
      const first = value[0];
      const last = value[value.length - 1];
      if ((first === '"' && last === '"') || (first === "'" && last === "'")) value = value.slice(1, -1);
    }
    values.set(key, value);
  }
  return values;
}

/** A secret worth using: non-empty after trimming, and long enough that it is not a guess. */
export function isUsableSecret(value) {
  return typeof value === 'string' && value.trim().length >= 16;
}

/**
 * Read the secret from `filePath`, cached until the file's identity changes.
 *
 * @returns {{ok: true, secret: string, path: string, bytes: number, readAt: string, reads: number}
 *          | {ok: false, path: string, reason: string, readAt: string}}
 */
export function loadSecret(filePath) {
  const readAt = new Date().toISOString();
  if (typeof filePath !== 'string' || filePath.trim() === '') {
    return { ok: false, path: String(filePath), reason: 'no secretFile configured', readAt };
  }
  const key = filePath;
  let identity = null;
  try {
    const stat = statSync(key);
    identity = `${stat.mtimeMs}:${stat.size}:${stat.ino ?? 0}`;
  } catch (error) {
    CACHE.delete(key);
    return {
      ok: false,
      path: key,
      reason: `cannot stat the secret file (${error?.code ?? error?.message ?? error})`,
      readAt,
    };
  }
  const cached = CACHE.get(key);
  if (cached !== undefined && cached.identity === identity) return { ...cached.value, readAt, reads: cached.reads };

  let values;
  try {
    values = parseEnvText(readFileSync(key, 'utf8'));
  } catch (error) {
    return {
      ok: false,
      path: key,
      reason: `cannot read the secret file (${error?.code ?? error?.message ?? error})`,
      readAt,
    };
  }
  const value = values.get('MESH_HTTP_SECRET') ?? values.get('MESH_SECRET');
  if (!isUsableSecret(value)) {
    return {
      ok: false,
      path: key,
      reason: value === undefined
        ? 'the file has no MESH_HTTP_SECRET= line'
        : 'the secret is shorter than 16 bytes, which is not a secret',
      readAt,
    };
  }
  const reads = (cached?.reads ?? 0) + 1;
  const value100 = {
    ok: true,
    secret: value.trim(),
    path: key,
    bytes: Buffer.byteLength(value.trim(), 'utf8'),
    readAt,
    reads,
  };
  CACHE.set(key, { identity, value: value100, reads });
  return value100;
}

/** Forget the cache. Unit tests only; a running engine never needs it. */
export function forgetSecret(filePath) {
  if (filePath === undefined) CACHE.clear();
  else CACHE.delete(filePath);
}
