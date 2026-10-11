/**
 * Machine posture — read from the ONE file that decides it — and a placement that
 * REFUSES to run a child on a host the estate has not designated as writable.
 *
 * ── THE DEFECT THIS CLOSES ──────────────────────────────────────────────────
 *
 * `lib/nodes.js` maps the broker-named node `secratary` to `ssh: 'secratary-ts'`
 * plus the office box's `driver`/`bin`/`cwd`. On 2026-10-11T05:43:36Z the company
 * authority was cut over to `secratary-cloud` and the office box was left FROZEN
 * as the rollback anchor (`settings/machines/host-posture.tsv`). The node table
 * kept naming it, and **nothing in this package consulted a posture file at all**
 * — so a broker placement could still select that node and run a child on the
 * frozen anchor. Retargeting the `ssh` field alone would have left the office
 * `driver`/`bin`/`cwd` in place, which is the half-migrated pair that took a node
 * down on 2026-10-07/08 (commit `6d686e4`), and it would not have stopped the
 * NEXT freeze either.
 *
 * So the fix is not a hostname swap. It is: **a placement must not select a host
 * whose posture is not writable**, and the set of such hosts is READ FROM
 * `settings/machines/host-posture.tsv` rather than duplicated here. A second copy
 * of "which hosts are frozen" is the drift that let this defect survive a claimed
 * fix once already (`docs/mesh/166-web-profile-office-references.md` §3).
 *
 * ── THE CONTRACT, MIRRORED FROM `scripts/mesh/guard-service-state.sh` ───────
 *
 * Same file, same three postures, same three refusals, so a reader who knows one
 * knows the other:
 *
 *   frozen        REFUSED, always, with no override. The freeze is a decision.
 *   read-only     REFUSED unless the placer was built with `allowReadOnly`
 *                 (the analogue of the guard's `--owner-confirmed`): a child
 *                 writes a cwd, a mailbox and an engine install footprint, so
 *                 "the tree is not to be written" is not compatible with running
 *                 one there by default.
 *   writable      ALLOWED, and the reading is recorded on the placement.
 *   undesignated  REFUSED — the guard's own rule is that an unrecognised host is
 *                 not permission (its exit 4), and a node row that no posture row
 *                 names is a node whose posture nobody has decided.
 *
 * ── WHY THIS MODULE EXISTS AND IS NOT INLINED IN `placement.js` ─────────────
 *
 * There is more than one placer (the broker placer, the direct-probe failover
 * fallback, the fixed-target placer) and every one of them turns a node or an ssh
 * destination into a machine that runs a child. The decision has to be the same
 * one in all of them, and it has to be readable by a test with no network, no
 * clock and no engine. So the parse is pure and the filesystem is injected.
 */

import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** The path, INSIDE harness-config, of the file that decides a machine's posture. */
export const POSTURE_FILE_RELATIVE = 'settings/machines/host-posture.tsv';

export const POSTURE_FROZEN = 'frozen';
export const POSTURE_READ_ONLY = 'read-only';
export const POSTURE_WRITABLE = 'writable';
/** No row in the file names this host, by any of its spellings. */
export const POSTURE_UNDESIGNATED = 'undesignated';

/** The placement was attempted against a FROZEN host. Refused, no override. */
export const PLACEMENT_HOST_FROZEN = 'placement-host-frozen';
/** The placement was attempted against a READ-ONLY host without `allowReadOnly`. */
export const PLACEMENT_HOST_READ_ONLY = 'placement-host-readonly';
/** The placement was attempted against a host no posture row designates. */
export const PLACEMENT_HOST_UNDESIGNATED = 'placement-host-undesignated';
/** The posture file could not be read, so no host can be shown to be placeable. */
export const PLACEMENT_POSTURE_UNKNOWN = 'placement-posture-unknown';

/** A refusal, carrying a stable `code` so a caller can gate on it. */
export class PostureRefusalError extends Error {
  /**
   * @param {string} code one of the `PLACEMENT_*` constants above
   * @param {string} message the text a caller reports — it says WHY, not just WHAT
   * @param {object} [detail] evidence: the node, the token that matched, the row, the file
   */
  constructor(code, message, detail = {}) {
    super(message);
    this.name = 'PostureRefusalError';
    this.code = code;
    this.detail = detail;
  }
}

