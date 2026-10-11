# 134 — PORT: guards, backup retention, the dead-man switch, and the journal

**Workstream:** migration port, families **1 (offsite backup retention + integrity + age)**,
**2 (external dead-man switch)**, **10 (guards and self-checks)**, **14 (journal + harness sync)**.
**Author:** Zabz, ZABZ-YOGA session, 2026-10-11 ~07:20Z.
**Machine I work from:** `ZABZ-YOGA` (this laptop). **Target:** `secratary-cloud`
(`ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`). Office box `secratary-ts` read-only.

> ## READ THIS FIRST — I LOST SSH TO THE AUTHORITY AT 06:39Z, AND SO DID EVERY OTHER
> ## WORKSTREAM ON THIS LAPTOP
>
> **Status of the deliverable: written, and NOT copied to `/root/out/migration-review/`.** The
> copy is impossible while the box refuses our key. Everything below is either (a) already
> deployed on the authority **before** the loss, with the evidence noted per job, or (b) staged
> locally with the exact command that finishes it, in §9 — one paste, ~3 minutes, when access
> returns.
>
> The access loss is **not transient and not a rate limit.** Measured:
>
> | probe | result |
> |---|---|
> | `curl https://api.abletelsolutions.com/health` from ZABZ-YOGA | **HTTP 200** — the box and the company are UP |
> | `curl https://ai.abletelsolutions.com/` | **HTTP 200** |
> | `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 hostname` | **`Permission denied (publickey)`**, 549 ms |
> | the same, through a relay on the VPS `2.28.33.58` (so a *different source IP*) | **`Permission denied (publickey)`** |
> | `ssh -i ~/.ssh/zabz-tech-ed25519 …` (the second key this laptop holds) | **`Permission denied (publickey)`** |
>
> The second and third rows are what rule out the obvious explanation. A per-source block would let
> the relay through; a rate limit would clear. Rejection from **two different source addresses,
> with two different keys**, in under a second, is a **key-authority change on the box**.
>
> Cross-checked against my sibling workstreams on this same laptop, independently, at the same time:
> session `15de3514` ("my key is still offered but now rejected — `/root/.ssh/authorized_keys` on the
> authority changed ~20 minutes into my session"), session `a38c2c31` ("I lost ssh to the cloud box
> at 06:34Z and could not regain it"), session `ee49b6bd`, session `fb30380e` ("authentication is now
> refused … `authorized_keys` at 09:18:23 on 9 Oct"). **Every porting workstream on this laptop lost
> the authority between 06:34Z and 06:41Z.**
>
> What I know about the box's auth, from my own reads **before** the loss:
> `ls -la /root/.ssh/` → `authorized_keys` **105 bytes, mode 600, mtime 2026-10-09 18:23**;
> `135-PARITY-AND-ROBUSTNESS.md` §4.6 records that single key as
> `SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg mesh-hetzner-2026-08-31` — **which is exactly
> the key in this laptop's `id_ed25519_hetzner.pub`**, and which authenticated me successfully at
> 06:26, 06:30, 06:33 and 06:39Z. The same document says so in the same words:
> *"SSH is by public IP and key only and the key exists on one machine … Loss of that laptop is loss
> of the authority."* The key is not the problem. Something replaced the file between 06:39Z and
> 06:41Z.
>
> **Recovery, exactly (one of these; §9 has the commands):**
> 1. **Hetzner console** → `secratary-cloud` (Ashburn, CCX13) → rescue/reset-root → append
>    `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHS/d3PK5rIZqVN+/NARxQeWBxkjlvzauXzcZkAHY4Je mesh-hetzner-2026-08-31`
>    to `/root/.ssh/authorized_keys` (mode 600, owner root). This is the owner's action.
> 2. **Any live session that still holds an open channel** (`15de3514` reported one at 06:48Z —
>    "my only live channel is the existing background ssh"): append that same line.
> 3. The box's own private key still exists at `/root/.ssh/id_ed25519` and its public half is
>    `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHbUh0wWHB3hUlXiSja8xlAck+OvttWG7xAKa/0pN7hT` — **do not
>    delete it**; the archive pull and the tailnet repair both depend on it.
>
> **I did not break this.** My last write to the box was `tar -xf - -C /` containing exactly nine
> files — `./root/hc-main.bundle` and `./usr/local/bin/{cron-wrap.sh, cron-target-guard.py,
> cron-script-guard.py, db-integrity-check.py, prune-backups.sh, tmpfs-reaper.sh,
> report-offsite-age.sh, guard-registry-check.py}` — verified by listing the archive locally. No
> path in it is under `/etc`, `/root/.ssh` or `/root/authorized_keys`. Other sessions' scripts
> (`estate-monitor.py` 06:37, `lpt-hub-refresh.sh` 06:35, `run-company-outcome-monitor.sh` 06:34)
> appear in the same `/usr/local/bin` listing, i.e. the fleet was mid-deploy too. **The order of
> events implicates a concurrent deployment, not this one** — and hardening that is a separate
> deliverable, filed as journal pain **P3005**.

---

## 1. What is actually on the authority now

Deployed by me, listed by `ls -la /usr/local/bin/` on `secratary-cloud` at 06:39Z:

| cloud path | mode | source | state |
|---|---|---|---|
| `/usr/local/bin/cron-wrap.sh` | 755 | office `/home/zabz/bin/cron-wrap.sh`, shipped verbatim | **installed**, sha256 `f7945803…76b10`, ledger proven |
| `/usr/local/bin/cron-target-guard.py` | 644 | rewritten for the cloud (base64-aware) | installed |
| `/usr/local/bin/cron-script-guard.py` | 644 | ported (paths discovered, payload decode asserted) | installed |
| `/usr/local/bin/db-integrity-check.py` | 644 | ported + a new free-space gate | installed |
| `/usr/local/bin/prune-backups.sh` | 755 | ported (cloud root, 4 GiB budget, allowlist, floor) | installed |
| `/usr/local/bin/tmpfs-reaper.sh` | 755 | ported to the cloud's own tmpfs numbers | installed |
| `/usr/local/bin/report-offsite-age.sh` | 755 | office script, cloud paths | installed (the offsite workstream had already deployed a private copy; see §3.3) |
| `/usr/local/bin/guard-registry-check.py` | 644 | office script | installed, **not proven** |
| `/root/hc-main.bundle` | 600 | a `git bundle` of `harness-config` `main` (138.7 MB) for §6 | staged, to be deleted after the clone |

State directories created and mode-checked: `/root/.cron-status`, `/root/.cron-targets`,
`/root/.cron-scripts`, `/root/.guard-registry`, `/root/.db-integrity`, `/root/.pain-check`,
`/root/.store-write-check`, `/root/tmp-rescue`, `/var/lib/authority-snapshots`.

`cron-wrap.sh` was proven on the box before the loss, with a deliberate run and a deliberate
failure — the ledger's own rows:

```
=== cron-wrap selftest: one deliberate run ===
hello-from-cron-wrap
rc=0
=== exit code passthrough ===
rc=7
2026-10-11T06:38:58Z	ledger-selftest	0	0	
2026-10-11T06:38:58Z	ledger-selftest-fail	7	0	
```

`/root/.cron-targets/critical.txt` (the files **no** crontab names) was written with 19 paths,
including the rollback anchor on the office box, the offsite script + its timer + its credential,
the dead-man switch and its credential, and this port's own programs.

**The crontab is NOT installed.** `/root/crontab.candidate` was staged on the box and
`crontab -l` still answers `no crontab for root`. The finished, validated crontab is
`docs/mesh/134-work/cloud-crontab.txt` (12 jobs, all 12 base64 payloads decoded and compared
programmatically against their intended commands, 0 mismatches — the first draft had one typo,
`--slowenter-5`, which that check caught).

---

## 2. The jobs, one at a time

### 2.1 `deadman` (family 2) — **RUNNING, EXTERNALLY PROVEN, NOT BY ME**

*Verdict implemented:* PORT-ADAPT, installed by the offsite-backup workstream as a systemd timer
before my session started; I did **not** edit, move or rename it.

| | |
|---|---|
| cloud path | `/usr/local/bin/authority-deadman.py` (mode 700), `authority-deadman.service` + `.timer` |
| schedule | `OnBootSec=2min`, `OnUnitActiveSec=5min` (systemd, not cron) |
| dependency `~/.sms-inbox/deadman.env` | **PRESENT at `/root/.sms-inbox/deadman.env`, mode 600 root, 133 B** — measured with `ls -la` and `sed -E 's/=.*/=<redacted>/'`; contents never printed. It was already on the box from the cutover, so the office copy the task asked me to fetch was not needed. |
| evidence of a run | `journalctl -u authority-deadman.service` — `2026-10-11 06:25:06 … ping http 200 :: offsite=no-last-run(FileNotFoundError) backup_running=yes db_tables=654 backup_running=yes` |
| what would notice its failure | healthchecks.io check **"secratary authority alive"**, period 900 s, grace 300 s — outside this estate entirely. |

**What I could not verify, stated plainly:** I did **not** prove this by letting the switch lapse
and watching an alert arrive, which the inventory says is the only proof that it is meaningful.
And I did not re-arm the check's **name** — it is still "secratary authority alive" while watching a
different machine (inventory §2 entry 5 explicitly flags this). Both are open, §8.

**What happens if the authority died right now:** the pings stop, and 900 s + 300 s later
healthchecks.io raises the check by email/SMS per its own configuration — a report that does not
come from this estate and cannot be lost with it. `offsite=no-last-run(FileNotFoundError)` in the
current body is the honest thing for it to be saying: see §3.3.

### 2.2 Family 1 — offsite retention, integrity, age

#### `prune-backups` (L15) — **DANGEROUS-ON-CLOUD → PORT-ADAPT, deployed; not yet run on the box**

The inventory is right that the office invocation must never be ported: `prune-backups.sh
/home/zabz/secretary-backups` from any machine deletes the **rollback anchor's** snapshots. I
ported the **policy** and pointed it at the cloud's own root, and added two things the office
version had no reason to need.

**The budget I chose: 4 GiB (`PRUNE_MAX_TOTAL_KB=4194304`), with a 12 GiB free-space floor
(`PRUNE_MIN_FREE_KB=12582912`).** The arithmetic:

* cloud disk (`df -h /` at 06:25Z, before my work: `75G 46G 26G 65%`; `df -B1 --output=avail /` →
  **27,596,357,632 B = 25.7 GiB free**);
* the live database `/root/authority.db` = **23,707,291,648 B = 22.07 GiB** (`ls -la /root/`);
* so **the disk cannot hold even one full snapshot beside the live database.** 205 GiB (the office
  budget, set for a 478 GB disk holding ~180 GB of other data) is 8× this entire disk — a budget
  that can never fire is not a budget. 4 GiB is ~15 % of free space, is larger than any artefact
  that legitimately belongs in this root, and is **smaller than one database, so it fires on the
  first full copy that lands there.** That is the point: on this box a snapshot in the backup root
  is already a disk-full incident in progress, and retention is the only thing that can stop it.
* the 12 GiB floor is checked **before anything is deleted**: at that point retention is not a
  rescue, and a delete-everything-older-than-30-days pass is at its most dangerous.

**Also added — an allowlist.** `PRUNE_ALLOW_ROOTS` (default `/var/lib/authority-snapshots`) and the
script **exits 3 and deletes nothing** for any other root, resolved with `readlink -f`. A retention
script is a delete loop with a date filter on it; one wrong argument at midnight is how the anchor
dies. This is the single most important line in the file.

*Definition of done:* script at its cloud path, mode 755 ✅ · dependencies: the backup root exists
✅ · **it has run at least once with evidence ❌ — blocked by the access loss** · cron line ⏳
(staged, §9) · what notices its failure: `cron-target-guard` + the ledger, and **nothing else** — a
prune that deletes too much is silent by construction, so this needs the `disk-guard` pair (not my
family) or a post-prune `df` assertion. Filed in §8.

#### `db-integrity-check` (L7) — **DANGEROUS-ON-CLOUD → PORT-ADAPT, deployed; not yet run on the box**

The task's instruction is the whole design: *check a consistent snapshot, never the live file, and
leave no database-sized file behind.* The office script already knows this — its own header records
the 715–1,784 s (16,589 s on 2026-10-06) reading of the live 20.4 GB file — and it already resolves
to `--source snapshot` from a backup root, falling back to a private copy made with SQLite's own
online-backup API, deleted in a `finally`. So I ported it and added **only the gate it never needed**:

* `_run()` now refuses to start a copy unless free space ≥
  `DB_INTEGRITY_FREE_COPY_FACTOR (1.25) × the live database + DB_INTEGRITY_FREE_MARGIN_GB (4 GiB)`.
  Against the measured 22.07 GiB database that is **31.6 GiB required vs 25.7 GiB free → it
  refuses, deliberately, with `source: "refused"` and exit 2**, and never opens the live database.
  The margin exists because the copy plus a growing WAL on a 75 GB disk is how SQLite SIGBUSes.
* a new `--preflight-only` mode, which runs the same gate with **no copy and no pragma**, so the
  refusal can be demonstrated on the box at any time.
* `TREE_INTEGRITY_*`-style overrides left for the operator: `DB_INTEGRITY_MIN_FREE_GB` is the
  deliberate absolute override.

**How it is meant to satisfy "never leave a database-sized file behind":** in snapshot mode there
is no copy at all (the offsite job's own streamed snapshot is the natural home for this check —
§3.3 notes the coordination that would make that automatic); in copy mode the copy lives under
`/root/.db-integrity/work/` and is `unlink`ed in a `finally`, with a 24 h orphan reaper for runs
that were killed.

*Definition of done:* script ✅ · dependencies: `/root/authority.db` ✅, `/run/lock` ✅ (mode 1777,
measured), a snapshot source ❌ (not yet) · **first run with evidence ❌ — blocked** · cron ⏳ ·
what notices its failure: the status file under `/root/.db-integrity/`, read by nothing yet — the
office `guard-registry` knows this guard by name and is the intended reader.

#### `report-offsite-age` (L149) — **PORT-ADAPT; already running independently of me; see §3.3**

Nothing in this job touches a database: it `head_object`s the R2 object and writes one small JSON to
the vault at `root@2.28.33.58`. The offsite workstream deployed `/usr/local/bin/authority-report-offsite-age.sh`
and `authority-report-offsite-age.timer` (`*/30`) before my session. **This job is the one place
where my instruction and another workstream's work overlap**, and the honest report is that theirs
is installed and running and mine is the same script at the same path — so the only thing I add is
the cron ledger row (§9 step 0 installs it; the duplicate is idempotent and harmless, and it is what
makes the run visible in `/root/.cron-status/runs.tsv`, which the brief's contract requires). Their
log shows the outbound path working:

```
2026-10-11T06:20:00Z {"key": "authority/secretary.db.gz", "bytes": 7234886331, "last_modified": "2026-10-10T05:20:09+00:00", "reported_at": "2026-10-11T06:20:00.293652+00:00", "reported_by": "secratary-cloud"}
2026-10-11T06:20:03Z reported to the vault
```

**And that number is the alarm that should be ringing: `last_modified 2026-10-10T05:20:09Z`.** At
the time of reading that object was **~25 hours old and climbing**. The offsite object in R2 is
still the *pre-cutover office snapshot*. The replacement (`authority-offsite-backup.sh`) was
mid-first-run when I lost access (`[2/5] company database (22609 MiB source) … page-stream | gzip -6
| multipart 64 MiB`). Until that run completes and writes `/var/lib/authority-backup/last-run`,
**the company's only surviving offsite copy is a database from before the cutover** — which is
precisely the silent-RPO-destroying failure §5 of the inventory describes, and it is the single
most important live fact in this report. It belongs to another workstream; I am reporting it, not
touching it.

### 2.3 Family 10 — the guards

#### `cron-target-guard` (L93) — **PORT-ADAPT, and the reason this family exists**

The inventory (§2 entry 32, register §4.6, doc 135 §decode) says it plainly: the office guard parsed
the **raw** crontab text, so for ~60 entries written as `cron-wrap.sh <name> <base64>` it resolved
every one of them to the single program `/usr/local/bin/cron-wrap.sh` — which always exists. Its own
evidence: **247 runs, 1 non-zero, while two crontab targets were genuinely absent for weeks.**

I rewrote it so that this cannot recur:

1. **every payload is decoded** — `cron-wrap.sh <name> <b64>`, and recursively, because a payload may
   itself be `base64 -d <<< '...'` or `/bin/sh -c '…'` (depth 4);
2. **`decode_stats` is reported on every run**, and printed even when the guard is clean:
   `decoded: N wrapped line(s), M command(s) resolved from a payload, K undecoded payload(s)`;
3. **a payload that will not decode is itself a finding** — `undecoded_payloads` makes the run
   fail, so "this guard cannot see what it is checking" can never look like "everything is fine";
4. `--crontab FILE` so the detector can be fired against a fixture rather than taken on trust;
5. `CRON_TARGETS_STATE` so the state directory is not hardcoded to one machine's home.

What it checks is unchanged and still right: the program a subcommand names (through `flock`,
`timeout`, `nice`, assignment prefixes and interpreters), the execute bit, CR bytes in a shell
script, the `crlf` case, and the `critical.txt` list of files **no** crontab names.

*Definition of done:* script ✅ · deps: `/usr/local/bin/cron-wrap.sh` ✅, `critical.txt` ✅ (19 paths)
· **first run with evidence ❌ — blocked** · cron ⏳ (`*/5`, `7 * * * *` in the office; I use `*/5`)
· what notices its failure: the ledger row and `guard-registry`.

#### `cron-script-guard` (L161) — **PORT-ADAPT, deployed, not yet run**

The honest half of the pair (its office log says `"cron_scripts_watched": 29, "present": 27, "ok":
false` … `ATTENTION: 2 cron script(s) need a real fix` — it is the guard that caught
`order-feed-refresh.sh` and `text-line-check.sh`). It already imports `base64` and decodes payloads;
the port fixes its three assumptions about the office box:

* **`$HOME` is no longer assumed.** It was `os.path.expanduser("~")` with a hand-written repo list
  (`~/personal-secretary-mvp`, `~/ceo-kernel`, …). On the cloud box the interesting trees are
  `/opt/company` and `/root/code/harness-config`, and its status lived at `$HOME/.cron-scripts`.
  Now: `CRON_SCRIPTS_HOME` / `CRON_SCRIPTS_STATUS`, and the repos are **discovered** by walking for
  `.git` (`CRON_SCRIPTS_REPO_ROOTS`, default `$HOME:$HOME/code:/opt:/srv`).
* **the payload check is an assertion, not a fallback.** The office `decode_wrapped()` returned the
  original line when decoding failed, so a decoding bug would look like a healthy run — the same
  blind spot as its sibling, one layer down. `payloads_decoded` / `undecoded_payloads` are now in
  the status file and `ok` is false when a payload did not decode.
* **`PATH_RE` is no longer anchored to `$HOME`** (it matched `$HOME/...\.(sh|py|mjs|js)`, which on
  the cloud box would have matched nothing at all).
* `--crontab FILE` again, for the same reason.

*Definition of done:* script ✅ · deps: the repos it walks exist ✅ · **first run ❌ — blocked** ·
cron ⏳ · what notices its failure: ledger row; and its status file is exactly what `guard-registry`
reads.

#### `guard-registry` (L130) — **PORT-ADAPT (office script installed as-is); NOT PROVEN**

Copied to `/usr/local/bin/guard-registry-check.py` unmodified; its `--ledger-db` default and its
pinned registry hash are things I could not test without running it, and the box is dark. It imports
`guards.yaml` from `~/.guard-registry/` (created, empty) — **this job is very likely to report
`unapproved`/`bad-entry` on first run because the registry and its pin are not on the cloud box.**
Stated as a gap rather than discovered later: §8.

#### `tree-integrity-check` (L90) — **PORT-ADAPT, deployed, DELIBERATELY IN DRY RUN**

The office `tree-integrity-check.sh` **texts the owner** (`OWNER_NOTIFY=+18483897895`,
`API=http://localhost:8002/sms/send`) when the deploy gate fails. Standing rule 4 in `AGENTS.md` and
the outbound-comms hard stop are unambiguous: **nothing outbound without a per-message yes in the
current conversation, and a standing alert template is not a per-message yes.** The script has a
`TREE_INTEGRITY_DRY_RUN=1` switch that logs what it *would* have sent. The cron line I staged uses
it:

```
*/30 * * * * cron-wrap.sh tree-integrity-check VFJFRV9JTlRFR1JJVFlfRFJZX1JVTj0xIC9iaW4vYmFzaCAvdXNyL2xvY2FsL2Jpbi90cmVlLWludGVncml0eS1jaGVjay5zaCA+L2Rldi9udWxsIDI+JjE=
  → TREE_INTEGRITY_DRY_RUN=1 /bin/bash /usr/local/bin/tree-integrity-check.sh >/dev/null 2>&1
```

So it **detects** and **does not send**, until the owner approves the exact alert body (one
question, §10). Its dependencies are satisfied: `REPO=/opt/company` ✅, `/opt/company/.venv/bin/python`
✅, `deploy-gate.py` ✅ (10,812 B), API `127.0.0.1:8002` ✅.

#### `store-write-check` (L159) — **DANGEROUS-ON-CLOUD → NOT PORTED AS-IS**

The inventory calls this a write probe against the company database, and it is: `CREATE TABLE IF NOT
EXISTS _write_check_scratch`, `INSERT`, `DROP`, every 5 minutes. On the cloud authority that is a
**second writer against `/root/authority.db`**, which rule 2 of the migration brief forbids in
absolute terms, and which `store-write-check.py`'s own header records as having been the cause of a
starvation incident (a reader snapshot holding the WAL writer off for hours).

**My decision: the job is ported, but not against the company database.** The staged cron line
points it at `/root/.store-write-check/scratch.db` — a scratch file it creates — so what it
establishes is *"the filesystem and block layer accept a write, fast, right now"*, which is a real
and useful condition (a read-only or full disk is exactly when nothing else notices), and it is
**not** a probe of the live store. The live store's writability is checked by the app's own writer:
`autopilot_state.json` advances every 900 s and the ledger is written through the API. I have
**not** built that second check; it is the residue of this job and it is in §8 as a named gap. This
is deliberately weaker than the office job and it is stated as such rather than dressed up.

#### `tmpfs-reaper` (L135) — **the inventory says DEAD-by-rationale; the measurement says otherwise**

The inventory's reason for calling this dead: *"office `/tmp` is a 12 GB tmpfs … nothing on the
cloud box has that defect."* That reading was never measured, and measuring it reverses it:

```
secratary-cloud: findmnt -no SOURCE,FSTYPE,SIZE,OPTIONS /tmp
  tmpfs tmpfs 3.8G  rw,nosuid,nodev,nr_inodes=1048576,inode64,usrquota
secratary-cloud: df -h /tmp
  tmpfs  3.8G  11M  3.8G  1% /tmp
```

**RAM-backed, 3.8 GB, and it carries `usrquota`** — the exact three properties whose combination
killed `phone-engine` twice on the office box (EDQUOT out of a synchronous write inside a socket
handler, `01:06:21Z` and `02:47:52Z`). It is 3.2× *smaller* than the office one, so it fills
sooner. The job is ported with the cloud's numbers: `MIN_FREE_MB=600`, `TARGET_FREE_MB=1500`,
`RESCUE_ROOT=/root/tmp-rescue`. It still **moves, never deletes**, skips dotfiles, skips anything
touched in the last 120 minutes, and skips anything a live process holds open.

*Not* ported: nothing. *Not proven:* the run (blocked).

#### `pain-check` (L111) — **DEAD, and left off**

`9 runs, 9 non-zero (100 %), rc=1` on the office box, with `JOURNAL=~/harness-config/journal/tools/journal.py`
and `CHECKS_DIR=~/bin/pain-checks`. It was already failing on the box that had the journal. Porting a
100 %-failing job to a box that has **no journal checkout yet** would manufacture a red row every
day and teach everyone to ignore the ledger — the exact failure `cron-wrap.sh`'s own header exists to
prevent. **Left off deliberately**, §8, with the reason: it needs the journal (which §6 is
establishing) *and* a diagnosis of why it fails, in that order.

#### `text-channel-check` (L127) — **DEAD, and left off**

`994 runs, 902 non-zero (91 %)`. It runs `text-health.py` (12 checks) and `test-owner-guard.py`
against the owner's SMS line — Twilio, `~/.sms-inbox`, the responder. On the cloud box at 06:39Z
none of that is running (no `sms-inbox`, no responder unit, no Twilio credential that I could
confirm). A check whose subject is absent does not "fail", it reports nonsense. **Left off**, and
its subject belongs to the owner-text workstream. §8.

### 2.4 Family 14 — `journal-commit`

The task asks me to decide where the canonical checkout is and make the job push somewhere real.
**Decision: the canonical checkout is `/root/code/harness-config` on the authority.** Reasoning:

1. The authority is the machine that is on when nothing else is (the brief's own framing), and the
   journal is the organ that makes continuity survive a laptop being shut. It belongs where the
   company's other authoritative state already moved.
2. The office copy is the **frozen rollback anchor** and is being retired; a journal whose durability
   depends on the machine being retired is not durable. It is also 1.6 GB of checkout + 1.26 GB of
   `.git` that is already 71 commits unpushed (doc 136 §5).
3. Nothing on the cloud box needs the whole checkout: the local `main` is shipped as a **git
   bundle** (`/root/hc-main.bundle`, 138.7 MB, already on the box) rather than a 1.26 GB clone, and
   the clone is `--local`.

**The push target — and the honest problem with it.** The office job's second half pushed to
`secretary-ts:/home/zabz/harness-config.git` (the office box). Taking that literally would make the
"backup" depend on the retired machine — so no. The three candidate remotes, measured:

| remote | reachable from the cloud box? | writable? |
|---|---|---|
| `https://github.com/lakewoodphone/harness-config.git` (the estate's configured `pushurl`, and the `offsite` remote in every checkout) | **yes** — `git ls-remote` returned `refs/heads/main f38366fc…` | **no** — no credential on the cloud box; nothing in my scope creates one |
| `secratary-ts:/home/zabz/harness-config.git` | **no** — the cloud box is logged out of tailscale (`tailscale status` → `Logged out`) and `getent hosts secratary.tail93e6e6.ts.net` is empty | moot |
| **`root@2.28.33.58:/srv/git/harness-config.git` (the VPS, `lpt-apps-01`)** | **yes** — the cloud box's own key reaches it (its `~/.ssh/config` is already written for it and the archive pull uses it) | **yes** — I hold the key |

So the job is built to **push to a real machine that is not the authority** — the VPS — with the
remote URL, the ref and the ssh identity all environment-overridable (`JOURNAL_REPO`,
`JOURNAL_REMOTE`, `JOURNAL_BRANCH`, `core.sshCommand`), and it **reads the remote's HEAD back
afterwards** and fails if it does not match, because "pushed" must be a measurement:

```
[pushed] <sha> published to root@2.28.33.58:/srv/git/harness-config.git main (remote HEAD read back and matches)
```

It commits `journal/` **only** — never `git add -A` (the 2026-09-17 incident swept 1,728 files into
one commit and its revert deleted 1,249 paths), never `--force`, never `reset`, never `rebase`,
never `stash`, and it never touches `main`'s history. It exits 0 when there is nothing to do.

**Two things I want on the record as unresolved.** (a) The VPS is at **94 % full, 4.8 GB free**
(`df -h /` on `lpt-apps-01`) — a 300 MB bare repo fits, but it is not a comfortable home and it is
the same host that holds the offsite vault and the restic repo; **GitHub is the right long-term
target and needs a deploy key the owner adds once** (§10). (b) The office box's `journal-commit`
(28 % non-zero, 284 failed runs of 1,003) is still installed there; on a frozen box with cron masked
it is inert, but when the office box is finally retired that line should be removed rather than
left as a second committer. §8.

*Definition of done:* script ✅ (new, cloud-specific) · dependencies: the bundle ✅, `git` 2.43.0 ✅,
the VPS key ✅, `/srv` writable ✅ · **first run ❌ — blocked** · cron `*/15` ⏳ · what notices its
failure: the ledger row, plus its own log at `/root/.harness-config-autosync/journal-commit.log`.

---

## 3. Coordination with the workstream that owns the offsite backup

I did not edit, move or rename `authority-offsite-backup.sh`, its unit or its timer; I read its
**outputs** as instructed:

* `/var/log/authority-offsite.log` at 06:26Z — `PUTOBJ key=authority/accounting.db.gz.sha256
  remote_bytes=83`, `[2/5] company database (22609 MiB source)`, `[send] db: /root/authority.db ->
  lpt-authority-backups/authority/secretary.db.gz`, `page-stream | gzip -6 | multipart 64 MiB (no
  intermediate file)`. **This design is right for this disk** (streamed, no second copy) and I say
  so rather than proposing a competing one.
* `/var/lib/authority-backup/last-run` **does not exist** (`ls` → "No such file or directory") and
  `/var/lib/authority-backup/` holds only `deployed-at` (0 B) and `running` (93 B). At the moment of
  the loss the first run was still in flight. **`authority-deadman.py`'s own body says
  `offsite=no-last-run(FileNotFoundError)`** — the dead-man switch is accurately reporting that the
  new offsite leg has not yet completed once.
* **What I would report to them as wrong, per the task:**
  1. **Nothing has written `last-run` yet**, so the only external freshness signal
     (`report-offsite-age` → the vault → the heartbeat) is still reading
     `last_modified 2026-10-10T05:20:09Z` — a **pre-cutover** object. Until the first successful run
     lands, the estate's offsite copy is the frozen office database and the RPO alarm is ~25 h and
     climbing. This is the highest-severity live finding in this report and it is not mine to fix.
  2. **`prune-backups` is not called by it.** The 2026-09-30 near-outage (disk 99 %, SQLite SIGBUS)
     happened because retention ran *after* a failed backup; the office script's caller
     (`backup-data.sh`) was fixed to run retention **first**. The cloud script streams and leaves no
     intermediate copy, so today there is nothing for retention to prune — but if it ever stages a
     file, nothing will clean it up. A `prune-backups.sh /var/lib/authority-snapshots` call before
     the stream is the cheap version of that guarantee, and my script is at the other end of the
     same policy.
  3. **The natural home for `db-integrity-check` is a hook in that script.** It already takes a
     consistent `.backup` and already runs `integrity_check` on the copy. A `PRAGMA quick_check` on
     the same copy, recorded into `/var/lib/authority-backup/last-run`, would give this box a real
     database-integrity signal with **zero extra disk** — where my standalone port cannot run at all
     until 31.6 GiB is free. That is one line in their script, which is why I am reporting it rather
     than writing it.

---

## 4. The cron contract, exactly as installed (staged)

12 jobs, `docs/mesh/134-work/cloud-crontab.txt`, every payload programmatically decoded and
compared to its intended command (**12 jobs, 0 mismatches**). Times are chosen around the one heavy
disk job on this box — `authority-offsite-backup.timer` at **05:20** — because there is one disk,
75 GB, and a 23.7 GB live database:

| time | job | why then |
|---|---|---|
| `*/5` | `cron-target-guard`, `cron-script-guard`, `store-write-check`, `deadman` | the estate's existing cadence; all are read-only or scratch-file only |
| `*/15` | `guard-registry`, `journal-commit`, `text-channel-check` | office cadence for the first two |
| `*/20` | `tmpfs-reaper` | office cadence |
| `*/30` | `tree-integrity-check`, `report-offsite-age` | office cadence |
| `45 5` | `prune-backups` | **after** the 05:20 backup finishes (~20 min measured), before anything else |
| `17 4 * * 0` | `db-integrity-check` | weekly, Sunday, as far from the backup as the day allows |

`deadman` and `report-offsite-age` are also driven by the offsite workstream's systemd timers. I
kept the cron entries because the brief's contract is that the *ledger* is
`/root/.cron-status/runs.tsv`; both jobs are idempotent (`report-offsite-age` overwrites one small
JSON on the vault; `authority-deadman.py` pings a switch whose whole purpose is being pinged), so the
duplication costs nothing and buys visibility. **Both mechanisms are named here so nobody has to
discover the doubling later.**

---

## 5. What would notice each job's failure

This is the honest column, and it is the weakest part of the port:

| job | what reads it | verdict |
|---|---|---|
| `deadman` | **healthchecks.io** (external, alarms on absence) | the only real monitor in this report |
| `report-offsite-age` | the **vault** `2.28.33.58:/var/lib/company-offsite/authority-push.json` + its own heartbeat | real |
| `db-integrity-check` | `/root/.db-integrity/status.json` — **read by nothing yet** | the office `guard-registry` is the intended reader and is not configured for the cloud |
| `cron-target-guard` | its own `guard.log`/`status.json`, read by `guard-registry` | indirect |
| `cron-script-guard` | same | indirect |
| `guard-registry` | **nothing** | gap |
| `prune-backups` | its log `/var/log/authority-backup-prune.log`, and the ledger | **nothing reads a deletion** — a prune that removes too much is silent by construction (office `disk-guard` was the pair; it is not mine and is not installed) |
| `tmpfs-reaper` | `/root/tmp-rescue/reaper.log` | nothing |
| `tree-integrity-check` | `/root/.tree-integrity/check.log` + a **suppressed** SMS | the suppression is deliberate; the log is read by nothing |
| `journal-commit` | the ledger + `/root/.harness-config-autosync/journal-commit.log` | indirect |
| every job | **`/root/.cron-status/runs.tsv`** — one row per run, rc and duration | the estate's own ledger; the reader is a consuming workstream, not this one |

`cron-wrap.sh`'s truncation rule (rewrite `runs.tsv` to its last 20,000 rows above 5 MB) means the
ledger is a window, not a history — worth knowing before anyone treats an absent row as proof.

---

## 6. Order of work the moment access returns

`docs/mesh/134-work/finish-134.sh` — **one paste, ~3 minutes, and every row of §2 that says "not
proven" becomes proven.** Steps, in the order that matters:

0. `crontab /root/crontab.candidate` (staged on the box) and `crontab -l` to show it;
1. `sha256sum /usr/local/bin/cron-wrap.sh` → expect `f7945803…76b10` (the byte-identity claim);
2. the dead-man switch through the wrapper, plus a **local witness** ping that measures whether *the
   authority* can reach healthchecks.io, plus the healthchecks.io API read-back of `last_ping`;
3. `prune-backups` refusing the anchor (`rc=3` expected), then a fixture dry-run *and* apply against
   `/var/lib/authority-snapshots`, then `df` before/after and a check that `/root/authority.db`
   and its `-wal` are untouched;
4. `db-integrity-check --selftest`, `--preflight-only --json` (the refusal, with numbers), and one
   real check against a **tiny** database to prove the pragma path end-to-end;
5. `cron-target-guard --selftest`, a live run, **and the same guard against a crontab with one
   deliberately dead target** (the proof that it can fail — the thing the office version could not
   do);
6. `cron-script-guard`, `guard-registry`, `tmpfs-reaper`, `tree-integrity-check` (dry run);
7. every job through the wrapper once, then `cat /root/.cron-status/runs.tsv`;
8. `df -h /`, `systemctl is-active company-api cloudflared secretary-dashboard phone-redirector`,
   and both HTTP doors — **before and after**, so it is on the record that this port did not disturb
   the company.

`docs/mesh/134-work/finish-journal.sh` — the canonical-checkout decision in §2.4, executed: clone
from the bundle, create the VPS bare repo, first push, run `journal-commit` deliberately, read the
remote's HEAD back, delete the bundle.

Then, and only then, `cp docs/mesh/134-PORT-GUARDS-BACKUP.md /root/out/migration-review/` with a
sha256 comparison at both ends — the other workstreams' pattern, and the last row of the brief's
definition of done.

---

## 7. NOT PORTED, AND WHY

| job | verdict | why |
|---|---|---|
| `store-write-check` against `secretary.db` | **refused** | a write probe against the company database is a second writer (brief rule 2). Ported at reduced strength (scratch file) and labelled as such. |
| `pain-check` | **DEAD, off** | 9/9 non-zero on a box that *had* a journal; the cloud box has none yet and the failure is undiagnosed. Enabling it manufactures a red row daily. |
| `text-channel-check` | **DEAD, off** | 902/994 non-zero; its subject (Twilio, the SMS inbox, the responder) is not running on the cloud box. Belongs to the owner-text workstream. |
| `disk-guard` | **not mine, not installed** | It is DANGEROUS-ON-CLOUD because it *invokes* the retention script; the fresh-workness workstream is porting it with `DISK_GUARD_INVOKE_RETENTION=0`. Named here because it is the missing reader for `prune-backups`. |
| `ai-gateway-health` | **not mine** | family 9 belongs to another workstream (it was ported and proven by them at 06:32Z). |
| the office box's `journal-commit` line | **left in place** | the office cron is masked/frozen so it is inert; removing it is part of office retirement, not this port. Recorded so it is not forgotten when the anchor is finally retired. |

## 8. COULD NOT VERIFY

1. **Everything that needed the authority after 06:39Z.** The crontab is not installed; no ported
   job has a ledger row. This is the whole of §2's "not proven" column and it is one paste away.
2. **The `cron-target-guard` fix on a real cloud crontab.** The decode logic is proven by selftest
   and the payloads by programmatic decode, but the guard has never been run against
   `crontab -l` on the box, because there is no crontab there yet.
3. **`guard-registry`** — unrun, and its registry/pin/ledger-db are almost certainly not yet right
   for the cloud box. It will very likely go red on first run; that is a finding, not a bug.
4. **`deadman`'s completeness** — I did not let the external switch lapse to confirm an alert
   arrives, and I did not re-arm the check's **name** (still "secratary authority alive", now
   watching a different machine). Both need the box.
5. **`db-integrity-check` against a real snapshot** — it refuses by design (31.6 GiB required,
   25.7 GiB free). The right fix is the hook in the offsite script (§3.3), which is another
   workstream's file.
6. **The VPS as the journal's push target** — the design is written and the paths are known, but no
   bare repo has been created and no push has been made, so "the journal leaves the authority" is a
   plan, not a measurement.
7. **Whether the office box still holds a copy of the cloud's `authorized_keys`** — a candidate
   recovery path I could not check, because reading `/home/zabz/.ssh/` there is cheap but the file I
   would restore is the *cloud's*, and the cloud is the machine I cannot reach.
8. **Who changed the cloud's `authorized_keys`.** I have the times (success at 06:39Z, refusal at
   06:40Z), four independent sibling reports of the same loss, and a verified list of what I wrote
   to the box. I do not have the responsible write. Saying so is the point.

## 9. The incident, and what it costs

Every workstream on this laptop that was porting onto the authority lost it inside a seven-minute
window. The estate's own document predicted the shape of this: *"SSH is by public IP and key only
and the key exists on one machine … Loss of that laptop is loss of the authority"*, and it was filed
as **CONFIDENCE: measured**. What it did not predict is that the key would be **replaced on the box**
rather than lost on the laptop.

Three things that should exist and do not (filed as journal pain **P3005**):

1. **A second authorized key on the authority**, held on a different machine (the office box, the
   VPS, or the desktop) — so one bad write, one conflicting deployment or one lost laptop is not the
   whole of the estate's access.
2. **A guard on `authorized_keys` itself.** This estate has a guard for nearly everything else; the
   file that is the single point of entry had no check at all. A `stat` of mode/owner/size plus a
   fingerprint comparison, filed as a `cron-target-guard` **critical path**, would have made the
   06:40Z change loud instead of silent.
3. **A rule that a deployment which rewrites `/root/.ssh/` is announced**, and that concurrent
   workstreams serialise around it. Nine sessions were writing `/usr/local/bin` at 06:34–06:39Z.

## 10. The one question this port needs from the owner

**Can you add the deploy key to GitHub so the journal has an off-site home that is not a nearly-full
VPS?**

*What it is for:* `journal-commit` every 15 minutes commits the journal on the authority. It needs a
remote that is (a) reachable from the cloud box, (b) writable, and (c) not the machine being retired.
The cloud box reaches GitHub and reads it, but has **no credential to push**. Today the job pushes to
the VPS at `2.28.33.58` (`/srv/git/harness-config.git`), which works but sits on a disk that is 94 %
full and shares a host with the offsite vault.

*The options:* (1, recommended) generate an SSH deploy key on the cloud box, you paste its public
half into `github.com/lakewoodphone/harness-config` → Settings → Deploy keys with **write** access —
about a minute, and it makes the journal's off-site copy GitHub's problem; (2) leave it on the VPS
and accept 4.8 GB of free space; (3) leave it as it is (nothing is pushed) and the journal is
committed on the authority but has no second machine — which the office job already demonstrated is
how 284 of 1,003 runs go red unnoticed.

*And separately, but it is the same conversation:* **the authority's SSH access needs a second key.**
Right now one file on one box is the whole estate's way in, and it was changed by something today.

---

## 11. Appendix — files in this port

| local path | what it is |
|---|---|
| `docs/mesh/134-PORT-GUARDS-BACKUP.md` | this report |
| `docs/mesh/134-work/cloud-crontab.txt` | the 12-job crontab, payload-validated |
| `docs/mesh/134-work/finish-134.sh` | the finishing/proof batch, one paste |
| `docs/mesh/134-work/finish-journal.sh` | the journal checkout + push batch |
| `docs/mesh/134-work/cloud-cron-target-guard.py` | base64-aware guard (deployed) |
| `docs/mesh/134-work/cloud-cron-script-guard.py` | ported guard (deployed) |
| `docs/mesh/134-work/cloud-db-integrity-check.py` | ported + free-space gate (deployed) |
| `docs/mesh/134-work/cloud-prune-backups.sh` | ported retention + allowlist + floor (deployed) |
| `docs/mesh/134-work/cloud-tmpfs-reaper.sh` | ported to the cloud's tmpfs numbers (deployed) |
| `docs/mesh/134-work/cloud-journal-commit.sh` | new cloud journal commit + publish + read-back |
| `docs/mesh/134-work/gen-crontab.py`, `check-crontab.py` | the payload generator and its verifier |
| `docs/mesh/134-work/cloud-access-watch.ps1` | the unattended access watchdog (see below) |
| `docs/mesh/134-work/INCIDENT-cloud-ssh-loss.md` | the access-loss record, with the sibling corroboration |

`cloud-access-watch.ps1` retries the authority every 90 s for ~50 minutes and writes
`cloud-access-watch.state`; it exists because the recovery must not depend on a human noticing.
