#!/usr/bin/env bash
# cutover.sh -- move phone-engine.service from the live DSH npm prefix to a new one.
#
# DESIGN: one stable indirection symlink.
#   $LINK  (/home/zabz/dsh-current)  ->  <engine npm prefix>
#   The unit's ExecStart always names $LINK, never a versioned prefix.
#   A cutover is: swap one symlink + daemon-reload + one restart.
#   A rollback is: the same swap in reverse + one restart.
#   The unit text stops changing after the first cutover, so a rollback never
#   has to reconstruct it, and only ONE restart is ever needed.
#
# DRY-RUN BY DEFAULT.  Nothing is written, moved, stopped or restarted
# without --apply.  Every precondition is checked before any change.
#
# Usage:
#   cutover.sh [--apply] [--target PREFIX] [--target-version V]
#              [--staged-home DIR] [--home-swap]
#              [--no-auto-rollback] [--yes] [--force-restart]
#              [--state-dir DIR] [--help]
#
# Exit: 0 dry-run ready / applied+verified
#       4 refused: a precondition failed (nothing was changed)
#       10 apply failed, auto-rollback ran
#       11 apply failed, no auto-rollback
#
set -uo pipefail

APPLY=0
TARGET=/home/zabz/dsh-install/0.2.0-rc.2
TARGET_VERSION=0.2.0-rc.2
STAGED_HOME=/home/zabz/_dsh020/stage
HOME_SWAP=0
AUTO_ROLLBACK=1
ASSUME_YES=0
FORCE_RESTART=0
STATE_DIR=/home/zabz/dsh-cutover

UNIT=phone-engine.service
UNIT_FILE=/etc/systemd/system/phone-engine.service
UNIT_DROPIN_DIR=/etc/systemd/system/phone-engine.service.d
LINK=/home/zabz/dsh-current
NODE=/home/zabz/node/bin/node
MODULE_REL=node_modules/@deepseek-ai/dsh/lib/bin.js
MODULE_SUFFIX="node_modules/@deepseek-ai/dsh/lib/bin.js"
LIVE_PREFIX=/home/zabz/dsh-engine
LIVE_HOME=/home/zabz/.dsh
PORT=3089
DIRNAME_OF_SCRIPT="$(cd "$(dirname "$0")" && pwd)"

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)             APPLY=1; shift ;;
    --target)            TARGET="${2:?}"; shift 2 ;;
    --target-version)    TARGET_VERSION="${2:?}"; shift 2 ;;
    --staged-home)       STAGED_HOME="${2:?}"; shift 2 ;;
    --home-swap)         HOME_SWAP=1; shift ;;
    --no-auto-rollback)  AUTO_ROLLBACK=0; shift ;;
    --yes)               ASSUME_YES=1; shift ;;
    --force-restart)     FORCE_RESTART=1; shift ;;
    --state-dir)         STATE_DIR="${2:?}"; shift 2 ;;
    -h|--help)           sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
done

TARGET="${TARGET%/}"
UTC="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$STATE_DIR/backups/$UTC"
STATE_FILE="$STATE_DIR/state.json"
ROLLBACK="$DIRNAME_OF_SCRIPT/rollback.sh"
VERIFY="$DIRNAME_OF_SCRIPT/verify-live.sh"

say(){ printf '%s\n' "$*"; }
step(){ printf '\n===== %s\n' "$*"; }
refuse(){ printf '\nREFUSE: %s\n' "$*" >&2; exit 4; }

say "cutover.sh  mode=$([ "$APPLY" -eq 1 ] && echo APPLY || echo 'DRY-RUN')  utc=$UTC"
say "  unit           : $UNIT_FILE"
say "  indirection    : $LINK  ->  <engine npm prefix>"
say "  live prefix    : $LIVE_PREFIX"
say "  target prefix  : $TARGET   (expect @deepseek-ai/dsh $TARGET_VERSION)"
say "  interpreter    : $NODE   (must be >= v22.19; must NOT resolve to v20)"
say "  state/backups  : $STATE_DIR"
if [ "$HOME_SWAP" -eq 1 ]; then
  say "  home swap      : YES  $LIVE_HOME  <-  $STAGED_HOME"
else
  say "  home swap      : no   ($LIVE_HOME is left untouched)"
fi

# ============================================================== PRECHECKS ===
step "PRECHECKS"
bad=0
chk(){ # chk <id> <verdict> <detail>
  printf '  %-4s %-28s %s\n' "$2" "$1" "$3"
  [ "$2" = BAD ] && bad=$((bad+1)); return 0
}

