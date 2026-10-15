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
  * never publishes a profile patch layer whose GENERATED preset rows are stale, and
    skips that step -- never the whole sync -- when the generator check cannot run
    (see check_generated_preset_rows; the drift it exists to catch is recorded in
    docs/mesh/166-web-profile-office-references.md)
  * --dry-run changes nothing

Usage:
    python scripts/sync.py --dry-run
    python scripts/sync.py
    python scripts/sync.py --backup     # also snapshot the current settings.yaml
"""
from __future__ import annotations

import argparse
import filecmp
import hashlib
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


def _ship(f: Path) -> bool:
    """Files that must never be copied into the live preset dir.

    Editor and git backups (`*.bak-*`, `*before-*`, `*~`) sat in presets/ and were being installed
    as if they were configuration: a `.bak` of a composition is not a composition, and the live
    preset directory is read by the engine on every session start.
    """
    name = f.name
    return not (name.endswith("~") or ".bak" in name or ".before" in name or name.startswith("."))


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
            if f.is_dir() or not _ship(f):
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
                if f.is_file() and _ship(f):
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


SKILL_ROOT = DSH_HOME / "skills"
SKILL_MANIFEST = SKILL_ROOT / ".installed-by-harness-config.json"
# Precedence when two presets ship the same skill name: the default preset first.
SKILL_PRESET_ORDER = ("zabz", "cordis-bg", "yocheved")
_TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".py", ".sh", ".ps1", ".js", ".mjs", ".cjs",
                  ".ts", ".json", ".yml", ".yaml", ".tsv", ".csv", ".toml", ".cfg", ".ini"}


def _skill_sources() -> list[tuple[str, Path]]:
    """(preset, skills dir) for every preset that ships skills, in precedence order."""
    root = REPO / "presets"
    if not root.is_dir():
        return []
    dirs = [p for p in sorted(root.iterdir()) if p.is_dir() and (p / "skills").is_dir()]
    order = {name: i for i, name in enumerate(SKILL_PRESET_ORDER)}
    dirs.sort(key=lambda p: (order.get(p.name, len(order)), p.name))
    return [(p.name, p / "skills") for p in dirs]


def _skill_entries(skills_dir: Path) -> dict[str, Path]:
    """name -> source, for each bundle (a directory holding SKILL.md) and each flat .md file."""
    out: dict[str, Path] = {}
    for entry in sorted(skills_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir() and (entry / "SKILL.md").is_file():
            out[entry.name] = entry
        elif entry.is_file() and entry.suffix in {".md", ".markdown"}:
            out[entry.stem] = entry
    return out


def _skill_files(src: Path) -> list[Path]:
    if src.is_file():
        return [src]
    return sorted(f for f in src.rglob("*") if f.is_file() and f.name != ".DS_Store")


def _copy_skill(src: Path, dest: Path) -> None:
    """Copy one skill, normalising line endings on text and never touching anything else."""
    if dest.exists():
        shutil.rmtree(dest)
    for f in _skill_files(src):
        rel = Path(f.name) if src.is_file() else f.relative_to(src)
        if src.is_file():  # flat markdown skill -> <name>/SKILL.md
            rel = Path("SKILL.md")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = f.read_bytes()
        if f.suffix.lower() in _TEXT_SUFFIXES:
            raw = _norm(raw)
        target.write_bytes(raw)


def plan_skills(dry: bool) -> list[str]:
    """Mirror the estate's skills into $DSH_HOME/skills -- the root an agent actually reads.

    WHY THIS EXISTS (measured 2026-10-08 on ZABZ-YOGA). The presets ship their skills in
    `<preset>/skills/` and the composition registers that directory with the skill provider
    (`customSkillDirs`). In this deployment that registration does nothing: a probe skill placed
    only in `~/.dsh/.agent-presets/zabz/skills/` never reached a fresh agent's catalog -- neither
    with the stock `!!js` expression nor with a literal absolute path -- while the same file
    dropped into `~/.dsh/skills/` appeared in the catalog within seconds (that root is watched
    live). The consequence was real: `fast-search`, the skill that tells every agent to use the
    indexed search instead of a recursive grep, was in the repo and in no agent's catalog, so a
    session had to go looking for a tool it already had.

    So the user root becomes a generated install target, exactly like ~/.dsh/.agent-presets:
    `presets/*/skills` stays the source of truth, and this step mirrors it. Skills are additive:
    a skill we did not install is never deleted (reported instead).
    """
    msgs: list[str] = []
    sources = _skill_sources()
    if not sources:
        return ["skills/: no preset ships a skills/ directory"]

    desired: dict[str, tuple[Path, str]] = {}
    conflicts: list[str] = []
    for preset, skills_dir in sources:
        for name, src in _skill_entries(skills_dir).items():
            if name in desired:
                prev_src, prev_preset = desired[name]
                if _same(src / "SKILL.md" if src.is_dir() else src,
                         prev_src / "SKILL.md" if prev_src.is_dir() else prev_src):
                    continue  # identical copy in two presets: one skill, no noise
                conflicts.append(f"{name} ({prev_preset} vs {preset} -- kept {prev_preset})")
                continue
            desired[name] = (src, preset)
    if conflicts:
        msgs.append("skills/: CONFLICT, same name different content -> " + "; ".join(conflicts))

    try:
        manifest = json.loads(SKILL_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    installed: dict[str, str] = manifest.get("installed", {})

    add, update = [], []
    for name, (src, preset) in sorted(desired.items()):
        dest = SKILL_ROOT / name
        wanted = _skill_files(src)
        if not dest.exists():
            add.append(name)
            continue
        for f in wanted:
            rel = Path("SKILL.md") if src.is_file() else f.relative_to(src)
            target = dest / rel
            if not target.exists():
                update.append(f"{name}/{rel}")
            elif not _same(f, target):
                update.append(f"{name}/{rel}")
    removed = sorted(n for n in installed if n not in desired)
    local_only = sorted(p.name for p in SKILL_ROOT.iterdir()
                        if p.is_dir() and p.name not in desired and p.name not in installed) \
        if SKILL_ROOT.is_dir() else []

    if dry:
        msgs.append(f"skills/: {len(desired)} to install "
                    f"(+{len(add)} new, ~{len(update)} file(s) changed, -{len(removed)} removed)"
                    if (add or update or removed) else f"skills/: up to date ({len(desired)} present)")
        for n in add:
            msgs.append(f"  + {n}  (from {desired[n][1]})")
        for f in update[:20]:
            msgs.append(f"  ~ {f}")
        if len(update) > 20:
            msgs.append(f"  ~ ... and {len(update) - 20} more file(s)")
        for n in removed:
            msgs.append(f"  - {n}  (was installed from {installed.get(n)}, gone from the repo)")
    else:
        SKILL_ROOT.mkdir(parents=True, exist_ok=True)
        for name, (src, preset) in sorted(desired.items()):
            _copy_skill(src, SKILL_ROOT / name)
        for name in removed:
            shutil.rmtree(SKILL_ROOT / name, ignore_errors=True)
        SKILL_MANIFEST.write_text(json.dumps({
            "note": "generated by harness-config/scripts/sync.py -- do not edit by hand",
            "installed": {n: p for n, (_, p) in sorted(desired.items())},
        }, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        msgs.append(f"skills/: {len(desired)} skill(s) mirrored to {SKILL_ROOT} "
                    f"({len(add)} new, {len(update)} file(s) written, {len(removed)} removed)")

    if local_only:
        msgs.append("skills/: local-only, left alone -> " + ", ".join(local_only))
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


GENERATOR = REPO / "scripts" / "make-preset-rows.mjs"


def check_generated_preset_rows() -> tuple[int, str]:
    """Are the COMMITTED generated preset rows still what `presets/` would produce?

    Returns (status, note): 0 = up to date, publish the profile patches as usual;
    1 = DRIFT, SKIP the profile step; 2 = the check itself could not run, SKIP the
    profile step (see `report_generated_step`).

    WHY THIS IS PART OF SYNC (2026-10-11). `profiles/web/presets.generated.patch.yml`
    and the `preset-rows` managed block inside `profiles/web/cordis.patch.yml` are
    DERIVED: `scripts/make-preset-rows.mjs` writes both from `presets/*/agent.cordis.yml`.
    `make-preset-rows.mjs` documents its own `--check` as living "in CI rather than a
    one-off" — and nothing ran it. `.github/workflows/` is empty, there is no root
    `package.json`, and the only caller was a test a human has to remember to run. So
    the committed artefact sat ONE GENERATION BEHIND its source, and it did real damage:
    a corrected row (`brokerSsh` pointing at the frozen office box) was fixed in the
    source, regenerated in nobody's checkout, and the stale copy is what a later sync
    published. A generated artefact one generation behind its source is how a fixed row
    comes back; the full record is `docs/mesh/166-web-profile-office-references.md` §3.

    WHY IT GATES ONLY THE PROFILE STEP. The drift is in the PROFILE files. The presets
    themselves are the SOURCE and are correct, so publishing them is right and is not
    skipped. The blast radius is one step, never the sync — the same rule
    `check_version_coupled` follows, and for the same reason: a sync that stops
    converging has frozen machines on this deployment before (PAIN P8).

    WHY status 2 SKIPS RATHER THAN PUBLISHES. A generated file whose generation cannot be
    reproduced is not a file to install on every machine. This mirrors `report_step`'s
    reasoning about the version check exactly: failing open here is how the stale copy
    reached the fleet in the first place. The remedy is one command and it is named in
    the message.
    """
    if not GENERATOR.exists():
        return 2, f"{GENERATOR.name} is absent from {GENERATOR.parent}"
    node = shutil.which("node")
    if not node:
        return 2, "node is not on PATH, so the generator could not be asked"
    try:
        proc = subprocess.run(
            [node, str(GENERATOR), "--check"],
            cwd=str(REPO), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 2, f"could not run {GENERATOR.name} ({exc})"
    lines = [ln.strip() for ln in ((proc.stdout or "") + (proc.stderr or "")).splitlines() if ln.strip()]
    if proc.returncode == 0:
        return 0, lines[-1] if lines else "--check reported no output"
    # The generator prints one `--check:` line per artefact, and the DRIFT line for the
    # standalone artefact goes to stderr while the managed-block verdict goes to stdout --
    # reading only the first `--check:` line therefore reported a cheerful "managed block
    # UP TO DATE" as the reason a step was skipped. So: report the lines that said DRIFT,
    # which is the only thing a reader can act on, and fall back to whatever there is.
    verdicts = [ln for ln in lines if ln.startswith("--check:")]
    drift = [ln for ln in verdicts if "DRIFT" in ln.upper()]
    detail = " | ".join(drift or verdicts or lines or [f"--check exited {proc.returncode} with no output"])
    return 1, detail


def _alarm_once(sig: str, title: str, body: str) -> str:
    """File ONE journal `pain` entry per distinct refusal, and say what happened.

    WHY THIS EXISTS (measured 2026-10-13). `report_generated_step` refuses to publish the profile
    layer when the committed generated preset rows are stale -- and it refused CORRECTLY, because
    they embedded `yocheved`'s PRE-correction sha. It printed one line into this script's output.

    The result: two days in which the corrected instructions were in git and absent from every
    machine that loads them. `sync.py` is scheduled as `PersonalSecretary-HarnessSync`, so it ran
    the whole time; the only thing that would have said "the deploy is blocked" was a line nothing
    surfaces. **A guard that refuses correctly and reports into a log nobody reads is
    indistinguishable from no guard at all** -- which is `AGENTS.md` §1's own finding about the
    archive alarm, in the deploy path this time.

    So a refusal now goes where work goes: the journal. Deduplicated by signature, so it files once
    per distinct reason and not on every tick. Best effort by design -- **a sync must never fail
    because a secondary report failed** -- and it always prints what it did, so a silent failure is
    not introduced by the thing meant to end one.
    """
    stamp = DSH_HOME / ".sync-alarm"
    try:
        if stamp.read_text(encoding="utf-8").strip() == sig:
            return "already filed (same reason as the last refusal)"
    except OSError:
        pass
    journal = REPO / "journal" / "tools" / "journal.py"
    if not journal.exists():
        return "NOT FILED -- no journal/tools/journal.py in this checkout"
    try:
        proc = subprocess.run(
            [sys.executable, str(journal), "append", "pain", "--title", title,
             "--body", body, "--quiet", "--no-fetch",
             "--tags", "sync,deploy-guard,generated-rows"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, cwd=str(REPO))
    except Exception as exc:  # noqa: BLE001
        return f"NOT FILED -- could not reach the journal ({exc}); the refusal is above only"
    if proc.returncode != 0:
        return ("NOT FILED -- journal append failed "
                f"({(proc.stderr or proc.stdout or '').strip()[:120]}); the refusal is above only")
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(sig, encoding="utf-8")
    except OSError:
        pass
    return "filed to the journal so a session picks it up: " + (proc.stdout or "").strip()[:80]


def report_generated_step(status: int, note: str) -> bool:
    """Print the generated-rows precondition's decision for the profile step.

    True means: apply the profile patches now. One deliberate consequence, the same one
    `report_step` has: neither skip message contains the word "WOULD". `autosync.ps1`
    verifies convergence with `-not ($verify -cmatch 'WOULD')` and records "did NOT
    converge" when it is false, so a "WOULD" here would stall the whole job every tick
    instead of reporting one honest skip.
    """
    if status == 0:
        print(f" profiles: generated preset rows UP TO DATE ({note})")
        return True
    if status == 1:
        print(f" profiles: SKIPPED -- the committed generated preset rows are STALE: {note}")
        print(" profiles:           regenerate and commit them with "
              "`node scripts/make-preset-rows.mjs --install`; the live profile patch is left untouched")
        sig = "generated-rows-stale:" + hashlib.sha256(note.encode("utf-8")).hexdigest()[:16]
        told = _alarm_once(
            sig,
            "sync REFUSED to publish the profile layer: the committed generated preset rows are stale",
            "\n".join([
                "Filed by `scripts/sync.py` on " + socket.gethostname() + ".",
                "",
                "The profile step was SKIPPED, so the agent presets a session loads may NOT be the",
                "ones in the repository. This is not a warning -- it is the deploy being blocked.",
                "",
                "**What the check said:** " + note,
                "",
                "**Fix:** `node scripts/make-preset-rows.mjs --install`, commit both regenerated",
                "artefacts (`profiles/web/presets.generated.patch.yml` and the managed block in",
                "`profiles/web/cordis.patch.yml`), then run `python3 scripts/sync.py` again.",
                "",
                "**Why this entry exists.** On 2026-10-13 this exact refusal held for two days while",
                "every corrected instruction sat in git and was absent from every machine that loads",
                "one. The guard was right; the refusal simply reached nobody. If you are reading this",
                "because it fired again, the same thing is happening now.",
                "",
                "**Check what is actually loaded:** `python3 scripts/preset-drift.py`.",
            ]))
        print(f" profiles:           {told}")
        return False
    print(f" profiles: SKIPPED -- the generated-rows check did NOT run ({note}), so a generated "
          "artefact that cannot be verified was not published; every other step of this sync still applies")
    told = _alarm_once(
        "generated-rows-unchecked:" + hashlib.sha256(note.encode("utf-8")).hexdigest()[:16],
        "sync could not verify the generated preset rows, so it published nothing for the profile step",
        "\n".join([
            "Filed by `scripts/sync.py` on " + socket.gethostname() + ".",
            "",
            "The generated-rows check itself did not run, so a generated artefact that cannot be",
            "verified was NOT published. Every other step of the sync still applied.",
            "",
            "**What the check said:** " + note,
            "",
            "This is the `NODATA` state, not a pass: an empty result is a refusal. Fix the check",
            "(usually a missing `node`, or `scripts/make-preset-rows.mjs` absent from the checkout)",
            "and run sync again.",
        ]))
    print(f" profiles:           {told}")
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


def verify_loaded_surface(dry_run: bool) -> bool:
    """Compare what this machine LOADS against what the repo says it should load.

    WHY THIS IS PART OF SYNC (measured 2026-10-13). Every step above reports what it DID. None of
    them reports what the machine now LOADS, and those are different questions: for two days every
    corrected instruction was in git and absent from every machine that loads one, while `sync.py`
    ran hourly and printed success -- because it had CORRECTLY refused the profile layer (the
    committed generated rows were stale) and nothing checked the result.

    `scripts/preset-drift.py` is that check. Running it here means the verification rides on the job
    that already runs on every machine (`PersonalSecretary-HarnessSync`), so nobody has to remember
    it -- which is the same reason this defect existed in the first place.

    A DRIFT OR A MISSING FILE IS ALARMED to the journal, once per distinct drift, because a deploy
    that silently did not land is exactly the failure that hid for two days. A repo that disagrees
    with ITSELF is reported but not alarmed: that is a tidiness problem in the repository, not a
    failure to deploy, and alarming on it would train the reader to ignore the alarm.
    """
    tool = REPO / "scripts" / "preset-drift.py"
    if not tool.exists():
        print(" verify: SKIPPED -- scripts/preset-drift.py is not in this checkout")
        return False
    try:
        proc = subprocess.run(
            [sys.executable, str(tool), "--repo", str(REPO), "--dsh-home", str(DSH_HOME), "--quiet"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, cwd=str(REPO))
    except Exception as exc:  # noqa: BLE001
        print(f" verify: COULD NOT RUN ({exc}) -- the loaded surface is UNVERIFIED, not clean")
        return False
    lines = [l.rstrip() for l in (proc.stdout or "").splitlines() if l.strip()]
    bad = [l for l in lines if l.startswith(("DRIFT", "MISSING"))]
    summary = next((l for l in reversed(lines) if l.startswith("compared")), "")
    divergent = [l for l in lines if "DIVERGENT" in l]

    if proc.returncode == 0:
        print(f" verify: loaded surface matches the repo ({summary})")
        return True

    if not bad:
        # Exit 1 with no DRIFT/MISSING means the repo disagrees with itself only.
        print(f" verify: loaded surface matches, but the repo disagrees with itself ({summary})")
        for d in divergent:
            print(" verify:   " + d.strip())
        return True

    for b in bad:
        print(" verify: " + b.strip())
    if dry_run:
        print(f" verify: {len(bad)} difference(s) -- expected in a dry run, nothing was applied")
        return False
    detail = " | ".join(b.strip() for b in bad[:6])
    told = _alarm_once(
        "loaded-surface-drift:" + hashlib.sha256(detail.encode("utf-8")).hexdigest()[:16],
        "sync ran but the loaded instruction surface does NOT match the repo on "
        + socket.gethostname(),
        "\n".join([
            f"Filed by `scripts/sync.py` on {socket.gethostname()}.",
            "",
            "`sync.py` completed, and `scripts/preset-drift.py` then found that the presets or skills",
            "this machine LOADS are not the ones in the repository. **A deploy that reports success",
            "and did not land is the failure this check exists for** -- on 2026-10-13 it hid for two",
            "days and every corrected instruction was absent from every machine.",
            "",
            "**Differences found:**",
            *[f"  - {b.strip()}" for b in bad[:12]],
            "",
            f"**Summary line:** {summary or '(none)'}",
            "",
            "**Fix:** read the difference, decide which copy is right (the repo is not automatically",
            "correct -- two scripts were recovered FROM the deployed side on 2026-10-13 because the",
            "running copy was newer), then re-run `python3 scripts/sync.py`.",
        ]))
    print(f" verify: {told}")
    return False


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
    # The exit code has to carry the SKIP, and until 2026-10-15 it did not -- pain P4185. This
    # returned `max(plugin_status, sampler_status)` and nothing else, so a run that REFUSED the
    # profile layer -- the exact refusal that left a stale persona on two machines for days while
    # the 15-minute job reported `LastTaskResult=0` -- exited 0, and `autosync.ps1` recorded
    # `result: clean` with the refusal buried in one field of the record. Round 5 named this defect;
    # this is the fix.
    #
    # THE CODE IS 4 AND IT MEANS "NOT CONVERGED", not "broken". `autosync.ps1` maps it to
    # `result: attention` with its own sentence, so a refusal is never reported as a crash -- two
    # different facts must not collapse into one sentence. A genuine failure keeps its own code.
    not_converged: list[str] = []

    presets_status, presets_missing, presets_engine, presets_note = check_version_coupled(
        "presets", args.engine_root)
    if report_step("presets", presets_status, presets_missing, presets_engine, presets_note):
        for m in plan_presets(args.dry_run):
            print(" " + m)
        # The preset's own skill root is not enough (see plan_skills): mirror the estate's skills
        # into the user root, which is the one an agent provably reads.
        for m in plan_skills(args.dry_run):
            print(" " + m)
    else:
        not_converged.append("presets SKIPPED")

    # BOTH preconditions must pass for the profile step, and each reports its own answer:
    # the version check (can this engine mount these rows?) and the generator check (is the
    # committed generated copy still what the source would produce?). The second one is the
    # 2026-10-11 repair -- it is what would have caught the stale `brokerSsh` row before a
    # sync published it (docs/mesh/166-web-profile-office-references.md §3, §7).
    gen_status, gen_note = check_generated_preset_rows()
    if report_generated_step(gen_status, gen_note):
        prof_status, prof_missing, prof_engine, prof_note = check_version_coupled(
            "profiles", args.engine_root)
        if report_step("profiles", prof_status, prof_missing, prof_engine, prof_note):
            for m in plan_profile_patches(args.dry_run):
                print(" " + m)
        else:
            not_converged.append("profiles SKIPPED")
    else:
        not_converged.append("profiles SKIPPED (generated rows)")

    plugin_status, plugin_msg = ensure_client_plugins(args.dry_run)
    print(" " + plugin_msg)

    sampler_status, sampler_msg = ensure_metrics_sampler(args.dry_run)
    print(" " + sampler_msg)

    # LAST, AND IT ASKS A DIFFERENT QUESTION FROM EVERY STEP ABOVE. Those steps report what they
    # DID; this reports what the machine now LOADS. The difference is the whole failure class this
    # program spent a day on: on 2026-10-13 every corrected instruction was in git and absent from
    # every machine that loads one, and `sync.py` reported success the whole time because it had
    # correctly refused the profile layer and nothing checked the result.
    verified = verify_loaded_surface(args.dry_run)
    if not verified:
        not_converged.append("the loaded surface does not match the repo")

    print()
    if args.dry_run:
        print("dry run: nothing was written")
    else:
        print("sync complete. Restart the DSH profile for a settings change to take effect.")
    if not_converged:
        print("NOT CONVERGED: " + "; ".join(not_converged))
        return 4
    return max(plugin_status, sampler_status)


if __name__ == "__main__":
    raise SystemExit(main())
