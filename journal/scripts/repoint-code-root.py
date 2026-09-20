#!/usr/bin/env python3
"""One resolver for host paths, and repoint the sites that guessed Windows.

Windows-era literals such as "C:/Users/ezabz/Code/quickbooks-agent" are relative
paths on the Linux authority, where they do not exist. Every failure is silent: a
scanner that finds no repositories, a subprocess that never starts, a status
endpoint that answers "accounting.db not found". The correct rule already existed
in app/chat_action_repos.py — Windows uses %USERPROFILE%\\Code, Linux uses
~/repos — it simply was not shared.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import time

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUPS = ROOT / ".runtime" / "deploy-backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

PATHS_MODULE = '''"""Where things live, resolved once, per platform.

This application was written on Windows and grew literals like
"C:/Users/ezabz/Code/quickbooks-agent". On the Linux authority those are relative
paths that do not exist, and every failure is silent -- a scanner that finds no
repositories, a subprocess that never starts, a status endpoint that reports "not
found" -- so the defect survived for weeks unnoticed.

Resolution order: an explicit environment variable, then the platform's real
convention, then the first remaining candidate that exists. Probing before
falling back matters: a wrong guess must not silently blind a scanner, which is
exactly how the local-context bug presented (it reported no repositories at all).
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_CODE_ROOT = "CODE_ROOT"
ENV_ACCOUNTING_DB = "ACCOUNTING_DB_PATH"


def app_root() -> Path:
    """The application directory -- the parent of the ``app`` package."""
    return Path(__file__).resolve().parents[1]


def code_root() -> Path:
    """The folder holding the owner's sibling repositories.

    Windows dev machines keep them under ``%USERPROFILE%\\\\Code``; the Linux hosts
    under ``~/repos``. This mirrors app/chat_action_repos.py, which held the only
    correct copy of the rule.
    """
    override = os.environ.get(ENV_CODE_ROOT)
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if os.name == "nt":
        candidates = (
            Path(os.environ.get("USERPROFILE", str(home))) / "Code",
            home / "repos",
            home / "code",
        )
    else:
        candidates = (home / "repos", home / "Code", home / "code")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def accounting_db_path() -> Path:
    """The accounting ledger, which deliberately lives outside the app tree."""
    override = os.environ.get(ENV_ACCOUNTING_DB)
    if override:
        return Path(override).expanduser()
    return Path.home() / "accounting-data" / "live" / "accounting.db"


ACCOUNTING_DB_PATH = accounting_db_path()
CODE_ROOT = code_root()
'''

WindowsOnlySkip = """{indent}if not {check}.exists():
{indent}    # A Windows-only one-shot utility. On a host that does not have it, record a
{indent}    # skip rather than a failure every day for something that cannot run here.
{indent}    logger.info("autopilot: {label} skipped - %s is not installed on this host", {check})
{indent}    self._record_subsystem("{subsystem}", success=True, detail="skipped: not installed on this host")
{indent}    return
"""

edits: list[tuple[str, str, str]] = [
    # ── the owner's code folder ───────────────────────────────────────────
    (
        "app/services/local_context.py",
        '_CODE_FOLDER = pathlib.Path("C:/Users/ezabz/Code")',
        "_CODE_FOLDER = code_root()",
    ),
    (
        "app/services/local_context.py",
        '            "C:/Users/ezabz/Code/personal-secretary-mvp"',
        '            str(_CODE_FOLDER / "personal-secretary-mvp")',
    ),
    (
        "app/services/source_watchers.py",
        '"config": {"path": r"C:\\Users\\ezabz\\Code", "depth": 1},',
        '"config": {"path": str(code_root()), "depth": 1},',
    ),
    (
        "app/services/next_stage_runtime.py",
        '    default_roots = ["C:/Users/ezabz/Code"]',
        "    default_roots = [str(code_root())]",
    ),
    # ── the quickbooks-agent fallbacks ────────────────────────────────────
    *[
        (
            svc,
            '_LEGACY_QB_REPO = Path("C:/Users/ezabz/Code/quickbooks-agent")',
            '_LEGACY_QB_REPO = code_root() / "quickbooks-agent"',
        )
        for svc in (
            "app/services/amazon_bank_service.py",
            "app/services/ebay_bank_service.py",
            "app/services/chase_bank_service.py",
            "app/services/boa_bank_service.py",
            "app/services/paypal_service.py",
        )
    ],
    # ── the two Windows-only one-shot utilities ───────────────────────────
    (
        "app/autopilot.py",
        '            script_dir = "C:/Users/ezabz/Code/personal-secretary-mvp/_scratch/one-shot-utils"',
        '            script_dir = app_root() / "_scratch" / "one-shot-utils"\n'
        + WindowsOnlySkip.format(
            indent=" " * 12,
            check='(script_dir / "balances.py")',
            label="balance capture",
            subsystem="balance_capture",
        )
        + '            script_dir = str(script_dir)',
    ),
    (
        "app/autopilot.py",
        '            script = "C:/Users/ezabz/Code/personal-secretary-mvp/_scratch/one-shot-utils/personal-spending-report.py"',
        '            script_path = app_root() / "_scratch" / "one-shot-utils" / "personal-spending-report.py"\n'
        + WindowsOnlySkip.format(
            indent=" " * 12,
            check="script_path",
            label="spending report",
            subsystem="spending_report",
        )
        + "            script = str(script_path)",
    ),
    (
        "app/autopilot.py",
        '            report_dir = "C:/Users/ezabz/Code/personal-secretary-mvp/data/spending-reports"',
        '            report_dir = str(app_root() / "data" / "spending-reports")',
    ),
    # ── importers of the module being replaced ────────────────────────────
    (
        "app/main.py",
        "from app.accounting_paths import accounting_db_path",
        "from app.paths import accounting_db_path",
    ),
    (
        "app/services/auto_categorize.py",
        "from app.accounting_paths import accounting_db_path",
        "from app.paths import accounting_db_path",
    ),
    # ── the test that guards all of this ──────────────────────────────────
    (
        "tests/test_accounting_db_path.py",
        "from app.accounting_paths import accounting_db_path",
        "from app.paths import accounting_db_path",
    ),
]

IMPORT_RE = re.compile(r"^(import|from) [A-Za-z0-9_., ]+$")

NEEDS_IMPORT = {
    "app/services/local_context.py": "code_root",
    "app/services/source_watchers.py": "code_root",
    "app/services/next_stage_runtime.py": "code_root",
    "app/autopilot.py": "app_root, code_root",
    "app/services/amazon_bank_service.py": "code_root",
    "app/services/ebay_bank_service.py": "code_root",
    "app/services/chase_bank_service.py": "code_root",
    "app/services/boa_bank_service.py": "code_root",
    "app/services/paypal_service.py": "code_root",
}

NEW_TEST = '''

