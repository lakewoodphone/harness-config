#!/usr/bin/env python3
"""CRON TARGET GUARD -- every path a crontab calls must exist, and somebody must hear when it does not.

WHY THIS EXISTS (2026-09-30, measured on the authority `secratary`)
------------------------------------------------------------------
Five crontab entries on the authority called files that DO NOT EXIST:

    */30  scripts/dialpad-harvest-cron.sh        the shop's Dialpad CALL harvest
    15,45 scripts/dialpad-sms-harvest-cron.sh    the shop's Dialpad SMS harvest
    */5   scripts/dialpad-recording-gap.py       voicemail recording backfill
    */10  scripts/dialpad-transcript-gap.py      call transcript backfill
    */15  scripts/ha/check-security-absence.py  the Home Assistant security ABSENCE alarm

The scripts were real and had been running: `~/dialpad-harvest.log` records a healthy pass at
2026-09-29T11:30Z and the trees preserved on 2026-09-28 carry byte-identical copies of all five.
They lived only in the working tree, and when the deployed checkout was switched to another
branch the working tree lost them -- while the crontab, which is not in git, kept calling them.

Nothing noticed for a day and a half. `cron` writes one line to a per-job log that nobody reads,
and `/bin/sh: 1: ...: not found` is indistinguishable from silence. The company's own freshness
check did eventually go red (`comms_freshness`: "call harvest has not completed in 27.9h"), which
is a check on the CONSEQUENCE, 28 hours later, and only because someone had built one.

THE CLASS THIS KILLS
--------------------
"A scheduled job that has stopped existing" is invisible by construction: the schedule is data
outside version control, the failure is a log line, and the consequence is an absence. The only
cheap way to see it is to look at the schedule and the filesystem together, which is what this
does.

CHANGED 2026-10-11 (the cutover port) -- THIS GUARD COULD NOT SEE ITS OWN SUBJECT.
------------------------------------------------------------------------------
The estate's whole crontab is written as `cron-wrap.sh <name> <base64-of-the-command>`. This
guard parsed the RAW crontab text, so every one of those ~60 entries resolved to the single
program `/usr/local/bin/cron-wrap.sh`, which always exists. Measured on the office box:
`grep -nE "base64|b64|decode" cron-target-guard.py` -> **no matches**, while TWO crontab targets
were genuinely absent and this guard reported `clean - 64 cron target(s) checked, 0 missing` on
every one of 247 recorded runs. A guard that cannot fail is not a guard, it is a green light with
a wiring diagram drawn on it.

So: every payload is now DECODED (base64, and recursively, because a payload may itself start
`base64 -d <<<` or `/bin/sh -c '...'`) and the program the payload NAMES is the thing checked.
`decode_stats` is reported on every run, and `undecoded` names any payload that would not decode
-- a decode failure is a finding, never a silent pass.

Exit codes: 0 clean, 1 at least one target missing or unusable, 2 the guard could not read the
crontab at all (which is itself a finding -- an unreadable schedule is not an empty one).

USAGE
    cron-target-guard.py                 # human output, exit 1 on any problem
    cron-target-guard.py --json          # machine output on stdout
    cron-target-guard.py --write-status  # also write ~/.cron-targets/status.json
    cron-target-guard.py --selftest      # prove the detector fires, and stays clean, on known input

The status file is the durable half: `~/.cron-targets/status.json` carries `ok`, `checked`,
`missing` and `at`, so a reader that wants a single boolean does not have to parse a command.
`~/.cron-targets/guard.log` keeps the append-only history.

MUST NEVER
    - report a failure because it could not parse something (say `unparsed` instead),
    - exit 0 when the crontab is unreadable,
    - report clean having decoded nothing, when the crontab is written in wrapped form,
    - write anywhere except its own two files under ~/.cron-targets/.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("CRON_TARGETS_STATE", str(Path.home() / ".cron-targets")))
STATUS = STATE_DIR / "status.json"
LOG = STATE_DIR / "guard.log"
# Files this system needs that NO crontab names -- the backup-retention script, the harvest scripts,
# the security-absence alarm. One absolute path per line, `#` comments allowed.
CRITICAL_FILE = STATE_DIR / "critical.txt"
# `--crontab FILE` reads a captured crontab instead of `crontab -l`. Used to prove the detector
# fires (and to test a candidate crontab before installing it); never used by the cron line.
CRONTAB_FILE: str | None = None

SCRIPT_SUFFIXES = (".sh", ".py", ".mjs", ".js", ".ps1", ".cjs")
INTERPRETERS = {
    "python", "python3", "python2", "bash", "sh", "dash", "zsh",
    "node", "nodejs", "pwsh", "powershell",
}
PREFIX_WRAPPERS = {"nohup", "env", "time", "setsid", "command"}
# Wrappers that take arguments of their own before the real command.
WRAPPER_ARITY = {"timeout": 1, "flock": 2, "nice": 1, "ionice": 2}

REDIRECT_RE = re.compile(r"(?<![0-9&])[0-9]?\s*>>?\s*\S+")
HERE_DOC_RE = re.compile(r"<<-?\s*['\"]?\w+['\"]?")
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAP = "cron-wrap.sh"
B64_RE = re.compile(r"^[A-Za-z0-9+/]{16,}={0,2}$")
DECODE_DEPTH = 4


def crontab_text(path: str | None = None) -> tuple[str | None, str]:
    """Return (text, error). `crontab -l` with no jobs exits 1 and prints 'no crontab for user'.

    `path` (from `--crontab FILE`) replaces `crontab -l` so the same detector can be run against a
    captured crontab -- which is how this guard is proved to fire on a real missing target instead
    of being taken on trust.
    """
    if path:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read(), ""
        except Exception as exc:  # noqa: BLE001
            return None, "could not read %s: %s" % (path, exc)
    for argv in (["crontab", "-l"],):
        try:
            p = subprocess.run(argv, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=30)
        except Exception as exc:  # noqa: BLE001
            return None, "could not run %s: %s" % (" ".join(argv), exc)
        if p.returncode == 0:
            return p.stdout or "", ""
        low = (p.stderr or "").lower()
        if "no crontab for" in low:
            return "", ""
        return None, ("crontab -l exited %d: %s" % (p.returncode, (p.stderr or "").strip()[:200]))
    return None, "unreachable"


def decode_wrapped(cmd: str, stats: dict) -> str:
    """Resolve `cron-wrap.sh <name> <base64>` (and any `base64`-carried payload) to the real command.

    The estate wraps every job as `cron-wrap.sh <name> <base64-of-the-command>`. Before this
    existed, the guard saw the wrapper -- one program that always exists -- and reported clean
    while the programs the payloads named were missing. Decoding is recursive because a payload
    can itself be `base64 -d <<< '...'` or `/bin/sh -c '...'`.
    """
    text = cmd
    for _ in range(DECODE_DEPTH):
        try:
            toks = shlex.split(text, posix=True)
        except ValueError:
            toks = text.split()
        if not toks:
            break
        if os.path.basename(toks[0]) == WRAP:
            stats["wrapped"] = stats.get("wrapped", 0) + 1
            if len(toks) >= 3:
                text = _b64(toks[-1]) or text
                continue
        # `base64 -d <<< '...'` / `base64 -d` reading an argument
        if any(os.path.basename(t) == "base64" for t in toks):
            got = None
            for t in toks:
                if t.startswith("-"):
                    continue
                got = _b64(t)
                if got:
                    break
            if got:
                stats["base64_cmd"] = stats.get("base64_cmd", 0) + 1
                text = got
                continue
        # a single bare base64-looking token that is the whole payload
        if len(toks) == 1 and B64_RE.match(toks[0]):
            got = _b64(toks[0])
            if got:
                stats["bare_b64"] = stats.get("bare_b64", 0) + 1
                text = got
                continue
        break
    return text


def _b64(token: str) -> str | None:
    """Decode one base64 token if it really is base64 text (never raise)."""
    tok = token.strip().strip("'\"")
    if len(tok) < 8 or not B64_RE.match(tok):
        return None
    try:
        raw = base64.b64decode(tok + "=" * (-len(tok) % 4), validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        out = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # A decoded command is text with shell in it; junk that happens to decode is not a command.
    if out.count("\x00") or not out.strip():
        return None
    return out


def expand(token: str) -> str:
    home = str(Path.home())
    token = token.replace("$HOME", home).replace("${HOME}", home)
    if token == "~":
        return home
    if token.startswith("~/"):
        return home + token[1:]
    return token


def strip_redirections(cmd: str) -> str:
    cmd = HERE_DOC_RE.sub(" ", cmd)
    prev = None
    while prev != cmd:
        prev = cmd
        cmd = REDIRECT_RE.sub(" ", cmd)
    return cmd


def split_subcommands(cmd: str) -> list[str]:
    """Split on ; && || and newlines, keeping the pieces."""
    parts = re.split(r"[\n]|;|&&|\|\|", cmd)
    return [p.strip() for p in parts if p.strip()]


def tokens_of(sub: str) -> list[str]:
    try:
        return shlex.split(sub, posix=True)
    except ValueError:
        return sub.split()


def script_token(toks: list[str]) -> str | None:
    """Return the token that names a program file, or None."""
    if not toks:
        return None
    i = 0
    # Skip leading VAR=value assignments and wrappers.
    while i < len(toks) and ASSIGN_RE.match(toks[i]):
        i += 1
    while i < len(toks):
        word = os.path.basename(toks[i])
        if word in PREFIX_WRAPPERS:
            i += 1
            continue
        if word in WRAPPER_ARITY:
            i += 1 + WRAPPER_ARITY[word]
            continue
        break
    if i >= len(toks):
        return None

    head = toks[i]
    base = os.path.basename(head)
    if base in INTERPRETERS:
        for cand in toks[i + 1:]:
            if cand.startswith("-") or ASSIGN_RE.match(cand):
                continue
            return cand
        return None
    if head.endswith(SCRIPT_SUFFIXES):
        return head
    return None


def looks_like_path(token: str) -> bool:
    return (token.startswith("/") or token.startswith("~/") or token == "~"
            or token.startswith("./") or token.startswith("../")
            or token.startswith("$HOME"))


def analyse(text: str, stats: dict | None = None) -> list[dict]:
    """Every candidate program path, with the line that names it."""
    stats = stats if stats is not None else {}
    stats.setdefault("lines", 0)
    found: list[dict] = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped and " " not in stripped.split("=")[0]:
            # A crontab environment assignment (`SHELL=/bin/sh`) is not a job.
            continue
        # A job line has five schedule fields; anything else is a variable or a comment.
        fields = stripped.split()
        if len(fields) < 6 and not stripped.startswith("@"):
            continue
        stats["lines"] += 1
        if stripped.startswith("@"):
            cmd = stripped.split(None, 1)[1] if " " in stripped else ""
        else:
            cmd = " ".join(fields[5:])
        if not cmd:
            continue
        before = cmd
        cmd = decode_wrapped(cmd, stats)
        if cmd != before:
            stats["decoded_lines"] = stats.get("decoded_lines", 0) + 1
        elif WRAP in before:
            stats.setdefault("undecoded", []).append(before[:160])
        cmd = strip_redirections(cmd)

        for sub in split_subcommands(cmd):
            toks = tokens_of(sub)
            # Track the effective working directory for relative targets.
            if toks and toks[0] == "cd" and len(toks) > 1:
                found.append({"kind": "cwd", "value": expand(toks[1]), "line": stripped})
                continue
            tok = script_token(toks)
            if tok is None:
                continue
            if not looks_like_path(tok) and "/" not in tok:
                # A bare filename is run from the crontab's cwd (usually $HOME).
                if not tok.endswith(SCRIPT_SUFFIXES):
                    continue
                parent = [f["value"] for f in found if f["kind"] == "cwd"]
                resolved = os.path.join(parent[-1] if parent else str(Path.home()), tok)
            else:
                resolved = expand(tok)
                if not os.path.isabs(resolved):
                    parent = [f["value"] for f in found if f["kind"] == "cwd"]
                    resolved = os.path.join(parent[-1] if parent else str(Path.home()), resolved)
            found.append({"kind": "target", "value": os.path.normpath(resolved), "line": stripped})
    # Deduplicate: one entry per (path, line).
    seen = set()
    out = []
    for item in found:
        key = (item["kind"], item["value"], item["line"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def has_cr(path: str) -> bool:
    """Does this shell script contain a CR? On Linux that is not a script, it is a train wreck.

    Measured 2026-09-30: `scripts/server/install-backup-timer.sh` carried 38 CR bytes in the repo,
    and the estate already has a trail of `.crlf-bak` files from the last time this happened -- the
    dispatcher's own header says "A CR in this file turns every line into `$'\\r': command not found`
    on Linux, and one slipped in the moment this was first written". A shell script that exists, is
    executable, and still cannot run is the guard's exact blind spot: presence is not function.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(1 << 20)
        return b"\r\n" in head
    except OSError:
        return False


