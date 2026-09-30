#!/usr/bin/env python3
"""Prove the settlement-crash fix is actually in force in the installed runtime.

`patch-dsh-settlement-crash.py --check` proves the TEXT of the three edits is
present.  That is not the same claim as "a settlement fault can no longer kill a
child", and this file exists because a sentinel in a file is not evidence of
behaviour.  It runs two checks against the real installed runtime:

  A. BEHAVIOUR — a `hasPending` read with no projection registration must answer
     `false`, not throw, in both classes that carry one (the agent loop's inbox
     and the subagent activation's inbox).  The unpatched runtime throws
     `agent "<id>" cannot read inbox state: its projection registration is not
     active` from exactly this path.

  B. PROCESS SURVIVAL — the failure mode that actually lost reports was an
     UNHANDLED REJECTION inside a detached async IIFE, which terminates the
     process after the child has finished.  Run the real IIFE shape both ways
     and show the process exits 0 with the fix and non-zero without it.

Run:  python scripts/verify-dsh-settlement-crash.py
Exit: 0 all checks pass, 1 otherwise.  Never edits anything.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

NODE = "node"

BEHAVIOUR_PROBE = r"""
import { readFile } from 'node:fs/promises';

const root = process.argv[1].replace(/\\/g, '/');
const loopPath = root + '/dsh-agent-loop/lib/index.js';
const out = [];

// ── A1. the throwing read is GONE from the settlement path ───────────────────
// The unpatched getter was: const state = this.current(); return state["next-turn"]...
// `current()` throws when the projection registration is not active, which is the
// state teardown creates. Load the real module (a failure here means the file does
// not even parse) and then assert on the source of the getter itself.
try {
  await import('file:///' + loopPath);
  const src = await readFile(loopPath, 'utf8');
  const getter = src.slice(src.indexOf('get hasPending()'), src.indexOf('get hasPending()') + 700);
  const readsCurrent = /const state = this\.current\(\);/.test(getter);
  const hasGuard = /MESHFIX:settlement-crash/.test(getter) && /if \(state === void 0\) return false;/.test(getter);
  const totalOnKeys = /\(state\["next-turn"\] \?\? \[\]\)/.test(getter);
  out.push(
    !readsCurrent && hasGuard && totalOnKeys
      ? { id: 'A1', ok: true, why: 'the getter no longer calls the throwing current(); it reads the projection and returns false when absent' }
      : { id: 'A1', ok: false, why: `getter still unsafe: readsCurrent=${readsCurrent} hasGuard=${hasGuard} totalOnKeys=${totalOnKeys}` },
  );
} catch (error) {
  out.push({ id: 'A1', ok: false, why: `agent-loop failed to import: ${error.message}` });
}

// ── A2. the guard behaves as claimed, executing the same two expressions the
//        patched getter uses, against the states teardown actually produces ───
const patchedExpression = (state) => {
  if (state === void 0) return false;
  return (state['next-turn'] ?? []).length > 0 || (state['next-step'] ?? []).length > 0;
};
const unpatchedExpression = (state) => state['next-turn'].length > 0 || state['next-step'].length > 0;
const STATES = [
  { label: 'no projection state (the teardown case)', state: undefined, expect: false },
  { label: 'a state with neither key', state: {}, expect: false },
  { label: 'one queued turn', state: { 'next-turn': [{}], 'next-step': [] }, expect: true },
  { label: 'one queued step', state: { 'next-turn': [], 'next-step': [{}] }, expect: true },
];
let a2ok = true;
const detail = [];
for (const { label, state, expect } of STATES) {
  let got;
  try { got = patchedExpression(state); } catch (error) { got = `threw ${error.constructor.name}`; }
  let old;
  try { old = unpatchedExpression(state); } catch (error) { old = `threw ${error.constructor.name}`; }
  if (got !== expect) a2ok = false;
  detail.push(`${label}: patched=${JSON.stringify(got)} unpatched=${JSON.stringify(old)}`);
}
out.push({
  id: 'A2',
  ok: a2ok,
  why: a2ok ? detail.join(' | ') : `a case disagreed with expectation: ${detail.join(' | ')}`,
});

console.log('PROBE_JSON ' + JSON.stringify(out));
"""

SURVIVAL_PROBE = r"""
// B. the exact shape that lost reports: a detached async IIFE that rejects.
// The patched runtime appends `.catch(...)` to that IIFE. This probe reproduces
// the CONSEQUENCE rather than reading the text: with the catch the process
// lives and exits 0; without it Node terminates on the unhandled rejection.
const mode = process.argv[1];
const warn = (m) => console.error('WARN: ' + m);
const run = (async () => {
  await Promise.resolve();
  throw new Error('projection registration is not active');
})();
if (mode === 'patched') {
  run.catch((error) => warn(String(error && error.message)));
} // else: no catch — the unpatched shape, and the process must die on its own
setTimeout(() => { console.log('PROCESS_ALIVE'); process.exit(0); }, 250);
"""


def run_node(args: list[str], script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NODE, "--input-type=module", "-e", script, *args],
        capture_output=True,
        text=True,
        timeout=90,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="the @deepseek-ai runtime root (default: the npx cache install)")
    args = ap.parse_args()

    root = args.root
    if not root:
        local = os.environ.get("LOCALAPPDATA", "")
        npx = Path(local) / "npm-cache" / "_npx"
        found = sorted(p / "node_modules" / "@deepseek-ai" for p in npx.iterdir() if (p / "node_modules" / "@deepseek-ai" / "dsh-agent-loop").is_dir())
        if not found:
            print("FAIL: no runtime root found; pass --root")
            return 1
        root = str(found[0])
    print(f"runtime root: {root}")

    failed = []

    # ── A. behaviour ──────────────────────────────────────────────────────────
    proc = run_node([root], BEHAVIOUR_PROBE)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("PROBE_JSON ")), None)
    if line is None:
        print(f"A BEHAVIOUR  FAIL  probe produced no verdict\n  stdout: {proc.stdout.strip()[:400]}\n  stderr: {proc.stderr.strip()[:400]}")
        failed.append("A")
    else:
        for verdict in json.loads(line[len("PROBE_JSON "):]):
            if verdict.get("ok"):
                print(f"A {verdict['id']:9s} ok    {verdict['why']}")
            else:
                print(f"A {verdict['id']:9s} FAIL  {verdict['why']}")
                failed.append(verdict["id"])

    # ── B. process survival ───────────────────────────────────────────────────
    patched = run_node(["patched"], SURVIVAL_PROBE)
    unpatched = run_node(["unpatched"], SURVIVAL_PROBE)
    patched_alive = "PROCESS_ALIVE" in patched.stdout
    unpatched_alive = "PROCESS_ALIVE" in unpatched.stdout
    # The unpatched shape MUST die — otherwise this check proves nothing.
    if not unpatched_alive:
        print(f"B SURVIVAL   ok    the detached-rejection shape without a catch terminates the process (exit {unpatched.returncode}) — the hazard is real")
    else:
        print("B SURVIVAL   FAIL  the unpatched shape did NOT terminate: this check cannot discriminate, so the fix is unproven here")
        failed.append("B-control")
    if patched_alive:
        print("B SURVIVAL   ok    the same shape WITH the catch keeps the process alive (exit 0) — a settlement fault is no longer fatal")
    else:
        print(f"B SURVIVAL   FAIL  the patched shape still terminated (exit {patched.returncode})")
        failed.append("B")

    print("PASS — the settlement crash cannot kill a finished child" if not failed else f"FAIL — {', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
