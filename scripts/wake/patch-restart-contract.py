#!/usr/bin/env python3
"""patch-restart-contract.py - let a headless shift restart a NAMED service.

WHY (owner-queue row 547, decided 2026-10-18; ledger decision D6593)
  Autonomy is the default; protection must earn its place by naming a specific
  vital asset.  The shift contract used to say, flatly, "do not restart
  production services".  That is not a protection with a named asset behind it:
  host-posture.tsv already names the frozen and read-only hosts and
  guard-service-state.sh already refuses them.  The flat rule only stopped work.

  The contract now permits a restart when ALL FIVE hold:
    1. the item names the HOST;
    2. the item names the SERVICE (unit or container);
    3. the item names the WINDOW (an explicit time or condition);
    4. the host is WRITABLE in settings/machines/host-posture.tsv; and
    5. the restart is RECORDED on the item's attempt trail (work.py attempt,
       did/proof/result/exit-code).
  It may NOT restart anything unnamed, anything on a frozen or read-only host,
  anything outside the window, or stop/disable/mask/enable anything.

  guard-service-state.sh remains the ONE gate.  Its logic is not duplicated in
  the contract, in this script, or anywhere else.

WHERE THE CONTRACT LIVES
  * scripts/wake/sources/project-keepalive.py        (repo, source)
  * scripts/deployed/bin/sources/project-keepalive.py (repo, deployed capture)
  * ~/bin/sources/project-keepalive.py                (LIVE on the authority)
  * ~/bin/shift-packet.py                             (LIVE frozen preamble;
                                                       not tracked in git - the
                                                       pre-existing gap noted in
                                                       docs/mesh/124)

  Four files, two texts: the full STEP 3c in project-keepalive.py, and a compact
  SERVICE RESTARTS block in the packet's frozen preamble.  Both carry the marker
  "RESTART-CONTRACT-V1" so --apply is idempotent.

USAGE
  python3 patch-restart-contract.py --check    # report, change nothing
  python3 patch-restart-contract.py --apply    # back up, write, verify
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
MARKER = "RESTART-CONTRACT-V1"

FULL_BLOCK = '''        "STEP 3c - A RESTART IS ALLOWED, UNDER THIS CONTRACT, AND ONLY UNDER IT. (RESTART-CONTRACT-V1)",
        "  A headless shift MAY restart a service when ALL FIVE of these hold:",
        "    (1) the ledger item NAMES THE HOST it will touch;",
        "    (2) the ledger item NAMES THE SERVICE (a systemd unit or a container);",
        "    (3) the ledger item NAMES THE WINDOW - an explicit time or an explicit",
        "        condition, e.g. 'the 02:00-04:00Z window' or 'after the merge is",
        "        proven and before the next business-hours traffic';",
        "    (4) the host's posture in",
        "        ~/code/harness-config/settings/machines/host-posture.tsv is WRITABLE; and",
        "    (5) the restart is RECORDED on this item's attempt trail before you finish.",
        "  If the item is missing the host, the service or the window, STOP. Do not",
        "  guess, do not borrow a window from another item, and do not restart: record",
        "  the gap with `work.py attempt` and take the next item.",
        "  THE GATE IS THE SCRIPT, NOT YOUR MEMORY. Ask it and obey its exit code:",
        "    bash ~/code/harness-config/scripts/mesh/guard-service-state.sh --host <host> --op restart",
        "      0  writable, ALLOW      -> proceed",
        "      2  frozen, REFUSED      -> STOP. Never touch the host.",
        "      3  read-only, REFUSED   -> STOP. `--owner-confirmed` is the OWNER'S yes;",
        "                                 a shift has no owner and never passes that flag.",
        "      4  host not designated   -> STOP. An unrecognised host is not permission.",
        "  Do NOT re-implement the posture table or its frozen/read-only/writable logic;",
        "  the script is the single gate, and an allow from anywhere else is not an allow.",
        "  THEN do the restart and record it, in this order:",
        "    systemctl restart <unit>        # or the container's own restart command",
        "    python3 ~/bin/work.py attempt <item-id> --by restart-<project> \\\\",
        "      --did 'RESTARTED <unit> on <host> at <UTC>; window: <the item window>; why: <why>' \\\\",
        "      --proof 'bash ~/code/harness-config/scripts/mesh/guard-service-state.sh --host <host> --op restart && systemctl restart <unit>; echo rc=$?' \\\\",
        "      --result '<the guard ALLOW line>; rc=0; <systemctl is-active <unit>>' \\\\",
        "      --state running --exit-code <the restart command's exit status>",
        "  Use a DISTINCT --by handle (restart-<project>), NEVER the claim handle: a later",
        "  `close` updates the open attempt of the SAME worker, so a restart recorded under",
        "  the shift's own handle would be overwritten by the close.",
        "  The attempt IS the record: what, where, when, why and the exit status. A restart",
        "  with no attempt line did not happen as far as the ledger is concerned.",
        "  YOU MAY NOT restart anything the item did not name, anything on a frozen or",
        "  read-only host, anything outside the named window, or any unit you started",
        "  yourself. This contract grants RESTART only - not stop, disable, mask or enable.",
'''

PACKET_BLOCK = '''SERVICE RESTARTS (allowed only under this contract)  RESTART-CONTRACT-V1
  A restart is permitted only when the item names the HOST, the SERVICE and the
  WINDOW, the host is WRITABLE in settings/machines/host-posture.tsv, and the
  restart is RECORDED with `work.py attempt` (did / proof / result / exit code).
  The gate is the script - obey its exit code, never re-implement it:
    bash ~/code/harness-config/scripts/mesh/guard-service-state.sh --host <host> --op restart
    0 allow; 2 frozen STOP; 3 read-only STOP (never pass --owner-confirmed);
    4 host not designated STOP.
  Never restart anything unnamed, on a frozen/read-only host, or outside the
  window. This grants RESTART only - not stop, disable, mask or enable.
'''

FULL_OLD = '''        "  * Do NOT touch cron, and do not restart production services.",
'''
FULL_NEW = '''        "  * Do NOT touch cron. A production restart is allowed ONLY under STEP 3c,",
        "    through guard-service-state.sh, recorded with work.py attempt - never otherwise.",
'''

PACKET_OLD = '''  Never send anything outbound. Do not raise a wake flag. Do not touch cron.
  Do not restart production services. Never commit to main, never force-push,
'''
PACKET_NEW = '''  Never send anything outbound. Do not raise a wake flag. Do not touch cron.
  A restart is allowed ONLY under SERVICE RESTARTS above, on the record. Never
  commit to main, never force-push,
'''

ANCHOR_STEP4 = '        "STEP 4 - WRITE BACK BEFORE YOU FINISH. THIS IS THE STEP THAT MAKES THE SYSTEM WORK;",'


def targets(repo: Path):
    return [
        ("full", repo / "scripts/wake/sources/project-keepalive.py"),
        ("full", repo / "scripts/deployed/bin/sources/project-keepalive.py"),
        ("full", HOME / "bin/sources/project-keepalive.py"),
        ("packet", HOME / "bin/shift-packet.py"),
    ]


def plan(kind: str, path: Path):
    if not path.is_file():
        return ("MISSING", path, None, None)
    src = path.read_text(encoding="utf-8")
    if MARKER in src:
        return ("ALREADY", path, src, None)
    if kind == "full":
        if src.count(FULL_OLD) != 1:
            return ("ANCHOR-MISS", path, src, None)
        if src.count(ANCHOR_STEP4) != 1:
            return ("STEP4-MISS", path, src, None)
        out = src.replace(ANCHOR_STEP4, FULL_BLOCK + ANCHOR_STEP4, 1)
        out = out.replace(FULL_OLD, FULL_NEW, 1)
    else:
        if src.count(PACKET_OLD) != 1:
            return ("ANCHOR-MISS", path, src, None)
        out = src.replace(PACKET_OLD, PACKET_NEW, 1)
        # put the block after THE OWNER CHANNEL, before HARD LIMITS
        anchor = "  A finished job is recorded in the ledger, not announced to him.\n\nHARD LIMITS\n"
        if out.count(anchor) != 1:
            return ("HARD-LIMITS-MISS", path, src, None)
        out = out.replace(anchor, PACKET_BLOCK + "\n" + anchor, 1)
    return ("PATCH", path, src, out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(HOME / "code/harness-config"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    repo = Path(a.repo)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    changed = 0
    bad = 0
    for kind, path in targets(repo):
        state, p, src, out = plan(kind, path)
        print("%-10s %-10s %s" % (kind, state, p))
        if state in ("MISSING", "ANCHOR-MISS", "STEP4-MISS", "HARD-LIMITS-MISS"):
            bad += 1
            continue
        if state != "PATCH":
            continue
        changed += 1
        if not a.apply:
            continue
        bak = p.with_name(p.name + ".bak-restart-contract-" + stamp)
        shutil.copy2(p, bak)
        tmp = p.with_name(p.name + ".tmp-restart-contract")
        tmp.write_text(out, encoding="utf-8")
        shutil.copymode(p, tmp)          # never turn an executable into 0644
        os.replace(tmp, p)
        print("           backed up -> %s" % bak.name)
    print("---")
    print("files=%d patch-needed=%d problems=%d marker=%s"
          % (len(targets(repo)), changed, bad, MARKER))
    if bad:
        return 2
    if a.apply:
        # re-plan: every full/packet file must now carry the marker
        left = [str(p) for k, p in targets(repo) if p.is_file() and MARKER not in p.read_text(encoding="utf-8")]
        print("unverified-after-apply=%d %s" % (len(left), left))
        return 0 if not left else 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
