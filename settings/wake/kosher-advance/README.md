# Kosher AI Filter — next real increment: an unauthenticated `/readyz`

Brief `W5-PROJECT-LOOP-AND-KOSHER-FILTER`, 2026-10-13.

## The gap, from the project's own record

`docs/IMPLEMENTATION_BACKLOG.md`, the 2026-09-14 audit, lists as an open defect:

> **No readiness endpoint** (`/health?deep=true` is auth-gated; verified 401 live), so "process up"
> and "database writable" are indistinguishable to an orchestrator.

This is the same distinction the wake loop itself needs: a health check that answers without a
credential. It is server-side, pure Python, and provable with the repo's own test runner.

## Where the patch applies

`0001-readyz.patch` applies to **`server/app/routers/health.py`** at:

* `mac-mini-ts` `/Users/lpt/work/kosher-filter-ai` HEAD `3cc033007a4fde54ad1766cc1b6afa036fdd52b3` (verified: `patch -p1` exit 0), and
* `desktop-ts` `C:\Users\ezabz\Code\kosher-filter-ai` HEAD `26da13f26a1ace2e9d569ba8737115b7f0240a41` (same file lineage).

It adds one route after `health()` and before `health_db()`:

```python
@router.get("/readyz")
def readiness(deps: AppDeps = Depends(get_app_deps)) -> dict[str, Any]:
    ...
    db = storage.health_check()
    writable = bool(db.get("writable"))
    payload = {"status": "ok" if writable else "error", "db": db}
    if not writable:
        raise HTTPException(status_code=503, detail=payload)
    return payload
```

Deliberately narrow: it performs no `_authorize_diagnostics` call, and exposes only the storage
layer's own `health_check()` verdict — no config, phone counts, listener state or secrets. The
auth-gated `/health?deep=true` and `/health/db` are unchanged.

## What was verified, and what was not

**Verified (command + output, 2026-10-13, `mac-mini-ts`):**

* the route did not exist: `grep -c '@router.get' health.py` -> `2`
* the patch applies cleanly to a pristine `git archive HEAD server` extraction:
  `patch -p1 --dry-run` then `patch -p1` -> `patching file 'server/app/routers/health.py'`, exit `0`
* the route now exists:
  `grep -n '@router.get' health.py` -> `127:/health`, `196:/readyz`, `224:/health/db`

**Not verified (blocked, reason recorded):** the pytest run.
`/usr/bin/python3 -m pytest tests/test_health_readiness.py` fails at collection with
`ModuleNotFoundError: No module named 'pydantic_settings'`, and no `.venv` exists under the Mac
checkout. The test is authored and shipped here; it needs an interpreter with the repo's
`requirements*.txt`. `docs/projects/kosher-ai-filter-first-instruction.md` names that as the
shift's first executable step and defines the close-out proof.

## Files

| file | purpose |
|---|---|
| `0001-readyz.patch` | unified diff for `server/app/routers/health.py` |
| `test_health_readiness.py` | 4 assertions: route exists; 200 when writable; 503 when not; 503 + error name when `health_check()` raises. Calls the endpoint with a stub deps, so it needs no DB and no env once the app package imports. |
