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

# Node-portable (2026-10-02, item 349). The old literal pinned this script to
# secratary's checkout, so a copy on ZABZ-TECH (C:\Users\ezabz\Code\harness-config)
# or linux-pc could not find settings/base.yaml and would crash before it could
# move anything. The default is now the repo this file lives in; a deployment may
# still override with HARNESS_CONFIG_REPO.
REPO = os.environ.get("HARNESS_CONFIG_REPO") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
BASE = os.path.join(REPO, "settings", "base.yaml")
STATE_DIR = os.path.expanduser("~/.dsh-model-watch")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
STATUS_FILE = os.path.join(STATE_DIR, "status.json")
LOG_FILE = os.path.join(STATE_DIR, "watch.log")
# A flip that could not be pushed is queued here and retried every run, so a
# local-only move is RECOVERABLE rather than lost (2026-10-02, item 367).
PENDING_FILE = os.path.join(STATE_DIR, "pending-flip.json")

# Durability must not run solely through secratary. origin lives on secratary; on
# the night the secratary HOST is the machine that is dark, persist() could only
# ever return NOT DURABLE, so the second mover on ZABZ-TECH flipped one node and
# the rest of the fleet stayed pinned to the dead tier -- the exact outage shape
# the second mover exists to end. A mirror remote on any host that is NOT
# secratary gives the scratch-worktree commit a push target the fleet can still
# fetch. MFW_MIRROR_REMOTE="" disables the fallback.
MIRROR_REMOTE = os.environ.get("MFW_MIRROR_REMOTE", "mirror")

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


def write_local(target):
    """Write settings/base.yaml atomically. THIS is the fix; git is only durability.

    Rewritten 2026-10-02 after the outage it did not prevent. The old move_to()
    refused to do anything unless the checkout was a clean ancestor of
    origin/master, because the flip is useless until it is pushed. On the
    authority the checkout is a long-lived feature branch (measured 2026-10-02:
    branch hk/176-headless-resume, 121 behind / 48 ahead of origin/master), so
    the precondition was PERMANENTLY false: between 2026-10-01T19:30Z, when
    deepseek-official/deepseek-flash stopped answering at the provider, and
    ~22:30Z when it recovered, this script decided to fail over 264 times and
    wrote "checkout is behind or diverged from origin/master; skipping this run"
    263 times. Every node's engine was pinned to that dead id through the whole
    window - the owner texted 'DSH ... is down on the yoga laptop on the tech
    computer and on the iPhone and on the secretary server this is an emergency'.

    A guard that can name the fix must never let a bookkeeping precondition stop
    it. So: the local file is written FIRST and unconditionally, then the commit
    and push are attempted as durability, and a push that fails is reported as
    NOT DURABLE rather than undoing the thing that keeps the fleet alive.
    """
    new_text = render(read_base(), target)
    tmp = BASE + ".tmp-failover"
    with open(tmp, "w") as f:
        f.write(new_text)
    os.replace(tmp, BASE)
    return True


def _scratch_worktree_persist(target, why, dest_ref="HEAD:master", marker=None,
                              remote="origin"):
    """Commit the ONE file onto <remote>/master from a scratch worktree and push.

    Used when the main checkout cannot carry the commit (diverged, or a dirty
    tree that is not ours to commit). This is what makes the flip reach the
    Windows nodes, whose engines read their own settings via autosync. Nothing
    is merged, rebased, reset or forced: a scratch tree at <remote>/master, one
    file written, one commit, `git push <remote> HEAD:master` - which fails
    loudly rather than rewriting anything if it is not a fast-forward.

    `remote` is normally origin (secratary). Item 367 added the same mechanism
    against a mirror remote that is NOT secratary, so durability does not die
    with the origin host.
    """
    import shutil
    import tempfile
    base_ref = "%s/master" % remote
    tmpdir = tempfile.mkdtemp(prefix="mfw-")
    try:
        git("fetch", remote)
        if git("worktree", "add", "--detach", tmpdir, base_ref).returncode != 0:
            return False, "scratch worktree could not be created from %s" % base_ref
        target_file = os.path.join(tmpdir, "settings", "base.yaml")
        try:
            text = open(target_file).read()
        except OSError as exc:
            return False, "cannot read %s settings/base.yaml: %s" % (base_ref, exc)
        new_text = render(text, target)
        if marker:
            new_text = new_text.rstrip("\n") + "\n" + marker + "\n"
        if new_text == text:
            # <remote>/master already names the target: durability is trivially
            # true and there is nothing to push. Said out loud rather than
            # silently treating a no-op as a successful commit.
            return True, "%s already carries %s; nothing to push" % (base_ref, TIERS[target][1])
        with open(target_file, "w") as f:
            f.write(new_text)
        for args in (["add", "settings/base.yaml"],
                     ["commit", "-m", "model: failover -- %s by model-failover-watch.py" % why],
                     ["push", remote, dest_ref]):
            r = subprocess.run(["git", "-C", tmpdir] + args, capture_output=True, text=True)
            if r.returncode != 0:
                tail = (r.stderr.strip().splitlines() or ["(no stderr)"])[-1]
                return False, "git %s failed in the scratch worktree: %s" % (args[0], tail)
        return True, "committed onto %s from a scratch worktree" % base_ref
    finally:
        subprocess.run(["git", "-C", REPO, "worktree", "remove", "--force", tmpdir],
                       capture_output=True, text=True)
        shutil.rmtree(tmpdir, ignore_errors=True)


