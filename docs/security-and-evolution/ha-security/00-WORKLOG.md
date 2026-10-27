# HA security overhaul — working record

**Owner's ask, 2026-10-26 (verbatim):** *"we were in the middle of trying to fully redesign the whole
security system in home assistant by making it way more dependent on you, meaning you manage it. The AI
company actually in real time manages the security and alerts and all that. Less like strictly dead code.
Autonomous and I need to overhaul the entire system. See what we have, see what we can make out of it. Be
creative. I want to really build a secure system that isn't just some stupid automated code, but rather a
system that you manage and evolves and real time security gets done by real time agents in your AI company
and it evolves and gets smarter over time and learns more. And then after that's all ordered and done, then
you could create like a decisions document with what's left for us to decide together and go through. But I
first wanted to spend at least 50 rounds auditing researching and thinking of this."*

**Session:** 2026-10-26 ~21:15Z onwards, **ZABZ-YOGA** (home laptop, tailnet 100.72.162.5, LAN 192.168.1.x).

> Correction made in this session: I first wrote "I'm on ZABZ-TECH". That was an inference, not a
> measurement. `COMPUTERNAME=ZABZ-YOGA` settled it. Home LAN is 192.168.1.x; the shop LAN is 192.168.50.x
> (HA .34, `secratary` .77, linux-pc .23, desktop .138, mac-mini .45). From home, HA is reachable **only**
> through the tailnet, not by LAN.

---

## 0. Prior work this must extend, not repeat

Written today on ZABZ-TECH by another session, in `~/code/ha-config` (branch `ha/reconcile-20261019`),
copied here into `from-zabz-tech/`:

| File | Size | What it is |
|---|---|---|
| `HANDOFF-2026-10-26-security-audit.md` | 22.8 KB | state of the live system, 8 fixes deployed today, 12 open audits, traps, own errors |
| `security-audit-2026-10-26.md` | 80.5 KB | 84 numbered findings `S1`–`S84`, append-only, each with evidence |
| `security-system-design-2026-10-26.md` | 79.9 KB | 20 design rounds: the deterministic envelope, the record, the department, phasing, red team, economics |
| `reports/W1–W8`, `R1–R4` | ~390 KB | eight workstreams (adversarial, triggers, response chain, paging, detection, observability, red team, maintenance) and four data rounds |

**What that design already settles, so I do not re-derive it:**

- **The three laws.** (1) anything that must happen while the network is down happens in HA,
  deterministically; (2) the agent may always *add* force, never be the *only* force; (3) the agent may
  never *silence* — silencing needs a credential, an explicit owner instruction, or the envelope's timeout.
- **L0/L1/L2 split** with latency budgets: envelope ≤2 s to siren, ≤30 s to first page; triage agent verdict
  ≤60 s and its absence changes nothing L0 did; learning overnight, minutes to daily.
- **Four record tables** in `/root/authority.db`: `security_event`, `security_decision`, `security_label`,
  `security_action` — one writer, retention 90 d / 2 y / forever / forever.
- **The department does not exist yet.** `company_blueprint.DEPARTMENTS` has fourteen and none is security.
  (`dept_security` exists in the *other* lineage's blueprint — see the security-and-evolution handoff — this
  is a divergence to reconcile, not a duplicate to build.)
- **The autonomy trap:** `app/services/autonomy.py:376` defaults unknown actions to **L4 autonomous**. For
  security that is backwards; every security action must be explicitly registered.
- **Phasing with acceptance tests, shadow-first migration, red team (12 attacks), learning-loop attacks (7),
  economics.** All written, none running.

**What is genuinely missing for the owner's new ask** — this session's work: the system has no *runtime*.
The company's autopilot is hourly; there is no always-on security service, no event bus from HA into the
company, no agent that wakes in under a second, no identity resolution, no vision, no conversation with the
owner at 03:00, no learning pipeline that has ever promoted anything, and no measured cost model for
per-event agent work.

---

