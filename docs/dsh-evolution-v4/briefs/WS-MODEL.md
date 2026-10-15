# BRIEF — WS-MODEL: every operational model reference resolves at runtime, or the build fails

You are one builder in a fleet. You own the model-resolution layer. Read this brief completely
before you write anything.

## 0. Where you are

* **Work on host `secratary-cloud`.** If `hostname` is not `secratary-cloud`, prefix commands with
  `ssh secratary-cloud '...'`. Report the host you actually ran on.
* **Repo root and branch:** `/root/work/r4-model`, branch `r4/model-runtime`, cut from `14ebb2322`.
  Report the `git log -1 --format=%H` you actually read.

## 1. Why this exists — the standing instruction and the measured consequence

The owner's standing instruction, 2026-09-15, verbatim:

> *"ai models change very often, can never be hardcoded and get changed and updated all the time so
> we need robust easy flows for that."*

The measured consequence of ignoring it: **every recorded live AI call in `personality-system`
failed for over a week** because a hardcoded model name stopped existing. The silent deterministic
fallback hid it — users saw plausible text and nobody knew.

Round-4 recon measured the current state: **429 literal model-id hits across 47 files** in this
repo. Many are legitimate (catalogue rows, test fixtures, docstrings). The ones that are not are
**operational defaults** — the id a live call uses when nothing else specifies one. Those are time
bombs with a known explosion date.

## 2. Read-first list

1. Find where a model is actually chosen for a live call:
   ```sh
   cd /root/work/r4-model
   grep -rn "model=" app/ --include=*.py | grep -v test | head -40
   grep -rln "deepseek-v4-flash\|gemini-3.5-flash\|gpt-5" app/ --include=*.py | head -40
   ```
2. Find the gateway/catalogue surface the estate already has. Do **not** invent one:
   ```sh
   grep -rn "v1/models\|list_models\|model_registry\|catalog" app/ --include=*.py | head -30
   sqlite3 -readonly /root/authority.db ".schema model_registry" 2>&1 | head -20
   sqlite3 -readonly /root/authority.db "SELECT * FROM model_registry LIMIT 5" 2>&1
   ```
3. Read `app/services/smart_router.py` — there is already a router; understand what it resolves and
   from where before adding another.
4. The estate rule this implements (journal lesson **L1606**): read the gateway's own catalogue,
   **prefer its route aliases** (`secretary-auto`, `secretary-fast`, `secretary-smart` — and never
   `secretary-genius`, measured 502 on 2026-09-15), let an operator override per tier with a
   comma-separated env chain, **validate every configured id against the catalogue and drop what is
   not listed**, cache with single-flight, fail soft, and **publish which model actually served a
   request**. Never let an AI outage be silent.

## 3. What to build

### 3a. One resolver, used everywhere

Add `app/services/model_resolution.py`:

```
def resolve_model(tier: str = "auto") -> str        # the id to use, evidenced
def resolve_model_detail(tier: str = "auto") -> dict  # {"id", "source", "tier", "catalogue_checked_at", "validated"}
def catalogue_model_ids() -> set[str]                # from the gateway's own /v1/models, cached
```

Rules, all of which must be true in the implementation and stated in the docstring:

* **Env override first, as a comma-separated chain per tier** — e.g. `ZABZ_MODEL_AUTO=a,b,c`; the
  first id that validates against the catalogue wins.
* **Route aliases preferred** over concrete ids.
* **Validation is mandatory**: an id not present in the catalogue is dropped with a loud log at
  WARNING naming the rejected id. Configuring a model must never be able to silently break calls.
* **Cache with single-flight**, TTL configurable (`ZABZ_MODEL_CATALOG_TTL_S`, default 900), and
  **fail soft**: if the catalogue cannot be fetched, fall back to the last known good set and say so
  in the returned `detail` — never raise into a caller, never return an unvalidated id silently.
* **Publish what served the request**: the returned `detail` carries `id` and `source`, and callers
  that record usage must record it.

### 3b. Repoint the operational defaults, and only those

Go through every literal model id and classify it. For each one that is an **operational default**
(the id a live call uses), replace it with `resolve_model(...)`. For catalogue rows, test fixtures,
prompts, and documentation, **leave them** and say so in your report with a count.

Produce a list in your report: `path:line — classified as <operational|catalogue|fixture|deco> — <action>`.
Do not do a blind global replace: replacing a fixture's id with a runtime call makes tests
network-dependent, which is a worse defect than the one you are fixing.

### 3c. The guard

Add a test `tests/test_r4_model_resolution.py` that fails the build when a **new operational
default** appears as a literal. It must be a real check with a small allow-list that is explicit in
the test source, so adding a literal requires a deliberate edit. State the count it currently
permits.

## 4. Exclusive file scope

**You may edit/create:** `app/services/model_resolution.py` (new), `app/services/smart_router.py`,
`tests/test_r4_model_resolution.py`, and the specific call sites you classify as operational
defaults — but if a call site is in `app/autopilot.py`, **do not edit `autopilot.py`**: another
builder owns it. Instead list those sites in your report as `NEEDS-EDIT: path:line` and explain the
exact replacement, so the manager can apply or brief them.
**You may not touch:** `app/autopilot.py`, `app/services/autonomy.py`, `app/services/agent_worker.py`,
`app/services/task_protection.py`, any other test file.

## 5. Tests

```sh
cd /root/work/r4-model
python3 -m pytest tests/test_r4_model_resolution.py -q --basetemp=/root/work/r4-model/_pt_m 2>&1 | tail -20
```

* Tests must **not** depend on the network. Monkeypatch the catalogue fetch; test the drop-on-invalid
  path explicitly, the env-chain precedence explicitly, and the fail-soft path explicitly.
* A regression test that fails on base `14ebb2322` and passes after, for at least the guard. Show
  both result lines.
* Never bind a port. Use `--basetemp` as shown.

## 6. Git rules — absolute

Branch `r4/model-runtime` only. Never push, never touch `master`/`main`, never `git add -A`/`.`,
never `reset --hard`/`clean`/delete. Stage explicit paths. Commit message names what changed and the
test result lines.

## 7. Definition of done

1. `python3 -c "import ast;ast.parse(open('app/services/model_resolution.py').read());print('AST OK')"` → `AST OK`
2. `python3 -m pytest tests/test_r4_model_resolution.py -q --basetemp=/root/work/r4-model/_pt_m` → pass line
3. The same test on base `14ebb2322` → fail line (for the guard at least)
4. `grep -c "resolve_model" app/services/smart_router.py` → non-zero
5. `/root/work/r4-model/CHECKPOINT.md` updated; `/root/work/r4-model/REPORT.md` written

## 8. Report format, and the honesty clause

```
HOST: <hostname>   BASE: <hash>   COMMIT: <hash>
FILES: <exact paths>
RESOLVER: <how tiers and overrides resolve, in five lines>
LITERALS CLASSIFIED: <total> = <operational> operational + <catalogue> + <fixture> + <deco>
OPERATIONAL SITES CHANGED: <list>
NEEDS-EDIT (in autopilot.py or another owner's file): <list with the exact replacement>
GUARD: <what it permits today, and what makes it fail>
TEST: <command> -> <exact result line>
BASE TEST: <command on 14ebb2322> -> <exact fail line>
NOT DONE: <what you left>
UNVERIFIED: <what you could not check, and what you checked instead>
```

**A confident claim you did not earn is worse than an honest gap.** If you did not exercise the
fail-soft path against a genuinely unreachable catalogue, say "not verified against an unreachable
catalogue". Do not describe behaviour you did not observe.
