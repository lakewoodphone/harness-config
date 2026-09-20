#!/usr/bin/env python3
"""Can the mesh actually place work, and if not, does anyone get told?

WHY THIS EXISTS (measured 2026-09-20)

On 2026-09-20 the owner called the mesh a threat to the workflows, correctly: four
children were dispatched, the dispatcher reported them running, and **nothing ran for
30 minutes**. The cause was one node, `zabz-tech`, whose capacity gate was dead:

    https://zabz-tech.tail93e6e6.ts.net/mesh/capacity  ->  HTTP 502
    tailscale serve 3086 -> nothing listening

Three separate things were true at once, and each made the others invisible:

1. **The broker appends, it does not exclude.** `zabz-tech` was marked `unreachable`
   while four healthy nodes sat idle. Nothing rerouted the work.
2. **Nothing alerted.** `~/.personal-secretary/mesh-health.json` — the existing cron
   monitor — reported `desktop: {reachable: true}` the whole time, because **ssh**
   answered. The machine was up; it was the *gate* that was dead, and the gate is the
   only thing the broker reads. Liveness by ssh is not liveness for placement.
3. **Nothing recorded the negative result.** The dispatcher's own report said the child
   "did not begin its report with MESH-HOST" — a provenance guard firing on a child
   that never arrived, which reads as *unproven* rather than *never ran*.

So this script measures the thing that matters — **how many nodes can take work** — and
says so out loud in three places: a state file, the owner's notification queue, and its
own exit code. It is deliberately read-only against the broker and writes nothing
except its own state and, when nodes are missing, one owner notification.

USAGE
    python3 mesh-placement-monitor.py            # report and alert if nodes are missing
    python3 mesh-placement-monitor.py --quiet    # state file only (cron default)
    python3 mesh-placement-monitor.py --json

Exit 0 when every roster node can take work, 1 when any cannot. An empty roster is a
failure, not a pass: a monitor that reports health because it read nothing is the exact
bug this file was written to kill.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BROKER = os.environ.get("MESH_BROKER_URL", "http://127.0.0.1:3091")
NOTIFY_URL = os.environ.get("MESH_NOTIFY_URL", "http://127.0.0.1:8002/tools/notify-owner")
STATE = Path(os.environ.get("MESH_MONITOR_STATE",
                            str(Path.home() / ".personal-secretary" / "mesh-placement.json")))
# One alert per node per cooldown, so a node that stays down does not become a flood.
COOLDOWN_SEC = int(os.environ.get("MESH_ALERT_COOLDOWN_SEC", "7200"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_nodes(fresh: bool = False, timeout: int = 25) -> dict:
    """The broker's own view.

    `fresh=1` forces a synchronous re-read of every gate against a hard wall-clock
    deadline, which under load produces spurious timeouts — measured 2026-09-20, a node
    that answered in 25 ms on the wire was reported as "timed out after 4000 ms" on a
    forced refresh. The cached document (<=15 s) is plenty for a monitor that runs every
    few minutes, so use it by default and only force a fresh read to CONFIRM a failure.
    """
    url = f"{BROKER}/nodes?fresh=1" if fresh else f"{BROKER}/nodes"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def classify(doc: dict) -> dict:
    """Which nodes can take work, and which cannot. Never trusts an empty list."""
    nodes = doc.get("nodes") or []
    good, bad = [], []
    for n in nodes:
        name = n.get("node") or "?"
        if n.get("unreachable") or n.get("state") == "unreachable":
            bad.append({"node": name, "reason": n.get("reason") or "unreachable",
                        "lastReadingAgeSec": n.get("lastReadingAgeSec"),
                        "location": n.get("location")})
        elif n.get("state") == "ok":
            good.append({"node": name, "location": n.get("location")})
        else:
            bad.append({"node": name, "reason": n.get("state") or "unknown state",
                        "lastReadingAgeSec": n.get("lastReadingAgeSec"),
                        "location": n.get("location")})
    return {"total": len(nodes), "usable": len(good), "good": good, "bad": bad,
            "empty_roster": len(nodes) == 0}


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"alerts": {}}


def save_state(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        tmp.replace(STATE)
    except Exception as exc:
        print(f"  (could not write state: {exc})", file=sys.stderr)


def notify(message: str, timeout: int = 45) -> dict:
    """Reach the owner through the APP, never by SMS.

    The app holds an owner SMS kill switch (created 2026-07-14 after the CEO sent 28+
    "URGENT" texts), and notifying is not the same as alarming: this posts to the
    owner's notification queue, where he sees it on the surface he already opens.
    """
    data = urllib.parse.urlencode({"message": message}).encode()
    req = urllib.request.Request(NOTIFY_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"ok": True, "raw": body[:200]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--quiet", action="store_true", help="write state, print nothing")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.add_argument("--no-notify", action="store_true", help="never notify the owner")
    a = p.parse_args()

    try:
        doc = fetch_nodes()
    except Exception as exc:
        # The broker itself is unreachable: that is a placement outage in its own right.
        report = {"as_of": now(), "ok": False, "error": f"broker unreachable: {exc}",
                  "total": 0, "usable": 0, "bad": [], "good": [], "empty_roster": True}
        save_state({**report, "alerts": load_state().get("alerts", {})})
        if not a.no_notify:
            state = load_state()
            key = "broker"
            last = state.get("alerts", {}).get(key, 0)
            if _due(last):
                res = notify(f"Mesh placement broker is not answering at {BROKER} "
                             f"({exc}). No agent work can be placed until it is back.")
                state.setdefault("alerts", {})[key] = _epoch()
                save_state(state)
                print(f"  notified the owner: {res}")
        if not a.quiet:
            print(json.dumps(report, indent=1) if a.json else
                  f"BROKER UNREACHABLE: {exc}")
        return 1

    c = classify(doc)

    # Confirm a failure before crying wolf: a monitor that alerts on one soft reading
    # is a monitor people stop reading. A second, forced read costs one call and turns
    # a flake into silence and a real outage into an alert.
    confirmed_from = "cache"
    if c["bad"]:
        try:
            doc2 = fetch_nodes(fresh=True)
            c2 = classify(doc2)
            # Keep whichever view is WORSE for the nodes we are unsure about: a
            # confirmed-good node must not be reported missing, and a node still
            # missing on a forced read is genuinely gone.
            still_bad = {b["node"] for b in c2["bad"]}
            c["bad"] = [b for b in c["bad"] if b["node"] in still_bad]
            c["usable"] = c2["usable"]
            c["total"] = c2["total"]
            c["good"] = c2["good"]
            confirmed_from = "cache + confirmed with a forced read"
            doc["reads"] = doc2.get("reads", doc.get("reads"))
        except Exception as exc:
            # The confirmation failed. Say so rather than pretending it was clean.
            confirmed_from = f"cache only (confirmation failed: {exc})"

    ok = (not c["empty_roster"]) and c["usable"] == c["total"] and c["usable"] > 0
    report = {"as_of": now(), "ok": ok, "broker_reads": doc.get("reads"),
              "reading": confirmed_from, **c}
    state = load_state()
    state.update({k: v for k, v in report.items() if k != "alerts"})
    alerts = state.setdefault("alerts", {})

    # Alert per missing node, with a cooldown. A recovered node clears its own entry so
    # the next outage is reported promptly rather than swallowed by the cooldown.
    if ok:
        alerts.clear()
    if not a.no_notify:
        for b in c["bad"]:
            key = b["node"]
            if not _due(alerts.get(key, 0)):
                continue
            res = notify(
                f"Mesh node '{b['node']}' cannot take agent work: {b['reason']}"
                + (f" (last capacity reading {b['lastReadingAgeSec']}s old)"
                   if b.get("lastReadingAgeSec") else "")
                + f". Other nodes are still being used, so work is not lost, but this "
                  f"node is off the mesh. Check its gate: on that machine, "
                  f"`phone-gate-ensure.ps1 -ListenPort 3086 -EnginePort 3099 -Publish`.")
            alerts[key] = _epoch()
            print(f"  notified the owner about '{key}': {res}")
    if c["empty_roster"] and not a.no_notify:
        if _due(alerts.get("roster", 0)):
            notify("Mesh broker reported an EMPTY node roster. That is not health - "
                   "it means the broker read nothing. No work can be placed safely.")
            alerts["roster"] = _epoch()

    save_state(state)

    if not a.quiet:
        if a.json:
            print(json.dumps(report, indent=1))
        else:
            print(f"mesh placement  {report['as_of']}")
            print(f"  usable {c['usable']} of {c['total']}"
                  + ("  <-- EMPTY ROSTER, not health" if c["empty_roster"] else ""))
            for g in c["good"]:
                print(f"    ok      {g['node']:<20} {g.get('location') or ''}")
            for b in c["bad"]:
                print(f"    MISSING {b['node']:<20} {b['reason']}"
                      + (f"  (reading {b['lastReadingAgeSec']}s old)"
                         if b.get("lastReadingAgeSec") else ""))
            print(f"  verdict {'OK - every node takes work' if ok else 'DEGRADED'}")
    return 0 if ok else 1


def _epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _due(last: int) -> bool:
    return (_epoch() - int(last or 0)) >= COOLDOWN_SEC


if __name__ == "__main__":
    sys.exit(main())
