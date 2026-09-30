# Disk space on a Windows node — how to measure it, and what actually eats it

Written 2026-09-30 on `ZABZ-YOGA` after a session in which three wrong numbers were one step away
from reaching the owner. It is the method, not the snapshot; the measured case is
`inventory/zabz-yoga-2026-09-30.md` next to this file.

**The rule this document serves:** nothing is deleted on a guess. A number without a command, a
path and a date behind it is not a measurement. And any deletion of a customer's data follows
`../shop/customer-data-retention.md` — 30-day window, owner's per-action yes, success line in the
tool's own log first.

## 1. Use the script

```powershell
# rank folders under a root, plus the largest loose files directly in it
pwsh -File scripts/windows/measure-space.ps1 -Root C:\Users\ezabz -Top 20 -MinGiB 0.2

# add a last-write date per folder (second pass over each — slower)
pwsh -File scripts/windows/measure-space.ps1 -Root C:\Users\ezabz -Newest

# machine-readable
pwsh -File scripts/windows/measure-space.ps1 -Root C:\ -Json
```

It walks with `robocopy /L /E /BYTES /XJ`, which is C-level (no per-file PowerShell objects) and
never copies. On this laptop `C:\Program Files` (30 GiB, 20 folders) takes ~10 s; a full user
profile with 1.17 M files takes minutes — **run that one in the background**, never in a
foreground call that dies at 120 s.

## 2. The four traps

**Junctions are not space.** `C:\Users\<user>\AppData\Local\Application Data` is a legacy NTFS
junction pointing back at `AppData\Local` (verified: attributes `Hidden, System, Directory,
ReparsePoint, NotContentIndexed`, target `C:\Users\ezabz\AppData\Local`). A recursive walk that
follows it reports **82.54 GiB of phantom space** and double counts the whole tree; the same
applies to `Local\History` → `Local\Microsoft\Windows\History` and `Local\Temporary Internet
Files` → `Local\Microsoft\Windows\INetCache`. Detect one with
`Get-Item <path> -Force | Select Attributes, Target` and skip anything whose attributes contain
`ReparsePoint`; `robocopy /XJ` does it for you.

**GiB is not GB.** PowerShell's `$_.Length / 1GB` is a **GiB** (2^30); robocopy `/BYTES` prints raw
bytes; a vendor's "40 GB" is often 10^9. In this session the same tree read as 43.67 GB and
40.7 GiB. Always carry the byte count and say which divisor you used.

**A folder ranking hides loose files.** `Red_Dead_Redemption_2_…zip` is 119.45 GiB of a 322 GiB
drive and sits in a *folder* only in one place — at a drive root or in `Downloads` a folder-only
report shows almost nothing. `measure-space.ps1` prints both tables for this reason.

**Reported-vs-actual delete.** Deleting 121.24 GiB of logical files returned 110.67 GiB of actual
free space, because part of the tree was NTFS-compressed. Logically-deleted bytes are an upper
bound on what you get back; always re-read `Get-PSDrive` free space afterwards and quote that.

## 3. Ranked offenders — where space actually goes on these machines

Measured on `ZABZ-YOGA`, 2026-09-30 (~733 GiB across the user profile; the nine paths first asked
about were ~259 GiB of it). Sizes are GiB.

| Rank | What | Size | Verdict |
|---|---|---|---|
| 1 | `Downloads` | 273 | Game repacks, 14,421 files. Owner's own; the usual reason a drive fills in an afternoon |
| 2 | `Code` (all repos) | 182 | ~4 M files. `node_modules`, `.venv`, `.git` and stale `_fleet`/`cfo-fleet` worktrees live *inside* repo directories, so they never show up beside them |
| 3 | `AppData` (Local 82.5 / Roaming 43.5) | 126 | **Live.** `Packages` 16.2, `Temp` 11.2, `Google` (Chrome) 8.5, Android SDK 8.5, two extra VS Code profile slots 9.4 + 4.6, `npm-cache` 3.9, `pnpm` 2.0, `ms-playwright` 3.8; `Roaming\Code\User\workspaceStorage` 36.8 = Copilot chat history |
| 4 | `Backups\<repo>` snapshots | 62 | **By design.** `\PersonalSecretaryBackup` task runs every 12 h; `backup-data.ps1` keeps all <24 h, 1/day for 30 days, 1/week beyond, ~2.04 GiB per snapshot. Not a leak — do not "fix" it |
| 5 | `.fsearch` | 25 | Live index 5.7 GiB + **19.6 GiB of `RETIRED-*` builds** from the 2026-09-14 reindex that nothing references |
| 6 | `car_chat_hits` | 19 | One-off 2026-09-18 copy of Copilot chat sessions; 4/5 sampled byte-identical to originals still in `workspaceStorage` |
| 7 | `.android` | 11 | 2 emulator images (re-creatable) + `adbkey`/`debug.keystore` (needed) |
| 8 | `.platformio` | 10 | Toolchains, untouched since 2026-06-17, re-downloadable |
| 9 | `_scratch`, `VSCodeBackups` | 4.9 + 4.8 | Session scratch (208,921 files) and VS Code backup copies — both disposable by nature, both worth checking for anything hand-made |
| 10 | `.gradle` | 3 | Caches, live |
| 11 | `accounting-data` | 2.8 | **Real books** — never a target |
| 12 | `.copilot`, `.dsh`, `_git-backup-<date>`, `dsh-backup-<date>` | 2.2 / 1.9 / 1.5 / 0.6 | Tool state and dated safety backups; cheap, keep |


Other places to look before declaring a drive full: `C:\$WINDOWS.~BT` and
`C:\Windows\SoftwareDistribution` (feature updates), `C:\Windows\Temp`, `pagefile.sys`
(14.85 GiB here), `hiberfil.sys`, WSL `ext4.vhdx` under `AppData\Local\Packages`, Docker images,
`C:\$Recycle.Bin`, and tool staging folders (`WatsGoBackup`, `Wondershare_*`,
`WatsGo-Cache`, `WatsGoGoogleDriverBackup`) — the last group has its own sweep:
`pwsh -File scripts/windows/sweep-transfer-staging.ps1`.

On the **Linux** nodes the same job has different offenders: `journalctl` and `/var/log`,
`~/secretary-backups` (298 GB once, with its retention script silently deleted — P2799/P2800),
Docker layers, `/tmp`, the DSH spill roots (age-only 30-day sweep at process start), `ollama`
models, and pip/npm caches.

## 4. Before deleting anything — five checks

1. **Is it referenced?** `grep` the folder and the scripts that own it (`RETIRED-*` fsearch
   databases: no reference to `RETIRED` anywhere in `fsearch.py`/`chatindex.py`, which use
   `index.db`, `names.db`, `chats.db`).
2. **Is it a duplicate?** Compare `Get-FileHash -Algorithm SHA256` against the original, and say
   how many of how many you checked. A 4-of-5 sample is *not* a proof of redundancy.
3. **Is it regenerated?** Find the writer and read its policy — the backup script, the scheduled
   task (`Get-ScheduledTask` + `Actions`), the tool's own log.
4. **Did the job succeed?** For any transfer/backup staging folder, find the success line
   (`Restore Success completed, total N files X GiB sent`) or its absence (`bugsplat::unhandledExceptionFilter`).
   A folder existing never means the job worked.
5. **What does the owner lose?** If the answer is not "nothing that exists nowhere else", it is
   his decision, asked as one question with a recommendation — not an engineering call.
