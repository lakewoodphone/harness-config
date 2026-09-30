/**
 * What went wrong with one remote child, and whether it may be retried.
 *
 * WHY THIS FILE EXISTS
 * A failed remote child used to be terminal: `start()` rejected at placement, or
 * the run settled `stopReason: 'error'`, and the whole dispatch was over. There
 * was no retry, no second node, and no way to ask for one. Two children died with
 * `exited 4294967295 and produced no final message` on 2026-09-30 and ten minutes
 * of fleet time bought nothing.
 *
 * The harder half is not "retry", it is "what may NOT be retried". A child that
 * already ran may have committed to a git branch, written files, or spent money.
 * A blind retry of that child is duplicate work with duplicate side effects, and
 * on a fleet it is the single most expensive mistake available. So every failure
 * is classified first, and the classification — not a counter — decides whether
 * the work is attempted again.
 *
 * THE FOUR ANSWERS
 *   structural                 the child ran and answered, or the caller gave up:
 *                              never retry, report it
 *   transient-same-node        the child provably never launched and the node is
 *                              plausibly fine: retry the SAME node
 *   node-specific / reroute    the child provably never launched and the node is
 *                              the problem: retry a DIFFERENT node
 *   child-ran-transport-fault  the child very likely did the work and only the
 *                              report was lost: HARVEST, never re-dispatch
 *
 * Everything here is pure. No I/O, no clock, no randomness that is not injected —
 * so the policy is testable, and so a caller can read the decision rather than
 * infer it from behaviour.
 */

/** The classification vocabulary, in one place so callers cannot drift. */
export const FAILURE_CLASSES = Object.freeze([
  'none',
  'transient-same-node',
  'node-specific',
  'reroute-only',
  'structural',
  'child-ran-transport-fault',
]);

/** Default budget. Justified in the comment below, not vibes. */
export const DEFAULT_RETRY_POLICY = Object.freeze({
  /**
   * THREE transport attempts, not more. The measured transport/read failure rate
   * on this mesh is bursty and tens of percent (journal P2819/P2554: 165 of 2820
   * reads failed on one day, 995 of 1653 on another), so a single retry is worth
   * having; a fourth attempt buys little and multiplies the duplicate-side-effect
   * and spend risk, which is the thing that actually costs money here.
   */
  maxAttempts: 3,
  /**
   * AT MOST TWO NODES. One reroute covers a node-specific fault — a node with a
   * wedged sshd or a broken executor. Spreading one child across three nodes
   * starts costing more wall clock than the child is worth.
   */
  maxDistinctNodes: 2,
  /** ~2 s: long enough to clear a transient socket/agent hiccup, short enough
   *  that a fleet does not visibly stall. Jittered by the caller. */
  backoffMs: 2_000,
  /** ~15 s: chosen to OUTLIVE the broker's 15 s capacity-cache TTL, so a reroute
   *  is ranked against a fresh reading rather than the one that just failed. */
  rerouteBackoffMs: 15_000,
  /** 45 min overall. Above the deployed 30-minute child timeout (so a slow but
   *  healthy child is never cut off by the retry budget) and well below the
   *  previous worst case, where a silent double timeout burned an hour. */
  totalCeilingMs: 45 * 60_000,
});

/** Does this outcome prove the child process never started? */
export function childNeverStarted(outcome, parsed) {
  if (outcome === undefined || outcome === null) return false;
  // The client itself could not be launched — nothing ran.
  if (typeof outcome.spawnError === 'string' && outcome.spawnError !== '') return true;
  // A shell command that was never found: the child was never executed.
  if (outcome.exitCode === 127 && (parsed === undefined || parsed?.framed !== true)) return true;
  return false;
}

/**
 * Classify one settled attempt.
 *
 * @param outcome  the transport outcome (exitCode, signal, timedOut, spawnError, stderr, ms)
 * @param parsed   the parsed frame (framed, host, answer, exitCode)
 * @param options.startedEvidence  true when a sentinel/progress file proves the child began;
 *                                 false when it proves it did not; undefined when unknown
 * @param options.aborted          the run was cancelled or disposed locally
 * @param options.hostMismatch     the recorded host contradicts the placed node (a real wrong-machine run)
 */
