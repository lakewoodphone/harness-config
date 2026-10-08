"""Refuse to publish config that names an @deepseek-ai package the RUNNING engine does not have.

WHY THIS EXISTS (2026-09-28). harness-config is the source of truth for presets and profile
patch layers, and it reaches the live ~/.dsh through scripts/sync.py -- run by a 15-minute
timer (PersonalSecretary-HarnessSync -> autosync.ps1 -> `git archive HEAD` -> sync.py), with
nobody watching. Some of that config is VERSION-COUPLED: the 0.1.7 line renamed
`@deepseek-ai/dsh-workflow-worker-thread` to `@deepseek-ai/dsh-workflow-ptc`, and replaced the
`@deepseek-ai/dsh-agent-presets` row with `@deepseek-ai/dsh-agent-preset-registry`, and moved
the singular `@deepseek-ai/dsh-agent-preset`. Each of those names exists on exactly ONE side of
the version line. A composition row naming a package that is not installed fails to resolve at
mount: inside a preset it breaks NEW SESSION CREATION, and in the mesh profile it can take the
boot down -- while existing sessions keep working, so the failure surfaces only the next time
somebody starts a chat, which is the last moment anyone would suspect a sync timer.

So: sync.py asks this script, immediately before it touches presets and immediately before it
touches profile patch layers, whether every package name in those files resolves against the
engine that is actually RUNNING. If one does not, sync.py skips THOSE TWO STEPS and applies
everything else -- the blast radius is the version-coupled work, never the whole sync.

ENGINE ROOT RESOLUTION -- LIVE EVIDENCE FIRST, CONFIGURATION LAST.
Fixed 2026-09-28 after the 15:32:08Z incident. The root is the npm prefix holding
`node_modules/@deepseek-ai/` -- the same thing `multi-window/dshw.ps1` looks for and the same
thing `scripts/merge-settings.mjs` probes for its `yaml` copy. Resolution order:

    1. `--engine-root` -- a deliberate operator statement, and the tests and staged runs depend
       on it (`dsh-update/tools/switch-engine.ps1` passes its staged prefix).
    2. THE ENGINE THAT IS ACTUALLY RUNNING. The live `dsh .../dsh/lib/bin.js web --port <n>`
       process (or any running engine process) is found in the live process table and its install
       root is derived from THE PROCESS'S OWN COMMAND LINE. The running process's path is the only
       direct evidence of what is executing.
    3. ONLY IF NO RUNNING ENGINE CAN BE FOUND: configuration -- `$env:DSH_INSTALL` / `$env:DSH_BIN`,
       then `dshInstall` in `multi-window/windows.json`, then `$DSH_HOME/profiles`, then a scan of
       `%LOCALAPPDATA%\\npm-cache\\_npx\\*`. Every reading taken that way is labelled
       `WEAK: no running engine found` in the report, because it is weaker evidence.

`dshInstall` IS NEVER THE DECIDING INPUT WHILE AN ENGINE IS RUNNING. It is written by
`dsh-update ... promote` and removed by `... rollback`, so it says which engine the launcher
would pick at the NEXT boot -- it does not say what is executing now, and it is TRANSIENT.
THE INCIDENT THIS PREVENTS (2026-09-28 15:32:08): a switch run transiently set `dshInstall` to
the candidate prefix, the 15-minute sync timer fired ~40 s later, the guard resolved the
CANDIDATE from that knob, the check PASSED, and sync.py installed version-coupled config onto a
host still running the OLD engine -- breaking new-session creation on the three agent presets.
A configured knob is not evidence of which engine is executing.
If the running engine and a configured knob disagree on version, that disagreement is itself the
dangerous state: it is reported LOUDLY, naming both, because the config that is about to be
published is version-coupled and the machine is standing on the seam.

TWO DIFFERENT ENGINES RUNNING AT ONCE is not decidable from here either (a `dsh web` engine plus
older sessions from another install root). That is exit 2 with both roots named, so the caller
skips the two coupled steps rather than judging them against a guess.

COMMENTS ARE NOT DEPENDENCIES. These files carry long explanatory prose naming precisely the
packages that were removed ("`@deepseek-ai/dsh-workflow-worker-thread` was REMOVED in
0.1.7-rc.1 ..."), so a scan that treats a `#` comment as a dependency invents a finding on the
GOOD engine and would pin the sync in a permanent skip. YAML `#` comments (and JS `//` and
`/* */` comments in the `!!js` blocks these files carry) are therefore masked before matching,
and every masked mention is COUNTED and reported so the skip is auditable.

Usage:
    python scripts/check-version-coupled-config.py
    python scripts/check-version-coupled-config.py --engine-root "$env:DSH_INSTALL"
    python scripts/check-version-coupled-config.py --scope presets --json
    python scripts/check-version-coupled-config.py --engine-port 39999      # force the no-engine path
    python scripts/check-version-coupled-config.py --windows-json %TEMP%\\windows.json

Exit codes:
    0  every name resolves against this engine
    1  one or more do not (they are named on stdout)
    2  this script's own usage/parse failure, or it could not tell which engine is running --
       the caller must NOT treat it as "missing", and must not publish version-coupled config
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCOPES = ("all", "presets", "profiles")

# `@deepseek-ai/<pkg>`, with or without a subpath: `@deepseek-ai/dsh-tool-subagent-control/list-agents`
# names the package `dsh-tool-subagent-control` (the part before the second `/`).
PKG_RE = re.compile(r"@deepseek-ai/([A-Za-z0-9][A-Za-z0-9._-]*)")

# The engine's own entry point. Only a process whose SCRIPT ARGUMENT is this path is an engine --
# see _engine_of_row for why the match is positional rather than "anywhere in the command line".
ENGINE_BIN_RE = re.compile(r"@deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js", re.IGNORECASE)

# One token of a recorded Windows command line: a double-quoted run, a single-quoted run, or a
# run of non-space characters. `C:\\Program Files\\nodejs\\node.exe ...` is three tokens.
CMDLINE_TOKEN_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')

# YAML's rule: `#` starts a comment at the beginning of a line or when preceded by whitespace.
# `foo#bar` is a plain scalar, not a comment. MULTILINE is required, not cosmetic: without it `^`
# only matches at the start of the FILE, and a whole comment block indented to column 0 --
# profiles/mesh/cordis.patch.yml lines 14-33, which name the exact packages that were removed --
# would be read as dependencies and invent three findings on a good engine.
NAIVE_HASH_RE = re.compile(r"(?:^|[ \t])#", re.MULTILINE)


def _engine_root_of(raw: str) -> tuple[Path, Path] | None:
    """Normalise a user-supplied path to (npm prefix, node_modules dir).

    Accepts any of the three things a human or another script already has in hand: the npm
    prefix, the `node_modules` directory itself, or a `.../@deepseek-ai/dsh/lib/bin.js` path
    (`$env:DSH_BIN` is that form, and dshw.ps1 handles it the same way).
    """
    p = Path(raw).expanduser()
    if p.name.lower() == "bin.js":
        p = p.parent.parent.parent.parent  # lib/bin.js -> dsh -> @deepseek-ai -> node_modules -> prefix
    for cand in (p, p.parent, p.parent.parent, p.parent.parent.parent):
        nm = cand / "node_modules"
        if (nm / "@deepseek-ai").is_dir():
            return cand, nm
        if cand.name == "node_modules" and (cand / "@deepseek-ai").is_dir():
            return cand.parent, cand
    return None


def _is_complete_install(nm: Path) -> bool:
    """A real engine install has the core package, not just a stray @deepseek-ai directory.

    Measured on ZABZ-YOGA 2026-09-28: 21 directories under `_npx`, two of which hold an
    `@deepseek-ai` tree, and only one of those has `@deepseek-ai/dsh` itself. Accepting the
    partial tree would check names against a half-populated cache entry.
    """
    return (nm / "@deepseek-ai" / "dsh" / "package.json").is_file()


def _resolve_alias(nm: Path) -> tuple[Path, Path, Path | None]:
    """Follow a junctioned `@deepseek-ai` tree to the real install it points at.

    `$DSH_HOME/profiles/node_modules/@deepseek-ai` is exactly this on ZABZ-YOGA: 240 entries,
    every one a JUNCTION into `...\\npm-cache\\_npx\\1e7f6d9597241db0\\node_modules\\@deepseek-ai`.
    That is a pointer, not an install -- resolving it means the report names the engine that
    actually owns the files, and a stubbed or half-populated mirror can never be mistaken for
    the engine. Returns (node_modules, @deepseek-ai dir, alias target or None).
    """
    api = nm / "@deepseek-ai"
    core = api / "dsh"
    try:
        # NOT Path.is_symlink(): on Windows that is False for a JUNCTION, and a junction is
        # exactly what this tree is. os.path.realpath follows both.
        real_core = Path(os.path.realpath(core))
        if real_core != core and _is_complete_install(real_core.parent.parent):
            return real_core.parent.parent, real_core.parent, core
    except OSError:
        pass
    return nm, api, None


def _windows_json_dsh_install(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = data.get("dshInstall") if isinstance(data, dict) else None
    return value if isinstance(value, str) else ""


def _accept(prefix: Path, nm: Path, why: str) -> tuple[Path, Path, str]:
    """Take a candidate install, following a junctioned tree to the install that owns it."""
    real_nm, _api, alias = _resolve_alias(nm)
    if alias is not None:
        return real_nm.parent, real_nm, f"{why} -- junction resolved to {real_nm.parent}"
    return prefix, nm, why


def _version_of(nm: Path) -> str:
    try:
        return str(json.loads((nm / "@deepseek-ai" / "dsh" / "package.json")
                              .read_text(encoding="utf-8")).get("version", "unknown"))
    except (OSError, ValueError, AttributeError):
        return "unknown"


# ── the live process table ───────────────────────────────────────────────────
# WHAT A RUNNING PROCESS IS EVIDENCE OF. A command line recorded by the OS is the one reading
# that cannot be stale configuration and cannot be a knob somebody set for the next boot. It is
# also, on Windows, cheap to read when it is filtered to one image name.

# Tab-separated, one node process per line. Run through -EncodedCommand so no quoting layer
# between here and PowerShell can mangle it. `-Filter` keeps this fast: dshw.ps1 measured an
# UNFILTERED Win32_Process query at 5-35 s on a busy machine, and this runs on a 15-minute timer.
_PS_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process -Filter "Name='node.exe'" | ForEach-Object {
  $st = ''
  if ($_.CreationDate) { $st = $_.CreationDate.ToString('o') }
  $cl = ''
  if ($_.CommandLine) { $cl = ($_.CommandLine -replace "\r?\n", ' ') }
  Write-Output ("{0}`t{1}`t{2}`t{3}" -f $_.ProcessId, $_.ParentProcessId, $st, $cl)
}
"""


