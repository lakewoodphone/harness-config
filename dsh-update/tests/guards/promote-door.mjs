/**
 * promote-door.mjs — the guard that holds the fix for the promote/preflight deadlock.
 *
 * THE DEFECT IT HOLDS FIXED (measured 2026-10-05, on the real pipeline).
 * --------------------------------------------------------------------------------------------
 * `preflight` and `promote` each carried their own reading of `verify.json`, and they disagreed on
 * precisely the upgrade this pipeline exists for. Preflight learned that G8 is a one-way DOOR an
 * operator may accept, and could reach GO with `--accept-session-format-upgrade`. Promote condition 1
 * still demanded `verify.pass === true`, and `verify.pass` is false whenever any gate that ran failed
 * — which G8 always is, for a candidate that starts writing a newer session format.
 *
 * So the flag that promote itself advertises, and that switch-engine.ps1 passes to it, could never
 * take effect. Promote refused at condition 1, and switch-engine.ps1 rolled the whole switch back.
 * `switch-engine.ps1`'s own warning at the time described the deadlock exactly: "unless G8 passes,
 * promote WILL refuse at step 2 and this switch will roll the pre-state back."
 *
 * Both verbs now call `verifyPromotable` from `lib/promote-reading.mjs`, and this file is the proof
 * that it is BOTH permissive enough to let an accepted door through AND strict enough that a door
 * cannot be used to smuggle a second failure past the gate.
 *
 * Run:  node dsh-update/tests/guards/promote-door.mjs        (exit 0 pass, 1 fail)
 *
 * It reads nothing, starts nothing, opens no port and touches no state: the function is pure.
 */

import { verifyPromotable, DECISION_GATES } from '../../lib/promote-reading.mjs';

let failures = 0;
let checks = 0;

function check(name, actual, expected) {
  checks += 1;
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    process.stdout.write(`  ok    ${name}\n`);
  } else {
    failures += 1;
    process.stdout.write(`  FAIL  ${name}\n        expected ${e}\n        actual   ${a}\n`);
  }
}

/** A well-formed verify.json: G1-G8 ran and passed, GFULL legitimately did not run. */
const allPass = () => ({
  pass: true,
  gates: [
    { id: 'G1', ran: true, ok: true }, { id: 'G2', ran: true, ok: true },
    { id: 'G3', ran: true, ok: true }, { id: 'G4', ran: true, ok: true },
    { id: 'G5', ran: true, ok: true }, { id: 'G6', ran: true, ok: true },
    { id: 'G7', ran: true, ok: true }, { id: 'G8', ran: true, ok: true },
    { id: 'GFULL', ran: false, ok: false },
  ],
});

/** All gates pass EXCEPT G8, the session-format one-way door. */
const g8Only = () => {
  const v = allPass();
  v.pass = false;
  v.gates.find((g) => g.id === 'G8').ok = false;
  return v;
};

const withGate = (v, id, patch) => {
  Object.assign(v.gates.find((g) => g.id === id), patch);
  return v;
};

process.stdout.write('promote-door: the one reading of verify.json\n');

// ── the strict half: everything the OLD behaviour refused must still be refused ───────────────────
check('null verify -> absent, not promotable',
  verifyPromotable(null).mode, 'absent');
check('a document with no gates array -> absent',
  verifyPromotable({ pass: true }).mode, 'absent');
check('all gates pass -> promotable, mode=pass',
  verifyPromotable(allPass()).mode, 'pass');
check('G8 fails and NOTHING accepts it -> refused (the door is not silently open)',
  verifyPromotable(g8Only()).mode, 'refused');
check('G8 fails and it is accepted -> promotable, mode=door-accepted',
  verifyPromotable(g8Only(), { acceptSessionFormat: true }).mode, 'door-accepted');
check('acceptance is false-y -> refused',
  verifyPromotable(g8Only(), { acceptSessionFormat: false }).mode, 'refused');
check('acceptance of the wrong thing (a string) -> refused',
  verifyPromotable(g8Only(), { acceptSessionFormat: 'yes' }).mode, 'refused');

// ── the property that makes it safe: a door cannot carry a second failure ────────────────────────
check('G8 + G2 fail, door accepted -> refused (a second failure is never swallowed)',
  verifyPromotable(withGate(g8Only(), 'G2', { ok: false }), { acceptSessionFormat: true }).mode, 'refused');
check('G8 + G2 fail, door NOT accepted -> refused',
  verifyPromotable(withGate(g8Only(), 'G2', { ok: false })).mode, 'refused');
check('G8 fails and a REQUIRED gate did not run -> refused even though the door is accepted',
  verifyPromotable(withGate(g8Only(), 'G4', { ran: false, ok: false }), { acceptSessionFormat: true }).mode, 'refused');
check('G8 present but did not run -> refused (an unrun gate is not a pass)',
  verifyPromotable(withGate(g8Only(), 'G8', { ran: false }), { acceptSessionFormat: true }).mode, 'refused');
check('an opt-in gate (GFULL) that did not run does NOT block the accepted door',
  verifyPromotable(g8Only(), { acceptSessionFormat: true }).mode, 'door-accepted');

// ── self-consistency: a lying document is refused, not trusted ───────────────────────────────────
check('pass:true while a gate failed -> refused (do not trust the flag over the gates)',
  verifyPromotable(withGate(allPass(), 'G8', { ok: false })).mode, 'refused');
check('a gate whose ok field is MISSING counts as failing, not as passing',
  verifyPromotable({ pass: true, gates: [{ id: 'G1', ran: true }, { id: 'G8', ran: true, ok: true }] }).mode, 'refused');
check('pass:true with no gates having run at all -> refused',
  verifyPromotable({ pass: true, gates: [{ id: 'G8', ran: false, ok: true }] }).mode, 'refused');

// ── the invariant that must survive any edit to the module ───────────────────────────────────────
check('G8 is the ONLY decision gate (widening this widens an irreversible gate)',
  [...DECISION_GATES], ['G8']);

process.stdout.write(`\npromote-door: ${checks - failures}/${checks} assertion(s) passed\n`);
if (failures > 0) {
  process.stdout.write('promote-door: FAIL — do not promote on a reading this file does not agree with.\n');
  process.exit(1);
}
process.exit(0);