def check(items: list[dict]) -> dict:
    targets = [i for i in items if i["kind"] == "target"]
    missing, unreadable, not_executable, ok, crlf = [], [], [], [], []
    for t in targets:
        path = t["value"]
        if not os.path.exists(path):
            missing.append({"path": path, "line": t["line"]})
            continue
        if not os.access(path, os.R_OK):
            unreadable.append({"path": path, "line": t["line"]})
            continue
        # CRLF is checked BEFORE the execute bit, and independently of it: a script can be
        # non-executable AND carry CR bytes, and the first version of this reported only the mode
        # and `continue`d, so the CRLF case was never reached (caught by the selftest).
        if path.endswith(".sh") and has_cr(path):
            crlf.append({"path": path, "line": t["line"]})
            continue
        if path.endswith((".sh", ".ps1")):
            if not os.access(path, os.X_OK):
                not_executable.append({"path": path, "line": t["line"]})
                continue
        ok.append(path)
    # THE CRITICAL PATHS. A crontab is not the only thing that names a file this system needs.
    # Measured 2026-09-30: the backup-retention script was deleted by a branch switch in the
    # deployed tree and NOTHING named it -- `backup-data.sh` calls it, notices it is gone, prints a
    # warning and carries on, so the backups grew unbounded until the disk reached 99% (P2799). The
    # five harvest scripts and the HA security-absence alarm were lost the same way. Those files
    # live in the guard's own state dir as `critical.txt`, one path per line, and are checked here
    # because a second guard would be a second thing to forget.
    crit_missing = []
    crit = CRITICAL_FILE
    crit_paths = []
    if crit.is_file():
        try:
            for ln in crit.read_text(encoding="utf-8").splitlines():
                p = ln.strip()
                if not p or p.startswith("#"):
                    continue
                p = expand(p)
                crit_paths.append(p)
                if not os.path.exists(p):
                    crit_missing.append({"path": p, "line": "critical path (%s)" % crit})
                elif not os.access(p, os.R_OK):
                    crit_missing.append({"path": p, "line": "critical path, unreadable"})
                elif p.endswith(".sh") and has_cr(p):
                    # Same rule as a cron target: on Linux a shell script with CR bytes is not a
                    # script. The critical list is where the files NO crontab names live, so this is
                    # the only place they would ever be checked.
                    crit_missing.append({"path": p, "line": "critical path, CRLF shell script"})
                elif p.endswith(".sh") and not os.access(p, os.X_OK):
                    crit_missing.append({"path": p, "line": "critical path, no execute bit"})
        except Exception as exc:  # noqa: BLE001
            crit_missing.append({"path": str(crit), "line": "could not read the critical list: %s" % exc})
    return {
        "ok": not (missing or unreadable or not_executable or crit_missing or crlf),
        "checked": len(targets),
        "critical_checked": len(crit_paths),
        "ok_paths": ok,
        "missing": missing,
        "unreadable": unreadable,
        "not_executable": not_executable,
        "crlf": crlf,
        "critical_missing": crit_missing,
    }