/**
 * Parse `host-posture.tsv`.
 *
 * FORMAT (the file's own header, quoted rather than paraphrased): one host per
 * line, FIVE fields separated by a PIPE `|` — `host | posture | since | decided |
 * reason`. Lines beginning with `#` and blank lines are ignored; the header line
 * is a COMMENT on purpose, so a blank or dotted column can never parse as a
 * posture. A row with fewer than five fields is skipped rather than guessed at:
 * a half-written row is not a designation.
 *
 * The lookup key is the host string EXACTLY as written, lowercased and trimmed —
 * case-insensitive, and deliberately not suffix-blind. The file's own contract is
 * that "every alias an agent might arrive as is a row" (`secratary`,
 * `secratary-ts`, `secratary-lan`, `192.168.50.77`), and that is the property that
 * must hold: a matcher that guessed across suffixes would also have to decide
 * whether `secratary-ts` and `secratary-cloud` are the same machine, and getting
 * THAT wrong is the whole incident this file guards (`secratary` is a prefix of
 * `secratary-cloud`).
 *
 * @param {string} text the file's bytes
 * @returns {Map<string, {host:string, posture:string, since:string, decided:string, reason:string, line:number}>}
 */
export function parsePostureTable(text) {
  const rows = new Map();
  const lines = String(text ?? '').split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index];
    if (raw === undefined) continue;
    const trimmed = raw.trim();
    if (trimmed === '' || trimmed.startsWith('#')) continue;
    const fields = raw.split('|');
    if (fields.length < 5) continue;
    const host = fields[0].trim();
    if (host === '') continue;
    // `\s`, not a POSIX class: this is JavaScript, where `[[:space:]]` is a set
    // of the literal characters `[ : s p a c e ]` and would quietly match "s".
    const posture = fields[1].replace(/\s/g, '').toLowerCase();
    if (posture === '') continue;
    const key = host.toLowerCase();
    // FIRST ROW WINS, so a duplicate designation cannot silently flip a frozen
    // host writable by being appended later in the file.
    if (rows.has(key)) continue;
    rows.set(key, {
      host,
      posture,
      since: fields[2].trim(),
      decided: fields[3].trim(),
      reason: fields[4].trim(),
      line: index + 1,
    });
  }
  return rows;
}

/**
 * Where the designation file may live, in the order it is looked for.
 *
 * MIRRORS `scripts/mesh/guard-service-state.sh`, including the environment
 * variable name (`HARNESS_CONFIG_POSTURE`), so an operator who has learned one
 * search order has learned both. The repo-relative candidate is first because
 * this module ships inside the repo that owns the file: at runtime the live
 * `~/.dsh/profiles/web/node_modules/dsh-plugin-remote-fanout` is a junction into
 * the checkout, and Node resolves a module's realpath, so the repo root is
 * reachable from `import.meta.url` even when the engine is started from `$HOME`.
 */
export function defaultPostureCandidates(env = process.env) {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const candidates = [
    env.HARNESS_CONFIG_POSTURE,
    env.HARNESS_CONFIG_ROOT ? path.join(env.HARNESS_CONFIG_ROOT, POSTURE_FILE_RELATIVE) : undefined,
    path.resolve(here, '..', '..', '..', POSTURE_FILE_RELATIVE),
    path.join(homedir(), 'code', 'harness-config', POSTURE_FILE_RELATIVE),
    path.join(homedir(), 'harness-config', POSTURE_FILE_RELATIVE),
  ];
  return candidates.filter((value) => typeof value === 'string' && value !== '');
}

/** The first candidate that exists, or `null`. Read-only: it stat()s, nothing more. */
export function findPostureFile({ env = process.env, candidates, exists = existsSync } = {}) {
  const list = Array.isArray(candidates) ? candidates : defaultPostureCandidates(env);
  for (const candidate of list) {
    try {
      if (exists(candidate)) return candidate;
    } catch {
      // An unreadable candidate is not a found file; keep looking.
    }
  }
  return null;
}

/**
 * Read and parse the designation file.
 *
 * A missing or unreadable file is a REFUSAL, not a shrug — the same choice
 * `guard-service-state.sh` makes ("That file IS the designation. Without it this
 * host is UNDESIGNATED, and an undesignated host is not permission"). For a
 * placement the consequence is stated in the message rather than discovered
 * later: with no table, no host can be shown to be writable, and dispatching
 * anyway is how a child lands on a frozen box. The remedy is one line and it is
 * in the error.
 *
 * @returns {{file:string, designations:Map}}
 * @throws {PostureRefusalError} code `placement-posture-unknown`
 */
