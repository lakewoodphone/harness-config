# ROUND 5 HANDOFF — the delta

**Written 2026-10-15 00:0xZ by the session that followed round 4, on ZABZ-YOGA.**
**Read [`HANDOFF-ROUND4.md`](HANDOFF-ROUND4.md) first.** It is still the spine: its §2 (five things
done), §3 (what is deployed), §4 (the loop's measured state), §7 (the traps) and §9 (how to work with
him) all stand, and this session did not re-verify them. This file is only what changed.

---

## 1. THE ONE THING TO KNOW

**Round 4 §5 said the instruction surface was "not started". That was wrong in one direction and right
in the more important one: it had been started, and none of it had reached him.**

Commits `895012f3` (08:58) and `723c600b` (09:14) on 2026-10-14 rewrote the persona — the four new
rules, and the compression of the do-not-ask block that round 4 §5 was *still asking for*. Round 4
read `presets/zabz/agent.cordis.yml` (correct, 09:14) and concluded the work was absent, because the
surface it can see is not the surface a session loads.

At 23:22Z, when this session started, the persona the owner's own Web GUI was running was **21 hours
old**: it had none of the four rules and none of the compression. Three separate gates each reported
success while that was true.

---

## 2. THE THREE DEFECTS, EVERY ONE REPRODUCED WITH A COMMAND

| # | command | before | after |
|---|---|---|---|
| 1 | `python scripts/make_zabz_preset.py --check` | **exit 1** — generator and output had diverged since 2026-09-28 | `zabz: in sync with the generator`, exit 0 |
| 2 | `node scripts/make-preset-rows.mjs --check` | **exit 1** — both committed `profiles/web` artefacts a generation behind `presets/` | `UP TO DATE`, exit 0 |
| 3 | `python scripts/sync.py` | `profiles: SKIPPED -- the committed generated preset rows are STALE … the live profile patch is left untouched`, **exit 0** | `profile web: cordis.patch.yml applied`, exit 0 |

**And the instrument that exists to catch exactly this reported health.** At 23:22Z:

```
python scripts/preset-drift.py  ->  compared 15  match=15  drift=0  missing=0        exit 0
sync.py                        ->  verify: loaded surface matches the repo (compared 15 match=15 drift=0)
sha256 ~/.dsh/profiles/web/cordis.patch.yml  !=  sha256 profiles/web/cordis.patch.yml
```

`preset-drift.py` compared `$DSH_HOME/.agent-presets/` and the skill catalog — **the surface the 0.1.7
line no longer reads** — and never `$DSH_HOME/profiles/<n>/cordis.patch.yml`, which is where a
session's instructions actually come from. It was written on 2026-10-13 specifically to catch a stale
persona, and it caught the previous form of the defect while missing the new one.

### The mechanism, which is the part worth carrying forward

`sync.py` refuses the profile layer — correctly — while the generated rows are stale. But it **exits
0**, and its own `verify` step then covers a surface that does not include the layer it just refused.
So **every persona edit widened the drift and pushed the live layer further behind, silently and
self-lockingly.** Recorded as the pain entry `P3993`.

---

## 3. WHAT WAS FIXED, AND HOW IT WAS VERIFIED

Committed **`378e7b49`** on `feat/card-due-watch-20261014` (harness-config), five files.

1. **The generator is the source of truth again, and the reconciliation went INWARD.** Every hand edit
   in `presets/zabz/agent.cordis.yml` was moved into `scripts/make_zabz_preset.py` — the persona
   (round-tripped byte-exactly), and the constants, which mattered more than the persona:
   `enableRunInBackground: true` on both mesh rows, seven documented incident comments, and
   **the company MCP rows, which the generator still aimed at the FROZEN office box**
   (`secretary-ts`, `/home/zabz/personal-secretary-mvp/…`). **Regenerating before this commit would
   have re-created the 2026-10-11 migration defect.** Rationale and the rejected alternative:
   decisions entry `D3467`.
2. **Both web artefacts regenerated from `presets/`** (`make-preset-rows.mjs --install`), which also
   fixed a second, older drift in `yocheved` (20 rows committed vs 21 in the source).
3. **`preset-drift.py` now compares the profile patch layer** (15 → 17 rows). Proven to fire by
   putting one stale line into the live file, reading `drift=1, exit 1`, then restoring it and reading
   `17/17`.

