#!/usr/bin/env bash
# =============================================================================
# lib-configset.sh -- the version-coupled config set, as a snapshot/restore pair.
#
# WHY THIS EXISTS
# On 2026-10-05 the first cutover of secratary's DSH 0.2.0-rc.2 upgrade failed its
# verification and auto-rolled-back. rollback.sh restored the UNIT and the LINK
# exactly as designed -- and left the 0.2.0 CONFIG in place, because the config had
# been applied by a different script that rollback.sh knew nothing about. The
# machine came to rest on 0.1.5-rc.1 running 0.2.0 config, and the owner's phone
# engine died on it:
#     TypeError: this.ctx.agentPresets.register is not a function
#        at [cordis.init] .../dsh-agent-preset/lib/index.js:25:37
#        at file:///home/zabz/.dsh/profiles/web/#preset-zabz
#
# An engine and a version-coupled config are ONE artefact. "Roll back the engine"
# is half a rollback, and the half left behind is the half that cannot boot.
#
# THE RULE THIS ENFORCES
# Any process that changes the engine version snapshots this set BEFORE the first
# change and leaves the snapshot beside the engine's own backups. Any rollback
# restores the set whether or not it knows what changed it. Discipline is not
# required: the set is defined here, not by the caller.
#
# USAGE
#   source lib-configset.sh
#   configset_snapshot "$BK/config-before"          # before the first change
#   configset_restore  "$BK/config-before" "$ASIDE" # in a rollback
#   configset_verify   "$BK/config-before"          # assert the live tree matches
#
# Env: DSH_CUTOVER_HOME overrides the home under test (default /home/zabz/.dsh).
#      This exists so the whole thing can be exercised in a sandbox; every path
#      below is derived from it and from nothing else.
# =============================================================================

CONFIGSET_HOME_DEFAULT=/home/zabz/.dsh

configset_home(){ printf '%s' "${DSH_CUTOVER_HOME:-$CONFIGSET_HOME_DEFAULT}"; }

# The set. Deliberately explicit and narrow: these are the paths that carry the
# engine version with them. Sessions, storages, credentials, logs and the governor
# are NOT version-coupled and must never be snapshotted or restored here -- a
# restore that rolls back live data is a worse failure than the one being fixed.
configset_paths(){
  local H; H="$(configset_home)"
  local p
  for p in \
    "$H/settings.yaml" \
    "$H/profiles"/*/cordis.patch.yml \
    "$H/profiles"/*/cordis.yml \
    "$H/profiles"/*/package.json \
    "$H/.agent-presets"/*/agent.cordis.yml \
    "$H/.agent-presets"/*/preset.yml \
    "$H/profiles/node_modules" ; do
    [ -e "$p" ] && printf '%s\n' "$p"
  done
  return 0
}

configset_key(){ # <abs path> -> a flat filename that survives a single cp
  local H; H="$(configset_home)"
  printf '%s' "$1" | sed "s#^$H/##" | tr '/' '_'
}

# Snapshot the set into a directory. Writes manifest.tsv beside the copies.
#   columns: <absolute path> <sha256|DIR> <backup filename>
configset_snapshot(){
  local dest="$1"
  local H; H="$(configset_home)"
  [ -n "$dest" ] || { echo "configset_snapshot: need a destination" >&2; return 2; }
  mkdir -p "$dest" || return 3
  : > "$dest/manifest.tsv"
  local p key
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    key="$(configset_key "$p")"
    # Never delete. If the destination already holds something, displace it.
    if [ -e "$dest/$key" ] || [ -L "$dest/$key" ]; then
      mkdir -p "$dest/.displaced" || return 3
      mv "$dest/$key" "$dest/.displaced/$key.$(date -u +%Y%m%dT%H%M%SZ)" || return 3
    fi
    if [ -L "$p" ]; then
      cp -a "$p" "$dest/$key" || { echo "configset: could not copy symlink $p" >&2; return 3; }
      printf '%s\tLINK\t%s\n' "$p" "$key" >> "$dest/manifest.tsv"
    elif [ -d "$p" ]; then
      cp -a "$p" "$dest/$key" || { echo "configset: could not copy $p" >&2; return 3; }
      printf '%s\tDIR\t%s\n' "$p" "$key" >> "$dest/manifest.tsv"
    elif [ -f "$p" ]; then
      cp -a "$p" "$dest/$key" || { echo "configset: could not copy $p" >&2; return 3; }
      printf '%s\t%s\t%s\n' "$p" "$(sha256sum "$p" | awk '{print $1}')" "$key" >> "$dest/manifest.tsv"
    fi
  done < <(configset_paths)
  printf 'configset: snapshotted %s path(s) into %s\n' "$(wc -l < "$dest/manifest.tsv" | tr -d ' ')" "$dest"
}

# Restore every path in the manifest. The current version is MOVED aside, never
# deleted, so a restore is itself reversible.
configset_restore(){
  local src="$1" aside="${2:-}"
  local H; H="$(configset_home)"
  [ -f "$src/manifest.tsv" ] || { echo "configset_restore: no manifest at $src/manifest.tsv" >&2; return 4; }
  [ -n "$aside" ] || aside="$src/moved-aside"
  mkdir -p "$aside" || return 3
  local path kind key rel
  local n=0
  while IFS=$'\t' read -r path kind key; do
    [ -n "${path:-}" ] || continue
    [ -e "$src/$key" ] || { echo "configset: backup file missing for $path -- SKIPPING, not guessed" >&2; continue; }
    rel="$(printf '%s' "$path" | sed "s#^$H/##")"
    if [ -e "$path" ]; then
      mkdir -p "$aside/$(dirname "$rel")" 2>/dev/null || true
      mv "$path" "$aside/$rel" || { echo "configset: could not displace $path" >&2; return 3; }
    fi
    mkdir -p "$(dirname "$path")" 2>/dev/null || true
    cp -a "$src/$key" "$path" || { echo "configset: could not restore $path" >&2; return 3; }
    n=$((n+1))
  done < "$src/manifest.tsv"
  printf 'configset: restored %s path(s) from %s (displaced copies in %s)\n' "$n" "$src" "$aside"
}

# Assert the live tree matches the snapshot. Prints one line per mismatch.
# Exit 0 only when nothing differs.
configset_verify(){
  local src="$1"
  [ -f "$src/manifest.tsv" ] || { echo "configset_verify: no manifest at $src" >&2; return 4; }
  local path kind key want got bad=0
  while IFS=$'\t' read -r path kind key; do
    [ -n "${path:-}" ] || continue
    if [ ! -e "$path" ]; then printf 'MISSING  %s\n' "$path"; bad=$((bad+1)); continue; fi
    if [ "$kind" = "DIR" ]; then
      want="$(find "$src/$key" -maxdepth 2 -type l 2>/dev/null | wc -l)"
      got="$(find "$path"    -maxdepth 2 -type l 2>/dev/null | wc -l)"
      [ "$want" = "$got" ] || { printf 'DIFFERS  %s (links %s -> %s)\n' "$path" "$want" "$got"; bad=$((bad+1)); }
    else
      want="$kind"
      got="$(sha256sum "$path" 2>/dev/null | awk '{print $1}')"
      [ "$want" = "$got" ] || { printf 'DIFFERS  %s\n' "$path"; bad=$((bad+1)); }
    fi
  done < "$src/manifest.tsv"
  [ "$bad" -eq 0 ] && { echo "configset: live tree matches the snapshot"; return 0; }
  printf 'configset: %s path(s) differ from the snapshot\n' "$bad"
  return 1
}
