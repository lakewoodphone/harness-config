# 135 — PARITY AND ROBUSTNESS: what the cloud authority does LESS well, does not do at all, and could do better

**Workstream:** measurement and analysis only. No fix in this document was applied.
**Written:** 2026-10-11, 06:10–06:40 UTC, from ZABZ-YOGA (Windows laptop, tailnet `zabz-yoga-1`).
**Authorities measured:** `secratary-cloud` = `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` (THE AUTHORITY);
`secratary` = `ssh secratary-ts` (frozen rollback anchor, read-only, bounded commands only).
**The standard (owner, verbatim, 2026-10-11):** the cloud authority must be *"a better version by orders of
magnitude over the office one, not missing anything or doing anything less in any way… everything and more it
should do even faster and more robustly."*

**Proof discipline.** Every number below carries the machine and the command that produced it. Where a like-for-like
office reading could not be taken without violating the freeze rules it says so and cites the recorded value instead.
Nothing was restarted, no database was written, no secret value is reproduced anywhere in this file — the `.env`
comparison is by KEY and by value **length class** only.

**Headline:** the *door* moved cleanly. The *actuators, the safety chain and the reachability* did not. Six of the
eleven findings below are "the new authority does not do this at all"; three are "it does it worse"; one is a
regression introduced by the move itself.

---

## §1 — ACTUATOR PARITY

### 1.1 The app's own autopilot loop: 39 of 39 subsystems moved, one of them started failing on the move — MEASURED

**WHAT.** The in-process autopilot is alive on the new authority with the *same* 39 subsystems, but the finance
sync family (`amazon_sync`, `ebay_sync`, `paypal_sync`) and `financial_alert_sweep` are now failing on the cloud
box, where they were healthy on the office box.

**EVIDENCE.**
- `python3 -c "import json;d=json.load(open(sys.argv[1]));print(len(d['subsystem_health']))" ...` on both boxes:
  office `SUBSYSTEMS 39`, cloud `SUBSYSTEMS 39`. Same 39 names, both sides.
- Cloud, `/opt/company/data/autopilot_state.json`, read 06:16Z:
  `amazon_sync {"consecutive_failures": 1, "last_error": "quickbooks-agent repo not found at /opt/company/domains/finance/quickbooks-agent"}`;
  identical text for `ebay_sync` and `paypal_sync`; `last_detail "quickbooks-agent repo not found at /opt/company/domains/finance/quickbooks-agent"`.
- Office, same file, read 06:12Z: `amazon_sync {"consecutive_failures": 0, "last_detail": "Amazon sync complete — 0 new transactions ingested into accounting.db."}`.
- Cloud: `ls -d /opt/company/domains` → `No such file or directory`.
- Cloud: `financial_alert_sweep {"last_detail": "Local ledger DB not available"}` (05:47Z) vs office `{"last_detail": "no_new_events (total=0)"}`.
  The message is raised by `app/services/quickbooks_service.py:674,769` (read from the laptop repo).
- Liveness of the rest: cloud `last_run_at 2026-10-11T06:09:42Z`, `interval_sec 900`, `consecutive_failures 0`;
  office frozen at `last_run_at 2026-10-11T03:25:12Z`. `plaid_sync` cloud 05:41Z `"13 added, 0 modified, 10 removed"`;
  `email_catalog` 05:49Z `"229 upserted, 0 new, 5 account(s)"`.

**SO WHAT.** The whole finance half of the company's senses is dark on the new authority — Amazon, eBay, PayPal
ingest and the financial-alert sweep now report nothing instead of reporting zero, which is the worse failure: a
subsystem that fails loudly is recoverable, a subsystem that reports "no new events" is a lie the owner acts on.
`balance_capture` and `spending_report` still carry a stale Windows-path error
(`/home/zabz/personal-secretary-mvp/C:/Users/ezabz/Code/personal-secretary…`) on **both** boxes — pre-existing, not a
regression, but it means two more actuators were already dead and travelled dead.

**FIX.** Copy the `quickbooks-agent` repo to `/opt/company/domains/finance/quickbooks-agent` (or repoint
`QB_AGENT_REPO_PATH`), then let the next tick prove it. Own it: the workstream porting the crontab's finance family.
Same for the ledger path behind `quickbooks_service.py`. Minimal, one path.

**CONFIDENCE.** Measured (the failure text and the missing directory are both directly read). The *cause* of the
office-vs-cloud difference is inferred: the office box had a `personal-secretary-mvp` checkout at `/home/zabz/…`
with `domains/finance/quickbooks-agent` inside it; the cloud app tree has no `domains/` at all.

---

### 1.2 The agent fleet is identical — 126 agents — and the register's "18 agents" is wrong — MEASURED

**WHAT.** The agent roster moved intact. `docs/mesh/000-SYSTEMS-REGISTER.md` describes the authority as "18 agents,
~300 ticks/day"; the measured roster is 126.

**EVIDENCE.**
- Office: `python3 -c "…json.load(open('/home/zabz/personal-secretary-mvp/data/agent_identities.json'))…"` →
  `agents 126` , `updated_at 2026-10-11T03:43:24Z`, file 39,124,416 B.
- Cloud: same script on `/opt/company/data/agent_identities.json` → `agents 126`, `updated_at 2026-10-11T06:10Z`,
  file 39,122,975 B. Top-level shape `{'agents': dict(126), 'updated_at': str}`.

**SO WHAT.** Parity is real and the register is stale by a factor of seven — anyone sizing concurrency, cost or
rate limits from "18 agents" is off by 7x. The roster is also being rewritten every few minutes on the cloud.

**FIX.** Correct the register (§1 table) to 126 agent identities, and state the tick rate from the log rather than
from memory. Own it: whoever owns `000-SYSTEMS-REGISTER.md`.

**CONFIDENCE.** Measured. (126 is a count of identity records; how many are *active* this hour was not measured.)

---

### 1.3 Home Assistant is unreachable from the new authority — MEASURED

**WHAT.** `HA_URL` is a public-DNS name on port 8123 that does not resolve from Ashburn, so every Home-Assistant
actuator (Shabbat automation, door lockdown, ceiling light, `run-ha-truth`, `run-ha-behaviour`) is dead.

**EVIDENCE.** From `secratary-cloud`:
```
v=$(grep -E "^HA_URL=" /opt/company/.env | cut -d= -f2-); getent hosts <host>   -> (no output)
curl -s -o /dev/null -m 8 -w "exit=%{exitcode} code=%{http_code}\n" "$v"        -> exit=6 code=000
```
`HA_URL` host class = PUBLIC-DNS, port = 8123. curl exit 6 = **could not resolve host**. From the laptop the same
name classifies as public DNS; the cloud box's resolver returns nothing for it.

**SO WHAT.** The owner's house is no longer reachable by the company. Two crontab jobs (`run-ha-truth`,
`run-ha-behaviour`) plus the Shabbat family of env vars (`SHABBAT_POWER_DOWN_ENABLED`,
`SHABBAT_DOOR_LOCKDOWN_AUTOMATIONS`, `SHABBAT_CEILING_LIGHT_ENTITY`) now configure an actuator with no wire.

**FIX.** The authority must reach the house over a path that survives the move — the same Tailscale network the
office box used. Until then, HA work has to be commissioned back through a machine that is on the LAN or the
tailnet. Own it: the workstream that owns HA, with the tailnet decision in §2.

**CONFIDENCE.** Measured (unreachable from the cloud box). *Why* it does not resolve (DDNS tied to the office's
public IP, or a name only resolvable inside the LAN) is inferred.

---

### 1.4 `/phone` on the new authority redirects into a network it is not on — MEASURED

**WHAT.** The `phone-redirector` unit runs on the cloud box and answers, but its redirect target is
`https://secratary.tail93e6e6.ts.net` — the office box's tailnet name. The cloud box has no tailscale and no DNS
for that name.

**EVIDENCE.** On `secratary-cloud`:
```
curl -s -D - -o /dev/null -m 8 http://127.0.0.1:3087/phone | grep -i ^location
  -> Location: https://secratary.tail93e6e6.ts.net
getent hosts secratary.tail93e6e6.ts.net   -> (nothing)
curl https://zabz-tech.tail93e6e6.ts.net/mesh/health -> 000
```
The unit is `active running` (`systemctl list-units --state=running`), and the tunnel ingress maps
`ai./phone -> :3087` (register §2.1).

**SO WHAT.** The front door the owner (and anyone holding the number) uses to reach the harness now lands on a
hostname that resolves nowhere from where it is served. It is a live 302 into a dead end.

**FIX.** Either point it at a name the cloud box can resolve (the public door) or move the redirector back to a
machine on the tailnet. One line of config, but it needs the §2 decision first.

**CONFIDENCE.** Measured.

---

### 1.5 `.env` key parity is COMPLETE — 301 of 301 keys, no length-class differences — MEASURED (a win)

**WHAT.** The new authority's environment is a superset of the old one's by key, and every shared key has the same
value-length class.

