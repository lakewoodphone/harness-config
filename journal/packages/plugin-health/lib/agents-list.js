/**
 * `list_agents` with a deadline and a short-TTL cache.
 *
 * THE TWO DEFECTS THIS REPLACES, AND THE EXACT MECHANISM OF EACH
 *
 * 1. NO DEADLINE. `dsh-tool-call-timeout-policy` wraps a tool only when the
 *    tool definition declares `timeoutMs`:
 *
 *        const timeoutMs = ctx.tools.get(exec.name, exec.agent)?.timeoutMs;
 *        if (timeoutMs === void 0) return next();
 *
 *    The shipped `list_agents` declares none, so a stalled listing has NO
 *    cancellation anywhere in the stack: it does not fail and it does not
 *    finish, and the card renders nothing, which an operator reads as a blank.
 *
 * 2. NO CACHE, AND THE COST IS REPAID BY EVERY CALLER. Every invocation runs
 *    `subagents.listChildren|listDescendants` → `prepareListing` →
 *    `sessionQuery.listSessions` → `session-persistence-jsonl.listArtifacts`,
 *    which is a fully serial walk of `~/.dsh/sessions`: readdir per session
 *    directory, `open`, read zstd frames, `decompressZstdFrame`, `JSON.parse`
 *    the header — for every session on disk, on the shared event loop, with no
 *    `Promise.all` and no cache. Measured on ZABZ-YOGA 2026-09-16: 389 session
 *    dirs / ~320 MB compressed. N concurrent callers pay it N times.
 *
 * WHAT THIS DOES
 *   * A cooperative deadline. The listing is given `deadlineMs`; when it
 *     expires the underlying scan is ABORTED through the signal the service
 *     already honors, and the caller gets the last known listing (marked stale)
 *     or an explicit `unavailable` diagnostic row — never a hang, never a blank.
 *   * A short-TTL cache with single-flight. One scan serves every caller inside
 *     the TTL, and concurrent callers inside one scan coalesce onto it. The TTL
 *     is deliberately 3 s: long enough that a burst of concurrent calls pays
 *     once, short enough that a just-spawned subagent is not invisible for long.
 *   * `timeoutMs` IS declared on the definition this registers, so the shipped
 *     timeout policy arms a hard backstop behind the cooperative deadline.
 *
 * WHAT IT DELIBERATELY DOES NOT CHANGE
 * The tool's name, its arguments, its output schema and its rendered text. A
 * caller cannot tell the difference between this and the shipped tool except
 * that it answers, and that an unreadable listing is named as such. The
 * projection below is the shipped `list-agents.js` projection, re-implemented
 * rather than imported because that module exports only `apply`.
 */

import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import path from 'node:path';

/** The tool name is deliberately unchanged: the catalog must not shift. */
const LIST_AGENTS = 'list_agents';

/** Defaults; every one is overridable from the composition row's `config`. */
const DEFAULT_CACHE_MS = 3000;
const DEFAULT_DEADLINE_MS = 8000;
const DEFAULT_MAX_DEADLINE_MS = 25000;

/**
 * Process-local statistics, shared by every plugin instance in this process.
 *
 * A module-scope object is the right home for this: the counters describe one
 * engine's listing behaviour, and every mount of this plugin in that engine
 * should add to the same numbers. The health surface reads them from here when
 * it is the same module instance, and from the mirror file when it is not.
 */
export const listingStats = {
  scans: 0,
  hits: 0,
  staleServes: 0,
  timeouts: 0,
  coalesced: 0,
  failures: 0,
  deadlineServes: 0,
  lastScanMs: null,
  lastScanAt: null,
  lastServedMs: null,
  lastOutcome: null,
  cacheMs: DEFAULT_CACHE_MS,
  deadlineMs: DEFAULT_DEADLINE_MS,
};

/**
 * Write the counters where a reader in another plugin instance can see them.
 *
 * Best effort by design: a statistics mirror must never be the reason a tool
 * call fails, so every failure here is swallowed. The write is atomic (temp +
 * rename) because the reader may poll it at any moment.
 */
