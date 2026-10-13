# The two kernel checks that "measure the wrong thing" were ALREADY FIXED

**Measured on `secratary-cloud`, 2026-10-13T01:1xZ, against `ck/sentinel.py` (4036 lines).**

Brief item 6 says, citing a two-day-old doc:

* `liveness` prints a constant; and
* `db_writable` escalates HIGH on a 6 s probe while 30/30 acquires succeed at 25 s.

Both statements were true of the revision that doc described. **They are not true of the file
now running on the authority.** A patch named
`ck/sentinel.py.bak-sentinelhonesty-20261012T160254Z` (2026-10-12 16:02:54Z) sits next to the
current file, and `diff -u` between them shows the fix. The before/after below is that diff,
not an assertion.

## 6.1 `liveness` -- before: constant 0; after: age from the timestamp

```
$ diff -u /root/ceo-kernel/ck/sentinel.py.bak-sentinelhonesty-20261012T160254Z \
          /root/ceo-kernel/ck/sentinel.py | grep -n 'age = pkt'
-def check_liveness(max_age_seconds: float = 3600) -> Finding:
+def check_liveness(max_age_seconds: float = LIVENESS_MAX_AGE_SECONDS) -> Finding:
-    age = pkt.data_age_seconds or 0
-    metrics = {"newest_tick": pkt.value, "age_seconds": round(age, 1)}
+    age = _age_seconds(pkt.value)
+    if age is None:
+        return Finding(check="liveness", severity=UNKNOWN, ok=False,
+            summary="cannot assess liveness: newest tick is not a readable timestamp", ...)
+    pkt.data_age_seconds = age
+    pkt.stale = age > max_age_seconds
```

The current file at `sentinel.py:504` writes `pkt.data_age_seconds = age` and sets `pkt.stale`
from the parsed timestamp, and the threshold is now derived, not chosen:

```
$ sed -n '445,452p' /root/ceo-kernel/ck/sentinel.py
#:      1 d   |    46   | 23.0m  | 61.6m  |  82.7m |   82.7m |   82.7m
#:     30 d   |  1162   | 26.9m  | 60.3m  | 149.0m | 1378.7m | 1414.5m
LIVENESS_MAX_AGE_SECONDS = 4 * 3600.0
```

**Before:** `age = pkt.data_age_seconds or 0` -- always 0 for a raw SQL scalar, so the check
reported *"ticking: newest tick 0.0m ago"* at a true age of 3,059 s (doc 170 §5.1) and could
never go stale. **After:** the age is computed from `MAX(started_at)`; a real multi-hour stall
fires CRITICAL.

## 6.2 `db_writable` -- before: one 6 s probe; after: 6 s then a 60 s confirming re-probe

```
$ sed -n '2316,2340p' /root/ceo-kernel/ck/sentinel.py
#: A 6 s miss therefore means "busy", not "the company cannot record a customer".
DB_WRITE_PROBE_SECONDS = 6.0
#: ... the worst contended acquire this estate has ever measured -- 9.0 s -- with real
#: margin; 60 s is ~6.7x that. ...
DB_WRITE_CONFIRM_SECONDS = 60.0
```

```
$ sed -n '2400,2432p' /root/ceo-kernel/ck/sentinel.py
    if acquired2:
        return Finding(check="db_writable", severity=MEDIUM, ok=False,
            summary=("the write lock was busy past %.0fs but was acquired at %.1fs -- "
                     "contended, not stuck ..."))
    return Finding(check="db_writable", severity=HIGH, ok=False,
        summary=("the authoritative database refuses writes: %s -- ... a %.0fs miss was "
                 "re-probed with a %.0fs budget and also failed"))
```

**Before (doc 170 §5.2):** a 6 s miss produced HIGH *"the authoritative database refuses
writes"*, while the same probe at 25 s acquired 30/30, worst wait 9.0 s, and the box logged 3
real `database is locked` events in 24 h. **After:** a 6 s miss is re-probed with a 60 s budget;
an acquire in between is reported as MEDIUM *"contended, not stuck"*, and HIGH needs both probes
to fail.

## 6.3 What is left to do about these two

Nothing is left to patch. What is left is to **re-measure the after**, which this brief's
budget did not allow (see `NOT VERIFIED` in `176`): run the live sentinel check and record the
`liveness` `age_seconds`/`metrics` and the `db_writable` severity on a real run, rather than
reading the source diff. The source is not a measurement.

The same file shows a remaining, unfixed defect: `check_config_sync()` still escalates a single
non-clean sample to HIGH -- see `scripts/authority/config-sync-two-sample.py`.
