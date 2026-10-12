# 161 — ai-gateway-health: the routing truth, the wrong patch, and the repair

WHO/WHERE: child agent on the mesh, host `zabz-tech` (Windows), work done on the cloud authority
`secratary-cloud` (178.156.194.1). Read `157-DIAGNOSIS-TWO-FAILING-JOBS.md` §2 first; this artifact does not
repeat it.

## 0 — The question this was sent to settle

`157` §2.6 flagged its own patch as a HYPOTHESIS: either `400 invalid model ID` is a provider condition (the
OpenAI endpoint refusing an id, like the 404s beside it) — in which case adding the string to
`CONDITION_ERROR_PATTERNS` is right — or it is OUR gateway offering a DeepSeek id to an OpenAI-shaped
endpoint that can never accept it — in which case the monitor was RIGHT and the repair belongs in the
routing, not in an error-pattern list. `157` said the distinguishing fact is "whether the gateway *intends*
to try that id on that provider".

**Answer: it does not. The second reading is the true one, and the repair belonged in the caller. It had
already been made in the caller, on disk, before this session. The prepared patch was therefore the WRONG
repair and I have corrected it.**

## 1 — State found: the prepared patch was ALREADY APPLIED

```
LIVE  sha256 69900cdb4ff0c2502f4257c0cfc9f53a119b1ce625aad3dd0b51a9a81fa3ec2f  /usr/local/bin/ai-gateway-health.py
ORIG  sha256 bc4a3637cb9d2927025f69b502a9ea90213040a8d89a508022a32bac89040286  .../155-ai-gateway-health.py.orig
```

LIVE == the "after" hash in `157`; ORIG == the "before" hash. mtime `Oct 11 21:28`. Nothing to re-do.

## 2 — And it had already changed the grade, exactly as predicted

`/root/.cron-status/runs.tsv`, every `ai-gateway-health` row (rc is field 2):

```
2026-10-11T10:00:01Z	ai-gateway-health	1	3      <- rc=1 on every run 09:00Z .. 21:00:01Z (25 rows)
2026-10-11T21:30:02Z	ai-gateway-health	3	7      <- patch landed 21:28
2026-10-11T22:00:02Z	ai-gateway-health	3	4
```

The 21:28 patch turned rc=1 into rc=3.
MEASURED, from the file itself: 28 `ai-gateway-health` rows for 2026-10-11 — 25 at rc=1 (2026-10-11T09:00:01Z .. 2026-10-11T21:00:01Z) and then 3 at rc=3 (2026-10-11T21:30:02Z .. 2026-10-11T22:30:01Z); no other code appears. rc=1 was this job grade for 12.0 hours before the 21:28 patch, and rc=3 has held for every run since.
 Per this estate's standing rule, that is a CHANGE OF GRADE. It is not
by itself a fix, and I do not present it as one.

## 3 — The truth: this was OUR misroute, not a provider condition

`authority.db`, read-only, 7-day window; every row in the `unknown` bucket carries `agent_id=self_improvement`,
`tier=fast`:

```
openai    |2026-10-05T20:18:44Z| openai attempt 1/3: Error code: 404 - The model `deepseek-v4-flash`
                                does not exist or you do not have access to it. (model_not_found)
openai    |2026-10-05T20:18:46Z| openai attempt 2/3: (same)
openai    |2026-10-05T20:19:02Z| openai attempt 3/3: (same)
anthropic |2026-10-05T20:19:04Z| anthropic attempt 1/3: Error code: 404 - not_found_error,
                                message: model: deepseek-v4-flash
anthropic |2026-10-05T20:19:06Z| anthropic attempt 2/3: (same)
anthropic |2026-10-05T20:19:10Z| anthropic attempt 3/3: (same)
openai    |2026-10-07T15:17:11Z| openai attempt 1/3: Error code: 400 - {'error': {'message':
                                'invalid model ID', 'type': 'invalid_request_error'}}
openai    |2026-10-07T15:17:13Z| openai attempt 2/3: (same)
openai    |2026-10-07T15:17:17Z| openai attempt 3/3: (same)
anthropic |2026-10-07T15:17:18Z| anthropic attempt 1/3: Error code: 404 - not_found_error,
                                message: model: deepseek/deepseek-v4-flash
... 24 rows total; 6 at 2026-10-05, 18 at 2026-10-07; last one 2026-10-07T16:52:10Z
```

