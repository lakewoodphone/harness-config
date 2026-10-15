# 50 - journal hygiene, round 6 (R6-JOURNAL)

**Measured 2026-10-15 14:10-14:25 UTC by mesh child R6-JOURNAL on ZABZ-TECH.**

> ## HEADLINE: THE JOURNAL HAS FORKED INTO FIVE TREES. NO WRITES WERE MADE.
> 
> Step 1 of the brief says: *"If more than one tree holds journal entries that the other does not,
> DO NOT WRITE - produce the resolution list instead and say so."* That condition is met, and met
> far worse than "staleness": **363 entry ids carry two or three different bodies depending on which
> tree you read.** A `journal.py resolve` in any tree is a write into a tree that will be overwritten,
> and can silently attach a status to a *different* entry than the author meant. **No `resolve` call
> was run. `50-resolutions.sh` is therefore a reproduce-and-plan script, not a log of executed calls.**

---

## 1. Which tree is authoritative - the comparison

All five trees carry a `journal/entries/` directory and a `journal.py`. None is a superset of another.

| tree | branch | HEAD | entries | OPEN PAIN | owner Qs (mirror) | `journal.py check` | legacy drift |
|---|---|---|---:|---:|---:|---|---|
| **yoga (manager)** | `incident/deepseek-spof-20261015` | `dbb2c1c1` | 4204 | **453** | 127 | 0 error(s) | 0 |
| **secratary-cloud (authority)** | `hk/182-wake-family-key` | `96f26c1b` | 4121 | **475** | 127 | 0 error(s) | 0 |
| **ZABZ-TECH (this node)** | `mesh/broker-host-cloud-default-20261013` | `2d01206f` | 3960 | **411** | 143 | 0 error(s) | 0 |
| **zabz-tech-linux** | `main` | `985f9378` | 3440 | **344** | 143 | 0 error(s) | 0 |
| **LakewooechsMini** | `master` | `45676b7f` | 1646 | **162** | 143 | 0 error(s) | 2 (wins) |

Read commands (all read-only):

```
# this node (ZABZ-TECH, Windows)
cd C:\Users\ezabz\code\harness-config; python journal/tools/journal.py status
# authority
ssh secratary-cloud 'cd /root/code/harness-config && python3 journal/tools/journal.py status'
# linux-pc / mac-mini / yoga - same command in each checkout
```

**The brief's numbers come from ZABZ-YOGA, the manager's own tree** - it is the only tree whose
`OPEN PAIN` is exactly **453** and whose mirror is exactly **127**. Every other tree disagrees:
the authority says 475, this node 411, linux-pc 344, mac-mini 162.

### 1.1 Pairwise divergence

`onlyA` / `onlyB` = ids present in one tree and absent from the other. `DIFFER` = ids present in
both whose **content hash differs**. Command: `python C:\Users\ezabz\_r6\analyze2.py` (source at
`C:\Users\ezabz\_r6\analyze2.py`, reproduces the whole section from the five manifests).

| A | B | onlyA | onlyB | shared-identical | **shared-DIFFERENT** |
|---|---|---:|---:|---:|---:|
| yoga (manager) | secratary-cloud (authority) | 145 | 62 | 3960 | **99** |
| yoga (manager) | ZABZ-TECH (this node) | 488 | 244 | 3462 | **254** |
| yoga (manager) | zabz-tech-linux | 764 | 0 | 3436 | **4** |
| yoga (manager) | LakewooechsMini | 2561 | 3 | 1611 | **32** |
| secratary-cloud (authority) | ZABZ-TECH (this node) | 423 | 262 | 3462 | **236** |
| secratary-cloud (authority) | zabz-tech-linux | 681 | 0 | 3436 | **4** |
| secratary-cloud (authority) | LakewooechsMini | 2478 | 3 | 1611 | **32** |
| ZABZ-TECH (this node) | zabz-tech-linux | 520 | 0 | 3440 | **0** |
| ZABZ-TECH (this node) | LakewooechsMini | 2317 | 3 | 1611 | **32** |
| zabz-tech-linux | LakewooechsMini | 1797 | 3 | 1611 | **32** |

### 1.2 The union

```
union of all five trees        : 4513 ids
present in all five            : 1643 ids
confined to exactly one tree   : 436 ids
ids with a CONTENT COLLISION   : 363
  (2 distinct bodies: 341, 3 distinct bodies: 22)
ids confined to each tree      : yoga (manager) 127, secratary-cloud (authority) 62, ZABZ-TECH (this node) 244, zabz-tech-linux 0, LakewooechsMini 3
```

**`zabz-tech-linux` is a strict id-subset of everything else** (`onlyB = 0` against yoga, the
authority, this node and mac-mini). It holds **0** ids that no other tree has. It is stale, not
divergent, and needs no merge - only a pull.

### 1.3 Why this is a collision, not staleness - worked examples

The same id names a different entry in different trees. This is the part that makes a blind merge
destructive, and it is why the brief's "divergence is worse than staleness" is the right rule:

