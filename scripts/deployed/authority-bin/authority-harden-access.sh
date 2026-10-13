#!/usr/bin/env bash
# authority-harden-access.sh ? make sure the estate's own traffic can never lock itself out again.
#
# THE INCIDENT THIS PREVENTS (2026-10-11): the estate lost ssh to its own authority for over an hour.
# The cause was NOT fail2ban and NOT the key - `/root` had been left mode 777, and OpenSSH with
# StrictModes refuses every authentication, key and password alike, from a world-writable home
# directory. That is fixed. But a burst of ~25 short-lived connections from this estate had also
# started to look like the brute-force this public box genuinely receives (11,671 failed password
# attempts in 24 h), so the estate's own addresses belong in fail2ban's ignoreip.
#
# IT DOES NOT TRUST ITSELF TO GUESS THE ADDRESSES. It reads the addresses that have actually
# authenticated successfully from outside, DERIVES the /24s they came from, prints what it found, and
# only then writes the config - and it never removes an existing ignoreip entry.
set -uo pipefail

JAIL=/etc/fail2ban/jail.local
STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
SELF_IPS="$(hostname -I | tr ' ' '\n' | grep -v '^$' | grep -v '^127\.' | sort -u)"

echo "== 0. this host's own addresses (never ignored: they cannot ssh in from outside)"
echo "$SELF_IPS" | sed 's/^/   /'

echo "== 1. addresses that have successfully authenticated recently =="
SUCCESS_IPS="$(journalctl -u ssh --since '30 days ago' --no-pager 2>/dev/null \
  | grep -E 'Accepted (publickey|password)' \
  | grep -oE 'from [0-9]{1,3}(\.[0-9]{1,3}){3}' | awk '{print $2}' | sort -u)"
if [ -z "$SUCCESS_IPS" ]; then
  echo "   (none in this journal window; falling back to the current ssh peers)"
  SUCCESS_IPS="$(ss -tnp 2>/dev/null | awk '$5 ~ /:22$/ {print $5}' | cut -d: -f1 | sort -u)"
fi
echo "$SUCCESS_IPS" | sed 's/^/   /'

# Derive the /24 of each external, successful address. A residential uplink changes its last octet
# and sometimes more; /24 is the narrowest range that survives an ordinary ISP lease change.
DERIVED="$(echo "$SUCCESS_IPS" | grep -E '^[0-9]' | while read -r ip; do
  case "$SELF_IPS" in *"$ip"*) continue ;; esac
  echo "$ip" | awk -F. '{printf "%s.%s.%s.0/24\n", $1, $2, $3}'
done | sort -u)"
echo "== 2. derived ranges to ignore =="
[ -n "$DERIVED" ] && echo "$DERIVED" | sed 's/^/   /' || echo "   (none derived - nothing will be added)"

echo "== 3. current ignoreip =="
EXISTING="$(fail2ban-client get sshd ignoreip 2>/dev/null \
  | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?' | sort -u | tr '\n' ' ')"
# ONLY addresses and CIDRs. Measured 2026-10-11: the client prints a human sentence ("These IP
# addresses/networks are ignored:") and a first version of this script fed that prose straight back
# into ignoreip, producing a config that parsed into garbage entries.
echo "   ${EXISTING:-<none>}"

if [ -z "$DERIVED" ] && [ -z "$EXISTING" ]; then
  echo "== nothing to write (no ranges derived and none configured). Nothing changed. =="
  exit 0
fi

echo "== 4. writing $JAIL (existing entries kept, backup taken) =="
[ -f "$JAIL" ] && cp -a "$JAIL" "$JAIL.before-$STAMP"
{
  echo "# Written $(date -u '+%Y-%m-%dT%H:%M:%SZ') by authority-harden-access.sh."
  echo "# WHY: on 2026-10-11 the estate locked itself out of its own authority. The root cause was a"
  echo "# world-writable /root refusing every ssh authentication under StrictModes; the ignoreip list"
  echo "# below is the second half of the fix, so that legitimate agent traffic - which is bursty by"
  echo "# nature - can never be mistaken for the brute force this public host receives."
  echo "# The ranges were DERIVED from addresses that actually authenticated successfully, not guessed."
  echo "# ONE ignoreip LINE: fail2ban refuses a duplicate option in a section, so the addresses are"
  echo "# space-separated on a single line (measured 2026-10-11: 'option ignoreip already exists')."
  echo "[DEFAULT]"
  {
    [ -n "$EXISTING" ] && for ip in $EXISTING; do echo "$ip"; done
    echo "$DERIVED"
  } | sort -u | grep -v '^$' | tr '\n' ' ' | sed 's/ *$//' | sed 's/^/ignoreip = /' | sed 's/$/\n/'
  echo "bantime  = 1h"
  echo "findtime = 10m"
  echo "maxretry = 8"
  echo
  echo "[sshd]"
  echo "enabled  = true"
  echo "backend  = systemd"
  echo "journalmatch = _SYSTEMD_UNIT=ssh.service + _COMM=sshd"
} > "$JAIL"

echo "== 5. reload and verify =="
fail2ban-client reload 2>&1 | tail -2
sleep 2
echo "   jails: $(fail2ban-client status 2>/dev/null | grep 'Jail list' | sed 's/.*://')"
echo "   ignoreip now:"
fail2ban-client get sshd ignoreip 2>/dev/null | sed 's/^/     /'
echo "   currently banned: $(fail2ban-client banned 2>/dev/null)"
echo
echo "== 6. the other half of the fix: a SECOND key and a guard on the file =="
ls -la /root/.ssh/authorized_keys
echo "   keys in the file:"
ssh-keygen -l -f /root/.ssh/authorized_keys 2>&1 | sed 's/^/     /'
echo "   /root mode: $(stat -c '%a' /root)  (must be 700: 777 is what broke ssh)"
