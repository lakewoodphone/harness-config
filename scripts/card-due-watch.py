#!/usr/bin/env python3
"""card-due-watch.py — text the owner 2 days before a card payment is due, and say
which account the money will actually come out of, and whether it is there.

WHY THIS EXISTS (owner request, 2026-10-14, verbatim)
----------------------------------------------------
    "okay so just make sure to remind and shoot me a text when you get an email
     about autopay, maybe 2 days before it's due or something"

THE INCIDENT THAT PROVES THE SHAPE WAS WRONG
--------------------------------------------
On 2026-10-11 a Chase card autopay of 2,380.06 drew on checking '...9730', which held
**72.47**, and put it at **available -2,307.59**. The owner *was* reminded - once, on
2026-10-10, one day ahead - and it read:

    "Chase CC (...9650) payment is due 10/11/2026 - schedule the payment in the
     Chase portal before the due date."

Three faults in one line, all fixed here:

  1. **It said "schedule the payment" when the payment was ALREADY armed.** Whoever
     wrote it had no view of the autopay state, so it gave advice that was the
     opposite of useful.
  2. **It never named the funding account**, which is the entire risk. A due date is
     not the danger; a due date plus an underfunded source account is.
  3. **One day of lead time.** A transfer needs time to clear; two days is the least
     that is actionable, and it is what the owner asked for.

Measured the same day: every deposit account he holds totalled **1,061.04**
(balance_snapshots, source 'plaid-api', 2026-10-14 04:30:13 UTC) against that
2,380.06 autopay. There was no arrangement of his own money that made it. A reminder
that names the source account and its balance turns a surprise into a decision.

DESIGN CONSTRAINTS, EACH LOAD-BEARING
-------------------------------------
  * **The amount is read from the issuer's own statement email**, not computed. The
    snippet is enough - it carries account last-4, due date, minimum and statement
    balance. (The *autopay* amount lives only in the message BODY; see NEXT below.)
  * **Autopay is never asserted from absence.** The statement snippet sometimes says
    "Auto-pay enabled" and sometimes says nothing - and card ...9650 has autopay while
    its statement snippet does not say so. So an absent flag proves NOTHING and this
    tool reports the funding account instead of a claim it cannot support.
  * **The funding account is a maintained mapping**, not a guess from the email, which
    says only "from your account". It is seeded from matched bank/card transaction
    pairs and lives in `settings/finance/card-funding-accounts.tsv`.
  * **Read-only on the money side.** Both sqlite handles are opened `mode=ro`.
    This tool contains no INSERT/UPDATE/DELETE against secretary.db or accounting.db.
  * **Sending goes through `textsend.py notify`**, the sanctioned owner path that
    POSTs the app's /tools/notify-owner. The owner-SMS kill switch and the send gate
    stay in charge; this tool never touches Twilio.
  * **Dry run by default.** `--send` is required to send anything, the same contract
    every other sender in this estate uses.

USAGE
    card-due-watch.py --list          # every parsed due date, with provenance
    card-due-watch.py                 # dry run: what would be texted today
    card-due-watch.py --send          # text the owner (2 days before each due date)
    card-due-watch.py --send --as-of 2026-10-16   # replay a date for verification

NEXT (not built, stated so it is not silently assumed)
    The exact AUTOPAY amount (e.g. 939.18 on ...5578) is only in the BODY of the
    "your automatic payment is scheduled" email; the Gmail search result carries a
    truncated snippet, and `email_catalog` does not hold the body at all. v2 should read
    those message bodies via /gmail/messages/<id> and report the autopay amount alongside
    the minimum. Until then this reports the minimum and the statement balance, both of
    which ARE present in the snippet we already fetch - so v1 makes no claim it cannot
    source.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------- configuration

TZ_NAME = "America/New_York"
DEFAULT_LEAD_DAYS = 2
DEFAULT_MAX_SENDS = 5

SECRETARY_DB = os.environ.get(
    "CARD_DUE_SECRETARY_DB", "/root/authority.db"
)
ACCOUNTING_DB = os.environ.get(
    "CARD_DUE_ACCOUNTING_DB", "/root/accounting-data/live/accounting.db"
)
FUNDING_MAP = os.environ.get(
    "CARD_DUE_FUNDING_MAP",
    "/root/code/harness-config/settings/finance/card-funding-accounts.tsv",
)
TEXTSEND = os.environ.get("CARD_DUE_TEXTSEND", "/root/bin/textsend.py")
STATE_DIR = os.environ.get("CARD_DUE_STATE_DIR", "/root/.card-due-watch")
PYTHON = os.environ.get("CARD_DUE_PYTHON", sys.executable or "/usr/bin/python3")
API_BASE = os.environ.get("CARD_DUE_API_BASE", "http://127.0.0.1:8002").rstrip("/")


def _rfc_to_epoch(text: str) -> int:
    """RFC-2822 mail date -> epoch seconds. 0 when unparsable, never a guess."""
    if not text:
        return 0
    try:
        from email.utils import parsedate_to_datetime
        return int(parsedate_to_datetime(text).timestamp())
    except Exception:
        return 0

# ---------------------------------------------------------------- parsing

# Observed shapes (Gmail statement snippets, issuer statement emails):
#   "...Account Chase Credit Card (...3929) Due date 11/07/2026 Minimum payment
#    due $251.65 Statement balance $3744.31 Visit our Resource Center"
#   "...Account Chase Credit Card (...7542) Due date 10/22/2026 Minimum payment
#    due $246.25 Statement balance $5931.22 Auto-pay enabled You're..."
RE_CARD = re.compile(r"Account\s+(?:Chase Credit Card\s*)?\(\.\.\.(\d{4})\)")
RE_DUE = re.compile(r"Due date\s+(\d{1,2}/\d{1,2}/\d{4})")
RE_MINIMUM = re.compile(r"Minimum payment due\s+\$([\d,]+\.\d{2})")
RE_STATEMENT = re.compile(r"Statement balance\s+\$([\d,]+\.\d{2})")
RE_AUTOPAY_FLAG = re.compile(r"Auto-?pay enabled", re.I)
RE_CARD_SUBJECT = re.compile(r"\(\.\.\.(\d{4})\)")


def money(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def parse_statement(snippet: str) -> dict | None:
    """Pull (card, due date, minimum, statement balance) out of one snippet.

    Returns None when the snippet is a deposit statement or otherwise lacks a card
    due date - the honest answer for a row this tool cannot use.
    """
    if not snippet:
        return None
    card = RE_CARD.search(snippet)
    due = RE_DUE.search(snippet)
    if not card or not due:
        return None
    return {
        "card": card.group(1),
        "due": due.group(1),
        "minimum": money(RE_MINIMUM.search(snippet).group(1))
        if RE_MINIMUM.search(snippet)
        else None,
        "statement": money(RE_STATEMENT.search(snippet).group(1))
        if RE_STATEMENT.search(snippet)
        else None,
        "autopay_flag": bool(RE_AUTOPAY_FLAG.search(snippet)),
    }


def parse_due(raw: str) -> date | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- data sources


def read_catalog(days: int = 45) -> list[dict]:
    """Issuer statement emails, via the app's own Gmail search. Read-only, no send.

    WHY GMAIL AND NOT `email_catalog` (measured 2026-10-14, both traps hit in one run)
      1. `email_catalog` holds **732 rows total and every `internal_ts` is NULL**. A query
         bounded by that column silently returns nothing, which reads as "no statements"
         when it means "no timestamps". Do not filter on it.
      2. Even unfiltered, the catalog only keeps what the last sync upserted (~222
         messages), so the August/September statement emails that carry the very due dates
         we need had already aged out. A bounded catalog cannot answer a monthly question.
    Gmail itself is the complete source and the app already holds the credentials, so this
    asks it directly at http://127.0.0.1:8002/gmail/search. The snippet alone carries
    account last-4, due date, minimum and statement balance - the BODY is not needed for
    any of those (it is needed only for the autopay amount; see NEXT in the module docstring).
    """
    from urllib.parse import urlencode
    from urllib.request import urlopen

    query = os.environ.get("CARD_DUE_GMAIL_QUERY", "subject:statement")
    params = urlencode({
        "q": query,
        "limit": 60,
        "all_accounts": "true",
    })
    url = f"{API_BASE}/gmail/search?{params}"
    try:
        with urlopen(url, timeout=45) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # a source that is down must not become a false negative
        raise SystemExit(
            f"card-due-watch: Gmail search failed ({exc}). NOTHING WAS SEARCHED - "
            "this is not 'no statements due', it is 'could not look'."
        )

    messages = payload.get("messages") or payload.get("results") or []
    out = []
    for m in messages:
        out.append({
            "date_text": m.get("date") or "",
            "account": m.get("account") or "",
            "sender": m.get("from") or "",
            "subject": m.get("subject") or "",
            "snippet": m.get("snippet") or "",
            "ts": _rfc_to_epoch(m.get("date") or ""),
        })
    return out


def read_balances() -> dict[str, dict]:
    """Latest 'current' balance per accounting account. Read-only."""
    if not os.path.exists(ACCOUNTING_DB):
        return {}
    uri = f"file:{ACCOUNTING_DB}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=20)
    try:
        conn.execute("PRAGMA query_only=1")
        rows = conn.execute(
            """
            SELECT b.account_id, b.amount_cents / 100.0, b.captured_at
            FROM balance_snapshots b
            JOIN (
                SELECT account_id, MAX(captured_at) AS mx
                FROM balance_snapshots GROUP BY account_id
            ) latest
              ON latest.account_id = b.account_id AND latest.mx = b.captured_at
            """
        ).fetchall()
    finally:
        conn.close()
    return {r[0]: {"amount": r[1], "captured_at": r[2]} for r in rows}


def read_funding_map() -> dict[str, dict]:
    """card_last4 -> {account_id, label}. Missing file is not fatal.

    Pipe separated, because a label legitimately contains spaces and an earlier
    tab-separated draft was silently mis-parsed by a stray space - a mapping file that
    half-reads is how a wrong funding account reaches an owner's phone.
    """
    out: dict[str, dict] = {}
    if not os.path.exists(FUNDING_MAP):
        return out
    with open(FUNDING_MAP, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            card, acct_id, label = parts[0], parts[1], parts[2]
            if not card.isdigit() or not acct_id:
                continue
            out[card] = {"account_id": acct_id, "label": label}
    return out


# ---------------------------------------------------------------- state


def state_path() -> str:
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, "state.json")


def load_state() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"sent": {}}


def save_state(state: dict) -> None:
    tmp = state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, state_path())


# ---------------------------------------------------------------- compose


def human_money(value: float | None) -> str:
    """Plain number, no currency symbol - pairs of dollar signs render as maths."""
    if value is None:
        return "unknown"
    return f"{value:,.2f}"


def compose(card: str, info: dict, funding: dict | None, bal: dict | None,
            due: date, days: int) -> str:
    """One card, one message. The comparison here is the whole point of the tool.

    THE FALSE REASSURANCE THIS FUNCTION MUST NOT EMIT (caught in a replay, 2026-10-14)
    An earlier version compared the balance against the MINIMUM and printed "That covers
    the minimum" for card ...9650 - because 72.47 does beat the 40.00 minimum. But the
    autopay on that card took **2,380.06**, and the account was emptied. A reminder that
    says "covered" while the account is about to be overdrawn is worse than no reminder,
    because it is a green light built on the wrong number.

    So the comparison has three bands and the middle one carries the warning:
        balance >= statement      -> genuinely covered
        minimum <= balance < stmt -> covers the minimum ONLY, and an autopay set to the
                                     statement or interest-saving balance will overdraw it
        balance < minimum         -> not even the minimum
    The autopay amount itself is not in this email (see NEXT in the module docstring), so
    the middle band must be stated as a risk, never as a pass.
    """
    lines = [
        f"Card ...{card} payment is due in {days} days, on {due.strftime('%m/%d')}.",
        f"Minimum {human_money(info.get('minimum'))}, statement balance "
        f"{human_money(info.get('statement'))}.",
    ]
    if not funding or not bal:
        lines.append(
            "I do not have a funding account mapped for this card, so I cannot tell you "
            "whether the money is there - check it before the due date."
        )
        return "\n".join(lines)

    minimum = info.get("minimum")
    statement = info.get("statement")
    have = bal["amount"]
    when = bal["captured_at"][:16].replace("T", " ")
    lines.append(
        f"It draws from {funding['label']} ({funding['account_id']}), which held "
        f"{human_money(have)} as of {when} UTC."
    )

    if statement is not None and have >= statement:
        lines.append("That covers the full statement balance.")
    elif minimum is not None and have >= minimum:
        lines.append(
            f"That covers the minimum but NOT the statement balance. If an autopay is "
            f"set to pay the statement or the interest-saving balance it will take more "
            f"than this account holds and will overdraw it or be returned - move money "
            f"in, or lower the autopay, before {due.strftime('%m/%d')}."
        )
    else:
        lines.append(
            "That is NOT enough even for the minimum - move money in before the due date."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------- send


def send_owner(body: str, do_send: bool) -> tuple[bool, str]:
    os.makedirs(STATE_DIR, exist_ok=True)
    body_file = os.path.join(STATE_DIR, "outbox.txt")
    with open(body_file, "w", encoding="utf-8") as fh:
        fh.write(body + "\n")
    cmd = [PYTHON, TEXTSEND, "notify", "--body-file", body_file]
    if do_send:
        cmd.append("--send")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0 and "ok=True" in out, out.strip()


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--send", action="store_true",
                    help="actually text the owner (default: dry run)")
    ap.add_argument("--list", action="store_true",
                    help="show every parsed card due date and stop")
    ap.add_argument("--as-of", default=None,
                    help="treat this date (YYYY-MM-DD) as today, for verification")
    ap.add_argument("--lead-days", type=int, default=DEFAULT_LEAD_DAYS)
    ap.add_argument("--max-sends", type=int, default=DEFAULT_MAX_SENDS)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    today = (datetime.strptime(args.as_of, "%Y-%m-%d").date()
             if args.as_of else date.today())

    rows = read_catalog()
    balances = read_balances()
    funding_map = read_funding_map()

    # Newest observation per (card, due date) wins - a later email may correct one.
    observed: dict[tuple[str, str], dict] = {}
    for row in rows:
        parsed = parse_statement(row["snippet"])
        if not parsed:
            continue
        key = (parsed["card"], parsed["due"])
        rec = observed.get(key)
        if rec is None or (row["ts"] or 0) > (rec["ts"] or 0):
            parsed["ts"] = row["ts"]
            parsed["subject"] = row["subject"]
            parsed["source_account"] = row["account"]
            observed[key] = parsed

    entries = []
    for (card, raw_due), info in observed.items():
        due = parse_due(raw_due)
        if due is None:
            continue
        entries.append({
            "card": card,
            "due_raw": raw_due,
            "due": due,
            "days_out": (due - today).days,
            "minimum": info.get("minimum"),
            "statement": info.get("statement"),
            "autopay_flag": info.get("autopay_flag"),
            "email_subject": info.get("subject"),
            "email_at": info.get("ts"),
            "mailbox": info.get("source_account"),
        })
    entries.sort(key=lambda e: (e["due"], e["card"]))

    if args.list:
        if args.json:
            print(json.dumps(entries, indent=2, default=str))
            return 0
        if not entries:
            print("card-due-watch: no card due dates parsed from the catalog.")
            return 0
        print(f"{'card':<6} {'due':<12} {'days':>5}  {'minimum':>10} "
              f"{'statement':>11}  mailbox")
        for e in entries:
            print(f"...{e['card']:<4} {e['due_raw']:<12} {e['days_out']:>5}  "
                  f"{human_money(e['minimum']):>10} {human_money(e['statement']):>11}"
                  f"  {e['mailbox']}")
        return 0

    due_now = [e for e in entries if e["days_out"] == args.lead_days]
    state = load_state()
    sent_now = 0
    results = []

    for e in due_now:
        key = f"{e['card']}:{e['due_raw']}"
        if key in state.get("sent", {}):
            results.append({"key": key, "action": "already-sent",
                            "at": state["sent"][key]})
            continue
        if sent_now >= args.max_sends:
            results.append({"key": key, "action": "capped"})
            continue

        funding = funding_map.get(e["card"])
        bal = balances.get(funding["account_id"]) if funding else None
        body = compose(e["card"], e, funding, bal, e["due"], e["days_out"])
        ok, detail = send_owner(body, args.send)
        results.append({
            "key": key,
            "action": "sent" if (ok and args.send) else ("would-send" if ok else "FAILED"),
            "body": body,
            "detail": detail.splitlines()[0] if detail else "",
        })
        if ok and args.send:
            state.setdefault("sent", {})[key] = datetime.now(timezone.utc).isoformat()
            sent_now += 1

    if args.send and sent_now:
        save_state(state)

    if args.json:
        print(json.dumps({"as_of": str(today), "lead_days": args.lead_days,
                          "due_today_check": len(due_now), "results": results},
                         indent=2, default=str))
        return 0

    print(f"card-due-watch: as of {today}, lead {args.lead_days}d, "
          f"{len(entries)} parsed due date(s), {len(due_now)} at the lead point, "
          f"mode={'SEND' if args.send else 'DRY RUN'}")
    if not due_now:
        print("  nothing at the lead point today.")
    for r in results:
        print(f"  {r['key']}: {r['action']}")
        if r.get("body"):
            for line in r["body"].splitlines():
                print(f"      {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
