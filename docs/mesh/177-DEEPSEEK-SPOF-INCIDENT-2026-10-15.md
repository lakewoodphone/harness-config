# 177 — The 2026-10-15 DeepSeek outage: blast radius, and the single point of failure it proved

**Written:** 2026-10-15 ~03:00Z · ZABZ-YOGA · incident document, not a post-mortem of a fix (nothing was fixed yet)
**Provider incident:** `status.deepseek.com/incidents/7116348214287`
**Owner's framing:** *"we can't have a single point of failure that if a deep sea api is down, then we're done for"*

---

> ## STATUS: DEFERRED — do not start this without the owner
>
> **Owner's instruction, 2026-10-15:** *"document as this needing to happen eventually and we'll get to it."*
>
> The work in §6 is **agreed and deliberately postponed**. It is a known open defect, not an
> in-progress build. Nothing here has been implemented; §7 describes the state *after* the outage,
> not after a fix.
>
> **When it is picked up:** the design constraints in §6 are the spec, and the one open question is
> the money cap, for which the recommendation is already worked out — **USD 10 per day** for the
> fallback tier, about 770 calls at the ~217k-token loop size, which covers an outage without letting
> a runaway loop spend the owner's money. That number is his to confirm, not mine to assume.
>
> **Do not file this as a company task.** The company's task queue is executed by the autonomous
> departments; filing it there would start the build without him. It is recorded here, in journal
> decisions, and as the open pain **P4121**, deliberately.
>
> **The defect is still live:** as of this writing, if DeepSeek stops answering, every DSH session on
> ZABZ-TECH, ZABZ-YOGA and SECRATARY stops with it.

---

## 0. The finding in one paragraph

On 2026-10-15 between **00:11Z and at least 02:48Z**, DeepSeek's inference API stopped answering and
every DSH session on every machine the owner uses stopped with it. The company survived — its gateway
has had a real escalation chain since before today and it carried the load on Gemini — but **the
harness did not fail over at all**: it retried the dead provider and gave up. The reason is one
literal model id (`deepseek-official/deepseek-flash`) shared by three machines, with no automatic
provider fallback anywhere in DSH. A second provider (DeepInfra, via `llm-pi-ai`) is already mounted
and was never used. That is the single point of failure, and it is still there as of this document.

---

## 1. The event, from the provider's own record

