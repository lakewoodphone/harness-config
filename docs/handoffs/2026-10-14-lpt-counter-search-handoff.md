# HANDOFF — LPT website: the counter search that could not reach a finished job (2026-10-14)

**Written by:** the DSH session on ZABZ-YOGA that did the work, at the owner's instruction to retire
and hand over. **Read this whole file before touching anything.** Everything below is either a
measurement with its command, or a named open question with the evidence needed to close it.

**Repo:** `lakewoodphone/phone-and-tech-full` (the shop's website + staff app).
**Worktree used:** `C:\Users\ezabz\code\_lpt-wo-search` (branch `lpt/counter-all-statuses-20261014`, HEAD `9af3741f7`).
**Integration branch:** `origin/test` = **`af0c5c416`** (this work is MERGED and DEPLOYED).
**Production (`main`) is BEHIND and has NOT been promoted with this work.**

---

## 0. State at a glance

| # | Thing | State | Where it lives |
|---|---|---|---|
| 1 | The owner's reported defect (search could not find a finished job) | **DONE, merged, deployed, verified end to end on test** | PR #441 → `af0c5c416`; proof script below |
| 2 | The class it belongs to (filters/controls whose label lies) | **OPEN** — audited, 4 controls reported LIES, none fixed yet | §4, and the audit report §9 |
| 3 | The ROADMAP class box | **OPEN, deliberately unticked** — tick it ONLY after §4 is fixed and the audit is quoted | `docs/website/ROADMAP.md` (in `test` now) |
| 4 | Production promotion (`test` → `main`) | **OPEN** — `main` does not carry this fix | §5 |
| 5 | `autonomy-status.sh` called a capped system dead | **FIXED LIVE on the authority, patch UNMERGED in harness-config** | §6 |
| 6 | `harness-config`'s copy of `autonomy-status.sh` is stale vs the live file | **OPEN**, ledger item 217 | §6 |
| 7 | CI: all four `Test Frontend` shards wedge | **KNOWN, NON-BLOCKING** since #443; do not chase unless it blocks | §7 |

---

## 1. What the owner reported, verbatim

> "when I search in the website in the global search for work orders or information and work orders,
> it only searches within whatever filters currently set, which would not be such a problem if there
> was a way to set the filter to all. But when you do all on the filter, like all, it only searches
> open work orders. It doesn't search any of the other statuses, so you need a way to be able to turn
> the filter to actually do all, not just open, and that way you could also search everything.
> Otherwise ridiculous when you put in something to search then you have to click every type of filter
> in order to search that type. There's no global search for real."

Filed through the owner channel as ledger item **216** (`owner-feedback.py add`) and as an
`OWNER-FILED (P3)` row at the top of the website queue.

## 2. What it actually was (read in the source, not inferred)

The page he is on is **the counter at `/work-orders`**. `frontend/src/App.tsx` mounts `CounterPage` at
exactly `/work-orders`, above `MVPRouter`, so `MVPRouter`'s own `'/work-orders': <WorkOrdersHub />`
never renders. ("The work orders page" = the counter; a fix in `pages/WorkOrdersHub` would have been
a fix to a screen nobody sees.)

**Root cause.** `frontend/src/features/staff-intake/staff-intake-list-queue.ts` had ONE scope value
behind TWO controls:

- `type StaffStatusFilter = WorkOrderStatusKey | 'ALL'`
- the `Open` chip and the `All statuses` radio BOTH set `status: 'ALL'`
- `queueStatusesFor()` in `staff-intake-list-query.ts` mapped `'ALL'` to `WORK_ORDER_OPEN_STATUS_VALUES`

So the control labelled **All statuses** asked `workOrders.getAll` for the four statuses in which the
device is still with the shop. `READY_FOR_PICKUP`, `CANCELLED` and `UNFIXABLE` were **never in the
payload** — no client-side filter could reach them, and the search box (which searches within the
scope in force) inherited it. Clicking each finished status individually DID work, which is exactly
the "you have to click every type of filter in order to search that type" he reported.

## 3. What was changed, and what proves it

### Files
- **NEW** `frontend/src/features/staff-intake/staff-intake-status-scope.ts` — `OPEN` / `ALL`,
  `statusFilterSet()` (the set each selects), `statusMatchesFilter()` (the row test), and the two
  scope sentences. **One rule, read by BOTH the request builder and the row filter** — that unity is
  what stops the request and the screen disagreeing again.
- **NEW** `frontend/src/features/staff-intake/staff-intake-case-counts.ts` — the open-ticket count,
  split out because the queue module is at the repo's enforced 500-line ceiling.
- `staff-intake-list-queue.ts` — `OPEN` is the default (so the default screen is unchanged), `ALL` is
  all seven; `readStatusParam` falls back to the DEFAULT (never the widest) on an unreadable `?status=`;
  `describeEmptyQueue` now names the scope that emptied it and the control that widens it. Re-exports
  both new modules, so no caller changed.
- `staff-intake-list-query.ts` — `queueStatusesFor()` now returns `[...statusFilterSet(filters.status)]`,
  i.e. **all seven go to the server** for `ALL`.
- `staff-intake.utils.ts` — `isOpenIntakeCase` keeps every open counter ticket under both scopes.
- `components/StaffOpenListFilters.tsx` — `All` is now a CHIP one tap from the search box; the two
  scopes each state what they mean under them; the sr-only note states both.
- Tests updated/added in `__tests__/staff-intake-list-queue.test.tsx`,
  `__tests__/StaffIntakePage.test.tsx`.
- **NEW** `e2e/personas/verify-search-reaches-finished-jobs.mjs` — the end-to-end proof (below).

### Commits (branch `lpt/counter-all-statuses-20261014`)
- `9d6815ce1` fix(counter): All statuses means every status, so a search can reach a finished job
- `057342db3` refactor(counter): one module for the status scopes, one for the ticket counts
  (the lint failed on `custom/max-file-lines` 528/500; the split is the honest fix, not an eslint-disable)
- `9af3741f7` test(counter): a mechanical before/after for the search that could not reach a finished job
- merge `af0c5c416` into `test` (PR #441)

### Evidence, all run and all green
```
pnpm --filter phone-and-tech-frontend lint        # 0 errors (3 pre-existing warnings in WorkOrdersTable.tsx)
pnpm --filter phone-and-tech-frontend typecheck   # exit 0
pnpm test:frontend:one -- <5 files>               # Test Files 5 passed (5) / Tests 169 passed (169)
pnpm test:frontend:one -- <3 more suites>         # Test Files 3 passed (3) / Tests 38 passed (38)
```
(the five: `staff-intake-list-queue.test.tsx`, `StaffIntakePage.test.tsx`, `staffOpenListDesktop.test.tsx`,
`counterStatusNames.test.tsx`, `routes/__tests__/CounterPage.test.tsx`)

**End-to-end, on the LIVE test site — a before and an after from the same script:**
```
node e2e/personas/verify-search-reaches-finished-jobs.mjs
  BEFORE (pre-deploy, exit 2): shelf rows found 78, a real shelf job's printed number = 12724,
        search under `Open` = 0 rows (correct), and NO `All` chip on the page
        -> "THIS DEPLOYMENT HAS NO `All` CHIP - the fix is NOT deployed here"
  AFTER  (post-deploy, exit 0): the SAME search, 12724 -> `Open` 0 rows, `All` 2 rows
        -> PASS: "search reached a finished job under `All` (2 row(s)) and did not under `Open` (0)"
```
The script needs an auth state: `npx playwright test --config=e2e/personas/personas.config.ts --project=persona-auth`
(env `E2E_BASE_URL=https://test.lakewoodphoneandtech.com`) writes `e2e/personas/.auth/admin.json`
(gitignored; the personas and their TEST credentials are hard-coded in `e2e/personas/lib/personas.ts`).

**Deploy:** run `38648886231` for `af0c5c416` — **completed success**. The served test bundle changed
with it, and the `All` chip is present in the deployed app (the AFTER run above proves both).

## 4. THE OPEN WORK, in priority order

### 4.1 Fix the filter controls whose label lies (the class the owner's report belongs to)
**Status: audited, NOT fixed, and NOT yet reproduced by a human.** The audit was done by a mesh
subagent; per this estate's rule, **re-read each file:line below and reproduce the claim before you
change anything**. The full report is at §9.

| # | Control | Verdict (as reported) | Where |
|---|---|---|---|
| 1 | Quotes list `Pending` tab | **LIES** — no `PENDING` in the `QuoteStatus` enum; the value is refused | `frontend/src/pages/quotes/QuoteListPage.tsx:874` |
| 2 | Quotes list `Total Quotes` card | **LIES** — the count is the ACTIVE status's count | `frontend/src/pages/quotes/QuoteListPage.tsx:760` |
| 3 | Admin FAQ `All Status` | **LIES** — the payload is pre-narrowed before the client filter sees it | `frontend/src/features/admin/faq/components/FaqTable.tsx:175`, narrowed at `FaqManagementPage.tsx:284` |
| 4 | Intake `All (N)` chips | filter honest, **the COUNT lies** | `frontend/src/features/repair-intake/components/RepairIntakeQueueOverviewPanel.tsx:123`, `.../RepairIntakeCaseCreatePanel.tsx:193` (the second is never mounted — verify) |
| 5 | Receipts `All Statuses` | **UNPROVEN** — `receipt.list` throws, so no where exists to read | `frontend/src/components/payments/ReceiptsTab.tsx:422` |
| 6 | Payments dashboard `All Statuses` | honest, but a SILENT 20-row cap | `frontend/src/features/payments/components/PaymentsDashboard.tsx:268` |
| — | 10 further controls (quotes/commits/FAQ/orders/customers/intake) | reported HONEST with quoted evidence | see §9 |

**Definition of done for this section:** each LIES is either fixed and re-proved the same way the
counter fix was (a test that pins the request AND the row list, plus a live check where the surface is
reachable on test), or written up as deliberately out of scope with the measurement that justifies it.
**Do not** tick the roadmap box before this is done.

### 4.2 Tick the roadmap class box — but only with the sweep in hand
`docs/website/ROADMAP.md` carries a new **unchecked** `OWNER-FILED (P3)` row ("A filter must mean what
its label says, and a search must be able to reach everything"), plus a change-log row for the counter
fix. Ticking the box is a CLAIM: it needs the sweep list (per control: the request it produces, quoted
from the code path) pasted into or cited by that row. `roadmap-supply.py` on the authority files one
ledger item per unchecked box, so leaving it unticked keeps the class on the queue — that is intended.

### 4.3 Promote `test` → `main` (production)
`main` does not carry the counter fix or the other merges of 2026-10-14. The procedure is written in
`docs/website/ROADMAP.md` §MERGE HYGIENE, Rule 2, and the head-branch name is ENFORCED
(`guardian/promote-test-to-main*`). "Verify" means from OUTSIDE: `api.lakewoodphoneandtech.com/health`
must name the new merge commit AND the served bundle must carry the change. **Merged is not live.**
Note the repo's own rule: after roughly every 2–4 merged PRs, and always before ending a shift that
merged anything. This session merged one (#441) and did not promote.

### 4.4 Ledger item 217 — the drifted copy of a live script
`harness-config/scripts/wake/autonomy-status.sh` is **13080 bytes, md5 `90ec479c44f865ba1b0351de06d7104d`**
(last touched 2026-09-30, commit `ad29fe0f`) while the file that RUNS on the authority is
**17297 bytes, md5 `23e5e7a1407ea5aa74e97e45efa262c0`** and carries patches never committed. **Never
sync the repo copy over the live one** — it will revert live fixes (the same shape as ledger item 163).
The item's DoD: reconcile the two lineages, record which differences are obsolete, and add a check that
compares key md5s and fails loudly. See `harness-config/AGENTS.md` §6.1.

### 4.5 The heartbeat patch is live but unmerged
`harness-config` branch **`fix/heartbeat-is-not-a-death-20261014`** (commit `da5d608d`, pushed to the
`offsite` remote = GitHub) contains `scripts/wake/heartbeat-is-not-a-death.py`, which patches
`autonomy-status.sh` so a spent daily cap is not reported as a dead dispatcher. It has been APPLIED on
the authority (backup at `/home/zabz/bin/autonomy-status.sh.bak-heartbeat-alive-20261014T142657Z`,
`bash -n` clean, live run exit 0 printing `no release : the dispatcher is alive and gated - ...`).
A running copy also exists at `/root/bin/heartbeat-is-not-a-death.py` (**= `/home/zabz/bin/`, they
resolve to the same file**). It is idempotent and refuses rather than half-writing. Merge it, or keep
it in mind that the fix currently lives on one host.

### 4.6 Item 193 — the CI frontend shards (KNOWN, NON-BLOCKING — do not chase unless it blocks)
All four `Test Frontend` shards fail on every branch, including docs-only ones. Measured cause, recorded
as an attempt on ledger item 193: the shards die in vitest's teardown (`Failed to terminate forks worker
for test files …/debug.sanitization.test.ts. Error: [vitest-pool-runner]: Timeout waiting for worker to
respond`, then `Error: write EPIPE` on `child.send`) — **not** on assertions. PR #443
(`b41033475`, "stop killing the shards before they report, and stop calling the kill a success") raised
the inner `timeout --signal=SIGKILL` from 300 s to 540 s and made the kill a warning instead of a fake
success, which is why the required gate (`CI Validation (PR Pre-Check)` / `Merge Queue`) is now green
while the shard jobs stay red. **The lesson from that commit, and the reason not to trust an old
"green": the shards have never reported a real test result in CI.** If you ever make them gating, first
make a shard actually report.

## 5. How to pick this up (exact commands)

```powershell
# 1. the worktree this session used (already installed, already set up)
cd C:\Users\ezabz\code\_lpt-wo-search
git fetch origin ; git status            # branch lpt/counter-all-statuses-20261014, clean
pnpm worktree:setup                      # idempotent; WITHOUT IT every suite that imports
                                         # @phone-and-tech/shared-types fails to resolve (15/15 failures
                                         # in CounterPage.test.tsx is that, not a code fault)
# 2. focused tests (never the whole suite locally - it runs >35 min on this laptop; CI shards it 4 ways)
pnpm test:frontend:one -- frontend/src/features/staff-intake/__tests__/staff-intake-list-queue.test.tsx
pnpm --filter phone-and-tech-frontend lint
pnpm --filter phone-and-tech-frontend typecheck
# 3. the live end-to-end check against TEST (needs the auth state, see §3)
npx playwright test --config=e2e/personas/personas.config.ts --project=persona-auth
node e2e/personas/verify-search-reaches-finished-jobs.mjs     # exit 0 = PASS
# 4. PRs: `gh` is authenticated on ZABZ-YOGA as `lakewoodphone` (repo+workflow scopes).
#    `origin/test` is PROTECTED - PR only; never force-push; never push to main.
gh pr create --repo lakewoodphone/phone-and-tech-full --base test --head <branch>
```

## 6. Traps, state, and things not to touch

- **Machines.** `secratary-cloud` = THE AUTHORITY (sole writer of `/root/authority.db`, the wake loop,
  the ledger, `~/bin/owner-feedback.py`). `secratary` (the office box) = **FROZEN rollback anchor —
  its masked cron is deliberate; never unmask/start/enable anything there.** Read
  `settings/machines/host-posture.tsv` before touching any host's service state.
- **The shared `harness-config` checkout on this laptop** (`C:\Users\ezabz\code\harness-config`) is on
  ANOTHER session's branch (`feat/card-due-watch-20261014`) with unrelated dirty files. Do NOT
  `git add -A` or switch branches there; use `git worktree add` if you need to commit (that is what
  this session did).
- **This session's scratch** (safe to delete, listed so nothing is mistaken for work):
  `C:\Users\ezabz\code\_shard1log.txt`, `_shard1prev.txt`, `_deploy.log`, `_mesh-audit-all-filters.md`.
  `e2e/personas/.auth/*.json` and `e2e/personas/artifacts/` are gitignored output.
- **The `All` chip's own arithmetic** in `StaffOpenListFilters.tsx` is stated as ARITHMETIC from the
  2026-10-08 measurement (8 chips = 564px + ~40px for `All`, against 876px at 1280px), not as a fresh
  measurement. If you re-measure the chip row, correct that comment.
- **The repo's own 500-line ceiling is enforced in CI** (`custom/max-file-lines`). `staff-intake-list-queue.ts`
  is now ~470 counted lines after the split — it has ~30 lines of headroom, and the next thing added
  there should be split instead.

## 7. Records already written (do not duplicate)

- **Ledger (on the authority, `~/bin/work.py`):** item **216** = the owner's report → **done**, with the
  test command and exit code as proof and the merge named as the remainder; item **215** = dropped
  (superseded by 216); item **193** = the CI shard diagnosis, as an attempt; item **217** = the
  `autonomy-status.sh` drift.
- **Journal (`~/code/harness-config/journal/tools/journal.py`):** handoffs **H3771** (the fix) and
  **H3778** (PR 441, the 500-line split, the status-script patch, the CI cause); lesson **L3928**;
  decision **D3209**. `journal.py check` = 0 errors.
- **The website roadmap** (`docs/website/ROADMAP.md`, in `test` now): the new unchecked class row and a
  change-log row with the whole diagnosis. It is IN `test` because the roadmap rode PR #441.
- **The owner's flag for item 216**: filed at priority 3. When the daily release cap resets the flag may
  release a shift whose instruction is "find the class and fix it" — if you have already done §4.1, say
  so there so the shift does not repeat the work.

## 8. What I would do first if I were you

1. Re-read the four LIES in §4.1 and reproduce each one (15 minutes, no fixes).
2. Fix them as ONE coherent change with tests that pin the request and the rows — the same shape as
   `staff-intake-list-queue.test.tsx`'s new `describe('the status scopes')` block.
3. Tick the roadmap class box with the sweep quoted, and have `roadmap-supply` close it.
4. Promote `test` → `main` with the `guardian/promote-test-to-main-*-YYYYMMDD` branch, then verify the
   LIVE production `/health` and the served bundle.
5. Only then look at item 217.

## 9. The audit report (verbatim from the mesh child, unverified by me)

The full report is **beside this file**: `harness-config/docs/handoffs/2026-10-14-all-filters-audit.md`
(17,118 bytes, 223 lines; written on ZABZ-TECH by the mesh child at `C:\Users\ezabz\mesh-audit-all-filters.md`
and pulled back to `C:\Users\ezabz\code\_mesh-audit-all-filters.md` on ZABZ-YOGA). **When you fix the
LIES, move this file into the repo it is about** — `phone-and-tech-full` at
`docs/website/audits/2026-10-14-all-filters-sweep.md` — and cite it from the roadmap's class row, so the
evidence lives with the code rather than in a handoff directory.
Its one-line-per-control summary:

```
 1  QuoteListPage.tsx:871          All (N) tab            → HONEST (count is date-windowed)
 2  QuoteListPage.tsx:874          Pending (N) tab        → LIES (no PENDING in QuoteStatus enum; zod rejects the value)
 3  QuoteListPage.tsx:760          Total Quotes card      → LIES (count is the active-status count)
 4  TransactionHistoryTab.tsx:486  All Statuses           → HONEST
 5  TransactionHistoryTab.tsx:504  All Payment Methods    → HONEST
 6  ReceiptsTab.tsx:422            All Statuses           → UNPROVEN (receipt.list throws; no where exists)
 7  PaymentsDashboard.tsx:268      All Statuses           → HONEST (silent 20-row cap)
 8  PaymentsTransactions.tsx:392   All Methods            → HONEST
 9  RepairIntakeQueueOverviewPanel.tsx:123  All (N) chip  → filter HONEST / count LIES
10  RepairIntakeCaseCreatePanel.tsx:193     All (N) chip  → same defect, never mounted
11  CustomerCommsTimeline.tsx:181   All                    → HONEST
12  CustomersPage.tsx:834           All Status             → HONEST
13  FaqTable.tsx:150                All Categories         → HONEST
14  FaqTable.tsx:175                All Status             → LIES (payload pre-narrowed at FaqManagementPage.tsx:284)
15  StaffIssuesPage.tsx:218         All                    → HONEST
16  CustomerOrderHistory.tsx:247    All Statuses           → HONEST
```

**Treat every line above as a LEAD, not as evidence.** The child that produced it also failed its own
first attempt on this job (a truncated report), and the harness rejected a second child for a hostname
mismatch — so two of the three mesh children on this job were unreliable. Reproduce before you act, and
if you delegate the sweep again, tell the child to (a) print `MESH-HOST: <output of hostname>` first and
(b) write its full report to a FILE and print only the path.

## 10. Also observed, and not resolved

- The deploy workflow (`Deploy environment` on push to `test`) failed at 20:07Z for `7339439a7` with
  `2 assertion(s) FAILED` from `node scripts/verify-deploy.mjs --check-env --check-api --check-stripe test`,
  one of them `FAIL Stripe: test carries a real pk_test_... publishable key: NO pk_test_... key in 3
  scanned file(s)` — **while the frontend DID deploy** (the log shows the Cloudflare Pages upload and
  then `PASS the host serves the build's entry asset index-WlMTJVyV.js`). The very next deploy, for this
  session's merge (`af0c5c416`, run `38648886231`), **succeeded**. So that redness was not reproducible
  in the next run and is recorded here only so it is recognised if it returns: the Stripe TEST
  publishable key appears to be missing from the test deploy environment.
- A curiosity worth knowing, not a task: `frontend/package.json`'s test script sets
  `NODE_OPTIONS=--max-old-space-size=8192` while the CI job sets 4096; #443's author measured that these
  are heap CAPS, not drawn amounts, and no shard log contains a JS heap error.