def persist(target, why):
    """Best-effort durability. Returns (durable, detail). Never raises.

    Tries origin first (secratary). If origin cannot carry the commit -- because
    the origin HOST is the machine that is down, or the checkout diverged past a
    clean scratch push -- it tries MIRROR_REMOTE, a second remote that is not
    secratary, so a flip still reaches the fleet on the one night that matters
    (item 367).
    """
    origin_detail = None
    if git("fetch", "origin").returncode != 0:
        origin_detail = "git fetch failed (offline or remote down)"
    elif git("merge-base", "--is-ancestor", "origin/master", "HEAD").returncode == 0:
        git("add", "settings/base.yaml")
        r = git("commit", "-m", "model: failover -- %s by model-failover-watch.py" % why)
        if r.returncode != 0:
            origin_detail = "commit failed: %s" % (r.stderr.strip() or "already committed")
        else:
            r = git("push", "origin", "HEAD:master")
            if r.returncode == 0:
                return True, "committed and pushed from the main checkout"
            origin_detail = "push failed: %s" % (r.stderr.strip().splitlines() or ["?"])[-1]
    else:
        ok, detail = _scratch_worktree_persist(target, why)
        if ok:
            return True, detail
        origin_detail = detail

    if MIRROR_REMOTE:
        ok, detail = _scratch_worktree_persist(target, why, remote=MIRROR_REMOTE)
        if ok:
            return True, ("origin could not carry it (%s); durability went via the "
                          "non-secratary mirror '%s': %s"
                          % (origin_detail, MIRROR_REMOTE, detail))
        return False, ("%s; mirror '%s' also failed: %s"
                       % (origin_detail, MIRROR_REMOTE, detail))
    return False, origin_detail


