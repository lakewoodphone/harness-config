# 166 — ai-gateway-health: is the finding GONE, or only RECLASSIFIED?

WHO/WHERE: child agent on the mesh, host `zabz-tech` (Windows), all work against the cloud authority
`secratary-cloud` (178.156.194.1). Read `157-DIAGNOSIS-TWO-FAILING-JOBS.md` §2 and
`161-AI-GATEWAY-HEALTH-ROUTING-TRUTH.md` first; this artifact does not repeat them. Every number below was
measured on the authority at 2026-10-11T22:52–23:00Z, most of it twice.

**Short answer.** The routing question is settled: the AI gateway was NEVER in this path, so the gateway
never intended to offer a DeepSeek id to an OpenAI-shaped endpoint — the misroute was ours and it was in the
CALLER (`app/code_self_edit.py`), and it was already repaired on 2026-10-07. The `model='unknown'` bucket
exists because the caller's failure path HARDCODES the string `unknown` instead of the model it tried; that
defect is still in the live file and is the real data-value defect. The job is NOT closed: it is rc=3, and
rc=3 is reached by an honest re-grade, not by a repair. The finding is NOT gone — but the *defect behind it*
is, and the wrong half of the prepared patch has been reverted.

---

## 1 — Q1: does the gateway intend to offer that `model` id to that provider? NO — it is not in the path at all

`/opt/company/app/code_self_edit.py` builds its OWN LangChain clients and talks to each provider DIRECTLY.
It never calls the gateway (`127.0.0.1:8002`):

| caller function | transport it builds itself | base_url |
|---|---|---|
| `_call_deepinfra` (l.536-552) | `ChatOpenAI` | `https://api.deepinfra.com/v1/openai` (or `api.fireworks.ai/inference/v1`) |
| `_call_deepseek` (l.590-592) | `ChatOpenAI` | `https://api.deepseek.com/v1` |
| `_call_openai` (l.630-631) | `ChatOpenAI` | default (`api.openai.com`), `settings.openai_api_key` |
| `_call_anthropic` (l.666-667) | `ChatAnthropic` | default, `settings.anthropic_api_key` |

Corroboration that the gateway is not the writer: the gateway's own logger is
`_billed_model_for(prepared)` -> `prepared['upstream_model']` (`services/ai_gateway.py:3692`), and the ONLY
occurrence of a `model="unknown"` write anywhere under `/opt/company/app` is
`code_self_edit.py:908`. The gateway's escalation chain resolves each candidate to *its own* provider and
model (`_alternate_prepared` -> `_resolve_upstream(provider=candidate.provider,
provider_model_id=candidate.provider_model_id)`, `ai_gateway.py:4325-4360`), so an escalation candidate is
never offered under another provider's id.

**So `157`'s hypothesis is refuted in the direction that matters, and the monitor was RIGHT that these rows
were ours.** The misroute was real: `_invoke_llm` walked a provider chain while carrying ONE DeepSeek
catalogue id, so OpenAI and Anthropic were each handed `deepseek-v4-flash` /
`deepseek/deepseek-v4-flash` and each answered 404; on 2026-10-07 api.openai.com answered
`400 invalid model ID`. The repair belongs in the caller, and it was made there, on disk, at
**2026-10-07T20:06:02Z** (backup `code_self_edit.py.bak-agwprovider-20261007T200602Z` — 3h after the last
bad row at `2026-10-07T16:52:10Z`): the chain now puts `deepseek` FIRST, `_call_openai` sends
`gpt-5.4`/`gpt-5.4-mini`, and `_call_anthropic` sends `claude-opus-4-6`/`claude-sonnet-4-5`. The source
comments say so in as many words.

## 2 — Q3: why does a bucket have `model = 'unknown'` at all? A hardcoded literal on the failure path

`_invoke_llm`'s exception handler (`code_self_edit.py:900-910`):

```python
err_msg = f"{prov_name} attempt {attempt}/{_MAX_LLM_RETRIES}: {exc}"
_record_llm_usage(
    settings,
    provider=prov_name,
    model="unknown",          # <-- l.908: the literal, not a model
    usage=None, latency_ms=latency_ms, success=False,
    error_message=err_msg[:500], tier=llm_tier,
)
```

The model IS known at the call site — every `_call_*` returns `(provider, model, text, usage)` and the
provider function chose the literal itself — but the exception path throws that away and writes a constant.
That is why the bucket is unattributable and why it is *regenerable by construction*: any future failure on
any leg writes `unknown` again. `company-api` (uvicorn :8002) was started 2026-10-11T15:17:41Z from this
file, so the running process carries the literal.

## 3 — The precise mechanism of rc=1 (this REFINES `157`, it does not just repeat it)