def _tokenize_cmdline(cmd: str) -> list[str]:
    out: list[str] = []
    for m in CMDLINE_TOKEN_RE.finditer(cmd or ""):
        out.append(next(g for g in m.groups() if g is not None))
    return out


def _collapse_seps(path: str) -> str:
    """A command line can record every separator twice (`C:\\\\Users\\\\ezabz\\\\...`).

    Measured on this host 2026-09-28 with the checker's own scan: 11 of 32 node processes carry a
    doubled-backslash path in their recorded command line (pid 17060 is one), because a launcher
    handed a single-quoted string to the shell. Collapsing is tried only as a SECOND attempt, on
    the script argument alone, and only after the path as recorded failed to resolve, so a
    UNC-style `\\\\server\\share` can never be rewritten by accident.
    """
    for _ in range(8):
        if "\\\\" not in path:
            break
        path = path.replace("\\\\", "\\")
    return path


def _engine_bin_of(script: str) -> tuple[Path, Path] | None:
    """The install (prefix, node_modules) a process's own script argument points at, or None."""
    for candidate in (script, _collapse_seps(script)):
        if not ENGINE_BIN_RE.search(candidate):
            continue
        found = _engine_root_of(candidate)
        if found and _is_complete_install(found[1]):
            return found
    return None


