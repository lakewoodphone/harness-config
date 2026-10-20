# Journal rename map - 73 ids that named two different documents

Written 2026-10-20 (ledger item 643). `harness-config`'s mirror lineage and its primary had allocated the same
journal entry ids to different entries: 73 ids, each naming two different documents depending on which lineage
you read. Merging the mirror resolved them by keeping the PRIMARY's entry under the existing id and reissuing
the mirror's entry under a new id above the union maximum, so nothing was deleted and no id now means two
things. The new ids are reserved in `journal/alloc/bands.tsv` for host ZABZ-TECH.

| old id | new id | kind | the reissued entry |
|---|---|---|---|
| D3034 | D3154 | decisions | **D3154 · 2026-10-08 · Weitman 2026-10-08: keyboard-only SD copy route; no fault assigned; no invented status; |
| D3035 | D3155 | decisions | **D3155 · 2026-10-08 · -NoVideo exists as an opt-in profile (86ec4ad0); on 616468703 the owner kept the galler |
| D3036 | D3156 | decisions | **D3156 · 2026-10-08 · The shop counter devices' password AutoFill was disabled by their own MDM profile; both |
| D3037 | D3157 | decisions | **D3157 · 2026-10-08 · Production session lifetimes: access token 7d -> 30d, refresh 7d -> 90d, secret untouch |
| D3038 | D3158 | decisions | **D3158 · 2026-10-09 · Shabbos power-down moves to 5 hours before sunset + ceiling light held ON.** |
| H3443 | H3618 | handoff |  |
| H3444 | H3619 | handoff |  |
| H3445 | H3620 | handoff |  |
| H3446 | H3621 | handoff |  |
| H3447 | H3622 | handoff |  |
| H3448 | H3623 | handoff |  |
| H3449 | H3624 | handoff | **CORRECTION — the gate was the wrong number.** The agent told the owner to register |
| H3450 | H3625 | handoff |  |
| L3504 | L3816 | lessons | **L3816 · CORRECTION to H3495: the live website reads operational, not app - and a stale label in lpt doctor i |
| L3505 | L3817 | lessons | **L3817 · A hardcoded reason string is a constant, not a fact - and a cron job cannot act while cron is dead** |
| L3506 | L3818 | lessons | **L3818 · Push from a worktree, not from the shared clone - cherry-picking onto a moved origin leaves the clon |
| L3668 | L3819 | lessons | **L3819 · L3511 WAS WRONG: the web profile still holds the office row, so re-applying it re-introduces the fro |
| L3669 | L3820 | lessons | **L3820 · L3668 was WRONG too - a line number in someone else's report is not a measurement. The real defect w |
| L3670 | L3821 | lessons | **L3821 · A scheduled task needing elevation fails QUIETLY: it 'restored' a Defender exclusion that was still  |
| L3671 | L3822 | lessons | **L3822 · FAT32: a valid 8.3 filename collides with another file's generated short name - one directory entry, |
| L3672 | L3823 | lessons | **L3823 · Counter checkout adds NJ tax to whatever you enter, so enter PRE-tax - quoting the customer a tax-in |
| L3673 | L3824 | lessons | **L3824 · A PAID item goes to the shop's 24/6 outside dropoff/pickup and can be collected any hour - do NOT wr |
| L3674 | L3825 | lessons | **L3825 · A simple customer notice is ONE sentence - four corrections in one message exchange, against a rule  |
| L3675 | L3826 | lessons | **L3826 · 'Pull up X' means SHOW X - not my summary of X. And a one-word 'which customer is this?' means the r |
| L3676 | L3827 | lessons | **L3827 · A label's reader is the SECRETARY - it must let her find the job, know who and what, and know what t |
| L3677 | L3828 | lessons | **L3828 · Be the someone: never write an obligation onto another person - 'only the website can create one' me |
| L3678 | L3829 | lessons | **L3829 · The customer-case sync SCHEMA is not a gate (306 of 413 records fail it) - the push tool's dry-run i |
| L3679 | L3830 | lessons | **L3830 · Two 'empty result' readings that both meant 'wrong query': gmail_search without an explicit account  |
| L3680 | L3831 | lessons | **L3831 · git add and git commit must be ONE shell call - explicit paths do not protect staged work on a share |
| L3681 | L3832 | lessons | **L3832 · Owner corrections 2026-10-12: foreground delegation, over-asking, and the SMS gate** |
| L3682 | L3833 | lessons | **L3833 · A lab ticket is not the case: a vendor-mailbox sweep cannot answer a customer-state question** |
| L3683 | L3834 | lessons | **L3834 · A vendor ticket is not the whole case - a state line about a CUSTOMER must be read out of the custom |
| L3684 | L3835 | lessons | **L3835 · Print labels from ZABZ-TECH with the repo build: the printer is on this LAN, and the copy on the sho |
| L3685 | L3836 | lessons | **L3836 · Owner corrections 2026-10-12 (2nd pass): how to draft a customer text he will actually let go out** |
| L3686 | L3837 | lessons | **L3837 · Two work orders for one job: the order that owns the intake case is canonical, and repointing a sync |
| L3687 | L3838 | lessons | **L3838 · A customer's newest inbound can exist in the LIVE store only. Read both stores before writing that n |
| L3688 | L3839 | lessons | **L3839 · Pricing a job where the customer supplies the part: our fitted quote minus the part's street value,  |
| P2996 | P3167 | pain | **What hurts.** Closed jobs and open jobs are indistinguishable in the operational store. |
| P2997 | P3168 | pain | **Measured 2026-10-08** from `~/code/lpt-hub`, `python tools/case-index/lptcase.py check`: |
| P2998 | P3169 | pain | **Evidence, 2026-10-08, work order `WO2608060003` (Kogel, 300DDR ticket 73459).** The order sat at status `AWA |
| P2999 | P3170 | pain | **Measured 2026-10-08**, `~/code/lpt-hub`: |
| P3000 | P3171 | pain | **Why this is worse than it looks:** the receipt's failure text says 26 named packages "failed to disable", |
| P3001 | P3172 | pain |  |
| P3002 | P3173 | pain | **Found** 2026-10-09 while verifying a fix to a neighbouring defect. Reproduced by me, not taken on |
| P3006 | P3174 | pain | **Addendum to P3005, measured 2026-10-09 (round 12).** Frequency and duration, |
| P3007 | P3175 | pain |  |
| P3008 | P3176 | pain |  |
| P3009 | P3177 | pain |  |
| P3010 | P3178 | pain | **What hurts.** Something on the authority, running as `zabz` with sudo around 04:03Z on 2026-10-11, |
| P3011 | P3179 | pain |  |
| P3012 | P3180 | pain |  |
| P3013 | P3181 | pain |  |
| P3014 | P3182 | pain |  |
| P3015 | P3183 | pain | **What hurts.** The 2026-10-11 authority cutover was executed without a journal entry, without its own |
| P3016 | P3184 | pain | **What hurts.** The shop's contact record is written to TWO stores that disagree about WHEN, and the disagreem |
| P3019 | P3185 | pain |  |
| P3020 | P3186 | pain | **MY CHILD REFUSED TO OVERWRITE, AND THAT WAS RIGHT.** It says so plainly - *"I will not overwrite either |
| P3021 | P3187 | pain | **Why it matters.** The case-sync contract instructs every session, as step 1 of finishing a case, to |
| P3022 | P3188 | pain | **What was measured.** At ~22:35Z a session read it and got *"Updated: 2026-10-11 20:30Z (ZABZ-TECH, |
| P3130 | P3189 | pain | **P — the graceful HA stop was dead code, so every Shabbat power-down hard-cut |
| P3131 | P3190 | pain | **P — the daily reprogram was failing silently on transient plug timeouts, and |
| P3132 | P3191 | pain | **P — the company API wedges: it accepts TCP and never answers, and the watchdog |
| P3133 | P3192 | pain | **The cost, named.** On 2026-09-30 five 300DDR messages had sat unread for five days. On 2026-10-02 four more  |
| P3134 | P3193 | pain |  |
| P3135 | P3194 | pain |  |
| P3136 | P3195 | pain | **inert**: his reply would be filed and never released, and the case would be scrapped on a timer |
| W2735 | W2809 | wins | **W2809 · 2026-10-09 · Shabbat automation reconciled: deployed tree matches the commits, 5h offset at every la |
| W2736 | W2810 | wins | **W2810 · 2026-10-11 · A parts_inventory table that held 0 rows now holds 12, traceable to the photo that prod |
| W2737 | W2811 | wins | **W2811 · 2026-10-11 · Hostile-fixture test suite for the card copier: 51/51, and it caught 4 real defects inc |
| W2738 | W2812 | wins | **W2812 · 2026-10-11 · The shadow-database read was found and killed by three independent surfaces, and proved |
| W2739 | W2813 | wins | **W2813 · 2026-10-11 · cron-wrap.sh error-tail fixed and PROVEN through the real scheduler - and the same fix  |
| W2740 | W2814 | wins | **W2814 · 2026-10-11 · Office box DEMOTED TO INERT and the guard now reaches ALL FOUR machines - one cloudflar |
| W2803 | W2815 | wins | **W2815 · 2026-10-08 · The iOS-backup injection technique is verified working on iOS 27.0: same manifest forma |

## How to read this

A citation of the OLD id refers to the primary's entry, which still carries it. A citation of the NEW id refers
to the mirror's entry, which was written on a machine that had not seen the primary's allocation. If you were
looking for the entry behind a new id, its heading line was preserved verbatim apart from the id itself.
