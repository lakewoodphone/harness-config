#!/usr/bin/env bash
# verify-live.sh -- post-cutover proof, run against the LIVE 3089 phone engine.
#
# Every check is printed PASS / FAIL / UNKNOWN.  UNKNOWN is never a pass.
#
# Tiers:
#   CORE  liveness, interpreter, running-engine version, unit/process agreement,
#         token exchange, session/create.  A CORE FAIL or UNKNOWN -> exit 1.
#   EDGE  the phone gate, session quarantine.  An EDGE FAIL or UNKNOWN -> exit 2.
#         (EDGE failure alone must NOT trigger cutover.sh's auto-rollback: the
#          gate lives outside the engine and can be down while the engine is fine.)
#
# Exit: 0 all pass | 1 CORE fail/unknown | 2 EDGE-only fail/unknown
#
# Usage:
#   verify-live.sh [--expect-version V] [--presets a,b,c] [--json]
#                  [--no-create] [--keep-sessions] [--quiet] [--help]
#
set -uo pipefail

EXPECT_VERSION=""
PRESETS="zabz,cordis-bg,yocheved"
JSON=0
NO_CREATE=0
KEEP_SESSIONS=0
QUIET=0

HOMEDIR=/home/zabz
UNIT=phone-engine.service
UNIT_FILE=/etc/systemd/system/phone-engine.service
PORT=3089
GATE_PORT=3086
BASE="http://127.0.0.1:3089"
GATE="http://127.0.0.1:3086"
LINK=/home/zabz/dsh-current
SESSIONS="$HOMEDIR/.dsh/sessions"
STDOUT_LOG="$HOMEDIR/.dsh-phone/engine-3089.log"
MW_GLOB="$HOMEDIR/.dsh/multi-window/logs/3089-*.log"
STATE_DIR=/home/zabz/dsh-cutover
SENTINEL=/tmp/__dsh_verify_does_not_exist__

while [ $# -gt 0 ]; do
  case "$1" in
    --expect-version) EXPECT_VERSION="${2:?}"; shift 2 ;;
    --presets)        PRESETS="${2:?}"; shift 2 ;;
    --json)           JSON=1; shift ;;
    --no-create)      NO_CREATE=1; shift ;;
    --keep-sessions)  KEEP_SESSIONS=1; shift ;;
    --quiet)          QUIET=1; shift ;;
    -h|--help)        sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
done

UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RESULTS="$(mktemp)"; trap 'rm -f "$RESULTS"' EXIT
JAR="$(mktemp)"; HDR="$(mktemp)"
TRAP_EXTRA="$JAR $HDR"
trap 'rm -f "$RESULTS" "$JAR" "$HDR"' EXIT

core_bad=0; edge_bad=0
ck(){ # ck <TIER> <id> <PASS|FAIL|UNKNOWN> <detail...>
  local tier="$1" id="$2" verd="$3"; shift 3
  local detail="$*"
  if [ "$QUIET" -eq 0 ]; then printf '%-5s %-8s %-26s %s\n' "$tier" "$verd" "$id" "$detail"; fi
  if [ "$verd" != PASS ] && [ "$verd" != INFO ]; then
    if [ "$tier" = CORE ]; then core_bad=1; else edge_bad=1; fi
  fi
  jq -nc --arg t "$tier" --arg i "$id" --arg v "$verd" --arg d "$detail" \
    '{tier:$t,id:$i,verdict:$v,detail:$d}' >> "$RESULTS" 2>/dev/null || true
  return 0
}

[ "$QUIET" -eq 0 ] && printf 'verify-live  host=secratary  utc=%s  expect-version=%s\n\n' "$UTC" "${EXPECT_VERSION:-any}"

# ---------------------------------------------------------------- C0 unit ---
UNIT_STATE=""
if command -v systemctl >/dev/null 2>&1; then
  UNIT_STATE="$(systemctl is-active "$UNIT" 2>/dev/null)"
else
  UNIT_STATE=""
fi
case "$UNIT_STATE" in
  active)     ck CORE unit-active PASS "systemctl is-active $UNIT = active" ;;
  activating|deactivating|reloading|inactive|failed)
              ck CORE unit-active FAIL "systemctl is-active $UNIT = $UNIT_STATE" ;;
  *)          ck CORE unit-active UNKNOWN "could not read systemd state for $UNIT (got '$UNIT_STATE')" ;;
esac

