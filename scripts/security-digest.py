#!/usr/bin/env python3
"""security-digest — the weekly page, rendered but NOT sent.

The Auditor's job is one page a week: what happened, what the system learned, what is blind, what wants a
decision. This renders that page from the record and the live building. It sends nothing — sending is outbound
and needs the owner's word every time.

Sections:
  1. the four KPIs, each beside the number that makes it honest
  2. what was judged, and where the rules and the model disagreed
  3. blind sensors: security entities that are unavailable, unknown, or flapping
  4. proposals and their gate verdicts
  5. the one line the owner should read if he reads nothing else

Usage: security-digest.py [--days 7] [--out /path.md]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

SECURITY_PREFIXES = ("binary_sensor.phoenix_", "binary_sensor.zone_", "binary_sensor.cam_",
                     "binary_sensor.video_doorbell_", "lock.", "input_boolean.phoenix_",
                     "binary_sensor.control_room_hub_")
CRITICAL = ("binary_sensor.phoenix_control_room_interior_door_contact",
            "binary_sensor.phoenix_control_room_exterior_door_contact",
            "binary_sensor.zone_control_room_occupied")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def ha_states() -> dict | None:
    """Live HA state, read the same way the listener does. None if unreachable — and that is reported."""
    try:
        import requests
        url = token = ""
        for line in open("/opt/company/.env", errors="ignore"):
            if line.startswith("HA_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
            if line.startswith("HA_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
        if not url or not token:
            return None
        r = requests.get(url.rstrip("/") + "/api/states",
                         headers={"Authorization": f"Bearer {token}"}, timeout=20)
        return {e["entity_id"]: e for e in r.json()} if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/root/authority.db")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    win = f"-{args.days} days"
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=10.0)
    q = lambda sql, a=(): conn.execute(sql, a).fetchone()  # noqa: E731

    events = q("SELECT COUNT(*) FROM security_event WHERE created_at > datetime('now',?)", (win,))[0]
    real = q("SELECT COUNT(*) FROM security_event WHERE created_at > datetime('now',?) "
             "AND entity_id NOT LIKE 'security.listener'", (win,))[0]
    episodes = q("SELECT COUNT(DISTINCT episode_id) FROM security_decision "
                 "WHERE episode_id IS NOT NULL AND created_at > datetime('now',?)", (win,))[0]
    labels = q("SELECT COUNT(*) FROM security_label WHERE created_at > datetime('now',?)", (win,))[0]
    actions = q("SELECT COUNT(*) FROM security_action WHERE attempted_at > datetime('now',?)", (win,))[0]
    pages = q("SELECT COUNT(*) FROM security_action WHERE attempted_at > datetime('now',?) "
              "AND action='PAGE'", (win,))[0]
    agent_only = q("SELECT COUNT(*) FROM security_decision d WHERE d.decided_by='fallback:shadow' "
                   "AND d.episode_id IS NOT NULL AND d.created_at > datetime('now',?) "
                   "AND NOT EXISTS (SELECT 1 FROM security_decision a WHERE a.episode_id=d.episode_id "
                   "AND a.decided_by LIKE 'agent%')", (win,))[0]
    reconnects = q("SELECT COUNT(*) FROM security_event WHERE recorder_gap=1 AND new_state LIKE 'reconnect%' "
                   "AND created_at > datetime('now',?)", (win,))[0]
    proposals = list(conn.execute("SELECT proposal_id, verdict, false_added, missed_real, notes FROM replay_run "
                                  "WHERE created_at > datetime('now',?) ORDER BY created_at DESC LIMIT 8", (win,)))
    dis = list(conn.execute("""
        SELECT episode_id,
               MAX(CASE WHEN decided_by='fallback:shadow' THEN decision END) r,
               MAX(CASE WHEN decided_by LIKE 'agent%' THEN decision END) a
        FROM security_decision WHERE episode_id IS NOT NULL AND created_at > datetime('now',?)
        GROUP BY episode_id HAVING r IS NOT NULL AND a IS NOT NULL AND r<>a LIMIT 5""", (win,)))

    states = ha_states()
    lines = [f"# Security — week to {utcnow()}", ""]

    lines.append("## The four numbers")
    lines.append("")
    lines.append(f"- **pages sent**: {pages}  (false pages are counted against episodes, and there are "
                 f"{episodes} episode(s) to judge them against)")
    lines.append(f"- **episodes judged**: {episodes}   **labelled**: {labels}   "
                 f"{'— none of the opinions can be graded yet' if not labels else ''}")
    lines.append(f"- **record**: {events} event row(s), {real} from the building "
                 f"({events - real} are listener markers), {actions} action(s)")
    lines.append(f"- **stream**: {reconnects} unplanned reconnect(s) in {args.days} day(s)")
    if agent_only:
        lines.append(f"- **WARNING**: {agent_only} episode(s) have no agent verdict — the agent was down or "
                     f"over budget, and those episodes were judged by rules alone")
    lines.append("")

    lines.append("## Where the rules and the model disagreed")
    lines.append("")
    lines += [f"- `{e}` → rules said **{r}**, model said **{a}**" for e, r, a in dis] or \
             ["- none (or no episode has both opinions yet)"]
    lines.append("")

    lines.append("## Blind sensors")
    lines.append("")
    if states is None:
        lines.append("- **the building could not be read at all** — HA unreachable from here. That is a "
                     "finding, not an empty list.")
    else:
        blind = [e for e, d in states.items()
                 if any(e.startswith(p) for p in SECURITY_PREFIXES) and d["state"] in ("unavailable", "unknown")]
        crit = [e for e in blind if e in CRITICAL]
        lines.append(f"- security entities unavailable/unknown: **{len(blind)}**")
        if crit:
            lines.append(f"- **CRITICAL among them**: {', '.join(f'`{c}`' for c in crit)} — the alarm's own "
                         f"perimeter is dark")
        for e in blind[:8]:
            lines.append(f"  - `{e}` = {states[e]['state']}")
        if len(blind) > 8:
            lines.append(f"  - … and {len(blind) - 8} more")
    lines.append("")

    lines.append("## Proposals through the gate")
    lines.append("")
    if not proposals:
        lines.append("- none this week")
    for pid, verdict, fa, mr, notes in proposals:
        if (pid or "").endswith("[baseline]"):
            continue  # baseline rows are the yardstick, not a proposal
        try:
            promoted = json.loads(notes).get("promoted")
        except (ValueError, TypeError):
            promoted = None
        tag = "PROMOTED" if promoted else ("REFUSED" if promoted is False else "run")
        lines.append(f"- `{(pid or '')[:40]}` — **{tag}** ({verdict}); false+{fa} missed-{mr}")
    lines.append("")

    lines.append("## If you read one line")
    lines.append("")
    if pages == 0 and episodes == 0:
        line = ("Nothing has happened at the building this week and nothing was paged. That is the system "
                "being idle, not successful — an empty record must never be read as a quiet week.")
    elif labels == 0:
        line = (f"{episodes} episode(s) judged and {pages} page(s) sent, but **no episode is labelled**: the "
                f"system still cannot tell you whether any of them was right.")
    else:
        line = (f"{episodes} episode(s), {labels} labelled, {pages} page(s). The labelled ones are the only "
                f"evidence that exists about whether this works.")
    lines.append(line)
    out = "\n".join(lines)
    print(out)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
        print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
