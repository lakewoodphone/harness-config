#!/usr/bin/env python3
"""Capture one still per camera into security_evidence. Needs no device credential.

The camera's own burned-in stamp is NOT trusted for time: captured_at comes from this host's
clock, and the camera's last measured offset is carried alongside it (see schema/02-evidence.sql).

A failed capture writes a row with result != 'ok' and the verbatim detail. It never writes nothing:
an absent row and a row saying http_500 are different facts, and only one of them is honest.

usage: security-capture.py <camera_entity> [door_id] [event_id] [entry_id]
"""
import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DB = '/root/authority.db'
ENV_FILE = '/opt/company/.env'
ROOT = '/root/security-evidence'


def env(key):
    try:
        with open(ENV_FILE) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                if k.strip().upper() == key:
                    return v.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def last_offset(conn, camera_id):
    row = conn.execute(
        'select offset_s, measured_at from camera_clock where camera_id = ? '
        'order by measured_at desc limit 1', (camera_id,)).fetchone()
    return (row[0], row[1]) if row else (None, None)


def capture(camera_id, door_id=None, event_id=None, entry_id=None):
    ha = (env('HA_URL') or '').rstrip('/')
    token = env('HA_TOKEN')
    if not ha or not token:
        raise SystemExit('HA_URL or HA_TOKEN missing from %s' % ENV_FILE)

    now = datetime.now(timezone.utc)
    local = datetime.now().astimezone()
    stamp = now.strftime('%Y%m%dT%H%M%SZ')
    short = camera_id.split('.')[-1]

    result, detail, path, sha, nbytes = 'ok', None, None, None, None
    try:
        req = Request('%s/api/camera_proxy/%s' % (ha, camera_id),
                      headers={'Authorization': 'Bearer %s' % token})
        with urlopen(req, timeout=25) as resp:
            data = resp.read()
            ctype = resp.headers.get('Content-Type', '')
        if not data:
            raise ValueError('empty body')
        if 'image' not in ctype.lower():
            raise ValueError('unexpected content-type %r' % ctype)
        day = os.path.join(ROOT, now.strftime('%Y/%m/%d'))
        os.makedirs(day, exist_ok=True)
        path = os.path.join(day, '%s-%s.jpg' % (now.strftime('%H%M%S'), short))
        with open(path, 'wb') as fh:
            fh.write(data)
        sha = hashlib.sha256(data).hexdigest()
        nbytes = len(data)
    except HTTPError as exc:
        result, detail = 'http_%s' % exc.code, str(exc)
    except URLError as exc:
        result, detail = 'timeout', str(exc)
    except Exception as exc:                                    # noqa: BLE001
        result, detail = 'no_frame', '%s: %s' % (type(exc).__name__, exc)

    conn = sqlite3.connect(DB, timeout=20)
    try:
        offset, measured = last_offset(conn, camera_id)
        row_id = 'ev-%s-%s' % (stamp, short)
        conn.execute(
            'insert or replace into security_evidence (id, event_id, entry_id, door_id, camera_id,'
            ' captured_at, captured_at_local, osd_offset_s, osd_measured_at, path, sha256, bytes,'
            ' source_host, result, detail, created_at)'
            ' values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (row_id, event_id, entry_id, door_id, camera_id,
             now.strftime('%Y-%m-%dT%H:%M:%SZ'), local.strftime('%Y-%m-%dT%H:%M:%S%z'),
             offset, measured, path, sha, nbytes,
             os.uname().nodename, result, detail, now.strftime('%Y-%m-%dT%H:%M:%SZ')))
        conn.commit()
        print('%-46s %-9s %s' % (camera_id, result, ('%s bytes %s' % (nbytes, sha[:16])) if sha else detail or ''))
        print('  row: %s' % row_id)
    finally:
        conn.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    capture(sys.argv[1],
            sys.argv[2] if len(sys.argv) > 2 else None,
            sys.argv[3] if len(sys.argv) > 3 else None,
            sys.argv[4] if len(sys.argv) > 4 else None)
