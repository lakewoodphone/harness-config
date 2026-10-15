# 91 — the unread owner sessions, read

Shard R8-UNREAD · read by the child agent **R8-UNREAD** on host **zabz-tech** (Windows 10.0.26200, PowerShell), 2026-10-15.
Covers **all 130** ids in `secratary-cloud:/root/work/r6/90-unread-owner-sessions.txt` — no sample.
Records live in `readers/R23.md` (43), `readers/R24.md` (44), `readers/R25.md` (43) = **130 records**.

## 1. What was actually read, and how

The 130 ids were matched to their machine from `owner-sessions.tsv` (130/130 matched, none missing).
Each transcript was read with the estate's own reader, never by hand:

```
node scripts/sessions.mjs show <id> --host <machine> --max-chars 4000 --out <file>
```

run from `/root/code/harness-config` on `secratary-cloud`, with `host` taken as the `machine` column.

**Every one of the 130 decoded cleanly: 0 failed frames, 0 unparseable lines.** Per-session provenance
(absolute path, file mtime, size, kind, event count, frame count, frames-failed, and the `origin` line)
is recorded per record in the appendix files, and is summarised here:

| | |
|---|---|
| sessions fetched | 130 / 130 |
| fetch exit codes | 130 × rc=0 |
| zstd frames failed to decode | **0** |
| unparseable JSON lines | **0** |
| total bytes of the 130 transcripts (corpus index) | 11,610,499 |
| total owner/user turns (corpus index) | 139 |
| turns measured from the transcripts | 140 |

Sources: transcripts live in `~/.dsh/sessions/` and `~/.dsh/sessions-archive/` on each machine that ran
them, read over ssh by `scripts/sessions.mjs`. No transcript was read by hand and no store table was queried.

## 2. The counts

| | |
|---|---|
| records written | **130** |
| unique session ids | **130** (0 duplicates) |
| parse problems | **0** |
| outcomes | completed **60** · unknown **32** · partial **22** · failed **16** |
| severity | 1 → **116** · 2 → **10** · 3 → **1** · 4 → **2** · 5 → **1** |
| friction ids fired | **7 total**: `tool-failure` 3 · `wrong-data` 2 · `correction` 1 · `slow` 1 |
| records with a non-empty `wanted` | **4** |
| empty friction lists, stated explicitly | **123** of 130 |

The friction total is small **and that is the finding, not a soft reading**: 64 of the 130 sessions contain
no owner turn at all (see §4), and 16 more are empty stores. Of the 50 sessions that do contain the
owner's own words, 43 were ordinary questions answered well. A census that manufactured friction out of
these would be inventing evidence.

### 2.1 Per-machine split

| machine (tsv) | sessions | real owner sessions | agent-spawned subagents | empty stores |
|---|---:|---:|---:|---:|
| `secratary` | 44 | 18 | 24 | 2 |
| `zabz-tech` | 34 | 13 | 13 | 8 |
| `zabz-yoga` | 52 | 19 | 27 | 6 |
| **total** | **130** | **50** | **64** | **16** |

Host aliases, as asked, and what each actually resolved to:

| alias used | resolved to | note |
|---|---|---|
| `secratary-cloud` | hostname `secratary-cloud`, user `root`, Ubuntu 26.04.1 LTS | **the authority**; posture `writable` |
| `secratary-ts` | hostname `secratary` | **the office box, frozen rollback anchor**; posture `frozen` since 2026-10-11T05:43:36Z. Used **read-only** (transcript reads only). |
| `desktop-ts` | `zabz-tech.tail93e6e6.ts.net` — **i.e. the node this child was already running on** | `ssh -G desktop-ts` confirms it. It "succeeds", but it is a **loopback to `zabz-tech`, not a distinct host** — reporting it as a reachable peer machine would be wrong. |
| `laptop-ts` / `yoga` / `zabz-yoga` | `zabz-yoga` | posture `writable` |
| `zabz-tech` | this node | posture `writable` |

