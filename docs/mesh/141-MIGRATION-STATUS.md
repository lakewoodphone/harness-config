# MIGRATION STATUS — written by the manager session, 2026-10-11 06:30Z

Short, current, and for the workstreams running in parallel. The full context is in
`131-MIGRATION-BRIEF.md`, `133-PORT-BRIEF.md` and the numbered reports in this directory.

## DONE, AND VERIFIED

- **Offsite backup**: streamed copy live (Track 2's v3 script). R2 objects `authority/accounting.db.gz`
  (re-uploaded, sha256 sidecar verified) and `authority/secretary.db.gz` being rewritten by the
  streaming implementation at 06:18Z. Check `/var/lib/authority-backup/last-run` for the finished
  record before you claim it works.
- **The accounting ledger has MOVED to the authority** (manager, 06:29Z). Real file, not the stub:
  - path `/root/accounting-data/live/accounting.db`
  - sha256 `55a9801a5a03d67e8efb262cb7afa6620694dcf0ea665a5d1e25725a4d7b5c` (verify it yourself)
  - `PRAGMA integrity_check` = ok; 24 tables; 8,490 transactions; 1,783 balance_snapshots; newest
    transaction_date 2026-10-09; table-by-table row counts identical to the office source.
  - the empty 16 KB stub it replaced is retained as
    `accounting.db.stub-empty-16384-20261011T062757Z.bak` (it held 0 rows — nothing was lost).
  - **Any job that was left DISABLED for "the ledger is absent" can be enabled now.** Do not copy the
    office ledger anywhere else and do not overwrite this file.
- **Crontab inventory**: `132-CRON-INVENTORY.md` — 92 jobs decoded and verdicted.
- **Estate inventory**: `136-ESTATE-INVENTORY.md` — what is still only on the office box.
- **Parity and robustness**: `135-PARITY-AND-ROBUSTNESS.md` — the mesh diagnosis, the OOM kill, the
  dead-man gap, the office timers that are still firing.

## IN FLIGHT (do not duplicate)

| workstream | artifact | owns |
|---|---|---|
| offsite backup chain | `133-OFFSITE-BACKUP.md` | `authority-offsite-backup.sh`, its schedule, freshness monitor, dead-man switch |
| transcript archive + session/chat ingestion | `134-ARCHIVE-CONTINUITY.md` | the raw archive move, `push-dsh-sessions`, Copilot chats, `transcript-archive` |
| guards, retention, integrity, deadman, journal | `134-PORT-GUARDS-BACKUP.md` | families 1, 2, 10, 14 |
| freshness monitors, gateway health | `135-PORT-FRESHNESS.md` | families 3, 9 |
| systemd timers | `137-PORT-SYSTEMD-TIMERS.md` | the five still-active office timers |
| comms + finance ingestion | `138-PORT-INGESTION.md` | families 4, 5, 16, 17 |
| owner channel, wake, asks, shop, CFO | `139-PORT-OWNER-CHANNEL.md` | families 6, 7, 8, 22 |
| core, sentinel, and the three gaps | `140-PORT-CORE-AND-GAPS.md` | `run-sentinel`, `converge-authority`, `chip-resume`, the OOM limit, the Hetzner token, the family-chat store |

## MANAGER-HELD

- The mesh repair (tailnet join for `secratary-cloud`, then the broker) — blocked on the owner's
  Tailscale auth key (owner question 445).
- The DSH engine on ZABZ-YOGA must be RESTARTED to load the placement failover committed on
  2026-10-09; the running process predates it, which is why `subagent` reports the raw broker error.
  A restart is being taken at the 0700Z window, not mid-session.
- `~/code/personal-secretary-mvp` on this laptop is a shallow copy (no `.git`); the canonical checkout
  for `journal-commit` is being decided.

## STANDING RULES FOR EVERY WORKSTREAM

See `133-PORT-BRIEF.md` §Hard rules. In one line each: the office box is read-only; one writer
(`company-api`); never delete `/root/authority.db`; disk is 26 GB free against a 23.7 GB database;
never restart `company-api`, `cloudflared`, `secretary-dashboard` or `phone-redirector` without
saying so; never print a credential value; prove the effect, not the exit code.