### The check that should close every instruction change from now on

`--check` exit 0 is not "the surface is right"; it is "the surface this check knows about is right".
Two of the three defects above sat behind a green check. The end-to-end instrument is the composed
config, which is the same tree boot builds:

```
node "C:\Users\ezabz\.dsh\engine\node_modules\@deepseek-ai\dsh\lib\bin.js" --profile web --dump-config > dump.yml
```

At 23:4xZ that dump contained `7b. When he corrects you`, ``server called `secratary-cloud` ``,
`The measurement rule, extended`, `When a tool fails, read the failure`, `enableRunInBackground: true`
×2 and `/opt/company/.venv/bin/python` ×3 — and contained **neither** `1b. On any larger job` **nor**
`2c. Never flag`, which is the compression working. Recorded as lesson `L4192` and win `W2942`.

---

## 4. OPEN — AND ONE OF THEM IS AN ACTION, NOT A NOTE

1. **A profile restart is needed for the fix to take effect.** `sync.py` prints it: *"Restart the DSH
   profile for a settings change to take effect."* The composed dump is correct; the engine that
   loaded at boot still holds the old persona, including this session. **Every new engine start is
   fixed**; nothing else is required, and nothing should be restarted from inside a live session
   without the owner knowing.
2. **`sync.py` should not exit 0 when it SKIPS a step.** This is the mechanism, not a symptom: a
   refused deploy printed one sentence among thirty and alarmed nobody. A skip is a non-zero exit or a
   journal alarm (`P3993` states what would fix it).
3. **Nothing compares the composed config as a routine.** Tonight it was a manual step; it is cheap
   enough to belong in `harness-verify.ps1` beside the other invariants.
4. **Round 4 §6's list stands untouched**, except that §6.1 (measure the loop) now has a +3 h reading:
   unchanged from round 4 §4 — 16 sessions, 0 failed, 6 completed, 10 budget-paused, `HANDOFF` 16/16,
   `RECON-DIRECTIVE` 1, `RECON_BUDGET_EXHAUSTED` 0, no new sessions in the window. **Still n=16.** The
   +24 h and +7 d readings are the ones that decide `PROGRAM.md` §8.
5. **The same defect is still live on the other two machines, and on this estate that is the bigger
   half of the job.** See §6.
6. **Round 4's §6.5 stands** (the `WRONG`/stale claims in round-3 documents), and §6.1–§6.4 are
   partly advanced: §6.2 is now delivered as `07-pain-register-v4.md` (§7), §6.3's two correctness
   jobs are built on a branch (§7), and §6.1 has a +3 h reading. Nothing was deployed.

---

## 5. WHAT I GOT WRONG OR COULD NOT VERIFY

- **I did not restart the engine, so I have not seen a live session receive the new persona.** What I
  verified is the composed config a boot would build, and the byte-identity of the live layer to the
  repo. That is one step short of the strongest claim and it is stated as such.
- **Round 4 §5's "not started" misled me for the first ten minutes** and would have cost the whole
  session if I had trusted it: I was about to "write the persona" that already existed. The census
  table it quotes is sound; its status line for H4 was not. **Verify a status claim against the file
  and the surface, never against the handoff.**
- I initially read the generator diff as "comment-only" and was wrong — the MCP rows were pointing at
  the frozen box. A diff skimmed at `--stat` size hides a behavioural change; read the hunks.
- **My child briefs contained two wrong premises, and the children found both.** (a) I told child 1
  its base was `14ebb2322`; round 4 preserved the tree and *then* deployed, so the live tree is
  `4b750e5aa`. (b) I gave it `app/agent_worker.py`; the file is `app/services/agent_worker.py`, and
  its own definition-of-done command (`git add -- app/agent_worker.py`) cannot run. Both came from
  round 4's handoff, which I quoted instead of checking. **A path or a commit in a brief is a claim
  like any other — verify it against the tree before it becomes an instruction.**

---

## 6. THE SAME DEFECT IS STILL LIVE ON THE OTHER TWO MACHINES

Measured 2026-10-14 23:5xZ, each with a command. The surface is
`<home>/.dsh/profiles/web/cordis.patch.yml` — the file a Web GUI session loads its persona from.

