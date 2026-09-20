#!/usr/bin/env python3
"""Provenance correction pass 2026-09-18T02:08Z.

Two errors of mine to fix in resolutions I had already written:
  1. I dated my own verifications 2026-09-17; the authoritative host date is 2026-09-18.
  2. Row #89's text asserted '169 dirty files' as if I had measured it; I measured 166
     (and 119 ahead, not 116). Counts in a live checkout move, so the text now states
     what I measured and when, and labels the row's figures as the row's.

`resolve` overwrites resolution text by id, so re-resolving is the correct repair.
"""
import os
import subprocess
import sys
import time

CLI = os.path.expanduser("~/bin/owner-queue.py")
PY = sys.executable or "python3"
D = "2026-09-18"

RESOLUTIONS = [
    (76, f"""ENGINEERING - a duplicate provisioning artifact, not a decision.

EVIDENCE: both endpoints are on the shop's own domains - ai.abletelsolutions.com (verified by me
{D} resolving to Cloudflare anycast 172.67.172.153 / 104.21.71.247, i.e. our own proxied edge) and
api.lakewoodphoneandtech.com (direct origin, no proxy). No third company is receiving customer
texts; the same shop estate is receiving each message twice, which is a defect and a
double-processing risk, not a vendor relationship.

CLOSURE, by us: read the lakewoodphoneandtech.com endpoint's inbound log to confirm nothing on the
website side still consumes Dialpad subscription 5364769636098048, then disable that subscription.
If the website side IS still live, repoint it at the surviving subscription rather than disabling
anything. Finally, fix the provisioning script
(phone-and-tech-full/backend/scripts/ops/provision-dialpad-sms-webhook.ts) so it reconciles
existing subscriptions instead of adding a second one - otherwise the next run recreates this."""),

    (83, f"""ENGINEERING - security configuration on our own MDM host.

INDEPENDENTLY VERIFIED BY ME {D}: GET https://mdm.abletelsolutions.com/enrollment.mobileconfig
returns HTTP 200 with no credentials and no auth challenge, served by 'WazeRestore/1.0
Python/3.13.13'. The row's finding is confirmed at the live URL.

CLOSURE, by us, in this order:
 (1) set ENROLLMENT_DYNAMIC_IDENTITY=true explicitly in /opt/waze-mdm/.env so the protection is a
     configured value rather than a code default that a future refactor silently changes;
 (2) rotate the embedded password literal out of the git-tracked enrollment.mobileconfig and out of
     every history-reachable copy, and add a guard so a literal cannot be committed again;
 (3) bench-test that a NEW device still enrols end to end;
 (4) only then consider the Caddy URL restriction. That is the stronger control but it is the one
     step that can break Setup Assistant enrolment, so it follows the bench test, not the reverse.

No owner input is required for any step; the only risk is breaking enrolment, which is why the
bench test is a precondition rather than a follow-up."""),

    (95, f"""ENGINEERING - a hosting migration, and the free branch of the choice.

INDEPENDENTLY VERIFIED BY ME {D} (response headers, which are authoritative):
pricing.lakewoodphoneandtech.com, admin.lakewoodphoneandtech.com and
gifter.abletelsolutions.com ALL carry Netlify's x-nf-request-id header, while
lakewoodphoneandtech.com does NOT. The row's correction of its own earlier over-claim is right:
only the three secondary sites are still on Netlify. (Noted in passing: the root of admin. returns
404 while still being Netlify-served, which is worth a look during the migration but is not part of
this decision.)

CLOSURE, by us: move the three small static sites to Cloudflare Pages, the same pattern already
proven on the main site. No Netlify top-up is needed and no money is spent, so there is no money
decision here. These are secondary sites, so there is no urgency.

DEPENDENCY: this needs the Cloudflare API token that exists on no machine - row #74. That token is
the single access grant that also unblocks the public hours fix, the filterapp DNS record, the R2
backup isolation and PR 142."""),

    (89, f"""NO LIVE OWNER DECISION. Verified real by me on the authority {D}:
`git rev-list --left-right --count origin/master...master` = 176 behind / 119 ahead, HEAD=master,
166 dirty files in that live checkout.

PROVENANCE NOTE: the row's own figures were 116 ahead / 169 dirty. They have already moved, because
this is a live checkout under a running service. Treat any count here as a snapshot with a
timestamp, not a fact - and note that I verified the DIVERGENCE, not the row's per-path conflict
tally (54 files differing on both sides).

WHY NOT HIS: the corrected sync tool is already durable on
origin/rescue/lpt-sync-correct-lineage-20260917 and live on both machines, so no work is waiting.
The diff shows no file deleted on one side only, so taking either side wholesale cannot delete
anything, and psm holds zero files under docs/customer-operations - the customer corpus is in
lpt-hub, a separate repo. The safe action is inaction.

DECISION RECORDED: leave master alone. Merge only the tooling files
(app/services/lpt_hub_sync.py, scripts/lpt-sync-to-production.py - take the authority side, proved
by check_sync_tool_sanity()) as engineering work when convenient.

THE CONTENT CONFLICTS (70 docs/personal-insurance, 7 app/family_chat) are personal-records content
and stay out of this queue. They will be raised to the owner only if and when a merge becomes
necessary and a human has to choose per path - they are not a live question now."""),

    (90, f"""PARTLY ENGINEERING, and the irreversible half is now moot.

THE FACT THE ROW COULD NOT ESTABLISH, NOW VERIFIED BY ME {D}:
 (a) github.com/lakewoodphone/lpt-hub is PRIVATE - the unauthenticated GitHub API returns 404, and
     a public control (torvalds/linux) returns 200 on the same instrument. The historical commits
     are therefore readable only by holders of repo access - the owner, the authority, ZABZ-TECH and
     the rescue branches - not by the internet;
 (b) `git ls-files docs/customer-operations/cases/` in /home/zabz/lpt-hub returns exactly 5
     _credentials-*.md paths, so the row's premise is confirmed at source, not just asserted.

ENGINEERING CLOSURE, by us: move those five files out of the tracked tree into the credential store
that is already not in git, remove them from HEAD, and add a guard so cases/_credentials-* cannot be
committed again. That stops new exposure immediately and is reversible.

HISTORY REWRITE IS NOT REQUIRED and I have NOT done it. A rewrite means a force-push, which is
irreversible and touches every clone - and the row's own recommendation is right that on a private,
access-controlled repo leaving the history may be entirely fine. The one owner question that
survives is narrow and NOT LIVE: if he cannot account for every existing clone, purging history
becomes worth considering. Until then the queue holds nothing for him here."""),
]


def main() -> int:
    failures = []
    for rid, how in RESOLUTIONS:
        for attempt in range(1, 6):
            p = subprocess.run([PY, CLI, "resolve", str(rid), "--how", how],
                               capture_output=True, text=True)
            out = (p.stdout or "") + (p.stderr or "")
            if "locked" in out.lower():
                print(f"#{rid}: locked attempt {attempt}, retry in 20s")
                time.sleep(20)
                continue
            print(f"{'OK ' if p.returncode == 0 else 'FAIL'} #{rid} rc={p.returncode} {out.strip()[:120]}")
            if p.returncode != 0:
                failures.append(rid)
            break
        else:
            failures.append(rid)
    print("FAILURES:", failures if failures else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
