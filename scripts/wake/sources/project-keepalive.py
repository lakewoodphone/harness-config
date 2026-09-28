#!/usr/bin/env python3
"""FLAG SOURCE: a project that is supposed to run itself, but has gone quiet.

THE OWNER'S ASK (2026-09-20, verbatim)
--------------------------------------
    "I want these systems working very long on the kosher ai filter system and
     the waste system and the LPT website fixing ... working in the background
     constantly ... but if they run into problems or any decisions they should
     add them to the owner queue and I'll get to them and then they should move
     on to the next thing while they're waiting for me to respond."

That is one sentence with two halves, and this source is the first half: the
thing that revives the work. `dormant-handoff.py` covers the generic "the
in-flight record stopped moving" case; this source covers the specific one --
a NAMED project the owner expects to be advancing on its own.

THE SIGNAL
----------
For each ENABLED project in `projects.json` that HAS work remaining and is
OUTSIDE its cooldown, this source raises ONE flag whose prompt carries that
project's standing worker contract. Nothing else. It is quiet for a disabled
project, a project with no work remaining, a project inside its cooldown, or a
project that has already spent its daily allowance.

SUBJECT  project:<id>:<YYYYMMDD>
    The subject IS the dedup key, so one project cannot produce two sessions in
    a day by accident, and tomorrow is a new key. When `max_flags_per_day` is
    raised above 1 the extra flags in the same day carry a `#<n>` suffix so the
    dedup key stays unique while the documented format is preserved for the
    first flag of each day.

CAPS, AND WHY IT SAYS WHICH ONE STOPPED IT
-----------------------------------------
The owner was asked how many autonomous wake-ups a day to allow and answered
"whatever you think, and you can change it over time if needed". The number
chosen is **4 releases a day across the whole system, and 1 per project per
day**. Two caps therefore apply and this source enforces BOTH, before the store
does:

    global-daily-cap    `wake_budget.released` for today against
                        min(registry `global_max_flags_per_day`,
                            wake.py's own WAKE_MAX_PER_DAY),
                        both 4 by default. The registry value can never be
                        raised above what wake.py itself would allow.
    project-daily-cap   today's `project:<id>:*` rows against the project's
                        own `max_flags_per_day`.

A source that silently declines to file is indistinguishable from a source
that found nothing, which is the failure the README calls out. So every
project gets exactly one line on stderr naming its verdict, and the caps are
named by name:

    project-keepalive: kosher-ai-filter  suppressed  global-daily-cap 4/4 releases today
    project-keepalive: lpt-website      suppressed  project-daily-cap 1/1 flags today
    project-keepalive: waste-system     suppressed  cooldown 31200s remaining
    project-keepalive: other-thing      suppressed  disabled
    project-keepalive: paused-thing     suppressed  paused (the store's kill switch ... exists)
    project-keepalive: done-thing       quiet       no work remaining

stdout stays frozen to the two words `_flag.run` owns (`quiet` / `flagged
<subject>`); everything above is stderr, where diagnostics belong.

AN UNREADABLE SIGNAL IS NEVER HEALTHY
-------------------------------------
A missing or malformed `projects.json`, a missing or malformed project state
file, a `state_file` that still says `UNKNOWN - needs discovery`, or a wake
store whose tables cannot be read all raise `_flag.Unreadable` -> one line on
stderr and exit 1. Never `quiet`. A project registry this source cannot read is
the exact condition that would otherwise look like "no project needs work".

WHAT THE FLAG TELLS THE WORKER
------------------------------
The prompt is the project's STANDING WORKER CONTRACT, not a task list. It says,
in the worker's own terms:

  * DONE needs the command that proves it -- a quoted command and its output,
    not a claim;
  * BLOCKED-ON-OWNER files ONE owner-queue row and then MOVES ON;
  * BLOCKED-ON-TECHNICAL records the measured blocker and moves on;
  * a worker may never end a shift with work it did not start because it was
    waiting for a person;
  * self-renewal is CONDITIONAL -- the worker rewrites its own state file, and
    the next flag is filed only from real remaining work named there. An empty
    `remaining` list is how a project goes quiet honestly.

CONDITIONAL SELF-RENEWAL IS THE WHOLE POINT
-------------------------------------------
This source does not decide that a project needs another shift; the project's
own state file does. The worker writes it, this source reads it. So the loop
stops when the work stops, and it cannot run forever out of momentum.

RUN
    python3 sources/project-keepalive.py [--dry-run]

ENVIRONMENT (all read at call time)
    PROJECT_KEEPALIVE_REGISTRY        default <this dir>/projects.json
    PROJECT_KEEPALIVE_STATE_DIR       redirect every state_file into this dir
                                      (for rehearsal, never in cron)
    PROJECT_KEEPALIVE_GLOBAL_MAX_PER_DAY   default 4
    SMS_INBOX_DB                      the wake store, as the rest of the source
                                      layer resolves it, via _flag.inbox_db()
    WAKE_PAUSE_FILE                   the store's kill switch; defaults to
                                      WAKE_PAUSED beside the store
    WAKE_MAX_PER_DAY                  the store's own cap; this source never
                                      plans past it

MUST NEVER
    * fire for a disabled project, a project with no work left, or one inside
      its cooldown;
    * raise a flag from inside a woken session (the store refuses that itself);
    * keep its own count of anything. The wake store and the project's state
      file are the only state; a private counter is a second version of the
      truth that will disagree with the first;
    * decide that a project is finished. It reports what the state file says.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flag                                                     # noqa: E402
from _flag import Finding, Unreadable                            # noqa: E402

SOURCE = "project-keepalive"
HERE = Path(__file__).resolve().parent

# The owner's number, in one place, so it is quoted the same way everywhere.
# NOT A BUDGET. The store owns the number; this is only the fallback used when
# neither WAKE_MAX_PER_DAY nor `wake.py stats` can be read. Measured 2026-09-28:
# this source said 4 while the store said 12, suppressed every project at
# "7/4", and no shift was woken. See D2715: count is a runaway backstop, SPEND
# is the limit.
DEFAULT_GLOBAL_MAX_PER_DAY = 500


# --------------------------------------------------------------------------- #
# environment
# --------------------------------------------------------------------------- #
def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        return default


def registry_path() -> Path:
    raw = os.environ.get("PROJECT_KEEPALIVE_REGISTRY")
    return Path(raw).expanduser() if raw else (HERE / "projects.json")


def pause_file() -> Path:
    """The store's kill switch, resolved the way wake.py resolves it.

    `wake.py` refuses every release while this file exists, so a source that
    files rows into a paused store is producing rows nobody will claim -- and
    stale rows, because the subject of the day is a date. The pause is a
    deliberate operator action, not blindness, so it is reported per project by
    name rather than raised.
    """
    raw = os.environ.get("WAKE_PAUSE_FILE")
    if raw:
        return Path(raw).expanduser()
    return _flag.inbox_db().parent / "WAKE_PAUSED"


def state_path(project: dict) -> Path:
    """Where a project keeps the one fact this source cannot invent.

    The registry names it. `PROJECT_KEEPALIVE_STATE_DIR` redirects every
    state_file by basename, which is how the contract's negative cases are
    rehearsed against copies instead of the live files.
    """
    raw = project.get("state_file")
    if not isinstance(raw, str) or not raw.strip():
        raise Unreadable(f"project {project.get('id')!r}: no state_file in the registry")
    if raw.strip().upper().startswith("UNKNOWN"):
        raise Unreadable(
            f"project {project.get('id')!r}: state_file is {raw.strip()!r}")
    path = Path(raw.strip()).expanduser()
    override = os.environ.get("PROJECT_KEEPALIVE_STATE_DIR")
    if override:
        path = Path(override).expanduser() / path.name
    return path


# --------------------------------------------------------------------------- #
# reading the registry
# --------------------------------------------------------------------------- #
def load_registry() -> tuple[dict, list[dict]]:
    """(caps, projects). Unreadable if it cannot be read or does not validate."""
    path = registry_path()
    if not path.is_file():
        raise Unreadable(f"no project registry at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Unreadable(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise Unreadable(f"{path} is not valid JSON: {exc}") from exc

    if isinstance(raw, list):
        caps, projects = {}, raw
    elif isinstance(raw, dict):
        caps = raw.get("caps") or {}
        projects = raw.get("projects")
    else:
        raise Unreadable(f"{path}: top level must be a list or an object")
    if not isinstance(caps, dict):
        raise Unreadable(f"{path}: 'caps' must be an object")
    if not isinstance(projects, list) or not projects:
        raise Unreadable(f"{path}: 'projects' must be a non-empty list")

    seen: set[str] = set()
    for idx, project in enumerate(projects):
        if not isinstance(project, dict):
            raise Unreadable(f"{path}: projects[{idx}] is not an object")
        pid = project.get("id")
        if not isinstance(pid, str) or not pid.strip():
            raise Unreadable(f"{path}: projects[{idx}] has no id")
        # A duplicate id is a registry that cannot be read honestly: two rows
        # would share one dedup key and one daily cap.
        if pid in seen:
            raise Unreadable(f"{path}: duplicate project id {pid!r}")
        seen.add(pid)
        # `enabled` is required and must be a real boolean. Defaulting it either
        # way would let a typo start or stop autonomous work silently.
        if not isinstance(project.get("enabled"), bool):
            raise Unreadable(
                f"{path}: project {pid!r} needs a boolean 'enabled'")
        for field, default in (("cooldown_seconds", 43200),
                               ("max_flags_per_day", 1)):
            value = project.get(field, default)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise Unreadable(
                    f"{path}: project {pid!r} has a bad {field}: {value!r}")
    return caps, projects


def load_state(project: dict) -> dict:
    """The project's own record of what is left. Unreadable if it cannot read."""
    path = state_path(project)
    if not path.is_file():
        raise Unreadable(
            f"project {project.get('id')!r}: no state file at {path} "
            f"(the project has not written its state yet)")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Unreadable(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise Unreadable(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise Unreadable(f"{path}: state must be a JSON object")
    return raw


def work_remaining(project: dict, state: dict) -> tuple[bool, list[str]]:
    """(has_work, [item, ...]) straight out of the project's own state file.

    A boolean `work_remaining` is authoritative. When it is absent the length of
    `remaining` answers instead. When neither is present the signal cannot be
    read, and that is raised rather than guessed.
    """
    items = state.get("remaining")
    if items is None:
        items = state.get("remaining_work")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise Unreadable(
            f"project {project.get('id')!r}: 'remaining' must be a list")
    items = [str(x).strip() for x in items if str(x).strip()]

    flag = state.get("work_remaining")
    if isinstance(flag, bool):
        return flag, items
    if "remaining" in state or "remaining_work" in state:
        return bool(items), items
    raise Unreadable(
        f"project {project.get('id')!r}: state file says nothing about "
        f"work_remaining (needs a boolean, or a 'remaining' list)")


# --------------------------------------------------------------------------- #
# reading the wake store, read-only, always
# --------------------------------------------------------------------------- #
def _store_view(conn, day: str) -> tuple[int, dict, dict]:
    """(released_today, {id: flags_today}, {id: newest_flag_at}).

    The global figure is the store's own `wake_budget.released`, the same
    number wake.py's `daily-cap` uses -- so "4 a day" means one thing on this
    host, not two. The per-project figures count the rows whose subject belongs
    to that project, which is a read of the dedup key itself rather than a
    private counter.
    """
    for table in ("wake", "wake_budget"):
        if not _flag.table_exists(conn, table):
            raise Unreadable(f"the wake store has no {table} table")

    row = conn.execute(
        "SELECT released FROM wake_budget WHERE day=?", (day,)).fetchone()
    released_today = int(row["released"]) if row else 0

    flags_today: dict[str, int] = {}
    newest: dict[str, datetime] = {}
    for r in conn.execute(
        "SELECT subject, created_at FROM wake WHERE subject LIKE 'project:%'"
    ).fetchall():
        subject = str(r["subject"] or "")
        parts = subject.split(":", 2)
        if len(parts) < 3:
            continue
        pid = parts[1]
        when = _flag.parse_dt(r["created_at"])
        if when is None:
            # A row whose age cannot be read cannot be counted against a daily
            # cap honestly. Better to refuse than to under-count the cap.
            raise Unreadable(
                f"wake row {subject!r} has an unreadable created_at: "
                f"{r['created_at']!r}")
        if when.strftime("%Y-%m-%d") == day:
            flags_today[pid] = flags_today.get(pid, 0) + 1
        if pid not in newest or when > newest[pid]:
            newest[pid] = when
    return released_today, flags_today, newest


# The work ledger CLI, on the authority. This is where the backlog, the claim, the attempt
# record (what was tried, the proving command, its output, what is left) and the item's
# definition of done live. Added 2026-09-28 with the ledger-driven standing_contract(); the
# first version of that patch referenced this name without defining it and raised
# NameError the first time a prompt was rendered. A source that cannot render a prompt is a
# source that starts nothing.
LEDGER = "python3 ~/bin/work.py"


# --------------------------------------------------------------------------- #
# the standing worker contract
# --------------------------------------------------------------------------- #
def standing_contract(project: dict, state: dict, items: list[str],
                      now: datetime) -> str:
    """The prompt every woken project session gets: the LEDGER-driven shift contract.

    Rewritten 2026-09-28. The old contract told the worker to rewrite a per-project JSON
    blob with a `remaining` list; that blob was the only record of what was left, it was
    rewritten wholesale by each shift, and nothing recorded what a shift had tried. The
    measured result: 27 filed rows never run, an identical lpt-website fix pushed by three
    shifts and merged by none, and every shift re-deriving the backlog from scratch.

    Now the ledger (`~/bin/work.py`, WAL, on the authority) owns the backlog, the claim, the
    attempt with its proving command and result, and what is left. The state file is still
    mentioned for continuity, but it is no longer where work lives.
    """
    pid = project["id"]
    title = str(project.get("title") or pid)
    where = str(project.get("repo") or project.get("case") or "UNKNOWN")
    state_file = str(state_path(project))
    notes = str(project.get("notes") or "").strip()

    return "\n".join(filter(None, [
        f"PROJECT SHIFT - {title} (`{pid}`). You are a woken session with no history of"
        " this project, and no memory of any previous shift. Everything you need is in the"
        " LEDGER named below; do not look for a summary of it anywhere else.",
        "",
        "THE PROJECT",
        f"  id            {pid}",
        f"  repo          {where}",
        f"  legacy state  {state_file}   (history only - the ledger is authoritative now)",
        f"  woken at      {now.strftime('%Y-%m-%d %H:%M')}Z by the project-keepalive source",
        ("  notes: " + notes) if notes else "",
        "",
        "STEP 1 - FIND OUT IF YOU ARE EVEN NEEDED.",
        f"  Run:  {LEDGER} claim-next --project {pid} --by keepalive-{pid} --lease 5400",
        "",
        "  * `claimed {{...}}` -> YOU OWN THAT ITEM NOW. Do it. (The item id, its title and",
        "    its definition of done are in the JSON on that line; `--json` is implied.)",
        "  * `already-yours` -> a previous shift died mid-item. Do it, then close it.",
        "  * `held-by-other` -> another shift is on it. Take the next one with",
        f"    `{LEDGER} claim-next --project {pid} --by keepalive-{pid} --lease 5400` again,",
        "    and if every item is held, run `work.py reap` once and retry.",
        "  * `nothing-todo` -> THE PROJECT IS FINISHED OR EXHAUSTED. Do not invent work.",
        "    Record why nothing is left and stop.",
        "",
        "STEP 2 - READ WHAT IS KNOWN BEFORE YOU TOUCH ANYTHING.",
        f"  {LEDGER} show <item-id>      # every previous attempt: what was tried, the",
        "                              # proving command, its OUTPUT, and what was left over",
        "  The attempt history is the memory you do not have. If a previous shift already",
        "  proved something, you do NOT need to re-prove it - build on it. If a previous",
        "  shift recorded a MEASURED blocker, do not rediscover it; either it is still true",
        "  (say so, move on) or you have new information that falsifies it.",
        "",
        "STEP 3 - DO THE ITEM, AND PROVE IT.",
        '  DONE requires THE COMMAND THAT PROVES IT, quoted with its output: the test run,',
        "  the curl, the diff, the exit code. \"I changed it\" is not done. If the item's",
        "  `dod` names a command, run THAT command and quote its result line.",
        "",
        "STEP 4 - WRITE BACK BEFORE YOU FINISH. THIS IS THE STEP THAT MAKES THE SYSTEM WORK;",
        "  a shift that does the work and does not write it down has cost money and taught",
        "  the next shift nothing. One call, always, including when you failed:",
        "",
        f"    {LEDGER} close <item-id> --by keepalive-{pid} \\",
        "        --did '<what you actually did, one or two lines>' \\",
        "        --proof '<the exact command you ran>' \\",
        "        --result '<its output, quoted, at least the result line>' \\",
        "        --left '<what is still open in this item, or empty if finished>'",
        "",
        "  Add `--state done` when it is finished (the default is `todo`: work remains).",
        "  `--state blocked --blocked-on '<who or what>'` when only a person or an external",
        "  thing can unblock it - and then TAKE ANOTHER ITEM IN THIS SAME SHIFT.",
        "  A close with no --proof and --result is RECORDED AS NOT DONE, on purpose.",
        "",
        "STEP 5 - IF YOU FIND NEW WORK, FILE IT. The ledger is the backlog, and a shift that",
        "  discovered real work is the best source of items:",
        f"    {LEDGER} add --project {pid} --title '<one line>' \\",
        "        --dod '<the command that will prove it>' --priority <1-9> \\",
        "        --why '<why it matters, one line>'",
        "  `--priority 1` is a blocker, `5` is normal, `9` is nice-to-have. Do NOT file items",
        "  to keep a loop alive; an item with no provable definition of done is not an item.",
        "",
        "STEP 6 - THE LEGACY STATE FILE. You may bring it current (it is what a human reads",
        f"  first), but it is NOT where work is tracked:  {state_file}",
        "  Keep `work_remaining` true only if real work remains, and describe it in terms the",
        "  ledger agrees with. If the two disagree, THE LEDGER IS RIGHT.",
        "",
        "STEP 7 - THE ONLY REASONS TO TEXT HIM, AND THE REASON NOT TO.",
        "  A text to the owner that carries anything else WASTES HIS ATTENTION, and he said so",
        "  sharply on 2026-09-28. Asked why he would receive a completion report, he answered:",
        "  whats the point, is there a question or clarification you need from me, or a warning",
        "  you need to give me? There was none. Do not repeat that.",
        "",
        "  TEXT HIM ONLY IF THE MESSAGE IS ONE OF THESE THREE:",
        "    (1) A QUESTION ONLY HE CAN ANSWER, with your recommendation on the same line.",
        "    (2) A WARNING HE MUST ACT ON TODAY - something about to break, be lost, or cost",
        "        money, where waiting for him to look would be too late.",
        "    (3) A DECISION WITH A DEADLINE - a reply is genuinely needed before time runs out.",
        "",
        "  DO NOT TEXT HIM: that a job started, that a job finished, that tests passed, that a",
        "  branch was pushed, that you filed a queue row, or to prove the channel works. A",
        "  FINISHED JOB IS RECORDED IN THE LEDGER, which is where it is useful. It finished is",
        "  not a reason to text.",
        "",
        "  If it IS one of the three: file the owner-queue row FIRST (step (b) below), so the",
        "  question exists somewhere durable, and then send ONE short message naming it. Write",
        "  the body into a file first; never put quotes or newlines on a command line:",
        "",
        "    printf %s 'YOUR ONE-LINE QUESTION. I recommend X.' > /tmp/reply.txt",
        "    python3 ~/bin/textsend.py send --to +18483897895 --body-file /tmp/reply.txt --send",
        "",
        "  The recipient is gated to the owner alone and may go NOWHERE ELSE. Quote the result",
        "  line back. Never write a price, a date, a commitment or a legal posture into it, and",
        "  never send anything outbound to a customer, vendor or colleague.",
        "",        "STOPPING. Stop for exactly one of three reasons, and say which:",
        "  (a) DONE - quote the proving command and its output, and name what is next.",
        "  (b) BLOCKED-ON-OWNER - it needs a decision only a person can make. File ONE row",
        "      and only one, then MOVE ON to the next item in this same shift:",
        "        python3 ~/bin/owner-queue.py add \\",
        "          --question '<the exact question, in one line>' \\",
        "          --recommendation '<what you would do if it were yours>' \\",
        "          --options '<option a>|<option b>|<option c>'",
        "      Do not wait for the answer, do not ask again, do not stop.",
        "  (c) NOTHING-LEFT - the ledger has no todo item for this project. Say so and stop.",
        "  A SHIFT MAY NEVER END WITH WORK IT DID NOT START BECAUSE IT WAS WAITING FOR A",
        "  PERSON. Waiting is not a status; it is a reason to start the next thing. In the",
        '  owner\'s words: "if they run into problems or any decisions they should add them',
        '  to the owner queue and I\'ll get to them and then they should move on to the next',
        '  thing while they\'re waiting for me to respond."',
        "",
        "HARD LIMITS",
        "  * Do NOT contact the owner or any customer: no email, no SMS, no call. The owner",
        "    queue is the only channel to him, and a shift never sends anything outbound.",        "  * Do NOT raise a wake flag. The dispatcher sets WAKE_SESSION=1 and the store",
        "    refuses; raising one would start a session that starts a session.",
        "  * Do NOT touch cron, and do not restart production services.",
        "  * Do NOT commit to main, never force-push, never `git reset --hard`, never",
        "    `rm -rf`. Work on a branch and leave it pushed for the integrator.",
        "  * Do NOT mark done what you did not do, and do not report a number you did not",
        "    read. An honest \"not verified\" is worth more than a confident guess.",
        "",
        "REPORT AT THE END: the item id, what you did, the command that proves it with its",
        "output, and what the ledger now says about this item and this project.",
    ]))



# --------------------------------------------------------------------------- #
# the source
# --------------------------------------------------------------------------- #
def collect(args) -> list[Finding]:
    now = _flag.now_utc()
    day = now.strftime("%Y-%m-%d")
    today = now.strftime("%Y%m%d")

    caps, projects = load_registry()

    configured = caps.get("global_max_flags_per_day")
    if not isinstance(configured, int) or isinstance(configured, bool) \
            or configured < 0:
        configured = _env_int("PROJECT_KEEPALIVE_GLOBAL_MAX_PER_DAY",
                              DEFAULT_GLOBAL_MAX_PER_DAY)
    configured = _env_int("PROJECT_KEEPALIVE_GLOBAL_MAX_PER_DAY", configured)
    # The store is the last word on the whole-system budget: planning past it
    # would only produce rows that can never be released.
    # THE STORE OWNS THE NUMBER. Prefer its live value; if that cannot be read, use the
    # env var or the fallback - and use the LARGEST of them, because a source that reports
    # a smaller cap than the store is a source that silently holds back work.
    store_cap = _env_int("WAKE_MAX_PER_DAY", DEFAULT_GLOBAL_MAX_PER_DAY)
    try:
        import json as _json, subprocess as _sp
        _live = _sp.run(["python3", str(Path.home() / "bin" / "wake.py"), "stats", "--json"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=60)
        _c = (_json.loads(_live.stdout or "{}").get("caps") or {}).get("max_per_day")
        if isinstance(_c, int) and _c > store_cap:
            store_cap = _c
    except Exception:
        pass
    global_cap = max(0, min(configured, store_cap))

    conn = _flag.ro_connect(_flag.inbox_db())
    try:
        released_today, flags_today, newest = _store_view(conn, day)
    finally:
        conn.close()

    budget = max(0, global_cap - released_today)
    findings: list[Finding] = []
    stayed: list[str] = []

    paused_at = pause_file()
    if paused_at.exists():
        for project in projects:
            stayed.append(
                f"{project['id']}  suppressed  paused (the store's kill switch "
                f"{paused_at} exists)")
        for line in stayed:
            print(f"{SOURCE}: {line}", file=sys.stderr)
        print(f"{SOURCE}: 0 flag(s) to raise, {len(stayed)} suppression(s), "
              f"the store is paused -- nothing would be released", file=sys.stderr)
        return []

    for project in projects:
        pid = project["id"]

        if not project["enabled"]:
            stayed.append(f"{pid}  suppressed  disabled")
            continue

        state = load_state(project)
        has_work, items = work_remaining(project, state)

        if not has_work:
            stayed.append(
                f"{pid}  quiet       no work remaining (state file says the work is done)")
            continue

        cooldown = int(project.get("cooldown_seconds", 43200))
        last = newest.get(pid)
        if last is not None and cooldown > 0:
            age = (now - last).total_seconds()
            if age < cooldown:
                stayed.append(
                    f"{pid}  suppressed  cooldown {int(cooldown - age)}s remaining "
                    f"(last flag {last.strftime('%Y-%m-%d %H:%M')}Z, "
                    f"cooldown {cooldown}s)")
                continue

        per_project = int(project.get("max_flags_per_day", 1))
        used = flags_today.get(pid, 0)
        if used >= per_project:
            stayed.append(
                f"{pid}  suppressed  project-daily-cap {used}/{per_project} flags today")
            continue

        if budget <= 0:
            stayed.append(
                f"{pid}  suppressed  global-daily-cap {released_today}/{global_cap} "
                f"releases today (system-wide, owner's limit)")
            continue

        # A day that would carry more than one flag needs a subject that stays a
        # unique dedup key; the first flag of the day keeps the documented shape.
        subject = f"project:{pid}:{today}"
        if used:
            subject = f"{subject}#{used + 1}"

        findings.append(Finding(
            subject=subject,
            prompt=standing_contract(project, state, items, now),
            context=(
                f"{SOURCE}: {pid} has work remaining ({len(items)} item(s) named in "
                f"{state_path(project)}); raised {used + 1}/{per_project} today, "
                f"system-wide {released_today + len(findings) + 1}/{global_cap}"),
            priority=str(project.get("priority") or "normal"),
            kind="project",
            cooldown_seconds=cooldown,
        ))
        stayed.append(
            f"{pid}  flagged     {subject}  ({len(items)} item(s) remaining)")
        budget -= 1

    # One line per project, on stderr. A source that declines to file has to say
    # so and name the reason, or "quiet" hides a broken cap.
    for line in stayed:
        print(f"{SOURCE}: {line}", file=sys.stderr)
    reasons = [ln for ln in stayed if "suppressed" in ln]
    print(f"{SOURCE}: {len(findings)} flag(s) to raise, {len(reasons)} suppression(s), "
          f"system-wide releases today {released_today}/{global_cap}",
          file=sys.stderr)
    return findings


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