**EVIDENCE.** Keys extracted with
`grep -E "^[A-Za-z_][A-Za-z0-9_]*=" FILE | while … echo "$k\t$bucket"; done | sort`, buckets
`0 / 1-15 / 16-39 / 40-99 / 100plus`. Office `/home/zabz/personal-secretary-mvp/.env` = **301 keys**;
cloud `/opt/company/.env` = **302 keys**. `Compare-Object` → *only on cloud*: `DATABASE_URL`. *Only on office*: none.
Key-by-key length-class comparison → **0 differences**.
`/opt/company/.env` is mode 600 and there are five timestamped `.env.before-*` copies beside it.

**SO WHAT.** This is the one place where "nothing is missing" is literally true, and it is worth recording as a
win so a later session does not re-audit it. It is a *key and length* statement only: same-length different values
are invisible to this test by construction.

**FIX.** None. Keep it — but re-run this exact check after every future `.env` edit, because the office `.env`
stopped changing at 2026-10-09 20:05Z and the cloud one is now the only one that matters.

**CONFIDENCE.** Measured (presence/absence and length class). Values not compared, by rule.

---

### 1.6 The 92-job cron layer that made this company act is entirely absent — MEASURED

**WHAT.** The whole scheduled actuator layer is missing on the new authority. This is not a partial port: the cloud
box's crontab is empty and `/etc/cron.d/` holds only the OS's `e2scrub_all`.

**EVIDENCE.**
- `wc -l < /home/zabz/cutover/crontab.before` = **176** lines; `grep -vcE "^\s*(#|$)"` = **92** live jobs;
  `grep -oE "cron-wrap\.sh +[A-Za-z0-9_.-]+" | awk '{print $2}' | sort -u | wc -l` = **87** distinct wrapper jobs,
  plus 5 direct commands (`lpt-audit-weekly.sh`, `lpt-dialpad-daily.sh`, `lpt-audit-freshness.py`,
  `lpt-dialpad-apply.sh`, `mesh-node-probe.sh`). 87 + 5 = 92.
- Cloud: `crontab -l` → `no crontab for root`; `ls -la /etc/cron.d/` → `.placeholder`, `e2scrub_all` only.
- The 87 names, measured, include: `deadman`, `push-db-offsite`, `company-offsite-push`, `report-offsite-age`,
  `transcript-archive`, `db-integrity-check`, `disk-guard`, `mesh-health`, `mesh-placement-monitor`, `agent`-side
  `heartbeat`, `family_chat_watchdog`, `dialpad-harvest-cron`, `dialpad-call-fresh`, `dialpad-recording-gap`,
  `dialpad-transcript-gap`, `dialpad-sms-harvest-cron`, `nightly-plaid-sync`, `daily-finance-sync-cron`,
  `push-dsh-sessions`, `journal-commit`, `prune-backups`, `store-write-check`, `sampler`, `sentinel`, `guard-registry`,
  `cron-target-guard`, `cron-script-guard`, `model-failover-watch`, `production-comms-freshness`, and 60 more.
- Note the brief says 168 lines: the preserved file is 176 lines / 92 jobs. Use 92 as the number of actuators.

**SO WHAT.** Every monitor, every backup, every freshness proof, every harvest, every guard, and the dead-man
switch were cron jobs. "Autopilot runs in-process" covers the *company's* ticks and nothing else. Anything the
owner expects to happen on a schedule — a nightly Plaid sync, a Dialpad harvest, a disk guard, an integrity check —
does not happen now, and no one is told.

**FIX.** Port by family, not by line, and fix the guard while porting (§6.6). Two workstreams already own the
crontab and the backup chain. The families this workstream measured as *unowned* in that port: the four `dialpad-*`
harvesters, `nightly-plaid-sync`, `daily-finance-sync-cron`, `family_chat_watchdog`, `push-dsh-sessions` +
`vscode_chat` ingestion, `journal-commit`, and `sampling`/`sentinel`.

**CONFIDENCE.** Measured for the gap and the job inventory. Which of the 92 are redundant with an in-process
subsystem was not determined.

---

## §2 — REACHABILITY PARITY

### 2.1 The cloud box is not on the tailnet and cannot be — MEASURED

**WHAT.** `secratary-cloud` is not a tailnet peer, has no tailscale installed, and cannot resolve or reach any
`.tail93e6e6.ts.net` name.

**EVIDENCE.**
- From ZABZ-YOGA: `tailscale status --json` peer list = `lakewooechsmini`, `secratary`, `zabz-tech`,
  `zabz-tech-linux`, plus five iOS/macOS peers. **No `secratary-cloud`, no entry for 178.156.194.1.**
- On `secratary-cloud`: `which tailscale` → *(nothing)*; `ls /var/lib/tailscale` → `No such file or directory`.
- On `secratary-cloud`: `getent hosts secratary.tail93e6e6.ts.net` → *(nothing)*;
  `curl -m 6 https://zabz-tech.tail93e6e6.ts.net/mesh/health` → `000`.
- On `secratary-cloud`: `ss -ltnp` → `0.0.0.0:22`, `127.0.0.53:53`, `127.0.0.54:53`, `127.0.0.1:20241` (cloudflared),
  `127.0.0.1:8002` (uvicorn), `127.0.0.1:3087`, `[::]:22`, `*:3000`. **No 3091, no 3097/3098.**
- `ps -eo pid,cmd | grep -iE "dsh|mesh|3091|3097|3098"` → nothing. There is no DSH engine on the cloud box.
- The only way in is `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`, and
  `ssh-keygen -l -f /root/.ssh/authorized_keys` → **one** key: `SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg mesh-hetzner-2026-08-31 (ED25519)`.

**SO WHAT — the cost of each, item by item.**
1. **The placement broker cannot run where the authority is.** `packages/mesh-broker` is designed for the authority
   and its client reaches it as `ssh <brokerSsh> curl http://localhost:3091` with `brokerSsh` = `secratary-ts`.
   The broker decides placement by reading `https://<node>.tail<tailnet>/mesh/health` — the probe target is
   hard-coded to the tailnet (`lib/node-probes.js: DEFAULT_TAILNET`). On the cloud box the broker can neither be
   reached by the old name nor read a single node.
2. **The mesh cannot dispatch work to it.** It answers no `/mesh/health`, so it is invisible to
   `failover-placement.js` and to the broker's roster, and `nodes.json` has no way to address it. Two vCPUs of
   capacity are outside the mesh permanently.
3. **"Cross-machine file transfer and the estate's mesh-run tooling" cannot include it.** `bin/mesh-run.mjs`,
   `scripts/mesh/*`, `mesh-node-probe.sh` and every `scp`-by-node-name path address peers by
   `<label>.tail93e6e6.ts.net`. The cloud box is reachable only by a literal public IP plus a single private key.
4. **SSH is by public IP and key only** and the key exists on one machine (§4.6). Loss of that laptop is loss of
   the only interactive path to the company, short of the provider console.
5. **New exposure**: `ufw status verbose` on the cloud box = `Default: deny (incoming)` with exactly one allow,
   `22/tcp ALLOW IN Anywhere`. sshd is on the public internet with fail2ban in front. The office box's sshd was
   behind NAT.

**WHAT ADDING IT TO THE TAILNET WOULD BUY.** `tailscale status` would list it; `/mesh/health` would answer over the
same surface the other nodes already use; the broker could live on the authority (which is where every document
says it belongs) and read every node; the mesh could place children on it; every estate tool that addresses nodes
by name would include it with no new credential; and recovery would not depend on one private key file on one
laptop. It is also the only route by which the authority can reach the house's Home Assistant (§1.3) or the office
LAN (`LINUX_PC_HOST` and `SHELLY_PLUG_HOST` are both PRIVATE-LAN class — measured — and unreachable from Ashburn).

**FIX.** Install `tailscale` on `secratary-cloud` and authorise it with `TAILSCALE_AUTH_KEY` (already present in
the env, key present on both sides). Then move the broker there with
`packages/mesh-broker/deploy/install-authority.sh` and repoint the client's `brokerSsh`/`MESH_BROKER_SSH` at the new
authority. Own it: the mesh workstream.

**CONFIDENCE.** Measured for every claim about reachability and exposure. "What it would buy" is a design
statement, not a measurement.

---

## §3 — THE MESH FAN-OUT: WHY THE FAILOVER DID NOT RESCUE THE DISPATCH

**(This is the item the brief called the most important. The mechanism is a stale process, not a broken design.)**

### 3.1 THE MECHANISM — the running engine was booted 1 day 17.5 hours BEFORE the failover code existed, and `patchReload: live` does not re-import JavaScript — MEASURED

**WHAT.** `subagent` (the mesh provider) failed with `broker-unreachable` **even though
`lib/failover-placer.js` is present in the repo and `placementFailover` defaults to ON**. The failover never ran,
because the engine process that is serving sessions right now loaded its JavaScript on **2026-10-07 20:33:13**, and
the failover was committed on **2026-10-09 14:04:30** — 41.5 hours later.

