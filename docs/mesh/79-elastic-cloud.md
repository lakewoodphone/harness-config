# 79 — Elastic cloud: should the mesh rent virtual computers instead of buying PCs?

**Program:** `docs/mesh/` — the volume the program does not have. It answers the owner's question of
2026-09-16: *"Instead of buying plenty of new PCs and adding them to the mesh, maybe we can rent virtual
computers. Whenever the mesh goes above a certain percent use and there's that slowing down, we activate
virtual computers that we rent very cheaply, because we only need them once in a while."*

**Written:** 2026-09-16, 23:28–23:59Z (19:28–19:59 EDT) from `ZABZ-YOGA`.
**Author:** a delegated session (agent 79), not the owner.
**Status:** analysis + a decision. **This is the only file this session wrote.**

**What I did and did not do.** Read-only `ssh` to the two Hetzner VPSs the fleet already pays for
(`hetzner`, `lpt-apps`), one read-only probe script per host. Read Hetzner's own price data files and plan
pages, Oracle's own free-tier documentation, Fly.io's pricing docs, and AWS's own spot price feed. Ran one
headless browser to render JS pricing pages. **Nothing was installed, started, stopped or resized on any
machine, anywhere. No git command that changes state was run. No credential of any kind was read or used.
No cloud account was touched.** Scratch files: `C:\Users\ezabz\mesh-probe-79.sh`,
`C:\Users\ezabz\mesh-probe-79b.sh` (local, inert).

**Provenance convention.** **SAW** = I read it today, with the URL and the time. **REMEMBERED** = I did not
see it today; it is knowledge, not evidence, and it is labelled as such where it appears. **ARITHMETIC** =
derived by me from SAW inputs, which are named. **COULD NOT VERIFY** = I looked and failed. A confidently
wrong number is the failure this whole program exists to prevent.

---

## 0. The answer, in one paragraph

**Yes, and not yet — and the thing standing in the way is not money.** The arithmetic genuinely favours
renting: a 23-child fleet is ~23 generating turns, which is ~24 rented vCPUs, and on today's verified
prices that is **$0.24–$0.68 per hour** — against **$652.47** to buy the 24 cores it replaces, i.e. the
rental pays for itself in **thirteen to fifty years** at one fleet-hour a week, which is another way of
saying it never pays back as *hardware* and does pay back immediately as *peak*. But his current bottleneck
is **not capacity, it is routing**. On 2026-09-16 23:20Z the broker placed a 6-child fleet on `ZABZ-TECH`
at `position 0` while that machine was 3 % busy, and the laptop did everything anyway (`76-broker.md`
§7.3). Renting a machine the dispatcher cannot reach buys nothing. **Order: finish the mesh, then make the two VPSs he already pays for
into nodes (free, worth ~4 one-shot turns — worth doing for the proof, not the capacity), and only then
build the elastic tier** — which needs one frozen-interface change (`GET /nodes` gains an `absent` state),
a hard node TTL, and a credential path that does not leave the model key in the provider's user-data. And
the single trap to avoid: **Oracle's always-free ARM VM is the biggest free machine on the board and Oracle
will take it away for being idle** — which is exactly what a burst-only node is.

---

## 1. The free tier he already pays for — two Hetzner VPSs, both verified live today

Both were reached by `ssh -o BatchMode=yes -o ConnectTimeout=8 <alias> "<script>"` on **2026-09-16
23:28Z**, read-only.

### 1.1 What each one is — MEASURED

| | `waze-mdm-01` (`hetzner`) | `lpt-apps-01` (`lpt-apps`) |
|---|---|---|
| public IPv4 | `87.99.141.172` | `2.28.33.58` |
| **Hetzner instance id** (metadata service) | **130707524** | **164128338** |
| **region / availability zone** (metadata) | **`us-east` / `ash-dc1` — Ashburn, Virginia** | **`eu-central` / `fsn1-dc8` — Falkenstein, Germany** |
| `systemd-detect-virt` | `kvm`, `sys_vendor=Hetzner`, `product_name=vServer` | same |
| OS | Ubuntu 24.04.3 LTS | Ubuntu 24.04.4 LTS |
| vCPU / model | **2** × AMD EPYC-Rome | **4** × Intel Xeon (Skylake, IBRS, no TSX) |
| RAM total / available | 1 919 MB / **1 061 MB** | 7 751 MB / **5 125 MB** |
| swap | 2 047 MB, 221 MB used | 2 047 MB, 608 MB used |
| disk `/` | 38 G, 18 G used, **19 G avail (50 %)** | 75 G, 60 G used, **12 G avail (84 %)** |
| uptime / booted | **126 d 21 h**, booted 2026-05-13 02:26:04 | 16 d 8 h, booted 2026-08-31 14:45:06 |
| load1 / load5 | 0.01 / 0.01 | 0.30 / 0.18 |
| **Node / npm / dsh / tailscale** | **all ABSENT** | **all ABSENT** |
| `~/.dsh` | absent | absent |
| running services | 23, incl. `docker`, `strongswan-starter` (IPsec), `dnsmasq`, `dep-profile-reconcile` | 20, incl. `docker`, `fail2ban` |
| containers | **11** — the whole Waze MDM production stack (`nanomdm`, `nanodep`, `fleet-api`, `fleet-dashboard`, `postgres`, `caddy`, `dns-filter`, `restore`, `yocheved`, `emt-quiz`) | **11** — `lakewood-rentals`, `chumash-timeline`, `lpt-backend`, `personality-test`, `lpt-test-backend`, `lpt_filter_site`, `lpt_filter_ai_api(_b)`, `caddy`, `lpt-postgres`, `lpt-redis` |
| listening on `0.0.0.0` | 22, 80, 443, 53 | 22, 80, 443, 1080, 1081, 9443, 9444 |
| cron | **12 jobs**, one of which runs **every single minute** (`fleet-api-call.sh POST /fleet/sweep`) | **1 job** (nightly backup) |
| egress reachability (from the box) | `nodejs.org` 200, `registry.npmjs.org` 200, `api.deepseek.com` **401** (i.e. reachable) | same three codes |

The metadata readings are the strongest identity evidence here and they contradict one thing
`10-inventory.md` §6/§7 left open: **`waze-mdm-01` is not in Europe — it is in Ashburn, Virginia**, the
same Hetzner location (`ASH1`) whose US list prices appear in §2 below. `lpt-apps-01` is the German one.

### 1.2 What they cost — **the invoice was NOT read, and I will not pretend otherwise**

**COULD NOT VERIFY: what he actually pays.** There is no Hetzner billing record on this machine, in
`harness-config`, or in the journal — I searched all three and found nothing. Reading the invoice needs the
Hetzner Cloud console (Billing) under his login, and I did not touch any account or credential.

What I *can* say is what SKU each box matches, from its own measured hardware, and what that SKU lists at
today:

