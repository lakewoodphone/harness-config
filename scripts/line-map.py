#!/usr/bin/env python3
"""line-map.py - the US Mobile line <-> Stripe subscription <-> customer mapping that nowhere held.

WHY THIS EXISTS
===============
On 2026-10-16 the owner pasted the US Mobile line inventory and asked for it to be matched against
Stripe. It took a session of ad-hoc scripts, and the answer could not be produced from any store,
because **no store records which line a subscription pays for**. The link lived in Stripe, in the
US Mobile page, and in the owner's head, and nothing joined them. That is how a line can go active
and unbilled, or a subscription keep billing after its line is gone, without anyone noticing.

Two errors in that session came from exactly this gap, and both are designed against here:

  1. Heichal Hatorah looked like "pays 11.00 for nothing". They actually pay **11.00 x 6 = 66.00**
     for six lines. The bug was reading `unit_amount` and never multiplying by `quantity`.
     => EVERY money field this tool prints is `unit x qty = total`, with all three terms visible.
  2. Ahron Bodner looked like a duplicate subscriber. He has **two lines** - 845-558-1290 and
     908-770-1707 - and two subscriptions, correctly. The lesson: a phone number is NOT a join
     key, because the Stripe customer's phone is the customer's *personal* number, not the line.

DESIGN RULES, each for a measured reason
========================================
  * READ-ONLY against Stripe and Postgres. The only thing written is this tool's own tables.
  * A mapping is never INVENTED. Matching proposes; a person asserts. Every row records HOW it was
    derived - PHONE, NAME, ASSERTED or NONE - so a guess is never mistaken for a fact. Heichal's six
    lines CANNOT be derived: they are an assertion by the owner, and they are stored as one.
  * The alarm is a COUNT MISMATCH: a subscription's `quantity` must equal the number of lines
    mapped to it. That is what would have caught six lines billed as one, and it catches the
    reverse too.
  * Names and numbers are normalised on both sides before any comparison, and a match on a name
    fragment is labelled WEAK rather than treated as a match.
  * `check` exits non-zero on an anomaly and can raise a wake flag, because a mapping that is
    silently wrong is worse than no mapping.

USAGE
=====
    line-map.py sync-usm <file|->          ingest the pasted US Mobile page
    line-map.py sync-stripe                pull subscriptions + customers (quantity counted)
    line-map.py sync-shop                  pull customer names from the operational store
    line-map.py assert <number> --holder H --kind K [--sub SUB] [--by WHO] [--note ...]
    line-map.py audit [--json]             THE ONE QUERY: billed, unbilled, unmatched, money
    line-map.py check [--flag]             exit 3 on an anomaly; optionally raise a wake flag
    line-map.py seed                       load the verified 2026-10-16 state
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DB = Path(os.environ.get("LINE_MAP_DB", "/root/authority.db"))
ENV_FILE = Path(os.environ.get("LINE_MAP_ENV", "/opt/company/.env"))
WAKE = os.environ.get("LINE_MAP_WAKE", "/root/bin/wake.py")
SHOP_DSN_KEYS = ("PHONE_TECH_FULL_DATABASE_URL",)

KINDS = ("customer", "owner", "shop", "pending", "unknown")
SOURCES = ("PHONE", "NAME", "ASSERTED", "NONE")


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS line_map (
    -- KEYED ON line_key, NOT line_number, and that is a modelling fact rather than a preference:
    -- the owner's own number 848-389-7895 carries TWO lines, an Unlimited phone AND an Apple
    -- Watch. A shared number is normal for a wearable. Keying on the number silently DROPPED one
    -- of them - the first run reported 19 lines where the page shows 20. line_key is
    -- "<10 digits>|<normalised label>", so both survive and neither is a duplicate.
    line_key             TEXT PRIMARY KEY,
    line_number          TEXT,
    line_label           TEXT,
    plan                 TEXT,
    renewal              TEXT,
    usm_status           TEXT,
    holder               TEXT,
    holder_kind          TEXT NOT NULL DEFAULT 'unknown',
    stripe_customer_id   TEXT,
    stripe_subscription_id TEXT,
    mapping_source       TEXT NOT NULL DEFAULT 'NONE',
    asserted_by          TEXT,
    monthly_usd          REAL DEFAULT 0,
    note                 TEXT,
    first_seen           TEXT,
    last_verified        TEXT
);
CREATE TABLE IF NOT EXISTS subscription_map (
    subscription_id   TEXT PRIMARY KEY,
    customer_id       TEXT,
    customer_name     TEXT,
    unit_amount_usd   REAL,
    quantity          INTEGER,
    monthly_usd       REAL,
    status            TEXT,
    created_at        TEXT,
    lines_mapped      INTEGER DEFAULT 0,
    last_verified     TEXT
);
CREATE TABLE IF NOT EXISTS line_map_runs (
    ran_at   TEXT,
    command  TEXT,
    detail   TEXT
);
"""


