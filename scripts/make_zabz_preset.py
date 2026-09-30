"""Author the `zabz` preset: the conversational CEO that replaces Copilot.

Built by transforming the `cordis-bg` composition (which already carries the
background-first shell policy) rather than writing a fresh file, so nothing that
was already fixed is lost.

WHAT THE SINGLE SOURCE OF TRUTH IS (fixed 2026-09-30)
-----------------------------------------------------
This generator reads TWO declarative inputs and nothing else:

  * ``presets/cordis-bg/agent.cordis.yml`` -- the shared base composition. Every
    row ``zabz`` does not override is inherited from here, so one fix reaches
    both presets.
  * ``presets/zabz/rows/`` -- the rows ``zabz`` changes or adds, as plain YAML:
      - ``persona.row.yml``      the whole ``- id: persona`` row
      - ``delegation.rows.yml``  the rows that replace the base's local ``tool-subagent``
      - ``mcp.rows.yml``         the whole MCP bridge section, appended

BEFORE THIS, those three regions were Python string constants inside this file,
and the committed preset carried hand edits the constants did not know about. So
regeneration silently deleted owner rules 8 and 9, the hardened outbound-comms
hard stop, the "ask him before a counterparty" rule and the mesh background flag
-- measured 2026-09-28 (33 lines) and again 2026-09-30. A rule that lives only in
the generated file is deleted the next time anyone runs this. Put every change in
``rows/`` (or in ``presets/cordis-bg/agent.cordis.yml`` when it belongs to both
presets), re-run, and use ``--check`` to catch drift.

GENERATED OUTPUT. ``presets/zabz/agent.cordis.yml`` and ``presets/zabz/preset.yml``
are rewritten wholesale from the inputs above. NEVER hand-edit either: an edit
there is reverted by the next run. ``profiles/web/cordis.patch.yml`` then carries a
GENERATED copy of these rows, written by ``scripts/make-preset-rows.mjs``. Run both,
in this order:

    python scripts/make_zabz_preset.py             # rows/ -> presets/zabz
    node scripts/make-preset-rows.mjs --install    # presets/zabz -> patch layer

    python scripts/make_zabz_preset.py --check && node scripts/make-preset-rows.mjs --check
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "presets" / "cordis-bg" / "agent.cordis.yml"
DST_DIR = REPO / "presets" / "zabz"
DST = DST_DIR / "agent.cordis.yml"

# The declarative source of every row this preset changes or adds. A row is
# defined HERE and nowhere else; the preset file below is generated output.
ROWS_DIR = DST_DIR / "rows"
PERSONA_ROW_SRC = ROWS_DIR / "persona.row.yml"
DELEGATION_ROWS_SRC = ROWS_DIR / "delegation.rows.yml"
MCP_ROWS_SRC = ROWS_DIR / "mcp.rows.yml"

# The base row `delegation.rows.yml` replaces. This is a match key into the BASE
# file, not a row definition: the definition lives in the base composition. It is
# checked rather than assumed -- if the base row is ever rewritten this exits 2
# instead of silently generating a preset whose `subagent` tool is still local.
LOCAL_SUBAGENT_ANCHOR = """    - id: tool-subagent
      name: '@deepseek-ai/dsh-tool-subagent'
      config:
        provider: spawn
        toolName: subagent
        modelSelectionSettings: true
        backgroundMode: continuable
