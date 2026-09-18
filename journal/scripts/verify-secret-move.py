#!/usr/bin/env python3
"""verify-secret-move.py - prove a secret moved between config layers is byte-identical.

Written 2026-09-15 while moving the waze-mdm fleet-dashboard bcrypt hash out of a
bind-mounted Caddyfile into the container environment (journal: lessons L1599/L1600,
handoff H293). It exists because every shortcut below makes an unapplied or corrupted
change look verified:

  * Docker Compose interpolates .env values. A bare `VAR=$2a$14$...` in .env loses
    everything from `$ABC...` onward. Values containing `$` must be single-quoted.
  * `docker compose config` renders `$` back as `$$`, so comparing its output with the
    .env value reports a false MISMATCH. Unescape before comparing.
  * A bind-mounted single file is pinned to an inode: `sed -i`, `install` and `mv` write
    a NEW file and the container keeps serving the old one. Write in place and then
    `docker compose up -d --force-recreate <svc>`; a plain `up -d` does nothing, and
    `validate`/`reload` would validate the old file.
  * `caddy:2` has no ENTRYPOINT, so `docker run caddy:2 validate ...` fails; use
    `docker run caddy:2 caddy validate ...`.
  * Caddy's admin API answers on 127.0.0.1:2019 inside the container, not on `localhost`.

Nothing here ever prints a secret value: comparisons are sha256 equality, and output is
MATCH/MISMATCH plus a 12-hex fingerprint (sha256[:12]) you can quote in a report.

Usage (run on the host that owns the files, e.g. waze-mdm-01):

  # digests of a secret: from a dotenv file, from a container's environment, from stdin
  verify-secret-move.py envval      .env DASHBOARD_PASSWORD_HASH
  verify-secret-move.py ctrenv      waze-mdm-caddy-1 DASHBOARD_PASSWORD_HASH
  verify-secret-move.py stdinsha
  compare any two digests with `[ "$a" = "$b" ] && echo MATCH`

  # what the running server actually loaded (Caddy admin API -> bcrypt fingerprints)
  docker exec <ctr> wget -qO- http://127.0.0.1:2019/config/ | verify-secret-move.py fp -

  # does the rendered compose env agree with .env?
  docker compose config --format json | verify-secret-move.py composecheck .env

  # does the fail-loud guard actually fire?
  verify-secret-move.py guardtest .env       # exits 0 when compose refuses to render

  # helpers used while editing: extract/verify/insert (see docs in the module)
  verify-secret-move.py counts <file>
"""
import hashlib
import json
import os
import re
import subprocess
import sys

# bcrypt: $2a$/$2b$/$2y$ + cost + 53 chars of salt+digest
HASH_RE = re.compile(r'\$2[aby]\$\d{2}\$[A-Za-z0-9./]{53}')


def parse_env(path):
    """Minimal dotenv reader: KEY=VALUE, strips matching quotes, skips comments."""
    out = {}
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            key = key.strip()
            if key.startswith('export '):
                key = key[7:].strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
                val = val[1:-1]
            out[key] = val
    return out


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def fp(text):
    return sha(text)[:12]


def cmd_envval(args):
    path, key = args
    val = parse_env(path).get(key)
    if val is None:
        print('MISSING')
        return 1
    print(f'{key} sha256={sha(val)} fp={fp(val)} from={path}')
    return 0


def cmd_ctrenv(args):
    ctr, key = args
    out = subprocess.run(
        ['docker', 'exec', ctr, 'sh', '-c', f'printf "%s" "${key}"'],
        capture_output=True, text=True)
    if out.returncode != 0:
        print(f'container read failed: {out.stderr.strip()[:200]}')
        return 1
    print(f'{key} sha256={sha(out.stdout)} fp={fp(out.stdout)} from={ctr}')
    return 0


def cmd_stdinsha(_args):
    print(sha(sys.stdin.read()))
    return 0


def cmd_fp(args):
    """counts/fp: distinct count, occurrence count, fingerprint of the single hash."""
    (src,) = args
    text = sys.stdin.read() if src == '-' else open(src, 'r', encoding='utf-8', errors='replace').read()
    uniq = sorted(set(HASH_RE.findall(text)))
    print('distinct=%d occurrences=%d fp=%s' % (
        len(uniq), len(HASH_RE.findall(text)), fp(uniq[0]) if len(uniq) == 1 else 'N/A'))
    return 0


def cmd_composecheck(args):
    (envfile,) = args
    want = parse_env(envfile).get('DASHBOARD_PASSWORD_HASH')
    cfg = json.load(sys.stdin)
    got = cfg['services']['caddy']['environment'].get('DASHBOARD_PASSWORD_HASH')
    got = got.replace('$$', '$') if got is not None else None
    ok = got is not None and want is not None and got == want
    print('MATCH (rendered value was $-escaped)' if ok else 'MISMATCH')
    return 0 if ok else 1


def cmd_guardtest(args):
    """The :? guard must refuse to render when the variable is unset."""
    (envfile,) = args
    keep = [l for l in open(envfile, encoding='utf-8', errors='replace')
            if not l.startswith('DASHBOARD_PASSWORD_HASH=')]
    tmp = '/tmp/.guardtest.env'
    with open(tmp, 'w') as fh:
        fh.writelines(keep)
    os.chmod(tmp, 0o600)
    try:
        out = subprocess.run(['docker', 'compose', '--env-file', tmp, 'config'],
                             capture_output=True, text=True, cwd=os.getcwd())
        err = out.stderr.strip().splitlines()
        fired = out.returncode != 0 and 'DASHBOARD_PASSWORD_HASH' in out.stderr
        print('guard fired=%s exit=%d %s' % (fired, out.returncode, err[0][:160] if err else ''))
        return 0 if fired else 1
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


COMMANDS = {
    'envval': cmd_envval,
    'ctrenv': cmd_ctrenv,
    'stdinsha': cmd_stdinsha,
    'fp': cmd_fp,
    'counts': cmd_fp,
    'composecheck': cmd_composecheck,
    'guardtest': cmd_guardtest,
}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(COMMANDS[sys.argv[1]](sys.argv[2:]))
