#!/usr/bin/env bash
# transcript-archive-pass.sh -- one scheduled pass of the permanent transcript archive, on the
# authority. Deployed from harness-config/scripts/transcript-archive-run.sh.
#
# WHY IT LIVES ON secratary-cloud: AGENTS.md §1 says the pull is driven from the machine that is
# always on, because a workstation-side scheduler cannot tell "nothing to send" from "I am broken"
# (measured 2026-10-09: PersonalSecretary-PushVSCodeChats reported LastTaskResult=0 every hour for
# 21 days while the Copilot archive stood still). Until 2026-10-11 that machine was the office box;
# the authority cutover moved it here.
set -uo pipefail

export HOME=/root
export TRANSCRIPT_ARCHIVE_ROOT=/opt/company/archive/lpt-transcripts
export TRANSCRIPT_SCRIPTS=/opt/company/archive/tools
export TRANSCRIPT_STATE_DIR=/var/lib/transcript-archive
export TRANSCRIPT_JOURNAL=/opt/company/archive/tools/journal.py
export TRANSCRIPT_MAX_BYTES="${TRANSCRIPT_MAX_BYTES:-500000000}"
export TRANSCRIPT_ROUNDS="${TRANSCRIPT_ROUNDS:-3}"
export TRANSCRIPT_MACHINES="${TRANSCRIPT_MACHINES:---all}"

mkdir -p "$TRANSCRIPT_STATE_DIR" "$TRANSCRIPT_ARCHIVE_ROOT/logs" "$TRANSCRIPT_ARCHIVE_ROOT/incoming"

bash "$TRANSCRIPT_SCRIPTS/transcript-archive-run.sh"
rc=$?
echo "transcript-archive-pass: run.sh exit=$rc at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Spool hygiene. Each pass leaves the tar it pulled in incoming/; nothing else prunes it, so with a
# 500 MB cap and five machines an unpruned spool is ~2.5 GB of a 75 GB disk. A tar is removed ONLY
# when the manifest records a successful ingest of that exact tar basename -- never on age, never
# when an ingest failed, and never before the objects are in the content-addressed store.
python3 - "$TRANSCRIPT_ARCHIVE_ROOT" <<'PY'
import os, sqlite3, sys
root = sys.argv[1]
spool = os.path.join(root, "incoming")
db = os.path.join(root, "manifest.sqlite")
if not os.path.isdir(spool) or not os.path.exists(db):
    sys.exit(0)
conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
done = {r[0] for r in conn.execute("SELECT DISTINCT tar_basename FROM ingest_run WHERE ok=1 AND tar_basename IS NOT NULL")}
freed = 0
for name in sorted(os.listdir(spool)):
    if not name.endswith(".tar") or name not in done:
        continue
    p = os.path.join(spool, name)
    try:
        n = os.path.getsize(p)
        os.unlink(p)
        freed += n
        print(f"spool: removed {name} ({n} bytes) -- its ingest is recorded ok=1")
    except OSError as exc:
        print(f"spool: could not remove {name}: {exc}")
print(f"spool: freed {freed} bytes")
PY
exit "$rc"
