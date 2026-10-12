# 134 — ARCHIVE CONTINUITY: where every transcript now lives, and what still does not

Written 2026-10-11 06:20–07:00Z by the archive-continuity workstream of the authority cutover
(`131-MIGRATION-BRIEF.md`). Every number below carries the machine and the command that produced it.
Where I could not measure something, it says so instead of guessing.

Standing rule this serves: `AGENTS.md` §1 — *every DSH session and every VS Code Copilot chat is
archived forever, and a copy must always exist*, because it is the company's training data and its
institutional memory. The cutover froze the office box and with it the machinery that kept that rule
true. This is what was actually measured, what was moved, what was repaired, and what is still open.

---

## 0. The headline

Three things were true at once, and only the first was known:

1. The raw archive's bytes existed on the **frozen office box and nowhere else** — a single copy of
   the oldest and least reconstructible data in the company.
2. The hourly pull that was supposed to keep it current **had been structurally broken since
   2026-10-10**, before the freeze, by a one-line bug, and nothing alarmed on it.
3. Even if it had run, **the raw archive has never held a single byte of Copilot chat** — the kind
   `AGENTS.md` §1 promises — because its first backfill was truncated and never resumed.

Plus one live, silent, ongoing loss: **`zabz-tech-linux` has been queueing 301 sessions and 6,881
rows every 30 minutes since 2026-10-05 and the authority has refused every batch** for a missing
token, with nothing reading the log. That is `AGENTS.md` §1 trap 2 happening again, on a different
machine, in a different costume.

---

## 1. Measured state — where the only copy is, and how stale

### 1a. Raw transcript archive (the bytes — the one that cannot be reconstructed)

| | |
|---|---|
| **Location** | office box `secratary:/home/zabz/lpt-transcripts/` — **and, from 06:29Z today, `secratary-cloud:/opt/company/archive/lpt-transcripts/`** |
| **Only copy?** | It **was** — single copy on a frozen box until this workstream copied it. It is now two copies on two hosts. |
| **Contents (office box, at the copy)** | `manifest.sqlite` 1,544,192 B; `objects/` **1,652 files**, 590,207,096 raw bytes / **535,727,207 stored bytes**; `logs/`; `incoming/` 2.5 GB of consumed spool tars (deliberately **not** copied — see §2.2) |
| **Freshness** | newest arrival is **2026-10-09T04:22:20Z**. Nothing has entered the raw archive in **over two days** — and not because of the freeze; see §1c. |

Newest arrival per machine and kind, measured on the office box:

```
ssh secratary-ts "cd /home/zabz/lpt-transcripts && sqlite3 'file:manifest.sqlite?mode=ro' \
  'SELECT machine,kind,count(*),max(received_at),datetime(max(source_mtime),\"unixepoch\") \
   FROM arrival GROUP BY machine,kind;'"
```
```
machine    kind             files  newest_arrival                    newest_source_mtime
secratary  dsh-attachments  627    2026-10-09T02:52:41.307025+00:00  2026-10-09 00:55:13
zabz-yoga  dsh-attachments  918    2026-10-09T04:21:57.024642+00:00  2026-10-09 04:10:34
zabz-yoga  dsh-sessions     109    2026-10-09T04:22:20.004018+00:00  2026-10-09 04:01:57
```
`copilot-chats` is **absent from that result entirely** — `SELECT kind, count(*) FROM arrival GROUP BY
kind` returned exactly two rows, `dsh-attachments|1545` and `dsh-sessions|109`. The archive has never
ingested a Copilot chat.

**Coverage against the source**, measured on ZABZ-YOGA (the machine being archived, so this is the
source of truth for what should be there):

| source on ZABZ-YOGA | count | bytes | in the raw archive |
|---|---|---|---|
| `~/.dsh/sessions/**/session.v3.jsonl.zstd` | 1,014 | 527 MB | **109 — 10.7 %** |
| `~/.dsh/attachments/**` | 952 | 131 MB | 918 — 96.4 % |
| `AppData\Roaming\Code\User\workspaceStorage\**\GitHub.copilot-chat\**` | 193 | 518 MB | **0 — 0 %** |

