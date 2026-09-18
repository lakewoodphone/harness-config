# Recovering from a journal id collision

**What happened (2026-09-16, ZABZ-YOGA).** The local `harness-config` checkout was **nine commits behind**
`origin/master` while other sessions were writing journal entries into the same tree on other machines. `journal.py`
allocates the next free id from *the tree it can see*, so ids allocated here (`D214`, `D215`, `H395`, `H396`, `L1741`-`L1745`)
already meant **different entries** upstream. The collision surfaced on `git pull --rebase` as `CONFLICT (add/add)` on the
entry files.

**The rule that prevents it.** `git fetch` and rebase **before** writing entries, not after. A behind checkout cannot
allocate a safe id. Upstream already recorded this (`ef12b0d`); this folder is the recovery, not the prevention.

## The two scripts

| Script | Does |
|---|---|
| `classify.ps1` | backs up the whole `journal/` tree, classifies every conflicting entry file into **id free** (restore it) / **identical** (drop it) / **collision** (re-append it), clears the merge conflict on the generated `journal/index/entries.tsv`, and writes `journal-collisions.json` |
| `reappend.py` | for each collision, parses the original entry file (header comment, heading, body, `tags=`/`refs=`), writes the body to a temp file and calls `journal.py append <kind> --title … --body-file … --host …`, so the tool allocates a **fresh id** and computes a correct body sha. Adds an honest note naming the original id. |

The two scripts are the ones that actually ran on 2026-09-16, so the paths inside are hardcoded
(`C:\Users\ezabz\code\harness-config`, the backup directory, and the `journal-collisions.json` location). **Adjust the
constants at the top of each before reusing on another machine.**

## Procedure

```powershell
# 1. the pull will fail on add/add conflicts - that is the signal, not an accident
git pull --rebase --autostash origin master

# 2. classify (this backs the journal tree up first and refuses to continue without a backup)
pwsh -File classify.ps1

# 3. re-append the colliding records (slow: journal.py rewrites its cache per call)
python reappend.py

# 4. verify, then commit
python journal/tools/journal.py check      # must be 0 errors
git add journal/entries journal/index/entries.tsv
git commit -m "journal: restore N entries and re-append M id-colliding records"
git pull --rebase --autostash origin master && git push origin master
```

## Why it is safe

- A **complete copy** of `journal/` is taken before anything else, and the scripts refuse to proceed if that backup looks
  short.
- Blocking untracked files are **moved, not deleted** — copied first and hash-verified before the original is removed, so
  every byte exists in exactly one place at all times. A file written by another session *after* the backup was taken is
  detected and the script stops rather than guess.
- Afterwards, every moved record is re-checked against the tree: present and identical, or it is reported.
- Nothing is rewritten in place: a collided record is re-emitted under a new id with a note naming the old one, so no id
  ever means two things and no content is reworded in hindsight.

## Traps (each cost real time)

- **Do not kill processes by command-line pattern without excluding `$PID`** — the command you are running contains the
  pattern, so you terminate your own shell.
- **`git pull --rebase` refuses while untracked files would be overwritten** by incoming commits; that is what the move
  step is for.
- **Do not nest PowerShell inside `powershell.exe -Command "…"` from pwsh** — `\$` is not an escape and the inner command
  arrives mangled. Write a `.ps1` and use `-File`.
- `journal.py append --body` **eats backticks** when the body comes from a shell; pass `--body-file`.
- The `journal/index/entries.tsv` conflict is cosmetic — it is a generated cache, so take either side and let the tool
  rebuild it. Do not hand-merge it.
