# Unabsorbed entries, quarantined 2026-09-18

Three files were found in `journal/entries/lessons/` during the 2026-09-18 car session, written there by
a checkout that was behind origin/master. They are moved here rather than deleted, because the record of
having been wrong is valuable and nothing should be destroyed.

| File | What it is |
|---|---|
| `L1749-legacy-L221.md` | A legacy-import duplicate of **L221** (same entry "Piping a journal body through PowerShell double-encodes it"), differing only in the header id, the sha, and two mojibake sequences that are themselves the subject of the entry. Safe to dedupe. |
| `L1750-legacy-shard.md` | A **legacy shard** whose first entry duplicates **L263**, but which continues with additional entries (starting "L-new · 2026-09-14 · One shared private key, named mesh…") that are **not** absorbed anywhere. This one needs `journal.py import-legacy --apply`, not dedupe. |
| `L1969-collided-variant.md` | A second, different lesson claiming id **L1969** ("A count whose collector had no input reads as a confident 0"). Origin/master's L1969 is "secretary-cf Cloudflare tunnel flaps". Two entries, one id — `journal.py repair-ids --apply` renumbers one and records an alias. |

**Why this happened:** the local `harness-config` checkout was behind origin/master, so it had stale copies
of `entries/`. A `git add -A journal` in a commit then staged them. Lesson **L1749** on origin is exactly
this failure ("local id allocation collides with a behind checkout"), which is a fitting coincidence.

**Do not `git add -A journal` in this repo while the checkout may be behind.** Add explicit paths.
