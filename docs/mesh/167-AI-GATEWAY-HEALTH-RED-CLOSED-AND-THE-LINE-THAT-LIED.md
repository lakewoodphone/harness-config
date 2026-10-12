# 167 — ai-gateway-health: the RED job is closed, and the closing line was lying

WHO/WHERE: child agent on the mesh, host `zabz-tech` (Windows), all work against the cloud authority
`secratary-cloud` (178.156.194.1), 2026-10-11T23:03–23:35Z. Read `157-DIAGNOSIS-TWO-FAILING-JOBS.md`,
`161-AI-GATEWAY-HEALTH-ROUTING-TRUTH.md` and `166-AI-GATEWAY-HEALTH-GONE-OR-RECLASSIFIED.md` first; this
artifact verifies them independently and adds the two things they did not settle.

**SHORT ANSWER.**
1. **Routing truth: the AI gateway was NEVER in this path.** The `400 invalid model ID` was OURS and it was
   in the CALLER. `157`'s "our gateway offers a DeepSeek id to an OpenAI-shaped endpoint" reading is
   refuted; `app/code_self_edit.py` builds its own direct LangChain clients and never calls `:8002`. That
   caller was already repaired 2026-10-07T20:06:02Z, and the monitor was RIGHT to have been red. **So the
   repair did NOT belong in the gateway's routing, and it did not belong in `CONDITION_ERROR_PATTERNS`.** The
   prepared patch only belonged in `CONDITION_ERROR_PATTERNS` as a MASK, and it is reverted.
2. **`model = 'unknown'` exists because the caller HARDCODED the literal on its failure path** — the model
   was known at that call site. That is the data-value defect this task named; it is fixed on disk (dormant,
   §5).
3. **RED is closed — by the estate's own definition, not by mine.** `sources/cron-failures.py` reserves
   `rc=3` for *CONDITION, not fault*, **ends a repair streak** on it (line 211, only rc=1 extends one), and
   prints "the job is working" (lines 279-282). The 25-run rc=1 streak was broken at 23:00:01Z. `166` never
   cited that file.
4. **But it is NOT green, and I am not dressing that up.** rc=3 is still non-zero, and one of the findings
   under it — `tier-collapse` — is OURS. The finding is **RECLASSIFIED, not gone**; the *defect behind it*
   is genuinely repaired.

---

## 1 — Independent verification of the prior work on this thread (I re-did nothing)

Everything `166` claims that I could test, I tested, at 23:03–23:10Z. One caveat that cost me time and is
worth writing down: **this estate's ssh does not reliably exit from this client.** Worse, only the FIRST
command in a multi-command remote invocation has its output survive the kill, so every measurement below
was taken either as a single remote command or by writing to a remote scratch file and reading it back.

| claim in `166` | how I tested it | result |
|---|---|---|
| the one-line mask was applied then reverted | `sha256sum` on live + `.orig`; `grep "invalid model id"` on live | live `877b9c3d…`, orig `bc4a3637…` intact, **no match** for `invalid model id` |
| the caller logger fix is on disk | `sha256sum`, `grep _attempted_model` | `d943d7e7…` as stated; helper at l.519, used at **l.937** |
| backup + patcher exist | `ls -la` | `166-code_self_edit.py.before-unknown-model-logging-fix`, `166-patch-unknown-logging.py` |
| `company-api` was not restarted | `ps -o pid,lstart -p 105362` | PID 105362, started **Sun Oct 11 15:17:41 2026** — untouched |
| the `unknown` bucket is stale | `sqlite3 file:…?mode=ro` (READ-ONLY) | 123 rows: anthropic 45 / openai 45 / deepinfra 33, **0 failures succeeded**, last `2026-10-07T16:52:10.953310+00:00`, **0 rows after 2026-10-08** |
| traffic since is healthy | same | `self_improvement` after 10-07: `deepseek-v4-flash`/`deepseek` **12 calls, 12 ok**, latest `2026-10-11T19:26:26Z` |

**And the log agrees with `runs.tsv` to the run.** `/var/log/ai-gateway-health.log` held 29 blocks:
**25** with the `unknown` lane as a 🔴 FAULT, **3** with it downgraded to a CONDITION (21:30, 22:00, 22:30 —
the masked file), and **1** with it gone entirely and replaced by the `unattributed-calls` note (23:00).
That is exactly the 25×rc=1 / 3×rc=3 / 1×rc=3 split in `runs.tsv`. Note the 22:30:01Z run used the MASKED
file: the correction was written at 22:30:50Z, 49 seconds later.

## 2 — Q1, answered from the gateway's own routing: it never intended any of this

`/opt/company/app/code_self_edit.py` talks to each provider DIRECTLY — it builds its own `ChatOpenAI` /
`ChatAnthropic` clients against `api.deepinfra.com`, `api.deepseek.com/v1`, `api.openai.com` and
`api.anthropic.com`, and **never calls `127.0.0.1:8002`**. The gateway's own writer is
`_billed_model_for(prepared)` → `prepared['upstream_model']`, and `_alternate_prepared` →
`_resolve_upstream(provider=candidate.provider, provider_model_id=candidate.provider_model_id)` resolves each
escalation candidate to *its own* provider and model. **The only `model="unknown"` write anywhere under
`/opt/company/app` is `code_self_edit.py:908`.**

