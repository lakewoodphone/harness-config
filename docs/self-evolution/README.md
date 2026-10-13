# The weekly evolution audit

**Owner's ask, 2026-10-13:** *"this should be like, you know, once a week or whatever, maybe even
more often. You should do a full audit in figure out, how are you wildly evolving this week."*

This directory is that ritual, made **reproducible, scheduled and measured** — not a promise and not
a document to be read. It is three artefacts, and nothing else:

| artefact | file | what it is |
|---|---|---|
| **the measurement** | `scripts/self-audit/weekly-evolution-audit.py` | what actually CHANGED in the last 7 days, as JSON + a one-screen digest, with a diff against the previous run |
| **the judge** | `scripts/self-audit/weekly-evolution.py` | a wake source that files the audit as work once per ISO week, and stays `quiet` when nothing moved |
| **the record** | this file + `runs/` | the ritual explained, and the FIRST REAL RUN's output committed |

It does not build a second journal, ledger or scheduler. It reads the ones that exist
(`journal.py`, `wake.py`, `work.py`, `git`, `systemd`) and cites them.

## The exact command a future session runs

On the authority (`secratary-cloud`, where the stores live):

```bash
python3 ~/code/harness-config/scripts/self-audit/weekly-evolution-audit.py \
    --repo ~/code/harness-config --out ~/.self-audit/runs --window-days 7
```

It prints the digest and writes `~/.self-audit/runs/run-<UTC>.json` plus `latest.json`.
Exit `0` means the record was produced, **even when some cells are `COULD NOT ASK`** — a blank is
never a zero. Exit `1` only means nothing could be written at all.

## The one rule every number obeys

Every metric carries **the exact command that produced it**, its **source**, and its **freshness**
(`live` / `git` / `file`). A file's mtime is not content freshness. When a store cannot be read the
cell is `COULD NOT ASK` with a `reason` and the `probes` tried — never `0`, never a guess. This is
the same rule `_flag.py` uses for wake sources: *an unreadable signal is never healthy.*

## What it measures

| metric | source | freshness |
|---|---|---|
| journal entries added, **by kind** | `journal.py list --since <7d> --json` — the tool is the only door to the tree | live |
| open-pain count (the estate's own) | `journal.py list --kind pain --status open --json` | live |
| wake releases in the window | read-only SQL on `~/.sms-inbox/inbox.db` table `wake` | live |
| wake store stats (released today, spend line) | `wake.py stats` | live |
| ledger closed **with proof** vs **left open** | read-only SQL `~/work/work.db`: `work_item` × `attempt.proof` (proof lives on the attempt, not the item) | live |
| owner queue filed / resolved / pending | read-only SQL `owner_decision_queue`, from the candidate DB with the most rows (`/root/authority.db`) | live |
| commits landing on `harness-config` | `git log --since --pretty=%H`, plus distinct files touched | git |
| new capabilities (sources, scripts, skills, routes, docs added) | `git log --since --diff-filter=A --name-only` | git |
| sources registered live | `ls ~/bin/sources/*.py` | live |
| services / timers | `systemctl list-units --state=running`, `list-timers` | live |
| sessions / agents run | probe of local dsh/session stores; `COULD NOT ASK` when none exist | live |
| spend for the week against its ceiling | `~/.sms-inbox/wake-cost.jsonl`; `COULD NOT ASK` when the store itself reports spend `UNMEASURED` | file |

## The judge: how it files, and how it stays quiet

`weekly-evolution.py` imports the **frozen** `_flag.py` plumbing from the live sources dir
(`WAKE_SOURCES_DIR`, default `~/bin/sources`) and obeys the frozen output contract: stdout is
exactly `quiet` or `flagged <subject>`; diagnostics go to stderr; it files only through the `flag`
CLI inside `_flag.flag`.

* **Subject (the dedup key):** `self-audit:<ISO-year>-W<ISO-week>` — e.g. `self-audit:2026-W42`.
  Stable for the whole week, so the store's own subject dedup turns a second file attempt into a
  `deduped`, never a second session. The finding also carries `cooldown_seconds=604800`.
* **It fires when:** no previous run exists (the baseline has real work), **or** something
  measurable changed since the previous run, **or** an instrument went dark (a metric that was
  `measured` is now `COULD NOT ASK`).
* **It stays `quiet` when:** a previous run exists and every measured value is identical and no
  instrument regressed. **A quiet week is a finding, not a silence.**

No source keeps state; the wake store is the only state (dedup, caps, cooldown, night gate).
Nothing on a timer raises a flag by itself — the flag exists because there IS work.

### Registration line for `run-wake-sources.sh` (content only — NOT installed here)

The orchestrator adds the source to the loop list and copies the two files to the live sources dir:

```bash
# install (orchestrator): cp the two files together, then register the source
install -m 0755 scripts/self-audit/weekly-evolution.py        /root/bin/sources/
install -m 0755 scripts/self-audit/weekly-evolution-audit.py  /root/bin/sources/

# registration: add `weekly-evolution` to the `for s in ...` list in
# run-wake-sources.sh, next to the existing judges:
#   ... project-keepalive ledger-keepalive weekly-evolution wake-tuner
```

`run-wake-sources.sh` runs every source every few minutes; this one is weekly *because the subject
is the week*, not because the runner knows a calendar.

## Evidence: the first real run, 2026-10-13 on `secratary-cloud`

`runs/first-real-run-2026-10-13.json` is the raw record. `runs/first-real-run-2026-10-13.digest.txt`
is the digest, verbatim:

* 50 journal entries in the window · 50 open pain · 128 wake releases · queue filed 167 /
  resolved 38 / pending 157 · 28 services · 22 timers · 25 live sources.
* `closed_with_proof 0` / `left_open 0` — the cloud ledger is empty; a measured zero, not a blank.
* `spend COULD NOT ASK` — the store itself reports spend `UNMEASURED` (no `wake-cost.jsonl`), so the
  USD cap cannot fire. That is a broken instrument, reported as such.

`runs/second-run-2026-10-13.json` + `.digest.txt` are a later run the same day, so the record ships
with a **diff that is not a baseline** and with the by-kind line the first digest predates: the
digest now prints `by_kind 50 [live] … {"decisions": 6, "handoff": 15, "lessons": 23, "pain": 6}`.
A count of entries is not "what KIND moved", which is the whole question the owner asked.

## What this deliberately does not do

It does not append to the journal (the orchestrator owns that), does not write to the wake store or
the ledger, does not install itself, and does not touch crontab or systemd. It measures; the
orchestrator schedules.
