# IN FLIGHT — work that is open right now

Updated: 2026-09-17 17:2xZ (ZABZ-YOGA, id-allocation session — L1928, `docs/mesh/108-id-allocation.md`). Previous: 2026-09-17 16:45Z (ZABZ-YOGA, journal convergence — merge `3568d39`, `docs/mesh/107`); 2026-09-17 16:40Z (ZABZ-YOGA, mesh closing session — W203); 2026-09-16 16:05Z (SECRATARY, containment + documentation session - H390)

Rewritten, not appended. Earlier sessions still live in this file: **ZABZ-TECH credential session, 2026-09-15 20:05Z**
(AWS key killed D164, Twilio token rotated D165, H275 - its open work is at the END of this file, do not overwrite it) and
the comms session (ZABZ-YOGA, 14:05Z).
*(Corrections: H208 cites "D142" for the digest decision — it is **D146**. H389 addenda 3/4 said the API fix was holding —
**H390 supersedes that**; it was not a fix.)*

## New since 2026-09-17 17:2xZ — THE JOURNAL ID ALLOCATOR, and a reverted `origin/master`

**A. `journal.py append` now writes LOCALLY ONLY and cannot move any ref. Read this before the
   next journal write on any machine.** The previous version claimed a window and pushed it
   inline, and on 2026-09-17 that reverted `origin/master` while recording a lesson:
   commit `79efb088`, parent `53cf517`, **1249 paths deleted and all 1728 journal entries gone**,
   exit 0. Cause: the parent COMMIT came from the just-fetched tip but the parent TREE came from
   the stale local `refs/remotes/origin/master` (13 commits behind), and a commit whose tree is
   not its parent's tree is a mass deletion. Restored with the owner's explicit authorisation
   (`--force-with-lease` naming the exact old value), content-verified: 1728 entries, `check`
   0 errors. Full record and every measurement: `docs/mesh/108-id-allocation.md` §5.

**The workflow from here, once per machine per window (~64 ids per kind):**

```
journal.py claim lessons     # explicit; reserves and PUBLISHES; refuses if it cannot confirm the ref
journal.py append ...        # local only; never touches a ref
```

`claim` with no kind covers all five kinds. `next-id KIND --plan` says whether a write would be
allowed without performing one. **If `append` exits 4, the machine has no reservation for that
kind: run `claim`.** Nothing is bricked — inside a window it already holds, a machine keeps
writing offline, and it only refuses at the window's edge with no reachable ref.

**B. The allocation rule is fixed and proved.** `journal/tools/verify-alloc.py` — 21 checks,
0 failures. The pre-change tool (from git `622876e`) mints `L2` on **both** machines; the new
rule has the first claim `L2..L65` and the second fetch that claim and mint `L66`. `selftest`
239/240 → **240/240**; `check` 0 errors before and after.

**C. Two smaller defects fixed:** every mutating command leaked `journal/.lock` (two causes: the
ownership test could not read its own lock file on Windows, then the unlink preceded the close),
and `note_git_ceiling()` is no longer dead code.

**D. Still open, recorded not fixed:** `check` cannot see a cross-tree collision (single-tree by
contract; the cheap fix is `git hash-object --stdin-paths` locally plus `git ls-tree -r
origin/master` upstream, and the right home is `idguard`, not `check`), and `idguard` undercounts
because it reads a generated cache a committing writer must remember to rebuild.

**E. Evidence left in place deliberately.** Local-only branch `broken/alloc-claim-20260917`
holds the bad commit `79efb088`. `refs/heads/alloc/zabz-yoga` also still points at it. Neither is
a live ref on the remote; do not build on either.

## New since 2026-09-17 16:45Z (ZABZ-YOGA, journal convergence — `docs/mesh/107-journal-convergence.md`)

A. **CLOSED — the journal collision, on this machine, and pushed.** The 18 contested ids were re-derived from source
   and resolved on `origin/master` at **`3568d39`**: origin keeps its entry at every contested id, this machine's
   conflicting entry moved to a fresh id allocated by `journal.py append --body-file`. The map —
   `D252→D256, D253→D257, D254→D258, H464→H480, H465→H481, H466→H482, H467→H483, H468→H484, L1906→L1920,
   L1907→L1921, L1908→L1922, L1909→L1923, L1910→L1924, L1911→L1925, L1912→L1926, P242→P249, P244→P250,
   P246→P251` — is a file: `journal/reference/id-collision-20260917-renumber.tsv`. The 8 vacated old-id paths are
   **moved, not deleted**, to `journal/archive/collided-ids-2026-09-17/`. Gates: `check` **0 errors**,
   `verify` **FAIL=0 WARN=0**, no-loss **1728 = |L ∪ O| = 1728, delta 0**, selftest 239/240 (the one failure
   reproduced on the unpatched tool). **The 23 entry files that existed in NO commit anywhere are now committed
   (`622876e`) and pushed**, so `checkout`/`clean`/`pull` can no longer destroy them. Two corrections to the record
   this replaces: it was **23** uncommitted entry files, not nine; and a one-sided renumber *does* converge when the
   mover merges origin first and renumbers above the merged high-water mark **including the other machine's recorded
   unpushed ids** — which is what happened here, and the laptop pushed first.