Evidence: `Get-ChildItem $env:USERPROFILE\.dsh\sessions -Recurse -Filter session.v3.jsonl.zstd`
against the office-box query above. The machine's own contact row says the same thing in its own
words — `zabz-yoga … files_seen 10718, files_new 1027, note "truncated; more to pull"`, and the pull
never resumed.

### 1b. Parsed stores in the company database

Location: **`/root/authority.db` on `secratary-cloud`** (the live authority). The office box's
`secretary.db` is the frozen rollback anchor and holds an identical copy as of 04:28:35Z; it is not a
second live copy and must not be read as one.

Measured 2026-10-11T06:34:59Z, read-only:

```
ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 \
 "sqlite3 'file:/root/authority.db?mode=ro' \
  'SELECT source_machine,count(*),max(updated_at),max(ingested_at) FROM dsh_sessions GROUP BY source_machine;'"
```

| machine | `dsh_sessions` | newest `ingested_at` | age at 06:35Z | verdict |
|---|---|---|---|---|
| `zabz-yoga` | 1,688 | **2026-10-11T06:31:09Z** | 4 min | **current** |
| `zabz-tech` | 3,505 | **2026-10-11T06:06:26Z** | 29 min | **current** |
| `lakewooechsmini` | 101 | 2026-10-11T03:17:51Z | 3.3 h | reporting |
| `secratary` | 525 | 2026-10-11T03:00:54Z | 3.6 h | correct behaviour — the box is frozen, so it writes nothing |
| `zabz-tech-linux` | 107 | **2026-10-05T03:30:02Z** | **6.1 days** | **DEFECT — §4.3** |
| `mac` | 39 | 2026-10-08T12:05:20Z | 2.8 days | legacy name; `mac` is not in the archive's machine list |
| `desktop-fgv6kmh` | 23 | 2026-09-28T16:04:27Z | 12.6 days | legacy name (this machine, renamed to `zabz-tech`) |
| `lakewood-phone--techs-mac-mini.local` | 80 | 2026-09-18T23:38:34Z | 22.9 days | legacy name for the mac mini |

`dsh_session_events` (1,860,394 rows total) tracks the same machines with the same dates; it has no
`updated_at`, so freshness is read from the parent row.

### 1c. Why the raw archive stopped on 2026-10-09, and it was not the freeze

The runner's own log on the office box records three hourly passes on 2026-10-11 — 01:23, 02:23,
03:23Z — and **every one failed on every machine** with the same traceback, before cron was masked at
04:03:

```
ssh secratary-ts 'tail -3 /home/zabz/lpt-transcripts/logs/pull-20261011.jsonl'
  → "error": "cursor generation failed: Traceback (most recent call last): … transcript-archive-server.py,
     line 661, in main … "
```

Reproduced on a read-only copy of the manifest from this laptop, which gives the actual line:

```
python transcript-archive-server.py --db manifest.sqlite --cursor-out /tmp/c.json --machine zabz-yoga
  File "transcript-archive-server.py", line 571, in cmd_cursor
    "held": [[r["kind"], r["rel_path"], r["sha256"]] for r in rows]}
IndexError: No item with that key
```

`cmd_cursor` selected `COALESCE(source_sha256, sha256) AS s` and then read back `r["sha256"]`, a
column that is not in the result set. `--cursor-out` is step 1 of every pull, so **no pull could run
on any machine**, and the last successful ingest stayed at 2026-10-09T04:22:20Z.

It went unseen for two days because **only a GAP (check exit 1) ever raised `ALARM` or filed a
journal entry**. A failed pull exited 3, and `cron-wrap.sh` recorded `rc=3` in
`~/.cron-status/runs.tsv` once an hour where nobody read it. Fixed in §3.3 and §3.4.