| box | measured spec | matching plan | today's list, **SAW 2026-09-16** | source |
|---|---|---|---|---|
| `waze-mdm-01` (Ashburn) | 2 vCPU AMD, ~1.9 GB, 38 GB | **CPX11** — 2 vCPU AMD, 2 GB, 40 GB | **$20.49/mo, $0.0328/hr** (ASH1, USD) | Hetzner's own calculator data file, `cloud_data.json` |
| `lpt-apps-01` (Falkenstein) | 4 vCPU Intel, ~7.6 GB, 75 GB | **CX33 (older Intel generation)** — 4 vCPU Intel/AMD, 8 GB, 80 GB | **€8.99/mo, €0.0144/hr** (EU, EUR, excl. VAT) | `hetzner.com/cloud/cost-optimized/`, SAW 23:35Z |

Two caveats, both real: the SKU match is an **inference from measured hardware**, not a reading of an
order; and **the current CX plan page displays `CX23`, `CX33` and `CX43` as `not available`** (SAW
23:35Z) — so the €8.99 figure prices the plan he is on, not a plan he could order today. `~/.ssh/config:236`
independently records `lpt-apps-01` as "`fsn1 cx33`", which is corroboration of the CX33 match, from a
config comment written 2026-08-31.

**Total rent he is already paying, on today's list prices: roughly $20.49 + €8.99 ≈ $31/mo**, for two
machines that contribute **zero** to the mesh. That is the honest size of the "free tier you already pay
for".

### 1.3 Exactly what it would take to make each a mesh node

Not a plan — a script that already exists and has already been run once. Stream S2 built
`scripts/provision-mesh-node.sh` and proved it on `zabz-tech-linux` on **2026-09-16 23:14–23:24Z**
(`73-linux-pc-node.md` §1.2). The steps, in order, with what each costs:

| step | what it does | evidence |
|---|---|---|
| 1. runtime | Node **v22.23.2** tarball from `nodejs.org` into `~/.local`, sha256 verified. **v22.23.2 is the floor that matters**: below 22.18 `import.meta.main` is `undefined` and the engine **exits 0 having printed nothing** — the worst failure shape in the pipeline (`62-worker-runtime.md` §1.1). `apt install nodejs` on Ubuntu 24.04 gives **18.19.1** and must never be used. | `73` §1.2 step 2; `62` §1.1 |
| 2. DSH | `npm ci --omit=dev` from **the authority's own `package-lock.json`** so the version is pinned to `0.1.5-rc.1` by integrity hash, not by the `^0.1.5-rc.1` range (`62` §4.1: a fresh ranged install can resolve to a *different build*) | `73` §1.2 step 3 |
| 3. credentials | `/etc/dsh-worker.env`, mode `0640 root:zabz`, holding `DEEPSEEK_API_KEY` + `DEEPINFRA_API_KEY`. **Never `~/.dsh/.credentials.yaml`** — that file is in `scripts/sync.py`'s `PROTECTED` set, and if it ever exists with group/other bits the engine **refuses to start** (`62` §1.3) | `73` §1.2 step 4 |
| 4. launcher | `/usr/local/bin/dsh`, resolving the interpreter rather than naming a version | `73` §1.2 step 5 |
| 5. systemd | `dsh-engine.service` (`web --port 3099 --no-open --trusted-host <fqdn>`) and `phone-gate.service` (`--listen-port 3086`), with `HOME` and `DSH_HOME` set explicitly — systemd sets neither, and without `HOME` the engine's `~/.dsh` resolves to `/` | `73` §1.2 step 6; `62` §1.4 |
| 6. the door | `tailscale serve --bg 3086` publishes the gate at `https://<node>.tail93e6e6.ts.net/` | `73` §1.2 step 7 |
| 7. **the tailnet itself** | `tailscale up --authkey=… --hostname=…`, then ACL tag **`tag:mesh-node`** and **key expiry disabled** — a node whose auth key expires silently leaves the mesh and the broker sees it as unreachable forever | `50-transport.md` §309, §316 |

**One gotcha that is specific to a VPS and that the script does not yet handle.** Step 2 as written does
`scp secratary:…/package-lock.json` from *the node*, and step 7 assumes the tailnet. `73` §1.2 says
explicitly: *"Run this ON the linux box, which is on the office LAN, so the office alias `secratary`
resolves."* **A Hetzner VPS can reach neither** — it is not on the LAN and not on the tailnet, so at the
moment it needs the lockfile it has no authenticated path to the authority. The lockfile must be delivered
from the operator's own machine (or by the node joining the tailnet *before* the DSH install), or step 2
fails. That ordering change is a real, small piece of work.

### 1.4 How many agent turns could each take — ARITHMETIC

The model, from `40-hardware-costs.md` §0: a node's useful capacity is
`min(cores that can generate, memory ceiling)`, **one generating turn ≈ 1 core**, and the corrected memory
form is `floor((0.75 × RAM_GB − 18) / 0.58)` — where the ≈18 GB resident floor was measured on
`ZABZ-YOGA` *with the full harness loaded*. `40` §0 states plainly that **a bare Linux node would have a
lower floor, and that measurement has never been taken**, so the memory column below is a *lower bound*
applied to machines that are already running 11 containers.

| node | CPU ceiling (cores × 0.75) | memory, using the 18 GB floor | **usable turns** | the thing that actually overrides it |
|---|---|---|---|---|
| `waze-mdm-01` | 2 × 0.75 = **1.5 → 1** | 1.06 GB avail ⇒ **0** | **1, and realistically 0** | It is the live Waze MDM production host: 11 containers, a cron job every 60 s, and 1.06 GB genuinely available. |
| `lpt-apps-01` | 4 × 0.75 = **3** | 5.13 GB avail ⇒ **0** at the 18 GB floor; 6.6 at 0.58 GB/process with no floor | **3** | Production for six LPT apps; and see the disk gate below. |

**And the broker's own frozen rule disqualifies both of them for exactly the work that would pay for a
node.** `71` §2.2: *"a node with `freeGiB < 20` is ineligible for `kind=fleet`."*

* `waze-mdm-01`: **19 GiB free** — fails the gate by **1 GiB**.
* `lpt-apps-01`: **12 GiB free** — fails by 8 GiB.

So the honest verdict is: **both VPSs can host one-shot turns and neither can host a fleet** — the same
position `secratary` is in, which reports `accepts.fleet:false` today (`76-broker.md` §7.2). **"Free added
capacity", measured: ~1 one-shot turn on `waze-mdm-01` and ~3 on `lpt-apps-01`, and zero fleets from
either.**

**Is that worth doing?** Yes — but not for the turns. It is worth doing because it is the only way to
prove, on a machine that is neither on the LAN nor on the tailnet, that the provisioner works against a
remote host over the public internet. That is a prerequisite for the elastic tier in §5 whether or not a
VPS is ever a node. It should be done in that order and for that reason, and the write-up should say
"proved the remote path", not "added 4 turns".