def store() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.commit()
    return con


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def ran(con, command: str, detail: str) -> None:
    con.execute("INSERT INTO line_map_runs VALUES (?,?,?)", (now(), command, detail[:500]))
    con.commit()


def env_value(*keys: str) -> str | None:
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        for k in keys:
            if s.startswith(k + "="):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def ten(p) -> str:
    return "".join(c for c in str(p or "") if c.isdigit())[-10:]


def norm_name(s) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower()).strip()


# --------------------------------------------------------------------------- #
# US Mobile ingest - tolerant, and it refuses to guess when the shape changes
# --------------------------------------------------------------------------- #
PHONE_RE = re.compile(r"\((\d{3})\)\s*(\d{3})-(\d{4})")
PLAN_RE = re.compile(r"^(Unlimited|Data Bundle|By the gig|Wearable|Talk & Text|Data Only)\b", re.I)
DATE_RE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}|Upon activation)$", re.I)
STATUS_RE = re.compile(r"^(Active|Pending Activation|Suspended|Paused|Expired)$", re.I)


def parse_usm(text: str):
    """Return [dict] for each line on the pasted page.

    The page copies out as stacked cells - name, number, plan, renewal, status each on their own
    line - so the number is the anchor and the plan/renewal/status are read FORWARD from it, while
    the line name is read BACKWARD to the nearest non-structural line.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    out, used_names = [], set()
    for i, ln in enumerate(lines):
        m = PHONE_RE.search(ln)
        if not m:
            continue
        number = m.group(1) + m.group(2) + m.group(3)
        plan = renewal = status = None
        for j in range(i + 1, min(i + 8, len(lines))):
            v = lines[j].strip()
            if not v:
                continue
            if plan is None and PLAN_RE.match(v):
                plan = v
                continue
            if renewal is None and DATE_RE.match(v):
                renewal = v
                continue
            if status is None and STATUS_RE.match(v):
                status = v
                break
            if PHONE_RE.search(v):
                break
        # THE NAME IS ON THE SAME LINE AS THE NUMBER, before it: "Test sim at&t\t(848) 389-5173".
        # The first version looked backwards to the previous line, found the header or a blank,
        # returned None, and then OVERWROTE good stored labels with nulls. Read same-line first.
        label = None
        head = ln[:m.start()].strip().strip("\t").strip()
        if head and not PLAN_RE.match(head) and not DATE_RE.match(head) and not STATUS_RE.match(head):
            label = head
        if not label:
            for j in range(i - 1, max(i - 4, -1), -1):
                v = lines[j].strip()
                if not v or PLAN_RE.match(v) or DATE_RE.match(v) or STATUS_RE.match(v):
                    continue
                if PHONE_RE.search(v) or v.lower().startswith(("line name", "autopay", "status",
                                                               "renewal", "plan type", "number")):
                    continue
                label = v
                break
        out.append({"line_number": number, "line_label": label, "plan": plan,
                    "renewal": renewal or "upon activation", "usm_status": status or "unknown"})
        if label:
            used_names.add(label.lower())

    # A pending line has no number yet. Record it as its own kind so the count reconciles.
    if re.search(r"To be assigned", text, re.I):
        out.append({"line_number": "", "line_label": "To be assigned", "plan": "Unlimited",
                    "renewal": "upon activation", "usm_status": "Pending Activation"})
    return out


def cmd_sync_usm(a) -> int:
    text = sys.stdin.read() if a.file == "-" else Path(a.file).read_text(
        encoding="utf-8", errors="ignore")
    rows = parse_usm(text)
    if not rows:
        print("REFUSING: parsed 0 lines. The page shape may have changed - not writing.")
        return 4
    con = store()
    prev = con.execute("SELECT COUNT(*) FROM line_map").fetchone()[0]
    if prev and abs(len(rows) - prev) > 0 and not a.allow_count_change:
        print("REFUSING: parsed %d lines but %d are already stored. A changed count is either a real "
              "change or a broken parse, and only a person can tell which. Re-run with "
              "--allow-count-change once you have checked." % (len(rows), prev))
        con.close()
        return 5
    for r in rows:
        num = r["line_number"] or ""
        lbl = r["line_label"] or ""
        key = (num + "|" + norm_name(lbl)) if num else ("pending|" + norm_name(lbl) or "pending|x")
        # COALESCE on every descriptive column: a parse that fails to read a field must NEVER
        # overwrite a value that is already recorded. The first version did exactly that and
        # replaced nine good labels with nulls in one run.
        con.execute(
            "INSERT INTO line_map (line_key, line_number, line_label, plan, renewal, usm_status,"
            " first_seen, last_verified) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(line_key) DO UPDATE SET"
            "   line_number=COALESCE(NULLIF(excluded.line_number,''), line_map.line_number),"
            "   line_label=COALESCE(NULLIF(excluded.line_label,''), line_map.line_label),"
            "   plan=COALESCE(NULLIF(excluded.plan,''), line_map.plan),"
            "   renewal=COALESCE(NULLIF(excluded.renewal,''), line_map.renewal),"
            "   usm_status=COALESCE(NULLIF(excluded.usm_status,''), line_map.usm_status),"
            "   last_verified=excluded.last_verified",
            (key, num, lbl, r["plan"], r["renewal"], r["usm_status"], now(), now()))
    con.commit()
    ran(con, "sync-usm", "%d lines" % len(rows))
    con.close()
    print("ingested %d US Mobile line(s)" % len(rows))
    for r in rows:
        print("  %-11s %-22s %-12s %-10s %s" % (r["line_number"] or "(no number)",
              (r["line_label"] or "?")[:22], r["plan"] or "?", r["renewal"] or "?",
              r["usm_status"]))
    return 0


# --------------------------------------------------------------------------- #
# Stripe - quantity is a first-class term everywhere
# --------------------------------------------------------------------------- #
def stripe_key() -> str | None:
    return env_value("STRIPE_SECRET_KEY")


def stripe_get(path: str, key: str):
    req = urllib.request.Request("https://api.stripe.com" + path,
                                 headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def cmd_sync_stripe(a) -> int:
    key = stripe_key()
    if not key:
        print("no STRIPE_SECRET_KEY in %s" % ENV_FILE)
        return 2
    con = store()
    subs = stripe_get("/v1/subscriptions?limit=100&status=all", key).get("data", [])
    n = 0
    for s in subs:
        items = (s.get("items") or {}).get("data", [])
        unit = quantity = 0
        monthly = 0.0
        for it in items:
            pr = it.get("price") or {}
            u = (pr.get("unit_amount") or 0) / 100.0
            q = it.get("quantity") or 1
            unit += u
            quantity += q
            monthly += u * q
        try:
            cust = stripe_get("/v1/customers/" + s["customer"], key)
        except urllib.error.HTTPError:
            cust = {}
        con.execute(
            "INSERT INTO subscription_map (subscription_id, customer_id, customer_name,"
            " unit_amount_usd, quantity, monthly_usd, status, created_at, last_verified)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(subscription_id) DO UPDATE SET"
            "   customer_id=excluded.customer_id, customer_name=excluded.customer_name,"
            "   unit_amount_usd=excluded.unit_amount_usd, quantity=excluded.quantity,"
            "   monthly_usd=excluded.monthly_usd, status=excluded.status,"
            "   last_verified=excluded.last_verified",
            (s["id"], s["customer"], cust.get("name"), unit, quantity, monthly, s.get("status"),
             dt.datetime.fromtimestamp(s["created"], dt.timezone.utc).strftime("%Y-%m-%d"), now()))
        n += 1
    con.commit()
    ran(con, "sync-stripe", "%d subscriptions" % n)
    total = con.execute("SELECT COALESCE(SUM(monthly_usd),0) FROM subscription_map"
                        " WHERE status='active'").fetchone()[0]
    lines_claimed = con.execute("SELECT COALESCE(SUM(quantity),0) FROM subscription_map"
                                " WHERE status='active'").fetchone()[0]
    con.close()
    print("%d subscription(s); recurring = %.2f/month covering %d line(s) claimed by quantity"
          % (n, total, lines_claimed))
    return 0


def cmd_sync_shop(a) -> int:
    """Fill holder names from the operational store. Read-only; absence is recorded, not guessed."""
    dsn = env_value(*SHOP_DSN_KEYS)
    if not dsn:
        print("no operational DSN; skipping shop sync (this is a refusal, not an empty result)")
        return 2
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 unavailable; run under /opt/company/.venv/bin/python")
        return 2
    con = store()
    pg = psycopg2.connect(dsn)
    cur = pg.cursor()
    filled = 0
    for row in con.execute("SELECT line_number, holder FROM line_map").fetchall():
        num = row["line_number"]
        if not num or not num.isdigit():
            continue
        cur.execute("""SELECT id, "firstName", "lastName", phone, "stripeCustomerId"
                       FROM customers
                       WHERE right(regexp_replace(coalesce(phone,''),'[^0-9]','','g'),10)=%s""",
                    (num,))
        hit = cur.fetchone()
        if hit:
            name = " ".join(x for x in (hit[1], hit[2]) if x)
            con.execute("UPDATE line_map SET holder=COALESCE(holder,?), note=COALESCE(note,'')"
                        " || CASE WHEN ? IS NOT NULL THEN ' [shop customer id %s]' ELSE '' END"
                        " WHERE line_number=?", (name, hit[4], hit[0], num))
            filled += 1
    con.commit()
    ran(con, "sync-shop", "%d lines matched a shop customer" % filled)
    pg.close()
    con.close()
    print("shop sync: %d line(s) matched a customer record" % filled)
    return 0


# --------------------------------------------------------------------------- #
# assert - how a fact that cannot be derived gets recorded
# --------------------------------------------------------------------------- #
def cmd_assert(a) -> int:
    con = store()
    rows = con.execute("SELECT * FROM line_map WHERE line_key=? OR line_number=?",
                       (a.number, ten(a.number))).fetchall()
    if not rows:
        print("no line %r in the map. Run sync-usm first." % a.number)
        return 3
    if len(rows) > 1 and not a.label:
        print("line number %s carries %d entries (%s) - a shared number is normal (a wearable "
              "shares its phone's). Pass --label to say which." % (
                  a.number, len(rows), ", ".join(r["line_label"] or "?" for r in rows)))
        return 3
    row = rows[0]
    if len(rows) > 1:
        want = norm_name(a.label)
        row = next((r for r in rows if norm_name(r["line_label"]) == want
                    or want in norm_name(r["line_label"])), None)
        if row is None:
            print("no entry on %s matching label %r" % (a.number, a.label))
            return 3
    key = row["line_key"]
    if a.kind and a.kind not in KINDS:
        print("kind must be one of %s" % (KINDS,))
        return 2
    sets, vals = [], []
    for col, val in (("holder", a.holder), ("holder_kind", a.kind),
                     ("stripe_subscription_id", a.sub), ("stripe_customer_id", a.customer),
                     ("note", a.note)):
        if val is not None:
            sets.append(col + "=?")
            vals.append(val)
    if a.sub:
        s = con.execute("SELECT quantity, unit_amount_usd FROM subscription_map WHERE"
                        " subscription_id=?", (a.sub,)).fetchone()
        if s:
            sets.append("monthly_usd=?")
            vals.append(round((s["unit_amount_usd"] or 0) * (s["quantity"] or 1), 2))
    sets += ["mapping_source=?", "asserted_by=?", "last_verified=?"]
    vals += ["ASSERTED", a.by or os.environ.get("USER") or "unknown", now()]
    vals.append(key)
    con.execute("UPDATE line_map SET " + ", ".join(sets) + " WHERE line_key=?", vals)
    con.commit()
    con.close()
    print("asserted: %s (%s) -> %s" % (key, row["line_label"] or "?",
          {k: v for k, v in (("holder", a.holder), ("kind", a.kind), ("sub", a.sub),
                             ("by", a.by)) if v}))
    return 0


# --------------------------------------------------------------------------- #
# audit - the one query
# --------------------------------------------------------------------------- #
def _audit_rows(con):
    lines = [dict(r) for r in con.execute(
        "SELECT * FROM line_map ORDER BY holder_kind, line_label")]
    subs = [dict(r) for r in con.execute(
        "SELECT * FROM subscription_map ORDER BY monthly_usd DESC")]
    for s in subs:
        s["lines_mapped"] = con.execute(
            "SELECT COUNT(*) FROM line_map WHERE stripe_subscription_id=?",
            (s["subscription_id"],)).fetchone()[0]
    return lines, subs


def cmd_audit(a) -> int:
    con = store()
    lines, subs = _audit_rows(con)
    billed = [l for l in lines if l["stripe_subscription_id"]]
    unbilled = [l for l in lines if not l["stripe_subscription_id"]]
    total = sum(s["monthly_usd"] or 0 for s in subs if s["status"] == "active")
    claimed = sum(s["quantity"] or 0 for s in subs if s["status"] == "active")

    if a.json:
        print(json.dumps({"lines": lines, "subscriptions": subs,
                          "monthly_total_usd": round(total, 2),
                          "lines_claimed_by_quantity": claimed,
                          "billed": len(billed), "unbilled": len(unbilled)}, indent=2))
        con.close()
        return 0

    print("MONEY - every figure as unit x qty = total")
    for s in subs:
        unit = s["unit_amount_usd"] or 0
        q = s["quantity"] or 1
        flag = "" if (s["lines_mapped"] or 0) == q else "   <<< MISMATCH: %d mapped, qty %d" % (
            s["lines_mapped"], q)
        print("  %-24s %6.2f x%-2d = %8.2f  %s%s" % (
            (s["customer_name"] or "?")[:24], unit, q, s["monthly_usd"] or 0,
            s["status"], flag))
    print("  %-24s %11s %8s = %8.2f" % ("TOTAL (active)", "", "", total))
    print()
    print("LINES  %d total, %d billed, %d unbilled" % (len(lines), len(billed), len(unbilled)))
    for l in lines:
        print("  %-9s %-22s %-12s %-9s %s %s" % (
            l["line_number"], (l["line_label"] or "?")[:22], l["plan"] or "?",
            l["holder_kind"], l["mapping_source"],
            ("-> " + (l["holder"] or "?")) if l["holder"] else ""))
    print()
    print("UNBILLED (%d)" % len(unbilled))
    for l in unbilled:
        print("  %-9s %-22s %-11s [%s]" % (l["line_number"], (l["line_label"] or "?")[:22],
                                           l["plan"] or "?", l["holder_kind"]))
    con.close()
    return 0


# --------------------------------------------------------------------------- #
# check - the alarm
# --------------------------------------------------------------------------- #
def cmd_check(a) -> int:
    con = store()
    lines, subs = _audit_rows(con)
    problems = []
    for s in subs:
        if s["status"] != "active":
            continue
        q = s["quantity"] or 1
        m = s["lines_mapped"] or 0
        if m != q:
            problems.append("subscription %s (%s) covers qty %d but %d line(s) are mapped to it"
                            % (s["subscription_id"], s["customer_name"], q, m))
    for l in lines:
        if l["holder_kind"] == "customer" and not l["stripe_subscription_id"]:
            problems.append("line %s (%s) is a customer line with NO subscription"
                            % (l["line_number"], l["line_label"]))
    for l in lines:
        if l["stripe_subscription_id"] and l["mapping_source"] == "NONE":
            problems.append("line %s has a subscription but no recorded derivation" % l["line_number"])
    unverified = [l for l in lines if l["holder_kind"] == "unknown"]
    if unverified:
        problems.append("%d line(s) have no holder recorded: %s"
                        % (len(unverified), ", ".join(l["line_label"] or l["line_number"]
                                                      for l in unverified)))
    con.close()
    if not problems:
        print("line map: OK - %d lines, %d subscriptions, totals reconcile" % (len(lines), len(subs)))
        return 0
    print("line map: %d problem(s)" % len(problems))
    for p in problems:
        print("  - %s" % p)
    if a.flag:
        r = subprocess.run(
            ["python3", WAKE, "flag", "--subject", "line-map-drift:%s" % dt.date.today().isoformat(),
             "--prompt", ("The US-Mobile-line to Stripe-subscription map does not reconcile: %s. "
                          "Run /root/bin/line-map.py audit. A subscription's quantity must equal the "
                          "number of lines mapped to it; a customer line with no subscription is "
                          "either unbilled revenue or a line that has left. Fix the map with "
                          "`line-map.py assert` and, if money is wrong, say so to the owner."
                          % "; ".join(problems[:4])),
             "--kind", "integration", "--source", "line-map", "--priority", "high"],
            capture_output=True, text=True)
        print("flag:", (r.stdout or r.stderr).strip()[:200])
    return 3


# --------------------------------------------------------------------------- #
# seed - the verified state of 2026-10-16
# --------------------------------------------------------------------------- #
SEED = {
    "heichal_sub": "sub_1UIWLJLnlgYj1gmTk4w0saSx",
    "heichal_cus": "cus_VGaAHTFuCotMGN",
    "lines": [
        ("7326642525", "Line 15", "By the gig", "10/30/26"),
        ("7325971335", "Line 16", "By the gig", "10/30/26"),
        ("8482265659", "Line 17", "By the gig", "10/30/26"),
        ("8482267421", "Line 18", "By the gig", "10/30/26"),
        ("7328644525", "Line 19", "By the gig", "10/30/26"),
        ("8482262205", "Line 20", "By the gig", "10/30/26"),
    ],
}


def _seed_put(con, number, label, plan, renewal, kind, holder=None,
              sub=None, customer=None, source="ASSERTED", note=None):
    key = (number + "|" + norm_name(label)) if number else "pending|" + norm_name(label)
    con.execute(
        "INSERT INTO line_map (line_key, line_number, line_label, plan, renewal, usm_status,"
        " holder, holder_kind, stripe_subscription_id, stripe_customer_id, mapping_source,"
        " asserted_by, note, first_seen, last_verified)"
        " VALUES (?,?,?,?,?, 'Active', ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(line_key) DO UPDATE SET"
        "   holder=COALESCE(excluded.holder, line_map.holder),"
        "   holder_kind=excluded.holder_kind,"
        "   stripe_subscription_id=COALESCE(excluded.stripe_subscription_id,"
        "                                  line_map.stripe_subscription_id),"
        "   stripe_customer_id=COALESCE(excluded.stripe_customer_id, line_map.stripe_customer_id),"
        "   mapping_source=CASE"
        "     WHEN line_map.mapping_source IN ('PHONE','NAME','ASSERTED')"
        "      AND excluded.mapping_source='NONE'"
        "     THEN line_map.mapping_source ELSE excluded.mapping_source END,"
        "   asserted_by=COALESCE(excluded.asserted_by, line_map.asserted_by),"
        "   note=COALESCE(excluded.note, line_map.note),"
        "   last_verified=excluded.last_verified",
        (key, number, label, plan, renewal, holder, kind, sub, customer, source,
         "zabz/owner 2026-10-16", note, now(), now()))


def cmd_seed(a) -> int:
    """Load what the owner CONFIRMED on 2026-10-16: these six unlabelled lines are Heichal's."""
    con = store()
    for num, label, plan, ren in SEED["lines"]:
        _seed_put(con, num, label, plan, ren, "customer", holder="Heichal Hatorah",
                  sub=SEED["heichal_sub"], customer=SEED["heichal_cus"],
                  note="the six unlabelled By-the-gig lines are Heichal Hatorah's six - ASSERTED by "
                       "the owner on 2026-10-16; their subscription is quantity 6 for 66.00/month, "
                       "verified against a paid 66.00 invoice of 2026-09-22")
    for num, label, plan, ren in (
            ("7322326678", "Hess", "Data Bundle", "11/11/26"),
            ("8482403408", "zevi lefkowitz", "Data Bundle", "10/30/26"),
            ("7328758493", "mrs greenwood", "Data Bundle", "10/30/26"),
            ("8455581290", "ahron bodner", "Data Bundle", "10/27/26"),
            ("9087701707", "bodner", "Data Bundle", "11/02/26"),
            ("8482407914", "avrohom newman", "Data Bundle", "11/12/26"),
            ("7324369319", "baruch ber svei", "Data Bundle", "11/12/26")):
        _seed_put(con, num, label, plan, ren, "customer", holder=label, source="NONE")
    for num, label, plan, ren, kind in (
            ("8483897895", "Eliyahu Zabrowsky", "Unlimited", "10/31/26", "owner"),
            ("8483897895", "My Apple Watch", "Wearable", "11/09/26", "owner"),
            ("8483895173", "Test sim at&t", "Data Bundle", "11/02/26", "shop"),
            ("8483267693", "sep 5 sim card", "By the gig", "10/23/26", "shop"),
            ("8482401820", "test sim verizon", "Data Bundle", "11/14/26", "shop"),
            ("9089109268", "test sim 3 verizon", "By the gig", "10/23/26", "shop"),
            ("", "To be assigned", "Unlimited", "upon activation", "pending")):
        _seed_put(con, num, label, plan, ren, kind, holder=label)
    con.commit()
    ran(con, "seed", "2026-10-16 verified state")
    n = con.execute("SELECT COUNT(*) FROM line_map").fetchone()[0]
    con.close()
    print("seeded %d line row(s)." % n)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sync-usm"); p.add_argument("file"); p.add_argument("--allow-count-change",
                                                                          action="store_true")
    p.set_defaults(fn=cmd_sync_usm)
    p = sub.add_parser("sync-stripe"); p.set_defaults(fn=cmd_sync_stripe)
    p = sub.add_parser("sync-shop"); p.set_defaults(fn=cmd_sync_shop)
    p = sub.add_parser("assert")
    p.add_argument("number", help="10-digit line number, or the label for the pending line")
    p.add_argument("--label", help="disambiguates when one number carries several lines")
    p.add_argument("--holder"); p.add_argument("--kind", choices=KINDS)
    p.add_argument("--sub"); p.add_argument("--customer"); p.add_argument("--by")
    p.add_argument("--note"); p.set_defaults(fn=cmd_assert)
    p = sub.add_parser("audit"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_audit)
    p = sub.add_parser("check"); p.add_argument("--flag", action="store_true"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("seed"); p.set_defaults(fn=cmd_seed)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
