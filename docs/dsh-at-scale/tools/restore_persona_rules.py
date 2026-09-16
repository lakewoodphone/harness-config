"""Restore the two hand-added persona rules that regeneration dropped.

WHY THIS EXISTS
`make_zabz_preset.py` rewrites `presets/zabz/agent.cordis.yml` wholesale from its own
PERSONA string. Two rules had been hand-added to the live preset *without* being put back
into the generator, so regenerating deleted them from the preset that ten live sessions
read as their system prompt:

  * "1b. On any larger job, orchestrate -- do not grind serially."
  * "AI models are never hardcoded -- resolve them at runtime."

The generator's own --check output warned about exactly this ("move any hand edit into
this file first, or regeneration deletes it") and I regenerated anyway.

This script copies the two paragraphs BYTE-FOR-BYTE out of the pre-regeneration backup and
inserts them into the generator's PERSONA, so the text cannot drift from the original.
"""
import io
import re
import sys

BACKUP = r"C:\Users\ezabz\AppData\Local\Temp\agent.cordis.yml.bak"
GEN = r"C:\Users\ezabz\code\harness-config\scripts\make_zabz_preset.py"

MARK_A = "1b. On any larger job, orchestrate"
MARK_B = "AI models are never hardcoded"
ANCHOR_A = "**1. Do not stop to ask permission you already have.**"
ANCHOR_B = "**One source of truth per thing.**"


def persona_lines() -> list[str]:
    text = io.open(BACKUP, encoding="utf-8").read()
    m = re.search(r"^- id: persona\n(?:.*\n)*?(?=^- id: )", text, re.M)
    if not m:
        sys.exit("could not find the persona block in the backup")
    raw = m.group(0).splitlines()
    # The YAML block scalar indents the body by six spaces; the generator's PERSONA is
    # unindented and the generator adds the six back when it writes.
    return [ln[6:] if ln.startswith("      ") else ln for ln in raw]


def pick(lines: list[str], marker: str) -> str:
    for ln in lines:
        if marker in ln:
            return ln
    sys.exit("marker not found in the backup persona: %r" % marker)


def insert_after(text: str, anchor: str, block: list[str]) -> str:
    out, done = [], False
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        out.append(ln)
        if not done and anchor in ln:
            # Keep exactly one blank line between paragraphs, matching the file's style.
            while out and out[-1].strip() == "":
                out.pop()
            out.append("")
            out.extend(block)
            out.append("")
            done = True
    if not done:
        sys.exit("anchor not found in the generator: %r" % anchor)
    return "\n".join(out)


def main() -> int:
    pl = persona_lines()
    block_a = [pick(pl, MARK_A)]
    block_b = [pick(pl, MARK_B)]
    print("recovered A: %d chars" % len(block_a[0]))
    print("recovered B: %d chars" % len(block_b[0]))

    gen = io.open(GEN, encoding="utf-8").read()
    if MARK_A in gen or MARK_B in gen:
        print("generator already contains the rules; nothing to do")
        return 0

    gen = insert_after(gen, ANCHOR_A, block_a)
    gen = insert_after(gen, ANCHOR_B, block_b)

    if MARK_A not in gen or MARK_B not in gen:
        sys.exit("insertion failed: markers still absent after editing")
    io.open(GEN, "w", encoding="utf-8", newline="\n").write(gen)
    print("generator updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
