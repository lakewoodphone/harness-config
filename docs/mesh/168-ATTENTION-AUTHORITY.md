# 168 — the findings were being computed on the frozen box: the sentinel's move to the authority

**Workstream:** 168, "attention authority". **Author:** Zabz, ZABZ-YOGA session, 2026-10-12 03:0x–04:0xZ.
**Opened from the owner's own question** — *"Why does it say stale? We migrated from the office
secretary to the cloud secretary … Why is everything stable? What's going on?"* — and it is a direct
consequence of the 2026-10-11T05:43:36Z authority cutover (`131-MIGRATION-BRIEF.md`).

**Authorities touched, and how.** `secratary-cloud` (THE AUTHORITY, **writable**, read-write only into
`/root/ceo-kernel*`, `/root/.cron-status/`, the root crontab and `/usr/local/assets/`); `secratary`
(office box, **FROZEN rollback anchor**, READ-ONLY: every command there was `ls`/`stat`/`cat`/`tail`/
`grep`/`sha256sum` — no service state changed, nothing written); ZABZ-YOGA (this laptop, the
harness-config checkout). Nothing was restarted anywhere. `company-api` was not touched.

---

## §0 — HEADLINE

| | |
|---|---|
| **symptom** | every badge in the fleet read `6 needing attention · stale 6h ago`, and the age grew forever. The owner asked whether the company had gone quiet. |
| **root cause** | the badge's findings are produced by the `ceo-kernel` sentinel, which **only ever ran on the office box** — now a frozen anchor whose last write was `2026-10-11T20:20:06Z`. The authority had the database, the API, the dashboard and the gate, and no sentinel. The badge was rendering a stopped clock, correctly labelled. |
| **second defect** | `BADGE_AUTHORITY` was a **hardcoded hostname in a client bundle**. Even with a live authority, every already-mounted machine would keep asking the frozen box for up to a year. |
| **fix** | sentinel ported to the authority and scheduled every 5 min; the gate needed **no restart**; the badge's data origin became a **list** with freshest-wins; the fixed badge asset deployed to both of the authority's asset paths. |
| **verified** | the authority now serves `read:true, host:secratary-cloud, age 0.3 s`; `node scripts/verify-badge.js` **181/181**; a real cron-path run wrote a ledger row (`run-sentinel 0 9`). |
| **the first live report was worse than the frozen one** | it named `db_writable` (HIGH — "the authoritative database refuses writes: database is locked", reproduced 4/4) and `web_currency_math` (HIGH — money typeset as LaTeX on the phone), and it dropped `config_sync` and `session_archive`, which had been artifacts of the frozen box. |
| **not closed** | no alarm on the sentinel's own death; 3 of 19 checks blind on the authority (exit 2 = "cannot see"); the kernel repo's canonical copy is still a bare repo on the frozen box. All three are named in §6. |

---

## §1 — What was actually true, measured

