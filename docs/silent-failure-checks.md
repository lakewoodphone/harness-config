# The three questions that find a silent failure

Written 2026-10-13 on `secratary-cloud`, after one session found **twelve** defects that all had the same
shape: **the code was good, the artifact existed, and the connection to a clock, a reader or a repository
was missing.** Every one of them looked healthy from the outside. This is the checklist that found them,
in the order that found them fastest.

## 1. When did this capability last RUN?

```bash
python3 /root/bin/cron-liveness.py        # NEVER RAN / STALE / non-zero exit, from the crontab + runs.tsv
```

A job that never ran and a job that runs correctly print nothing different. Six found this way:
`marketplace-orders-sync.sh` documented *"SCHEDULE. 05:10 UTC"* in its own header and **had no crontab
entry at all**; `tax-deadlines.py` ran daily and wrote a file nothing read; `forward-view.py` was a
working 36-month forward statement that **had never been executed once**.

## 2. Who READS this artifact?

```bash
grep -rl -- '<artifact-name>' /root/bin /usr/local/bin /opt/company/scripts | grep -v '<artifact-name>'
```

A report with no reader is a cron exiting 0 into silence. `cron-liveness.py` itself was written because
this question, asked of `/root/.cfo`, found exactly one orphan — which is the point: the question is cheap
enough to ask of everything.

## 3. Is it IN THE REPOSITORY?

```bash
git -C /opt/company status --porcelain | grep '^??' | grep '\.py$' | grep -v '\.bak'
```

**This one was added last and found the largest defect of the session.** `marketplace_order_sync.py` — 2,310
lines of money-critical code — was **untracked**, existing only as working-tree state. So were
`forward-view.py`, `finance_freshness.py`, `statement_csv_import.py` and `lpt_analytics/tracking.py`: 19
modules and 9,175 lines with no history anywhere. A file that runs perfectly and is not in version control
looks identical from the outside to one that is.

**And the distinction that makes the fix correct rather than tidy:** an **untracked** file has no record, so
committing it *creates* one — do it. A **modified** file has a committed baseline, so committing it blends
changes you cannot account for into a new baseline — do not, unless you have read the diff and can say what
changed. "Commit everything" is wrong; "commit what has no account at all" is right.

## The other two, which are about evidence rather than plumbing

**4. Is the measurement INDEPENDENT of the thing it tests?** Twice in one session a number was reasoned from
that turned out to be downstream of what was being tested — once a balance reading used to explain the
transactions it was computed from.

**5. Is the value IMPOSSIBLE?** A deposit account cannot hold a negative balance. That single invariant
found a savings account with 22 impossible months, and adding it as a rule (`R4` in `cfo-balances.py`)
reconciled the account.

## What this checklist is NOT

**It is not a licence to fix what you find before reading it.** Of twelve apparent defects in that session,
**six were false alarms** — four were two fields meaning two things, or a lagging tail. Read the artifact's
own docstring or the code that produced the reading **before** proposing a change. `AGENTS.md` section 0
already says it: *prove it does not already exist.* The freshness source (`sources/finance-freshness.py`)
proves the point — it already alarmed on the *second* of these questions, on two axes, because someone had
measured the same problem properly and written the reason down.

## The one-line version

> **A capability that never ran, an artifact nobody reads, and a file with no history all look exactly like
> working systems. Ask about all three, and read before you fix.**