| id | yoga + authority | ZABZ-TECH |
|---|---|---|
| `D3034` | *"Decisions while making the shop's money & customer tracking survive long-term"*, 2026-10-09 | *"Weitman 2026-10-08: keyboard-only SD copy route..."* |
| `D3124` | *"Wake fleet ceiling set to 5 USD/day (not 25)"*, ZABZ-YOGA | *"Exalt mic replacement is 110 with a 50 non-refundable deposit"*, ZABZ-TECH |
| `H3393` | *"The shop's money & customer tracking is now a system..."*, secratary, 2026-10-09 00:52Z | *"New always-on box provisioned..."*, ZABZ-YOGA, 2026-10-09 19:00Z |

Reproduce any row with:

```
python journal/tools/journal.py show D3034          # on ZABZ-TECH
ssh secratary-cloud 'cd /root/code/harness-config && python3 journal/tools/journal.py show D3034'
```

A `resolve D3034 --status done` on the authority would mark *the shop's money system* resolved using
evidence gathered about *Weitman's SD card*. That is the failure this STOP condition prevents.

---

## 2. The resolution list (what must happen before anyone writes)

This is the deliverable the brief asks for in place of the writes. It is ordered; each step is
decidable without a judgement call beyond the ones named.

**R1 - Freeze writes in every tree.** Until R4 completes, no `journal.py resolve` and no
`journal.py append` in *any* of the five trees. Otherwise the three sets below move while they are
being reconciled.

**R2 - Adopt one tree as the merge base.** The authority (`secratary-cloud:/root/code/harness-config`,
`%s`) is the only defensible choice: `owner_decision_queue` - which the status page already declares
"authoritative: owner_decision_queue on the authority" - lives on that box, and `AGENTS.md` §5 makes it
the sole writable host. **Recommendation, not a fact I can verify from here:** the manager should
confirm that `/root/code/harness-config` is the tree the authority's own sessions were writing to.

**R3 - Reconcile the three sets, in this order.**

  1. **%d colliding ids** (`%d` with 2 bodies, `%d` with 3) - every one needs a human/manager decision:
     keep one body, copy the other to a fresh id from the allocator, then write an alias row.
     **Do not union blindly.** `journal.py check` cannot see this - it validates ids *within* a tree.
     Machine-readable list: `C:\Users\ezabz\_r6\collisions.json`.
  2. **%d ids confined to one tree** - pure additions, safe to copy. %s
  3. **%d ids present in two or more trees with identical content** - nothing to do; already converged.

**R4 - Then, and only then, resume the pain work.** Only after R3 can a `resolve` be trusted to
attach to the entry its author meant.

### 2.1 The collision set, in full (363 ids)

```
D200 D3034 D3035 D3036 D3037 D3038 D3124 D3125 D3126 D3127 D3128 D3129 D3130 D3131 D3132 D3133
D3134 D3135 D3136 D3137 D3147 D3148 D3149 D3150 D3151 D3152 D3154 D3402 H2171 H2340 H2403 H2596
H2727 H2728 H2729 H3061 H3095 H3096 H3146 H3178 H3179 H3180 H3181 H3182 H3183 H3393 H3394 H3401
H3402 H3403 H3404 H3405 H3443 H3444 H3445 H3446 H3447 H3448 H3449 H3450 H3565 H3566 H3567 H3568
H3569 H3570 H3571 H3572 H3573 H3574 H3575 H3576 H3577 H3578 H3579 H3580 H3581 H3582 H3583 H3584
H3585 H3586 H3587 H3588 H3589 H3590 H3591 H3592 H3593 H3594 H3595 H3596 H3597 H3598 H3599 H3600
H3601 H3602 H3603 H3604 H3605 H3606 H3607 H3610 H3611 H3612 H3613 H3614 H3615 H3616 H3617 H3618
H3619 H3620 H3621 H3622 H3623 H3624 H3625 H3626 H3627 H3628 H3629 H3630 H3631 H3632 H3633 H3634
H3635 H3636 H3637 H3638 H3639 H3640 H3641 H3671 H3672 H3673 H3674 H3675 H3676 H3779 H4168 H4169
H4296 H4424 H444 H4552 H558 H604 H610 L1684 L1776 L221 L2524 L2784b L3504 L3505 L3506 L3668
L3669 L3670 L3671 L3672 L3673 L3674 L3675 L3676 L3677 L3678 L3679 L3680 L3681 L3682 L3683 L3684
L3685 L3686 L3687 L3688 L3692 L3730 L3731 L3732 L3733 L3734 L3735 L3736 L3737 L3738 L3739 L3740
L3741 L3742 L3743 L3744 L3745 L3746 L3747 L3748 L3749 L3750 L3751 L3752 L3753 L3754 L3755 L3756
L3757 L3758 L3759 L3760 L3761 L3762 L3763 L3764 L3765 L3766 L3767 L3768 L3769 L3770 L3771 L3772
L3773 L3774 L3775 L3776 L3777 L3778 L3779 L3780 L3781 L3782 L3783 L3784 L3785 L3786 L3787 L3788
L3789 L3790 L3791 L3792 L3793 L3794 L3795 L3796 L3797 L3798 L3799 L3800 L3802 L3803 L3804 L3805
L3806 L3807 L3808 L3809 L3810 L3811 L3812 L3813 L3814 L3815 L3818 L3819 L3820 L3821 L3822 L3936
L3937 L3938 L3939 L3940 L3941 L4512 P2477 P2561b P2996 P2997 P2998 P2999 P3000 P3001 P3002 P3006
P3007 P3008 P3009 P3010 P3011 P3012 P3013 P3014 P3015 P3016 P3019 P3020 P3021 P3022 P3130 P3131
P3132 P3133 P3134 P3135 P3136 P3151 P3152 P3153 P3154 P3155 P3156 P3157 P3158 P3159 P3160 P3161
P3162 P3163 P3164 P3165 P3166 P3167 P3168 P3169 P3170 P3171 P3172 P3173 P3174 P3175 P3176 P3177
P3178 P3179 P3180 P3181 P3182 P3183 P3184 P3185 P3186 P3187 P3188 P3199 P3929 W2735 W2736 W2737
W2738 W2739 W2740 W2803 W2804 W2805 W2806 W2807 W2808 W2809 W2878
```

