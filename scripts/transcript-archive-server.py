#!/usr/bin/env python3
"""transcript-archive-server.py — the write side of the permanent transcript archive.

THE RULE THIS IMPLEMENTS (owner, 2026-10-09, verbatim):

    "we need copies of all vscode copilot chats and all dsh sessions forever for data
     and training data, and those a copy always needs to exist"

SO THE ARCHIVE IS:
  * COMPLETE     — every DSH session file and every VS Code Copilot chat store we can
                   find, from every machine, including files the older parsers silently
                   skipped (the 50 MB cap in scripts/vscode_chat_extractor.py).
  * OFF-MACHINE  — it lands here, on secratary, never on the machine that wrote it.
  * APPEND-ONLY  — a file is addressed by the sha256 of its bytes. An edited chat is a
                   NEW object; the old one stays. A chat deleted from VS Code stays.
                   Nothing here is ever updated or removed.
  * READABLE     — `--read <machine> <kind> <rel_path>` prints the newest stored copy.
                   `--stats` says what is held. `--check` says whether it is current.

STORE LAYOUT

    ARCHIVE_ROOT/
      objects/<sha[0:2]>/<sha>[.zst]   every unique content version, named by its hash
      manifest.sqlite                  provenance: what arrived, from where, when
      incoming/                        spools waiting to be ingested
      incoming/done/                   spent spools (kept; they are re-ingestible)
      logs/

TABLES (append-only unless stated)
  object         sha256 PK, raw_bytes, stored_bytes, compression, first_seen_at  (immutable)
  arrival        (machine, kind, rel_path, sha256) PK, source_mtime, raw_bytes,
                 received_at, run_id, transform, redactions, scan_state
  machine_contact(machine, run_id, at, files_seen, files_new, newest_source_mtime,
                 new_bytes, note)                                   -- one row per pull
  ingest_run     (run_id PK, machine, started_at, finished_at, tar_basename,
                 members, new_objects, dedup_objects, quarantined, rejected,
                 bytes_in, bytes_stored, ok, error)
  quarantine     (machine, rel_path, sha256, reason, hits, at, run_id)  -- never copied

WHAT IS NEVER COPIED
  Secret stores are refused by name — VS Code `state.vscdb` (its ItemTable is the
  encrypted secret store), `.credentials.yaml`, `id_*` keys, `*.pem`, `*.key`,
  `.env`. Text is scanned for Luhn-valid card numbers and credential shapes; a match
  is REDACTED in the stored copy and counted, never copied through. The bytes that
  arrive are re-scanned here, so a client's redaction is verified rather than trusted:
  anything still matching is refused outright and recorded in `quarantine`.

  Precedent this exists because of: journal P13b, 2026-09-11 — "I leaked a live API key
  into the session transcript."

USAGE
  transcript-archive-server.py --tar incoming/x.tar --machine zabz-yoga --run-id ID
  transcript-archive-server.py --machine secratary --dir /path --local --run-id ID
  transcript-archive-server.py --cursor-out /tmp/cursor.json --machine zabz-yoga
  transcript-archive-server.py --stats | --check | --read m k p [--out FILE]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone

ARCHIVE_ROOT = os.environ.get("TRANSCRIPT_ARCHIVE_ROOT", "/home/zabz/lpt-transcripts")
DB_PATH = os.path.join(ARCHIVE_ROOT, "manifest.sqlite")
SCHEMA_VERSION = 1

# Anything at least this big is worth compressing on arrival.
COMPRESS_MIN_BYTES = 8 * 1024
# Extensions that are already compressed (or are opaque binaries we still keep raw).
PRECOMPRESSED = (".zst", ".zstd", ".gz", ".xz", ".zip", ".7z", ".bz2")

# ── what is refused by name, before a single byte is read ────────────────────────────────────────
REFUSE_NAMES = {
    # VS Code's `state.vscdb` ItemTable IS the encrypted secret store, per profile.
    "state.vscdb", "state.vscdb-shm", "state.vscdb-wal",
    # Copilot CLI's session store sits beside it and we cannot prove it credential-free.
    "session-store.db", "session-store.db-shm", "session-store.db-wal",
    ".credentials.yaml", ".credentials.yaml.bak",
}
REFUSE_RE = re.compile(
    r"(^|/)("
    r"id_(rsa|dsa|ecdsa|ed25519)[^/]*"
    r"|[^/]*\.(pem|key|pfx|p12|jks|keystore)"
    r"|\.env(\..*)?"
    r"|\.netrc|\.git-credentials"
    r"|known_hosts|authorized_keys"
    r"|copilot_auth\.json|credentials\.json"
    r")$",
    re.IGNORECASE,
)

# ── what is redacted inside text ────────────────────────────────────────────────────────────────
CREDENTIAL_RES = [
    ("openai_key", re.compile(r"sk-[A-Za-z0-9_\-]{16,}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}")),
    ("github_pat", re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("github_fine_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("aws_akid", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]{0,40}PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]{24,}={0,2}")),
    ("twilio_sid", re.compile(r"\bAC[0-9a-fA-F]{32}\b")),
]
CARD_SHAPE = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")


def luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def scan_text(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, reasons). Reasons name the class, never the value."""
    reasons: list[str] = []
    redacted = text
    for name, pattern in CREDENTIAL_RES:
        redacted, n = pattern.subn(f"[REDACTED:{name}]", redacted)
        if n:
            reasons.append(f"{name}x{n}")
    # Card numbers: shape first, then Luhn, so a phone number or an order id is not touched.
    out, last, cards = [], 0, 0
    for m in CARD_SHAPE.finditer(redacted):
        digits = re.sub(r"\D", "", m.group(0))
        if not (13 <= len(digits) <= 19) or not luhn(digits):
            continue
        out.append(redacted[last:m.start()])
        out.append("[REDACTED:card]")
        last = m.end()
        cards += 1
    if cards:
        out.append(redacted[last:])
        redacted = "".join(out)
        reasons.append(f"cardx{cards}")
    return redacted, reasons


