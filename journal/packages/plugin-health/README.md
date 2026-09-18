# dsh-plugin-health

Three things this deployment did not have, in one host-plane row.

| Surface | What it is | How to reach it |
|---|---|---|
| **Health** | live engine health: loop lag p50/p95/max, process memory, physical + commit-charge availability, process/thread counts, live tool-call runner processes, live MCP server processes per name, sessions with a running agent loop, uptime | `GET /healthz` (JSON), `GET /healthz?format=text` (a few lines), or the `engine_health` tool from a session |
| **`list_agents` deadline + cache** | the shipped listing is replaced by one that cannot hang and does not re-scan the whole session corpus for every caller | transparent: the tool keeps its name, arguments, output schema and rendering |
| **Admission governor** | a cross-process lease protocol that reports GRANTED or a queue position for heavy work, with a budget derived from measured memory headroom | `node bin/governor.mjs <status\|acquire\|renew\|release\|reap>`, or the `admission_governor` tool |

Everything durable lives in this directory. See
`_dsh-scale/90-plugin-health-governor.md` for what was measured before and after,
what could not be made to work, and the rollback.

## Mounting

The row is the package's own `cordis.patch.yml`, applied automatically because
the package name is in the profile's `dsh.profile.bundles`. The machine-local
half — the bundle entry and the `node_modules` link — is the keeper's job:

```powershell
pwsh scripts/install-client-plugins.ps1 -RequireAll   # link + add to bundles
pwsh scripts/install-client-plugins.ps1 -Check        # verify it resolves
```

**A new bundle does NOT hot-mount.** Measured 2026-09-16 on an isolated engine:
adding the name to `dsh.profile.bundles` and linking the package while the engine
runs left `GET /healthz` at 404 before and after, with no side effects. The
engine must be restarted. `patchReload: live` covers the profile's own
`cordis.patch.yml`, not the bundle list.

Because the row is `insert` with an id, it can be disabled from a later layer:

```yaml
- id: plugin-health
  disabled: true
```

## Configuration (all optional)

```yaml
- id: plugin-health
  name: dsh-plugin-health
  config:
    probeIntervalMs: 5000      # process-snapshot cadence; the probe is skipped while one is in flight
    lagIntervalMs: 250         # event-loop timer period
    lagWindow: 512             # lag readings retained for p50/p95/max
    staleAfterMs: 30000        # a snapshot older than this makes /healthz answer 503
    snapshotFile: <path>       # default $DSH_HOME/health/processes.json
    listAgentsCacheMs: 3000    # 0 disables the cache (used to measure the raw scan)
    listAgentsTimeoutMs: 8000  # cooperative deadline
    listAgentsMaxTimeoutMs: 25000
    slotBytes: 167772160       # measured cost of one heavy tool slot (runner + shell)
    maxSlots: 24               # ceiling on concurrent heavy slots
    minSlots: 4                # floor: the budget never falls below this
    governorRoot: <path>       # default $DSH_HOME/governor
```

## The governor in one paragraph

`gov acquire` creates one lease file per slot with `O_CREAT|O_EXCL`, so the
filesystem is the mutex. Liveness is a heartbeat, not a pid guess: a lease whose
`expiresAt` has passed is dead, and the reaper claims it with an atomic rename,
re-reads it, and puts it back if the holder renewed meanwhile. The budget is
`(free memory - reserve) / measured slot cost`, capped at `maxSlots` and floored
at `minSlots`; a caller who cannot be granted a slot is given a queue position
and exit code 10, never a refusal.

```powershell
node bin/governor.mjs status
LE=$(node bin/governor.mjs acquire --kind fleet --note "integration run" | Select-String -Pattern 'id (\S+)').Matches.Groups[1].Value
# ... do the heavy work, renewing with: node bin/governor.mjs renew --id $LE
node bin/governor.mjs release --id $LE
```

## Verifying it is working

```powershell
node --test test/model.test.mjs test/agents-list.test.mjs test/governor.test.mjs
node test/governor-stress.mjs --contenders 30 --slots 5
curl -s "http://127.0.0.1:3099/healthz?format=text"   # needs the session cookie, see the doc
```