### 2.2 Ids confined to one tree - the copy list

**yoga (manager)** - 127 ids

```
D3153 D3208 D3209 D3274 D3466 D3467 D3468 D3594 D3722 H3642 H3643 H3644 H3645 H3646 H3647 H3648
H3649 H3650 H3651 H3652 H3653 H3654 H3655 H3656 H3657 H3658 H3659 H3660 H3661 H3662 H3663 H3664
H3665 H3666 H3667 H3668 H3669 H3670 H3704 H3768 H3769 H3770 H3771 H3772 H3773 H3774 H3775 H3776
H3777 H3778 H3843 H3911 H3912 H4170 H4232 H4233 H4234 H4425 H4426 H4616 L3801 L3816 L3817 L3859
L3923 L3924 L3925 L3926 L3927 L3928 L3929 L3930 L3931 L3932 L3933 L3934 L3935 L4000 L4001 L4064
L4065 L4066 L4067 L4068 L4069 L4192 L4193 L4194 L4195 L4384 L4385 L4386 L4576 P3993 P3994 P3995
P4121 W2810 W2811 W2812 W2813 W2814 W2815 W2816 W2817 W2818 W2819 W2820 W2821 W2822 W2823 W2824
W2825 W2826 W2827 W2828 W2869 W2870 W2871 W2872 W2873 W2874 W2875 W2876 W2877 W2942 W3006
```

**secratary-cloud (authority)** - 62 ids

```
D3155 D3156 D3210 D3211 D3212 D3213 D3214 D3215 D3338 D3339 D3530 D3658 H3780 H3781 H3782 H3783
H3784 H3976 H4040 H4104 H4360 H4488 H4553 L3823 L3824 L3825 L3826 L3827 L3828 L3942 L3943 L4128
L4129 L4256 L4320 L4321 L4448 P3189 P3190 P3191 P3192 P3193 P3194 P3195 P3196 P3197 P3198 P3200
P3201 P3202 P3203 P3204 P3205 P3206 P3207 P3208 P3209 P3210 P3211 P3865 P3866 P4057
```

**ZABZ-TECH (this node)** - 244 ids

```
D3111 D3112 D3113 D3114 D3115 D3116 D3117 D3118 D3119 D3120 D3121 H3451 H3452 H3453 H3454 H3455
H3456 H3457 H3458 H3459 H3460 H3461 H3462 H3463 H3464 H3465 H3466 H3467 H3468 H3469 H3470 H3471
H3472 H3473 H3474 H3475 H3476 H3477 H3478 H3479 H3480 H3481 H3482 H3483 H3484 H3485 H3486 H3487
H3488 H3489 H3490 H3491 H3492 H3493 H3494 H3495 H3496 H3497 H3498 H3499 H3503 H3504 H3505 H3506
H3507 H3508 H3509 H3510 H3511 H3512 H3513 H3514 H3515 H3516 H3517 H3518 H3519 H3520 H3521 H3522
H3523 H3524 H3525 H3526 H3527 H3528 H3529 H3530 H3531 H3532 H3533 H3534 H3535 H3536 H3537 H3538
H3539 H3540 H3541 H3542 H3543 H3544 H3545 H3546 H3547 H3549 H3550 H3556 H3557 H3558 H3559 H3561
H3562 H3563 H3564 L3469 L3470 L3471 L3472 L3473 L3474 L3475 L3476 L3477 L3478 L3479 L3480 L3481
L3482 L3483 L3484 L3485 L3486 L3487 L3488 L3489 L3490 L3491 L3492 L3493 L3494 L3495 L3496 L3497
L3498 L3499 L3500 L3501 L3502 L3503 L3507 L3508 L3509 L3511 L3512 L3513 L3514 L3515 L3516 L3517
L3518 L3519 L3520 L3521 L3522 L3523 L3524 L3525 L3526 L3527 L3528 L3529 L3530 L3531 L3532 L3533
L3534 L3535 L3536 L3537 L3538 L3539 L3540 L3541 L3542 L3543 L3544 L3545 L3546 L3547 L3548 L3549
L3550 L3551 L3552 L3553 L3554 L3555 L3556 L3557 L3558 L3700 L3701 L3703 L3704 L3705 L3706 L3707
L3709 L3710 L3711 L3712 L3713 L3714 L3715 L3716 L3717 L3718 L3719 L3720 L3721 L3722 L3723 L3724
L3725 L3726 L3727 L3728 L3729 P2990 P2991 P2992 P2993 P2994 P2995 P3146 P3147 P3148 P3149 P3798
P3800 P3801 P3802 P3803
```