# P1 sudo
if sudo -n true 2>/dev/null; then chk sudo OK "sudo -n works for $(id -un)"; else
  if [ "$APPLY" -eq 1 ]; then chk sudo BAD "sudo -n true failed; --apply needs root-equivalent access"
  else chk sudo WARN "sudo -n true failed (only matters for --apply)"; fi
fi

# P2 unit present, exactly one ExecStart
if [ ! -r "$UNIT_FILE" ]; then chk unit-file BAD "not readable: $UNIT_FILE"; else
  n=$(grep -c '^ExecStart=' "$UNIT_FILE" 2>/dev/null)
  if [ "$n" -ne 1 ]; then chk execstart BAD "expected exactly 1 ExecStart= line, found $n"; else
    chk execstart OK "exactly 1 ExecStart= line"
  fi
fi
EXEC_LINE="$(grep -m1 '^ExecStart=' "$UNIT_FILE" 2>/dev/null || true)"
EXEC_ARGV=(${EXEC_LINE#ExecStart=})
EXEC_INTERP="${EXEC_ARGV[0]:-}"
EXEC_MODULE="${EXEC_ARGV[1]:-}"

# P3 interpreter is the explicit v22 node and really is v22+, not v20
if [ -x "$NODE" ]; then
  NODE_VER="$("$NODE" --version 2>/dev/null)"
  NODE_MAJOR="$(printf '%s' "$NODE_VER" | sed -E 's/^v([0-9]+).*/\1/')"
  case "$NODE_MAJOR" in
    ''|*[!0-9]*) chk node BAD "cannot parse node version '$NODE_VER'" ;;
    *) if [ "$NODE_MAJOR" -ge 22 ]; then chk node OK "$NODE = $NODE_VER (major >= 22)"
       else chk node BAD "$NODE = $NODE_VER -- 0.2.0-rc.2 declares engines.node >=22.19"; fi ;;
  esac
else
  chk node BAD "$NODE is missing or not executable"
fi
case "$EXEC_INTERP" in
  "")              chk exec-interp BAD "cannot read the ExecStart interpreter" ;;
  "$NODE")         chk exec-interp OK "ExecStart interpreter is $NODE" ;;
  *)               chk exec-interp BAD "ExecStart interpreter is '$EXEC_INTERP', expected '$NODE'" ;;
esac
PATH_NODE="$(command -v node 2>/dev/null || echo none)"
chk path-node INFO "node on PATH = $PATH_NODE ($("$PATH_NODE" --version 2>/dev/null || echo '?')) -- must never be used by the unit"

