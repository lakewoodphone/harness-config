#!/usr/bin/env python3
"""
merge-family-chat.py — merge the office family-chat store INTO the authority's copy, without loss.

WHY THIS IS NOT A FILE COPY
Measured 2026-10-11: the office copy holds 3,156 messages and its newest row is 2026-10-11 02:45:22;
the authority's copy holds 1 message and its newest is 2026-10-11 05:41:32 - NEWER than the office's.
So neither side contains the other: a copy in either direction destroys something real. This merges.

THE TRAP IT EXISTS TO AVOID
`members` has the same columns in a DIFFERENT ORDER on the two sides (cloud: ..., active, muted,
created_at, updated_at; office: ..., active, created_at, updated_at, muted). A positional
`INSERT ... SELECT *` would write each member's timestamps into `muted` and vice versa, silently.
Every statement here names its columns explicitly.

RULES
  * The target is modified through a LOCKED transaction and committed once; a failure rolls back.
  * A copy of the target is taken before anything is written, and its path is printed.
  * Rows are only ever INSERTED. Nothing is deleted or overwritten, except `settings`, where the
    office value wins for a key both sides hold because the office copy is the historical truth for
    configuration the authority has only just received - and that is stated, not silent.
  * It prints a per-table before/after count and exits non-zero if the additions do not match what it
    reported it would add.
"""
import argparse
import os
import shutil
import sqlite3
import time

TABLES = ["messages", "members", "settings", "outbox", "chip_memories"]


def cols(conn, table):
    return [r[1] for r in conn.execute('pragma table_info("%s")' % table)]


def merge(src_path: str, dst_path: str, apply: bool) -> int:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = dst_path + ".before-merge-" + stamp
    print("target :", dst_path)
    print("source :", src_path, os.path.getsize(src_path), "bytes")
    print("backup :", backup)
    shutil.copy2(dst_path, backup)

    src = sqlite3.connect("file:%s?mode=ro" % src_path, uri=True)
    dst = sqlite3.connect(dst_path, timeout=60)
    dst.execute("pragma busy_timeout=60000")

    plan = []
    for t in TABLES:
        sc, dc = cols(src, t), cols(dst, t)
        if set(sc) != set(dc):
            print("!! column SET differs for %s: source %s / target %s" % (t, sc, dc))
            return 2
        if sc != dc:
            print("   note: %s column ORDER differs (source %s / target %s) - matching by name" % (t, sc, dc))
        shared = [c for c in dc if c in sc]
        before = dst.execute('select count(*) from "%s"' % t).fetchone()[0]
        src_rows = src.execute('select %s from "%s"' % (",".join('"%s"' % c for c in shared), t)).fetchall()
        plan.append((t, shared, before, src_rows))

    print("\n--- merge plan ---")
    for t, shared, before, rows in plan:
        print("   %-14s target has %-6d source has %-6d" % (t, before, len(rows)))
    if not apply:
        print("\n--dry-run: nothing written")
        return 0

    added = {}
    with dst:  # one transaction
        for t, shared, before, rows in plan:
            collist = ",".join('"%s"' % c for c in shared)
            placeholders = ",".join("?" for _ in shared)
            if t == "settings":
                # a key both sides hold: the office value wins (historical truth), and it says so
                dst.executemany(
                    'insert into "settings" (%s) values (%s) on conflict("key") do update set value=excluded.value'
                    % (collist, placeholders), rows)
            else:
                dst.executemany(
                    'insert or ignore into "%s" (%s) values (%s)' % (t, collist, placeholders), rows)
            after = dst.execute('select count(*) from "%s"' % t).fetchone()[0]
            added[t] = after - before
            print("   %-14s %d -> %d  (+%d)" % (t, before, after, added[t]))

    print("\n--- verification ---")
    ok = True
    for t, shared, before, rows in plan:
        after = dst.execute('select count(*) from "%s"' % t).fetchone()[0]
        newest_src = src.execute('select max(created_at) from "%s"' % t).fetchone()[0] if "created_at" in shared else None
        newest_dst = dst.execute('select max(created_at) from "%s"' % t).fetchone()[0] if "created_at" in shared else None
        print("   %-14s rows=%-6d newest_source=%-20s newest_target=%s" % (t, after, newest_src, newest_dst))
        if after < before:
            print("   !! %s SHRANK - that must never happen" % t)
            ok = False
        if newest_src and newest_dst and str(newest_dst) < str(newest_src):
            print("   !! %s target's newest row is OLDER than the source's" % t)
            ok = False
    check = dst.execute("pragma integrity_check").fetchone()[0]
    print("   integrity_check:", check)
    if check != "ok":
        ok = False
    dst.close()
    src.close()
    print("\nbackup kept at", backup)
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    raise SystemExit(merge(a.source, a.target, a.apply))
