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

## Sweep

`harness-config/scripts/windows/sweep-transfer-staging.ps1` reports these folders with age and size, and deletes only
the ones past the window when given `-Delete`:

```powershell
pwsh -File scripts/windows/sweep-transfer-staging.ps1                 # report only
pwsh -File scripts/windows/sweep-transfer-staging.ps1 -Delete -Days 30 # delete what is past 30 days
```

It is report-only by default on purpose: the deletion of a customer's data is an act, not a cron side effect, and the
owner's policy fixes the window, not the moment.
