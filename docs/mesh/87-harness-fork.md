# 87 — The forked repository: `harness-config` on the authority

Stream **O6** of `81-overnight-program.md`. Owner of this file: O6 only. Deliverable: the fork
resolved deliberately, on a branch, backed up first, with the journal's own tools. Done when every
machine can `git pull --ff-only` again and `journal.py check` is 0 errors.

**EXECUTED 2026-09-17 03:34–04:15 UTC, and green.** This began as a read-and-plan-first stream; it
became an execution under an explicit per-action yes for §4.5. Final state:

* `origin/master` = **`c4b1b576cba59d3046da8b527407b830fe6bf239`** — a real two-parent merge commit
  (`d09163a` + `c057738`). Three commits landed, all fast-forwards: `d09163a` (the authority's 41),
  `c4b1b57` (the stream merge), plus the record you are reading.
* **`journal.py check` = 0 errors** on the authority, on `origin/master`, and on the merged tree.
* **Every machine can `git pull --ff-only` again.** The authority was proven by doing it
  (`Updating d09163a..c4b1b57  Fast-forward`, exit 0, now `0 0` against origin); the laptop was
  proven by ancestry (`merge-base HEAD origin/master` = `c057738` = `HEAD`, so the pull is a pure
  fast-forward). See §7 for the arithmetic that accounts for every entry.

* The plan below is preserved unedited where it was right, and corrected in place where execution
  proved it wrong — §4.6 and §4.7 exist because of measured mistakes, mine included (§7.3).
* `origin/master` moved three times during the work (`0d07ace` → `2ce3ad9` → `d09163a` → `c4b1b57`)
  because other streams were live. **Every count names the revision it was taken at.**
* Throwaway work: `/home/zabz/hc-fork-lab-20260917T033457Z` (a `cp -a` copy), `/tmp/hc-union-<TS>`
  (abandoned mid-merge, never pushed, see §7.3), `/tmp/hc-merge2-<TS>` (the merge that landed), and
  worktrees `/tmp/hc-w-origin`, `/tmp/hc-w-auth`, `/tmp/hc-rehearse*`.
* Backups: `/home/zabz/backups/harness-fork/` — see §4.0. The real checkout's history was preserved
  before it was aligned.
* Quarantine: `/tmp/hc-runaway-quarantine-20260917/` — 457 files, moved not deleted. §7.3.

---

## 0. The brief's premise is inverted, and that inverts the risk

`81-overnight-program.md` §1 O6 and the O6 brief both say the authority's checkout is *"300 commits
ahead of origin/master and 13 behind"*, so *"every fix tonight had to be copied file-by-file to
reach that machine."*

Measured, on `/home/zabz/harness-config`, HEAD `30958c8`:

```
$ git rev-list --left-right --count HEAD...origin/master
13      316
$ git pull --ff-only
hint: Diverging branches can't be fast-forwarded, you need to either:
hint:   git merge --no-ff
```

`--left-right` prints **behind first**: the authority is **13 ahead and 316 behind**, not 300 ahead.
The refusal is real, but it is caused by the *small* side. This is not a cosmetic correction — it
changes which side holds the record:

* the authority's **13** commits are a local journal round (2026-09-14 23:10 → 2026-09-15 16:12) and
  are **already preserved on origin** as `origin/secretary-journal-preserved-20260915`, whose tip is
  exactly `30958c8`. `git branch -r --contains HEAD` names it. **No commit of the authority's is at
  risk from any ref move.** The brief's fear — "this may be a large amount of record that exists ONLY
  there" — is true of the *working tree*, not of the commits.
* what is `origin/master`'s and not the authority's is 316 commits: the whole mesh build, the gate,
  the broker, the mac-mini work, plus 669 journal entries.

The distinction that decides the whole plan:

| | commits | content |
|---|---|---|
| in the authority's **history** | 13, all reachable from an origin ref | recoverable by anyone |
| in the authority's **working tree**, committed nowhere | 0 | **512 untracked files** (510 of them journal entries) + 11 modified tracked files |

The second row is the whole of the content risk. Everything else is a ref-topology problem.

Two more checkouts exist on the authority and neither is the subject: `/home/zabz/code/harness-config`
(clean, at `af2a6e7`, whose `origin/master` ref is stale — it has never been fetched since) and
`/tmp/jv2`, a detached worktree at `e383047` whose message is a prior session's verdict:
*"merge origin/master into the main tree: the only conflict was the generated cache, resolved by
regenerating it."* That commit is already an ancestor of `origin/master`, so a previous attempt is
part of the record — and it is the prior art the plan below follows for the cache.

`git reflog` on the real checkout also shows a **rebase that was started at 2026-09-15 01:40 and
aborted at 01:41** ("rebase (start): checkout origin/master" → "rebase (abort)"). A previous
occupant reached for rebase, which is the one verb §2 forbids. The plan below deliberately does not
rebase and does not rewrite anything.

---

## 1. What the authority actually holds, grouped and counted

Identity here means the journal's own: `(kind, journal.py's norm_body(body))` — README §"Integrity",
and `identity_of()` at `journal/tools/journal.py:3370`. Every number in this section was computed by
calling the tool's own `identity_of`, not a re-implementation of it (a re-implementation disagreed
on 1 of 1,824 entries; see §4.6).

### 1.1 The 13 commits, by kind

`git log --oneline HEAD ^origin/master`, newest first — **12 journal commits and 1 phone commit**:

```
30958c8 2026-09-15 16:12  journal: round 50 -- the kernel's tick-collapse alarm was history; badge attention 6 to 5 ...
5f59cee 2026-09-15 01:04  journal: L1467 - resolve a number's carrier with Twilio Lookup; magicJack's measured terms
68b3b7a 2026-09-15 00:25  journal: L1466 - the Google Voice home-phone path is dead; magicJack's real price ...
cb5a2ff 2026-09-14 23:43  journal: the measured scale of P135 -- 1,807 task closures from the progress mirror
9139929 2026-09-14 23:37  journal: P135 (tasks retired by a progress mirror), D144, H208 ...
1c3f9a5 2026-09-14 23:26  journal: H207 -- the supplier delivery watchdog is built and P132 is closed ...
37fcbd0 2026-09-14 23:26  journal: L1465 - CHR30A is an access point, not a router ...
b23d997 2026-09-14 23:25  journal: P134 -- the journal has forked (936 entries only here, 304 only on origin) ...
82385ae 2026-09-14 23:24  journal: H206 heading fix (tool already writes the heading)
325f86b 2026-09-14 23:23  journal: H206 + L1462-L1464 + D143 -- the Fios home install recorded ...
5322b05 2026-09-14 23:20  journal: H205 + L1461 -- the question card is anchored to the visual viewport ...
a1290c1 2026-09-14 23:20  phone:   the question card's QUESTION was the part that went off-screen -- pin the sheet ...
ff45068 2026-09-14 23:10  journal: idempotent legacy absorption, complete pain/decisions/wins migration ...
```

By kind: 12 journal (rounds, entries, and the absorption/migration work), 1 phone/question-card UI
fix. Nothing in them is product code; none of them carries a file the 316 commits on
`origin/master` do not already contain or supersede.

The commit message the brief quotes is `b23d997`. It records the fork as **936 entries only there,
304 only on origin** — that is the 2026-09-14 measurement, taken by hand, and it has grown since.

### 1.2 Entries, by where they live

Authority working tree 1,824 entries (`entries/` files, HEAD of the throwaway snapshot) against
`origin/master` 1,541, at `2ce3ad9`:

| class | count | meaning |
|---|---|---|
| authority entry whose logical identity is **already in master** | **1,783** | nothing to do — usually under a *different id* |
| authority entry whose logical identity is **not in master** | **41** | the entire carry-in: 16 lessons, 9 handoffs, 7 decisions, 6 pain, 3 wins |
| of those 41, on **no origin ref at all** | **0** | every one is also on some preserved branch |
| **same `(kind,id)`, different body** | **403** | **the dangerous class** |
| … of those, the same entry already in master under another id | **370** | a duplicate → alias it |
| … of those, master holds no copy of the text | **33** | genuinely new text sitting on an id master already owns |
| carry-in that lands on a **free** id | **8** | `L1080 L1270 L1460 L1461 L510 L700 L890 W67` |

By path rather than by identity, the two trees share 1,023 entry paths; 801 paths are
authority-only and 518 are master-only. Of the 1,023 shared paths: **492 byte-identical**, 3 differ
only by CRLF, 1 differs only in the `<!-- j2 -->` metadata line, 124 have an identical body under a
different marker or heading, and **403 have a genuinely different body**.

### 1.3 What the dangerous class actually is — not corruption, two allocation streaks

The 403 are not damaged files. They are **two machines that independently allocated the same
number**. The tool's own side-by-side, from `journal.py pairs` on each side:

```
D39   authority: **D39 · 2026-09-14 · A verdict is cached against the thing it is about …**
      master   : **D39b · 2026-09-12 · A verdict is cached against the thing it is about …**