**What is *not* free and is actually sitting idle:** `zabz-tech-linux`, which S2 provisioned tonight —
**12 cores at load 0.2, 10.1 GB available, swap 15 % used, answering `GET /mesh/capacity` in 48 ms**
(`73` §0; `76` §7.2). That node, not a rented VM, is the first answer to a burst. And behind it,
`ZABZ-TECH`: **32 logical / 24 physical cores, 51.88 GB free, measured 3 % busy, 24 slots** — the machine
that the broker already places a 6-child fleet on, at `position 0`, and which the owner's own complaint
says work *does not land on*.

---

## 2. What renting costs, verified live

### 2.1 The one rule that decides the shape of every row

Hetzner, in its own words on its own plan pages (SAW 2026-09-16 23:32Z,
`hetzner.com/cloud/regular-performance/`):

> *"Your server's bill will never exceed its monthly price cap. If you delete your cloud server before the
> end of the billing month, we will only bill you for the hourly rate."*

**That is the mechanism the owner is describing**, and it is the single most important sentence in this
document: Hetzner bills **by the hour**, with the **monthly price as a hard cap**. There is no commitment,
no minimum term, and deleting mid-month costs only the hours used. `0.0328 × 744 = $24.40 > $20.49`, so the
cap is real and not a marketing ratio: **the hourly rate stops mattering after 624.7 h/month.**

### 2.2 The table — every price below was SAW today at the timestamp given

All prices **exclude VAT**. USD rows are Hetzner's US (Ashburn / Hillsboro) list; EUR rows are EU list.

| # | provider · plan | vCPU | RAM | disk | **hourly** | **monthly cap** | billing | egress | SAW |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Hetzner CPX11** (Ashburn) | 2 shared | 2 GB | 40 GB | **$0.0328** | **$20.49** | per hour, monthly cap | ~$0.0012/GB beyond included | 23:31Z, data file |
| 2 | **Hetzner CPX21** (Ashburn) | 3 shared | 4 GB | 80 GB | $0.0601 | $37.49 | per hour, monthly cap | as above | 23:31Z, data file |
| 3 | **Hetzner CPX31** (Ashburn) | 4 shared | 8 GB | 160 GB | $0.1178 | $73.49 | per hour, monthly cap | as above | 23:31Z, data file |
| 4 | **Hetzner CPX41** (Ashburn) | 8 shared | 16 GB | 240 GB* | **$0.2267** | **$141.49** | per hour, monthly cap | as above | 23:31Z, data file |
| 5 | **Hetzner CPX51** (Ashburn) | 16 shared | 32 GB | 360 GB* | $0.4479 | $279.49 | per hour, monthly cap | as above | 23:31Z, data file |
| 6 | **Hetzner CCX13** (Ashburn) | **2 dedicated** | 8 GB | 80 GB | **$0.0817** | **$50.99** | per hour, monthly cap | as above | 23:31Z / 23:35Z |
| 7 | **Hetzner CCX23** (Ashburn) | **4 dedicated** | 16 GB | 160 GB | $0.1650 | $102.99 | per hour, monthly cap | as above | 23:31Z / 23:35Z |
| 8 | **Hetzner CCX33** (Ashburn) | **8 dedicated** | 32 GB | 240 GB | $0.2660 | $165.99 | per hour, monthly cap | as above | 23:31Z / 23:35Z |
| 9 | **Hetzner CCX43** (Ashburn) | 16 dedicated | 64 GB | 360 GB | $0.5280 | $329.49 | per hour, monthly cap | as above | 23:31Z / 23:35Z |
| 10 | **Hetzner CX23** (EU only) | 2 shared | 4 GB | 40 GB | €0.0096 | €5.99 | per hour, monthly cap | €1.00/TB beyond incl. | 23:35Z — **page marks it `not available`** |
| 11 | **Hetzner CX33** (EU only) | 4 shared | 8 GB | 80 GB | €0.0144 | €8.99 | per hour, monthly cap | as above | 23:35Z — **`not available`** |
| 12 | **Hetzner CX43** (EU only) | 8 shared | 16 GB | 160 GB | €0.0264 | €16.49 | per hour, monthly cap | as above | 23:35Z — **`not available`** |
| 13 | **Hetzner CPX42** (EU only) | 8 shared | 16 GB | 320 GB | €0.1122 | €69.99 | per hour, monthly cap | as above | 23:32Z |
| 14 | **Hetzner CPX52** (EU only) | 12 shared | 24 GB | 480 GB | €0.1618 | €100.99 | per hour, monthly cap | as above | 23:32Z |
| 15 | **Oracle Always Free · A1.Flex (ARM)** | **2 OCPU** | **12 GB** | up to 200 GB total | **$0** | **$0** | free, in home region only | **10 TB/mo free** | 23:37Z, Oracle docs |
| 16 | **Oracle Always Free · E2.1.Micro ×2** | 2 × 1/8 OCPU | 2 × 1 GB | shared 200 GB | **$0** | **$0** | free | 10 TB/mo free | 23:37Z, Oracle docs |
| 17 | **AWS EC2 Spot · t3.medium** (us-east-1) | 2 | 4 GB | EBS extra | **$0.0167** | **none documented** | per second, Linux | **$0.09/GB** (first 10 TB) | 23:48Z, AWS's own spot feed |
| 18 | **AWS EC2 Spot · c7i.large** (us-east-1) | 2 | 4 GB | EBS extra | $0.0275 | none documented | per second, Linux | $0.09/GB | 23:48Z |
| 19 | **AWS EC2 Spot · c7i.xlarge** (us-east-1) | 4 | 8 GB | EBS extra | $0.0538 | none documented | per second, Linux | $0.09/GB | 23:48Z |
| 20 | **AWS EC2 Spot · m7i.xlarge** (us-east-1) | 4 | 16 GB | EBS extra | $0.0836 | none documented | per second, Linux | $0.09/GB | 23:48Z |
| 21 | **GCP Spot · e2-standard-2** (us-central1) | 2 | 8 GB | disk extra | **$0.040212** | **none documented** | Spot granularity **COULD NOT VERIFY** | **$0.12/GiB** (1 GiB–1 TiB) | 23:45Z, `cloud.google.com/spot-vms/pricing` |
| 22 | **GCP Spot · e2-standard-4** (us-central1) | 4 | 16 GB | disk extra | **$0.080424** | none documented | as above | $0.12/GiB | 23:45Z |
| 23 | **GCP Spot · n2-standard-2** (us-central1) | 2 | 8 GB | disk extra | $0.058256 | none documented | as above | $0.12/GiB | 23:45Z |
| 24 | **Fly.io `shared-cpu-2x`** | 2 shared | 1 GB–4 GB | rootfs | **$0.0111** (1 GB) / $0.0198 (2 GB) | none (it is per-second) | **per second** | not verified | 23:38Z, Fly docs |
| 25 | **Fly.io `shared-cpu-4x`** | 4 shared | 8 GB | rootfs | **$0.0396** | none | **per second**; stopped = **$0.15 per GB of rootfs per 30 days** | not verified | 23:38Z |
| 26 | **Fly.io `shared-cpu-8x`** | 8 shared | 2 GB | rootfs | $0.0270 | none | as above | not verified | 23:38Z |
| 27 | **Fly.io `shared-cpu-6x`, 6 GB** | 6 shared | 6 GB | rootfs | $0.0593 | none | as above | not verified | 23:38Z |

