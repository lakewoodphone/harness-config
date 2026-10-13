#!/usr/bin/env python3
"""guard-registry-check.py -- verify the guards that matter, from a DIFFERENT process.

WHY THIS EXISTS (housekeeping item 175, journal SI-5)
-----------------------------------------------------
A guard verified by the same process that could disable it is not a guard. The failure
to design against is a self-modification that silently turns a safety check off, and the
published evidence is that agents attempt exactly that. This checker is the second
process: it never runs the guards and it does not trust them. It reads the registry
(`guards.yaml`), the live crontab, and each guard's own status file, and it exits
non-zero when a guard is MISSING, DISABLED or FAILING.

  * missing   -- no active crontab line matches the guard's `cron_match`.
  * disabled  -- the registry marks `enabled: false`, or the command file is gone or
                 has lost its execute bit.
  * failing   -- the guard's status file is absent, unreadable, or says `ok` is not true;
                 or the status is older than the guard's `max_age_seconds`.
  * unapproved-- the registry hash is not the pinned baseline and guards.approval.json
                 holds no record for that hash naming a real owner-queue row. Removing a
                 guard entry cannot be hidden, because removal changes the hash.
                 A record is not enough on its own. Its owner_row must name a row that
                 EXISTS in owner_decision_queue, that the owner actually answered or
                 resolved, AND whose own text (question, context, answer, resolution)
                 names the guard registry. A fabricated record naming row 1, a row still
                 pending, or an answered row about something else entirely (a redeploy, a
                 form filing) is rejected -- otherwise the same agent the guard restrains
                 could write the approval that is supposed to gate it, which is the
                 self-modification this exists to stop.

THE PIN IS THE POINT
--------------------
BOOTSTRAP_REGISTRY_SHA256 below is the registry this checker was built for. Editing
`guards.yaml` to disable or drop a guard changes the hash and turns this checker red.
The only sanctioned way through is an owner approval record, which is a deliberate,
recorded act. Do not "fix" a red checker by editing the pin: that is disabling the
guard, which is the exact behaviour this file exists to catch.

WHAT THIS IS NOT
----------------
It never executes a guard and never sends anything. A guard's own status file is its
verdict; this process only judges whether the guard is still there and still saying it
is well.

EXIT CODES, and why a guard FINDING is not a job failure
--------------------------------------------------------
Measured 2026-10-05: `/` sat at 93.8%, over disk-guard's 90% warn threshold, so disk-guard's
own status said `ok: false`, so THIS checker reported `FINDING disk failing` and exited 1.
sources/cron-failures.py then read ten rc=1 rows in a row as "a scheduled job that does not
work" -- for a job that was working correctly. rc=1 cannot tell "a finding" from "a fault in
me", and that ambiguity is what turned a healthy guard into a red row.

    0                    clean.
    3 (CONDITION_EXIT)   EVERY finding is a guard REPORTING A RED CONDITION (kind `failing`):
                         the guard ran, said its own domain is unwell, and the remedy belongs
                         to that domain -- the disk, the database -- which its own source
                         (sources/disk-space.py, sources/db-integrity.py) already raises
                         against the same status file. There is no fault here to repair.
    1                    a finding that means the GUARD SYSTEM ITSELF is broken or has been
                         tampered with -- `missing`, `disabled`, `stale`, `unapproved`,
                         `bad-entry`. These stay a hard rc=1 ON PURPOSE: turning a guard off
                         is the one thing nothing else watches for, and it is the exact
                         self-modification this file exists to catch.
    2                    the checker could not read its own inputs (an unreadable registry or
                         crontab is a finding, never a clean pass).

USAGE
    guard-registry-check.py                  # exit 3 on a guard CONDITION, 1 on a guard-system fault
    guard-registry-check.py --json           # machine-readable
    guard-registry-check.py --write-status   # also write ~/.guard-registry/status.json
    guard-registry-check.py --selftest       # prove the detector fires, on known input
    guard-registry-check.py --registry COPY --pin-sha256 <sha of COPY>
                                             # judge an alternative registry against its
                                             # own hash (used only to demonstrate a
                                             # disabled copy; the cron job never passes it)
    guard-registry-check.py --ledger-db PATH # where to verify an approval's owner_row
                                             # (default ~/personal-secretary-mvp/data/
                                             # secretary.db; only read when the registry
                                             # hash is not the pinned baseline)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except Exception:  # noqa: BLE001
    yaml = None

HOME = Path.home()
DEFAULT_REGISTRY = HOME / "bin" / "guards.yaml"
DEFAULT_APPROVAL = HOME / "bin" / "guards.approval.json"
STATE_DIR = HOME / ".guard-registry"
STATUS = STATE_DIR / "status.json"
LOG = STATE_DIR / "guard.log"
DEFAULT_LEDGER_DB = HOME / "personal-secretary-mvp" / "data" / "secretary.db"

# See "THE PIN IS THE POINT" above. Substituted at install time with the sha256 of the
# registry shipped alongside this file.
BOOTSTRAP_REGISTRY_SHA256 = "91ea76998a893eb7d232307abdfb84597d3f7abc37b9da04feecc738f65d4483"

#: This repo's word for "CONDITION, not fault" (the same 3 as CONDITION_EXIT in
#: `ai-gateway-health.py` and `supplier-delivery-watch.py`; `sources/cron-failures.py` honours
#: rc=3 for EVERY job and files no repair session for a streak of it). Used ONLY when every
#: finding is kind `failing` -- a guard that ran and reported its own domain unwell. A
#: guard-integrity finding (missing, disabled, stale, unapproved) still exits 1 and still files
#: work. Measured 2026-10-05: ten consecutive rc=1 rows from `disk` at 93.8% were filed as a
#: broken job.
CONDITION_EXIT = 3

TIMESTAMP_FIELDS = ("at", "checked_at", "time", "timestamp", "updated_at")
TIMESTAMP_FORMATS = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ")

# A guard-registry change is approved only by an owner row whose own text is ABOUT the
# guard registry. Requiring merely that the row exists and was answered is not enough:
# any answered row would then do -- a redeploy, a tax form -- and the record would exist
# while the owner never approved THIS change. Case-insensitive substrings, matched
# against the row's question, context, answer and resolution.
GUARD_REGISTRY_MARKERS = (
    "guard registry",
    "guard-registry",
    "guard_registry",
    "guards.yaml",
    "guards.approval.json",
    "guard-registry-check",
)


# --------------------------------------------------------------------------- helpers

def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bytes(path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def read_text(path) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def crontab_text(path=None):
    """Return (text, error). `crontab -l` with no jobs exits 1 and says 'no crontab for'."""
    if path:
        try:
            return read_text(path), ""
        except Exception as exc:  # noqa: BLE001
            return None, "could not read %s: %s" % (path, exc)
    try:
        p = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
    except Exception as exc:  # noqa: BLE001
        return None, "crontab -l could not run: %s" % exc
    if p.returncode == 0:
        return p.stdout or "", ""
    if "no crontab for" in (p.stderr or "").lower():
        return "", ""
    return None, "crontab -l exited %d: %s" % (p.returncode, (p.stderr or "").strip()[:200])


def active_lines(text) -> list:
    return [ln for ln in (text or "").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def parse_timestamp(obj):
    if not isinstance(obj, dict):
        return None
    for key in TIMESTAMP_FIELDS:
        value = obj.get(key)
        if not isinstance(value, str):
            continue
        for fmt in TIMESTAMP_FORMATS:
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def load_status(path):
    """Return (ok, detail, parsed). A status file is the guard's own verdict."""
    if not os.path.exists(path):
        return False, "status file does not exist: %s" % path, None
    try:
        obj = json.loads(read_text(path))
    except Exception as exc:  # noqa: BLE001
        return False, "status file is not valid json: %s" % exc, None
    if not isinstance(obj, dict):
        return False, "status file is not a json object", None
    if "ok" not in obj:
        return False, "status file has no 'ok' field", obj
    if obj.get("ok") is True:
        return True, "ok", obj
    return False, "status ok=%r" % (obj.get("ok"),), obj