Grouped exactly (14-day window, `error_message LIKE '%invalid model ID%'`):

```
openai|unknown|9|2026-10-07T15:17:11Z|2026-10-07T16:52:03Z
```

Read as one logical call: (1) `openai` is handed `deepseek-v4-flash` — a DeepSeek provider id — and answers
404 `model_not_found`; (2) the chain escalates to `anthropic` with the SAME DeepSeek id — another 404; (3) on
2026-10-07 the id escalated to the CATALOGUE form `deepseek/deepseek-v4-flash` and api.openai.com answered
`400 invalid model ID` — a slash-bearing slug it will never accept. That, and not any provider condition, is
what the nine fault-class rows are.

So the "dead route" reading is refuted twice over: the endpoint was live, and the id we sent it was ours and
wrong for that provider. In this estate's own history, a `400 invalid model ID` from api.openai.com is
evidence of OUR malformed id — the opposite of an external condition.

## 4 — Why a bucket has `model = 'unknown'`: a hardcoded logger literal

`model_usage.model` is normally the provider-side id (`ai_gateway._billed_model_for()` returns
`prepared['upstream_model']`). This bucket is not written by the gateway at all. It is written by the CALLER,
`/opt/company/app/code_self_edit.py`, in `_invoke_llm()`'s failure path:

```python
err_msg = f"{prov_name} attempt {attempt}/" f"{_MAX_LLM_RETRIES}: {exc}"
...
_record_llm_usage(
    settings,
    provider=prov_name,
    model="unknown",          # <-- line 908: the literal that creates the whole bucket
    usage=None, latency_ms=latency_ms, success=False, error_message=err_msg[:500], tier=llm_tier,
)
```

`agent_id` on every row is `self_improvement`, which is this module's own agent id — the correlation is
exact. The failure site knows only `prov_name`; the model id being attempted is chosen one frame down inside
`_call_openai` / `_call_anthropic`, so "unknown" is literally all the failure site can name without a
refactor. **That is the answer to "why unknown": it is a failure-only attribution placeholder — a DATA defect
in the caller's logging, not a gateway catalogue problem.** The 15 condition-class rows in the same bucket are
real provider conditions (402 / 404 not-deployed); the 9 fault-class rows are our misroute.

## 5 — The caller defect is already repaired on disk

`code_self_edit.py` lines 613-679 carry the post-mortem of exactly these rows and now give each provider its
own model:

```
# MEASURED: the OpenAI call was handed the DeepSeek catalogue id `deepseek/deepseek-v4-flash`, and
# api.openai.com ... answered `400 invalid model ID` on all three retries of every run; the
# attempts were recorded as model='unknown' ...
model = "gpt-5.4"          # _call_openai
...
# api.anthropic.com answered `404 ... not_found_error ... model: deepseek/deepseek-v4-flash`
model = "claude-opus-4-6"  # _call_anthropic
```

This is the repair `157` said belonged in the routing. It is in place. Verification follows in §6.

## 6 — Verification of the caller repair (to be completed)

_(filled in below as it is measured)_

## 6 — Verification of the caller repair: it is live, and traffic proves it

```
/opt/company/app/code_self_edit.py   mtime 2026-10-07 20:06:02 UTC   (70891 bytes)
company-api (uvicorn 127.0.0.1:8002) MainPID 105362, started 2026-10-11 15:17:41 UTC
```

The caller was repaired **3h 14m after the last bad row** (2026-10-07T16:52:10Z), and the running API
process started *after* that repair, so the repaired caller is the code the authority is executing.

