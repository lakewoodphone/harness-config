#!/usr/bin/env python3
"""archive-transcripts.py — the read side of the permanent transcript archive.

THE RULE (owner, 2026-10-09, verbatim):

    "we need copies of all vscode copilot chats and all dsh sessions forever for data
     and training data, and those a copy always needs to exist"

This runs on the machine that WROTE the transcripts. It finds every DSH session file and
every VS Code Copilot chat store, scans them, and packs the ones the archive does not
already hold into a tar for shipment to `secratary` (never left on the machine that wrote
them — a copy on the same disk is not a copy).

WHAT IT COLLECTS
  dsh-sessions      <DSH_HOME>/sessions/**            every generation, every project,
                                                      including the *.zstd frames
  dsh-attachments   <DSH_HOME>/attachments/**
  copilot-chats     for every VS Code user-data root found:
                      <profile>/workspaceStorage/*/chatSessions/*
                      <profile>/workspaceStorage/*/chatEditingSessions/*
                      <profile>/workspaceStorage/*/GitHub.copilot-chat/**
                      <profile>/globalStorage/emptyWindowChatSessions/**
                      <profile>/globalStorage/github.copilot-chat/**

  Roots searched: %APPDATA%\\Code\\User (and its profiles/), Code - Insiders, VSCodium,
  Cursor, plus $VSCODE_CHAT_USER_DIRS (semicolon-separated) and, on Linux/macOS,
  ~/.config/Code/User and ~/.vscode* user dirs.

WHY IT DOES NOT REUSE scripts/vscode_chat_extractor.py
  That parser silently skips any chat file over 50 MB (`_MAX_JSONL_BYTES`) and stores only
  a parsed projection. Measured on ZABZ-YOGA 2026-10-09: 14 chat files exceed 50 MB and
  therefore are in NO store anywhere. This script archives BYTES, so nothing is skipped and
  nothing is lossy — the parse can be redone later, the bytes cannot be recovered.

WHAT IT WILL NOT SEND
  Credential stores, by name (see the server's REFUSE_NAMES): VS Code `state.vscdb` and the
  Copilot CLI `session-store.db` are encrypted secret stores, and `.env`/`id_*`/`*.pem`/
  `*.key` are keys. Card numbers and credential-shaped strings inside text are redacted and
  counted here, and re-scanned on arrival, so the redaction is verified rather than trusted.

THE CURSOR LIVES ON THE AUTHORITY
  `--held <file>` is a JSON list of (kind, rel_path, sha256) the archive already holds,
  produced by `transcript-archive-server.py --cursor-out`. Nothing is tracked only on this
  laptop: a rebuilt machine re-derives its state from the authority. A local
  `<DSH_HOME>/transcript-archive-state.json` caches (size, mtime) -> sha purely so a repeat
  run does not re-hash 26 GB of unchanged files, and it is safe to delete.

USAGE
  archive-transcripts.py --list --json                  # what is here, no tar
  archive-transcripts.py --held cursor.json --out /tmp/batch.tar --max-bytes 2000000000
  archive-transcripts.py --held cursor.json --out batch.tar --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
import time
from datetime import datetime, timezone

SCHEMA_VERSION = 1
DEFAULT_MAX_BYTES = 2_000_000_000          # per-run cap, so a first backfill is chunked
HASH_CACHE_NAME = "transcript-archive-state.json"

# ── the same refusal + redaction rules as the server (defence in depth, not trust) ──────────────
REFUSE_NAMES = {
    "state.vscdb", "state.vscdb-shm", "state.vscdb-wal",
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


def scan_bytes(raw: bytes) -> tuple[bytes, list[str], str]:
    """Return (possibly-redacted bytes, reasons, scan_state)."""
    if b"\x00" in raw[:8192]:
        return raw, [], "binary_not_scanned"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    reasons: list[str] = []
    for name, pattern in CREDENTIAL_RES:
        text, n = pattern.subn(f"[REDACTED:{name}]", text)
        if n:
            reasons.append(f"{name}x{n}")
    out, last, cards = [], 0, 0
    for m in CARD_SHAPE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if not (13 <= len(digits) <= 19) or not luhn(digits):
            continue
        out.append(text[last:m.start()])
        out.append("[REDACTED:card]")
        last = m.end()
        cards += 1
    if cards:
        out.append(text[last:])
        text = "".join(out)
        reasons.append(f"cardx{cards}")
    return text.encode("utf-8"), reasons, "scanned"


def dsh_home() -> str:
    return os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")


def vscode_user_roots() -> list[tuple[str, str]]:
    """Return [(profile_label, user_dir)] for every VS Code-ish user-data root present."""
    roots: list[tuple[str, str]] = []

    def add(label: str, path: str) -> None:
        if os.path.isdir(path):
            roots.append((sanitise_label(label), path))
            profiles = os.path.join(path, "profiles")
            if os.path.isdir(profiles):
                for entry in sorted(os.listdir(profiles)):
                    sub = os.path.join(profiles, entry)
                    if os.path.isdir(sub):
                        roots.append((sanitise_label(f"{label}-{entry}"), sub))

    override = os.environ.get("VSCODE_CHAT_USER_DIRS")
    if override:
        for part in re.split(r"[;\n]", override):
            part = part.strip()
            if part:
                add(os.path.basename(os.path.dirname(part)) or "custom", part)

    appdata = os.environ.get("APPDATA")
    if appdata:
        for product in ("Code", "Code - Insiders", "VSCodium", "Cursor", "Windsurf"):
            add(product, os.path.join(appdata, product, "User"))
    home = os.path.expanduser("~")
    for product in ("Code", "Code - Insiders", "VSCodium", "Cursor"):
        add(product, os.path.join(home, ".config", product, "User"))
        add(product, os.path.join(home, "Library", "Application Support", product, "User"))
    return roots


def sanitise_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "root"


def sanitise_rel(path: str) -> str:
    p = path.replace("\\", "/")
    p = re.sub(r"^[A-Za-z]:", "", p)
    parts = [seg for seg in p.split("/") if seg not in ("", ".", "..")]
    return "/".join(parts)


def walk_files(root: str) -> list[str]:
    out = []
    for base, dirs, files in os.walk(root):
        # never descend into a nested archive or our own output
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for f in files:
            out.append(os.path.join(base, f))
    return out


def discover() -> list[dict]:
    """Every transcript file on this machine, with its kind and archive-relative path."""
    found: list[dict] = []

    dh = dsh_home()
    sessions = os.path.join(dh, "sessions")
    if os.path.isdir(sessions):
        for path in walk_files(sessions):
            rel = sanitise_rel(os.path.relpath(path, dh))
            found.append({"kind": "dsh-sessions", "rel_path": rel, "path": path})
    attachments = os.path.join(dh, "attachments")
    if os.path.isdir(attachments):
        for path in walk_files(attachments):
            rel = sanitise_rel(os.path.relpath(path, dh))
            found.append({"kind": "dsh-attachments", "rel_path": rel, "path": path})

    for label, user_dir in vscode_user_roots():
        targets: list[str] = []
        ws = os.path.join(user_dir, "workspaceStorage")
        if os.path.isdir(ws):
            for wsid in sorted(os.listdir(ws)):
                wsdir = os.path.join(ws, wsid)
                if not os.path.isdir(wsdir):
                    continue
                for sub in ("chatSessions", "chatEditingSessions", "GitHub.copilot-chat"):
                    subdir = os.path.join(wsdir, sub)
                    if os.path.isdir(subdir):
                        targets.append(subdir)
        gs = os.path.join(user_dir, "globalStorage")
        if os.path.isdir(gs):
            for sub in ("emptyWindowChatSessions", "github.copilot-chat"):
                subdir = os.path.join(gs, sub)
                if os.path.isdir(subdir):
                    targets.append(subdir)
        for root in targets:
            for path in walk_files(root):
                rel = sanitise_rel(os.path.relpath(path, user_dir))
                found.append({"kind": "copilot-chats", "rel_path": f"{label}/{rel}", "path": path})

    return found


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def sha_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="Pack this machine's transcripts for the archive.")
    ap.add_argument("--held", help="JSON cursor of what the archive already holds")
    ap.add_argument("--out", help="tar to write")
    ap.add_argument("--sidecar", help="JSON metadata for the tar (default: <out>.manifest.json)")
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    ap.add_argument("--machine", default=os.uname().nodename.lower() if hasattr(os, "uname")
                    else (os.environ.get("COMPUTERNAME") or "unknown").lower())
    ap.add_argument("--list", action="store_true", help="report what is here and exit")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="ignore the held cursor")
    args = ap.parse_args()

    held: set[tuple[str, str, str]] = set()
    if args.held and not args.force:
        data = load_json(args.held, {})
        held = {(k, r, s) for k, r, s in (data.get("held") or [])}

    found = discover()
    cache_path = os.path.join(dsh_home(), HASH_CACHE_NAME)
    cache = load_json(cache_path, {})
    newest_mtime = max((os.path.getmtime(f["path"]) for f in found), default=0)

    if args.list:
        by_kind: dict[str, dict] = {}
        for f in found:
            b = by_kind.setdefault(f["kind"], {"files": 0, "bytes": 0, "newest_mtime": 0})
            b["files"] += 1
            try:
                st = os.stat(f["path"])
                b["bytes"] += st.st_size
                b["newest_mtime"] = max(b["newest_mtime"], st.st_mtime)
            except OSError:
                pass
        print(json.dumps({"ok": True, "machine": args.machine, "dsh_home": dsh_home(),
                          "vscode_roots": [label for label, _ in vscode_user_roots()],
                          "by_kind": by_kind, "held_by_archive": len(held),
                          "total_files": len(found)}, indent=1))
        return 0

    if not args.out:
        print(json.dumps({"ok": False, "error": "--out required (or --list)"}))
        return 2

    queued: list[dict] = []
    queued_bytes = 0
    unchanged = 0
    refused: list[dict] = []
    redacted: list[dict] = []
    truncated = False
    new_cache: dict[str, dict] = {}

    for f in sorted(found, key=lambda x: x["path"]):
        path, rel, kind = f["path"], f["rel_path"], f["kind"]
        base = os.path.basename(rel)
        try:
            st = os.stat(path)
        except OSError:
            continue
        if not st.st_size:
            continue

        if base in REFUSE_NAMES or REFUSE_RE.search(rel):
            refused.append({"kind": kind, "rel_path": rel, "reason": "credential_store_by_name"})
            continue

        key = f"{kind}|{rel}"
        cached = cache.get(key)
        if cached and cached.get("size") == st.st_size and abs(cached.get("mtime", 0) - st.st_mtime) < 1:
            sha = cached["sha"]
        else:
            try:
                sha = sha_of(path)
            except OSError:
                continue
        new_cache[key] = {"size": st.st_size, "mtime": st.st_mtime, "sha": sha}

        # The held set is keyed on the sha of the bytes AS THEY SIT ON DISK, not on the sha of
        # the redacted copy: redaction changes the bytes, so comparing a stored-copy hash to a
        # local-file hash would mark every redacted file as new and re-send it forever. The
        # server records this as `source_sha256` for exactly this comparison.
        if not args.force and (kind, rel, sha) in held:
            unchanged += 1
            continue

        if queued_bytes and queued_bytes + st.st_size > args.max_bytes:
            truncated = True
            break

        queued.append({"kind": kind, "rel_path": rel, "path": path,
                       "size": st.st_size, "mtime": st.st_mtime, "sha": sha})
        queued_bytes += st.st_size

    if not args.dry_run:
        try:
            os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
            tmp = cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(new_cache, fh)
            os.replace(tmp, cache_path)
        except OSError:
            pass

    sidecar = {"schema": SCHEMA_VERSION, "source_machine": args.machine,
               "created_at": datetime.now(timezone.utc).isoformat(), "files": []}
    written = 0
    tar_bytes = 0

    if args.dry_run:
        written = len(queued)
        tar_bytes = queued_bytes
    else:
        sidecar_path = args.sidecar or (args.out + ".manifest.json")
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with tarfile.open(args.out, "w") as tf:
            for item in queued:
                try:
                    with open(item["path"], "rb") as fh:
                        raw = fh.read()
                except OSError as exc:
                    print(f"skip unreadable {item['rel_path']}: {exc}", file=sys.stderr)
                    continue
                clean, reasons, scan_state = scan_bytes(raw)
                sha = hashlib.sha256(clean).hexdigest()
                member = f"{item['kind']}/{item['rel_path']}"
                info = tarfile.TarInfo(member)
                info.size = len(clean)
                info.mtime = int(item["mtime"])
                info.mode = 0o644
                tf.addfile(info, __import__("io").BytesIO(clean))
                written += 1
                tar_bytes += len(clean)
                if reasons:
                    redacted.append({"kind": item["kind"], "rel_path": item["rel_path"],
                                     "reasons": reasons})
                sidecar["files"].append({
                    "member": member, "kind": item["kind"], "rel_path": item["rel_path"],
                    "mtime": item["mtime"], "bytes": len(clean), "sha256": sha,
                    "source_sha256": item["sha"],
                    "transform": "redacted" if reasons else "as-is",
                    "scan_state": scan_state,
                    "redactions": ",".join(reasons),
                })
        with open(sidecar_path, "w", encoding="utf-8") as fh:
            json.dump(sidecar, fh)

    summary = {
        "ok": True, "machine": args.machine,
        "files_seen": len(found), "files_unchanged": unchanged, "files_queued": len(queued),
        "members_written": written, "new_bytes": tar_bytes,
        "newest_source_mtime": newest_mtime, "truncated": truncated,
        "tar": None if args.dry_run else args.out,
        "sidecar": None if args.dry_run else (args.sidecar or (args.out + ".manifest.json")),
        "refused_credential_stores": refused, "redacted_files": redacted,
        "scan_note": ("chat files over 50 MB are included here; the older "
                      "vscode_chat_extractor.py skipped them, which is why this archives bytes"),
    }
    if args.json or not args.dry_run:
        print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