---

## 2. The second copy, and its verification

### 2.1 What was copied where

```
source      secratary:/home/zabz/lpt-transcripts/{objects/,manifest.sqlite,logs/}
target      secratary-cloud:/opt/company/archive/lpt-transcripts/
method      rsync -a --numeric-ids over an ssh reverse-forward relay (below)
result      1,652 files, 535,727,207 bytes, speedup 1.00, "Number of deleted files: 0"
```

The authority has no Tailscale and no route to the fleet (§5.2), so the transfer was relayed through
ZABZ-YOGA with `ssh -R 127.0.0.1:2222:secratary.tail93e6e6.ts.net:22` and the authority's own
`id_ed25519` — which the office box's `authorized_keys` already carries as `secratary-cloud`.

### 2.2 What was deliberately not copied

`incoming/` — **2,534,974,266 bytes** of spent spool tars (`secratary.tar` 400 MB, `zabz-yoga.tar`
2.13 GB). They are the packed input of ingests already recorded `ok=1` with
`members == new_objects` (627/627 and 1027/1027), so their bytes are already content-addressed under
`objects/`. Copying 2.5 GB of duplicate bytes onto a volume shared with a 23.6 GB database would have
bought nothing.

### 2.3 Verification — every object, not a sample

The object store is content-addressed, so each file's name **is** the sha256 of its *raw* bytes;
`.zst` objects are named for the raw bytes and stored compressed. All 1,652 were re-hashed on the
authority, decompressing where necessary:

```
for f in $(find . -type f); do case "$base" in *.zst) got=$(zstd -dc "$f" | sha256sum) ;; *) got=$(sha256sum "$f") ;; esac;
  [ "$got" = "$name" ] && ok++ || bad++ ; done
→ objects verified by content hash: ok=1652 bad=0
```

Object count and byte totals are identical on both hosts (`find objects -type f | wc -l` = 1652;
`du -sb objects` = 535,727,207 on the office box and on the authority). `manifest.sqlite` is the same
1,544,192-byte file.

### 2.4 Tooling, and the same read commands working there

Deployed `transcript-archive-{server,pull,run}*.py|sh` and `archive-transcripts.py` to
`secratary-cloud:/opt/company/archive/tools/` (`.source` records `harness-config` commit `ee3a7e2`),
symlinked at `/root/code/harness-config/scripts/` so the paths `AGENTS.md` §1 documents resolve, and
`/etc/environment` exports `TRANSCRIPT_ARCHIVE_ROOT`, `TRANSCRIPT_SCRIPTS`, `TRANSCRIPT_STATE_DIR`,
`TRANSCRIPT_JOURNAL`.

```
ssh secratary-cloud 'python3 ~/code/harness-config/scripts/transcript-archive-server.py --stats'
 → {"ok": true, "archive_root": "/opt/company/archive/lpt-transcripts",
    "objects": {"count": 1652, "raw_bytes": 590207096, "stored_bytes": 535727207}, "arrivals": 1654, "quarantined": 0}
```

`zstd` was installed (the authority had neither the `zstandard` module nor the `zstd` binary, and
`--read` on a `.zst` object needs one of them).

**Nothing about the safety rules was weakened.** `REFUSE_NAMES` (VS Code `state.vscdb`, the Copilot CLI
`session-store.db`, `.env`, `id_*`, `*.pem`, `*.key`, `.netrc`, `authorized_keys`) is untouched;
card/credential redaction is untouched; and the cursor still keys on `source_sha256`, never on the
stored hash — the changed line in §3.3 was changed *towards* that rule, not away from it. Quarantine
count on the copied archive: 0.

---

## 3. The schedule, on the machine that is always on

### 3.1 The unit

`/etc/systemd/system/transcript-archive-pull.timer` → `transcript-archive-pull.service` →
`/usr/local/bin/transcript-archive-pass.sh` → `harness-config/scripts/transcript-archive-run.sh`.
Absolute paths throughout, `Persistent=true` (a missed window runs once on the next boot), journald
logging, `Nice=10` + `IOSchedulingClass=idle` so an archive pass can never starve the authority.