def render(res: dict, error: str) -> str:
    lines = []
    for m in res["missing"]:
        lines.append("MISSING     %s\n            <= %s" % (m["path"], m["line"]))
    for m in res["unreadable"]:
        lines.append("UNREADABLE  %s\n            <= %s" % (m["path"], m["line"]))
    for m in res["not_executable"]:
        lines.append("NO EXEC BIT %s\n            <= %s" % (m["path"], m["line"]))
    for m in res.get("crlf", []):
        lines.append("CRLF SHELL  %s\n            <= %s   (CRLF makes every line 'not found' on Linux)"
                     % (m["path"], m["line"]))
    for m in res.get("critical_missing", []):
        lines.append("CRITICAL MISSING %s\n            <= %s" % (m["path"], m["line"]))
    if error:
        lines.append("UNREADABLE CRONTAB: %s" % error)
    if not lines:
        lines.append("clean - %d cron target(s) and %d critical path(s) checked, all present"
                     % (res["checked"], res.get("critical_checked", 0)))
    # The decode accounting is printed on EVERY run, clean or not. A guard that checks one
    # wrapper 60 times must not be able to look like a guard that checked 60 programs.
    ds = res.get("decode_stats") or {}
    if ds:
        lines.append("decoded: %d wrapped line(s), %d command(s) resolved from a payload, "
                     "%d undecoded payload(s)" % (ds.get("wrapped", 0), ds.get("decoded_lines", 0),
                                                  len(ds.get("undecoded") or [])))
        for u in (ds.get("undecoded") or [])[:5]:
            lines.append("UNDECODED   %s" % u)
    return "\n".join(lines)