export function classifyFailure({ outcome, parsed, startedEvidence, aborted, hostMismatch } = {}) {
  // Cancellation is the caller's own decision. Retrying it would ignore them.
  if (aborted === true) return 'structural';
  if (outcome === undefined || outcome === null) return 'structural';

  // A wrong-machine run is a placement/protocol fault, not a transport one. The
  // work exists and belongs to the operator, so it is reported, never re-run.
  if (hostMismatch === true) return 'structural';

  const framed = parsed?.framed === true;
  const producedAnswer = typeof parsed?.answer === 'string' && parsed.answer !== '';

  // ── SUCCESS FIRST, EXPLICITLY ─────────────────────────────────────────────
  // Everything below is a failure rule, so the success case must be recognised
  // before any of them can accidentally claim it. (Measured 2026-09-30: without
  // this the classifier reported a clean run as `structural`, and the retry loop
  // read that as "stop", which is the sort of bug that hides behind a green test.)
  if (outcome.exitCode === 0 && framed) return 'none';

  // Two DIFFERENT signals, and conflating them loses work (my own test caught
  // this). A hard refusal means the session was never established, so nothing
  // ran and another node is worth asking. A transport fault mid-run means the
  // child may already be working, so it must NOT be re-dispatched.
  const stderr = String(outcome.stderr ?? '');
  const sshRefused = /Permission denied|Host key verification failed|Connection refused|kex_exchange_identification|Network is unreachable|no route to host/i.test(stderr);
  const transportFault = /Connection timed out|Operation timed out|Connection reset|send disconnect|Read from remote host|Broken pipe|Connection closed/i.test(stderr);
  if (!framed && !producedAnswer && !sshRefused && transportFault) return 'child-ran-transport-fault';
  if (!framed && !producedAnswer && sshRefused) return 'node-specific';

  // Nothing at all came back and the child provably never launched: the cheapest
  // and most common failure, and the one a retry genuinely fixes.
  if (childNeverStarted(outcome, parsed)) {
    return sshRefused ? 'node-specific' : 'transient-same-node';
  }

  // The child started. Whatever happened next, the work may exist — retrying it
  // would duplicate side effects, so this is harvest-or-report territory, never
  // re-dispatch.
  if (startedEvidence === true) return 'child-ran-transport-fault';

  if (outcome.timedOut === true) return 'child-ran-transport-fault';

  // A non-zero exit WITH a frame and an answer is the child's own outcome. If the
  // child reasoned, that is its answer and it is structural.
  if (outcome.exitCode !== 0 && outcome.exitCode !== undefined) {
    if (framed || producedAnswer) return 'structural';
    // NO FRAME, NO ANSWER, NOTHING IN STDERR — and this is the measured
    // production shape: the transport died before the closing frame was written,
    // so the child's last moment was never captured. It may have done work, so
    // the honest reading is "harvest, do not re-run". A retry here is the
    // duplicate-side-effect risk the whole policy exists to avoid.
    return 'child-ran-transport-fault';
  }

  // Exit 0 with no frame: the target profile never ran. Nothing was produced.
  if (outcome.exitCode === 0 && !framed) return 'transient-same-node';

  return 'structural';
}

/**
 * Turn one classification into an action, given what has already been spent.
 *
 * @param classification  from classifyFailure
 * @param attemptIndex    0 for the first attempt
 * @param options.distinctNodes how many different nodes have been used so far
 * @param options.elapsedMs     wall clock since the first attempt started
 * @param options.random        injectable [0,1) source, for deterministic tests
 */
