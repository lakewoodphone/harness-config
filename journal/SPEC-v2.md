# SPEC v2 — the journal as a record store, not a document

Contract for the rebuild of `harness-config/journal`. Written 2026-09-14 by Zabz on
ZABZ-YOGA. Evidence for every target is in `AUDIT.md` beside this file.

## 0. What must not change

1. **The tool is the only writer.** Every mutation goes through `tools/journal.py`.
2. **The log is append-only.** An entry is never edited to look better in hindsight; a
   correction is a *new* entry citing the old one. Status changes are rows in
   `state/status.tsv`. Only the state tier (`NOW.md`, `state/in-flight.md`, generated
   files) is rewritten, and each carries `Updated:`.
3. **Never destroy data.** No command deletes an entry, a shard or a flat file. Moving
   anything out of a live path requires `--apply`, is a `git mv`-able move into
   `archive/`, and leaves a resolvable record (alias row) behind.
4. **Provenance.** Every read a human sees names its source and age; an empty result is
   a refusal, not health. Nothing is reported as working because it was configured.
5. **One source of truth per thing.** Owner questions: `owner_decision_queue` on the
   authority (this tree holds a generated mirror). Harness config: `harness-config`.
   Company data: the authority.

## 1. On-disk layout

```
journal/
  FORMAT                     "2\n" — format generation. Read by check and doctor.
  README.md                  the map; rewritten by this change.
  AUDIT.md SPEC-v2.md        this change's evidence and contract.
  NOW.md                     STATE. Rewritten. Capped inputs are enforced by status.
  state/
    in-flight.md             STATE, hand-written. status displays a capped slice of it.
    status.tsv               append-only status corrections.
    open-pain.md             GENERATED (state).
    owner-questions.md       GENERATED mirror (questions).
  entries/<kind>/<id>.md     THE LOG. One file per entry. 781+ files.
  index/                     GENERATED CACHE. Disposable; source of truth is entries/.
    entries.tsv                v1-compatible columns (see §4) so a stale v1 tool still
                               reads correct ids.
    aliases.tsv                alias_id -> canonical_id, so old references resolve.
    stamp.json                 the signature of entries/ the cache was built from.
    journal.db                 sqlite3 + FTS5, regenerable, gitignored.
    README.md
  log/                       FROZEN legacy shards (absorbed). Never read except by
                             import-legacy and check's drift test.
  archive/                   flat files, duplicates, migration record. Never read
                             except by search --legacy and import-legacy.
  reference/                 topic documents (unchanged).
  tools/
    journal.py               v2, the only writer.
    selftest.py              the format/CLI/migration tests.
    archive/journal-v1.py    frozen v1, for the compatibility test.
    archive/selftest-v1.py   frozen v1 tests.
    bin/journal.cmd  bin/j   convenience wrappers (PowerShell/cmd and POSIX).
```

Git matters: one file per entry means two machines appending simultaneously write two
different files and **cannot** conflict. That is the structural answer to defect 10.

## 2. Entry file format

An entry file is a **single-entry shard**, byte-identical to the block v1 wrote into a
shard, plus one optional trailing metadata comment:

```
<!-- e:lessons|L173|2026-09-14|ZABZ-YOGA|open -->
**L173 · The title**

The body, exactly as written, in as many paragraphs as it needs.
<!-- j2 tags=journal,provenance refs=L172,D50 sha=4f2a91c3 alias_of= -->
```

Rules:
- Line 1 is the **v1-exact** marker (`^<!--\s*e:(kind)\|(id)\|(date)\|(host)\|(status)\s*-->$`).
  Do not add fields to it; a stale v1 `show`/`next-id` must keep working.
- Line 2 is the heading, one line, produced by the v1 `build_heading` rules.
- The body is the whole rest of the file, verbatim (`norm_body` applied exactly as v1
  did, so migration is a pure split, not a rewrite).
- The **last** line may be `<!-- j2 k=v k=v -->` with `tags`, `refs`, `sha`, `alias_of`.
  It is stripped on render. Its presence is optional; parsing must not require it.
  `sha` is `entry_hash(heading, body)`; when present, `check` recomputes it and an
  unequal value is an ERROR.
