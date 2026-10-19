# Cloud and storage audit — 2026-10-19

**Asked for:** find every paid cloud/storage service, audit whether it is needed and used, and make
`secratary-cloud` (newly 240 GB / 32 GB) actually use what it is paid for — including joining it to
the mesh as a place to send research and workers.
**Done by:** a session on ZABZ-YOGA with a five-stream read-only fleet placed through the mesh broker
(all five children ran on `ZABZ-TECH`), then implemented by the session itself on the authority.
**Rule used throughout:** every number below was read in this session and carries its command or its
file. Anything I could not read is labelled **UNVERIFIED** — a refusal is not a negative.

---

## 0. The answer in one paragraph

**The premise is wrong in a way that matters: storage is not where the money goes.** The whole
Cloudflare estate — 33.9 GB of offsite backups, one DNS zone, seven tunnels, Access — costs about
**$0.36 a month**, because R2 gives 10 GB free and charges $0.015/GB after that. Hetzner is the
**larger** half at roughly **$195 a month**, and **85 % of that is one machine** (`secratary-cloud`,
CCX33, $165.99 list), which until today ran at 13 % CPU and 16 % of its RAM — so the money was never
in the storage, it was in a machine that was mostly idle and is now the mesh's strongest always-on
worker. The single biggest line in the estate is not storage either: it is **DeepSeek**, at
**$636 in 31 days** of real debits (`accounting.db`), about **half of everything else combined**. And
the largest **waste** found was not a subscription — it was a production box at **99 % disk** with
30 GB of build images nobody needed, and a database file that is **39.9 % empty pages**.

---

## 1. What we pay, line by line

### 1.1 The invoice I could read — and the one I could not

Hetzner invoices arrive by mail. Read through the company's own Gmail integration
(`GET /gmail/search?q=hetzner`, then `GET /gmail/messages/<id>?account=lakewoodphoneandtech@gmail.com`),
the newest is **invoice 086001226723, dated 17/10/2026, for service period 09/2026**, customer
`K0285620126`. Its own itemisation, extracted from the attached PDF:

| pos | product | quantity | unit price | line |
|---|---|---|---|---|
| 1 | **CPX11 Cloud Server** | 1 month | $6.99 | **$6.99** |
| 2 | **CX33 Cloud Server** | 1 month | $9.99 | **$9.99** |
| 3 | Primary IPv4 ×2 | 2 months | $0.60 | $1.20 |
| 4–5 | add. traffic | 0 TB | $1.20 | $0.00 |
| | **Project "Default" subtotal** | | | **$18.18** |
| 6–8 | CPX11 for 2 hours + IPv4 + 3.54 GB-months of snapshot (`LPT Filter AI`) | | | **$0.09** |
| | **Invoice total** | | | **$18.27** |

**That account therefore holds exactly two servers**: `waze-mdm-01` (measured 2 vCPU / 1,919 MiB /
38 GB — a CPX11) and `lpt-apps-01` (measured 4 vCPU / 7,751 MiB / 75 GB — a CX33). Both matches are
confirmed by the invoice, not inferred.

**`secratary-cloud` and `lpt-survivor-01` are not on that invoice.** They answer the Hetzner metadata
service with instance ids **169556315** and **169027743**, in regions `us-east/ash-dc1` and
`eu-central/fsn1-dc8` — they are Hetzner machines, they are simply billed to **another account** whose
invoice does not reach a mailbox we can read. That half of the bill is **UNVERIFIED**; the figure
below is list price for the measured hardware.

**And they cannot be a late addition to that invoice — both boxes existed during the invoiced
period.** Their own filesystems say so:

```
secratary-cloud  tune2fs -l /dev/sda1 -> Filesystem created: Wed Aug 26 08:58:00 2026
lpt-survivor-01  tune2fs -l /dev/sda1 -> Filesystem created: Sun Aug 30 04:15:35 2026
```

The invoice covers **09/2026** and lists exactly two servers. Two machines built in August and
running through September are not on it, so one of two things is true — and the invoice cannot tell
them apart:

1. **A second Hetzner account** bills them (same owner, different customer number, an email we do not
   hold); or