export function loadPosture({ env = process.env, candidates, exists = existsSync, read = readFileSync } = {}) {
  const list = Array.isArray(candidates) ? candidates : defaultPostureCandidates(env);
  const file = findPostureFile({ env, candidates: list, exists });
  if (file === null) {
    throw new PostureRefusalError(
      PLACEMENT_POSTURE_UNKNOWN,
      `REFUSED — no machine-posture designation could be read, so no node can be shown to be placeable. `
      + `Looked for "${POSTURE_FILE_RELATIVE}" at: ${list.join(' , ')}. `
      + `That file IS the designation (settings/machines/host-posture.tsv): it is what makes a frozen host frozen, `
      + `and a placement decided without it is a placement decided by guesswork. `
      + `Point HARNESS_CONFIG_POSTURE at it, or HARNESS_CONFIG_ROOT at the harness-config checkout, and retry.`,
      { candidates: list },
    );
  }
  let text;
  try {
    text = String(read(file, 'utf8'));
  } catch (error) {
    throw new PostureRefusalError(
      PLACEMENT_POSTURE_UNKNOWN,
      `REFUSED — the machine-posture designation at ${file} could not be read (${String(error?.message ?? error)}); `
      + `without it no node can be shown to be placeable. Fix the file (or the permissions on it) and retry.`,
      { file, cause: String(error?.message ?? error) },
    );
  }
  const designations = parsePostureTable(text);
  if (designations.size === 0) {
    throw new PostureRefusalError(
      PLACEMENT_POSTURE_UNKNOWN,
      `REFUSED — ${file} parsed to ZERO designations. An empty table is not "nothing is frozen"; it is a file that `
      + `cannot say, and a placement decided from it would be decided by guesswork. Check the file's five-pipe-field `
      + `format (host | posture | since | decided | reason) and retry.`,
      { file },
    );
  }
  return { file, designations };
}

/**
 * Every spelling of a node that the designation file might use for it.
 *
 * A node is named by the broker with its Tailscale DNS label, and `lib/nodes.js`
 * carries the ssh destination and the hostnames the node is allowed to report.
 * `host-posture.tsv` may key any of them (`secratary` is a row AND `secratary-ts`
 * is a row), so all of them are checked and EVERY match counts — the frozen
 * direction must not be lost because a writable spelling was tried first.
 */
export function nodePostureTokens(node, facts) {
  const tokens = [node];
  if (facts !== undefined && facts !== null) {
    if (typeof facts.ssh === 'string' && facts.ssh !== '') {
      tokens.push(facts.ssh);
      // `root@178.156.194.1` is a row of its own in the file, so the whole string
      // is kept; the host part is added too, because an ssh destination written
      // as `user@host` names the same machine either way.
      const at = facts.ssh.indexOf('@');
      if (at >= 0 && at + 1 < facts.ssh.length) tokens.push(facts.ssh.slice(at + 1));
    }
    if (Array.isArray(facts.hosts)) tokens.push(...facts.hosts);
  }
  const seen = new Set();
  const out = [];
  for (const token of tokens) {
    if (typeof token !== 'string') continue;
    const value = token.trim();
    if (value === '') continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(value);
  }
  return out;
}

/**
 * The posture of one node, and the token that decided it.
 *
 * THE STRICTEST MATCH WINS: if any spelling of the node is `frozen`, the node is
 * frozen, whatever another spelling says. That ordering is not cosmetic — a node
 * reachable as `secratary` (frozen) and, say, an alias still marked writable would
 * otherwise be placeable through the alias, which is precisely the
 * `secratary` / `secratary-cloud` confusion `AGENTS.md` §5 was written about.
 */
export function postureForNode(node, { designations, nodes = undefined } = {}) {
  const table = designations instanceof Map ? designations : new Map();
  const facts = nodes === undefined ? undefined : nodes[node];
  const tokens = nodePostureTokens(node, facts);
  const matches = [];
  for (const token of tokens) {
    const row = table.get(token.toLowerCase());
    if (row !== undefined) matches.push({ token, row });
  }
  const severity = [POSTURE_FROZEN, POSTURE_READ_ONLY, POSTURE_WRITABLE];
  for (const posture of severity) {
    const found = matches.find((match) => match.row.posture === posture);
    if (found !== undefined) {
      return { posture, matchedBy: found.token, tokens, row: found.row };
    }
  }
  const unknown = matches[0];
  return {
    posture: unknown === undefined ? POSTURE_UNDESIGNATED : unknown.row.posture,
    matchedBy: unknown?.token ?? null,
    tokens,
    row: unknown?.row ?? null,
  };
}