| machine | live layer mtime | has rule `7b` (new) | still has `1b` (compressed away at 09:14) |
|---|---|---|---|
| `ZABZ-YOGA` | 2026-10-14 19:30 | **yes** | no |
| `ZABZ-TECH` | 2026-10-13 21:53 | **no** | **yes** |
| `secratary-cloud` | **2026-10-12 00:19** | **no** | **yes** |

So §3's fix reaches one machine of three, and **the one it has not reached is the one the company
runs on.** The authority's persona is nearly three days old: it predates the compression, the four
rules of 2026-10-14 08:58, and the `secratary-cloud` correction in its own MCP rows.

**It is not a stale copy, so do not "just re-sync" it.** The authority's checkout
(`/root/code/harness-config`, branch `hk/182-wake-family-key`, autocommitting) **does not contain the
round-4/5 work at all** — its own committed `profiles/web/cordis.patch.yml` has no `7b` and no
`secratary-cloud` either. Its crontab states the design: *"The authority is the SOURCE of
harness-config, not a consumer."* This is a branch-lineage problem, not a sync that failed. Three
machines, three branches, newest instructions on exactly one:

| machine | harness-config branch |
|---|---|
| `ZABZ-YOGA` | `feat/card-due-watch-20261014` |
| `ZABZ-TECH` | `mesh/broker-host-cloud-default-20261013` |
| `secratary-cloud` | `hk/182-wake-family-key` |

**Done about it:** `e36d8aac` was pushed to `offsite` (`2a479499..e36d8aac`) and to the authority's own
checkout (the `cloud:` remote). That makes the work *reachable*; it does not publish it to either
machine's engine. **The next session should treat "the persona the authority's engine loads" as its
own deliverable with its own verification, not as a consequence of this commit.**

---

## 7. THE TWO CHILDREN, AND WHAT THEY FOUND

Both ran on `ZABZ-TECH` as mesh children working into the authority over ssh. **Every claim below was
re-run by the manager, not believed.**

**Child 1 — the company (`/root/work/r5-company`, branch `r5/company`, commit `04d30e98c`).**
- **It corrected the brief and the correction is right.** Round 4 preserved the live tree at
  `14ebb2322` and *then deployed*, so `/opt/company` is no longer that commit: it is byte-identical
  to `4b750e5aa` (`r4/integration`) for the files in scope, and `14ebb2322` contains neither
  `model_resolution.py` nor `attempt_context.py`. Reproduced: `diff -q` of the resolver against
  `/opt/company` → identical.
- **J1:** `app/services/agent_worker.py:3061` — the last-resort `_gateway_model = "secretary-fast"` is
  now `resolve_model("fast")`. The child's own honest caveat: that literal was a *route alias*, not a
  time-bomb id, so the real gain is honouring `ZABZ_MODEL_FAST` and catalogue validation.
- **J2:** the dead `_prior_attempt_context` is deleted (98 deletions / 9 insertions) with a written
  justification. 26 tests pass across three files.
- **J3 is the finding worth carrying to the next round.** The company's own #1 complaint — sessions
  that read forever and never act — is closed at `app/autopilot.py:3489` with `status="paused"`, and
  line 3471 says that is deliberate. But the retry seed reads
  `PRIOR_ATTEMPT_STATUSES = ("failed", "expired")` (`app/services/attempt_context.py:79`).
  **The exact failure mode the company suffers most from is therefore invisible to its own retry:
  those retries start with an empty context and re-pay for every read.** Reproduced directly here.
  That is a one-line candidate for the next round's company work, and it should be measured, not
  assumed.

**Child 2 — the pain register.** [`07-pain-register-v4.md`](07-pain-register-v4.md), 995 lines,
69,564 bytes, sha256 `410a7b9c…`, fetched byte-exactly (local sha == remote sha). It ranks
`tool-failure` (302 sessions, 76 blocking, mean severity **2.75** — loud by count, quiet by severity,
which is why it never gets fixed), `frustration` (96 sessions, mean **4.08**, the highest of any
high-volume class), `wrong-data` (116), `restart-agent` (73), `correction` (132). It reports its
disagreements rather than smoothing them: `census.per_file[].bytes` is stale for 17 of 19 readers,
and the JSON holds no per-session friction or severity, which it recovered from the reader files —
reproducing all 20 friction counts and all five severity buckets exactly. It also records its own
first-parser error in the document instead of hiding it.