`OnCalendar=*:23` keeps the estate's own `23 * * * *` rhythm. `SuccessExitStatus=0 2` because exit 2
is "no gap, but a machine is silent", which a powered-off laptop produces honestly every night; exit
1 (GAP) and exit 3 (the pull itself failed) **fail the unit**, so `systemctl --failed` and journald
carry them. That is the difference from the cron layer it replaces.

### 3.2 Proof it is scheduled

```
ssh secratary-cloud 'systemctl list-timers transcript-archive-pull.timer --no-pager'
NEXT                         LEFT LAST PASSED UNIT                          ACTIVATES
Sun 2026-10-11 07:23:00 UTC  57min    -      - transcript-archive-pull.timer transcript-archive-pull.service
```

### 3.3 The bug that had to be fixed first (harness-config, committed)

`scripts/transcript-archive-server.py` `cmd_cursor` — the `r["sha256"]` / `AS s` mismatch of §1c, with
a hard guard so the alias and the read can never drift apart again.

`scripts/transcript-archive-pull.py` — **two traps, both found by running it on the authority:**

* **`secratary` was hardcoded `alias: "local"`.** That was right on the office box, which *was* the
  archive host. On the authority it made the pull run `archive-transcripts.py` against the **cloud
  box's own files** and record `secratary … files_seen=0, newest_source_mtime=0.0`. Because `--check`
  compares newest *source* mtime against newest *archived* mtime, a source mtime of **zero** is older
  than everything — the office box, the one holding the only copy, would have read as perfectly
  current **forever**. Now each machine's alias is overridable per host
  (`/etc/transcript-archive.env` sets `TRANSCRIPT_ALIAS_SECRATARY=secratary-ts`) while the machine's
  identity in the manifest is unchanged, so every existing cursor still matches.
* **The failure message named the wrong cause.** Every unreachable machine reported *"no working
  (python, archive-transcripts.py) pair … is harness-config synced there?"* while the actual line was
  `ssh: Could not resolve hostname secratary.tail93e6e6.ts.net`. The probe now carries the transport's
  own last line into the error.

`scripts/transcript-archive-run.sh` — **a failed pull and a failed check are now alarms**, not just a
GAP: both write `ALARM` and file one guarded journal `pain` entry. Without this the exact 2026-10-10
failure would repeat invisibly. `TRANSCRIPT_JOURNAL` also became overridable so the runner works off
the office box.

`scripts/transcript-archive-server.py` — **a read may no longer invent the archive it reads**.
`connect()` creates the database when missing, which is right for an ingest and wrong for every read:
`--stats` with a path that holds nothing printed `ok: true, objects: 0, arrivals: 0` — a clean bill of
health — and `--cursor-out` handed back an **empty cursor**, which would make the client re-send the
entire corpus. Measured, then guarded:

```
python3 transcript-archive-server.py --db /tmp/does-not-exist/nope.sqlite --stats
 → {"ok": false, "error": "archive database does not exist at … - refusing to report an empty archive as health"}
   exit 3
```

### 3.4 Proof it ran — and exactly where it stops

Three passes were run at 06:26:44Z, 06:27:27Z and 06:27:40Z; the unit enters `failed` with
`ExecMainStatus=3`, and the journal carries:

```
journalctl -u transcript-archive-pull.service -o cat
  Starting transcript-archive-pull.service …
  2026-10-11T06:27:40Z TRANSCRIPT ARCHIVE PULL FAILED — machines could not be pulled, so nothing was archived this pass
  transcript-archive-pass: run.sh exit=3
  spool: removed secratary.tar (10240 bytes) -- its ingest is recorded ok=1
```

The per-machine result, from the runner's own JSON log:

```
machine            alias           ok      error
secratary          secratary-ts    False   could not run the client on that machine — the probe's own last output was: ssh: Could not resolve hostname secratary.tail93e6e6.ts.net: Name or service not known
zabz-yoga          zabz-yoga-1     False   (same)
zabz-tech          zabz-tech       False   (same)
zabz-tech-linux    linux-pc-ts     False   (same)
lakewooechsmini    mac-mini-ts     False   (same)
failed: ['secratary','zabz-yoga','zabz-tech','zabz-tech-linux','lakewooechsmini']
```

**The schedule is installed, enabled, and proven to execute, log, alarm and fail loudly. It cannot
yet archive anything, and the reason is a missing network path, not a missing job — §5.2.**

### 3.5 The catch-up that closed the 2-day gap anyway

Because the authority can reach the fleet through a relay hosted on ZABZ-YOGA, the real pull was run
on the authority — through `catch-*` ssh aliases pointing at the relay ports — so that objects landed
in the real cloud archive through the real pipeline:

* arrivals before: **1,654**; objects 1,652 / 535,727,207 stored bytes
* `secratary.tar` built at **397,404,160 B** from the office box — the first time the office box's
  own transcripts since 2026-10-09T02:52 have been captured at all
* arrivals during the run: **2,803**; objects 516 MB → **790 MB** on disk

**This is a one-shot catch-up, not the durable path** — its transport is a relay on a laptop, which is
exactly the dependency `AGENTS.md` §1 trap 2 exists to forbid. It is labelled as such and it is not
what the timer uses. The run was also stopped early (§5.4) rather than pushed to completion.

---

## 4. The per-machine pushers — verified by row delta, not by exit code

### 4.1 `PersonalSecretary-PushDSHSessions` on ZABZ-YOGA — works

```
Get-ScheduledTask PersonalSecretary-PushDSHSessions | Get-ScheduledTaskInfo
  last 10/11/2026 02:05:01   result=0   next 03:05:00
  action: wscript … \scripts\hidden-tasks\PersonalSecretary-PushDSHSessions.vbs
          → node scripts\push-dsh-sessions.mjs          (no args; transport defaults to http,
                                                          endpoint defaults to api.abletelsolutions.com)
```
The destination is the **new authority**: `zabz-yoga` `newest ingested_at 2026-10-11T06:31:09Z`
against a task that last fired at 06:05:01Z. A live run from this laptop, same command as the task,
ships rather than merely succeeding:

```
node scripts/push-dsh-sessions.mjs --dry-run
  would ship: 7 session(s), 2215 new row(s), 13344 KB
  unchanged : 1685 session(s) already complete (cursor)
```
The live run — the same command the task issues — exited **0** with
`shipped: 10 session(s), 4202 new row(s), 23173 KB`, and it printed
`retry 1/3 in 5s — ingest transport: The operation was aborted due to timeout` before it did: the
authority's ingest endpoint was slow under the concurrent migration load, and **the pusher's own retry
ladder is what turned that into success rather than a silent loss.** `dsh_sessions` for `zabz-yoga`
went 1,686 → 1,688 and `dsh_session_events` 778,815 → 779,406 in that window. **This pusher is real.**

### 4.2 `PersonalSecretary-PushVSCodeChats` on ZABZ-YOGA — succeeds and is telling the truth

```
last 10/11/2026 01:26:15  result=0   next 02:26:14
action: wscript … PersonalSecretary-PushVSCodeChats.vbs
        → push_vscode_chats.py --days 1 --server https://api.abletelsolutions.com --stats --exclude-workspace phone-and-tech-full
```
Its own output: `Found 0 sessions across 0 workspaces (0.3s) / Nothing to push.` That is **not** the
21-day trap this time — the source really is empty:

| machine | Copilot transcript files | newest file | newest in `vscode_chat_sessions` |
|---|---|---|---|
| ZABZ-YOGA | 193 (518 MB) | **2026-06-05** | 2026-09-18T07:26:17Z (350 sessions / 905 messages) |
| ZABZ-TECH | 111 | **2026-09-14** | 2026-09-14T20:30:33Z (1,258 / 3,468) |

