/**
 * A pure circuit breaker for one node's TRANSPORT health, with an injected
 * clock and no timers, no I/O, and no process state.
 *
 * WHY THIS EXISTS (F3)
 * A node whose sshd handshake stretched to 8 seconds under load — and the load
 * was our own fan-out — is a node we should stop piling onto. The transport's
 * own `ConnectTimeout=10` was not enough because the node that was slow was the
 * one receiving the children. The breaker counts consecutive TRANSPORT failures
 * per node, opens for a cooldown, lets one probe through, and closes only after
 * the configured number of half-open successes.
 *
 * THE RULE THAT MATTERS (F4)
 * 'structural' failures are a child that RAN and returned a wrong answer (wrong
 * or missing `MESH-HOST:`, disagreeing location, a refused model, a bad final
 * message). Those say something about the child, not about the wire, and they
 * must NEVER open the circuit. Only transport/placement-class failures — a
 * refused connection, a timeout, a spawn error, an unreachable broker — do.
 * Passing no `kind` is therefore a transport-class failure, which is the safe
 * default: the caller only has to name the exception.
 *
 * The state machine is deterministic given `now`, so every transition is
 * testable with a fake clock.
 *
 * @param {object} [options]
 * @param {() => number} [options.now]              injected clock (epoch ms)
 * @param {number} [options.failureThreshold]        consecutive transport failures that open the circuit
 * @param {number} [options.cooldownMs]              how long an open circuit refuses work
 * @param {number} [options.halfOpenSuccesses]       successes needed to close from half-open
 */

/** A finite integer at least `minimum`, or `fallback`. */
function positiveInt(value, fallback, minimum = 1) {
  const n = Number(value);
  return Number.isFinite(n) && n >= minimum ? Math.floor(n) : fallback;
}

export function createCircuitBreaker(options = {}) {
  const {
    now = () => Date.now(),
    failureThreshold = 3,
    cooldownMs = 60000,
    halfOpenSuccesses = 1,
  } = options ?? {};
  const clock = typeof now === 'function' ? now : () => Date.now();
  const threshold = positiveInt(failureThreshold, 3, 1);
  const cooldown = positiveInt(cooldownMs, 60000, 0);
  const requiredWins = positiveInt(halfOpenSuccesses, 1, 1);

  /** node -> { state, consecutiveFailures, openedAt, lastKind, halfOpenWins } */
  const nodes = new Map();

  const entryFor = (node) => {
    const key = String(node);
    let entry = nodes.get(key);
    if (entry === undefined) {
      entry = { state: 'closed', consecutiveFailures: 0, openedAt: 0, lastKind: undefined, halfOpenWins: 0 };
      nodes.set(key, entry);
    }
    return entry;
  };

  const time = () => {
    const t = Number(clock());
    return Number.isFinite(t) ? t : 0;
  };

  /** An open circuit becomes half-open once its cooldown has elapsed. */
  const refresh = (node, at = time()) => {
    const entry = entryFor(node);
    if (entry.state === 'open' && at - entry.openedAt >= cooldown) {
      entry.state = 'half-open';
      entry.halfOpenWins = 0;
    }
    return entry;
  };

  const open = (entry, at) => {
    entry.state = 'open';
    entry.openedAt = at;
    entry.halfOpenWins = 0;
  };

  return {
    /** The node's state as of now: 'closed' | 'open' | 'half-open'. */
    state(node) {
      return refresh(node).state;
    },

    /** May a call be attempted right now? false only while an open circuit cools. */
    allow(node) {
      return refresh(node).state !== 'open';
    },

    /** A transport call completed: closes after the configured half-open wins. */
    recordSuccess(node) {
      const at = time();
      const entry = refresh(node, at);
      if (entry.state === 'half-open') {
        entry.halfOpenWins += 1;
        if (entry.halfOpenWins >= requiredWins) {
          entry.state = 'closed';
          entry.consecutiveFailures = 0;
          entry.openedAt = 0;
          entry.halfOpenWins = 0;
          entry.lastKind = undefined;
        }
      } else if (entry.state === 'closed') {
        entry.consecutiveFailures = 0;
      }
    },

    /**
     * A call failed. `kind: 'structural'` (the child ran and the wire was fine)
     * is ignored for state; anything else counts toward opening the circuit.
     */
    recordFailure(node, options = {}) {
      const kind = options?.kind;
      const at = time();
      const entry = refresh(node, at);
      entry.lastKind = kind ?? 'transport';
      if (kind === 'structural') return;

      entry.consecutiveFailures += 1;
      if (entry.state === 'half-open') {
        open(entry, at);
      } else if (entry.state === 'closed' && entry.consecutiveFailures >= threshold) {
        open(entry, at);
      }
    },

    /** Epoch ms until this node may be tried again; 0 when it is not sleeping. */
    sleepUntil(node) {
      const at = time();
      const entry = refresh(node, at);
      return entry.state === 'open' ? entry.openedAt + cooldown : 0;
    },

    /** A serialisable read of every node the breaker has seen. */
    snapshot() {
      const at = time();
      const out = {};
      for (const node of nodes.keys()) {
        const entry = refresh(node, at);
        out[node] = {
          state: entry.state,
          consecutiveFailures: entry.consecutiveFailures,
          openedAt: entry.openedAt,
          sleepingMs: entry.state === 'open' ? Math.max(0, entry.openedAt + cooldown - at) : 0,
          lastKind: entry.lastKind,
        };
      }
      return { nodes: out };
    },
  };
}