`model_usage`, `agent_id=self_improvement`, 10-day window, grouped:

```
deepinfra |deepseek-ai/DeepSeek-V4-Flash-0731|success=1| 13 |2026-10-01T23:20Z|2026-10-02T19:52Z
deepinfra |unknown                          |success=0| 33 |2026-10-02T21:19Z|2026-10-04T09:50Z
openai    |unknown                          |success=0| 45 |2026-10-02T21:19Z|2026-10-07T16:52Z
anthropic |unknown                          |success=0| 45 |2026-10-02T21:19Z|2026-10-07T16:52Z
deepseek  |deepseek-v4-flash               |success=1| 12 |2026-10-07T20:06Z|2026-10-11T19:26Z
```

Every `self_improvement` row written after the repair is a **success on `deepseek/deepseek-v4-flash`**
(11 rows after 2026-10-08, latest 2026-10-11T19:26:26Z) and there is **no openai/anthropic row after
2026-10-07T16:52:10Z**. The cross-provider offer is gone in real traffic, not just on disk.

Note also the second `unknown` bucket (`deepinfra`, 33 failures, 2026-10-02 .. 10-04) — same logger literal,
earlier provider chain. It has already aged out of the 7-day window.

## 7 — The prepared patch was the wrong repair, and I corrected it

**Why it was wrong.** The patch taught the monitor that `invalid model id` is an external provider condition.
The evidence says the opposite: that string was produced by **our own id** handed to api.openai.com, and the
rows were written by a caller that **bypasses the gateway entirely** (`code_self_edit.py` calls providers
through LangChain and writes `model_usage` itself with its own `openai attempt N/3` format at line 900).
`157` asked whether the gateway *intends* to offer that id to that provider: the gateway never saw these
calls at all, and no `model_registry` row pairs `openai`/`anthropic` with a DeepSeek id (the DeepSeek rows
are `deepseek`, `deepinfra`, `fireworks` only, and the fireworks ones are `retired`). So the pattern said
"external condition" about a defect of ours — and would have hidden the very recurrence the monitor exists
to catch.

**What I changed** (`/usr/local/bin/ai-gateway-health.py`):

| | |
|---|---|
| backup | `/root/out/migration-review/161-ai-gateway-health.py.before-routing-correction` — sha256 `69900cdb4ff0c2502f4257c0cfc9f53a119b1ce625aad3dd0b51a9a81fa3ec2f` |
| patcher | `/root/out/migration-review/161-patch.py` — sha256 `a7e070baaa2df937fe21628a2cee006acb81d370dcfd4dad719a9a00fff75b2b` (re-runnable, all 4 anchors asserted) |
| before | sha256 `69900cdb4ff0c2502f4257c0cfc9f53a119b1ce625aad3dd0b51a9a81fa3ec2f` |
| after | sha256 `877b9c3d494997d6aca0c6cf41ce62ca272d4568f331163cb79b8740ec8ed5cd` (49783 bytes) |
| rollback to the applied patch | `cp /root/out/migration-review/161-ai-gateway-health.py.before-routing-correction /usr/local/bin/ai-gateway-health.py` |
| rollback to pristine | `cp /root/out/migration-review/155-ai-gateway-health.py.orig /usr/local/bin/ai-gateway-health.py` (`bc4a3637cb...`) |

1. **Removed `|invalid model id` from `CONDITION_ERROR_PATTERNS`** — restores the pristine list. A `400
   invalid model ID` from api.openai.com is, in this estate's own history, evidence of OUR malformed id. The
   genuinely external "the provider no longer serves this id" phrasings (`model not found`, `not_found_error`,
   `does not exist or you do not have access`, `not deployed`, `no such model`) stay in the list — and the
   2026-10-05 half of this very bucket was caught by them.