- No other lines are added. Empty body is legal (some old lessons live entirely in the
  heading) — do not invent content.
- File name is the id: `entries/pain/P46b.md`. `show` must be a direct path lookup when
  the id is exact, so it opens exactly one file and no index.

## 3. The index is a cache, and it must never be believed stale

`index/entries.tsv`, `index/aliases.tsv`, `index/stamp.json` and `index/journal.db` are
all generated from `entries/`. Any read command calls `ensure_cache()` first:

1. Compute the **tree signature**: sha1 over `sorted((relpath, size, mtime_ns))` of every
   file under `entries/`, plus the count. Cost: one stat per file (< 20 ms for 800).
2. If it equals `stamp.json`, the cache is fresh — use it.
3. If not, rebuild the cache in-process (parse entries, rewrite tsv/aliases/db), write
   the stamp last, and print one line to stderr: `journal: cache rebuilt (N entries)`.
   If the mutation lock cannot be taken because another session holds it, **do not
   block a read**: report `cache is stale and locked by <owner>` on stderr and answer
   from `entries/` directly.
4. If the cache is missing or unreadable, treat it as stale. Never abort a read because
   of a cache.

The signature must also detect a **wiped** cache: v1's `index` command regenerates
`entries.tsv` from `log/`, so a stale machine can empty it of real rows. The stamp check
catches that and rebuilds.

## 4. `index/entries.tsv` keeps v1's shape (deliberate)

Header and column order stay exactly as v1 had them:

```
kind  id_full  num  suffix  date  host  status  heading  file  line_start  line_end  hash
```

with `file` = `entries/<kind>/<id>.md`, `line_start` = 1, `line_end` = last line number,
`hash` = `entry_hash`. Reason: a machine still running v1 must be able to read ids
correctly (its `remote_max`/`next-id`/`show` depend on this file), or it will start
allocating from 1 and recreate the collision scar. Verified by the compatibility test
in §10.

`index/aliases.tsv`: `alias_id  kind  canonical_id  reason  date`.

## 5. Query surface — the flags that did not exist

Global: `--root PATH` (default: the parent of `tools/`, so it works from any cwd),
`--json`, `--budget BYTES` (default per command), `--quiet`, `--no-color`.