D41   authority: **D41 · 2026-09-14 · The kosher filter's calibration question goes to the owner …**
      master   : **D41c · 2026-09-12 · The kosher filter's calibration question goes to the owner …**
D21   authority: **D21 · 2026-09-11 · One DSH engine, many windows — not one process per window.**
      master   : **D17b · 2026-09-11 · One DSH engine, many windows — not one process per window.**
```

**Master is already the repaired side.** It carries the scar tissue — `D17b`, `D17c`, `D39b`,
`L41b`, `H78a`, and 62 base-id collisions in total — because it is the side that has been through
`repair-ids` and `append`'s bump-on-collision. The authority's copy of D39 is the *un-repaired*
pre-split text of the same entry master files as `D39b`. That is why 370 of the 403 resolve to
"same entry, different id", and it settles which side keeps the number: master's ids are the ones
master's own entries already cite in `refs=`, and README §6 forbids renumbering to tidy up.

The remaining **33** are the ones with no master twin: real text from the authority's 2026-09-14/15
work that master has never seen, landing on ids master already owns. They need a fresh id each.
Among them: `D145` (NVR-recorded evidence clips), `D148` (an owner answer — the desk light joins the
room-lights occupancy group), `H211`/`H212` (a valid code fires a 3-person intrusion alert; the door
sensors were dead for six days), and `L1468`–`L1475` (the Home Assistant evidence overhaul).

### 1.4 Why it forked, and why it stayed forked

`scripts/autosync.sh` runs from the authority's checkout **every 15 minutes**
(`*/15 * * * * /home/zabz/harness-config/scripts/autosync.sh`). Read in full, its behaviour on a
diverged checkout is:

```
if [ "$AHEAD" -gt 0 ]; then
  record attention "local commits ahead of origin ($AHEAD) — this checkout is not a place to commit; needs a human"
  exit 1