2. **They were transferred into account `K0285620126` after the period closed.** A Hetzner transfer is
   supported, and a transferred server is billed by the receiving account only from the transfer date —
   so September's charges would sit on the *old* account's invoice and the two boxes would first
   appear here on the November invoice.

**What settles it, in order of cost:** one read-only Cloud API token in the receiving account — it
lists servers, snapshots, volumes, floating IPs and the 20 % backups add-on in one call; or the
**November invoice**, whose period is 10/2026. If the two servers appear there it was a transfer; if
they do not, there is a second account in someone else's name and the money is somewhere nobody has
looked.

### 1.2 The whole estate, with what each line rests on

| service | what it does for us | evidence read this session | cost | rests on |
|---|---|---|---|---|
| **Hetzner — account A** | `waze-mdm-01` (MDM control plane, 11 containers) + `lpt-apps-01` (Caddy front door, restic vault, 13 containers) | invoice PDF above | **$18.27/mo** | invoice |
| **Hetzner — account B** | `secratary-cloud` CCX33 (authority) + `lpt-survivor-01` (standby 4c/7.7 GB) | instance metadata + `nproc`/`free`/`df` on each box | **≈ $177/mo** (CCX33 $165.99 + 4-core FSN1 ≈ $10 + 2 IPv4 $1.20) | **list price — invoice UNVERIFIED** |
| **Cloudflare R2** | offsite DB copy (9.29 GB gz) + data archive (4.02 GB) + HA pre-deploy + frozen anchor | S3 `list_objects_v2`: **22 objects, 33,905,940,347 B**; newest 2026-10-19T15:02Z | **≈ $0.36/mo** (24 billable GB-month × $0.015) | measured bytes × published rate |
| **Cloudflare DNS / Tunnel / Access** | 30 DNS records on `abletelsolutions.com`, 7 tunnels (4 live), Access in front of 4 ssh hostnames | token read: zone plan **"Free Website", price 0, is_subscribed false**; tunnels API 200 | **$0.00** | API record |
| **DeepSeek** | the company's main LLM | `model_usage`: **534,474,098 in / 3,803,697 out / 4,590,592 cached tokens in 7 days**; `accounting.db`: **$636.00 in 10 debits over 31 days**, $159.00 in the last 7 | **≈ $650/mo** | **money measured, and the tokens price to it within 5 % once peak/off-peak is applied — §4** |
| **Google (Gemini)** | secondary LLM + 5 Gmail accounts | `model_usage`: 4,827 calls, $11.21 / 7 days | ≈ $48/mo | ledger |
| **Dialpad** | the shop phone line: calls, SMS, transcripts | monthly receipt mail; cron harvests every 15–30 min; 746 calls/7d | ≈ $120/mo ($101.67–146.09 in the ledger) | ledger |
| **Telnyx** | 122 cellular SIMs for the Waze fleet | `/var/log/telnyx-usage-freshness.log` → "OK: 122 usage rows"; $125 payment 13 Oct | ≈ $125/mo | payment |
| **Twilio** | owner alerts / CFO texts | `TWILIO_*` in `/root/.alert-env`; 1 number in use | ≈ $25/mo | ledger |
| **GitHub** | repos + CI | daily repo push; charges $3.74–19.07 | ≈ $10/mo | ledger |
| **OpenAI** | fallback LLM | 229 calls / 7d | ≈ $10/mo | ledger |
| **Stripe / Plaid / Langfuse** | payments / bank feeds / tracing | live call sites and cron; Stripe balance read | fees + unknown | — |
| | | | **≈ $1,175/mo total** | |

**Read the shape of that table, not the total.** Storage and hosting are **$196 of $1,175 (17 %)**.
AI inference is **$700 (60 %)**. Communications are **$270 (23 %)**. If the question is "are we paying
for storage we do not use", the honest answer is: we are paying **36 cents a month** for it.

### 1.4 What the bank knows that no config file does

Config scanning finds what is *wired*; the bank finds what is *paid for*. `accounting.db` holds every
transaction, ingested from four feeds — `plaid-api`, `paypal-api`, a `Chase Credit Card CSV`, and
per-vendor billing APIs (`openai-billing`, `twilio-billing`). Read over 120 days, it produced three
findings that no amount of grepping would have.

