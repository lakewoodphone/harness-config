# MIGRATION PORT BRIEF — how to move a job onto the new cloud authority

Companion to `131-MIGRATION-BRIEF.md` (read that first — machine list, the non-negotiable rules, the
frozen office box). The work list is `132-CRON-INVENTORY.md`: §2 is the port list (every PORT-AS-IS and
PORT-ADAPT item, decoded command, dependencies, how to prove it ran), §3 the DEAD items, §4 the
OFFICE-ONLY ones, §5 the DANGEROUS-ON-CLOUD ones. Read the section that covers the jobs you own before
you touch anything.

## The target

`secratary-cloud` — `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`. Everything runs as **root**
(its only real user), from `/opt/company` (the app), `/root` and `/usr/local/bin`. There is **no
`/home/zabz`** on it beyond an empty directory: every office path `/home/zabz/...` must be translated,
not copied. Recommended mapping:

| office | cloud |
|---|---|
| `/home/zabz/bin/<tool>` | `/usr/local/bin/<tool>` |
| `/home/zabz/personal-secretary-mvp` | `/opt/company` |
| `/home/zabz/personal-secretary-mvp/data/secretary.db` | `/root/authority.db` |
| `/home/zabz/personal-secretary-mvp/.venv/bin/python` | `/opt/company/.venv/bin/python` |
| `/home/zabz/<state dir>` | `/root/<state dir>` |
| `~/.cron-status/runs.tsv` | `/root/.cron-status/runs.tsv` |
| `http://127.0.0.1:8002` | `http://127.0.0.1:8002` (unchanged — the app is there) |

## The scheduling contract — cron plus the estate's own wrapper

Use **cron**, not systemd timers, for the ported jobs, because the estate's whole "did it actually run"
ledger is built on it and re-inventing it is how a job becomes unobservable. Keep the office wrapper's
contract exactly:

```
cron-wrap.sh <name> <base64-of-the-command>
```

- Get `cron-wrap.sh` from the office box (`/home/zabz/bin/cron-wrap.sh` — read it first, its header
  explains the 2026-09-30 failure it exists to prevent) and install it at `/usr/local/bin/cron-wrap.sh`,
  mode 755. It appends one row per run to `${CRON_STATUS_DIR:-$HOME/.cron-status}/runs.tsv`:
  `<ISO-8601 UTC>\t<name>\t<rc>\t<seconds>\t<first 160 chars of stderr>`, and it always exits with the
  job's own exit code. Do not change that format — several monitors parse it.
- Base64 (not quoting) because the commands contain single quotes, backticks, `$` and nested quotes.
  Encode locally: `printf '%s' "<command>" | base64 -w0`.
- Root's crontab line shape: `*/15 * * * * /usr/local/bin/cron-wrap.sh <name> <base64>`.
- The **name must stay the same as the office job's name** where the job is the same job, so the ledger
  and any monitor that keyed on it still read true. If a job genuinely changes meaning, give it a new
  name and say so in your report.
- Keep the run's own stdout/stderr going where the office version sent it (a log under `/var/log/` or
  `/root/`), and check that path is writable before you rely on it.

Anything that must survive a reboot and is not a cron job (a service, a socket, a timer that already
exists) keeps its own mechanism; say what you chose and why.

## Hard rules for this box

1. **One writer.** `company-api` owns `/root/authority.db` for writes. A job that needs to WRITE goes
   through the API (HTTP) or through a dedicated script the app already provides. **Never open the
   database read-write from a cron script.** Read-only is `sqlite3 "file:/root/authority.db?mode=ro"` or
   Python with `uri=True, mode=ro`.
2. **Never delete or overwrite `/root/authority.db`, `-wal`, `-shm`, or any backup on any machine.**
3. **Never restart** `company-api`, `cloudflared`, `secretary-dashboard` or `phone-redirector` without
   saying so in your report first.
4. **Disk is the binding constraint**: 75 GB total, 46 GB used, about 27 GB free, against a 23.7 GB
   database. Check `df -h /` before and after anything that writes more than a few MB. No job may leave
   a second database-sized file on that disk. If a job needs one, redesign it to stream.
5. **Do not run heavy work against the live database.** A `PRAGMA integrity_check` or a full-table scan
   on a 23.7 GB database belongs against a **snapshot**, not the live file, and it takes 12–30 minutes:
   run it on the consistent copy the offsite backup already produces, or make your own and delete it.
6. **The office box is READ-ONLY** — never start, enable, unmask or write anything there, and never run a
   bulk operation on it (its disk starvation has taken the company down three times).
7. Every claim carries its machine, command and output line. "Unmeasured" is a correct answer;
   "configured, so it works" is not. A job that reports success while doing nothing is the exact defect
   this estate has paid for twice — prove the effect, not the exit code.

## Definition of done, per job

A job is ported when ALL of these are true and written down:

1. Its script exists at its cloud path, mode 755 (or is a documented service).
2. Every file, credential and path it needs exists there — check each dependency from §2's list, and if
   one is missing, either move it (if you own that move) or **leave the job DISABLED and say so**; a job
   enabled with a missing dependency is worse than one that is off, because it manufactures failures.
3. It has run at least once, deliberately, and you have the evidence: the line in
   `/root/.cron-status/runs.tsv` (timestamp, name, rc, seconds) plus the job's own output or its effect
   in the world (a file written, a row changed, a message queued).
4. Its cron line is installed and `crontab -l` shows it.
5. You know what happens when it fails, and something would notice — name the monitor that reads it, or
   say plainly that nothing does and file a journal `pain` entry for it.

## Your report

Write `docs/mesh/<your number>-<slug>.md` and copy it to
`/root/out/migration-review/<same name>`. Per job: name, verdict you implemented, cloud path, cron line,
dependencies checked (each one: exists / missing), the evidence of the first run, and what would notice
its failure. Then a section "NOT PORTED, AND WHY" and a section "COULD NOT VERIFY". Finish by replying
with: jobs ported and proven, jobs deliberately left off and why, the exact commands of your strongest
evidence, and anything you could not verify. Honest gaps are welcome; confident claims you did not earn
are not.
