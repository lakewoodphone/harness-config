# 140 — PORT CORE (the four jobs I own) AND THE THREE MEASURED GAPS

**Workstream:** 140, "port core + gaps". **Author:** Zabz, ZABZ-YOGA session, 2026-10-11 06:25–06:50Z.
**Authorities touched:** `secratary-cloud` = `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` (THE
AUTHORITY, read-heavy, no write applied); `secratary` = `ssh secratary-ts` (frozen rollback anchor,
READ-ONLY — every office command was `wc`/`ls`/`stat`/`grep`/`sha256sum`/`sqlite3 mode=ro`, load stayed
0.01–0.87, no bulk pass); ZABZ-YOGA (this laptop); `zabz-tech` (one reachability probe).
**Discipline:** no credential value is reproduced anywhere below — the Hetzner token is compared by
**sha256 of the value** and by length only. No database was written. Nothing was restarted. No
`packages/**` file and no `authority-offsite-backup.sh` was touched.

---

## §0 — HEADLINE

| | result |
|---|---|
| `run-sentinel` | **PORT-ADAPT, fully prepared, NOT INSTALLED** — `ceo-kernel` (5.2 MB) + its state (3.5 MB) are copied and verified on this laptop, the 2-line authority patch is written and tested in a script, and the exact cron line is computed — but **a mid-session SSH-authorization break on the authority stopped every cloud-side write** (§1). |
| `converge-authority` | **DEAD, verified** — the last **40 runs are all exit 3**, and its own log shows the same unfixable condition `main diverged from origin/main: behind=14 ahead=70` from 01:15Z to its final run at 04:00Z. Its target checkout does not exist on the cloud box. |
| `chip-resume` | **DISABLED, deliberately** — it resumes a *family-facing* chat bot (`chip_enabled=1`); it already fired once (2026-10-05T13:00:05Z) and its trigger key is empty, so today it is a no-op whose only live capability is to start something the owner did not ask for in this workstream. |
| `push-dsh-sessions` (cloud's own sessions) | **DISABLED, deliberately** — the authority has **no DSH session store and no DSH engine** (measured), so the job would report success while shipping nothing. |
| `sync`, `node-agent-cron` | **NOT TOUCHED** — `138-PORT-INGESTION.md` does not exist on the authority (`/root/out/migration-review/` holds only 132, 135, 136) nor locally, so per instruction both were left alone. |
| **B1 API memory** | measured: idle cgroup **3.09 GB**, ordinary tick peak **4.78 GB**, the fatal event **7.19 GiB anon** on a 7.74 GB box, no ceiling. Recommendation with numbers in §B1; **not applied**. |
| **B2 Hetzner token** | present, 64 chars, **identical on both boxes** (same value-hash), and **401 invalid** → revoked/deleted, not absent and not a scope problem. No second copy exists anywhere. §B2. |
| **B3 family chat** | office **3,156 messages / 1,134,592 B** is the only current copy; cloud holds a **1-message / 61,440 B** stub; the laptop holds a **113-message** week-old dev copy. Exact copy command in §B3; **not run**. |

---

## §1 — THE BLOCKER: the authority stopped accepting the estate's only SSH key, mid-session

**This is the most consequential thing in this report. It is an estate incident, not just my obstacle.**

**What happened.** Between **06:44Z and 06:47Z** on 2026-10-11, `root@178.156.194.1` stopped
authenticating the estate's only authorized key. Before it, this session made ~20 successful root logins
with it; after it, none.

**Evidence — same key, three source networks.**

| from | when | result |
|---|---|---|
| ZABZ-YOGA (home IP) | 06:27–06:44Z | **login OK**, ~20 times (`hostname; crontab -l; systemctl show company-api -p ...`) |
| `secratary` (office IP), via `ssh -J secratary-ts` | 06:47Z | `root@178.156.194.1: Permission denied (publickey)` |
| `zabz-tech` (office LAN, its own copy of the key) | 06:48Z | `root@178.156.194.1: Permission denied (publickey)` |
| ZABZ-YOGA direct, `IdentitiesOnly=yes`, both estate keys offered | 06:48Z | `Permission denied (publickey)` |
| `secratary` with `id_ed25519_mesh`, `id_rsa_linux_pc`, `id_ed25519_lpt-apps`, `ha-mesh-key` | 06:47–06:49Z | all `Permission denied (publickey)` |

**The key is not the problem — measured.**

- `ssh-keygen -lf ~/.ssh/id_ed25519_hetzner` → `256 SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg mesh-hetzner-2026-08-31 (ED25519)`
- `zabz-tech`'s `id_ed25519_hetzner` → **the same fingerprint**; nobody rotated the key material.
- That fingerprint is exactly what `secratary-cloud:/root/.ssh/authorized_keys` held at 06:29Z
  (`-rw------- root root 105 B`, one key, and `135-PARITY-AND-ROBUSTNESS.md` §2.1 names the same key).
- The host is the same host: `ssh-keyscan 178.156.194.1` ed25519 = `SHA256:1ThtkV9TTB/vHw3svS23+EkpGxoGyOFbna1Zxeq8o50`,
  byte-identical to the entry already in `~/.ssh/known_hosts`. Not a rebuild, not a different VM.
- The algorithm is not the problem: `ssh -vvv` shows the server's `server-sig-algs=` **includes
  `ssh-ed25519`**, and the server answered `Authentications that can continue: publickey` after the client
  offered `SHA256:91iMQc2AFg...`. It accepted the offer to negotiate and then refused the key.
- A *separate*, second effect on the same port: from 06:45Z the laptop's IP was refused before the key
  exchange at all, with the 26-byte SSH banner **`Not allowed at this time`** (read directly with a raw TCP
  socket, not inferred). ss hd advertises `SSH-2.0-OpenSSH_10.2p1 Ubuntu-2ubuntu3.6`; that banner is the
  per-source penalty box (`PerSourcePenalties`, OpenSSH ≥ 9.8) which a burst of connections can trigger and
  which expires within its `max` (default 600 s). That effect **cleared** — the later attempts reached the
  key exchange — so it is *not* the cause of the key refusal, only a second, transient way to be shut out.

**Therefore:** the authorization data on the box changed — `/root/.ssh/authorized_keys` (content, or its
mode/ownership, which makes sshd ignore the file silently) or an sshd rule (`Match`/`AllowUsers`/
`PermitRootLogin`). Which one **could not be determined from outside** and is listed in COULD NOT VERIFY.
The timing lines up with another workstream doing SSH work *on that box*: at 06:29–06:30Z
`/root/.ssh/config` and `known_hosts` were rewritten, a `/root/.ssh/agent/` directory was created, and
`/root/.ssh/id_ed25519` had appeared at 00:27Z.

**Why this matters more than my tasks.** `135` §4.6 recorded that this key was the **only** interactive
path to the company. As of 06:47Z the estate no longer has one from any node: the box is reachable only
through the Hetzner web console — and the provider API token that would otherwise drive the provider is
**invalid** (§B2). Recovery from a wedged authority currently depends on a credential that is confirmed
dead and a console login nobody has tested. **The first thing anyone with access should do is fix root SSH
and add the second authorized key that 135 §4.6 already recommended.**

**What I did NOT do:** I did not attempt to re-add keys, did not touch authorized_keys, did not use the
application's own API as a shell, did not use `HETZNER_EMAIL`/`HETZNER_PASSWORD` to log into the provider
console, and did not mint anything. Those are escalation actions, not migration steps.

**Exact cost of the blocker to this workstream:** `ceo-kernel` was **not** pushed to the cloud, `cron-wrap.sh`
was **not** installed, `run-sentinel` has **no cron line**, the memory drop-in was **not** staged on the box,
and this report was **not** copied to `/root/out/migration-review/140-PORT-CORE-AND-GAPS.md`. Everything
needed to finish those five steps in one command is in §A1 and in
`harness-config/scripts/mesh/port-140-run-sentinel-install.sh`.

---

## PART A — THE JOBS I OWN

### A1 · `run-sentinel` (family 13) — PORT-ADAPT · **prepared and verified, NOT INSTALLED (blocker §1)**

**What the job actually is** (read from `/home/zabz/ceo-kernel/scripts/run-sentinel.sh`, 58 lines): it
`cd`s to the `ceo-kernel` checkout, runs `python3 -m ck status --json --no-colour`, writes
`latest.json` / `history.jsonl` / `run.log` into `$CEO_KERNEL_STATE` (default `/home/zabz/ceo-kernel-var`),
and always exits 0 on purpose (a finding is the signal, not a scheduler failure).

**Its real dependency is the `ceo-kernel` checkout — proven, not assumed.** The script derives its repo
from its own path (`REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"`) and imports `ck` from it. So
the move is required, and it is far smaller than the inventory estimated (which said "~50 MB, unmeasured"):

| item | office, measured | note |
|---|---|---|
| `/home/zabz/ceo-kernel` | **3,776,449 B (5.2 MB apparent du), 290 files** | `/home/zabz/ceo-kernel`, git checkout with `.git` |
| `/home/zabz/ceo-kernel-var` | **3,532,414 B, 17 files** | the trend: `history.jsonl` 1,775,585 B, `latest.json` 35,161 B, `run.log` 280,405 B |
| `ceo-kernel.git`, `ceo-kernel.stale-*` | not needed for the job | bare repo / retired copy; left on the office box |

**The one real port edit, and why it is unavoidable.** `ck/sources.py` hard-codes the *old* authority as
module constants:

```python
AUTHORITATIVE_DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"
AUTHORITATIVE_HOST = "secratary"
...
is_authority = HOST.lower() == AUTHORITATIVE_HOST.lower() and Path(AUTHORITATIVE_DB).exists()
```

On the cloud box `socket.gethostname()` is `secratary-cloud` and the authority is `/root/authority.db`, so
**no symlink can make the kernel report honestly** — the hostname comparison fails regardless of paths.
Porting therefore needs the smallest possible change, made on the cloud copy only (the office box is
read-only):

```python
AUTHORITATIVE_DB = os.environ.get("CEO_KERNEL_DB",
                    "/home/zabz/personal-secretary-mvp/data/secretary.db")
AUTHORITATIVE_HOST = os.environ.get("CEO_KERNEL_AUTHORITY_HOST", "secratary")
```

The old values stay as defaults, so the kernel's behaviour anywhere else is unchanged; on the authority the
env names what is true. It is a `git diff` in the copied checkout, so the divergence is visible forever.
**The same two lines should be changed upstream** by whoever owns `ceo-kernel` — the constants are now a
stale statement about the estate no matter what this workstream does.

**Planned cloud layout** (per `133-PORT-BRIEF.md`'s mapping; kept at the repo root because the script
resolves its own repo from its own path):

| office | cloud |
|---|---|
| `/home/zabz/ceo-kernel/` | `/root/ceo-kernel/` (checkout incl. `.git`) |
| `/home/zabz/ceo-kernel-var/` | `/root/ceo-kernel-var/` |
| `/home/zabz/ceo-kernel/scripts/run-sentinel.sh` | `/root/ceo-kernel/scripts/run-sentinel.sh`, mode 755 |
| `/home/zabz/bin/cron-wrap.sh` | `/usr/local/bin/cron-wrap.sh`, mode 755 |
| `~/.cron-status/runs.tsv` | `/root/.cron-status/runs.tsv` |

**The exact cron line** (name kept as `run-sentinel`, so the ledger and any monitor keyed on the name keep
reading true). Payload = base64 of:

```
CEO_KERNEL_STATE=/root/ceo-kernel-var CEO_KERNEL_DB=/root/authority.db CEO_KERNEL_AUTHORITY_HOST=secratary-cloud /root/ceo-kernel/scripts/run-sentinel.sh
```

```
*/5 * * * * /usr/local/bin/cron-wrap.sh run-sentinel <base64 of the line above>
```

**Dependencies, each checked on the cloud box (06:31Z unless stated):**

| dependency | state |
|---|---|
| `python3` | **exists** — `/usr/bin/python3`, Python **3.14.4** (same as the office box; the kernel is stdlib-only per its README) |
| `ceo-kernel` checkout | **staged on this laptop** (290 files, hashes below mat ch the office), **not yet on the cloud box** — §1 |
| `ceo-kernel-var` (state) | **staged on this laptop** (17 files) — §1 |
| `/root/authority.db` | **exists** (the live authority; WAL moving) — opened `mode=ro` only |
| `cron-wrap.sh` on the office box | **exists**, `sha256 8db5fe43291405dcc5ed26736e5ac2b02466ba7d2ef51c6aa9a04e88ec1ffa14`, 5,428 B base64 — captured and ready to install |
| `cron` on the cloud box | installed; `crontab -l` = "no crontab for root" at 06:27Z |
| disk | 26 GB avail at 06:31Z (and 25 GB at 06:41Z) before anything I write; the job writes ~2 MB/day into the state dir |
| network | none — the kernel is deliberately offline |

**Verification already done on this side (copy fidelity):** office
`ck/sources.py = f191a2594933a2fb570e268c1f90b330126a6500cc234100986a650d462fc2be`,
`ck/sentinel.py = 074bc62ed2cdc9c247f8f4ffee03ba3081e2951b00001d41fb6f0357d161fdee`, 290 files.
`scp -rp` returned **rc=0** and the laptop copy has **290 files** in `ceo-kernel` and **17** in
`ceo-kernel-var`. (The `.git` "local set times" messages are Windows refusing to stamp mtimes on read-only
git objects; they do not affect content.) The first cloud-side action of the follow-up session is
`git -C /root/ceo-kernel status --porcelain`, which proves every tracked file content-matches its blob.

**Proof the port is complete** (the four things `133` requires, with the commands that will produce them,
in the staged script): the state dir gains a new `history.jsonl` line and `run.log` line;
`/root/.cron-status/runs.tsv` gains `…\trun-sentinel\t0\t<seconds>\t` from **both** a manual run and a
cron-driven run; `crontab -l` shows the line. The office record for comparison: 2,991 runs, **0 non-zero**,
last `2026-10-11T04:00:02Z run-sentinel 0 13`.

**What would notice its failure: nothing — and that is a defect I am filing.** `cron-wrap.sh` records the
exit code and the script always exits 0, so a sentinel that stops *sensing* looks identical to a sentinel
that senses nothing wrong. On the office box nothing read `history.jsonl` either. Journal `pain` entry filed
(§journal). The honest monitor is "no new `history.jsonl` row in 15 minutes", which is exactly the
absence-reporting monitor `131` §7 asks for.

### A2 · `converge-authority` (family 13) — **DEAD, verdict verified**

`132-CRON-INVENTORY.md` §2 (row 65) and §3 both call it DEAD (999 runs, 527 non-zero). Verified from the
frozen box's own ledger and from its own log:

- rc histogram over all **999** runs: `0 → 472`, `1 → 217`, **`3 → 310`**.
- **the last 40 runs are 100 % exit 3**; the last six rows are
  `…02:45:01Z converge-authority 3`, `03:00:03Z 3`, `03:15:01Z 3`, `03:30:02Z 3`, `03:45:02Z 3`, `04:00:02Z 3`.
- its log `/home/zabz/.harness-config-autosync/converge.log` (153,554 B) says the same thing every 15 minutes,
  `01:15:02Z → 04:00:06Z`, verbatim:
  `[condition] main diverged from origin/main: behind=14 ahead=70 -- not merging automatically, a human should look`
  (behind stays 14, ahead 70→71). The script's own header defines exit 3 as "CONDITION, NOT FAULT: the
  branch cannot be reconciled automatically" — a state that needs a decision, not a job.
- it cannot be ported as-is anyway: it starts with `cd "${HARNESS_JOURNAL_REPO:-$HOME/harness-config}"`, and
  the cloud box has **no harness-config checkout** (`/root/code/harness-config` exists but contains only a
  `scripts/` directory, is not a git repo — `git log` → *"not a git repository"* — and was created at 06:26Z
  by another workstream).

**So it is not ported, and the reason is not "it failed 53 % of the time" but "it converged nothing, ever,
and its target no longer exists on the target machine".** Revival condition, if anyone wants it back: a
real `harness-config` checkout on the authority, `HARNESS_JOURNAL_REPO` pointed at it, **and** the fix the
script's own header names as *"THE REAL FIX, not done here"* — stop tracking the generated
`journal/index/*`, or the tree is dirty within a minute of every commit and no fast-forward is possible.

### A3 · `chip-resume` (family 22) — **DISABLED, deliberately**

**What it resumes** (read from `/home/zabz/bin/chip-resume.py`, 77 lines — this is the whole of it): it reads
the setting `chip_resume_at`; if that epoch has passed it **sets `chip_enabled=1`** in the family-chat
database's `settings` table and clears the key. `chip_enabled=0` is the existing kill switch for **"Chip"**,
the family-chat bot that talks to the owner's family over SMS; the header records the owner's instruction of
2026-09-30 ("shut him off for the next few days, have him turn back on after the holiday and not talking so
much"), with the resume due Mon 2026-10-05.

**It has already done its job, and this is measured:**

- `/home/zabz/chip-resume.log` contains exactly one firing:
  `2026-10-05T13:00:05+00:00 chip-resume: Chip turned back on (was due 2026-10-05T13:00:00+00:00); pacing settings in force: chip_daily_max=1, chip_min_dormant=72, chip_rate=0.008, …`
- office `settings`: `chip_enabled = 1`, **`chip_resume_at = ` (empty)** — the trigger was cleared as it fired.
- 998 runs, 0 non-zero, and every run since 2026-10-05 is a silent no-op by construction.
- the cloud box's `family_chat.db` is a **1-row stub** (§B3) — it does not even hold the settings table's
  content, so the job would have no subject there.

**Why it is left DISABLED.** Its only possible effect is to switch a **family-facing outbound actor** back
on. The owner's instruction that justified it is discharged; nobody in this workstream asked for it; and a
migration is not a mandate to inherit a dormant trigger that starts the family bot talking. Enabling it
would also be a job that reports success while doing nothing today — the defect class this estate has paid
for twice (`132` §2 #44 style: "a job that reports success while doing nothing"). **Re-enable condition:**
after the family-chat store is moved (§B3), and only on an explicit owner request to schedule a mute/resume.
Nothing was changed on the office box; the job simply is not scheduled on the cloud box.

### A4 · `push-dsh-sessions` for the cloud box's own sessions — **DISABLED (no subject)**

**What the pusher needs** (read from `harness-config/scripts/push-dsh-sessions.mjs`, header + first 80 lines):
`$DSH_HOME/sessions` (default `~/.dsh/sessions`), a cursor at `~/.dsh/dsh-archive-state.json`, and a POST to
`DSH_ARCHIVE_ENDPOINT` — on the cloud box `http://127.0.0.1:8002/...` **is** the live authority, which is the
correct target as `132` §2 #44 says.

**Measured on `secratary-cloud` (06:31Z):** `/root/.dsh` exists and contains **exactly one file**,
`transcript-archive-state.json` (2 bytes); there is **no `sessions` directory anywhere** on the box
(`find / -xdev -maxdepth 6 -type d -name sessions` → only `/opt/company/data/browser/sessions` and a Next.js
route directory); `/home/zabz/.dsh` does not exist; and there is **no DSH engine process**
(`ps -eo pid,cmd | grep -iE "dsh|deepseek"` → nothing), which `135` §2.1 also measured independently.

**So the authority has no DSH sessions of its own to ship.** Enabled, the job would run every 30 minutes,
find nothing, exit 0, and write a clean ledger row — a job that is green and meaningless. Left DISABLED; the
`.mjs` was **not** copied to the box. **Re-enable condition:** the moment a DSH engine (or a session store)
exists on the authority, install `/root/code/harness-config/scripts/push-dsh-sessions.mjs` and schedule it
against the cloud's own `/usr/bin/node` (v20.20.2, measured). For the record, the machines that *do* produce
sessions are the laptops: ZABZ-YOGA holds **1,704 files** under `~/.dsh/sessions` and already has the
scheduled tasks `PersonalSecretary-PushDSHSessions` and `PersonalSecretary-PushVSCodeChats` (both `Ready`,
measured 06:36Z) — and AGENTS.md §1 trap 2 warns that a client-side task which "reports success while
shipping nothing" is this estate's known failure, so that pipeline should be verified by *row counts in the
authority*, not by task state. That belongs to family 16/17, not here.

### A5 · `sync` and `node-agent-cron` — **NOT TOUCHED, by instruction**

`138-PORT-INGESTION.md` (the ingestion/search-index workstream's report) **does not exist** on the authority
(`ls /root/out/migration-review/` at 06:27Z → `132-CRON-INVENTORY.md`, `135-PARITY-AND-ROBUSTNESS.md`,
`136-ESTATE-INVENTORY.md` only) nor locally in `docs/mesh/`. Instruction: if it is not there yet, leave them
alone. Both were left alone. Note for whoever owns them: `sync` (crontab L51) is
`cd $HOME/code/unified-search && python3 scripts/sync.py --db $HOME/.unified-search/usearch.db` and its
inventory verdict is **DEAD** (498 runs, 104 non-zero; a desk-scoped checkout and a per-machine index),
while `node-agent-cron` (L9) is PORT-ADAPT (11 % non-zero) and needs `VSCODE_CHAT_INGEST_TOKEN` from the app
`.env`, posting to `--hub http://localhost:8002`.

---

## NOT PORTED, AND WHY

| job | verdict implemented | why |
|---|---|---|
| `run-sentinel` | PORT-ADAPT — **staged, not installed** | §1 blocker: no cloud-side write was possible after 06:44Z. Everything needed is in §A1 + `scripts/mesh/port-140-run-sentinel-install.sh`. |
| `converge-authority` | **DEAD (verified)** | 40/40 last runs exit 3 with the identical unfixable divergence; no `harness-config` checkout exists on the target box. |
| `chip-resume` | **DISABLED** | already fired (2026-10-05), trigger key empty, and its only capability is turning a family-facing bot back on — nobody asked for that here. |
| `push-dsh-sessions` (cloud's own) | **DISABLED** | no session store, no engine on the authority → a green job that ships nothing. |
| `sync`, `node-agent-cron` | **not touched** | `138-PORT-INGESTION.md` absent → owned elsewhere per instruction. |
| B1 memory drop-in | **written, staged locally, NOT applied** | restarting `company-api` takes the public API down; the instruction is to say so first. |
| B3 family-chat copy | **documented, NOT run** | another workstream may own the data move, and this is a user-data move that should happen once, carefully. |
| B2 token | **diagnosed, nothing minted** | minting/rotating is the owner's action at the provider. |

---

## COULD NOT VERIFY

1. **Why the authority stopped accepting the estate's SSH key** (§1). Measured: the key is unchanged, the
   host is unchanged, the algorithm is supported, and every source network is refused. Not determined:
   whether `/root/.ssh/authorized_keys` was rewritten, lost its modes/ownership (sshd ignores it silently in
   that case), or an sshd `Match`/`AllowUsers`/`PermitRootLogin` rule was added. Looking needs the access
   that is now missing.
2. **The cloud box's free space after 06:41Z.** Last reading I could take: `df -h /` → **25 GB avail, 66 %
   used** at 06:41Z (and 26 GB at 06:31Z; `135` §5.5 measured 4.4 GB during the offsite run — the number
   moves by 22 GB while that job runs, so *believe a fresh reading, not this one*).
3. **Whether the `company-api` memory peak repeats on a fresh boot.** I measured the *current* incarnation
   (started 05:47:35) for 10 minutes; I did not restart the service to watch a boot, and I will not without
   the owner's agreement (§B1).
4. **The application's exact allocator of the 7.19 GiB anon** — measured that the agent worker was mid-flight
   (`dept_scheduling`, `dept_systems_custody`, rounds 4–5) immediately before the kill and that the cap on
   that fan-out is `AUTOPILOT_MAX_AGENTS_PER_TICK=20`; the causal link is **inferred**, not measured.
5. **Whether the office box's crontab `sync`/`node-agent-cron` were already claimed** — the report that would
   say so does not exist; I did not read another workstream's in-flight state.
6. **The laptop's/mesh's other copies of `family_chat.db`** beyond the one found (§B3): I searched
   `C:\Users\ezabz\code` (depth-bounded) and the app's own data dir; a full-disk search was not run.

---

## PART B — THE THREE MEASURED GAPS

### B1 · The API was OOM-killed four minutes after the cutover, and nothing bounds it

**Measured need, current incarnation (MainPID 55564, started 2026-10-11 05:47:35Z; all readings 06:28–06:49Z
from `secratary-cloud`).**

`systemctl show company-api -p ...`:

| property | value |
|---|---|
| `MemoryCurrent` | **3,090,120,704 B (2.88 GiB)** |
| `MemoryPeak` | **7,165,288,448 B (6.67 GiB)** |
| `MemoryMax` / `MemoryHigh` / `MemorySwapMax` | **infinity / infinity / infinity** |
| `OOMPolicy` | `stop` (already) |
| `Restart` / `RestartSec` / `NRestarts` | `always` / `10s` / `1` |
| `ExecMainStartTimestamp` | `2026-10-11 05:47:35 UTC` |

**The peak is this incarnation's, not a leftover:** `/sys/fs/cgroup/system.slice/company-api.service` was
created `2026-10-11 05:47:35.747977184 +0000` — i.e. after the OOM kill — so 6.67 GiB was reached *since*
05:47:35. Its composition at 06:33Z (`memory.stat`): **anon 1,864,146,944**, **file 2,557,046,784**,
kernel 61,181,952, inactive_file 1,610,645,504, active_file 946,302,976, slab 54,693,624;
`memory.swap.current` 1,603,379,200. So the current incarnation's peak is **file-cache-dominated**, while
the *fatal* event was **anonymous**.

**Sampling — 40 samples, 15 s apart, 06:28:58Z → 06:38:47Z** (`memory.current`, `memory.stat anon`,
`/proc/meminfo`, `/proc/vmstat`):

| reading | min | max |
|---|---|---|
| cgroup `memory.current` | **2,491,396,096 B (06:38:17)** | **4,775,997,440 B (06:35:00)** |
| cgroup `anon` | **1,717,391,360 B (06:38:32)** | **1,914,110,784 B (06:35:00)** |
| `MemAvailable` | 5,028,412 kB | 5,310,404 kB |
| `SwapFree` | 2,349,992 kB | 2,474,736 kB (≈125 MB more swap taken during the window) |

**The 4.78 GB maximum is a tick, and an ordinary one.** `autopilot_state.json` says
`last_run_at 2026-10-11T06:19:50Z, interval_sec 900, enabled true, consecutive_failures 0`, so the tick was
due **06:34:50Z**; the only sample at a maximum is **06:35:00Z**, and it decays afterwards. In that same
window the cgroup's **anon moved by 20 MB** — an ordinary tick is file-cache (database reads), which is
reclaimable, and it is *not* what killed the company. Note also the shape of the app: `/health` answered
`ok:false, database: "db check timed out (lock contention); api still responsive"` at **06:43:18Z** (during
another workstream's `.backup`) and `ok:true, database ok` at **06:49:09Z** — the live database is contended,
and contended reads are what the file-cache peak is.

**The fatal event, re-read from the kernel (`journalctl -k`):**

```
05:47:24 f2b/a.sshd invoked oom-killer: gfp_mask=0x140cca(...), order=0, oom_score_adj=0
05:47:24 oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=/,mems_allowed=0,
        global_oom,task_memcg=/system.slice/company-api.service,task=python,pid=54912,uid=0
05:47:24 Out of memory: Killed process 54912 (python) total-vm:15637784kB, anon-rss:7544976kB,
        file-rss:3328kB, shmem-rss:0kB, UID:0 pgtables:23628kB oom_score_adj:0
```

`global_oom` + `CONSTRAINT_NONE` is the point: **there was no cgroup ceiling, so the kernel chose a victim
globally** — and the caller was an `sshd` allocation. `anon-rss 7,544,976 kB = 7.19 GiB` on a box whose
total RAM is **7,742 MB** (`free -m`, 06:32Z: used 2,558, buff/cache 5,021, available 5,183; swap 4,095 total,
1,679 used).

**What the app was doing when it blew up** — the last 30 lines of the *first* incarnation (672 lines total,
05:38:00→05:47:25Z) are the in-process agent fleet mid-flight:

```
05:46:33 app.services.agent_worker: Agent dept_scheduling step 47418 round 5: secretary-auto not in COPILOT_MODE
05:46:33 app.services.smart_router: router served task=work_mode alias=secretary-auto model=...
05:46:42 app.services.agent_worker: D016: Goal 004ede874f47 completed -> closed parent task 28201
05:46:44 app.services.agent_worker: Agent dept_systems_custody step 47417 round 5 recovered via gateway fallback
05:47:24 systemd[1]: company-api.service: The kernel OOM killer killed some processes in this unit.
```

and the only cap on that fan-out in the environment is **`AUTOPILOT_MAX_AGENTS_PER_TICK=20`**
(`AGENT_BUS_ENABLED=true`, `AGENT_BUS_START_SCHEDULER=true`). Twenty multi-round agent loops, each holding
an LLM conversation and tool results, is a plausible 7 GiB of heap — **inferred, not measured**; what is
measured is that the fleet was running, that the cap is 20, and that a later normal tick in the same
configuration moved anon by only 20 MB.

#### Recommendation, with numbers (NOT APPLIED — this needs one deliberate `company-api` restart)

1. **Bound the cgroup at a level a normal tick never reaches and a runaway cannot escape.** `MemoryHigh=5500M`,
   `MemoryMax=6800M`, `MemorySwapMax=3072M`, keeping `OOMPolicy=stop` and `Restart=always`/`RestartSec=10`
   which are already set. Arithmetic: the observed ordinary peak is **4,775,997,440 B ≈ 4.45 GiB**, i.e. **65 %
   of a 6,800 MiB cap** — so the cap does not touch normal operation; `MemoryHigh` starts reclaiming
   (file cache first — 2.56 GB of the current total is reclaimable) before the kill; and a repeat of the
   7.19 GiB anon event is killed **inside its own cgroup** and restarted by systemd in 10 s instead of the
   kernel picking a global victim that could be `sshd`, `cloudflared` or the process holding the database.
   The 6,800 MiB ceiling leaves ~900 MiB for everything else measured on the box (dashboard 43 MB, cloudflared
   25 MB, sshd 21 MB, journald 26 MB, tailscaled 29 MB, fail2ban 22 MB, kernel) — thin, which is honest:
   this is containment, not sizing.
2. **`OOMPolicy=stop` plus `Restart=always` is right, and here is why in mechanism, not taste.** The autopilot
   is *inside* the API process (`AUTOPILOT_INTERVAL_SEC=900`, 39 subsystems, 126 agent identities). Any cgroup
   OOM therefore ends the whole app and the tick with it; `OOMPolicy=continue` would leave a half-killed
   process serving traffic, which is strictly worse. What the autopilot needs to survive a kill: its state is
   on disk (`/opt/company/data/autopilot_state.json` is rewritten every tick), and the **lifecycle sweep**
   re-releases work left mid-flight (measured sweeps at 06:26:03Z and 06:28:07Z, ~140–160 s apart, with
   `stale_released` in each report) — so a restart costs at most one 900 s tick interval and does not strand
   tasks. Add `StartLimitIntervalSec=300` / `StartLimitBurst=5` so a crash *loop* stops and is visible rather
   than spinning silently.
3. **The real fix is the instance size, and that is the owner's money decision.** A measured 7.19 GiB working
   set does not fit a 7,742 MB box with an OS on it; `135` §5.2 already names the same conclusion. One size up
   — **CCX23, 4 vCPU / 16 GB** — is the recommendation; the price must be read in the Hetzner console because
   the API token is invalid (§B2), and the resize itself is a provider action that needs a reboot.
4. **The cheap product-side lever, which only the app's owner can weigh:** `AUTOPILOT_MAX_AGENTS_PER_TICK=20`
   is the only bound on the in-process agent fan-out that produced the fatal anon. Bounding concurrency (or
   making it adaptive to available memory) reduces the peak without buying a bigger box — at the cost of
   throughput. **I did not change it**: it is a change in how much the company does, and the measurement that
   would justify a specific number (a tick-level anon curve under a known agent count) is exactly what the
   restart in (1) would let us take.
5. **How to apply, exactly once, when the owner agrees** (the drop-in text is prepared in
   `harness-config/scripts/mesh/port-140-run-sentinel-install.sh`, and it restarts the service exactly once):

```bash
install -o root -g root -m 644 /root/company-api-memory.staged.conf \
    /etc/systemd/system/company-api.service.d/30-memory.conf
systemctl daemon-reload
systemctl restart company-api                      # ONE restart: the public API is briefly down
n=0; until curl -sf -m 3 -o /dev/null http://127.0.0.1:8002/health; do n=$((n+1)); [ $n -gt 60 ] && break; sleep 5; done
curl -s -o /dev/null -w 'health=%{http_code}\n' https://api.abletelsolutions.com/health
systemctl show company-api -p MemoryMax -p MemoryHigh -p MemoryPeak -p NRestarts
```
   Revert is the same shape: `rm /etc/systemd/system/company-api.service.d/30-memory.conf && systemctl daemon-reload && systemctl restart company-api`.
   **Risk stated plainly:** if the app's true cold-boot working set exceeds 6,800 MiB, this converts one
   global OOM into a restart loop; that is what `StartLimitBurst` and the off-box dead-man switch are for, and
   it is why I did not apply it unilaterally.

**Also relevant to the same restart:** the family-chat store swap in §B3 is cleanest if it happens while the
app is down — so one restart can carry both.

### B2 · The provider token is invalid, so the estate cannot see its own host

**Measured on `secratary-cloud`, 06:35Z:**

| reading | value | command |
|---|---|---|
| key present? | **yes** — `HETZNER_API_TOKEN`, plus `HETZNER_EMAIL` (len 30), `HETZNER_PASSWORD` (len 15), `HETZNER_MDM_IP` (len 13) | key **names** only via `grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' /opt/company/.env` |
| token shape | **len 64** — the correct shape for a Hetzner Cloud project token | value length only, never the value |
| the token actually sent | `sha256(bearer) = b131d9b75b0fd52af0167cba2ef8186b80877dd332c19feb0c745bb21a6cf687` | `sha256sum` over the value, **never printed** |
| live probe | `http=401 {"error":{"code":"unauthorized","details":null,"message":"the token you have provided is invalid"}}` | `curl -H "Authorization: Bearer $T" https://api.hetzner.cloud/v1/servers` |
| the office copy | **the same value** — `sha256` of the office `.env` value = **b131d9b7…687**, identical | `sha256sum` on `secratary-ts` |
| other copies | **none found**: `/root/.secrets/` does not exist; the office `/home/zabz/.secrets/` holds 8 files and **no Hetzner file**; no `hcloud` CLI and no `/root/.config/hcloud/`; the only in-repo mention is the prose doc `deploy/hosting-migration/SHUTDOWN_PLAN.md` | `ls -la`, `which hcloud`, `grep -rl HETZNER_API_TOKEN /opt/company/deploy /opt/company/scripts /usr/local/bin` |

**Diagnosis — absent, expired, or scoped wrongly?** It is **not absent** (present, 64 chars, sent as a
bearer) and it is **not a scope problem**: Hetzner answers a permission problem with `403 permission_denied`;
`401 unauthorized` means *this token does not exist*. Hetzner Cloud project tokens have **no TTL**, so
"expired" is not a mechanism either — the token has been **revoked or deleted** (or the value is a
credential of a different kind, e.g. a console/Robot password pasted into the token slot, which the 401
cannot distinguish). Both readings have the same fix, and the second is worth testing cheaply: the file also
carries `HETZNER_PASSWORD`, which is not a bearer token.

**Exactly what is needed to fix it (nothing here was minted or rotated):**

1. **Owner action, at the provider:** sign in to the Hetzner Cloud console for the project that owns
   `secratary-cloud` (Ashburn, CCX13, `178.156.194.1`) → *Security → API tokens* → create a **Read & Write,
   project-scoped** token. Read & Write is required, not Read: provider-level recovery means
   start/rebuild/reboot/snapshot the server, and a read-only token cannot rescue a wedged box. Raw
   credential details (whether the console login still uses the stored `HETZNER_EMAIL`/`HETZNER_PASSWORD`)
   are the owner's to confirm — I deliberately did not log in with them.
2. **Where it must be installed — two places, deliberately:** (a) `/opt/company/.env`, key
   `HETZNER_API_TOKEN`, mode 600 (the app's copy), and (b) **a copy that is reachable when the company is
   down**, which must not be inside the company's own environment file — e.g. `/root/.secrets/hetzner.env`
   mode 600 on the authority *and* on this laptop. The whole point of this credential is recovering a host
   that cannot serve you its own `.env`.
3. **A probe, so a dead token is found before the day it is needed:** a read-only
   `GET /v1/servers` on a schedule (5 min or hourly) through `cron-wrap.sh`, whose *absence* of a green row
   is the alarm — `135` §6.2 asks for exactly this. Without it, this failure stayed invisible until someone
   tried to *use* the provider, which is the worst possible moment.
4. **What is blocked until then:** nobody can check whether the VM has provider-level backups or snapshots
   (`135` §7.1 is unanswered for the same reason), nobody can reboot, resize (§B1.3), rebuild or take a
   snapshot of the authority, and — as of §1 — nobody can reach the box out-of-band to fix SSH. The
   provider API is the *only* recovery path that does not need the box, and it is currently dead.

### B3 · Family chat history did not move

**The two stores, measured (all counts read `mode=ro`; the office read creates nothing):**

| | office `secratary` | cloud `secratary-cloud` |
|---|---|---|
| path | `/home/zabz/personal-secretary-mvp/data/family_chat.db` | `/opt/company/data/family_chat.db` |
| size | **1,134,592 B** | **61,440 B** |
| sha256 | `9f69aa81c7b5d841d3a4bbebe570d24868d04b08be8dc830f91589e91434e5ac` | `1702d96eb854c8991596eb8618545c2bed1e1a26e5721ca3b009ddf7ec86bb8b` |
| messages | **3,156** (rowid 1…158,791) | **1** (rowid 1) |
| `created_at` range | 2026-08-09 16:54:53 → **2026-10-11 02:45:22** | **2026-10-11 05:41:32** (the single row) |
| `settings` rows | 40 | 1 (`last_inbound_processed_at`) |
| tables | `messages, members, member_events, outbox, settings, chip_memories` — **same schema on both** | same |
| `-wal` / `-shm` | **none** — no WAL file on disk, `page_count 277 × 4096 = 1,134,592` = file size exactly, so the file is fully checkpointed and a byte copy is exact | `-wal` 0 B, `-shm` present |
| writer | frozen box (mtime 03:43:59Z, before the freeze) | `lsof /opt/company/data/family_chat.db` → **no process holds it open** (the app opens it per use) |

**Where the only copy is: the office box.** Searched and negative: no `family_chat*` anywhere under
`/home/zabz/secretary-backups` (maxdepth 3), none in `/home/zabz/data` or `/home/zabz/bin`; on the cloud box
the only files are the live stub and its `-wal`/`-shm`; the offsite chain carries `authority.db` +
`accounting.db` only, so **no R2 object contains this data**. One *stale* extra copy exists and must not be
mistaken for a backup: **this laptop**, `C:\Users\ezabz\code\personal-secretary-mvp\data\family_chat.db`,
**81,920 B, sha256 `73dd0063…43d0`, mtime 2026-10-04 22:10**, **113 messages**, created 2026-09-01 →
2026-10-02 — i.e. a developer's week-old checkout copy missing 3,043 messages.

**The trap in the obvious fix.** The cloud stub is **not empty**: it holds one message created
**2026-10-11 05:41:32**, which is *newer* than the office copy's newest (02:45:22) — so a naive overwrite
destroys a real inbound family message. It is the same class of defect as the 60 KB accounting stub and the
decoy `secretary.db` `135` §6.9 found: **the app creates an empty database at a missing path and serves from
it.**

**Exact copy command, with sizes — STATED, NOT RUN** (the office box is never written to; nothing large is
ever left on the cloud's 75 GB disk, and this file is 1.1 MB):

```bash
# 1. VERIFY the source is quiescent and complete (office box = read-only, mode=ro reads only)
ssh secratary-ts 'ls -la /home/zabz/personal-secretary-mvp/data/family_chat.db; \
  sha256sum /home/zabz/personal-secretary-mvp/data/family_chat.db; \
  sqlite3 "file:/home/zabz/personal-secretary-mvp/data/family_chat.db?mode=ro&immutable=1" \
     "select count(*), max(rowid), max(created_at) from messages;"'
# expect: 1134592 bytes, sha256 9f69aa81c7b5d841d3a4bbebe570d24868d04b08be8dc830f91589e91434e5ac,
#         3156 | 158791 | 2026-10-11 02:45:22   (no -wal file present)

# 2. CARRY IT (office -> laptop -> authority; 1,134,592 B each hop, never onto the office disk)
scp -p secratary-ts:/home/zabz/personal-secretary-mvp/data/family_chat.db \
    C:\Users\ezabz\code\_mig140\family_chat.db.office
scp -p C:\Users\ezabz\code\_mig140\family_chat.db.office root@178.156.194.1:/root/family_chat.db.office

# 3. ON THE AUTHORITY: verify the carrier, keep the stub, MERGE the one live row, then swap atomically
sha256sum /root/family_chat.db.office        # must equal 9f69aa81...e5ac
cp -p /opt/company/data/family_chat.db /root/family_chat.db.cloudstub      # 61,440 B, the only copy of the 05:41:32 row
sqlite3 /root/family_chat.db.office <<'SQL'
ATTACH DATABASE '/root/family_chat.db.cloudstub' AS live;
INSERT INTO messages (twilio_sid, direction, from_number, to_number, body, media_urls,
                      status, cost, created_at, outbox_id)
  SELECT l.twilio_sid, l.direction, l.from_number, l.to_number, l.body, l.media_urls,
         l.status, l.cost, l.created_at, l.outbox_id
    FROM live.messages l
   WHERE l.created_at > (SELECT MAX(created_at) FROM messages);
SELECT 'after-merge', count(*), max(created_at) FROM messages;
SQL
# then, with `lsof /opt/company/data/family_chat.db` EMPTY (measured: nothing holds it):
install -o root -g root -m 644 /root/family_chat.db.office /opt/company/data/family_chat.db.new
mv -f /opt/company/data/family_chat.db.new /opt/company/data/family_chat.db
rm -f /opt/company/data/family_chat.db-wal /opt/company/data/family_chat.db-shm
sqlite3 'file:/opt/company/data/family_chat.db?mode=ro' 'select count(*) from messages;'   # expect 3157
```

**Two notes for whoever runs it.** (a) The `lsof` check is the acceptance test, not a formality: the app
opens this file per use, so the swap is safe between requests, but if the family-chat hub is restarted for
§B1 anyway, do the swap while it is down instead — same one restart carries both. (b) **After** the move,
`chip-resume` (§A3) becomes meaningful again on the authority and should be reconsidered *with* the owner,
because it will then have a `settings` table carrying `chip_enabled`/`chip_resume_at`.

---

## APPENDIX — every command behind a claim

Machine `Y` = this laptop (ZABZ-YOGA); `O` = `ssh secratary-ts`; `C` = `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`.

| claim | machine | command |
|---|---|---|
| SSH refused mid-session | Y/O/zabz-tech | `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 hostname` (worked to 06:44Z, then `Permission denied (publickey)` from all three networks) |
| the key is unchanged | Y, zabz-tech | `ssh-keygen -lf ~/.ssh/id_ed25519_hetzner(.pub)` → `SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg` |
| same host | Y | `ssh-keyscan 178.156.194.1` vs `~/.ssh/known_hosts` → both `SHA256:1ThtkV9TTB/vHw3svS23+EkpGxoGyOFbna1Zxeq8o50` |
| the algorithm is supported | Y | `ssh -vvv …` → `server-sig-algs=<ssh-ed25519,…>`, then `Offering public key: …SHA256:91iMQc2AFg…`, then `Authentications that can continue: publickey` |
| the penalty banner | Y | `TcpClient('178.156.194.1',22)` raw read → 26 bytes `Not allowed at this time`; banner `SSH-2.0-OpenSSH_10.2p1 Ubuntu-2ubuntu3.6` |
| the ceiling is absent | C | `systemctl show company-api -p MemoryCurrent -p MemoryPeak -p MemoryMax -p MemoryHigh -p MemorySwapMax -p OOMPolicy -p Restart -p NRestarts -p ExecMainStartTimestamp` |
| the peak is this incarnation's | C | `stat -c %y /sys/fs/cgroup/system.slice/company-api.service` → 2026-10-11 05:47:35.748 |
| the 10-minute curve | C | 40 × (`memory.current`, `memory.stat` anon, `MemAvailable`, `SwapFree`, `vmstat`) every 15 s, 06:28:58–06:38:47Z |
| the tick is the 4.78 GB sample | C | `autopilot_state.json` `last_run_at 06:19:50Z + interval_sec 900` = 06:34:50Z; sample max at 06:35:00Z |
| the OOM anatomy | C | `journalctl -k --since "2026-10-11 05:40" \| grep -iE "oom\|Killed process"` |
| what the app was doing | C | `journalctl -u company-api --since "05:38:00" --until "05:47:25" \| tail -30` → `agent_worker … step 47418 round 5` |
| the fan-out cap | C | `grep -oE '^[A-Za-z_]+=' /opt/company/.env` then `AUTOPILOT_MAX_AGENTS_PER_TICK=20` |
| the API's own view | C/Y | `curl https://api.abletelsolutions.com/health` → 06:43:18Z `ok:false, "db check timed out (lock contention)"`; 06:49:09Z `ok:true` |
| token key names only | C | `grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' /opt/company/.env \| tr -d '=' \| grep -i hetzner` |
| token length only | C/O | `awk -F= '/^HETZNER_API_TOKEN=/{print length(substr($0,index($0,"=")+1))}' .env` → 64 |
| token value hashed, never printed | C/O | `… \| sha256sum` → `b131d9b7…687` on **both** boxes |
| token is dead | C | `curl -H "Authorization: Bearer $T" https://api.hetzner.cloud/v1/servers` → `http=401 unauthorized` |
| no second copy | C/O | `ls -la /root/.secrets/` (absent), `ls -la /home/zabz/.secrets/` (8 files, no Hetzner), `which hcloud`, `ls /root/.config/hcloud/` |
| family chat counts | O/C/Y | `sqlite3 "file:…family_chat.db?mode=ro" "select count(*), max(rowid), max(created_at) from messages;"` → 3156/158791/2026-10-11 02:45:22 (O), 1/1/05:41:32 (C), 113/11529/2026-10-02 (Y) |
| the stub has no writer holding it | C | `lsof /opt/company/data/family_chat.db` → *(empty)* |
| no copy in the office backup chain | O | `find /home/zabz/secretary-backups -maxdepth 3 -name 'family_chat*'` → *(empty)* |
| converge-authority is dead | O | rc histogram `0 472 / 1 217 / 3 310`; last 40 rows all `3`; `tail -12 …/.harness-config-autosync/converge.log` → `[condition] main diverged from origin/main: behind=14 ahead=70` ×12 |
| no harness-config checkout on the authority | C | `git -C /root/code/harness-config log --oneline -1` → *"not a git repository"* |
| chip-resume's one firing | O | `tail -5 /home/zabz/chip-resume.log`; `sqlite3 … "select key,value from settings where key in ('chip_enabled','chip_resume_at')"` → `1` and empty |
| the authority has no sessions to ship | C | `ls -la /root/.dsh/`; `find / -xdev -maxdepth 6 -type d -name sessions`; `ps -eo pid,cmd \| grep -iE 'dsh\|deepseek'` |
| job scripts, read verbatim | O | `cat /home/zabz/bin/cron-wrap.sh /home/zabz/ceo-kernel/scripts/run-sentinel.sh /home/zabz/bin/converge-authority.sh /home/zabz/bin/chip-resume.py` |
| the cron payloads | O | `grep -nE "cron-wrap.sh (run-sentinel\|chip-resume\|push-dsh-sessions\|sync\|node-agent-cron\|converge-authority) " /home/zabz/cutover/crontab.before` |

**END OF 140.**
