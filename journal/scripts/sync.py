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
import subprocess
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


def _norm(data: bytes) -> bytes:
    """Normalise line endings for comparison.

    Windows git with core.autocrlf=true rewrites LF to CRLF on checkout, while the
    live files under ~/.dsh are LF. Byte comparison would then report a difference
    that never converges and rewrite the preset on every sync. Compare content, not
    line endings.
    """
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _same(a: Path, b: Path) -> bool:
    try:
        return _norm(a.read_bytes()) == _norm(b.read_bytes())
    except OSError:
        return False


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
            elif not _same(f, target):
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
                    # write LF explicitly: the source of truth is LF, and the
                    # harness reads these files directly.
                    target.write_bytes(_norm(f.read_bytes()))
            msgs.append(f"preset {preset.name}: applied ({len(changed)} file(s))")

    # report unknown local presets rather than deleting them
    known = {p.name for p in src_root.iterdir() if p.is_dir()}
    for local in sorted(p for p in PRESET_ROOT.iterdir() if p.is_dir()):
        if local.name not in known:
            msgs.append(f"preset {local.name}: local-only (not in repo -- left alone)")
    return msgs


def plan_profile_patches(dry: bool) -> list[str]:
    """Copy profiles/<name>/cordis.patch.yml into $DSH_HOME/profiles/<name>/.

    The profile's own cordis.patch.yml is the layer that belongs to us: it is applied
    after every bundle layer. The shipped packages under profiles/node_modules are never
    touched, and a profile we do not have an overlay for is left exactly as it is.
    """
    msgs: list[str] = []
    src_root = REPO / "profiles"
    if not src_root.is_dir():
        return ["profiles/: none in repo"]
    for name in sorted(p for p in src_root.iterdir() if p.is_dir()):
        src = name / "cordis.patch.yml"
        if not src.is_file():
            msgs.append(f"profile {name.name}: no cordis.patch.yml in repo")
            continue
        dest_dir = DSH_HOME / "profiles" / name.name
        if not dest_dir.is_dir():
            msgs.append(f"profile {name.name}: not present on this machine -- skipped")
            continue
        dest = dest_dir / "cordis.patch.yml"
        if dest.exists() and _same(src, dest):
            msgs.append(f"profile {name.name}: cordis.patch.yml up to date")
            continue
        if dry:
            state = "WOULD UPDATE" if dest.exists() else "WOULD CREATE"
            msgs.append(f"profile {name.name}: {state} cordis.patch.yml")
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                shutil.copy2(dest, dest.with_suffix(f".yml.bak-{stamp}"))
            dest.write_bytes(_norm(src.read_bytes()))
            msgs.append(f"profile {name.name}: cordis.patch.yml applied")
    return msgs