| Command | Flags | Behaviour |
|---|---|---|
| `status` | `--budget`, `--json`, `--full` | The always-read page. **Assembled under the cap**: each section is written through a budgeter that truncates and appends `… (+N more)`; exit **0** even when truncated. Sections: header with time/host/format, capped `NOW.md`, newest handoff one-liner, counts per kind, open pains (top 8 by id, capped), owner questions count + mirror age, capped `state/in-flight.md`, legacy-drift line, cache state, `check` summary (cheap rules only). Target ≤ 6,000 B, < 0.4 s. No subprocess, no full-tree grep. |
| `list` | `--kind K` (repeatable), `--status S`, `--since D`, `--until D`, `--tag T`, `--host H`, `--limit N` (default 50), `--sort newest\|id`, `--long`, `--json`, `--budget` | one line per entry: `id  date  status  host  title`. Never prints bodies. |
| `newest KIND [N]` | `--kind/-k`, `-n`, `--full`, `--budget` | back-compatible with `newest handoff 2`. |
| `show ID...` | `--full`, `--budget`, `--refs`, `--json`, `--all` | exact id → one file. Base id matching several entries prints all of them with a note (never silently picks one). Aliases resolve with a one-line note. |
| `search PAT...` | `--kind`, `--since`, `--until`, `--status`, `--tag`, `--limit`, `--context N`, `--budget`, `--regex`, `--all-words`, `--legacy`, `--sort relevance\|newest`, `--json` | FTS5 when available and the pattern is not a regex, else a bounded scan of `entries/`. Prints id + heading + matching lines with context, never a whole file. Exit 1 when nothing matches (an empty result must be visible). |
| `backlinks ID` | `--budget` | which entries reference this id (from the refs table). |
| `pairs` | `--limit` | the historical base-id collisions (two distinct entries, one number), so a reference can be disambiguated. |
| `stats` | `--json`, `--top N` | counts, bytes, per-kind/per-month table, biggest entries, open/closed, tags, oldest untouched. |
| `kinds` | — | what lives where, one line per kind, with letters and counts. |
| `state` | `--budget` | regenerate `state/open-pain.md` (bounded, ranked, counts). |
| `questions` | `--offline`, `--budget` | mirror `owner_decision_queue` into `state/owner-questions.md`; degrades to the existing mirror if the authority is unreachable, and says so. |
| `check` | `--fix`, `--quiet`, `--json`, `--budget`, `--max-warn N` | integrity, see §6. Exit non-zero **only** on ERROR. |
| `costs` | `--json` | measure and print the read-path cost table (bytes + wall ms for status/list/show/search/newest) plus tree sizes. This is how the acceptance targets stay honest. |
| `doctor` | `--json` | one screen: format version, root, entry count, cache freshness, lock state, legacy drift, writable, python/sqlite/FTS5, git remote reachability (the only network-ish check, skipped with `--offline`). |
| `append KIND` | `--title`, `--body -`/`--body TEXT`/`--body-file F`, `--date`, `--host`, `--status`, `--tags a,b`, `--refs`, `--alias-of`, `--dry-run`, `--no-fetch`, `--json` | the only writer. Positional form `append lessons --title T --body -` must keep working. Absorbs legacy drift first. |
| `resolve ID` | `--status`, `--why` | appends a row to `state/status.tsv`. Also `--alias-of` to record a duplicate. |
| `import-legacy` | `--apply`, `--dry-run` (default), `--json` | absorb everything in `log/**` and the six flat files (and `archive/legacy-*/**`) that is not in `entries/`, with an exact-content proof. |
| `migrate-v2` | `--apply`, `--dry-run` (default), `--json` | split `log/**` shards into `entries/` files one-for-one, then run `import-legacy`. Idempotent. |
| `dedupe` | `--apply` | exact-content duplicates: keep the lowest id in place, move the other's file to `archive/duplicates/<kind>/<id>.md`, write an alias row, reindex. |
| `repair-ids` | `--apply` | renumber an entry whose id collides with different content, writing an alias from the old id, so no id ever means two things again. |
| `gc-legacy` | `--quiet-hours N`, `--apply` | move `log/**` into `archive/legacy-shards-<date>/` once no file there has changed for N hours, leaving `log/README.md` and a re-creatable directory so a stale v1 writer still lands somewhere absorbable. |
| `index` | `--force`, `--stats` | rebuild the cache explicitly. |
| `selftest` | — | runs `tools/selftest.py`. |

Rules: **no subprocess on any read path.** `git` may only be used by `next-id`,
`append --fetch` and `doctor`. Every command that prints a body or a list obeys
`--budget` by truncating with a visible marker; a read never fails because a page was
long.

## 6. Check rules (exact, so it can be quiet)

ERROR (exit 1): a duplicate id with **different** content; a malformed entry file
(missing/unparseable marker, heading that does not match its kind, id in the file name
that disagrees with the marker); a `sha=` in the metadata that does not match the body;
a marker with a kind that is not in KINDS; `entries/` unreadable.

WARNING: an alias whose canonical id is missing; an entry with an empty body (INFO if
it is one of the known heading-only lessons — detect by kind, not by a hardcoded list);
a ref that resolves to nothing **and** is absent from the whole tree (dangling refs are
computed from the cache's refs table plus a scan of `entries/` only — never a grep over
`log/` or `archive/`, which is what made the old check take 8.9 s); legacy drift
(entries in `log/**` or flats not yet absorbed) with the **true** count; cache stale for
longer than the last write; `state/` older than the newest entry.

INFO: historical base-id collisions (count + `pairs`), entries out of order, entries
never referenced, `archive/duplicates` size.

The WARNING summary line must always print the three counts, and `check --quiet` prints
only the summary and any ERROR.

## 7. Ids

`next-id KIND`: max over (a) `entries/`, (b) `index/entries.tsv`, (c) every local and
remote git ref (`git grep` for the marker pattern, exactly as v1 did — this is the part
that stopped two machines choosing the same number), plus an optional `git fetch` with a
short timeout, skipped by `--no-fetch`.

