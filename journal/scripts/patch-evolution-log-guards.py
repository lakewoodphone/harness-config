"""The evolution log records the same offer again and again, and once for a vendored file.

Measured 2026-09-15 in the authoritative database:

    unapplied, last 7 days:  18 rows  ["app/services/activity_sync.py"]
                              8 rows  ["web/node_modules/flatted/python/flatted.py"]
    that first target, all unapplied: 38 rows, **1 distinct description**,
                                      38 distinct proposal_ids
    node_modules rows, all time: 19

So the engine mints a fresh `proposal_id` for a change it has already offered, and `log_evolution`
faithfully records each one. The kernel's `check_evolution` reads exactly this and has read HIGH for
weeks: "18 duplicate offers on [...] app/services/activity_sync.py; 1 target file(s) inside
node_modules". That is spend and a loop that never closes (P4), and the node_modules target is a
filter that was never written.

Two guards, both at the single writer (`app/database.py::log_evolution`):

1. **A vendored or generated target is never logged.** Paths under `node_modules`, `.venv`,
   `site-packages`, `__pycache__`, `.next`, `dist` or `build` are dropped from the target list; if
   nothing is left, the call logs at INFO and records nothing. A proposal that touches both a source
   file and a vendored one keeps its source target.
2. **An identical unapplied offer is not recorded twice.** Keyed on
   `(change_type, files_changed, description)` while `applied=0` -- the description is what makes two
   offers the same change, and the measurement above shows the duplicate set is exactly that: 38 rows,
   one description. An application (`applied=True`) always inserts, because applying something is a
   fact about the world and not an offer.
"""

from __future__ import annotations

import pathlib
import sys

DB = pathlib.Path.home() / "personal-secretary-mvp" / "app" / "database.py"

HELPER_ANCHOR = '''def log_evolution(
    db_url: str,
    change_type: str,
    description: str,
    files_changed: list[str] | None = None,
    proposal_id: str | None = None,
    applied: bool = False,
    agent_id: str = "orchestrator",
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO evolution_log
               (agent_id, change_type, description, files_changed,
                proposal_id, applied, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_id,
                change_type,
                description,
                json.dumps(files_changed or []),
                proposal_id,
                1 if applied else 0,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0'''

HELPER_REPLACE = '''# Directories whose contents are vendored or generated: a proposal that edits them either gets
# overwritten by the next install or is not source anyone maintains. Measured 2026-09-15: 19
# evolution_log rows targeted web/node_modules/flatted/python/flatted.py.
_VENDORED_PATH_PARTS = frozenset(
    {"node_modules", ".venv", "site-packages", "__pycache__", ".next", "dist", "build", ".git"}
)


def _is_vendored_path(path: str) -> bool:
    """True when a path lives inside a vendored or generated tree."""
    norm = str(path or "").replace("\\\\", "/").strip().lstrip("./").lower()
    if not norm:
        return True
    return any(part in _VENDORED_PATH_PARTS for part in norm.split("/") if part)


def log_evolution(
    db_url: str,
    change_type: str,
    description: str,
    files_changed: list[str] | None = None,
    proposal_id: str | None = None,
    applied: bool = False,
    agent_id: str = "orchestrator",
) -> int:
    """Record an evolution offer, once, and never against a vendored file.

    Two guards, both measured on 2026-09-15 (see the module note in the commit and P4):

    * vendored/generated targets are dropped from the list -- an offer that still has a real source
      file keeps it, and an offer with nothing left is not recorded at all (returns 0);
    * an identical UNapplied offer is not recorded twice. The engine mints a fresh `proposal_id` each
      time it re-offers a change, so the key is `(change_type, files_changed, description)` while
      `applied=0`: 38 unapplied rows for one file shared one description across 38 proposal ids.
      An application always inserts -- that is a fact, not an offer.
    """
    conn = _get_conn(db_url)
    now = _now_iso()

    targets = [str(p) for p in (files_changed or [])]
    kept = [p for p in targets if not _is_vendored_path(p)]
    dropped = [p for p in targets if _is_vendored_path(p)]
    if dropped:
        log.info(
            "evolution: dropped %d vendored/generated target(s) from a proposal: %s",
            len(dropped),
            ", ".join(dropped[:4]),
        )
    if targets and not kept:
        log.info("evolution: proposal targets only vendored/generated files; not logged")
        return 0
    payload = json.dumps(kept)

    with _db_lock:
        if not applied:
            existing = conn.execute(
                """SELECT id FROM evolution_log
                   WHERE applied = 0 AND change_type = ? AND files_changed = ? AND description = ?
                   ORDER BY id LIMIT 1""",
                (change_type, payload, description),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
        cur = conn.execute(
            """INSERT INTO evolution_log
               (agent_id, change_type, description, files_changed,
                proposal_id, applied, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_id,
                change_type,
                description,
                payload,
                proposal_id,
                1 if applied else 0,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0'''


def main() -> int:
    text = DB.read_text(encoding="utf-8")
    if text.count(HELPER_ANCHOR) != 1:
        print(f"REFUSE: anchor count {text.count(HELPER_ANCHOR)} (expected 1)")
        return 2
    if "_is_vendored_path" in text:
        print("REFUSE: already applied")
        return 2
    DB.write_text(text.replace(HELPER_ANCHOR, HELPER_REPLACE, 1), encoding="utf-8")
    print(f"WROTE {DB}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
