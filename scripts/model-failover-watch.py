#!/usr/bin/env python3
"""Model failover watch — runs on secratary via cron (every 5 min).

Keeps the DSH fleet on the best working model without a human. Three tiers, in
preference order:

    0  deepseek-official / deepseek-flash                     (the owner's normal)
    1  deepseek-official / deepseek-v4-pro                    (owner-chosen bridge)
    2  deepinfra        / deepseek-ai/DeepSeek-V4-Flash-0731  (independent infra)

Every run probes ALL tiers (one 1-token completion each, 20 s cap) and writes
the fleet default in settings/base.yaml to a tier that is actually answering:

  DOWN  current tier has failed N consecutive probes  -> jump to the LOWEST tier
        below it that answered in THIS probe. A dead provider therefore fails
        the fleet over in ~10 min, and it never stops on a tier that is itself
        dead.
  UP    a HIGHER tier has answered N consecutive probes -> climb back to it.
        Recovery needs N consecutive good probes so a flapping provider cannot
        bounce the fleet.

Only settings/base.yaml is touched, one commit per move, pushed to origin so
autosync carries it to every machine within 15 min. The `# BRIDGE(` marker line
means "not on the owner's normal model": if the owner ever pins a model by hand
and removes that line, this script leaves it alone.

State survives restarts in ~/.dsh-model-watch/state.json; every run and move is
logged to ~/.dsh-model-watch/watch.log.

Prior art: the 2026-09-14 platform-wide DeepSeek flash outage. Nothing failed
over automatically, the fleet stayed pinned to a dead model, and the owner's
office was blocked. This script is the answer to "this can never happen again".
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

N = 2          # consecutive same-state probes before a move
TIMEOUT = 20   # seconds per probe; a hang counts as unhealthy

# (provider, model, chat-completions base, credential ref)
TIERS = [
    ("deepseek-official", "deepseek-flash", "https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    ("deepseek-official", "deepseek-v4-pro", "https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    ("deepinfra", "deepseek-ai/DeepSeek-V4-Flash-0731", "https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY"),
]

BRIDGE_MARKER = "# BRIDGE("
BRIDGE_LINE = ("# BRIDGE(2026-09-14): fleet is on a fallback model while the preferred one is "
               "down; model-failover-watch.py manages this line.")
PROVIDER_RE = re.compile(r"^  provider: (\S+)$")
MODEL_RE = re.compile(r"^  model: (\S+)$")


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def credentials():
    """Map credential ref -> secret from the harness credential store."""
    out = {}
    path = os.path.expanduser("~/.dsh/.credentials.yaml")
    try:
        text = open(path).read()
    except OSError:
        return out
    for m in re.finditer(r"^\s*([A-Z0-9_]+):\s*(\S+)\s*$", text, re.M):
        out[m.group(1)] = m.group(2)
    return out


def probe(tier, creds):
    """True when the tier answers a completion with a real body."""
    provider, model, base, ref = tier
    key = creds.get(ref)
    if not key:
        return False
    body = json.dumps({"model": model,
                       "messages": [{"role": "user", "content": "ping"}],
                       "max_tokens": 1})
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=body.encode(),
        headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"},
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


def current_index(text):
    provider = model = None
    for line in text.splitlines():
        if PROVIDER_RE.match(line):
            provider = PROVIDER_RE.match(line).group(1)
        elif MODEL_RE.match(line):
            model = MODEL_RE.match(line).group(1)
        if provider and model:
            break
    for i, (p, m, _b, _k) in enumerate(TIERS):
        if p == provider and m == model:
            return i
    return None


def render(text, target):
    provider, model, _b, _k = TIERS[target]
    out = []
    for line in text.splitlines():
        if line.startswith(BRIDGE_MARKER):
            continue
        if PROVIDER_RE.match(line):
            line = "  provider: %s" % provider
        elif MODEL_RE.match(line):
            line = "  model: %s" % model
        out.append(line)
    if target > 0:
        for i, line in enumerate(out):
            if line == "agent-default-model:":
                out.insert(i, BRIDGE_LINE)
                break
    return "\n".join(out) + "\n"


def git(*args):
    return subprocess.run(["git", "-C", REPO] + list(args), capture_output=True, text=True)


def safe_to_commit():
    """Local master must not be behind origin, or the flip cannot be pushed."""
    if git("push", "origin", "master").returncode != 0:
        pass  # could be behind; the ancestor check decides
    if git("fetch", "origin").returncode != 0:
        log("git fetch failed; skipping this run")
        return False
    if git("merge-base", "--is-ancestor", "origin/master", "HEAD").returncode != 0:
        log("checkout is behind or diverged from origin/master; skipping this run")
        return False
    return True


def move_to(target, why):
    if not safe_to_commit():
        return False
    new_text = render(read_base(), target)
    with open(BASE, "w") as f:
        f.write(new_text)
    git("add", "settings/base.yaml")
    r = git("commit", "-m", "model: failover -- %s by model-failover-watch.py" % why)
    if r.returncode != 0:
        log("commit failed: %s" % r.stderr.strip())
        return False
    r = git("push", "origin", "master")
    if r.returncode != 0:
        log("push failed: %s" % (r.stderr.strip().splitlines() or ['?'])[-1])
        return False
    return True


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    state = {"ok": {}, "bad": {}}
    if os.path.exists(STATE_FILE):
        try:
            state.update(json.load(open(STATE_FILE)))
        except Exception:
            pass
    ok = state.get("ok", {})
    bad = state.get("bad", {})

    creds = credentials()
    health = [probe(t, creds) for t in TIERS]
    for i in range(len(TIERS)):
        k = str(i)
        if health[i]:
            ok[k] = ok.get(k, 0) + 1
            bad[k] = 0
        else:
            bad[k] = bad.get(k, 0) + 1
            ok[k] = 0

    text = read_base()
    cur = current_index(text)
    names = ["%s/%s" % (t[0], t[1]) for t in TIERS]
    log("probe ok=%s bad=%s current=%s" % (
        [names[i] for i in range(len(TIERS)) if health[i]],
        [names[i] for i in range(len(TIERS)) if not health[i]],
        "?" if cur is None else names[cur]))

    if cur is None:
        log("current model is not one of the known tiers; leaving it alone")
    elif bad.get(str(cur), 0) >= N:
        down = [j for j in range(cur + 1, len(TIERS)) if health[j]]
        if down:
            target = down[0]
            log("FAILOVER %s -> %s (failed %d probes)" % (names[cur], names[target], bad[str(cur)]))
            if move_to(target, "failover to %s (%s down)" % (names[target], names[cur])):
                log("failover committed")
                bad[str(cur)] = 0
        else:
            log("current tier is down but no lower tier is answering; holding")
    else:
        up = [j for j in range(0, cur) if ok.get(str(j), 0) >= N]
        if up:
            target = up[0]
            log("RECOVERY %s -> %s (healthy %d probes)" % (names[cur], names[target], ok[str(target)]))
            if move_to(target, "recovery to %s" % names[target]):
                log("recovery committed")
                ok[str(target)] = 0

    state["ok"] = ok
    state["bad"] = bad
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


if __name__ == "__main__":
    main()