**EVIDENCE — the six lines that prove it.**
1. The live failure, reproduced in this session:
   `subagent("<trivial prompt>")` →
   `Error: remote-ssh: broker-unreachable: the placement broker could not be reached at secratary-ts:http://localhost:3091/place — ssh exited 7: curl: (7) Failed to connect to localhost port 3091 after 0 ms: Could not connect to server`
2. The ledger record of that same failure, written by `provider.js:504-517`
   (`C:\Users\ezabz\.dsh\mesh\placements\remote-cfbf76fd-25d7-48df-9304-140427ac3267.json`):
   `{"state": "placement-failed", "code": "broker-unreachable", "at": "2026-10-11T06:09:50.465Z", "error": "the placement broker could not be reached at secratary-ts:http://localhost:3091/place — …"}`
   A *direct-probe* placement would have written `"source": "direct-probe"`; a genuine "nothing answered
   anywhere" would have written `"code": "mesh-unreachable-no-probe"`. Neither appears. The raw BrokerError
   propagated to the provider.
3. The engine process: `Get-CimInstance Win32_Process -Filter "Name='node.exe'"` →
   `10668  10/7/2026 8:33:13 PM  "C:\Program Files\nodejs\node.exe" C:\Users\ezabz\.dsh\engine\node_modules\@deepseek-ai\dsh\lib\bin.js web --port 3099 --no-open`.
   **Started 2026-10-07 20:33:13 local.**
4. The code: `git log --date=iso --format='%h %ad %s' -- packages/plugin-remote-fanout/lib/failover-placer.js` →
   exactly one commit, `a813fab2 2026-10-09 14:04:30 -0400 mesh: the broker becomes an optimisation, not a veto - a dead control plane no longer stops a dispatch`.
   The same commit touched `lib/index.js`. Both files' `LastWriteTime` = `10/9/2026 2:05:59 PM`.
   HEAD at the time of measurement: `ee3a7e2f 2026-10-10 20:14:48`.
5. The plugin is loaded from the repo through a symlink —
   `C:\Users\ezabz\.dsh\profiles\web\node_modules\dsh-plugin-remote-fanout -> C:\Users\ezabz\code\harness-config\packages\plugin-remote-fanout`
   — so the *installed* copy is current. Only the *in-memory* module graph is stale.
6. The config is not the cause. `C:\Users\ezabz\.dsh\profiles\web\cordis.patch.yml` has exactly one
   `remote-fanout` row (line 132) and it does **not** set `placementFailover`; `lib/index.js:288` is
   `const failoverEnabled = config.placementFailover !== false;` → **ON**. The row also does not set
   `placement`, so `resolvePlacementMode` yields `broker` (`index.js:71`), which is the mode that *has* the
   failover wrapper. Nothing in the live config disables it.

**THE DECIDING LINE.** `provider.js:504` calls `this.placer.acquire(...)`. In the code on disk, `this.placer` is
the failover wrapper built at `index.js:289-302`; in the process that is actually running, that wrapper did not
exist at boot, so `this.placer` is the bare `createNodePlacer`, whose `acquire` re-throws the BrokerError at
`placement.js:407` after the broker call at `placement.js:380` fails. `provider.js:506` then records
`code = error.code = "broker-unreachable"` and re-throws — which is exactly the ledger file in evidence 2.
`patchReload: "live"` (profile `package.json`) re-reads **YAML patches**; it does not re-import an ES module that
was resolved at process start.

**CONFIRMATION THAT THE FALLBACK WOULD HAVE WORKED.** The direct probe reads
`https://<node>.tail93e6e6.ts.net/mesh/health` (`lib/node-probes.js:40-42`). Measured from this laptop at 06:12Z:
`zabz-tech` → **HTTP 200 in 657 ms**; `zabz-yoga-1` → **HTTP 200 in 211 ms** (`zabz-tech-linux` 404,
`secratary` 502, `lakewooechsmini` 502 — all non-fatal, the probe records them). Two eligible nodes answered, so a
failover-enabled process would have placed and dispatched instead of failing.

**CONFIDENCE.** Measured for every step. The one inference is that no other `remote-ssh` provider instance shadows
this one; it is the only `subagent`-shaped provider row in the live profile and the failure text carries the
provider's own name.

### 3.2 THE MINIMAL CORRECT FIX

**FIX 1 — immediate (restores dispatch, one action).** Restart the DSH engine on ZABZ-YOGA (`dsh web`, PID 10668)
so it loads `a813fab2`. This is the whole difference: after the restart `this.placer` is `createFailoverPlacer`
and a broker outage places by direct probe. **This workstream did not do it** — brief rule 5 and this workstream's
scope forbid restarting the engine. Own it: the owner or whoever holds the engine's restart decision.
Two corroborating facts to check on the way back up: the boot log must contain
`PLACEMENT FAILOVER is ON — …`, and the first new file in `.dsh\mesh\placements\` after a failed broker call must
say `"source": "direct-probe"`.

**FIX 2 — the durable half, so this cannot silently recur.** The defect class is "a fix in the repo that the
running process never loaded". The smallest correct guard is a boot-time and periodic comparison of the loaded
plugin's identity against the repo's, surfaced where a human sees it: record the git SHA of
`packages/plugin-remote-fanout` at module load, publish it on the health surface, and make the mesh provider refuse
to report itself "installed" when the loaded SHA is older than HEAD for that package. Nothing in the estate today
can tell a stale engine from a current one — that is why this cost a day of fan-out. Own it: the harness/plugin
workstream.

**FIX 3 — the broker's home.** Independently of Fix 1, `brokerSsh` is `secratary-ts` and there is no broker there:
`systemctl is-active mesh-broker` on `secratary-ts` = **`inactive`** and `list-unit-files` = **`disabled`**
(the unit file exists at `/etc/systemd/system/mesh-broker.service`, 5325 B, dated Oct 9 19:59);
on the cloud box there is no unit at all and `ss -ltnp | grep 3091` = *nothing* on either machine. Two ways out,
and both should be done in this order: **(a)** install and start the broker on the new authority with
`packages/mesh-broker/deploy/install-authority.sh` and set `MESH_BROKER_SSH=secratary-cloud` (the alias already
exists in this laptop's `~/.ssh/config`, so no `sshArgs` change is needed); **(b)** leave the office box's
`mesh-broker.service` disabled — it is out of the rollback set and starting it would put a control plane on a
machine that is supposed to be inert. Until (a) happens every dispatch pays the broker's `brokerTimeoutMs`
(default 30000) before falling back to the probe.

**CONFIDENCE.** Measured (service states, unit presence, absence of any :3091 listener).

---

## §4 — SINGLE POINTS OF FAILURE AND SINGLE COPIES

| # | thing | where it is | where else it exists | lost if that machine dies | cheapest correct remedy |
|---|---|---|---|---|---|
| 4.1 | **The authority database** | `secratary-cloud:/root/authority.db` (23,707,291,648 B, 231 tables, WAL 67,108,864 B, mtime 06:08Z) | The office copy is a **frozen snapshot 1.5 h older** (23,622,823,936 B, unchanged since 04:28:35Z). R2 `authority/secretary.db.gz` = **7,234,886,331 B, last modified 2026-10-10T05:20:09Z — 25 h stale** | The company. Everything after 2026-10-10 05:10Z, and every customer record, message, ticket and journal row since | Finish the first offsite push and **schedule** it. The credential now exists (`/root/.lpt-r2.env`, 643 B, mode 600, 06:01Z) but `/var/lib/authority-backup/last-run` **does not exist** and `crontab -l \| grep -c offsite` = **0** |
| 4.2 | **The raw transcript archive** (AGENTS.md rule 1: "a copy must always exist") | `secratary:/home/zabz/lpt-transcripts/` — `manifest.sqlite` 1,544,192 B, `objects/` 256 shards | **Nowhere.** The cloud box has no copy and no updater; the archive's own cron job (`transcript-archive`, hourly) froze with the box | The bytes of every DSH session and Copilot chat that the parser never read — the one store that cannot be reconstructed | Pull the archive to the new authority and move the pull-driven scheduler with it (`scripts/transcript-archive-run.sh` + `transcript-archive-server.py --check`) |
| 4.3 | **The accounting ledger** | `accounting.db` is **0 bytes on both boxes** (`/home/zabz/personal-secretary-mvp/data/accounting.db` and `/opt/company/data/accounting.db`) | — | Nothing directly; but the ledger the app actually reads is elsewhere and the cloud box cannot find it: `financial_alert_sweep` → `"Local ledger DB not available"` | Find the path `quickbooks_service.py:674,769` expects and place it. Own it with §1.1 |
| 4.4 | **The app's non-database data** | `secratary-cloud:/opt/company/data` = **14 G** | The office `data/` directory is the source; no second copy anywhere | `chromadb/`, `mem0/`, `neshama/`, `dialpad/`, `browser/`, `google_voice_profiles/` (5,197 entries), `token_archive/`, `voice_recordings/` — the company's memory and every OAuth token | It has moved but was never verified: the `data/` rsync is the one that took the office box down at 02:14Z (`H3406`). Two concrete losses are PROVEN below (§4.5) |
| 4.5 | **Family chat history** | `secratary-cloud:/opt/company/data/family_chat.db` = **61,440 B, 1 message** | `secratary:/home/zabz/personal-secretary-mvp/data/family_chat.db` = **1,134,592 B, 3,156 messages** (max rowid 158,791) | **3,155 family-chat messages.** The authority DB has no `%family%` tables (`select name from sqlite_master where type like`) — so the history is on the frozen box and nowhere else | Copy that one file and re-verify by row count. It is 1.1 MB. This is the cheapest fix in this document |
| 4.6 | **The SSH key to the authority** | `C:\Users\ezabz\.ssh\id_ed25519_hetzner` on **this laptop only** | `secratary-cloud:/root/.ssh/authorized_keys` holds **exactly one** key, `SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg mesh-hetzner-2026-08-31` | Interactive access to the company from anywhere except the Hetzner console — and the token that would drive that console is dead (§4.8) | Add a second key from `zabz-tech` and from the owner's phone-capable agent host; keep a sealed copy of the private key off the laptop |
| 4.7 | **The code and the journal** | Laptop working copy at `C:\Users\ezabz\code\harness-config`, `origin` **fetch** = `secretary-ts:/home/zabz/harness-config.git` (the frozen office box) | `offsite` = `https://github.com/lakewoodphone/harness-config.git`; `git ls-remote offsite HEAD` = `d8ecbd148f1fc7b1bccbe9ca77a8805d33bba139` (≠ local HEAD `ee3a7e2f`, so GitHub is not behind) | If the office box dies, `origin` fetch dies — every clone/fetch of the journal fails | Nothing urgent (GitHub holds a copy) but the register's claim "the git repo harness-config (remote on the authority)" is now FALSE: `find / -maxdepth 4 -name harness-config -type d` on `secratary-cloud` → **nothing**; there is no checkout, no journal, no bare repo on the new authority |
| 4.8 | **The provider API token** | `HETZNER_API_TOKEN` in `/opt/company/.env` | Copy in the office `.env` | Provider-level recovery (start/rebuild/snapshot `secratary-cloud`), and the backup monitor | **The token is invalid.** `curl -H "Authorization: Bearer $T" https://api.hetzner.cloud/v1/servers` → `http=401 {"error":{"code":"unauthorized","message":"the token you have provided is invalid"}}`. Re-issue it before you need it |
| 4.9 | **The dead-man switch** | `secratary:/home/zabz/bin/deadman.py` + `/home/zabz/.sms-inbox/deadman.env` (133 B, mode 600), run by crontab line 117 `*/5 * * * *` | **Nowhere.** No `deadman` on the cloud box's `/usr/local/bin` equivalent... see note — a workstream installed `authority-deadman.py` at 06:20Z mid-session, unscheduled | The only mechanism that can report the authority being dead from outside it | See §6.7 — this is the most consequential finding in the document |
| 4.10 | **The R2 credential** | `secratary:/home/zabz/.lpt-r2.env` (643 B, mode 600, Oct 5) and now `secratary-cloud:/root/.lpt-r2.env` (643 B, mode 600, 06:01Z) | ✅ this one is duplicated | — | None. Record it as a win |
| 4.11 | **Local DB snapshots** | `secratary:/home/zabz/secretary-backups/` (8 stamp dirs, newest `20261011T025626Z`) | The single office SSD only | The last good local backup chain | See §6.3: the two newest snapshots have **no `COMPLETE` marker**; the newest complete one is `20261010T180001Z` |

