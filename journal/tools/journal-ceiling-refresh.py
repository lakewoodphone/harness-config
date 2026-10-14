#!/usr/bin/env python3
"""One global id ceiling for the journal, refreshed by one command, on every node.

WHY THIS EXISTS. Ids were allocated from whatever a machine could see locally, so two machines
minted the same id for different entries. A reserve-a-window scheme was added, but it allocates
from a ceiling built out of *peer* reservations, and peer reservations are only as fresh as the
last successful fetch. Measured on the authority 2026-10-14 19:50Z:

    refs/remotes/origin/journal/zabz-yoga  -> bands.tsv newest row  2026-10-14 11:59 UTC
    the live bands.tsv on the authority    -> newest row            18:50 UTC
    ZABZ-YOGA's own bands.tsv (fetched)    -> newest row            19:45 UTC

so the authority's ceiling could not see the eight hours of reservations yoga had made in between,
and `next-id pain` on the authority produced **P3212** — a number yoga had already reserved and was
about to write. It is not a rare race; it is the steady state.

WHAT THIS DOES, and why in this shape

  1. `git fetch` each peer remote that exists here, with a timeout, tolerating failure. A fetch is
     how reservations travel; a fetch that fails must not silently leave a stale ceiling.
  2. Read `journal/alloc/bands.tsv` from **every ref that carries it**, newest ref commits first,
     rather than from one hard-coded ref name — a ref name is a guess, the blob is a fact.
  3. Take the maximum `reserved_through` per kind across: the local file, every ref that carries
     one, and the local entry filenames themselves.
  4. Write `journal/alloc/ceiling.json` — the fast path an interactive `next-id` reads.

The two-process shape is deliberate: a fetch plus a scan of thousands of refs is too slow to run
inside an interactive `next-id` (the full path exceeded a 120 s budget, measured), so the slow part
runs on a timer and the fast part is a dict lookup.

USAGE
    python3 journal-ceiling-refresh.py              # refresh, report, publish ceiling.json
    python3 journal-ceiling-refresh.py --json       # machine-readable
    python3 journal-ceiling-refresh.py --dry-run    # compute and report, publish nothing
    python3 journal-ceiling-refresh.py --no-fetch   # use refs as they stand (offline, tests)

Exit codes: 0 refreshed · 1 a peer fetch failed but a ceiling was still published (degraded) ·
2 could not publish.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

KINDS = {
    "lessons": ("L", "journal/entries/lessons"),
    "wins": ("W", "journal/entries/wins"),
    "handoff": ("H", "journal/entries/handoff"),
    "pain": ("P", "journal/entries/pain"),
    "decisions": ("D", "journal/entries/decisions"),
}
# Candidate peer remotes. Only those that exist in this checkout are fetched — a remote name that
# is absent is not a failure, it is a fact about this checkout, and reporting it as one would train
# the reader to ignore the failure list.
PEER_CANDIDATES = ["yoga", "tech", "cloud", "offsite", "journalpub", "vault"]
FETCH_TIMEOUT_S = 90
ENTRY_RE = re.compile(r"^[A-Za-z](\d+)[a-z]?\.md$")

# PEERS' LIVE WORKING TREES, read over ssh, because a git ref is not the newest reservation.
#
# Measured 2026-10-14 19:55Z on the authority: the newest `refs/remotes/.../journal/alloc/bands.tsv`
# carrying yoga's rows stopped at 11:59Z, the authority's own bands stopped at 18:50Z, and yoga's
# *working tree* held 19:36/19:38/19:45Z reservations that no ref had yet — because `bands.tsv` is
# written at allocation time and committed later, if at all. Reading only refs therefore hands out
# numbers a peer has already reserved and is about to write, which is exactly the collision this
# file exists to prevent. ZABZ-TECH's live tree carried a `pain` reservation at 3801-3864 that
# appeared in no ref the authority held at all.
#
# Each entry is (label, ssh_alias, posix-ish path that the peer's own shell understands). The read
# is one ssh per peer with a hard timeout, and an unreachable peer is reported as UNREACHABLE, not
# as a failure: a laptop that is switched off is not a defect.
LIVE_PEERS = [
    ("ZABZ-YOGA", "zabz-yoga-ts", "C:/Users/ezabz/code/harness-config/journal/alloc/bands.tsv"),
    ("ZABZ-TECH", "zabz-tech-ts", "C:/Users/ezabz/code/harness-config/journal/alloc/bands.tsv"),
    ("SECRATARY-CLOUD", "secratary-cloud", "/home/zabz/code/harness-config/journal/alloc/bands.tsv"),
    ("ZABZ-TECH-LINUX", "linux-pc-ts", "/home/zabz/harness-config/journal/alloc/bands.tsv"),
]
LIVE_TIMEOUT_S = 25


def repo_root() -> str:
    """Walk up for a `.git` DIRECTORY OR FILE (a worktree/submodule has a file)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):
        if os.path.exists(os.path.join(here, ".git")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    env = os.environ.get("HARNESS_CONFIG_ROOT")
    if env and os.path.isdir(env):
        return env
    return os.getcwd()


def run(args: list[str], cwd: str, timeout: int = FETCH_TIMEOUT_S) -> tuple[int, str]:
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(args)}"
    except FileNotFoundError as exc:
        return 127, str(exc)


