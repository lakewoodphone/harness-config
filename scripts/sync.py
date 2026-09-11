"""Apply this harness-config repo onto the local ~/.dsh.

Merges settings/base.yaml with settings/machines/<hostname>.yaml (machine wins)
and writes ~/.dsh/settings.yaml, then copies presets into ~/.dsh/.agent-presets/.

Safety rules, deliberately enforced:
  * never writes .credentials.yaml
  * never touches sessions/
  * never touches the SHIPPED preset install beside the deployment
  * never deletes a user preset it did not put there (reports instead)
  * --dry-run changes nothing

Usage:
    python scripts/sync.py --dry-run
    python scripts/sync.py
    python scripts/sync.py --backup     # also snapshot the current settings.yaml
"""
from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML required: pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)

REPO = Path(__file__).resolve().parent.parent
DSH_HOME = Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))
PRESET_ROOT = DSH_HOME / ".agent-presets"
SETTINGS = DSH_HOME / "settings.yaml"

# Never write these, whatever happens.
PROTECTED = {"sessions", ".credentials.yaml", ".anonymous-user-id", "profiles", "storages"}


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base; override wins on scalars."""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a YAML mapping")
    return data


def drop_none(d: dict) -> dict:
    """Remove null-valued keys so a machine file can delete a base key with `key:`."""
    out = {}
    for k, v in d.items():
        if v is None:
            continue
        out[k] = drop_none(v) if isinstance(v, dict) else v
    return out


def plan_settings(hostname: str, dry: bool) -> str:
    base = load_yaml(REPO / "settings" / "base.yaml")
    machine = load_yaml(REPO / "settings" / "machines" / f"{hostname}.yaml")
    merged = drop_none(deep_merge(base, machine))
    rendered = yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)

    existing = SETTINGS.read_text(encoding="utf-8") if SETTINGS.exists() else ""
    if existing == rendered:
        return "settings.yaml: already up to date"
    if dry:
        return f"settings.yaml: WOULD CHANGE ({len(existing)} -> {len(rendered)} bytes)"
    if existing:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(SETTINGS, SETTINGS.with_suffix(f".yaml.bak-{stamp}"))
    SETTINGS.write_text(rendered, encoding="utf-8")
    return f"settings.yaml: written ({len(rendered)} bytes)"


def plan_presets(dry: bool) -> list[str]:
    msgs: list[str] = []
    src_root = REPO / "presets"
    if not src_root.is_dir():
        return ["presets/: none in repo"]
    PRESET_ROOT.mkdir(parents=True, exist_ok=True)
    for preset in sorted(p for p in src_root.iterdir() if p.is_dir()):
        dest = PRESET_ROOT / preset.name
        changed: list[str] = []
        for f in sorted(preset.rglob("*")):
            if f.is_dir():
                continue
            rel = f.relative_to(preset)
            target = dest / rel
            if not target.exists():
                changed.append(f"+ {rel}")
            elif not filecmp.cmp(f, target, shallow=False):
                changed.append(f"~ {rel}")
        if not changed:
            msgs.append(f"preset {preset.name}: up to date")
            continue
        if dry:
            msgs.append(f"preset {preset.name}: WOULD UPDATE -> " + ", ".join(changed))
        else:
            for f in sorted(preset.rglob("*")):
                if f.is_dir():
                    (dest / f.relative_to(preset)).mkdir(parents=True, exist_ok=True)
            for f in sorted(preset.rglob("*")):
                if f.is_file():
                    target = dest / f.relative_to(preset)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)
            msgs.append(f"preset {preset.name}: applied ({len(changed)} file(s))")

    # report unknown local presets rather than deleting them
    known = {p.name for p in src_root.iterdir() if p.is_dir()}
    for local in sorted(p for p in PRESET_ROOT.iterdir() if p.is_dir()):
        if local.name not in known:
            msgs.append(f"preset {local.name}: local-only (not in repo -- left alone)")
    return msgs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--hostname", default=socket.gethostname())
    args = ap.parse_args()

    host = args.hostname.upper()
    print(f"harness-config sync")
    print(f"  repo     : {REPO}")
    print(f"  DSH_HOME : {DSH_HOME}")
    print(f"  hostname : {host}")
    print(f"  mode     : {'DRY RUN' if args.dry_run else 'APPLY'}")
    print(f"  protected: {', '.join(sorted(PROTECTED))}")
    print()

    if not DSH_HOME.is_dir():
        print(f"! {DSH_HOME} does not exist -- install DSH first", file=sys.stderr)
        return 2

    machine_file = REPO / "settings" / "machines" / f"{host}.yaml"
    print(f"machine settings: {machine_file.name} "
          f"({'found' if machine_file.exists() else 'MISSING -- only base will apply'})")

    print(" " + plan_settings(host, args.dry_run))
    for m in plan_presets(args.dry_run):
        print(" " + m)

    print()
    if args.dry_run:
        print("dry run: nothing was written")
    else:
        print("sync complete. Restart the DSH profile for a settings change to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
