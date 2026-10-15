#!/bin/sh
# 50-resolutions.sh - round 6, R6-JOURNAL (mesh child on ZABZ-TECH), 2026-10-15.
#
# ============================================================================
# THIS SCRIPT RUNS NO `journal.py resolve`. NOT ONE.
#
# The brief's step 1 says: "If more than one tree holds journal entries that the
# other does not, DO NOT WRITE - produce the resolution list instead and say so."
#
# That condition is met with room to spare. Measured 2026-10-15 14:10-14:25Z:
#   5 trees, 4513 distinct entry ids in the union, 1643 present in all five,
#   436 confined to a single tree, and 363 ids whose BODY DIFFERS between trees.
#
# A resolve in any tree would attach a status to whichever entry that tree
# happens to hold under that id - not necessarily the entry the author meant.
# Example: D3034 is "the shop's money & customer tracking survives long-term"
# on yoga and the authority, and "Weitman SD copy route" on ZABZ-TECH.
#
# So this file is the REPRODUCE + PLAN script the task asks for in place of an
# executed log. Section A reproduces the finding. Section B is the plan, as
# commands, deliberately NOT executed. Section C is what a resolve would have
# looked like, and why none was issued.
# ============================================================================
#
# Usage:  sh 50-resolutions.sh          (read-only; writes only to /tmp)
# ============================================================================

set -u

WORK="${WORK:-/root/work/r6}"
SCRATCH="${SCRATCH:-/tmp/r6-repro}"

echo "=============================================================="
echo "A. REPRODUCE THE DIVERGENCE"
echo "=============================================================="
echo
echo "A1. The five trees, their branch, HEAD and entry count."
echo "    (run from any node that can reach them)"
echo
cat <<'EOF'
  yoga (manager, ZABZ-YOGA)   incident/deepseek-spof-20261015  dbb2c1c1  4204 entries  453 open pain
  authority (secratary-cloud) hk/182-wake-family-key            96f26c1b  4121 entries  475 open pain
  this node (ZABZ-TECH)       mesh/broker-host-cloud-default-...2d01206f  3960 entries  411 open pain
  zabz-tech-linux             main                              985f9378  3440 entries  344 open pain
  LakewooechsMini             master                            45676b7f  1646 entries  162 open pain

  Per-tree commands:
    cd ~/code/harness-config && git rev-parse --abbrev-ref HEAD && git log -1 --format=%h
    python3 journal/tools/journal.py status        # python on Windows
    python3 journal/tools/journal.py check
    find journal/entries -type f -name '*.md' | wc -l
    ssh secratary-cloud 'cd /root/code/harness-config && python3 journal/tools/journal.py status'
EOF
echo

echo "A2. Build one manifest per tree: '<entry-id> <TAB> <sha256>'."
echo "    The manifests used for this report are the ones in \$WORK."
echo
cat <<'EOF'
  # Linux / macOS node
  cd ~/code/harness-config
  find journal/entries -type f -name '*.md' -print0 \
    | xargs -0 sha256sum \
    | awk '{n=$2; sub(/.*\//,"",n); sub(/\.md$/,"",n); print n"\t"$1}' | sort > /tmp/r6-ids.tsv

  # Windows node (PowerShell), same file shape
  Set-Location "$env:USERPROFILE\code\harness-config"
  Get-ChildItem journal\entries -Recurse -File -Filter *.md -Force | ForEach-Object {
    "$([System.IO.Path]::GetFileNameWithoutExtension($_.Name))`t$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())"
  } | Sort-Object | Set-Content "$env:TEMP\r6-manifest.tsv"

  # fetch them all to one place
  scp -O yoga:/tmp/...           # NOTE: vanilla `scp` fails against ZABZ-YOGA ("Connection closed");
  scp -O zabz-yoga-ts:...        # use the legacy protocol flag `-O`, which works.
EOF
echo

echo "A3. Compare the five manifests."
echo "    python analyze2.py  (shipped alongside this script; reads the five .tsv manifests)"
echo "    Key output lines:"
echo
cat <<'EOF'
  === D. CONTENT DISAGREEMENT ===
    ids whose body has 1 distinct version(s): 4150
    ids whose body has 2 distinct version(s): 341
    ids whose body has 3 distinct version(s): 22
    TOTAL ids with a content collision: 363

  === B. PAIRWISE (onlyA / onlyB / shared-identical / shared-DIFFERENT) ===
    yoga vs authority    145   62   3960    99
    yoga vs zabz-tech    488  244   3462   254
    authority vs zabz-tech 423 262   3462   236
    (full matrix in 50-journal-hygiene.md section 1.1)
EOF
echo

