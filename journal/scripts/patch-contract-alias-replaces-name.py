"""A validation_alias replaces the field name as the accepted env name.

The previous patch made the contract alias-*aware* but kept the uppercased field name in the
expected set, so `HA_PTT_KEY`, `SECURITY_API_KEY` and `SECURITY_ALERT_EXTRA_RECIPIENTS` were
still demanded -- names pydantic does not accept, because those three fields declare
`validation_alias=AliasChoices("HA_PTT_API_KEY" | "HA_SECURITY_API_KEY" |
"HA_SECURITY_EXTRA_RECIPIENTS")`. An alias overrides the input name; only an alias-less field
is read under its own name.

So: alias names if the field has them, otherwise the uppercased field name.
"""

from __future__ import annotations

import pathlib
import sys

CC = pathlib.Path.home() / "personal-secretary-mvp" / "app" / "config_contract.py"

ANCHOR = '''    keys = {name.upper() for name in Settings.model_fields.keys()}
    for field in Settings.model_fields.values():
        keys |= _alias_env_names(getattr(field, "validation_alias", None))
    return keys.union(ROOT_ENV_ALLOWED_EXTRA_KEYS)'''

REPLACE = '''    keys: set[str] = set()
    for name, field in Settings.model_fields.items():
        # An alias REPLACES the field name as the accepted input name, so a field that
        # declares one is not read under its own name -- which is why demanding
        # HA_PTT_KEY/SECURITY_API_KEY/SECURITY_ALERT_EXTRA_RECIPIENTS was wrong.
        aliases = _alias_env_names(getattr(field, "validation_alias", None))
        keys |= aliases if aliases else {name.upper()}
    return keys.union(ROOT_ENV_ALLOWED_EXTRA_KEYS)'''


def main() -> int:
    text = CC.read_text(encoding="utf-8")
    if text.count(ANCHOR) != 1:
        print(f"REFUSE: anchor count {text.count(ANCHOR)} (expected 1)")
        return 2
    if REPLACE in text:
        print("REFUSE: already applied")
        return 2
    CC.write_text(text.replace(ANCHOR, REPLACE, 1), encoding="utf-8")
    print(f"WROTE {CC}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
