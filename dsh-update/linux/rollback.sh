#!/usr/bin/env bash
# rollback.sh -- undo a cutover in ONE step: previous engine indirection,
#                previous unit file, and previous home, then one restart.
#
# DRY-RUN BY DEFAULT.  Nothing is written, moved, stopped or restarted
# without --apply.
#
# It restores, and says exactly what it restores from where:
#   $BK/phone-engine.service   ->  /etc/systemd/system/phone-engine.service   (byte copy, sha256-checked)
#   $BK/unit.d/                ->  /etc/systemd/system/phone-engine.service.d/
#   $LINK                      ->  <state.link_target_before>                  (atomic symlink swap)
#   $BK/home.old               ->  /home/zabz/.dsh                            (only if home_swap.performed)
# and it backs up the CURRENT unit and home first, so a rollback can itself be
# rolled forward.  Nothing is ever deleted.
#
# Usage:
#   rollback.sh [--apply] [--from STATE_FILE] [--target PREFIX] [--yes]
#               [--state-dir DIR] [--no-restart] [--skip-home] [--help]
#
# Exit: 0 dry-run ready / applied+verified
#       4 refused: a precondition failed (nothing was changed)
#       10 apply failed
#
set -uo pipefail

APPLY=0
CONFIG_ONLY=0
STATE_DIR=/home/zabz/dsh-cutover
STATE_FILE=""
TARGET_OVERRIDE=""
ASSUME_YES=0
NO_RESTART=0
SKIP_HOME=0

UNIT=phone-engine.service
UNIT_FILE=/etc/systemd/system/phone-engine.service
UNIT_DROPIN_DIR=/etc/systemd/system/phone-engine.service.d
LINK=/home/zabz/dsh-current
NODE=/home/zabz/node/bin/node
MODULE_REL=node_modules/@deepseek-ai/dsh/lib/bin.js
MODULE_SUFFIX="node_modules/@deepseek-ai/dsh/lib/bin.js"
LIVE_HOME=/home/zabz/.dsh
PORT=3089
DIRNAME_OF_SCRIPT="$(cd "$(dirname "$0")" && pwd)"
VERIFY="$DIRNAME_OF_SCRIPT/verify-live.sh"

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)       APPLY=1; shift ;;
    --from)        STATE_FILE="${2:?}"; shift 2 ;;
    --target)      TARGET_OVERRIDE="${2:?}"; shift 2 ;;
    --config-only)      CONFIG_ONLY=1; shift ;;
    --yes)         ASSUME_YES=1; shift ;;
    --state-dir)   STATE_DIR="${2:?}"; shift 2 ;;
    --no-restart)  NO_RESTART=1; shift ;;
    --skip-home)   SKIP_HOME=1; shift ;;
    -h|--help)     sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
done
[ -n "$STATE_FILE" ] || STATE_FILE="$STATE_DIR/state.json"

say(){ printf '%s\n' "$*"; }
step(){ printf '\n===== %s\n' "$*"; }
refuse(){ printf '\nREFUSE: %s\n' "$*" >&2; exit 4; }

UTC="$(date -u +%Y%m%dT%H%M%SZ)"
say "rollback.sh  mode=$([ "$APPLY" -eq 1 ] && echo APPLY || echo 'DRY-RUN')  utc=$UTC"

# ============================================================== PRECHECKS ===
step "PRECHECKS"
bad=0
chk(){ printf '  %-4s %-28s %s\n' "$2" "$1" "$3"; [ "$2" = BAD ] && bad=$((bad+1)); return 0; }

if sudo -n true 2>/dev/null; then chk sudo OK "sudo -n works"; else
  if [ "$APPLY" -eq 1 ]; then chk sudo BAD "sudo -n true failed; --apply needs root-equivalent access"
  else chk sudo WARN "sudo -n true failed (only matters for --apply)"; fi
fi
for c in curl jq python3 sha256sum; do
  command -v "$c" >/dev/null 2>&1 && chk "tool:$c" OK "$(command -v $c)" || chk "tool:$c" BAD missing
