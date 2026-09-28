#!/usr/bin/env bash
# verify-deploy.sh — prove that what is DEPLOYED is what you think you deployed.
#
# WHY THIS EXISTS
# This session lost more time to the gap between "I wrote it" and "it is running" than to any logic bug.
# Three separate failures, all in that gap:
#
#   * 2026-09-17 ~16:40  a 33 KB stale copy of `lpt-sync-to-production.py` was deployed over the live
#                        89,945-byte tool. It reported success and passed `ast.parse` — a 28 KB skeleton of
#                        a 90 KB program is valid Python. Found hours later by RUNNING it.
#   * same day            two rounds were spent "fixing" a guard in `tools/customer/audit.py` that had
#                        been written but NEVER DEPLOYED. Every logical change was applied to a file
#                        nobody was running, and "no observable effect" was misread as "wrong logic" —
#                        twice. Found by grepping the DEPLOYED copy: `grep -c orphan_shared_targets` -> 0.
#   * same day            the owner-attention digest was edited, committed and never deployed.
#
# The rule this mechanises: **verify the host, not your intent.** A deploy command that prints nothing,
# or that produces no error, is not evidence — and a file that parses is not a file that is running.
#
# USAGE
#   verify-deploy.sh                      # check every entry in the manifest
#   verify-deploy.sh --local-hub DIR      # manifest entries with a `hub:` path are compared against DIR
#   verify-deploy.sh --quiet              # only print failures
#
# EXIT: 0 everything matches · 1 a marker is missing or a file is absent · 2 could not measure
#
# A MANIFEST ENTRY IS:  <host>|<absolute path>|<required marker>|<label>
# The marker is the cheapest possible proof that a specific change reached the host — an identifier that
# exists ONLY in the version you meant to deploy. Generic markers ("import json") prove nothing.
set -u

QUIET=0
HUB_LOCAL=""
for arg in "$@"; do
  case "$arg" in
    --quiet) QUIET=1 ;;
    --local-hub=*) HUB_LOCAL="${arg#--local-hub=}" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# ── THE MANIFEST ──────────────────────────────────────────────────────────────────────────────────
# One line per load-bearing deployed artefact, with the marker that proves WHICH VERSION is there.
# Keep this list to files where a stale copy would silently change behaviour. A manifest that lists
# everything is a manifest nobody maintains.
#
# `local` means "the host this script is running on" — the normal case, because the authority is where
# these files live and where this script is run. A `local` entry is checked without SSH, which also
# removes the reason the first version failed: it tried to ssh to `secratary-ts` FROM secratary, where
# that alias does not resolve to loopback.
MANIFEST="$(cat <<'EOF'
local|/home/zabz/repos/lpt-hub/tools/customer/audit.py|orphan_shared_targets|four-surface verifier (collision guard)
local|/home/zabz/repos/lpt-hub/tools/customer/repair.py|set-source-path|repair tool (F04 sourcePath writer)
local|/home/zabz/repos/lpt-hub/tools/customer/dialpad.py|KNOWN_SHOP_NUMBERS|comms surface
local|/home/zabz/repos/lpt-hub/tools/case-index/lptcase.py|corpus_integrity_warnings|case finder (corpus warnings)
local|/home/zabz/personal-secretary-mvp/scripts/server/owner-attention-digest.sh|carry a recorded hold reason|owner digest (held/actionable line)
local|/home/zabz/personal-secretary-mvp/scripts/server/owner-attention-digest.sh|nothing would be created|owner digest (corpus line, wording corrected)
local|/home/zabz/personal-secretary-mvp/scripts/ai-gateway-health.py|failing-historical|gateway detector (recent-vs-aggregate calibration)
local|/home/zabz/personal-secretary-mvp/scripts/ai-gateway-health.py|configured-but-silent|gateway detector (silent-tier check)
local|/home/zabz/personal-secretary-mvp/scripts/server/owner-attention-digest.sh|AI gateway:|owner digest (gateway line)
local|/home/zabz/harness-config/scripts/owner-attention-digest.sh|nothing would be created|harness-config COPY of the digest must match what is live
local|/home/zabz/bin/lpt-recon-check.sh|push_held_not_drift|reconciliation reporter (held count)
local|/home/zabz/personal-secretary-mvp/scripts/lpt-sync-to-production.py|_GUARD_REFUSING_KINDS|production sync tool (pre-create guard)
local|/home/zabz/personal-secretary-mvp/scripts/lpt-sync-to-production.py|sync_hold|production sync tool (hold gate)
local|/home/zabz/personal-secretary-mvp/app/services/lpt_hub_sync.py|check_sync_tool_sanity|lpt-hub resolver + tool sanity
local|/home/zabz/personal-secretary-mvp/app/config.py|CONTENT_SANDBOX_ATTR|config (sandbox constant)
local|/home/zabz/personal-secretary-mvp/app/services/daily_reconciliation.py|dry_run=not _linker_may_write|reconciler (linker write gate)
EOF
)"