**4.5 proof, verbatim.**
```
office: sqlite3 "file:…/family_chat.db?mode=ro&immutable=1" "select count(*) from messages;"   -> 3156
office: sqlite3 "file:…/family_chat.db?mode=ro&immutable=1" "select min(rowid), max(rowid) from messages;" -> 1|158791
cloud : sqlite3 /opt/company/data/family_chat.db "select count(*) from messages;"              -> 1
cloud : sqlite3 /root/authority.db "select name from sqlite_master where type='table' and name like '%family%';" -> (nothing)
```
The office read used `mode=ro&immutable=1` deliberately: it takes no lock, creates no `-shm`/`-wal`, and cannot
write. That is the safe way to read a database on the frozen box, and it should be the standing method.

---

## §5 — PERFORMANCE AND RELIABILITY, MEASURED

### 5.1 The API is fast — the network is the latency, not the app — MEASURED

**WHAT.** Public API latency (laptop → Cloudflare → tunnel → cloud box), 5 samples each, `curl -w "%{time_total} %{http_code}"`:

| endpoint | n | code | median | max | min |
|---|---|---|---|---|---|
| `https://api.abletelsolutions.com/health` | 5 | 200 | **0.221 s** | 0.251 s | 0.148 s |
| `https://ai.abletelsolutions.com/health` | 5 | 200 | 0.302 s | 0.359 s | 0.185 s |
| `https://ai.abletelsolutions.com/` | 5 | 307 | 0.165 s | 0.176 s | 0.154 s |
| `https://api.abletelsolutions.com/` | 5 | 401 | 0.166 s | 0.193 s | 0.144 s |
| `https://api.abletelsolutions.com/api/v1/company/status` | 5 | 404 | 0.179 s | 0.240 s | 0.153 s |

