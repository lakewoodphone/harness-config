# IN FLIGHT — work that is open right now

Updated: 2026-09-14
Rewritten, not appended. An item leaves this file by being finished (a `log/handoff/` entry) or by
becoming a `state/open-pain.md` row.
## Mine, being worked

| Item | Where | Next concrete step |
|---|---|---|
| The journal rebuild itself | this tree | Import the flat files until they go quiet (`journal.py import-flat`), then retire them completely. |
| Kosher filter: audit ledger for third-party verdicts | `kosher-filter-ai` (`decisions/36`, research `022` §1) | Append a decisions row on every human review instead of updating in place, so per-provider accuracy becomes computable. Then the dry-run mode (D36-10). |
| Kosher filter: browsing escalation route | `kosher-filter-ai` | `escalateToServerThreshold` is read by nothing; every `Decision.ESCALATE` still ends as block/cover. |
| Search index | `harness-config/scripts/fsearch.py` | Recorded 45.34 s → 0.075 s; re-measure after any index change. |
| The three stale checkouts | `ZABZ-TECH` 6 behind, `secratary` 1 behind on 2026-09-14 | Pull them before trusting a reading taken there. |

## Mine, waiting on a measurement before I claim it

| Item | What would settle it |
|---|---|
| Whether the open-pain list is really 58 live problems | Nothing in the record marks old entries done; only 1 of 59 carries a completion marker. `journal.py resolve <id> --status done --why ...` is now the way to say so, and every closure needs its evidence. |
| Per-machine journal divergence | `journal.py check` warns when a flat file holds entries the log lacks, and `audit` proves a merge lost nothing. It already found three entries written on `ZABZ-TECH` that existed nowhere else (L185, L186, D58). |

## His, queued (see `state/owner-questions.md`)

Nothing is raised here; the queue on the authority is the list, and it is read one item at a time.

## Broken, as last measured

- The company has delivered nothing to the owner since 2026-07-19 while its sensors fired into a dead
  channel (**P55**, measured 2026-09-14: 296 `held`, 2 `queued`, newest `sent` 2026-07-19T02:32Z).
  The SMS kill-switch is his decision and is being honoured. The replacement channel is his to choose;
  nothing outbound is sent without his explicit word.
