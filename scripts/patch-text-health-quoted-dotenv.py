#!/usr/bin/env python3
"""One-shot: make text-health.py parse quoted dotenv values like the app does.

MEASURED, 2026-10-28
--------------------
<APP>/.env was rewritten at 2026-10-28T07:23:53Z and `DATABASE_URL` came back quoted:

    DATABASE_URL='sqlite:////root/authority.db'      # after 07:23:53
    DATABASE_URL=sqlite:////root/authority.db        # .env.bak-20261019T222924Z

`_resolve_app_db()` read the line, split on '=', and kept the quotes, so the prefix strip
("sqlite:///", "sqlite://", "file:") never matched and it returned Path("'sqlite:/...'") -- a
RELATIVE path. Six of the channel's checks then failed with `unable to open database file`, and
C1 failed with `invalid literal for int() with base 10: "'20'"`, the same class on a number.

runs.log pins it to the minute: green at 07:15:03Z and 07:30:02Z showed 8 FAIL.

The app itself was never affected -- pydantic-settings strips quotes. Only this reader was.
So the fix belongs in this reader: a dotenv value may be quoted, and stripping matching outer
quotes is standard dotenv behaviour.

Idempotent: refuses to apply twice, and asserts each anchor matches exactly once.
"""
import re
import shutil
import sys
import time

PATH = "/root/bin/text-health.py"
STAMP = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
BAK = f"{PATH}.bak-quoteddotenv-{STAMP}"

HELPER = '''
def _dotenv_value(raw: str) -> str:
    """Strip a dotenv value the way the app's own loader does.

    MEASURED 2026-10-28T07:23:53Z: `<APP>/.env` gained quotes -- `DATABASE_URL='sqlite:////root/
    authority.db'`. Splitting on '=' keeps them, so the prefix strip below missed, the "path"
    came back relative, and six checks failed with `unable to open database file` while C1
    failed on `int("'20'")`. The app was unaffected (pydantic-settings strips quotes); only this
    reader was blind, which is the worse failure because it still printed a result.
    """
    v = str(raw).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1].strip()
    return v


'''

ANCHOR_ENV = '''                if line.startswith("DATABASE_URL="):
                    raw = line.split("=", 1)[1].strip()
                    break'''
REPLACE_ENV = '''                if line.startswith("DATABASE_URL="):
                    raw = _dotenv_value(line.split("=", 1)[1])
                    break'''

ANCHOR_RAW = '''    raw = str(os.environ.get("DATABASE_URL") or "").strip()'''
REPLACE_RAW = '''    raw = _dotenv_value(os.environ.get("DATABASE_URL") or "")'''

ANCHOR_C1 = '''            env = line.split("=", 1)[1].strip()'''
REPLACE_C1 = '''            env = _dotenv_value(line.split("=", 1)[1])'''

ANCHOR_FUNC = '''def _resolve_app_db() -> Path:'''


def main() -> int:
    src = open(PATH, encoding="utf-8").read()

    if "_dotenv_value" in src:
        print("ALREADY PATCHED -- _dotenv_value is present; refusing to apply twice")
        return 1

    for name, anchor in (("_resolve_app_db", ANCHOR_FUNC), ("env-line", ANCHOR_ENV),
                         ("env-var", ANCHOR_RAW), ("C1", ANCHOR_C1)):
        n = src.count(anchor)
        if n != 1:
            print(f"REFUSED -- anchor {name!r} matched {n} times, expected exactly 1")
            return 1

    src = src.replace(ANCHOR_FUNC, HELPER.lstrip("\n") + ANCHOR_FUNC, 1)
    src = src.replace(ANCHOR_ENV, REPLACE_ENV, 1)
    src = src.replace(ANCHOR_RAW, REPLACE_RAW, 1)
    src = src.replace(ANCHOR_C1, REPLACE_C1, 1)

    compile(src, PATH, "exec")  # syntax gate before anything is written
    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(src)
    print(f"PATCHED {PATH} (backup {BAK})")
    print(f"  _dotenv_value helper added; 3 call sites converted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