## 1. Facts measured in this session (each with how it was read)

| # | Fact | How |
|---|---|---|
| F1 | This session runs on **ZABZ-YOGA** | `COMPUTERNAME=ZABZ-YOGA`, `tailscale status --self` → 100.72.162.5 |
| F2 | HA is **alive**: ping True, TCP 8123 True from the shop desktop | base64 PS script over `ssh 100.85.153.96` |
| F3 | The company **can** reach HA in real time, over the tailnet | `/opt/company` on the authority: `settings.ha_url = http://zabz-tech.tail93e6e6.ts.net:8123`, `check_connection` → `{"connected": true, "version": "2025.10.3", "location_name": "Home", "components": 229, "state": "RUNNING"}` |
| F4 | The **public** HA URL is behind Cloudflare Access, so it cannot carry media or unauthenticated API calls | from the authority: `curl -D - https://ha.abletelsolutions.com/` → `HTTP/2 302`, `location: https://dawn-cell-26a7.cloudflareaccess.com/...`, JWT meta `"service_token_status":false` |
| F5 | The company's HA client is **REST only, synchronous, 15 s timeout, 25 s hard cap** — no websocket | `app/services/home_assistant.py` header and constants (lines 1–32) |
| F6 | The company has a real-time *shape* already: `event_queue.py`, `event_router.py`, `ceo_wake.py`, `trigger_engine.py`, `agent_worker.py` | repo service map; to be verified live (see round log) |
| F7 | The prior session's live HA facts stand: recorder keeps ~28 days, 1,036 entities, 15 intrusion episodes/30 d, zero unauthorised entries, no page ever delivered | `from-zabz-tech/HANDOFF...md` §1, §5 |

Warnings carried forward from the prior handoff (do not re-learn): `/api/logbook/<start>` truncates at 24 h
and exits 0; `shell_command` runs with a shell only when the command has **no** Jinja; `stop` ends the whole
script; `condition` aborts the sequence; restarting HA flaps entities and can re-arm; `last_triggered`
resets on restart.

---

## 2. Round log

Rounds are working passes, not messages. Every round writes here before the next one starts.