fi
```

and its own header says *"It never commits, merges, rebases, stashes, resets or force-pushes.
Divergence is reported."* The authority's copy is the **pre-fix** version. `origin/master`'s copy
carries the fix added 2026-09-14 — *"DIVERGENCE: PRESERVE FIRST, THEN REPORT"* — which pushes the
diverged commits to `refs/heads/diverged-<host>-<date>` before reporting, so a machine holding a
commit is at least discoverable.

That fix **cannot reach the authority**, because the authority cannot fast-forward — which is the
freeze. It has been reporting `attention` every 15 minutes since 2026-09-14 into a status file whose
only consumer is a sentinel noted in the script as deliberately not built. So: the fork is not
mysterious, it is a documented refusal with no reader.

**Consequence for the plan:** fixing the fork is not enough. If the authority is aligned but its
checkout still runs the old `autosync.sh`, it diverges again the first time an agent commits there.
Phase 5 below is followed by a check that the post-alignment tree carries origin's version.

---

## 2. Do `origin/master`'s commits touch the same paths? Are the conflicts content or cache?

Both, and the answer decides whether a merge is a merge or a lottery.

* `git merge-base HEAD origin/master` = `bda19d274c863803b40a3d252d06bcc1411b2ddf`.
* `origin/master`'s extra commits changed **2,891** files under `journal/entries/` across **173**
  commits, 187 under `journal/index/`, 139 elsewhere under `journal/`, and 529 outside `journal/`.
* A trial merge, run **only in the throwaway copy** and then aborted:

```
$ git merge --no-commit --no-ff origin/master
Automatic merge failed; fix conflicts and then commit the result.
--- conflicts grouped by area ---
    209 journal/entries      <- CONTENT
      5 journal/other        <- state/*.md, state/status.tsv, tools/journal.py
      4 journal/index        <- GENERATED CACHE (entries.tsv, aliases.tsv, journal.db, stamp.json)
      1 scripts/mesh-capacity-probe.ps1
      1 scripts/lpt-hub-refresh.sh
--- total unmerged files ---
220
--- auto-merged journal/entries changes ---
1832
```

So the conflicts are **not** confined to the cache. `journal/index/**` is generated (*"Disposable:
`entries/` is the truth"*, README §"The tree") and a conflict there is not a real conflict — that is
settled prior art, both by `e383047` and by the tool (`check --fix` / `index --force` rebuild it).
The 209 in `journal/entries/**` are real.

**And the number that matters most is the one Git does not print.** Only 209 of the 403
body-collisions conflict; Git auto-resolved roughly **318** of them silently, taking one side and
dropping the other out of the tree. A plain `git merge` therefore does not produce a merge conflict
the executor can inspect — it produces a tree that has quietly lost about 318 entries' worth of one
side's text. That is the failure this plan exists to prevent, and it is why the plan below does not
merge the two trees at all.

---

## 3. Losing versus duplicating, from the journal's own contract

**Duplicating is the safe failure; losing is the failure with no repair path.** Four independent
pieces of the contract say so.

1. **The record already tolerates duplication, measurably.** `journal.py dedupe` against
   `origin/master` **alone**, right now, reports **18 duplicate copies**:

   ```
   H229 == H228 · L1736 == L1698 · L1708 == L1707 · L1709 == L1707
   L1779..L1790 == L1778   (11 copies of one lesson) · L1803 == L1802 · L221a == L221
   ```

   Eleven copies of the same lesson live in `origin/master` today, and `journal.py check` still
   reports **`-- 0 error(s), 59 warning(s)`**. Duplication is not treated as corruption by this
   tree's own standard.

2. **Duplication has a named instrument; loss has none.** README §"Integrity":
   * two entries with the same identity → **`journal.py dedupe --apply`** — "moves the later copy to
   `archive/duplicates/`, records an alias". It moves; it never deletes.
   * one id, two different entries → **`journal.py repair-ids --apply`** — "renumbers, records the
   alias".

   Nothing in the tool's surface restores a deleted entry. `verify.py` is described as *"the
   independent no-loss gate"*; the rebuild procedure the README is proudest of is the one that
   *"lost nothing"*. The asymmetry is the answer.

3. **README §6, verbatim:** *"Ids are handles, not order. `L41b` exists because two machines once
   chose 41 twice; it still means that entry and always will. Never renumber to tidy up —
   `repair-ids` only exists for an id that means two different things, and it leaves an alias
   behind."* The tree's design assumes collisions happen and budgets a mechanism for them.

4. **`pairs` exists precisely to make the collision class visible**: *"historical base-id
   collisions: one number, two entries"* — 62 of them, reported identically on both sides.

**The instrument to name for the dangerous class is `journal.py repair-ids`** (renumbers the entry
whose id collides with different content, and leaves an alias). Its companions, in the order the
plan uses them: **`journal.py append`** — the only *sanctioned writer*, which allocates the id over
`entries/`, the cache, `log/**`, the flat files **and every `refs/remotes/origin/*` ref**, and which
*bumps and aliases* rather than overwriting when the target id is taken (`cmd_append`,
`journal/tools/journal.py:2891`); and **`journal.py dedupe`** for the exact-identity surplus the
union creates.

Therefore: **union first. Never resolve a collision by dropping a side.** Any procedure that lets a
merge pick a winner for 403 collisions loses ~318 of them silently, and no tool can put them back.

---

## 4. The plan

Ordering is mandatory: **the union must land on `origin/master` before the authority's checkout is
aligned**, or the authority's own view of its 41 carried entries disappears (they would survive on
the preserve branch, but the working tree would not show them).

### 4.0 Backup — DONE, and it is the rollback

```
/home/zabz/backups/harness-fork/
  harness-config-authority-ALLREFS-20260917T033457Z.bundle        14,554,538 B
     sha256 d6223383a31b1032bfb296472bcd20fc795f9f3b3d81919a7bc18d9da67a2088
     `git bundle verify` -> "The bundle records a complete history." (all refs, incl. HEAD 30958c8)
  harness-config-authority-worktree-20260917T033457Z.tar.gz       30,625,219 B
     sha256 e0b38d0ea46b54f31e877c16be00a975f8d019f02550f0c4b8cc9a52d120dfde
     the whole checkout including .git AND all 512 untracked files
  journal-untracked-entries-20260917T033457Z.tar.gz                1,320,582 B
     sha256 fc1ca93bba385b1b18f3c38232bef0c28628ac0975e4e46bf06f8814be055dce
  SHA256SUMS.txt
```

Three copies is deliberate: the bundle is the history, the tarball is the working tree, the third is
the 510 uncommitted entries alone and is small enough to move anywhere. **A second location was not
made** — copying the bundle to `ZABZ-YOGA` or the Hetzner VPS is cheap and is the first thing the
executor should do; the authority's `/` has 178 G free but is still one disk.

### 4.1 Preserve the working tree — additive, no history rewritten

```
cd /home/zabz/harness-config
git fetch origin                                   # read-only for the tree
git switch -c preserve/secratary-worktree-20260917
git add -A
git -c user.name=secratary -c user.email=secratary@local \
    commit -m "preserve: the authority's working tree on 2026-09-17 -- 510 uncommitted journal entries and 11 modified files"
git push origin preserve/secratary-worktree-20260917
git rev-parse HEAD                                  # RECORD THIS SHA. It is the rollback anchor.
```

Verify: `git log --oneline -1` shows the preserve commit; `git status --porcelain | wc -l` is 0;
`git ls-remote origin refs/heads/preserve/secratary-worktree-20260917` prints the same sha.

This is a **new branch and a new remote ref**. Nothing existing is rewritten, and deleting the
branch undoes it entirely. Note the working-tree modifications are *not* new work. Of the 11 modified
tracked files, 3 are `journal/index/{entries.tsv,journal.db,stamp.json}` — generated — and **all 8
of the code files (`assets/mobile.css`, `assets/question-card.css`, `packages/plugin-mobile/README.md`,
`packages/plugin-mobile/lib/client.js`, `packages/plugin-mobile/test/client-smoke.mjs`,
`scripts/check-phone-ui.sh`, `scripts/phone-gate.py`, `scripts/question-card-live-probe.py`) are
byte-identical to `origin/master`'s version.** They are the residue of the file-by-file copying the
brief describes. Of the untracked helpers, `scripts/lpt-hub-refresh.sh` and
`scripts/phone-gate-allow.txt` also match origin exactly, and only `scripts/mesh-capacity-probe.ps1`
differs (22,889 B against origin's 23,035 B; a comment and a naming change in `Resolve-Targets`) —
untracked on the authority, so it never conflicts.

### 4.2 Build the union on a branch off `origin/master`

```
cd /home/zabz/harness-config
git fetch origin
git worktree add /tmp/union-$(date -u +%Y%m%d) -b reconcile/secratary-$(date -u +%Y%m%d) origin/master
cd /tmp/union-$(date -u +%Y%m%d)
```

Then run the carry-in script below **inside that worktree**. It reads the authority's entries from
its preserved commit (4.1) and pushes only those whose logical identity master lacks, through
`journal.py append` — the sanctioned writer. `--body-file` is used, not `--body`; that is measured,
not stylistic (§4.6).

```python
#!/usr/bin/env python3
"""Carry the authority's unique entries into a tree that already sits at origin/master.
Run with cwd = the union worktree. Reads the source from the preserved commit."""
import subprocess, os, re, json, hashlib, collections, tempfile, sys

SRC = os.environ["SRC"]          # the preserve commit from 4.1
JPY = "journal/tools/journal.py" # in the union worktree
def g(*a): return subprocess.run(["git"]+list(a),capture_output=True,text=True,check=True).stdout
def blob(sha): return subprocess.run(["git","cat-file","blob",sha],capture_output=True).stdout
def jpy(*a):
    r=subprocess.run(["python3",JPY]+list(a),capture_output=True,text=True)
    return r.returncode,(r.stdout or "")+(r.stderr or "")

MARK=re.compile(r"<!--\s*e:([a-z]+)\|([^|]+)\|([^|]*)\|([^|]*)\|([^|]*)\s*-->")
META=re.compile(r"^<!--\s*j2\s(.*?)-->\s*$")
def parse(raw):
    L=raw.decode("utf8","replace").replace("\r\n","\n").rstrip("\n").split("\n")
    m=MARK.search(L[0]); kind,eid,date,host,status=m.groups()
    heading=L[1] if len(L)>1 else ""
    meta={}
    if META.match(L[-1]):
        for t in META.match(L[-1]).group(1).split():
            if "=" in t: k,v=t.split("=",1); meta[k]=v
        body="\n".join(L[2:-1])
    else:
        body="\n".join(L[2:])
    return dict(kind=kind,id=eid,date=date,host=host,status=status,heading=heading,body=body,meta=meta)
def title_of(kind,heading):
    h=heading.strip()
    if kind=="handoff":
        p=h.lstrip("# ").split(" · ",2); return p[2].strip() if len(p)==3 else h.lstrip("# ").strip()
    h=h.strip("*").rstrip(".")
    if kind=="pain": return h.split(" — ",1)[1].strip() if " — " in h else h
    if " · " in h:
        b=h.split(" · ")
        return " · ".join(b[1:]).strip() if kind=="lessons" else (
               " · ".join(b[2:]).strip() if len(b)>2 else " · ".join(b[1:]).strip())
    return h

# --- load both sides, identity computed by the TOOL, not by this script ---
import importlib.util, pathlib
spec=importlib.util.spec_from_file_location("J",JPY)
J=importlib.util.module_from_spec(spec); spec.loader.exec_module(J)
J.JOURNAL=pathlib.Path.cwd()/"journal"

def tree(rev):
    d={}
    for rec in g("ls-tree","-r","-z",rev,"--","journal/entries/").split("\0"):
        if rec:
            mm,pp=rec.split("\t",1); d[pp]=mm.split(" ")[2]
    return d
def ident(raw):
    e=parse(raw); return J.identity_of(e["kind"], e["heading"], e["body"])

A={p:blob(s) for p,s in tree(SRC).items()}          # the authority
have=set()
for dp,_d,fs in os.walk("journal/entries"):
    for f in fs:
        if f.endswith(".md"):
            have.add(ident(open(os.path.join(dp,f),"rb").read()))

carry=[p for p in sorted(A) if ident(A[p]) not in have]
print("carry-in candidates: %d  (expected 41 at 2ce3ad9; re-derive, do not trust the number)" % len(carry))

tmp=tempfile.mkdtemp(); res=[]
for p in carry:
    e=parse(A[p]); bf=os.path.join(tmp,e["id"]+".txt")
    open(bf,"w",encoding="utf8").write(e["body"])
    a=["--root","journal","append",e["kind"],"--title",title_of(e["kind"],e["heading"]),
       "--body-file",bf,"--date",e["date"],"--host",e["host"],"--status",e["status"],"--json"]
    if e["meta"].get("tags"): a+=["--tags",e["meta"]["tags"]]
    if e["meta"].get("refs"): a+=["--refs",e["meta"]["refs"]]
    rc,out=jpy(*a)
    res.append((e["id"],rc,out.strip()[:120]))
    if rc: print("  FAILED %s: %s" % (e["id"], out.strip()[:200]))
print("appended: %d, failed: %d" % (len([r for r in res if r[1]==0]), len([r for r in res if r[1]])))
json.dump(res, open("/tmp/carry-in-result.json","w"), indent=1)
```

Then the aliases for the 370 same-entry-different-id collisions. `append --alias-of <master-id>`
records an alias and writes nothing (README: *"A source entry whose identity the tree already holds
is recorded as an ALIAS … and nothing is written"*):

```bash
# for each (authority_id, master_id) pair from the 370 set:
python3 journal/tools/journal.py --root journal append <kind> \
    --title "<the master entry's title>" --alias-of <master_id> --body-file /dev/null --dry-run
# verify the dry run reports "nothing written", then drop --dry-run
```

The 33 that master owns with different content are handled by `append` itself: it allocates
`max(entries/, index, log/**, flats, every origin ref) + 1`, so it cannot hand out a number any
origin ref has used, and it bumps-with-alias if the target path exists anyway. In the rehearsal all
41 landed with **0 bumps and 0 failures**.

### 4.3 Verify the union — this is the gate, not a formality

```bash
python3 journal/tools/journal.py --root journal dedupe            # report only
python3 journal/tools/journal.py --root journal dedupe --apply    # collapse the surplus, alias it
python3 journal/tools/journal.py --root journal check             # MUST print "-- 0 error(s)"
python3 journal/tools/journal.py --root journal stats             # entries, per-kind
python3 journal/tools/journal.py --root journal check --fix       # only if a stale sha appears
python3 journal/tools/journal.py --root journal verify            # the independent no-loss gate
```

Every count must be **accounted for**, not merely plausible:

* entries = `origin/master`'s 1,541 **+ 41** − the duplicates `dedupe --apply` moved.
  Rehearsed: `1,541 → 1,582`, then **1** further collapse.
* `check` = **0 errors**. Warnings are expected and are not a pass condition for this task; the
  authority's own tree reports 691 warnings today and that is a separate defect.
* the duplicate pairs must be **master's 18 + the union's own**. Rehearsed: **18 → 19**, and the one
  new pair was `W193 == W26b`.
* coverage, computed with the tool's `identity_of`: **every one of the authority's 1,824 entries
  present**, and **none of master's 1,541 lost**. Rehearsed: master lost **0**.

### 4.4 Land it — manager

```
git push origin reconcile/secratary-20260917                  # additive
git switch master && git merge --ff-only reconcile/secratary-20260917
git push origin master
# then delete nothing; keep the branch until every node has pulled
```

### 4.5 Align the authority's checkout — **the one step that needs an explicit yes**

Everything before this point is additive. This step replaces the authority's working tree, which
makes it the twin of `git reset --hard` — the verb `81-overnight-program.md` §2 names. It is
nonetheless safe *because 4.1 committed and pushed the tree first*: nothing leaves the object store
and nothing leaves origin. Say so out loud before running it, per §2's "stop-and-report" rule.

```
cd /home/zabz/harness-config
git fetch origin
git merge-base --is-ancestor 30958c8 origin/secretary-journal-preserved-20260915 \
    && echo "the 13 local commits are preserved on origin: OK"   # must print OK
git switch --force-create master origin/master
```

Verify:

```
git rev-list --left-right --count HEAD...origin/master    # must be: 0   0
git pull --ff-only                                        # must be silent
python3 journal/tools/journal.py check                    # must be: -- 0 error(s)
python3 journal/tools/journal.py stats                    # must read the §4.3 count
git status --porcelain | wc -l                            # untracked build residue only; no entry files
grep -c "PRESERVE FIRST, THEN REPORT" scripts/autosync.sh  # must be 1 -- the anti-refreeze fix is now live
```

Two things must be announced before running it, not after:

* **`phone-gate.py` (pid 1905952, up 3 h 20 m) and `phone-redirector.py` (pid 2515526, up 5 days) are
  running out of this directory.** §2 forbids killing a process you did not start. Do not kill them;
  the executor decides whether they read their files per-request, and says so first.
* **the `*/15` autosync cron fires at :00/:15/:30/:45.** It never commits, merges, resets or forces
  (read in full), so its worst interference is a `git fetch`. Complete 4.5 inside one window; do not
  start it at :14. `git-health-check.sh` (`*/30`) was **not** read and may also touch this repo.

Rollback, in order of increasing severity:

```
git switch --force-create master preserve/secratary-worktree-20260917   # back to 4.1's state
git switch --force-create master 30958c8                                # back to the divergence
git fetch /home/zabz/backups/harness-fork/harness-config-authority-ALLREFS-*.bundle \
    'refs/heads/*:refs/heads/restored/*'                                # the bundle, if the repo is gone
