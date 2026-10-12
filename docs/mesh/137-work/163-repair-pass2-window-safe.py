#!/usr/bin/env python3
"""Pass 2: move any renumbered id that landed inside ANOTHER HOST's reserved window.

WHY THIS IS NEEDED (my defect in pass 1, measured after the rebase made the published
ledger visible):

`allocation_ceiling(kind)` is `max(max_number(kind), stamp.json:git_ceiling[kind])` -- the
ID SPACE, entries plus git refs. It does NOT read `journal/alloc/bands.tsv`. And
`next_writable(kind)` returns `max(max_number, allocation_ceiling) + 1`, with the host's own
window contributing only its `reserved_from`. So a host mints from the FLOOR of its window
and walks upward. A number inside another host's window is therefore not merely reserved --
it is the number that host is about to write next.

Pass 1 allocated above `max(max_number, ceiling, git_max)` as measured in THIS checkout.
That is correct against everything this checkout could see. It could not see
`decisions 3039-3102 ZABZ-YOGA` (published 2026-10-10, still 48 commits away). The rebase
brought that row in, and it covers D3047-D3056 -- exactly the ids pass 1 minted. Other hosts'
rows cover P3023-P3025 (ZABZ-YOGA 3002-3065) and W2741-W2743 (ZABZ-YOGA 2733-2796).

So: for every id pass 1 minted, if any ledger row belonging to a DIFFERENT host covers it,
move it above the maximum `reserved_through` for that kind across ALL hosts, and take a
fresh ZABZ-TECH reservation for the new range. Same journal primitives and the same three
byte-fidelity gates as pass 1. Chained aliases are recorded (old -> pass1 id -> pass2 id).
"""
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

repo = Path(r"C:\Users\ezabz\code\harness-config")
spec = importlib.util.spec_from_file_location("jl", repo / "journal" / "tools" / "journal.py")
jl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jl)
jl.JOURNAL = repo / "journal"
jl.clear_caches()
ME = jl.host_tag().upper()

manifest = json.loads((repo / "docs" / "mesh" / "163-repair-manifest.json").read_text())
rows = jl.read_ledger_rows()


def foreign_cover(kind, n):
    out = []
    for r in rows:
        if r["kind"] == kind and r["host"].upper() != ME:
            if r.get("reserved_from", 0) <= n <= r["reserved_through"]:
                out.append(r)
    return out


at_risk = []
for rec in manifest["renumbered"]:
    n = jl.num_of(rec["new_id"])
    cov = foreign_cover(rec["kind"], n)
    if cov:
        at_risk.append((rec, cov))
        print("AT RISK %-8s (pass1) covered by %s" %
              (rec["new_id"], ", ".join("%s %d-%d" % (r["host"], r["reserved_from"],
                                                      r["reserved_through"]) for r in cov)))
print("\n%d of %d pass-1 ids sit inside another host's window\n" % (len(at_risk), len(manifest["renumbered"])))
if not at_risk:
    print("nothing to do")
    sys.exit(0)
if "--apply" not in sys.argv:
    print("report only; re-run with --apply")
    sys.exit(0)

acquired, token = jl.acquire_lock("repair-ids")
if not acquired:
    print("REFUSED: journal lock held elsewhere")
    sys.exit(3)
facts = []
try:
    floor = {}
    for rec, _c in at_risk:
        k = rec["kind"]
        floor[k] = max([r["reserved_through"] for r in rows if r["kind"] == k] + [floor.get(k, 0)])
    for rec, _c in at_risk:
        kind, cur = rec["kind"], rec["new_id"]
        path = jl.entries_dir() / kind / (cur + ".md")
        full = jl.parse_entry(path, kind)
        otxt = path.read_bytes()
        if jl.entry_bytes(full).encode("utf-8") != otxt:
            print("REFUSING %s: no round-trip" % cur)
            continue
        floor[kind] += 1
        cand = floor[kind]
        ok, want, detail = jl.ensure_reservation(kind, cand, fetch=False)
        if not ok:
            print("REFUSING %s: %s" % (cur, detail))
            continue
        n = max(cand, want)
        while (jl.entries_dir() / kind / ("%s%d.md" % (jl.KINDS[kind]["letter"], n))).exists():
            n += 1
        floor[kind] = n
        new_id = "%s%d" % (jl.KINDS[kind]["letter"], n)
        new_heading = re.sub(r"\b" + re.escape(cur) + r"\b", new_id, full["heading"], count=1)
        oh, nh = full["heading"].encode(), new_heading.encode()
        if cur.encode() in oh:
            if nh != oh.replace(cur.encode(), new_id.encode(), 1):
                print("REFUSING %s: heading rewrite not a single substitution" % cur)
                continue
        elif nh != oh:
            print("REFUSING %s: heading changed" % cur)
            continue
        full2 = dict(full)
        full2["id_full"] = new_id
        full2["heading"] = new_heading
        full2["sha"] = jl.entry_hash(new_heading, full["body"])
        ntxt = jl.entry_bytes(full2).encode("utf-8")
        old_sha = jl.entry_hash(jl.effective_heading(full), full["body"]).encode()
        new_sha = jl.entry_hash(jl.effective_heading(full2), full["body"]).encode()
        marker_old = otxt.split(b"\n", 1)[0]
        marker_new = marker_old.replace(cur.encode(), new_id.encode(), 1)
        expect = otxt
        if marker_new != marker_old:
            expect = expect.replace(marker_old, marker_new, 1)
        if nh != oh:
            expect = expect.replace(oh, nh, 1)
        if new_sha != old_sha:
            expect = expect.replace(old_sha, new_sha, 1)
        if ntxt != expect:
            print("REFUSING %s: bytes changed by more than the id token and hash" % cur)
            continue
        dest = jl.entries_dir() / kind / (new_id + ".md")
        arch = jl.JOURNAL / jl.ARCHIVE_NAME / ("collided-ids-" + jl.today()) / kind
        arch.mkdir(parents=True, exist_ok=True)
        adest = arch / (cur + ".md")
        k = 1
        while adest.exists():
            k += 1
            adest = arch / ("%s-%d.md" % (cur, k))
        jl.atomic_write(dest, jl.entry_bytes(full2))
        shutil.move(str(path), str(adest))
        back = jl.parse_entry(dest, kind)
        if back["body"] != full["body"]:
            print("FATAL: body changed %s -> %s" % (cur, new_id))
            sys.exit(9)
        jl.record_alias(cur, kind, new_id,
                        "pass 2: %s fell inside another host's published reservation window; "
                        "moved above every published ceiling for %s" % (cur, kind),
                        host=full.get("host"), sha=full.get("hash"), source=jl._rel_of(adest))
        facts.append({"kind": kind, "pass1_id": cur, "id": new_id,
                      "original_id": rec["old_id"],
                      "path": jl._rel_of(dest), "archive": jl._rel_of(adest),
                      "sha256_before": hashlib.sha256(otxt).hexdigest(),
                      "sha256_after": hashlib.sha256(ntxt).hexdigest(),
                      "body_sha256": hashlib.sha256(full["body"].encode()).hexdigest()})
        print("moved %-8s -> %-8s (was %s)" % (cur, new_id, rec["old_id"]))
finally:
    jl.release_lock(token)
jl.rebuild_cache(compute_drift=True)
out = repo / "docs" / "mesh" / "163-repair-pass2-manifest.json"
out.write_text(json.dumps({"host": ME, "at_risk": len(at_risk), "moved": facts}, indent=1))
print("\n-- %d moved; manifest %s" % (len(facts), out))