| # | Round | Output |
|---|---|---|
| 1 | Read the handoff I was given (`docs/security-and-evolution/HANDOFF-TO-NEXT-AGENT.md`) | company-side security dept + evolution engine, unrelated to the building but shares the word "security" |
| 2 | Survey the HA estate: `~/code/ha-config` tree, config, packages, automations, custom components | HA GitOps repo, 13 packages, 4 automation files, 7 custom components |
| 3 | Read the live security logic (`packages/phoenix_security.yaml`) | trigger list, 6 s grace window, script chain, rest_command page to the company webhook |
| 4 | Read `STATE-2026-09-17` + `SECURITY_CAPABILITY_MAP` | building map, door actuators, keypad/RFID, roster |
| 5 | Establish the network truth (own host, HA reachability, public URL) | F1–F4 |
| 6 | Establish whether the company can command HA | F3 — yes, over tailnet, via a proxy on the shop desktop |
| 7 | Owner correction: pull the ZABZ-TECH agent's work | found `ha-config` on that box, branch `ha/reconcile-20261019`, 8 commits of audit/design, 3 docs + 12 reports; copied here |
| 8 | Read the ZABZ-TECH handoff in full | the real state of play; 8 fixes deployed, 6 phases designed, 12 open audits |
| 9 | Read design rounds 5, 7, 8, 9, 10, 11, 12, 13 | the three laws, L0/L1/L2, the record, red team, learning attacks, economics, phasing |
| 10 | Fix the broken probe (`PYTHONPATH` — `python /tmp/x.py` puts `/tmp` on `sys.path`, not cwd) | open item closed. Second one on the authority: `/tmp/copy.py` shadows the stdlib the same way; run from `-c` or `/root` |
| 11 | Owner correction: pull the ZABZ-TECH agent's work — done, and it changed the job | `from-zabz-tech/` (3 docs + 12 reports) |
| 12 | Size the code the agents would replace | **188** automation blocks, **997** Jinja expressions, **58** `delay:` steps, `access_control.yaml` 92.7 KB (regex counts over `ha-config/config`) |
| 13 | Write the architecture spine (`10-ARCHITECTURE.md`) | reflex / mind / memory / constitution; the agent supplies facts, HA computes the boolean |
| 14 | Attack my own design | **found a hole I built**: an agent that writes `expected_empty` can silence the building. Fixed by construction in `40-SAFETY.md` §1.1 |
| 15 | Replace the invented siren delay with a standard | SIA **CP-01** timings + **AVS-01** levels, adopted from `research/E` |
| 16 | Write the operating model (`20-OPERATIONS.md`) | building state machine, escalation ladder, autonomy table, cost arithmetic, four KPIs |
| 17 | Verify the deployed reflex rather than trust the handoff | pulled live `phoenix_security.yaml` etc. byte-exact, sha256-matched; **the repo copy in this clone differs from what runs** |
| 18 | Read the live presence/credential files | **found the disarm-by-presence defect** (`05-LIVE-FINDINGS.md` L1) and measured it live |
| 19 | Prove the defect is live, not theoretical | `monty=home`, `worker_is_here=on` with the room empty, `intrusion_disarm last_triggered 21:06:07.627Z`, keypad handler `off` since 2025-12-16 |
| 20 | Measure the company's real path to HA | `/api/` 200 in **54 ms**, `/api/states` 1,037 entities in **66 ms**, page endpoint **170–471 ms** |
| 21 | Research lanes E and D returned | AVS-01/CP-01 adopted; learning loop = record first, learner later, six tables, monthly cadence, disarm is a *complaint* not evidence |
| 22 | Write the safety spine (`40-SAFETY.md`) | 14 attacks, the fail-safe ladder, the code-level allow-list, the two industry refusals |
| 23 | Read the live credential layer (`apartment_deadbolt_codes.LIVE.yaml`) | slot map: 1 Eliyahu, **4 = mother+father shared**, 5 Yocheved, 6 house-access, 11 tenant; one-writer-per-slot discipline |
| 24 | Resolve "who is Yocheved" from the record, not by asking | `D7429`: **his wife**, own full-access code 2026-10-18, delivered via him (no mobile on file); and `D7429`'s expected roster says **zero tenant** while slot 11 is live |
| 25 | Write the identity layer (`30-IDENTITY.md`) | what each credential proves, the registry shape, the plaintext-`pin_code` leak, the three identity rules |
| 26 | Verify D's claim about the evolution verifier | `evolution_verifier.py:424-432` → `status='passed', reason='timeout_neutral'`. **A timeout is recorded as a pass.** |
| 27 | Check whether the security department actually needs building | **it exists** on the authority (`company_blueprint.py:604`), `DEPARTMENTS` = **32** not 14 — but its mission is hosts/credentials/certificates, `repos` = personal-secretary, lpt-hub. **No HA, no `ha-config`, no building.** |
| 28 | Check whether a security table already exists | `sqlite_master` on `/root/authority.db`: **no** `security_*` table. The record is genuinely absent |
| 29 | Write the build plan (`50-BUILD-PLAN.md`) | 8 stages, acceptance test per stage, ~8 working days, and the 15-minute stage that removes the live hole |
| 30 | Cover the runtime lane myself while lane C ran | **`AUTOPILOT_INTERVAL_SEC=900`** (15 min, not hourly) and **no wake unit exists** on the authority: `systemctl list-units --all \| grep -i wake` → nothing |
| 31 | Verify "no page has ever been delivered" from the receiving end | `sms_log`: 4507 rows, **0** containing `LPT-SECURITY` |
| 32 | Write `OWNER-DECISIONS.md` | 10 decisions, each with the evidence, my recommendation, and what is mine instead |
| 33 | Journal the whole thing | `H13374` — handoff with the live defect, the measurements, the traps and the open decisions |
| 34 | Lane B (vision) returned, and it corrected three of my own premises | actual AI spend is **$9.62–$37.78/day**, not $5; **Google is excluded at the provider level** so every Gemini id is uncallable; **5 physical cameras**, not 7 |
| 35 | Re-costed the mind against the real ledger and fixed every place the wrong number appeared | `20-OPERATIONS.md` §4 rewritten; department table in `10-ARCHITECTURE.md`; decision #11 added |
| 36 | Measured the vision question instead of assuming it | Frigate+OpenVINO on the i5-11400 iGPU: **14 ms/frame**, ~71 fps vs ~25 fps load; blocker is `zabz` missing from the `render` group; Coral adds nothing at this camera count; cloud VLM **$0.000205/event** |
| 37 | Lane A (transport) returned and corrected two of my assertions | webhooks cannot report failure (200 on unregistered id and on handler raise); listener belongs on **`zabz-tech-linux`** (LAN 40 ms + tailnet), not the authority; **`company-api` has never been OOM-killed** — 66 of 69 kills are `transcript-archive-pull` |
| 38 | Lane C (agent runtime) returned and found the real blocker | **`events` table has 0 rows ever**; `autopilot.py:9322` passes `task_type=` to a `job_type=` parameter, the `TypeError` is swallowed and the event is marked processed; fastest working path is p50 **37 min**; and every HA service call is approval-gated, so **the company can read the alarm and cannot fire the siren** |
| 39 | Verified C's two load-bearing claims myself | deployed `autonomy.py:302` = `L1_SUGGEST` (**not** L4 — the prior design doc is stale), `UNSAFE_ACTIONS_ENABLED=false`, `HA_CALL_SERVICE_REQUIRES_APPROVAL=true`, `events` = 0 |
| 40 | Folded A's four plumbing fixes into the build plan | dedup index vs pending-only upsert; P0/P1 or 900 s; monotonic `seq` instead of `created_at`; resync + gap marker on reconnect |
| 41 | Reconciled a contradiction between my own doc and lane B | HA lists 25 camera entities; there are **5 physical cameras** (4 Dahua channels + doorbell), the rest are substreams, a stale placeholder and a channel-fallback duplicate |
| 42 | Found and added the IP-ban hazard to the token decision | `ip_ban_enabled: true`, threshold 5, bans written with no expiry → five bad-token attempts **from the proxy** ban `192.168.50.138` and cut every cloud→HA path at once |
| 43 | Wrote `25-MIND-CONTRACT.md` | the event bundle (and its three deliberate absences), the output schema with no `action` field, the five cases where the mind may not think, the 30-line fallback triage, and the 15-episode golden set that measures specificity only |
| 44 | Wrote `README.md` | the reading order for 41 files |
| 45 | Checked the design against all 84 prior findings | `45-FINDING-COVERAGE.md`: 52 addressed, 9 become owner decisions, 6 are hardware/money, **7 explicitly not fixed** — of which the unattributed webhook POST (S75) is a genuine loose end that should be closed on its own |
| 46 | Wrote the operator card | `60-OPERATOR-CARD.md` — what to do tonight, including that test mode is cleared by nothing (S40) and that walking in to test the alarm disarms it |
| 47 | Consistency pass on my own numbers | qualified the automation counts as floors (one file failed to parse); attributed the `ip_ban` threshold to research lane A rather than to a measurement I did not take |
| 48 | Re-measured the live defect before reporting it again | still true at **21:37:52Z**: `worker_is_here = on` since 21:06:07.424Z, room empty, `everyone_away = off` — **31 min 45 s** unarmed. Also corrected an invented timestamp of my own (`21:45Z` / "39 minutes") in `05-LIVE-FINDINGS` |

_(the audit, the five research lanes, the design, the coverage check, the operator card and the owner
decisions are complete. What remains is work that needs the owner's word: `OWNER-DECISIONS.md` items 1–11.)_