The same routes on the cloud box's own loopback: `http://127.0.0.1:8002/health` → `0.010125, 0.004053,
0.003817, 0.002493, 0.003150` s → **median 0.0038 s, max 0.0101 s**; dashboard `:3000/health` → median 0.0238 s,
max 0.0730 s. The `404` and `401` are real route/auth answers, not failures — the app answered.

**SO WHAT.** The app itself answers in single-digit milliseconds; the tunnel and the two links add ~217 ms. That is
a good result and a fair claim to make: **the new authority's API is not the bottleneck.** The office equivalent
**could not be measured** — the office API is stopped and the box is frozen, and taking a like-for-like reading
would require starting it, which the freeze rules forbid. The nearest recorded office number is the broker's own
node probe on 2026-10-11 00:27Z while the office box was still serving: `secratary: unreachable (last attempt 0 s
ago, last good reading 178 s old: timed out after 4000 ms (hard wall-clock deadline))` — i.e. the office box could
not answer a `/mesh/health` request inside 4 s while the same probe read `zabz-tech` in 57 ms warm.
(Cited from `.dsh\mesh\placements\remote-057ab79e-….json`, not measured by me. **Inferred comparison.**)

### 5.2 The new box is WORSE on memory, and the kernel has already killed the company once — MEASURED

**WHAT.** On 2026-10-11 at **05:47:24Z — four minutes after the cutover landed — the kernel's global OOM killer
killed the company API.**

**EVIDENCE.** `journalctl -k --since 2026-10-09 | grep -iE "out of memory|oom-kill|Killed process"` on `secratary-cloud`:
```
05:47:24 f2b/a.sshd invoked oom-killer: gfp_mask=0x140cca(GFP_HIGHUSER_MOVABLE|__GFP_COMP), order=0, oom_score_adj=0
05:47:24 oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=/,mems_allowed=0,global_oom,task_memcg=/system.slice/company-api.service,task=python,pid=54912,uid=0
05:47:24 Out of memory: Killed process 54912 (python) total-vm:15637784kB, anon-rss:7544976kB, file-rss:3328kB, shmem-rss:0kB, UID:0 pgtables:23628kB oom_score_adj:0
```
(One event; the three lines are its anatomy. `systemctl` restarted the unit — `Restart=always`.)

Current state, `free -m` at 06:21:39Z: `Mem: total 7742, used 2294, free 298, buff/cache 5464, available 5447`;
`Swap: 4095 total, 1687 used, 2408 free`. `ps -eo pid,rss,pmem --sort=-rss`: `55564 python 1,690,444 kB = 21.3 %`.
`systemd-cgtop -n1` → `system.slice 5.6G`. VmSwap by process: `python 616,420 kB`, `next-server 68,016 kB`.
`vmstat 1 3` showed `si/so` non-zero (16/52) — the box is **actively swapping**.

**SO WHAT.** The application needs **7.54 GB** of anonymous memory at its peak and the box has **7.74 GB** of
physical RAM. There is no ceiling on the cgroup — the drop-in explicitly declines to copy the office's
`MemoryMax=8G` because "it would OOM-kill on this 7.7 GB box" (`/etc/systemd/system/company-api.service.d/*.conf`).
And the kill was `global_oom`, `CONSTRAINT_NONE`: the victim is chosen **by the kernel, globally**, and on this
evidence the round before last it chose `company-api` while `f2b/a.sshd` was the caller. Nothing stops it choosing
`sshd`, `cloudflared`, or the process holding the database next time. This is the single largest "does less well"
in the document: the office box had 23,421 MB with 1,052 MB used and 7 MB of swap; the new authority runs the same
application in one third of the memory and has already been killed by it.

**FIX.** (a) Set `MemoryMax`/`MemoryHigh` **below** physical (e.g. `MemoryHigh=5G`, `MemoryMax=6G`) so a runaway is
killed *inside its own cgroup* instead of the kernel picking a global victim; (b) put the company API's worker and
cache sizes under that ceiling; (c) if the peak is genuinely 7.5 GB it needs a bigger instance — CCX13 is 2 vCPU /
8 GB and the measured working set does not fit. Own it: whoever owns `company-api.service`; the sizing decision
is the owner's (money).

**CONFIDENCE.** Measured. That the app will reach 7.5 GB again is inferred from the fact that it did so once
already, on this box, within four minutes of the cutover.

### 5.3 Everything else about the new box is faster — MEASURED, with one correction to the brief

**WHAT.** The cloud box is faster at every measured storage and throughput task. The brief's description of the
office box as having "a spinning disk" is **wrong**, and the correction matters.

| | office `secratary` | cloud `secratary-cloud` |
|---|---|---|
| CPU | Intel i5-4570, **4 cores / 4 threads**, 3.20 GHz, 2013 | **AMD EPYC-Milan, 2 vCPU** |
| RAM | 23,421 MB total, 1,052 used, swap 7 MB | 7,742 MB total, 2,294 used, swap 1,687 MB |
| System disk | `/dev/sda` — **`PNY 500GB SATA S`, `ROTA=0`, `/sys/block/sda/queue/rotational` = 0** — i.e. a **SATA SSD**, not a spinning disk; LUKS (`sda3 crypto_LUKS` → LVM → `/`) | `/dev/sda1`, `QEMU HARDDISK`, `ROTA=0`, 75 G NVMe-backed |
| Disk use | 467 G total, **411 G used, 37 G free (92 %)** | 75 G total, **46 G used, 26 G free (64 %)** |
| DB | 23,622,823,936 B, 231 tables (H3407; unchanged since 04:28:35Z) | 23,707,291,648 B (**+84 MB since the copy**), 231 tables, WAL 64→67 MB moving |
| Throughput evidence | the 14.2 GB / ~200,000-file rsync ran at **2–7 MB/s** (`H3406`) | the consistent 23.6 GB `.backup` completed in **175 s ≈ 139 MB/s** (`/var/log/authority-offsite.log`, 06:01:38Z); the cutover ship ran 41.5 MB/s |
| Load | 0.01–0.61 on 4 threads (idle, frozen) | **2.0–3.6 on 2 vCPU** |
| Boots | 8 boots in the journal, 1.6 GB of journal | **1 boot** since 2026-10-09 18:23:06Z, 32 MB of journal |
| Processes | 239 | 156 |

**SO WHAT.** The storage claim in every document ("a single disk", "a spinning disk") should be corrected: the
office box's disk is a **consumer SATA SSD at 92 % full behind LUKS**, which explains the 2–7 MB/s without needing
a spinning platter — a nearly-full consumer SSD with an encryption layer and 200k small-file reads is the worst
case for exactly this workload. The cloud box is **20–70x faster** on the same class of operation. That is a real
"orders of magnitude" win and it is the strongest support for the migration.

### 5.4 The new box runs at its capacity line at rest — MEASURED

**WHAT.** Pressure-stall information (`/proc/pressure/*`) read twice, 90 s apart, with no work of mine in between
(`date; cat; sleep 90; date; cat`):
```
06:20:09  cpu  some avg10=32.10 avg60=32.13 avg300=19.34   full avg10=0.00
06:20:09  mem  some avg10= 2.11 avg60= 1.80                full avg10=1.15
06:20:09  io   some avg10=49.61 avg60=46.60 avg300=37.37   full avg10=18.08 avg60=16.38
06:21:39  cpu  some avg10=26.36 avg60=28.78                full avg10=0.00
06:21:39  mem  some avg10= 0.75                           full avg10=0.53
06:21:39  io   some avg10=36.48 avg60=43.79                full avg10=11.31 avg60=14.83
```
with `cut -d" " -f1-3 /proc/loadavg` → `3.55 3.00 2.05` at 06:21:39Z.

**SO WHAT.** On 2 vCPU the box spends ~26–32 % of wall time with at least one task stalled on CPU and ~36–50 %
with at least one task stalled on IO, of which ~11–18 % is *full* IO stall (every runnable task waiting on disk).
That is a machine with no headroom, carrying the company plus the concurrent migration fleet. The honest
comparison is that the office box's idle load (0.01–0.61 on 4 threads) is an idle machine and the cloud box's
load (2.0–3.6 on 2 vCPU) is a busy one; the useful part of the measurement is that **there is no spare capacity
here for another workstream, another fleet, or a doubled tick rate** — which is exactly what the migration
programme is currently spending on it.

**FIX.** Nothing to fix in software. Record it: any new always-on job, and any increase in tick rate, should be
budgeted against a box already at its CPU and IO pressure lines. Own it: the owner (sizing) and whoever schedules
new work.

**CONFIDENCE.** Measured. My own probing in the minutes before the first reading inflates `avg60`/`avg300`; the
`avg10` pair is the clean number.

### 5.5 The disk on the new authority reaches 94 % during its own backup, on a disk that also holds the database — MEASURED

**WHAT.** Two `df -h /` readings eleven minutes apart, on the same machine:
```
06:09:32  /dev/sda1  75G  68G  4.4G  94%  /
06:20:50  /dev/sda1  75G  46G   27G  64%  /
```
The 22 GB that appeared and vanished is a live `.backup`, proven by the log and by a process still cleaning it up:
`tail /var/log/authority-offsite.log` → `[1/4] consistent copy of /root/authority.db -> /var/tmp/offsite.6xmKSc/authority.db (22528 MiB source)  ok in 175 s, 23622823936 bytes`; and
`ps` showed `bash -c … rm -rf /var/tmp/offsite.6xmKSc …` with `etime 02:28`.

**SO WHAT.** The authority's own backup procedure transiently needs a second full copy of the database — 22 GB
— on a 75 GB disk with 26 GB free. At the moment I measured it, free space was **4.4 GB**, and the brief's own
rule 4 forbids exactly that ("Nothing may leave a second full copy of the database on that disk"). Two backups
overlapping, or a database 5 GB bigger, fills the disk and SQLite starts failing writes on the company's only
database. The 26 GB of headroom is one database and a bit, not "27 GB free" in any useful sense.

**FIX.** The new offsite script should stream the `.backup` through a **gzip to the object store without ever
materialising a second uncompressed copy** — the office's `push-db-offsite.sh` already did the compressed-stream
form and should be read before a new one is written (AGENTS.md §0: use what exists). If a local temp file is
unavoidable, gate it: refuse to start unless `df --output=avail /` is at least database-size-plus-margin, exactly
as the script already refuses a missing credential. Also delete the leftover `/root/authority.db.new` (0 bytes,
05:41Z) and the 1.8 MB decoy described in §6.9. Own it: the workstream that owns the offsite chain.

**CONFIDENCE.** Measured, including the two `df` readings and the log line. That the transient was *entirely* that
`.backup` is inferred from the byte count matching the database and the cleanup process naming that exact directory.

### 5.6 Tick cadence is alive on the new authority and stopped on the old one — MEASURED

**EVIDENCE.** `journalctl -u company-api --since "2026-10-11 05:40" -o short-iso | grep -c initiative_tick` = 16.
Successive autopilot lifecycles: `06:10:18 Lifecycle sweep …', 'task_lifecycle_updated': 241 …`, `06:12:38` same,
`06:14:40` same — i.e. **~140 s apart against a configured `interval=120`**, with the loop's own
`Lifecycle sweep not running: waiting for the interval (…)` lines at ~30 s spacing in between.
`autopilot_state.json` `last_run_at` = `2026-10-11T06:09:42Z`, `updated_at 06:10:16Z`, `interval_sec 900`,
`enabled true`, `consecutive_failures 0`. Office: `last_run_at 2026-10-11T03:25:12Z`, frozen.

**SO WHAT.** The company's heart is beating and the cadence is measurable. Worth stating plainly because the
brief's central worry was "the cron layer did not move" — the *in-process* layer did, and it is the layer that
generates the company's work.

**FIX.** None. Own it: nobody.

**CONFIDENCE.** Measured.

---

## §6 — THE NINE WAYS THE OFFICE BOX FAILED, AND WHETHER THE NEW ONE REPEATS THEM

### 6.1 Disk starvation taking sshd down — **EXPOSED, and closer to the edge than the old box**

**EVIDENCE.** Office: measured three times, most recently 2026-10-11 02:14:30Z — load 52 on 4 threads, `bo`
5,000–22,000 blocks/s, sshd silent while `tailscale ping` answered in 37 ms (`H3406`). Cloud:
`/proc/pressure/io some avg10=36–50 %, full avg10=11–18 %` at rest (§5.4), `df` at 94 % during its own backup
(§5.5), and one disk for database + data + logs + everything.
**WHAT IS DIFFERENT.** The cloud box is a QEMU guest with `qemu-guest-agent` running and a provider console; the
office box's only path in was a disk-starved sshd. A wedged cloud box can in principle be reached out-of-band.
**SO WHAT.** The failure mode is not fixed, it is relocated: same single disk, same sshd-as-only-door, and 64 %
used with a backup that transiently needs 22 GB.
**FIX.** The provider console is the answer only if it is known to work and the credentials for it are valid —
and the token is currently invalid (§4.8). Verify the console path once, deliberately, and re-issue the token.
Own it: the owner (Hetzner account), then the workstream that owns `company-api`.
**CONFIDENCE.** Office side measured (recorded). Cloud pressure measured. The console recovery path is
**inferred** — it was not exercised and must not be assumed.

### 6.2 No wake path — **IMMUNE, replaced by a different dependency**

**EVIDENCE.** Office: `ethtool eno1 | grep -i wake` → *no `Wake-on:` line at all*; the register records
`ethtool -s eno1 wol g` as a silent no-op. Cloud: a virtual machine — there is no NIC to wake; it is started by the
provider API. `HETZNER_API_TOKEN` is present as a key in both `.env` files, and it is **invalid** (HTTP 401,
§4.8).
**SO WHAT.** The trap does not apply, but its replacement is a credential that is already broken. "It is a VM,
so I can always restart it" is true only while the provider account and token work.
**FIX.** Re-issue the Hetzner token and store it where it is reachable when the company is down — not only inside
the company's own `.env`. Add a probe that exercises the provider API read-only and reports failure, so a dead
token is discovered before the day it is needed.
**CONFIDENCE.** Measured for both the NIC and the token.

### 6.3 A single disk for database and backups — **EXPOSED, and WORSE than the office box**

**EVIDENCE.** Cloud: one filesystem `/dev/sda1 75G mounted /`. `/root` 24 G (the database), `/opt/company` 16 G,
`/var/log` 49 M, `/var/lib` 181 M. There is **no backup of any kind on this machine** — and none off it either
newer than 2026-10-10T05:20:09Z (§4.1).
Office: also a single disk, but it had 8 local snapshot directories and a daily R2 push, and the newest *complete*
one is `20261010T180001Z` (`COMPLETE` marker present, `control-plane.tgz` 1,481,453,861 B +
`personal-secretary-code.tgz` 29,975,053 B). Its two newest snapshots — `20261011T000001Z` and
`20261011T025626Z` — have **no `COMPLETE` marker** (`find /home/zabz/secretary-backups -maxdepth 2 -name COMPLETE`
returns six stamps, none newer than `20261010T180001Z`). So the old chain was already degraded, and the new
authority has none.
**SO WHAT.** This is strictly worse, not equal. Today the company's database exists in exactly two places, both
stale: a frozen office snapshot (1.5 h behind) and an R2 object from 2026-10-10 05:20Z (25 h behind).
**FIX.** Two independent destinations and a freshness monitor that reports **absence** (§6.7). The scripts now
exist on the cloud (`/usr/local/bin/authority-offsite-backup.sh` 05:55Z, `authority-report-offsite-age.sh`,
`authority-deadman.py` 06:20Z) but nothing schedules them.
**CONFIDENCE.** Measured.

### 6.4 A watchdog that restarted services during a freeze — **IMMUNE in the same shape; the real finding is that the freeze was narrower than claimed**

**EVIDENCE.** Office: `H3407` §3 — after the first stop, `secretary-api` was `ActiveState=active` again 90 s
later with a new MainPID; the timers **and their `.service` siblings** had to be stopped and disabled.
Cloud: `systemctl list-timers --all` shows only OS timers (`sysstat-*`, `apt-daily*`, `logrotate`,
`systemd-tmpfiles-clean`, `e2scrub_all`, `motd-news`, `update-notifier-*`, `fstrim`, `man-db`). There is no
watchdog unit on the new authority at all, so a supervisor cannot fight an operator.
**THE REAL FINDING.** Measured on the office box at 06:24Z — **six timers are still active on the "frozen" box**,
and two of them fired within the previous ten minutes:
`estate-monitor.timer` (*last run 06:22:02, next 06:24:02*), `tmp-reaper.timer` (last 06:15:03),
`fa-index.timer` (last 06:17:02), `trunk-check.timer` (last 06:14:32), `fwupd-refresh.timer` (last 06:07:33),
`sysstat-collect.timer` (last 06:20:03), and `company-outcome-monitor.timer` = **`active / enabled`**, which has
already run **since the freeze** (last 04:07:00, next 08:07:00). On top of those: `/home/zabz/heartbeat.sh` (an
`@reboot` orphan, PID 1673, `while true; do …; sleep 60; done`) is still looping, and
`eliyahuzabrowsky_at_gmail_com_token.json` in both `gmail_tokens/` and `calendar_tokens/` was rewritten at
**05:58:18Z** — 1 h 12 min after the box was declared frozen — while `secretary.db-shm` shows an open at
**06:07:33Z**.
**SO WHAT.** `H3408`'s "Office box `secratary-ts` confirmed frozen and not writing" is true of the *company
database* and false of the *box*. What is verified is narrower and should be stated that way: **`secretary.db` is
unchanged (mtime 04:28:35.685490725Z, `FROZEN` marker: `frozen 2026-10-11T04:46:27Z lsof=0
size=23622823936 snapshot=23622823936`)**, plus `secretary.db-wal` = **0 bytes**. Six systemd timers, one orphan
shell loop, a GitHub Actions runner (`/opt/actions-runner/runsvc.sh`), a VS Code tunnel (`code tunnel --name
ezabz-secretary`) and `phone-gate.py` are all still running on it. Nothing currently writing is a *writer of the
database*, and that is why the freeze holds — not because the box is idle.
**FIX.** Sharpen the freeze definition and its check from "cron is masked" to the property that matters:
"no process holds a write handle on the database, and no timer, orphan or runner can start one". Concretely: stop
`estate-monitor.timer`, `tmp-reaper.timer`, `fa-index.timer`, `trunk-check.timer` and
`company-outcome-monitor.timer` on the office box (they are not in the rollback set at all — `H3407`'s list names
only the three watchdogs and the five writer units), and re-run `lsof` as the acceptance test rather than
`systemctl is-active cron`. Own it: whoever owns the office box until the rollback window closes.
**CONFIDENCE.** Measured.

### 6.5 `systemctl mask` not working — **EXPOSED, same file layout, and now MEASURED on both sides**

**EVIDENCE.** `H3407` §2: `Failed to mask unit: File '/etc/systemd/system/secretary-api.service' already exists`.
Reproduced as a fact on the office box:
`systemctl show secretary-api.service -p FragmentPath` → `FragmentPath=/etc/systemd/system/secretary-api.service`.
And on the cloud box, `systemctl cat company-api` → first line `# /etc/systemd/system/company-api.service`.
`systemctl mask` writes its `/dev/null` symlink into `/etc/systemd/system/<name>`, and the unit file is already
there — so **`systemctl mask company-api` on the new authority will fail exactly the same way**. Measured where it
does work: `ls -l /etc/systemd/system/cron.service` on the office box → `-> /dev/null`, because `cron.service`
lives in `/usr/lib/systemd/system` and not in `/etc/systemd/system`.
**SO WHAT.** Any future runbook that says "mask it" will half-work: it works for the distro's units and fails for
this estate's, which are the ones that matter. Under pressure that is a silent partial freeze.
**FIX.** Use `disable --now` (which is what actually stopped the writers on the office box) and put the reason in
the runbook next to the word "mask". Better: give the estate a one-line `freeze` script whose acceptance test is
`lsof <db>` = 0, so the mechanism is the property and not the verb.
**CONFIDENCE.** Measured.

### 6.6 Cron jobs whose commands are base64-opaque to guards — **EXPOSED AND WILL BE PORTED VERBATIM**

**EVIDENCE.** The crontab's own form: line 117 is
`*/5 * * * * /home/zabz/bin/cron-wrap.sh deadman L3Vzci9iaW4vcHl0aG9uMyAvaG9tZS96YWJ6L2Jpbi9kZWFkbWFuLnB5ID4+IC9ob21lL3phYnovLnNtcy1pbmJveC9kZWFkbWFuLmxvZyAyPiYx`
which decodes to `/usr/bin/python3 /home/zabz/bin/deadman.py >> /home/zabz/.sms-inbox/deadman.log 2>&1`.
`grep -nE "base64|b64|decode" /home/zabz/bin/cron-target-guard.py` → **no matches in 468 lines**: that guard never
decodes the blob, which is why it reports `ok / 0 missing` over ~60 jobs that are all the same wrapper.
**A sibling guard already solves it**: `cron-script-guard.py` imports `base64` and has
`def decode_wrapped(line)` at line 74, `base64.b64decode(tok, validate=True)` at line 80, and decodes at line 129.
So the estate has both a blind guard and a seeing one — and the blind one is the one whose "ok" is believed.
**SO WHAT.** Porting the crontab unchanged carries the blindness onto the new authority, where the guard will
again report health it has not checked. `H3408` already flags this; the measurement above is the mechanism.
**FIX.** When the crontab is ported, either retire `cron-target-guard.py` in favour of `cron-script-guard.py`, or
give the former the latter's `decode_wrapped`. One function. Own it: the workstream porting the crontab.
**CONFIDENCE.** Measured.

### 6.7 Guards whose failure has never been seen — **EXPOSED, and this is the most consequential finding in this document**

**WHAT.** The external dead-man switch — the only mechanism that can report the authority being dead from outside
it — was already dead 5 hours 18 minutes before the authority moved, and nothing exists on the new authority to
replace it.

**EVIDENCE.**
- The job: crontab line 117, `*/5 * * * * … cron-wrap.sh deadman …` → `deadman.py`, which pings an external
  healthchecks.io check (`/home/zabz/.sms-inbox/deadman.env`, 133 B, mode 600; `HEALTHCHECKS_API_KEY` is **not**
  among the 301 `.env` keys, so it comes from elsewhere).
- Its own run log, `/home/zabz/.cron-status/runs.tsv` (95,456 lines, 2,378 `deadman` rows):
  **the last deadman run is `2026-10-10T22:45:02Z`, exit 0.** The file's last lines overall are
  `2026-10-11T04:00:02Z run-wake-sources 0 182`, `… dialpad-harvest-cron 0 500`, `… sync 0 1001` — so cron was
  still writing at 04:00, and `deadman` had stopped 5 h 15 min earlier. On a `*/5` schedule that is ~63 missing runs.
- The dark window was `2026-10-11T02:14:30Z → 05:43:36Z` (`H3407`), i.e. **entirely inside the period when the
  dead-man switch was already silent**. The owner's 3 h 29 min of darkness produced no external alarm, because the
  thing that raises it had stopped.
- The new authority has no scheduled dead-man: cloud `crontab -l` → `no crontab for root`. A workstream did install
  `/usr/local/bin/authority-deadman.py` (6,628 B, mode 700) at **06:20Z — during this measurement session** — but
  nothing schedules it and `/var/lib/authority-backup/last-run` does not exist, so the freshness reporter would
  have nothing to report on either.
- The other three external-reporter jobs tell the same story: `transcript-archive` last ran
  `2026-10-10T22:23:01Z` with **exit 3**; `company-offsite-push` last ran `2026-10-10T19:40:01Z` with **exit 1**
  and its two predecessors also exit 1; `report-offsite-age` last ran `2026-10-10T22:30:01Z` exit 0. Only
  `push-db-offsite` succeeded late (`2026-10-10T05:10:01Z`, exit 0).

**SO WHAT.** The entire external safety chain — the dead-man switch, the transcript-archive alarm, the offsite
push and the offsite-age reporter — was already failing or silent *before* the cutover, and not one of them moved.
The company is therefore in the exact state the estate's oldest failure describes: every heartbeat this system
keeps is read by something on the authority, so if the authority dies, **its own health checks die with it and the
owner learns nothing.** That is now literally true, by measurement.

**FIX.** One thing, first: schedule `authority-deadman.py` on a machine that is not the authority (or fix and
re-arm the healthchecks.io check from wherever cron runs), and give the offsite-age reporter the same treatment —
a reporter that lives on the thing it reports on is not a reporter. Then re-run the same `runs.tsv` evidence next
week and require the *absence* of a run to be the alarm. Own it: the offsite/backup workstream, escalated to the
owner only for the choice of external endpoint.
**CONFIDENCE.** Measured for the last run times, the exit codes and the missing schedule. *Why* deadman stopped at
22:45 on 10-10 is **not determined** — the crontab still contains it, so the schedule was not removed; a
`cron-wrap.sh` fault, a lost crontab reload, or a per-job guard are all consistent with the evidence.

### 6.8 A public hostname resolving to a different machine than expected — **EXPOSED, with one live instance**

**EVIDENCE.** From the laptop, measured:
`https://dialer.abletelsolutions.com/` → **502** (`0.220 s`), while `https://api.abletelsolutions.com/health` → 200
and `https://ai.abletelsolutions.com/health` → 200. `H3407`: "there is no unit, no cron entry, no file mentioning
`8899`, no `server.js`, and nothing in the journal that ever served that port… It should be resolved or the rule
deleted, not carried." Register §2.1 (`D3040`): `dialer.` and `secretary-ssh.` deliberately stay on the office
tunnel. And `secretary-ssh.abletelsolutions.com`: `Test-NetConnection -Port 22` → **`TcpTestSucceeded: False`,
remote `2606:4700:3034::ac43:ac99`** — a Cloudflare address, i.e. the name is proxied and cannot carry SSH.
**SO WHAT.** Two of the four public hostnames do not describe the machine the reader assumes. One of them returns
502 to anyone who asks, and the other advertises SSH and cannot carry it. The register's authority-status header
(which names only `api.` and `ai.`) is correct; everything else that repeats "the four hostnames" is not.
**FIX.** Decide and record, once: either delete the `dialer.` ingress rule and the DNS record, or point it at the
prototype that was meant to serve it. For `secretary-ssh.`, either un-proxy the record (grey cloud) or delete the
hostname and use the tailnet — there is no third answer that works through Cloudflare's proxy on port 22.
Own it: the owner (he chose to keep them office-bound) for the decision; DNS work for whoever owns the tunnel.
**CONFIDENCE.** Measured.