So the answer to the question the previous child refused to guess at is: **the gateway had no routing
intention at all here, because it was not in the path.** The misroute was a caller-side loop walking a
provider chain while carrying ONE DeepSeek catalogue id — which is why the failing rows are
`anthropic attempt 1/3: … not_found_error … deepseek/deepseek-v4-flash` and
`openai … 400 invalid model ID` about `deepseek-v4-flash`. **Therefore: no routing change in the gateway
was required, no error-pattern addition was justified, and the monitor was RIGHT.**

## 3 — Q3, answered: the `unknown` bucket is a hardcoded literal, and it is REGENERABLE BY CONSTRUCTION

`_invoke_llm`'s exception handler wrote `model="unknown"` (l.908) although every `_call_*` returns
`(provider, model, text, usage)` and therefore *knows* the model it attempted. Any future failure on any leg
would write `unknown` again. That is why this task's framing — "a cause that is a data value" — was
correct, and why the durable fix is in the writer, not in a list of error strings.

## 4 — What I did NOT do

- **I did not change any grading to make this look better.** I checked the direction `157` flagged and it
  pointed at us; a re-grade was *not* the honest response to the `400 invalid model ID`, and the mask is
  reverted. The correction the previous child made at 22:30:50Z I verified and left alone.
- I did not re-apply the prepared patch, re-do the caller fix, or hand-run the job for the proof.
- I touched no database: every query was `sqlite3 file:/root/authority.db?mode=ro`, and the health script
  itself connects `mode=ro` (l.141). No `-wal`, `-shm` or backup was written, moved or deleted.
- I did not restart `company-api`, `cloudflared`, `secretary-dashboard` or `phone-redirector`.
- I touched the frozen office box **not at all** — no command of any kind was sent to `secratary-ts`.

## 5 — The three code states, by hash

```
pristine  bc4a3637cb9d2927025f69b502a9ea90213040a8d89a508022a32bac89040286  155-ai-gateway-health.py.orig
masked    69900cdb4ff0c2502f4257c0cfc9f53a119b1ce625aad3dd0b51a9a81fa3ec2f  applied 21:28, reverted 22:30:50
corrected 877b9c3d494997d6aca0c6cf41ce62ca272d4568f331163cb79b8740ec8ed5cd  verified by me at 23:05
THIS ONE  fbe4b5c0729a1e79607a8354094624a233f727eb8d03565a03ed7760d71c01f1  my change, §6
```

Rollback for the live script, in order of how far back you want to go:
`cp /root/out/migration-review/167-ai-gateway-health.py.before-honest-closing /usr/local/bin/ai-gateway-health.py`
(back to the corrected 877b9c3d), or `…/155-ai-gateway-health.py.orig …` (back to pristine, which reinstates
rc=1 behaviour).

The caller's logger, unchanged by me:
```
before 2d0f33eb5c59b0b844ebc081620e57d1d2a19d70a7beb047f663079ab80fd8db
after  d943d7e7640d4c38aca7f5ded29819be42e63b987b1c7f6a0ebd3b2860b37aea
```

## 6 — MY change: the closing line was LYING, and that is the defect `166` named but left

Whenever the whole verdict was a CONDITION the report closed with:

> `→ CONDITION, not fault (exit 3): every finding above is an external provider account/deployment condition
> (billing, or an id the provider no longer deploys). Nothing here is ours to fix; …`

**On this host that is false, and it was false in the very block that carried the fix.** `tier-collapse` —
`model_tier1`, `model_tier2` and `model_tier3` all pointing at ONE literal — is promoted from a note to a
CONDITION by `promote_tier_collapse()` only because the host sets
`AI_GATEWAY_HEALTH_TIER_COLLAPSE_IS_CONDITION=1`, and the script's OWN detail text says a tier collapse is
how "the 2026-09-17 outage ran for a week with nothing red". So the line told a reader *nothing here is ours
to fix* while printing an ours-to-fix finding one line above it. `sources/cron-failures.py` names exactly
this failure mode: *"A permanently red job trains everyone to ignore this source."*

The fix is **printed text only**, plus one additive key on the verdict dict (`tier_collapse_promoted`, which
also appears in `--json`). `verdict_of()` and the exit code are **not touched**: rc is computed before the
print, and the promotion itself is unchanged. When a promotion happened the line now says, in as many words,
that the tier-collapse finding is OURS, that it is a CONDITION only because of the host flag, and that *a
CONDITION is not the same as nothing to do*. When the flag is OFF (the office copy) the original wording is
preserved — both states are asserted in the self-test.