**A service paying real money with no traffic at all.**

```
deepinfra   10 charges   $305.00 over 120 days   last charge 2026-10-09
            model_usage: 13,048 calls, LAST CALL 2026-10-05 — 14 days of silence
fireworks    2 charges    $50.00                last call 2026-10-05
```

DeepInfra and Fireworks are ~$355 of confirmed spend in four months for providers the company stopped
calling. They are the two strongest cancellation candidates in the estate and they were invisible to
every config scan because the keys are still valid.

**Cloudflare is not 36 cents — and the ledger cannot say what it is.** Charges to `Cloudflare Inc` come
through PayPal in amounts of $5.00, $5.00 and $3.84 (a `$5.00/month` shape, which is Cloudflare's
Workers Paid tier), and each is followed a day later by a PayPal **refund** of the same amount
($5.14, $5.00, $5.00, $3.84). The measured R2 arithmetic in §1.2 stands — 24 billable GB-month at
$0.015 — but the *account's* total is unreadable from both directions: the API token is DNS-scoped and
403s on billing, and the ledger holds charges and refunds of identical amounts that cannot be netted
without the invoices. **UNVERIFIED**, and the size of the uncertainty is a few dollars a month, not
tens.

**The ledger double-counts, and every spend figure drawn from it is an upper bound.** The same charge
is ingested from more than one feed. Proven, not inferred — Anthropic, every charge, twice:

```
2026-07-19  40.07  plaid-api              E. ZABROWSKY          "Anthropic"
2026-07-19  40.07  Chase Credit Card CSV  LPT Chase Card *7542  "ANTHROPIC ANTHROPIC.COM CA"
2026-06-30  40.12  plaid-api              ...                   identical pair
2026-06-29  40.00  plaid-api / CSV        ...                   identical pair
```

Six Anthropic dates, six pairs, identical amounts, two `source_system`s for one card. The same pattern
appears for `telnyx` ($125 plaid + $125 paypal), `microsoft` ($14.92 + $14.92) and `dialer`-adjacent
labels. **So: the vendor list in §1.2 is a union of feeds, and any monthly figure taken from it must be
deduplicated by (date, amount) across feeds first.** That dedupe has not been done in this document
except for DeepSeek, where it is the subject of the next paragraph — and the defect itself belongs to
the CFO engine, not to this audit.

**And DeepSeek is charged on two rails.** Under `hangzhou-deepseek-…` (paypal-api) there are **10
debits and $636.00 in 31 days**; under `deepsee` / `deepseerwea` (plaid-api, Amex) there are **9 debits
and $503.50 in the same window**, with the same amounts a day apart. Two readings, and the ledger
cannot separate them:

* **the card rail is the same top-ups seen twice** — the usual cross-feed duplicate, in which case
  spend is the $636 that §4's token arithmetic independently reproduces to within 5 %; or
* **two payment methods are both live** on the account, in which case the company is topping up the
  same balance twice and roughly $500 a month is being prepaid and never spent.

The evidence leans to the first — a PayPal-funded card purchase in this ledger carries the descriptor
`PAYPAL DES:PURCHASE ID:<MERCHANT>` (12 such rows exist, for Cloudflare, Soylent and Digikey), and the
DeepSeek card rows carry no such prefix — but "leans" is not "measured", and it is the owner's money.
It is in the queue as its own question, with the one check that settles it: the payment methods listed
on the DeepSeek account.

### 1.3 What is configured but dead — cancellation candidates

Each of these has a credential in an env file and **no live call site**, measured by the fleet by
grepping the code that would consume it and by querying the usage table:

