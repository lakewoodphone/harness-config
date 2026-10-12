# 155 — `production-comms-freshness` FAILS EVERY RUN: DIAGNOSIS

**Author:** remote child agent on **ZABZ-TECH** (Windows), dispatched over the mesh thread
`remote-bd0c2c32-a8f3-4de8-9094-d95eaf2c794b`, 2026-10-11 ~21:20Z onward. All commands run read-only
against `secratary-cloud` (`root@178.156.194.1`). Nothing was restarted, nothing was written outside
this directory, and `/root/authority.db` was never opened read-write.

**Subject job:** `production-comms-freshness`, cron `*/15`, wrapped by `/usr/local/bin/cron-wrap.sh`.
**Symptom:** rc=1 on every run. **Verdict so far: the lag is real for the CURSOR, and the cursor is the
wrong clock — the website itself is NOT stale.** Detail below; this file is being written as the work
progresses, per instruction.

---

## 0. The ledger: when it broke, to the tick

`/root/.cron-status/runs.tsv`, fields `ts · job · rc · seconds`:

```
2026-10-11T16:30:01Z  production-comms-freshness  0  6
2026-10-11T16:45:01Z  production-comms-freshness  0  5
2026-10-11T17:00:01Z  production-comms-freshness  0  3
2026-10-11T17:15:02Z  production-comms-freshness  0  3
2026-10-11T17:30:02Z  production-comms-freshness  1  4   <-- FIRST FAILURE
2026-10-11T17:45:01Z  production-comms-freshness  1  2
...
2026-10-11T21:15:01Z  production-comms-freshness  1  1
```

The transition is **clean and permanent**: green through `17:15:02Z`, red from `17:30:02Z` and every run
since. Nothing in between is intermittent. That shape — a threshold being crossed once and then never
un-crossing — is the signature of a **monotonic clock running away from a frozen one**, not of a flapping
dependency.

## 1. What the check actually compares — the two sides, and the numbers right now

`/usr/local/bin/production-comms-freshness.py` computes, per `sync_type`:

```
lag_h = (local_newest  -  website_sync_cursor.last_synced_at) / 3600     # hours
```

* **Side A ("local store"):** `MAX(created_at)` of `dialpad_sms_cache` (filtered to pushable ids) and
  `MAX(date_started_ms)` of `dialpad_call_full`, read from **`/root/authority.db`** — the live cloud
  authority. That is the right database; the cron line sets `FRESHNESS_SECRETARY_DB=/root/authority.db`.
* **Side B ("the website"):** the row `website_sync_cursor.last_synced_at` — **the last time the
  local→website PUSH completed.** It is *not* a reading of the website. It is a reading of the pusher's
  own bookkeeping, stored in the same local database as side A.
* Fails when `lag_h > THRESHOLD_HOURS = 2.0`.

The check does *also* open the website Postgres (`communications`, read-only) and read
`COUNT(*), MAX("createdAt")` — but that third measurement can only *add* a problem. It is gated on
`if age_h is not None and age_h > THRESHOLD_HOURS`, i.e. it is **silent whenever the website is fresh**.

**Measured now**, from `/root/.lpt-recon/production-comms-freshness.json` at `2026-10-11T21:15:01Z`:

| | value |
|---|---|
| `dialpad_calls.cursor` | `2026-10-11T15:11:48.403398+00:00` |
| `dialpad_calls.cursor_age_hours` | **6.05** |
| `dialpad_calls.behind_local_hours` | **5.96** |
| `dialpad_sms.cursor` | `2026-10-11T15:11:53.128402+00:00` |
| `dialpad_sms.cursor_age_hours` | **6.05** |
| `dialpad_sms.behind_local_hours` | **6.05** |
| `local_newest_sms` | `2026-10-11T21:14:42.949000+00:00` |
| `local_newest_call` | `2026-10-11T21:09:41.949000+00:00` |
| **`website.newest`** | **`2026-10-11 21:14:44.814000`** |
| **`website.newest_age_hours`** | **0.01** |
| `website.rows` | 126113 |
| `problems` | 2 (the two `behind_local` lines above) |
| `ok` | false |

The 21:15:01Z run is the one quoted by `151` as *"website 5.25 h behind local store"* — that string is
`behind_local_hours` from an earlier tick (20:30:01Z: `behind_local=5.25h`). It is **not** a statement
about the website's contents.

## 2. Is the lag real, or is the check measuring the wrong thing? — THE CRUX

**The website's own newest row is 21:14:44.814Z against a local-store newest message of
21:14:42.949Z — the website's copy is 1.865 seconds NEWER than the local original.** The
website's `newest_age_hours` is **0.01 h = 36 seconds**. Nothing in the website reading is remotely
stale.

Read side by side, the three series tell the whole story:

| tick | cursor (frozen) | website `MAX(createdAt)` | website `rows` |
|---|---|---|---|
| 20:15:02Z | 15:11:48Z | 20:09:26Z | 126101 |
| 20:30:01Z | 15:11:48Z | 20:23:25Z | 126104 |
| 20:45:01Z | 15:11:48Z | 20:38:11Z | 126108 |
| 21:00:02Z | 15:11:48Z | 20:51:44Z | 126110 |
| 21:15:01Z | 15:11:48Z | 21:14:44Z | 126113 |

**The `rows` column is climbing and the `MAX("createdAt")` column is tracking live traffic within
seconds.** Whatever the check believes, the website is *receiving what the shop sends*, continuously,
right now. The only thing frozen is `website_sync_cursor.last_synced_at`, a value inside
`/root/authority.db`.

So the honest first-order answer is: **the number the check reports is a real fact about the wrong
object.** `behind_local_hours = local_newest − cursor` assumes the cursor advances whenever the local
store advances. It does not. This check is therefore deciding freshness from a **heartbeat**, and the
heartbeat has stopped while the thing it heartbeats for has not.

That is precisely the failure the file's own docstring says it was written to prevent, inverted:

> "capture_freshness() checks MAX(dialpad_sms_cache.fetched_at) — the LOCAL receive time, which the live
> Dialpad webhook keeps refreshing every few minutes [...] The watchdog watched the clock that could not
> go wrong."

The 2026-09-15 defect was *watching a clock that always moves*. The 2026-10-11 defect is *watching a
clock that never moves.* Both are clock mistakes; they are mirror images, and the second was introduced
by the port that was meant to fix the first.

### Why the flip is exactly at 17:30Z, from the arithmetic alone

The cursor froze at `15:11:48Z`. `behind_local_hours` grows at 1 h/h. The threshold is 2.0 h, so the
first tick whose lag *exceeds* 2.0 h is the first tick after `17:11:48Z` — which is **17:15:02Z** if the
lag is measured against `local_newest_due`, and **17:30:02Z** against `local_newest`. The ledger flips at
17:30:02Z. **No other explanation is needed and none is available: the failure time is a pure function
of the freeze time plus the 2 h threshold.** That is why the job was green for its first four ticks on
the cloud and red ever after.

*(continued below as the work proceeds — §3, §4 to follow)*