**zabz-tech-linux** - 0 ids

```

```

**LakewooechsMini** - 3 ids

```
H2672 H3054 H3145
```

> `zabz-tech-linux` has none, and `LakewooechsMini` has 3. The 244 on this node are the reason the
> local checkout cannot simply be reset to the authority: 244 entries exist nowhere else.

---

## 3. Status counts, before -> after

**Before (2026-10-15 14:10Z):**

* yoga (manager) - 4204 entries, **453** open pain, 127 open owner questions, check 0 error(s), legacy drift 0
* secratary-cloud (authority) - 4121 entries, **475** open pain, 127 open owner questions, check 0 error(s), legacy drift 0
* ZABZ-TECH (this node) - 3960 entries, **411** open pain, 143 open owner questions, check 0 error(s), legacy drift 0
* zabz-tech-linux - 3440 entries, **344** open pain, 143 open owner questions, check 0 error(s), legacy drift 0
* LakewooechsMini - 1646 entries, **162** open pain, 143 open owner questions, check 0 error(s), legacy drift 2 (wins)

**After: unchanged.** This task ran zero `resolve`, zero `append` and edited no entry file. The
comparison in §1 is therefore against the same state it was measured in, and `journal.py check`
reporting `0 error(s)` at the end is evidence that nothing was broken - not evidence that anything
was fixed.

### 3.1 `journal.py check` at the end of this task

```
$ cd C:\Users\ezabz\code\harness-config && python journal/tools/journal.py check
-- 0 error(s), 251 warning(s), 83 info
$ ssh secratary-cloud 'cd /root/code/harness-config && python3 journal/tools/journal.py check'
-- 0 error(s), 267 warning(s), 83 info
```

`check` only validates *within* one tree - duplicate id, malformed entry, sha. It cannot and does
not detect the 363 cross-tree collisions in §1.2. **`check` returning 0 errors in all five trees while
363 ids disagree across them is the sharpest single statement of this finding.**

---

## 4. Per-pain verdict table - NOT PRODUCED, and why

Steps 2 and 3 of the brief (read every open pain, test it, `resolve` the dead ones) are **blocked by
step 1's own STOP condition**, and the brief pre-authorises the response: *"If a bulk list is more
honest than individual judgement, say so and stop."*

Concretely, on **ZABZ-YOGA** - the tree the 453 figure comes from - a verdict would have to be
written against entries that:

* differ in content from the same id on the authority for **99** ids, and on this node for **254**;
* are joined by **488** ids ZABZ-TECH holds and yoga does not, and **244** the other way;
* cannot be resolved at all without a write, because `resolve` is the only mechanism and it is the
  blocked operation.

A verdict table produced here would be a table of **claims about a tree that is about to change**,
and the brief is explicit that *"closing a pain whose condition you did not test is the single worst
thing you could do in this task."* I could test individual conditions, but I could not *record* the
result without writing, and an unrecorded verdict is exactly the memory that already fails to
survive between sessions.

### 4.1 What was established about the 453 without writing

One thing worth carrying forward, because it bears on *"453 open rows is not a list, it is noise"*:

```
ZABZ-YOGA   : 560 pain files carry '|open -->' in their first line; journal.py status says OPEN PAIN 453
authority   : 581 raw '|open -->' markers;                                          status says 475
ZABZ-TECH   : 514 raw '|open -->' markers;                                          status says 411
```

**This is not a defect.** The difference is `journal/state/status.tsv`, the append-only status log:
the entry file records how the entry was *written*, and `status.tsv` records what *became of it*.
`journal.py`'s `open_entries()` applies `effective_status()`, which lets `status.tsv` override the
marker - documented in `journal/tools/journal.py` lines 990-1008. Worked example, verbatim:

```
$ Get-Content journal/entries/pain/P11.md -TotalCount 1
<!-- e:pain|P11||-|open -->                     <-- the file still says open
$ Select-String -Path journal/state/status.tsv -Pattern '^pain	P11	'
pain  P11  done  2026-09-30  ZABZ-TECH  Verified ALREADY FIXED on 2026-09-30 by the pain-corpus audit ...
```

So `OPEN PAIN 453` is the honest number and the raw marker count is not. **Anyone grepping
`|open -->` to size this backlog over-counts by 100-110 rows per tree.**

---

## 5. The owner queue - 127 pending rows, classified

Command (read-only):

```
ssh secratary-cloud 'python3 ~/bin/owner-queue.py next'     # head, 124 live / 3 deferred
```
plus the full table from `owner_decision_queue` on the authority:

```sql
SELECT status, COUNT(*) FROM owner_decision_queue GROUP BY status;
-- resolved 279 | pending 127 | dismissed 71 | answered 40
```

Nothing here was resolved, answered, dismissed or deferred - **classification only**, as instructed.

### 5.1 The rule applied

From `HANDOFF-ROUND4.md` §9 and `AGENTS.md` §2: **his** = money, customers, legal/contractual
posture, family, anything irreversible, real taste. **ours** = an engineering fault, or a decision an
agent should have made. The measured shape of the failure being corrected: *"Rounds 1-3 pushed 595
things at him of which 383 were engineering faults."*

### 5.2 The tally

```
pending rows            : 127
HIS                     : 26
OURS                    : 101   (80%)
```

### 5.3 The `ours` list - 101 rows, each with the one-line reason it is not his

**Proposed one-line disposition for the whole `ours` set:** *an agent decides it, records the
decision in the journal (after resolution step R3), and moves on - the owner is not asked.*

Where a row has a money, login or legal component that genuinely is his, the reason column says
so and that component should be **split into its own money row** rather than left bundled with the
engineering half. The row as a whole still does not belong in his queue.

| id | row | why it is not his |
|---:|---|---|
| 212 | autonomous daily caps raised 4->500 and $3->$70 | an agent-governance cap, not a business decision |
| 218 | lpt_prod lacks the ConditionPreference column | schema drift between lpt_test and lpt_prod is an engineering fault |
| 237 | approve the 333 ceiling-fix deploy | a tested, green deploy that needs no owner |
| 239 | personality-test main frozen; 3 fix branches unpromoted | unpromoted fix branches are a merge chore |
| 261 | Deep Infra dead (card 402); 5.5x failover cost | the gateway silently burns 5.5x on a dead rung; routing is ours (the ~$30 card top-up is a separate money row) |
| 262 | ZABZ-TECH RDP wedged; reboot to get mic passthrough | a wedged RDP service on a machine we operate |
| 270 | both live Stripe webhook endpoints are OFF | two Stripe webhooks switched off is a configuration fault |
| 277 | two-way control Yoga<->desktop | remote-control topology is an engineering choice |
| 283 | broker: two instances on one SQLite file | one writer vs Postgres is an architecture decision an agent makes |
| 284 | Android release signing key has one copy | key-custody placement is an ops decision with an obvious answer |
| 295 | 223 new high audit findings - walk them? | a production audit's findings are agent work |
| 305 | Dialpad ~1,260/yr avoidable spend | cleaning up a SaaS account is operational |
| 306 | unclassified $127.95 US MOBILE charge | classifying our own bank lines is bookkeeping |
| 315 | Spitzer or John Frankl owns (917) 848-2026 | reconciling two names for one number is a data-join task |
| 316 | Sayagh flip phone: fixable, and what cost | diagnosing a dropped-off phone and quoting bench rate is the job |
| 318 | does the OnePlus belong to Reifman, and what is wrong | identifying an unlabelled handset is the job |
| 319 | Reifman's Cadence returned 'doesn't charge' | diagnosing a charging fault is the job |
| 323 | $9.99 Dell cover set for Neiman; quote $60? | a $9.99 part and a $60 quote are routine |
| 324 | Nebenzahl: is this job alive or dead | whether a lead is alive is answerable from the record |
| 325 | Nintendo Switch battery repair price (mrs glass) | routine repair pricing once margin policy exists |
| 327 | Eli Green's $120 collected or written off | reconstructing whether $120 was taken is bookkeeping |
| 328 | Ribowsky's $69.31 card charge captured? | whether a card charge captured is a processor lookup |
| 329 | Birnbaum's AirTags waived or billed $75 | waived or billed is a record lookup |
| 330 | hirschberg battery price | routine battery pricing |
| 331 | three stale leads: chase or drop | chasing or dropping stale leads is routine |
| 332 | two finished jobs with no price | pricing two finished jobs is routine once policy exists |
| 335 | money plane: let money alerts out or not | an outbound-guard engineering trade-off |
| 336 | counter iPad/iPhone have no real web restriction | an iPad/iPhone filtering misconfiguration |
| 353 | Kyocera job ready-but-unpaid contradiction | a paid/unpaid contradiction in the ledger |
| 356 | Seagate drive un-closed with no reason | an un-closed work order with no reason recorded |
| 359 | is the TSL5 Tesla-module job dead | whether a job is dead is answerable from the record |
| 368 | is there a laptop here from a cancelled order | inventory reconciliation against a drop-off text |
| 371 | closed UNFIXABLE but customer told $105 | status contradicts what the customer was told |
| 374 | customer's USB in the hallway closet drop-off | the USB/hallway drop-off is a physical reconciliation |
| 375 | is the GoPro still on the shelf | whether the GoPro is on the shelf is a stock check |
| 377 | 'paid $1000 cash' vs 'still owes $250' | two contradictory payment records on one work order |
| 379 | Pixel 6 disassembled on a cancelled order | an unreconciled bench state on a cancelled order |
| 380 | cancelled with no reason recorded | a cancellation with no reason recorded |
| 382 | four SD cards: cancelled after recovery work | an unreconciled cancellation with recovered cards |
| 383 | UNFIXABLE with no record of return | no record of the customer being told or the drive returned |
| 389 | cancelled, but an adapter was ordered | an adapter ordered against a cancelled order |
| 392 | LG Exalt repair cost / nothing collected | a repair with no price and no collection recorded |
| 394 | lab quote promised on a closed order | an unfulfilled promise of a lab quote |
| 395 | Galaxy A54 cancelled, case open with a $349 quote | an order cancelled while its case file is open with a live quote |
| 396 | Lachman's bag of drives: still here? | whether customers' drives are still on the shelf is a stock check |
| 397 | Shimon Vogel's HP Compaq still in the shop? | whether a machine is still in the shop is a stock check |
| 398 | Shimon Vogel's HP ProDesk still in the shop? | whether a machine is still in the shop is a stock check |
| 400 | Jacobowitz E4610 repair path still pending | a pending repair-path decision on a diagnosed board |
| 403 | Kleimar Moto G Play screen fitted? | whether a screen was fitted is a record check |
| 405 | A02s screen replaced? | whether a screen was replaced is a record check |
| 417 | Chaya Brodie's laptop lead: chase or close | chasing or closing a quiet lead is routine |
| 418 | Greenwald $120+tax collected? | whether a charge was collected is a processor lookup |
| 419 | what to do with Nechama Gewirtz's flip phone | what to do with an unrepairable handset is a case decision |
| 420 | has Devorah Goldberg's iPad been collected | whether an iPad was collected is a record check |
| 421 | was this cancellation deliberate | whether a cancellation was deliberate is answerable internally |
| 422 | is the E4610 in the green bin or with her | a note/text contradiction about where a phone is |
| 424 | duplicate $15 battery sale on your own account | a duplicate $15 row on our own account |
| 425 | two customer ids on one number | two customer ids on one number need merging |
| 427 | ~30 orders 'paid' with no payment row | ~30 orders marked paid with no payment row |
| 428 | release months-old 'out for pickup' orders? | an 'out for pickup' ageing policy is a process decision |
| 430 | ~201 uncategorised Zelle payments (~$45,800) | ~201 uncategorised Zelle payments is bookkeeping |
| 431 | unclassified $4.39 PLAN FEE - ALIPAY | classifying our own bank lines is bookkeeping |
| 434 | work order quarantined after 5 failed runs | a quarantined work order after 5 failed runs |
| 435 | install the nightly books pipeline | installing a verified pipeline is engineering |
| 436 | unclassified $69.68 NPGS-MAIN ST | classifying our own bank lines is bookkeeping |
| 441 | kosher-ai-filter main frozen; promote merges | unpromoted merges are a merge chore |
| 443 | unclassified $52.13 purchase interest | classifying our own bank lines is bookkeeping |
| 446 | dialer record dead weight - delete or build | deleting a dead DNS record is operational |
| 447 | stop the mesh broker on the frozen office box | stopping a redundant broker on a frozen box is operational |
| 448 | authority box cannot hold its working set | memory limits/leaks on our own box |
| 455 | AI text line is not answering your own texts | an unscheduled responder script |
| 457 | unclassified $92.84 lcd screen | classifying our own bank lines is bookkeeping |
| 458 | unanswered inbound text on the AI line | an unanswered inbound text is the responder's job |
| 459 | inbound: 'that was a loan from me to the business' | an inbound financial statement must be recorded and acted on |
| 460 | OpenAI spend feed unreadable (no usage scope) | obtaining an API scope for our own spend feed is ops |
| 461 | merge proven branch into personality-test main | a proven conflict-free merge |
| 462 | production running unreleased code | production running unreleased code is a deploy fault |
| 468 | 20 orders CAPTURED with no payment row | tieing Stripe payments to orders is engineering |
| 471 | 268 terminal payments tied to no work order | requiring a work order at the terminal is a config change |
| 473 | full disk: the free fix does not work | disk/schema options are engineering trade-offs |
| 474 | merge PR #1 in chumash-timeline | a clean one-file fast-forward merge |
| 485 | promote PR #92 into personal-secretary-mvp master | a proven green merge |
| 487 | disable mesh-broker on the frozen office box | disabling a redundant service is operational |
| 489 | restore the 15-minute text-channel safety check | restoring a missing safety check is engineering |
| 490 | Chaya Shande deleted video unrecoverable | an unrecoverable deletion and a quote is a case decision |
| 496 | alert boxes bypassing the text relay | two alert boxes bypassing the relay is an engineering fault |
| 497 | flood guard refuses the same text 5 times | a flood guard refusing the same text 5 times |
| 498 | Item 32 DoD vs 199 legacy sync rows | a DoD check against legacy rows is engineering |
| 500 | rotate the shared filter-broker credential | rotating a leaked credential is security work |
| 501 | deploy the _db_lock fix and restart company-api | a built, tested fix waiting to deploy |
| 502 | revoke the leaked legacy GitHub token | revoking a leaked live token is security work |
| 503 | credential passed as a process argument | a leaked credential passed as a process argument |
| 504 | authority DB 27.79 GB, memory stalls | a 27.79 GB database and memory pressure is engineering |
| 505 | WO2601150002 has two $140 payments | a duplicate $140 payment is a ledger reconciliation |
| 506 | WO2602180002 has two $40 payments | two payments on a $40 order is a ledger reconciliation |
| 507 | autopilot thread holds the DB lock | a DB lock held by the autopilot thread is an engineering fault |
| 512 | Fisher SD card: call to read 23 names, or park | resuming a case by calling the customer is the job |
| 515 | resolver refuses to book three credits | unbookable ledger credits is bookkeeping |
| 516 | BitLocker key still in lpt-hub git history | purging a leaked key from git history is security work |
| 517 | company-api hit its 10G MemoryMax | a MemoryMax trade-off on our own box |
| 518 | 8.29 GB snapshot can never be pushed | an unpushable 8.29 GB snapshot is a retention decision |