B. **STILL OPEN — the defect that generates the next collision. Both machines now mint from the same refs.** After
   `3568d39` the next free id is **`D259, H485, L1927, P252, W204` on BOTH machines** (measured, and the frozen v1
   reader agrees: `v1 next-id lessons -> L1927`). The next pair of concurrent writes recreates exactly this defect,
   and none of `check` / `idguard` / `repair-ids` can see it. **Obligation: `zabz-tech` must merge `origin/master`
   before its next journal write** — `append` fetches by default, so it will then mint above `L1926` instead of at
   `L1927`. That is a timing promise, not a mechanism. The real fix is still the **reserved band per machine, or a
   host suffix on the id**, that `D191`/`D198` asked for and that does not exist. Highest-value follow-up here.

C. **This machine's working tree is `0 ahead / 11 behind` and cannot fast-forward.** `git merge --ff-only
   origin/master` refuses **atomically** (HEAD and the other file unchanged) on `scripts/lpt-hub-refresh.sh` —
   another stream's staged, uncommitted work, three different blobs: worktree+index `f458cef…`, `HEAD dc4287e…`,
   `origin 679e27a…` — and on `journal/state/absorb-stamp.json` (generated, touched by the journal tools as other
   streams write). **Nothing is at risk while it waits**: `622876e` and `3568d39` are both on `origin`. One
   `git merge --ff-only origin/master` completes it once that stream commits its file.

D. **`P243` was restored, deliberately.** It existed at `HEAD` and on `origin/master`, had been deleted in this
   working tree with **no status event, no reference from any entry and no commit** explaining it, and the merge would
   have honoured that deletion **silently** (delete-local + unchanged-upstream). Origin's copy is back. The deletion
   is still visible in Git history, so a stream that meant it can repeat it in one command — dropping a unique entry
   is the more expensive error.

E. **`zabz-tech`'s live engine (pid 24556, started 09:32:02) is still pre-placement** and needs one restart in an honest
   idle window to consult the broker (D247, doc 106 §5). It was NOT restarted by this session, and it should now
   succeed: the junction is repaired, the provider resolves at `0.2.0` from both reader classes, and `desktop-ts` from
   its own Interactive logon class returns exit 0 in 402 ms. The same machine's `ssh` from *inside* an ssh session hangs
   for every destination (measured) — probe it as an Interactive one-shot task, never over ssh.

F. **Tool defects, and exactly which are fixed.** `repair-ids --apply` wrote the renumbered copy and **left the
   offending file behind**, so the tree still failed `check` after the "repair" (reproduced on a synthetic tree,
   `journal.py:3711` pre-fix) — **FIXED and proved** in `3568d39`: it now moves the replaced file to
   `archive/collided-ids-<date>/<kind>/` and records host/sha/source on the alias row, the way `dedupe` always has
   (`2 errors → 0 errors`). **Characterised, not fixed:** `check` cannot see a cross-tree collision at all
   (single-tree by contract — it would take `git hash-object --stdin-paths` locally plus `git ls-tree -r origin/master`
   upstream, and the right home is **`idguard`**, not `check`, which is on the read path); `idguard` reads the
   generated `journal/index/entries.tsv` and **undercounts** (9 when the answer was 10 — `zabz-tech` committed
   `D254/H474/L1914/P247` without rebuilding it); and `note_git_ceiling()` is **dead code**, so
   `allocation_ceiling`'s `git_ceiling` field is `{}` on every machine. **Newly measured:** `questions` and
   `import-legacy` each leave `journal/.lock` behind **after exiting 0** (reproduced twice, holder pids dead) — that
   is the single check `selftest` fails (239/240) and it is a real defect, not a flake. `_lock_holder_is_dead()`
   makes it benign for the tool, but a stale lock makes every later reader ask whether a writer is live. Stale locks
   left by this session's own runs were found in **both** trees and removed; the exit path that fails to release was
   not chased.

## Open right now

1. **`secretary-api` memory runaway — CONTAINED, NOT FIXED (P211).** The 09-15 fixes (`44e3f8e8`, `ce20ab28`) moved the
   failure interval from 6.5 minutes to 30–60 minutes but did not stop it: **23 OOM kills on 2026-09-16** (hourly, 00:00 →
   13:18) after **8 on 2026-09-15**, all at ~20.2–20.8 GB `anon-rss`, plus a SIGBUS at 14:35 on 09-16. Containment applied
   2026-09-16: `MemoryHigh=5G MemoryMax=8G MemorySwapMax=1G` on the unit (drop-in `20-memory-guard.conf`, runtime
   `set-property` too, reversible without a restart). **The allocator is still un-named.** Armed: `~/phone/oom-evidence/
   burst-catcher.sh` (6 h window, 2 s poll, py-spy dumps at 5 GB) — give it HOURS; a 40-minute watch against a 30–60 minute
   interval is a coin flip (L1735). Next levers in order: `app/workforce.py:1417` per-tick `ThreadPoolExecutor` +
   `shutdown(wait=False)` (unbounded abandoned ticks), the reviewed-but-unapplied
   `docs/incidents/2026-09-15-secretary-api-oom/proposed-hard-heap-limit.patch`, then `ANALYZE` (never run on the 5.5 GB
   database — no `sqlite_stat1` exists). Full evidence + numbers: `harness-config/docs/incidents/2026-09-15-secretary-api-oom/`.
2. **RattleByte ticket #188880 (portal id 2553) — reopened with the owner's photos, waiting on the vendor.**
   Portal: *"Reopened by info@lakewoodphoneandtech.com 16/09/2026 00:11"*, **three client messages** — the back-plate photo
   (`01-back-panel-full.jpg`, 541.1 kb) and the full reply as an attached `.txt`, because the portal silently stored only the
   first **122 characters** of the 2,900-character reply it reported as posted (L1733). Asked of Eriks: is
   `RattleByte-Panasonic-BD83-V1.84-R1-Solderless-Initial` right for this exact unit, and what triggers the Initial install.
   **One item still owed to him: the OEM Main Version screen** (HOME MENU → Setup → Player Settings → System → System
   Information → Firmware Version Information → Main Version). Case log on `main` at
   `lpt-hub/hardware-diagnostics/panasonic-dmp-bd84-rattlebyte-diagnostic-2026-09-12.md` (§F5 photos, §F6 verbatim
   correspondence); commits `738baba47` + `7effbfed4`. Free retry that needs nobody: a 256 MB–2 GB USB stick, single
   partition, FAT32 formatted on Windows, `PANA_DVD.FRM` alone at root. The portal session expired — request a fresh access
   link via `view.php` → "Check Ticket Status" (email + ticket number) before looking for a reply; it will never arrive by
   email (L1512).
   `shutdown(wait=False)` (unbounded abandoned ticks), and `ANALYZE`, which has never run on the 5.5 GB database.


## Done — the comms objective is met

Texts **127,678** (2025-04-18 → live) · calls **12,552** (2025-10-20 → live; the far end probed
in 2024-10, 2025-01, 2025-04, 2025-06, 2025-07 and 2025-09, `read=0 stored=0 errors=0` each time,
so the oldest call is the account's first and not the harvest's horizon) · voicemails **916**
records with audio fetched for every one Dialpad will still serve · **transcripts: 6,497 calls
carry Dialpad's own text and 1,101 carry a transcript we made from the audio, and the queue is
0** · index **166,939 with 0 missing** (2026-09-15 14:00Z), base = fts = trigram, rebuilt on
`:07`/`:37` and swapped in atomically · five read modes through the live API, the CLI and MCP,
registered so agents find them · staleness visible on both halves, with the cron failing on
either. Spend **~$10.90 of the ~$36 cap**.

**Do not re-open the ceiling.** **6,055 calls can never have words**: 74 hold a file that is not
audio, 1,258 hold media URLs Dialpad refuses with HTTP 404, and 4,797 have no audio URL at all —
Dialpad neither recorded nor transcribed them, because its AI transcription only appears in this
account's data from around April 2026. Of the 916 voicemail calls, 312 are readable and 604 are in
that bucket (**L1481**, **L1479**).

## Done — the reader layer, 2026-09-15 (H224, H225)

The index was built and kept fresh; the *reader* was not usable by an agent. Measured: 34
calls to `comms_search` through the live API, every one of them mine — the fleet had been
told to use it and could not. Fixed: parameter aliases and `**extra` (an agent guesses
`query=`, and a guessed key used to be dropped, leaving FTS5 to answer
`syntax error near ""`); every query tokenised and quoted (`screen replacement?` was a
syntax error); the loose fallback drops stopwords, orders by bm25 and reports
`match_mode` + the terms used (a sentence used to return `It's a iPhone 16 pro max`);
`_party_filter` is shared by search and thread (they disagreed about who "Dovid" is, so
`thread Dovid` returned 0 while `search --party Dovid` returned his messages); opt-outs
have their own bucket (a `Stop` sat at the top of `waiting`); `search --party X` with no
keywords works; `--line` gives a digest one age-carrying summary line.