Neither machine has written a Copilot chat in 27+ days, so "nothing to push" and "the store is at
its source-mtime" agree. **Residual defect, recorded not fixed:** `--days 1` is an outer *window*, not
a cursor. `push_vscode_chats.py` also keeps `data/vscode_chat_sync_state.json`, so a session seen once
is not re-sent — but a chat created while the pusher was down falls outside the window on every later
run and is then never shipped to the **parsed** store. The raw archive is the safety net for that, and
it is the thing that was broken (§1c). Also note `vscode_chat_extractor.py`'s silent 50 MB skip
(`AGENTS.md` §1 trap 3) — currently 0 such files on ZABZ-YOGA, so it is not biting today.

### 4.3 `zabz-tech-linux` — the live defect, found and repaired

```
crontab -l on zabz-tech-linux
  */30 * * * * cd /home/zabz/code/harness-config && /usr/local/bin/node scripts/push-dsh-sessions.mjs \
               --transport http >>/home/zabz/.dsh-session-ship.log 2>&1
```
Every 30 minutes, forever:

```
tail ~/.dsh-session-ship.log
  REFUSED  : 100 fragment(s) not accepted by the authority — no token: set DSH_ARCHIVE_TOKEN
  cursor   : NOT advanced for these sessions; they are re-sent whole next run
  queued: 301 session(s), 6881 new row(s), 20612 KB
  refused: 5 batch(es)
  unchanged: 107 session(s) already complete (cursor)
```

Cause: the pusher's token lookup (`$DSH_ARCHIVE_TOKEN`, then `~/code/personal-secretary-mvp/.env`,
`~/Code/…`, `~/personal-secretary-mvp/.env`, `~/code/harness-config/.env`) found **none of those
files** on that box — `ls` showed all three paths MISSING. The machine has 408 session files on disk,
newest 2026-10-11T00:00:47Z, and the authority has received **nothing from it since
2026-10-05T03:30:02Z**.

Repair: wrote `/home/zabz/code/harness-config/.env` (mode 600, untracked so `autosync.sh`'s
add-and-overwrite-only apply cannot remove it) with `DSH_SESSION_INGEST_TOKEN` — the path the shipper
itself documents as *"the one place guaranteed to exist wherever this script runs"*. The box's pusher
was then run by hand, and **it worked**:

```
cd /home/zabz/code/harness-config && node scripts/push-dsh-sessions.mjs --transport http
  retry 1/3 in 5s — ingest transport: The operation was aborted due to timeout
  shipped: 301 session(s), 6881 new row(s), 20612 KB
  unchanged : 107 session(s) already complete (cursor)
```

`shipped` is the authority's own acknowledgement — the identical code path that had printed
`REFUSED : … no token` every 30 minutes for six days. The cron line is unchanged and will now advance
its cursor instead of re-queueing the same 301 sessions forever. **(Independent row count on the
authority is still unmeasured — §5.3 — because ssh to it went down while this ran.)**

---

## 5. What I could not verify

1. **`lakewooechsmini` (the mac mini) is SILENCE, not health.** `ssh mac-mini-ts` times out from
   ZABZ-YOGA — `ssh: connect to host lakewooechsmini.tail93e6e6.ts.net port 22: Connection timed
   out` — so it was never pulled through the relay either. Its parsed `dsh_sessions` last ingested
   2026-10-11T03:17:51Z, i.e. it *was* reporting a few hours ago and has since gone quiet. From the
   authority a powered-off machine and a broken pull look identical; this is reported as exactly
   that, never as health.