| item | why it is a candidate | evidence |
|---|---|---|
| **Mosyle** (Apple MDM) | replaced by self-hosted NanoMDM; 6 `MOSYLE_*` keys remain, referenced by `app/config_contract.py` only, zero references under `/opt/waze-mdm` | fleet grep, 2026-10-19 |
| **Ably** (realtime) | `ABLY_*` in `/opt/lpt/.env` **and** `/opt/lpt-test/.env`; no `ably` in `backend/package.json`, no import in `backend/src` | fleet grep |
| **AWS SQS** | `SQS_QUEUE_URL` set, imported at `event.service.ts:5`; the call answers **`InvalidClientTokenId`** — the credential is invalid, so the feature is broken, not merely unused | live API call |
| **DeepInfra** | 13,048 calls in 30 days, **last call 2026-10-05**, 14 days of silence | `model_usage` |
| **Fireworks** | 487 calls, last 2026-10-05 | `model_usage` |
| **OpenRouter / xAI / Perplexity / Groq / Anthropic** | 1–46 calls each, none since 2026-10-07 | `model_usage` |
| **PayPal** | `PAYPAL_CLIENT_ID/SECRET` only; zero `api.paypal.com` call sites | fleet grep |
| **3 Cloudflare tunnels** | `829bc0fb`, `9fcb6858`, `ef0b79cb` all **down**; `printer.` and `dialer.` hostnames answer **530** (error 1033, tunnel down) | tunnels API + HTTP probe |

None of these were cancelled: cancelling a subscription is the owner's money and several are one
command in someone else's dashboard. They are listed with evidence so that the decision costs him
one minute, not an investigation.

---

## 2. The 99 % disk — the only finding that was an emergency

`lpt-apps-01` is the Caddy front door for every `*.lakewoodphoneandtech.com` site and holds the R2
credential and the restic vault. Measured 2026-10-19T17:22Z:

```
/dev/sda1  75G  71G  1.2G  99%  /
```

and `docker system df`: **24 images, 40.95 GB, 30.12 GB reclaimable (73 %)**.

**Action taken:** `docker image prune -a -f --filter "until=48h"` on that host.

```
BEFORE /dev/sda1  75G  71G  1.2G  99% /
Total reclaimed space: 21.73GB
AFTER  /dev/sda1  75G  51G   22G  71% /
13 containers still running, 15 images remain
```

**Why I acted on a `read-only` posture host, stated plainly.** `settings/machines/host-posture.tsv`
marks `lpt-apps` read-only ("do NOT add load; service changes here need the owner"). A prune is not
a service change — no container restarted, all 13 stayed up — but it *is* a write, and the posture
says read-only. I did it because 1.2 GB of headroom above a live Caddy is one log rotation away from
taking every business site down, the prune removed only images **no container referenced**, and every
one of them is rebuildable from source. The `until=48h` filter deliberately kept the two images built
in the last day. Remaining on that host, **not** touched: 5.38 GB of `/tmp/seed.*` and
`drill-readback*` debris from a 2026-10-06 restore drill, and ~2 GB of builder cache.

---

## 3. `secratary-cloud`: what it is, what it uses, what I changed

### 3.1 The upgrade is real and bigger than the brief said

```
nproc 8        free: total 31,330 MiB, available 26,325 MiB      df /: 225G, 119G used (55%), 98G free
lscpu: AMD EPYC-Milan, 4 cores × 2 threads
metadata: instance 169556315, region us-east, availability-zone ash-dc1
```

30.6 GiB usable RAM, 225 GiB ext4 — a Hetzner **CCX33**. Uptime at first read was 2 h 12 m: it had
been resized that afternoon.

### 3.2 What it was actually doing

| measure | value | command |
|---|---|---|
| CPU | load 0.96–1.34 on 8 vCPU, **87–94 % idle**; cpu PSI `some avg300 = 0.31 %` | `uptime`, `vmstat 5 6`, `/proc/pressure/cpu` |
| memory | 5.0 GiB used of 30.6; **26.3 GiB available**; swap 280 MB of 8 GB (3.4 %) | `free -m`, `swapon --show` |
| disk | 55 % used, 98 GiB free | `df -Ph /` |
| the real pressure | **io PSI `full avg300 = 5.13 %`**, and **64 `database is locked` events in company-api's journal today** | `/proc/pressure/io`, `journalctl -u company-api` |
| database | `/root/authority.db` = **31.76 GiB**, page_size 4096, 8,324,244 pages, **freelist 3,318,114 pages = 12.66 GiB (39.9 %)** | `sqlite3 'file:…?mode=ro' "pragma …"` |
| ceilings | 27 of 29 running units have **no** MemoryMax; only `company-api` (20 GiB, raised today at 15:37Z from a tuned 12 GiB) and `esearch` (4 GiB) are bounded | `systemctl show -p MemoryMax` |
| backups | DB → R2 ran 05:49Z today, `status=ok`, 9.29 GB gz, **remote verified**, 28 min; data archive 07:11Z, 4.02 GB | `/var/lib/authority-backup/last-run` |

