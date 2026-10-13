# settings/wake — the project registry, the ledger seed, and the woken-shift contract

Authored for BRIEF `W5-PROJECT-LOOP-AND-KOSHER-FILTER`, 2026-10-13, base `985f93786076eaa420b8a1033184ad294c4f14aa`.
This directory is the brief's exclusive scope; nothing here edits the orchestrator's live loop.

## Why this exists (the measured failure)

A woken shift calls `work.py claim-next` **from the WORK LEDGER**. If a project has no ledger
item, the session gets `nothing-todo` and stops — the project is scheduled, woken, and advances
nothing. On 2026-10-13 the authority's ledger was measured empty:

```
$ python3 /root/bin/work.py list
no items
```

and the registry file itself was gone:

```
$ ls -l /root/bin/sources/projects.json
ls: cannot access '/root/bin/sources/projects.json': No such file or directory
```

This directory is the repair, in three parts, plus the leading project's first increment.

## Files

| file | what it is |
|---|---|
| `projects.json` | the project registry (schema `wake-projects/2`). The nine owner-named projects, all enabled, each with a verified repo location, a reason, and a checkable definition of done. `waste-system` is recorded under `disclaimed_projects` as deliberately excluded. Drop-in compatible with `project-keepalive.py` / `ledger-keepalive.py` (superset of the old keys). |
| `ledger-seed-2026-10-13.json` | one or more real, claimable items per enabled project (10 items, 9 projects). Every `dod` is a command. |
| `apply-ledger-seed.py` | the loader. Dry-run by default; refuses the live DB without `--allow-live`; idempotent; registers projects first (measured: `work.py add` returns `error:unknown-project` if the project is not in the `project` table). |
| `kosher-advance/` | the leading project's next real increment: `0001-readyz.patch`, its test, and a README. |
| `../docs/projects/kosher-ai-filter-first-instruction.md` | the literal first instruction for a woken shift on the leading project. |

## Verified on a throwaway ledger (2026-10-13)

```
$ cp /root/work/work.db /tmp/w5-seed/work-test.db
$ python3 apply-ledger-seed.py --db /tmp/w5-seed/work-test.db --apply     # APPLIED: 10 item(s), 0 skipped, 9 project(s), 0 failure(s)
$ python3 apply-ledger-seed.py --db /tmp/w5-seed/work-test.db --apply     # APPLIED: 0 item(s), 10 skipped, 9 project(s), 0 failure(s)
   cfo                  todo   1
   chumash              todo   1
   housekeeping         todo   1
   kosher-ai-filter     todo   2
   lpt-sync             todo   1
   lpt-website          todo   1
   personality-system   todo   1
   prod-db-sync         todo   1
   rental-system        todo   1
$ python3 /root/bin/work.py --db /tmp/w5-seed/work-test.db claim-next --project kosher-ai-filter --by w5-verify --lease 60 --json \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print({k:d[k] for k in ("ok","id","project","prior_attempts")})'
{'ok': 'claimed', 'id': 1, 'project': 'kosher-ai-filter', 'prior_attempts': 1}
```

`--json` is required to see the result: without it the call still claims the item but prints nothing
(it buffers the underlying `claim` line), so a shift cannot tell what it took. Same on the live
`sources/work.py` shape. Before the seed, the same call prints `{"ok": "nothing-todo", "project": "kosher-ai-filter"}`. The live store was **not** written;
`/tmp/work.db*` and the throwaway copy were removed.

## What the orchestrator installs (not this brief)

1. copy `projects.json` to the registry path the sources read (`/root/bin/sources/projects.json`);
2. register + seed: `python3 settings/wake/apply-ledger-seed.py --db /root/work/work.db --apply --allow-live`;
3. restore scheduling with the existing `run-wake-sources.sh` orchestrator it already owns.

## Honesty notes

* Repo paths are re-verified per project; the historical `/home/zabz/repos/<name>` paths were
  measured absent on `secratary-cloud` and `zabz-tech-linux`.
* Where a project's true build/test entrypoint could not be established in this brief's budget,
  the seed item is an honest discovery item, not a placeholder, and the registry says `COULD NOT ASK`.
* The kosher `/readyz` patch applied cleanly to a pristine archive (route count 2 -> 3) but its
  pytest run is **not verified**: `mac-mini-ts`'s system python lacks `pydantic_settings`.
