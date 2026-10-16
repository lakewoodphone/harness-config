#!/bin/bash
# R7-JOURNAL-MERGE step 2: collect all five machine journal trees onto the authority.
# NOTHING here writes to a live journal tree: every tar is READ-ONLY on the source.
set -u
R7=/root/work/r7
LOG="$R7/logs/collect.log"
mkdir -p "$R7/trees" "$R7/manifests" "$R7/logs"
: > "$LOG"
say(){ echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }

SSH="ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o StrictHostKeyChecking=accept-new"

say "AUTHORITY SELF-TEST"
hostname
df -Pk / | tail -1

say "cloud (authority, local tar)"
tar -cf "$R7/trees/cloud.tar" -C /root/code/harness-config journal \
  && say "cloud.tar $(stat -c %s "$R7/trees/cloud.tar") bytes"

say "yoga via zabz-yoga-ts"
$SSH zabz-yoga-ts "tar -cf - -C C:/Users/ezabz/code/harness-config journal" \
  > "$R7/trees/yoga.tar" 2> "$R7/logs/yoga.err"
say "yoga.tar $(stat -c %s "$R7/trees/yoga.tar") bytes err=[$(head -c 300 "$R7/logs/yoga.err" | tr '\n' ' ')]"

say "tech via zabz-tech"
$SSH zabz-tech "tar -cf - -C C:/Users/ezabz/code/harness-config journal" \
  > "$R7/trees/tech.tar" 2> "$R7/logs/tech.err"
say "tech.tar $(stat -c %s "$R7/trees/tech.tar") bytes err=[$(head -c 300 "$R7/logs/tech.err" | tr '\n' ' ')]"

say "linux via linux-pc-ts"
$SSH linux-pc-ts "tar -cf - -C /home/zabz/code/harness-config journal" \
  > "$R7/trees/linux.tar" 2> "$R7/logs/linux.err"
say "linux.tar $(stat -c %s "$R7/trees/linux.tar") bytes err=[$(head -c 300 "$R7/logs/linux.err" | tr '\n' ' ')]"

say "mac via -l lpt mac-mini-ts"
$SSH -l lpt mac-mini-ts "tar -cf - -C /Users/lpt/code/harness-config journal" \
  > "$R7/trees/mac.tar" 2> "$R7/logs/mac.err"
say "mac.tar $(stat -c %s "$R7/trees/mac.tar") bytes err=[$(head -c 300 "$R7/logs/mac.err" | tr '\n' ' ')]"

say "EXTRACT"
for n in cloud yoga tech linux mac; do
  mkdir -p "$R7/trees/$n"
  if tar -xf "$R7/trees/$n.tar" -C "$R7/trees/$n"; then
    c=$(find "$R7/trees/$n/journal/entries" -type f -name '*.md' 2>/dev/null | wc -l)
    ids=$(grep -rhoP '(?<=<!-- e:)[a-z]+\|[A-Za-z0-9]+' "$R7/trees/$n/journal/entries" 2>/dev/null | wc -l)
    uids=$(grep -rhoP '(?<=<!-- e:)[a-z]+\|[A-Za-z0-9]+' "$R7/trees/$n/journal/entries" 2>/dev/null | sort -u | wc -l)
    say "$n extracted: files=$c markers=$ids unique_ids=$uids"
  else
    say "$n EXTRACT FAILED"
  fi
done
say "DONE"
df -Pk / | tail -1