`157` said the rc=1 had "one cause: a bucket whose model column literally reads `unknown`". Measured, that is
half the story. **The pristine script already contained `not_found_error` and `does not exist or you do not
have access` in `CONDITION_ERROR_PATTERNS`** (verified: `155-ai-gateway-health.py.orig`), and a lane is
downgraded to a CONDITION only when its faults are *entirely* condition text. In the 7-day window the
`unknown` bucket held **24 calls / 24 failures, of which 15 match a condition pattern and 9 do not** — and
exactly those **9** are the `400 invalid model ID` rows, i.e. OUR malformed id. 15-of-24 is not all, so the
lane stayed a FAULT: 🔴, and `runs.tsv` recorded rc=1 for **25 consecutive runs, 2026-10-11T09:00:01Z
through 21:00:01Z**.

MEASURED, both copies run by hand read-only on the SAME data and the same cron env, seconds apart:

```
ORIG  (155-...orig)          -> rc=1   and the ONLY 🔴 in the report is `unknown`
LIVE  (corrected, 877b9c3d)  -> rc=3   no `unknown` lane; a ⚠️ note naming 9 OUR-text failures
```

And the prepared patch's diff against pristine was **one line**: it appended `|invalid model id` to the
condition pattern. That single string is what turned 9 unmatched faults into 9 matched conditions, which is
what flipped rc=1 -> rc=3 at 21:30Z. **So the prepared patch was a mask, and it is now reverted.**

## 4 — State found, verified by hash (nothing was re-done)

```
ORIG  bc4a3637cb9d2927025f69b502a9ea90213040a8d89a508022a32bac89040286  155-...py.orig      mtime 08:29:56Z
PREP  69900cdb4ff0c2502f4257c0cfc9f53a119b1ce625aad3dd0b51a9a81fa3ec2f  161-...before-...   mtime 21:28:42Z
LIVE  877b9c3d494997d6aca0c6cf41ce62ca272d4568f331163cb79b8740ec8ed5cd  /usr/local/bin/... mtime 22:30:50Z
```

The prepared patch WAS applied (at 21:28) and then superseded at 22:30:50Z by the correction diffed in §3
of `161` — reverting `invalid model id`, and making an unattributable bucket a note while it has no recent
traffic. I re-derived both from the files rather than trusting the summary.

## 5 — The plain answer to "gone, or reclassified?"

- The **misroute** is GONE: repaired in the caller 2026-10-07, and `agent_id=self_improvement` has written
  zero `unknown` rows since 2026-10-07T16:52:10Z (4 days), while succeeding normally on `deepseek`.
- The **rc=1 -> rc=3 change is a change of GRADE**, exactly as the task warned. But for once the re-grade is
  the *correct* one, because the surviving 15-of-24 condition matches are genuine (Anthropic/OpenAI really
  did return `not_found_error` for an id they do not deploy — a fact, not an excuse), and the 9 rows that
  were ours are no longer *called* external. What the job no longer does is turn red for them.
- The **residual rc=3 is NOT this finding**: it is `tier-collapse` (`model_tier1/2/3` all point at
  `deepseek/deepseek-v4-flash` — that one is OURS, and the script grades it a CONDITION by explicit
  configuration) plus two stale `failing-historical` lanes (deepinfra's retired `DeepSeek-V4-Flash-0731`,
  `gemini-2.5-pro`). So ai-gateway-health remains non-zero for reasons that this task did not ask me to fix.
- **The logger defect is NOT gone** — see §2. That is the one thing that is genuinely still wrong.

## 6 — What I changed

### (a) The health script — NOT re-done by me; verified only

The correction the previous child on this thread made at 22:30:50Z is exactly the right shape and I left it
in place. Verified from the diff itself (`161-...before-routing-correction` -> live): it reverts the one-line
`|invalid model id` mask (§3), and turns an `unknown` bucket with `recent_calls == 0` into a ⚠️
`unattributed-calls` note that still prints the honest count — the live run says verbatim *"9 of the
failures match OUR error text rather than a provider condition"*. A recurrence with live traffic keeps the
normal grading. Rollback if ever needed:
`cp /root/out/migration-review/155-ai-gateway-health.py.orig /usr/local/bin/ai-gateway-health.py`.

### (b) The caller's logger — MY change (this is the actual data-value defect)

`/opt/company/app/code_self_edit.py`, one line plus one new pure function:

```
-                    model="unknown",
+                    model=_attempted_model(settings, prov_name, llm_tier),
```
plus `_attempted_model(settings, provider, llm_tier)`, which returns the model that leg would attempt
(including `_call_deepinfra`'s Fireworks switch) and, for an unrecognised provider, `"<provider>:<tier>"`
rather than collapsing back to a constant.

```
backup     /root/out/migration-review/166-code_self_edit.py.before-unknown-model-logging-fix
before     sha256 2d0f33eb5c59b0b844ebc081620e57d1d2a19d70a7beb047f663079ab80fd8db
after      sha256 d943d7e7640d4c38aca7f5ded29819be42e63b987b1c7f6a0ebd3b2860b37aea
checks     py_compile OK; helper 12/12 cases (5 providers x 2 tiers + fireworks + unknown-provider)
patcher    /root/out/migration-review/166-patch-unknown-logging.py  (idempotent, re-runnable)
rollback   cp /root/out/migration-review/166-code_self_edit.py.before-unknown-model-logging-fix \
             /opt/company/app/code_self_edit.py
```

**Honest limit on (b): it is DORMANT and cannot be verified by the cron run.** `company-api`
(PID 105362, started 2026-10-11T15:17:41Z, `NRestarts=1`) holds the already-imported module in memory, and
the task forbids restarting it, so the fix takes effect only at the next controlled restart — and an
unplanned one (this box OOM-killed `company-api` once today) will also load it. I made it the smallest
possible change for exactly that reason: the new helper is a pure function of `(settings, provider, tier)`
that cannot raise, and no existing call path was restructured. I did NOT write to `authority.db` and did not
touch `-wal`/`-shm` or any backup.

## 7 — Proof: the job's own next scheduled `*/30` run (not a hand-run)

```
$ grep '2026-10-11T23:00.*ai-gateway-health' /root/.cron-status/runs.tsv | cat -A
2026-10-11T23:00:01Z^Iai-gateway-health^I3^I4^I[no stderr; rc=3 -- reason is on stdout or in the job's own log]$
```

`/var/log/ai-gateway-health.log` mtime `2026-10-11 23:00:05.433140802 +0000`, size 47078 — that file is
written only by the crontab entry's own `>> /var/log/ai-gateway-health.log 2>&1`, so the block below is the
scheduled run, not a hand-run. It carries the marker `unattributed-calls`, a string that exists ONLY in the
corrected script (grep count 1 in the newest 40 lines), which is how cron's run is distinguished from
mine:

```
  🟠 failing-historical     deepseek-ai/DeepSeek-V4-Flash-0731 — 31 of 31 ... [CONDITION: provider account/deployment error]
  🟠 failing-historical     gemini-2.5-pro — 16 of 23 ... [CONDITION: provider account/deployment error]
  🟠 tier-collapse          deepseek/deepseek-v4-flash — model_tier1/2/3 all point at one literal. GRADED AS A CONDITION (exit 3) ...
  ⚠️  retired-lane           29 of 29 calls failed (100%) ... Recorded, not current.
  ⚠️  unattributed-calls     24 of 24 calls over 7d were recorded as `unknown` by the caller, so they name no
                            lane at all; last seen 2026-10-07T16:52:10.953310+00:00. 9 of the failures match OUR
                            error text rather than a provider condition. This is NOT a failing model: it is the
                            caller logging a failure without the model it tried (app/code_self_edit.py ...).
  → CONDITION, not fault (exit 3)
```

**So: gone, or reclassified? RECLASSIFIED — and I will not dress that up.**

- The **rc=1 is gone and the `unknown` lane is gone**, but the **nine our-text failures are still on the
  page**, as a ⚠️ note that prints their number. Nothing was hidden; the *grade* changed.
- The *defect* behind them is genuinely gone, and that is the only reason the re-grade is defensible: the
  caller's routing was repaired 2026-10-07, and no `unknown` row has been written for 4 days.
- **`ai-gateway-health` is still NOT green: rc=3 is its fourth consecutive grade.** I am not claiming
  closure of the job. The residual rc=3 is *other* findings — `tier-collapse` (ours, graded a CONDITION by
  explicit configuration) and two stale `failing-historical` lanes — none of which is the data value this
  task named.

## 8 — Residual limits, stated so the next reader is not misled

1. The 123 historical `unknown` rows are permanent. `authority.db` has one writer and I did not touch it, so
   they cannot be relabelled; they leave the 7-day window around 2026-10-14 and the note then disappears by
   itself. Until then, "not a lane" must not be read as "no fault ever happened".
2. The corrected script's blind spot: an unattributable bucket whose failures STOP before the 6-hour recent
   window becomes a note instead of a fault. A *live* recurrence still fires, but a burst of our own faults
   that ends can be quietly downgraded — that is the price of the re-grade, and it is worth knowing.
3. `tier-collapse` is three tiers on ONE literal — that is OURS — yet it is graded a CONDITION by explicit
   configuration, and the report's closing line ("Nothing here is ours to fix") is therefore overbroad. That
   is the next honest thing to fix in this job, and it is not the finding this task named.
4. The condition patterns `not_found_error|does not exist or you do not have access` are still
   indistinguishable from our own misroute text. Once my logger fix is live, a regressed misroute would be
   *attributable* (the lane would name the model and the provider that refused it) but would still be graded
   a CONDITION, not a fault. The durable guard is a caller-side check that each provider leg is offered a
   model that provider actually deploys — not another string in an error-pattern list.
5. My caller fix is **dormant**: `company-api` was not restarted (forbidden), verified still PID 105362,
   unchanged, throughout.
6. Diagnostics were read-only. The two hand-runs wrote nothing to `authority.db` and nothing to the cron log
   (output went to `/tmp`); the proof row in §7 is the scheduled one.