def _windows_process_table() -> tuple[list[dict], str]:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return [], "no pwsh/powershell on PATH, so the live process table could not be read"
    encoded = base64.b64encode(_PS_QUERY.encode("utf-16-le")).decode("ascii")
    try:
        proc = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=90)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"the live process table could not be read ({exc})"
    if proc.returncode != 0:
        tail = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
        return [], (f"the live process table query failed (exit {proc.returncode}: "
                    f"{tail[0] if tail else 'no detail'})")
    rows: list[dict] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t", 3)
        if len(parts) < 4:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        rows.append({"pid": pid, "ppid": parts[1].strip(), "started": parts[2].strip(),
                     "cmdline": parts[3], "argv": None})
    return rows, ""


def _posix_process_table() -> tuple[list[dict], str]:
    proc = Path("/proc")
    if not proc.is_dir():
        return [], "this host has no /proc, so the running engine could not be looked up"
    rows: list[dict] = []
    for entry in sorted(proc.iterdir(), key=lambda p: p.name):
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        argv = [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]
        if not argv:
            continue
        rows.append({"pid": int(entry.name), "ppid": "", "started": "",
                     "cmdline": " ".join(argv), "argv": argv})
    return rows, ""


def _process_table() -> tuple[list[dict], str]:
    """(rows, note). A note means the table could not be read; the caller must say so rather than
    report "nothing is running", which is a different and much stronger claim."""
    if os.name == "nt":
        return _windows_process_table()
    return _posix_process_table()