Source: `status.deepseek.com/incidents/7116348214287`, read 2026-10-15T02:54Z. Times are **UTC** (the
owner's screenshot rendered them as 08:11 PM America/New_York — same incident, same instant).

| time (UTC) | state |
|---|---|
| 00:11 | Investigating — "The issue is being investigated to identify the cause." |
| 00:14 | Investigating |
| 01:06 | Identified — "The cause has been identified and a fix is being implemented." |
| 01:08 | Identified |
| ~02:48 | **Still "Identified · Full Outage", elapsed 2h37min** |

Affected components: **DeepSeek V4 Pro API service** and **DeepSeek V4.1 Flash API service**.

**The page is still open and the incident is not marked resolved.** At 02:41Z, however, a live
inference call to `api.deepseek.com/chat/completions` returned **HTTP 200 in 2003 ms**. Both are true:
the API is serving again while the provider has not yet closed the incident. Verify with a live
inference call, not with the status page, and not with `/models` (see §8.1).

---

## 2. The blast radius, measured

### 2.1 The company (authority `secratary-cloud`)

Source: `model_usage` table on `/root/authority.db`, queried via `ps_db_query` at ~02:47Z, filtered to
`created_at >= '2026-10-15T00:00' AND <= '2026-10-15T03:00'`. This is a `T`-separator comparison —
see §8.2 for why that matters.

**Nine failed model calls in the window.** Longest single call: **23 minutes 3 seconds.**

| time (UTC) | model | tier | latency | error |
|---|---|---|---|---|
| 01:19:47 | deepseek-v4-flash | fast | 1,383,408 ms (**23m03s**) | Request timed out. |
| 01:32:24 | deepseek-v4-flash | fast | 723,416 ms (**12m03s**) | Request timed out. |
| 01:35:21 | deepseek-v4-flash | ceo | 3,121 ms | 503 — "Service is too busy. We advise users to temporarily switch to…" |
| 02:00:18 | deepseek-v4-flash | fast | 3,272 ms | 503 — same |
| 02:22:23.944 | deepseek-v4-pro | mid | 900,385 ms (**15m00s**) | no_choices: upstream returned no choices |
| 02:22:23.960 | deepseek-v4-pro | mid | 900,415 ms | same |
| 02:22:24.001 | deepseek-v4-pro | mid | 900,438 ms | same |
| 02:22:24.018 | deepseek-v4-pro | mid | 900,452 ms | same |
| 02:22:35 | gemini-3.1-pro-preview | ceo | 11,406 ms | finish_reason_length: upstream response was truncated |

The four `deepseek-v4-pro` rows at 02:22 are one fan-out of four parallel calls, each pinned at the
900-second ceiling, every one returning **no choices at all**. The 23-minute and 12-minute rows are
what "nothing would go when I type a question" actually measures.

**The gateway carried the company, and it did so itself.** `app/services/ai_gateway.py` has an
escalation chain and a `_should_try_fallback(reason_code)` path that retries the request on the next
candidate. It fired today:

- DeepSeek `deepseek-v4-flash` volume per hour on 2026-10-14 ran 6–143 calls, and 55–143 in the busy
  hours. In the **01:00Z hour on 2026-10-15 it was 14** (11 ok, 3 failed).
- **`gemini-3.5-flash-lite` was absent from 07:00Z to 23:00Z on 2026-10-14 — seventeen hours — and
  returned for the three hours of the outage** (00:00Z 109, 01:00Z 102, 02:00Z 109 calls).

Stated precisely: that **coincides** with the outage and is the mechanism that kept the company
answering. It is not proof on its own, because DeepSeek volume has quiet hours too (6 and 12 calls in
single hours on 2026-10-14).

**Company API.** `company-api.service` restarted **gracefully at 00:25:19Z** — the log shows
"Waiting for application shutdown" → "Application shutdown complete" → systemd `Stopped` → `Started`.
`NRestarts=0`, so systemd did not restart it after a crash; something asked it to stop. The unit
`company-api-liveness.service` ("Restart company-api when it is ALIVE BUT NOT ANSWERING — the
73-minute freeze of 2026-10-14") runs every 2 minutes and is a live candidate, **but I did not find
the log line that attributes this restart, so I am not claiming which.** Uptime at check: 2h17m.

**Ticks.** `tick_telemetry` recorded **0 ticks in the 01:00Z hour**. Read with care: 2026-10-14
already had five empty hours (09, 11, 16, 21, 23), so the tick cadence is irregular by nature and this
is one additional gap, not a collapse from a steady baseline.

**`error_log` is blind to this class of failure.** The whole window holds **two rows**, both
`db_contention`, at 00:26:54 and 00:31:54. An outage that produced nine model failures and 28 harness
retries produced two database-contention rows. `error_log` records unhandled exceptions only.

### 2.2 DSH across the mesh — this is where the owner felt it

Source: `dsh_session_events` on the authority, queried ~02:50Z over the same window.

- **Twenty sessions were affected, across three machines: `zabz-tech`, `zabz-yoga`, `zabz-tech-linux`.**
  Every node that ran a session in the window shows damage. `secratary` (frozen anchor) and
  `lakewooechsmini` had no session activity in the window.
- **Five sessions have a turn that started and never ended** (`turn/start` with no matching
  `turn/end`) — the signature of a hang:

  | machine | session | turn starts | turn ends | retries |
  |---|---|---|---|---|
  | zabz-tech | `9fda7c73-2e56-4a16-8715-44510656ea1c` | 1 | **0** | **6** |
  | zabz-tech | `d7696601-c9a0-49c5-91aa-11a74da0f84f` | 1 | **0** | 1 |
  | zabz-tech | `d8dbded0-9979-47e4-9026-4208da4b62d7` | 1 | **0** | 1 |
  | zabz-tech | `a2cb81f7-eaf1-42ad-89be-94c739dd0a9a` | 1 | **0** | 0 |
  | zabz-yoga | `e3046949-fabe-4c4d-b5c3-58a92846d976` | 1 | **0** | 0 |

- **28 `llm/retry` events in the window, and every single one names `provider: "deepseek-official"`.**
  Sample, verbatim from the raw event:
  `{"type":"llm/retry","seq":396,...,"data":{"retryId":"560760bb-...","turn":1,"step":58,"provider":"deepseek-official","mode":"normal",...}}`
  That is the whole defect in one field: **the retry policy retries the provider that is down.**
- Event volume per hour: 00:00Z **7,601**, 01:00Z **5,996**, 02:00Z **408**. **Do not read the
  02:00Z figure as a collapse** — see §8.5.

### 2.3 Customer-facing

Source: `ps_comms_waiting`, read ~02:47Z, index age 0.1h (fresh).

**21 parties waiting, 17 missed calls.** Of those, only four fall inside or after the outage window:

| party | waiting | last message |
|---|---|---|
| +18483897895 | 1.1h | "Didn't we already go through that it's my wife's professional liability insurance…" |
| Bayla Stein | 0.7h | "How long does it take because we can't not have the phone at this time" |
| (848) 240-3774 | 0.7h | voicemail — 246 device that doesn't charge |
| Jon Meyer | 0.4h | missed inbound call, 0s, hangup |

**The other seventeen are between 3 and 49 hours old and predate the outage by a day or more.** They
are a standing backlog, not outage damage, and it would be wrong to present them as such. Note also
that this was read at ~22:47 local, when the shop is shut and a night-time unanswered text is normal.

---

## 3. Why it was *total* — the single point of failure, named

**One literal, three machines.**

- `settings/base.yaml:58-60` declares `agent-default-model: { provider: deepseek-official, model: deepseek-flash }`.
- `scripts/harness-sync.mjs` merges `base.yaml` + `settings/machines/<HOSTNAME>.yaml` (machine wins)
  into `~/.dsh/settings.yaml` on every node.
- Machine-file override count, measured today: **`DESKTOP-FGV6KMH.yaml` 2, `LAKEWOOECHSMINI.yaml` 2,
  `SECRATARY.yaml` 0, `ZABZ-TECH.yaml` 0, `ZABZ-YOGA.yaml` 0.**
- So **the owner's own three machines all inherit the same single literal**, and the only two that
  override it are machines he does not work on.

**The same literal is stated a second time, in the composition:**

```
profiles/web/cordis.patch.yml:1739: { id: agent-default-model, config: { provider: deepseek-official, model: deepseek-flash } }
```

Two surfaces, one value. Per `AGENTS.md` §6.3 they must move together or one will silently win.

**A second provider is mounted and is never used automatically.**

```
profiles/web/cordis.patch.yml:143: - id: llm-pi-ai
profiles/web/cordis.patch.yml:1742: { id: llm-pi-ai, config: { providers: { deepinfra: { apiKeyEnv: DEEPINFRA_API_KEY, api: openai-completions, baseURL: https://api.deepinfra.com/v1/openai, models: [ … ] } } } }
```

`llm-pi-ai` **is** mounted. DeepInfra **is** registered with a key ref. Nothing routes to it. It is a
second provider in the catalog, not a fallback.

**There is no provider-fallback code to find.** `grep -i "fallback|failover"` over
`@deepseek-ai/dsh-llm` and `@deepseek-ai/dsh-llm-pi-ai` in the installed engine
(`C:\Users\ezabz\.dsh\engine\node_modules\`) returns **no matches**. The retry policy is the only
resilience that exists, and it is pinned to one provider — proven by all 28 retry events naming
`deepseek-official`.

**Therefore:** when DeepSeek stops answering, every session on every machine the owner uses stops, and
the harness retries the corpse until the policy is exhausted.

---

## 4. What already exists — do not rebuild any of it

Surveyed per the `estate-systems` skill before any design sentence.

| need | already here | state |
|---|---|---|
| Company-side multi-provider routing with escalation | `personal-secretary-mvp` `app/services/ai_gateway.py` — `_OPENAI_COMPAT_UPSTREAM` covers openai, anthropic, google, deepinfra, fireworks; escalation chain + `_should_try_fallback` | **Working.** Carried the company today. |
| Anthropic reachable from the company | `/opt/company/.env` holds `ANTHROPIC_API_KEY`; gateway maps `anthropic -> https://api.anthropic.com/v1` | **Configured.** |
| Whole-company failover to another host | `lpt-survivor-01:/opt/company/deploy/hosting-migration/scripts/company-promote.py` (dry-run by default, refuses on two writers) | Exists, proven 2026-10-06. Not used today. |
| Offsite backup | `~/bin/push-db-offsite.sh` → Cloudflare R2; `company-offsite-push.sh` → restic | Exists. |
| DSH second provider (adapter) | `llm-pi-ai` with DeepInfra | **Mounted, unused.** |
| API liveness watchdog | `company-api-liveness.service`, every 2 min | Running. |

The gap is **not** "the estate has no failover". The gap is that **DSH's own model path has none**, and
the company's chain does not include the tier the owner has already paid for.

---

## 5. What is missing

1. **No automatic provider fallback in DSH.** The retry policy retries one provider. Nothing switches.
2. **The owner's Claude key is not in any ladder.** A live probe of `claude-haiku-5-5` returned
   **HTTP 200 in 1079 ms** at 02:41Z. The capability is paid for, present in `~/.dsh/.credentials.yaml`,
   and wired to nothing.
3. **No alert when the primary provider dies.** This outage was **discovered by the owner, from a
   status page, hours in** — not by the estate. Nothing in this system watches provider health.
4. **The company's ladder has no Anthropic rung** despite the key being configured on the authority.

---

## 6. The backup: design constraints for implementation (next work, not done)

Recorded now so the implementation has a spec. These are constraints, not a finished design.

1. **Fail at the provider layer, automatically.** Trigger on hard failures — connect error, 5xx, and
   timeout — with no human edit, no restart, and no session death. A config change is not a backup.
2. **Define it once.** In `harness-config` (`settings/base.yaml`), reaching every node by the existing
   sync. A per-machine file is what produced today's drift.
3. **Change both surfaces together.** `settings/base.yaml:58-60` **and**
   `profiles/web/cordis.patch.yml:1739` state the same literal.
4. **Resolve model ids at runtime from the provider catalog.** Standing instruction 2026-09-15; the
   catalog read today returns `claude-haiku-4-5-20251001` and `claude-haiku-5-5`, and DeepSeek's
   returns `deepseek-flash` and `deepseek-v4-pro`. Never hardcode — `deepseek-v4.1-flash` is REJECTED
   by the API.
5. **Cap the fallback tier in money.** See §7.3 for the measured cost shape.
6. **Alert on the primary dying.** The next outage should be announced by this estate, not found by
   the owner.
7. **Do not break the working company chain.** `ai_gateway.py` is an asset; add a rung, do not replace
   the mechanism.

**Measured cost shape for the fallback tier** (from journal `L3394`/`L3395`, Artificial Analysis
Intelligence Index v4.3.2): Haiku 5.5 scores **43** (#2 of 182) against DeepSeek V4.1 Flash **39**
(#7 of 117). Haiku leads on the row that matters most here — AA-Omniscience **11 against DeepSeek's
minus 5**, i.e. DeepSeek answers confidently wrong more often than it abstains, on an estate that has
been burned by confident wrong numbers. Cost inverts above 100k prompt tokens: Haiku at USD 0.50 in /
2.50 out per million against DeepSeek off-peak 0.15 / 0.60, and our agent loops sit near 217k tokens.
So **Haiku is the right failover and the wrong default** — expect roughly 7–10x per call at loop size,
which is exactly why it must be capped and must only fire on a hard failure.

---

## 7. Current state, verified 2026-10-15 02:41–02:54Z

| check | reading | source |
|---|---|---|
| DeepSeek inference | **HTTP 200, 2003 ms** | live `POST /chat/completions` |
| Anthropic `claude-haiku-5-5` | **HTTP 200, 1079 ms** | live `POST /v1/messages` |
| Provider incident | still "Identified · Full Outage", 2h37min | status page, 02:54Z |
| `company-api.service` | **active**, uptime 2h17m, `NRestarts=0` | systemd on authority |
| `cloudflared.service` | **active** | systemd on authority |
| `mesh-broker.service` | **active** | systemd on authority |
| `company-api-liveness` | firing every 2 min, completing successfully | journalctl |
| Authority disk | **68% used, 48.6 GB free** | `df -Pk /` |
| Authority memory | 15.6 GB total, **10.9 GB available** | `free -m` |
| Mesh `zabz-tech` | ok, 75 ms, children 0/8 | `/nodes?fresh=1` 02:42:34Z |
| Mesh `zabz-yoga-1` | ok, 180 ms, children 0/5 | same |
| Mesh `zabz-tech-linux` | ok, 59 ms, children 0/4 | same |
| Mesh `secratary` | **unreachable** — the FROZEN rollback anchor; expected, not breakage | same |
| Mesh `lakewooechsmini` | **unreachable** — Yisroel's Mac | same |
| Broker read health | reads 473, **readFailures 219 (46.3%)** | same |

**Verdict: everything is running.** Both model paths answer, the company is up and serving, all three
live mesh nodes answer in under 200 ms. Two standing items are not new today: the frozen box and the
Mac are unreachable, and those two are the whole explanation for the 46% broker read-failure rate —
the broker keeps probing a box that is frozen by policy and a machine that is off.

---

## 8. Measurement traps hit while writing this — for the next reader

Each one is a place where a confident number would have been wrong.

**8.1 `/models` is the catalog, not the service.** My first probe asked `api.deepseek.com/models`,
got HTTP 200, and I told the owner "DeepSeek is up" **while inference was down**. The endpoint that
failed was `/chat/completions`. **Probe the surface that fails, not the surface that is cheap.**

**8.2 These timestamps use a `T` separator, and a space silently matches everything.**
`created_at >= '2026-10-14 20:00'` is true for *every* `2026-10-14T…` string, because `'T' (0x54) >
' ' (0x20)`. My first window queries returned ~24 hours while appearing to return the window. Use
`>= '2026-10-15T00:11'` with the `T`.

**8.3 `dsh_sessions.updated_at` is INGEST time, not activity.** "45 sessions written during the
outage" measured the hourly ingest job touching rows. The per-event truth is in `dsh_session_events`.

**8.4 `error_log` undercounts by design.** Two rows for this outage. It holds unhandled exceptions
only — handled model failures are counted in `model_usage`, if anywhere.

**8.5 A window that is still open cannot be compared to a closed one.** The 02:00Z event bucket reads
408 against 5,996 an hour earlier, which looks like a collapse and is mostly **ingest lag** — the
bucket was under an hour old at query time. Do not compare a partial bucket to a complete one.

**8.6 A high failure rate needs its denominator.** `readFailures 219` looks alarming until the node
list shows the failures are addressed to a deliberately frozen box and a switched-off Mac.

**8.7 Knowledge split across surfaces is how this was possible at all.** The fact that the model was
pinned for three machines lived in a `base.yaml` comment and a composition literal. The person who
wrote the composition warning put it in **YAML comments, which are never injected into a session**
(`AGENTS.md` §7). A rule in a comment has no reader.

---

## 9. Sources

- Provider: `https://status.deepseek.com/incidents/7116348214287` (read 2026-10-15T02:54Z)
- Authority DB `/root/authority.db`: `model_usage`, `tick_telemetry`, `error_log`, `dsh_sessions`,
  `dsh_session_events` (via `ps_db_query`, ~02:47–02:52Z)
- Host: `secratary-cloud` systemd, `journalctl -u company-api`, `journalctl -u company-api-liveness`,
  `df -Pk /`, `free -m`, `curl /nodes?fresh=1` (02:41–02:54Z)
- Live provider probes: `POST api.deepseek.com/chat/completions`, `POST api.anthropic.com/v1/messages`
  (02:41Z)
- Business: `ps_comms_waiting` (02:47Z)
- Config: `settings/base.yaml:58-60`, `settings/machines/*.yaml`, `profiles/web/cordis.patch.yml:143,1739,1742`
- Prior art: journal `L3394`, `L3395` (Haiku 5.5 vs DeepSeek V4.1 Flash, cost and intelligence);
  `docs/mesh/000-SYSTEMS-REGISTER.md`
- Owner's screenshot of the incident (2026-10-15)
