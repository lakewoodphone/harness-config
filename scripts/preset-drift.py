#!/usr/bin/env python3
"""preset-drift.py — is the instruction surface this machine LOADS the one in the repo?

THE FAILURE CLASS, MEASURED 2026-10-13. The estate keeps producing edits that are correct in git and
absent where they run. Four instances in one program: the archive script (W2758), two `main`
lineages of harness-config (P3164), `scripts/owner-queue.py` being 8.7 KB behind its deployed copy,
and this one -- the worst of them, because it is the *instructions*:

    secratary-cloud  /root/.dsh/.agent-presets/zabz/agent.cordis.yml
                     57,970 bytes, mtime 2026-10-11 20:14 -- two days old, still shipping the
                     single-brace `{cwd}` bug, with none of the rules written that week.
    ZABZ-YOGA        %USERPROFILE%\\.dsh\\.agent-presets\\zabz\\agent.cordis.yml
                     58,677 bytes vs the repo's 56,297 -- also not the repo's file.

So a session could read a corrected persona in the repo, write a rule into it, verify it, report it
fixed -- and every session on every machine would keep loading the old one. **A commit is a claim
about a file, not about a machine.**

RELATION TO `assert-bin-matches-repo.py`: that tool answers the same question for a DIFFERENT surface
(the text-line scripts in `/home/zabz/bin/` on the authority, compared over ssh against captured
copies). This one answers it for the surfaces a machine LOADS ITSELF -- the agent presets and the
skill catalog under `$DSH_HOME` -- and is deliberately local, so every machine can check itself with
no ssh and no manifest to keep in step.

SURFACES COMPARED
    repo                                    -> loaded
    presets/<p>/agent.cordis.yml            -> $DSH_HOME/.agent-presets/<p>/agent.cordis.yml
    presets/<p>/preset.yml                  -> $DSH_HOME/.agent-presets/<p>/preset.yml
    presets/<p>/skills/<s>/SKILL.md         -> $DSH_HOME/skills/<s>/SKILL.md

**THE SKILL CATALOG IS ONE SHARED NAMESPACE.** Every preset carries its own copy of a skill, and
`$DSH_HOME/skills/<s>/SKILL.md` holds exactly one of them -- measured 2026-10-13, the catalog's
`lpt-production-case-work` matched `zabz`'s copy (11,878 B) while `yocheved` and `cordis-bg` carried
an older one (10,545 B). So comparing each preset's copy against the catalog one at a time reports
drift where there is none, and applying them in turn would let whichever ran LAST win. A skill is
therefore MATCH when the loaded file equals **any** preset's copy, and `--apply` installs skills from
one named source (`--skill-source`, default `zabz`) and says so.

One line per compared file, in `assert-bin-matches-repo.py`'s own vocabulary:

    MATCH    <path>   sha=<sha>
    MATCH    skill/<s>  = presets/<p>   (the catalog matches this preset's copy)
    DRIFT    <path>   repo=<sha> loaded=<sha> [repo=<bytes>B loaded=<bytes>B]
    DRIFT    skill/<s>  loaded=<sha> matches none of: <preset>=<sha>, ...
    MISSING  <path>   repo=<sha|ABSENT> loaded=<sha|ABSENT>

EXIT
    0  every compared file is MATCH
    1  at least one is DRIFT or MISSING
    2  the tool could not do its job (no repo, no preset dir, nothing compared) -- never a pass

USAGE
    preset-drift.py [--repo DIR] [--dsh-home DIR] [--json] [--quiet]
                    [--preset NAME] [--apply] [--skill-source NAME] [--backup-dir DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def repo_root(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if (p / "presets").is_dir() else None
    # Walk up from this file: <repo>/scripts/preset-drift.py
    here = Path(__file__).resolve()
    for cand in (here.parent.parent, here.parent.parent.parent):
        if (cand / "presets").is_dir():
            return cand
    for env in ("HARNESS_CONFIG",):
        if os.environ.get(env):
            p = Path(os.environ[env]).expanduser()
            if (p / "presets").is_dir():
                return p
    return None


def dsh_home(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("DSH_HOME"):
        return Path(os.environ["DSH_HOME"]).expanduser()
    return Path(os.path.expanduser("~/.dsh"))


def pairs(repo: Path, only: str | None) -> list[tuple[str, Path, Path]]:
    """(label, repo_path, loaded_path) for the PER-PRESET files (not the shared skill catalog)."""
    out: list[tuple[str, Path, Path]] = []
    for preset_dir in sorted((repo / "presets").iterdir()):
        if not preset_dir.is_dir():
            continue
        name = preset_dir.name
        if only and name != only:
            continue
        for fn in ("agent.cordis.yml", "preset.yml"):
            src = preset_dir / fn
            if src.is_file():
                out.append((f"{name}/{fn}", src, HOME / ".agent-presets" / name / fn))
    return out


def skill_copies(repo: Path, only: str | None) -> dict[str, list[tuple[str, Path]]]:
    """{skill_name: [(preset, src), ...]} — every preset's copy of every skill.

    The catalog is ONE namespace, so this is a group, not a list of independent files.
    """
    out: dict[str, list[tuple[str, Path]]] = {}
    for preset_dir in sorted((repo / "presets").iterdir()):
        if not preset_dir.is_dir():
            continue
        name = preset_dir.name
        if only and name != only:
            continue
        sk = preset_dir / "skills"
        if not sk.is_dir():
            continue
        for s in sorted(sk.iterdir()):
            f = s / "SKILL.md"
            if f.is_file():
                out.setdefault(s.name, []).append((name, f))
    return out


HOME: Path  # set in main; module-level so pairs() can use it


def main() -> int:
    global HOME
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo")
    ap.add_argument("--dsh-home")
    ap.add_argument("--preset", help="compare only this preset")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="only DRIFT/MISSING and the summary")
    ap.add_argument("--apply", action="store_true",
                    help="install the repo's file over the loaded one (timestamped backup first)")
    ap.add_argument("--skill-source", default="zabz",
                    help="which preset's copy to install for a shared skill (default: zabz)")
    ap.add_argument("--backup-dir", help="where the pre-install copies go (default: alongside)")
    a = ap.parse_args()

    repo = repo_root(a.repo)
    if repo is None:
        print("preset-drift: cannot find a harness-config checkout (no presets/ dir) -- "
              "pass --repo. This is exit 2, not a pass.", file=sys.stderr)
        return 2
    HOME = dsh_home(a.dsh_home)

    todo = pairs(repo, a.preset)
    skills = skill_copies(repo, a.preset)
    if not todo and not skills:
        print(f"preset-drift: nothing to compare in {repo}/presets"
              + (f" for preset {a.preset!r}" if a.preset else "") + " -- exit 2, not a pass.",
              file=sys.stderr)
        return 2
    if not (HOME / ".agent-presets").is_dir() and not (HOME / "skills").is_dir():
        print(f"preset-drift: {HOME} holds no .agent-presets/ and no skills/ -- this machine has no "
              "loaded instruction surface to compare against. Exit 2, not a pass.", file=sys.stderr)
        return 2

    rows, installed, drifted, missing = [], [], [], []
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

    def install(src: Path, dst: Path) -> dict:
        dst.parent.mkdir(parents=True, exist_ok=True)
        extra = {}
        if dst.is_file():
            bdir = Path(a.backup_dir).expanduser() if a.backup_dir else dst.parent
            bdir.mkdir(parents=True, exist_ok=True)
            bak = bdir / (dst.name + f".pre-driftsync-{ts}")
            shutil.copy2(dst, bak)
            extra["backup"] = str(bak)
        shutil.copyfile(src, dst)
        extra["installed"] = True
        extra["installed_sha"] = sha256(dst)
        extra["verified"] = extra["installed_sha"] == sha256(src)
        installed.append(str(dst))
        return extra

    for label, src, dst in todo:
        s_sha = sha256(src)
        d_sha = sha256(dst) if dst.is_file() else None
        if d_sha is None:
            state = "MISSING"
            missing.append(label)
        elif d_sha == s_sha:
            state = "MATCH"
        else:
            state = "DRIFT"
            drifted.append(label)
        row = {"label": label, "kind": "preset-file", "state": state,
               "repo_path": str(src), "loaded_path": str(dst), "repo_sha": s_sha,
               "loaded_sha": d_sha, "repo_bytes": src.stat().st_size,
               "loaded_bytes": dst.stat().st_size if dst.is_file() else None}
        if a.apply and state != "MATCH":
            row.update(install(src, dst))
        rows.append(row)

    # --- the shared skill catalog: ONE namespace, so it is measured against ONE designated source.
    # Matching "any preset" was the first cut and it was WRONG in a way worth keeping written down:
    # `parallel-agent-orchestration` read MATCH because the catalog held `cordis-bg`'s 10,802-byte
    # copy -- while `zabz`'s 13,275-byte copy carried three rules this program had added. "Matches
    # something in the repo" is not "matches the surface this preset loads". The standard is the
    # designated source, and the repo disagreeing with itself is reported separately.
    divergent = []
    for skill, copies in sorted(skills.items()):
        dst = HOME / "skills" / skill / "SKILL.md"
        by_sha = {}
        for preset, src in copies:
            by_sha.setdefault(sha256(src), []).append((preset, src))
        if len(by_sha) > 1:
            sizes = ", ".join(f"{p}={s.stat().st_size}B" for p, s in copies)
            divergent.append(f"skill/{skill} ({sizes})")

        src_preset = a.skill_source
        pick = next((s for p, s in copies if p == src_preset), None)
        if pick is None:
            pick, src_preset = copies[0][1], copies[0][0]
        target_sha = sha256(pick)

        d_sha = sha256(dst) if dst.is_file() else None
        matched_preset = None
        if d_sha:
            for sha, group in by_sha.items():
                if sha == d_sha:
                    matched_preset = group[0][0]
                    break
        if d_sha is None:
            state = "MISSING"
        elif d_sha == target_sha:
            state = "MATCH"
        else:
            state = "DRIFT"

        row = {"label": f"skill/{skill}", "kind": "skill", "state": state,
               "loaded_path": str(dst), "loaded_sha": d_sha,
               "loaded_bytes": dst.stat().st_size if dst.is_file() else None,
               "preset_copies": {p: sha256(s)[:12] for p, s in copies},
               "preset_sizes": {p: s.stat().st_size for p, s in copies},
               "repo_internally_divergent": len(by_sha) > 1,
               "skill_source": src_preset,
               "loaded_matches_preset": matched_preset,
               "repo_path": str(pick), "repo_sha": target_sha,
               "repo_bytes": pick.stat().st_size}
        if state != "MATCH":
            (missing if state == "MISSING" else drifted).append(row["label"])
            if a.apply:
                row.update(install(pick, dst))
        rows.append(row)

    if a.json:
        print(json.dumps({"repo": str(repo), "dsh_home": str(HOME), "at": ts,
                          "compared": len(rows), "drift": drifted, "missing": missing,
                          "installed": installed, "rows": rows}, indent=2))
    else:
        for r in rows:
            if a.quiet and r["state"] == "MATCH":
                continue
            if r["state"] == "MATCH":
                extra = (f"  = presets/{r['skill_source']}" if r["kind"] == "skill" else
                         f"  sha={r['repo_sha'][:12]}")
                print(f"MATCH    {r['label']:<44}{extra}")
            elif r["state"] == "MISSING":
                print(f"MISSING  {r['label']:<44} loaded=ABSENT"
                      + (f"  repo={r['repo_sha'][:12]}" if r.get("repo_sha") else ""))
            else:
                if r["kind"] == "skill":
                    cand = ", ".join(f"{p}={s}" for p, s in r["preset_copies"].items())
                    print(f"DRIFT    {r['label']:<44} loaded={(r['loaded_sha'] or 'ABSENT')[:12]}"
                          f" is {r['loaded_matches_preset'] or 'no preset'}; "
                          f"needs presets/{r['skill_source']} ({r['repo_bytes']}B) of {cand}")
                else:
                    print(f"DRIFT    {r['label']:<44} repo={r['repo_sha'][:12]} "
                          f"loaded={(r['loaded_sha'] or 'ABSENT')[:12]} "
                          f"[{r['repo_bytes']}B vs {r['loaded_bytes']}B]")
            if r.get("installed"):
                print(f"         installed -> {r['loaded_path']}"
                      + (f"  (backup {r['backup']})" if r.get("backup") else "")
                      + (f"  from presets/{r['skill_source']}" if r.get("skill_source") else "")
                      + ("  VERIFIED" if r.get("verified") else "  ** HASH MISMATCH **"))
        print()
        if divergent:
            print("THE REPO DISAGREES WITH ITSELF — the catalog can hold only one copy of each of "
                  "these, so the presets are not interchangeable:")
            for d in divergent:
                print(f"  DIVERGENT  {d}")
            print()
        print(f"compared {len(rows)}  match={len(rows)-len(drifted)-len(missing)}  "
              f"drift={len(drifted)}  missing={len(missing)}  divergent-in-repo={len(divergent)}"
              + (f"  installed={len(installed)}" if a.apply else ""))

    if a.apply:
        bad = [r for r in rows if r.get("installed") and not r.get("verified")]
        if bad:
            return 2
        return 0
    return 1 if (drifted or missing or divergent) else 0


if __name__ == "__main__":
    sys.exit(main())