export function publishListingStats(file) {
  if (typeof file !== 'string' || file.length === 0) return;
  try {
    const temp = `${file}.tmp-${process.pid}`;
    writeFileSync(temp, JSON.stringify({ ...listingStats, at: new Date().toISOString() }));
    renameSync(temp, file);
  } catch (error) {
    // The directory may not exist yet on a fresh home. Creating it here keeps
    // the mirror working even when the host-plane row (which normally creates
    // it) is not mounted, and a failure after that is still not the listing's
    // fault, so it stays swallowed.
    try {
      mkdirSync(path.dirname(file), { recursive: true });
      const temp = `${file}.tmp-${process.pid}`;
      writeFileSync(temp, JSON.stringify({ ...listingStats, at: new Date().toISOString() }));
      renameSync(temp, file);
    } catch {
      // A mirror that cannot be written is not a fault of the listing.
    }
  }
}

/** Read a mirror written by another instance, or undefined. */
export function readListingStats(file) {
  if (typeof file !== 'string' || file.length === 0) return undefined;
  try {
    const parsed = JSON.parse(readFileSync(file, 'utf8'));
    return parsed !== null && typeof parsed === 'object' ? parsed : undefined;
  } catch {
    return undefined;
  }
}

/** Where the mirror lives, next to the process snapshot. */
export function defaultStatsFile(dshHome) {
  return path.join(dshHome, 'health', 'list-agents.json');
}

/**
 * The listing cache: a TTL per scope plus single-flight coalescing.
 *
 * Keyed by `scope` because `children` and `descendants` are different answers.
 * Both are served from the SAME underlying scan by the service, but caching them
 * together would mean computing both answers for every caller, which is worse
 * for a caller that only wants one.
 */
export class ListingCache {
  #entries = new Map();
  #inflight = new Map();

  constructor({ ttlMs = DEFAULT_CACHE_MS } = {}) {
    this.ttlMs = ttlMs;
  }

  /** Cached value for a scope, with its age, or undefined when cold. */
  peek(scope) {
    const hit = this.#entries.get(scope);
    if (hit === undefined) return undefined;
    return { value: hit.value, ageMs: Date.now() - hit.at, fresh: Date.now() - hit.at < this.ttlMs };
  }

