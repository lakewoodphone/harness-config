#!/usr/bin/env python3
"""One-shot: stop dsh_session_ingest from replacing a real sqlite error with an AssertionError.

MEASURED 2026-10-28
-------------------
`journalctl -u company-api` carried sixteen `AssertionError` tracebacks in thirty minutes, all
from `app/services/dsh_session_ingest.py` line 588:

        except sqlite3.OperationalError:
            assert last_exc is not None      # <-- line 588
            raise last_exc

`last_exc` is only assigned inside the retry loop. When the OperationalError is raised by
something the loop never reached -- acquiring `_INGEST_WRITE_LOCK`, or the first `_get_conn` --
`last_exc` is still None, the assert fires, and the AssertionError REPLACES the sqlite error that
actually happened. So the log said `assert last_exc is not None / AssertionError` and told nobody
which lock failed, on which database, or why.

That is the estate's recurring shape: a handler that describes its own assumption instead of the
failure. The original exception is available; it must be raised.

Applied to BOTH copies, which were verified byte-identical (md5 dee6d1f2021501901c8d5cc1a3bf2519):
  /root/personal-secretary-mvp/app/services/dsh_session_ingest.py   (source of truth)
  /opt/company/app/services/dsh_session_ingest.py                   (deployed)

NOTE ON EFFECT: the running uvicorn imported this module at start-up, so the fix takes effect at
the next restart of company-api. The file is deployed now; no restart is performed here, because
the API is serving during shop hours and this defect only affects the wording of an error path.
"""
import hashlib
import shutil
import sys
import time

PATHS = [
    "/root/personal-secretary-mvp/app/services/dsh_session_ingest.py",
    "/opt/company/app/services/dsh_session_ingest.py",
]

ANCHOR = """    except sqlite3.OperationalError:
        assert last_exc is not None
        raise last_exc"""

REPLACE = """    except sqlite3.OperationalError as _outer_exc:
        # The retry loop above records its own failure in `last_exc`; when the OperationalError
        # comes from somewhere the loop never reached -- taking _INGEST_WRITE_LOCK, or the first
        # _get_conn -- `last_exc` is still None. MEASURED 2026-10-28: sixteen of these in thirty
        # minutes logged as `assert last_exc is not None / AssertionError`, which REPLACED the
        # real sqlite error and hid which lock failed. Raise the original.
        raise (last_exc if last_exc is not None else _outer_exc) from _outer_exc"""


def main() -> int:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for path in PATHS:
        try:
            src = open(path, encoding="utf-8").read()
        except OSError as exc:
            print(f"SKIP {path}: {exc}")
            continue
        if "if last_exc is not None else _outer_exc" in src:
            print(f"ALREADY PATCHED {path}")
            continue
        n = src.count(ANCHOR)
        if n != 1:
            print(f"REFUSED {path}: anchor matched {n} times, expected exactly 1")
            return 1
        new = src.replace(ANCHOR, REPLACE, 1)
        compile(new, path, "exec")
        bak = f"{path}.bak-ingestassert-{stamp}"
        shutil.copy2(path, bak)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)
        print(f"PATCHED {path}")
        print(f"        md5 was {hashlib.md5(src.encode()).hexdigest()[:8]}, "
              f"now {hashlib.md5(new.encode()).hexdigest()[:8]}, backup {bak}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
