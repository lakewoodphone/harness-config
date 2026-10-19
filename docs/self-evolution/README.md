# Self-evolution: the weekly audit

**What this is.** The owner asked (2026-10-13): *"once a week or whatever … you should
do a full audit and figure out how are you wildly evolving this week."* A promise is
not a ritual and a prose document is not a measurement. This directory holds the
measurement, the audit artefacts, and the judge that turns them into work.

## The three pieces

| piece | lives at | job |
|---|---|---|
| **measurement** | `scripts/self-audit/weekly-evolution-audit.py` | reads the estate's own stores and writes one machine record per run to `/root/.self-audit/runs/` |
| **judge** | `scripts/self-audit/weekly-evolution.py` | decides whether the numbers mean a live session must do the audit, and files exactly one wake flag per ISO week (`self-audit:<YYYY>-W<WW>`) |
| **audit** | `docs/self-evolution/audits/<YYYY>-W<WW>.md` + `.json` | the week's artefact: what changed, what did not move, and every broken instrument |

Both scripts are installed on the authority at `/root/bin/sources/`, invoked by
`/root/bin/run-wake-sources.sh` (`WEEKLY-EVOLUTION` block). The repo copies here are
the canonical source; `/root/bin/sources/` is what runs.

## The one rule

Every number carries the exact command that produced it and how fresh that source is.
**If a source cannot be read the metric is `COULD NOT ASK` with the reason and the
probe list — never 0, never a guess.** A blank is never a NO, and a broken instrument
must read as broken rather than as a small number.

## Run it by hand

```bash
python3 scripts/self-audit/weekly-evolution-audit.py --repo /root/code/harness-config \
    --out /root/.self-audit/runs --window-days 7
```

`--repo` is **not optional in practice**: it defaults to the CWD, and the source runs
from `/root/bin/sources`, which is not a git repository. The first weekly run
(2026-W42) was measured that way and produced two `COULD NOT ASK` cells plus five
false zeros. `weekly-evolution.py` now passes `--repo`
(`SELF_AUDIT_REPO` → `HARNESS_REPO` → `/root/code/harness-config`).

## Audits

- [`audits/2026-W42.md`](audits/2026-W42.md) — the baseline week. Its git axis was
  measured against the wrong path; the audit names the broken instruments and records
  the corrected measurement that becomes the baseline for every week after it.
- [`audits/2026-W43.md`](audits/2026-W43.md) — the first week measured against the
  corrected baseline. 20/20 cells measured, 0 `COULD NOT ASK`; the audit names nine
  measured-but-wrong cells (wake-instance "sessions", row-count "spend",
  dropped-as-open, autocommit-heavy commits, and the selftest mix in wake releases)
  and reconstructs the honest week: 70 new files, 476 ledger closes in a ledger that
  is one week old, 701 commits of which 560 are autocommits.

