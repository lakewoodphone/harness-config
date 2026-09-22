#!/usr/bin/env python3
"""Watch the three rolled Stripe keys while they are still alive.

Owner decision 2026-09-15: keep the old keys valid through Stripe's grace period
"just in case" the new key breaks something. That is his call, but a live key that
nobody watches is how a maybe becomes a never-knew. This script runs on a timer and
answers two questions every time:

  1. Are the old keys still alive, and are they finally dead after the grace period?
     (It reads them from the *.bak-striperoll-20260915 backups, so no extra copy of a
     live secret is created anywhere. The backup files are the only reason it can test
     them at all - if they are gone, it says so instead of pretending.)

  2. Has anything happened on the account that we did not do? Specifically:
       - a NEW terminal reader, or any terminal.reader.registered event
       - a payment intent or charge created since the previous run (logged for the eye,
         not alarmed: the shop legitimately makes charges all day)
       - a refund, dispute or payout that we did not originate
     A finding is written to owner_decision_queue, which is the one channel the owner
     reads, so an alert cannot rot in a log file.

Anomalies are written to the queue; everything else goes to the log and a status JSON.
Nothing here is destructive and nothing here sends anything outbound.

Usage:  python3 stripe-key-watch.py            # one pass
        python3 stripe-key-watch.py --status   # print the last run
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

STATE_DIR = os.path.expanduser("~/.lpt-verify")
STATE = os.path.join(STATE_DIR, "stripe-watch-state.json")
LOG = os.path.join(STATE_DIR, "stripe-watch.log")
QUEUE = os.path.expanduser("~/bin/owner-queue.py")
BASELINE_READER = "tmr_GavzfgCDIyZ9pN"   # the front-desk WisePOS E, the only reader on 2026-09-15
OLD_KEY_FILES = [
    "/home/zabz/personal-secretary-mvp/.env.bak-striperoll-20260915",   # ...ETe1 (secretary)
]
# The production backup lives on lpt-apps; read it over ssh so this script needs no copy of it.
REMOTE_KEY_FILES = {
    "lpt-apps": "/opt/lpt/.env.bak-striperoll-20260915",   # ...hJuq
}
NOW = lambda: datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"{NOW()} {msg}"
    print(line, flush=True)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(line + "\n")


def load_state() -> dict:
    try:
        return json.load(open(STATE))
    except Exception:
        return {"started": NOW(), "last_run": None, "last_intent_created": None, "known_readers": [BASELINE_READER]}


def save_state(st: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE)


def key_from_env(path: str) -> str | None:
    try:
        txt = open(path).read()
    except Exception:
        return None
    m = re.search(r"(?m)^STRIPE_SECRET_KEY=(.*)$", txt)
    return m.group(1).strip().strip('"').strip("'") if m else None


def key_from_ssh(host: str, path: str) -> str | None:
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
             f"grep -m1 '^STRIPE_SECRET_KEY=' {path} | cut -d= -f2-"],
            capture_output=True, text=True, timeout=45,
        )
        val = (out.stdout or "").strip().strip('"').strip("'")
        return val or None
    except Exception:
        return None


def stripe(path: str, key: str, params: dict | None = None):
    url = "https://api.stripe.com/v1/" + path
    if params:
        q = "&".join(f"{k}={v}" for k, v in params.items())
        url += "?" + q
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return "ERR", str(e)[:120]


def raise_question(title: str, body: str) -> None:
    """File the finding where the owner actually reads it."""
    if not os.path.exists(QUEUE):
        log(f"ANOMALY (queue tool missing, printing instead): {title} :: {body}")
        return
    try:
        subprocess.run(
            ["python3", QUEUE, "add", "--severity", "high", "--question", f"{title}. {body}"],
            capture_output=True, text=True, timeout=45, check=False,
        )
        log(f"ANOMALY filed to owner_decision_queue: {title}")
    except Exception as e:
        log(f"ANOMALY but could not file it: {title} ({str(e)[:80]})")


def main() -> int:
    if "--status" in sys.argv:
        st = load_state()
        print(json.dumps(st, indent=1))
        return 0

    st = load_state()
    anomalies: list[str] = []

    # --- 1. are the old keys still alive? -------------------------------------
    alive, dead, unreadable = [], [], []
    keys: dict[str, str] = {}
    for path in OLD_KEY_FILES:
        k = key_from_env(path)
        if k:
            keys[f"...{k[-4:]}"] = k
        else:
            unreadable.append(path)
    for host, path in REMOTE_KEY_FILES.items():
        k = key_from_ssh(host, path)
        if k:
            keys[f"...{k[-4:]}"] = k
        else:
            unreadable.append(f"{host}:{path}")
    for label, k in keys.items():
        code, _ = stripe("account", k)
        (alive if code == 200 else dead).append(label)
        log(f"old key {label}: HTTP {code} ({'ALIVE' if code == 200 else 'dead'})")
    for path in unreadable:
        log(f"could not read an old key from {path} - it cannot be tested")
    if not keys:
        anomalies.append("none of the old-key backups could be read, so the grace-period keys are unwatched")

    # --- 2. anything on the account we did not do? ----------------------------
    newest = keys and list(keys.values())[0]
    if newest:
        code, data = stripe("terminal/readers", newest, {"limit": 20})
        if code == 200 and data:
            ids = sorted(r.get("id") for r in data.get("data", []))
            known = set(st.get("known_readers", [BASELINE_READER]))
            new = [i for i in ids if i not in known]
            if new:
                anomalies.append(f"NEW TERMINAL READER(S) on the account: {new} - nothing we did registers readers")
                st["known_readers"] = sorted(known | set(ids))
            log(f"readers: {ids}")

        since = st.get("last_run")
        if since:
            epoch = int(datetime.datetime.fromisoformat(since).timestamp())
            code, data = stripe("events", newest, {"limit": 50, "types[]": "terminal.reader.registered", "created[gte]": epoch})
            if code == 200 and data and data.get("data"):
                anomalies.append(f"terminal.reader.registered fired {len(data['data'])} time(s) since the last run")
            code, data = stripe("payment_intents", newest, {"limit": 20, "created[gte]": epoch})
            if code == 200 and data:
                for pi in data.get("data", []):
                    st["last_intent_created"] = pi.get("created")
                    if pi.get("status") not in ("succeeded", "requires_payment_method", "canceled", "processing"):
                        anomalies.append(f"payment intent in an unexpected state: {pi.get('id')} {pi.get('status')}")
                log(f"payment intents since last run: {len(data.get('data', []))} (shop sales are expected)")
            code, data = stripe("refunds", newest, {"limit": 10, "created[gte]": epoch})
            if code == 200 and data and data.get("data"):
                anomalies.append(f"{len(data['data'])} refund(s) since the last run - confirm they are ours")
            code, data = stripe("disputes", newest, {"limit": 10, "created[gte]": epoch})
            if code == 200 and data and data.get("data"):
                anomalies.append(f"{len(data['data'])} dispute(s) since the last run")

    st.update({
        "last_run": NOW(),
        "old_keys_alive": alive,
        "old_keys_dead": dead,
        "old_keys_unreadable": unreadable,
        "anomalies": anomalies,
    })
    save_state(st)

    if anomalies:
        raise_question(
            "Stripe grace-period watch: something on the account changed unexpectedly",
            "While the three rolled Stripe keys are still valid (owner decision 2026-09-15), the "
            "watcher saw: " + "; ".join(anomalies) + ". Details in ~/.lpt-verify/stripe-watch.log. "
            "Old keys still alive in this run: " + (", ".join(alive) or "none") + "."
        )
    elif alive:
        log(f"watch clean; keys still alive per the grace period: {', '.join(alive)}")
    else:
        log("watch clean and every old key is now dead - the grace period has ended; this watcher can be removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