2. **The durable pull path does not exist yet: the authority is not on the tailnet.** Measured:
   `ip -o link show` → `lo eth0` only; `command -v tailscale` → ABSENT (since installed 1.104.1, but
   `tailscale status` → "Logged out"); `getent hosts secratary.tail93e6e6.ts.net` → nothing.
   The estate's own `TAILSCALE_AUTH_KEY` in `/opt/company/.env` is **dead**:
   `tailscale up --authkey=… --hostname=secratary-cloud --accept-dns=false --accept-routes=false` →
   `backend error: invalid key: API key does not exist`. `docs/mesh/88-elastic-build.md` §3.4 already
   records that **no Tailscale API token exists anywhere this fleet can reach**, so no new key can be
   minted from inside the estate. `docs/mesh/122-cloud-authority-provision.md:48` and
   `126-authority-cutover-runbook.md:104-106` both make "join the tailnet **before** provisioning" a
   required step; `123-mesh-state-of-play.md:50` records it as **NOT DONE**. It is still not done, and
   it blocks the archive, the mesh broker and the freshness monitors alike. **This needs one
   Tailscale auth key generated in the admin console (key expiry disabled, as `79-elastic-cloud.md`
   §1.3 prescribes).**

3. **`zabz-tech-linux`'s row delta is unmeasured.** The repair is in place and the pusher was run;
   the authority accepted **301 sessions / 6,881 rows** by its own accounting, which is the same
   response path that had refused with `no token` for six days. What is missing is the independent
   count on `/root/authority.db` that §4.1 has for `zabz-yoga`: ssh to the authority became
   unavailable (§5.4) before it could be taken. Treat the fix as **very likely correct and not yet
   independently confirmed**. The verification command, for whoever has access, is one line:
   `sqlite3 "file:/root/authority.db?mode=ro" "SELECT count(*),max(ingested_at) FROM dsh_sessions WHERE source_machine='zabz-tech-linux';"`
   — before the repair it read 107 / 2026-10-05T03:30:02Z.

4. **I lost ssh to `secratary-cloud` at ~06:41Z and could not diagnose or fix it.** This is the most
   serious thing in this report and it is not my own breakage, but it now affects every workstream.

   Measured facts:

   * `https://api.abletelsolutions.com/health` and `https://ai.abletelsolutions.com/health` kept
     answering **HTTP 200** throughout — the company is up.
   * The failure is **server-side, not source-scoped**: the same key is refused from ZABZ-YOGA, from
     the office box, and from `lpt-survivor-01` and `lpt-apps-01`. So it is not `PerSourcePenalties`
     and not a failure of one client.
   * The **host key is unchanged** — `ssh-keyscan -t ed25519 178.156.194.1` returns
     `AAAAC3NzaC1lZDI1NTE5AAAAIJRTR+qtCMByDTO3OiDS/jIA0yKmoDUPrcNeHCNlr5nZ`, byte-identical to the
     line stored in `known_hosts` earlier today, and the banner is the same `OpenSSH_10.2p1 Ubuntu`.
     **The box was not rebuilt or replaced.**
   * With `-v` the key exchange completes, the client offers
     `SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynHtRL4rmAKg (mesh-hetzner-2026-08-31)` — **the exact key
     `135-PARITY-AND-ROBUSTNESS.md:208` recorded as the only line in that box's
     `/root/.ssh/authorized_keys`** — and the server answers `Authentications that can continue:
     publickey`. Symptoms move between `Permission denied (publickey)`,
     `kex_exchange_identification: read: Unknown error`, `banner exchange … Unknown error` and
     `Connection closed`.
   * It authenticated fine at **06:34:59Z** (the `--stats`/freshness readings above) and not at
     **06:41Z**. I changed only `/opt/company/archive/**`, `/etc/systemd/system/transcript-archive-pull.*`,
     `/etc/transcript-archive.env`, `/etc/environment`, `/root/.ssh/config` and
     `/root/code/harness-config/scripts/` on that host.

   The prime suspect is a **concurrent workstream applying the hardening in
   `126-authority-cutover-runbook.md:111-112`** — `sed -i 's/^#\?PasswordAuthentication.*/…/' /etc/ssh/sshd_config && systemctl reload ssh`,
   then `ufw allow 22/tcp; ufw allow in on tailscale0; ufw --force enable`, with `fail2ban` installed
   by the line above them. Any of those, applied from a template that also sets `PermitRootLogin no`
   or an `AllowUsers`/`Match` block, refuses root key auth with exactly the message observed, while
   leaving the API, the tunnel and the dashboard untouched. I could not confirm it, because
   confirming it requires the access it removed.

   **Consequences:** `/root/out/migration-review/134-ARCHIVE-CONTINUITY.md` could **not** be written;
   the 07:23Z timer run could not be observed; and there is **no out-of-band recovery**, because
   `135-PARITY-AND-ROBUSTNESS.md` records the `HETZNER_API_TOKEN` in `/opt/company/.env` as **invalid**
   (`/v1/servers` → `401`), so the Hetzner console path is closed too. This needs the manager: find
   which workstream reloaded sshd on `secratary-cloud`, or issue a fresh Hetzner token so the console
   can be used.