### 6.9 Byte-count verification proving transport but not content — **EXPOSED; the new chain has never been verified end to end**

**EVIDENCE.** The cutover's own verification was good and included content checks
(`PRAGMA integrity_check` = ok on both sides, page geometry `4096 / 5,767,291`, 231 tables,
`dsh_session_events` = 1,856,458, `max(rowid)` equal, FTS `MATCH 'the'` = 637,169 — `H3407`). But the *new*
chain has produced exactly two objects, and only one of them is the database's:
`list_objects_v2(Bucket=…, Prefix='authority/')` → `authority/secretary.db.gz` **7,234,886,331 B,
2026-10-10T05:20:09Z** (the OLD office push), `authority/accounting.db.gz` 426 B and
`authority/accounting.db.gz.sha256` 83 B, both **2026-10-11T06:18:06Z**. So a new-authority push ran at 06:18Z,
uploaded the tiny empty accounting DB and its digest, and did **not** produce a new `authority/secretary.db.gz`.
`psm-backups/` under the same bucket → **0 objects** (the restic "Box 2" path; note this credential is scoped to
one bucket, so a repository in another bucket would be invisible — see §7).
**A related trap, measured, and it is worth one line of its own:** reading a live WAL database with
`sqlite3 "file:…?mode=ro&immutable=1"` reported `pragma journal_mode` = **`delete`**, while the same file read
`mode=ro` reported **`wal`**. The row counts agreed (`1,860,394` both ways), so the hazard did not bite here — but
an immutable read of a live WAL database returns *metadata from the main file alone*, and a decision made from it
would be made on a stale header. That is the same shape as the estate's worst recorded failure (a stale copy read
and believed).
**SO WHAT.** "The upload succeeded" currently means "the bytes arrived". No one has ever downloaded
`authority/secretary.db.gz`, decompressed it, opened it and checked it — and the first new-authority database push
has not happened at all. Also note `push-db-offsite` last succeeded 2026-10-10T05:10:01Z and has a
`sha256` sidecar for the *old* object; the sidecar that exists for the new one is for the accounting DB.
**FIX.** Make the offsite script's own definition of success "download the object to a scratch path, verify the
sha256, `PRAGMA integrity_check`, and compare a cheap fingerprint (table count + one `max(rowid)`) against the
live database" — and, given §5.5, do the download on a disk that is not the authority's. Until that runs, the
offsite copy is a transport claim, not a backup.
**CONFIDENCE.** Measured for the object list, the sizes, the timestamps and the journal_mode discrepancy.
**One more trap of this exact class, on the new authority, unproven but loaded:**
`/opt/company/data/secretary.db` is a **1,826,816 B, 145-table database created 2026-10-11 01:18Z** sitting at the
path the app would use if `DATABASE_URL` were ever unset or mis-set. The unit's own drop-in documents that this
file was created precisely that way: *"A DB PATH THAT IS WRONG IS NOT A CRASH. It is a silent new empty database:
before this was understood, starting the service created /opt/company/data/secretary.db, bootstrapped 31
departments into it, and served from it. Anything that starts this unit with a mis-set path serves an EMPTY company
and looks healthy doing it."* It also records that `Environment=` cannot override `EnvironmentFile=` for the same
key, and that the only effective place is the `DATABASE_URL` line in `/opt/company/.env`. **FIX:** delete the decoy,
or move it out of the tree and leave a README in its place; and make the app's startup refuse to serve when the
opened database has fewer than N tables. **CONFIDENCE:** measured (file size, table count, mtime, and the quoted
drop-in).

