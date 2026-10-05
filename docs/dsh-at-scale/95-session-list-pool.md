# 95 · The session-list walk: three sequential await chains, pooled (2026-10-05)

**Owner's ask:** run 8+ DSH sessions on `ZABZ-YOGA` with no sluggishness. This document covers one of
the four measured causes found that night; the others are in the handoff `H3158`.

## The symptom, measured

| what | number | where |
|---|---|---|
| `POST /api/session/list`, live engine | **219 223 ms**, later **641 532 ms** | `~/.dsh/multi-window/logs/origins.log` 02:05/02:44Z |
| the same call, probed directly at :3099 | **no answer inside 300 s** (undici headers timeout) | `_scratch/perf/session-list-probe.mjs` |
| every *other* RPC, same engine, same moment | **14–330 ms** (`agentPresets/list` 330, `settings/describe` 23, `llm/listProviders` 14, `/favicon.svg` 45) | same |
| the same filesystem work, no engine | **6 797 ms** (1059 dirs; 62.8 MB of first-64-KB reads = 2 582 ms; 1059 stats = 4 161 ms) | `multi-window/tools/replicate-list-scan.mjs` |
| engine event-loop lag under load | **p50 73 ms, p95 1 258 ms, max 5 216 ms**, with 28 sessions / 15 agent loops executing | `engine_health` 02:34Z |
| Windows that cost a fresh window | 0.095 s/s of a core (fresh is cheap; open-with-live-work is not) | `_scratch/perf/idle-window-probe.mjs` |

## The mechanism

`dsh-session-persistence-jsonl/lib/index.js` walks the store as **three strictly sequential await
chains** of ~1068 iterations each:

- `listGenerations()` (line 3004) — for each project, for each session directory, `await
  resolveGenerationInDirectory()` (a readdir + sort) one at a time;
- `listArtifacts()` (line 3031) — for each selected generation, `await readGenerationHeader()` one at
  a time, and that is `open` + up to several 8 KB `read`s + `decompressZstdFrame` + `close`;
- `checkRootEncoding()` (line 3448) — one more readdir per session directory, also serial.

That is ~7 500–10 000 awaited round-trips. On an engine shared with 15 live generations each await
waits behind the loop, whose **median lag is 73 ms**: 7 000 × 73 ms ≈ 511 s, which is the observed
219–641 s. **The disk is 3 % of the cost; the loop is the rest.** This is the same conclusion the
2026-09-17 note reached for a much smaller store (8.5–42 s), which is why the harness's proxy caches
this call at all — but nothing ever made the walk itself cheaper, and the store has grown 681 → 1068
sessions since.

## The fix

`scripts/patch-engine-session-list.mjs` replaces those three bodies with the same work done through a
**bounded pool** (`DSH_LIST_CONCURRENCY`, default 32). Order is preserved, the duplicate-id check is
preserved, the encoding-mismatch check is preserved, nothing is skipped, and no data or capability
changes — it only overlaps waits that were previously serialised.

```
node scripts/patch-engine-session-list.mjs --check     # 0 ready, 2 already patched, 3 needs a re-derive
node scripts/patch-engine-session-list.mjs --apply     # backs up, patches, node --check, only then writes
node scripts/patch-engine-session-list.mjs --restore   # newest backup back
```

## Verified, without restarting the engine

`~/.dsh/engine/session-list-ab.mjs` instantiates the real store class against the real session root
(the class is the package's `default` export), so both versions can be run on live data, interleaved.
Its canonical copy is `scripts/session-list-ab.mjs` in this repo; **it must be run from the engine
root** (copy it to `~/.dsh/engine/`), because its bare `@deepseek-ai/*` imports have to resolve
through that directory's `node_modules`, and `unpatched` mode imports the patched file's own backup
as `./unpatched-store.mjs`.

| run | `listMs` | artifacts | id-set digest (sha256, first 16) |
|---|---|---|---|
| original (sequential) | 23 608 | 1068 | `6f4bc3b71ef630c3` |
| patched, pool 32 | 1 001 | 1068 | `6f4bc3b71ef630c3` |
| original (sequential) | 18 762 | 1068 | `6f4bc3b71ef630c3` |
| patched, pool 32 | 1 638 | 1068 | `6f4bc3b71ef630c3` |

**21 185 ms → 1 320 ms = 16.1×**, with an **identical artifact id set** in every run — the patch
changes nothing observable. At pool 1 the pooled body is *slower* than the original (60.6 s vs 21.9 s
in a single non-interleaved run), which is why the default is 32 and why the pool width is a runtime
env knob rather than a constant: the per-iteration overhead of the pooled body only pays off when
there is concurrency to overlap.

The engine under load should gain more than 16×, because the serialised case is latency-bound and
pooling overlaps exactly that latency — but that specific number is **not yet measured**; it needs an
engine start, and the arithmetic above is the prediction, not evidence.

## Where it takes effect, and why that is safe

The running engine keeps the old code in memory, so this applies at the next engine start. Because
`DSH Engine Pin Install` runs `npm install` in `~/.dsh/engine` — which re-extracts the package and
reverts the file — the patch is **re-applied by `scripts/mesh-restart-at-0700.ps1` STEP 4b**,
immediately before the restart it is about to perform. A version change is a WARNING there, not a
blocker: the engine is fine, the walk is merely slow again, and the fact is recorded in the run log
and the report JSON rather than swallowed.

## Open

1. Measure the walk again **after** the next engine start, under load, and replace the 16.1× with the
   engine-side figure.
2. The store is still unbounded (1064 sessions / 554 MB). Bound it — the archive task has already
   shipped 1059 of 1068 to the authority, so a local archive of shipped sessions costs no record.
3. `harness-verify.ps1` does not yet assert that this patch is applied; only the restart path applies
   it. A machine that never runs the 07:00 restart would start unpatched and silently slow.