def _engine_of_row(row: dict) -> dict | None:
    """This process, when it IS a DSH engine. None otherwise.

    THE MATCH IS POSITIONAL: a `.../dsh/lib/bin.js` path means the engine only when it is the
    process's own SCRIPT ARGUMENT (`argv[1]`). Matching anywhere in the recorded command line
    would also fire on a process that merely quotes the path -- measured in this session at
    15:35, `dsh-update/lib/settings-effective.mjs --engine C:\\...\\@deepseek-ai\\dsh\\lib\\bin.js
    --version 0.1.5-rc.1 ...` (pid 19128) sat in this host's table with the path at argv[3], and
    letting it vote would have put a process that is not an engine into the decision about which
    engine is running.
    """
    tokens = row.get("argv") or _tokenize_cmdline(row.get("cmdline") or "")
    if len(tokens) < 2:
        return None
    script = tokens[1]
    found = _engine_bin_of(script)
    if not found:
        return None
    prefix, nm = found
    sub = tokens[2:4]
    m = re.search(r"--port[=\s]+(\d{1,5})", " " + " ".join(tokens[2:]))
    return {
        "pid": row.get("pid"),
        "started": row.get("started") or "",
        "cmdline": row.get("cmdline") or "",
        "bin": _collapse_seps(script),
        "prefix": prefix,
        "nm": nm,
        "version": _version_of(nm),
        "isWeb": "web" in sub,
        "port": int(m.group(1)) if m else None,
    }


def _live_engines(port_filter: int | None) -> tuple[list[dict], str, int]:
    """Every running engine process. Returns (engines, why-none-found, processes-scanned)."""
    rows, table_note = _process_table()
    engines: list[dict] = []
    for row in rows:
        engine = _engine_of_row(row)
        if not engine:
            continue
        if port_filter is not None and (not engine["isWeb"] or engine["port"] != port_filter):
            continue
        engines.append(engine)
    if engines:
        return engines, "", len(rows)
    if table_note:
        return [], table_note, len(rows)
    scope = (f"--engine-port {port_filter} restricted the lookup to a `dsh ... web` process on that "
             f"port" if port_filter is not None else "the lookup was not restricted to a port")
    return [], (f"no engine process was found among the {len(rows)} node process(es) scanned "
                f"({scope})"), len(rows)


def _representative(group: list[dict]) -> dict:
    """One process to name as "the running engine", for a group that shares one install root."""
    web = [e for e in group if e["isWeb"]] or group
    return sorted(web, key=lambda e: (e["started"] or "", e["pid"] or 0))[0]


def _choose_live(engines: list[dict]) -> tuple[dict | None, list[dict], bool]:
    """Which running engine decides. Returns (chosen, every distinct-root representative, ambiguous).

    One install root -- trivially that one. Several roots with exactly ONE of them serving
    `dsh web` -- the web engine serves sessions, so it decides, and the others are named. Several
    roots each serving `dsh web` -- genuinely undecidable from here, and the caller must refuse
    rather than guess: publishing version-coupled config on a coin flip is the incident again.
    """
    groups: dict[str, list[dict]] = {}
    for engine in engines:
        groups.setdefault(os.path.normcase(str(engine["prefix"])), []).append(engine)
    reps = [_representative(g) for g in groups.values()]
    if not groups:
        return None, [], False
    if len(groups) == 1:
        return reps[0], [], False
    web = {k: v for k, v in groups.items() if any(e["isWeb"] for e in v)}
    if len(web) == 1:
        key = next(iter(web))
        return _representative(web[key]), [r for k, r in zip(groups.keys(), reps) if k != key], False
    return None, reps, True


def _configured_candidates(windows_json_paths: list[Path], dsh_home: Path) -> list[tuple[str, str]]:
    """The install locations that CONFIGURATION names, in the order they were tried before this
    fix: the two environment knobs, `dshInstall` in windows.json, then the live profile tree."""
    ordered: list[tuple[str, str]] = []
    for var in ("DSH_INSTALL", "DSH_BIN"):
        if os.environ.get(var):
            ordered.append((os.environ[var], f"$env:{var}"))
    for cfg in windows_json_paths:
        value = _windows_json_dsh_install(cfg)
        if value:
            ordered.append((value, f"dshInstall in {cfg}"))
    ordered.append((str(dsh_home / "profiles"), "$DSH_HOME/profiles"))
    return ordered


