#!/usr/bin/env bash
# =============================================================================
# prove-configset.sh -- exercise lib-configset.sh in a SANDBOX.
#
# Nothing here touches /home/zabz/.dsh. The whole test runs against a throwaway
# home under /home/zabz/dsh-cutover/scratch, chosen because DSH_CUTOVER_HOME
# overrides every path the library derives.
#
# The test reproduces the exact 2026-10-05 failure shape: a version-coupled config
# migration applied, verification failing, and a rollback that must put the config
# back as well as the engine.
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UTC="$(date -u +%Y%m%dT%H%M%SZ)"
SB="/home/zabz/dsh-cutover/scratch/cfgset-test-$UTC"
H="$SB/home/.dsh"

pass=0; fail=0
ok(){ printf '  PASS  %s\n' "$*"; pass=$((pass+1)); }
no(){ printf '  FAIL  %s\n' "$*"; fail=$((fail+1)); }

echo "sandbox: $SB"
mkdir -p "$H/profiles/web" "$H/profiles/headless" "$H/profiles/headless-resume" \
         "$H/profiles/node_modules/@deepseek-ai" "$H/.agent-presets/zabz" "$H/sessions/keep"

# --- a miniature of the real version-coupled set -----------------------------
cat > "$H/settings.yaml" <<'EOF'
agent-presets:
  default: zabz
spend-guard:
  warnUsd: 35
EOF
printf 'profile web v1\n'      > "$H/profiles/web/cordis.patch.yml"
printf 'profile headless v1\n' > "$H/profiles/headless/cordis.patch.yml"
printf 'profile resume v1\n'   > "$H/profiles/headless-resume/cordis.patch.yml"
printf '{"name":"p-web"}\n'    > "$H/profiles/web/package.json"
printf 'preset zabz v1\n'      > "$H/.agent-presets/zabz/agent.cordis.yml"
printf 'order: 12\n'           > "$H/.agent-presets/zabz/preset.yml"
ln -sf /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh "$H/profiles/node_modules/@deepseek-ai/dsh"
# data that must NEVER be touched by this tool
printf 'a live session\n' > "$H/sessions/keep/session.v3.jsonl.zstd"

export DSH_CUTOVER_HOME="$H"
# shellcheck source=/dev/null
source "$HERE/lib-configset.sh"

echo
echo "=== 1. the set is what we think it is ==="
configset_paths | sed 's#^#    #'
n=$(configset_paths | wc -l)
echo "    ($n paths -- packages.json x2, patches x2, settings, preset, node_modules)"
[ "$n" -eq 8 ] && ok "8 paths, and sessions/ is NOT among them" || no "expected 8 paths, got $n"
configset_paths | grep -q "sessions" && no "sessions leaked into the version-coupled set" || ok "sessions excluded"

echo
echo "=== 2. snapshot ==="
configset_snapshot "$SB/before"
cat "$SB/before/manifest.tsv" | sed 's#^#    #'
[ -f "$SB/before/manifest.tsv" ] && ok "manifest written" || no "no manifest"
[ -f "$SB/before/settings.yaml" ] && ok "settings copied" || no "settings not copied"
[ -d "$SB/before/profiles_node_modules" ] && ok "anchor farm copied as a directory" || no "anchor not copied"

echo
echo "=== 3. verify on an unmodified tree must PASS ==="
configset_verify "$SB/before" >/dev/null 2>&1 && ok "verify clean == 0" || no "verify failed on a clean tree"

echo
echo "=== 4. simulate the 0.2.0 config migration (what broke on 2026-10-05) ==="
printf 'profile web v2 (0.2.0)\n'      > "$H/profiles/web/cordis.patch.yml"
printf 'preset zabz v2 workflow-ptc\n' > "$H/.agent-presets/zabz/agent.cordis.yml"
cat > "$H/settings.yaml" <<'EOF'
agent-presets:
  default: standard
EOF
ln -sfn /home/zabz/dsh-install/0.2.0-rc.2/node_modules/@deepseek-ai/dsh "$H/profiles/node_modules/@deepseek-ai/dsh"
echo "    migrated 3 files and repointed the anchor"

echo
echo "=== 5. verify must now FAIL and name every changed path ==="
out="$(configset_verify "$SB/before" 2>&1)"; rc=$?
echo "$out" | sed 's#^#    #'
[ "$rc" -ne 0 ] && ok "verify reports a difference (rc=$rc)" || no "verify said clean after a migration"
for f in "profiles/web/cordis.patch.yml" ".agent-presets/zabz/agent.cordis.yml" "settings.yaml"; do
  echo "$out" | grep -q "$f" && ok "named $f" || no "did not name $f"
done

echo
echo "=== 6. restore ==="
configset_restore "$SB/before" "$SB/aside" | sed 's#^#    #'

echo
echo "=== 7. verify must now PASS again (this is the whole point) ==="
configset_verify "$SB/before" >/dev/null 2>&1 && ok "the config set matches the snapshot again" || no "still differs after restore"
grep -q "workflow-ptc" "$H/.agent-presets/zabz/agent.cordis.yml" && no "the migrated preset survived" || ok "preset restored to v1"
grep -q "default: zabz" "$H/settings.yaml" && ok "settings restored" || no "settings not restored"

echo
echo "=== 8. the anchor symlink is back where it was ==="
tgt="$(readlink "$H/profiles/node_modules/@deepseek-ai/dsh")"
echo "    -> $tgt"
case "$tgt" in *dsh-engine*) ok "anchor points at the old prefix again";; *) no "anchor still points elsewhere: $tgt";; esac

echo
echo "=== 9. live DATA was never touched, and the restore was itself reversible ==="
[ -f "$H/sessions/keep/session.v3.jsonl.zstd" ] && ok "session data untouched" || no "session data disturbed"
[ -e "$SB/aside/profiles/web/cordis.patch.yml" ] && ok "the pre-restore version was MOVED aside, not deleted" || no "no displaced copy kept"
grep -q "v2 (0.2.0)" "$SB/aside/profiles/web/cordis.patch.yml" && ok "the displaced copy holds the migrated bytes" || no "displaced copy is wrong"

echo
echo "=== 10. snapshot is idempotent and never deletes ==="
configset_snapshot "$SB/before" >/dev/null 2>&1
[ -d "$SB/before/.displaced" ] && ok "a second snapshot displaced the old copies instead of deleting them" || ok "second snapshot had nothing to displace"
configset_verify "$SB/before" >/dev/null 2>&1 && ok "still consistent after a re-snapshot" || no "re-snapshot broke consistency"

echo
printf 'RESULT: %s passed, %s failed   (sandbox: %s)\n' "$pass" "$fail" "$SB"
[ "$fail" -eq 0 ] || exit 1
