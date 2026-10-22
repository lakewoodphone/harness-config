# Read-only audit: filter labels that promise more than they deliver

**Commit** `af0c5c416` (`test` head, merge of PR #441) � **Repo** github.com/lakewoodphone/phone-and-tech-full
**Checkout** `C:\Users\ezabz\Code\phone-and-tech-full` (origin matches; `git fetch origin` run; every file read via `git show af0c5c416:<path>`) � **Host** `zabz-tech`
Every quotation is a real line from that commit, never paraphrased. Read-only: no file in any repo was modified.

## Verdict table

| # | Control | Label | Verdict |
|---|---|---|---|
| 1 | `QuoteListPage.tsx:871` | `All (N)` tab | HONEST (count is date-windowed) |
| 2 | `QuoteListPage.tsx:874` | `Pending (N)` tab | **LIES** |
| 3 | `QuoteListPage.tsx:760` | `Total Quotes` card | **LIES** (count only) |
| 4 | `TransactionHistoryTab.tsx:486` | `All Statuses` | HONEST |
| 5 | `TransactionHistoryTab.tsx:504` | `All Payment Methods` | HONEST |
| 6 | `ReceiptsTab.tsx:422` | `All Statuses` | UNPROVEN |
| 7 | `PaymentsDashboard.tsx:268` | `All Statuses` | HONEST |
| 8 | `PaymentsTransactions.tsx:392` | `All Methods` | HONEST |
| 9 | `RepairIntakeQueueOverviewPanel.tsx:123` | `All (N)` chip | filter HONEST / count **LIES** |
| 10 | `RepairIntakeCaseCreatePanel.tsx:193` | `All (N)` chip | same defect, never mounted |
| 11 | `CustomerCommsTimeline.tsx:181` | `All` | HONEST |
| 12 | `CustomersPage.tsx:834` | `All Status` | HONEST |
| 13 | `FaqTable.tsx:150` | `All Categories` | HONEST |
| 14 | `FaqTable.tsx:175` | `All Status` | **LIES** |
| 15 | `StaffIssuesPage.tsx:218` | `All` | HONEST |
| 16 | `CustomerOrderHistory.tsx:247` | `All Statuses` | HONEST |

## 1-3. QuoteListPage.tsx  repairQuote.list  repairQuoteService.list

Control 1, `QuoteListPage.tsx:871-872`: `871: <TabsTrigger value="ALL">` / `872: All ({stats?.total || 0})`
Request input, `QuoteListPage.tsx:263`: `263:    status: activeTab === 'ALL' ? undefined : activeTab,`
Where the result is decided - the server default is "no status constraint":
```
backend/src/trpc/routers/repairQuote.ts:151:  status: z.nativeEnum(QuoteStatus).optional(),
backend/src/services/repairQuote.service.ts
774:      if (filters?.status) {
775:        where.status = filters.status
776:      }
810:      const quotes = await prisma.repairQuote.findMany({
811:        where,
```
No `take`. `QuoteStatus` = `DRAFT, SENT, ACCEPTED, REJECTED, EXPIRED, CONVERTED` (`backend/prisma/schema.prisma:5429`) - `undefined` reaches all six.
**VERDICT: HONEST** (proven by 263 / 151 / 774-776 / 810-811). Two caveats, both about the *number*, not the status reach:
- The same call always carries a date window (265-266 `startDate:` / `endDate:` from `dateRange`), defaulting to today:
```
186:      return {
187:        from: startOfDay(new Date()),
188:        to: endOfDay(new Date()),
189:      }
```
Presets are `today | yesterday | thisWeek | thisMonth | custom` (line 42) - no "all time". `All (N)` is "all six statuses **created today**".
- `stats` is derived from the already status-filtered rows (552-556), so each tab prints the active tab's count; on the only reachable tab those happen to be right.

Control 2, `QuoteListPage.tsx:874-875`: `874: <TabsTrigger value="PENDING">` / `875: Pending ({stats?.pending || 0})`
`553:      pending: allQuotes.filter((q: RepairQuote) => q.status === 'PENDING').length,`
Request input: line 263 with `activeTab = 'PENDING'`. Result decided: nowhere - rejected before the `where`. `QuoteStatus` (schema.prisma:5429) has no `PENDING` member, so `z.nativeEnum(QuoteStatus)` (`repairQuote.ts:151`) cannot accept it.
**VERDICT: LIES.** Unreachable: **every quote**. The tab's count is a hard 0 forever. Same defect on the stat card `QuoteListPage.tsx:763-773` (`765: onClick={() => handleTabChange('PENDING')}`).
**Smallest honest change:** the frontend enum is fiction. `QuoteListPage.tsx:40 type QuoteStatus = 'ALL' | 'PENDING' | 'ACCEPTED' | 'REJECTED' | 'EXPIRED'`  `'ALL' | 'DRAFT' | 'SENT' | ...`, tab 874-875  `value="DRAFT"`, add a `SENT` tab, 553  `q.status === 'DRAFT'`. A two-value "Pending" would instead need `z.union([z.nativeEnum(QuoteStatus), z.literal('PENDING')])` plus a `where.status = { in: ['DRAFT','SENT'] }` branch.

Control 3, `QuoteListPage.tsx:755-761`: `755: onClick={() => handleTabChange('ALL')}` / `757: aria-label="Filter by all quotes"` / `760: <div ...>{stats.total}</div>` / `761: <div ...>Total Quotes</div>`, with `552:      total: allQuotes.length,`
**VERDICT: LIES (count).** `stats.total` is the length of the status-filtered response, so on any status tab the card labelled *Total Quotes* prints that status's count.
**Smallest change:** at 761 say what it measures (`Quotes in view`), or read the number from a second `useQuery` issued with `status: undefined`.

## 4-5. TransactionHistoryTab.tsx  payments.getTransactionHistory

Control 4, `TransactionHistoryTab.tsx:486`: `486:              <option value="ALL">All Statuses</option>`
Request input: `263:    if (statusFilter !== 'ALL') { 264: input.status = statusFilter 265: }`
Result decided, `backend/src/trpc/routers/payments.ts`: `2835:        if (input.status) { 2836: where.status = input.status 2837: }`
`PaymentTransactionStatus` (`schema.prisma:3915`) is exactly the seven values the client types (`TransactionHistoryTab.tsx:53-60`) and all seven are options (487-492). **HONEST.**

Control 5, `TransactionHistoryTab.tsx:504`: `504:              <option value="ALL">All Payment Methods</option>`
Request input: 267-269 (`input.paymentMethodType = paymentMethodFilter`). Result decided:
```
2847:        if (input.paymentMethodType) {
2848:          where.paymentMethod = {
2849:            type: input.paymentMethodType,
2850:          }
2851:        }
```
**HONEST.** Omitted  no relation constraint  all rows, including rows with no `paymentMethod` at all. Adjacent, *different* defect: `PaymentMethodType` (`schema.prisma:3879`) has eight values while the dropdown offers six (505-510) - `ZELLE` and `BANK_TRANSFER` have no option of their own, but **All** still reaches them.
**Truncation note:** `limit: 100` (259), `offset: 0` (260), no pager - a search cannot reach past the first 100 matches, but this is *disclosed*: `1209: Showing {transactions.length} of {transactionsQuery.data.pagination.total} transactions`.

## 6. ReceiptsTab.tsx  receipt.list

Control: `422:              <option value="all">All Statuses</option>` � Request input (the value is always sent, never omitted): `117:      status: statusFilter,`
Result decided: **not found**, because the handler throws before building any query:
```
backend/src/trpc/routers/receipt.router.ts
27:        status: z.enum(['paid', 'refunded', 'voided', 'all']).optional().default('all'),
41:      throw new TRPCError({
42:        code: 'BAD_REQUEST',
43:        message: MVP_RECEIPT_ERROR,
44:      })
```
No `prisma.receipt.*` call and no `where` for `receipt.list` exists here; `backend/src/services/receipt.service.ts` holds only per-order rendering (`where: { id: orderId }` at 46 and 182) - no list method.
**VERDICT: UNPROVEN.** What I could not find: any Prisma `where`, service method or default that decides what `status: 'all'` returns. The zod signature is honest (`'all'` accepted *and* the default), so the label is neither provably true nor provably false at this commit.

## 7. PaymentsDashboard.tsx  payments.listInvoices

Control: `268:            <option value="">All Statuses</option>` � Request input: `262:                status: (e.target.value as InvoiceStatus) || undefined,`
Result decided, `backend/src/trpc/routers/payments.ts`: `2403:        if (input.status) { 2404: whereClause.status = input.status 2405: }`
Server enum = eight statuses (2354-2363), matching `InvoiceStatus` (`features/payments/types/domain.ts:33-41`); the dropdown offers four; omitted  no constraint  all eight reachable. **HONEST.**
**Truncation note:** `limit: 20` (line 29), `offset` pinned at 0 (30, reset at 263), no pager - newest 20 invoices only, **silently** (no "showing X of Y" anywhere in the file).

## 8. PaymentsTransactions.tsx  paymentRouter.list  paymentService.list

Control: `392:              <option value="ALL">All Methods</option>`
Request input: `214:    if (methodFilter !== 'ALL') { 215: input.method = methodFilter 216: }`
Result decided:
```
backend/src/services/paymentService.ts
306:      if (filters.method) {
307:        // Filter by metadata.paymentMethod
308:        where.metadata = {
309:          path: ['paymentMethod'],
310:          equals: filters.method,
311:        }
312:      }
```
**HONEST.** Omitted  no `metadata` constraint  every payment, including legacy rows with no stored method; real methods with no option (`PAYPAL`, `APPLE_PAY`, `AFFIRM` - `paymentRouter.ts:23-31`) are still reachable through All. Adjacent, *different* defect: options 397-398 (`STORE_CREDIT`, `OTHER`) are not in `paymentMethodSchema` (`paymentRouter.ts:23-31`). Paging is complete (633-635).

## 9-10. Repair intake "All" chip  repairIntakeCases.list

Mounted control, `RepairIntakeQueueOverviewPanel.tsx`: `109: const count = statusOption === 'ALL' ? total : counts[statusOption]` and `123: {statusOption === 'ALL' ? 'All' : STATUS_LABELS[statusOption]} ({count})`
Request input, `RepairIntakeCasesPage.tsx`: `19: useState<RepairIntakeCaseStatus>('ALL')` / `26:      status: statusFilter,` / `27:      syncStatus: 'ALL',`
Result decided, `backend/src/services/repair-intake-cases/repair-intake-case.service.ts`: `2083:      status: input.status && input.status !== 'ALL' ? input.status : undefined,`
with the router accepting `'ALL'` (`repairIntakeCases.ts:155`). **FILTER VERDICT: HONEST** - `'ALL'`  `undefined`; `take` is only `input.limit` (675), no status excluded.

**The number in the label is not the all-count.** `total` is counted *under the active status filter*:
```
666:      const where = this.buildWhere(input)
677:        prisma.repairIntakeCase.count({ where }),
```
That value is handed to the panel as `total={repairIntakeData.total}` (`RepairIntakeCasesPage.tsx:86`) and printed as `All ({count})`.
**COUNT VERDICT: LIES.** Unreachable value: the true all-status total whenever a status chip is active - "All (12)" is the selected status's count. No all-total is exposed (`RepairIntakeCaseListResult`, service 395-399, is `total, counts, syncCounts, items`).
**Smallest change - one line,** `RepairIntakeQueueOverviewPanel.tsx:109`  `const count = statusOption === 'ALL' ? Object.values(counts).reduce((a, b) => a + b, 0) : counts[statusOption]`. The per-status counts are already computed with `status: 'ALL'` (667), so their sum is exactly the set the chip promises.

Control 10, `RepairIntakeCaseCreatePanel.tsx:179/193` carries the identical chip and count defect, but the component is **never mounted**: `git grep RepairIntakeCaseCreatePanel af0c5c416 -- frontend/src` returns only its own definition (14, 27, 38) - no page or test imports it. Real in the file, unreachable in the app.
**Truncation note:** `limit: 50` (`RepairIntakeCasesPage.tsx:25`) with no offset/pager and server `take: input.limit` (675) - 50 rows maximum, silently; older cases are unreachable by any filter or search.

## 11. CustomerCommsTimeline.tsx "All"  communications.getCustomerTimeline

Control: `180: const KIND_FILTERS: Array<{ value: 'ALL' | TimelineKind; label: string }> = [` / `181:   { value: 'ALL', label: 'All' },`
Request input: `279:      kinds: kind === 'ALL' ? undefined : [kind],`
Result decided:
```
backend/src/services/communications/customer-timeline.service.ts
236:    const kinds = input.kinds?.length ? input.kinds : null
239:    const includeNotes = !kinds || kinds.includes('NOTE')
250:                ...(wantedCommTypes ? { type: { in: wantedCommTypes } } : {})
337:    if (!kinds) return null
```
`null` kinds  no `type` clause, notes included. **HONEST** - all seven `TimelineKind` values, including `CHAT`, `VIDEO_CALL` and `NOTIFICATION` (which have no chip of their own), are reachable.

## 12. CustomersPage.tsx "All Status" (customers/** filter, surface 4)

`834:          <option value="">All Status</option>` with options 835-838 `ACTIVE`, `INACTIVE`, `SUSPENDED`, `PENDING`.
Request input: `312:    status: statusFilter || undefined,` � Result decided, `backend/src/services/customers/query.service.ts`:
```
216:    if (filters.status) {
217:      where.status = Array.isArray(filters.status)
218:        ? { in: filters.status }
219:        : filters.status
```
**HONEST** - `''`  `undefined`  no constraint, and all four `CustomerStatus` values are individually offered too.

## 13-14. FaqTable.tsx "All Categories" / "All Status"

Control 13: `150:            <option value="ALL">All Categories</option>` with `52:    if (filters.category && filters.category !== 'ALL') { 53: result = result.filter(...) }`
**HONEST** - the payload is not category-narrowed anywhere, and options 151-160 cover the enum.

Control 14: `175:            <option value="ALL">All Status</option>` with `57:    if (typeof filters.published === 'boolean') { 58: result = result.filter((faq) => faq.isPublished === filters.published) }`
`'ALL'` is a string, so line 57 is false and no status filter runs - the control asks for everything. It cannot get it, because the rows were already narrowed upstream:
```
frontend/src/features/admin/faq/pages/FaqManagementPage.tsx
61:  const filteredFaqs =
62:    selectedTab === 'published'
63:      ? allFaqs.filter((faq: Faq) => faq.isPublished)
64:      : selectedTab === 'drafts'
65:      ? allFaqs.filter((faq: Faq) => !faq.isPublished)
66:      : allFaqs
271:        ) : selectedTab === 'all' ? (
282:        ) : (
283:          <FaqTable
284:            faqs={filteredFaqs}
```
`FaqTable` is only mounted from the two narrowed branches (the `'all'` tab renders `FaqReorderList`, 273), so it is never handed `allFaqs`.
**VERDICT: LIES.** Unreachable values: the whole `isPublished: false` set while the Published tab (`:242`) is selected, and the whole `isPublished: true` set while Drafts (`:252`) is selected - in each case `All Status` and the opposite option come back empty, because the payload was narrowed by the request that fed the control.
**Smallest change:** `FaqManagementPage.tsx:284` - `faqs={filteredFaqs}`  `faqs={allFaqs}`, which makes `All Status` genuinely all statuses (the page tab must then drive the table's own select rather than the prop). Relabelling or dropping `All Status` while a narrowed tab is selected restores only the label's honesty, not its reach.

## 15. StaffIssuesPage.tsx "All"

Control: `218:            {s === 'all' ? 'All' : STATUS_LABELS[s]}` (options from line 208, the full `StatusFilter` union)
Request input: `132:    { status: statusFilter, limit: 100, offset: 0 },`
Result decided, `backend/src/trpc/routers/staff-issues.router.ts`: `166:        const where = 167: statusFilter && statusFilter !== 'all' 168: ? { status: ... } 169: : {}`
**HONEST** - `'all'` yields `{}`, no constraint.
**Truncation note:** `limit: 100, offset: 0`, no pager - at most 100 issues, **partially disclosed**: `{total} total` is rendered at line 221, so the true count is visible though the extra rows are not reachable.

## 16. CustomerOrderHistory.tsx "All Statuses"

Control: `247:            <SelectItem value="all">All Statuses</SelectItem>`
Request input - the request carries no status at all: `96:        const result = await vanillaTrpcClient.order.getCustomerOrders.query({ customerId })`
Result decided - client filter over an unfiltered server read:
```
160:    if (statusFilter !== 'all') {
161:      filtered = orders.filter((order: Order) => order.status === statusFilter)
backend/src/services/order.service.ts
99:      const orders = await prisma.order.findMany({
100:        where: { customerId },
```
**HONEST.** No `status`, no `take`; `'all'` applies no client filter, and the individual options are derived from the loaded rows themselves (`availableStatuses`, 181-185), so they cannot miss a value.

## Controls whose "All" also silently truncates (different defect)

- `TransactionHistoryTab.tsx:259` - `limit: 100`, offset 0  **disclosed** at 1209; a filter cannot reach past the first 100.
- `PaymentsDashboard.tsx:29` - `limit: 20`, offset pinned 0  **silent**; no "showing X of Y" in the file.
- `RepairIntakeCasesPage.tsx:25` - `limit: 50`, no pager  **silent**; cases older than the newest 50 by `updatedAt` unreachable.
- `StaffIssuesPage.tsx:132` - `limit: 100`, offset 0  **partially disclosed** (`{total} total`, line 221).

## Not proven / not found

- **`receipt.list`** - no `where`, no service list method, no deciding default; the handler throws (`receipt.router.ts:41-44`) before any query. Recorded UNPROVEN rather than guessed.
- **`RepairIntakeCaseCreatePanel.tsx`** - same chip, same count defect, but no import site exists at `af0c5c416`; whether it was ever live is outside this commit.