def existing_remotes(root: str) -> set[str]:
    rc, out = run(["git", "remote"], root, timeout=20)
    return set(out.split()) if rc == 0 else set()


def fetch_peers(root: str) -> tuple[list[str], list[str], list[str]]:
    present = existing_remotes(root)
    the_peers = [p for p in PEER_CANDIDATES if p in present]
    absent = [p for p in PEER_CANDIDATES if p not in present]
    ok, failed = [], []
    for peer in the_peers:
        rc, _out = run(["git", "fetch", peer, "--quiet", "--no-tags"], root)
        (ok if rc == 0 else failed).append(peer)
    return ok, failed, absent


def bands_refs(root: str, path: str = "journal/alloc/bands.tsv") -> list[tuple[str, int, str]]:
    """(refname, commit unix time, blob sha) for every ref whose tree HAS `path`."""
    rc, out = run(["git", "for-each-ref", "--format=%(refname)", "refs/"], root, timeout=60)
    if rc != 0:
        return []
    refs = [r.strip() for r in out.splitlines() if r.strip()]
    if not refs:
        return []
    # One `git log` for the ref->date mapping is far cheaper than one call per ref.
    rc2, dates = run(["git", "for-each-ref", "--format=%(refname)\t%(committerdate:unix)", "refs/"],
                     root, timeout=60)
    when_by_ref = {}
    for line in dates.splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            try:
                when_by_ref[parts[0]] = int(parts[1])
            except ValueError:
                pass
    # One `git ls-tree` per ref is the reliable way to know the ref's tree holds the path.
    found = []
    for ref in refs:
        rc3, sha = run(["git", "rev-parse", f"{ref}:{path}"], root, timeout=20)
        if rc3 != 0 or not sha.strip():
            continue
        found.append((ref, when_by_ref.get(ref, 0), sha.strip()))
    found.sort(key=lambda t: t[1], reverse=True)
    return found


