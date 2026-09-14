#!/usr/bin/env python3
"""Add transcript-artifact cleanup to commsindex.py, verifying BEFORE writing.

Written as a real script (not shell-escaped) because the previous attempt escaped
`\\n` through two layers and corrupted the file -- it wrote before checking.
This one parses the result first and only then writes.
"""
import ast
import io
import os
import shutil
import time

P = "/home/zabz/.fsearch/commsindex.py"
s = io.open(P, encoding="utf-8").read()

if "clean_text" in s:
    print("already applied")
    raise SystemExit(0)

HELPER = (
    "\n\n"
    "# Markers the transcription pipeline injects into transcripts. They read as\n"
    "# content to FTS and as noise to a human, so they are removed before indexing.\n"
    "_ARTIFACT_MARKERS = (\n"
    "    \"whole_call_summary_fragment\",\n"
    "    \"action_item_v2\",\n"
    "    \"action_item\",\n"
    "    \"ai_csat_reboot_ineligible\",\n"
    "    \"whole_call_summary\",\n"
    "    \"call_summary_fragment\",\n"
    "    \"summary_fragment\",\n"
    "    \"reboot_ineligible\",\n"
    "    \"sentiment_analysis\",\n"
    "    \"next_steps_fragment\",\n"
    ")\n"
    "\n"
    "\n"
    "def clean_text(text):\n"
    "    \"\"\"Remove structural markers, preserving everything a person actually said.\n"
    "\n"
    "    Conservative by design: a line is dropped only when it IS a marker, and a\n"
    "    marker is stripped only when it TRAILS speech on the same line. Sentences\n"
    "    are never rewritten.\n"
    "    \"\"\"\n"
    "    if not text:\n"
    "        return text\n"
    "    out = []\n"
    "    for raw in text.split(NEWLINE):\n"
    "        line = raw.strip()\n"
    "        if not line:\n"
    "            continue\n"
    "        low = line.lower()\n"
    "        if any(low == m or low == m + \":\" for m in _ARTIFACT_MARKERS):\n"
    "            continue\n"
    "        for m in _ARTIFACT_MARKERS:\n"
    "            if low.endswith(m):\n"
    "                line = line[: -len(m)].rstrip(\" :.\")\n"
    "                low = line.lower()\n"
    "        if any(low == m or low == m + \":\" for m in _ARTIFACT_MARKERS):\n"
    "            continue\n"
    "        if line:\n"
    "            out.append(line)\n"
    "    return NEWLINE.join(out).strip()\n"
    "\n"
    "NEWLINE = \"\\n\"\n"
)

# NEWLINE must be defined before clean_text runs, and referencing it keeps this
# patch free of any escape sequence that a shell could mangle.
HELPER = HELPER.replace("NEWLINE = \"\\n\"\n", "")
HELPER = "NEWLINE = chr(10)\n" + HELPER

anchor = "\nEXTRACTORS = ("
assert s.count(anchor) == 1, f"anchor={s.count(anchor)}"
out = s.replace(anchor, HELPER + "\nEXTRACTORS = (", 1)

old = "                text = str(text).strip()[:100_000]"
new = ("                text = clean_text(str(text).strip())[:100_000]\n"
       "                if not text:\n"
       "                    continue")
assert out.count(old) == 1, f"text anchor={out.count(old)}"
out = out.replace(old, new, 1)

ast.parse(out)                      # verify FIRST
backup = P + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
shutil.copy2(P, backup)
io.open(P, "w", encoding="utf-8", newline="\n").write(out)   # then write
print("backup:", backup)
print("clean_text added and applied; file parses")