---

## §7 — WHAT I COULD NOT DETERMINE

Stated plainly, because an empty result is not health.

1. **Whether `secratary-cloud` has a provider-level backup or snapshot.** The only token available
   (`HETZNER_API_TOKEN` in `/opt/company/.env`) is **invalid** — `https://api.hetzner.cloud/v1/servers` → `401
   {"code":"unauthorized","message":"the token you have provided is invalid"}`. The new authority does contain
   `/opt/company/deploy/hosting-migration/scripts/hetzner-backup.sh`, `hetzner-restore.sh` and
   `monitor-hetzner-backups.sh`, so a mechanism is *named*; whether it is enabled for this server is unknown. Until
   this is answered, treat 4.1 as "one copy, 25 hours stale".
2. **Whether the restic "Box 2" repository exists at all.** Prefix `psm-backups/` in the bucket this credential
   can list holds **0 objects**; the credential is scoped to one bucket, so a repository in another bucket is
   invisible from here. `company-offsite-push` exited 1 on its last three runs (07:40, 13:40, 19:40 on 10-10),
   which suggests it is broken, but the repository's existence was not tested.
3. **Why the dead-man switch stopped at 2026-10-10T22:45:02Z.** The crontab still contains the job. A
   `cron-wrap.sh` fault, an un-reloaded crontab, or a per-job guard are all consistent with `runs.tsv`. The job
   was not run to find out, because running it on the frozen box would be an outbound ping from the authority.
