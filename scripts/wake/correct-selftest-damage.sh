set -u
W=/home/zabz/bin/wake.py
D=/home/zabz/.sms-inbox/inbox.db

echo "=== BEFORE ==="
sqlite3 -readonly "$D" "select id,state,attempts,substr(subject,1,40) from wake where id in (158,161,162);"

# 1. RESTORE TRUTH on the real subject my selftest marked done. The work was never done; the subject must be
#    claimable again. The outcome line says who did it and why, so a reader never has to guess.
sqlite3 "$D" "update wake set state='new', finished_at=NULL, claimed_by=NULL, claimed_at=NULL, lease_until=NULL, outcome='CORRECTED 2026-09-30: this real subject was marked done by a verification script whose claim call took the next eligible row instead of its own test subject. The work was never done. Restored to new so it is claimed and performed.' where id=158 and subject like 'project:housekeeping%';"

# 2. STOP THE JUNK. Two selftest subjects were left live and the dispatcher would have spent releases on
#    them. A non-transient outcome on purpose, so the retryable classifier does NOT refund them.
python3 "$W" finish 161 --failed --outcome "selftest artefact, not real work - created by a verification script and never cleaned up. Not retryable by design; this subject is closed on purpose." >/dev/null 2>&1 || true
python3 "$W" finish 162 --failed --outcome "selftest artefact, not real work - created by a verification script and never cleaned up. Not retryable by design; this subject is closed on purpose." >/dev/null 2>&1 || true

echo "=== AFTER ==="
sqlite3 -readonly "$D" "select id,state,attempts,substr(subject,1,40) from wake where id in (158,161,162);"
echo "=== no selftest subject may be left claimable ==="
sqlite3 -readonly "$D" "select count(*) from wake where state in ('new','claimed') and subject like 'retryable-selftest%';"
echo "=== and no NON-test subject may be sitting done by my hand ==="
sqlite3 -readonly "$D" "select count(*) from wake where state='done' and outcome like 'CORRECTED%';"
