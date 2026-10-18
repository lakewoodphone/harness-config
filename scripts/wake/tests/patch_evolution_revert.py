#!/usr/bin/env python3
"""Give the verification a revert target, and make a measured regression restore it.

MEASURED 2026-10-18. Three separate facts, each verified:
  1. `code_self_edit` already snapshots every file it applies and RETURNS `snapshot_id`
     (50 snapshots sit in /opt/company/data/code_snapshots).
  2. `evolution_verification` has no column that can name that snapshot, and
     `create_verification()` never received it.
  3. `evolution_verifier.py` recorded a regression as status='failed' and returned.

So the code to revert EXISTED and had no target. This patch:
  * adds `snapshot_id TEXT` to evolution_verification (additive, idempotent);
  * gives create_verification a `snapshot_id` parameter and stores it;
  * adds `_restore_snapshot()`, which restores the files and REFUSES to restore
    nothing silently -- a row must never read 'reverted' over code that is still regressed;
  * replaces the record-and-return branch with restore-then-record, status 'reverted';
  * passes the real snapshot_id from app/evolution.py.

Every file is parse-checked before it is written, and each edit refuses unless its anchor
appears exactly once.
"""
import ast
import io
import sqlite3
import sys

VERIFIER = "/opt/company/app/services/evolution_verifier.py"
EVOLUTION = "/opt/company/app/evolution.py"
APP_DB = "/root/authority.db"

EDITS = []

# ---------------------------------------------------------------- verifier: imports + restore
EDITS.append((VERIFIER, '''from app.config import settings
from app.database import connect_db''', '''import os

from app.config import settings
from app.database import connect_db

# ── REVERT (2026-10-18) ─────────────────────────────────────────────────────
# A measured regression used to be recorded as `failed` and left in place. The apply
# path has ALWAYS written a code snapshot and returned its id; nothing carried that id
# as far as the measurement, so a regression had no target to revert to. The id now
# lives on the verification row and this restores it.
_LIVE_CHECKOUT_ROOT = Path(
    os.environ.get("CODE_CHECKOUT_ROOT") or str(Path(__file__).resolve().parents[2])
)


def _restore_snapshot(snapshot_id: str) -> list[str]:
    """Put every file in a code snapshot back. Returns the relative paths restored.

    Raises rather than returning an empty list on any problem: a revert that silently
    restores nothing is worse than one that fails loudly, because the row would then
    claim 'reverted' over code that is still regressed.
    """
    snap = _LIVE_CHECKOUT_ROOT / "data" / "code_snapshots" / ("%s.json" % snapshot_id)
    if not snap.is_file():
        raise FileNotFoundError("code snapshot %s not found at %s" % (snapshot_id, snap))
    payload = json.loads(snap.read_text(encoding="utf-8"))
    files = payload.get("files") or {}
    if not files:
        raise ValueError("code snapshot %s holds no files" % snapshot_id)
    root = _LIVE_CHECKOUT_ROOT.resolve()
    written: list[str] = []
    for rel, info in files.items():
        content = (info or {}).get("content")
        if not isinstance(content, str):
            raise ValueError("snapshot %s: %s carries no content" % (snapshot_id, rel))
        target = (root / rel).resolve()
        if target != root and root not in target.parents:
            raise ValueError("snapshot %s: %s escapes the checkout" % (snapshot_id, rel))
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".revert.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)
        written.append(rel)
    return written'''))

# ---------------------------------------------------------------- verifier: create_verification
EDITS.append((VERIFIER, '''def create_verification(
    proposal_id: int,
    evolution_log_id: int | None,
    target_metric: str,
    baseline_value: float,
    target_value: float | None = None,
) -> int:
    """Create a verification record for an applied proposal."""
    with _conn() as conn:
        cursor = conn.execute(
            "INSERT INTO evolution_verification "
            "(proposal_id, evolution_log_id, target_metric, baseline_value, "
            "target_value, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'measuring', ?)",
            (
                proposal_id,
                evolution_log_id,
                target_metric,
                baseline_value,
                target_value,
                _now(),
            ),
        )''', '''def create_verification(
    proposal_id: int,
    evolution_log_id: int | None,
    target_metric: str,
    baseline_value: float,
    target_value: float | None = None,
    snapshot_id: str | None = None,
) -> int:
    """Create a verification record for an applied proposal.

    `snapshot_id` names the code snapshot the apply wrote, so a later regression can be
    reverted instead of merely recorded.
    """
    with _conn() as conn:
        cursor = conn.execute(
            "INSERT INTO evolution_verification "
            "(proposal_id, evolution_log_id, target_metric, baseline_value, "
            "target_value, status, created_at, snapshot_id) "
            "VALUES (?, ?, ?, ?, ?, 'measuring', ?, ?)",
            (
                proposal_id,
                evolution_log_id,
                target_metric,
                baseline_value,
                target_value,
                _now(),
                snapshot_id,
            ),
        )'''))