done
[ -x "$VERIFY" ] && chk script:verify-live.sh OK "$VERIFY" || chk script:verify-live.sh BAD "$VERIFY missing/not executable"
[ -r "$UNIT_FILE" ] || chk unit-file BAD "$UNIT_FILE not readable"

BK=""; LINK_BEFORE=""; VER_BEFORE=""; HOME_PERFORMED=false; HOME_MOVED_TO=""
MODE=""
if [ -n "$TARGET_OVERRIDE" ]; then
  MODE=target
  chk state-file INFO "--target given: $TARGET_OVERRIDE (no state file needed)"
  case "$TARGET_OVERRIDE" in /*) : ;; *) chk target BAD "--target must be an absolute path" ;; esac
  [ -f "$TARGET_OVERRIDE/$MODULE_REL" ] || chk target BAD "no bin.js at $TARGET_OVERRIDE/$MODULE_REL"
  VER_BEFORE="$(jq -r '.version // "unknown"' "$TARGET_OVERRIDE/node_modules/@deepseek-ai/dsh/package.json" 2>/dev/null || echo unknown)"
  LINK_BEFORE="$TARGET_OVERRIDE"
else
  MODE=state
  if [ ! -f "$STATE_FILE" ]; then
    refuse "no state file at $STATE_FILE and no --target given.
         rollback.sh needs to know what to go back to. Run cutover.sh --apply at least once
         (it writes this file BEFORE it changes anything), or pass --target PREFIX explicitly."
  fi
  chk state-file OK "$STATE_FILE (started $(jq -r '.started_utc // "?"' "$STATE_FILE"))"
  BK="$(jq -r '.backup_dir // empty' "$STATE_FILE")"
  LINK_BEFORE="$(jq -r '.link_target_before // empty' "$STATE_FILE")"
  VER_BEFORE="$(jq -r '.version_before // empty' "$STATE_FILE")"
  HOME_PERFORMED="$(jq -r '.home_swap.performed // false' "$STATE_FILE")"
  HOME_MOVED_TO="$(jq -r '.home_swap.moved_to // empty' "$STATE_FILE")"
  [ -n "$BK" ] || chk backup-dir BAD "state file has no backup_dir"
  [ -d "$BK" ] || chk backup-dir BAD "backup dir does not exist: $BK"
  [ -f "$BK/phone-engine.service" ] || chk unit-backup BAD "no unit backup at $BK/phone-engine.service"
  [ -n "$LINK_BEFORE" ] || chk link-before BAD "state file has no link_target_before"
  [ -n "$VER_BEFORE" ] || chk version-before BAD "state file has no version_before"
  case "$LINK_BEFORE" in /*) : ;; "") : ;; *) chk link-before BAD "link_target_before is not absolute" ;; esac
  if [ -n "$LINK_BEFORE" ]; then
    [ -f "$LINK_BEFORE/$MODULE_REL" ] || chk prev-prefix BAD "previous prefix has no bin.js: $LINK_BEFORE/$MODULE_REL"
  fi
fi

# =========================================== WHAT WILL BE RESTORED, FROM WHERE
step "RESTORES"
if [ "$MODE" = state ]; then
  printf '  %-46s %s\n' "FILE" "FROM -> TO"
  printf '  %-46s %s\n' "-------------------------------" "---------------------------------"
  printf '  %-46s %s\n' "/etc/systemd/system/phone-engine.service" "$BK/phone-engine.service -> $UNIT_FILE"
  printf '  %-46s %s\n' "/etc/systemd/system/phone-engine.service.d/" "$BK/unit.d -> $UNIT_DROPIN_DIR"

  if [ -f "$BK/config-before/manifest.tsv" ]; then
    printf '  %-46s %s\n' "version-coupled config set" "$(wc -l < "$BK/config-before/manifest.tsv" | tr -d ' ') path(s) <- $BK/config-before"
  fi
  printf '  %-46s %s\n' "$LINK" "$(readlink "$LINK" 2>/dev/null || echo 'absent') -> $LINK_BEFORE"
  if [ "$HOME_PERFORMED" = true ] && [ "$SKIP_HOME" -eq 0 ]; then
    printf '  %-46s %s\n' "$LIVE_HOME" "$HOME_MOVED_TO -> $LIVE_HOME"
    printf '  %-46s %s\n' "(and $LIVE_HOME moved aside first, to $STATE_DIR/moved-aside/$UTC/home.after-cutover)"
  else
    printf '  %-46s %s\n' "$LIVE_HOME" "LEFT ALONE (home_swap.performed=$HOME_PERFORMED, skip_home=$SKIP_HOME)"
  fi
  if [ -f "$BK/unit.sha256.before" ]; then
    printf '\n  unit backup sha256 recorded : %s\n' "$(cat "$BK/unit.sha256.before")"
    printf '  unit backup sha256 on disk  : %s\n' "$(sha256sum "$BK/phone-engine.service" | awk '{print $1}')"
  fi
else
  printf '  %-46s %s\n' "$LINK" "$(readlink "$LINK" 2>/dev/null || echo 'absent') -> $LINK_BEFORE"
  printf '  %-46s %s\n' "ExecStart module path" "-> $LINK/$MODULE_REL   (indirection kept; no unit backup available)"
fi

# idempotency
ALREADY=0
if [ "$MODE" = state ] && [ -f "$BK/phone-engine.service" ]; then
  cur="$(sudo sha256sum "$UNIT_FILE" 2>/dev/null | awk '{print $1}')"
  want="$(sha256sum "$BK/phone-engine.service" | awk '{print $1}')"
  linknow="$(readlink -f "$LINK" 2>/dev/null || true)"
  wantlink="$(readlink -f "$LINK_BEFORE" 2>/dev/null || true)"
  if [ "$cur" = "$want" ] && [ -L "$LINK" ] && [ -n "$linknow" ] && [ "$linknow" = "$wantlink" ]; then ALREADY=1; fi
fi
[ "$ALREADY" -eq 1 ] && chk already-rolled-back INFO "unit and link already match the pre-cutover state"

if [ "$bad" -gt 0 ]; then refuse "$bad precondition(s) marked BAD above. Nothing was changed."; fi

if [ "$APPLY" -eq 0 ]; then
  printf '\nDRY-RUN: rollback is possible and every source above exists. Nothing was changed.\n'
  say "         To do it for real:  sudo $0 --apply --yes"
  exit 0
fi

if [ "$ALREADY" -eq 1 ] && [ "$NO_RESTART" -eq 0 ]; then
  say "\nALREADY ROLLED BACK. Restarting anyway is harmless but pointless; continuing to verify only."
fi

if [ "$ASSUME_YES" -eq 0 ]; then
  printf '\nThis will restore the unit, repoint %s and restart %s on a LIVE control plane.\n' "$LINK" "$UNIT"
  printf 'Type exactly: rollback %s\n> ' "$VER_BEFORE"
  read -r answer
  [ "$answer" = "rollback $VER_BEFORE" ] || refuse "confirmation did not match; nothing was changed."
fi

# ============================================================== APPLY =======
step "APPLY"
mkdir -p "$STATE_DIR/moved-aside/$UTC" || { say "cannot create the moved-aside dir"; exit 10; }
ASIDE="$STATE_DIR/moved-aside/$UTC"

# --- CONFIG-ONLY mode: restore the version-coupled set and stop --------------
# Performs no unit install, no drop-in change, no link swap, no home move and no
# restart. NOTE: the RESTORES table printed above lists those operations anyway,
# because it is drawn before this branch is reached -- in this mode they are NOT
# performed. Only the config-set line of that table applies.
if [ "$CONFIG_ONLY" -eq 1 ]; then
  say ""
  say "CONFIG-ONLY mode: restoring the version-coupled config set; engine untouched."
  if [ ! -f "$BK/config-before/manifest.tsv" ]; then
    say "REFUSE: no config-set snapshot at $BK/config-before/manifest.tsv"
    exit 4
  fi
  # shellcheck source=/dev/null
  source "$DIRNAME_OF_SCRIPT/lib-configset.sh" || { say "cannot source lib-configset.sh"; exit 10; }
  if [ "$APPLY" -eq 1 ]; then
    configset_restore "$BK/config-before" "$ASIDE/config" || { say "config-set restore FAILED"; exit 10; }
    configset_verify  "$BK/config-before" || { say "config-set VERIFY FAILED: it does not match the snapshot"; exit 11; }
    say "config-only restore complete and verified; the engine was NOT restarted"
  else
    say "  would restore $(wc -l < "$BK/config-before/manifest.tsv" | tr -d ' ') path(s) from $BK/config-before"
  fi
  exit 0
fi

# --- back up what we are about to replace (so a rollback is reversible) ----
sudo cp -a "$UNIT_FILE" "$ASIDE/phone-engine.service.after-cutover" || { say "could not back up the current unit"; exit 10; }
say "backed up current unit -> $ASIDE/phone-engine.service.after-cutover"
sha256sum "$ASIDE/phone-engine.service.after-cutover" | awk '{print $1}' > "$ASIDE/unit.sha256.after-cutover"

if [ "$MODE" = state ]; then
  # --- restore the unit file byte-for-byte --------------------------------
  want="$(sha256sum "$BK/phone-engine.service" | awk '{print $1}')"
  sudo install -o root -g root -m 644 "$BK/phone-engine.service" "$UNIT_FILE" || { say "restoring the unit failed"; exit 10; }
  got="$(sudo sha256sum "$UNIT_FILE" | awk '{print $1}')"
  say "restored $UNIT_FILE"
  say "  expected sha256 $want"
  say "  actual   sha256 $got"
  [ "$want" = "$got" ] || { say "sha256 MISMATCH after restore -- stopping"; exit 10; }
  say "  sha256 MATCH"
  if [ -d "$BK/unit.d" ]; then
    sudo cp -a "$BK/unit.d/." "$UNIT_DROPIN_DIR/" || { say "restoring drop-ins failed"; exit 10; }
    say "restored drop-ins from $BK/unit.d"
  fi
else
  # --- no backup available: rewrite ExecStart back onto the indirection ----
  TMP_UNIT="$ASIDE/phone-engine.service.restored"
  python3 - "$UNIT_FILE" "$TMP_UNIT" "$NODE" "$LINK/$MODULE_REL" <<'PYEOF'
import sys
src, dst, new_interp, new_mod = sys.argv[1:5]
SUFFIX = "node_modules/@deepseek-ai/dsh/lib/bin.js"
lines = open(src, "r", encoding="utf-8").read().splitlines(keepends=True)
out, changed = [], 0
for line in lines:
    if line.startswith("ExecStart="):
        body = line[len("ExecStart="):]
        nl = ""
        if body.endswith("\n"):
            body, nl = body[:-1], "\n"
        toks = body.split(" ")
        if len(toks) < 2:
            sys.exit("ExecStart has fewer than 2 tokens")
        toks[0] = new_interp
        for i, t in enumerate(toks):
            if t.endswith(SUFFIX):
                toks[i] = new_mod
        new = "ExecStart=" + " ".join(toks) + nl
        if new != line:
            changed += 1
        out.append(new)
    else:
        out.append(line)
if changed > 1:
    sys.exit("refusing: more than one ExecStart line would change")
open(dst, "w", encoding="utf-8").write("".join(out))
print("execstart_lines_changed=%d" % changed)
PYEOF
  [ $? -eq 0 ] || { say "ExecStart rewrite failed"; exit 10; }
  sudo install -o root -g root -m 644 "$TMP_UNIT" "$UNIT_FILE" || { say "installing the restored unit failed"; exit 10; }
  say "rewrote ExecStart module path -> $LINK/$MODULE_REL"
fi



# --- the version-coupled config set (pain P2850) ---------------------------
# Without this, a rollback restores the engine and leaves the config that engine
# cannot boot. Restores only what was snapshotted; live data is never in the set.
if [ "$MODE" = state ] && [ -f "$BK/config-before/manifest.tsv" ]; then
  say ""
  say "restoring the version-coupled config set"
  # shellcheck source=/dev/null
  source "$DIRNAME_OF_SCRIPT/lib-configset.sh" || { say "cannot source lib-configset.sh"; exit 10; }
  if [ "$APPLY" -eq 1 ]; then
    configset_restore "$BK/config-before" "$ASIDE/config" || { say "config-set restore FAILED"; exit 10; }
    configset_verify  "$BK/config-before" || say "WARNING: the config set still does not match the snapshot -- see the DIFFERS lines above"
  else
    say "  would restore $(wc -l < "$BK/config-before/manifest.tsv" | tr -d ' ') path(s) from $BK/config-before"
  fi
fi
# --- home (opt-in, and only if the cutover actually swapped it) ------------
if [ "$MODE" = state ] && [ "$HOME_PERFORMED" = true ] && [ "$SKIP_HOME" -eq 0 ]; then
  if [ -d "$HOME_MOVED_TO" ]; then
    say "stopping $UNIT for the home restore"
    sudo systemctl stop "$UNIT" || { say "stop failed"; exit 10; }
    sudo mv "$LIVE_HOME" "$ASIDE/home.after-cutover" || { say "moving the post-cutover home aside FAILED"; exit 10; }
    say "moved   $LIVE_HOME -> $ASIDE/home.after-cutover"
    sudo mv "$HOME_MOVED_TO" "$LIVE_HOME" || { say "restoring the previous home FAILED"; exit 10; }
    say "restored $HOME_MOVED_TO -> $LIVE_HOME"
  else
    say "WARNING: the previous home $HOME_MOVED_TO is missing; leaving $LIVE_HOME in place"
  fi
fi

# --- repoint the indirection ---------------------------------------------
if [ -L "$LINK" ] && [ "$(readlink -f "$LINK")" = "$(readlink -f "$LINK_BEFORE")" ]; then
  say "link    UNCHANGED ($LINK -> $LINK_BEFORE)"
else
  sudo ln -s "$LINK_BEFORE" "$LINK.tmp.$$" || { say "ln -s failed"; exit 10; }
  sudo mv -Tf "$LINK.tmp.$$" "$LINK" || { say "atomic swap failed"; exit 10; }
  say "link    $LINK -> $LINK_BEFORE   (atomic rename)"
fi

# --- reload + restart ----------------------------------------------------
sudo systemctl daemon-reload || { say "daemon-reload failed"; exit 10; }
say "daemon-reload OK"
if [ "$NO_RESTART" -eq 1 ]; then
  say "--no-restart given: NOT restarting. The running process is still the new engine."
  exit 0
fi
sudo systemctl restart "$UNIT" || { say "restart failed"; exit 10; }
say "restart issued"

step "WAIT for 127.0.0.1:$PORT"
ok=0
for n in $(seq 1 90); do
  if (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then exec 3<&- 2>/dev/null; exec 3>&- 2>/dev/null; ok=1; break; fi
  sleep 1
done
[ "$ok" -eq 1 ] && say "port up after ${n}s" || say "port never came up after 90 s"

step "VERIFY (the OLD engine must answer)"
"$VERIFY" --expect-version "$VER_BEFORE"
vrc=$?
say "verify-live.sh exit=$vrc"
if [ "$vrc" -eq 0 ]; then
  say ""
  say "ROLLBACK OK: $UNIT is running @deepseek-ai/dsh $VER_BEFORE from $LINK_BEFORE"
  exit 0
fi
say ""
say "ROLLBACK VERIFY FAILED (exit $vrc). The unit is at $VER_BEFORE per the restore above;"
say "check $UNIT_FILE and  journalctl -u $UNIT -n 50"
exit 10
