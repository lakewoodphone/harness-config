#!/usr/bin/env bash
# Keep the shop review surface current: group, capture stills, record clips.
#
# Runs on a timer because every piece of this page is derived: visits are grouped from raw
# signals, pictures are captured when a visit appears, clips are recorded while a visit is
# happening. None of those can happen after the fact — a clip especially, since camera.record
# only records forward. A manual run means the page silently freezes, which is exactly the
# failure mode this estate keeps repeating.
#
# Order matters: grouping first (so there are visits to work on), then stills, then clips.
# Every step is idempotent, so a rerun costs nothing.
set -uo pipefail
cd /opt/company || exit 1

PY=/opt/company/.venv/bin/python
export PYTHONPATH=/opt/company

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

log "grouping recent signals"
"$PY" /root/shop-visits.py --rebuild --since 8h 2>&1 | tail -3

# after grouping, because --rebuild deletes and re-inserts the window, taking `subjects` with it
log "naming visits from the access log"
"$PY" /root/shop-attribute.py --since 12h 2>&1 | tail -2

log "capturing stills for new visits"
"$PY" /root/shop-capture.py --since 8h 2>&1 | tail -4

log "recording clips for visits happening now"
"$PY" /root/shop-clip.py --recent 4 2>&1 | tail -4

echo "[$(date -u +%H:%M:%S)] done"
