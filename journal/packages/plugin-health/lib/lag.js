/**
 * Self-timing event-loop lag sampler — the honest way to measure whether the
 * engine's shared event loop is blocked.
 *
 * WHY SELF-TIMING, AND NOT SOMETHING ELSE
 * A `setInterval(fn, 250)` that records `now - scheduledAt` measures exactly the
 * thing that hurts: the loop was busy and could not run the timer at its due
 * time. It costs one timer wake-up per interval and nothing else — no busy poll,
 * no worker, no allocation on the hot path. `perf_hooks.monitorEventLoopDelay`
 * uses an internal histogram that only reports when polled, cannot report a max
 * over a bounded window, and adds a native reservation per call; the engine also
 * has no reader for it. This module is deliberately the simpler, inspectable
 * thing: a ring of the last N lag readings in whole milliseconds.
 *
 * WHAT IT DOES NOT CLAIM
 * Lag is sampled, not complete: a block that starts and ends between two
 * wake-ups is invisible. That is why the *max* over the window matters more than
 * the mean, and why the window length is published with every read.
 */

/**
 * Fixed-capacity ring of lag readings, in whole milliseconds.
 *
 * Whole milliseconds because a float ring at sub-millisecond resolution is
 * noise dressed as precision: the smallest block that matters here (a
 * `structuredClone` of a large event, a `spawnSync taskkill`) is milliseconds to
 * seconds.
 */
export class LagSampler {
  #ring;
  #at = 0;
  #count = 0;
  #scheduled;
  #timer;

  /**
   * @param {object} options
   * @param {number} [options.intervalMs] wake-up period; also the quantisation floor
   * @param {number} [options.capacity] readings retained
   */
  constructor({ intervalMs = 250, capacity = 512 } = {}) {
    if (!Number.isFinite(intervalMs) || intervalMs <= 0) throw new TypeError('lag: intervalMs must be a positive finite number');
    if (!Number.isInteger(capacity) || capacity <= 0) throw new TypeError('lag: capacity must be a positive integer');
    this.intervalMs = intervalMs;
    this.capacity = capacity;
    this.#ring = new Float64Array(capacity);
  }

  /**
   * Start sampling. Idempotent: a second call is a no-op, because two timers
   * would double-count every wake-up into one ring.
   *
   * The timer is `unref`'d so the sampler can never hold the process open by
   * itself — the engine's own server keeps it alive, and a plugin that keeps a
   * shutting-down engine alive would be a bug.
   */
  start() {
    if (this.#timer !== undefined) return;
    this.#scheduled = Date.now() + this.intervalMs;
    this.#timer = setInterval(() => {
      const now = Date.now();
      const latency = now - this.#scheduled;
      this.#scheduled = now + this.intervalMs;
      this.#ring[this.#at] = latency < 0 ? 0 : latency;
      this.#at = (this.#at + 1) % this.capacity;
      if (this.#count < this.capacity) this.#count += 1;
    }, this.intervalMs);
    if (typeof this.#timer.unref === 'function') this.#timer.unref();
  }

  /** Stop sampling and release the timer. Safe to call more than once. */
  stop() {
    if (this.#timer === undefined) return;
    clearInterval(this.#timer);
    this.#timer = undefined;
  }

  /** Whether the sampler currently owns a timer. */
  get running() {
    return this.#timer !== undefined;
  }

  /** Readings retained, oldest-to-newest insertion order for the sample array. */
  samples() {
    const out = new Array(this.#count);
    for (let i = 0; i < this.#count; i += 1) {
      // Oldest first: when the ring is full, the write cursor holds the oldest.
      const index = (this.#at + this.capacity - this.#count + i) % this.capacity;
      out[i] = this.#ring[index];
    }
    return out;
  }

  /**
   * Percentile and max over the retained window.
   *
   * `p` is a fraction (0.5, 0.95). Nearest-rank, not interpolated: with 512
   * whole-millisecond readings an interpolated p95 would report a value that no
   * wake-up actually observed.
   *
   * @param {number[]} [sorted] an already-sorted sample array, to avoid re-sorting
   */
  summary(sorted) {
    const values = sorted ?? this.samples().sort((a, b) => a - b);
    if (values.length === 0) return { count: 0, p50: null, p95: null, max: null };
    const at = (p) => values[Math.min(values.length - 1, Math.max(0, Math.ceil(p * values.length) - 1))];
    return {
      count: values.length,
      p50: at(0.5),
      p95: at(0.95),
      max: values[values.length - 1],
    };
  }
}