def resolve_engine(explicit: str | None, dsh_home: Path,
                   windows_json_paths: list[Path],
                   engine_port: int | None) -> tuple[Path, Path, str, dict]:
    """Find the engine to check against: (prefix, node_modules, why, evidence report)."""
    configured: list[dict] = []
    for raw, knob in _configured_candidates(windows_json_paths, dsh_home):
        found = _engine_root_of(raw)
        if not found or not _is_complete_install(found[1]):
            configured.append({"knob": knob, "raw": raw, "root": "", "nm": "", "version": "",
                               "resolvedFrom": "", "complete": False})
            continue
        prefix, nm, resolved = _accept(found[0], found[1], knob)
        configured.append({"knob": knob, "raw": raw, "root": str(prefix),
                           "nm": str(nm), "version": _version_of(nm),
                           "resolvedFrom": resolved, "complete": True})

    report: dict = {
        "engineResolvedBy": "",
        "enginePid": 0,
        "engineStarted": "",
        "engineCmdline": "",
        "engineProvenance": "",
        "liveSearch": "",
        "liveProcessesScanned": 0,
        "runningEngines": [],
        "configuredCandidates": configured,
        "usedConfigured": False,
        "conflictDetail": "",
        "conflictLines": [],
    }

    # 1. An explicit --engine-root wins: a deliberate operator statement, and the staged switch
    #    (dsh-update/tools/switch-engine.ps1) and the switch tests pass one on purpose.
    if explicit:
        found = _engine_root_of(explicit)
        if not found:
            print(f"check-version-coupled-config: --engine-root is not a DSH install: {explicit}\n"
                  f"  expected <prefix>/node_modules/@deepseek-ai/dsh/package.json",
                  file=sys.stderr)
            raise SystemExit(2)
        prefix, nm, why = _accept(found[0], found[1], "--engine-root")
        report["engineResolvedBy"] = "engine-root"
        report["engineProvenance"] = f"--engine-root {explicit} (operator statement)"
        return prefix, nm, why, report

    # 2. The engine that is actually RUNNING. Its own command line is the direct evidence.
    engines, why_none, scanned = _live_engines(engine_port)
    report["liveSearch"] = why_none
    report["liveProcessesScanned"] = scanned
    report["runningEngines"] = [
        {"pid": e["pid"], "root": str(e["prefix"]), "version": e["version"],
         "web": e["isWeb"], "port": e["port"], "started": e["started"], "cmdline": e["cmdline"]}
        for e in engines
    ]
    chosen, others, ambiguous = _choose_live(engines)

    if ambiguous:
        running = "\n".join(
            f"    {r['version']:<12} {r['prefix']}  (pid {r['pid']}, "
            f"{'web engine on port ' + str(r['port']) if r['isWeb'] else 'session process'})"
            for r in others
        )
        print("check-version-coupled-config: TWO DIFFERENT ENGINES ARE RUNNING and this check cannot "
              "say which one a new session would mount on. Refusing to judge the version-coupled "
              "config against either:\n" + running + "\n"
              "  Stop one engine (or pass --engine-root to state the engine you mean). Until then the "
              "two steps that depend on this answer -- presets and profile patch layers -- must not "
              "be applied.", file=sys.stderr)
        raise SystemExit(2)

    if chosen is not None:
        prefix, nm, why = _accept(chosen["prefix"], chosen["nm"],
                                  f"the RUNNING process, pid {chosen['pid']}")
        report["engineResolvedBy"] = "running-process"
        report["enginePid"] = chosen["pid"]
        report["engineStarted"] = chosen["started"]
        report["engineCmdline"] = chosen["cmdline"]
        started = f", started {chosen['started']}" if chosen["started"] else ""
        report["engineProvenance"] = (
            f"the RUNNING process, pid {chosen['pid']}{started} -- its own command line: "
            f"{chosen['cmdline']}")
        if others:
            report["engineProvenance"] += (
                "; other engine processes from a DIFFERENT install root are also running: "
                + "; ".join(f"pid {r['pid']} {r['prefix']}" for r in others))
        running_version = _version_of(nm)
        differing = [c for c in configured if c["complete"] and c["version"] != running_version]
        if differing:
            report["conflictDetail"] = (
                f"the RUNNING engine is {running_version} but configuration names "
                + "; ".join(f"{c['version']} ({c['knob']} -> {c['root']})" for c in differing)
                + " -- see the DANGEROUS STATE block above")
            report["conflictLines"] = [
                "!!",
                "!! DANGEROUS STATE -- THE RUNNING ENGINE AND THE CONFIGURED ENGINE DISAGREE.",
                f"!!   RUNNING    : {running_version:<12} {prefix}  (pid {chosen['pid']})",
            ] + [
                f"!!   CONFIGURED : {c['version']:<12} {c['root']}  ({c['knob']})" for c in differing
            ] + [
                "!! A configured knob is not evidence of which engine is executing: `dshInstall` says",
                "!! which engine the launcher picks at the NEXT boot and is TRANSIENT (`dsh-update",
                "!! promote` sets it, `... rollback` removes it). THIS CHECK JUDGED THE ENGINE THAT IS",
                "!! RUNNING, and the configuration above was NOT used to decide anything.",
                "!!",
            ]
        return prefix, nm, why, report

    # 3. No running engine could be found: configuration is all that is left, and every reading
    #    taken this way is labelled WEAK because a knob is a statement of intent, not of fact.
    weak = "WEAK: no running engine found"
    detail = why_none or "no running engine was found"
    tried: list[str] = []
    for entry in configured:
        if not entry["complete"]:
            tried.append(f"{entry['knob']} = {entry['raw']}")
            continue
        report["usedConfigured"] = True
        report["engineResolvedBy"] = "config"
        # `entry` is already junction-resolved by _accept above; only the WEAK marker is added,
        # and it goes directly after the knob so a reader sees the strength of the reading first.
        suffix = entry["resolvedFrom"][len(entry["knob"]):]
        why = f"{entry['knob']} -- {weak}{suffix}"
        report["engineProvenance"] = (
            f"CONFIGURATION ONLY ({weak}) -- {detail}. A configured path is where the launcher "
            f"expects the engine, not evidence of what is executing, so this reading is weaker "
            f"than a running process and the report says so.")
        return Path(entry["root"]), Path(entry["nm"]), why, report

    # The npx cache, whose directory hash is not stable across machines -- the same last-resort
    # scan merge-settings.mjs and dshw.ps1 do. Newest complete install wins, and says so.
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    npx = Path(local) / "npm-cache" / "_npx"
    candidates: list[tuple[float, Path, Path]] = []
    if npx.is_dir():
        for entry in sorted(npx.iterdir()):
            found = _engine_root_of(str(entry))
            if found and _is_complete_install(found[1]):
                stamp = (found[1] / "@deepseek-ai" / "dsh" / "package.json").stat().st_mtime
                candidates.append((stamp, found[0], found[1]))
        tried.append(f"npx cache scan of {npx}")
    if candidates:
        candidates.sort(key=lambda c: (c[0], str(c[1])), reverse=True)
        _stamp, prefix, nm = candidates[0]
        scan = ("npx cache scan (only complete install)" if len(candidates) == 1
                else f"npx cache scan (newest of {len(candidates)} complete installs)")
        prefix, nm, why = _accept(prefix, nm, f"{scan} -- {weak}")
        report["engineResolvedBy"] = "config"
        report["usedConfigured"] = True
        report["engineProvenance"] = (
            f"CONFIGURATION ONLY ({weak}) -- {detail}; fell through to a cache scan. No running "
            f"engine was found, so this reading is weaker and the report says so.")
        return prefix, nm, why, report

    print("check-version-coupled-config: cannot locate a DSH engine install "
          "(no <root>/node_modules/@deepseek-ai/dsh/package.json), and no running engine was found "
          f"({detail}).\n"
          "  Pass --engine-root, or set $env:DSH_INSTALL to the npm prefix DSH is installed under.\n"
          "  tried: " + ("; ".join(tried) or "nothing"), file=sys.stderr)
    raise SystemExit(2)