2. **`UNATTRIBUTED_MODEL = "unknown"` is graded as an attribution note, not as a lane** — but only while it
   has NO traffic in the recent window. A bucket with recent failures keeps the normal grading, so a live
   recurrence is still a **FAULT within one 30-minute run**. This is the same shape the file already uses for
   retired lanes: history stays visible, the false claim goes.
3. **Four negative controls added to `--self-test`**, including the one that matters: `invalid model ID` must
   NOT classify as a condition, and a LIVE `unknown` bucket must still fire. `--self-test` → `SELF-TEST
   PASSED`; `py_compile` clean.

## 8 — Before/after composition, measured with the cron's own environment

Both versions run read-only (`--json`) with the full cron env (`AI_GATEWAY_HEALTH_DB=/root/authority.db`,
`..._CONFIG=/opt/company/app/config.py`, `..._CATALOGUE=1`, `..._KEY_FILE=/opt/company/.env`,
`..._TIER_COLLAPSE_IS_CONDITION=1`):

```
OLD (the applied patch)  rc=3
  problems: failing-historical deepseek-ai/DeepSeek-V4-Flash-0731 condition=True
            failing-historical gemini-2.5-pro                 condition=True
            failing-historical unknown                        condition=True   <-- FALSE CLAIM
            tier-collapse     deepseek/deepseek-v4-flash      condition=True
  notes   : retired-lane accounts/fireworks/models/deepseek-v4-flash-0731

NEW (this correction)    rc=3
  problems: failing-historical deepseek-ai/DeepSeek-V4-Flash-0731 condition=True
            failing-historical gemini-2.5-pro                 condition=True
            tier-collapse     deepseek/deepseek-v4-flash      condition=True
  notes   : retired-lane accounts/fireworks/models/deepseek-v4-flash-0731
            unattributed-calls unknown   ("24 of 24 calls over 7d were recorded as `unknown` by the
                                          caller, so they name no lane at all; last seen
                                          2026-10-07T16:52:10Z. 9 of the failures match OUR error text
                                          rather than a provider condition. This is NOT a failing model")
```

## 9 — Gone, or merely reclassified? Plainly.

* **The rc=1 FAULT is gone, and it is gone for a causal reason**: the caller defect that produced the only
  fault-class evidence in that bucket was repaired on 2026-10-07T20:06Z and is verified live by the app's own
  post-repair traffic (§6). Nothing about the fault needed the pattern list to change.
* **It is not merely reclassified either.** The applied patch left the run at rc=3 *while asserting something
  false* — that the `unknown` lane's failures were all external conditions. My correction keeps the run at
  rc=3 but the false assertion is replaced by a true note that names the 9 rows as OURS, and the false rule
  is removed so a recurrence cannot be waved through.
* **But I will not overclaim**: the exit code was 3 before my change and 3 after it. My correction changed
  *what the record says and what the rule is*, not the number. The number moved from 1 to 3 earlier, at
  21:28, by the previous child's patch.
* **The remaining rc=3 is earned by three separate conditions, none of them this bucket**: DeepInfra
  `402 positive balance` (`deepseek-ai/DeepSeek-V4-Flash-0731`, 47/47, last 10-05), `gemini-2.5-pro`
  name-resolution failures (16/25, last 10-08), and the tier collapse (`model_tier1/2/3` all
  `deepseek/deepseek-v4-flash` — real, recorded in `157` §2.5, and the one thing here that is still a
  configuration defect).
* **The window self-clears anyway on ~2026-10-14** (`157` §2.6), because `created_at` ages out of the 7-day
  window. That is why I did not treat "wait for it to go away" as a fix.

## 10 — Proof: the job's own next scheduled run