# --------------------------------------------------------------------------- the check

def check_guard(guard, lines, now, status_loader, exists, is_exec):
    findings, warnings = [], []
    gid = str(guard.get("id") or "<no id>")

    if guard.get("enabled", True) is not True:
        findings.append((gid, "disabled", "registry marks enabled: false"))

    match = guard.get("cron_match")
    if not match:
        warnings.append((gid, "no-cron-match", "no cron_match; presence cannot be checked"))
    elif not [ln for ln in lines if match in ln]:
        findings.append((gid, "missing", "no active crontab line contains %r" % match))

    command = guard.get("command")
    if not command:
        findings.append((gid, "disabled", "registry entry names no command"))
    elif not exists(command):
        findings.append((gid, "disabled", "command does not exist: %s" % command))
    elif not is_exec(command):
        findings.append((gid, "disabled", "command is not executable: %s" % command))

    status_file = guard.get("status_file")
    if not status_file:
        warnings.append((gid, "no-status", "no status_file; health cannot be judged"))
    else:
        ok, detail, obj = status_loader(status_file)
        if not ok:
            findings.append((gid, "failing", detail))
        else:
            ts = parse_timestamp(obj)
            max_age = guard.get("max_age_seconds")
            if ts is not None and isinstance(max_age, (int, float)) and max_age > 0:
                age = (now - ts).total_seconds()
                if age > max_age:
                    findings.append((gid, "stale",
                                     "status is %.0fs old (max %ss)" % (age, max_age)))
    return findings, warnings