fails=0
unmeasured=0
checked=0

if [ "$QUIET" -eq 0 ]; then
  echo "=== DEPLOY VERIFICATION ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ==="
  echo "A missing marker means the host is running a DIFFERENT version of that file."
  echo
fi

while IFS='|' read -r host path marker label; do
  [ -z "${host:-}" ] && continue
  checked=$((checked + 1))
  # ONE probe per entry, asking for the size, the mtime and whether the marker is present.
  # `local` is checked on this filesystem; anything else over ssh. A `local` entry distinguishes "the
  # host this runs on" from a hostname, which is precisely what the first version got wrong.
  PROBE_CMD="if [ -f '$path' ]; then printf '%s|%s|%s' \"\$(wc -c < '$path')\" \"\$(date -u -r '$path' +%Y-%m-%dT%H:%MZ)\" \"\$(grep -c -- '$marker' '$path' || true)\"; else echo 'MISSING||0'; fi"
  if [ "$host" = "local" ]; then
    probe=$(bash -c "$PROBE_CMD" 2>/dev/null) || probe=""
  else
    probe=$(ssh -o ConnectTimeout=20 -o BatchMode=yes "$host" "$PROBE_CMD" 2>/dev/null) || probe=""
  fi
  if [ -z "$probe" ]; then
    echo "  🔴 COULD NOT MEASURE  $label  ($path on ${host})"
    unmeasured=$((unmeasured + 1))
    continue
  fi
  size=$(printf '%s' "$probe" | cut -d'|' -f1)
  when=$(printf '%s' "$probe" | cut -d'|' -f2)
  hits=$(printf '%s' "$probe" | cut -d'|' -f3)
  if [ "$size" = "MISSING" ]; then
    echo "  🔴 ABSENT            $label  ($path)"
    fails=$((fails + 1))
  elif [ "${hits:-0}" = "0" ]; then
    echo "  🔴 MARKER MISSING    $label  ($path is $size B, $when) — this is a DIFFERENT version"
    fails=$((fails + 1))
  else
    [ "$QUIET" -eq 0 ] && echo "  ✅ $label  ($size B, $when, marker x$hits)"
  fi
done <<< "$MANIFEST"

# ── REPO COPY vs LIVE COPY: THE CHECK A MARKER CANNOT MAKE ──────────────────────────────────────
# The manifest above proves WHICH VERSION is deployed. It cannot prove two copies of the SAME file are
# identical, because a marker appears in BOTH when one is merely older. MEASURED 2026-09-17: the
# harness-config copy of the digest was 21,478 B against the live 22,815 B — genuinely stale — and the
# marker check PASSED. **An entry labelled "must match what is live" that cannot detect a difference is
# worse than no entry, because it reports success.** So the pair is compared by sha256 instead.
#
# PAIRS are `left|right` lines, one file per line, in a deliberately separate list so the manifest format
# stays single-purpose.
PAIRS="$(cat <<'EOF'
/home/zabz/personal-secretary-mvp/scripts/server/owner-attention-digest.sh|/home/zabz/harness-config/scripts/owner-attention-digest.sh
EOF
)"
if [ "$QUIET" -eq 0 ]; then
  echo
  echo "=== PAIRED COPIES (byte-for-byte) ==="
fi
while IFS='|' read -r left right; do
  [ -z "${left:-}" ] && continue
  checked=$((checked + 1))
  lsum=$(sha256sum "$left" 2>/dev/null | cut -d' ' -f1)
  rsum=$(sha256sum "$right" 2>/dev/null | cut -d' ' -f1)
  if [ -z "$lsum" ] || [ -z "$rsum" ]; then
    echo "  🔴 CANNOT COMPARE     ${left##*/} vs ${right##*/} (one is unreadable)"
    unmeasured=$((unmeasured + 1))
  elif [ "$lsum" = "$rsum" ]; then
    [ "$QUIET" -eq 0 ] && echo "  ✅ ${left##*/} == ${right##*/}  (${lsum:0:12})"
  else
    echo "  🔴 COPIES DIFFER     ${left##*/} (${lsum:0:12}) != ${right##*/} (${rsum:0:12})"
    echo "                       the repo copy is NOT the file that runs — the gap this script exists for"
    fails=$((fails + 1))
  fi
done <<< "$PAIRS"

echo
if [ "$unmeasured" -gt 0 ]; then
  echo "🔴 $fails failure(s), $unmeasured UNMEASURED of $checked — an unmeasured deploy is not a verified one"
  exit 2
elif [ "$fails" -gt 0 ]; then
  echo "🔴 $fails of $checked artefact(s) are the WRONG VERSION on the host"
  exit 1
fi
echo "✅ all $checked deployed artefact(s) carry their expected marker"
exit 0