echo "A4. Prove one collision by hand (the D3034 example)."
echo
cat <<'EOF'
  ssh secratary-cloud 'cd /root/code/harness-config && head -2 journal/entries/decisions/D3034.md'
  # --> <!-- e:decisions|D3034|2026-10-09|secratary|open -->
  #     **D3034 . 2026-10-09 . Decisions while making the shop's money & customer tracking survive long-term.**

  # on ZABZ-TECH, PowerShell:
  Get-Content C:\Users\ezabz\code\harness-config\journal\entries\decisions\D3034.md -TotalCount 2
  # --> <!-- e:decisions|D3034|2026-10-08|ZABZ-TECH|open -->
  #     **D3034 . 2026-10-08 . Weitman 2026-10-08: keyboard-only SD copy route; no fault assigned...**
EOF
echo

echo "A5. Show that journal.py check cannot see any of this."
echo "    All five trees report 0 error(s) while 363 ids disagree across them."
echo
cat <<'EOF'
  python3 journal/tools/journal.py check
  # -- 0 error(s), 267 warning(s), 83 info        (authority)
  # -- 0 error(s), 251 warning(s), 83 info        (ZABZ-TECH)
EOF
echo

echo "=============================================================="
echo "B. THE RESOLUTION PLAN - NOT EXECUTED"
echo "=============================================================="
echo
cat <<'EOF'
  R1. FREEZE WRITES in all five trees until R4. No `journal.py resolve`,
      no `journal.py append`, no hand edits to journal/entries/**.
      Reason: the three sets below move while they are being reconciled.

  R2. ADOPT THE AUTHORITY AS MERGE BASE.
      tree: secratary-cloud:/root/code/harness-config  (branch hk/182-wake-family-key)
      Why this one: `owner_decision_queue` lives on that box, and the status page
      already declares it "authoritative: owner_decision_queue on the authority";
      AGENTS.md section 5 makes secratary-cloud the sole writable host.
      NOT VERIFIED FROM THIS TASK: that /root/code/harness-config is the tree the
      authority's own sessions actually write to. Confirm before R3.

  R3. RECONCILE, IN THIS ORDER:
      3a. 363 COLLIDING IDS. Each needs one decision: keep one body, re-file the
          other under a fresh id from the allocator, then write an alias row.
          Machine-readable: collisions.json (363 ids).
          DO NOT UNION BLINDLY - `journal.py check` validates ids within a tree
          only, so it will not catch this.
      3b. 436 IDS CONFINED TO ONE TREE. Pure additions, safe to copy:
              yoga 127 | authority 62 | ZABZ-TECH 244 | linux-pc 0 | mac-mini 3
          The 244 on ZABZ-TECH are why this checkout cannot simply be reset to
          the authority: those entries exist nowhere else.
      3c. 3698 ids shared by at least two trees with IDENTICAL content:
          nothing to do, already converged.
      3d. zabz-tech-linux is a strict id-subset (onlyB = 0 against every other
          tree, 0 sole-holder ids). It needs a PULL, not a merge.

  R4. ONLY THEN resume the pain work from the brief's steps 2-3:
      read each open pain, test it, and `journal.py resolve` the provably dead.
      A resolve issued before R3 can attach a status to the wrong entry.

  R5. Fix the root cause after the merge, not before:
      the allocator mints per-tree ceilings. PROGRAM-v6.md section 1 row 5 says
      the allocator "no longer mints duplicates" (evidence: `journal.py next-id
      pain` -> P3865). That is true WITHIN a tree; duplicate ids were still
      minted ACROSS trees for ranges D3034-D3137, H3393-H3450, H3565-H3641,
      L3668-L3941, P2996-P3022 and more.
EOF
echo

echo "=============================================================="
echo "C. THE RESOLVE COMMANDS THAT WERE *NOT* RUN"
echo "=============================================================="
echo
cat <<'EOF'
  The brief's step 3 says to close dead pains with:

      python journal/tools/journal.py resolve <id> --status done --why "<evidence, one line>"

  ZERO of these were issued. The count is zero because of the R1 freeze, not
  because the list was short: on the manager's own tree 453 pain ids are open
  and every one of them is a candidate the brief wanted adjudicated.

  If the manager wants the mechanical form of what a batch would have looked
  like, it is exactly the line above, once per id, and the ids live in:

      ssh secratary-cloud 'cd /root/code/harness-config && python3 journal/tools/journal.py list --kind pain --status open'

  Print that, then check each id against the id-collision list in
  collisions.json BEFORE issuing a resolve. An id on that list cannot be
  resolved safely on both trees.

  A worked caution, using the D3034 example above:
      # SAFE on the authority (its D3034 is the shop-money decision)
      python3 journal/tools/journal.py resolve D3034 --status done --why "<evidence>"
      # the SAME command on ZABZ-TECH would close "Weitman SD copy route"
      # with evidence gathered about the shop-money decision. Wrong entry, no error.
EOF
echo
echo "=============================================================="
echo "END. No journal row was written by this script or by R6-JOURNAL."
echo "=============================================================="
