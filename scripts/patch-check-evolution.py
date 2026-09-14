"""Make check_evolution stop crying wolf about a deliberately disabled setting.

Measured 2026-09-14. `evolution_log` holds 102 applied and 72 unapplied, and the
kernel reports:

    evolution  high  evolution loop not closing: 72 proposals unapplied; 38
                     duplicate offers on [...]; 1 target file(s) inside node_modules

But the loop is not supposed to apply anything. `app/evolution.py` gates the apply
path on `code_edit_auto_apply`:

    wants_auto_apply = bool(getattr(settings, "code_edit_auto_apply", False))

and that setting is **declared False in config.py:803 and set False explicitly in
the authority's .env:123**. The last applied proposal is 2026-07-04, which is when it
took effect. So "72 proposals unapplied" is the configured behaviour, and a check
that calls it HIGH on the owner's badge is a false alarm that never clears.

That matters beyond accuracy: P52 already records that a sentinel and an alarm
disagreeing teaches the owner "to start ignoring both". An alarm that is permanently
wrong does the same job more slowly.

What stays real and keeps its severity: duplicate offers on one file, and targets
inside node_modules. Both were genuine and both are fixed at the source (W57), and
the check should still catch them if they return.

Gated: every anchor must match exactly once or nothing is written.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "ceo-kernel" / "ck" / "sentinel.py"
BACKUP = Path.home() / "ceo-kernel" / ".runtime" / "check-evolution.py.pre"

HELPER = '''

def _auto_apply_enabled() -> bool:
    """Whether the app is configured to apply its own proposals automatically.

    Reads CODE_EDIT_AUTO_APPLY from the app's .env on this host. The setting is
    declared False in app/config.py and set False explicitly in the authority's .env,
    so an absent or unreadable value means "off" -- the safe direction for a check
    that would otherwise raise a permanent HIGH alarm about expected behaviour.
    """
    import pathlib as _p

    candidates = (
        _p.Path("/home/zabz/personal-secretary-mvp/.env"),
        _p.Path.home() / "personal-secretary-mvp" / ".env",
    )
    for path in candidates:
        try:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip().upper() == "CODE_EDIT_AUTO_APPLY":
                    return value.strip().lower() in ("1", "true", "yes", "on")
        except OSError:
            continue
    return False

'''

PROBLEMS_OLD = '''    problems: list[str] = []
    if unapplied > 10:
        problems.append(f"{unapplied} proposals unapplied")
    if applied == 0 and unapplied > 0:
        problems.append("no proposal has ever been applied")
'''

PROBLEMS_NEW = '''    auto_apply = _auto_apply_enabled()
    metrics["auto_apply_enabled"] = auto_apply

    problems: list[str] = []
    if auto_apply:
        # Only a loop that is SUPPOSED to apply can be judged on how much it applied.
        if unapplied > 10:
            problems.append(f"{unapplied} proposals unapplied")
        if applied == 0 and unapplied > 0:
            problems.append("no proposal has ever been applied")
    else:
        metrics["queued_for_review"] = unapplied
'''

SEVERITY_OLD = '''    if problems:
        return Finding(
            check="evolution",
            severity=HIGH if applied else CRITICAL,
            ok=False,
            summary="evolution loop not closing: " + "; ".join(problems),
            metrics=metrics,
            provenance=[_pkt_note(pkt), _pkt_note(dup)],
        )
'''

SEVERITY_NEW = '''    if problems:
        return Finding(
            check="evolution",
            severity=HIGH if applied else CRITICAL,
            ok=False,
            summary="evolution loop not closing: " + "; ".join(problems),
            metrics=metrics,
            provenance=[_pkt_note(pkt), _pkt_note(dup)],
        )
    if not auto_apply:
        # Not a fault: the apply path is switched off in configuration. Report it as
        # a reading so the badge shows a fact instead of a permanent false alarm.
        return Finding(
            check="evolution",
            severity=INFO,
            ok=True,
            summary=(
                f"evolution proposes but does not self-apply: auto-apply is off in "
                f"configuration, so {unapplied} proposal(s) are queued for review "
                f"({applied} applied historically)"
            ),
            metrics=metrics,
            provenance=[_pkt_note(pkt), _pkt_note(dup)],
        )
'''

EDITS = [
    ("helper", "def check_evolution() -> Finding:", HELPER.lstrip("\n") + "def check_evolution() -> Finding:"),
    ("problems", PROBLEMS_OLD, PROBLEMS_NEW),
    ("severity", SEVERITY_OLD, SEVERITY_NEW),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    problems = []
    for name, old, _new in EDITS:
        n = text.count(old)
        if n != 1:
            problems.append(f"  {name}: anchor matched {n} time(s), need 1")
    if problems:
        print("REFUSING: anchors did not match uniquely; nothing written.")
        print("\n".join(problems))
        return 1

    before = hashlib.sha256(text.encode()).hexdigest()
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)

    new = text
    for _n, old, replacement in EDITS:
        new = new.replace(old, replacement, 1)

    checks = [
        ("helper defined", "def _auto_apply_enabled()" in new),
        ("auto_apply consulted", "auto_apply = _auto_apply_enabled()" in new),
        ("unapplied only alarms when auto-apply is on", "if auto_apply:" in new),
        ("queued_for_review reported", '"queued_for_review"' in new),
        ("duplicates still alarm", "duplicate offers on" in new),
        ("node_modules still alarms", "inside node_modules" in new),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed; nothing written. " + ", ".join(failed))
        return 1

    TARGET.write_text(new, encoding="utf-8")
    print(f"sha256 {before} -> {hashlib.sha256(new.encode()).hexdigest()}")
    print(f"backup: {BACKUP}")
    print("PATCH APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