# ---------------------------------------------------------------- verifier: the regression branch
EDITS.append((VERIFIER, '''            if regressed:
                conn.execute(
                    "UPDATE evolution_verification "
                    "SET status = 'failed', rollback_reason = ?, "
                    "completed_at = ? WHERE id = ?",
                    (
                        f"Regressed from {baseline} to {current_value}",
                        _now(),
                        verification_id,
                    ),
                )
                conn.commit()
                return {
                    "status": "failed",
                    "reason": "regression",
                    "baseline": baseline,
                    "current": current_value,
                }''', '''            if regressed:
                # ── REVERT FIRST, THEN RECORD (2026-10-18) ───────────────────
                snapshot_id = (
                    (row["snapshot_id"] or "").strip()
                    if "snapshot_id" in row.keys() else ""
                )
                restored: list[str] = []
                revert_err = ""
                if snapshot_id:
                    try:
                        restored = _restore_snapshot(snapshot_id)
                    except Exception as rev_exc:  # noqa: BLE001
                        revert_err = f"{type(rev_exc).__name__}: {rev_exc}"
                note = f"Regressed from {baseline} to {current_value}"
                if restored:
                    status = "reverted"
                    note += "; RESTORED " + ", ".join(restored)
                elif revert_err:
                    status = "failed"
                    note += f"; REVERT FAILED: {revert_err}"
                else:
                    status = "failed"
                    note += "; NO snapshot_id on this row, so nothing was restored"
                conn.execute(
                    "UPDATE evolution_verification "
                    "SET status = ?, rollback_reason = ?, "
                    "completed_at = ? WHERE id = ?",
                    (status, note, _now(), verification_id),
                )
                conn.commit()
                return {
                    "status": status,
                    "reason": "regression",
                    "baseline": baseline,
                    "current": current_value,
                    "restored": restored,
                    "revert_error": revert_err,
                }'''))

# ---------------------------------------------------------------- evolution.py: pass the id
EDITS.append((EVOLUTION, '''                create_verification(
                    # MEASURED 2026-10-18: this was the literal 0, so all 25 verification rows
                    # named a proposal that does not exist and no rollback could find its target.
                    # `proposal_id` is the non-empty string validated above; it is an int column.
                    proposal_id=int(proposal_id),
                    evolution_log_id=None,
                    target_metric="error_count",
                    baseline_value=float(_get_error_baseline()),
                )''', '''                create_verification(
                    # MEASURED 2026-10-18: this was the literal 0, so all 25 verification rows
                    # named a proposal that does not exist and no rollback could find its target.
                    # `proposal_id` is the non-empty string validated above; it is an int column.
                    proposal_id=int(proposal_id),
                    evolution_log_id=None,
                    target_metric="error_count",
                    baseline_value=float(_get_error_baseline()),
                    # The apply already wrote a code snapshot; without this the measurement
                    # could not revert, only apologise.
                    snapshot_id=(apply_result or {}).get("snapshot_id")
                    if isinstance(apply_result, dict) else None,
                )'''))


def main() -> int:
    failures = 0
    for path, old, new in EDITS:
        src = io.open(path, encoding="utf-8").read()
        # Idempotency: if this exact replacement is already present, there is nothing to do.
        if new in src:
            print("ALREADY-PATCHED: %s" % path)
            continue
        n = src.count(old)
        if n != 1:
            print("REFUSED: %s anchor found %d times (expected 1)" % (path, n))
            failures += 1
            continue
        out = src.replace(old, new, 1)
        try:
            ast.parse(out)
        except SyntaxError as exc:
            print("REFUSED: %s would not parse after the edit: %s" % (path, exc))
            failures += 1
            continue
        io.open(path, "w", encoding="utf-8").write(out)
        print("WROTE %s  %d -> %d bytes" % (path, len(src), len(out)))

    # ---- the column, additive and idempotent
    conn = sqlite3.connect(APP_DB, timeout=30)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(evolution_verification)")]
    if "snapshot_id" in cols:
        print("COLUMN already present: evolution_verification.snapshot_id")
    else:
        conn.execute("ALTER TABLE evolution_verification ADD COLUMN snapshot_id TEXT")
        conn.commit()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(evolution_verification)")]
        print("COLUMN added: snapshot_id -> %s" % ("snapshot_id" in cols))
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
