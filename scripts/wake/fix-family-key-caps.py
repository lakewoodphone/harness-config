#!/usr/bin/env python3
"""Ledger item 182: make guard 1 (dedup), guard 2 (cooldown) and guard 9 (the
attempt ceiling) evaluate a PROJECT subject against its FAMILY key
`project:<id>:<day>` (the subject with a trailing `#<n>` stripped), so the
`#<n>` day-suffix project-keepalive appends cannot step around them. A
non-project subject is unchanged.

Idempotent: refuses to run twice (the marker `_PROJECT_BASE_RE` must be absent).
Writes a timestamped backup next to the target before touching it.
"""
import pathlib
import shutil
import sys
import time
from datetime import datetime, timezone

TARGET = pathlib.Path("/root/bin/wake.py")

DOC_PARA = '''
THE PROJECT FAMILY. project-keepalive must be allowed more than one flag a day
(`max_flags_per_day`), and it makes each extra flag unique with a `#<n>` suffix
(`project:<id>:<day>`, then `#2`, `#3`, ...), because `subject` is UNIQUE.
Evaluated on the exact string, guard 1, guard 2 and guard 9 can NEVER bind on
the 2nd..Nth flag of a day: every one is a brand-new row with attempts=0 and no
release to cool down from. They are therefore evaluated on the FAMILY
`project:<id>:<day>` for PROJECT subjects only - one live row per family, the
family's own filing/release clock for the cooldown, and the family's attempt
ledger. A non-project subject has no family and is byte-for-byte unchanged.
MEASURED 2026-10-14 as the defect this fixes: chumash
`project:chumash:20261013#10` released 03:39:03Z and `#11` at 03:54:04Z, 15
minutes apart against a 1800 s cooldown.
'''

FAMILY_BLOCK = '''
# --------------------------------------------------------------------------- #
# THE PROJECT SUBJECT FAMILY - one project, one day, one throttle
# --------------------------------------------------------------------------- #
# WHY THIS EXISTS. project-keepalive deliberately makes each extra flag of a day
# a UNIQUE subject by appending `#<n>` (see its `subject = f"project:{pid}:{today}"`
# plus `#(used + 1)`), because `subject` is UNIQUE and a project is allowed more
# than one flag a day. The cost: guard 1 (dedup), guard 2 (cooldown) and guard 9
# (the attempt ceiling) were all evaluated on the EXACT subject string, so for
# the 2nd..Nth flag of a day no per-subject guard could ever bind - each family
# member was a brand-new row with attempts=0 and no release to cool down from.
# MEASURED 2026-10-14: chumash `project:chumash:20261013#10` released 03:39:03Z
# and `#11` at 03:54:04Z - 15 minutes apart against a 1800 s cooldown - and
# project-keepalive's per-project cooldown is consulted when it FILES, never by
# the store when it RELEASES. The guards therefore key on the FAMILY for project
# subjects only. A non-project subject has no family: `family_key` returns it
# unchanged and every branch reduces to the exact-subject behaviour it had.
_PROJECT_BASE_RE = re.compile(r"^project:[^:\\s]+:\\d{8}$")
_PROJECT_MEMBER_RE = re.compile(r"^(project:[^:\\s]+:\\d{8})#\\d+$")


def project_family(subject: str) -> str | None:
    """`project:<id>:<utc-day>` for the base subject and for any `#<n>` member,
    else None. This is the trap the day-suffix must not escape."""
    s = (subject or "").strip()
    m = _PROJECT_MEMBER_RE.match(s)
    if m:
        return m.group(1)
    return s if _PROJECT_BASE_RE.match(s) else None


def family_key(subject: str) -> str:
    """The throttle key for a subject: the project family when there is one,
    otherwise the subject unchanged."""
    s = (subject or "").strip()
    return project_family(s) or s


def family_rows_in(conn: sqlite3.Connection, family: str, project: bool) -> list[dict]:
    """Every wake row that shares `family`'s throttle key, oldest first. A
    non-project subject has a family of exactly one: itself."""
    if not project:
        row = row_dict(conn.execute("SELECT * FROM wake WHERE subject=?", (family,)).fetchone())
        return [row] if row is not None else []
    rows = conn.execute(
        "SELECT * FROM wake WHERE subject=? OR subject LIKE ? ORDER BY id",
        (family, family + "#%"),
    ).fetchall()
    out: list[dict] = []
    for raw in rows:
        r = row_dict(raw)
        if r is not None and project_family(str(r["subject"] or "")) == family:
            out.append(r)
    return out


def family_activity(row: dict) -> datetime | None:
    """The family's clock. A FILING counts as well as a release, because the
    whole point of the family key is that the project's own `cooldown_seconds`
    binds between two flags of the same day - and a row sitting `new` (filed but
    not yet claimed) is exactly the state the `#<n>` suffix used to step around."""
    stamps = [_last_release(row), parse_dt(row.get("created_at"))]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def family_last_activity(rows: list[dict], project: bool) -> datetime | None:
    """The newest activity in the family. A non-project family keeps the
    release-only clock it always had (byte-for-byte unchanged behaviour)."""
    stamps = []
    for row in rows:
        d = family_activity(row) if project else _last_release(row)
        if d is not None:
            stamps.append(d)
    return max(stamps) if stamps else None
'''

