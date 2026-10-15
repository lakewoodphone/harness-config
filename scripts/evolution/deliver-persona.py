#!/usr/bin/env python3
"""deliver-persona.py — put ONE persona on a machine, and prove the machine loads it.

WHY THIS EXISTS (round 6, 2026-10-15). The instruction surface reached one machine of three.
ZABZ-YOGA carried the current persona; ZABZ-TECH and `secratary-cloud` carried a generation that
predated it and still named the FROZEN office box as the authority. Every gate reported success
while that was true, because each machine's own checkout was self-consistently old: its generator
matched its preset, its preset matched its committed rows, and `make_zabz_preset.py --check`
answered "in sync with the generator" on all three.

So the thing to propagate is not the generated artefact — it is the GENERATOR, which is the source
of truth for `presets/zabz/agent.cordis.yml`. This script assumes the corrected
`scripts/make_zabz_preset.py` is already in place in the repo and does the rest, in order, printing
the evidence for each step:

  1. back up the three files this touches
  2. regenerate  presets/zabz/agent.cordis.yml  from the generator
  3. regenerate  profiles/web/*                 from presets/   (`make-preset-rows.mjs --install`)
  4. repair the hand-maintained head: a `brokerSsh` default naming the frozen office box
  5. publish     the live layer                 (`scripts/sync.py`)
  6. VERIFY      the COMPOSED config the engine actually builds (`--dump-config`)

Step 6 is the only step that answers "what will a session load". A green `--check` on steps 2-4 is
"the surface this check knows about is right" — round 5 measured a green check sitting on top of a
persona 21 hours stale. Step 6 is not optional.

Exit codes: 0 all steps verified; 1 a step failed; 2 usage/environment; 3 verified with a WARNING
(see the note on `--allow-dirty`).

Nothing here pushes, resets, cleans or deletes. It edits three files in one repo and publishes a
copy into `$DSH_HOME`.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# The markers that decide whether an instruction surface is the current one. Chosen because each
# one is a RULE that exists only in the current generation, and the two OLD strings are rules the
# current generation deliberately compressed away. A surface has to carry all of them NEW and
# neither OLD; anything else is a partial delivery and is reported as one.
#
# ROUND 6 (2026-10-15) moved the second marker set: the round-5 `read the failure before` paragraph
# was absorbed into the new rule 3, so it is no longer a marker of currency and asserting on it
# would have reported a good surface as stale. The markers name the RULE, not the paragraph that
# happens to carry it.
NEW_MARKERS = (
    "When he corrects you",
    "measurement rule, extended",
    "A non-zero exit is an open item",
    "Know which shell you are on",
)
OLD_MARKERS = (
    "On any larger job",
    "Never flag",
)

FILES_BACKED_UP = (
    "scripts/make_zabz_preset.py",
    "presets/zabz/agent.cordis.yml",
    "profiles/web/cordis.patch.yml",
)

BROKER_RE = re.compile(r"^(\s*brokerSsh:\s*(?:!!js\s*)?[\"']?[^\"'\n]*?)(secratary-ts)([\"']?,?\s*)$")

# The managed block markers. Everything BETWEEN them is generated from `presets/`; everything
# OUTSIDE them is hand-maintained, and that is where a stale hostname survives a regeneration.
# NOTE the shape: both markers begin with `<<<` (the BEGIN one reads
# `<<< preset-rows: BEGIN managed block ...`). A first version looked for `>>> preset-rows` and so
# never entered the block at all, which made every line look hand-maintained.
BLOCK_RE = re.compile(r"preset-rows:\s*(BEGIN|END)")

FROZEN_NAMES = ("secratary-ts",)


def run(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    """Run a command, return (exit code, combined output). Never raises on a non-zero exit."""
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        return 127, f"{cmd[0]}: not found ({exc})"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: {' '.join(cmd)}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def tail(text: str, n: int = 6) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join("    | " + ln for ln in lines[-n:])


def markers(text: str) -> tuple[dict[str, int], dict[str, int]]:
    return ({m: text.count(m) for m in NEW_MARKERS}, {m: text.count(m) for m in OLD_MARKERS})


def verdict(new: dict[str, int], old: dict[str, int]) -> tuple[bool, str]:
    missing = [m for m, c in new.items() if c == 0]
    present = [m for m, c in old.items() if c > 0]
    if not missing and not present:
        return True, "CURRENT"
    bits = []
    if missing:
        bits.append("missing: " + ", ".join(missing))
    if present:
        bits.append("still carries: " + ", ".join(present))
    return False, "; ".join(bits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="absolute path to the harness-config checkout")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--node", default="node")
    ap.add_argument("--engine-bin", default=None,
                    help="absolute path to @deepseek-ai/dsh/lib/bin.js; required for step 6 when "
                         "the engine is not resolvable from the running process")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-preset", action="store_true",
                    help="pass --force to make_zabz_preset.py, discarding paragraphs that exist in "
                         "the committed preset but not in the generator. READ THEM FIRST: the "
                         "generator prints them. This is the right flag when the committed preset is "
                         "an OLDER generation whose content the current generator supersedes, and the "
                         "wrong flag when someone put a real hand edit in the preset.")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="do not fail when the repo has uncommitted changes in the three files")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not (repo / "scripts" / "make_zabz_preset.py").is_file():
        print(f"! {repo} does not look like harness-config", file=sys.stderr)
        return 2

    host = os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "?")
    print(f"deliver-persona  host={host}  repo={repo}  mode={'DRY RUN' if args.dry_run else 'APPLY'}")
    print(f"  python={args.python}  node={args.node}")

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = repo / f".persona-backup-{stamp}"
    problems: list[str] = []
    warnings: list[str] = []

    # ---- 1. back up -------------------------------------------------------------------------
    print("\n[1] backup")
    if args.dry_run:
        print(f"    would copy {len(FILES_BACKED_UP)} files to {backup}")
    else:
        backup.mkdir(parents=True, exist_ok=True)
        for rel in FILES_BACKED_UP:
            src = repo / rel
            if src.is_file():
                shutil.copy2(src, backup / Path(rel).name)
                print(f"    {rel} -> {backup.name}/{Path(rel).name}")
            else:
                print(f"    {rel} ABSENT (nothing to back up)")

    # ---- 2. regenerate the preset -----------------------------------------------------------
    print("\n[2] regenerate presets/zabz/agent.cordis.yml from the generator")
    rc, out = run([args.python, "scripts/make_zabz_preset.py", "--check"], repo)
    print(f"    --check exit={rc}")
    print(tail(out, 3))
    if rc != 0:
        print("    drift or failure -- regenerating")
        if not args.dry_run:
            regen = [args.python, "scripts/make_zabz_preset.py"]
            if args.force_preset:
                regen.append("--force")
                print("    --force-preset given: the generator's refuse-to-delete paragraphs are "
                      "being discarded deliberately")
            rc2, out2 = run(regen, repo)
            print(f"    regenerate exit={rc2}")
            print(tail(out2, 4))
            if rc2 != 0:
                problems.append("step 2: make_zabz_preset.py failed")
        rc3, out3 = run([args.python, "scripts/make_zabz_preset.py", "--check"], repo)
        print(f"    re-check exit={rc3}")
        if rc3 != 0:
            problems.append("step 2: preset still not in sync after regeneration")
    else:
        print("    preset already in sync with the generator")

    # ---- 3. regenerate the profile rows -----------------------------------------------------
    print("\n[3] regenerate profiles/web from presets/ (make-preset-rows.mjs --install)")
    if args.dry_run:
        rc, out = run([args.node, "scripts/make-preset-rows.mjs", "--check"], repo)
        print(f"    --check exit={rc}")
        print(tail(out, 3))
    else:
        rc, out = run([args.node, "scripts/make-preset-rows.mjs", "--install"], repo)
        print(f"    --install exit={rc}")
        print(tail(out, 4))
        if rc != 0:
            problems.append("step 3: make-preset-rows.mjs --install failed")
        rc, out = run([args.node, "scripts/make-preset-rows.mjs", "--check"], repo)
        print(f"    --check exit={rc}")
        if rc != 0:
            problems.append("step 3: generated rows still not up to date")

    # ---- 4. the hand-maintained head --------------------------------------------------------
    # A LINE-BASED TRANSFORM, deliberately. The first version of this step used a regex that
    # required the hostname to be the first thing after the quote; the real line is
    #     brokerSsh: !!js "process.env.MESH_BROKER_SSH ?? 'secratary-ts'",
    # so the regex matched NOTHING and the step reported "nothing to repair" while the frozen
    # office box was still the composed default. A false negative that reads like a clean bill of
    # health is the worst shape a guard can have; a substring test cannot miss it this way.
    print("\n[4] the hand-maintained head: stale hostnames outside the generated block")
    patch_path = repo / "profiles" / "web" / "cordis.patch.yml"
    lines = patch_path.read_text(encoding="utf-8").splitlines()
    in_block = False
    head_hits: list[tuple[int, str]] = []
    broker_fixed = 0
    for i, ln in enumerate(lines):
        m = BLOCK_RE.search(ln)
        if m:
            in_block = m.group(1) == "BEGIN"
            continue
        if in_block or not any(n in ln for n in FROZEN_NAMES):
            continue
        if "brokerSsh" in ln:
            if args.dry_run:
                print(f"    would rewrite line {i+1}: {ln.strip()}")
            else:
                lines[i] = ln.replace("secratary-ts", "secratary-cloud")
                print(f"    rewrote line {i+1}: {lines[i].strip()}")
            broker_fixed += 1
        else:
            head_hits.append((i + 1, ln.strip()))
    if not broker_fixed and not head_hits:
        print("    no stale hostname outside the generated block")
    for n, ln in head_hits:
        print(f"    REVIEW line {n} (NOT rewritten -- judge it): {ln[:140]}")
        warnings.append(f"step 4: line {n} outside the generated block names a frozen host")
    if not args.dry_run and broker_fixed:
        patch_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        after = [ln.strip() for ln in lines if "brokerSsh" in ln]
        for ln in after:
            print(f"    now : {ln}")
        if any("secratary-ts" in ln for ln in after):
            problems.append("step 4: brokerSsh still names the frozen box")

    # ---- 5. publish the live layer ----------------------------------------------------------
    print("\n[5] publish the live layer (scripts/sync.py)")
    if args.dry_run:
        rc, out = run([args.python, "scripts/sync.py", "--dry-run"], repo)
    else:
        rc, out = run([args.python, "scripts/sync.py"], repo)
    print(f"    sync exit={rc}")
    print(tail(out, 8))
    if rc != 0:
        # A non-zero exit here is the point of the loud-skip change, not automatically a failure of
        # this delivery: read what it says rather than assuming.
        warnings.append(f"step 5: sync.py exited {rc} -- read its output above")

    # ---- 6. VERIFY the composed config ------------------------------------------------------
    print("\n[6] VERIFY the composed config the engine builds (--dump-config)")
    bin_path = args.engine_bin
    if not bin_path:
        candidates = [
            Path(os.environ.get("DSH_HOME", Path.home() / ".dsh")) / "engine" /
            "node_modules/@deepseek-ai/dsh/lib/bin.js",
            Path("/opt/dsh-phone/node_modules/@deepseek-ai/dsh/lib/bin.js"),
        ]
        for c in candidates:
            if c.is_file():
                bin_path = str(c)
                break
    if not bin_path:
        print("    NO ENGINE FOUND -- pass --engine-bin. The composed config is UNVERIFIED.")
        problems.append("step 6: no engine bin; composed config unverified")
    else:
        print(f"    engine: {bin_path}")
        rc, out = run([args.node, bin_path, "--profile", "web", "--dump-config"], repo, timeout=300)
        print(f"    dump-config exit={rc}  bytes={len(out)}")
        if rc != 0:
            problems.append(f"step 6: --dump-config exited {rc}")
        else:
            new, old = markers(out)
            ok, why = verdict(new, old)
            for m, c in new.items():
                print(f"      NEW  {m:<32} {c}")
            for m, c in old.items():
                print(f"      OLD  {m:<32} {c}")
            print(f"    VERDICT: {'CURRENT' if ok else 'STALE -- ' + why}")
            if not ok:
                problems.append(f"step 6: composed config is not current ({why})")

    # ---- summary ----------------------------------------------------------------------------
    print("\n" + "=" * 72)
    if problems:
        print("FAILED:")
        for p in problems:
            print(f"  - {p}")
    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  - {w}")
    if not problems and not warnings:
        print("all steps verified")
    print("=" * 72)
    if problems:
        return 1
    return 3 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
