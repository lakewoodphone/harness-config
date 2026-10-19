#!/usr/bin/env python3
"""Before/after count for the production owner-attention pager.

The family is the delivered text whose body carries "N items, M urgent".  This
reads those texts from the PRODUCTION authority DB, maps each to the full digest
artefact that produced it, and reports:

  BEFORE  what the live pager actually sent (stored SMS body).
  AFTER   the same full digests composed by the module under test, with the
          rotation state carried across them exactly as daily sends would.

It also shows the latest one-item text (the 79-character fragment format) and
what the same item becomes under the new composer.

It writes nothing: no SMS, no database row, no state file.  Run it with
--module pointing at the live file or at a staged copy.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

OWNER = "8483897895"
APP = Path("/root/personal-secretary-mvp")
ART = APP / "data" / "owner-attention"
DB = "/root/authority.db"


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("owner_attention_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def digest_artifacts():
    out = []
    for p in ART.glob("*.txt"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})-(\d{4})$", p.stem)
        if not m:
            continue
        dt = datetime.strptime(m.group(1) + m.group(2), "%Y-%m-%d%H%M").replace(tzinfo=timezone.utc)
        out.append((dt, p))
    return sorted(out)


def artifact_for(body: str, created_at: str, arts):
    """The artefact named by the body's own header, else the nearest one."""
    m = re.search(r"'(\d{2})-(\d{2}) (\d{2}):(\d{2}) UTC", body)
    if m:
        year = created_at[:4]
        dt = datetime.strptime(
            f"{year}-{m.group(1)}-{m.group(2)} {m.group(3)}:{m.group(4)}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=timezone.utc)
        p = ART / f"{dt:%Y-%m-%d-%H%M}.txt"
        if p.exists():
            return p, dt
    when = datetime.fromisoformat(created_at)
    dt, path = min(arts, key=lambda x: abs((x[0] - when).total_seconds()))
    if abs((dt - when).total_seconds()) <= 15 * 60:
        return path, dt
    return None, None


def old_stats(body: str) -> dict:
    m = re.search(r"(\d+) items,\s*(\d+) urgent", body)
    first = re.search(r"^- (.+)$", body, re.M)
    return {
        "items": int(m.group(1)) if m else 0,
        "urgent": int(m.group(2)) if m else 0,
        "path": int("data/owner-attention" in body),
        "ask": int("reply" in body.lower()),
        "chars": len(body),
        "first": " ".join(first.group(1).split()) if first else "",
        "question": int("?" in body),
        "midword": int(body.rstrip()[-1:] not in ".?!\u2026"),
    }


def after_stats(mod, art_text: str, state: dict, now: datetime) -> tuple[str, dict]:
    sent = state.setdefault("sent", {})
    if hasattr(mod, "compose_sms_body"):
        body, rendered = mod.compose_sms_body(art_text, sent)
        if rendered:
            sent[mod.item_fingerprint(rendered)] = now.isoformat()
    else:
        # The pre-change module only exposes sms_body(); inject the in-memory
        # state so the measurement cannot read or write the live sent-items file.
        old = getattr(mod, "_load_sent", None)
        mod._load_sent = lambda: sent
        try:
            body = mod.sms_body(art_text)
        finally:
            if old is not None:
                mod._load_sent = old
        if body:
            sent[mod.item_fingerprint(body)] = now.isoformat()
    first = body.split("\n", 1)[0] if body else ""
    return body, {
        "items": 1 if body else 0,
        "urgent": 0,
        "path": int("data/owner-attention" in body),
        "ask": int("reply" in body.lower()),
        "chars": len(body),
        "first": first,
        "question": int("?" in body),
        "midword": int(bool(body) and body.rstrip()[-1:] not in ".?!\u2026"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default=str(APP / "scripts" / "owner_attention.py"))
    ap.add_argument("--db", default=DB)
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()

    mod = load_module(Path(a.module))
    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    since = (datetime.now(timezone.utc) - timedelta(days=a.days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT id, created_at, status, body FROM sms_log
            WHERE to_number LIKE ? AND direction='outbound'
              AND body LIKE '%items, % urgent%' AND created_at >= ?
              AND status IN ('delivered','sent')
            ORDER BY id""",
        (f"%{OWNER}%", since),
    ).fetchall()
    arts = digest_artifacts()

    print(f"module: {a.module}")
    print(f"family: delivered texts with 'N items, M urgent', {a.days} days")
    print(f"{'id':>5} {'when':16} {'status':9} | {'old':^28} | {'new':^28}")
    print(f"{'':5} {'':16} {'':9} | items urg path ask chars | items ask chars q?")
    old_items = old_urgent = old_path = old_ask = old_replies = 0
    old_first: set[str] = set()
    new_items = new_ask = new_path = new_chars = 0
    new_first: set[str] = set()
    state = {"sent": {}}
    for r in rows:
        o = old_stats(r["body"])
        replied = conn.execute(
            """SELECT COUNT(*) FROM sms_log
                WHERE from_number LIKE ? AND direction='inbound'
                  AND created_at >= ? AND created_at <= ?""",
            (f"%{OWNER}%", r["created_at"], (datetime.fromisoformat(r["created_at"]) + timedelta(hours=24)).isoformat()),
        ).fetchone()[0]
        art, art_dt = artifact_for(r["body"], r["created_at"], arts)
        if art:
            new_body, n = after_stats(mod, art.read_text(encoding="utf-8", errors="replace"), state, art_dt)
        else:
            new_body, n = "(no artefact)", {"items": 0, "ask": 0, "chars": 0, "first": "", "question": 0}
        old_items += o["items"]; old_urgent += o["urgent"]
        old_path += o["path"]; old_ask += o["ask"]; old_replies += int(replied)
        old_first.add(o["first"].lower())
        new_items += n["items"]; new_ask += n["ask"]; new_path += n["path"]; new_chars += n["chars"]
        new_first.add(n["first"].lower())
        print(f"{r['id']:>5} {r['created_at'][:16]:16} {r['status']:9} | "
              f"{o['items']:>5} {o['urgent']:>3} {o['path']:>4} {o['ask']:>3} {o['chars']:>5} | "
              f"{n['items']:>5} {n['ask']:>3} {n['chars']:>5} {n['question']:>2}")

    print()
    print(f"FAMILY BEFORE  {len(rows)} delivered | {old_items} item-slots | {old_urgent} urgent labels | "
          f"{old_path}/{len(rows)} server paths | {old_ask}/{len(rows)} reply instructions | "
          f"{len(old_first)} distinct leading line(s) | {old_replies} inbound message(s) in the 24h windows")
    print(f"FAMILY AFTER   {len(rows)} delivered | {new_items} item-slots | 0 urgent labels | "
          f"{new_path}/{len(rows)} server paths | {new_ask}/{len(rows)} reply instructions | "
          f"{len(new_first)} distinct item(s) | {new_chars} total chars")

    # The latest one-item text: the format that replaced the wall.
    one = conn.execute(
        """SELECT id, created_at, body FROM sms_log
            WHERE to_number LIKE ? AND direction='outbound' AND body LIKE '- %'
              AND created_at >= ? AND status IN ('delivered','sent')
            ORDER BY id DESC LIMIT 1""",
        (f"%{OWNER}%", since),
    ).fetchone()
    if one:
        art, art_dt = artifact_for(one["body"], one["created_at"], arts)
        before = one["body"]
        after = before
        raw = ""
        if art:
            text = art.read_text(encoding="utf-8", errors="replace")
            items = [l for l in text.split("\n") if l[:4].strip().rstrip(".").isdigit() and "] " in l]
            raw = next((l for l in items if mod._render_item(l) == before), "")
            if raw and hasattr(mod, "_compose_one"):
                after = mod._compose_one(raw)
        print()
        print(f"ONE-ITEM BEFORE id={one['id']} {one['created_at'][:16]} chars={len(before)} "
              f"question={'?' in before} ask={'reply' in before.lower()} "
              f"midword={before.rstrip()[-1:] not in '.?!\u2026'}")
        print(before)
        print(f"ONE-ITEM AFTER  chars={len(after)} question={'?' in after} ask={'reply' in after.lower()} "
              f"midword={after.rstrip()[-1:] not in '.?!\u2026'}")
        print(after)

    latest = ART / "latest.txt"
    if latest.exists():
        live = mod._load_sent() if hasattr(mod, "_load_sent") else {}
        print()
        print("NEXT LIVE SEND (existing state, no write):")
        if hasattr(mod, "compose_sms_body"):
            body, rendered = mod.compose_sms_body(latest.read_text(encoding="utf-8", errors="replace"), live)
            print(f"chars={len(body)} key={rendered!r}")
        else:
            old = getattr(mod, "_load_sent", None)
            mod._load_sent = lambda: live
            try:
                body = mod.sms_body(latest.read_text(encoding="utf-8", errors="replace"))
            finally:
                if old is not None:
                    mod._load_sent = old
            print(f"chars={len(body)}")
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