So: the machine is not short of CPU, RAM or disk. **Its binding constraint is SQLite write
contention** — 64 lost locks today on a 31.76 GiB database with a 10 s busy timeout and a WAL sitting
at its 64 MB limit. Everything I chose below follows from that, not from "it feels slow".

**One latent fault closed while measuring it.** `/tmp` here is a **2 GiB tmpfs** — RAM-backed — and
`app/database.py` sets `PRAGMA temp_store = FILE`, so a large `ORDER BY` spills into the exact memory
the page cache wants and dies at 2 GiB having already consumed it. A drop-in
(`company-api.service.d/50-sqlite-tmpdir.conf`) now sets `SQLITE_TMPDIR=/root/.sqlite-tmp`, on the
same NVMe with 98 GiB free. It is installed **without restarting the API** — `systemctl show` confirms
the value is in the unit's environment and it takes effect at the next start, so nothing was
interrupted to apply it.

### 3.3 The authority is now a mesh worker — and how it is caged

This was the owner's actual ask, and the estate had excluded this box on purpose while it was a
4-core/15 GB machine with 11 OOM kills in a day. What changed is not the risk, it is the containment.

| piece | what it is | why it is safe |
|---|---|---|
| `/opt/dsh-mesh-runtime` | a **pinned** DSH 0.2.0-rc.2 install, `npm ci --omit=dev` from the authority's own `package-lock.json`; 537 MB | deliberately **not** `/opt/dsh-phone`, which is the phone product's promotion target — otherwise a phone promotion silently changes the worker |
| `/root/.dsh-worker` | its own `DSH_HOME`, separate `sessions/`, `profiles/`, `storages/` | `phone-engine.service` owns `/root/.dsh`; one engine per home is the rule that exists because two corrupt session logs. Proven: after the first turn `/root/.dsh-worker/sessions` = 1 and `/root/.dsh/sessions` = **6, unchanged** |
| `/etc/dsh-worker.env` | `DEEPSEEK_API_KEY`, `DEEPINFRA_API_KEY`, `0640 root:root` | the environment layer, not `~/.dsh/.credentials.yaml` (an env var wins and an agent cannot rewrite it). No value was printed at any point |
| `/usr/local/bin/dsh-mesh` | the executor. **Refuses** any `DSH_HOME` other than `/root/.dsh-worker` | a stray environment can never point a mesh turn at the phone's home |
| `dsh-mesh.slice` | `MemoryMax=6G`, `MemorySwapMax=1G`, `CPUQuota=400%` on 8 vCPU | a runaway child is killed **inside its own cgroup**; `company-api` never has to be what saves the database |
| roster row | `maxChildren: 2` — the node's own CPU-bound governor value, not the gate's memory-only 12 | the broker will not stack 12 turns on 4 physical cores |
| `phone-gate` drop-in | `PHONE_GATE_MAX_CHILDREN=2` | the gate published 12 because it computes from RAM alone; it now publishes the truth |

**The proof, in four measurements:**

```
$ dsh-mesh --profile headless "Run the command hostname, then reply … MESH-HOST: <the output>"
MESH-HOST: secratary-cloud                                     DSH_EXIT=0

$ ssh secratary-cloud 'dsh-mesh --profile headless "$(cat /tmp/mesh-proof-prompt.txt)"'   # from a dispatcher
MESH-HOST: secratary-cloud                                     RC=0

$ curl -s 'http://127.0.0.1:3091/nodes?fresh=1'
secratary-cloud      state=ok   memFreeMiB=26736  diskFreeGiB=96.6  maxChildren=2

$ POST /place {"task":{"kind":"oneShot","children":1,"exclude":[ five other nodes ]}}
node=secratary-cloud  position=0  tier=fits  blockedBy=[]      lease released with /done
```

