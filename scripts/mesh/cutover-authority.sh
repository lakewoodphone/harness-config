#!/usr/bin/env bash
# =============================================================================
# cutover-authority.sh — Stages 4/5/6 of docs/mesh/126-authority-cutover-runbook.md
# THE RUNBOOK IS AUTHORITATIVE. Stage 4 freeze+delta | Stage 5 verify | Stage 6
# switch | Stage 4+6 rollback, plus a read-only `status`. diff_check() records the one
# place the BRIEF and the runbook disagree (must byte count and page_count be EQUAL? the
# runbook says no): the conversion drops the duplicated contentless-FTS `_fts_content` and
# VACUUMs, leaving ~23.5 GB / 5.67 M pages on the office vs ~13.1 GB / 3.42 M on the copy.
# RPO (runbook §3): up to 24 h standing — everything since the 12:00Z R2 push. During the
#   freeze, writes that arrive while writers are stopped are LOST; measured ~0.70 MB/min,
#   so a 45-min freeze defers ~30 MB. Stage 9's archive-and-prune is the only permanent-
#   loss step and its recovery is HOURS.
# RTO (runbook §3): 2-5 MINUTES back to the office DB, because the office file is never
#   modified. During the freeze it is <=5 min of commands PLUS the drive to Lakewood —
#   `ethtool eno1` reports no `Wake-on:` line at all.
# SAFETY (runbook §2): office DB frozen, never deleted, rollback for >=7 days; one writer
#   and ZERO during the freeze, proven by `lsof` on the FILE still empty after one FULL
#   CRON PERIOD, never a systemctl exit code; nothing points at the copy until compared;
#   never two cloudflared connectors; the new API binds loopback only; prune only after.
#   Mutating stages change NOTHING without --confirm; status and verify are read-only.
# =============================================================================
set -euo pipefail
# MEASURED facts, runbook §1. Override via the environment; never guess them.
OFFICE_HOST="${CUTOVER_OFFICE_HOST:-secratary-ts}"       # Linux office box = the authority
CLOUD_HOST="${CUTOVER_CLOUD_HOST:-root@178.156.194.1}"   # secratary-cloud, Ubuntu 26.04
CLOUD_KEY="${CUTOVER_CLOUD_KEY:-$HOME/.ssh/id_ed25519_hetzner}"
CLOUD_SHIP="${CUTOVER_CLOUD_SHIP:-root@178.156.194.1}"   # runbook says root@secratary-cloud; that alias does not exist yet
OFFICE_DB="${CUTOVER_OFFICE_DB:-/home/zabz/personal-secretary-mvp/data/secretary.db}"
OFFICE_DIR="${CUTOVER_OFFICE_DIR:-/home/zabz/cutover}"; OFFICE_FINAL="$OFFICE_DIR/final.db"
CRONTAB_BAK="$OFFICE_DIR/crontab.before"
CLOUD_DIR="${CUTOVER_CLOUD_DIR:-/root/cutover}"; CLOUD_FINAL="$CLOUD_DIR/final-src.db"
CLOUD_DB="${CUTOVER_CLOUD_DB:-/root/authority.db}"; CONVERT_LOG="$CLOUD_DIR/final-convert.log"
FTS_CONVERT="${CUTOVER_FTS_CONVERT:-/root/fts-convert.sh}"
TERM="${CUTOVER_FTS_TERM:-the}"                          # the search fingerprint term
MARK="${CUTOVER_EXPECTED_TABLE_DIFF:-dsh_session_events_fts_content}"  # the ONE expected table diff
CRON_PERIOD="${CUTOVER_CRON_PERIOD:-360}"                # one full `*/5` cron period (runbook 4d)
CONNECT_TIMEOUT="${CUTOVER_CONNECT_TIMEOUT:-8}"; SSH_TIMEOUT="${CUTOVER_SSH_TIMEOUT:-180}"
HEAVY_TIMEOUT="${CUTOVER_HEAVY_TIMEOUT:-1800}"           # integrity_check / .backup / convert
SUDO="${CUTOVER_SUDO:-sudo -n}"                          # CUTOVER_SUDO=sudo if NOPASSWD is off
WRITERS="secretary-api dialpad-sms-ws secretary-dashboard phone-engine"
TIMERS="secretary-api-watchdog.timer secretary-access-watchdog.timer"
TMPD="${TMPDIR:-/tmp}"; TMPD="${TMPD%/}"; RC=0; OUT=""; FAILED=0
ROLLBACK_CMD="ssh $CLOUD_HOST '$SUDO systemctl stop secretary-api cloudflared; tailscale serve --https=443 off'; ssh $OFFICE_HOST '$SUDO systemctl unmask secretary-api.service dialpad-sms-ws.service; $SUDO systemctl start cloudflared secretary-api secretary-dashboard phone-engine dialpad-sms-ws; crontab $CRONTAB_BAK'"
hdr(){ printf '\n=== %s ===\n' "$*"; }
say(){ printf '%s\n' "$*"; }
warn(){ printf '!! %s\n' "$*" >&2; }
pass(){ printf '  [PASS] %s\n' "$*"; }
fail(){ printf '  [FAIL] %s\n' "$*"; FAILED=$((FAILED+1)); }
info(){ printf '  [info] %s\n' "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit "${2:-1}"; }
usage(){ cat <<'U'
cutover-authority.sh — Stages 4/5/6 of docs/mesh/126-authority-cutover-runbook.md
  --stage <name>   REQUIRED: status | freeze | delta | verify | switch | rollback
      status read-only: who is serving, DB size/mtime both, which writers run
      freeze Stage 4: stop every writer, then PROVE the freeze held (lsof)
      delta  Stage 4: sqlite3 .backup snapshot, ship it, convert it
      verify Stage 5: PASS/FAIL the copy against the frozen source (read-only)
      switch Stage 6: loopback API, tailnet, then the Cloudflare tunnel
      rollback Stage 4/6: office box back in charge
  --confirm  execute a mutating stage. Without it a mutating stage prints the
             exact commands it would run and changes NOTHING.
  -h, --help this text. A bare invocation is refused: no stage is guessed.
U
}
# Remote scripts travel base64-encoded and are decoded to a FILE before bash runs them: the
# runbook measured that Windows mangles remote quoting and that a *piped* ssh stdout can hang.
# Keeping bash's stdin off the pipe also lets remote commands like `crontab -` read their input.
_tout(){ if command -v timeout >/dev/null 2>&1; then timeout "$1" "${@:2}"; else shift; "$@"; fi; }
b64_run(){ # $1 target, $2 script, $3 key file ('' = ssh config)
  local target="$1" script="$2" key="${3:-}" enc f
  local -a a=(-o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" -o StrictHostKeyChecking=accept-new)
  if [ -n "$key" ] && [ -f "$key" ]; then a+=(-i "$key"); fi
  enc="$(printf '%s' "$script" | base64 | tr -d '\r\n')"; f="$(mktemp "$TMPD/cutover.XXXXXX")"; RC=0
  _tout "$SSH_TIMEOUT" ssh "${a[@]}" "$target" \
    "umask 077; T=\$(mktemp /tmp/cutover-stage.XXXXXX); echo $enc | base64 -d > \"\$T\"; bash \"\$T\"; rc=\$?; rm -f \"\$T\"; exit \$rc" \
    >"$f" 2>&1 || RC=$?
  OUT="$(cat "$f")"; rm -f "$f"; return 0
}
o_run(){ b64_run "$OFFICE_HOST" "$1" ""; }
c_run(){ b64_run "$CLOUD_HOST" "$1" "$CLOUD_KEY"; }
dry(){ say ""; say "DRY RUN — nothing changed. With --confirm this would run EXACTLY:"; say "-----8<-----"; say "$1"; say "----->8----"; }
# The raw lsof on the office DB (runbook §4c). An lsof with no matches prints NOTHING; with
# matches it prints a header plus a row per fd. The runbook's test is `| wc -l` == 0, so this
# line count has identical semantics. lsof IS the success test; a systemctl code is not.
lsof_script(){ cat <<EOF
command -v lsof >/dev/null 2>&1 || { echo 'lsof NOT INSTALLED - /proc fallback follows'; ls -l /proc/*/fd 2>/dev/null | grep -F '$OFFICE_DB' || true; exit 0; }
$SUDO lsof -nP -- '$OFFICE_DB' 2>/dev/null || lsof -nP -- '$OFFICE_DB' 2>/dev/null || true
EOF
}
probe_lsof(){
  o_run "$(lsof_script)"
  LSOF="$OUT"; LSOF_N="$(printf '%s\n' "$LSOF" | grep -c '[^[:space:]]' || true)"
  LSOF_PIDS="$(printf '%s\n' "$LSOF" | awk 'NR>1 && $2 ~ /^[0-9]+$/ {print $2}' | sort -u | tr '\n' ' ' || true)"
}
# One '|'-separated line: page_size|page_count|tables|rows|sum(len raw)|max rowid|fts hits|sample rowids
shape_sql(){ cat <<SQL
SELECT (SELECT page_size FROM pragma_page_size),(SELECT page_count FROM pragma_page_count),(SELECT count(*) FROM sqlite_master WHERE type='table'),
 (SELECT ifnull(count(*),0) FROM dsh_session_events),(SELECT ifnull(sum(length(raw)),0) FROM dsh_session_events),(SELECT ifnull(max(rowid),0) FROM dsh_session_events),
 (SELECT count(*) FROM dsh_session_events_fts WHERE dsh_session_events_fts MATCH '$TERM'),
 (SELECT ifnull(group_concat(rowid),'-') FROM (SELECT rowid FROM dsh_session_events_fts WHERE dsh_session_events_fts MATCH '$TERM' LIMIT 5));
SQL
}
probe_shape(){ # $1 target, $2 key, $3 db -> SHAPE, SHAPE_BYTES ('DB-MISSING' when absent)
  b64_run "$1" "D='$3'
[ -f \"\$D\" ] || { echo DB-MISSING; exit 0; }
sqlite3 -separator '|' \"\$D\" <<'SQL'
$(shape_sql)
SQL
echo \"BYTES=\$(stat -c %s \"\$D\")\"" "$2"
  SHAPE="$(printf '%s\n' "$OUT" | grep -v '^BYTES=' | head -1)"
  SHAPE_BYTES="$(printf '%s\n' "$OUT" | sed -n 's/^BYTES=//p' | head -1)"
}
probe_integrity(){ SSH_TIMEOUT="$HEAVY_TIMEOUT"; b64_run "$1" "sqlite3 '$3' 'PRAGMA integrity_check;' 2>&1 | head -1" "$2"; INTEGRITY="$(printf '%s' "$OUT" | head -1)"; }
probe_tables(){ b64_run "$1" "sqlite3 '$3' \"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;\" 2>/dev/null || echo TABLE-LIST-UNAVAILABLE" "$2"; TABLES="$OUT"; }
stage_status(){ # read-only, always runs
  hdr "AUTHORITY CUTOVER STATUS (read-only) — $(date -u '+%Y-%m-%dT%H:%M:%SZ')"; local oh ch
  o_run "curl -s -m 6 http://127.0.0.1:8002/health 2>/dev/null | head -c 90 || true"; oh="$(printf '%s' "$OUT" | tr -d '\n')"
  c_run "curl -s -m 6 http://127.0.0.1:8002/health 2>/dev/null | head -c 90 || true"; ch="$(printf '%s' "$OUT" | tr -d '\n')"
  hdr "1. WHO IS SERVING (company API on loopback :8002)"
  info "office $OFFICE_HOST  -> ${oh:-NO ANSWER}"; info "cloud  $CLOUD_HOST   -> ${ch:-NO ANSWER}"
  if [ -n "$oh" ] && [ -z "$ch" ]; then say "  => AUTHORITY IS THE OFFICE BOX ($OFFICE_HOST)"
  elif [ -z "$oh" ] && [ -n "$ch" ]; then say "  => AUTHORITY IS THE CLOUD BOX ($CLOUD_HOST)"
  elif [ -n "$oh" ] && [ -n "$ch" ]; then warn "BOTH answer :8002 — only ONE may own the public path (runbook §2.4)"
  else warn "NEITHER box answers :8002 on loopback"; fi
  hdr "2. DATABASE — size and mtime on both"; o_run "stat -c '%s  %y  %n' '$OFFICE_DB' 2>&1 | head -1; echo -n 'WAL bytes: '; stat -c %s '$OFFICE_DB-wal' 2>/dev/null || echo none"
  say "  office: $(printf '%s' "$OUT" | tr '\n' '|')   (the rollback; this script never writes to it)"
  c_run "stat -c '%s  %y  %n' '$CLOUD_DB' 2>&1 | head -1"; say "  cloud : $OUT"
  hdr "3. WRITERS — who holds the office DB right now (lsof IS the test)"; probe_lsof
  info "lsof lines on $OFFICE_DB: $LSOF_N   (0 == no writer, which is what a freeze must show)"
  info "distinct writer PIDs: ${LSOF_PIDS:-none}"; printf '%s\n' "$LSOF" | head -6 | sed 's/^/      /'
  hdr "4. WRITER UNITS / RESTART PATHS (the set is measured, never assumed)"
  o_run "for u in $WRITERS mesh-broker cloudflared tailscaled; do echo \"  \$u = \$(systemctl is-active \$u 2>&1)\"; done
echo '  --- timers that defeat a freeze ---'; systemctl list-timers --all 2>/dev/null | grep -i secretary || echo '  (none matched)'
echo '  --- crontab restarter ---'; crontab -l 2>/dev/null | grep -n secretary-startup || echo '  (no secretary-startup cron line)'"
  say "$OUT"; say "  -- cloud --"
  c_run "for u in secretary-api secretary-dashboard mesh-broker cloudflared tailscaled; do echo \"  \$u = \$(systemctl is-active \$u 2>&1)\"; done
echo \"  swap devices = \$(swapon --show 2>/dev/null | tail -n +2 | wc -l)\""; say "$OUT"
}
freeze_script(){ cat <<EOF
set -eu
mkdir -p '$OFFICE_DIR'
crontab -l > '$CRONTAB_BAK' 2>/dev/null || echo '(no crontab for this user)'
crontab -l 2>/dev/null | grep -v secretary-startup | crontab - || true
echo "secretary-startup lines remaining: \$(crontab -l 2>/dev/null | grep -c secretary-startup || true)"
$SUDO systemctl stop $TIMERS
$SUDO systemctl mask --now secretary-api.service dialpad-sms-ws.service
$SUDO systemctl stop secretary-dashboard.service phone-engine.service
echo 'freeze command sequence completed'
EOF
}
stage_freeze(){
  hdr "STAGE 4 — FREEZE the writers (runbook §4a-§4d)"
  say "The writer set is DISCOVERED by lsof here, not assumed (runbook §1, §6.9: a transient third"
  say "PID appeared between two reads, so the set is not fixed)."
  probe_lsof; hdr "lsof BEFORE the freeze — raw evidence ($OFFICE_DB)"
  printf '%s\n' "$LSOF"; info "lines: $LSOF_N   pids: ${LSOF_PIDS:-none}"
  say "SUCCESS TEST: lsof empty, then STILL empty after ${CRON_PERIOD}s (one full cron period), with"
  say "an unchanged stat size/mtime across the wait. A systemctl exit code proves nothing."
  say "ROLLBACK: $ROLLBACK_CMD"
  if [ "$CONFIRM" -eq 0 ]; then dry "$(freeze_script)"; return 0; fi
  hdr "Executing the freeze"; o_run "$(freeze_script)"; printf '%s\n' "$OUT"
  [ "$RC" -eq 0 ] || warn "freeze sequence returned rc=$RC — read the output above before trusting anything"
  hdr "lsof AFTER the freeze (read 1 of 2)"; probe_lsof; printf '%s\n' "$LSOF"; L1="$LSOF_N"; info "lines: $L1"
  o_run "stat -c '%s %y' '$OFFICE_DB'"; S1="$OUT"; info "stat: $S1"
  hdr "Waiting one full cron period (${CRON_PERIOD}s) — runbook §4d"; say "'A freeze that survives its own cron is a freeze.'"
  sleep "$CRON_PERIOD"
  hdr "lsof AFTER one full cron period (read 2 of 2)"; probe_lsof; printf '%s\n' "$LSOF"; L2="$LSOF_N"; info "lines: $L2"
  o_run "stat -c '%s %y' '$OFFICE_DB'"; S2="$OUT"; info "stat: $S2"
  hdr "FREEZE VERDICT"; FAILED=0
  [ "$L1" -eq 0 ] && pass "lsof read 1 empty — no process holds the DB" || fail "lsof read 1 still shows $L1 line(s): writers alive"
  [ "$L2" -eq 0 ] && pass "lsof read 2 empty after ${CRON_PERIOD}s — the freeze survived its own cron" || fail "lsof read 2 still shows $L2 line(s): something restarted a writer"
  [ "$S1" = "$S2" ] && pass "stat unchanged across the wait: $S2" || fail "stat CHANGED across the wait: $S1 -> $S2"
  if [ "$FAILED" -eq 0 ]; then say ""; say "FREEZE HOLDS. Next: $0 --stage delta --confirm"
  else warn "FREEZE NOT PROVEN — do not ship. ROLLBACK: $ROLLBACK_CMD"; return 3; fi
}
snapshot_script(){ cat <<EOF
set -eu
mkdir -p '$OFFICE_DIR'
sqlite3 '$OFFICE_DB' 'PRAGMA wal_checkpoint(TRUNCATE);'
sqlite3 -cmd '.timeout 60000' '$OFFICE_DB' ".backup '$OFFICE_FINAL'"
echo "INT=\$(sqlite3 '$OFFICE_FINAL' 'PRAGMA integrity_check;' | head -1)"
echo "MAX=\$(sqlite3 '$OFFICE_FINAL' 'SELECT ifnull(max(rowid),0) FROM dsh_session_events;')"
echo "BYTES=\$(stat -c %s '$OFFICE_FINAL')"
EOF
}
ship_script(){ cat <<EOF
set -eu
mkdir -p '$CLOUD_DIR' 2>/dev/null || true
rsync -a --partial --info=progress2 '$OFFICE_FINAL' $CLOUD_SHIP:'$CLOUD_FINAL' 2>&1 | tail -4
EOF
}
convert_script(){ cat <<EOF
set -eu
[ -f '$FTS_CONVERT' ] || { echo MISSING-CONVERTER; exit 3; }
DB='$CLOUD_FINAL' LOG='$CONVERT_LOG' bash '$FTS_CONVERT' 2>&1 | tail -15
echo '--- verdict ---'; tail -3 '$CONVERT_LOG'
EOF
}
stage_delta(){
  hdr "STAGE 4 — DELTA: .backup snapshot, ship, convert (runbook §4e/§4f)"; say "NOTE: sqlite3 .backup is consistent even on a HOT database, but runbook Stage 4 wants the freeze first; a delta taken while writers run will be behind the frozen source at verify time."
  probe_lsof
  if [ "$LSOF_N" -eq 0 ]; then pass "freeze looks proven (lsof empty)"; else warn "the office DB is STILL HELD by $LSOF_N lsof line(s) — see the note above"; fi
  if [ "$CONFIRM" -eq 0 ]; then dry "$(snapshot_script)"; dry "$(ship_script)"; dry "$(convert_script)"; return 0; fi
  hdr "4e — consistent snapshot on the office box (NEVER a raw cp of a live SQLite file)"
  SSH_TIMEOUT="$HEAVY_TIMEOUT"; o_run "$(snapshot_script)"; printf '%s\n' "$OUT"
  local O_INT O_MAX O_BYTES
  O_INT="$(printf '%s\n' "$OUT" | sed -n 's/^INT=//p')"; O_MAX="$(printf '%s\n' "$OUT" | sed -n 's/^MAX=//p')"
  O_BYTES="$(printf '%s\n' "$OUT" | sed -n 's/^BYTES=//p')"; FAILED=0
  [ "$O_INT" = ok ] && pass "office final.db integrity_check = ok" || fail "office final.db integrity_check = '$O_INT'"
  info "office final.db bytes=$O_BYTES max(rowid)=$O_MAX"
  [ "$FAILED" -eq 0 ] || { warn "snapshot failed — nothing shipped"; return 3; }
  hdr "4f — ship it node-to-node (never through this laptop: that is two hops)"
  o_run "$(ship_script)"; printf '%s\n' "$OUT"
  [ "$RC" -eq 0 ] || warn "rsync returned rc=$RC — a bad ship is silent, so read the byte counts below"
  hdr "4f — verify the shipped copy ON THE NEW BOX"
  probe_shape "$CLOUD_HOST" "$CLOUD_KEY" "$CLOUD_FINAL"; FAILED=0
  if [ "$SHAPE" = DB-MISSING ]; then fail "cloud copy $CLOUD_FINAL is MISSING"; warn "ROLLBACK: $ROLLBACK_CMD"; return 3; fi
  local C_BYTES="$SHAPE_BYTES" C_SHAPE="$SHAPE" C_INT C_TBL C_HITS C_IDS
  probe_integrity "$CLOUD_HOST" "$CLOUD_KEY" "$CLOUD_FINAL"; C_INT="$INTEGRITY"
  probe_tables "$CLOUD_HOST" "$CLOUD_KEY" "$CLOUD_FINAL"; C_TBL="$(printf '%s\n' "$TABLES" | grep -c '[^[:space:]]' || true)"
  IFS='|' read -r _ _ _ _ _ _ C_HITS C_IDS <<<"$C_SHAPE"
  say "  office bytes = $O_BYTES   cloud bytes = $C_BYTES"
  [ "$O_BYTES" = "$C_BYTES" ] && pass "byte count shipped intact ($C_BYTES)" || fail "byte count MISMATCH (office $O_BYTES vs cloud $C_BYTES): truncated in transit"
  [ "$C_INT" = ok ] && pass "cloud integrity_check = ok" || fail "cloud integrity_check = '$C_INT'"
  [ "${C_TBL:-0}" -gt 0 ] && pass "cloud table count = $C_TBL" || fail "cloud table list is empty"
  say "  cloud FTS MATCH '$TERM' hits = $C_HITS   sample rowids = $C_IDS"
  [ "${C_HITS:-0}" -gt 0 ] && pass "search fingerprint non-zero (the index searches)" || fail "search fingerprint is ZERO: the FTS index is broken"
  [ "$FAILED" -eq 0 ] || { warn "SHIP VERIFICATION FAILED — do not convert, do not switch."; warn "ROLLBACK: $ROLLBACK_CMD"; return 3; }
  hdr "4f — convert the shipped copy (never in place on the serving copy)"
  SSH_TIMEOUT="$HEAVY_TIMEOUT"; c_run "$(convert_script)"; printf '%s\n' "$OUT"
  case "$OUT" in *verdict=ok*) pass "fts-convert verdict=ok";; *) fail "fts-convert did not report verdict=ok";; esac
  say ""; say "Next: $0 --stage verify"
}
eq_check(){ if [ "$2" = "$3" ]; then pass "$1: equal ($2)"; else fail "$1: office='$2' cloud='$3'"; fi; }
diff_check(){ # the brief-requested equality tests the runbook overrides; see the header
  say "  $1: office=$2 cloud=$3"
  if [ "$2" = "$3" ]; then pass "$1 equal (the copy is unconverted)"; return 0; fi
  if [ "$3" -lt "$2" ] && [ "$3" -gt $(($2 / 2)) ]; then
    pass "$1 differs as EXPECTED: the conversion reclaims duplicated FTS content (runbook §0/§1)"
  else fail "$1 differs OUTSIDE the expected conversion band (office $2, cloud $3)"; fi
}
stage_verify(){ # read-only, always runs
  hdr "STAGE 5 — VERIFY the final copy against the frozen source (runbook §5)"; local cpath="$CLOUD_FINAL"
  c_run "[ -f '$CLOUD_FINAL' ] && echo present || { [ -f '$CLOUD_DB' ] && echo promoted || echo missing; }"
  case "$OUT" in
    promoted) cpath="$CLOUD_DB"; info "$CLOUD_FINAL is gone (promoted by mv, runbook Stage 5) — comparing $CLOUD_DB";;
    missing)  die "no cloud copy at $CLOUD_FINAL or $CLOUD_DB — run --stage delta --confirm first" 3;;
    *)        info "comparing cloud copy $cpath";;
  esac
  say "source: $OFFICE_HOST:$OFFICE_FINAL (frozen; the rollback) / copy: $CLOUD_HOST:$cpath — this reads both files; integrity_check alone is minutes on 23.5 GB."
  probe_shape "$OFFICE_HOST" "" "$OFFICE_FINAL"
  [ "$SHAPE" = DB-MISSING ] && die "office snapshot $OFFICE_FINAL is missing — run --stage delta --confirm first" 3
  local o_shape="$SHAPE" o_bytes="$SHAPE_BYTES"
  probe_shape "$CLOUD_HOST" "$CLOUD_KEY" "$cpath"
  [ "$SHAPE" = DB-MISSING ] && die "cloud copy $cpath is missing" 3
  local c_shape="$SHAPE" c_bytes="$SHAPE_BYTES"
  probe_integrity "$OFFICE_HOST" "" "$OFFICE_FINAL"; local o_int="$INTEGRITY"
  probe_integrity "$CLOUD_HOST" "$CLOUD_KEY" "$cpath"; local c_int="$INTEGRITY"
  probe_tables "$OFFICE_HOST" "" "$OFFICE_FINAL"; local o_tables="$TABLES"
  probe_tables "$CLOUD_HOST" "$CLOUD_KEY" "$cpath"; local c_tables="$TABLES"
  local o_ps o_pc o_tbl o_rows o_sum o_max o_hits o_ids c_ps c_pc c_tbl c_rows c_sum c_max c_hits c_ids
  IFS='|' read -r o_ps o_pc o_tbl o_rows o_sum o_max o_hits o_ids <<<"$o_shape"
  IFS='|' read -r c_ps c_pc c_tbl c_rows c_sum c_max c_hits c_ids <<<"$c_shape"
  FAILED=0
  hdr "Checks — runbook §5 SUCCESS list (hard), then the brief's EXPECTED-DIFF pair"
  eq_check "integrity_check" "$o_int" "$c_int"; eq_check "page_size" "$o_ps" "$c_ps"
  eq_check "dsh_session_events count(*)" "$o_rows" "$c_rows"; eq_check "dsh_session_events sum(length(raw))" "$o_sum" "$c_sum"
  eq_check "dsh_session_events max(rowid)" "$o_max" "$c_max"; eq_check "FTS MATCH '$TERM' hit count" "$o_hits" "$c_hits"
  eq_check "FTS sample rowids" "$o_ids" "$c_ids"
  [ "$((o_pc * o_ps))" = "$o_bytes" ] && pass "office page_count x page_size == file size ($o_bytes)" || fail "office page geometry != file size (truncated in transit, runbook §5.4)"
  [ "$((c_pc * c_ps))" = "$c_bytes" ] && pass "cloud page_count x page_size == file size ($c_bytes)" || fail "cloud page geometry != file size (truncated in transit, runbook §5.4)"
  local tdir tdiff nlines; tdir="$(mktemp -d "$TMPD/cutover-tbl.XXXXXX")"
  printf '%s\n' "$o_tables" >"$tdir/src.txt"; printf '%s\n' "$c_tables" >"$tdir/conv.txt"
  tdiff="$(diff "$tdir/src.txt" "$tdir/conv.txt" || true)"; nlines="$(printf '%s\n' "$tdiff" | grep -c '^[<>]' || true)"
  say "  table count: office=$o_tbl cloud=$c_tbl   table-list diff lines=$nlines"
  if [ -z "$tdiff" ]; then pass "table list identical ($o_tbl tables)"
  elif [ "$nlines" -eq 1 ] && printf '%s' "$tdiff" | grep -q "^< $MARK"; then
    pass "table list differs by exactly the ONE named line: '< $MARK' (runbook §0/§5, expected)"
  else fail "table-list diff is not the single expected line — unexplained schema change (runbook §5.2)"
    printf '%s\n' "$tdiff" | head -10 | sed 's/^/        /'; fi
  rm -f "$tdir/src.txt" "$tdir/conv.txt"; rmdir "$tdir" 2>/dev/null || true
  hdr "The two brief-requested comparisons the runbook says are NOT equal"; diff_check "file byte count" "$o_bytes" "$c_bytes"; diff_check "PRAGMA page_count" "$o_pc" "$c_pc"
  hdr "STAGE 5 VERDICT"
  if [ "$FAILED" -eq 0 ]; then say "  ALL CHECKS PASS — nothing points at the copy yet; that is Stage 6."
  else say "  $FAILED CHECK(S) FAILED — DO NOT SWITCH."; say "  ROLLBACK: $ROLLBACK_CMD"; return 4; fi
}
api_script(){ cat <<'EOF'
set -eu
U=/etc/systemd/system/secretary-api.service
[ -f "$U" ] || { echo MISSING-UNIT; exit 3; }
sed -i 's|--host 0.0.0.0|--host 127.0.0.1|' "$U"
grep -n -- --host "$U" || true
systemctl daemon-reload; systemctl start secretary-api; sleep 20
echo -n 'loopback health: '; curl -s -m 10 http://127.0.0.1:8002/health || true; echo
EOF
}
tunnel_stop_script(){ cat <<EOF
set -eu
$SUDO systemctl stop cloudflared; sleep 2
echo -n 'office cloudflared is now: '; systemctl is-active cloudflared 2>&1 || true
EOF
}
stage_switch(){
  hdr "STAGE 6 — THE SWITCH (runbook §6a-§6d)"
  say "6a loopback API | 6b canary write | 6c tailnet publish | 6d tunnel LAST, never two connectors"
  if [ "$CONFIRM" -eq 0 ]; then
    dry "$(api_script)"
    say "then, in order: canary POST (CUTOVER_CANARY_URL) + max(rowid) compared on both boxes; cloud:"
    say "tailscale serve --bg --https=443 http://127.0.0.1:8002; office: stop cloudflared and PROVE it"
    say "inactive BEFORE the cloud connector starts; only then scp the tunnel config + json across and"
    say "start the cloud connector. ROLLBACK: $ROLLBACK_CMD"; return 0
  fi
  hdr "6a — the new API, LOOPBACK only (runbook §2.5: the office unit says 0.0.0.0)"
  c_run "$(api_script)"; printf '%s\n' "$OUT"; FAILED=0
  case "$OUT" in *'"ok":true'*) pass "cloud API answers on its own loopback";; *) fail "cloud API did not answer ok on loopback — STOP";; esac
  [ "$FAILED" -eq 0 ] || { warn "ROLLBACK: $ROLLBACK_CMD"; return 4; }
  hdr "6b — a write on the new authority, and proof the office box did not move"
  c_run "sqlite3 '$CLOUD_DB' 'SELECT ifnull(max(rowid),0) FROM dsh_session_events;'"; local c1="$OUT"
  o_run "sqlite3 '$OFFICE_DB' 'SELECT ifnull(max(rowid),0) FROM dsh_session_events;'"; local o1="$OUT"
  info "cloud max(rowid)=$c1   office max(rowid)=$o1"
  if [ -n "${CUTOVER_CANARY_URL:-}" ]; then
    c_run "curl -s -m 10 -X POST '$CUTOVER_CANARY_URL' >/dev/null 2>&1 || true
sqlite3 '$CLOUD_DB' 'SELECT ifnull(max(rowid),0) FROM dsh_session_events;'"
    info "cloud max(rowid) after canary=$OUT (must have ADVANCED)"
  else warn "no canary endpoint: runbook 6b needs '<a-real-write-endpoint>'. Set CUTOVER_CANARY_URL to"
       warn "a real write endpoint to complete 6b; the read-only half above proves nothing on its own."; fi
  o_run "sqlite3 '$OFFICE_DB' 'SELECT ifnull(max(rowid),0) FROM dsh_session_events;'"
  if [ "$OUT" = "$o1" ]; then pass "office max(rowid) unchanged ($o1) — the freeze held"
  else fail "office max(rowid) MOVED ($o1 -> $OUT): a writer survived, stop and re-read runbook §2.2"; warn "ROLLBACK: $ROLLBACK_CMD"; return 4; fi
  hdr "6c — publish on the tailnet first (DNS-free and instantly reversible)"
  c_run "tailscale serve --bg --https=443 http://127.0.0.1:8002 2>&1 | tail -2; sleep 3; curl -s -m 10 https://secratary-cloud.tail93e6e6.ts.net/health || true"
  printf '%s\n' "$OUT"
  case "$OUT" in *'"ok":true'*) pass "tailnet URL answers";; *) warn "tailnet URL did not answer ok — do not move the public tunnel until it does";; esac
  hdr "6d — the Cloudflare tunnel LAST, and NEVER with two connectors (runbook §2.4)"
  o_run "$(tunnel_stop_script)"; printf '%s\n' "$OUT"
  if printf '%s' "$OUT" | grep -q 'is now: active'; then
    warn "office cloudflared is STILL ACTIVE. Two connectors round-robin the public hostname between two databases. ABORTED before the cloud connector starts."
    warn "ROLLBACK: $ROLLBACK_CMD"; return 4; fi
  pass "office cloudflared stopped and proven inactive — the public hostname is unserved"
  say "THE SHARP EDGE (runbook §6): this tunnel also serves dialer., secretary-ssh. and the /phone redirector, whose backends STAY on the office box. Create a SECOND tunnel for api./ai. plus a DNS record change (the owner's step; write the old record down as the rollback) or move those backends too. DO NOT do a partial config move and call it done."
  say "Then, by hand: scp $OFFICE_HOST:/etc/cloudflared/config.yml /tmp/cloudflared.new.yml ; scp $OFFICE_HOST:/home/zabz/.cloudflared/829bc0fb-30f9-4244-b2ea-14fbb61a2753.json $CLOUD_HOST:/root/.cloudflared/ ; $CLOUD_HOST: systemctl start cloudflared && curl -s -m 10 https://api.abletelsolutions.com/health"
  say "SUCCESS: /health ok from the cloud loopback; the canary advanced the cloud max(rowid) while the office's stayed put; the tailnet URL answers; the public URL answers with a fresh canary visible through it; office cloudflared inactive."
  warn "The office connector is STOPPED, so the company is UNREACHABLE on the public hostname right now. Finish the DNS decision and start the cloud connector, or roll back. $ROLLBACK_CMD"
}
cloud_stop_script(){ cat <<EOF
$SUDO systemctl stop secretary-api 2>/dev/null || true
$SUDO systemctl stop cloudflared 2>/dev/null || true
tailscale serve --https=443 off 2>&1 | tail -1 || true
for u in secretary-api cloudflared; do echo "  \$u = \$(systemctl is-active \$u 2>&1)"; done
EOF
}
restore_script(){ cat <<EOF
set -eu
$SUDO systemctl unmask secretary-api.service dialpad-sms-ws.service
$SUDO systemctl start cloudflared secretary-api secretary-dashboard phone-engine dialpad-sms-ws
if [ -f '$CRONTAB_BAK' ]; then crontab '$CRONTAB_BAK' && echo 'crontab restored'; else echo "NO crontab backup at $CRONTAB_BAK: the */5 restarter is still stripped"; fi
for u in $WRITERS cloudflared; do echo "  \$u = \$(systemctl is-active \$u 2>&1)"; done
EOF
}
stage_rollback(){
  hdr "ROLLBACK — office box back in charge (runbook Stage 4 / Stage 6 ROLLBACK)"
  say "ORDER MATTERS: the cloud stops first, then the office restarts. This script never wrote to the"
  say "office DB, so it is still the authority it was. RTO 2-5 min."
  if [ "$CONFIRM" -eq 0 ]; then dry "$(cloud_stop_script)"; dry "$(restore_script)"
    say "then prove it: curl the office loopback /health and re-read lsof."; return 0; fi
  hdr "1-2 — stop the cloud side first"; c_run "$(cloud_stop_script)"; printf '%s\n' "$OUT"
  hdr "3-5 — restore the office box"; o_run "$(restore_script)"; printf '%s\n' "$OUT"
  hdr "6 — prove the office is serving again"; sleep 20
  o_run "echo -n 'office loopback health: '; curl -s -m 10 http://127.0.0.1:8002/health || true; echo"
  printf '%s\n' "$OUT"
  case "$OUT" in *'"ok":true'*) pass "office API answers — rollback complete (RTO 2-5 min)";;
    *) warn "office API has not answered yet; secretary-api boot is 2-4 min by its own unit comment (TimeoutStartSec=600). Re-check: $0 --stage status";; esac
  probe_lsof; info "office lsof lines now: $LSOF_N (writers back is expected after a rollback)"
  say ""; say "Then: $0 --stage status"
}
main(){ # a bare invocation is REFUSED; there is no default stage
  local STAGE="" CONFIRM=0 STAGES="status|freeze|delta|verify|switch|rollback"
  while [ $# -gt 0 ]; do
    case "$1" in
      --stage) [ $# -ge 2 ] || { usage >&2; die "--stage needs a value" 2; }; STAGE="$2"; shift 2 ;;
      --stage=*) STAGE="${1#*=}"; shift ;;
      --confirm|-y) CONFIRM=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) usage >&2; die "unknown argument: $1" 2 ;;
    esac
  done
  [ -n "$STAGE" ] || { usage >&2; die "no --stage given. This script refuses to guess: pass --stage <$STAGES>" 2; }
  say "cutover-authority.sh | stage=$STAGE confirm=$CONFIRM | runbook docs/mesh/126-authority-cutover-runbook.md"
  say "RPO: up to 24 h standing; writes during the freeze are LOST (~0.70 MB/min)."
  say "RTO: 2-5 min rollback while the office file is untouched."
  case "$STAGE" in
    status) stage_status ;; freeze) stage_freeze ;; delta) stage_delta ;;
    verify) stage_verify ;; switch) stage_switch ;; rollback) stage_rollback ;;
    *) usage >&2; die "unknown stage: $STAGE" 2 ;;
  esac
}
main "$@"