The job's cron line is `*/30 * * * * /usr/local/bin/cron-wrap.sh ai-gateway-health <env> /opt/company/.venv/bin/python
/usr/local/bin/ai-gateway-health.py`; `cron-wrap.sh` appends one row per run to `/root/.cron-status/runs.tsv`.
Measured, in order:

```
2026-10-11T09:00:01Z .. 2026-10-11T21:00:01Z   ai-gateway-health  1   (25 consecutive scheduled runs — the red job)
2026-10-11T21:30:02Z                          ai-gateway-health  3   <- applied patch landed 21:28
2026-10-11T22:00:02Z                          ai-gateway-health  3
2026-10-11T22:30:01Z                          ai-gateway-health  3   <- still the applied patch (I patched at ~22:41)
```
`<the 23:00 run is appended below when it lands — held until the scheduled run, never run by hand>`

## 11 — What I did NOT do, and the residual defect

* **Did not touch `/opt/company/app/code_self_edit.py`.** The durable cure for question 3 is there: its
  failure path can only name `prov_name`, because the model id is chosen one frame down in
  `_call_openai`/`_call_anthropic`. Recording it needs a small refactor (surface the attempted model out of
  the provider call and pass it to `_record_llm_usage` at line ~908). A disk-only edit would not take effect
  until `company-api` restarts, and restarting `company-api` is forbidden in this session (it was OOM-killed
  once today), so I did **not** leave an unverifiable change in a live service. **Residual defect, stated
  plainly: a future failure in this caller is still logged as `model="unknown"` and is still unattributable.**
  The monitor's new rule bounds the damage: such a bucket with recent failures is still a FAULT, and when
  quiet it is a named note.
* **Did not open `/root/authority.db` read-write.** Every query used `file:...?mode=ro` with
  `PRAGMA query_only` semantics (the `sqlite3 -readonly` flag); no `-wal`/`-shm`/backup was touched, and no
  row was written or deleted.
* **Did not restart** `company-api`, `cloudflared`, `secretary-dashboard` or `phone-redirector`; did not go
  near the frozen office box (`secratary-ts`).
* **Did not print any credential value.** The gateway's bearer is read through
  `AI_GATEWAY_HEALTH_KEY_ENV`/`_KEY_FILE` by the monitor itself; I only ever referenced those variable names.
  The cron line's env prefix is base64-encoded in the crontab and I did not decode credentials from it.

## 12 — Judgement call worth reviewing

Removing `invalid model id` means a *genuine* external "provider does not serve this id" reported with that
exact OpenAI wording would now grade as a FAULT. I made that trade deliberately: in this estate the string
has only ever been measured as OUR malformed slug, the external cases all use other phrasings that remain in
the list, and a false "external condition" is the more expensive error — it is what kept this job's record
unreadable in the first place. If a real external case of that wording appears, the correct move is a
*narrower* pattern (e.g. requiring `does not exist` beside it), not this one.

## 13 — Addendum: the note is visible in the job's own stdout

The job's stdout is its record (`cron-wrap.sh` line 145 says so in as many words:
`[no stderr; rc=3 -- reason is on stdout or in the job's own log]`), so the new note has to reach it. The
human printer at the end of `main()` does print notes:

```python
        for n in verdict["notes"]:
            print("  ⚠️  %-22s %s" % (n["kind"], n["detail"]))
```

so the scheduled run's output will carry `⚠️  unattributed-calls 24 of 24 calls over 7d were recorded as
`unknown` by the caller ... 9 of the failures match OUR error text`. Verified by reading the code and by the
`--json` run; the scheduled run's own stdout is the proof and lands below.

**One imprecision I did not change, and am flagging instead.** The rc=3 summary line prints *"every finding
above is an external provider account/deployment condition (billing, or an id the provider no longer
deploys)"*. That is now inexact: one of the three remaining rc=3 findings is `tier-collapse`
(`model_tier1/2/3` all pointing at one literal), which is a **configuration** defect and is therefore ours
to fix, not a provider's. It was already inexact before this session (the env-gated
`AI_GATEWAY_HEALTH_TIER_COLLAPSE_IS_CONDITION=1` promotes it, while the summary text still calls every
condition a provider condition). I left the wording alone because it is not part of this job's cause and
changing user-visible text without a need is how unrelated breakage gets introduced; it is recorded here so
the next reader is not misled by the summary line.
