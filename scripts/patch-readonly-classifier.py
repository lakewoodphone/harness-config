#!/usr/bin/env python3
"""Decide read-only-ness from every token in an action name, not the first one.

MEASURED 2026-09-14 from the action names real sessions executed (count in
parentheses): list_tasks(125), system_health(63), ha_states(56), ha_status(34),
repo_search(29), web_search(27), close_task(25), task_hygiene(23), memory_search(22),
gmail_list(21), gmail_search(20), qb_search(19), repo_read_file(18), repo_list_dir(17),
calendar_list(15), ha_entity(15), github_list_prs(14), update_task(12),
save_memory(10), qb_query(10), qb_status(7), contact_lookup(4), contact_search(4).

The old rule tested a prefix at the START of the name, so ha_states, ha_status,
memory_search, gmail_list, gmail_search, qb_search, qb_query, qb_status,
calendar_list, ha_entity, github_list_prs, contact_lookup and contact_search were all
classified as WORK. In a namespaced name the verb is the second word. That is
exactly the reconnaissance the nudge exists to detect, reported as progress -- and it
would have let a purely exploratory session earn budget extensions.

A mutating verb anywhere wins, so update_task_status stays work.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUPS = ROOT / ".runtime" / "deploy-backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

OLD_CONSTS = '''    _READ_ONLY_ACTION_PREFIXES = (
        "list_", "get_", "read_", "search_", "show_", "view_", "check_", "find_",
        "query_",
    )
    _READ_ONLY_ACTIONS = frozenset({
        "system_health", "task_hygiene", "repo_list_dir", "repo_read_file",
        "repo_search", "github_read_file", "github_list_issues", "web_search",
        "fetch_url", "get_current_datetime", "list_dynamic_tools",
        "read_call_transcript",
    })'''

NEW_CONSTS = '''    # Read-only versus work is decided by EVERY token in an action name, not by its
    # first token. The old prefix rule called ha_states, qb_status, gmail_list,
    # memory_search, calendar_list, contact_lookup and github_list_prs "work",
    # because in a namespaced name the verb is the second word -- so the
    # reconnaissance nudge was fed a false signal, and the budget extension would
    # have rewarded exploration as if it were progress.
    _READ_ONLY_VERBS = frozenset({
        "list", "get", "read", "search", "show", "view", "check", "find", "query",
        "lookup", "fetch", "count", "describe", "inspect", "states", "state",
        "status", "entity", "entities", "transcript", "health", "summary", "review",
    })
    _MUTATING_VERBS = frozenset({
        "create", "update", "close", "delete", "send", "save", "write", "edit",
        "set", "add", "remove", "assign", "complete", "approve", "reject", "start",
        "stop", "schedule", "execute", "apply", "ingest", "upload", "post", "put",
        "patch", "insert", "enqueue", "cancel", "archive", "mark", "record", "open",
        "link", "unlink", "sync", "run", "pay", "buy", "notify",
    })
    _READ_ONLY_ACTION_PREFIXES = (
        "list_", "get_", "read_", "search_", "show_", "view_", "check_", "find_",
        "query_",
    )
    _READ_ONLY_ACTIONS = frozenset({
        "system_health", "task_hygiene", "repo_list_dir", "repo_read_file",
        "repo_search", "github_read_file", "github_list_issues", "web_search",
        "fetch_url", "get_current_datetime", "list_dynamic_tools",
        "read_call_transcript",
    })

    @classmethod
    def _action_name_is_read_only(cls, name: str) -> bool:
        """True when an action name only looked at something.

        A mutating verb anywhere in the name wins, so `update_task_status` is work.
        Otherwise a read verb anywhere, an explicit entry, or a leading read prefix
        makes it read-only. An unrecognised name counts as work, so the nudge never
        suppresses a mutating tool it has not seen before.
        """
        token = str(name or "").strip().lower()
        if not token:
            return False
        words = [w for w in re.split(r"[^a-z0-9]+", token) if w]
        if any(w in cls._MUTATING_VERBS for w in words):
            return False
        if token in cls._READ_ONLY_ACTIONS:
            return True
        if any(w in cls._READ_ONLY_VERBS for w in words):
            return True
        return token.startswith(cls._READ_ONLY_ACTION_PREFIXES)'''

OLD_CLASSIFY = '''        return all(
            n in cls._READ_ONLY_ACTIONS or n.startswith(cls._READ_ONLY_ACTION_PREFIXES)
            for n in names
        )'''
NEW_CLASSIFY = '''        return all(cls._action_name_is_read_only(n) for n in names)'''

OLD_PROGRESS = '''                read_only = name in cls._READ_ONLY_ACTIONS or name.startswith(
                    cls._READ_ONLY_ACTION_PREFIXES
                )
                if not read_only:
                    return True'''
NEW_PROGRESS = '''                if not cls._action_name_is_read_only(name):
                    return True'''

TEST = '''"""Read-only-ness must be read from the whole action name, not its first token.