def selftest() -> int:
    """Prove the detector fires on a missing target and stays quiet on a present one."""
    global CRITICAL_FILE
    good = sys.executable
    sample = (
        "SHELL=/bin/sh\n"
        "# a comment, not a job\n"
        "*/5 * * * * %s -c 'pass' >>/tmp/g.log 2>&1\n"
        "*/5 * * * * %s --nope\n"
        "*/5 * * * * cd /home/zabz && ./definitely-not-here-12345.sh\n"
        "15,45 * * * * /usr/bin/python3 /tmp/definitely-not-here-12345.py >> /tmp/x.log 2>&1\n"
        "*/5 * * * * flock -n /tmp/l.lock /bin/bash /tmp/also-not-here-999.py\n"
    ) % (good, good)

    # THE WRAPPED HALF -- the defect this port fixes. A cron-wrap.sh payload that names a
    # non-existent program must be reported, and the wrapper itself must not be all that is seen.
    payload_missing = base64.b64encode(b"/usr/bin/python3 /tmp/definitely-not-here-wrapped-4242.py").decode()
    payload_present = base64.b64encode(("%s -c 'pass'" % good).encode()).decode()
    sample += ("*/5 * * * * /usr/local/bin/cron-wrap.sh wrapped-missing %s\n" % payload_missing)
    sample += ("*/5 * * * * /usr/local/bin/cron-wrap.sh wrapped-present %s\n" % payload_present)
    # double-wrapped: `base64 -d <<< <b64 of b64>`
    inner = base64.b64encode(b"/bin/sh /tmp/definitely-not-here-double-77.sh").decode()
    outer = base64.b64encode(("base64 -d <<< '%s'" % inner).encode()).decode()
    sample += ("*/5 * * * * /usr/local/bin/cron-wrap.sh wrapped-double %s\n" % outer)

    # The critical-path half, on a temporary list: one path that exists, one that does not.
    import tempfile
    tmpdir = Path(tempfile.mkdtemp())
    crit = tmpdir / "critical.txt"
    crit.write_text("# a comment\n%s\n/tmp/definitely-not-here-critical-77.py\n" % good,
                    encoding="utf-8")
    keep = CRITICAL_FILE
    CRITICAL_FILE = crit
    try:
        stats: dict = {}
        res = check(analyse(sample, stats))
        res["decode_stats"] = stats
    finally:
        CRITICAL_FILE = keep

    missing = sorted(m["path"] for m in res["missing"])
    want = sorted([
        "/tmp/definitely-not-here-12345.py",
        "/tmp/also-not-here-999.py",
        "/home/zabz/definitely-not-here-12345.sh",
        "/tmp/definitely-not-here-wrapped-4242.py",
        "/tmp/definitely-not-here-double-77.sh",
    ])
    problems = []
    if missing != want:
        problems.append("expected missing %s, got %s" % (want, missing))
    if res["checked"] < 5:
        problems.append("expected at least 5 targets checked, got %d" % res["checked"])
    if stats.get("decoded_lines", 0) < 3:
        problems.append("the wrapped payloads were not decoded: %r" % stats)
    if stats.get("undecoded"):
        problems.append("a valid payload was left undecoded: %r" % stats["undecoded"])
    crit_missing = [m["path"] for m in res.get("critical_missing", [])]
    if crit_missing != ["/tmp/definitely-not-here-critical-77.py"]:
        problems.append("critical-path check wrong: %s" % crit_missing)
    if res.get("critical_checked") != 2:
        problems.append("critical list length wrong: %s" % res.get("critical_checked"))
    # The wrapper must never be the only thing seen: `cron-wrap.sh` itself is not a finding here
    # (it exists), but the payload's program must appear in the checked set.
    if "/usr/local/bin/cron-wrap.sh" in missing:
        problems.append("the wrapper was reported missing instead of the payload's program")
    # The CRLF half: a shell script with CR bytes is not a script.
    import tempfile as _tf
    crl = Path(_tf.mkdtemp()) / "crlf.sh"
    crl.write_bytes(b"#!/bin/bash\r\necho hi\r\n")
    keep_crit = CRITICAL_FILE
    crit.write_text("# a comment\n%s\n%s\n" % (good, crl), encoding="utf-8")
    CRITICAL_FILE = crit
    try:
        items2 = analyse("* * * * * /bin/bash %s\n" % crl)
        res2 = check(items2)
    finally:
        CRITICAL_FILE = keep_crit
    crlf_hits = [m["path"] for m in res2.get("crlf", [])]
    if str(crl) not in crlf_hits:
        problems.append("a CRLF shell script was not reported: %s" % crlf_hits)
    lf = Path(_tf.mkdtemp()) / "lf.sh"
    lf.write_bytes(b"#!/bin/bash\necho hi\n")
    res3 = check(analyse("* * * * * /bin/bash %s\n" % lf))
    if res3.get("crlf"):
        problems.append("a clean LF script was reported as CRLF")
    # The present interpreter must not be reported.
    for path in res["ok_paths"]:
        if not os.path.exists(path):
            problems.append("reported a non-existent path as ok: %s" % path)
    if problems:
        print("SELFTEST FAILED")
        for p in problems:
            print("  - " + p)
        return 1
    print("SELFTEST OK (%d cron target(s), %d critical path(s), %d missing as expected, "
          "%d payload(s) decoded)"
          % (res["checked"], res.get("critical_checked", 0), len(res["missing"]),
             stats.get("decoded_lines", 0)))
    return 0