"""


def load_row_sources() -> tuple[str, str, str] | None:
    """Read the three declarative row sources, or report exactly what is missing."""
    missing = [p for p in (PERSONA_ROW_SRC, DELEGATION_ROWS_SRC, MCP_ROWS_SRC) if not p.exists()]
    if missing:
        for path in missing:
            print(f"missing row source: {path.relative_to(REPO)}", file=sys.stderr)
        print(
            "every row this preset changes or adds must live in presets/zabz/rows/; "
            "there is no other definition site.",
            file=sys.stderr,
        )
        return None
    return (
        PERSONA_ROW_SRC.read_text(encoding="utf-8"),
        DELEGATION_ROWS_SRC.read_text(encoding="utf-8"),
        MCP_ROWS_SRC.read_text(encoding="utf-8"),
    )


def build() -> str | None:
    """Return the generated preset text, or None when an input is missing/invalid."""
    if not SRC.exists():
        print(f"missing source composition: {SRC}", file=sys.stderr)
        return None

    rows = load_row_sources()
    if rows is None:
        return None
    persona_row, delegation_rows, mcp_rows = rows

    text = SRC.read_text(encoding="utf-8")

    # Replace the whole persona row (from `- id: persona` to the next top-level row)
    # with the declarative row. `lambda` because the replacement is YAML text, not a
    # template: backslashes and group references must stay literal.
    pattern = re.compile(r"^- id: persona\n(?:.*\n)*?(?=^- id: )", re.MULTILINE)
    if not pattern.search(text):
        print("could not locate the persona row in the base composition", file=sys.stderr)
        return None
    text = pattern.sub(lambda _m: persona_row, text, count=1)

    # ── the mesh routing default ─────────────────────────────────────────────
    # WHY IT IS REWRITTEN HERE AND NOT IN presets/cordis-bg/agent.cordis.yml:
    # that file is the SOURCE for two presets, and the mesh route is granted to
    # one of them on purpose -- the owner's own `zabz` sessions. `cordis-bg` keeps
    # delegating locally. The rows themselves are declared in
    # presets/zabz/rows/delegation.rows.yml.
    if "tool-subagent-local" not in text:
        occurrences = text.count(LOCAL_SUBAGENT_ANCHOR)
        if occurrences != 1:
            print(
                f"could not locate the local tool-subagent row "
                f"(found {occurrences}, want exactly 1) -- refusing to generate a preset "
                f"whose `subagent` tool would still run its children on this machine",
                file=sys.stderr,
            )
            return None
        text = text.replace(LOCAL_SUBAGENT_ANCHOR, delegation_rows, 1)

    if "mcp-secretary" not in text:
        text = text.rstrip("\n") + "\n" + mcp_rows

    return text


PRESET_YML = (
    "name: Zabz (CEO)\n"
    "description: >-\n"
    "  The conversational CEO. Full toolbelt plus the secretary bridge, and a persona\n"
    "  written from the measured analysis of 23,035 owner turns: finish the work, ask\n"
    "  rarely and one at a time, decide the development questions, record decisions,\n"
    "  verify rather than assume, and never report a number without its provenance.\n"
)


def skill_drift() -> list[str]:
    """One-way skill check: every cordis-bg skill must be present and identical here.

    Extra skills under presets/zabz/skills/ are allowed and are NOT reported: they
    are zabz-only (e.g. `secretary-wake`), and the delete-then-copy this replaced
    silently removed them on every regeneration.
    """
    src_skills = SRC.parent / "skills"
    if not src_skills.is_dir():
        return []
    dst_skills = DST_DIR / "skills"
    drifted = []
    for item in sorted(src_skills.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(src_skills)
        target = dst_skills / rel
        if not target.exists() or target.read_bytes() != item.read_bytes():
            drifted.append(str((DST_DIR / "skills" / rel).relative_to(REPO)))
    return drifted


def sync_skills() -> None:
    """Copy the base skills over, WITHOUT deleting zabz-only skills.

    The previous rmtree+copytree removed presets/zabz/skills/secretary-wake on every
    run -- a silent loss of a tracked capability, the same defect class as the rows.
    """
    src_skills = SRC.parent / "skills"
    if not src_skills.is_dir():
        return
    dst_skills = DST_DIR / "skills"
    for item in sorted(src_skills.rglob("*")):
        if item.is_file():
            rel = item.relative_to(src_skills)
            target = dst_skills / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate presets/zabz from presets/cordis-bg and presets/zabz/rows.")
    ap.add_argument(
        "--check",
        action="store_true",
        help="report whether the committed preset matches this generator; write nothing.",
    )
    args = ap.parse_args()

    text = build()
    if text is None:
        return 2

    # `--check` compares bytes, not text -- a line-ending change is drift too -- and writes
    # nothing. This is what makes a hand edit to the generated file visible, instead of
    # silently overwritten by the next run.
    if args.check:
        expected = {
            DST: text.encode("utf-8"),
            DST_DIR / "preset.yml": PRESET_YML.encode("utf-8"),
        }
        drifted = [
            str(path.relative_to(REPO))
            for path, want in expected.items()
            if not path.exists() or path.read_bytes() != want
        ]
        drifted.extend(skill_drift())
        if drifted:
            print("DRIFT: the committed preset does not match this generator:", file=sys.stderr)
            for name in drifted:
                print(f"  {name}", file=sys.stderr)
            print(
                "Re-run without --check to regenerate -- but move any hand edit into "
                "presets/zabz/rows/ (or presets/cordis-bg/agent.cordis.yml) first, or "
                "regeneration deletes it.",
                file=sys.stderr,
            )
            return 1
        print("zabz: in sync with the generator (rows + skills)")
        print("next: node scripts/make-preset-rows.mjs --check   # patch layer")
        return 0

    DST_DIR.mkdir(parents=True, exist_ok=True)
    # Write LF explicitly. `.gitattributes` forces `eol=lf` and the live presets under
    # ~/.dsh are LF, but Python's text mode translates "\n" to os.linesep -- so on Windows
    # every generation produced a whole-file CRLF diff and left `preset.yml` permanently
    # dirty. That is the "difference that never converges" the line-ending policy exists to
    # prevent.
    DST.write_text(text, encoding="utf-8", newline="\n")
    (DST_DIR / "preset.yml").write_text(PRESET_YML, encoding="utf-8", newline="\n")

    # Carry the base skills across so the preset is self-contained, additively.
    sync_skills()

    rows = re.findall(r"^- id: (\S+)", text, re.MULTILINE)
    print(f"wrote {DST.relative_to(REPO)}")
    print(f"  rows: {len(rows)}")
    print(f"  {', '.join(rows)}")
    print("  row sources: presets/zabz/rows/{persona.row,delegation.rows,mcp.rows}.yml")
    print("next: node scripts/make-preset-rows.mjs --install   # regenerate the patch layer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