**Never write a colliding id.** `append` re-checks the chosen id against
`entries/<kind>/<id>.md` immediately before writing; if that path exists with different
content, it bumps to the next free number, writes the entry, and prints
`id bumped L190 -> L242 (collision avoided)`. An id may only be reused for byte-identical
content, and then it is written as an alias, not a second file.

Writes are atomic: write a temp file in the same directory, then `os.replace`.

## 8. Migration (this is where the data can be lost — do it in the open)

`migrate-v2 --apply`:
1. Take the mutation lock.
2. `import-legacy` first, so nothing that exists only in a flat file is left behind.
3. For every shard file under `log/**`: parse with the **v1** parsers (copy them from
   `tools/archive/journal-v1.py`, they encode the two bugs that mattered — the wrapped
   bold heading and the empty body), and write each entry to `entries/<kind>/<id>.md`.
   The block is copied verbatim: marker, heading, body. **No reformatting.**
4. Rebuild the cache; run `check`.
5. Print a report: entries written, entries skipped as already present (same id + same
   hash), ids bumped (with the collision it avoided), and a **byte-preservation proof**:
   for every source shard, `sum(len(block))` of its entries vs the source's content
   bytes, and the count of source lines accounted for. Non-zero unexplained residue must
   fail the migration.
6. Idempotent: a second run writes nothing and says so.

`import-legacy` uses the exact identity key `entry_hash(heading, body)`; a legacy entry
is *absorbed* when an entry with that hash exists, *added* when it does not, and
*aliased* when its id is taken by a different entry. It must report all three counts,
and it must find 175 lessons, 34 decisions, 21 pains and 16 wins (the audit's numbers)
or explain the difference.

## 9. Compatibility with machines still running v1

Non-negotiable, because the fleet drifts: `index/entries.tsv` keeps v1's columns (§4),
entry files start with v1's marker (§2), and `append`'s legacy absorption means a v1
append that lands in `log/` after the migration is absorbed on the next v2 write or
`import-legacy`. The test in §10 must prove the frozen v1 tool can still `show` an
entry through the v2 index.

## 10. Acceptance tests (the subagent must run these and paste the evidence)

1. `python tools/selftest.py` — all pass. Cases must include: marker parse (well-formed,
   extra field, glued, mid-line), heading build per kind, `entry_hash` on heading-only
   entries, metadata parse/strip, base-id vs suffixed-id resolution, budgeter truncation
   marks the cut and never exceeds the budget, front-matter-less file, sha mismatch.
2. **Migration fixture**: build a synthetic legacy tree in a temp dir (two shards with a
   duplicate handoff across them, a wrapped-heading flat `LESSONS.md` with one entry not
   in the log, a `PAIN.md`, an entry with an empty body, an entry whose id collides with
   different content). Run `migrate-v2 --apply --root TMP`, then assert: every source
   entry's `entry_hash` is present exactly once; the collision was bumped and aliased;
   `check --json` reports 0 errors; a second `migrate-v2 --apply` writes nothing; every
   legacy id resolves through `show`.
3. **Byte preservation** on the real tree, run against a **copy** (never the live tree):
   for each shard in the copy's `log/`, the concatenated blocks of its entries equal the
   shard content after whitespace normalisation, and the residue is 0. Report the numbers.
4. **Cost**: `journal.py costs --json --root <copy>` → status output bytes ≤ 6000, exit 0,
   status < 1.0 s; `show` < 30 ms; `search` < 300 ms; and confirm by instrumentation that
   `show` opens exactly one file.
5. **Concurrency**: launch 6 `append` processes at once against a fixture; assert 6
   distinct ids, 0 errors, and that a serial `check` is clean.
6. **v1 compatibility**: with the frozen `tools/archive/journal-v1.py`, run
   `show <an id>` and `next-id <kind>` against a migrated fixture; assert the heading and
   body come back and the id is not below the real maximum.
7. **Windows and Linux**: the tool must run on `python3` on the authority (`ssh
   secratary-ts`); no `os.uname()` without a guard, no POSIX-only paths, `newline="\n"`
   on every write, UTF-8 everywhere.

Do not run `--apply` against the real `journal/`. Use `--root` on copies. Return: what
you built, the test evidence, anything you could not do, and the file list.
