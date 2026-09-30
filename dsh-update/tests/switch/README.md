# dsh-update/tests/switch

Tests for `dsh-update/tools/switch-engine.ps1` — the single operation that changes the engine pin and
the version-coupled config together.

```
pwsh -File dsh-update/tests/switch/run-tests.ps1 [-Case <name>] [-Rebuild]

-Case parse | dryrun | refusals | accept | rback | quarantine | syncstep | build | all
```

Cases run against **real inputs** where that is safe and against **fixtures** where the write path
would otherwise touch the live deployment:

| thing | real | fixture |
|---|---|---|
| `-Version` | `0.1.7-rc.2` | — |
| `-StagedHome` | `%TEMP%\dsh-staged-migrated` (the prepared, migrated copy) | `fixtures\staged-old` (the live, un-migrated config) for the refusal case |
| `-BackupDir` | `%USERPROFILE%\dsh-backup-20260928-switch` (real, verified, 3275 files) | `fixtures\backup-{ok,old,bad,missing}` |
| live engine | port 3099, whatever `windows.json` `primaryPort` names | — |
| `state\pin.json`, `state\history` | real (this is the pipeline's own bookkeeping) | — |
| launcher config | hash proven unchanged | `fixtures\windows.json` via `DSH_UPDATE_WINDOWS_JSON` |
| DSH home the config is installed into | `~\.dsh` is never written by a test | `fixtures\targethome` via `DSH_SWITCH_TARGET_HOME` |

`DSH_UPDATE_WINDOWS_JSON` is the override the pipeline already documents. `DSH_SWITCH_TARGET_HOME`
is the same class of override for the switch, added so `sync.py` can be exercised for real without
publishing 0.1.7 package names onto a running 0.1.5 engine. Both are announced loudly on every run.

## What the fixtures contain

* `windows.json` — a copy of the real launcher config, with `primaryPort` left at 3099 (so the
  live-engine precondition still sees the real engine) and `dshInstall` set to the 0.1.5-rc.1 prefix
  — i.e. exactly the value a roll-back restores.
* `targethome\` — a synthetic DSH home carrying the **live, 0.1.5-shaped** `.agent-presets/*/agent.cordis.yml`
  and `profiles/*/cordis.patch.yml`, plus `settings.yaml` and one fixture session.
* `staged-old\` — the same un-migrated config, used to prove precondition 2 refuses a staged home
  that does not name the new packages.
* `syncstep-{old,new}\` — identical copies of the fixture home used to prove that the **same** sync
  command flips from `SKIPPED` to `version check passed` depending only on `--engine-root`.
* a `switch-<UTC stamp>` pre-state built inside the real `state\` directory, for the `-Rollback`
  cases. That is where `-Rollback` looks for its most recent pre-state, and it is the switch's own
  output — which is the point being tested.

Nothing here deletes anything. The runner only creates and copies.

## A PowerShell 7 trap this test found (2026-09-28)

`@(<a generic List>)` **inside an `[ordered]@{}` hashtable literal** throws
`ArgumentException: Argument types do not match`. It is silent at parse time and only fails at run
time, so it took out the whole pre-state write and left a directory with no `PRE-STATE.json` in it.

```
$ls = [System.Collections.Generic.List[string]]::new(); $ls.Add('a')
[ordered]@{ a = @($ls) }     # THROWS: Argument types do not match
[ordered]@{ a = $ls.ToArray() }   # OK
[ordered]@{ a = [object[]]$ls }   # OK
[pscustomobject]@{ a = @($ls) }   # OK — only the [ordered] literal is affected
```

`switch-engine.ps1` therefore casts with `[object[]]` in `New-PreState`, and `run-tests.ps1` asserts
the pre-state parses before it promotes anything (`Stop-Hard`, exit 5) rather than continuing on a
way back it cannot read.

## Known gap, measured rather than assumed

**STEP 3 cannot be reached end to end for `0.1.7-rc.2` on this deployment, because `promote` refuses.**

`promote` condition 1 requires `verify.pass === true`, and `lib/verify.mjs` sets
`pass = ran.every(g => g.ok) && bootGatesRan`. G8 (the session-format one-way door) runs and fails —
the candidate writes v4 while the live logs are v3 — so `pass` is false, and
`--accept-session-format-upgrade` satisfies condition 4 only. `verify.mjs` exposes no acceptance flag.
So the accepted-G8 path reaches step 2, gets a `REFUSED` from the pipeline's own gate, and the switch
rolls the pre-state back (exit 4). The `syncstep` case proves the mechanism step 3 depends on instead:
the same sync command, on identical config, skips both coupled steps against the 0.1.5 root and
applies both against the 0.1.7-rc.2 root.