ENGINE_PID=""
if command -v systemctl >/dev/null 2>&1; then
  ENGINE_PID="$(systemctl show -p MainPID --value "$UNIT" 2>/dev/null)"
  case "$ENGINE_PID" in ''|0|*[!0-9]*) ENGINE_PID="" ;; esac
fi

# ---------------------------------------------------------------- C1 port ---
SS_ROW="$(ss -ltnp 2>/dev/null | grep -E "127\.0\.0\.1:$PORT\b" | head -1)"
if (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then
  exec 3<&- 2>/dev/null; exec 3>&- 2>/dev/null
  ck CORE port-listening PASS "127.0.0.1:$PORT accepts a connection; ss: ${SS_ROW:-<ss unavailable>}"
  PORT_UP=1
else
  ck CORE port-listening FAIL "127.0.0.1:$PORT refuses a connection; ss: ${SS_ROW:-<ss unavailable>}"
  PORT_UP=0
fi

# ------------------------------------------- C2 the running interpreter ---
EXE_REAL=""; NODE_VER=""; UNIT_INTERP=""
EXEC_LINE="$(grep -m1 '^ExecStart=' "$UNIT_FILE" 2>/dev/null || true)"
if [ -n "$EXEC_LINE" ]; then
  read -r -a UTOK <<< "${EXEC_LINE#ExecStart=}"
  UNIT_INTERP="${UTOK[0]:-}"
fi
if [ -n "$ENGINE_PID" ] && [ -e "/proc/$ENGINE_PID/exe" ]; then
  EXE_REAL="$(readlink -f "/proc/$ENGINE_PID/exe" 2>/dev/null)"
  if [ -n "$EXE_REAL" ] && [ -x "$EXE_REAL" ]; then
    NODE_VER="$("$EXE_REAL" --version 2>/dev/null)"
    EMB="$(grep -a -o -m1 -E 'v[0-9]+\.[0-9]+\.[0-9]+' "$EXE_REAL" 2>/dev/null | head -1)"
    MAJ="$(printf '%s' "$NODE_VER" | sed -E 's/^v([0-9]+).*/\1/')"
    DETAIL="running interpreter $(readlink "/proc/$ENGINE_PID/exe") -> $EXE_REAL  ($NODE_VER, embedded string ${EMB:-none}); unit ExecStart interpreter=$UNIT_INTERP"
    if [ "$EXE_REAL" != "$(readlink -f "$UNIT_INTERP" 2>/dev/null)" ]; then
      ck CORE interpreter FAIL "$DETAIL -- MISMATCH: the unit names a different interpreter"
    elif ! printf '%s' "$MAJ" | grep -qE '^[0-9]+$'; then
      ck CORE interpreter UNKNOWN "$DETAIL -- cannot parse a major version"
    elif [ "$MAJ" -lt 22 ]; then
      ck CORE interpreter FAIL "$DETAIL -- too old: 0.2.0-rc.2 declares engines.node >=22.19"
    else
      ck CORE interpreter PASS "$DETAIL"
    fi
  else
    ck CORE interpreter UNKNOWN "/proc/$ENGINE_PID/exe does not resolve to an executable"
  fi
else
  ck CORE interpreter UNKNOWN "no engine pid (/proc/<pid>/exe unreadable)"
fi
PATH_NODE="$(command -v node 2>/dev/null || echo none)"
[ "$QUIET" -eq 0 ] && printf '%-5s %-8s %-26s %s\n' "INFO" "-" "node-on-path" "node on PATH = $PATH_NODE ($("$PATH_NODE" --version 2>/dev/null || echo '?')) -- the unit must never use this"

# ------------------------------- C3 the version the RUNNING process loaded ---
PKG_VERSION=""; MOD_ARG=""; MOD_REAL=""; PREFIX=""; MAPS_HITS="?"
if [ -n "$ENGINE_PID" ] && [ -r "/proc/$ENGINE_PID/cmdline" ]; then
  mapfile -t PARGV < <(tr '\0' '\n' < "/proc/$ENGINE_PID/cmdline")
  MOD_ARG="${PARGV[1]:-}"
  MOD_REAL="$(readlink -f "$MOD_ARG" 2>/dev/null)"
  # <prefix>/node_modules/@deepseek-ai/dsh/lib/bin.js -> dirname x2 -> .../@deepseek-ai/dsh
  PKGDIR="$(dirname "$(dirname "$MOD_REAL")")"
  PKG_VERSION="$(jq -r '.version // empty' "$PKGDIR/package.json" 2>/dev/null)"
  PREFIX="${MOD_REAL%%/node_modules/*}"
  if [ -r "/proc/$ENGINE_PID/maps" ]; then
    MAPS_HITS="$(grep -c "^[0-9a-f]*-[0-9a-f]* .* $PREFIX/" "/proc/$ENGINE_PID/maps" 2>/dev/null || true)"
  fi
fi
if [ -z "$PKG_VERSION" ]; then
  ck CORE module-version UNKNOWN "cannot read the version at the running process's module path (argv[1]=${MOD_ARG:-none})"
else
  PROC_START="$(stat -c %Y "/proc/$ENGINE_PID" 2>/dev/null || echo 0)"
  PKG_MTIME="$(stat -c %Y "$PKGDIR/package.json" 2>/dev/null || echo 0)"
  DETAIL="argv[1]=$MOD_ARG -> realpath $MOD_REAL -> @deepseek-ai/dsh $PKG_VERSION ; prefix=$PREFIX ; maps lines naming that prefix=$MAPS_HITS ; indirection=$([ "$MOD_ARG" != "$MOD_REAL" ] && echo YES || echo no)"
  if [ -n "$EXPECT_VERSION" ] && [ "$PKG_VERSION" != "$EXPECT_VERSION" ]; then
    ck CORE module-version FAIL "$DETAIL -- EXPECTED $EXPECT_VERSION"
  elif [ "$PKG_MTIME" -gt "$PROC_START" ] && [ "$PROC_START" -gt 0 ]; then
    ck CORE module-version UNKNOWN "$DETAIL -- package.json was modified AFTER the process started (pkg_mtime=$PKG_MTIME > proc_start=$PROC_START), so the running process may have loaded different bytes"
  else
    ck CORE module-version PASS "$DETAIL"
  fi
fi

# --------------------------------- C3b the loaded tree's own engines floor ---
ver_lt(){ [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" = "$1" ]; }
if [ -n "$PREFIX" ] && [ -n "$NODE_VER" ]; then
  NEED="$(python3 - "$PREFIX" <<'PYEOF'
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
  ACTUAL_V="$(printf '%s' "$NODE_VER" | sed -E 's/^v//')"
  if [ -z "$NEED" ] || [ "$NEED" = "0.0.0" ]; then
    ck CORE engines-floor UNKNOWN "no engines.node floor found under $PREFIX/node_modules -- assumed, not measured"
  elif ver_lt "$ACTUAL_V" "$NEED"; then
    ck CORE engines-floor FAIL "the running interpreter is v$ACTUAL_V but the tree it loaded ($PREFIX) requires >=$NEED"
  else
    ck CORE engines-floor PASS "running interpreter v$ACTUAL_V satisfies the >=$NEED floor declared inside $PREFIX/node_modules"
  fi
fi

# ------------------------------- C4 the unit agrees with the live process ---
if [ -n "$ENGINE_PID" ] && [ -n "$EXEC_LINE" ] && [ -r "/proc/$ENGINE_PID/cmdline" ]; then
  UJOIN="$(printf '%s ' "${UTOK[@]}")"
  PJOIN="$(printf '%s ' "${PARGV[@]}")"
  if [ "$UJOIN" = "$PJOIN" ]; then
    ck CORE unit-matches-process PASS "systemd's ExecStart and the running argv are identical: $PJOIN"
  else
    ck CORE unit-matches-process FAIL "unit ExecStart: $UJOIN ||| running argv: $PJOIN  (the running process is NOT what the unit says -- the daemon-reload/restart did not take effect)"
  fi
else
  ck CORE unit-matches-process UNKNOWN "cannot compare (pid=${ENGINE_PID:-none}, execstart=${EXEC_LINE:-none})"
fi

# --------------------------------------------------- C5 launch token -------
TOKENS=(); TOKEN_SOURCE=""
if compgen -G "$MW_GLOB" >/dev/null 2>&1; then
  NEWEST_MW="$(ls -1t $MW_GLOB 2>/dev/null | head -1)"
  mapfile -t TOKENS < <(grep -a -o 'token=[A-Za-z0-9_-]*' "$NEWEST_MW" 2>/dev/null | sed 's/^token=//')
  TOKEN_SOURCE="multi-window newest log: $NEWEST_MW"
fi
if [ "${#TOKENS[@]}" -eq 0 ]; then
  mapfile -t TOKENS < <(grep -a -o 'token=[A-Za-z0-9_-]*' "$STDOUT_LOG" 2>/dev/null | sed 's/^token=//')
  TOKEN_SOURCE="unit stdout append file: $STDOUT_LOG"
fi
# which is TRUE on this host, stated in the report:
if [ ! -d "$HOMEDIR/.dsh/multi-window/logs" ]; then
  [ "$QUIET" -eq 0 ] && printf '%-5s %-8s %-26s %s\n' "INFO" "-" "token-source" "$HOMEDIR/.dsh/multi-window/logs does not exist -> the launch token lives on the unit's stdout append file"
fi

AUTHED=0; TOK_USED=""; TOK_INDEX=""
if [ "${#TOKENS[@]}" -eq 0 ]; then
  ck CORE token-exchange UNKNOWN "no launch token found (source: $TOKEN_SOURCE)"
elif [ "$PORT_UP" -eq 0 ]; then
  ck CORE token-exchange UNKNOWN "port $PORT is not reachable, so the exchange cannot be attempted"
else
  n=${#TOKENS[@]}
  for ((i=n-1; i>=0 && i>=n-5; i--)); do
    tok="${TOKENS[$i]}"
    curl -s -o /dev/null -D "$HDR" -c "$JAR" --max-time 10 "$BASE/?token=$tok" >/dev/null 2>&1
    st="$(head -1 "$HDR" 2>/dev/null | awk '{print $2}')"
    cookies="$(grep -ci '^set-cookie: *dsh-auth-' "$HDR" 2>/dev/null || true)"
    if [ "$st" = "303" ] && [ "${cookies:-0}" -ge 1 ]; then
      AUTHED=1; TOK_USED="$tok"; TOK_INDEX="$(( n - 1 - i ))"
      ck CORE token-exchange PASS "GET $BASE/?token=<43-char token #$((n-i)) from newest> -> 303 + Set-Cookie dsh-auth-* (HttpOnly). Source: $TOKEN_SOURCE ; token age rank from newest = $TOK_INDEX"
      break
    fi
  done
  [ "$AUTHED" -eq 0 ] && ck CORE token-exchange FAIL "none of the last ${n} token(s) in $TOKEN_SOURCE produced 303 + Set-Cookie dsh-auth-* (last status='${st:-?}')"
fi

# --------------------------------------------------- C6 session/create -----
CREATED_IDS=()
IFS=',' read -r -a PRESET_ARR <<< "$PRESETS"
if [ "$NO_CREATE" -eq 1 ]; then
  ck CORE session-create UNKNOWN "--no-create given: session/create was not attempted"
elif [ "$AUTHED" -eq 0 ]; then
  ck CORE session-create UNKNOWN "no authenticated cookie, so session/create cannot be attempted"
else
  for p in "${PRESET_ARR[@]}"; do
    p="${p// /}"
    [ -n "$p" ] || continue
    body="$(jq -nc --arg p "$p" --arg cwd "$SENTINEL" \
      '{type:"client-request",rpcId:"verify-live",method:"session/create",payload:{args:{request:{cwd:$cwd,agentPreset:$p}}}}')"
    resp="$(curl -s -b "$JAR" -H 'content-type: application/json' -X POST --data-binary "$body" --max-time 30 "$BASE/api/session/create" 2>/dev/null)"
    ok="$(printf '%s' "$resp" | jq -r '.result.ok // false' 2>/dev/null)"
    sid="$(printf '%s' "$resp" | jq -r '.result.value.sessionId // empty' 2>/dev/null)"
    emsg="$(printf '%s' "$resp" | jq -r '.result.error.message // .result.error.code // empty' 2>/dev/null)"
    if [ "$ok" = "true" ] && [ -n "$sid" ]; then
      CREATED_IDS+=("$sid")
      ck CORE "session-create/$p" PASS "ok:true sessionId=$sid agentPreset=$p cwd=$SENTINEL"
    else
      ck CORE "session-create/$p" FAIL "agentPreset=$p -> ok=$ok ${emsg:+error=$emsg} (raw: $(printf '%s' "$resp" | head -c 300))"
    fi
  done
fi

# --------------------------------------------------- C7 the phone gate -----
if command -v curl >/dev/null 2>&1; then
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$GATE/" 2>/dev/null)"
  case "$CODE" in
    200) ck EDGE phone-gate PASS "GET $GATE/ -> 200 (phone-gate.py proxies to the engine)" ;;
    000) ck EDGE phone-gate FAIL "GET $GATE/ -> no answer at all" ;;
    *)   ck EDGE phone-gate FAIL "GET $GATE/ -> HTTP $CODE (expected 200)" ;;
  esac
else
  ck EDGE phone-gate UNKNOWN "curl is not available"
fi

# ------------------------------------------- C8 quarantine the test sessions
if [ "$KEEP_SESSIONS" -eq 1 ]; then
  ck EDGE session-quarantine UNKNOWN "--keep-sessions given: the test sessions were left in the store"
elif [ "${#CREATED_IDS[@]}" -eq 0 ]; then
  ck EDGE session-quarantine UNKNOWN "no session was created, so nothing to quarantine"
else
  QDIR="$STATE_DIR/quarantine/$UTC"
  SENTINEL_DIR="$SESSIONS/--tmp-__dsh_verify_does_not_exist__--"
  SRC=""
  if [ -d "$SENTINEL_DIR" ]; then
    SRC="$SENTINEL_DIR"
  else
    for sid in "${CREATED_IDS[@]}"; do
      hit="$(find "$SESSIONS" -maxdepth 2 -type d -name "$sid" 2>/dev/null | head -1)"
      [ -n "$hit" ] && SRC="$(dirname "$hit")" && break
    done
  fi
  if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
    ck EDGE session-quarantine UNKNOWN "the sentinel session dir was not found under $SESSIONS (nothing was moved)"
  else
    mkdir -p "$QDIR" 2>/dev/null
    if mv "$SRC" "$QDIR/$(basename "$SRC")" 2>/dev/null; then
      left=0
      for sid in "${CREATED_IDS[@]}"; do
        [ -e "$SESSIONS/--tmp-__dsh_verify_does_not_exist__--/$sid" ] && left=$((left+1))
      done
      ck EDGE session-quarantine PASS "moved $(basename "$SRC") out of the store -> $QDIR/$(basename "$SRC")  (created ids: ${CREATED_IDS[*]}; still in store: $left)"
      # Measured 2026-10-05: the engine holds every session it created open for the
      # life of the process, and it flushes its registry to disk.  So a still-loaded
      # session's directory is recreated as an empty stub moments after the move.
      # The move itself succeeded, so this is INFO, not a failure -- disclosed, never hidden.
      sleep 3
      if [ -d "$SENTINEL_DIR" ]; then
        stubs="$(find "$SENTINEL_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)"
        ck EDGE quarantine-stub INFO "a STUB reappeared at $SENTINEL_DIR ($stubs session dir(s), $(du -sb "$SENTINEL_DIR" 2>/dev/null | awk '{print $1}') bytes): the engine still holds that session open and flushed its registry to disk. The moved-out copy is intact in $QDIR. The stub is empty and its cwd does not exist; it disappears when the engine restarts."
      else
        ck EDGE quarantine-stub PASS "the sentinel dir stayed gone 3 s after the move"
      fi
    else
      ck EDGE session-quarantine FAIL "could not move $SRC out of the store"
    fi
  fi
fi

# ---------------------------------------------------------------- verdict --
if [ "$core_bad" -gt 0 ]; then VERDICT=FAIL; EXIT=1
elif [ "$edge_bad" -gt 0 ]; then VERDICT=EDGE-FAIL; EXIT=2
else VERDICT=PASS; EXIT=0; fi

if [ "$JSON" -eq 1 ]; then
  jq -s --arg v "$VERDICT" --arg t "$UTC" --arg e "${EXPECT_VERSION:-any}" \
    '{utc:$t,host:"secratary",expect_version:$e,verdict:$v,checks:.}' "$RESULTS"
  exit "$EXIT"
fi

echo
echo "VERDICT: $VERDICT  (core_bad=$core_bad edge_bad=$edge_bad)"
case "$EXIT" in
  0) echo "  the live 3089 engine answers, its reported version is the one it was launched from, and all three presets create sessions." ;;
  1) echo "  a CORE check failed or could not be measured -- the engine is NOT proven good." ;;
  2) echo "  CORE is good; an EDGE check (the phone gate or the quarantine) failed. The ENGINE is fine." ;;
esac
exit "$EXIT"
