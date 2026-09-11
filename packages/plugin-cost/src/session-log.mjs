/**
 * Locate and read one DSH session log from disk.
 *
 * The harness persists a session as a concatenated Zstandard frame container at
 * `<dshHome>/sessions/<workspace>/<sessionId>/session.v3.jsonl.zstd`. Node's
 * one-shot zstd decoder stops at the first frame, so a naive read returns only the
 * session header; every frame is located by its magic number and decoded alone.
 * A torn final frame is legal in this container and is skipped, because the writer
 * appends in batches and a hard kill can leave one incomplete.
 */
import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { zstdDecompressSync } from 'node:zlib';

const ZSTD_MAGIC = 0xfd2fb528;

/**
 * The harness's home directory, in the same precedence the CLI uses.
 * @returns {string} absolute path to the DSH home
 */
export function dshHome() {
  return process.env.DSH_HOME ?? join(homedir(), '.dsh');
}

/**
 * Directory name the session store derives from a cwd.
 * Observed: `C:\Users\ezabz\code` -> `--C-Users-ezabz-code--`. The drive colon is
 * dropped rather than replaced, and separators become `-`.
 */
export function workspaceDirName(cwd) {
  return `--${cwd.replace(/:/g, '').replace(/[\\/]/g, '-')}--`;
}

/**
 * The session-store directory name for a session id. Root sessions opened from the
 * GUI are stored with a `session-` prefix; other identities are not.
 */
export function sessionDirName(sessionId) {
  return /^session-/.test(sessionId) ? sessionId : `session-${sessionId}`;
}

/**
 * Find one session log by id.
 * @param {string} sessionId the live agent's session id
 * @param {string|undefined} cwd the live agent's working directory
 * @returns {{file:string, candidates:string[]}} the first existing log and every path tried
 */
export function findSessionLog(sessionId, cwd) {
  const root = join(dshHome(), 'sessions');
  const candidates = [];
  if (typeof cwd === 'string' && cwd.length > 0) {
    candidates.push(join(root, workspaceDirName(cwd), sessionDirName(sessionId), 'session.v3.jsonl.zstd'));
    candidates.push(join(root, workspaceDirName(cwd), sessionId, 'session.v3.jsonl.zstd'));
  }
  return { file: candidates.find((path) => existsSync(path)), candidates };
}

/**
 * Decode a session log into its event records.
 * @param {string} file absolute path to a `.jsonl.zstd` session log
 * @returns {Array<object>} one object per JSONL line
 */
export function readSessionLog(file) {
  const buffer = readFileSync(file);
  const offsets = [];
  for (let i = 0; i + 3 < buffer.length; i += 1) {
    if (buffer.readUInt32LE(i) === ZSTD_MAGIC) offsets.push(i);
  }
  const parts = [];
  let frames = 0;
  for (let i = 0; i < offsets.length; i += 1) {
    const end = i + 1 < offsets.length ? offsets[i + 1] : buffer.length;
    try {
      parts.push(zstdDecompressSync(buffer.subarray(offsets[i], end)));
      frames += 1;
    } catch {
      // Torn tail frame: legal, and the only frame allowed to be incomplete.
    }
  }
  if (frames === 0) throw new Error(`no decodable zstd frame in ${file}`);
  const events = [];
  for (const line of Buffer.concat(parts).toString('utf8').split('\n')) {
    if (line.length === 0) continue;
    try {
      events.push(JSON.parse(line));
    } catch {
      // A torn write can leave one partial line; skip it and keep the rest.
    }
  }
  return events;
}
