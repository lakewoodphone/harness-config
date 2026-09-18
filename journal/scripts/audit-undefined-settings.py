"""Which feature flags are read but never defined?

`spending_report_enabled` is not in `config.py` and not in `.env`, so
`getattr(self._settings, "spending_report_enabled", False)` is permanently False and
the subsystem has never run deliberately. Nothing in the system says the flag is
missing -- the default hides it, which is the same silent-failure shape as the
breaker that could never clear.

This finds the whole class: every `getattr(<settings>, "name", <default>)` where
`name` is not a field on the Settings class and does not appear in `.env`.

Not every hit is a bug -- a `getattr` with a default can be a deliberate "off unless
configured" flag. The list is for review, and each entry is a feature whose state
cannot be changed by configuration alone.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

APP = Path("app")
CONFIG = APP / "config.py"
ENV = Path(".env")

GETATTR_RE = re.compile(
    r"""getattr\(\s*(?:self\._settings|settings|app_settings|self\.settings)\s*,\s*["']([a-z0-9_]+)["']\s*,\s*([^)]{0,40})""",
    re.IGNORECASE,
)


def settings_fields() -> set[str]:
    """Field names declared on the Settings class (annotated assignments)."""
    text = CONFIG.read_text(encoding="utf-8", errors="replace")
    names = set(re.findall(r"^\s{4}([a-z][a-z0-9_]*)\s*:\s*\w", text, re.MULTILINE))
    # also pick up aliases/dict-driven fields if present
    names |= set(re.findall(r"^\s{4}([a-z][a-z0-9_]*)\s*=", text, re.MULTILINE))
    return names


def env_keys() -> set[str]:
    if not ENV.exists():
        return set()
    keys = set()
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys


def main() -> int:
    fields = settings_fields()
    envs = env_keys()
    print(f"Settings fields declared: {len(fields)}")
    print(f".env keys:                {len(envs)}\n")

    hits: dict[str, dict] = {}
    for path in sorted(APP.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in GETATTR_RE.finditer(text):
            name, default = m.group(1), m.group(2).strip()
            if name in fields:
                continue
            upper = name.upper()
            entry = hits.setdefault(name, {"default": default, "files": set(), "in_env": upper in envs})
            entry["files"].add(str(path))

    undefined = {k: v for k, v in hits.items() if not v["in_env"]}
    print(f"read with a default, never defined in config.py: {len(hits)}")
    print(f"  ...and not present in .env either:             {len(undefined)}\n")

    print(f"{'setting':<44} {'default':<12} {'files':>6}  in .env")
    for name, info in sorted(undefined.items(), key=lambda kv: -len(kv[1]["files"])):
        if not name.endswith(("_enabled", "_time", "_path", "_url", "_key", "_id", "_limit",
                              "_sec", "_days", "_minutes", "_threshold")):
            continue
        print(f"{name:<44} {info['default'][:11]:<12} {len(info['files']):>6}  {info['in_env']}")

    interesting = [
        (n, v) for n, v in undefined.items()
        if n.endswith("_enabled")
    ]
    print(f"\n== the sharpest subset: *_enabled flags that nothing defines ({len(interesting)}) ==")
    for name, info in sorted(interesting):
        print(f"  {name:<44} default={info['default'][:20]:<20} {sorted(info['files'])[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
