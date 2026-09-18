# archive/ — the pre-2026-09-14 record, kept verbatim

Nothing here is read in normal work. It exists so the rebuild can be audited and so no entry, no
heading and no instruction that used to be in the journal is now unaccounted for.

| Path | What it is |
|---|---|
| `flat-2026-09-14/*.md` | Point-in-time snapshot of the six flat files at the moment of the rebuild. The live flat files remain in the journal root as frozen inputs while a second session finishes with them. |
| `MIGRATION.md` | The machine-written report of the migration: entries parsed per source file, per-machine counts, ids written, and which collided ids were repaired with suffixes. |
| `README.md` | This file. |

## Why the flat files were not deleted

Two DSH sessions were writing them at the same time as the rebuild: on 2026-09-14 01:19-01:23 all five
files were dirty in git while the migration ran. Anything appended after the rebuild is absorbed by
`journal.py import-flat`, and `journal.py check` warns when a flat file holds an entry the log lacks —
so the transition cannot silently lose a session's work.

Retire them completely once `import-flat` reports nothing new for a full working day. At that point the
files can be moved here and their old paths replaced with one-line stubs.

## QUESTIONS.md — retired, and where each row went

`QUESTIONS.md` held **open owner questions and answered ones in the same table**, in three separate
tables, out of date order, with a bulleted list spliced mid-table. It was also a second store for the
same fact as `owner_decision_queue`, with no statement of which one was authoritative — so the two
drifted, and one of them was invisible.

**The authority is `owner_decision_queue`** (table on the authority's database, read with
`~/bin/owner-queue.py`). `journal/state/owner-questions.md` is a generated mirror. `QUESTIONS.md` is
retired; its content is preserved in `flat-2026-09-14/QUESTIONS.md`.

Disposition of every row, 2026-09-14:

| Row | Question (abbreviated) | Disposition |
|---|---|---|
| 14 | Email reply loop never completed; 36 drafts pending | **Queued #12** — customers and the owner's voice. |
| 15 | HA security system blind; two door contacts offline | Not queued: operational, and mine to fix. If still broken it belongs in `log/pain/`. |
| 16 | Phone access: Tailscale-only, or public too? | Decided by me — **D33/D35** (tailnet plus the public redirector, left alone). |
| 17 | One long office session or many short ones? | Not queued: it shapes continuity, which is a development question (**L7**). |
| 18 | Why did Copilot usage collapse after April 2026? | Not queued: a research question, not a decision. |
| 19 | Twelve days of zero ticks — deliberate or outage? | Answered 2026-09-11 (**D16**): work loop dead 13d 17h. |
| 20 | Multi-window: one engine or one per window? | Decided by me — **D17/D18/D19** (one engine, many windows). |
| 21 | Multi-window: restore straight to a session? | Development question; sequenced by me. |
| 22 | Multi-window: layout and "new window"? | Development question; decided by me. |
| 23 | Rosh Hashana / Yom Kippur power-down blocks | Answered 2026-09-11: *"For sure, split it"* — implemented (**D41**). |
| 32 | Modesty model: fund it or prepare it? | Superseded 2026-09-14: off-the-shelf models cover the attributes, so the question is ground truth, not training. |
| 34 | The accuracy claim has no ground truth | Decided by me: build the harness, label ~200 frames from shop-owned devices, no customer data, no cash. |
| 37 | Privacy posture for the modesty path | Answered 2026-09-14: he rejected the framing; tiers plus engineered privacy (**D50**). |
| 40 | 18 open visual-modesty decisions, walked one at a time | Superseded by **D50**; the remaining items are mine. |
| 42 | Legal counsel: two exposures engineering cannot remove | Answered 2026-09-14: *"you have to be the lawyer yourself"* (**D54**). |
| 45 | What may we promise a customer about accuracy? | Held behind the legal question, which is now answered by **D54** — mine to bring back as one question. |
| 49 | "Staging is gone" — recreate the Heroku app | **Retracted by the row below it**: Heroku is dead; the real path is Netlify + Hetzner, and the deploy was done and verified. |
| 50 | (The retraction of row 49) | Kept as the record of having been wrong — **L53**. |
| 52 | May the HA app on the iPhone have your location? | **Queued #14** — his privacy, one setting. |
| 56 | How should a finding reach you? | **Queued #11** — the most consequential live one: nothing has reached him since 2026-07-19. |
| 57 | Yocheved's write access in week one | **Queued #13** — real customer data. |
| 61 | What should happen to Google Voice? | **Queued #15** — his numbers, his money. |

**5 rows were queued, 16 were closed as answered, superseded, retracted or mine.** The reconciliation
script is `tools/reconcile-questions.py`, kept so the reasoning is reproducible.
