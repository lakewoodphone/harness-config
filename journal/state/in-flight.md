# IN FLIGHT — work that is open right now

Updated: 2026-10-05 21:5xZ (ZABZ-TECH, Weinberg settlement session — H3215). Previous: 2026-09-17 17:2xZ (ZABZ-YOGA, id-allocation session — L1928, `docs/mesh/108-id-allocation.md`); 2026-09-17 16:45Z (ZABZ-YOGA, journal convergence — merge `3568d39`, `docs/mesh/107`); 2026-09-17 16:40Z (ZABZ-YOGA, mesh closing session — W203); 2026-09-16 16:05Z (SECRATARY, containment + documentation session - H390)

## New since 2026-10-05 21:5xZ — two branches waiting on an integrator, and one payment waiting on the owner

**A. `personal-secretary-mvp` — branch `docs/weinberg-arrears-banner` (commit `cb6cc664`) is pushed and
unmerged.** It banners the two finance docs that still quote the retracted 2,208.31 Weinberg arrears
(`payroll-arrears-2026-09-10.md`, and the SEE ALSO line in `lpt-profitability-problem-2026-09-04.md`) and
points them at the settled figure. It was cherry-picked onto `origin/master` rather than pushing local
`master`, which is 118 ahead of `origin/master` while `origin/master` is 279 ahead of it — **do not
`git pull --rebase` local master onto origin/master to "fix" this; hand the branch to the integrator.**
A duplicate of the same content also sits as local `master` commit `7caf8314`; blobs are identical, so a
merge will not conflict.

**B. `lpt-hub` — nothing unmerged.** All five Weinberg commits are on `origin/main` (`420fb7336`,
`45e7e17e5`, `fa28d7d71`, `7ec51b5f0`, `1bc13d20a`).