def write_pending(target, why):
    """Queue a flip that is on disk but not yet durable, to retry every run."""
    try:
        with open(PENDING_FILE, "w") as f:
            json.dump({"target": target, "why": why,
                       "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f)
    except OSError:
        pass


def pending_flip():
    """The queued flip as a dict, or None."""
    try:
        return json.load(open(PENDING_FILE))
    except Exception:
        return None


def clear_pending():
    try:
        os.unlink(PENDING_FILE)
    except OSError:
        pass


def flush_pending():
    """Retry a queued flip before this run probes. Returns a detail line or None.

    This is the other half of item 367: if neither origin nor the mirror answered
    when the flip was applied, the move is not lost -- it is retried on every
    subsequent run and delivered the moment a durable remote answers.
    """
    p = pending_flip()
    if not p:
        return None
    durable, detail = persist(p["target"], p.get("why", "queued flip"))
    if durable:
        clear_pending()
        log("QUEUED FLIP DELIVERED: %s -> %s (%s)"
            % (p.get("why", "?"), TIERS[p["target"]][1], detail))
        return detail
    log("queued flip still not deliverable: %s" % detail)
    return None


def move_to(target, why):
    """Apply locally, then try to make it survive. The local apply is the move.

    Returns "durable" | "local-only" | False; the caller treats any truthy value
    as the move having happened, because it has: the file on disk is flipped.
    A move that is not durable is QUEUED, not dropped (item 367).
    """
    if not write_local(target):
        return False
    durable, detail = persist(target, why)
    if durable:
        clear_pending()
        log("persisted: %s" % detail)
        return "durable"
    write_pending(target, why)
    log("NOT DURABLE: %s -- settings/base.yaml was still flipped locally, so this "
        "node is on %s, but the other machines will not receive it until a push "
        "succeeds. QUEUED as a pending flip and retried every run (item 367)."
        % (detail, TIERS[target][1]))
    return "local-only"


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

    # Deliver a flip a previous run could not push (origin host was down).
    flush_pending()

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
            outcome = move_to(target, "failover to %s (%s down)" % (names[target], names[cur]))
            if outcome:
                log("failover applied (%s)" % outcome)
                state["last_move"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                      "from": names[cur], "to": names[target], "kind": "failover",
                                      "durable": outcome == "durable"}
                state["not_durable"] = outcome != "durable"
                bad[str(cur)] = 0
        else:
            log("current tier is down but no lower tier is answering; holding")
    else:
        up = [j for j in range(0, cur) if ok.get(str(j), 0) >= N]
        if up:
            target = up[0]
            log("RECOVERY %s -> %s (healthy %d probes)" % (names[cur], names[target], ok[str(target)]))
            outcome = move_to(target, "recovery to %s" % names[target])
            if outcome:
                log("recovery applied (%s)" % outcome)
                state["last_move"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                      "from": names[cur], "to": names[target], "kind": "recovery",
                                      "durable": outcome == "durable"}
                state["not_durable"] = outcome != "durable"
                ok[str(target)] = 0

    state["ok"] = ok
    state["bad"] = bad
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

    # A machine-readable surface so a monitor, the badge or a future session can
    # see what the fleet is actually running and when it last moved, without
    # parsing the log. This exists because the 2026-09-14 outage proved the fleet
    # can change model silently and nobody is told.
    status = {
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "current": "?" if cur is None else names[cur],
        "tier": cur,
        "bridged": BRIDGE_MARKER in read_base(),
        "healthy": [names[i] for i in range(len(TIERS)) if health[i]],
        "unhealthy": [names[i] for i in range(len(TIERS)) if not health[i]],
        "last_move": state.get("last_move"),
        # LOCAL-ONLY MOVES ARE NOT A SUCCESS (2026-10-02). A flip this node applied but
        # could not push leaves every other machine on the dead model, which is the
        # exact outage shape this script exists to end - so it is a first-class field
        # a monitor can alarm on, not a line in a log nobody reads.
        "not_durable": bool(state.get("not_durable")),
        # A queued flip is local-only but RECOVERABLE: it is retried on every run
        # and delivered when origin or the mirror answers (item 367).
        "pending_flip": pending_flip(),
    }
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=1)
        f.write("\n")


def doctor(prove_push=False):
    """Say whether a failover could actually be applied and made durable HERE.

    Added 2026-10-02: the script spent three hours telling a log nobody reads that
    it could not act. This prints the two facts that decide it - which tier is
    answering, and whether this checkout can carry the commit - and, with
    --prove-push, proves the fallback path end to end by pushing a throwaway ref
    (never master). Exit 0 when the fleet could be moved, 1 when it could not.
    """
    creds = credentials()
    names = ["%s/%s" % (t[0], t[1]) for t in TIERS]
    health = [probe(t, creds) for t in TIERS]
    text = read_base()
    cur = current_index(text)
    print("current:  %s" % ("?" if cur is None else names[cur]))
    print("answering: %s" % ", ".join(names[i] for i in range(len(TIERS)) if health[i]) or "none")
    print("dead:      %s" % (", ".join(names[i] for i in range(len(TIERS)) if not health[i]) or "none"))
    ancestry_ok = (git("fetch", "origin").returncode == 0
                   and git("merge-base", "--is-ancestor", "origin/master", "HEAD").returncode == 0)
    print("main checkout can carry the commit: %s" % ("yes" if ancestry_ok else "no"))
    print("path that would be used:             %s"
          % ("main checkout + push" if ancestry_ok else "scratch worktree + push origin HEAD:master"))
    if cur is not None and not health[cur] and any(health[cur + 1:]):
        print("VERDICT: failover is REQUIRED and CAN be applied" +
              ("" if ancestry_ok else " (local flip always works; durability goes via the scratch worktree)"))
        rc = 0
    elif cur is not None and health[cur]:
        print("VERDICT: nothing to do, the current tier answers")
        rc = 0
    else:
        print("VERDICT: the tier in force is dead and no lower tier answers -- HOLDING")
        rc = 1
    if prove_push:
        # PROVES THE MECHANISM WITHOUT TOUCHING master: same worktree, same commit,
        # pushed to a throwaway ref. Delete it afterwards:
        #   git push origin --delete refs/heads/mfw-selftest
        ok, detail = _scratch_worktree_persist(
            cur if cur is not None else 0,
            "selftest (throwaway ref, nothing to see here)",
            dest_ref="HEAD:refs/heads/mfw-selftest",
            marker="# mfw-selftest %s" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        print("prove-push (throwaway ref mfw-selftest, master untouched): %s -- %s"
              % ("OK" if ok else "FAILED", detail))
    return rc


if __name__ == "__main__":
    if "--doctor" in sys.argv:
        sys.exit(doctor(prove_push="--prove-push" in sys.argv))
    main()
