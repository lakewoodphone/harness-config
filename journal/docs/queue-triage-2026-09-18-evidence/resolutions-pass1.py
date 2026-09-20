#!/usr/bin/env python3
"""Triage pass 2026-09-17: close the engineering rows in owner_decision_queue.

Uses the CLI itself so the write path is exactly the one already proven
(commit-before-write to avoid SQLITE_BUSY on a read->write upgrade).
Retries on 'database is locked' -- that is transient contention, not a failure.
"""
import os
import subprocess
import sys
import time

CLI = os.path.expanduser("~/bin/owner-queue.py")
PY = sys.executable or "python3"

RESOLUTIONS = [
    (65, """ENGINEERING - not an owner decision. It is a data-representation choice
(which table holds the fact), and development decisions are delegated to us.

STANDING POLICY, recorded here: every customer payment we have evidence of is recorded in
production against the real order as PENDING. A row never becomes CAPTURED without an
observed settlement (a Stripe read or the counter card reader), and any change to a money
column writes an order_status_history row saying why. The alternative - leaving production
at $0.00 while we hold the customer's money - is the shape of the two data losses this
business has already had.

CLOSURE, by us: apply that policy to the unrecorded rows via the reconciliation tooling.
PRECONDITION: the wrong-order links must be fixed first - the E4610 balance record currently
points at order 2837, which is Shmuel Birnbaum's. That link correction is engineering and is
tracked in row #92. No money moves and no customer is contacted by any of this.

The separate question - is a given deposit actually captured - is a verification task against
the card reader or Stripe, not a decision for the owner."""),

    (72, """ENGINEERING - credential hygiene on our own accounts, not an owner decision.

CLOSURE, by us, each step verified before and after:
 (1) cut github-actions-deployer from AdministratorAccess to deploy-only, delete the key, and
     confirm the GitHub Actions deploy still runs green afterwards;
 (2) delete the superseded Stripe key once the counter card reader is confirmed to be on the
     new key, with the reader alive throughout;
 (3) rotate AI_GATEWAY_API_KEY and scrub the three backup copies;
 (4) remove every tracked copy of the exposed literals and add a commit guard so they cannot
     return.

NOT OURS: the fourth item in the row - OUTWORQ's Twilio token - belongs to a third party's
account and cannot be rotated by us. That single ask (ask Shimon, or authorise a drafted
message for the owner's go) is the only owner-relevant part, and it is already on the queue
as row #17. Nothing else in this row needs him."""),

    (76, """ENGINEERING - a duplicate provisioning artifact, not a decision.

EVIDENCE: both endpoints are on the shop's own domains - ai.abletelsolutions.com (verified
2026-09-17 resolving to our Cloudflare-proxied edge) and api.lakewoodphoneandtech.com. No
third company is receiving customer texts; the same shop system is receiving each message
twice, which is a defect and a double-processing risk, not a vendor relationship.

CLOSURE, by us: read the lakewoodphoneandtech.com endpoint's inbound log to confirm nothing
on the website side still consumes Dialpad subscription 5364769636098048, then disable that
subscription. If the website side IS still live, repoint it at the surviving subscription
rather than disabling anything. Finally, fix the provisioning script
(phone-and-tech-full/backend/scripts/ops/provision-dialpad-sms-webhook.ts) so it reconciles
existing subscriptions instead of adding a second one - otherwise the next run recreates this."""),

    (83, """ENGINEERING - security configuration on our own MDM host.

INDEPENDENTLY VERIFIED BY ME 2026-09-17: GET https://mdm.abletelsolutions.com/enrollment.mobileconfig
returns HTTP 200 with no credentials, served by WazeRestore/1.0. The row's finding is confirmed.

CLOSURE, by us, in this order:
 (1) set ENROLLMENT_DYNAMIC_IDENTITY=true explicitly in /opt/waze-mdm/.env so the protection is
     a configured value rather than a code default that a future refactor silently changes;
 (2) rotate the embedded password literal out of the git-tracked enrollment.mobileconfig and out
     of every history-reachable copy, and add a guard so a literal cannot be committed again;
 (3) bench-test that a NEW device still enrols end to end;
 (4) only then consider the Caddy URL restriction. That is the stronger control but it is the one
     step that can break Setup Assistant enrolment, so it follows the bench test, not the reverse.

No owner input is required for any step; the only risk is breaking enrolment, which is why the
bench test is a precondition rather than a follow-up."""),

    (73, """ENGINEERING - a stuck helper boolean, plus a notification path that was never tested. Both ours.

CLOSURE, by us:
 (1) clear input_boolean.phoenix_worker_is_here and find what set it - a helper that still read
     'present' is the whole reason the automation fired once since 2026-08-03;
 (2) prove end to end that automation.security_occupancy_detected_while_away actually delivers a
     snapshot with the clip to notify.mobile_app_zabz_waze. This has never been tested, and an
     alarm whose alert never arrives is worse than no alarm;
 (3) then re-measure how often security_mode_auto_away_when_empty fires.

Only if it STILL mis-arms while someone is in the back does a narrow owner question exist - what
counts as 'empty'. That question is not live today, so the row does not belong on his list now."""),

    (82, """ENGINEERING - an ops default, not a preference of his.

RESOLVED AS: worker/headless nodes only - secratary and linux-pc. ZABZ-YOGA and ZABZ-TECH stay
report-only, because both already run the existing DSH Process Reaper for our own leaked helpers
and the only thing class A would add there is closing the owner's idle browser. That default
leaves his machines exactly as they are, so it needs no decision from him.

CLOSURE, by us: install the O4 hygiene job on secratary and linux-pc only, confirm it writes its
drift line every run so a node sliding out of the placeable set is visible, and record the
one-command off switch. Revisit only if a node looks slow for a reason this does not explain."""),

    (24, """ENGINEERING - a revoked OAuth token, not a decision.

It is the loudest error in the system (650 retries per window) against a credential that can never
succeed, and the retry loop is the actual defect.

CLOSURE, by us: stop the retry loop so the noise ends, and keep the integration's configuration
intact so nothing is lost. Re-connecting Spotify needs a one-time Spotify login that only the owner
can perform - that is a one-minute action whenever he wants it, not a decision to schedule, so it
does not hold a slot on this queue. If the re-connect is wanted, it is raised as an action, not a
question."""),

    (92, """ENGINEERING - data errors and a calibration, not owner decisions. repair.py refuses these
classes only because it is a production-write tool, not because the content is his.

CLOSURE, by us, one record at a time, re-running the verifier after each:
 (1) C06 x3 - the AUTOMATED LINKER mis-links. Re-point each hub record at its correct order, or
     CLEAR the link where no true order exists, after checking each against its case file. Note
     weissman-ssd-not-read carries its own warning that BOTH its links are wrong, so clearing is
     the honest action there rather than guessing. This changes which order a record points at,
     not what any customer owes;
 (2) C07 x2 - WO26081112580 and WO2608310003 moved READY_FOR_PICKUP -> IN_REPAIR/AWAITING_PARTS.
     Confirm the shop's real state from the case file: if the job genuinely went back, the hub is
     correct and the mirror lagging, so demote them in the tool as calibrated; if the shop did
     promise ready, correct the record. Either way it is a measurement against the case file.

No customer is contacted and no amount owed changes. If a record turns out to need a NEW promise
to a customer, that is a separate owner ask and will be raised on its own."""),

    (89, """NO LIVE OWNER DECISION. Verified 2026-09-17 by me on the authority: the divergence is real
(origin/master...master both diverged, 169 dirty files in the live checkout), but nothing is
blocked and nothing can be lost.

WHY NOT HIS: the corrected sync tool is already durable on
origin/rescue/lpt-sync-correct-lineage-20260917 and live on both machines, so no work is waiting.
The diff shows no file deleted on one side only, so taking either side wholesale cannot delete
anything, and psm holds zero files under docs/customer-operations - the customer corpus is in
lpt-hub. The safe action is inaction.

DECISION RECORDED: leave master alone. Merge only the tooling files
(app/services/lpt_hub_sync.py, scripts/lpt-sync-to-production.py - take the authority side, proved
by check_sync_tool_sanity()) as engineering work when convenient.

THE 54 CONTENT CONFLICTS (70 docs/personal-insurance, 7 app/family_chat) are personal-records
content and stay out of this queue. They will be raised to the owner only if and when a merge
becomes necessary and a human has to choose per path - they are not a live question now."""),

    (95, """ENGINEERING - a hosting migration, and the free branch of the choice.

INDEPENDENTLY VERIFIED BY ME 2026-09-17 (header evidence, which is authoritative): 
pricing.lakewoodphoneandtech.com, admin.lakewoodphoneandtech.com and
gifter.abletelsolutions.com all carry Netlify's x-nf-request-id header, while
lakewoodphoneandtech.com does NOT. The row's correction of its own earlier over-claim is right:
only the three secondary sites are still on Netlify.

CLOSURE, by us: move the three small static sites to Cloudflare Pages, the same pattern already
proven on the main site. No Netlify top-up is needed and no money is spent, so there is no money
decision here. These are secondary sites, so there is no urgency.

DEPENDENCY: this needs the Cloudflare API token that does not exist on any machine - row #74.
That token is the single access grant that also unblocks the public hours fix, the filterapp DNS
record, the R2 backup isolation and PR 142."""),

    (90, """PARTLY ENGINEERING, and the irreversible half is now moot.

THE FACT THE ROW COULD NOT ESTABLISH, NOW VERIFIED BY ME 2026-09-17: github.com/lakewoodphone/lpt-hub
is PRIVATE. Unauthenticated GitHub API returns 404, and a public control (torvalds/linux) returns 200
on the same instrument. The historical commits are therefore readable only by holders of repo access
- the owner, the authority, ZABZ-TECH and the rescue branches - not by the internet.

ENGINEERING CLOSURE, by us: move the five docs/customer-operations/cases/_credentials-*.md files out
of the tracked tree into the credential store that is already not in git, remove them from HEAD, and
add a guard so cases/_credentials-* cannot be committed again. That stops new exposure immediately and
is reversible.

HISTORY REWRITE IS NOT REQUIRED and I have NOT done it. A rewrite means a force-push, which is
irreversible and touches every clone - and the row's own recommendation is right that on a private,
access-controlled repo leaving the history may be entirely fine. The one owner question that survives
is narrow and NOT LIVE: if he cannot account for every existing clone, purging history becomes worth
considering. Until then the queue holds nothing for him here."""),
]


def main() -> int:
    failures = []
    for rid, how in RESOLUTIONS:
        for attempt in range(1, 6):
            p = subprocess.run(
                [PY, CLI, "resolve", str(rid), "--how", how],
                capture_output=True, text=True,
            )
            out = (p.stdout or "") + (p.stderr or "")
            if "locked" in out.lower():
                print(f"#{rid}: locked on attempt {attempt}, retrying in 20s")
                time.sleep(20)
                continue
            status = "OK " if p.returncode == 0 else "FAIL"
            print(f"{status} #{rid} rc={p.returncode} {out.strip()[:200]}")
            if p.returncode != 0:
                failures.append(rid)
            break
        else:
            print(f"FAIL #{rid}: still locked after 5 attempts")
            failures.append(rid)
    print("FAILURES:", failures if failures else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
