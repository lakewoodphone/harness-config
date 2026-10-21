#!/usr/bin/env python3
"""Read every email in a window across every authenticated Gmail account.

Read-only. Never sends. Fetches FULL message bodies so a human or agent can
actually read the mail rather than a subject line.

WHY SERIAL: the google-api-python-client / httplib2 stack used here SEGFAULTS
under a ThreadPoolExecutor (reproduced 2026-10-13: `Fatal Python error:
Segmentation fault` after ~30 messages with workers=1/3/8, thread 0x...6c0;
the identical 181-message sweep run serially completed with zero errors). So
this script fetches on ONE thread and parallelises by ACCOUNT instead - launch
one process per account via systemd-run --user.

Usage (from /home/zabz/personal-secretary-mvp):
    python3 ~/bin/lpt-email-sweep.py --days 10 --accounts a@gmail.com --out /tmp/email-sweep

Writes:
    <out>/all.jsonl              one JSON object per message, full body included
    <out>/accounts/<acct>.jsonl  per-account results, flushed when the account finishes
    stdout                       compact JSON summary (metadata + body excerpt)
    stderr                       progress lines, flushed per message

Exit codes: 0 ok, 2 nothing could be read.
"""
from __future__ import annotations

import argparse
import base64
import html as _html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(os.environ.get("LPT_APP_ROOT", "/home/zabz/personal-secretary-mvp"))
sys.path.insert(0, str(APP_ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(APP_ROOT / ".env")
except Exception:
    pass

from app.config import settings as APP_SETTINGS  # noqa: E402
from app.services import gmail_service  # noqa: E402
from app.services.email_intake import classify_message  # noqa: E402


def _extract_body(payload: dict) -> str:
    """Body text from a payload, preferring text/plain. Depth-bounded.

    The app's own `gmail_service._extract_body` recurses without a depth guard
    over `parts`; a deeply nested marketing MIME tree can blow the recursion
    limit. This one walks with an explicit stack and never recurses.
    """
    stack = [payload]
    html_fallback = ""
    while stack:
        node = stack.pop(0)
        if not isinstance(node, dict):
            continue
        data = (node.get("body") or {}).get("data")
        mime = node.get("mimeType") or ""
        if data:
            try:
                text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                text = ""
            if text:
                if mime.startswith("text/plain"):
                    return text
                if mime.startswith("text/html") and not html_fallback:
                    html_fallback = text
        parts = node.get("parts")
        if parts:
            stack.extend(parts)
    return html_fallback


def _headers(raw: dict) -> dict:
    out = {}
    for h in raw.get("payload", {}).get("headers", []) or []:
        name = str(h.get("name", "")).lower()
        if name in ("from", "to", "cc", "subject", "date", "message-id"):
            out.setdefault(name, h.get("value", ""))
    return out


def clean(body: str) -> str:
    if not body:
        return ""
    text = body
    low = text[:4000].lower()
    if "<html" in low or "<body" in low or "<div" in low or "<table" in low:
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = _html.unescape(text)
    text = re.sub(r"[ \t\u00a0\u200c\u200b]+", " ", text)
    text = re.sub(r"(\r?\n)\s*(\r?\n\s*){2,}", "\n\n", text)
    return text.strip()


def list_ids(service, days: int, limit: int) -> list[str]:
    newer = f"newer_than:{max(1, days)}d"
    # ── THE FOURTH QUERY, AND WHY IT EXISTS ──────────────────────────────────
    # This list used to stop at three: inbox, sent, and everything-else-minus-spam.
    # The middle line of that third query is `-in:spam`, so Gmail's junk folder was
    # the one folder no pipeline on this estate ever read, and nobody owned it.
    #
    # Measured cost of that gap, 2026-10-20: LRRC's "Section 8 Housing Voucher (HUD)
    # Applications Open for a Limited Time" — a notice that Lakewood's Section 8
    # waiting list opens 2026-11-02 and that 3,000 households will be drawn by
    # lottery — landed in SPAM (labelIds UNREAD/CATEGORY_UPDATES/SPAM). It never
    # entered this corpus, never reached `email_catalog`, never got an
    # `owner_mail_verdict`, and never reached the owner. He heard it from someone
    # else. A false positive in Gmail is invisible to every layer below Gmail, so
    # the folder that Gmail is WRONG about is exactly the folder worth reading.
    #
    # Volume is small and known: over 14 days the five mailboxes held 25, 27, 107,
    # 109 and (unmeasured) spam rows — so reading them costs a few hundred serial
    # fetches twice a day, and the judge still decides on the body. Rows keep their
    # `labels`, so a rescued message stays identifiable as one that came from spam.
    spam_days = max(1, min(int(days), 14))
    queries = [
        (f"in:inbox {newer}", limit),
        (f"in:sent {newer}", limit),
        (f"in:anywhere -in:inbox -in:sent -in:spam -in:trash {newer}", limit),
        (f"in:spam newer_than:{spam_days}d", min(limit, 250)),
    ]
    ids: list[str] = []
    seen: set[str] = set()
    for q, cap in queries:
        token = None
        fetched = 0
        while fetched < cap:
            kwargs = {"userId": "me", "q": q, "maxResults": min(100, cap - fetched)}
            if token:
                kwargs["pageToken"] = token
            resp = service.users().messages().list(**kwargs).execute()
            batch = resp.get("messages") or []
            for stub in batch:
                mid = stub.get("id")
                if mid and mid not in seen:
                    seen.add(mid)
                    ids.append(mid)
            fetched += len(batch)
            token = resp.get("nextPageToken")
            if not token or not batch:
                break
    return ids


def sweep_account(account: str, days: int, limit: int) -> list[dict]:
    service = gmail_service._build_service(APP_SETTINGS, account)
    ids = list_ids(service, days, limit)
    print(f"[sweep] {account}: {len(ids)} ids to fetch", file=sys.stderr, flush=True)

    rows: list[dict] = []
    errors = 0
    for i, mid in enumerate(ids, 1):
        raw = None
        for attempt in range(3):
            try:
                # metadataHeaders is ignored on format=full, but the full
                # payload already carries every header; read it defensively.
                raw = (
                    service.users()
                    .messages()
                    .get(userId="me", id=mid, format="full")
                    .execute()
                )
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    errors += 1
                    print(f"[sweep] {account}: FAILED {mid}: {exc}", file=sys.stderr, flush=True)
                time.sleep(0.5 * (attempt + 1))
        if raw is None:
            continue
        h = _headers(raw)
        body = clean(_extract_body(raw.get("payload", {}) or {}))
        labels = raw.get("labelIds") or []
        rows.append(
            {
                "account": account,
                "id": raw.get("id"),
                "thread_id": raw.get("threadId") or "",
                "internal_ts": int(raw.get("internalDate") or 0),
                "from": h.get("from", ""),
                "to": h.get("to", ""),
                "cc": h.get("cc", ""),
                "subject": h.get("subject", "(no subject)"),
                "date": h.get("date", ""),
                "snippet": raw.get("snippet") or "",
                "labels": labels,
                "unread": "UNREAD" in labels,
                "body": body,
            }
        )
        if i % 25 == 0:
            print(f"[sweep] {account}: {i}/{len(ids)}", file=sys.stderr, flush=True)

    rows.sort(key=lambda r: int(r.get("internal_ts") or 0), reverse=True)
    print(f"[sweep] {account}: {len(rows)} messages, {errors} errors", file=sys.stderr, flush=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--accounts", default="")
    ap.add_argument("--max-per-account", type=int, default=900)
    ap.add_argument("--out", default="/tmp/email-sweep")
    ap.add_argument("--excerpt-chars", type=int, default=1200)
    args = ap.parse_args()

    accounts = [a.strip() for a in args.accounts.split(",") if a.strip()]
    if not accounts:
        accounts = gmail_service.list_authenticated_accounts(APP_SETTINGS)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    acct_dir = out_dir / "accounts"
    acct_dir.mkdir(parents=True, exist_ok=True)

    summary: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "days": args.days,
        "accounts": accounts,
        "account_counts": {},
        "errors": [],
        "messages": [],
    }

    all_rows: list[dict] = []
    for acct in accounts:
        try:
            rows = sweep_account(acct, args.days, args.max_per_account)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append({"account": acct, "error": str(exc)})
            print(f"[sweep] {acct} FAILED: {exc}", file=sys.stderr, flush=True)
            continue
        summary["account_counts"][acct] = len(rows)
        all_rows.extend(rows)
        with (acct_dir / f"{acct}.jsonl").open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    with (out_dir / "all.jsonl").open("w", encoding="utf-8") as fh:
        for row in all_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    for row in all_rows:
        cls = classify_message(row.get("from", ""), row.get("subject", ""))
        body = row.get("body") or ""
        summary["messages"].append(
            {
                "a": row.get("account"),
                "id": row.get("id"),
                "t": row.get("thread_id"),
                "ts": row.get("internal_ts"),
                "d": row.get("date"),
                "from": row.get("from"),
                "subj": row.get("subject"),
                "unread": row.get("unread"),
                "cat": cls["category"],
                "pri": cls["priority"],
                "owner": cls["needs_owner"],
                "snippet": row.get("snippet"),
                "blen": len(body),
                "body": body[: args.excerpt_chars],
            }
        )

    summary["total"] = len(all_rows)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if all_rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