def registry_named_in(texts):
    """Does any of these owner-row text fields name the guard registry?

    Approving a guard-registry change means the owner was asked about the guard
    registry. An answered row about a redeploy or a tax form is not that approval,
    however real the row is. Returns (ok, marker).
    """
    haystack = " ".join(t for t in texts if isinstance(t, str)).lower()
    for marker in GUARD_REGISTRY_MARKERS:
        if marker in haystack:
            return True, marker
    return False, ""


def verify_owner_row(row, db_path=None):
    """Return (ok, detail) for a claimed owner approval.

    A registry change is approved only when the record's owner_row names a row that
    EXISTS in owner_decision_queue, that the owner actually answered or resolved, and
    whose own text names the guard registry. Anything else -- a fabricated row number, a
    row still pending, an answered row about something unrelated, an unreadable ledger --
    is NOT an approval. This is the difference between "an approval record exists" and
    "the owner approved it": without the second half, the agent the guard exists to
    restrain can write the first itself and the checker passes it.
    """
    if isinstance(row, bool) or not isinstance(row, int) or row <= 0:
        return False, "owner_row %r is not a positive integer" % (row,)
    path = str(db_path or DEFAULT_LEDGER_DB)
    if not os.path.exists(path):
        return False, "ledger db is not readable at %s (cannot verify owner_row %r)" % (path, row)
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
    except Exception as exc:  # noqa: BLE001
        return False, "cannot open ledger db %s: %s" % (path, exc)
    try:
        cur = con.execute(
            "SELECT status, answered_at, answer, resolved_at, resolution, question, context "
            "FROM owner_decision_queue WHERE id = ?", (row,))
        found = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        return False, "cannot query owner_decision_queue: %s" % exc
    finally:
        con.close()
    if found is None:
        return False, "owner_row %r does not exist in owner_decision_queue" % (row,)
    status, answered_at, answer, resolved_at, resolution, question, context = (
        list(found) + [None] * 7)[:7]
    if status not in ("answered", "resolved"):
        return False, ("owner_row %r is %r, not answered or resolved by the owner"
                       % (row, status))
    if not any((answer, resolution, answered_at, resolved_at)):
        return False, "owner_row %r records no answer or resolution" % (row,)
    named, _marker = registry_named_in((question, context, answer, resolution))
    if not named:
        return False, ("owner_row %r is %s, but its text does not name the guard "
                       "registry, so it cannot approve a change to it" % (row, status))
    return True, "owner row %r is %s and names the guard registry" % (row, status)