\* CPX41/CPX51 disk figures — the RAM and vCPU counts are SAW; the disk sizes for the 1-series CPX plans
are marked *REMEMBERED* because the rendered plan page listed only the **2-series** (`CPX12`…`CPX52`) and
the 1-series US rows exist only in the price data file, which carries cores and prices but not RAM or disk.
**The hourly and monthly prices in rows 1–5 are SAW; the RAM and disk columns for rows 1–5 derive from the
1-series spec family and should be treated as *REMEMBERED*.** Rows 6–9 (CCX) have all three columns SAW.

**Sources, exactly:**
* Hetzner USD/ASH1 rows: `https://www.hetzner.com/_resources/app/data/bench/cloud_data.json` — Hetzner's
  own calculator dataset, SAW 2026-09-16 23:31Z. It carries `price`, `hourPrice`, per-location `traffic`,
  `cores`, `coreType` for every CPX and CCX SKU.
* Hetzner EUR rows and **€0.60/mo, $0.60/mo per IPv4** (`IP` block in the same file): SAW 23:31–23:35Z.
* **Egress cross-check, and this one is worth reading:** Hetzner publishes a competitor comparison at
  `cloud_traffic.json` (SAW 23:30Z) whose USD figures per GB are — **hcloud US/DE $0.001154** (first
  20 TB included), vultr $0.01, **azure** $0.08, **gcp US** $0.085 (first 200 GB free), **aws US $0.09**,
  alicloud $0.077. Hetzner's own per-location `traffic` map for ASH1 reads `{"0":0,"1":"1.200000"}` =
  **$1.20 per additional TB = $0.0012/GB**, consistent. So: **AWS and GCP charge roughly 75–100× Hetzner per
  GB of egress.** (The exact US *included* allowance is the one thing here I could not pin down: the
  comparison file says 20 000 GB free, the per-location map reads as free only to 1 TB. **COULD NOT
  VERIFY**; the decision-relevant fact — that extra egress is ~$0.0012/GB rather than $0.09/GB — holds
  either way.)

### 2.3 Oracle, precisely — and why the free tier is a trap for *this* use case

Everything below is from Oracle's own documentation, SAW **2026-09-16 23:37Z**
(`docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm`, page footer
"Copyright © 2026") and Oracle's own free-tier data file (`oracle.com/a/ocom/docs/oci-free-tier_v1.json`,
SAW 23:29Z).

* **ARM, Always Free:** the first **1 500 OCPU-hours and 9 000 GB-hours per month** on
  `VM.Standard.A1.Flex`. Oracle's own docs state: *"For Always Free tenancies, this is equivalent to
  **2 OCPUs and 12 GB of memory**."* **This is a reduction from the 4 OCPU / 24 GB that older write-ups
  describe** — the current number is 2 / 12, and the monthly-hours arithmetic confirms it (9 000 ÷ 744 =
  12.1 GB).
* **AMD micro, Always Free:** up to **two** `VM.Standard.E2.1.Micro`, each **1/8 OCPU and 1 GB**, 50 Mbps.
  Too small to run DSH usefully.
* **Storage:** **200 GB** of block volume total, and the **minimum boot volume is 47 GB**.
* **Egress: 10 TB/month free** — by far the best on this board, 5× AWS's free 100 GB.
* **Home region only.** Always Free resources exist only in the tenancy's *home region*, which is chosen at
  signup and cannot be moved. He would be choosing a region once, blind.
* **A new account can still get it — and may not be able to create it.** Oracle documents the failure
  itself: *"If you receive an 'out of host capacity' error when trying to create a Compute instance, this
  indicates a temporary lack of Always Free shapes in your home region. Try creating the instance in a
  different availability domain, or wait a while, and try again."* That is Oracle's own acknowledgement
  that the free ARM shape is frequently unavailable, and the third-party tooling
  (`github.com/alexpua/oci-arm-catcher`, found 2026-09-16) exists only because it is.
* **And the disqualifier, quoted verbatim:**
  > *"Idle Always Free compute instances may be reclaimed by Oracle. Oracle will deem virtual machine and
  > bare metal compute instances as idle if, during a 7-day period, the following are true: CPU utilization
  > for the 95th percentile is less than 20 %; Network utilization is less than 20 %; Memory utilization is
  > less than 20 % (applies to A1 shapes only)."*

  **That is a perfect description of an elastic burst node.** A machine rented to absorb a fleet twice a
  month and idle the rest of the time hits all three criteria and is taken away. **Oracle's always-free
  tier is the opposite of an elastic tier: it is a *resident* node that must visibly work for a living.**
  If he ever wants it, it must be a node the mesh keeps busy — and only then is it the best deal on this
  page (2 OCPU / 12 GB / 10 TB egress, $0, forever).

### 2.4 The AWS spot caveat, stated rather than smoothed over

The spot prices in rows 17–20 come from **AWS's own public spot feed**
(`https://website.spot.ec2.aws.a2z.com/spot.json`, 2 826 668 bytes, `"rate":"perhr"`, `us-east-1`,
SAW 23:48Z). **The payload carries no publication timestamp** — only `vers` and `config` — so it is dated
by *my fetch*, not by AWS. Two independent cross-checks disagree with it in the same direction: AWS's own
**Spot Advisor** bulk data gives us-east-1 Linux savings of 53–61 % against on-demand, and
`ec2.shop?region=us-east-1` quotes 3–50 % higher than this feed on individual types (e.g. `t3.large`
$0.0409 vs $0.0277 here). **Treat rows 17–20 as "AWS's own feed, as read at 23:48Z, uncorroborated by
AWS's own second source."** The ordering is what matters and it does not change: AWS spot is roughly in
Hetzner's band per hour and 75× worse on egress.

Other verified AWS/GCP facts: **AWS spot gives a two-minute, best-effort termination notice** delivered via
EventBridge and instance metadata, and AWS docs recommend polling every 5 seconds; Linux is billed
per second with no hourly minimum (`docs.aws.amazon.com/.../spot-instance-termination-notices.html`,
`.../billing-for-interrupted-spot-instances.html`, read 2026-09-16). **GCP's default spot preemption
notice is 0 seconds** — metadata `preempted=TRUE` then an immediate ACPI G2 Soft Off; 120 seconds exists
but is **in Preview** (`cloud.google.com/compute/docs/instances/spot`). A reminder of the owner's rule:
*"AI models change very often"* — the same is true of instance types, and none of these SKUs belongs
anywhere in code.

---

## 3. The costs no one puts on the price page

### 3.1 Boot to ready — measured, and it costs about a cent

The sequence in §1.3 has been **executed and timed once**, by S2 on `zabz-tech-linux` on 2026-09-16
(`73-linux-pc-node.md` §1.2). The measured pieces:

| step | measured | source |
|---|---|---|
| Node v22.23.2 tarball download | **29.35 MiB in 3.08 s = 9.5 MB/s** on the owner's own link; the exact byte count is `content-length: 30776836`, SAW today by HEAD request | measured 23:41Z |
| `npm ci` for DSH | **11 s, 524 packages** — the *slow step*, and every other step is seconds | `73` §1.2, SAW in the doc |
| installed footprint | `node_modules` = **305 MB, 25 428 files**; Node runtime = **204 MB**; Tailscale package installed-size ≈ **72 MB** | MEASURED on `secratary` 23:40Z |
| the whole S2 session, start to verified | **10 minutes** (23:14–23:24Z) — and that includes writing a 513-line document and verifying with a real `MESH-HOST:` turn | `73` header |

**Boot-to-ready for a fresh Linux VM using the existing provisioner: 2–4 minutes of machine time**, with
the download and `npm ci` dominating. (A fresh VPS also pays the provider's own boot, ~10–30 s, and every
download is *cold*: a new node has no `harness-config` checkout — 45 MB, 18.56 MiB of it git pack, measured
23:43Z — and no npm cache, against 383 MB of cache on `secratary`.)

**What that costs at the hourly rate:**
* Hetzner CPX41 at $0.2267/hr = $0.003778/min → **3 minutes = $0.011**.
* Hetzner CPX11 at $0.0328/hr → **3 minutes = $0.0016**.
* Fly `shared-cpu-2x` at $0.0198/hr → **3 minutes = $0.00099**.

**Boot-to-ready costs about one cent, and it is the least important of the three hidden costs.** Take that
seriously as a finding, because it is the one people assume is fatal and it is not. What *is* fatal is the
next two items — and the fourth thing in §3.4.

One real caveat: `zabz-tech-linux` sits **0.21 ms** from the authority on the office LAN (`62` §3.1). A
VPS in Falkenstein is ~90–100 ms away and a VPS in Ashburn ~10–20 ms, and both reach the authority only
through Tailscale — which the **laptop** currently cannot do directly at all, only via the NYC DERP relay
at 30–44 ms (`10-inventory.md` §2.6). A rented node in Ashburn would very likely form a *direct* WireGuard
path to the New Jersey office, i.e. a **better** path than the owner's laptop has today — but I could not
measure it, because neither VPS has Tailscale installed and installing it is out of scope. **COULD NOT
VERIFY**; it is a reason to prefer a US-East node over a German one, not a proven fact.

### 3.2 The model API key on a machine that appears and disappears

This is the real risk, and the fleet has already solved it once for a machine that stays.

**The pattern that works** (`73` §1.2 step 4): the key lives in `/etc/dsh-worker.env`, mode
**`0640 root:zabz`**, loaded by the systemd unit, read-only from inside the agent process, and it never
touches disk inside `~/.dsh`. `62` §1.5(a) explains why that layer and not the file: an environment
variable **wins** over `~/.dsh/.credentials.yaml` and cannot be written by an agent (the provider refuses
a write the environment would shadow), and `scripts/sync.py:42` already refuses to sync
`.credentials.yaml`, so the fleet has already decided this.

**What changes when the machine is rented, in three named failure modes:**

1. **cloud-init user-data is read back by the instance and retained by the provider.** I proved the
   channel exists by reading it: `http://169.254.169.254/hetzner/v1/metadata` returned the full
   `vendor_data` blob — the cloud-config that created the box — on **both** VPSs today. Anything baked
   into user-data at provision time is therefore readable from inside the node **and stored on Hetzner's
   side**. A key delivered that way is a key handed to the provider and to anyone who later gets console
   access or a snapshot.
2. **Snapshots and images outlive the VM.** A provider snapshot taken before teardown carries the key
   wherever it goes. Teardown must therefore be **destroy the server AND delete its images**, and if any
   image was ever taken, **rotate the key** regardless.
3. **The delete is the credential control.** There is no "un-provision". The honest rule is: the key's
   lifetime equals the VM's lifetime, the VM's lifetime is capped by a hard timer (§5.3), and the key is
   delivered **over the already-authenticated tailnet** (scp from the authority, or an
   `EnvironmentFile` pushed after the tailnet join) rather than through the provider's metadata channel.

**What makes this cheapest to get right, and it is a development decision, not his:** the fleet already
has a mechanism that does not put the key on the node at all — the environment layer plus a launcher that
reads `/etc/dsh-worker.env`. So the elastic path is: **join the tailnet first, then `scp` the env file from
the authority over WireGuard, then start the unit.** That inverts the §1.3 order (which currently installs
DSH before joining the tailnet) and removes the provider from the credential path entirely.

**One thing I could not verify and it matters:** whether the gateway can issue **per-node, revocable,
scoped keys**. If it can, a node's credential should be a throwaway issued at boot and revoked at teardown,
which turns a rotation problem into a bookkeeping problem. **COULD NOT VERIFY** — I did not read the
gateway's credential API, and the standing rule applies: **models are resolved at runtime from the
gateway's catalogue, never hardcoded** (`journal L1606`), so the node needs the *gateway base URL* as well
as a key, and that URL is another thing to provision and destroy.

### 3.3 Durability — what dies with the node, and the frozen rule that decides it

**`71` §0, measured: "Sessions are node-local and do not move."** And `71` §5 rules out the fix:
*"Sessions moving between nodes — they cannot, by construction. Session placement … is v2."*

So a rented node can never be a place a session lives. It is a **job runner**, and that is a design
constraint, not a preference. The consequences, and what must happen before teardown:

| what is on the VM | what happens | what must be true before destroy |
|---|---|---|
| `~/.dsh/sessions/**` | **destroyed, and it cannot be moved mid-flight.** A session created there is gone. | Either the node only ever runs `dsh --profile headless` (one task, one process, exits — `62` §2.1) whose **stdout goes to a log on the caller**, or `~/.dsh/sessions` is `rsync`ed to the authority *before* destroy and the node is declared session-free. |
| worktrees | destroyed | Committed and pushed, or archived to the authority. **No `git push` is in scope for the elastic provisioner as designed** — the dispatcher does it, or the node is a read-only runner. |
| the repo clone | destroyed | Nothing. It is re-cloned every boot; that is what the 45 MB is for. |
| npm cache | destroyed | Nothing — but it means `npm ci` is cold every time (11 s, measured; still cheap). |
| **logs and the `MESH-HOST:` proof** | destroyed | `71` §2.3 already requires the dispatcher to capture stdout/stderr to `~/.dsh/mesh/logs/` **on the caller**. That is what makes a rented node auditable: without it, work ran and left no record. |
| the credential file | destroyed with the disk | §3.2 — and see the provider's backup retention, which is **COULD NOT VERIFY**. |

The write-down that must exist: `71` §2.4's `MESH-HOST:` line, which the dispatcher verifies against the
node it believes it used. For an elastic node that check is *more* important, not less, because "which
machine actually ran this" is the one fact a VM that no longer exists cannot be asked about afterwards.

### 3.4 The cost that actually decides it: the node left running

There is no line on any price page for this, and it is larger than everything else in §3 combined.