tar xzf /home/zabz/backups/harness-fork/harness-config-authority-worktree-*.tar.gz -C /home/zabz
```

### 4.6 Two measured deviations the executor must not "fix"

* **Use `--body-file`, never `--body <text>`.** The first rehearsal used `--body` and produced
  **1 stale-sha ERROR** in `journal/tools/journal.py`'s `check`:
  `ERROR entries/wins/W193.md: metadata sha=cf41512165df6c8d does not match the body (f5cb345d742376c3)`.
  Running the identical 41 with `--body-file` produced **0 errors on the first pass**. `check --fix`
  is the documented remedy for a stale sha and clears it either way.
* **One entry disagrees between identity implementations, and only the tool's counts.** My first
  measurement (CRLF-only normalisation) *and* a faithful transcription of `norm_body` agreed with
  each other at 41 carry-ins — and after the round trip the tool's own `dedupe` still flagged one
  pair as the same entry. Byte-level, for `wins/W40` against master's `wins/W26b`: body 15 lines
  against 16, both whitespace-normalised to 1,447 characters with **identical tails**, and
  `identity_of` reports them **different** while the tool's `dedupe` pairs the written copy with
  `W26b`. I did **not** establish the cause. The procedure is unaffected — `dedupe --apply` is
  already step 4.3 and collapses exactly this pair — but the executor must **re-derive the carry-in
  list with the tool at the moment of execution and then reconcile it against `dedupe`**, and treat
  a duplicate count other than "master's + 1" as a stop.

### 4.7 Two rules this stream earned the hard way, for anyone who carries entries again

**1. A check that cannot fail is not a check.** The first carry script carried
`EXPECT = 41` and used it to *print a note* when the computed set differed. That is a comment
wearing a gate's clothes. The second script had no gate at all, and when its "already present" set
came back wrong it began appending an entire tree — 457 spurious files before it was caught (§7.3).
The correct form, now in the script: **compute the expected set, and if the computed set is not
exactly it, write nothing and exit non-zero.** The same defect appeared twice more in the same night
in other streams: the acceptance harness bound `$body` to the `-Body` parameter so every POST sent
an empty body and four sub-cases passed while testing the wrong task; a macOS audit script's `uid`
silently failed as a readonly bash builtin so every blocker check reported "none". **All three
passed while proving nothing, all three were found by running them, none by reading them.**

**2. Another writer can move the id ceiling between your computation and your write.** Ids are
allocated as `max(everything seen) + 1`, so the ceiling is a *shared* resource across live sessions.
Hence a second gate, immediately before the first write: re-read the tree and refuse if the carry
set's identities have appeared, or if the identity count moved at all. Refuse and retry; never
proceed into a tree that changed underneath you. And record the moment of the write and the entry
count before and after, so **a collision caused by a concurrent writer is distinguishable from a bug
in the carry**. The merge in §7 ran with both gates and logged
`write begins at 2026-09-17T04:10:36Z UTC · entries before 1563 · after 1576 · delta 13 of 13`.

---

## 5. Is this safe to execute unattended?

**Yes. There is no decision here that is the owner's.** I am not asking him anything, and I am not
promoting an engineering parameter into an owner question.

The reasons it is safe are the measured ones:

1. **Nothing unique can be lost.** Zero authority entries have text that exists on no origin ref
   (measured against the union of all 13 remote refs). 1,783 of the 1,824 are already in
   `origin/master` by the tool's own identity; 41 are not, and all 41 are also on preserved branches.
2. **Both sides are healthy**: `journal.py check` is **0 errors** on the authority's working tree and
   0 errors on `origin/master`.
3. **No history is rewritten.** The 13 local commits are already `origin/secretary-journal-preserved-20260915`;
   every step is a new branch, a new commit, or a fast-forward.
4. **The union is small and rehearsed end to end**: 41 appends, 0 failures, 1,541 → 1,582 entries,
   `check` 0 errors, 0 master entries lost.
5. **Three independent backups exist**, and the plan is executed on a branch.

The one thing that is not mine to wave through is §4.5's `git switch --force-create`, because §2 of
the program names `git reset --hard` explicitly and that step is its twin. It is **a stop-and-report
item, not an owner question** — it is reversible (the preserve branch, `30958c8`, the bundle), the
content is committed and pushed before it runs, and the failure mode of *not* doing it is the one
the brief is about: `git pull --ff-only` keeps refusing and every fix keeps being copied by hand.

The alternative, if that step is refused: leave `/home/zabz/harness-config` diverged and stand up a
fresh clone at a new path for the company to use. It is strictly safe and it **does not meet the
done-when** — the old checkout still cannot fast-forward — so I do not recommend it.

---

## 6. What was executed, what was not, and what could not be verified

**Executed, in order** (the plan's §4.0–§4.5, under an explicit per-action yes for §4.5):

* §4.0 backups created and re-verified, then again at execution time: `sha256sum -c SHA256SUMS.txt`
  → **OK on all three**, and `git bundle verify` → *"The bundle records a complete history."*
* §4.1 the preserve commit `1642d1a391183d0bee21e6fe459e1c90f18bfc0e`, pushed to origin **before**
  anything else, and confirmed with `git ls-remote`. It captures **523 files: 512 added, 11 modified**
  — the 11 named in §4.1, all present. `git status --porcelain` → 0 afterwards, and 0 entry files
  left untracked or ignored, so nothing was left behind for the switch to strand.
* §4.2/§4.3 the union, in a **fresh clone** (`/tmp/hc-union-<TS>`) rather than a worktree of the real
  repo: carry-in re-derived at execution time with the tool's own `identity_of` = **41**, matching
  the rehearsal exactly; **41 appends, 0 failures, 0 bumps**, `--body-file` throughout.
* `dedupe --apply` → **19 pairs collapsed** (18 of which were `origin/master`'s own, plus one the
  union created). `check` **0 errors**. `verify` → **FAIL=0 WARN=0**.
* §4.4 pushed to origin and fast-forwarded master: `2ce3ad9..d09163a`.
* §4.5 `git switch --force-create master origin/master` on the authority, after re-proving the
  preserve branch was on origin and that `30958c8` was still reachable from
  `origin/secretary-journal-preserved-20260915`.
* §7 below: a second, larger collision appeared from a live stream and was merged and landed.

**Deliberately not done:** no `git reset --hard` anywhere (including where it would have been the
easy repair — the abandoned clone was left alone and a fresh one made instead), no `git clean`, no
force-push, no rebase, no history rewritten, no process killed except one I started myself, no
`worktree` registered against the real repo, and no edit to any file other than this one.

**Not verified, and stated as such:**

* The cause of the one-entry identity disagreement in §4.6 is **still not established**. It is
  bounded and non-lossy, and `dedupe` handles the resulting pair, but it is unexplained.
* `scripts/git-health-check.sh` (`*/30`) was **not** read; whether it touches this repo is unknown.
  `scripts/autosync.sh` (`*/15`) *was* read in full, and its behaviour is the reason §1.4 exists.
* No second-location copy of the backups was made — they are on one disk. This is the weakest point
  of the rollback and it is cheap to fix.
* The authority's 691 pre-fork warnings were not diagnosed; after the alignment they are **60**, so
  most of them were the divergence itself rather than a defect. Which 60 remain was not investigated.
* `phone-gate.py` and `phone-redirector.py` were **not** restarted, per §2. They were serving from
  the aligned checkout across the §4.5 file replacement; both were still running afterwards.

---

## 7. What actually landed, and the second collision

### 7.1 The authority's half — 41 entries

`d09163a`, fast-forwarded onto `2ce3ad9`. Contents: **41 appends** (no git text merge — a trial merge
had silently resolved **318 of the 403** id collisions, and that is the count of entries it would
have dropped), **19 duplicate copies collapsed** by `dedupe --apply` (18 of them `origin/master`'s
own pre-existing ones — `L1779`–`L1790` were eleven copies of one lesson — plus `W193 == W26b`).
**Entry count 1,541 → 1,582 → 1,563 after dedupe.** `check` **0 errors**, `verify` **FAIL=0 WARN=0**.

### 7.2 The stream's half — 13 entries, and the same disease again

Between that push and the next read, another stream committed `c057738` — **also branched from
`2ce3ad9`** — so both sides allocated the same next ids from the same view. All 13 of its journal
entries collided: its `D234` was *"Shlock's canonical design sources…"* (2026-09-16, zabz-yoga) and
master's `D234` was *"Supplier orders get a ledger row…"* (2026-09-14, SECRATARY).

Resolved as a **real merge** (`c4b1b57`, parents `d09163a` + `c057738`), because a merge puts
`c057738` in master's history and the laptop can then fast-forward **with no ref move on a working
tree other streams were live in**. On the 15 conflicted paths master's side was taken (its bodies
are the landed ones), and the incoming texts were re-filed by `journal.py append`:

| incoming | landed as | | incoming | landed as |
|---|---|---|---|---|
| `D234` | **`D241`** | | `L1834` | **`L1850`** |
| `D235` | **`D242`** | | `L1835` | **`L1851`** |
| `D236` | **`D243`** | | `L1836` | **`L1852`** |
| `H424` | **`H433`** | | `L1837` | **`L1853`** |
| `H425` | **`H434`** | | `P223` | **`P229`** |
| `L1832` | **`L1848`** | | `P224` | **`P230`** |
| `L1833` | **`L1849`** | | | |

Gates, in the order they ran: computed carry set **exactly 13** (refused to write otherwise);
a fresh re-read immediately before the write showed **0** of the set already present, and the
identity count unchanged; **13 appends, 0 failures**; entry delta **13 of 13** at
`2026-09-17T04:10:36Z`; `dedupe --apply` moved **0**; `check` **0 errors**; and a coverage pass in
which **0 of the stream's entries and 0 of master's entries were unrepresented**.

The non-journal half of `c057738` merged intact — the whole point of merging rather than
re-landing the texts: `docs/mesh/{71,86,87,88}`, the seven new `packages/mesh-broker/deploy/*` and
`deploy/verify-deploy.sh`, and the modified `mesh-broker.service`, `secratary-smoke.sh`,
`broker.js`, `scoring.js`, `scoring.test.mjs`. **28 files changed, 3,582 insertions** against
`d09163a`.

### 7.3 A mistake I made, and what it cost

The second carry script computed its "already present" set with `journal.py parse_entry` and that
computation came back effectively empty. With no gate on the size of the computed set, it began
appending **an entire tree** under fresh ids. It ran nine minutes before the ssh call timed out;
by then it had created **457 spurious untracked entry files** (the journal read 2,020 against a
correct 1,563).

Nothing was committed and nothing was pushed. I killed the process (my own), **moved** all 457 to
`/tmp/hc-runaway-quarantine-20260917/` rather than deleting them, and — because `git merge --abort`
refused (a generated index file was dirty from the runaway) and the alternative was a destructive
reset — **abandoned that clone entirely and built the merge in a fresh one.** The abandoned clone
was never pushed from; `origin/master` never held any of it.

The fix is §4.7 rule 1. The lesson is that the first script *had* the constant `EXPECT = 41` and used
it for a printed note — the same shape as the other two silent-pass defects found tonight. Which is
why §4.7 now says what it says.

### 7.4 Final accounting

| | count | revision |
|---|---|---|
| `origin/master` at the start of the night | 1,541 entries | `2ce3ad9` |
| + the authority's 41 carried in | +41 → 1,582 | `d09163a` |
| − duplicates collapsed by `dedupe --apply` | −19 → **1,563** | `d09163a` |
| + the stream's 13 carried in under fresh ids | +13 → **1,576** | `c4b1b57` |

`1,576` on the authority, on `origin/master`, and in the merge clone; **`check` 0 errors** on all
three; `git pull --ff-only` succeeded on the authority (`d09163a..c4b1b57 Fast-forward`) and is a
pure fast-forward for the laptop (`merge-base HEAD origin/master` = `c057738` = `HEAD`);
`grep -c "PRESERVE FIRST, THEN REPORT" scripts/autosync.sh` = **1** on `origin/master`, on the
authority, and on the laptop — so the machine that would otherwise re-diverge every fifteen minutes
now carries the fix that reports a divergence instead of freezing on it silently.

### 7.5 The third collision, caught live — and why it is a rule, not a bug

Minutes after `c4b1b57` landed, the laptop's tree held **8 untracked journal entries whose ids were
the ones the merge had just used**: `handoff/H433.md`, `lessons/L1848`–`L1852.md`, `pain/P229.md`,
`pain/P230.md` — every one of them a *different* entry from master's, e.g. laptop `H433` is
*"Reconciled the owner's inventory sheet vs the live MDM registry…"* (04:10Z) while master's `H433`
is *"O5 THE AUTHORITY: the broker is a systemd service…"* (03:49Z). A live stream had allocated from
a view taken before the push.

Its consequence is specific and easy to misread: the laptop's **ancestry is clean**
(`merge-base HEAD origin/master` = `c057738` = `HEAD`, so `git pull --ff-only` is a pure
fast-forward), but the **working-tree update is refused** — *"The following untracked working tree
files would be overwritten by merge"*. A verifier that checks ancestry passes; a verifier that
actually pulls fails. **That failure is a concurrent writer, not a defect in the merge**, and the
only reason it is distinguishable is that the write was logged: `2026-09-17T04:10:36Z UTC`,
entries 1563 → 1576, gate 2 having proved on a fresh read that none of the 13 was present.

**Three collisions in one night** — the authority's 41, `c057738`'s 13, this stream's 8. The same
mechanism each time: `journal.py append` allocates `max(everything it can see) + 1`, and it **cannot
see another machine's uncommitted files.** So the rule is not a tool but a discipline:

> **Pull before you append, and treat an uncommitted entry in a diverged tree as an id already
> spent.** A fleet that appends first will collide every time, and the collision will always look
> like the other side's fault.

The remedy for the 8 is the same instrument as for the other two — re-file through `append`, which
bumps on collision and leaves an alias — and **never** by hand-renaming the files, which is how the
v1 tree acquired 220 duplicate copies.