def test_code_root_prefers_a_directory_that_exists():
    """A wrong guess here is silent: the scanners simply find nothing."""
    from pathlib import Path

    from app.paths import code_root

    home = Path.home()
    existing = [p for p in (home / "repos", home / "Code", home / "code") if p.is_dir()]
    root = code_root()
    if existing:
        assert root in existing, f"code_root()={root} ignored the existing {existing}"
        assert root.is_dir()
'''


def backup(rel: str) -> None:
    dst = BACKUPS / f"{pathlib.Path(rel).name}.{STAMP}.bak"
    if not dst.exists():
        shutil.copy(rel, dst)


def main() -> int:
    (ROOT / "app" / "paths.py").write_text(PATHS_MODULE, encoding="utf-8")
    print("wrote app/paths.py")

    for rel, old, new in edits:
        path = pathlib.Path(rel)
        src = path.read_text(encoding="utf-8")
        found = src.count(old)
        assert found == 1, f"{rel}: expected exactly 1 of {old[:70]!r}, found {found}"
        backup(rel)
        path.write_text(src.replace(old, new), encoding="utf-8")
        print(f"  {rel}: replaced")

    for rel, names in sorted(NEEDS_IMPORT.items()):
        path = pathlib.Path(rel)
        src = path.read_text(encoding="utf-8")
        if "from app.paths import" in src:
            print(f"  {rel}: import already present")
            continue
        backup(rel)
        lines = src.split("\n")
        first = next((i for i, ln in enumerate(lines) if IMPORT_RE.match(ln)), None)
        assert first is not None, f"{rel}: no single-line top-level import to anchor on"
        # Walk to the end of that first contiguous import block (imports and blank
        # lines only). Anchoring on the LAST import in the file would risk landing
        # below module-level code that calls what we import.
        j = first
        while j + 1 < len(lines) and (IMPORT_RE.match(lines[j + 1]) or not lines[j + 1].strip()):
            j += 1
        lines.insert(j + 1, f"from app.paths import {names}")
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  {rel}: import added after line {j + 1} (first import block)")

    test = pathlib.Path("tests/test_accounting_db_path.py")
    src = test.read_text(encoding="utf-8")
    if "def test_code_root_prefers" not in src:
        test.write_text(src.rstrip("\n") + "\n" + NEW_TEST, encoding="utf-8")
        print("  tests/test_accounting_db_path.py: code_root guard added")

    old_module = ROOT / "app" / "accounting_paths.py"
    if old_module.exists():
        shutil.copy(old_module, BACKUPS / f"accounting_paths.py.{STAMP}.bak")
        old_module.unlink()
        print("  removed app/accounting_paths.py (superseded by app/paths.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