  /**
   * Resolve one scope, from cache when fresh, from one shared scan otherwise.
   *
   * @param {string} scope - `children` or `descendants`
   * @param {() => Promise<unknown>} load - the scan; called at most once per flight
   * @returns {Promise<{value: unknown, cached: boolean, coalesced: boolean, ageMs: number, scanMs: number|null}>}
   */
  async resolve(scope, load) {
    if (this.ttlMs > 0) {
      const hit = this.peek(scope);
      if (hit !== undefined && hit.fresh) {
        return { value: hit.value, cached: true, coalesced: false, ageMs: hit.ageMs, scanMs: null };
      }
    }
    const pending = this.#inflight.get(scope);
    if (pending !== undefined) {
      // Inside one flight: this caller pays nothing and waits for the scan that
      // is already running. This is the case that made N concurrent calls cost
      // N full corpus scans.
      const outcome = await pending;
      return { value: outcome.value, cached: true, coalesced: true, ageMs: Date.now() - outcome.at, scanMs: outcome.scanMs };
    }
    const startedAt = Date.now();
    const flight = (async () => {
      const value = await load();
      return { value, at: Date.now(), scanMs: Date.now() - startedAt };
    })();
    // Mark the flight as handled even if every awaiter walks away at its
    // deadline: without this, an abandoned scan that later rejects would surface
    // as an unhandled rejection in an engine log.
    flight.catch(() => {});
    this.#inflight.set(scope, flight);
    let outcome;
    try {
      outcome = await flight;
    } finally {
      if (this.#inflight.get(scope) === flight) this.#inflight.delete(scope);
    }
    this.#entries.set(scope, { at: outcome.at, value: outcome.value });
    return { value: outcome.value, cached: false, coalesced: false, ageMs: 0, scanMs: outcome.scanMs };
  }

  /** Whether a scan for this scope is in flight right now. */
  inFlight(scope) {
    return this.#inflight.has(scope);
  }

  /**
   * Stop waiting on the current scan for one scope.
   *
   * Called when a caller's deadline expires while the scan is still running. The
   * scan itself keeps going (it was aborted, but an abort is cooperative and the
   * result is still worth keeping); it is simply no longer the flight that later
   * callers coalesce onto. Without this, one scan that ignores cancellation would
   * wedge the cache for that scope forever, and every later caller would wait on
   * a promise that never settles — the exact hang this module exists to remove.
   *
   * The cost of the choice: in that pathological case a later caller starts a
   * second concurrent scan. Bounded, rare, and strictly better than a permanent
   * hang.
   */
  abandon(scope) {
    this.#inflight.delete(scope);
  }

  /** Drop everything. Used when the cache TTL is configured to zero. */
  clear() {
    this.#entries.clear();
  }

  get size() {
    return this.#entries.size;
  }
}

/** Normalize the `scope` argument exactly as the shipped tool does. */
export function resolveScope(args) {
  const requested = args !== null && typeof args === 'object' ? args.scope : undefined;
  return requested === 'descendants' ? 'descendants' : 'children';
}

/**
 * Project one service entry onto the model-facing row, or drop it.
 *
 * The two drops are the shipped behaviour and are kept deliberately: a one-shot
 * child cannot be continued by `send_message`, and a live child whose identity
 * fold has not been written yet has no id to offer. A caller sees fewer rows,
 * never a wrong row.
 */
export function projectEntry(agents, entry, position) {
  const at = position === undefined ? {} : { parent: position.parentId, depth: position.depth };
  if (entry.kind === 'diagnostic') {
    return { kind: 'diagnostic', id: String(entry.id), reason: entry.reason, ...at };
  }
  if (entry.mode !== 'continuable') return undefined;
  const live = agents === undefined || typeof agents.get !== 'function' ? undefined : agents.get(entry.id);
  const status = live === undefined ? 'ready' : live.status === 'running' ? 'running' : 'idle';
  return { kind: 'child', id: String(entry.id), label: entry.label, status, ...at };
}

/** Project a whole listing, preserving order and dropping what cannot be listed. */
export function projectListing(agents, entries, scope) {
  const out = [];
  for (const entry of entries) {
    const position = scope === 'descendants' ? { parentId: entry.parentId, depth: entry.depth } : undefined;
    const row = projectEntry(agents, entry, position);
    if (row !== undefined) out.push(row);
  }
  return out;
}

/**
 * The rendered text. NEVER blank, in every case that can occur:
 *   * a genuinely empty listing renders `(no subagents)` — visible text;
 *   * a timed-out listing with nothing cached renders a sentence that says so;
 *   * a stale listing says it is stale and how old it is.
 */
export function renderListing(args, entries) {
  const scope = resolveScope(args);
  const rows = Array.isArray(entries) ? entries : [];
  if (rows.length === 0) return [{ type: 'text', text: '(no subagents)' }];
  const lines = rows.map((entry) => {
    const at = scope === 'descendants' ? ` parent=${String(entry.parent)} depth=${String(entry.depth)}` : '';
    return entry.kind === 'child'
      ? `${entry.id} [${entry.status}]${at} — ${entry.label}`
      : `${entry.id} [diagnostic: ${entry.reason}]${at}`;
  });
  return [{ type: 'text', text: lines.join('\n') }];
}

/**
 * The output schema, the same shape as the shipped tool's.
 *
 * RAW JSON Schema, not the author DSL. `tools.register` validates this with
 * `assertSupportedJsonSchema`, which requires `required` to be an ARRAY of
 * property names; writing `required: true` inside a property (which is what the
 * author DSL used by `defineTool` looks like) throws
 * `JsonSchemaError: required must be an array of strings`, and because that
 * throw happens inside a registration guarded for safety the tool silently does
 * not exist while the plugin still looks mounted. That cost an hour once; the
 * shape below is the corrected one.
 */
const OUTPUT_SCHEMA = {
  type: 'array',
  items: {
    oneOf: [
      {
        type: 'object',
        additionalProperties: false,
        properties: {
          kind: { type: 'string', enum: ['child'] },
          id: { type: 'string' },
          label: { type: 'string' },
          status: { type: 'string', enum: ['running', 'idle', 'ready'] },
          parent: { type: 'string' },
          depth: { type: 'number' },
        },
        required: ['kind', 'id', 'label', 'status'],
      },
      {
        type: 'object',
        additionalProperties: false,
        properties: {
          kind: { type: 'string', enum: ['diagnostic'] },
          id: { type: 'string' },
          reason: { type: 'string', enum: ['corrupt', 'unsupported', 'unavailable'] },
          parent: { type: 'string' },
          depth: { type: 'number' },
        },
        required: ['kind', 'id', 'reason'],
      },
    ],
  },
};

const DESCRIPTION = 'List your continuable background subagents by durable id and label. Use it to recall which ones '
  + 'you started, not to poll for completion — you are told when one finishes. Status comes from the live registry: '
  + 'running means the agent is working right now, idle means it is loaded but between turns (it may be waiting on '
  + 'agents it started), and ready means it exists only in storage — resumable, not terminal, and not a result waiting '
  + 'to be collected; a `send_message` steers a running child at its nearest step boundary or starts a turn for an idle '
  + 'or ready child. Scope `descendants` walks the whole tree below you in stable pre-order, annotating each entry with '
  + 'its durable direct-parent session id and depth. Answers come from a short-lived shared cache: a listing produced '
  + 'within the last few seconds is served as-is instead of re-reading every session on disk, and if reading takes '
  + 'longer than the deadline the last known listing is returned rather than stalling — a row whose id is `list_agents` '
  + 'with reason `unavailable` means the listing could not be read in time and nothing was cached.';

/**
 * Register the replacement `list_agents` into the calling context's tool layer.
 *
 * Registered from the SAME scope the shipped row occupies, so the tool the model
 * sees is unchanged in name, arguments, schema and rendering — only its two
 * behaviours under load differ.
 *
 * @param {object} ctx - the context whose tool layer should receive the tool
 * @param {object} options
 * @param {number} [options.cacheMs] TTL; 0 disables caching (used to measure the raw scan)
 * @param {number} [options.deadlineMs] cooperative deadline
 * @param {number} [options.maxDeadlineMs] ceiling for the cooperative deadline
 * @param {string} [options.statsFile] where to mirror the counters
 * @param {string} [options.toolName] defaults to `list_agents`
 * @returns {() => void} disposer
 */
export function registerListAgents(ctx, options = {}) {
  const cacheMs = Number.isFinite(options.cacheMs) && options.cacheMs >= 0 ? options.cacheMs : DEFAULT_CACHE_MS;
  const rawDeadline = Number.isFinite(options.deadlineMs) && options.deadlineMs > 0 ? options.deadlineMs : DEFAULT_DEADLINE_MS;
  const maxDeadlineMs = Number.isFinite(options.maxDeadlineMs) && options.maxDeadlineMs > 0 ? options.maxDeadlineMs : DEFAULT_MAX_DEADLINE_MS;
  const deadlineMs = Math.min(rawDeadline, maxDeadlineMs);
  const statsFile = options.statsFile;
  const toolName = options.toolName || LIST_AGENTS;

  const cache = new ListingCache({ ttlMs: cacheMs });
  listingStats.cacheMs = cacheMs;
  listingStats.deadlineMs = deadlineMs;

  const definition = {
    name: toolName,
    description: DESCRIPTION,
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        scope: {
          type: 'string',
          enum: ['children', 'descendants'],
          description: 'children (default) lists direct children only; descendants walks the complete tree below you.',
        },
      },
    },
    output: {
      schema: OUTPUT_SCHEMA,
      render: renderListing,
    },
    // The definition declares the backstop the shipped tool never had, so the
    // timeout policy wraps this call instead of passing it through untouched.
    // The cooperative deadline below returns a useful answer first; this is the
    // hard cancel behind it.
    timeoutMs: deadlineMs + 2000,
    async execute(args, exec) {
      const startedAt = Date.now();
      const scope = resolveScope(args);
      const agents = ctx.get('agents');
      const subagents = ctx.get('subagents');
      if (subagents === undefined || typeof subagents.listChildren !== 'function') {
        listingStats.failures += 1;
        listingStats.lastOutcome = 'no subagents service';
        listingStats.lastServedMs = Date.now() - startedAt;
        publishListingStats(statsFile);
        return [{ kind: 'diagnostic', id: toolName, reason: 'unavailable' }];
      }
      const parent = exec.agent;
      if (parent === undefined || parent === null) {
        // Same refusal the shipped tool makes: without a calling agent there are
        // no children to list, and inventing an empty list would be a lie.
        throw new Error('list_agents requires a calling agent (exec.agent was undefined)');
      }

      const controller = new AbortController();
      const callerSignal = exec.signal;
      const signals = callerSignal === undefined || callerSignal === null
        ? [controller.signal]
        : [controller.signal, callerSignal];
      const signal = signals.length > 1 && typeof AbortSignal.any === 'function'
        ? AbortSignal.any(signals)
        : signals[0];
      let timedOut = false;
      // A sentinel, not a rejection: the deadline ends the WAIT, and what the
      // caller gets is decided below. `Promise.race` is what makes the deadline
      // unconditional — the abort above is a courtesy that lets the scan stop
      // early, but a service that ignores it can no longer hang this call.
      const DEADLINE = Symbol('deadline');
      let fireDeadline;
      const deadlineReached = new Promise((resolve) => { fireDeadline = resolve; });
      const timer = setTimeout(() => {
        timedOut = true;
        controller.abort(new Error(`list_agents: deadline of ${deadlineMs} ms exceeded`));
        fireDeadline(DEADLINE);
      }, deadlineMs);
      // If the deadline has already gone by the time this runs, fire at once.
      if (deadlineMs <= 0) fireDeadline(DEADLINE);

      const load = async () => {
        const entries = scope === 'descendants'
          ? await subagents.listDescendants(parent.id, signal)
          : await subagents.listChildren(parent.id, signal);
        return projectListing(agents, entries, scope);
      };

      try {
        const raced = await Promise.race([cache.resolve(scope, load), deadlineReached]);
        if (raced === DEADLINE) {
          return serveAfterDeadline();
        }
        const outcome = raced;
        if (outcome.scanMs !== null) {
          listingStats.scans += 1;
          listingStats.lastScanMs = outcome.scanMs;
          listingStats.lastScanAt = new Date().toISOString();
        }
        if (outcome.coalesced) listingStats.coalesced += 1;
        else if (outcome.cached) listingStats.hits += 1;
        listingStats.lastOutcome = outcome.coalesced ? 'coalesced' : outcome.cached ? 'hit' : 'scan';
        listingStats.lastServedMs = Date.now() - startedAt;
        return outcome.value;
      } catch (error) {
        if (timedOut) return serveAfterDeadline();
        listingStats.failures += 1;
        listingStats.lastOutcome = `failed: ${error instanceof Error ? error.message : String(error)}`;
        listingStats.lastServedMs = Date.now() - startedAt;
        throw error;
      } finally {
        clearTimeout(timer);
        publishListingStats(statsFile);
      }

      /**
       * The listing did not arrive in time. Serve the last known one, or an
       * explicit diagnostic — never a blank, never a hang.
       */
      function serveAfterDeadline() {
        listingStats.timeouts += 1;
        listingStats.deadlineServes += 1;
        // Let a later caller start its own scan instead of queueing behind a
        // flight this caller has already given up on.
        cache.abandon(scope);
        const known = cache.peek(scope);
        listingStats.lastServedMs = Date.now() - startedAt;
        if (known !== undefined) {
          listingStats.staleServes += 1;
          listingStats.lastOutcome = `stale listing after ${deadlineMs} ms (${known.ageMs} ms old)`;
          return known.value;
        }
        listingStats.lastOutcome = `timed out with nothing cached after ${deadlineMs} ms`;
        // `unavailable` is the shipped vocabulary for "this could not be read".
        return [{ kind: 'diagnostic', id: toolName, reason: 'unavailable' }];
      }
    },
  };

  return ctx.tools.register(definition);
}