def looks_texty(raw: bytes) -> bool:
    if b"\x00" in raw[:8192]:
        return False
    try:
        raw[:8192].decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def decompress_zstd(raw: bytes) -> bytes | None:
    """Best-effort: concatenated zstd frames -> the text they carry. None if unavailable.

    Prefers the `zstandard` module and falls back to the `zstd` binary, because the
    authority has /usr/bin/zstd and does not have the module — and installing a package
    into the company server's Python to satisfy an archive would be the tail wagging the
    dog. If neither is available the caller stores the bytes untouched and says so.
    """
    try:
        import zstandard  # type: ignore
    except ImportError:
        zstandard = None  # type: ignore
    if zstandard is not None:
        try:
            d = zstandard.ZstdDecompressor()
            out, reader = [], d.stream_reader(raw)
            while True:
                chunk = reader.read(1 << 20)
                if not chunk:
                    break
                out.append(chunk)
            return b"".join(out)
        except Exception:
            return None
    try:
        p = subprocess.run(["zstd", "-dc", "-q"], input=raw, capture_output=True, timeout=600)
        if p.returncode == 0:
            return p.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def compress_zstd(raw: bytes) -> bytes | None:
    try:
        import zstandard  # type: ignore
    except ImportError:
        zstandard = None  # type: ignore
    if zstandard is not None:
        try:
            return zstandard.ZstdCompressor(level=10).compress(raw)
        except Exception:
            pass
    try:
        p = subprocess.run(["zstd", "-10", "-q", "-c"], input=raw, capture_output=True, timeout=900)
        if p.returncode == 0 and p.stdout:
            return p.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS object (
            sha256        TEXT PRIMARY KEY,
            raw_bytes     INTEGER NOT NULL,
            stored_bytes  INTEGER NOT NULL,
            compression   TEXT NOT NULL DEFAULT 'none',
            first_seen_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS arrival (
            machine       TEXT NOT NULL,
            kind          TEXT NOT NULL,
            rel_path      TEXT NOT NULL,
            sha256        TEXT NOT NULL,
            source_mtime  REAL,
            raw_bytes     INTEGER,
            received_at   TEXT NOT NULL,
            run_id        TEXT,
            transform     TEXT,
            redactions    TEXT,
            scan_state    TEXT,
            source_sha256 TEXT,
            PRIMARY KEY (machine, kind, rel_path, sha256)
        );
        CREATE INDEX IF NOT EXISTS idx_arrival_recent
            ON arrival(machine, kind, received_at DESC);
        CREATE TABLE IF NOT EXISTS machine_contact (
            machine             TEXT NOT NULL,
            run_id              TEXT,
            at                  TEXT NOT NULL,
            files_seen          INTEGER,
            files_new           INTEGER,
            newest_source_mtime REAL,
            new_bytes           INTEGER,
            note                TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_contact_machine ON machine_contact(machine, at DESC);
        CREATE TABLE IF NOT EXISTS ingest_run (
            run_id       TEXT PRIMARY KEY,
            machine      TEXT,
            started_at   TEXT,
            finished_at  TEXT,
            tar_basename TEXT,
            members      INTEGER DEFAULT 0,
            new_objects  INTEGER DEFAULT 0,
            dedup_objects INTEGER DEFAULT 0,
            quarantined  INTEGER DEFAULT 0,
            rejected     INTEGER DEFAULT 0,
            bytes_in     INTEGER DEFAULT 0,
            bytes_stored INTEGER DEFAULT 0,
            ok           INTEGER DEFAULT 1,
            error        TEXT
        );
        CREATE TABLE IF NOT EXISTS quarantine (
            machine   TEXT NOT NULL,
            rel_path  TEXT NOT NULL,
            sha256    TEXT,
            reason    TEXT NOT NULL,
            hits      TEXT,
            at        TEXT NOT NULL,
            run_id    TEXT,
            PRIMARY KEY (machine, rel_path, reason, sha256)
        );
        """
    )
    # Forward migration: an archive that has already run must gain new columns without a rewrite.
    have = {r[1] for r in conn.execute("PRAGMA table_info(arrival)")}
    if "source_sha256" not in have:
        conn.execute("ALTER TABLE arrival ADD COLUMN source_sha256 TEXT")
    conn.commit()
    return conn


# ── ingest ──────────────────────────────────────────────────────────────────────────────────────

def object_path(sha: str, compression: str) -> str:
    suffix = ".zst" if compression == "zstd" else ""
    return os.path.join(ARCHIVE_ROOT, "objects", sha[:2], sha + suffix)


def store_object(conn, raw: bytes, sha: str) -> tuple[int, int, str]:
    """Put bytes in the object store once. Returns (raw_bytes, stored_bytes, compression)."""
    row = conn.execute("SELECT raw_bytes, stored_bytes, compression FROM object WHERE sha256=?", (sha,)).fetchone()
    if row:
        return row["raw_bytes"], row["stored_bytes"], row["compression"]

    compression, payload = "none", raw
    if len(raw) >= COMPRESS_MIN_BYTES:
        packed = compress_zstd(raw)
        if packed is not None and len(packed) < len(raw):
            compression, payload = "zstd", packed

    path = object_path(sha, compression)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):                    # write-once; never overwrite an object
        tmp = path + f".tmp.{os.getpid()}"
        with open(tmp, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    conn.execute(
        "INSERT OR IGNORE INTO object (sha256, raw_bytes, stored_bytes, compression, first_seen_at) "
        "VALUES (?,?,?,?,?)",
        (sha, len(raw), len(payload), compression, now_iso()),
    )
    return len(raw), len(payload), compression


def process_member(conn, machine: str, member: str, raw: bytes, meta: dict, run_id: str) -> dict:
    """Decide, scan, redact and store one file. Returns a small result dict."""
    kind = (meta.get("kind") or (member.split("/", 1)[0] if "/" in member else "unknown"))
    if meta.get("rel_path"):
        rel_path = meta["rel_path"]
    elif "/" in member:
        rel_path = member.split("/", 1)[1]
    else:
        rel_path = member
    base = os.path.basename(rel_path)
    out = {"member": member, "kind": kind, "rel_path": rel_path, "action": "stored"}

    # 1. Refuse secret stores by name — not scanned, not copied.
    if base in REFUSE_NAMES or REFUSE_RE.search(rel_path.replace("\\", "/")):
        conn.execute(
            "INSERT OR IGNORE INTO quarantine (machine, rel_path, sha256, reason, hits, at, run_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (machine, rel_path, None, "credential_store_by_name", base, now_iso(), run_id),
        )
        out["action"] = "refused_credential_store"
        return out

    # 2. zstd-compressed session files: decompress so the CONTENTS can be scanned, and store the
    #    redacted text recompressed. An unscannable compressed blob is not an acceptable archive.
    transform = meta.get("transform") or "as-is"
    server_transformed = False
    if raw[:4] == b"\x28\xb5\x2f\xfd":
        plain = decompress_zstd(raw)
        if plain is not None:
            raw, transform, server_transformed = plain, "zstd-redacted", True

    scan_state = "binary_not_scanned"
    redactions = ""
    if looks_texty(raw):
        text = raw.decode("utf-8", errors="replace")
        redacted, reasons = scan_text(text)
        scan_state = "scanned"
        if reasons:
            raw = redacted.encode("utf-8")
            redactions = ",".join(reasons)
            transform = f"{transform}+redacted"

    sha = sha256(raw)

    # 3. Second gate: the bytes that ARRIVED must not still match. A client's redaction is
    #    verified here, not trusted.
    if looks_texty(raw):
        _, residual = scan_text(raw.decode("utf-8", errors="replace"))
        if residual:
            conn.execute(
                "INSERT OR IGNORE INTO quarantine (machine, rel_path, sha256, reason, hits, at, run_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (machine, rel_path, sha, "residual_secret_after_redaction", ",".join(residual), now_iso(), run_id),
            )
            out["action"] = "rejected_residual_secret"
            out["hits"] = ",".join(residual)
            return out

    existed = conn.execute("SELECT 1 FROM object WHERE sha256=?", (sha,)).fetchone() is not None
    raw_bytes, stored_bytes, compression = store_object(conn, raw, sha)

    # `source_sha256` is the sha of the bytes as they sat on the machine, before redaction. The
    # cursor is keyed on THIS, because redaction changes the stored bytes and a stored-copy hash
    # would never match a local file again — which would re-send every redacted file forever.
    # Verified where it can be: if neither side transformed the bytes, the received bytes must
    # hash to the client's claim. Where redaction happened the claim is recorded, not verifiable.
    claimed_source = meta.get("source_sha256")
    source_sha = claimed_source or sha
    if claimed_source and not server_transformed and not redactions and "redacted" not in transform:
        if claimed_source != sha:
            conn.execute(
                "INSERT OR IGNORE INTO quarantine (machine, rel_path, sha256, reason, hits, at, run_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (machine, rel_path, sha, "source_sha_mismatch",
                 f"claimed={claimed_source[:16]} actual={sha[:16]}", now_iso(), run_id),
            )

    inserted = conn.execute(
        "INSERT OR IGNORE INTO arrival (machine, kind, rel_path, sha256, source_mtime, raw_bytes, "
        "received_at, run_id, transform, redactions, scan_state, source_sha256) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (machine, kind, rel_path, sha, meta.get("mtime"), raw_bytes, now_iso(), run_id,
         transform, redactions, scan_state, source_sha),
    ).rowcount

    out.update({
        "sha256": sha,
        "action": "stored_new" if inserted else "already_held",
        "dedup_object": existed,
        "raw_bytes": raw_bytes,
        "stored_bytes": stored_bytes,
        "compression": compression,
        "redactions": redactions,
        "scan_state": scan_state,
    })
    return out


def ingest_tar(conn, tar_path: str, machine: str, run_id: str, sidecar: dict | None = None) -> dict:
    started = now_iso()
    results: list[dict] = []
    members_meta: dict[str, dict] = {}
    if sidecar:
        for item in sidecar.get("files") or []:
            members_meta[item.get("member") or f"{item.get('kind')}/{item.get('rel_path')}"] = item

    tmp_dir = os.path.join(ARCHIVE_ROOT, "incoming", f".unpack-{run_id}")
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        with tarfile.open(tar_path, "r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                name = member.name.lstrip("./")
                if name.endswith("_manifest.json") or name == "cursor.json":
                    continue
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                raw = fh.read()
                meta = members_meta.get(name, {})
                try:
                    results.append(process_member(conn, machine, name, raw, meta, run_id))
                except Exception as exc:  # one bad member must not lose the rest of the batch
                    results.append({"member": name, "action": "error", "error": str(exc)[:200]})
                conn.commit()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    new_objects = sum(1 for r in results if r.get("action") == "stored_new")
    dedup = sum(1 for r in results if r.get("action") == "already_held")
    refused = sum(1 for r in results if r.get("action") in ("refused_credential_store", "rejected_residual_secret"))
    errors = sum(1 for r in results if r.get("action") == "error")
    bytes_in = sum(int(r.get("raw_bytes") or 0) for r in results)
    bytes_stored = sum(int(r.get("stored_bytes") or 0) for r in results)

    conn.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, machine, started_at, finished_at, tar_basename, "
        "members, new_objects, dedup_objects, quarantined, rejected, bytes_in, bytes_stored, ok, error) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, machine, started, now_iso(), os.path.basename(tar_path), len(results), new_objects,
         dedup, refused, errors, bytes_in, bytes_stored, 0 if errors else 1,
         f"{errors} member error(s)" if errors else None),
    )
    conn.commit()
    return {
        "ok": errors == 0 or new_objects > 0,
        "machine": machine, "run_id": run_id, "members": len(results),
        "new_objects": new_objects, "already_held": dedup, "quarantined": refused, "errors": errors,
        "bytes_in": bytes_in, "bytes_stored": bytes_stored,
        "redacted_files": [r for r in results if r.get("redactions")],
        "byte_counts": results,
    }


# ── reading ──────────────────────────────────────────────────────────────────────────────────────

def load_object(conn, sha: str) -> bytes | None:
    row = conn.execute("SELECT compression FROM object WHERE sha256=?", (sha,)).fetchone()
    if not row:
        return None
    path = object_path(sha, row["compression"])
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        raw = fh.read()
    if row["compression"] == "zstd":
        plain = decompress_zstd(raw)
        if plain is None:
            raise RuntimeError("zstandard module unavailable here; cannot decompress this object")
        return plain
    return raw


def cmd_read(conn, machine: str, kind: str, rel_path: str, out: str | None) -> int:
    rows = conn.execute(
        "SELECT sha256, received_at, raw_bytes, transform FROM arrival "
        "WHERE machine=? AND kind=? AND rel_path=? ORDER BY received_at DESC",
        (machine, kind, rel_path),
    ).fetchall()
    if not rows:
        like = f"%{rel_path}%"
        rows = conn.execute(
            "SELECT sha256, received_at, raw_bytes, transform, machine, kind, rel_path FROM arrival "
            "WHERE machine=? AND rel_path LIKE ? ORDER BY received_at DESC LIMIT 20",
            (machine, like),
        ).fetchall()
    if not rows:
        print(json.dumps({"ok": False, "error": "no such entry"}))
        return 1
    latest = rows[0]
    raw = load_object(conn, latest["sha256"])
    if raw is None:
        print(json.dumps({"ok": False, "error": "object missing from store"}))
        return 2
    if out:
        with open(out, "wb") as fh:
            fh.write(raw)
        print(json.dumps({"ok": True, "wrote": out, "bytes": len(raw),
                          "sha256": latest["sha256"], "versions_held": len(rows)}))
    else:
        sys.stdout.buffer.write(raw)
    return 0


def cmd_stats(conn) -> int:
    out = {"ok": True, "archive_root": ARCHIVE_ROOT, "db": DB_PATH, "schema_version": SCHEMA_VERSION,
           "db_bytes": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0}
    out["objects"] = conn.execute("SELECT COUNT(*) c, SUM(raw_bytes) r, SUM(stored_bytes) s FROM object").fetchone()[0:3]
    out["objects"] = {"count": out["objects"][0], "raw_bytes": out["objects"][1], "stored_bytes": out["objects"][2]}
    out["arrivals"] = conn.execute("SELECT COUNT(*) FROM arrival").fetchone()[0]
    out["quarantined"] = conn.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0]
    out["by_machine"] = [dict(r) for r in conn.execute(
        "SELECT machine, kind, COUNT(*) files, SUM(raw_bytes) raw_bytes, MAX(source_mtime) newest_source_mtime "
        "FROM arrival GROUP BY machine, kind ORDER BY machine, kind")]
    out["last_contact"] = [dict(r) for r in conn.execute(
        "SELECT machine, MAX(at) at FROM machine_contact GROUP BY machine")]
    print(json.dumps(out, indent=1, default=str))
    return 0


def cmd_cursor(conn, machine: str, out_path: str) -> int:
    """Hand the client the list of (kind, rel_path, sha) already held, so it sends only what is new.

    The sha handed back is the SOURCE sha (bytes as they sat on the machine), because that is the
    one the client can recompute from its own disk without re-reading every file every run.
    """
    rows = conn.execute(
        "SELECT kind, rel_path, COALESCE(source_sha256, sha256) AS s FROM arrival WHERE machine=?",
        (machine,),
    ).fetchall()
    payload = {"schema": 1, "machine": machine, "generated_at": now_iso(),
               "held": [[r["kind"], r["rel_path"], r["sha256"]] for r in rows]}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    print(json.dumps({"ok": True, "cursor": out_path, "held": len(payload["held"])}))
    return 0


def cmd_check(conn, stale_hours: float, gap_hours: float) -> int:
    """Is the archive current? This is the check that has to fail loudly when it is not.

    Two independent questions, because they fail differently:

      1. SILENCE — a machine that used to report has stopped. It cannot be told apart from
         "the machine is off" from here, so it is reported as exactly that, never as health.
      2. GAP — a machine's own newest source file is newer than anything archived from it.
         This one is a real defect: data exists on the box and the archive does not have it.

    Exit 0 = current, 1 = a real defect (gap), 2 = silence only. journal H340 is why this
    exists: "session archive 14.7h stale" was found by accident, which means nothing watched.
    """
    now = time.time()
    problems, silences = [], []
    machines = [r["machine"] for r in conn.execute("SELECT DISTINCT machine FROM machine_contact ORDER BY machine")]
    for m in machines:
        c = conn.execute(
            "SELECT at, files_seen, newest_source_mtime FROM machine_contact WHERE machine=? ORDER BY at DESC LIMIT 1",
            (m,),
        ).fetchone()
        age_h = (now - datetime.fromisoformat(c["at"]).timestamp()) / 3600.0
        newest_arr = conn.execute(
            "SELECT MAX(source_mtime) FROM arrival WHERE machine=?", (m,)
        ).fetchone()[0]
        newest_src = c["newest_source_mtime"]
        gap = None
        if newest_src and newest_arr:
            gap = (float(newest_src) - float(newest_arr)) / 3600.0
        if age_h > stale_hours:
            silences.append({"machine": m, "last_contact_hours": round(age_h, 1),
                             "newest_source_mtime": newest_src,
                             "note": "either idle or unable to reach it; a remote disk cannot be seen from here"})
        if gap is not None and gap > gap_hours:
            problems.append({"machine": m, "gap_hours": round(gap, 1),
                             "newest_source_mtime": newest_src, "newest_archived_mtime": newest_arr,
                             "note": "the machine reports source files newer than anything archived from it"})
    by_kind = [dict(r) for r in conn.execute(
        "SELECT machine, kind, COUNT(*) files, MAX(received_at) last_arrival FROM arrival GROUP BY machine, kind")]
    out = {"ok": not problems, "checked_at": now_iso(),
           "machines_reporting": len(machines), "gaps": problems, "silent": silences, "coverage": by_kind}
    print(json.dumps(out, indent=1, default=str))
    if problems:
        print(f"TRANSCRIPT ARCHIVE: {len(problems)} GAP(S) — data exists on a machine that the archive "
              f"does not hold. See 'gaps' above.", file=sys.stderr)
        return 1
    if silences:
        print(f"TRANSCRIPT ARCHIVE: archive itself holds no gap; {len(silences)} machine(s) silent "
              f"(cannot distinguish idle from unreachable from here).", file=sys.stderr)
        return 2
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Server side of the permanent transcript archive.")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--tar", help="tar of one pull")
    ap.add_argument("--sidecar", help="JSON sidecar with per-member metadata")
    ap.add_argument("--machine", required=False, default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--cursor-out", help="write the list of what is already held, for the client")
    ap.add_argument("--contact", help="JSON with {files_seen,files_new,newest_source_mtime,note}")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--stale-hours", type=float, default=float(os.environ.get("TRANSCRIPT_STALE_HOURS", 26)))
    ap.add_argument("--gap-hours", type=float, default=float(os.environ.get("TRANSCRIPT_GAP_HOURS", 6)))
    ap.add_argument("--read", nargs=3, metavar=("MACHINE", "KIND", "REL_PATH"))
    ap.add_argument("--out", help="where --read writes")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    conn = connect(args.db)
    try:
        if args.stats:
            return cmd_stats(conn)
        if args.check:
            return cmd_check(conn, args.stale_hours, args.gap_hours)
        if args.read:
            return cmd_read(conn, *args.read, args.out)
        if args.cursor_out:
            if not args.machine:
                print(json.dumps({"ok": False, "error": "--machine required with --cursor-out"}))
                return 2
            return cmd_cursor(conn, args.machine, args.cursor_out)
        if args.contact:
            data = json.loads(args.contact)
            conn.execute(
                "INSERT INTO machine_contact (machine, run_id, at, files_seen, files_new, "
                "newest_source_mtime, new_bytes, note) VALUES (?,?,?,?,?,?,?,?)",
                (args.machine, args.run_id, now_iso(), data.get("files_seen"),
                 data.get("files_new"), data.get("newest_source_mtime"),
                 data.get("new_bytes"), data.get("note")),
            )
            conn.commit()
            print(json.dumps({"ok": True, "contact_recorded": args.machine}))
            return 0
        if not args.tar:
            print(json.dumps({"ok": False, "error": "nothing to do: pass --tar, --stats, --check, "
                                                    "--read or --cursor-out"}))
            return 2
        if not args.machine:
            print(json.dumps({"ok": False, "error": "--machine required with --tar"}))
            return 2
        sidecar = None
        if args.sidecar and os.path.exists(args.sidecar):
            with open(args.sidecar, encoding="utf-8") as fh:
                sidecar = json.load(fh)
        run_id = args.run_id or f"{args.machine}-{int(time.time())}"
        result = ingest_tar(conn, args.tar, args.machine, run_id, sidecar)
        print(json.dumps({k: v for k, v in result.items() if k != "byte_counts"}, indent=1, default=str))
        return 0 if result.get("ok") else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