export function planFor(classification, attemptIndex = 0, options = {}) {
  const policy = { ...DEFAULT_RETRY_POLICY, ...(options.policy ?? {}) };
  const random = typeof options.random === 'function' ? options.random : Math.random;
  const elapsedMs = Number.isFinite(options.elapsedMs) ? options.elapsedMs : 0;
  const distinctNodes = Number.isFinite(options.distinctNodes) ? options.distinctNodes : 1;
  const jitter = (base) => Math.round(base * (0.75 + random() * 0.5));

  if (classification === 'none') return { action: 'accept', delayMs: 0, reason: 'the run succeeded' };

  // Harvest is not a retry: no budget is consumed and no delay is paid. The work
  // is either recoverable from the remote node or it is lost, and waiting does
  // not change which.
  if (classification === 'child-ran-transport-fault') {
    return {
      action: 'harvest',
      delayMs: 0,
      reason: 'the child started, so re-dispatching it could duplicate side effects — the report is harvested instead',
    };
  }

  if (classification === 'structural') {
    return { action: 'fail', delayMs: 0, reason: 'the child ran and its outcome is its own; retrying would re-run decided work' };
  }

  if (elapsedMs >= policy.totalCeilingMs) {
    return {
      action: 'fail',
      delayMs: 0,
      reason: `${Math.round(elapsedMs / 1000)} s of the ${Math.round(policy.totalCeilingMs / 1000)} s retry ceiling is spent — stopping rather than starting another attempt`,
    };
  }

  const attemptsUsed = attemptIndex + 1;
  if (attemptsUsed >= policy.maxAttempts) {
    return {
      action: 'fail',
      delayMs: 0,
      reason: `${attemptsUsed} of ${policy.maxAttempts} transport attempts are spent`,
    };
  }

  const wantsDifferentNode = classification === 'node-specific' || classification === 'reroute-only';
  if (wantsDifferentNode && distinctNodes >= policy.maxDistinctNodes) {
    // Try again on the node we have rather than declare defeat: the node may have
    // recovered, and the remaining attempt is worth more than nothing.
    return {
      action: 'retry',
      delayMs: jitter(policy.backoffMs),
      reason: `${distinctNodes} node(s) already used, which is the limit — retrying the current node instead of rerouting`,
    };
  }

  return wantsDifferentNode
    ? {
      action: 'reroute',
      delayMs: jitter(policy.rerouteBackoffMs),
      reason: 'the node is the problem, so the reroute delay outlives the broker\'s 15 s capacity cache and this attempt is ranked on a fresh reading',
    }
    : {
      action: 'retry',
      delayMs: jitter(policy.backoffMs),
      reason: 'the child never launched and the node is plausibly fine',
    };
}

/** One line a reader can check, for the report header. */
export function describeRetryPolicy(policy = {}) {
  const p = { ...DEFAULT_RETRY_POLICY, ...policy };
  return `at most ${p.maxAttempts} transport attempt(s) across at most ${p.maxDistinctNodes} node(s); `
    + `same-node retry after ~${Math.round(p.backoffMs / 1000)} s, reroute after ~${Math.round(p.rerouteBackoffMs / 1000)} s; `
    + `${Math.round(p.totalCeilingMs / 60000)} min total ceiling; a child that started is NEVER re-dispatched`;
}

/** One line describing one attempt, for the report header. */
export function describeAttempt(n, { node, classification, action, detail, delayMs, startedEvidence } = {}) {
  const parts = [`node "${node ?? '?'}"`, `— ${classification ?? '?'}`];
  if (startedEvidence === true) parts.push('— child started');
  else if (startedEvidence === false) parts.push('— child not-started');
  if (detail !== undefined && detail !== '') parts.push(`— ${detail}`);
  if (action === 'retry') parts.push(`— RETRYING IN ${delayMs} ms`);
  else if (action === 'reroute') parts.push(`— REROUTING IN ${delayMs} ms`);
  else if (action === 'harvest') parts.push('— HARVESTING, NOT RE-DISPATCHING');
  return `attempt ${n} = ${parts.join(' ')}`;
}

/**
 * A bounded salvage for a failure with nothing else to show. `remote-script.js`
 * exports `harvestOutput`, which is the real implementation; this fallback keeps
 * the provider honest about a failure whose work is genuinely gone instead of
 * printing a bare diagnostic.
 */
export function fallbackHarvest(outcome, parsed, { maxBytes = 4000 } = {}) {
  const parts = [];
  if (typeof parsed?.answer === 'string' && parsed.answer !== '') parts.push({ source: 'answer', text: parsed.answer });
  const tail = (text, source) => {
    const value = String(text ?? '');
    if (value === '') return;
    parts.push({ source, text: value.length > maxBytes ? `…[truncated]…\n${value.slice(-maxBytes)}` : value });
  };
  tail(outcome?.stdout, 'stdout-tail');
  tail(outcome?.stderr, 'stderr-tail');
  parts.push({
    source: 'outcome',
    text: `exit=${outcome?.exitCode ?? 'none'} signal=${outcome?.signal ?? 'none'} timedOut=${outcome?.timedOut === true} in ${outcome?.ms ?? '?'} ms`,
  });
  const text = parts.map((p) => `[${p.source}]\n${p.text}`).join('\n');
  return { text, complete: parsed?.framed === true, parts };
}

/** Resolve `harvestOutput` if the transport module provides it, else the fallback. */
export function resolveHarvest(candidate) {
  return typeof candidate === 'function' ? candidate : fallbackHarvest;
}