def check_approval(reg_sha, approval_path, pin, exists, read_bytes_fn,
                   owner_row_verifier=verify_owner_row):
    if pin and reg_sha == pin:
        return [], [("<registry>", "bootstrap", "registry hash is the pinned baseline")]
    if not exists(approval_path):
        return [("<registry>", "unapproved",
                 "registry changed (sha %s) and no approval record exists" % reg_sha[:12])], []
    try:
        record = json.loads(read_bytes_fn(approval_path).decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        return [("<registry>", "unapproved", "approval record is not valid json: %s" % exc)], []
    if not isinstance(record, dict):
        return [("<registry>", "unapproved", "approval record is not a json object")], []
    if record.get("registry_sha256") != reg_sha:
        return [("<registry>", "unapproved",
                 "approval record names sha %s, registry is %s"
                 % (str(record.get("registry_sha256"))[:12], reg_sha[:12]))], []
    row = record.get("owner_row")
    if isinstance(row, bool) or not isinstance(row, int) or row <= 0:
        return [("<registry>", "unapproved",
                 "approval record for this hash has no valid owner_row "
                 "(changing a guard needs an owner approval record)")], []
    ok, detail = owner_row_verifier(row)
    if not ok:
        return [("<registry>", "unapproved",
                 "approval record for this hash is not backed by the owner queue: %s"
                 % detail)], []
    return [], [("<registry>", "owner-approved",
                 "approved by %r for owner row %r (%s)"
                 % (record.get("approved_by"), row, detail))]


def evaluate(reg_bytes, crontab_lines, now, status_loader, exists, is_exec,
             approval_path, pin, read_bytes_fn=None, owner_row_verifier=verify_owner_row):
    """Pure judgement over injected inputs so --selftest can prove it on known data."""
    findings, warnings, checked = [], [], 0
    if read_bytes_fn is None:
        read_bytes_fn = read_bytes
    if yaml is None:
        return None, None, "PyYAML is not importable"
    try:
        registry = yaml.safe_load(reg_bytes.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, None, "registry is not valid yaml: %s" % exc
    if not isinstance(registry, dict) or not isinstance(registry.get("guards"), list):
        return None, None, "registry has no 'guards' list"

    reg_sha = sha256_bytes(reg_bytes)
    af, aw = check_approval(reg_sha, approval_path, pin, exists, read_bytes_fn,
                            owner_row_verifier)
    findings += af
    warnings += aw

    for guard in registry["guards"]:
        if not isinstance(guard, dict):
            findings.append(("<registry>", "bad-entry", "a guards entry is not a mapping"))
            continue
        checked += 1
        gf, gw = check_guard(guard, crontab_lines, now, status_loader, exists, is_exec)
        findings += gf
        warnings += gw
    return findings, warnings, None


# --------------------------------------------------------------------------- reporting

def render(findings, warnings, checked, reg_sha, pin, quiet=False):
    lines_out = []
    if not quiet:
        lines_out.append("guard-registry-check: %d guard(s), registry sha %s%s"
                         % (checked, reg_sha[:12],
                            "" if reg_sha == pin else " (NOT the pinned baseline)"))
        for gid, kind, detail in findings:
            lines_out.append("  FINDING  %-12s %-12s %s" % (gid, kind, detail))
        for gid, kind, detail in warnings:
            lines_out.append("  warn     %-12s %-12s %s" % (gid, kind, detail))
        lines_out.append("guard-registry-check: %s" % ("clean" if not findings else "FAIL"))
    return "\n".join(lines_out)


def write_status(findings, warnings, checked, reg_sha, pin):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": not findings,
        "at": iso_now(),
        "checked": checked,
        "findings": [{"guard": g, "kind": k, "detail": d} for g, k, d in findings],
        "warnings": [{"guard": g, "kind": k, "detail": d} for g, k, d in warnings],
        "registry_sha256": reg_sha,
        "pinned_sha256": pin,
    }
    tmp = STATUS.with_name(STATUS.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATUS)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write("%s\tok=%s\tchecked=%d\tfindings=%d\n"
                     % (payload["at"], payload["ok"], checked, len(findings)))
    except OSError:
        pass
    return payload


# --------------------------------------------------------------------------- selftest

def selftest() -> int:
    import tempfile

    if yaml is None:
        print("selftest: PyYAML is not importable", file=sys.stderr)
        return 2

    good_registry = (
        "version: 1\n"
        "guards:\n"
        "  - id: alpha\n"
        "    command: /bin/true\n"
        "    cron_match: \"cron-wrap.sh alpha\"\n"
        "    status_file: /tmp/alpha.json\n"
        "    max_age_seconds: 3600\n"
        "  - id: beta\n"
        "    command: /bin/true\n"
        "    cron_match: \"cron-wrap.sh beta\"\n"
        "    status_file: /tmp/beta.json\n"
    )
    crontab = ("*/5 * * * * /home/zabz/bin/cron-wrap.sh alpha X\n"
               "*/5 * * * * /home/zabz/bin/cron-wrap.sh beta Y\n")
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    statuses = {
        "/tmp/alpha.json": json.dumps({"ok": True, "at": "2026-10-01T11:59:00Z"}),
        "/tmp/beta.json": json.dumps({"ok": True, "at": "2026-10-01T11:59:00Z"}),
    }

    def status_loader(path):
        if path not in statuses:
            return False, "status file does not exist: %s" % path, None
        obj = json.loads(statuses[path])
        if obj.get("ok") is True:
            return True, "ok", obj
        return False, "status ok=%r" % (obj.get("ok"),), obj

    known_paths = {"/bin/true"}

    # The selftest must not touch the real ledger, so this mirrors verify_owner_row's
    # verdict on a known queue. 227 is the real owner row that approved installing this
    # watchdog, so its text names the guard registry. 182 was answered about an NJ DOL
    # form and 77 is still pending, so neither can approve a registry change; the rest
    # are absent. The text test runs through registry_named_in, the same pure matcher
    # verify_owner_row uses.
    QUEUE = {
        227: ("resolved", "Should I install the guard-registry watchdog as a cron job?"),
        182: ("answered", "File the NJ DOL Form BC28 separation answer for Yisroel Weinberg"),
        77: ("pending", "Google still tells customers that Lakewood Phone and Tech opens at 10:30"),
    }

    def fake_owner_row(row):
        entry = QUEUE.get(row)
        if entry is None:
            return False, "owner_row %r does not exist in owner_decision_queue" % (row,)
        status, text = entry
        if status not in ("answered", "resolved"):
            return False, ("owner_row %r is %r, not answered or resolved by the owner"
                           % (row, status))
        named, _marker = registry_named_in((text,))
        if not named:
            return False, ("owner_row %r is %s, but its text does not name the guard "
                           "registry, so it cannot approve a change to it" % (row, status))
        return True, "owner row %r is %s and names the guard registry" % (row, status)

    def exists(path):
        return path in known_paths

    def is_exec(path):
        return path == "/bin/true"

    sha = sha256_bytes(good_registry.encode("utf-8"))
    tmpdir = tempfile.mkdtemp(prefix="guard-registry-selftest-")
    approval = os.path.join(tmpdir, "approval.json")
    with open(approval, "w", encoding="utf-8") as fh:
        fh.write('{"registry_sha256": "%s", "approved_by": "owner", "owner_row": 227}' % sha)
    known_paths.add(approval)

    failures = []

    def run(reg_text, lines, pin, use_approval=True, statuses_override=None,
            verifier=fake_owner_row):
        nonlocal statuses
        saved = statuses
        if statuses_override is not None:
            statuses = statuses_override
        try:
            f, w, err = evaluate(
                reg_text.encode("utf-8"), lines, now, status_loader, exists, is_exec,
                approval if use_approval else os.path.join(tmpdir, "absent.json"), pin,
                None, verifier)
        finally:
            statuses = saved
        return f, w, err

    f, w, err = run(good_registry, active_lines(crontab), sha)
    if err or f:
        failures.append("clean input should have no findings: %r %r" % (err, f))

    disabled = good_registry.replace("  - id: beta\n", "  - id: beta\n    enabled: false\n")
    f, w, err = run(disabled, active_lines(crontab), sha256_bytes(disabled.encode("utf-8")))
    if not any(k == "disabled" for _, k, _ in f or []):
        failures.append("disabled guard was not detected: %r" % (f,))

    f, w, err = run(good_registry, active_lines(crontab.replace(
        "*/5 * * * * /home/zabz/bin/cron-wrap.sh beta Y\n", "")), sha)
    if not any(k == "missing" for _, k, _ in f or []):
        failures.append("missing crontab line was not detected: %r" % (f,))

    f, w, err = run(good_registry, active_lines(crontab), sha,
                    statuses_override={"/tmp/alpha.json": json.dumps({"ok": True}),
                                       "/tmp/beta.json": json.dumps({"ok": False})})
    if not any(k == "failing" for _, k, _ in f or []):
        failures.append("failing guard was not detected: %r" % (f,))

    stale = {"/tmp/alpha.json": json.dumps({"ok": True, "at": "2026-09-01T00:00:00Z"}),
             "/tmp/beta.json": json.dumps({"ok": True})}
    f, w, err = run(good_registry, active_lines(crontab), sha, statuses_override=stale)
    if not any(k == "stale" for _, k, _ in f or []):
        failures.append("stale status was not detected: %r" % (f,))

    f, w, err = run(good_registry, active_lines(crontab), "0" * 64, use_approval=False)
    if not any(k == "unapproved" for _, k, _ in f or []):
        failures.append("unapproved change was not detected: %r" % (f,))

    f, w, err = evaluate(good_registry.encode("utf-8"), active_lines(crontab), now,
                         status_loader, exists, is_exec, approval, "0" * 64,
                         None, fake_owner_row)
    if any(k == "unapproved" for _, k, _ in f or []):
        failures.append("a matching owner approval was rejected: %r" % (f,))

    mismatch = os.path.join(tmpdir, "mismatch.json")
    with open(mismatch, "w", encoding="utf-8") as fh:
        fh.write('{"registry_sha256": "%s", "approved_by": "owner", "owner_row": 227}'
                 % ("f" * 64))
    known_paths.add(mismatch)
    f, w, err = evaluate(good_registry.encode("utf-8"), active_lines(crontab), now,
                         status_loader, exists, is_exec, mismatch, "0" * 64,
                         None, fake_owner_row)
    if not any(k == "unapproved" for _, k, _ in f or []):
        failures.append("approval record with a mismatched hash was accepted: %r" % (f,))

    # An approval record is not an approval. It must be backed by a real owner-queue row
    # the owner answered or resolved, AND that row must be about the guard registry;
    # otherwise the agent the guard restrains can forge the record that is supposed to
    # gate it, or cite an unrelated answered row (182, an NJ DOL form) as its approval.
    for label, row in (("nonexistent", 999999), ("still-pending", 77),
                       ("string", "182"), ("zero", 0),
                       ("unrelated-answered", 182)):
        forged = os.path.join(tmpdir, "forged-%s.json" % label)
        with open(forged, "w", encoding="utf-8") as fh:
            fh.write('{"registry_sha256": "%s", "approved_by": "self", "owner_row": %s}'
                     % (sha, json.dumps(row)))
        known_paths.add(forged)
        f, w, err = evaluate(good_registry.encode("utf-8"), active_lines(crontab), now,
                             status_loader, exists, is_exec, forged, "0" * 64,
                             None, fake_owner_row)
        if not any(k == "unapproved" for _, k, _ in f or []):
            failures.append("forged approval (%s owner_row) was accepted: %r" % (label, f))

    f, w, err = run("not: [valid", active_lines(crontab), sha)
    if err is None:
        failures.append("invalid yaml should be an error")

    # CONDITION vs FAULT (the 2026-10-05 fix): a guard reporting a red condition grades
    # CONDITION_EXIT; anything meaning the guard system itself is broken stays rc=1, even
    # when it sits beside a condition.
    if verdict_for([]) != 0:
        failures.append("no findings should grade 0")
    if verdict_for([("disk", "failing", "status ok=False")]) != CONDITION_EXIT:
        failures.append("a guard reporting a red condition should grade CONDITION_EXIT")
    if verdict_for([("disk", "failing", "status ok=False"),
                    ("cron-targets", "missing", "no active crontab line")]) != 1:
        failures.append("a guard-system fault must stay rc=1 beside a condition")
    if verdict_for([("disk", "disabled", "command does not exist")]) != 1:
        failures.append("a disabled guard must stay rc=1")
    if verdict_for([("<registry>", "unapproved", "registry changed")]) != 1:
        failures.append("an unapproved registry must stay rc=1")

    if failures:
        for line in failures:
            print("selftest: FAIL: %s" % line, file=sys.stderr)
        return 1
    print("selftest: ok (clean=0 findings; detected disabled, missing, failing, stale, "
          "unapproved, forged approval, unrelated approval row; condition=3, "
          "guard-system fault=1)")
    return 0


# --------------------------------------------------------------------------- main

def verdict_for(findings) -> int:
    """0 clean; CONDITION_EXIT when every finding is a guard reporting a red condition;
    1 when any finding means the guard system itself is broken or was tampered with.

    The distinction is the whole point. `failing` is disk-guard saying "/ is 93.8% full",
    which sources/disk-space.py already escalates against the same status file. `missing` or
    `disabled` is a guard that has been turned off -- the one thing nothing else watches for,
    and the reason this checker exists. Grading those together is what made a working guard
    read as a dead cron job.
    """
    if not findings:
        return 0
    if all(kind == "failing" for _, kind, _ in findings):
        # The cron line sends this job's stderr to ~/.guard-registry/cron.log (it ends in
        # `2>&1`), so this line names the condition beside the FAIL block there. runs.tsv's
        # cause column stays EMPTY because of that redirect -- which is exactly why rc has to
        # carry the meaning here: an empty column beside a non-zero rc is what made 10 healthy
        # runs read as a job that does not work (2026-10-05).
        sys.stderr.write(
            "guard-registry-check: rc=%d CONDITION, not fault - %s\n" % (
                CONDITION_EXIT,
                "; ".join("%s %s" % (g, d) for g, k, d in findings if k == "failing")[:280],
            ))
        return CONDITION_EXIT
    sys.stderr.write(
        "guard-registry-check: rc=1 GUARD-SYSTEM FAULT - %s\n" % (
            "; ".join("%s %s (%s)" % (g, k, d) for g, k, d in findings)[:280],
        ))
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="verify the guards that matter, from a different process")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--approval", default=str(DEFAULT_APPROVAL))
    parser.add_argument("--ledger-db", default=str(DEFAULT_LEDGER_DB),
                        help="secretary.db holding owner_decision_queue; read (only) to "
                             "verify that an approval record's owner_row is a real row "
                             "the owner answered or resolved AND whose text names "
                             "the guard registry")
    parser.add_argument("--crontab-file", default=None,
                        help="read the crontab from a file instead of `crontab -l` (tests only)")
    parser.add_argument("--pin-sha256", default=None,
                        help="treat this hash as the pinned baseline (tests only; cron never passes it)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    if not os.path.exists(args.registry):
        print("guard-registry-check: registry does not exist: %s" % args.registry, file=sys.stderr)
        return 2
    try:
        reg_bytes = read_bytes(args.registry)
    except Exception as exc:  # noqa: BLE001
        print("guard-registry-check: cannot read registry: %s" % exc, file=sys.stderr)
        return 2

    text, err = crontab_text(args.crontab_file)
    if text is None:
        print("guard-registry-check: cannot read the crontab: %s" % err, file=sys.stderr)
        return 2

    pin = args.pin_sha256 or BOOTSTRAP_REGISTRY_SHA256
    owner_row_verifier = (lambda row: verify_owner_row(row, args.ledger_db))
    findings, warnings, err = evaluate(
        reg_bytes, active_lines(text), datetime.now(timezone.utc), load_status,
        os.path.exists, lambda p: os.access(p, os.X_OK), args.approval, pin,
        None, owner_row_verifier)
    if err is not None:
        print("guard-registry-check: %s" % err, file=sys.stderr)
        return 2

    reg_sha = sha256_bytes(reg_bytes)
    try:
        parsed = yaml.safe_load(reg_bytes.decode("utf-8"))
        checked = len([g for g in parsed.get("guards", []) if isinstance(g, dict)]) \
            if isinstance(parsed, dict) else 0
    except Exception:  # noqa: BLE001
        checked = 0
    if args.write_status:
        write_status(findings, warnings, checked, reg_sha, pin)

    if args.json:
        print(json.dumps({
            "ok": not findings,
            "registry_sha256": reg_sha,
            "pinned_sha256": pin,
            "findings": [{"guard": g, "kind": k, "detail": d} for g, k, d in findings],
            "warnings": [{"guard": g, "kind": k, "detail": d} for g, k, d in warnings],
            "at": iso_now(),
        }, indent=2))
    else:
        out = render(findings, warnings, checked, reg_sha, pin, quiet=args.quiet)
        if out:
            print(out)
    return verdict_for(findings)


if __name__ == "__main__":
    raise SystemExit(main())