* Hetzner **CPX41** left up for a month: **$141.49**.
* A used OptiPlex 3090 Micro, verified at **$152.98** with free delivery (`61-buy-list-verified.md` §4.2,
  listing `/itm/267785174714`, SAW 2026-09-16) — **$163.12 taxed**.

**One forgotten 8-vCPU node for one month costs 87 % of owning the machine outright, and it is gone at
the end of the month.** The broker's lease TTL is **900 s** and it reclaims expired leases itself
(`71` §2.2) — but that is a *lease* TTL for a dispatcher, not a *node* TTL, and §2.2 deliberately stores
nothing that a dead dispatcher can wedge. **An elastic tier therefore needs its own hard wall-clock
lifetime, owned by the provisioner, and it needs a spend alarm.** Without those two things the elastic
tier is a mechanism for converting an occasional slowdown into a recurring bill.

---

## 4. The break-even

### 4.1 What owning costs — ARITHMETIC on verified inputs

The comparison machine is the owner's own verified pick: **Dell OptiPlex 3090 Micro, i5-10500T
(6 c / 12 t), 16 GB, 256 GB NVMe, $152.98 free delivery, 3 available** — `61-buy-list-verified.md` §4.2,
SAW 2026-09-16.

| input | value | source |
|---|---|---|
| purchase price | $152.98 | live listing, 2026-09-16 |
| NJ sales tax 6.625 % → **taxed price** | **$163.12** | NJ Treasury / taxcloud, `40` §0; `61` §4.2 gives $489.35 for three ✓ |
| amortisation | **36 months** (the same convention `40` §4 uses) | `40` §4 |
| **upfront, per month** | **$4.531** | 163.12 ÷ 36 |
| idle draw | **12.7 W** — *meter-measured on the sibling 5090 Micro*; the 3090's own watts are **NOT measured** | `61` §4.2 |
| electricity | 12.7 W × 8.766 kWh/W·yr × $0.2495/kWh = $27.78/yr = **$2.315/mo** | EIA Table 5.6.A, June 2026 data, NJ residential 24.95 ¢/kWh, `40` §0 |
| **total cost of owning, per month** | **$6.846** | ARITHMETIC |

**The asymmetry that makes his question the right question:** a bought machine is on 24/7 — it *must* be,
to be in the mesh — so its cost is incurred whether or not it works. A rented machine is billed only while
it exists. **$6.846/month buys unlimited hours of the owned machine; the rental buys only the hours you
run it.** Break-even is therefore a number of hours, and nothing else.

### 4.2 Break-even hours per month — `h* = $6.846 ÷ hourly price`

| rented plan | $/hr | **h\* per month** | ≈ h/day | does not beat buying above | 24/7 costs |
|---|---|---|---|---|---|
| Hetzner CPX11 (2 vCPU / 2 GB, Ashburn) | 0.0328 | **209 h** | 6.9 | 209 h | $20.49/mo (cap) |
| Hetzner CPX21 (3 / 4) | 0.0601 | **114 h** | 3.8 | 114 h | $37.49/mo |
| Hetzner CPX31 (4 / 8) | 0.1178 | **58 h** | 1.9 | 58 h | $73.49/mo |
| **Hetzner CPX41 (8 / 16)** | 0.2267 | **30 h** | **1.0** | 30 h | **$141.49/mo** |
| Hetzner CPX51 (16 / 32) | 0.4479 | **15 h** | 0.5 | 15 h | $279.49/mo |
| Hetzner CCX13 (2 ded. / 8) | 0.0817 | **84 h** | 2.8 | 84 h | $50.99/mo |
| Hetzner CCX23 (4 ded. / 16) | 0.1650 | **42 h** | 1.4 | 42 h | $102.99/mo |
| Hetzner CCX33 (8 ded. / 32) | 0.2660 | **26 h** | 0.9 | 26 h | $165.99/mo |
| Fly `shared-cpu-2x` 2 GB (+$0.45 rootfs) | 0.0198 | **369 h** | 12.3 | 369 h | $14.24/mo |
| Fly `shared-cpu-4x` 8 GB (+$0.60 rootfs) | 0.0396 | **188 h** | 6.3 | 188 h | $28.48/mo |
| AWS spot `c7i.large` 2/4 (+$2.40 EBS, 30 GB gp3) | 0.0275 | **336 h** | 11.2 | 336 h | none documented |
| AWS spot `c7i.xlarge` 4/8 (+$2.40 EBS) | 0.0538 | **172 h** | 5.7 | 172 h | none documented |
| GCP spot `e2-standard-2` 2/8 | 0.040212 | **170 h** | 5.7 | 170 h | none documented |
| GCP spot `e2-standard-4` 4/16 | 0.080424 | **85 h** | 2.8 | 85 h | none documented |
| **Oracle A1.Flex 2 OCPU / 12 GB** | **$0** | **∞** | — | never | **$0, if it is not reclaimed** |

**Assumptions, named, so the arithmetic can be argued with:**
1. 36-month amortisation and the mini PC's electricity are the *only* owned costs counted. **No maintenance
   labour, no OS patching, no reboot window, no failure domain, no physical space** — `40` §4 states there
   is no authoritative dollar figure for that and calls it engineering judgement. They are real; they are
   omitted because they have no verified price.
2. Egress is ignored on both sides, because a fleet of agent turns is text: a 23-child fleet moves
   megabytes, not terabytes. **If any workload ever moves bulk data, AWS and GCP lose instantly** —
   $0.09/GB and $0.12/GB against Hetzner's ~$0.0012/GB.
3. The 12.7 W is the **5090's** measured idle, used for the 3090 because the 3090's is unmeasured. At
   **20 W** — the top of the SFF band `40` §5 says nobody has ever measured — the owned cost rises to
   **$8.18/mo (+19 %)** and every h\* in §4.2 rises by the same 19 %. It changes no ordering and no
   conclusion: the cheapest plan's h\* moves from 209 h to 249 h, still far above any plausible cadence.
4. Rental prices are **list** today; his invoice may be lower (he is on a legacy CX33).

### 4.3 The number that actually answers him: cost per fleet-hour

`h*` is about a single node running a long time. His load is not that — it is *bursty*, and the fleet is
the burst. Measured demand from the brief and from `40` §4: **1–3 concurrent agent turns typical, 9–23
during a fleet**, and **~1 generating turn ≈ 1 core**.

**A 23-child fleet needs ≈ 23 cores, so it needs ~24 rented vCPUs.** The "compared with buying" column uses
**4 × OptiPlex 3090 Micro = $652.47 taxed = 24 physical cores** (`61` §4.2), because 3 machines give only
18 cores and the comparison has to be by **cores**, which is the constraint `40` §4 measured to bind:

| how you buy 24 vCPU / ≥48 GB | shape | **cost per fleet-hour** | hardware it displaces | **fleet-hours to break even** |
|---|---|---|---|---|
| **Fly.io `shared-cpu-4x` × 6** (4 vCPU / 8 GB each) | per **second**, stopped ≈ $0.15/GB/30d | **$0.238/hr** | 4 × $163.12 = **$652.47** | **2 746 h** (≈ 53 yr at 1 h/wk) |
| **Hetzner CPX41 × 3** (8 vCPU / 16 GB each, Ashburn) | per hour, monthly cap | **$0.680/hr** | $652.47 | **959 h** (≈ 18 yr) |
| **Hetzner CPX31 × 6** (4 vCPU / 8 GB each) | per hour, monthly cap | **$0.707/hr** | $652.47 | **923 h** (≈ 18 yr) |
| **Hetzner CCX23 × 6** (4 dedicated vCPU / 16 GB) | per hour, monthly cap | **$0.990/hr** | $652.47 | **659 h** (≈ 13 yr) |
| **GCP spot `e2-standard-2` × 12** | per second (granularity unverified) | **$0.483/hr** | $652.47 | **1 352 h** (≈ 26 yr) |
| AWS spot `c7i.xlarge` × 6 (+EBS, +egress) | per second, 2-minute notice | **$0.323/hr** + EBS | $652.47 | **2 021 h** (≈ 39 yr) |

**Read the last column again: if a fleet runs one hour a week — 52 hours a year — renting 24 vCPUs instead
of buying 24 cores pays back in thirteen to fifty years, depending on which rental.** That is the honest
arithmetic, and it is the arithmetic that says **yes, rent the peak**.

But the same table says why the answer is still *not yet*: **it assumes the mesh can place 23 children
across six machines it has never met.** The broker's acceptance test (`71` §4.3) — "a 6-child fleet
produces 6 `MESH-HOST:` lines naming the nodes the broker chose, and at least two distinct nodes are named
when two are free" — **has not been run**. Renting six machines the dispatcher cannot fan out to is
$0.238/hr spent on nothing.

**And the counter-case, stated fairly.** A mini PC is not only peak capacity: it is on all the time, so it
also absorbs the *typical* 1–3 concurrent load, and it is a place a session can live. If his real problem
were baseline capacity, buying would win — a $163.12 machine costs $6.85/mo and a rented equivalent costs
$28.48–$141.49/mo for the same uptime. **The reason renting wins here is precisely the reason he gave:
he only needs it once in a while.**

---

## 5. The trigger, in this system's terms

### 5.1 What exists today, read out of the built code

`packages/mesh-broker/**` is **built, tested and running on the authority** (`76-broker.md`, 2026-09-16
23:15–23:21Z): 37/37 tests on Node v24.12.0 *and* v20.20.2; `POST /place`, `POST /done`,
`GET /nodes[?fresh=1]`, `GET /healthz`; roster in `packages/mesh-broker/nodes.json`
(`zabz-tech`, `zabz-yoga`, `zabz-tech-linux`, `secratary`); port 3091 **loopback only**; systemd unit
written but **not installed**.

The frozen arithmetic, verbatim from `71` §2.2:

```
slots = min(floor((freeMiB - 3885) / 160), 24) - governor.inUse
```