The names below and their counts come from the action names real sessions executed on
secratary in the 24 hours to 2026-09-14. The old rule classified every namespaced read
(gmail_list, qb_search, ha_states) as work, which is the reconnaissance the nudge
exists to detect -- reported as progress.
"""

import pytest

from app.autopilot import AutopilotController as AC

# Observed reconnaissance: must count as read-only, or the loop cannot tell that it
# is exploring instead of working.
READ_ONLY = [
    "list_tasks", "system_health", "ha_states", "ha_status", "repo_search",
    "web_search", "task_hygiene", "memory_search", "gmail_list", "gmail_search",
    "qb_search", "repo_read_file", "repo_list_dir", "calendar_list", "ha_entity",
    "github_list_prs", "qb_query", "qb_status", "contact_lookup", "contact_search",
    "list_dynamic_tools", "get_task", "fetch_url",
]

# Observed work: must NOT be read-only, or the session will never be seen as acting.
WORK = [
    "close_task", "update_task", "save_memory", "create_task", "send_sms",
    "schedule_reminder", "execute_action", "update_task_status", "create_task_note",
]


@pytest.mark.parametrize("name", READ_ONLY)
def test_namespaced_reads_are_read_only(name):
    assert AC._action_name_is_read_only(name) is True, name


@pytest.mark.parametrize("name", WORK)
def test_mutating_names_are_not_read_only(name):
    assert AC._action_name_is_read_only(name) is False, name


def test_a_mutating_verb_anywhere_wins():
    """`update_task_status` must not be read-only just because it says 'status'."""
    assert AC._action_name_is_read_only("update_task_status") is False
    assert AC._action_name_is_read_only("qb_status") is True


def test_unknown_actions_count_as_work():
    """Never suppress a mutating tool merely because its name is unfamiliar."""
    assert AC._action_name_is_read_only("frobnicate_widget") is False
    assert AC._action_name_is_read_only("") is False
    assert AC._action_name_is_read_only(None) is False


def test_the_step_list_classifier_agrees_with_the_name_classifier():
    actions = [{"name": "ha_states"}, {"name": "list_tasks"}, {"name": "qb_status"}]
    assert AC._actions_are_read_only(actions) is True
    actions = [{"name": "ha_states"}, {"name": "update_task"}]
    assert AC._actions_are_read_only(actions) is False


def test_progress_needs_a_real_action():
    recon = "Step 1: a [ACTIONS: 2 (ha_states, list_tasks)]\\nStep 2: b [ACTIONS: 1 (qb_status)]\\n"
    assert AC._work_session_is_progressing(recon) is False
    acted = "Step 1: a [ACTIONS: 2 (ha_states, list_tasks)]\\nStep 2: b [ACTIONS: 1 (update_task)]\\n"
    assert AC._work_session_is_progressing(acted) is True


def test_only_the_recent_window_counts():
    text = (
        "Step 1: closure [ACTIONS: 1 (close_task)]\\n"
        "Step 2: a [ACTIONS: 1 (gmail_list)]\\n"
        "Step 3: b [ACTIONS: 1 (ha_states)]\\n"
        "Step 4: c [ACTIONS: 1 (qb_status)]\\n"
    )
    assert AC._work_session_is_progressing(text) is False


def test_the_feedback_suffix_does_not_break_parsing():
    text = "Step 1: x [ACTIONS: 2 (list_tasks, save_memory)] [TOOL-RESULTS-FED: 776c]\\n"
    assert AC._work_session_is_progressing(text) is True


def test_the_extension_is_bounded():
    assert AC._WORK_ABSOLUTE_MAX_STEPS > AC._WORK_MAX_STEPS
    assert AC._WORK_ABSOLUTE_MAX_STEPS <= 30
    assert AC._WORK_STEP_EXTENSION > 0
'''


def main() -> int:
    path = pathlib.Path("app/autopilot.py")
    src = path.read_text(encoding="utf-8")

    for label, needle in (
        ("old constants", OLD_CONSTS),
        ("classifier tail", OLD_CLASSIFY),
        ("progress test", OLD_PROGRESS),
    ):
        assert src.count(needle) == 1, f"{label}: {src.count(needle)} matches"
    assert "_action_name_is_read_only" not in src

    backup = BACKUPS / f"autopilot.py.{STAMP}.bak5"
    if not backup.exists():
        shutil.copy("app/autopilot.py", backup)

    src = src.replace(OLD_CONSTS, NEW_CONSTS)
    src = src.replace(OLD_CLASSIFY, NEW_CLASSIFY)
    src = src.replace(OLD_PROGRESS, NEW_PROGRESS)
    path.write_text(src, encoding="utf-8")
    print("patched app/autopilot.py")

    pathlib.Path("tests/test_budget_extension.py").write_text(TEST, encoding="utf-8")
    print("rewrote tests/test_budget_extension.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