**The owner can now see it**: digest section **1c** prints
`🔔 N customer(s) waiting on a reply (last 3 days)` and nothing when N is 0. Verified by
running the digest as cron does — 6.1 s end to end. (`D146`'s line, delivered.)

`scripts/comms-verify.py` (harness-config) is the regression battery: **13 assertions**
through the live HTTP dispatcher and the CLI. Run it after any change here.

**Two measurement rules earned in this batch:** HTTP 200 is not success — `{"ok": false}`
rides inside a 200, so a log full of "200 OK" is not evidence a tool worked (**L1503**);
and any search that loosens must be relevance-ordered, name the terms it used, and say it
loosened (**L1504**).

## Running — four cron entries, nothing session-dependent

| Job | Schedule | What says it worked |
|---|---|---|
| **Dialpad harvest** (calls, sessions, transcripts) | `*/30` | Freshness in `health`: newest SMS 0.4 h, newest call 0.8 h |
| **Media fetch** (`dialpad-recording-gap.py --limit 300`) | `*/5` | Dry run selects ~0 (only calls the harvest added minutes ago) |
| **Transcript gap** (`dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600`) | `*/10` | Dry run selects **0**. Cumulative budget inside the tool (6,000 min ≈ $36) |
| **Index refresh** (`~/.fsearch/comms-refresh.py`) | `7,37` | Exit 0; `comms_state.json`; **builds beside the live file and swaps it in atomically**, so no reader sees a half-built table |

**Read this before touching them.** Ten defects, all one family: **a job that runs, exits 0 and
produces nothing.** A flag that never reached the layer doing the work; selectors that joined the
media **row** and never tested the **file**; a multi-URL call judged from one joined row; a scan
window too small to see the work; three writers where `database is locked` discarded completed
work — in one case work already **paid for** (**L1484**); a selector re-offering URLs Dialpad had
already refused; and a selector re-offering files that are not audio. Every one was found by
measuring the job's *subject* rather than watching its exit code.

## Also settled, with evidence

* **A dynamic tool edited in place is deployed on the next call** — `run_tool` reloads when the
  file is newer than the loaded copy; proven by editing the installed file (the next API call
  returned the change) and reverting it.
* **`--shard I/N` partitions the work** by `rowid % N`, so several transcription processes can run
  at once without paying twice for the same call. It took the rate from ~3/min to ~24/min.

## Mine, measured and waiting on a trigger

| Item | What would show it |
|---|---|
| **Names for the unnamed people** | 1,226 people, ~922 named; 43 of 60 `waiting` rows still show a bare number. A read-only subagent is measuring which of the business's own records (repair jobs, invoices, orders, lpt-hub case files, contact exports) hold name↔phone mappings, and how many of the unnamed they would cover. Biggest single lever on every other view. |
| **`display_name` can be a source LABEL, not a person** | `7325036369` has 1,669 communications and reads as **"Microsoft Word"**, because `dialpad_sms_cache.customer_name` says so — the source says it, so this is not a merge error, but an agent will be misled. 38 of 1,226 names look non-human by a rough filter and most of the rest are legitimate businesses. Needs a deliberate design pass (prefer evidence-weighted names; fall back to the number), not a blocklist guessed in a hurry. |
| **The fleet still does not reach for it** | 34 calls, all mine. The tool can no longer dead-end; nothing yet puts recent comms in front of an agent at the moment a customer speaks (inbound message or task context). |
| **Kernel index-age metric** (**P131**) | `ck/sentinel.py` was being edited by another session, so a change there collides. `health` exposes it to agents and the cron fails on ingestion staleness. |
| **The softer re-transcripts** | Calls that already have Dialpad text and could be re-transcribed from better audio for ~$45. Now the only transcript work left, and it is a quality swap, not a gap. |
| **The authority's app checkout is a third lineage** (**P143**) | 57 commits reachable from no remote (now backed up as `backup/secratary-checkout-20260915`), 136 behind origin/master, 75 dirty files. Needs a dedicated reconciliation session; never scp a whole file into it — patch the single hunk (`/tmp/pt.py` pattern). |

## Credential session, 2026-09-15 20:05Z (ZABZ-TECH) — full record **H275**, decisions **D163–D165**

Closed tonight: the AWS AdministratorAccess key in `phone-and-tech-full/backend/.env.test` is deleted
and verified dead (**D164**); Lakewood's own Twilio auth token is rotated through Twilio's
secondary-token path, every consumer patched and restarted, the old token now 401 (**D165**).
Device Parts is out of favour by owner instruction (**D163**).

Still open, mine:

| Item | State |
|---|---|
| **ZABZ-YOGA's app stack** | DONE 19:58Z — patched, restarted, `/health` 200 with token fp `c4e6`. The earlier "unreachable" was Tailscale on ZABZ-TECH being stopped, not yoga. |
| **Tailscale on ZABZ-TECH** | Root cause found and fixed at the cause (**D172**): IP Helper crashed at 15:40 local and Windows stopped Tailscale as its dependent; iphlpsvc's own recovery never restarts it. `scripts/ensure-mesh-prereqs.ps1` + the 5-minute task 'DSH Mesh Prereqs (5m)' now repair iphlpsvc first, then Tailscale, then the LAN portproxy — verified by breaking it on purpose. **Still open: the other five nodes have no such watch.** |
| **Dead plaintext in the repos** | The leaked AWS key and Twilio token strings are still in `phone-and-tech-full` and `personal-secretary-mvp`. Both are inert now, so this is hygiene plus a pre-commit secret gate — not done inside another session's dirty tree. |
| **Outworq LLC's Twilio token** | Still live in `personal-secretary-mvp/deploy/twilio-studio-flow/.env.vogel`, verified active. Client account — queue **#17**, needs Shimon. |
| **IAM leftovers** | `github-actions-deployer` holds an unused AdministratorAccess key; root has MFA disabled and no root access keys; `~/.twilio-cli/config.json` holds two API-key secrets (not affected by an auth-token rotation). |
| **Local desktop API startup** | ~6 minutes to `Application startup complete` (Chroma telemetry warning last line before it). `scripts/restart-api.ps1` waits only 45s, so it always reports failure — **L1566**. |

---

## In flight — appended 2026-09-15 22:5xZ (ZABZ-YOGA, self-audit round 59; entry ids renumbered by the convergence)

*(Ids below are the POST-convergence numbers: the local lineage was renumbered because two
machines had allocated the same ids for different entries. Map:
`_scratch/merge-20260915/renumber-map.tsv`. Old numbers, for anyone holding them:
H255→H349, L1537→L1664, L1538→L1665, D158→D190, P159→P197.)*

- **The journal divergence is CLOSED.** 62 upstream commits merged (`8e135b4`), 98 cross-machine
  id collisions resolved by renumbering the local lineage onto fresh ids (`a009aaa`), pushed,
  `behind/ahead: 0 0`. `journal.py check` = 0 errors; `verify` = FAIL=0 WARN=0; index 1,211
  entries. The 15-minute HarnessSync task now returns `[clean]`, exit 0 —
  `~/.dsh-sync-status/status.json` says `result: clean, behind: 0, ahead: 0`.
- **Found while doing it:** the repo had been left mid-merge with 103 unresolved paths by a
  session that pulled from the authority's *working copy*; cleared. The autosync script itself
  was innocent — it never merges or rebases, and had been reporting the divergence correctly
  every 15 minutes all along.
- **Shipped earlier this round:** `check_owner_queue` in `~/ceo-kernel` (`9962993`, `491e4ef`) —
  the next owner decision, one at a time, in the badge payload. Owner queue 14 → 11 pending;
  evolution proposals 12 → 0.
- **Mine, not his, still open:** enable cheap-first routing as a *measured* change; repair Google
  Voice monitoring over CDP; find why a medical task routed to `finance_bookkeeper`; fix the
  generic-refactor proposer template once `app/evolution.py` is free (another session holds it).
- **Blocked on another session, not the owner:** anything touching `app/evolution.py` or
  `app/workforce.py`.
- **Loose ends to remember:** (1) row #39's resolution carries a `CORRECTION:` clause — an
  earlier version claimed a config row was deleted before the delete had run (L1664); (2)
  `_scratch/merge-20260915/` holds both sides of every collision and must not be deleted until
  someone has confirmed nothing needs recovering from it.

