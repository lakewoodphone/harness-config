#!/usr/bin/env python3
"""The owner-attention pipeline: ONE digest of everything that needs Eliyahu.

WHY THIS EXISTS
  Six subsystems independently decide what the owner should see (email triage,
  the Google Voice digest, the waiting-comms sweep, the owner decision queue,
  the LPT books obligations, the task board). He said the result "does not look
  like a unified brain, it looks scattered and split up" (2026-10-10), and the
  measured consequence on 2026-10-13 was that 1113 emails in ten days produced
  ~30 owner items that were never put in front of him while the same three
  questions resurfaced.

  This is the single writer of the owner's attention list. It gathers from every
  source that already holds a claim on his time, ranks them together, and
  publishes ONE artefact with ONE numbering.

WHAT IT NEVER DOES
  It does not send anything to a customer, and it never writes a price, a date
  or a commitment into any outbound text. The only outbound is to the owner
  himself, and only if the environment names a destination.

USAGE (on the authority)
  python3 scripts/owner_attention.py status
  python3 scripts/owner_attention.py build                 # write the artefact
  python3 scripts/owner_attention.py build --days 3 --top 15
  python3 scripts/owner_attention.py send --dry-run        # show, do not send
  python3 scripts/owner_attention.py send

ARTEFACTS
  data/owner-attention/<YYYY-MM-DD-HHMM>.txt   the numbered digest
  data/owner-attention/latest.txt              copy of the newest digest
  <secretary.db>  memories(category='owner_attention')  one row per build
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(APP_ROOT / ".env")
except Exception:
    pass

ART = APP_ROOT / "data" / "owner-attention"
ART.mkdir(parents=True, exist_ok=True)

# ── rank vocabulary ────────────────────────────────────────────────────────
SEV = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Sender domains whose mail can never be an owner item on its own. The list is
# deliberately about the SENDER, not the words: a marketing blast can contain
# the word "final notice" and still not be his problem.
_NEWSLETTER_HINTS = (
    "unitedwithisrael", "ugg", "aloyoga", "waves-audio", "dreampairs", "edikted",
    "fameoncentral", "historyfacts", "topgolf", "monoprice", "tuftandneedle",
    "thestickybrand", "concernedpatriot", "jackieglaser", "mostlymusic", "zoom.us",
    "instagram", "priority.instagram", "mail.instagram", "pinterest",
    "codecademy", "msg.wegmans", "news.paypal", "email.topgolf", "zakatelaviv",
    "unitedwithisrael", "chabad.org", "torahanytime", "caringcontact", "hineini",
    "feedisrael", "pillarsfamily", "collaborativeminds", "gmb.io", "30daysinger",
    "news@emails", "digikey", "lowes", "tractorsupply", "uber.com", "expedia",
    "mango", "audible", "amazon-adsystem", "mail.aliexpress", "info.aliexpress",
    "seekingalpha", "hubspot", "linkedin", "webroot", "bestbuy", "epicgames",
)

# Things that are genuinely his even though a machine could compute them.
_HARD_DEADLINE = re.compile(
    r"\b(deadline|dispute window|expires|expiration|final notice|past due|"
    r"overdue|suspended|suspension|terminated|collections|chargeback|"
    r"refund|legal|attorney|lawsuit|IRS|NJ DORES|subpoena|renewal date)\b",
    re.I,
)
_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")

# A sender that is a machine. These can carry facts worth acting on (the books
# pipeline, a health check) but they are not a person asking the owner for
# something, so they never become an owner item by themselves.
_AUTOMATED_SENDER = re.compile(
    r"(no-?reply|do-?not-?reply|donotreply|notification|notifications|"
    r"auto-confirm|auto-reply|automated|mailer|bounce|postmaster|"
    r"support@|info@|news@|updates?@|alerts?@|service@|billing@|"
    r"account-update|order-update|shipment-tracking|verify|security-noreply)",
    re.I,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _db_path() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite:///data/secretary.db")
    return url.replace("sqlite:///", "")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), timeout=30)
    c.row_factory = sqlite3.Row
    return c


# ── sources ────────────────────────────────────────────────────────────────
def from_owner_queue(limit: int = 12) -> list[dict]:
    """The owner decision queue. This is the authoritative question store."""
    out: list[dict] = []
    try:
        import subprocess

        raw = subprocess.run(
            ["python3", os.path.expanduser("~/bin/owner-queue.py"), "list", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        rows = json.loads(raw.stdout)
    except Exception as exc:  # noqa: BLE001
        return [{"source": "owner-queue", "severity": "high", "title": f"queue unreadable: {exc}"}]

    def is_deferred(r: dict) -> bool:
        d = str(r.get("deferred_until") or "")[:10]
        return bool(d) and d > _now().strftime("%Y-%m-%d")

    def blocking(r: dict) -> bool:
        b = str(r.get("blocks") or "").strip().lower()
        return b not in ("", "nothing", "none", "n/a", "-")

    rows = [r for r in rows if r.get("status") == "pending"]
    live = [r for r in rows if not is_deferred(r)]
    live.sort(key=lambda r: (0 if blocking(r) else 1, SEV.get(str(r.get("severity")).lower(), 2), -int(r.get("id") or 0)))
    # Collapse repeats: the queue holds the same question several times (the
    # prepaid-AI-balance row alone appears four times), and a list of four
    # identical lines is not an attention list, it is noise.
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in live:
        key = re.sub(r"[\W_]+", " ", str(r.get("question") or "").lower())[:90]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    live = deduped
    for r in live[:limit]:
        out.append(
            {
                "source": "owner-queue",
                "ref": f"q{r.get('id')}",
                "severity": str(r.get("severity") or "medium").lower(),
                "title": re.sub(r"\s+", " ", str(r.get("question") or ""))[:400],
                "blocks": str(r.get("blocks") or ""),
                "recommendation": str(r.get("recommendation") or "")[:300],
            }
        )
    out.append({"source": "owner-queue", "ref": "count", "severity": "info",
                "title": f"{len(live)} live question(s) in the queue, {len(rows) - len(live)} deferred by you"})
    return out


def from_waiting_comms(days: int = 14) -> list[dict]:
    """Who is waiting on a reply. Last word was theirs.

    The index is served by `scripts/comms-search.py` in harness-config - the
    same engine behind the ps_comms_waiting MCP tool - so this calls that one
    script rather than importing a service function that does not exist.
    """
    script = Path(os.path.expanduser("~/code/harness-config/scripts/comms-search.py"))
    if not script.exists():
        return [{"source": "comms-waiting", "severity": "info",
                 "title": f"comms index script missing at {script}"}]
    import subprocess

    out: list[dict] = []
    try:
        raw = subprocess.run(
            ["python3", str(script), "--json", "waiting", "--days", str(days)],
            capture_output=True, text=True, timeout=180,
        )
        if not raw.stdout.strip():
            return [{"source": "comms-waiting", "severity": "info",
                     "title": f"comms index returned nothing (rc={raw.returncode}): {raw.stderr.strip()[:200]}"}]
        data = json.loads(raw.stdout)
    except Exception as exc:  # noqa: BLE001
        return [{"source": "comms-waiting", "severity": "info", "title": f"comms unread: {exc}"}]

    rows = data.get("waiting") or []
    if data.get("index_age_hours") is not None:
        out.append({
            "source": "comms-waiting", "severity": "info",
            "title": f"comms index age {data['index_age_hours']}h"
                     f"{' STALE' if data.get('index_stale') else ''} — "
                     f"{data.get('total_waiting')} waiting, {data.get('total_missed_calls')} missed call(s)",
        })
    for w in rows[:20]:
        hrs = w.get("hours_waiting")
        sev = "high" if isinstance(hrs, (int, float)) and hrs >= 48 else "medium"
        out.append({
            "source": "comms-waiting",
            "ref": str(w.get("party")),
            "severity": sev,
            "title": f"{w.get('who') or w.get('party')} — waiting {hrs}h — "
                     f"{(w.get('last_text') or '')[:180]}",
        })
    return out


def from_email_catalog(days: int = 3, limit: int = 25) -> list[dict]:
    """Email that wants the owner, judged from the message body.

    TWO SOURCES, and the difference is measured. `email_catalog` is written by
    the app's own sync, which keeps only a ~100-char Gmail snippet and whose
    `internal_ts` lags badly (2026-10-13: catalog newest 2026-10-11 19:07 while
    Gmail held mail to 2026-10-13 00:42; a 3-day window over it returned ZERO
    owner rows against 121 flagged). `/tmp/email-sweep/**` is the full-body
    Read sweep and is preferred whenever present. A snippet cannot decide
    whether a message needs a person; the body can.
    """
    rows: list[dict] = []
    sweep = Path(ART.parent.parent.parent / "email-sweep" / "accounts")
    if not sweep.is_dir():
        sweep = Path("/tmp/email-sweep/accounts")
    cutoff_ms = int((_now() - timedelta(days=days)).timestamp() * 1000)
    if sweep.is_dir():
        for f in sorted(sweep.glob("*.jsonl")):
            for line in f.open(encoding="utf-8"):
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                if int(m.get("internal_ts") or 0) < cutoff_ms:
                    continue
                rows.append({
                    "account": m.get("account", ""),
                    "sender": m.get("from", ""),
                    "subject": m.get("subject", ""),
                    "snippet": m.get("snippet", ""),
                    "body": m.get("body", ""),
                    "ts": int(m.get("internal_ts") or 0),
                    "priority": "",
                })
    if not rows:
        try:
            c = _conn()
            since_ms = cutoff_ms
            for r in c.execute(
                """SELECT account, sender, subject, snippet, category, priority, internal_ts
                     FROM email_catalog
                    WHERE needs_owner=1 AND internal_ts >= ?
                    ORDER BY internal_ts DESC LIMIT 400""",
                (since_ms,),
            ).fetchall():
                rows.append({
                    "account": r["account"], "sender": r["sender"], "subject": r["subject"],
                    "snippet": r["snippet"], "body": r["snippet"], "ts": int(r["internal_ts"] or 0),
                    "priority": r["priority"],
                })
            c.close()
        except Exception as exc:  # noqa: BLE001
            return [{"source": "email", "severity": "info", "title": f"email unread: {exc}"}]

    out: list[dict] = []
    seen_thread: set[str] = set()
    seen_subj: set[str] = set()
    for r in sorted(rows, key=lambda x: -x["ts"]):
        sender = r["sender"] or ""
        low = sender.lower()
        if any(h in low for h in _NEWSLETTER_HINTS):
            continue
        if _AUTOMATED_SENDER.search(low):
            continue
        key = re.sub(r"[\W_]+", " ", (r["subject"] or "").lower())[:70]
        if key in seen_subj:
            continue
        seen_subj.add(key)
        # The body decides. A snippet is a marketing teaser as often as a fact.
        blob = f"{r['subject']} {r['body']}"
        from app.services.email_intake import classify_message  # type: ignore

        cls = classify_message(sender, r["subject"] or "")
        sev = "low"
        if cls.get("needs_owner"):
            sev = "medium"
        if _HARD_DEADLINE.search(blob) or (r["priority"] == "p0"):
            sev = "high"
        if sev == "low":
            continue
        if len(out) >= limit:
            break
        body = re.sub(r"\s+", " ", r["body"] or "")
        when = datetime.fromtimestamp(r["ts"] / 1000, timezone.utc).strftime("%m-%d %H:%M")
        out.append({
            "source": "email",
            "ref": f"{r['account'].split('@')[0]}/{when}",
            "severity": sev,
            "title": f"{when} {sender[:48]} | {(r['subject'] or '')[:110]}",
            "detail": body[:300],
        })
    return out


def from_obligations(days: int = 21) -> list[dict]:
    """Money and filings due, from the LPT books store (read-only)."""
        # A local namesake of the remote books store, not a copy of the database: on the
    # CLOUD authority the real store is on the office box, so this file holds the
    # `obligations` rows dumped over ssh by the deploy step. `_cloud_books_mirror` marks
    # this patch so a second run cannot nest itself.
    _mirror = "/root/accounting-data/books.db"
    path = os.environ.get("LPT_BOOKS_DB") or (
        _mirror if Path(_mirror).exists() else "/home/zabz/accounting-data/books.db"
    )  # _cloud_books_mirror
    if not Path(path).exists():
        return [{"source": "books", "severity": "info", "title": f"books store not found at {path}"}]
    out: list[dict] = []
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        cols = {r[1] for r in c.execute("PRAGMA table_info(obligations)")}
        # The store's own columns: due_on, form, jurisdiction, amount_cents, blocker.
        date_col = next((x for x in ("due_on", "due_date", "due") if x in cols), None)
        if not date_col:
            return [{"source": "books", "severity": "info",
                     "title": f"obligations has no date column (has: {sorted(cols)})"}]
        horizon = (_now() + timedelta(days=days)).strftime("%Y-%m-%d")
        for r in c.execute(
            f"""SELECT * FROM obligations
                 WHERE {date_col} <= ? AND coalesce(status,'') NOT IN ('paid','done','closed')
                 ORDER BY {date_col} ASC LIMIT 25""",
            (horizon,),
        ):
            d = dict(r)
            due = str(d.get(date_col))[:10]
            overdue = due < _now().strftime("%Y-%m-%d")
            amt = d.get("amount_cents")
            amt_s = f"{amt/100:,.2f}" if isinstance(amt, (int, float)) else "amount not recorded"
            out.append({
                "source": "books",
                "ref": due,
                "severity": "high" if overdue else "medium",
                "title": f"{'OVERDUE ' if overdue else 'due '}{due} — {d.get('form') or d.get('kind') or 'obligation'} "
                         f"({d.get('jurisdiction') or d.get('entity') or ''}) — {amt_s}",
                "detail": str(d.get("blocker") or "")[:200],
            })
        c.close()
    except Exception as exc:  # noqa: BLE001
        out.append({"source": "books", "severity": "info", "title": f"books unread: {exc}"})
    return out


def from_latest_digests() -> list[dict]:
    """Any other owner-facing digest the fleet produced, so nothing is orphaned."""
    out: list[dict] = []
    try:
        c = _conn()
        for r in c.execute(
            """SELECT category, content, created_at FROM memories
                WHERE category IN ('gv_daily_digest','gv_digest','email_attention',
                                   'email_hub_monitor','voicemail','owner_attention')
                ORDER BY created_at DESC LIMIT 6"""
        ):
            out.append({
                "source": f"memory:{r['category']}",
                "severity": "info",
                "title": f"latest {r['category']} ({str(r['created_at'])[:16]}): "
                         + re.sub(r"\s+", " ", str(r["content"] or ""))[:260],
            })
        c.close()
    except Exception:
        pass
    return out


# ── build ──────────────────────────────────────────────────────────────────
def build(days: int = 3, top: int = 15) -> tuple[str, dict]:
    items: list[dict] = []
    items += from_owner_queue()
    items += from_email_catalog(days=days)
    items += from_obligations()
    items += from_waiting_comms()
    items += from_latest_digests()

    # section the digest so it is read the way a person reads
    def sec(x: dict) -> str:
        return {
            "owner-queue": "DECISIONS WAITING ON YOU",
            "email": "EMAIL THAT WANTS AN ANSWER",
            "books": "MONEY AND FILINGS",
            "comms-waiting": "PEOPLE WAITING ON A REPLY",
        }.get(x["source"], "OTHER")

    order = ["DECISIONS WAITING ON YOU", "MONEY AND FILINGS", "EMAIL THAT WANTS AN ANSWER",
             "PEOPLE WAITING ON A REPLY", "OTHER"]
    rank = {s: i for i, s in enumerate(order)}
    items.sort(key=lambda x: (rank.get(sec(x), 9), SEV.get(str(x.get("severity")), 4)))

    lines: list[str] = []
    n = 0
    per_section = {"DECISIONS WAITING ON YOU": max(top, 12)}
    lines.append(f"OWNER ATTENTION — {_now().strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append(f"window: last {days} day(s) of email · {len(items)} candidate(s) from 5 sources")
    lines.append("")
    current = None
    used: dict[str, int] = {}
    for it in items:
        s = sec(it)
        if s != current:
            current = s
            lines.append(f"== {s} ==")
        if it.get("severity") == "info":
            lines.append(f"   · {it.get('title')}")
            continue
        # Cap each section independently: a 156-question queue would otherwise
        # consume the whole digest and hide every email and every deadline.
        cap = per_section.get(s, 8)
        if used.get(s, 0) >= cap:
            continue
        used[s] = used.get(s, 0) + 1
        n += 1
        lines.append(f"{n:>3}. [{it.get('severity')}] {it.get('title')}")
        if it.get("detail"):
            lines.append(f"       {it['detail']}")
        if it.get("blocks"):
            lines.append(f"       blocks: {it['blocks'][:140]}")
        if it.get("recommendation"):
            lines.append(f"       my recommendation: {it['recommendation'][:220]}")
    lines.append("")
    lines.append("Nothing here was sent to a customer. Reply with a number or a name.")

    text = "\n".join(lines)
    stamp = _now().strftime("%Y-%m-%d-%H%M")
    (ART / f"{stamp}.txt").write_text(text, encoding="utf-8")
    (ART / "latest.txt").write_text(text, encoding="utf-8")

    # persist so a later session can read it without re-deriving it
    try:
        c = _conn()
        c.execute(
            """INSERT INTO memories (category, content, created_at, importance, source)
               VALUES ('owner_attention', ?, ?, ?, 'owner_attention.py')""",
            (text, _now().strftime("%Y-%m-%dT%H:%M:%S"), 7),
        )
        c.commit()
        c.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[attention] warn: memory write failed: {exc}", file=sys.stderr)

    return text, {"items": n, "candidates": len(items)}


def destination() -> str:
    """Where an owner-bound message goes.

    Prefer the app's own resolver, because that is the single place that already
    knows the owner's number, the override rules and the quiet hours. Reading
    OWNER_ALERT_NUMBER / OWNER_PHONE_NUMBER directly from the environment was
    the first version of this function and it returned "" on the office box,
    where the number lives in the app settings rather than the shell - so the
    digest built correctly and then had nowhere to go. A pipeline that reports
    "no destination" while a destination exists is a false alarm, and this box
    has produced a false alarm of exactly that shape before.
    """
    try:
        from app.config import settings as _s  # type: ignore
        from app.services.owner_notifications import owner_notify_target  # type: ignore

        target = str(owner_notify_target(_s) or "").strip()
        if target:
            return target
    except Exception:
        pass
    return (
        os.environ.get("OWNER_ALERT_NUMBER")
        or os.environ.get("OWNER_PHONE_NUMBER")
        or ""
    ).strip()



# The owner's own surface allows 320 characters in one text. Measured
# 2026-10-13: a 1201-character digest was refused with reason `too_long` after
# first being refused with `below_owner_sms_threshold`. Two gates, both real,
# and neither visible to a caller that reports success by itself.
OWNER_SMS_MAX = 320

SEV_MARK = {"high": "!", "medium": "-", "low": "."}


def sms_body(text: str) -> str:
    """The digest as ONE text of at most OWNER_SMS_MAX characters.

    The full numbered digest is a file and a memory row; this is the pager
    version - how many things, the worst of them, and where the rest is. A text
    that gets refused for length reaches nobody, and a text that names only the
    section headings tells him nothing he can act on.
    """
    items = [l for l in text.split("\n") if l[:4].strip().rstrip(".").isdigit() and "] " in l]
    highs = [l for l in items if "[high]" in l]
    head = f"'{_now().strftime('%m-%d %H:%M')} UTC  {len(items)} items, {len(highs)} urgent"
    out = [head]
    budget = OWNER_SMS_MAX - len(head) - 40
    for l in (highs or items)[:4]:
        short = l.split("] ", 1)[-1].strip()
        line = "- " + short[:78]
        if len("\n".join(out + [line])) > budget:
            break
        out.append(line)
    out.append("full: data/owner-attention/latest.txt")
    body = "\n".join(out)
    return body[:OWNER_SMS_MAX]


def send(text: str, dry_run: bool, urgency: str = "normal") -> int:
    """Hand the digest to the owner surface, and REPORT WHAT ACTUALLY HAPPENED.

    THE BUG THIS REPLACES, measured 2026-10-13 01:48 UTC: the first version
    called `send_owner_update(...)` and then printed `sent 1201 chars to
    +18483897895` unconditionally. The surface had in fact REFUSED the message,
    first on `below_owner_sms_threshold` and then on `too_long`, and the row went
    to `owner_message_queue` as `held`. So the log said "sent", no SMS row
    existed, and the only way to find out was to go and look in three places. A
    pipeline that reports delivery it did not get is worse than one that reports
    nothing - the same defect class as the stale database read.
    """
    dest = destination()
    if not dest:
        print("owner destination NOT configured - digest written, nothing sent")
        return 1
    body = sms_body(text)
    if dry_run:
        print(f"DRY RUN - would hand {len(body)} chars to {dest} at urgency={urgency}:")
        print("-" * 60)
        print(body)
        return 0

    from app.tool_factory import send_owner_update  # type: ignore

    result = send_owner_update(body, reason="owner_attention_digest", urgency=urgency) or {}
    if result.get("ok") and not result.get("held") and not result.get("suppressed"):
        print(f"SENT {len(body)} chars to {dest} (urgency={urgency})")
        return 0
    if result.get("held") or result.get("suppressed"):
        print(
            f"HELD, NOT SENT to {dest}: owner surface refused it "
            f"(reason={result.get('reason')}, urgency={urgency}, queue_id={result.get('queue_id')}). "
            f"Digest is written; the row is in owner_message_queue as 'held'."
        )
        return 2
    print(f"NOT SENT to {dest}: {result.get('error') or result}")
    return 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "send", "status"])
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--urgency", default="normal", choices=["normal", "urgent"],
                    help="the level the owner surface judges against; the surface may still refuse")
    a = ap.parse_args()

    if a.cmd == "status":
        latest = ART / "latest.txt"
        print(f"artefacts: {len(list(ART.glob('*.txt')))} in {ART}")
        print(f"latest: {latest.stat().st_mtime if latest.exists() else 'none'}")
        print(f"owner destination: {destination() or 'NOT SET'}")
        return 0

    text, meta = build(days=a.days, top=a.top)
    print(f"built: {meta['items']} item(s) surfaced from {meta['candidates']} candidate(s)")
    if a.cmd == "build":
        print(text)
        return 0
    return send(text, a.dry_run, a.urgency)


if __name__ == "__main__":
    raise SystemExit(main())
