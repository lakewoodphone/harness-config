"""The contract must count the env names the application actually accepts.

`backend_expected_env_keys()` is `{name.upper() for name in Settings.model_fields}` -- it
uppercases **field names** and ignores `validation_alias`. Three fields rename themselves on
purpose, to keep the HA-scoped keys from being confused with anything else:

    security_api_key               -> AliasChoices("HA_SECURITY_API_KEY")
    ha_ptt_key                     -> AliasChoices("HA_PTT_API_KEY")
    security_alert_extra_recipients -> AliasChoices("HA_SECURITY_EXTRA_RECIPIENTS")

So the contract demanded `SECURITY_API_KEY`, `HA_PTT_KEY` and `SECURITY_ALERT_EXTRA_RECIPIENTS`
-- three names the code never reads -- while reporting the three names it *does* read as
"unexpected keys" in `.env.example` (measured 2026-09-15, three failing tests in
tests/test_config_contract.py). The template was right; the contract had drifted from the code.

This teaches it the aliases. Duck-typed on `.choices` rather than importing AliasChoices, so an
AliasPath or a plain string is handled the same way and nothing new is coupled.
"""

from __future__ import annotations

import pathlib
import sys

CC = pathlib.Path.home() / "personal-secretary-mvp" / "app" / "config_contract.py"

ANCHOR = '''def backend_expected_env_keys() -> set[str]:
    return {name.upper() for name in Settings.model_fields.keys()}.union(
        ROOT_ENV_ALLOWED_EXTRA_KEYS
    )'''

REPLACE = '''def _alias_env_names(alias: Any) -> set[str]:
    """Every env name a pydantic alias declares, including each AliasChoices member.

    Duck-typed on `.choices` so a plain string, an AliasChoices and (by falling through) an
    AliasPath need no import from pydantic here.
    """
    if alias is None:
        return set()
    if isinstance(alias, str):
        return {alias.upper()}
    choices = getattr(alias, "choices", None)
    if choices:
        out: set[str] = set()
        for choice in choices:
            out |= _alias_env_names(choice)
        return out
    return set()


def backend_expected_env_keys() -> set[str]:
    """Every env name the application actually accepts.

    Field names alone are not the answer: a field may rename itself with
    `validation_alias`/`AliasChoices`, and three do (HA_PTT_API_KEY, HA_SECURITY_API_KEY,
    HA_SECURITY_EXTRA_RECIPIENTS). Uppercasing field names without the aliases made this
    contract demand three env names the code never reads while calling the three it does
    read "unexpected" -- measured 2026-09-15, three failing tests.
    """
    keys = {name.upper() for name in Settings.model_fields.keys()}
    for field in Settings.model_fields.values():
        keys |= _alias_env_names(getattr(field, "validation_alias", None))
    return keys.union(ROOT_ENV_ALLOWED_EXTRA_KEYS)'''


def main() -> int:
    text = CC.read_text(encoding="utf-8")
    if text.count(ANCHOR) != 1:
        print(f"REFUSE: anchor count {text.count(ANCHOR)} (expected 1)")
        return 2
    if "_alias_env_names" in text:
        print("REFUSE: already applied")
        return 2
    CC.write_text(text.replace(ANCHOR, REPLACE, 1), encoding="utf-8")
    print(f"WROTE {CC}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
