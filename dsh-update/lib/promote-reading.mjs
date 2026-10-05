/**
 * promote-reading.mjs — THE ONE READING of `verify.json` that decides whether a promote may ride on it.
 *
 * WHY THIS IS ITS OWN MODULE AND NOT A FUNCTION INSIDE cli.mjs.
 * --------------------------------------------------------------------------------------------
 * `preflight` and `promote` each grew their own reading of `verify.json`, and the two disagreed on
 * precisely the upgrade this pipeline exists for. That disagreement was measured, not theorised, and
 * it deadlocked the whole write path.
 *
 * `verify.pass` is true only when EVERY gate that ran is ok. G8 is deliberately NOT ok for a candidate
 * that starts writing a newer session format, because no down-migration codec exists and a rollback
 * therefore stops being a complete undo. On 2026-09-28 `preflight` learned to separate "G8 is the
 * one-way door" from "something else is broken", and could legitimately reach GO with
 * `--accept-session-format-upgrade`. `promote` condition 1 still demanded `verify.pass === true`.
 *
 * The result: preflight GO, `promote` REFUSED on condition 1, and `switch-engine.ps1` rolled the whole
 * switch back. `--accept-session-format-upgrade` could never take effect on any candidate that needed
 * it — a flag that is passed to promote, accepted in the help text, and structurally impossible to
 * satisfy. `switch-engine.ps1`'s own warning said so at the time: "unless G8 passes, promote WILL
 * refuse at step 2 and this switch will roll the pre-state back."
 *
 * Everything in `state/history/events.tsv` for 2026-09-28 is a row from a pipeline that never reached
 * its own write path: `analyze` BREAKS, `patch-effect` BREAKS (against a test fixture's profiles, in
 * that case), `preflight` NO-GO.
 *
 * One module, one function, imported by both verbs, so they cannot drift apart again. A test imports
 * this file directly — `cli.mjs` calls `main()` on import and is deliberately not a library.
 *
 * STRICTNESS IS UNCHANGED, and that is the property to preserve when editing this file.
 * --------------------------------------------------------------------------------------------
 * `ok: true` is returned for exactly two shapes and no others:
 *
 *   (a) 'pass'          — `verify.pass === true` AND no non-opt-in gate failed to run.
 *   (b) 'door-accepted' — every required gate ran, EXACTLY the decision gate(s) failed and nothing
 *                         else, and each failing door was actually accepted.
 *
 * A candidate with any other failing gate, or any required gate that did not run, is `refused` exactly
 * as it was before this module existed. `(b)` cannot swallow a second failure: two failing gates, one
 * of them not a door, falls through to `refused`. A door that did not run is not accepted by either
 * branch, because "an unrun gate is not a pass".
 *
 * NEVER widen `DECISION_GATES` to make a candidate pass. A gate belongs here only if its failure is a
 * deliberate, accepted, one-way consequence rather than a defect — and adding one widens the only hole
 * in a gate that stands between this deployment and an irreversible session-log format change.
 */

/**
 * Gates that are opt-in, so "did not run" is a legitimate reading rather than a gap.
 * GFULL boots the whole web profile and is deliberately not requested by default.
 */
export const OPT_IN_GATES = new Set(['GFULL']);

/**
 * DECISION gates — gates whose failure is a one-way door an operator may walk through consciously,
 * rather than a defect. G8 is the only one: the candidate starts writing session format vN+1, and no
 * down-migration codec exists, so a rollback stops being a complete undo.
 */
export const DECISION_GATES = new Set(['G8']);

/**
 * @param {object|null|undefined} verify  the parsed `state/candidates/<ver>/verify.json`
 * @param {{acceptSessionFormat?: boolean}} [opts]  whether the operator accepted the door
 * @returns {{
 *   ok: boolean,
 *   mode: 'pass'|'door-accepted'|'refused'|'absent',
 *   failing: string[], notRun: string[], unexpectedNotRun: string[],
 *   g8: object|null,
 * }}
 */
export function verifyPromotable(verify, opts = {}) {
  const acceptSessionFormat = opts.acceptSessionFormat === true;
  if (!verify || !Array.isArray(verify.gates)) {
    return { ok: false, mode: 'absent', failing: [], notRun: [], unexpectedNotRun: [], g8: null };
  }
  const gates = verify.gates.filter(Boolean);
  const ran = gates.filter((g) => g.ran === true);
  // `g.ok !== true` rather than `g.ok === false`: a gate whose outcome field is missing has not
  // demonstrated a pass, and treating a malformed gate as passing is the one mistake this function
  // must never make.
  const failing = ran.filter((g) => g.ok !== true).map((g) => g.id);
  const notRun = gates.filter((g) => g.ran !== true).map((g) => g.id);
  const unexpectedNotRun = notRun.filter((id) => !OPT_IN_GATES.has(id));
  const g8 = gates.find((g) => g.id === 'G8') ?? null;
  // A door that is `ok` was never opened for this candidate, so there is nothing to accept.
  const doorAccepted = (id) => id === 'G8' && (g8?.ok === true || acceptSessionFormat);

  // (a) The plain reading. `failing.length === 0` is checked IN ADDITION to `pass === true` on
  // purpose: verify.mjs computes `pass` as "every gate that ran is ok", so the two agree on a
  // well-formed document — and when they disagree the document is self-inconsistent, which is not a
  // pass. Trusting the flag alone would let a malformed verify.json carrying `pass: true` next to a
  // failing gate walk an irreversible change through the one gate that guards it.
  if (verify.pass === true && failing.length === 0 && unexpectedNotRun.length === 0) {
    return { ok: true, mode: 'pass', failing, notRun, unexpectedNotRun, g8 };
  }
  if (failing.length > 0
    && failing.every((id) => DECISION_GATES.has(id))
    && unexpectedNotRun.length === 0
    && failing.every(doorAccepted)) {
    return { ok: true, mode: 'door-accepted', failing, notRun, unexpectedNotRun, g8 };
  }
  return { ok: false, mode: 'refused', failing, notRun, unexpectedNotRun, g8 };
}