/** The text a refused placement reports: what the host is FOR, who decided it, since when, and what to read. */
function refusalMessage(node, reading, { file, headline, remedy }) {
  const row = reading.row;
  return `${headline}\n`
    + `  NODE           : ${node}\n`
    + `  MATCHED BY     : ${reading.matchedBy ?? '(no designation row names this node)'}\n`
    + (row === null ? '' : `  WHAT IT IS FOR : ${row.reason}\n`)
    + (row === null ? '' : `  WHO DECIDED    : ${row.decided}\n`)
    + (row === null ? '' : `  SINCE          : ${row.since}\n`)
    + `  DESIGNATION    : ${reading.posture}   (from ${file ?? POSTURE_FILE_RELATIVE})\n`
    + (row === null ? '' : `  TOKENS CHECKED : ${reading.tokens.join(', ')}\n`)
    + (remedy === '' ? '' : `  ${remedy}`);
}

/**
 * THE DECISION, in one place: may a child be placed on this node?
 *
 * @returns {null|{code:string, message:string, detail:object}} `null` means allowed.
 */
export function placementRefusal(node, { designations, nodes = undefined, file = undefined, allowReadOnly = false } = {}) {
  const reading = postureForNode(node, { designations, nodes });
  const shared = { file, allowReadOnly };
  if (reading.posture === POSTURE_FROZEN) {
    return {
      code: PLACEMENT_HOST_FROZEN,
      message: refusalMessage(node, reading, {
        file,
        headline: `REFUSED — node "${node}" resolves to a FROZEN host; no child is placed there.`,
        remedy: 'A MASKED OR STOPPED UNIT ON THIS HOST IS DELIBERATE. It does not mean the company is down and it is\n'
          + '  not yours to "restore". Do not start, stop, mask, unmask, enable, disable or restart anything there, and\n'
          + '  do not run a child on it: a child is a writer. READ FIRST: docs/mesh/131-MIGRATION-BRIEF.md (Rule 1 and\n'
          + '  Rule 2), docs/mesh/142-ANCHOR-WRITE-NOTICE.md, AGENTS.md §5. If the freeze is genuinely wrong, ASK THE\n'
          + '  OWNER — the answer is a decision, not a command you already have.',
      }),
      detail: { node, ...shared, ...reading },
    };
  }
  if (reading.posture === POSTURE_READ_ONLY && allowReadOnly !== true) {
    return {
      code: PLACEMENT_HOST_READ_ONLY,
      message: refusalMessage(node, reading, {
        file,
        headline: `REFUSED — node "${node}" resolves to a READ-ONLY host; no child is placed there without a deliberate yes.`,
        remedy: 'A child writes a working directory, a mailbox and its engine\'s own footprint, so "this tree is not to be\n'
          + '  written" is not compatible with running one here by default. The guard for service state has the same rule\n'
          + '  and the same escape (--owner-confirmed); here it is `allowReadOnly` on the placer, which is only set once\n'
          + '  the owner has said yes in the current conversation.',
      }),
      detail: { node, ...shared, ...reading },
    };
  }
  if (reading.posture === POSTURE_UNDESIGNATED) {
    return {
      code: PLACEMENT_HOST_UNDESIGNATED,
      message: refusalMessage(node, reading, {
        file,
        headline: `REFUSED — node "${node}" is UNDESIGNATED: no row in the posture file names it.`,
        remedy: `An unrecognised host is NOT permission (guard-service-state.sh exits 4 on the same rule). Add a row for\n`
          + `  this node's name, its ssh alias and every hostname it reports to ${POSTURE_FILE_RELATIVE}, with the posture\n`
          + `  someone decided, and retry.`,
      }),
      detail: { node, ...shared, ...reading },
    };
  }
  return null;
}

/**
 * The node names a caller should ask the broker to avoid — a HINT only.
 *
 * `exclude` is soft by the broker's own contract (`packages/mesh-broker/lib/broker.js`:
 * an exclusion that names every node yields to "queue, never amputate"), so this
 * cannot be the guarantee. It is here so the common case does not spend a lease
 * on a node that would then be refused: the guarantee is `placementRefusal`,
 * applied to whatever the broker names.
 */
export function barredNodeNames({ designations, nodes, allowReadOnly = false } = {}) {
  const table = designations instanceof Map ? designations : new Map();
  const names = nodes === undefined || nodes === null ? [] : Object.keys(nodes);
  return names.filter((node) => placementRefusal(node, { designations: table, nodes, allowReadOnly }) !== null);
}