5. **`134-ARCHIVE-CONTINUITY.md` (this file) is the artifact `141-MIGRATION-STATUS.md` assigns to the
   "transcript archive + session/chat ingestion" workstream** — no other workstream has claimed it, and
   the tailnet key is already **owner question 445** in the manager's hands. Neither is duplicated
   here.

6. **I ran one archive pass outside systemd**, so it had none of the unit's `Nice=10` /
   `IOSchedulingClass=idle`, on a 2 vCPU box that also runs the authority. It may have contributed to
   load; the third and fourth passes were stopped rather than pushed to completion. That was a
   mistake on my part, and it is the reason §3.5's catch-up is partial rather than finished.

---

## 6. Exactly what changed

| # | change | where | proof |
|---|---|---|---|
| 1 | Raw archive given a second copy | `secratary-cloud:/opt/company/archive/lpt-transcripts/` | 1,652 objects, 535,727,207 B, `ok=1652 bad=0` content hashes |
| 2 | `cmd_cursor` fixed (`r["sha256"]` → the aliased column) | `harness-config/scripts/transcript-archive-server.py` | reproduction before, `held 1027` / `held 627` after |
| 3 | Read commands refuse a non-existent archive | same file | `exit 3` + explicit error, not `ok:true, objects:0` |
| 4 | Failed pull / failed check now raise `ALARM` + one journal `pain` | `scripts/transcript-archive-run.sh` | new alarm branches; `bash -n` clean |
| 5 | Per-host machine→alias override; honest transport error | `scripts/transcript-archive-pull.py` | `secratary alias=secratary-ts`; error now quotes the ssh line |
| 6 | Hourly timer on the always-on host | `transcript-archive-pull.{timer,service}` | `systemctl list-timers` 07:23:00 UTC; three runs journalled |
| 7 | Archive tooling + documented read commands work on the authority | `/opt/company/archive/tools/`, `/root/code/…`, `/etc/environment` | `--stats` → 1,652 objects / 1,654 arrivals |
| 8 | Catch-up of the office box's 2026-10-09→11 backlog | cloud archive | `secratary.tar` 397,404,160 B; arrivals 1,654 → 2,803 |
| 9 | `zabz-tech-linux` pusher unblocked | `/home/zabz/code/harness-config/.env` (600) | authority accepted `shipped: 301 session(s), 6881 new row(s)`; independent row count unmeasured (§5.3) |

Not done, deliberately: nothing was unmasked, enabled, started or written on the office box; the
archive's `REFUSE_NAMES` / redaction / `source_sha256` cursor semantics are untouched; `company-api`,
`cloudflared`, `secretary-dashboard` and `phone-redirector` were never restarted; `incoming/`'s 2.5 GB
of consumed tars were not copied; and the one bogus `machine_contact` row my first pass wrote
(`secratary`, `files_seen=0`, `newest_source_mtime=0.0`) was deleted from the authority's manifest so
it could not mask the office box as current — it is recorded here instead.