### 5.4 The `his` list - 26 rows (unchanged, for contrast)

| id | row | why it is his |
|---:|---|---|
| 78 | mother's US Mobile port needs four account fields | family - his mother's US Mobile account; only he can supply the port fields |
| 110 | 2022 Elantra: ~$400 IVT fluid + monitoring | money + taste - authorising ~$400 of work on his own car |
| 169 | Fall 2026 Felician balance $5,758 - who pays | family + money - who pays a $5,758 tuition balance |
| 206 | NJ DOL/Weinberg: make the one phone call? | legal posture - the entry says the call to NJ DOL is his to make |
| 207 | T-Mobile home internet still billing $85; gateway? | his property + money - only he knows if he still holds the T-Mobile gateway |
| 276 | do you own a responsa database / print pesak shelf | his property - whether he owns a responsa database or print pesak shelf |
| 279 | Amex payment failure - which card to fix | his account - a declined Amex payment is his to fix |
| 290 | Shop Jasmyn WhatsApp extraction - what to charge | real taste + money - setting a new customer price ($150 extraction) |
| 299 | customer device photos: retention and access | customer privacy policy - retention and access to customer device photos |
| 303 | off Dialpad now, or the fast unification first | business posture - keeping or leaving Dialpad is a contract/cost strategy call |
| 307 | approve the $50 diagnostic-fee wording | customer-facing pricing copy - wording that changes what customers pay |
| 312 | did Yisroel's actual hours change with the shop week | payroll - whether Yisroel's actual hours changed with the shop's week |
| 333 | paste the LIVE Stripe publishable key | his login - the LIVE Stripe publishable key exists only behind his dashboard |
| 449 | fund Telnyx so the Waze device can ship | money - adding a card to Telnyx funds the Waze product |
| 463 | cancel the leftover Audible membership | his login + money - Amazon/Audible cancellation needs him |
| 465 | file the NJ ST-50 Q3 return | tax/legal - filing the NJ ST-50 sales-tax return |
| 482 | Chase card ending 9680 - what was it | his account - a Chase card only he can identify |
| 492 | NJ payroll returns have no filer | tax/legal - NJ payroll filings with no filer |
| 493 | fund Telnyx so the fleet has cellular | money - funding the Telnyx account |
| 495 | top up the prepaid AI balance | money - topping up the prepaid AI balance |
| 499 | NJ ST-50: no filing record, source needs your login | tax/legal + his login - the NJ ST-50 filing source needs him |
| 508 | top up the prepaid AI balance | money - topping up the prepaid AI balance |
| 510 | Apple ABM forbids reselling supervised devices | legal/contractual posture - whether to keep selling supervised devices |
| 511 | camera product uploads photos to our cloud | product taste - the camera product's connectivity positioning |
| 513 | top up the prepaid AI balance | money - topping up the prepaid AI balance |
| 514 | top up the prepaid AI balance | money - topping up the prepaid AI balance |