**C. Waiting on the owner, not on an agent:** he pays Yisroel Weinberg **663.46 in cash** (gross basis;
597.29 net) and will say when. On that word: record the date and amount in
`lpt-hub/docs/operations/payroll/Weinberg-2026-09-28/` (`RECEIPT-2026-10-05.md` is the receipt to get
signed), append to the payroll log, resolve owner-queue #162, close task 27207, and clear the ten held
duplicate reminders in `owner_message_queue` that still read 597.29 (task 27673 owns the fan-out bug, and
its text requires the owner's yes before a bulk send or delete).

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

## 2026-10-19 01:05Z (ZABZ-YOGA) — THREE SESSIONS ARE WORKING THE OWNER QUEUE. THE SPLIT IS RECORDED HERE.

The owner is running three concurrent queue sessions and told each to take a different section.
Read this before touching an `owner_decision_queue` row; the rows below are claimed.

| Session | Section | Rows |
|---|---|---|
| `d49559c6` (local, "Work through my queue one at a time") | money + household: rent/zelle/utilities ledger, bank overdrafts, returned payments, service bills | closed 698, 636, 645, 631, m2631; deferred 646/693/640, 644; then moved into the **Home Assistant / apartment-access cluster** 714–721, 711 |
| `4d070efd` (local, "Start queue processing from middle") | account security + shop website: carrier 2FA/sign-ins, site copy, published prices, promo mail | closed 634/635/637, dismissed 628; reading 557, 558; next 656, 694 |
| `76d2fc46` (this session) | **CUSTOMERS — everyone who called, texted or is waiting on an answer from the shop** | 606, 600, 590, 595, 592, 591, 608, 605, 614, 616, q12a8, q2ba8 |

**Row ids are the claim.** There is no lease or claim column in `owner_decision_queue` — `card` just
returns the top-ranked row, so two sessions both running `card` collide by construction. Coordination
is this table. A fourth session: pick a section not listed above and add a row here in the same
commit, before answering anything.

**Measured facts behind the customer section (2026-10-19 01:15Z, read this session, so the next
session does not re-run them):**

* Five people asked the shop for help on the owner's Google Voice line between 7 and 14 October and
  none became a job: `848-525-4002` (#606, computer won't turn on), `732-962-2080` (#600, Canon
  camera), `848-986-3948` (#605, brother's laptop), `845-671-6665` (#595, wants to buy a Kyocera),
  `201-566-7852` (#592, "get my phone today").
* **None of those five numbers exists in production.** `customers.phone` normalised with
  `right(regexp_replace(phone,'[^0-9]','','g'),10)` returned **0 customer rows and 0 orders** for
  each, queried with `psql` against the DSN in `/root/personal-secretary-mvp/.env` on the authority.
  The only number in that list that IS a customer is `848-389-7895` = "TEST Zabz ; Eliyahu
  Zabrowsky" — which is why #590 (voicemail, no `Number:` field in its card) is probably the owner
  himself, not a lead.
* `732-962-2080` is a **repeat customer**: Canon camera, Dec 2025, paid and picked up
  (`dialpad_call_full` 2025-12-03 / 2025-12-04), so "no production customer" does not mean "never
  served".
* The comms index holds **zero rows** matching `8485254002` (exact search, index age 0.46 h,
  181,166 indexed) — the Google Voice lineage reaches the queue through Gmail
  (`owner-queue-ingest-gv.py` → `gmail_service` + `parse_gv_email`), **not** through the comms
  index, so a reply sent from the Voice app leaves no trace here. Never call that absence proof
  that nobody replied.

**Owner rule 2026-10-19, verbatim:** *"No, I dont respond to business questions on my personal
line. If I see it right away, maybe I'll respond to Reach out to the business number, but I'm not
responding later."* and, minutes later on a 14-day-old family ask: *"It's way later they don't need
help anymore. And you didn't bring this up when they asked so. There's nothing to do right now."*
Two standing consequences, both now implemented or in flight:
1. A stranger's shop enquiry on his Google Voice line is **never his queue item** — it becomes a
   task for the shop (subagent `subagent-107` is patching `owner-queue-ingest-gv.py`).
2. **A stale ask is closed, never surfaced.** Measured cause of the 13-day lateness of rows
   613/614/616/617: `owner_queue_ingest_run` has **zero `gv` runs before 2026-10-18** (earliest
   15:13Z that day) — the ingest is one day old, every run reads a 3-day window, and the
   2026-10-18T13:11Z backfill wrote 5-Oct messages as pending. Nothing could have reached him on
   5 October. Unfixed: stale-on-arrival should be written closed, and a voicemail with no phone and
   no name should be dropped at ingest (#590 was one, now dismissed).
3. 31 rows closed by this session tonight (606/600/605/595/594/592, 613/614/616/617/591/608,
   618/619/622/623/700/597/598/621/602/603/589/633/607/612/712/722/723/724, 590). The visible
   working set went **69 → 39** (`owner-queue.py queue`, 01:02Z vs 01:32Z; the other two sessions
   closed their own).

## 2026-10-19 01:35Z — THE AUTHORITY IS AT 96% AND THAT OUTRANKS THE QUEUE. MEASURED.

| what | number | how |
|---|---|---|
| root filesystem | **150 G total, 138 G used, 6.6 G free, 96%** | `df -h /` on secratary-cloud, 01:12Z |
| the queue's own row #711, filed ~5.9 h earlier | 93% full, 10.7 G free | `owner-queue.py queue` title |
| ⇒ consumed in ~6 h | **4.1 G** | the two lines above |
| `/root/authority.db` | **31.2 GiB, and it is ALL live data** | `pragma page_size/page_count/freelist_count` = 4096 / 8,180,535 / 1,732 |
| biggest table | `dsh_session_events` **2,692,243** rows | `select max(rowid)`; every other table is 3–4 orders smaller (dsh_sessions 8,690; activity_log 333,147) |
| the same bytes already packed off-box | **51,669 objects, 256 shards**, manifest 56 MB, last pull 00:23–00:24Z today, `"nothing new to send"` | `/opt/company/archive/lpt-transcripts/{manifest.sqlite,objects,logs/pull-20261019.jsonl}` |
| cold agent work dirs | ~**5 G** (`r4-preserve` 1.9G, `r4-loop` 1.3G, `r4-integration` 1.3G, `fd-*` 0.47G) — newest file **2026-10-16 08:42** | `find /root/work/*/ -printf` |
| derived search index | `/root/.usearch/usearch.db` **10.1 G** | `find /root -size +2G` |

**The trap that decides the plan:** deleting rows from SQLite **frees no disk** until a `VACUUM`, and
a `VACUUM` needs ~31 G of free space, which is exactly what we do not have. So space must be freed
elsewhere **first**, and only then can the database be compacted. `/opt` is not the culprit (chromadb
2.2 G is its largest) and the archive's `incoming/` is 0.02 G.

**Awaiting the owner's yes** (deletions are his call): (1) remove the Oct-16-cold work dirs (~5 G),
(2) prune `dsh_session_events` older than 90 days and then `VACUUM` (file 31 G → ~11 G). Unattributed:
the 4.1 G consumed in ~6 h has no identified writer yet; baseline taken at 01:12Z.

