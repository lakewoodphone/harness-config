#!/usr/bin/env python3
"""Insert the reconcile call immediately before the company_tick tree walk.

Line-targeted on purpose: the same statement appears at 1705 (company_tick) and
2120 (a different caller), and a global replace would have patched both.
Guards verify the exact line and that it sits inside company_tick before writing.
"""
import io
import sys

PATH = "app/workforce.py"
TARGET_LINE = 1705  # 1-based

lines = io.open(PATH, encoding="utf-8").read().split("\n")

if any("reconcile_blueprint_tree" in ln for ln in lines):
    print("ALREADY PATCHED - no change")
    sys.exit(0)

idx = TARGET_LINE - 1
anchor = lines[idx]
if anchor.strip() != "agents = walk_agent_tree(root_id, max_depth=max_depth)":
    print("FATAL: line %d is not the expected anchor: %r" % (TARGET_LINE, anchor))
    sys.exit(10)

# Prove it is inside company_tick by scanning upward for the nearest top-level def.
def_line = None
for i in range(idx, -1, -1):
    if lines[i].startswith("def "):
        def_line = (i + 1, lines[i])
        break
if not def_line or "def company_tick(" not in def_line[1]:
    print("FATAL: line %d is not inside company_tick (nearest def: %r)" % (TARGET_LINE, def_line))
    sys.exit(11)

insert = """        # ── Blueprint/tree reconciliation (2026-10-26) ──
        # bootstrap_company() is SKIPPED on this host (.env sets
        # AUTOPILOT_SKIP_BOOTSTRAP), so a department added to DEPARTMENTS was
        # never parented into the tree and therefore never received a
        # productive tick. walk_agent_tree() below walks hierarchy.children,
        # so an orphan is invisible and its standing work orders stall until
        # lifecycle_sweep releases them. This repairs only the part the tick
        # depends on. It hires nothing and deletes nothing.
        try:
            from app.services.org_reconcile import reconcile_blueprint_tree

            _recon = reconcile_blueprint_tree(root_id)
            if _recon.get("repaired_count"):
                log.warning(
                    "company_tick: reconciled %d blueprint department(s) into the "
                    "agent tree: %s",
                    _recon["repaired_count"],
                    [r["agent_id"] for r in _recon.get("repaired", [])],
                )
            if _recon.get("missing"):
                log.warning(
                    "company_tick: blueprint departments with NO identity record "
                    "(not hired): %s",
                    _recon["missing"],
                )
        except Exception as _recon_exc:
            log.warning("company_tick: blueprint reconcile failed: %s", _recon_exc)
"""

lines.insert(idx, insert)
io.open(PATH + ".new", "w", encoding="utf-8", newline="\n").write("\n".join(lines))
print("anchor verified at line %d inside %s" % (TARGET_LINE, def_line[1]))
print("wrote %s.new" % PATH)
