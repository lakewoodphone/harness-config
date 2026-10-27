# Evidence — `ZABZ-TECH` disk audit, 2026-10-27

Everything a future session needs to re-open this work without redoing it. **Read
`../zabz-tech-2026-10-27.md` first** — that is the finding. This folder is the raw measurement
behind it: every number in that document came out of one of these files.

Machine state when measured: `zabz-tech`, Windows, `C:` = one 951.65 GiB Micron SSD. Session began
with **11.23 GiB free** (`Get-Volume`, 11:06), which the recycle bin raised to 59.10 GiB on its own at
11:17, and the deletion pass in §7 of the inventory took to **~247 GB** (it oscillates by up to
8 GB because the hourly transcript-archive job stages in `C:\Windows\Temp`).

## The files

| File | What it holds | How it was produced |
|---|---|---|
| `measure.tsv` | every directory one level under 12 roots: `C:\`, `C:\Users`, `…\ezabz`, `Code`, `AppData`, `AppData\Local`, `AppData\Roaming`, `Downloads`, `Program Files`, `Program Files (x86)`, `ProgramData`, `Windows` — GiB, files, bytes | `scripts/windows/measure-parallel.ps1 -RootsFile roots.txt` |
| `measure2.tsv` | the roots the first pass missed (the `C:\` root loop had resolved to the CWD — lesson `L12392`) plus `ProgramData\Microsoft`, `Apple`, `Backups`, `.fsearch`, `_scratch`, `_fleet`, `_worktrees`, `Packages`, `.dsh`, `.android` | same, `-RootsFile roots2.txt` |
| `measure3.tsv` | inside the big repos: `personal-secretary-mvp` (`_scratch` 30.30, `data` 29.90), `lpt-hub` (`tmp` 6.34), `_pbp`, `_customer-plane-build`, `.platformio`, `car_chat_hits`, `Downloads\customer data` per customer, `Windows\Installer` | same, `-RootsFile roots3.txt` |
| `roots.txt`, `roots2.txt`, `roots3.txt` | the three root lists, so any row can be reproduced exactly | hand-written |
| `worktree-verdict.tsv` | the 285 agent checkouts with per-directory `git` evidence: branch, HEAD, modified count, non-ignored untracked count, `onRemote`, and the verdict `SAFE` / `HOLD-*` | `scripts/windows/verify-worktrees.ps1` |
| `wt-safe.txt` | the 166 paths that passed every test and were deleted | derived from the verdict file |
| `wt-deleted.tsv` | outcome per path after `rd /s /q` (166/166 gone) | the deletion job |
| `deleted-2026-10-27.tsv` | **the manifest of what was actually removed** — batch, path, bytes, files, date. The worktree batch has `Bytes=0` because those rows were recorded by path; their size is in `measure*.tsv` | appended by each deletion job |
| `customer-data-scan.json` | every file on the profile matching customer-device-data patterns: 176 hits, 20.60 GiB, two locations | `scripts/windows/scan-customer-data.py` (9.4 M directories, 3 h 55 m) |
| `car_chat_verify.tsv` | all 887 `car_chat_hits` files, each with `DUPLICATE`/`UNIQUE` and the matching live path it was hashed against — 887 duplicate, 0 unique | `scripts/windows/verify-chat-copies.py` |

## The tools, now in `scripts/windows/`

They are generic and reusable; none of them is specific to this date.

- **`measure-parallel.ps1`** — ranks directories by size with `robocopy /L /E /BYTES /XJ`, one worker
  per directory, N at a time. Use it instead of the single-threaded `measure-space.ps1` on anything
  large: 12 minutes for this whole volume. Reports **logical** bytes only (see the hardlink trap).
- **`verify-worktrees.ps1`** — decides per checkout whether deleting it can lose work. A directory is
  SAFE only if: no modified tracked file, no untracked **and non-ignored** file, and HEAD reachable
  from a remote branch. Everything else prints its reason. Read its header before changing the test.
- **`scan-customer-data.py`** — one pass over a profile for `msgstore*`, `*.crypt14/15`, `*.ab`,
  `MobileSync\Manifest.db`, `BackupInfo.ini`/`Deivce.ini`. Excludes `Downloads\customer data` by
  design. Slow on a 9 M-directory profile; run it in the background.
- **`verify-chat-copies.py`** — proves a folder of chat `.jsonl` files is redundant by hashing every
  file against a live VS Code `workspaceStorage` copy. Sample-hashing is not enough; this does all.

## Three traps this audit paid for — do not re-learn them

1. **A worktree's size is mostly hardlinks** (`L12391`). 141 checkouts measured 309.5 GiB logical and
   are worth ~55 GiB. `node_modules/react/package.json` was one inode with **132 links**. Measure one
   directory's `node_modules` share before quoting a reclaim figure.
2. **`Get-ChildItem -LiteralPath 'C:'` means "current directory on C:"** (`L12392`), so a drive-root
   loop silently measured the CWD. Bare drive roots need a trailing backslash.
3. **Age and location are not expiry.** 24.1 GiB of customer data looked like expired debris and was
   the salvaged copy for an **open** work order (`P9995`). Never name customer data as a deletion
   candidate before reading the production order; and per the standing rule, an agent never deletes
   it at all — `../../shop/customer-data-retention.md`.

## Reproducing the headline

```powershell
Get-Volume C; Get-PSDrive C                      # must agree
pwsh -File scripts/windows/measure-parallel.ps1 -RootsFile docs/windows/inventory/2026-10-27-zabz-tech/roots.txt -Out C:\temp\m1.tsv
pwsh -File scripts/windows/verify-worktrees.ps1 -RootsFile C:\temp\wt-roots.txt -Out C:\temp\verdict.tsv
pwsh -File scripts/windows/sweep-transfer-staging.ps1          # customer data, report only
```