`settings/machines/host-posture.tsv` was read before any host was touched. **No service state was
started, stopped, masked, unmasked, enabled or restarted on any host.** All work on `secratary`,
`zabz-yoga` and `zabz-tech` was transcript reads and file writes under `/root/work/r8/`.

## 3. Comparison against `CENSUS-v4.md`

`CENSUS-v4.md` (the published round-4 census) reports:

| | CENSUS-v4.md (R01–R19) | R20–R22 | **R23–R25 (this shard)** |
|---|---:|---:|---:|
| reader files | 19 | 3 | **3** |
| records | 1008 | 86 | **130** |
| unique sessions | 1008 | 86 | **130** |
| duplicates | 0 | 0 | **0** |
| parse problems | 0 | 0 | **0** |
| outcomes | completed 767 · partial 158 · unknown 74 · failed 8 · abandoned 1 | — | completed 60 · partial 22 · unknown 32 · failed 16 |
| severity 4–5 | **122** (12.1 %) | — | **3** (2.3 %) |
| sessions with a want | — | — | **4** |

The comparison that matters: the sample that was read (R01–R19) carries **12.1 %** of its sessions at
severity 4–5; the 130 that were not read carry **2.3 %**. The selection rules in the shard manifest
(`shard/MANIFEST.json`: `conversation(turns>=4)` 288, `failure-dense` 646, `heavy` 15,
`stratified-machine-month` 25, `random` 34) deliberately reached for volume and failure density, and the
tell is exactly that — the unread remainder is quiet, short and mostly not the owner's own sessions at all.

## 4. The load-bearing finding: `owner-sessions.tsv` is not a list of owner sessions

**52 % of the 1,149 "owner sessions" in the corpus index are agent-spawned subagent sessions.**

The signal is `metadata_json.header.delegationDepth` in `/home/zabz/evolution-corpus-v4/sessions.jsonl`.
`delegationDepth > 0` means the session was started by another agent, not by a human; its first
user-role message is the *delegating agent's brief*, not the owner's words.

| population | n | depth 0 | depth > 0 |
|---|---:|---:|---:|
| all `owner-sessions.tsv` | 1149 | 549 | **600 (52.2 %)** |
| ids named by R01–R19 | 1008 | 472 | **536** |
| ids named by R20–R22 | 86 | 72 | 0 (14 not in the 10-14 index) |
| ids named by R23–R25 (this shard) | 130 | 66 | **64** |

Verified against known cases rather than inferred from the distribution:

| id | depth | ground truth |
|---|---:|---|
| `38f9de0f` (R01 rec 1) | 0 | ordinary owner session, "hello" |
| `02b49abf` (R01 rec 2) | 0 | ordinary owner session, owner greeting |
| `8372b842` (R01 rec 3) | 0 | ordinary owner session, owner iPhone question |
| `028daa68` (this shard) | **2** | `sessions.mjs` prints `[subagent by directory convention]` / `origin subagent parent cef0faf0`; its single "USER" turn is a **five-paragraph research brief from the parent agent** about RIASEC and the O*NET Interest Profiler |

Two independent detectors agree on exactly the same 64 ids in this shard — the `origin` header the
reader prints (64 `subagent`) and the directory-convention `class` label (64 `subagent`).

**This changes what the 130 are.** Of the 130 "owner sessions never read":

* **50** are genuine owner sessions containing the owner's own words (139→140 turns between them);
* **64** are agent-spawned subagent sessions that contain **no owner turn whatsoever** — 24 on the office
  box alone. Recording these as "the owner asked for something and got nothing" would be false;
* **16** are empty stores (3–5 events, no user row, no assistant row) — `/tmp/__dsh_verify_does_not_exist__`
  is literally one of the paths.

R01–R19 read **536** such subagent sessions and recorded them as owner records. Any census built from
those files over-counts "owner sessions" by something like a factor of two. This is a defect in the
*corpus index and the reader fleet*, not only in the unread remainder.