NEW_FILE_WAKE = r'''def file_wake(conn: sqlite3.Connection, *, subject: str, prompt: str, context: str = "",
              kind: str = "task", source: str = "", priority: str = "normal",
              cooldown_seconds: int | None = None,
              max_attempts: int | None = None,
              allow_from_session: bool = False,
              detail: dict | None = None) -> tuple[str, int | None]:
    """File, dedupe, suppress or cap. Returns (result, row_id). Never raises on
    a guard decision: every decision is one of the four frozen words.

    GUARD 1, GUARD 2 AND GUARD 9 KEY ON THE PROJECT FAMILY (see `family_key`),
    not on the exact subject, so a project-keepalive `#<n>` day-suffix cannot
    step around the dedup, the cooldown or the attempt ceiling. A non-project
    subject has no family and every branch below reduces to the exact-subject
    behaviour it had before. `detail`, when the caller passes a dict, is filled
    with the family a suppression happened inside of - the frozen stdout word is
    unchanged; the name is reported to the caller for stderr/--json."""
    # Guard 11, first and unconditional: a woken session must never raise a flag,
    # or one session becomes two becomes a fleet. This is in the store layer on
    # purpose so every caller inherits it.
    if in_session() and not allow_from_session:
        return "suppressed:inside-a-woken-session", None

    subject = (subject or "").strip()
    prompt = prompt or ""
    if not subject or not prompt:
        return "suppressed:usage", None

    kind = kind or "task"
    # A responder-filed await is its own source bucket, so the per-source cap
    # means what it says without the caller having to pass a source.
    source = source or (kind if kind and kind != "task" else "manual")
    priority = priority if priority in ("high", "normal", "low") else "normal"
    cooldown = _env_int("WAKE_COOLDOWN_SEC", 1800) if cooldown_seconds is None else int(cooldown_seconds)
    max_att = _env_int("WAKE_MAX_ATTEMPTS", 2) if max_attempts is None else int(max_attempts)
    if max_att < 1:
        max_att = 1

    if paused():
        return "suppressed:paused", None

    stamp = now()
    existing = row_dict(conn.execute("SELECT * FROM wake WHERE subject=?", (subject,)).fetchone())

    # THE FAMILY. For a project subject the guards below are evaluated against
    # `project:<id>:<day>`, so the `#<n>` day-suffix cannot restart them. For any
    # other subject `family == subject` and `family_rows` is the exact row only.
    family = family_key(subject)
    project = project_family(subject) is not None
    family_rows = family_rows_in(conn, family, project)
    # The governing member is the newest row of the family: its attempt ledger
    # and unverified count are the family's, so a fresh `#<n>` cannot reset them.
    governing = family_rows[-1] if family_rows else existing

    # guard 1 - dedup: one live row per issue, per FAMILY. A `#2` filed while the
    # base subject (or any other member) is live is a no-op, not a second session.
    for row in family_rows:
        if row["state"] in LIVE_STATES:
            return "deduped", row["id"]

    if governing is None:
        # No row in the family has ever existed: a plain new subject.
        cur = conn.execute(
            """INSERT INTO wake(subject,kind,source,prompt,context,priority,created_at,
                                not_before,state,attempts,max_attempts)
               VALUES(?,?,?,?,?,?,?,NULL,'new',0,?)""",
            (subject, kind, source, prompt, context or "", priority, stamp, max_att),
        )
        row_id = int(cur.lastrowid)
        result = "filed"
    else:
        # guard 9 - the FAMILY's attempt ceiling: a family that has failed
        # `max_att` times is never retried automatically. `done`/`expired` reset
        # the ledger (a family that completed is not the family that kept failing).
        carried = int(governing["attempts"] or 0)
        # THE UNVERIFIED BOUND. An `unverified` outcome refunds its attempt (that
        # is the point of the third outcome), so the attempt ceiling cannot bound
        # it; the row's own unverified count can. `done`/`expired` reset the
        # count: a subject that completed is not the subject that kept being
        # unreadable. WAKE_MAX_UNVERIFIED=0 disables the bound.
        unverified = int(governing.get("unverified") or 0)
        if governing["state"] not in ("done", "expired"):
            if carried >= max_att:
                return "suppressed:attempts", governing["id"]
            unver_cap = _env_int("WAKE_MAX_UNVERIFIED", DEFAULT_MAX_UNVERIFIED)
            if unver_cap > 0 and unverified >= unver_cap:
                return "suppressed:unverified", governing["id"]
        else:
            carried = 0                      # success or abandonment is not a failure
            unverified = 0

        # guard 2 - cooldown after a release, keyed on the FAMILY's newest
        # activity so `#<n>` cannot step around the project's own cooldown.
        last = family_last_activity(family_rows, project)
        if cooldown > 0 and last is not None and (now_dt() - last) < timedelta(seconds=cooldown):
            until = (now_dt() + timedelta(seconds=cooldown)).isoformat(timespec="seconds")
            if existing is not None:
                conn.execute(
                    """UPDATE wake SET kind=?, source=?, prompt=?, context=?, priority=?,
                           created_at=?, not_before=?, state='new', attempts=?, max_attempts=?,
                           unverified=?, claimed_by=NULL, claimed_at=NULL, lease_until=NULL,
                           finished_at=NULL, outcome=NULL, cost_usd=NULL
                       WHERE id=?""",
                    (kind, source, prompt, context or "", priority, stamp, until, carried,
                     max_att, unverified, existing["id"]),
                )
            if detail is not None:
                age = int((now_dt() - last).total_seconds())
                detail.update({
                    "guard": "cooldown",
                    "family": family,
                    "family_row": int(governing["id"]),
                    "last_activity": last.isoformat(timespec="seconds"),
                    "note": (f"suppressed:cooldown inside the project family {family}: "
                             f"wake #{governing['id']} was active "
                             f"{last.isoformat(timespec='seconds')} ({age}s of {cooldown}s ago)"),
                })
            return "suppressed:cooldown", int(existing["id"] if existing is not None else governing["id"])

        if existing is not None:
            # A terminal row for the EXACT subject: revive it (unchanged path).
            # `subject` is UNIQUE, so this is the only way a re-flag can mean
            # anything for that subject.
            conn.execute(
                """UPDATE wake SET kind=?, source=?, prompt=?, context=?, priority=?,
                       created_at=?, not_before=NULL, state='new', attempts=?, max_attempts=?,
                       unverified=?, claimed_by=NULL, claimed_at=NULL, lease_until=NULL,
                       finished_at=NULL, outcome=NULL, cost_usd=NULL
                   WHERE id=?""",
                (kind, source, prompt, context or "", priority, stamp, carried, max_att,
                 unverified, existing["id"]),
            )
            row_id = existing["id"]
        else:
            # A NEW member of the family. It CARRIES the family's attempt ledger,
            # so `max_flags_per_day` cannot multiply the attempt ceiling.
            cur = conn.execute(
                """INSERT INTO wake(subject,kind,source,prompt,context,priority,created_at,
                                    not_before,state,attempts,max_attempts,unverified)
                   VALUES(?,?,?,?,?,?,?,NULL,'new',?,?,?)""",
                (subject, kind, source, prompt, context or "", priority, stamp,
                 carried, max_att, unverified),
            )
            row_id = int(cur.lastrowid)
        result = "filed"

    # guards 3 and 10 reported at file time: the row is filed either way (the
    # contract says an over-cap row stays `new`), but the caller is told.
    if result == "filed" and release_block(conn) in ("daily-cap", "cost-cap"):
        result = "capped"
    return result, row_id
'''


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "_PROJECT_BASE_RE" in src:
        print("already-patched")
        return 0
    assert "\nimport os\n" in src
    assert "\nimport re\n" not in src
    assert "ENVIRONMENT (all read AT CALL TIME" in src
    old_last_release = (
        "def _last_release(row: dict) -> datetime | None:\n"
        "    stamps = [parse_dt(row.get(\"claimed_at\")), parse_dt(row.get(\"finished_at\"))]\n"
        "    stamps = [s for s in stamps if s is not None]\n"
        "    return max(stamps) if stamps else None\n"
    )
    assert src.count(old_last_release) == 1, "the _last_release anchor is not unique"
    assert src.count("def file_wake(") == 1
    assert src.count("def _one_line(") == 1
    old_cmd = (
        "def cmd_flag(args) -> int:\n"
        "    allow = bool(getattr(args, \"allow_from_session\", False))\n"
        "    try:\n"
    )
    assert src.count(old_cmd) == 1, "the cmd_flag anchor is not unique"
    old_tail = (
        "    if getattr(args, \"json\", False):\n"
        "        sys.stdout.write(json.dumps({\"ok\": ok, \"result\": result, \"id\": row_id}) + \"\\n\")\n"
        "    else:\n"
        "        sys.stdout.write(_one_line(result) + \"\\n\")\n"
        "    return 0\n"
    )
    assert src.count(old_tail) == 1, "the cmd_flag tail anchor is not unique"

    out = src.replace("\nimport os\n", "\nimport os\nimport re\n", 1)
    out = out.replace("ENVIRONMENT (all read AT CALL TIME",
                      DOC_PARA.lstrip("\n") + "\nENVIRONMENT (all read AT CALL TIME", 1)
    out = out.replace(old_last_release, old_last_release + FAMILY_BLOCK, 1)

    start = out.index("def file_wake(")
    end = out.index("def _one_line(")
    out = out[:start] + NEW_FILE_WAKE + "\n\n" + out[end:]

    out = out.replace(old_cmd,
                      "def cmd_flag(args) -> int:\n"
                      "    allow = bool(getattr(args, \"allow_from_session\", False))\n"
                      "    detail: dict = {}\n"
                      "    try:\n", 1)
    out = out.replace("                allow_from_session=allow,\n            )\n        ok = True",
                      "                allow_from_session=allow,\n"
                      "                detail=detail,\n"
                      "            )\n        ok = True", 1)
    out = out.replace(old_tail,
                      "    # A family-cooldown suppression has to NAME the family release it\n"
                      "    # is inside of, or the caller sees only `suppressed:cooldown` and\n"
                      "    # cannot tell which flag of the day it collided with. stdout keeps\n"
                      "    # the frozen word; the name goes to stderr and into --json.\n"
                      "    if detail.get(\"note\"):\n"
                      "        print(f\"wake: {detail['note']}\", file=sys.stderr)\n"
                      "    payload = {\"ok\": ok, \"result\": result, \"id\": row_id}\n"
                      "    if detail:\n"
                      "        payload[\"detail\"] = detail\n"
                      "    if getattr(args, \"json\", False):\n"
                      "        sys.stdout.write(json.dumps(payload) + \"\\n\")\n"
                      "    else:\n"
                      "        sys.stdout.write(_one_line(result) + \"\\n\")\n"
                      "    return 0\n", 1)

    # syntax gate before anything is written
    compile(out, str(TARGET), "exec")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = TARGET.with_name(TARGET.name + f".bak-item182-{ts}")
    shutil.copy2(TARGET, backup)
    tmp = TARGET.with_suffix(".py.item182-new")
    tmp.write_text(out, encoding="utf-8")
    tmp.replace(TARGET)
    print(f"patched {TARGET} (backup {backup.name}, {len(src)} -> {len(out)} bytes)")


if __name__ == "__main__":
    sys.exit(main())
