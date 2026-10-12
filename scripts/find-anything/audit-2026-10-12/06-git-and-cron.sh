#!/usr/bin/env bash
# 06-git-and-cron.sh -- two checks that are cheap, mechanical, and were both wrong by hand:
#
#   (a) WOULD A PUSH FAST-FORWARD, OR HAS THE CLONE DIVERGED?
#       Measured 2026-10-12 on the authority: 95 commits only there, 2 only on GitHub. Neither clone's
#       push is a fast-forward, and the tempting command is a force push, which is how work is lost.
#       This prints the count on both sides and says plainly whether a push is safe.
#       (The divergence is already journal P3135 -- this script is how you re-measure it, not news.)
#
#   (b) DO MY SCHEDULED MINUTES COLLIDE WITH ANOTHER JOB'S?
#       Measured 2026-10-12: the first search-index refresh fragment used `*/15`, colliding with a
#       pre-existing `journal-commit */15`. The index builder calls `journal.py status`, which rebuilds
#       the journal cache; two rebuilds on one minute measured `ps_search what=journal` at 21,902 ms
#       against a 5 s budget. This is how you find that before it happens rather than after.
#
# READ-ONLY: it fetches into a remote-tracking ref (working tree untouched) and reads the crontab.
set -uo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")" || exit 1

GH="${HARNESS_GITHUB:-https://github.com/lakewoodphone/harness-config.git}"
echo "############ (a) is a push a fast-forward? ############"
echo "  repo: $(pwd)"
echo "  HEAD: $(git log --oneline -1 2>/dev/null)"
if timeout 60 git fetch --quiet "$GH" main:refs/remotes/ghprobe/main 2>/dev/null; then
  echo "  GitHub main: $(git log --oneline -1 refs/remotes/ghprobe/main)"
  counts=$(git rev-list --left-right --count HEAD...refs/remotes/ghprobe/main 2>/dev/null)
  only_here=$(echo "$counts" | awk '{print $1}')
  only_gh=$(echo "$counts" | awk '{print $2}')
  echo "  commits only here: $only_here    commits only on GitHub: $only_gh"
  if git merge-base --is-ancestor HEAD refs/remotes/ghprobe/main 2>/dev/null; then
    echo "  VERDICT: HEAD is BEHIND -> a pull fast-forwards; a push would be rejected. Do not force."
  elif git merge-base --is-ancestor refs/remotes/ghprobe/main HEAD 2>/dev/null; then
    echo "  VERDICT: push fast-forwards. Safe to commit and push from here."
  else
    echo "  VERDICT: DIVERGED. Do NOT force. Converge deliberately, with someone who knows what the"
    echo "           $only_here commits are. Both trees carrying the same content is not the same as"
    echo "           the same history, and a merge will show it."
  fi
else
  echo "  FETCH FAILED -- cannot judge. That is not 'in sync'; it is 'unknown'."
fi

echo
echo "############ (b) do my cron minutes collide? ############"
crontab -l 2>/dev/null > /tmp/_cron.$$ || { echo "  no crontab"; exit 0; }
python3 - /tmp/_cron.$$ <<'PY'
import re, sys
MINE = {"fa-index-refresh", "fa-index-freshness", "tool-body-guard"}

def minutes(spec):
    if spec == "*":
        return set(range(60))
    if spec.startswith("*/"):
        return set(range(0, 60, int(spec[2:])))
    out = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out |= set(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.add(int(part))
    return out

rows = []
for line in open(sys.argv[1]):
    line = line.rstrip("\n")
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    f = line.split()
    if len(f) < 6:
        continue
    m = re.search(r"cron-wrap\.sh\s+(\S+)", line)
    name = m.group(1) if m else "(unwrapped)"
    try:
        rows.append((name, minutes(f[0]), line))
    except ValueError:
        continue

found = [r for r in rows if r[0] in MINE]
if not found:
    print("  none of the search clocks are installed on this host")
for name, mins, _ in found:
    clashes = sorted({o for o, om, _ in rows if o != name and (om & mins)})
    print(f"  {name:20s} minutes={sorted(mins)}")
    if clashes:
        print(f"      COLLIDES WITH: {clashes}")
        print("      If any of those rebuilds the same artefact, expect a latency spike under load.")
    else:
        print("      collides with: nothing")
# The every-minute jobs collide by definition; say so rather than crying wolf.
allmin = [n for n, m, _ in rows if len(m) == 60]
if allmin:
    print(f"  (jobs on `* * * * *` collide with everything by construction: {allmin})")
PY
rm -f /tmp/_cron.$$
exit 0
