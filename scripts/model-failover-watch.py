#!/usr/bin/env python3
"""Model failover watch — runs on secratary via cron (every 5 min).

Two jobs, both touching ONLY settings/base.yaml, one commit per flip:

  1. FAILOVER: fleet default is `deepseek-flash` and the DeepSeek API stops
     answering for N consecutive probes -> switch the committed default to
     `deepseek-v4-pro` (the owner-chosen bridge, 2026-09-14) and add the
     BRIDGE marker line.
  2. RECOVERY: fleet default is the v4-pro BRIDGE and deepseek-flash answers
     for N consecutive probes -> revert to `deepseek-flash` and drop the marker.

Hysteresis (N=2, probes 5 min apart) means no flip on a single blip. If the
checkout is not exactly at origin/master the run skips (autosync fast-forwards
it within 15 min). State survives restarts in ~/.dsh-model-watch/state.json;
every run and every flip is logged to ~/.dsh-model-watch/watch.log.

The marker line is the single source of truth for "this is a bridge, not a
permanent choice": if the owner ever pins v4-pro permanently and removes the
marker, this script leaves it alone.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

REPO = "/home/zabz/harness-config"
BASE = os.path.join(REPO, "settings", "base.yaml")
STATE_DIR = os.path.expanduser("~/.dsh-model-watch")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = os.path.join(STATE_DIR, "watch.log")

N = 2          # consecutive same-state probes before any flip
TIMEOUT = 20   # seconds per probe (a hang counts as unhealthy)

BRIDGE_MARKER = "# BRIDGE("
BRIDGE_LINE = ("# BRIDGE(2026-09-14): v4-pro while DeepSeek flash is down; "
               "model-failover-watch.py reverts when healthy (owner-chosen bridge).")
MODEL_RE = re.compile(r"^  model: (\S+)$")


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def api_key():
    cred = os.path.expanduser("~/.dsh/.credentials.yaml")
    try:
        text = open(cred).read()
    except OSError:
        return None
    m = re.search(r"DEEPSEEK_API_KEY:\s*(\S+)", text)
    return m.group(1) if m else None


def probe_flash(key):
    """True if deepseek-flash answers a completion with a real body."""
    if not key:
        log("no DEEPSEEK_API_KEY found; treating flash as unhealthy")
        return False
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    })
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body.encode(),
        headers={"Authorization": "Bearer %s" % key,
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read().decode()
        return '"choices"' in data
    except Exception:
        return False


def read_base():
    with open(BASE) as f:
        return f.read()


def current_model(text):
    for line in text.splitlines():
        m = MODEL_RE.match(line)
        if m:
            return m.group(1)
    return None


def flip(text, to_pro):
    out = []
    for line in text.splitlines():
        if line.startswith(BRIDGE_MARKER):
            continue
        m = MODEL_RE.match(line)
        if m:
            line = "  model: %s" % ("deepseek-v4-pro" if to_pro else "deepseek-flash")
        out.append(line)
    if to_pro:
        for i, line in enumerate(out):
            if line == "agent-default-model:":
                out.insert(i, BRIDGE_LINE)
                break
    return "\n".join(out) + "\n"


def git(*args):
    return subprocess.run(["git", "-C", REPO] + list(args),
                          capture_output=True, text=True)


def sync_with_origin():
    """Ensure local master is exactly at origin/master (or ahead of it only by
    an already-committed flip). Returns True when it is safe to flip."""
    if git("push", "origin", "master").returncode != 0:
        # Not fatal: could be behind, or transient. The ancestor check below
        # decides. A stranded flip commit from a previous failed push lands here.
        pass
    if git("fetch", "origin").returncode != 0:
        log("git fetch failed; skipping this run")
        return False
    r = git("merge-base", "--is-ancestor", "origin/master", "HEAD")
    if r.returncode != 0:
        log("checkout is behind or diverged from origin/master; skipping")
        return False
    return True


def commit_and_push(what):
    git("add", "settings/base.yaml")
    r = git("commit", "-m",
            "model: %s by model-failover-watch.py (deepseek-flash health change)" % what)
    if r.returncode != 0:
        log("commit failed: %s" % r.stderr.strip())
        return False
    r = git("push", "origin", "master")
    if r.returncode != 0:
        log("push failed: %s" % r.stderr.strip().splitlines()[-1])
        return False
    return True


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    state = {"healthy_count": 0, "unhealthy_count": 0}
    if os.path.exists(STATE_FILE):
        try:
            state.update(json.load(open(STATE_FILE)))
        except Exception:
            pass

    healthy = probe_flash(api_key())
    if healthy:
        state["healthy_count"] += 1
        state["unhealthy_count"] = 0
    else:
        state["unhealthy_count"] += 1
        state["healthy_count"] = 0

    text = read_base()
    model = current_model(text)
    bridged = BRIDGE_MARKER in text

    if model == "deepseek-v4-pro" and bridged:
        if state["healthy_count"] >= N:
            log("flash healthy %d/%d; reverting fleet to deepseek-flash" % (state["healthy_count"], N))
            if sync_with_origin():
                new_text = flip(read_base(), to_pro=False)
                with open(BASE, "w") as f:
                    f.write(new_text)
                ok = commit_and_push("revert to deepseek-flash (outage recovered)")
                log("revert pushed" if ok else "revert failed; will retry")
            state["healthy_count"] = 0
        else:
            log("bridge active; flash healthy %d/%d (unhealthy %d/%d)"
                % (state["healthy_count"], N, state["unhealthy_count"], N))
    elif model == "deepseek-flash":
        if state["unhealthy_count"] >= N:
            log("flash unhealthy %d/%d; failing fleet over to deepseek-v4-pro" % (state["unhealthy_count"], N))
            if sync_with_origin():
                new_text = flip(read_base(), to_pro=True)
                with open(BASE, "w") as f:
                    f.write(new_text)
                ok = commit_and_push("failover to deepseek-v4-pro (flash outage)")
                log("failover pushed" if ok else "failover failed; will retry")
            state["unhealthy_count"] = 0
        else:
            log("flash unhealthy %d/%d (healthy %d/%d)"
                % (state["unhealthy_count"], N, state["healthy_count"], N))
    else:
        log("no action: model=%s bridged=%s" % (model, bridged))

    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


if __name__ == "__main__":
    main()
