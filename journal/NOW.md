# NOW — the one page every session reads

Updated: 2026-09-14
Written by ZABZ-YOGA. This file is **state**, not history: it is rewritten, never appended. History
lives in `log/`, and every claim here traces to an entry there.

## Read this, in this order — and nothing else

```
J=~/code/harness-config/journal/tools/journal.py
python $J status                     # this page + counts + integrity, ~7 KB
python $J newest handoff 2           # the last two sessions' state of play, ~8 KB
python $J search "the area I am about to touch"
python $J show P46                   # one entry, by id
```

Never read a shard end to end: `log/handoff/2026-09.1.md` is 198 KB; `newest handoff 1` is 4 KB.
The state tier is `state/`: `open-pain.md`, `owner-questions.md`, `in-flight.md`, `status.tsv`.
Write with `python $J append <kind> --title ... --body -`; it allocates the id over the index, the
shards *and* every git ref, which is what stops two machines choosing the same number twice.

## Where the owner's work stands

- The kosher filter's tiers and privacy posture are settled (escalate on-device → our server →
  third-party API; privacy is engineered and audited). Remaining questions are mine —
  `log/decisions/2026-09.md` **D50**, **D54**; `log/lessons/2026-09.md` **L175-L177**.
- The last owner instruction on the record: *"you have to be the lawyer yourself"* (**D54**), and
  before that *"pull my emails and Google Voice calls/texts/voicemails and tell me what needs
  attention"* (**H66**).
- Owner questions live in `owner_decision_queue` on the authority and only there. `state/owner-questions.md`
  is a generated mirror, so a session with no route to the authority still reads the truth instead of
  re-asking. Live read: `ssh secratary-ts "python3 ~/bin/owner-queue.py next"`. On 2026-09-14 the retired
  `QUESTIONS.md` was reconciled into it: five rows promoted (#12 the email reply loop, #13 Yocheved's write
  access, #14 iPhone location, #15 Google Voice, and #11 the delivery channel), sixteen closed with a
  disposition each in `archive/README.md`, and **#11 answered the same hour** — the owner picked the
  harness badge, so it is closed and must not be re-asked. **7 pending.**

## State of the systems, as last measured

- **This journal was rebuilt on 2026-09-14.** Six flat files (590 KB, 389 entries when the migration ran,
  60 collided ids) became sharded logs, a state tier and a generated index; the tree now holds **407
  indexed entries** and grows by append. Six files that used to be read whole are now searched in slices.
  `archive/MIGRATION.md` is the record; the flat files stay in place as frozen inputs until they go quiet,
  and `journal.py check` warns if any of them gains an entry the log lacks. That check has already paid:
  it found **L185, L186 and D58**, written on `ZABZ-TECH` and present on no other machine, and
  `import-flat` there absorbed them into the shared record.
- **The fleet's three checkouts drift.** On 2026-09-14 `ZABZ-TECH` was **6 commits** behind
  `origin/master` and `secratary` **1** behind; both working trees were clean, so they were stale, not
  forked. The desktop's journal import then had to be merged back here (clean, no conflicts). Pull before
  trusting a reading taken on another machine.
- **Two sessions were writing this journal at once** while it was being rebuilt (`git status` was dirty in
  all five flat files at 01:19-01:23, and one of them committed this session's staged files under its own
  message). Any flat-file append after the rebuild is absorbed by `journal.py import-flat` — including an
  entry whose source *grew*, which is resynced rather than duplicated. The collision suffixes
  (P46/P46b/P46c, D41/D41b…) are the scar of the earlier unguarded merges.
- **`~/.dsh` is never the source of truth.** `harness-config` is (D7).

## Id spaces, so a reference can be checked

**H1-H68 · L1-L186 · P1-P58 · D1-D58 · W1-W36.** A bare number is ambiguous wherever the suffix repair
applied; the suffixed id in `index/entries.tsv` is the one to cite. (`L75` is referenced twice in old
prose and has never existed — an INFO in `check`, left visible rather than papered over.)

## The rule that keeps this honest

Every reading carries its source and its age. If a file here cannot say when it was written and from
where, it is not evidence (**L1**). An empty result is a refusal, not a health check (**L2**).