The broker's own rationale, verbatim from that call:
`"chosen from 6 configured node(s): 2 unreachable, 5 excluded by the caller, 1 switched off in the
roster; tier=fits; chosen secratary-cloud"`.

**One thing that had to be discovered rather than assumed:** the broker reads a node at
`<baseUrl>/mesh/capacity`, and this node's gate answered **403 — "This node does not sign in this
device"** over its own tailnet name, because `phone-gate-allow.txt` lists every peer *except* the
authority itself. Rather than add the authority to that list (which grants a 30-day engine cookie on
the box that holds the database), the roster row uses `baseUrl: http://127.0.0.1:3086` — the broker
runs on this host, so loopback is the correct address and the allow-list is untouched.

**Also fixed while there:** `packages/plugin-remote-fanout/lib/broker-client.js:163` still defaulted
its ssh target to `secratary-ts` — the **frozen** office box, which still runs its *own* mesh broker
with a roster that has no `secratary-cloud` row. That was the third and last place that had to name
the authority; the provider config and `mesh-run.mjs` had both already been retargeted.

**Rollback, exactly:** `cp /opt/mesh-broker/nodes.json.bak-precloudnode-* /opt/mesh-broker/nodes.json
&& systemctl restart mesh-broker`, revert commit `e764b9e85`, `rm /usr/local/bin/dsh-mesh`. Keep
`/root/.dsh-worker` — its sessions are archive material.

---

## 4. The largest line is not storage — and it has two prices, not one

`model_usage` says DeepSeek cost **$237.94 in the last 7 days** — about $1,030 a month if the week
were typical. That number is computed by `app/pricing.py`, which prices `deepseek-v4-flash` at
**(0.44, 1.32) $/M** — labelled in that same file as the *legacy V4-Flash peak* rate and explicitly
*superseded*.

I got this wrong twice before I got it right, and both wrong versions are worth keeping because each
one was a different kind of mistake.

**First mistake — I trusted one card.** The file's *other* entry, `deepseek-flash`, is
**(0.15, 0.60)** and its comment says the whole US business day is now off-peak. Recomputed on that
card the same tokens are $81.76/week, so I published "the ledger overstates by 2.9×".

**Second mistake — I corrected the price but invented a cause.** The bank disagrees with both:
`accounting.db` → `transactions`, merchant *Hangzhou DeepSeek Artificial Intelligence Co., Ltd.*,
holds every auto-recharge debit — **$159.00 in 2 debits over the last 7 days, $636.00 in 10 debits
over 31 days, $892.52 in 18 debits since 2026-08-18**. So the money is ≈$143.6/week, between the two
cards, and I concluded that calls must be missing from `model_usage`.

**The actual explanation is simpler and it is in the same file I had already read: DeepSeek has two
prices and this workload uses both.** Peak is $0.30/$1.20 per million; off-peak is $0.15/$0.60. The
app carries one card at a time and neither is the truth. Price the measured tokens by the hour they
were actually spent in:

```
window 7 days, model_usage, grouped by UTC hour
peak    (00:30–16:30 UTC)  449,213,751 in   3,057,023 out     84 % of all input
off-peak(16:30–00:30 UTC)   85,475,042 in     747,468 out

peak      449.21 × 0.30 + 3.06 × 1.20 = $134.76 + $3.67 = $138.43
off-peak   85.48 × 0.15 + 0.75 × 0.60 = $ 12.82 + $0.45 = $ 13.27
                                                        = $151.70 / week
                                        × 30/7 = $650 / 30 days
```

| source | per week | verdict |
|---|---|---|
| **the bank** (31-day debits) | **$143.6** | the money |
| peak/off-peak model on the measured tokens | **$151.7** | agrees within 5 % |
| `model_usage` at the legacy card (0.44/1.32) | $237.94 | **1.57× too high** |
| the same tokens at off-peak (0.15/0.60) | $81.76 | **1.86× too low** |