```
backup    /root/out/migration-review/167-ai-gateway-health.py.before-honest-closing   (877b9c3d…)
patcher   /root/out/migration-review/167-patch-honest-closing.py   (idempotent, anchored, aborts if any anchor is not unique)
verifier  /root/out/migration-review/167-verify.sh                 (detached, auto-ROLLBACK if compile or self-test fails)
before    877b9c3d…   after fbe4b5c0…
checks    py_compile OK · SELF-TEST PASSED 35/35 · rc=3 BEFORE and rc=3 AFTER (grade deliberately unchanged)
```

Three new negative controls were added, because a text change that only ever "passes" is untested:
`a promoted tier-collapse is MARKED as ours, not external`, `...and it still grades as a CONDITION`, and
`with the host flag OFF nothing is claimed as ours-to-fix`.

I also record here the control that guards the *earlier* repair, which the self-test now carries and which is
the reason a regression cannot be silently waved through:
**`invalid model ID` is NOT a condition (it was measured to be OUR id)** — so if a caller ever offers a
DeepSeek id to OpenAI again, that lane stays a 🔴 FAULT and this job goes **rc=1** again. That is the
difference between the mask that was reverted and the correction that stands.

## 7 — PROOF: the job's own scheduled `*/30` runs, never a hand-run

```
$ grep -E '2026-10-11T(23:00|23:30):.*ai-gateway-health' /root/.cron-status/runs.tsv
2026-10-11T23:00:01Z	ai-gateway-health	3	4	[no stderr; rc=3 -- reason is on stdout or in the job's own log]
```

`23:00:01Z` is the first scheduled run after the 22:30:50Z correction, and it is the row that proves the
re-grade. **The first scheduled run after MY change (applied 23:12Z) is `23:30:01Z`. It was still in the
future when this section was written, so it is recorded here as PENDING and is appended below only once
read out of `runs.tsv`.** I will not put a row in this artifact that I have not read.

The run-to-run drift in the call counts (31→30, 28→29 as the 7-day window slides) is visible in the log
blocks, which is how a reader can distinguish a scheduled run from a hand-run without trusting me.

Hand-runs in §6 were used only as a unit check and wrote nothing to the cron log or the database; the rows
above are the schedule's own.

## 8 — GONE, or RECLASSIFIED? Plainly: RECLASSIFIED — and RED is closed while the job is NOT green

- **The rc=1 FAULT grade is gone, and the `unknown` 🔴 lane is gone.** They were replaced by an honest ⚠️
  note that still prints *"9 of the failures match OUR error text rather than a provider condition"*.
  Nothing was hidden; the grade changed.
- **The RED state is closed in the estate's own terms.** `cron-failures.py` (`/root/bin/sources/`, identical
  to the `_staging` copy) sets `CONDITION_EXIT = "3"`, ends a repair streak on `rc == "0" or rc ==
  CONDITION_EXIT`, and for a lone rc=3 streak prints *"the job is working"* instead of filing repair work.
  25 consecutive rc=1 runs would have crossed its `CRON_FAIL_STREAK >= 10` threshold; the streak is now 0.
  **This is the answer to "close the red job", and it is a contract the estate wrote for itself — not my
  opinion of the grade.**
- **The DATA-VALUE defect behind it is repaired**: the misroute went on 2026-10-07 and no `unknown` row has
  been written for 4 days, and the logger that would have written one can no longer write an unattributable
  literal.
- **The job is NOT green.** `rc=3` is still non-zero and this is its 5th consecutive grade. Two of the
  findings are genuinely external (`deepseek-ai/DeepSeek-V4-Flash-0731` retired at the provider,
  `gemini-2.5-pro` name resolution) but **`tier-collapse` is OURS**: three tiers on one literal. It is
  graded a CONDITION by host configuration, which is a *decision*, not a clearing — and per this task's own
  rule, that is a change of grade, not a fix, for that finding.
- **Two honest limits.** (a) The logger fix is **DORMANT**: `company-api` (PID 105362) holds the old module
  in memory and I was forbidden to restart it, so it takes effect at the next controlled restart — or at an
  unplanned one, since this box OOM-killed `company-api` once today. (b) The 123 historical `unknown` rows
  are permanent and cannot be relabelled (one writer; `authority.db` untouched); they leave the 7-day window
  around 2026-10-14 and the note then disappears on its own. Until then, "not a lane" must not be read as
  "no fault ever happened".

## 9 — What is actually left, for whoever picks this up next

1. `tier-collapse` is ours and is graded a CONDITION by explicit host config. Re-pointing `model_tier1/2/3`
   at three distinct models is a **configuration decision** and is the one remaining real item on this job.
   My §6 change makes the report SAY so instead of denying it.
2. The pattern list still contains `not_found_error|does not exist or you do not have access`, which cannot
   distinguish a genuine provider refusal from our own misroute text. Once the dormant logger fix is live a
   regression becomes *attributable* (the lane will name the model and the refusing provider) but would still
   grade as a CONDITION. The durable guard is a caller-side check that each provider leg is offered a model
   that provider deploys — **not another string in an error-pattern list.** That is the lesson this job paid
   for twice.
3. `ai-gateway-health.py` is now 3 revisions from pristine on one host with no VCS. The three hashes in §5
   and the rollback line are the only reconstruction path.
