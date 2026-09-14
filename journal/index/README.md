# index/ — generated, disposable, and now provably fresh

Nothing here is a source of truth. `../entries/<kind>/<id>.md` is; every file in this
directory is rebuilt from it, and any read command rebuilds it without being asked.

| file | what it is |
|---|---|
| `entries.tsv` | one row per entry — **v1's exact 12 columns**, so a machine still running the frozen `tools/archive/journal-v1.py` reads correct ids |
| `aliases.tsv` | `alias_id -> canonical_id`, so an old reference still resolves |
| `stamp.json` | the signature of `entries/`, `log/` and the flat files this cache was built from |
| `journal.db` | sqlite3 (+ FTS5 when the build has it): `entries`, `refs`, `aliases` and `meta` tables, regenerable at any time |
| `README.md` | this file |

## Why it can be trusted

Every read calls `ensure_cache()`, which hashes `(relpath, size, mtime_ns)` for every file
under `entries/`, plus the frozen `log/**` and the flat files, and compares that with
`stamp.json`. If it differs — including when the cache was *wiped*, which is what an old
checkout running v1's `index` does — the cache is rebuilt from `entries/` before anything
is read, and one line goes to stderr: `journal: cache rebuilt (N entries)`.

If the rebuild cannot take the lock because another session is writing, the read is **not**
blocked and **not** silently answered from a stale cache: it says
`cache is stale and locked by <owner> — answering from entries/` and reads the files
directly. A missing or unreadable cache is treated as stale, never as an error.

## entries.tsv columns (unchanged from v1, on purpose)

```
kind  id_full  num  suffix  date  host  status  heading  file  line_start  line_end  hash
```

`file` is `entries/<kind>/<id>.md`, `line_start` is 1, `line_end` is the entry file's last
line, and `hash` is `entry_hash(heading, body)` — sha1 of the heading and the
whitespace-normalised body. The columns stay exactly as v1 left them so a stale v1 tool
still computes the right `next-id` instead of allocating from 1 and recreating the
collision scar.

## Useful greps

```
grep -P '\tpain\t' entries.tsv | cut -f2,7            # every pain id and its status
awk -F'\t' '$3==46' entries.tsv                        # everything numbered 46, in any kind
grep -P '\topen$' entries.tsv                          # ids with no proof of done
cut -f1,3 aliases.tsv                                  # every id that resolves elsewhere
```

Rebuild it explicitly with `journal.py index --force --stats`; read freshness, the lock,
the legacy drift and the cost of every read path with `journal.py doctor` and
`journal.py costs`.
