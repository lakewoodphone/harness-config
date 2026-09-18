# Measured mesh inventory

Measured 2026-09-18 15:00Z from ZABZ-YOGA by `_scratch/mesh-inventory/run-inventory.ps1`.
Every cell is a reading from the node itself; `sshMs` is the wall-clock cost of the whole probe over ssh.

| node | what | reachable | sshMs | cores | memTotalMiB | memFreeMiB | commitFreeMiB | cFreeGiB | node | dshOnPath | engineOn3099 | harness-config |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| laptop-ts | ZABZ-YOGA (laptop, this machine) | True | 3373 | 22 | 32373 | 13678 | 20812 | 48.4 | v24.12.0 | False | True | True |
| desktop-ts | ZABZ-TECH (office desktop) | True | 3348 | 32 | 65173 | 38761 | 39504 | 185.5 | v24.19.0 | False | True | True |
| secratary-ts | secratary (Linux authority) | True | 734 | 4 | 23421 | 15349 | 3369 | 134.8 | v20.20.2 | False | False | True |
| linux-pc-ts | zabz-tech-linux | True | 1018 | 12 | 11673 | 10329 | 4666 | 20.9 | v22.23.2 | True | True | True |
| mac-mini-ts | LakewooechsMini (macOS) | True | 764 | 10 | 16384 |  |  | 46.0 | absent | False | False | True |

Unreachable rows keep their error text in `inventory.jsonl`; an empty cell means the node did not answer that field, never that the field is zero.
