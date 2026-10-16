#!/usr/bin/env python3
"""converge-pull.py — carry entries the machines have written since the last capture INTO the record.

WHAT THIS IS FOR. The union landed on 2026-10-16 and was a superset for 38 minutes. After that the
canonical tree fell behind, because the machines write to their own checkouts and nothing carries those
writes anywhere: measured 6 entries of drift in that window (L6464). This is the missing half — the
PULL. It is one iteration of a loop, run by hand tonight and schedulable once the writer model is set.

IT IS ADDITIVE, AND THAT IS THE DESIGN. It never edits, renumbers or removes an entry that is already
in the canonical tree. For each source entry whose BODY is not already present:

  * its own id is free                        -> copy it in under that id
  * its id is taken by a different entry      -> give IT a fresh id (rewrite the marker's id and the
                                                 entry's own id token in the body's first line)

Only the INCOMING entry's id can change. So the canonical tree's existing citations cannot break, and
the whole operation is reversible: everything it adds is a file that did not exist before.

WHY NOT JUST RE-RUN THE UNION. Because the union rebuilds from a base and renumbers the base's entries
too — which is correct once, and wrong as a routine: it would move the canonical tree's own ids under
the machines' every time it ran. This is the incremental form.

IDENTITY is `journal.py`'s own `identity_of`, imported from the canonical tree, so "already present"
means the same thing here as it does in `check` and in the acceptance gate.
"""
from __future__ import annotations

import argparse
import importlib.util
import pathlib
import re
import sys

KINDS = ("decisions", "handoff", "lessons", "pain", "wins")
ID_TOKEN = re.compile(r"\b[DHILPW][0-9]{1,6}[a-z]{0,3}\b")


def load_tool(root: pathlib.Path):
    spec = importlib.util.spec_from_file_location("_jm_pull", root / "tools" / "journal.py")
    m = importlib.util.module_from_spec(spec)
    m.JOURNAL = root
    spec.loader.exec_module(m)
    return m


def entries_dir_of(t: pathlib.Path):
    ent = t / "entries"
    if not ent.is_dir():
        ent = t / "journal" / "entries"
    return ent if ent.is_dir() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canonical", required=True, help="the journal root to add entries to")
    ap.add_argument("--trees", required=True, help="directory holding one subdir per source tree")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="stop after N additions (0 = no limit)")
    args = ap.parse_args()

    root = pathlib.Path(args.canonical)
    trees = pathlib.Path(args.trees)
    if not (root / "entries").is_dir():
        print(f"! {root}/entries not found", file=sys.stderr)
        return 2
    if not trees.is_dir():
        print(f"! {trees} not found", file=sys.stderr)
        return 2
    jm = load_tool(root)
    ent = root / "entries"

    # what the canonical tree already holds, by identity and by id
    live_ident = set()
    live_ids = set()
    highest = {k: 0 for k in KINDS}
    for f in ent.rglob("*.md"):
        if "/archive/" in str(f).replace("\\", "/"):
            continue
        e = jm.parse_entry(f, f.parent.name)
        if not e:
            continue
        live_ident.add(jm.identity_of(e["kind"], e.get("heading"), e.get("body") or ""))
        live_ids.add((e["kind"], e["id_full"]))
        m = re.match(r"^[DHILPW]([0-9]+)", e["id_full"] or "")
        if m and e["kind"] in highest:
            highest[e["kind"]] = max(highest[e["kind"]], int(m.group(1)))
    print(f"canonical   : {root}")
    print(f"live entries: {len(live_ids)} ids, {len(live_ident)} distinct identities")
    print(f"ceilings    : " + ", ".join(f"{k}:{highest[k]}" for k in KINDS))

    plan = []
    seen_new = set()
    skipped_present = 0
    per_tree = {}
    for t in sorted(x for x in trees.iterdir() if x.is_dir()):
        src = entries_dir_of(t)
        if not src:
            continue
        n = 0
        for f in sorted(src.rglob("*.md")):
            if "/archive/" in str(f).replace("\\", "/"):
                continue
            e = jm.parse_entry(f, f.parent.name)
            if not e:
                continue
            ident = jm.identity_of(e["kind"], e.get("heading"), e.get("body") or "")
            if ident in live_ident:
                skipped_present += 1
                continue
            if ident in seen_new:
                continue                       # the same new entry in two source trees: add it once
            seen_new.add(ident)
            kind, want = e["kind"], e["id_full"]
            if kind not in KINDS:
                continue
            if (kind, want) in live_ids or (ent / kind / f"{want}.md").exists():
                highest[kind] += 1
                target = f"{want[0]}{highest[kind]}"
                why = "id taken"
            else:
                target = want
                why = "id free"
            live_ids.add((kind, target))
            plan.append((t.name, kind, want, target, why, f))
            n += 1
        per_tree[t.name] = n

    print("new entries per source tree: " + (" ".join(f"{t}:{n}" for t, n in per_tree.items()) or "none"))
    print(f"already present in the canonical tree: {skipped_present}")
    print(f"\nTO ADD: {len(plan)}")
    for tn, kind, want, target, why, f in plan[:25]:
        flag = "" if want == target else f"  -> {target}"
        print(f"   {tn:12} {kind:9} {want}{flag}   ({why})")

    if not args.apply:
        print("\nMEASURE ONLY -- re-run with --apply")
        return 0

    written = 0
    for tn, kind, want, target, why, f in plan:
        raw = f.read_bytes()
        if target != want:
            text = raw.decode("utf-8", "replace")
            lines = text.splitlines(keepends=True)
            if "|" in lines[0]:
                lines[0] = lines[0].replace(f"|{want}|", f"|{target}|", 1)
            for i in range(1, len(lines)):
                if not lines[i].strip():
                    continue
                if re.search(r"(?<![A-Za-z0-9])" + re.escape(want) + r"(?![A-Za-z0-9])", lines[i]):
                    lines[i] = re.sub(r"(?<![A-Za-z0-9])" + re.escape(want) + r"(?![A-Za-z0-9])",
                                      target, lines[i])
                break
            raw = "".join(lines).encode("utf-8")
        (ent / kind).mkdir(parents=True, exist_ok=True)
        dst = ent / kind / f"{target}.md"
        dst.write_bytes(raw)
        if target != want:
            # RENUMBERING INVALIDATES THE RECORDED sha=. The sha is computed over the heading AND the
            # body, and the rewrite above changes both, so the entry lands with metadata that does not
            # match and `check` reports:
            #   ERROR entries/<kind>/<ID>.md: metadata sha=... does not match the body (...)
            # Measured 2026-10-16 on the first arrival this happened to (L6657), which took the record
            # to 1 error. Fixing it HERE keeps the job additive: the alternative, running
            # `check --fix` in the job, is a second writer touching an entry the pull had just landed,
            # and it would also mask the next bug of this class instead of failing.
            e2 = jm.parse_entry(dst, kind)
            if e2:
                want_sha = jm.entry_hash(jm.effective_heading(e2), e2.get("body") or "")
                text = dst.read_text(encoding="utf-8", errors="replace")
                fresh = re.sub(r"(<!--\s*j2\s+[^>]*?)sha=\S+", r"\1sha=" + want_sha, text, count=1)
                if fresh != text:
                    dst.write_bytes(fresh.encode("utf-8"))
        written += 1
        if args.limit and written >= args.limit:
            break
    print(f"\nwrote {written} entr(ies). No existing entry was read-modified, moved or removed.")
    print("next: journal.py index, then journal.py check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
