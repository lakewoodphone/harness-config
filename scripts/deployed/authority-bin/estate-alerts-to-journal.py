#!/usr/bin/env python3
"""estate-alerts-to-journal.py — THE READER THE ESTATE MONITOR NEVER HAD.

THE DEFECT, MEASURED 2026-10-13 on secratary-cloud.

`estate-monitor.py` is a good instrument and it works: every two minutes it measures 31 things,
stamps each with its own age, and computes a verdict. At 14:04:01Z that verdict was
**`critical`, 4 crit / 1 warn / 1 nodata**, including `oom_kills_24h=11` and
`swap_used_pct=83.5%` at a **streak of 49** consecutive runs.

Nobody was told, and that is **by design, and the design is right**:

    ITS OWN RULE 3: "IT CANNOT TEXT THE OWNER. Nothing here opens a socket to a person. The only
    escalation is syslog(daemon.err) + alerts.jsonl + an ESCALATED flag file ... Everything else
    is log-only."

The reason that rule exists is sound -- a disk reading is not the owner's business, and flooding him
destroys the signal of the alerts that are. **So the fix is not a louder producer. It is a consumer.**

And the filter is the other half of the defect: only `public_health_status` has `mode="alert"`, so
`alerts.jsonl` holds **three rows, all one metric**, while the eleven OOM kills never entered the
stream at all. This reads `state.json` instead, which carries the state of **every** metric.

WHAT IT DOES. For each metric that is critical (or warning, with `--include-warn`) and has held that
state for `--min-streak` consecutive runs, it files **one journal `pain` entry** -- the estate's
existing channel for work a session will pick up. It files once per episode: when the metric clears
and goes critical again, that is a new episode and a new entry, because a recurrence is information.

WHAT IT DELIBERATELY DOES NOT DO
  * It does not text, email or call anyone. It writes a journal entry and stops. If the owner ever
    needs to know, that is the owner queue's job, one question at a time -- not this.
  * It does not modify the monitor, its thresholds or its escalation list. The monitor's rule 3 is
    kept exactly.
  * It does not file on a single bad run: `--min-streak` (default 3) means a blip is not an episode.
  * It is DRY RUN BY DEFAULT. `--apply` writes.

USAGE
  estate-alerts-to-journal.py                  # report what would be filed
  estate-alerts-to-journal.py --apply
  estate-alerts-to-journal.py --json
  estate-alerts-to-journal.py --include-warn --min-streak 6
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("ESTATE_MONITOR_STATE", "/root/.estate-monitor/state.json"))
LEDGER = Path(os.environ.get("ESTATE_ALERT_LEDGER",
                             "/root/.estate-monitor/journal-filed.json"))
JOURNAL_CANDIDATES = (
    "/root/code/harness-config/journal/tools/journal.py",
    os.path.expanduser("~/code/harness-config/journal/tools/journal.py"),
)

# Metrics whose CRIT is a fact about the instrument rather than about the estate. Filing a pain for
# the monitor's own blind spot on every run would be exactly the noise this file exists to avoid.
IGNORE = {
    "authority_db_growth_mb_h",   # NODATA for the first 10 minutes after a restart, by design
}


def journal_path() -> str | None:
    override = os.environ.get("ESTATE_ALERT_JOURNAL")
    if override:
        return override if os.path.exists(override) else None
    for c in JOURNAL_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def load_ledger() -> dict:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ledger(d: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, LEDGER)


def signature(mid: str, m: dict, th: dict) -> str:
    """What makes this episode distinct.

    Deliberately coarse on the VALUE -- the fact that swap is critical is the finding; 83.4 vs 83.6
    is not a new one. It is exact on the STATE, so warn->crit is a new episode and crit->ok clears.
    """
    return "%s|%s|streak>=%s" % (mid, m.get("st"), th.get("for_runs", 1))


def body(mid: str, m: dict, th: dict, state: dict, episode: int) -> str:
    return "\n".join([
        f"Filed by `estate-alerts-to-journal.py` from `/root/.estate-monitor/state.json`.",
        "",
        f"**{mid} is `{m.get('st')}`** at **{m.get('v')} {m.get('u', '')}**.",
        "",
        f"- held for **{m.get('streak', '?')} consecutive runs** (warn>={th.get('warn')} "
        f"crit>={th.get('crit')} {th.get('unit', '')}, mode={th.get('mode', 'log')})",
        f"- measured from `{m.get('src')}`, age {m.get('age_s')}s, last ok {m.get('last_ok')}",
        f"- the monitor's own note: {m.get('note', '(none)')}",
        f"- monitor verdict at that run: **{state.get('verdict')}** "
        f"{state.get('counts')} on {state.get('host')} at {state.get('generated_at')}",
        f"- episode {episode} for this metric",
        "",
        "WHY THIS IS A JOURNAL ENTRY AND NOT A MESSAGE. `estate-monitor.py` rule 3 says it cannot",
        "text the owner, and that rule is right -- a disk reading is not his to triage, and flooding",
        "him destroys the signal of the alerts that are. But `mode=\"log\"` means this condition never",
        "reached `alerts.jsonl` either, so it reached nobody. This is the reader that was missing.",
        "",
        "WHAT TO DO: read the metric on the box, decide whether it is a real condition or a threshold",
        "that needs moving, act, and `resolve` this entry with what you measured. If it recurs after",
        "clearing, a new entry is filed -- a recurrence is information.",
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the entries (default: report)")
    ap.add_argument("--include-warn", action="store_true", help="also file WARN metrics")
    ap.add_argument("--min-streak", type=int, default=3,
                    help="consecutive runs in state before it is an episode (default 3)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if not STATE.exists():
        print(f"no state file at {STATE} -- is the monitor running?")
        return 0
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"could not parse {STATE}: {exc}")
        return 1

    metrics = state.get("metrics") or {}
    thresholds = state.get("thresholds") or {}
    wanted = {"crit"} | ({"warn"} if a.include_warn else set())
    ledger = load_ledger()

    to_file, cleared = [], []
    seen_now = set()
    for mid, m in metrics.items():
        if mid in IGNORE or not isinstance(m, dict):
            continue
        st = m.get("st")
        th = thresholds.get(mid) or {}
        if isinstance(th, list):  # thresholds serialise as a list in state.json
            th = {"warn": th[0], "crit": th[1], "unit": th[2] if len(th) > 2 else "",
                  "mode": th[3] if len(th) > 3 else "log",
                  "for_runs": th[5] if len(th) > 5 else 1}
        if st in wanted and (m.get("streak") or 0) >= a.min_streak:
            sig = signature(mid, m, th)
            seen_now.add(mid)
            prev = ledger.get(mid) or {}
            if prev.get("sig") == sig:
                continue                      # same episode, already filed
            episode = int(prev.get("episode") or 0) + 1
            to_file.append((mid, m, th, sig, episode))
        else:
            # Cleared (or below the streak): end the episode so the next one files.
            if mid in ledger:
                cleared.append(mid)

    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "verdict": state.get("verdict"), "counts": state.get("counts"),
           "would_file": [x[0] for x in to_file], "cleared_episodes": cleared,
           "applied": []}

    if a.json and not a.apply:
        print(json.dumps(out, indent=2))
        return 0

    print(f"monitor verdict : {state.get('verdict')}  {state.get('counts')}")
    print(f"metrics         : {len(metrics)}   threshold-table shape: "
          f"{'ok' if thresholds else 'ABSENT'}")
    for mid in cleared:
        ledger.pop(mid, None)
    if cleared:
        print(f"episodes ended  : {', '.join(sorted(cleared))}")

    if not to_file:
        print("nothing to file — every critical metric is either below the streak or already filed")
        if a.apply and cleared:
            save_ledger(ledger)
        return 0

    print(f"\nwould file {len(to_file)} entr{'y' if len(to_file) == 1 else 'ies'}:")
    for mid, m, th, sig, ep in to_file:
        print(f"  {mid:<28} {m.get('st'):<5} {m.get('v')} {m.get('u',''):<4} "
              f"streak={m.get('streak')}  episode {ep}")

    if not a.apply:
        print("\nDRY RUN — nothing written. Pass --apply to file them.")
        return 0

    j = journal_path()
    if not j:
        print("\ncannot file: no journal.py found (set ESTATE_ALERT_JOURNAL to name one)")
        return 1

    for mid, m, th, sig, ep in to_file:
        want = "critical" if m.get("st") == "crit" else "warning"
        title = ("Estate monitor: %s is %s (%s %s) across %s consecutive runs"
                 % (mid, want, m.get("v"), m.get("u", ""), m.get("streak")))
        cmd = [sys.executable, j, "append", "pain", "--title", title,
               "--body", body(mid, m, th, state, ep), "--quiet", "--no-fetch",
               "--tags", "estate-monitor,auto-filed,not-the-owners",
               "--refs", "metrics/%s" % mid]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
        ok = r.returncode == 0
        print(("  filed  " if ok else "  FAILED ") + mid + "  "
              + (r.stdout or r.stderr or "").strip()[:100])
        out["applied"].append({"metric": mid, "ok": ok})
        if ok:
            ledger[mid] = {"sig": sig, "episode": ep, "at": out["at"], "title": title}
    save_ledger(ledger)
    if a.json:
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