def main(argv: list[str]) -> int:
    global CRONTAB_FILE
    if "--selftest" in argv:
        return selftest()
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    if "--crontab" in argv:
        i = argv.index("--crontab")
        if i + 1 >= len(argv):
            print("--crontab needs a FILE", file=sys.stderr)
            return 2
        CRONTAB_FILE = argv[i + 1]

    text, error = crontab_text(CRONTAB_FILE)
    if text is None:
        res = {"ok": False, "checked": 0, "ok_paths": [], "missing": [],
               "unreadable": [], "not_executable": []}
        out = render(res, error)
        print(out, file=sys.stderr)
        return 2

    stats: dict = {}
    items = analyse(text, stats)
    res = check(items)
    res["at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    res["crontab_lines"] = len([l for l in text.splitlines() if l.strip()])
    res["decode_stats"] = stats
    # A crontab written in wrapped form whose payloads did not decode is a FAILURE of this guard,
    # not a clean crontab: that is exactly the 2026-10-11 defect, and it must never pass silently.
    if stats.get("undecoded") and res["ok"]:
        res["ok"] = False
        res["unreadable"] = list(res.get("unreadable", [])) + [
            {"path": u, "line": "payload did not decode"} for u in stats["undecoded"]]

    if "--json" in argv:
        print(json.dumps(res, indent=1))
    else:
        print(render(res, ""))

    if "--write-status" in argv:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = STATUS.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
            tmp.replace(STATUS)
            with LOG.open("a", encoding="utf-8") as fh:
                if res["ok"]:
                    fh.write("%s  ok  %d target(s) checked, %d payload(s) decoded\n"
                             % (res["at"], res["checked"], stats.get("decoded_lines", 0)))
                else:
                    fh.write("%s  FAIL  missing=%s unreadable=%s not_executable=%s crit=%s\n"
                             % (res["at"],
                                [m["path"] for m in res["missing"]],
                                [m["path"] for m in res["unreadable"]],
                                [m["path"] for m in res["not_executable"]],
                                [m["path"] for m in res.get("critical_missing", [])]))
        except Exception as exc:  # noqa: BLE001
            print("WARN: could not write %s: %s" % (STATUS, exc), file=sys.stderr)

    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