### 4.1 The two checks the brief asked for

**Are the 130 genuinely small, or is the `turns` column wrong?**
The `turns` column is **substantially right**. Measured the rendered owner turns for all 130 and compared:

* **129 of 130 agree exactly** with `turns`;
* **1 disagrees**: `a3b966e3-f5a4-4720-b634-1085b033f9a4` — tsv says 2, the transcript contains 3
  (the third turn is a third photo, `[image image.jpg 3024x4032]`, after "Research this fully now").
* The aggregate also moves by one: tsv sums to 139, the transcripts hold 140.

So the column is not the reason these were dropped. The brief's own explanation — a rule that filters on
volume — is the right one, and `shard/MANIFEST.json` names the rules. The brief's stated *mechanism*
("the reader brief instructs an empty friction list for one-turn sessions") is **not** what happened:
the brief has no such instruction, and the sample was drawn before any reader ran.

The 130 really are small — but the mean in the brief (89 KB) hides a bimodal spread:
min 325 B, median 57,658 B, p75 138,364 B, max 354,483 B. The corpus index's byte counts are correct
(files read matched the recorded sizes).

**Does any of the 130 contain an owner `want` that no shard records?**
**Yes — seven, and they are the same complaint.** Seven sessions contain a concrete owner request and the
transcript records **no assistant text row at all** — not a bad answer, no answer:

| id | machine | what he asked for |
|---|---|---|
| `2362fb7d` | zabz-tech | iPhone DSH broken on a trip; "Nothing comes back" |
| `e66dd54a` | zabz-yoga | the same outage again: "everything just like freezes and nothing happens" |
| `ab7c83d1` | zabz-yoga | "deep sea carnage" dead on the office desktop and iPhone — "It destroyed today's workflow. I couldn't work in my office" |
| `4a99bd5e` | zabz-yoga | fix the zabz-tech desktop workspace chooser "fully and robustly" |
| `294e5212` | secratary | how many ticks today, and which database |
| `93b3dda7` | secratary | how many ticks today, and which database |
| `a2c2b96b` | secratary | how many ticks today, and which database file |

Six further sessions with zero assistant rows (`31b363ca`, `5136b7cc`, `52803c83`, `69eb9c9f`,
`6a4c2eee`, `df5453bd`) contain only greetings and hold no want.

**A vocabulary gap this exposes.** The closed friction vocabulary has no id for *"the agent produced no
reply at all"*. `non-answer` is defined as "he got an answer that did not answer"; `stopped-early`
requires an agent that "stopped with work remaining and reported instead of finishing". Neither fits a
session where nothing was emitted. Those seven sessions therefore land in an empty friction list with the
failure stated only in `beat`, which means **the friction counts in every census built on this
vocabulary structurally cannot see the worst failure in this shard.** Adding an id for it (e.g.
`no-reply`) is a concrete recommendation.

## 5. Corpus coverage after this shard

```
1,149   owner sessions in owner-sessions.tsv (column 2)
-1,019   named by some shard among R01-R22
=  130   never named by any shard          <- the list this shard was given
  +130   read by R23-R25 (this shard)
=    0   still never named
```

So `owner-sessions.tsv` is now covered **1,149 / 1,149 = 100 %**.

By shard union rather than by the tsv:

```
1,008   distinct ids named by R01-R19            ("sample_sessions": 1008 in shard/MANIFEST.json)
+   86   distinct ids named by R20-R22
-   60   of those 86 were ALREADY named by R01-R19
=1,034   distinct ids named by R01-R22           <- matches the brief exactly
+  130   distinct ids named by R23-R25 (this shard, disjoint by construction)
=1,164   distinct ids named by R01-R25
```

