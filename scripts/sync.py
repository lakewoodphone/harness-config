"""Apply this harness-config repo onto the local ~/.dsh.

Merges settings/base.yaml with settings/machines/<hostname>.yaml (machine wins)
and writes ~/.dsh/settings.yaml, then copies presets into ~/.dsh/.agent-presets/.

Safety rules, deliberately enforced:
  * never writes .credentials.yaml
  * never touches sessions/
  * never touches the SHIPPED preset install beside the deployment
  * never deletes a user preset it did not put there (reports instead)
  * never publishes a preset or a profile patch layer whose @deepseek-ai package
    names the RUNNING engine does not provide, and skips those two steps -- never the
    whole sync -- when the version check cannot run (see check_version_coupled)
  * --dry-run changes nothing

Usage:
    python scripts/sync.py --dry-run
    python scripts/sync.py
    python scripts/sync.py --backup     # also snapshot the current settings.yaml
"""
from __future__ import annotations

import argparse
import filecmp
import json
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


CHECKER = REPO / "scripts" / "check-version-coupled-config.py"


def check_version_coupled(scope: str, engine_root: str | None) -> tuple[int, list[str], str, str]:
    """Can the presets (or the profile patch layers) mount on the engine that is running here?

    Returns (status, missing_names, engine_version, note): 0 = every name resolves, apply as
    usual; 1 = one or more names are not installed, SKIP THAT STEP; 2 = the check itself failed,
    SKIP THAT STEP (see report_step). `note` is, for status 2, WHY the check did not run, and for
    status 0/1 a loud warning when the RUNNING engine and a configured knob disagree on version
    (empty when they agree, and always empty when the caller passed --engine-root, because naming
    the engine explicitly is how the staged switch applies its config on purpose).

    WHY THIS IS PART OF SYNC (2026-09-28). This deployment is moving from the 0.1.5 line to
    0.1.7-rc.2, and part of that move is VERSION-COUPLED config: the 0.1.7 line renamed
    `@deepseek-ai/dsh-workflow-worker-thread` to `@deepseek-ai/dsh-workflow-ptc`, replaced the
    `@deepseek-ai/dsh-agent-presets` row with `@deepseek-ai/dsh-agent-preset-registry`, and moved
    the singular `@deepseek-ai/dsh-agent-preset`. Each name exists on exactly one side of that
    line. sync.py is applied from committed HEAD every 15 minutes by a scheduled task with nobody
    watching, so committing those files even one tick before the engine is promoted would publish
    a preset that names a package the running engine does not have.

    WHAT THAT COSTS. A composition row that cannot resolve fails at mount: in a preset it breaks
    NEW SESSION CREATION, and in the mesh profile it can take the boot down. Existing sessions keep
    working, so the damage appears only the next time somebody starts a chat -- the last place
    anyone would look for a sync timer.

    WHICH ENGINE THE CHECKER ASKS ABOUT (fixed 2026-09-28, incident 15:32:08Z). It prefers the
    engine that is actually RUNNING -- the live `dsh web --port <n>` process, resolved from that
    process's own command line -- and falls back to configuration only when no engine is running,
    saying so and labelling the answer WEAK. `dshInstall` is never the deciding input while an
    engine runs: it says which engine the launcher picks at the NEXT boot and is transient
    (`dsh-update promote` sets it, `... rollback` removes it). The incident was exactly that knob
    being believed: a switch transiently set it, the 15-minute timer fired ~40 s later, the check
    PASSED against the candidate, and version-coupled config landed on a host still running the
    old engine.

    THE BLAST RADIUS IS THE TWO STEPS, NEVER THE SYNC. On a missing name AND on a check that
    cannot run, sync.py skips presets and profile patch layers only and applies everything else; a
    sync that stops converging has frozen machines on this deployment before (PAIN P8), which is
    worse than the thing being guarded against. One deliberate consequence: the skip message does
    not contain the word "WOULD". autosync.ps1 verifies convergence with
    `-not ($verify -cmatch 'WOULD')` (line 496) and, when that is false, records
    `did NOT converge`, skips the push and exits 1 -- so a "WOULD" here would stall the whole
    job every tick instead of reporting one honest skip.
    """
    if not CHECKER.exists():
        return 2, [], "unknown", f"{CHECKER.name} is absent"
    cmd = [sys.executable, "-X", "utf8", str(CHECKER),
           "--repo", str(REPO), "--scope", scope, "--json"]
    if engine_root:
        cmd += ["--engine-root", str(engine_root)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return 2, [], "unknown", f"could not run {CHECKER.name} ({exc})"
    if proc.returncode == 2:
        lines = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
        return 2, [], "unknown", lines[0] if lines else "the checker reported a usage/parse error"
    try:
        data = json.loads(proc.stdout)
    except (ValueError, TypeError):
        return 2, [], "unknown", f"{CHECKER.name} produced no readable report"
    version = str(data.get("engineVersion") or "unknown")
    missing = [str(n) for n in (data.get("missing") or [])]
    # WHERE THE ANSWER CAME FROM, in this sync's own output -- a reading that does not say where it
    # came from is not a reading. Two things are worth printing here: a disagreement between the
    # engine that is RUNNING and a configured knob (the machine is standing on the version seam),
    # and a check that had to fall back to CONFIGURATION because no running engine could be found
    # (a WEAK reading: a configured path says where the launcher expects the engine, not what is
    # executing -- and believing exactly that is what the 2026-09-28 15:32:08Z incident was).
    # Both are suppressed when this caller named the engine itself with --engine-root, because that
    # is a deliberate operator statement (dsh-update/tools/switch-engine.ps1 passes one on purpose).
    note = ""
    if not engine_root:
        parts: list[str] = []
        if data.get("conflictDetail"):
            parts.append(str(data["conflictDetail"]))
        if data.get("engineResolvedBy") == "config":
            parts.append("no running engine was found, so this check used CONFIGURATION "
                         f"({data.get('engineSource') or 'configuration'}) -- a WEAK reading; a "
                         "configured path says where the launcher expects the engine, not what is "
                         "executing now")
        note = "; ".join(parts)
    if proc.returncode == 0 and not missing:
        return 0, [], version, note
    return 1, missing, version, note


def report_step(scope: str, status: int, missing: list[str], engine: str, note: str) -> bool:
    """Print the precondition's decision for one step. True means: apply this step now.

    status 2 -- the checker could not run, or could not tell which engine is running -- SKIPS the
    step. A VERSION guard that cannot run must not publish version-coupled config to an engine it
    could not identify: failing open here is the 2026-09-28 15:32:08Z incident, where a transient
    `dshInstall` knob made the check pass against an engine that was not the one executing, and
    the config that landed broke new-session creation. Everything else in this sync still applies
    -- a sync that stops converging has frozen machines on this deployment before (PAIN P8), so
    this stays a two-step skip and never a refusal to sync.
    """
    label = "presets" if scope == "presets" else "profiles"
    if status == 0:
        print(f" {label}: version check passed (engine {engine})")
        if note:
            print(f" {label}: WARNING -- {note}")
        return True
    if status == 1:
        print(f" {label}: SKIPPED -- the repo config names {', '.join(missing)}, which the running "
              f"engine ({engine}) does not provide; the live copies are left untouched")
        if note:
            print(f" {label}: WARNING -- {note}")
        return False
    print(f" {label}: SKIPPED -- the version check did NOT run ({note}), so this version-coupled "
          f"step was not published; every other step of this sync still applies")
    return False


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
    ap.add_argument("--engine-root", default=None,
                    help="DSH install root the version precondition checks against (the npm prefix "
                         "holding node_modules/@deepseek-ai/). Passing it OVERRIDES the default, "
                         "which is the engine that is actually RUNNING (resolved from the live "
                         "process's own command line); configuration -- $env:DSH_INSTALL, then "
                         "dshInstall in multi-window/windows.json, then $DSH_HOME/profiles, then a "
                         "scan of %%LOCALAPPDATA%%\\npm-cache\\_npx -- is used only when no engine "
                         "is running, and is then reported as WEAK. Use it to dry-run what a "
                         "different engine would do.")
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

    # The two version-coupled steps are gated separately, each immediately before it runs, so a
    # missing name -- or a check that cannot run at all -- can only ever cost its own step, never
    # the sync. Same decision in --dry-run: the point is to report it, not to write it.
    if report_step("presets", *check_version_coupled("presets", args.engine_root)):
        for m in plan_presets(args.dry_run):
            print(" " + m)

    if report_step("profiles", *check_version_coupled("profiles", args.engine_root)):
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
