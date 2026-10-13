# Kosher AI Filter — WHAT A WOKEN SHIFT MUST DO FIRST

Brief: `W5-PROJECT-LOOP-AND-KOSHER-FILTER` · authored 2026-10-13 · status: seed + design verified, build not run.

The woken shift is a fresh session with no history. This is its literal first action, in order.

## Step 0 — claim, do not browse

```
python3 /root/bin/work.py claim-next --project kosher-ai-filter --by keepalive-kosher-ai-filter --lease 5400 --json
```

`--json` is **required**. Measured against `scripts/wake/work.py` on 2026-10-13: without it, `claim-next`
claims the item but prints nothing (it redirects the underlying `claim` result word into a buffer, so the
caller cannot see what it took). With `--json` it prints exactly one JSON object, and the branch is the
object's `"ok"` field:

* `"ok": "claimed"` → the object carries the item `id`, `title`, `dod`, `why` and `prior_attempts`. **Do that item.**
* `"ok": "nothing-todo"` → the ledger has no item for this project. **Do not invent one.** Record that fact and stop.
* `"ok": "held-by-other"` → every item is leased; run `python3 /root/bin/work.py reap`, then claim again.

The seed for this project holds two items (verified on a throwaway ledger, 2026-10-13):

1. *"Kosher server: add an unauthenticated /readyz that distinguishes process-up from DB-writable"* — the increment is already authored as a patch at `settings/wake/kosher-advance/0001-readyz.patch` with a test beside it. The shift's first job is to **run** it, not re-design it.
2. *"Kosher Android: give the shipped client a real broker default and a managed-provisioning path"*.

## Step 1 — the /readyz item, exactly

```bash
# 1. a PRISTINE, throwaway copy of the Mac repo (never the read-only checkout itself)
D=/tmp/kf-shift; rm -rf "$D"; mkdir -p "$D"
git -C /Users/lpt/work/kosher-filter-ai archive HEAD server | tar -x -C "$D"

# 2. prove the route does not exist yet
grep -c '@router.get' "$D/server/app/routers/health.py"          # before: 2

# 3. apply the authored patch
patch -p1 -d "$D" < <repo>/settings/wake/kosher-advance/0001-readyz.patch
grep -n '@router.get' "$D/server/app/routers/health.py"          # after: /health, /readyz, /health/db

# 4. put the test in and run it with the repo's OWN python that has the deps
cp <repo>/settings/wake/kosher-advance/test_health_readiness.py "$D/server/tests/"
cd "$D/server" && <the repo's python> -m pytest tests/test_health_readiness.py -q
```

**Known blocker, measured 2026-10-13 on `mac-mini-ts`:** the system `/usr/bin/python3` (3.9.6) cannot import the app — `ModuleNotFoundError: No module named 'pydantic_settings'` — and no `.venv` exists under the Mac checkout. The shift must find the interpreter that has the repo deps (Desktop `C:\Users\ezabz\Code\kosher-filter-ai` ran server pytest successfully in the 2026-10-14 ledger history; the roadmap-supply build-host map sends `python -m pytest` to a host with `.venv`) or create/point at one, then run step 4. Quoting the pytest summary line is the definition of done.

## Step 2 — close the item, with proof

```
python3 /root/bin/work.py close <id> --by keepalive-kosher-ai-filter \
    --did '...' --proof '<the exact command>' --result '<its output line>' --left '<what is open>'
```

`--state done` only when the pytest summary is green. If the interpreter cannot be found inside the shift's budget, close as `--state blocked --blocked-on 'a python interpreter with the kosher server deps'` and take the second seed item in the same shift.
