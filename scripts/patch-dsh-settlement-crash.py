#!/usr/bin/env python3
"""Patch the pinned DSH runtime so a child agent can never die at settlement.

THE DEFECT (found 2026-09-30, root cause read out of the source, not guessed)

A child agent that has FINISHED its work can still crash, and when it does its
entire report is lost and the process exits with no message.  Three real
incidents are on record (journal P2249b, P2253b), and two were reproduced in
this seat's own hands on 2026-09-30 when two mesh dispatches each returned
`the remote one-shot exited 4294967295 ... produced no final message` after the
child had already printed its opening frame.

The chain, every link read in the installed runtime at 0.1.5-rc.2:

  dsh-subagent/lib/index.js:1148   watchSettlement() starts an async IIFE
                                   `(async () => { while (true) { ... } })()`
                                   WITH NO `.catch` on it.
  dsh-subagent/lib/index.js:1153   calls this.settlementState(...)
  dsh-subagent/lib/index.js:1196   `if (activation.inbox.hasPending || ...)`
  dsh-subagent/lib/index.js:712    `get hasPending()` -> `this.agent.inbox.nextTurn`
  dsh-agent-loop/lib/index.js:82   `get nextTurn()` -> `this.current()["next-turn"]`
  dsh-agent-loop/lib/index.js:178  `current()` THROWS when the inbox projection
                                   registration is no longer active:
                                   `agent "<id>" cannot read inbox state: its
                                   projection registration is not active`

The projection registration is owned by the child agent's own scope fiber and is
released when that scope is disposed.  During teardown the scope can be disposed
before the settlement watcher's last read, so the watcher throws.  Because the
IIFE has no catch, the throw becomes an UNHANDLED REJECTION, which the harness
turns into a process exit — losing the finished child's report exactly at the
moment it was about to be delivered.

WHY THIS PATCH AND NOT A VERSION BUMP

Upgrading the runtime is a change to every running agent session and is not this
script's call.  This patch is deliberately the smallest change that removes the
failure mode, and it is written to FAIL LOUDLY rather than silently stop
working when the runtime changes underneath it.

WHAT IT CHANGES (three edits, all idempotent)

  1. dsh-agent-loop/lib/index.js      `hasPending` becomes total: no projection
                                      state means "nothing pending" (`false`),
                                      which is the only sensible answer during
                                      teardown.
  2. dsh-subagent/lib/index.js        the activation's `hasPending` reads its
                                      agent's inbox defensively.
  3. dsh-subagent/lib/index.js        `watchSettlement`'s IIFE gets a `.catch`
                                      that LOGS instead of crashing the process.

Every edit inserts a sentinel marker, so a second run is a no-op and `--check`
can prove the install is patched.

USAGE
    python patch-dsh-settlement-crash.py            # patch (idempotent)
    python patch-dsh-settlement-crash.py --check    # exit 1 if not patched
    python patch-dsh-settlement-crash.py --root DIR # a different runtime root

Exit codes: 0 patched or already-patched and verified; 1 nothing was patched and
something is wrong (missing anchor, unpatched under --check, verification
failed).  It never edits a file it could not first read and anchor.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path

SENTINEL = "MESHFIX:settlement-crash"

# ── edit 1: dsh-agent-loop/lib/index.js ───────────────────────────────────────
LOOP_OLD = """	/** Whether either pending-message list contains work. */
	get hasPending() {
		const state = this.current();
		return state["next-turn"].length > 0 || state["next-step"].length > 0;
	}"""
LOOP_NEW = """	/** Whether either pending-message list contains work. */
	get hasPending() {
		// MESHFIX:settlement-crash — this getter is reachable from the settlement
		// watcher AFTER the agent's own scope has released the "inbox" projection
		// registration, at which point current() throws. A throw here killed a
		// finished child's report (P2249b/P2253b). No projection state means
		// nothing pending, so the total answer during teardown is `false`.
		const state = this.projections.stateOf(this.session, "inbox");
		if (state === void 0) return false;
		return (state["next-turn"] ?? []).length > 0 || (state["next-step"] ?? []).length > 0;
	}"""

# ── edit 2: dsh-subagent/lib/index.js, the activation's hasPending ─────────────
SUB_INBOX_OLD = """	get hasPending() {
		return this.agent.inbox.nextTurn.length > 0 || this.agent.inbox.nextStep.length > 0;
	}"""
SUB_INBOX_NEW = """	get hasPending() {
		// MESHFIX:settlement-crash — total during teardown: the agent's inbox (and
		// the projection behind it) can already be gone when the settlement watcher
		// reads this. `false` is the honest answer, and it cannot throw.
		const inbox = this.agent?.inbox;
		if (inbox === void 0 || inbox === null) return false;
		try {
			return inbox.nextTurn.length > 0 || inbox.nextStep.length > 0;
		} catch {
			return false;
		}
	}"""

# ── edit 3: the settlement watcher's missing catch ────────────────────────────
WATCH_OLD = """				return;
			}
		})();
	}
	/** Classify one Inbox and owned-child observation without reading Agent execution state. */
	settlementState(activation, observation) {"""
WATCH_NEW = """				return;
			}
		})().catch((error) => {
			// MESHFIX:settlement-crash — an unhandled rejection here terminates the
			// whole child process AFTER its work is done, which is why a finished
			// child's report vanished with no message and exit -1. A settlement
			// fault must be reported, never fatal.
			try {
				this.ctx.logger.warn(`subagent "${activation.childId}" settlement watcher failed: ${String(error?.stack ?? error)}`);
			} catch {
				// a logger that itself throws must not resurrect the crash
			}
		});
	}
	/** Classify one Inbox and owned-child observation without reading Agent execution state. */
	settlementState(activation, observation) {"""

# The same edits for the module variant, which is where the registry CLASS actually
# lives: `dsh-subagent/lib/index.js` re-exports it, and the recorded crash stack
# names index.js only because that is the entry point that was loaded.
ACT_OLD = """        if (activation.inbox.hasPending || activation.ownedChildren.size > 0)
            return 'wait';"""
ACT_NEW = """        // MESHFIX:settlement-crash — total during teardown: the agent's inbox
        // projection can already be released when this runs.
        if ((activation.inbox?.hasPending ?? false) || activation.ownedChildren.size > 0)
            return 'wait';"""

ACT_WATCH_OLD = """                return;
            }
        })();
    }
    /** Classify one Inbox and owned-child observation without reading Agent execution state. */
    settlementState(activation, observation) {"""
ACT_WATCH_NEW = """                return;
            }
        })().catch((error) => {
            // MESHFIX:settlement-crash — an unhandled rejection here terminates the
            // whole child process AFTER its work is done, which is why a finished
            // child's report vanished with no message and exit -1.
            try {
                this.ctx.logger.warn(`subagent "${activation.childId}" settlement watcher failed: ${String(error?.stack ?? error)}`);
            }
            catch {
                // a logger that itself throws must not resurrect the crash
            }
        });
    }
    /** Classify one Inbox and owned-child observation without reading Agent execution state. */
    settlementState(activation, observation) {"""

EDIT_SETS = (
    ("dsh-agent-loop/lib/index.js", ((LOOP_OLD, LOOP_NEW),)),
    (
        "dsh-subagent/lib/index.js",
        ((SUB_INBOX_OLD, SUB_INBOX_NEW), (WATCH_OLD, WATCH_NEW)),
    ),
    (
        "dsh-subagent/lib/types/continuation-activation.js",
        ((ACT_OLD, ACT_NEW), (ACT_WATCH_OLD, ACT_WATCH_NEW)),
    ),
)


def sha8(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def candidate_roots() -> list[Path]:
    """Every place this runtime could be installed, in preference order.

    The list is deliberately wider than the npx cache. Measured 2026-09-30: the
    mesh worker node `zabz-tech-linux` runs children from
    `/home/zabz/dsh-engine/node_modules/@deepseek-ai`, which no npx-only search
    would ever find — so that machine kept the crash while the fix "shipped".
    A patch that only covers the machine it was written on is not a fix.
    """
    roots: list[Path] = []
    env = os.environ.get("MESHFIX_DSH_ROOT")
    if env:
        roots.append(Path(env))
    home = Path.home()
    # the npx cache (the live install on the Windows machines)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        npx = Path(local) / "npm-cache" / "_npx"
        if npx.is_dir():
            roots.extend(sorted(p / "node_modules" / "@deepseek-ai" for p in npx.iterdir() if (p / "node_modules" / "@deepseek-ai").is_dir()))
    # a global install
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "npm" / "node_modules" / "@deepseek-ai")
    # a dedicated engine directory or a source checkout (the mesh worker layout)
    for rel in (
        "dsh-engine/node_modules/@deepseek-ai",
        "code/dsh-engine/node_modules/@deepseek-ai",
        ".dsh/node_modules/@deepseek-ai",
        "code/deepseek-harness/node_modules/@deepseek-ai",
        "deepseek-harness/node_modules/@deepseek-ai",
        "node_modules/@deepseek-ai",
    ):
        roots.append(home / rel)
    roots.extend(
        [
            Path("/usr/lib/node_modules/@deepseek-ai"),
            Path("/usr/local/lib/node_modules/@deepseek-ai"),
            Path("/opt/dsh-engine/node_modules/@deepseek-ai"),
        ]
    )
    # dedupe, keep order
    seen = set()
    out = []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        if r.is_dir():
            out.append(r)
    return out


def apply(path: Path, edits, check: bool) -> str:
    """Apply one file's edits. Returns a status word for the report."""
    text = path.read_text(encoding="utf-8")
    if SENTINEL in text and all(new in text for _, new in edits):
        return "already-patched"
    if check:
        return "MISSING-PATCH"
    applied = 0
    for old, new in edits:
        if new in text:
            applied += 1
            continue
        if old not in text:
            raise SystemExit(
                f"FAIL {path}: the anchor this patch targets is not present.\n"
                f"  The runtime changed underneath the patch — do NOT hand-edit it.\n"
                f"  Re-derive the patch against this version instead.\n"
                f"  missing anchor begins: {old.splitlines()[0][:90]!r}"
            )
        if text.count(old) != 1:
            raise SystemExit(f"FAIL {path}: the anchor appears {text.count(old)} times, expected exactly 1")
        text = text.replace(old, new, 1)
        applied += 1
    if applied == 0:
        return "no-anchor-applicable"
    backup = path.with_suffix(path.suffix + ".meshfix-bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8")
    return f"patched({applied})"


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch the DSH runtime so a child cannot die at settlement.")
    ap.add_argument("--check", action="store_true", help="verify the patch is present; exit 1 if not")
    ap.add_argument("--root", help="the @deepseek-ai runtime root to patch (default: every one found)")
    args = ap.parse_args()

    roots = [Path(args.root)] if args.root else candidate_roots()
    if not roots:
        print("FAIL: no @deepseek-ai runtime root found. Set MESHFIX_DSH_ROOT or pass --root.")
        return 1

    verdict = 0
    for root in roots:
        print(f"=== runtime root: {root}")
        for rel, edits in EDIT_SETS:
            path = root / rel
            if not path.is_file():
                print(f"  {rel:52s} absent — nothing to patch")
                continue
            try:
                status = apply(path, edits, args.check)
            except SystemExit as exc:
                print(f"  {rel:52s} {exc}")
                verdict = 1
                continue
            marker = "ok " if not status.startswith(("MISSING", "no-")) else "!! "
            print(f"  {marker}{rel:52s} {status}  sha8={sha8(path)}")
            if status == "MISSING-PATCH" or status == "no-anchor-applicable":
                verdict = 1

    if args.check:
        print("PATCHED and verified" if verdict == 0 else "NOT PATCHED — a settlement crash can still lose a child's report")
    return verdict


if __name__ == "__main__":
    sys.exit(main())
