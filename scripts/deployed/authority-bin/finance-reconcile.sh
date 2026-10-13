#!/bin/sh
# /usr/local/bin/finance-reconcile.sh -- the program's SECOND completion condition, on a clock.
#
# WHY (finance fleet 2026-10-13): the CFO program is defined as done when every account-month is
# (1) explained, (2) RECONCILED against the account's own balance movement, and (3) carries no
# unnamed exception. Only (1) was ever measured.
#
# MAIL IS READ, AND THAT IS DELIBERATE (changed 2026-10-13). The first version passed --no-mail
# for speed. Measured over the same ledger and window:
#     --no-mail : anchored  59, disagreements 21
#     with mail : anchored 119, disagreements 69
# Reading statement balances out of Gmail - through the application's own reader, the one
# cfo-balances.py already calls - DOUBLES the months that can be judged at all, and surfaces 48
# disagreements the snapshot-only run could not see (2025 gaps on personal-chase-9650 and
# lpt-chase-7542 among them). A reconciliation that cannot see half the months is not a cheaper
# reconciliation, it is a smaller one.
#
# READ-ONLY: the ledger is opened mode=ro and the tool contains no write statement.
set -eu
OUT=${FINANCE_RECONCILE_OUT:-/root/.cfo/balances-live.json}
WORKLIST=${FINANCE_RECONCILE_WORKLIST:-/root/.cfo/reconciliation-worklist.md}
LEDGER=${ACCOUNTING_DB_PATH:-/root/accounting-data/live/accounting.db}
MAIL_MAX_AGE_DAYS=${FINANCE_RECONCILE_MAIL_MAX_AGE_DAYS:-400}
/usr/bin/python3 /root/bin/cfo-balances.py --build --months 24 --ledger "$LEDGER" \
    --mail-max-age-days "$MAIL_MAX_AGE_DAYS" --out "$OUT" >/dev/null
/usr/bin/python3 - "$OUT" "$WORKLIST" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
rows = []
for a in d["accounts"]:
    for ds in (a.get("disagreements") or []):
        rows.append((abs(ds.get("delta_cents") or 0), a.get("account_id"), ds.get("month"),
                     ds.get("derived_cents"), ds.get("anchored_cents"), ds.get("delta_cents"),
                     ds.get("note"), ds.get("anchor_warned")))
rows.sort(reverse=True)
t = d["totals"]
lines = ["# Reconciliation -- account-months where the ledger and the balance disagree", "",
         f"Generated {d.get('at')} from {sys.argv[1]}.", 
         f"window {d['window']['from']} .. {d['window']['to']}; account-months {t['account_months']} "
         f"anchored {t['anchored']} derived {t['derived']} unknown {t['unknown']} "
         f"DISAGREEMENTS {t['disagreements']} (of which {t.get('disagreements_from_warned_anchor', 0)} "
         f"open on an anchor the tool itself warns about)",
         "", "| account | month | derived | anchored | delta | anchor_warned | note |",
         "|---|---|---|---|---|---|---|"]
for r in rows:
    lines.append(f"| {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[7]} | {r[6]} |")
open(sys.argv[2], "w").write("\n".join(lines) + "\n")
print(f"reconciliation: {t['disagreements']} disagreement(s), {t['anchored']} anchored month(s), "
      f"{t.get('disagreements_from_warned_anchor', 0)} from a warned anchor")
PYEOF
