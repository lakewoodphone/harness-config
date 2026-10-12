# Search-system audit evidence — 2026-10-12

The probe scripts behind every number in **`docs/mesh/172-MASTER-RECORD-SEARCH-SYSTEM.md`**.

They are kept because the claims they support are the kind that get re-litigated: "the search was
broken", "599 of 607 tools had no body", "the journal returned a false negative", "the indexes were
current". Each script prints what it measured, so a future session can re-run it instead of trusting
this directory.

**They are evidence, not the product.** The product is `scripts/find-anything/` one level up.

| script | the question it answers |
|---|---|
| `01-survey.sh` | What is installed on this node, what indexes exist, how old are they, and what is scheduled to refresh them? |
| `02-tool-bodies.py` | Which ACTIVE registered tools have no implementation file on disk? |
| `03-modes.sh` | Does every engine mode answer, with the documented exit code, inside the budget? |
| `04-acceptance.sh` | Are the guards green, the clocks installed, the ledger recording, and every mode working? |
| `05-journal-semantics.sh` | Does a multi-word journal query return hits, and does a real negative stay a negative? |
| `06-git-and-cron.sh` | Would a push fast-forward? Do my scheduled minutes collide with another job's? |
| `07-zabztech-diagnose.ps1` | On `zabz-tech`: what is ruled out, and how to run the refresh so its output can be read? |

## Conventions these scripts follow, deliberately

* **Nothing is hardcoded to one machine's layout.** The checkout, the harness-config root and the
  engine are resolved by environment override → probe → legacy path. This is the fix for root cause R3
  in the master record, applied to the audit tools as well as to the product — a hardcoded path is how
  the search system broke in the first place.
* **Exit codes are read, not prose.** The engine's contract: `0` hits · `1` a real negative · `2` bad
  usage · `3` answered but possibly stale · `4` **NOTHING was searched** · `5` the index failed. A `4`
  reported as "no match" is the failure this whole audit is about.
* **Read-only by default.** Only `04-acceptance.sh` invokes anything that writes, and only the product's
  own guards (which write a status file). No script here changes service state, crontabs or databases.

## Running them

```bash
# from a copy of this repo on the node you are auditing
bash scripts/find-anything/audit-2026-10-12/01-survey.sh
bash scripts/find-anything/audit-2026-10-12/03-modes.sh
python3 scripts/find-anything/audit-2026-10-12/02-tool-bodies.py

# the Windows diagnostic runs on zabz-tech, not here
powershell -NoProfile -ExecutionPolicy Bypass -File 07-zabztech-diagnose.ps1
```
