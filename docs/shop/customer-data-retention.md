# Shop customer device data — retention and sweep

Owner policy, stated 2026-09-30: **we are not responsible for a customer's data more than 30 days after the job.**
Asked to clear three leftover WhatsApp-transfer folders, he answered: *"delete all 3, we aren't responsible for data
more than 30 days."* So the 30-day window is the shop's own rule, it is not a judgement call for a session to reopen,
and a transfer job's staging copy is not an asset to be preserved — it is a liability with an expiry date.

## What a phone transfer leaves behind, and where

Both WhatsApp transfer tools stage **the entire attachment set of the phone** on the technician's Windows machine
and never clean it up. Measured on `ZABZ-YOGA` 2026-09-30, one customer's job = **121.2 GiB across four folders**
(199,310 files) while that drive had 78 GB free.

| Folder | Tool | When it appears |
|---|---|---|
| `C:\WatsGoBackup\` | WatsGo (iToolab) | at backup: `BackupModule::onBackup` / `TT_AndroidWaBackupCopyFile`. Contains `BackupInfo.ini` with device name, serial and date, `Media\` (browsable, real filenames) and `database\msgstore.db` |
| `C:\WatsGo-Cache\` | WatsGo | during an Android→iOS **restore** |
| `C:\WatsGoGoogleDriverBackup\` | WatsGo | Google-Drive cloud restore staging (often left empty, because the Drive downloads 404) |
| `C:\Wondershare_DrFone_WhatsApp_Backup\` | Dr.Fone / MobileTrans | at backup: `Deivce.ini` holds device name, serial and `BackupDate` |
| `C:\Wondershare_SocialApp_Temp\` | Dr.Fone / MobileTrans | during an Android→iOS restore; the tool's own last step is `DeleteCache_Success` |

The backup folder carries the customer's whole chat database (`msgstore.db`, hundreds of thousands of messages) plus
every photo and video. On a real job the video alone was 29 GB of the 40 GB.

## The rule

1. **A staging folder is kept only while the job is live**, and deleted once the transfer has completed and the
   customer has the phone — never later than 30 days after the job.
2. **Never delete without the owner's per-action yes** for that exact folder. This is customer data and the record of
   having deleted it (folder, size, file count, evidence the job succeeded) goes into the journal.
3. **Before deleting, verify the job actually succeeded** in the tool's own log:
   - Dr.Fone: `%APPDATA%\Wondershare\MobileTransPro\log\MobileTrans.log` → `Restore Success completed, total N files X GiB sent`.
   - WatsGo: `C:\Program Files (x86)\WatsGo\log\AppLog.log` → look for `onTaskFinished {task: TT_AndroidWaBackupCopyFile, result: 0}` and, for restores, `bugsplat::unhandledExceptionFilter`. WatsGo crashed repeatedly at 40 % of an iPhone restore on the job that produced the 2026-07-05 folders; the transfer was finished with Dr.Fone three days later.
4. A tool that crashed or a restore that never completed is exactly why a folder may still be the only copy of the
   data — never sweep a folder whose job has no success line.

## Where a FULL copy is allowed to live — and the month

Owner rule, stated 2026-10-27, verbatim: *"we only keep full copies of customer data in the
downloads/customer data folder that we we can find it and make sure to delete it after a month,
so move it there fully"*.

1. **One home:** `Downloads\customer data\` (`%USERPROFILE%\Downloads\customer data`), one subfolder per
   customer, named so a person can find it — `shande 7185017418 iris easy flip`, not a uuid and not a date.
   Nothing else on the machine keeps a full copy: a bench pull, a recovery image, a carved set a
   customer's library can be rebuilt from, all belong in that folder, not in a scratch or evidence tree.
2. **The month runs from when the copy was MADE, not from when it was moved.** A tidy-up does not restart
   the clock; treating it as a fresh landing keeps a customer's library longer than the rule allows for no
   reason. The Shande copy was made 2026-10-11 and moved on 2026-10-27 — it is due 2026-11-11, not 11-27.
3. **Every folder carries `_landed-on.txt`** whose FIRST LINE is `Landed: YYYY-MM-DD`. That file is the only
   honest date: a moved folder keeps the phone's own file timestamps (2026-10-06/07 on the Shande job), so an
   age check based on mtimes calls fresh data a month old. **A folder with no marker is not swept** — an
   undated copy is unread, and unread is never expired.
4. **Deleting is still an act, not a schedule.** The sweep reports; it deletes only with
   `-DeleteCustomerData`, and the per-folder yes is the owner's. Check the job succeeded first — see point 3 of
   **The rule** above, which is about the transfer tools and applies here unchanged:
   measured 2026-10-27, `sarah levi` was 33 days old *and* her order WO2609030001 was completed 2026-09-08
   with 159.94 CAPTURED, which is what makes her folder eligible rather than merely old.

What this separation is for: WhatsApp/Dr.Fone staging folders are the **tool's** debris and are deleted
freely on the window, while `Downloads\customer data` is the **shop's** copy of a customer's library and is
deleted only after the job is proved done. Same clock, different act.

## Sweep

`harness-config/scripts/windows/sweep-transfer-staging.ps1` reports these folders with age and size, and deletes only
the ones past the window when given `-Delete` (staging) or `-DeleteCustomerData` (the customer-data folder):

```powershell
pwsh -File scripts/windows/sweep-transfer-staging.ps1                 # report only
pwsh -File scripts/windows/sweep-transfer-staging.ps1 -Delete -Days 30 # delete transfer staging past 30 days
pwsh -File scripts/windows/sweep-transfer-staging.ps1 -DeleteCustomerData -Days 30  # the owner's per-folder yes
```

It is report-only by default on purpose: the deletion of a customer's data is an act, not a cron side effect, and the
owner's policy fixes the window, not the moment.

`scripts/windows/run-customer-data-sweep.ps1` is the scheduled wrapper: it runs the report, writes
`%USERPROFILE%\.customer-data-sweep\report-<date>.txt` and `last-report.txt`, and writes a `DUE.txt` naming every
folder past the window so the due list is a file a session can read instead of a memory. On `ZABZ-TECH` it is a
weekly Scheduled Task, `LPT-CustomerDataSweep` (Sundays 09:00), report-only.

**The script itself did not run for a month and nobody noticed (found 2026-10-27).** It called
`Measure-Object -Length -Sum`; `Length` is not a parameter name, so the first folder it met threw
*"A parameter cannot be found that matches parameter name 'Length'"* and it exited 1 — a documented
mechanism that had never once produced a report. It is `-Property Length` now, and the `-Json` mode no longer
has prose appended to it.