def mask_comments(text: str) -> str:
    """Replace every comment character with a space, preserving offsets and newlines.

    Handles YAML `#` comments and, because these files carry `!!js` blocks, JS `//` and
    `/* */` comments. Quoted scalars are honoured -- with YAML's `''` doubled-quote escape,
    which is exactly the shape a `!!js` expression inside single quotes has -- so a `#` inside
    a string is not mistaken for a comment. A scalar does not span a newline in these files, so
    the quote state resets at each newline and cannot leak from an unbalanced line into the next.
    """
    out = list(text)
    state: str | None = None
    block = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if block:
            if text.startswith("*/", i):
                out[i] = out[i + 1] = " "
                block = False
                i += 2
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
            continue
        if state is not None:
            if ch == "\n":
                state = None
                i += 1
                continue
            if state == "'" and ch == "'":
                if i + 1 < n and text[i + 1] == "'":  # YAML '' escape
                    i += 2
                    continue
                state = None
                i += 1
                continue
            if state in ('"', "`") and ch == "\\":
                i += 2
                continue
            if state != "'" and ch == state:
                state = None
                i += 1
                continue
            i += 1
            continue
        # normal state
        if ch in "'\"`":
            state = ch
            i += 1
            continue
        if ch == "#" and (i == 0 or text[i - 1] in " \t\r\n"):
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if ch == "/" and text.startswith("//", i) and not (i > 0 and text[i - 1] == ":"):
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if ch == "/" and text.startswith("/*", i):
            block = True
            i += 2
            continue
        i += 1
    return "".join(out)


def mask_naive_hash(text: str) -> str:
    """Mask `#` comments with no quote awareness at all, and UNION it with the scan above.

    Belt and braces, and deliberately so: prose in these files is full of apostrophes
    ("the owner's sentence ..."), and a single stray apostrophe can put the quote-aware scanner
    into string state for the rest of the line, which would leave a real comment looking like
    code. The naive rule cannot be fooled by an apostrophe, and it cannot hide a real dependency
    either -- a dependency row is `name: '@deepseek-ai/...'` with no `#` anywhere before it.
    """
    out = list(text)
    for m in NAIVE_HASH_RE.finditer(text):
        start = text.index("#", m.start())
        end = text.find("\n", start)
        end = len(text) if end < 0 else end
        for k in range(start, end):
            out[k] = " "
    return "".join(out)