4. **Why four more timers are still active on the frozen office box** (`estate-monitor`, `tmp-reaper`, `fa-index`,
   `trunk-check`). They are not in the freeze list in `H3407` and their unit files were not read. Whether any of
   them can write is unknown; two of them (`tmp-reaper`, `fa-index`) plausibly can.
5. **Whether the office box's write path to the database is truly closed**, as distinct from currently unused. The
   evidence is strong — `lsof secretary.db` empty, WAL 0 bytes, main-file mtime unchanged since 04:28:35Z — but
   six timers, one orphan shell loop and a GitHub Actions runner are live on that machine, and the Actions runner
   in particular can execute arbitrary code from a repository event. Not tested; it should be.
6. **What `estate-monitor.timer` and `company-outcome-monitor.timer` do when they fire on the frozen box.** The
   latter is documented in its own unit file as "read-only; independent of secretary-api"; the former's unit file
   was not read. Both have run since the freeze.
7. **Which of the 92 crontab jobs are already redundant** with an in-process autopilot subsystem. I measured that
   all 39 subsystems are present and that 92 jobs are absent; I did not attempt the mapping, and doing it badly
   would overstate the gap as much as understate it.
8. **The office box's API response times for the §5.1 endpoint set.** They cannot be taken without starting the
   office API, which the freeze forbids. The recorded 4 s `/mesh/health` timeout is quoted with its source and is
   not a substitute.
9. **Whether the office box's private keys for the estate are held anywhere else.** `~/.ssh/id_ed25519_hetzner`
   was confirmed on this laptop and the authority's `authorized_keys` was counted (one key); the other nodes'
   `~/.ssh` directories were not enumerated (my one attempt targeted a Windows host with a POSIX command and
   failed — the check itself was not completed).
10. **The agent count that is actually working.** 126 identities were counted on both boxes. How many are
    `running` this hour is not in that file; it would come from `ctx.agents.list()` or a DB state column that was
    not queried.
11. **`/root/authority.db.new` (0 bytes, 05:41Z)** — an artefact of the cutover. What created it and whether
    anything still writes to that path is unknown. Safe to delete, but I did not.
12. **The Hetzner `dialer.`/`secretary-ssh.` decision** is the owner's, not a measurement, and it is recorded in
    §6.8 as such.

---

## APPENDIX — every command behind a claim, in one place

Machine `Y` = this laptop (ZABZ-YOGA); `O` = `ssh secratary-ts`; `C` = `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`.

| claim | machine | command |
|---|---|---|
| failover never ran | Y | `subagent("<trivial>")` → `remote-ssh: broker-unreachable … curl: (7) …localhost:3091` |
| ledger says the raw error escaped | Y | read `.dsh\mesh\placements\remote-cfbf76fd-…json` |
| engine boot time | Y | `Get-CimInstance Win32_Process -Filter "Name='node.exe'"` → PID 10668, 10/7/2026 8:33:13 PM |
| failover commit date | Y | `git log --date=iso --format='%h %ad %s' -- packages/plugin-remote-fanout/lib/failover-placer.js` |
| failover is ON by default | Y | `lib/index.js:288`, `provider.js:504`, `placement.js:380,407` (read) |
| live row does not disable it | Y | `select-string remote-fanout\|placementFailover` in `.dsh\profiles\web\cordis.patch.yml` |
| probe would have worked | Y | `Invoke-WebRequest https://zabz-tech.tail93e6e6.ts.net/mesh/health` → 200 (657 ms); yoga-1 → 200 (211 ms) |
| broker absent everywhere | O/C | `systemctl is-active mesh-broker`; `ss -ltnp \| grep 3091` |
| tailnet absence | Y/O/C | `tailscale status --json`; `which tailscale`; `getent hosts …ts.net` |
| 39 subsystems both sides | O/C | `python3 -c` over `autopilot_state.json` |
| finance regression | C | same file → `quickbooks-agent repo not found at /opt/company/domains/finance/quickbooks-agent`; `ls -d /opt/company/domains` |
| 126 agents both sides | O/C | `python3 -c` over `agent_identities.json` |
| `.env` key parity | Y | key+length-class extraction and `Compare-Object` (301 vs 302, 0 class differences) |
| 92 cron jobs missing | O/C | `grep -vcE "^\s*(#\|$)" /home/zabz/cutover/crontab.before` = 92; `crontab -l` on C |
| HA unreachable | C | `getent hosts <HA_URL host>` empty; `curl -w %{exitcode}` → 6 |
| `/phone` redirects to the tailnet | C | `curl -D - http://127.0.0.1:3087/phone` → `Location: https://secratary.tail93e6e6.ts.net` |
| family chat 1 vs 3156 | O/C | `sqlite3 "file:…family_chat.db?mode=ro&immutable=1" "select count(*) from messages;"` |
| R2 offsite state | C | `boto3 list_objects_v2(Prefix='authority/')` and `('psm-backups/')` |
| OOM | C | `journalctl -k --since 2026-10-09 \| grep -iE "out of memory\|oom-kill\|Killed process"` |
| memory now | C | `free -m`; `ps -eo pid,rss,pmem --sort=-rss`; `systemd-cgtop -n1`; `vmstat 1 3` |
| disk 94 % → 64 % | C | `df -h /` twice, 06:09:32Z and 06:20:50Z; `tail /var/log/authority-offsite.log` |
| pressure at rest | C | `date; cat /proc/pressure/{cpu,memory,io}; sleep 90; date; cat …` |
| office SSD not spinning | O | `lsblk -d -o NAME,ROTA,SIZE,MODEL`; `cat /sys/block/sda/queue/rotational` |
| six timers live on the frozen box | O | `systemctl list-timers --all --no-legend` |
| token touching after the freeze | O | `ls -la --time-style=full-iso …/gmail_tokens …/calendar_tokens` → 05:58:18Z |
| mask would fail identically | O/C | `systemctl show secretary-api.service -p FragmentPath`; `systemctl cat company-api` |
| guard blindness | O | `grep -nE "base64\|b64\|decode" /home/zabz/bin/cron-target-guard.py` (0) vs `cron-script-guard.py` (lines 25,74,80,129) |
| dead-man stopped | O | `grep deadman /home/zabz/.cron-status/runs.tsv \| tail -2` → last `2026-10-10T22:45:02Z`; `tail -3` of the file → `2026-10-11T04:00:02Z` |
| dead-man body | Y | base64 decode of crontab line 117 → `/usr/bin/python3 /home/zabz/bin/deadman.py >> …/deadman.log 2>&1` |
| deadman's own doc | O | `head -30 /home/zabz/bin/deadman.py` |
| invalid provider token | C | `curl -H "Authorization: Bearer $HETZNER_API_TOKEN" https://api.hetzner.cloud/v1/servers` → 401 |
| public latency | Y | `curl -o NUL -w "%{time_total} %{http_code}" --max-time 30 <url>` × 5 |
| decoy empty company DB | C | `ls -l /opt/company/data/secretary.db` (1,826,816 B); `sqlite3 … "select count(*) from sqlite_master where type='table'"` (145); drop-in text |
| `immutable` read gives a stale header | C | `pragma journal_mode` → `delete` via `immutable=1`, `wal` via `mode=ro`; `max(rowid)` equal (1,860,394) |

**END OF 135.**