The 60 is not an error in this shard: `1034 - 1008 = 26` genuinely new ids from R20–R22, so
`1008 + 26 = 1034`, and `86 - 26 = 60` duplicate ids. **Round 6's "R6-RECENT delta" re-read 70 % of its own
ids from sessions R01–R19 had already read.** Any census that merges all 25 files must de-duplicate those 60.

Coverage of the *tsv* is now complete. Coverage of the *question the owner actually asked* is not:
because 600 of the 1,149 entries are subagent sessions, the true count of owner-typed top-level sessions
in the index is **549**, and 1,019 of the entries read before this shard were "read" under a
classification that was wrong for 536 of them.

## 6. Mergeability, proved rather than asserted

Round 4's own aggregator, `reader-census.py`, was found **only at `/tmp/reader-census.py` on
`secratary-cloud`** — see §7. It was run, unmodified, over three file sets:

| reader set | files | records | unique | dupes | **parse_problems** |
|---|---:|---:|---:|---:|---:|
| R20–R23 (the brief's check) | 4 | 129 | 129 | **0** | **0** |
| R23–R25 only (this shard) | 3 | **130** | **130** | **0** | **0** |
| R01–R22 baseline | 22 | 1094 | 1034 | 60 | **0** |
| R01–R25 full merge | 25 | 1224 | **1164** | **60** | **0** |

`1224 − 1094 = 130` and `1164 − 1034 = 130`, and the duplicate count is **unchanged at 60** — so all 130
new records are new sessions and none collides with an existing one. `parse_problems = 0` on every run
means every record parsed, every `frictions` value was a valid closed-vocabulary id, and every
`severity` was an integer. The shards are mechanically mergeable.

Two notes for whoever merges: the aggregator's `--out` **writes `CENSUS-v4.md` and `CENSUS-v4.json`**, so
it must never be pointed at `/home/zabz/evolution-corpus-v4` unless overwriting the published census is
intended (all runs here wrote to scratch directories). And `--readers` is a flat directory scan of `*.md`,
so the new files must be copied into the readers directory rather than passed as paths.

## 7. What contradicts this brief

1. **"130 owner sessions" is not accurate.** 64 of the 130 are agent-spawned subagent sessions and 16
   are empty stores. Only **50** contain the owner's own words. The corpus index they were drawn from
   misclassifies subagents as owner sessions at 52 % across all 1,149 entries.
2. **The 130 were not skipped for the reason the brief gives.** The brief says the reader contract's
   "empty friction list for one-turn sessions" is "almost certainly why they were skipped". The reader
   brief contains no such instruction, and the selection happened before any reader ran.
   `shard/MANIFEST.json` records the real reason: `per_shard: 55`, `sample_sessions: 1008`,
   `coverage_pct: 87.73`, with explicit rules `conversation(turns>=4)`, `failure-dense`, `heavy`,
   `stratified-machine-month`, `random`. R01–R19 was a **declared sample**, not a census, and the unread
   130 is its complement. (The brief's *conclusion* — that a volume filter would drop exactly these — is
   correct.)
3. **`reader-census.py` is not in the authority's checkout.** The brief says to run
   `harness-config/scripts/evolution/reader-census.py`. That directory contains only `deliver-persona.py`.
   `find / -iname '*reader*census*'` returns exactly one hit: **`/tmp/reader-census.py`**. The script's own
   docstring and the published `CENSUS-v4.md` both cite `scripts/evolution/reader-census.py`, a path that
   no longer exists anywhere on the authority. It was recovered and run from `/tmp`.
4. **The `turns` column is not the defect the brief suspected.** 129 / 130 agree exactly; one session is
   off by one.
5. **`host-posture.tsv` does not name the alias this estate actually uses for the laptop.** The file's own
   header requires that "every one of those names must be present" for a host. It lists `zabz-yoga-1` and
   `laptop-ts` — but **not** `zabz-yoga` and **not** `yoga`, which are the names in the ssh config
   (`Host laptop yoga zabz-yoga`), in `owner-sessions.tsv`'s `machine` column, and in `sessions.mjs`' node
   list. An agent arriving as `zabz-yoga` would not be found by the posture guard.
6. **`ssh desktop-ts` "succeeding" is misleading.** It resolves to `zabz-tech.tail93e6e6.ts.net` — the
   very node this child was running on. Reporting it as a reachable peer would overstate fleet reachability.
7. **R20–R22 are not a delta.** 60 of their 86 ids were already read by R01–R19.

## 8. What I deliberately did not do, and what I could not verify

Not done, on purpose:

* **No sample.** All 130 were read. No session was inferred from its id, its size or its neighbours.
* **No service state on any host.** No start, stop, mask, unmask, enable, disable or restart, on
  `secratary` (frozen), `secratary-cloud` (the authority), `zabz-yoga` or `zabz-tech`. `secratary` was
  touched read-only for transcript reads only.
* **No transcript was dumped into a context.** Every read went to a file with `--out` and was then
  digested; the digest was read, not the raw render.
* **No push, no `main`, no `reset --hard`, no `checkout .`, no `clean`, no `rm -rf` outside `/root/work/r8`.
  Nothing outside `/root/work/r8` and `/root/work/r6` was written. No git repository was staged or committed.

Could not verify, and therefore not claimed:

* **Whether any subagent session held an owner turn I could not see.** For the 64 subagent sessions I
  asserted only what two independent signals show — `delegationDepth > 0` and `origin subagent`. I did not
  open their parents to see whether an owner want upstream was ever satisfied. `51c4a691` (the child that
  actually wrote the handoff-media standard) and `22620a00` (the child that refuted a candidate row)
  plainly did land work, but the owner's satisfaction with it is not in these transcripts.
* **Whether the 7 unanswered sessions were answered elsewhere.** They may have been re-reported in another
  session that did get an answer — `2362fb7d`, `e66dd54a` and `ab7c83d1` look like three reports of one
  outage. I checked only that *these* sessions contain no assistant text row.
* **The semantics of the `o` field** in `owner-turns-final.jsonl` (values 8, 9, 22, 44, …). It behaves
  like an origin code and correlates with the subagent split, but nothing in the corpus documents it, so I
  did not build any claim on it. The `delegationDepth` finding does not depend on it.
* **Severity is a reading, not a measurement.** 116 of 130 records are severity 1 because the sessions are
  genuinely uneventful or empty, not because nothing happened in the estate that week.
* **The quotes are clipped at the source.** The digest clips each owner turn at 320 characters, so where a
  quote ends in `…` in the appendix it is a prefix of a longer turn, not the whole turn. Short turns
  (the great majority here) are complete and verbatim, typos included. For the two long research briefs
  (`07551492`, `1c28428e` and siblings) the span quoted is the complete opening of the brief.
* **One transcription error was caught and fixed, not hidden.** The first pass wrote the wrong tail for
  `c7de045c-…`; a verification pass comparing all 130 `## ` headings against the source id list caught it,
  and it was corrected. The final files were re-verified: 130 records, 130 unique ids, 0 missing, 0 extra,
  0 duplicates, all friction ids inside the closed vocabulary, all seven fields present on every record.

## 9. Artefacts

| file | what |
|---|---|
| `readers/R23.md` | 43 records, sessions 1–43 |
| `readers/R24.md` | 44 records, sessions 44–87 |
| `readers/R25.md` | 43 records, sessions 88–130 |
| `91-unread-census.md` | this file |
| `evidence/digest.md` | the per-session digest the records were written from, with provenance and both turn counts |
| `evidence/reader-census.py` | round 4's aggregator, recovered from `/tmp` on the authority |
| `evidence/unread-rows.tsv` | the 130 ids joined to their `owner-sessions.tsv` rows |
| `evidence/turns-comparison.json` | tsv `turns` vs turns measured from each transcript |
| `evidence/host-posture.tsv` | the posture file read before touching any host |