and the four rules that an elastic tier must not break: **it never refuses** (position is computed, never a
threshold); **it stores nothing it can go stale on**; **every decision is explainable** via `rationale`;
**a dead dispatcher cannot wedge the mesh** (leases are TTL'd, 900 s, and reaped by whoever reads them).

### 5.2 The elastic tier, precisely — four parts

**(a) A roster entry with a volatile flag.** `nodes.json` (a config file, not a frozen interface) gains:

```json
{ "node": "mesh-el-1",
  "baseUrl": "https://mesh-el-1.tail93e6e6.ts.net",
  "volatile": true,
  "hourlyUsd": 0.2267,
  "maxLifetimeSec": 3600,
  "provisioner": "scripts/mesh-elastic-up.sh",
  "excluded": false }
```

`excluded: true` already exists as the operator's hard switch (`76` §5.8); `volatile` is a new axis and
means *"this node may legitimately not exist"*.

**(b) A provisioner.** `scripts/mesh-elastic-up.sh`, which **wraps `scripts/provision-mesh-node.sh`** — the
script S2 wrote and proved — rather than inventing a second one, and which:
1. takes a **single-flight lock**, so two callers detecting the same burst do not boot two nodes (this is
   the governor's lesson, applied to money rather than to memory);
2. creates the instance via the provider API, waits for ssh, **joins the tailnet first**, then `scp`s
   `/etc/dsh-worker.env` from the authority over WireGuard (§3.2 — this is the ordering change);
3. runs the provisioner, then **polls `GET /mesh/capacity` until it returns a schema-1 object** — the same
   measurement the broker uses, so "ready" means ready *to the broker*, not "the process started";
4. records the instance id, the hourly price and the boot deadline **into a single file the teardown rule
   reads**, and writes one `journal append` line naming the node and who asked for it.

**(c) A teardown rule.** Destroy — **not stop**: a stopped VM still bills storage and still holds the key —
when the **first** of these is true:
* no broker lease has named the node for `idleSec` (default 600 s), **or**
* `maxLifetimeSec` (default 3600 s) has elapsed since the capacity route first answered.

Before destroy: `rsync` `~/.dsh/sessions` to the authority, delete any provider image of that VM, and write
the handoff line. **The hard wall-clock cap is not optional and it belongs to the provisioner, not the
broker** — the broker's 900 s TTL governs leases, and `71` §2.2 deliberately forbids the broker storing
node state.

**(d) The condition that fires it — and the design must not invent a threshold.** The owner said *"above a
certain percent use"*. **The frozen design deliberately has no threshold**: `position` is computed fresh
and the broker never refuses. So the honest analogue of "percent used" is the broker's own vocabulary —
the **tier** of a placement it just made:

| fire | do not fire |
|---|---|
| `POST /place` for a job you actually want to run **now** returns **`tier != "fits"`** — i.e. no node can start it and the mesh is in `highest-slots` or `queued` — **and** the same answer holds on a second, `?fresh=1` read ≥ 60 s later inside the same busy window. One reading is a burst; two a minute apart is a demand. | on a **percentage of free slots**, or on a wall-clock schedule, or on `governor.inUse`. That is the stale-threshold mistake `71` §2.2 exists to refuse. |
| only for **`kind = "fleet"` with `children ≥ 2`**. A fleet can amortise a 2–4 minute boot. | for **`kind = "oneShot"`**: a headless turn is **3–5 s** (`73` §1.3), so provisioning 2–4 minutes for it is a guaranteed loss of 30–50×. |
| when the *highest `slots`* on the mesh is genuinely too small for the job. | when the only node "blocking" is **`secratary` reporting `accepts.fleet:false`** — that is its designed state, not a shortage (`76` §7.2). |
| with a **spend cap**: at most N nodes, at most $X/hour, and an alarm if any node outlives `maxLifetimeSec`. | ever, for a job that `tier == "fits"` can place at `position 0` today. |

### 5.3 Is that an extension of the frozen design, or a change to it?

**It is one extension and one genuine change.** Being precise about which matters, because `71`'s own
preamble says a stream that needs a change "asks the manager, it does not change the interface".

**The change — `GET /nodes` (§2.2) must gain a third state.** Today a configured node is either reachable,
or it is reported as `{"node": …, "unreachable": true, "ageSec": n, "reason": …}`, and the contract says
*"a node unreachable is reported … never dropped, never faked."* A `volatile` node that has **never been
provisioned** is neither reachable nor unreachable, and reporting it as `unreachable` is **a false
statement about reachability** — the exact class of error `76` §5(11) already had to fix once, when a node
answering `mem.freeMiB: null` would have been called unreachable. So §2.2 needs:

> `{"node": "mesh-el-1", "absent": true, "reason": "volatile node, not provisioned"}` — **and `absent`
> nodes are excluded from `eligible`, are never chosen for placement, and are never counted as a failed
> read in the latency cache.**

**That is a change to a frozen interface and it needs the program manager's sign-off before it is built.**
It is small, it is additive, and it is still a change.

**Everything else is an extension that touches no frozen clause:**

* `nodes.json` gaining keys — it is a config file.
* `scripts/mesh-elastic-up.sh` / `-down.sh` — new files, wrapping S2's provisioner.
* The firing condition living in the **dispatcher** (`mesh-run`, S6) rather than the broker: `mesh-run`
  already receives `position` and `rationale`, and its exit contract (0 / 10 / 1, `71` §2.3) is unchanged
  by an elastic retry. The broker keeps doing exactly what §2.2 froze — it decides *where*, never *what to
  buy*.
* The gate's `/mesh/capacity` (§2.1) needs **no** change at all: it reports measurements, and a rented node
  that is up reports them like any other. That the capacity surface needed nothing was the whole point of
  putting it in the gate, and it holds here.

**Two collisions worth naming before anyone builds this:**
1. **`71` §0: "Sessions are node-local and do not move"**, and §5: *"Sessions moving between nodes — they
   cannot, by construction."* An elastic node is a **job runner only**. If the owner's mental model is
   "my agent keeps working on a rented computer", the answer is no.
2. **`71` §0: "One engine per `DSH_HOME`, one `DSH_HOME` per node."** A rented node must have its own
   `DSH_HOME` and therefore its own engine — which is fine — but it must **not** be handed a copy of an
   existing node's home, because two engines on one home corrupt session logs.

---

## 6. Recommendation

**Do it, in this order — and not yet, in the sense that the elastic tier must not be the first thing
built.** First, **finish the mesh you already have**: the broker is running on the authority with 37/37
tests and a measured live placement, but it serves `127.0.0.1:3091` only and nothing was added to
`tailscale serve`; publish it, run `71` §4's acceptance test, and confirm a 6-child fleet really produces
six `MESH-HOST:` lines on two distinct nodes. That is a day's work and it is the precondition for every
dollar below. Second, **make the two VPSs he already pays for into mesh nodes** — not for the turns, which
are ~1 and ~3 and zero fleets because both fail the frozen 20 GiB disk gate (`waze-mdm-01` by 1 GiB), but
because it is the only cheap way to prove the provisioner works against a host that is on neither the LAN
nor the tailnet, and it costs nothing but an evening. Fix the ordering first so the credential goes over
the tailnet rather than through the provider's user-data, because I read that user-data channel today and
it is real. Third, **only if the acceptance test shows a fleet that genuinely cannot place at `position 0`
while `ZABZ-TECH` (24 slots, 3 % busy) and `zabz-tech-linux` (12 cores, load 0.2, 48 ms) are both free**,
build the elastic tier in this order: the `volatile` roster flag and the `/nodes` `absent` state (which
needs the frozen-interface change approved), the provisioner wrapping S2's script with a single-flight lock
and tailnet-first credential delivery, the **hard node lifetime and the spend alarm**, and only then the
`tier != "fits"` firing condition. **Rent one node by hand once, time it end to end, and put the invoice
next to the measured benefit before automating anything.** What would have to be true first, as falsifiable
statements: a fleet that cannot place at `position 0` on an otherwise-idle mesh; a measured cadence of
≥ 2 fleets a week; a node TTL and an alarm that make a forgotten node impossible, because **a forgotten
CPX41 is $141.49 a month against $163.12 to own the machine outright**; and a credential path that never
puts the model key in the provider's metadata. **If he rents exactly one thing, the pick is Hetzner CPX11
in Ashburn at $0.0328/hr with a $20.49 monthly cap** — cheapest verified US-located turn, per-hour billing
with the cap stated in Hetzner's own words, and break-even against the $152.98 mini PC at **209 hours a
month**. **And the trap to name out loud: Oracle's always-free 2 OCPU / 12 GB ARM VM is bigger than any of
these and free forever — and Oracle reclaims it after seven days in which CPU, network and memory all sat
below 20 %. That is a description of an elastic node, so Oracle's free tier is a *resident* node, not a
burst one.**

---

## 7. What I could not verify

Stated as refusals, not as health.

1. **What he actually pays for the two VPSs.** No billing record exists in `harness-config`, the journal or
   either host; the invoice is in the Hetzner console under his login and I did not touch any account. The
   §1.2 figures are **today's list prices for the SKUs the measured hardware matches**, and the match is an
   inference.
2. **Whether `waze-mdm-01` is CPX11 and `lpt-apps-01` is CX33.** Hardware match + a config comment
   (`~/.ssh/config:236` "fsn1 cx33") + the metadata region/AZ. Not an order read. Command that would
   settle it: the Hetzner console's server list, or `GET /servers/<id>` with a project token.
3. **Hetzner's exact US included-traffic allowance.** Two of Hetzner's own files disagree (20 000 GB free
   vs a map reading as free to 1 TB). Extra egress is ~$0.0012/GB either way.
4. **AWS live spot price from a source AWS itself corroborates.** I read AWS's own spot feed; it carries no
   timestamp and AWS's own Spot Advisor implies different numbers for some types. Rows 17–20 are labelled.
5. **GCP Spot billing granularity** (per-second vs per-minute), and **GCP on-demand prices** for the same
   types — so **no GCP spot discount percentage is stated anywhere in this document.**
6. **Tailscale latency from a rented US-East or German node to the office.** Neither VPS has Tailscale
   installed; installing it was out of scope. The 10–20 ms estimate is an inference from geography and is
   labelled as one.
7. **Whether the gateway can issue per-node, revocable, scoped model keys.** Decides whether §3.2 is a
   rotation problem or a bookkeeping problem. I did not read the gateway's credential API.
8. **The provider's image/snapshot retention after server deletion** (Hetzner, Fly, AWS, GCP) — matters for
   §3.2 and unread.
9. **The measured idle wattage of an OptiPlex 3090 Micro.** §4.1 uses the 5090's measured 12.7 W.
10. **The cold-`npm ci` time on a *rented* host.** The 11 s figure is measured on an office LAN box. A VPS
    pulling from the public registry may differ; §3.1's 2–4 minute figure absorbs it either way.
11. **Whether the two VPSs would be reachable by the broker at all.** `76` §9 records that publication of
    the broker past the authority's loopback is undecided; until it is published, a VPS node could answer
    `GET /mesh/capacity` and still never be asked.