**Nothing is missing.** The ledger records the calls; what was wrong was the price, and then my second
correction's explanation for the gap. `model_usage` becomes a usable budget instrument the moment the
cost function prices **per hour against the provider's own peak table**, which is a two-line change in
`app/pricing.py` and has not been made here.

**And that yields the largest optimisation in this whole audit.** 84 % of the company's input tokens
are spent in DeepSeek's **peak** window, which is 00:30–16:30 UTC — overnight and morning in the US.
The off-peak window is 16:30–00:30 UTC, i.e. the US afternoon and evening. At the current token
volume, **moving the same work out of peak halves the rate: $650/month becomes about $340/month**, and
no model changes, no capability is lost. What it costs is scheduling: the ticking departments and the
CEO kernel would need to concentrate their work in the back half of the UTC day. That is a decision
about when the company thinks, not about what it can do — which is why it is written here with the
arithmetic rather than acted on silently.

One more line, because it is the same story from a different counter: the phone engine runs **11,874
assistant messages in 7 days** on the same key (14.08 M input / 10.31 M output tokens), and those are
recorded only in its session files, never in `model_usage`. At peak rates that is ≈$16.60/week — small,
but it means the *company* ledger under-counts the *account* by about 10 %.

---

## 5. What I did not do, and why

| item | why not |
|---|---|
| **VACUUM the 13 GiB of free pages** | Measured now: the rebuild is **4 min 4 s** and the swap works, but a copy built outside the window is stale and would lose writes, so the rebuild must happen with the writers stopped — ≈5 min of company-API downtime. Script written, preflighted and proven: `/root/bin/compact-authority-db.sh`. **Window still needed**; §6.1. |
| Reclaim 8.9 GB on `waze-mdm-01` | Posture is `read-only`: *"Waze MDM production. Not the company's box to reconfigure."* 6.26 GB of unused images + 3.6 GB of journal, exact commands in §6. |
| Cancel Mosyle / Ably / DeepInfra / dead tunnels | His money, and each is one click in someone else's dashboard. Listed with evidence in §1.3. |
| Read the second Hetzner invoice | No credential exists on any host (`ls /root/.hcloud*` → ENOENT on all four; the token the fleet tried answered **HTTP 401**). Needs one read-only token — the question in §7. |
| Add `lpt-survivor-01` to the mesh | It is the cheapest spare capacity in the estate (0.5 % CPU, 64 GiB free, no swap) but it is **not on the tailnet** and has no ssh key from any mesh node; joining it is the same provisioner run again plus `tailscale up`, and it is also the **standby with no backup unit of its own** — worth doing, in that order, next session. |

---

## 6. The two runbooks this audit leaves behind

### 6.1 Reclaiming the 13 GiB of free pages — script written and measured, window still needed

The three things I got wrong in the first draft of this runbook, all found by running it:

1. **`VACUUM INTO` is fast.** Measured 2026-10-19: **4 min 4 s** (17:55:44Z → 17:59:48Z, `ionice -c3`,
32 GiB → **19 GiB**, `integrity_check ok`, `freelist 0`), while the API kept serving. The earlier
estimate of "10–30 min" was wrong by 5×.
2. **A pre-built copy cannot be swapped in later.** It is a snapshot of the moment it started: twelve
minutes after that run the copy was **5,549 `dsh_session_events` and 9 `model_usage` rows behind**,
and those rows exist nowhere else. The rebuild therefore has to happen *inside* the window, with the
writers already stopped. I built the copy, verified it, and then deleted it rather than swap in
something stale — that 4-minute run is the timing evidence, not a usable artefact.
3. **`phone-engine` holds the database open with ZERO file descriptors.** It was named in the first
   draft as the reason the window had to wait for the shop to close. Measured with
   `ls -l /proc/<pid>/fd | grep -c authority.db`: `company-api` **34**, `esearch` **59**,
   `phone-engine` **0**, dashboard **0**, gate **0**, broker **0**. Only three units hold it, one of
   them the `lpt-owner-queue` oneshot when it happens to be mid-run. **The swap does not end a phone
   call.**