### 5.5 Patterns worth acting on

1. **Bookkeeping is the largest single class.** 5 rows ask the owner to classify *our own* bank or ledger lines (ids 306, 431, 436, 443, 457). He cannot know these better than the ledger can; they are a categorisation job with a merchant-normalisation and matching fix behind it.
2. **A large share of the queue is a data contradiction**, not a decision: 16 rows read "the order says X and the record says Y" (e.g. 315, 353, 368, 374, 375, 379, 382, 396, 397, 398, 403, 405, 420, 422, 505, 506). Each is answerable from the estate's own systems.
3. **Five separate rows are the same money question** - "the prepaid AI balance is low, top it up?"
   (ids 495, 508, 513, 514 and the Telnyx pair 493/449). Repeated re-asking of one money decision is
   itself the defect; it belongs as **one** standing rule ("top up automatically up to $N"), asked once.
4. **Four merge/promote rows** (ids 239, 441, 461, 474, 485) are pure engineering chores that reached
   the owner's queue. `HANDOFF-ROUND4.md` §9 already says development decisions are not his.

---

## 6. What contradicts the brief or the round-4/5 documents

1. **The brief's "read first" paths do not exist in any tree.** There is no
   `docs/dsh-evolution-v6/PROGRAM.md` and no `docs/dsh-evolution-v4/HANDOFF-ROUND4.md` in this
   checkout, on the authority, or anywhere in `C:\Users\ezabz\code\harness-config`. Verified:
   `grep -r 'dsh-evolution-v[456]|HANDOFF-ROUND[456]'` over the whole checkout returns **no matches**, and
   `ls -d docs/dsh-evolution*` returns only `docs/dsh-evolution-v2`. The real documents are the
   renamed copies in the round-6 working directory **`C:\Users\ezabz\code\_r6-recent\`**
   (`PROGRAM-v6.md`, `PROGRAM-v4.md`, `HANDOFF-ROUND4.md`, `HANDOFF-ROUND5.md`, `CENSUS-v4.md`),
   written 2026-10-15 10:11-10:16 local. Round 6's own definition of done (§6.5 of `PROGRAM-v6.md`)
   names `docs/dsh-evolution-v6/50-journal-hygiene.md` as the output path; **that directory does not
   exist**, so this file is delivered to `/root/work/r6/` as instructed by the task instead.
2. **"453 open pain" is true in exactly one tree.** It is ZABZ-YOGA's number. The authority reports
   **475** and this node **411**. The brief and `PROGRAM-v6.md` §3 present 453 as the estate's
   backlog; it is one tree's backlog, and 363 ids across the estate disagree about their content.
3. **"127 pending owner questions" is consistent** across yoga and the authority (both 127) - this
   is the one number that survives the fork, because the queue lives in a database on the
   authority, not in the journalled trees. **This node and the two older trees show 143** - a
   16-row-stale mirror, so the per-tree mirror is not trustworthy in the older trees.
4. **`journal.py check` = 0 errors is not a health signal for the journal.** All five trees report
   0 errors while 363 ids carry conflicting bodies across them. `check` has no cross-tree rule.
5. **`PROGRAM-v6.md` §1 row 5 says the id allocator "no longer mints duplicates"** - settled there
   with `journal.py next-id pain` returning `P3865`. That is true *within a tree*. The evidence in
   §1.3 shows duplicate ids were minted **across** trees for at least `D3034`-`D3137`, `H3393`-`H3450`,
   `H3565`-`H3641`, `L3668`-`L3941`, `P2996`-`P3022` and more. The allocator fix does not address
   the fork; each tree allocates from its own ceiling.
6. **`PROGRAM-v6.md` §4 says "does not touch `secratary`" and `AGENTS.md` §5 freezes it.** Nothing in
   this task wrote to any host. Confirmed rather than contradicted - recorded because the rule was
   relevant and was obeyed.

---

## 7. What I deliberately did not do, and what I could not verify

**Did not do:**

* **No `journal.py resolve`** in any tree, and no `journal.py append` anywhere - both forbidden by
  the step-1 STOP condition and by the task's write allow-list.
* **No edit to any entry file**, no `git add -A`, no commit, no push, no `git reset`, no `checkout`,
* no `clean`, no `rm`. The only files written on this node are under `C:\Users\ezabz\_r6\`
  (scratch manifests + this report) and the two deliverables.
* **No service state changed on any host** (`AGENTS.md` §5). The authority was read-only throughout:
  `scp`/`ssh` of read-only probe scripts into `/root/work/r6/`, which the task itself instructed.
* **No owner queue row was resolved, answered, dismissed or deferred.** Classification only.

**Could not verify (and did not claim):**

* **ZABZ-YOGA's full manifest is loaded but its per-entry content was not diffed beyond hashes.**
  The 99 yoga-vs-authority content collisions are established by SHA-256, not by reading both bodies.
  `D3034`, `D3124` and `H3393` were read on both sides as spot checks; the other 96 were not.
* **`mac-mini` reports `LEGACY DRIFT 2 entries not absorbed (wins:2)`.** I did not open them. It is
  the only tree with non-zero drift and it is not claimed as healthy here.
* **`zabz-tech-linux` was reached at branch `main` `985f9378`.** Its 764-id deficit against yoga is
  established by hash comparison of its manifest; I did not inspect its working tree or its
  uncommitted state.
* **The claim that the authority is the right merge base is a recommendation.** I verified it is
  the box that owns `owner_decision_queue` and that `AGENTS.md` §5 makes it the sole writable host.
  I did **not** verify that `/root/code/harness-config` is the tree the authority's own sessions
  write to; it may itself be a stale checkout with the live journal elsewhere on that box.
* **The owner queue rows were classified from question + context + recommendation text**, not from
  the underlying case files. Where a row's classification turns on a detail inside a case file
  (e.g. 290, 353, 490), the classification is a reading of the row's own wording.
* **No pain was closed and no pain was re-filed as live.** 453 open pain rows on ZABZ-YOGA, 475 on
  the authority and 411 here remain exactly as they were. That is the honest state, and §4 says why.

---

## 8. Reproduce everything in this document

```
python C:\Users\ezabz\_r6\analyze2.py      # sections 1.1-1.3, from the five manifests
* manifests: C:\Users\ezabz\_r6\{yoga,auth,local,linuxpc,macmini}-manifest.tsv
bash 50-resolutions.sh                    # read-only; prints the divergence proof and the plan
```