# P3b: the real requirement -- the highest engines.node floor anywhere in the tree
# the engine will load.  Measured 2026-10-05: @deepseek-ai/dsh itself declares NO
# engines field; the >=22.19 floor comes from undici and @deepseek-ai/libreoffice-kit*.
# So read it from the tree, do not assume it from the top-level package.
ver_lt(){ [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" = "$1" ]; }
TARGET_NODE_MIN="$(python3 - "$TARGET" <<'PYEOF'
import glob, json, os, re, sys
root = os.path.join(sys.argv[1], "node_modules")
need = (0, 0, 0)
for p in glob.glob(os.path.join(root, "**", "package.json"), recursive=True):
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    e = (d.get("engines") or {}).get("node")
    if not e:
        continue
    m = re.match(r"^\s*>=\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(e))
    if m:
        v = (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0))
        if v > need:
            need = v
print("%d.%d.%d" % need)
PYEOF
)"
[ -n "$TARGET_NODE_MIN" ] || TARGET_NODE_MIN=0.0.0
chk target-engines INFO "highest engines.node floor in $TARGET/node_modules = >=$TARGET_NODE_MIN"
if [ -x "$NODE" ] && [ "$TARGET_NODE_MIN" != "0.0.0" ]; then
  ACTUAL_V="$(printf '%s' "$NODE_VER" | sed -E 's/^v//')"
  if ver_lt "$ACTUAL_V" "$TARGET_NODE_MIN"; then
    chk target-engines-check BAD "$NODE is v$ACTUAL_V but the target tree requires >=$TARGET_NODE_MIN"
  else
    chk target-engines-check OK "$NODE is v$ACTUAL_V, satisfies >=$TARGET_NODE_MIN"
  fi
else
  chk target-engines-check SKIP "cannot compare (node missing or no engines floor found)"
fi

# P4 target prefix + package identity + version
TARGET_PKG="$TARGET/node_modules/@deepseek-ai/dsh/package.json"
TARGET_BIN="$TARGET/$MODULE_REL"
if [ ! -d "$TARGET" ]; then chk target-dir BAD "target prefix does not exist: $TARGET"
elif [ ! -f "$TARGET_BIN" ]; then chk target-bin BAD "no bin.js at $TARGET_BIN (install incomplete)"
elif [ ! -x "$TARGET_BIN" ] && [ ! -r "$TARGET_BIN" ]; then chk target-bin BAD "$TARGET_BIN exists but is not readable"
else chk target-bin OK "$TARGET_BIN present"; fi
if [ -f "$TARGET_PKG" ]; then
  tv=$(jq -r '.version // empty' "$TARGET_PKG" 2>/dev/null)
  tn=$(jq -r '.name // empty' "$TARGET_PKG" 2>/dev/null)
  if [ "$tv" = "$TARGET_VERSION" ]; then chk target-version OK "@deepseek-ai/dsh $tv"; else
    chk target-version BAD "@deepseek-ai/dsh at target is '$tv', expected '$TARGET_VERSION'"; fi
  [ "$tn" = "@deepseek-ai/dsh" ] && chk target-name OK "$tn" || chk target-name BAD "package name '$tn' is not @deepseek-ai/dsh"
  eng=$(jq -r '.engines.node // empty' "$TARGET_PKG" 2>/dev/null)
  chk target-engines-dsh INFO "@deepseek-ai/dsh declares engines.node = '${eng:-none}' (the real floor is computed from the whole tree below)"
else
  chk target-version BAD "no package.json at $TARGET_PKG (install incomplete)"
fi
case "$TARGET" in "$LIVE_PREFIX"|"$LIVE_PREFIX"/*) chk target-distinct BAD "target is inside the live prefix" ;; esac
case "$LIVE_PREFIX" in "$TARGET"/*) chk target-distinct BAD "live prefix is inside the target" ;; esac

# P5 the link path must not be a real directory
if [ -d "$LINK" ] && [ ! -L "$LINK" ]; then
  chk link-path BAD "$LINK exists and is a real DIRECTORY, not a symlink -- move it aside first"
else
  chk link-path OK "$LINK is free to use (or already a symlink)"
fi

# P6 staged home (only when asked for)
if [ "$HOME_SWAP" -eq 1 ]; then
  if [ ! -d "$STAGED_HOME" ]; then chk staged-home BAD "not a directory: $STAGED_HOME"
  elif [ "$(readlink -f "$STAGED_HOME")" = "$(readlink -f "$LIVE_HOME")" ]; then chk staged-home BAD "staged home IS the live home"
  elif [ ! -f "$STAGED_HOME/settings.yaml" ]; then
    if ls "$STAGED_HOME"/settings.yaml.* >/dev/null 2>&1; then
      chk staged-home BAD "$STAGED_HOME has no settings.yaml -- only $(ls "$STAGED_HOME"/settings.yaml.* 2>/dev/null | xargs -n1 basename | tr '\n' ' '). The staging is NOT finished; do not --home-swap yet."
    else
      chk staged-home BAD "$STAGED_HOME/settings.yaml missing -- does not look like a .dsh home"
    fi
  else chk staged-home OK "$STAGED_HOME (has settings.yaml)"
  fi
else
  chk staged-home SKIP "--home-swap not requested"
fi

# P7 helpers the scripts need
for c in curl jq python3 sha256sum; do
  if command -v "$c" >/dev/null 2>&1; then chk "tool:$c" OK "$(command -v $c)"; else chk "tool:$c" BAD "missing"; fi
done
for s in "$ROLLBACK" "$VERIFY"; do
  [ -x "$s" ] && chk "script:$(basename $s)" OK "$s" || chk "script:$(basename $s)" BAD "missing or not executable: $s"
done

# P8 idempotency: are we already at the target?
ALREADY=0
if [ -L "$LINK" ] && [ "$(readlink -f "$LINK")" = "$(readlink -f "$TARGET" 2>/dev/null)" ] \
   && printf '%s' "$EXEC_MODULE" | grep -q '/dsh-current/'; then
  ALREADY=1
  chk already-at-target INFO "the link and ExecStart already point at $TARGET_VERSION"
fi

# ============================================================== THE PLAN ====
step "PLAN (what --apply would do, in this order)"
BK="$BACKUP_DIR"
i=0
p(){ i=$((i+1)); printf '  %2d. %s\n' "$i" "$*"; }
p "mkdir -p $BK"
p "cp -a $UNIT_FILE -> $BK/phone-engine.service     (UTC backup, byte copy)"

  p "snapshot the version-coupled config set -> $BK/config-before   (BEFORE the first change, so rollback can undo it)"
p "cp -a $UNIT_DROPIN_DIR -> $BK/unit.d/            (UTC backup of every drop-in)"
p "systemctl cat $UNIT > $BK/systemctl-cat.before.txt"
p "sha256sum unit before -> $BK/unit.sha256.before"
if [ "$HOME_SWAP" -eq 1 ]; then
  p "systemctl stop $UNIT                              (needed only because --home-swap was given)"
  p "mv $LIVE_HOME -> $BK/home.old                     (MOVE, never a delete)"
  p "mv $STAGED_HOME -> $LIVE_HOME"
fi
if [ "$ALREADY" -eq 1 ]; then
  p "ln -s $TARGET -> $LINK.tmp && mv -Tf -> $LINK     (UNCHANGED: already at target)"
else
  p "ln -s $TARGET -> $LINK.tmp.\$\$ && mv -Tf $LINK.tmp.\$\$ $LINK   (atomic rename(2) swap)"
fi
p "rewrite ExecStart: interpreter -> $NODE, module -> $LINK/$MODULE_REL   (in place, verified single-line)"
p "sudo install -o root -g root -m 644 <new unit> $UNIT_FILE"
p "write $STATE_FILE                                (BEFORE any change, so rollback works mid-flight)"
p "systemctl daemon-reload"
p "systemctl restart $UNIT"
p "wait up to 90 s for 127.0.0.1:$PORT to accept a connection"
p "$VERIFY --expect-version $TARGET_VERSION"
if [ "$AUTO_ROLLBACK" -eq 1 ]; then p "if verify fails -> $ROLLBACK --apply --yes   (auto-rollback)"; else p "if verify fails -> stop and print the rollback command (auto-rollback disabled)"; fi

if [ "$bad" -gt 0 ]; then
  refuse "$bad precondition(s) marked BAD above. Nothing was changed.
         The most likely cause on a fresh host: the 0.2.0-rc.2 install is not finished
         (check $TARGET_PKG and $TARGET_BIN)."
fi

if [ "$APPLY" -eq 0 ]; then
  printf '\nDRY-RUN: all preconditions OK. Nothing was changed.\n'
  if [ "$ALREADY" -eq 1 ] && [ "$FORCE_RESTART" -eq 0 ]; then
    say "         Already at $TARGET_VERSION -- --apply would report ALREADY AT TARGET and not restart."
  fi
  say "         To do it for real:  $0 --apply$([ "$HOME_SWAP" -eq 1 ] && echo ' --home-swap')"
  exit 0
fi

if [ "$ALREADY" -eq 1 ] && [ "$FORCE_RESTART" -eq 0 ] && [ "$HOME_SWAP" -eq 0 ]; then
  say ""
  say "ALREADY AT TARGET: link and ExecStart already point at $TARGET_VERSION. Nothing to do."
  say "Use --force-restart to restart anyway."
  exit 0
fi

if [ "$ASSUME_YES" -eq 0 ]; then
  printf '\nThis will restart %s on a LIVE production control plane.\n' "$UNIT"
  printf 'Type exactly: cutover %s\n> ' "$TARGET_VERSION"
  read -r answer
  [ "$answer" = "cutover $TARGET_VERSION" ] || refuse "confirmation did not match; nothing was changed."
fi

# ============================================================== APPLY =======
step "APPLY"
mkdir -p "$BK" || { say "cannot create $BK"; exit 10; }

# ---- backup -----------------------------------------------------------
sudo cp -a "$UNIT_FILE" "$BK/phone-engine.service" || { say "unit backup failed"; exit 10; }
say "backed up unit  -> $BK/phone-engine.service"
if [ -d "$UNIT_DROPIN_DIR" ]; then
  sudo cp -a "$UNIT_DROPIN_DIR" "$BK/unit.d" || { say "drop-in backup failed"; exit 10; }
  say "backed up drop-ins -> $BK/unit.d"
fi
systemctl cat "$UNIT" > "$BK/systemctl-cat.before.txt" 2>&1 || true
sha256sum "$UNIT_FILE" | awk '{print $1}' > "$BK/unit.sha256.before"
UNIT_SHA_BEFORE="$(cat "$BK/unit.sha256.before")"


# ---- config-set snapshot (pain P2850, added 2026-10-05) ---------------------
# An engine and a version-coupled config are ONE artefact, so "restore the engine"
# is only half a rollback and the half left behind is the half that cannot boot.
# Measured 2026-10-05: the first 0.2.0-rc.2 cutover failed verification, the
# automatic rollback put the 0.1.5 engine back and left the 0.2.0 config in place,
# and the engine then died on
#   TypeError: this.ctx.agentPresets.register is not a function  at #preset-zabz
# The set is defined by lib-configset.sh, not by the caller, so this snapshot
# happens whether or not anyone remembered to ask for it.
# shellcheck source=/dev/null
source "$DIRNAME_OF_SCRIPT/lib-configset.sh" || { say "FATAL: cannot source $DIRNAME_OF_SCRIPT/lib-configset.sh"; exit 10; }
configset_snapshot "$BK/config-before" || { say "FATAL: config-set snapshot failed -- refusing to change anything"; exit 10; }

# ---- previous state ---------------------------------------------------
LINK_BEFORE="$(readlink "$LINK" 2>/dev/null || true)"
case "$EXEC_MODULE" in
  *"/dsh-current/$MODULE_SUFFIX") LINK_BEFORE="${LINK_BEFORE:-}" ; MODULE_BEFORE="$EXEC_MODULE" ;;
  *) MODULE_BEFORE="$EXEC_MODULE" ;;
esac
EXEC_MOD_REAL="$(readlink -f "$EXEC_MODULE" 2>/dev/null || echo /nonexistent)"
# <prefix>/node_modules/@deepseek-ai/dsh/lib/bin.js -> dirname x2 -> .../@deepseek-ai/dsh
VERSION_BEFORE="$(jq -r '.version // "unknown"' "$(dirname "$(dirname "$EXEC_MOD_REAL")")/package.json" 2>/dev/null || echo unknown)"
PREFIX_BEFORE="$(printf '%s' "$EXEC_MODULE" | sed -E 's#/node_modules/.*##')"
[ -n "$LINK_BEFORE" ] || LINK_BEFORE="$PREFIX_BEFORE"

# state.json is written BEFORE the first change, so a crash mid-flight is recoverable
jq -n \
  --arg started "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg unit "$UNIT" --arg unit_file "$UNIT_FILE" \
  --arg sha_before "$UNIT_SHA_BEFORE" \
  --arg link "$LINK" --arg link_before "$LINK_BEFORE" --arg link_after "$TARGET" \
  --arg prefix_before "$PREFIX_BEFORE" --arg prefix_after "$TARGET" \
  --arg version_before "$VERSION_BEFORE" --arg version_after "$TARGET_VERSION" \
  --arg backup_dir "$BK" \
  --argjson home_swapped "$([ "$HOME_SWAP" -eq 1 ] && echo true || echo false)" \
  --arg live_home "$LIVE_HOME" --arg staged_home "$STAGED_HOME" \
  --arg home_moved_to "$BK/home.old" \
  '{
     cutover_version: 1, completed_utc: null, started_utc: $started,
     unit: $unit, unit_file: $unit_file, unit_sha256_before: $sha_before,
     link: $link, link_target_before: $link_before, link_target_after: $link_after,
     prefix_before: $prefix_before, prefix_after: $prefix_after,
     version_before: $version_before, version_after: $version_after,
     backup_dir: $backup_dir,
     home_swap: { performed: $home_swapped, live_home: $live_home, staged_home: $staged_home, moved_to: $home_moved_to }
   }' > "$STATE_FILE" || { say "cannot write $STATE_FILE"; exit 10; }
cp -a "$STATE_FILE" "$BK/state.json"
say "wrote state     -> $STATE_FILE"

# ---- home swap (opt-in; requires a stop) ------------------------------
if [ "$HOME_SWAP" -eq 1 ]; then
  say "stopping $UNIT for the home swap"
  sudo systemctl stop "$UNIT" || { say "stop failed"; exit 10; }
  sudo mv "$LIVE_HOME" "$BK/home.old" || { say "moving the live home aside FAILED"; exit 10; }
  say "moved   $LIVE_HOME -> $BK/home.old"
  sudo mv "$STAGED_HOME" "$LIVE_HOME" || { say "moving the staged home in FAILED"; exit 10; }
  say "moved   $STAGED_HOME -> $LIVE_HOME"
fi

# ---- atomic symlink swap ----------------------------------------------
if [ -L "$LINK" ] && [ "$(readlink -f "$LINK")" = "$(readlink -f "$TARGET")" ]; then
  say "link    UNCHANGED ($LINK -> $TARGET)"
else
  sudo ln -s "$TARGET" "$LINK.tmp.$$" || { say "ln -s failed"; exit 10; }
  sudo mv -Tf "$LINK.tmp.$$" "$LINK" || { say "atomic swap failed"; exit 10; }
  say "link    $LINK -> $TARGET   (atomic rename)"
fi

# ---- rewrite ExecStart -------------------------------------------------
TMP_UNIT="$BK/phone-engine.service.new"
python3 - "$UNIT_FILE" "$TMP_UNIT" "$NODE" "$LINK/$MODULE_REL" <<'PYEOF'
import sys
src, dst, new_interp, new_mod = sys.argv[1:5]
SUFFIX = "node_modules/@deepseek-ai/dsh/lib/bin.js"
with open(src, "r", encoding="utf-8") as fh:
    lines = fh.read().splitlines(keepends=True)
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
    sys.exit("refusing: more than one ExecStart line would change (%d)" % changed)
if not any(l.startswith("ExecStart=") for l in lines):
    sys.exit("refusing: no ExecStart line found")
with open(dst, "w", encoding="utf-8") as fh:
    fh.write("".join(out))
print("execstart_lines_changed=%d" % changed)
PYEOF
[ $? -eq 0 ] || { say "ExecStart rewrite failed"; exit 10; }
NEW_EXEC="$(grep -m1 '^ExecStart=' "$TMP_UNIT")"
say "new     $NEW_EXEC"

sudo install -o root -g root -m 644 "$TMP_UNIT" "$UNIT_FILE" || { say "installing the new unit failed"; exit 10; }
sha256sum "$UNIT_FILE" | awk '{print $1}' > "$BK/unit.sha256.after"

# ---- reload + restart --------------------------------------------------
sudo systemctl daemon-reload || { say "daemon-reload failed"; exit 10; }
say "daemon-reload OK"
sudo systemctl restart "$UNIT" || { say "restart failed"; exit 10; }
say "restart issued"

step "WAIT for 127.0.0.1:$PORT"
ok=0
for n in $(seq 1 90); do
  if (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then exec 3<&- 2>/dev/null; exec 3>&- 2>/dev/null; ok=1; break; fi
  sleep 1
done
if [ "$ok" -eq 1 ]; then say "port up after ${n}s"; else say "port never came up after 90 s"; fi

# ---- token-ready wait (added 2026-10-05) ------------------------------------
# The banner is printed after the MCP servers start, so a port-open check is NOT
# proof the token is usable yet. Wait until some token in the append log actually
# exchanges for a 303, or give up after 150 s and let verify record the failure.
TOKLOG="${TOKLOG:-/home/zabz/.dsh-phone/engine-${PORT}.log}"
BASE_URL="http://127.0.0.1:${PORT}"
tok_ready=0
for _i in $(seq 1 150); do
  for _t in $(grep -a -o 'token=[A-Za-z0-9_-]*' "$TOKLOG" 2>/dev/null | tail -8 | sed 's/^token=//'); do
    _c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${BASE_URL}/?token=${_t}" 2>/dev/null || echo 000)
    if [ "$_c" = "303" ]; then tok_ready=1; break 2; fi
  done
  sleep 1
done
if [ "$tok_ready" -eq 1 ]; then
  say "launch token usable after ${_i}s"
else
  say "WARNING: no usable launch token after 150 s -- verify will report what it sees"
fi

step "VERIFY"
"$VERIFY" --expect-version "$TARGET_VERSION"
vrc=$?
say "verify-live.sh exit=$vrc"

if [ "$vrc" -eq 0 ]; then
  jq '.completed_utc = "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"' "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
  say ""
  say "CUTOVER OK: $UNIT is running @deepseek-ai/dsh $TARGET_VERSION from $TARGET"
  say "ROLLBACK IF NEEDED:  sudo $ROLLBACK --apply --yes"
  exit 0
fi

say ""
say "VERIFY FAILED (exit $vrc)."
if [ "$AUTO_ROLLBACK" -eq 1 ]; then
  say "AUTO-ROLLBACK: running  sudo $ROLLBACK --apply --yes --from $STATE_FILE"
  sudo "$ROLLBACK" --apply --yes --from "$STATE_FILE"
  rrc=$?
  say "rollback exit=$rrc"
  exit 10
fi
say "AUTO-ROLLBACK DISABLED. Run this now:"
say "  sudo $ROLLBACK --apply --yes --from $STATE_FILE"
exit 11