def parse_bands(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines()[1:]:
        cells = line.rstrip("\n").split("\t")
        if len(cells) < 4:
            continue
        kind = cells[0].strip()
        if kind not in KINDS:
            continue
        try:
            rows.append({
                "kind": kind,
                "reserved_from": int(cells[1] or 0),
                "reserved_through": int(cells[2] or 0),
                "host": cells[3].strip(),
                "stamp": cells[4].strip() if len(cells) > 4 else "",
            })
        except ValueError:
            continue
    return rows


def local_entry_max(root: str) -> dict[str, int]:
    best = {k: 0 for k in KINDS}
    for kind, (_letter, rel) in KINDS.items():
        d = os.path.join(root, rel)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            m = ENTRY_RE.match(name)
            if m:
                best[kind] = max(best[kind], int(m.group(1)))
    return best


def read_live_peer_bands(local_host: str) -> tuple[list[dict], list[str]]:
    """Read every reachable peer's LIVE bands.tsv.

    Returns (rows, unreachable_labels). Rows carry `where` = "<label> live working tree", which is
    the only provenance that tells an operator the number came from a tree rather than a ref.
    """
    rows: list[dict] = []
    unreachable: list[str] = []
    for label, alias, path in LIVE_PEERS:
        if label.upper() == local_host.upper():
            continue
        # The peer's own shell may be PowerShell (Windows) or bash (Linux); `Get-Content -Tail`
        # and `tail -n` are each native on one of them, so try the one that fits the alias.
        is_windows = "yoga" in alias or "tech-ts" in alias
        cmd = (f'Get-Content "{path}" -Tail 200' if is_windows else f'tail -n 200 "{path}"')
        rc, out = run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", "-o", "StrictHostKeyChecking=accept-new",
             alias, cmd],
            os.getcwd(), timeout=LIVE_TIMEOUT_S,
        )
        if rc != 0 or not out.strip():
            unreachable.append(f"{label} ({'rc=' + str(rc)})")
            continue
        # The peer may echo its own transport banner; only tab-separated band lines are wanted.
        body = "\n".join(l for l in out.splitlines() if l.count("\t") >= 4 and "\t" in l)
        got = parse_bands("kind\tfrom\tthrough\thost\tstamp\trev\n" + body)
        for r in got:
            rows.append({"where": f"{label} live working tree", **r})
        if not got:
            unreachable.append(f"{label} (no parseable band rows)")
    return rows, unreachable


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--no-live", action="store_true",
                    help="skip reading peers' live working trees (they are newer than any ref)")
    ap.add_argument("--adopt", action="store_true",
                    help="append live-peer reservations to the local bands.tsv (provenance only; "
                         "the allocator skips another host's rows, so this ALONE does not prevent "
                         "a collision — use --claim-gap)")
    ap.add_argument("--claim-gap", action="store_true",
                    help="append a LOCAL reservation spanning every number this host can see but "
                         "does not hold, so the allocator's own arithmetic cannot hand one out")
    ap.add_argument("--raise-cache", action="store_true",
                    help="also raise journal/index/stamp.json's git_ceiling to the global maximum, "
                         "which is the only term `allocation_ceiling()` actually reads for this")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", default="")
    args = ap.parse_args()

    root = args.root or repo_root()
    started = time.time()

    fetched_ok, fetched_failed, remotes_absent = ([], [], []) if args.no_fetch else fetch_peers(root)

    sources: list[dict] = []
    best = {k: 0 for k in KINDS}

    local_path = os.path.join(root, "journal/alloc/bands.tsv")
    if os.path.isfile(local_path):
        for r in parse_bands(open(local_path, errors="replace").read()):
            sources.append({"where": "local bands.tsv", **r})
            best[r["kind"]] = max(best[r["kind"]], r["reserved_through"])

    seen_blobs: set[str] = set()
    refs_read = 0
    for ref, when, sha in bands_refs(root):
        if sha in seen_blobs:
            continue
        seen_blobs.add(sha)
        rc, text = run(["git", "cat-file", "-p", sha], root, timeout=30)
        if rc != 0:
            continue
        rows = parse_bands(text)
        if not rows:
            continue
        refs_read += 1
        for r in rows:
            sources.append({
                "where": ref,
                "ref_age_s": (int(time.time()) - when) if when else None,
                **r,
            })
            best[r["kind"]] = max(best[r["kind"]], r["reserved_through"])

    entries = local_entry_max(root)
    for kind, n in entries.items():
        if n > best[kind]:
            best[kind] = n
            sources.append({
                "where": "local entries (a number above every reservation)",
                "kind": kind, "reserved_through": n, "host": "(this machine)",
            })

    # The live working trees, which are newer than every ref by construction (see LIVE_PEERS).
    live_rows, live_unreachable = ([], [])
    if not args.no_live:
        live_rows, live_unreachable = read_live_peer_bands(os.uname().nodename)
        for r in live_rows:
            sources.append(r)
            best[r["kind"]] = max(best[r["kind"]], r["reserved_through"])

    adopted: list[dict] = []
    if args.adopt and live_rows:
        # Append the live peer reservations this authority does not already hold, so that
        # `journal.py next-id` — which reads bands.tsv and knows nothing about ceiling.json —
        # cannot hand out a number a reachable peer has already claimed. Rows are only ADDED:
        # nothing is rewritten or removed, and a later refresh replaces a row it now sees a real
        # one for rather than editing another host's history.
        _, local_text = run(["cat", local_path], root, timeout=20) if os.path.isfile(local_path) else (1, "")
        held = {(r["kind"], r["reserved_from"], r["reserved_through"], r["host"].upper())
                for r in parse_bands(local_text)}
        for r in live_rows:
            key = (r["kind"], r["reserved_from"], r["reserved_through"], r["host"].upper())
            if key in held:
                continue
            adopted.append(r)
            held.add(key)
        if adopted:
            with open(local_path, "a") as fh:
                for r in adopted:
                    fh.write("{}\t{}\t{}\t{}\t{}\t{}\n".format(
                        r["kind"], r["reserved_from"], r["reserved_through"], r["host"],
                        r.get("stamp") or "adopted-from-live-peer", "-"))

    # CLAIM THE GAP, in the allocator's own arithmetic.
    #
    # Adding another host's row is NOT enough, and this was measured rather than assumed:
    # `allocation_ceiling()` takes `reserved_through_others()`, which by design EXCLUDES rows
    # belonging to this host — so adopting a peer's row as that peer leaves this host free to
    # hand out a number inside it. Measured on the authority 2026-10-14 20:0xZ: 39 rows adopted,
    # ceiling unchanged, `next-id pain` still P3212 while ZABZ-TECH held 3801-3864.
    #
    # What closes it is a LOCAL claim spanning everything this host can currently see:
    # `from = (this host's own highest through) + 1`, `through = the global maximum`. The
    # allocator already treats a host's own window as reserved, so after this row the next
    # number it can hand out is the global maximum + 1 — which no peer has claimed.
    # Rows are only ever appended; nothing is removed or narrowed, so no number already
    # handed out is revisited and a gap costs nothing (a reused number destroys citations).
    claimed: list[dict] = []
    if args.claim_gap and os.path.isfile(local_path):
        me = os.uname().nodename.upper()
        _, local_text = run(["cat", local_path], root, timeout=20)
        local_rows = parse_bands(local_text)
        stamp_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        for kind in KINDS:
            mine_through = max([r["reserved_through"] for r in local_rows
                                if r["kind"] == kind and r["host"].upper() == me] or [0])
            target = best[kind]
            if target > mine_through:
                claimed.append({
                    "kind": kind,
                    "reserved_from": mine_through + 1,
                    "reserved_through": target,
                    "host": me,
                    "stamp": stamp_now,
                })
        if claimed and not args.dry_run:
            with open(local_path, "a") as fh:
                for r in claimed:
                    fh.write("{}\t{}\t{}\t{}\t{}\t{}\n".format(
                        r["kind"], r["reserved_from"], r["reserved_through"], r["host"],
                        r["stamp"], "-"))

    winners = {}
    for kind in KINDS:
        cands = [s for s in sources
                 if s.get("kind") == kind and s.get("reserved_through") == best[kind]]
        cands.sort(key=lambda s: (s.get("where", "").endswith("live working tree") * -1,
                                  s.get("ref_age_s") is None, s.get("ref_age_s") or 0))
        winners[kind] = (cands[0]["where"] if cands else "none")

    out = {
        "refreshed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": os.uname().nodename,
        "repo_root": root,
        "ceiling": best,
        "high_water": {k: KINDS[k][0] + str(best[k]) for k in KINDS},
        "entries_high_water": {k: KINDS[k][0] + str(entries[k]) for k in KINDS},
        "ceiling_source": winners,
        "peers_fetched": fetched_ok,
        "peers_failed": fetched_failed,
        "remotes_absent": remotes_absent,
        "bands_refs_read": refs_read,
        "live_peer_rows": len(live_rows),
        "live_peer_unreachable": live_unreachable,
        "adopted_rows": len(adopted),
        "claimed_gap_rows": claimed,
        "sources_seen": len(sources),
        "seconds": round(time.time() - started, 1),
    }

    if not args.dry_run:
        dest = os.path.join(root, "journal/alloc/ceiling.json")
        tmp = dest + ".part"
        with open(tmp, "w") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, dest)
        out["written"] = dest

        # ALSO RAISE THE ALLOCATOR'S OWN CACHE.
        #
        # `allocation_ceiling()` is `max(local max_number, stamp["git_ceiling"], other hosts'
        # windows, stamp["ledger_ceiling"])`, and it deliberately EXCLUDES this host's own rows.
        # So neither a peer row nor a local claim is visible to it: measured on the authority
        # 2026-10-14, after appending a local claim through P3864, `next-id pain` still answered
        # P3212 because the only term that had moved was one the function skips. The term it does
        # read is `stamp["git_ceiling"]`, and this is the value it should hold: the maximum this
        # host can see anywhere — refs, peers' live trees, and its own entries.
        #
        # The allocator only ever MAX-merges this field, so writing it can only raise a ceiling.
        if args.raise_cache:
            stamp_path = os.path.join(root, "journal/index/stamp.json")
            if os.path.isfile(stamp_path):
                try:
                    stamp = json.load(open(stamp_path))
                    merged = dict(stamp.get("git_ceiling") or {})
                    before = dict(merged)
                    for kind, value in best.items():
                        merged[kind] = max(int(merged.get(kind) or 0), int(value or 0))
                    stamp["git_ceiling"] = merged
                    stamp["ceiling_refreshed_at"] = out["refreshed_at"]
                    stamp["ceiling_source"] = winners
                    tmp2 = stamp_path + ".part"
                    with open(tmp2, "w") as fh:
                        json.dump(stamp, fh, indent=1, sort_keys=True)
                        fh.write("\n")
                    os.replace(tmp2, stamp_path)
                    out["stamp_git_ceiling_before"] = before
                    out["stamp_git_ceiling_after"] = merged
                    out["stamp_updated"] = stamp_path
                except Exception as exc:
                    out["stamp_error"] = f"{type(exc).__name__}: {exc}"

    if args.json:
        print(json.dumps(out, indent=1, sort_keys=True))
    else:
        print(f"ceiling refreshed in {out['seconds']}s on {out['host']}  (root {root})")
        for k in KINDS:
            print(f"  {k:10} through {KINDS[k][0]}{best[k]:<6} (local entries at "
                  f"{KINDS[k][0]}{entries[k]:<6}) from {winners[k]}")
        print(f"  bands refs read={refs_read}  live peer rows={len(live_rows)}  "
              f"adopted={len(adopted)}  sources={len(sources)}  "
              f"fetched={fetched_ok}  failed={fetched_failed}")
        if live_unreachable:
            print(f"  live peers unreachable (a switched-off laptop is not a defect): {live_unreachable}")
        if remotes_absent:
            print(f"  no such remote here (not a failure): {remotes_absent}")
        if out.get("written"):
            print(f"  wrote {out['written']}")

    return 1 if fetched_failed else 0


if __name__ == "__main__":
    sys.exit(main())