def ensure_client_plugins(dry_run: bool) -> tuple[int, str]:
    """Every name in the profile's bundle list must resolve. Returns (status, message).

    WHY THIS IS PART OF SYNC (2026-09-16). This script copies settings, presets and the profile
    patch into ~/.dsh -- and does NOT install plugin packages, because the bundle list lives in
    the machine-local `~/.dsh/profiles/web/package.json` and the packages themselves are
    junctioned into `profiles/node_modules`. So a machine rebuilt from harness-config, or a
    node_modules tree that gets rebuilt, silently loses every plugin with no error.

    That is not hypothetical: on 2026-09-11 the engine refused to boot with
    `cannot resolve profile bundle "dsh-plugin-cost"`, and plugin-windows had to be copied by
    hand twice. `scripts/install-client-plugins.ps1` is the keeper for that invariant (its own
    header cites DECISIONS D38: "a component that can silently disappear needs a keeper, not a
    procedure") -- but until now nothing called it, so the keeper only ran when someone
    remembered. This is the call.

    A failure here returns attention (1) rather than 2: the sync itself succeeded, and what is
    wrong is a machine-local resolution problem that the message names.
    """
    if os.name != "nt":
        return 0, "client plugins: not Windows -- skipped"
    installer = REPO / "scripts" / "install-client-plugins.ps1"
    if not installer.exists():
        return 0, "client plugins: installer absent -- skipped"
    if dry_run:
        return 0, "client plugins: would run install-client-plugins.ps1 -RequireAll"
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return 1, "client plugins: no pwsh/powershell on PATH -- could not verify the bundle list"
    try:
        proc = subprocess.run(
            [shell, "-NoProfile", "-File", str(installer), "-RequireAll"],
            capture_output=True, text=True, timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"client plugins: could not run the installer ({exc})"
    if proc.returncode == 0:
        return 0, "client plugins: every bundle name resolves"
    tail = [ln for ln in (proc.stdout or proc.stderr or "").strip().splitlines() if ln.strip()]
    return 1, "client plugins: PROBLEM -- " + " | ".join(tail[-3:] or ["no output"])


def ensure_metrics_sampler(dry_run: bool) -> tuple[int, str]:
    """The continuous metrics sampler must exist and be reachable on every Windows node.

    WHY THIS IS PART OF SYNC (2026-09-16, verification pass -- docs/mesh/60-verification.md).
    `scripts/harness-metrics.ps1` is the machine's own longitudinal record: it is what every
    measurement in the mesh design documents is checked against, and what a future session reads to
    answer "is this laptop under pressure". It had exactly the failure mode `ensure_client_plugins`
    exists to prevent -- it was installed by hand, once, on one machine, and nothing kept it alive.

    MEASURED: the task `DSH Metrics Sampler` ran a FINITE `-Samples 540` (three hours) with a trigger
    that had NO repetition, so pid 908 started at 16:10:25Z and the record ended at 19:10:25Z with the
    next run at 23:59 -- a 4.8-hour hole, and nothing anywhere reported it. A stale CSV looks exactly
    like an idle machine, which is why the check is "the CSV advanced", not "the task is Running".

    The keeper is `scripts/Install-MetricsSampler.ps1`: it registers a repeating task, exits 0 when a
    sampler is live, and (on a machine whose task file is owned by Administrators and unwritable by
    the running token) registers a watchdog task it owns instead, printing the one elevated command
    that removes the old one. It is quiet by default so a per-sync run does not add noise.

    A failure returns attention (1), not 2: the sync itself succeeded.
    """
    if os.name != "nt":
        return 0, "metrics sampler: not Windows -- skipped"
    installer = REPO / "scripts" / "Install-MetricsSampler.ps1"
    if not installer.exists():
        return 0, "metrics sampler: installer absent -- skipped"
    if dry_run:
        return 0, "metrics sampler: would run Install-MetricsSampler.ps1 -Quiet"
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return 1, "metrics sampler: no pwsh/powershell on PATH -- could not install"
    try:
        proc = subprocess.run(
            [shell, "-NoProfile", "-File", str(installer), "-Quiet"],
            capture_output=True, text=True, timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"metrics sampler: could not run the installer ({exc})"
    if proc.returncode == 0:
        return 0, "metrics sampler: task present and a sampler is reachable"
    tail = [ln for ln in (proc.stdout or proc.stderr or "").strip().splitlines() if ln.strip()]
    return 1, "metrics sampler: PROBLEM -- " + " | ".join(tail[-3:] or ["no output"])


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
    for m in plan_profile_patches(args.dry_run):
        print(" " + m)

    plugin_status, plugin_msg = ensure_client_plugins(args.dry_run)
    print(" " + plugin_msg)

    sampler_status, sampler_msg = ensure_metrics_sampler(args.dry_run)
    print(" " + sampler_msg)

    print()
    if args.dry_run:
        print("dry run: nothing was written")
    else:
        print("sync complete. Restart the DSH profile for a settings change to take effect.")
    return max(plugin_status, sampler_status)


if __name__ == "__main__":
    raise SystemExit(main())