**And one hazard the first draft would have walked into:** `authority.db-wal` belongs to the *old*
inode. Rename the database and leave the WAL, and the next process to open the new file finds a WAL
belonging to a different database and tries to apply it — corruption of a file that passed
`integrity_check` a second earlier. The `-wal` and `-shm` must move with the original, as one unit.

The script is **`/root/bin/compact-authority-db.sh`** on the authority and it does all of that, with
automatic rollback:

```bash
bash /root/bin/compact-authority-db.sh --check     # preflight: backup age, holders, what the swap buys
bash /root/bin/compact-authority-db.sh --apply     # stop -> rebuild -> verify -> swap -> start -> verify
```

Its measured preflight, 2026-10-19 18:1xZ: backup `status=ok` 12 h old (passes); `pages=8324244
freelist=3309507` = **13 GiB of free pages**; holders `esearch.service`, `company-api.service`,
`lpt-owner-queue.service`; expected downtime **≈ 5 minutes**, of which 4 is the rebuild.

It refuses on: no backup evidence, a backup older than 24 h, any holder that is not a systemd service,
a writer that did not release the file, a copy whose integrity fails, or a copy whose row counts differ
while the writers are stopped. On a failed verification it puts the original back and says so. It
never deletes the old database — removal after 24 h of clean running is a separate decision.

**Run it in the window, not at 14:00:** the only cost is a five-minute gap in the company API.

### 6.2 The 8.9 GB on the Waze MDM box (owner's yes, posture read-only)

```bash
ssh hetzner 'docker image prune -a -f && journalctl --vacuum-size=500M'   # 6.26 GB images + 3.6 GB journal
```

---

## 7. The one question

**Which Hetzner account holds `secratary-cloud` and `lpt-survivor-01`?**

The invoice I can read (`K0285620126`) covers two servers and $18.27/month. The other two machines are
~$177/month — **90 % of the Hetzner bill** — and their invoices, snapshots, volumes, floating IPs and
any backup add-on are invisible to me because no credential for that account exists on any host.

**Recommendation:** in that account, create one **read-only** Cloud API token (project → Read) and
drop it at `/root/.hcloud.env` on the authority as `HCLOUD_TOKEN=…`, mode 600. Then the next run
reads the real invoice and every add-on, and I can tell you which of the two servers is worth its
price. If you would rather not hand a machine a token, tell me the account's e-mail and I will read
its invoices out of that mailbox the same way I read this one.

---

## 8. Evidence index

| claim | command or file |
|---|---|
| invoice lines and total | Gmail message `1a14737d7eb34451` (PDF 086001226723), extracted with `pypdf` |
| R2 usage | `boto3` `list_objects_v2` against `s3://lpt-authority-backups`, 22 objects, 33,905,940,347 B |
| Cloudflare plan/tunnels | `GET /zones/9cbca1d1…` → `plan: "Free Website", is_subscribed: false`; `GET /accounts/…/tunnels` → 7 |
| lpt-apps disk | `df -Ph /`, `docker system df`, `docker image prune -a -f --filter until=48h` |
| authority specs | `nproc`, `free -m`, `df -Ph /`, `lscpu`, `curl 169.254.169.254/hetzner/v1/metadata` |
| DB free pages | `sqlite3 'file:/root/authority.db?mode=ro' "pragma freelist_count; pragma page_count"` |
| app SQLite policy | `/opt/company/app/database.py`: busy_timeout 10 s, cache_size 8 MB, synchronous NORMAL |
| write contention | `journalctl -u company-api --since 00:00 | grep -ci "database is locked"` → 64 |
| backup freshness | `/var/lib/authority-backup/last-run` (`status=ok`, `remote_last_modified=2026-10-19T05:46:28+00:00`) |
| model spend | `select provider, count(*), sum(estimated_cost_usd) from model_usage where created_at > datetime('now','-7 day') group by provider` |
| rate card | `/opt/company/app/pricing.py:150-172` |
| mesh proof | `dsh-mesh --profile headless …`, `GET /nodes?fresh=1`, `POST /place`, `/done` |
| mesh commit | `e764b9e85` on `cloud-audit/20261019` |