| question | reading | command |
|---|---|---|
| who serves the badge? | `secratary.tail93e6e6.ts.net` → **100.84.72.88 = the office box** | `tailscale status`; `curl -w '%{remote_ip}'` |
| when did it last compute anything? | `latest.json` mtime `2026-10-11T20:20:06Z`, `host: secratary`, `summary {total 19, attention 6, ok 13, unknown **0**}`; `run.log` ends `20:20:06 exit=1` | `ls -l --time-style=full-iso`; `tail run.log` |
| why did it stop? | `cron` is `masked` + `inactive` — the box was frozen at the cutover, and that 20:20 write is inside the accidental **19:04–20:26Z unfreeze window** of 2026-10-11 (`AGENTS.md` §5, `142-ANCHOR-WRITE-NOTICE.md`) | `systemctl is-enabled cron` → `masked` |
| was anything else being asked? | yes: the office gate was still serving `/dsh-attention.json` to `zabz-yoga-1` (the owner's own browser) every 60 s, and had answered **115,737** such requests | office `~/.dsh-phone/gate.log` |
| did the authority have a sentinel? | **no.** `ls /root/ceo-kernel*` → nothing; no `run-sentinel` line in the root crontab. The port had been prepared on 2026-10-11 and **never installed** (`140-PORT-CORE-AND-GAPS.md` §A1, blocked mid-session by an SSH refusal) | cloud `crontab -l`, `ls` |
| could it have? | yes, and the gate was already wired for it: `BADGE_STATE = $HOME/ceo-kernel-var/latest.json` and the gate runs as root, so `/root/ceo-kernel-var/latest.json` is the *default* path. It answered `{"read": false, "error": "cannot read /root/ceo-kernel-var/latest.json: No such file or directory"}` | `curl https://secratary-cloud…/dsh-attention.json` |
| was the office box healthy? | yes — that is the point. `cron` masked **by decision**, `phone-engine.service` masked, load 0.00. Nothing was broken; the job had moved house and left its alarm clock. | `systemctl list-units --state=running` |

**One correction worth keeping.** `2001` bytes (this laptop's `curl`) versus `2199` bytes (the gate's
own log line) for the same payload is **not** a size change: the gate logs `len(whole HTTP response)`
and `curl` reports `Content-Length`, so the 198-byte difference is the status line and headers. Two
numbers that disagree are not automatically two different things.

## §2 — The port, exactly

**Where it lives now** (the layout `133-PORT-BRIEF.md` planned, kept because `run-sentinel.sh` resolves
its own repo from its own path):

| office | authority |
|---|---|
| `/home/zabz/ceo-kernel/` | `/root/ceo-kernel/` (git checkout, HEAD `7be7fde`, `git status --porcelain` empty at clone) |
| `/home/zabz/ceo-kernel-var/` | `/root/ceo-kernel-var/` (seeded from the frozen box for trend continuity; `history.jsonl` keeps its 3,007 prior rows plus a one-line move marker) |
| `/home/zabz/bin/cron-wrap.sh` | `/usr/local/bin/cron-wrap.sh` (already present — the authority has 48 wrapped jobs) |

**The one code change, and it is in the kernel's repo, not this one.** `ck/sources.py` hardcoded the
old authority, so **no symlink could have made the kernel report honestly** — `socket.gethostname()`
on the authority is `secratary-cloud`, and the comparison against `"secratary"` fails regardless of
paths:

```diff
-AUTHORITATIVE_DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"
-AUTHORITATIVE_HOST = "secratary"
+AUTHORITATIVE_DB = os.environ.get("CEO_KERNEL_DB",
+                    "/home/zabz/personal-secretary-mvp/data/secretary.db")
+AUTHORITATIVE_HOST = os.environ.get("CEO_KERNEL_AUTHORITY_HOST", "secratary")
```

The defaults are the old values, so behaviour anywhere else is unchanged; on the authority the
environment names what is true. `git diff --stat` on the authority: `ck/sources.py | 5 +++--`.

**The schedule** (name unchanged, so any monitor or ledger keyed on `run-sentinel` keeps reading
true). Cadence came from the measurement, not from taste — the first run took **15 s**, so `*/5` rather
than the `*/15` a slow run would have forced:

```
*/5 * * * * /usr/local/bin/cron-wrap.sh run-sentinel <base64 of:>
  CEO_KERNEL_STATE=/root/ceo-kernel-var CEO_KERNEL_DB=/root/authority.db
  CEO_KERNEL_AUTHORITY_HOST=secratary-cloud nice -n 10 /root/ceo-kernel/scripts/run-sentinel.sh
```

`nice -n 10` is deliberate: this is a monitoring job on a 2-vCPU box that has OOM-killed the company
API once, and it must lose every race with the company. The root crontab was backed up to
`/root/crontab.before-sentinel-port-20261012T031536Z` (53 lines) before the one line was added.

**Recovery, if this is ever re-done or reverted.** The idempotent install script is
`_mig140/port-kernel-to-cloud.sh` in the session's staging directory, and the bundle it needs
(`kernel.bundle`, 137,884 B, created with `git bundle create --all` from HEAD `7be7fde`) plus the
seeded state are on the authority at `/root/`. Reverting is: `crontab -l | grep -v run-sentinel |
crontab -`, restore `/root/crontab.before-sentinel-port-*.`, and leave the state dir in place (it is
harmless and it is the record).

## §3 — Why the gate needed no restart, and why that mattered

`phone-gate.py` resolves its findings from `os.environ.get("CEO_KERNEL_STATE", str(Path.home() /
"ceo-kernel-var"))`. The unit runs as root with `HOME=/root`, so the default path **is**
`/root/ceo-kernel-var/latest.json` — exactly where the port put the state. The port therefore made a
live badge appear without touching a running service. Measured immediately after the first run:

```
$ curl -s http://127.0.0.1:3086/dsh-attention.json | head -c 120
{"read": true, "at": "2026-10-12T03:15:45.224159+00:00", "host": "secratary-cloud", "total": 19, …
gate read=True age_seconds=0.3 host=secratary-cloud total=19 attention=6
```

The generalisable note: **the accessor's default is the contract.** Had the gate required an explicit
`CEO_KERNEL_STATE`, this would have been a service change on the authority and a decision rather than
a port.

## §4 — The badge's second defect: a hostname in a client bundle

`packages/plugin-attention-badge/lib/client.js` carried
`const BADGE_AUTHORITY = 'https://secratary.tail93e6e6.ts.net'`. Client bundles are served
**immutable**, so a mounted machine caches its copy for a year: after any authority move, a machine
that was already loaded asks the wrong host with no error anywhere, forever. Tonight it was visible
only because the frozen box was *still answering* — with a stale reading that the badge honestly
labelled `stale`.

The fix is a **list** (`BADGE_AUTHORITIES`, authority first, the frozen box only as a stand-in) plus a
badge that asks the candidates in order and keeps the **freshest readable reading**, keeping a stale
one only if nothing fresher answers — still labelled, still naming its host. The whole point is that
a frozen source can never *shadow* a live one, and a stale reading is never presented as current.

Verified with the repo's own contract test, extended for exactly this scenario:
`node scripts/verify-badge.js` → **181/181** (was 163), including frozen-first/live-second, a refusal
falling through to the next source, an unreachable source, all-sources-stale, and nothing-declared.
`python scripts/verify-badge-gate.py` → **55/55**.

**Deployed to both asset paths**, because `resolve_asset()` searches `/usr/local/assets/` *before* the
checkout and the two had already diverged in intent if not in bytes:
`/usr/local/assets/phone-badge.js` and `/root/code/harness-config/assets/phone-badge.js`, each with a
`*.pre-multisource-<stamp>` backup. The gate caches the script on `(mtime, size)`, so the new bytes are
served on the next request — measured: served sha256 `46fb7f1f…`, `var VERSION = '4'`.

## §5 — What the live authority said, which the frozen one could not

| check | frozen box (20:20Z, reading a frozen DB) | authority (live) |
|---|---|---|
| `agent_dead_weight` | HIGH | HIGH — `frontier_risk_board`, 30 ticks, 0 completions |
| `attention_debt` | HIGH | HIGH — 7 held, oldest 8d, none urgent |
| `owner_queue` | HIGH | HIGH — 159 waiting, 6 deferrals expired, next **#228** (blocking, 10.5d) |
| `model_lane_health` | HIGH — `deepseek-ai/DeepSeek-V4-Flash-0731` 0/181 | HIGH — 4 dead-and-selectable lanes; worst 0/24, and the recorded error is **`http_402: You need positive balance`** |
| `db_writable` | *absent* | **HIGH — "the authoritative database refuses writes: database is locked"** (`BEGIN IMMEDIATE`, reproduced 4/4 at 5 s each) |
| `web_currency_math` | *absent* | **HIGH — money typeset as LaTeX in the phone's web bundle** |
| `config_sync` | HIGH ("git fetch failed") | unknown — no autosync record on the authority |
| `session_archive` | HIGH ("zabz-tech-linux not shipping") | ok — 3 machines shipping, newest contact 3 s ago |
| `app_voice`, `model_failover` | ok / absent | unknown — port artifacts (§6.2) |
| totals | 19 checks, 13 ok, 6 attention, 0 unknown | 19 checks, 9 ok, 6 attention, **3 unknown**, exit **2** |

**Two of the six findings the owner was looking at were artifacts of a stopped machine**, and two
genuine HIGH findings were invisible to it. That is the cost of a stopped clock: it is not neutral.
(One of the two new HIGH findings was fixed during this session and verified against the kernel's own
check — `web_currency_math` now reads `ok`, "currency is text in 1 web bundle(s)", and the two copies
of the bundle that had to be patched, the one the check names and the one the engine actually serves,
are recorded in the workstream's journal entry.)

## §6 — Open, named, and not quietly left

1. **Nothing alarms when the sentinel dies.** The badge says `stale <age>`; nothing escalates, and no
   surface watches for a *missing* reading. `140 §A1` recorded this on 2026-10-11 ("nothing would
   notice its failure"), and tonight is that prediction arriving. The honest monitor is "no new
   `history.jsonl` row in 15 minutes" — an absence-reporting check, not an exit-code check, because
   `run-sentinel.sh` exits 0 on purpose.
2. **Three checks are blind on the authority and the kernel exits 2 ("cannot see") on every run.**
   `app_voice` names the *office* unit `secretary-api` while the authority's is `company-api` — a
   porting error. `config_sync` has no status writer on the cloud, and `model_failover` has no
   model-watch record there. A check that can never see teaches its reader to ignore `unknown`; each
   should end up correct, correctly judged, or explicitly not-applicable with the reason in the code.
3. **The kernel repo's canonical copy is a bare repo on the frozen office box**
   (`secratary:/home/zabz/ceo-kernel.git`). The authority's checkout is now ahead of it by the
   `sources.py` patch. Where it should live is an open question, named here so it is not discovered by
   accident.
4. **The office box is still a live badge source**, serving a v3 badge and a six-hour-stale reading to
   anything that asks it (`115,737` requests in its log). With the list + freshest-wins it is a
   stand-in rather than a trap; retire the entry in `BADGE_AUTHORITIES` when the box is decommissioned.
5. **`converge-authority` was never ported** (v3's verdict: DEAD — 999 runs, 310 exit-3, target
   checkout gone). The authority's config publishing runs as `authority-repo-push`, which was found
   refusing every run (`cron-wrap REFUSED: payload … is not valid base64`) — owned by the config
   workstream, named here because `config_sync` cannot be judged until it works.
6. **A v3 badge in the browser still works**, because the *list* lives in the plugin's attribute and a
   v3 badge reads the first entry it is given. That is luck, not design: the deployment still needs a
   page reload per machine, and the record should not pretend the roll-out is automatic.
7. **`journal/` holds a stale copy of this repo, and one of the copies names the old authority.**
   Measured while grepping for `secratary.tail93e6e6.ts.net`: `journal/packages/plugin-attention-badge/
   lib/client.js` still reads `BADGE_AUTHORITY = 'https://secratary.tail93e6e6.ts.net'` while the real
   file is `packages/…` at the repo root. It is not a stray file — **598 files that mirror the repo
   tree** were committed under `journal/` on 2026-09-17 by commit `afbd9f3a` ("journal(alloc): ZABZ-YOGA
   publishes the reservation ledger"), sitting alongside the journal's own `entries/`, `index/`,
   `log/`, `state/`. Nobody has touched them since, and nothing reads them. It is left **in place**:
   removing 598 committed paths is a change that needs its own decision and its own survey, and
   deleting files is not a tidy-up to do at the end of an incident. Named here so the next person who
   greps for a hostname, a constant or a script finds the real one and not this shadow — and so whoever
   does decide gets the measured shape of it: same names, one generation behind, committed as a block.

## §7 — Lessons, for whichever session reads this next

1. **A moved authority moves its producers, not just its data.** The cutover moved the database, the
   API and the dashboard, and left one cron job behind. Everything downstream of that job kept
   rendering, forever, from a machine that had stopped. When you move a host, enumerate what *reads*
   the thing you moved, not just what writes it.
2. **"Stale" on a surface is not a monitor.** A reading that is honestly labelled stale still requires
   a human to look at it and know what stale *means*. The alarm for a missing producer belongs outside
   the producer.
3. **No hostname belongs in a client bundle.** Immutable caching makes a constant into a year-long
   commitment. A list with a freshness rule costs one attribute and turns a silent, permanent
   wrong-host read into a self-correcting one.
4. **When a monitoring job moves hosts, re-check every check.** Three of nineteen were blind on
   arrival, one of them because it named a unit that does not exist on the new box.
5. **The frozen box was not broken and that is why this lasted six hours.** `cron` masked *by
   decision* looks identical to `cron` stopped by a fault unless you know which box you are on and why.

<!-- tags=attention-badge,kernel,sentinel,cutover,authority,badge-stale,port,coo-kernel refs=131,133,140,141,142,166,H3567 -->