def scan_file(path: Path) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Return (real matches, comment-only matches) as [(name, line), ...]."""
    text = path.read_text(encoding="utf-8", errors="replace")
    aware = mask_comments(text)
    naive = mask_naive_hash(text)
    masked = "".join(" " if (a == " " or b == " ") else c
                     for a, b, c in zip(aware, naive, text))
    real: list[tuple[str, int]] = []
    in_comment: list[tuple[str, int]] = []
    for m in PKG_RE.finditer(text):
        name = "@deepseek-ai/" + m.group(1)
        line = text.count("\n", 0, m.start()) + 1
        target = in_comment if masked[m.start()] == " " else real
        if (name, line) not in target:
            target.append((name, line))
    return real, in_comment


def config_files(repo: Path, scope: str) -> list[Path]:
    """Every presets/*/agent.cordis.yml and every profiles/*/cordis.patch.yml, in order."""
    wanted: list[Path] = []
    if scope in ("all", "presets"):
        root = repo / "presets"
        if root.is_dir():
            for preset in sorted(p for p in root.iterdir() if p.is_dir()):
                f = preset / "agent.cordis.yml"
                if f.is_file():
                    wanted.append(f)
    if scope in ("all", "profiles"):
        root = repo / "profiles"
        if root.is_dir():
            for profile in sorted(p for p in root.iterdir() if p.is_dir()):
                f = profile / "cordis.patch.yml"
                if f.is_file():
                    wanted.append(f)
    return wanted


def build(repo: Path, scope: str, explicit_root: str | None,
          windows_json_paths: list[Path], engine_port: int | None) -> dict:
    dsh_home = Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))
    prefix, nm, why, evidence = resolve_engine(explicit_root, dsh_home, windows_json_paths, engine_port)
    api = nm / "@deepseek-ai"
    version = _version_of(nm)

    files: list[dict] = []
    missing: list[str] = []
    occurrences = 0
    distinct: set[str] = set()
    comment_total = 0
    comment_examples: list[dict] = []

    for path in config_files(repo, scope):
        real, in_comment = scan_file(path)
        rows = []
        for name, line in real:
            present = (api / name.split("/", 1)[1]).is_dir()
            rows.append({"name": name, "line": line, "resolves": present})
            occurrences += 1
            distinct.add(name)
            if not present and name not in missing:
                missing.append(name)
        comment_total += len(in_comment)
        for name, line in in_comment:
            comment_examples.append({"name": name, "file": rel(path, repo), "line": line})
        files.append({
            "file": rel(path, repo),
            "rows": rows,
            "commentMentions": len(in_comment),
        })

    data = {
        "status": "missing" if missing else "ok",
        "missing": missing,
        "engineRoot": str(prefix),
        "engineNodeModules": str(nm),
        "engineVersion": version,
        "engineSource": why,
        "enginePackages": sum(1 for p in api.iterdir() if p.is_dir()) if api.is_dir() else 0,
        "scope": scope,
        "files": files,
        "occurrences": occurrences,
        "distinct": len(distinct),
        "commentSkipped": comment_total,
        "commentExamples": comment_examples,
        "repo": str(repo),
    }
    data.update(evidence)
    return data


def rel(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return str(path)


def render(data: dict) -> None:
    print("version-coupled config check")
    print(f"  repo        : {data['repo']}")
    print(f"  engine root : {data['engineRoot']} (from {data['engineSource']})")
    print(f"  engine      : {data['engineVersion']}  (@deepseek-ai/dsh/package.json)")
    print(f"  found via   : {data['engineProvenance']}")
    if data.get("runningEngines"):
        for e in data["runningEngines"]:
            if e["pid"] == data.get("enginePid") and data.get("engineResolvedBy") == "running-process":
                continue
            print(f"  also running: {e['version']}  {e['root']}  (pid {e['pid']}, "
                  f"{'web engine on port ' + str(e['port']) if e['web'] else 'session process'})")
    for c in data.get("configuredCandidates") or []:
        if not c["complete"]:
            if c["raw"]:
                print(f"  configured  : {c['knob']} -> {c['raw']} (not a DSH install)")
            continue
        if data.get("engineResolvedBy") == "config":
            mark = ("[USED -- no running engine was found, so this reading is WEAK]"
                    if c["root"] == data["engineRoot"] else
                    "[not used -- a higher-priority configured path won]")
        elif data.get("engineResolvedBy") == "engine-root":
            mark = "[not used -- --engine-root decides]"
        else:
            mark = "[NOT USED -- an engine is RUNNING and the running process decides]"
        print(f"  configured  : {c['knob']} -> {c['root']} ({c['version']}) {mark}")
    if data.get("liveSearch"):
        print(f"  live search : {data['liveSearch']}")
    print(f"  packages    : {data['enginePackages']} under {data['engineNodeModules']}\\@deepseek-ai")
    print(f"  scope       : {data['scope']}")
    if data.get("conflictLines"):
        print()
        for line in data["conflictLines"]:
            print(line)
    print()
    for entry in data["files"]:
        print(entry["file"])
        if not entry["rows"]:
            print("  (no @deepseek-ai names in code -- comment mentions only)"
                  if entry["commentMentions"] else "  (no @deepseek-ai names)")
        for row in entry["rows"]:
            state = "ok     " if row["resolves"] else "MISSING"
            print(f"  line {row['line']:<5} {state} {row['name']}")
        if entry["commentMentions"]:
            print(f"  ({entry['commentMentions']} comment mention(s) skipped)")
        print()
    verdict_engine = (f"the RUNNING engine {data['engineVersion']} ({data['engineRoot']})"
                      if data.get("engineResolvedBy") == "running-process"
                      else f"engine {data['engineVersion']} ({data['engineSource']})")
    if data["missing"]:
        print(f"summary: {len(data['missing'])} MISSING -- {', '.join(data['missing'])} -- "
              f"{verdict_engine} does not provide "
              f"{'them' if len(data['missing']) > 1 else 'it'}; a composition row naming "
              f"{'them' if len(data['missing']) > 1 else 'it'} fails to mount "
              f"({data['occurrences']} occurrence(s), {data['distinct']} distinct package(s), "
              f"{len(data['files'])} file(s))")
    else:
        print(f"summary: every name resolves -- {verdict_engine}, "
              f"{data['occurrences']} occurrence(s), {data['distinct']} distinct package(s), "
              f"{len(data['files'])} file(s)")
    print(f"comment mentions skipped: {data['commentSkipped']}"
          + (f" -- e.g. {data['commentExamples'][0]['name']} at "
             f"{data['commentExamples'][0]['file']}:{data['commentExamples'][0]['line']}"
             if data["commentExamples"] else ""))


def _run(argv: list[str] | None) -> int:
    ap = argparse.ArgumentParser(
        description="Check that every @deepseek-ai package named by presets/*/agent.cordis.yml "
                    "and profiles/*/cordis.patch.yml exists in the engine that is RUNNING.")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent),
                    help="harness-config repo root (default: the parent of this script)")
    ap.add_argument("--engine-root", default=None,
                    help="DSH install root: the npm prefix containing node_modules/@deepseek-ai/, "
                         "or that node_modules dir, or a .../dsh/lib/bin.js path. DEFAULT (this now "
                         "wins over everything but --engine-root): the engine that is RUNNING, "
                         "resolved from the live process's own command line.")
    ap.add_argument("--engine-port", type=int, default=None,
                    help="restrict the running-engine lookup to the `dsh ... web` process serving "
                         "this port. A port nothing is listening on makes the lookup find nothing, "
                         "which exercises the configuration fallback on a machine that does have an "
                         "engine running. Default: any running engine process.")
    ap.add_argument("--windows-json", action="append", default=None, metavar="PATH",
                    help="read `dshInstall` from this launcher config instead of the defaults "
                         "(<repo>/multi-window/windows.json and $DSH_HOME/multi-window/windows.json). "
                         "Repeatable. Use it to test a TRANSIENT config without touching the real "
                         "one. Ignored while an engine is running, and that is the point.")
    ap.add_argument("--scope", choices=SCOPES, default="all",
                    help="which steps to check (default: all). sync.py checks each step separately.")
    ap.add_argument("--json", action="store_true",
                    help="print one machine-readable JSON object on stdout and nothing else "
                         "(used by scripts/sync.py; all warnings then go to stderr)")
    args = ap.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    if not (repo / "presets").is_dir() and not (repo / "profiles").is_dir():
        print(f"--repo is not a harness-config tree (no presets/ and no profiles/): {repo}",
              file=sys.stderr)
        return 2

    dsh_home = Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))
    if args.windows_json:
        windows_json_paths = [Path(p).expanduser() for p in args.windows_json]
    else:
        windows_json_paths = [repo / "multi-window" / "windows.json",
                              dsh_home / "multi-window" / "windows.json"]

    data = build(repo, args.scope, args.engine_root, windows_json_paths, args.engine_port)
    if args.json:
        # stdout carries exactly one JSON object; every warning is on stderr. The conflict block
        # is a warning, so it goes to stderr here and is also carried as JSON for the caller.
        for line in data.get("conflictLines") or []:
            print(line, file=sys.stderr)
        if data.get("liveSearch"):
            print(f"check-version-coupled-config: {data['liveSearch']}", file=sys.stderr)
        print(json.dumps(data, ensure_ascii=True))
    else:
        render(data)
    return 1 if data["missing"] else 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    try:
        return _run(argv)
    except SystemExit:
        raise
    except Exception as exc:  # never let a bug in the checker masquerade as a finding
        print(f"check-version-coupled-config: ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
