#!/bin/bash
# Owner-queue collapse, 2026-09-16 ~02:2xZ (ZABZ-YOGA).
# 33 pending -> only what genuinely needs the owner. Every dismissal carries its evidence.
# Evidence: journal D (2026-09-16), handoff H366. Four read-only triage slices, 01:22-02:08Z.
Q="python3 $HOME/bin/owner-queue.py"

echo "== CLOSE AS DONE =="
$Q resolve 55 --how "Done: chumash's SSO secret now matches the live login service (sha 3d4e5cd38044 both sides, read 2026-09-16 01:52Z). Only the per-app credential improvement remains, and that is mine."
$Q resolve 44 --how "Answered: the Stripe key was rotated 2026-09-15 19:35-19:47. The narrower question that survives (the OLD key still answers HTTP 200) is folded into the new credential-retirement row."

echo "== DISMISS: premise was false (the owner was asked for something that already had an answer) =="
$Q resolve 28 --dismissed "Measured false premise: admin/Hello@1234 IS the NVR password - digest auth returns type=N41C2P2 HTTP 200, and a wrong password returns Invalid Authority. Home Assistant sends basic auth and gets 401. Re-filed as mine: fix the integration auth and restore the 3 dead cameras of 6."

echo "== DISMISS: already built or already the behaviour =="
$Q resolve 45 --dismissed "Feature already exists: Armed mode, auto-away when the control room is empty 4 min, and a clip-attached push to the phone are all built and switched on. Replaced by the narrower arming-rule row."
$Q resolve 51 --dismissed "Already the current behaviour and needs no change: Lost Mode exists only as session-gated authenticated API routes, and the customer portal exposes pause/resume/cap only."

echo "== DISMISS: stale - the owner already decided it =="
$Q resolve 50 --dismissed "Stale: the owner approved these exact numbers (9/month, 250MB, 800MB cap, 18/GB) on 2026-09-05 - docs/research/responses/060-waze-data-usage-per-month.md:237. The row asked him to re-confirm his own decision."

echo "== DISMISS: duplicate =="
$Q resolve 70 --dismissed "Duplicate of the public-hours defect (54/59) - one hours bug on three surfaces. Folded, with its Netlify token blocker, into the single consolidated hours row."
$Q resolve 54 --dismissed "Duplicate - folded into the single consolidated public-hours row."
$Q resolve 59 --dismissed "Duplicate - folded into the single consolidated public-hours row."
$Q resolve 14 --dismissed "Duplicate: presence is already served by a working GPS tracker (device_tracker.zabz_waze, accuracy 10m, read 2026-09-16 01:44Z), and no office zone exists, so the permission would not have enabled at-the-shop either."
$Q resolve 48 --dismissed "Twilio half was a duplicate of row 17. The AWS half is folded into the new credential-retirement row."

echo "== DISMISS: mine to do, no owner decision in it =="
$Q resolve 43 --dismissed "Mine: buy every unit whole at 135.80 - cheaper than the repair route and no customer-visible Non-Genuine Display row."
$Q resolve 52 --dismissed "Mine: keep location for loss and theft recovery, 30-day retention, disclosed in the terms. Safe default."
$Q resolve 56 --dismissed "Mine: build the STOP opt-out so the sentence we already send customers is true. An A2P compliance obligation, not a taste call."
$Q resolve 57 --dismissed "Mine: scrub the tracked copies of backend/.env.test in phone-and-tech-full (its AWS key was already deleted 2026-09-15) and rotate the Ably key once a dashboard token exists."
$Q resolve 58 --dismissed "Mine: rotate the AI gateway key now, and schedule the shared DB password rotation as its own planned job."
$Q resolve 63 --dismissed "Mis-filed: its own recommendation is that I can do it. Delete the stale tracked credential file and leave history alone."
$Q resolve 66 --dismissed "Mine: move the tracked customer-password files to the secret store and add a pre-commit guard. No history rewrite, no force-push."
$Q resolve 67 --dismissed "Mine: redact the card number, purge the CVV from the local caches, and push that message with the other 110."
$Q resolve 46 --dismissed "Mine, and dormant: no customer can reach the portal at all (verified in a browser 2026-09-16 01:44Z), so this costs nothing today. Folded into the portal work."
$Q resolve 60 --dismissed "Mine, and dormant: the portal flag is off in all four Netlify contexts, not a production-only switch, and every /customer-portal/ URL redirects to the homepage. Costs 0 in customers."
$Q resolve 47 --dismissed "Mine to execute once the token exists - the Cloudflare R2 ask is an access grant, not a decision, and it is already covered by the credential-access row below."

echo "== ADD: the only questions left =="
$Q add --question "Confirm the shop's real opening hours. Today three surfaces disagree and all of them are wrong: the site's visible copy says Mon-Thu 10:30-5:30, the site's structured data tells search engines 18:00-23:00 Sun-Thu, and Google Business Profile says Wednesday 10:30 AM. The shop is actually CLOSED Wednesday, so the first unstaffed Wednesday is 2026-09-16." \
  --recommendation "Give me the hours in one line, and a Netlify deploy token so the fix can ship. I recommend: Mon/Tue/Thu 10:30-17:30, Fri 10:30-13:00, Wed and Sat closed, Sun by appointment - and one token, because without it nothing can be deployed and the fix stays on a laptop." \
  --options "Give the hours and a Netlify token (recommended)|Give the hours only, and you run the deploy yourself|Hours are different from my guess - tell me what they are" \
  --context "Measured live 2026-09-16 01:28-01:47Z: served HTML carries the 18:00-23:00 JSON-LD, a real browser shows every /customer-portal/ URL landing on the homepage, and production is a MANUAL Netlify deploy that no reachable machine holds a token for. Cost of silence, measured at a conservative 3 lost walk-ins a month at an 85 average ticket: about 255 a month, plus a drive-over on the first closed Wednesday." \
  --blocks "Public hours across the website, the structured data and Google Business Profile" --ages-days 1

$Q add --question "May I retire the exposed credentials in one pass? Four live exposures are still open: a leftover AWS deploy login that can do anything in the cloud account and that GitHub uses automatically, the OUTWORQ client's Twilio token sitting in a tracked repo file (confirmed live by a read-only API call, HTTP 200, friendly_name OUTWORQ LLC), the OLD Stripe key that still answers 200 after the rotation, and the AI gateway key printed into a session transcript." \
  --recommendation "One yes. I cut the AWS deploy login to deploy-only and delete the key, delete the old Stripe key once I confirm the counter card reader is on the new one, rotate the AI gateway key, and scrub every tracked copy - each step verified before and after, and the reader stays alive throughout. Shimon's OUTWORQ token is the one I cannot rotate: that needs you to ask him, or to tell me to draft the message for your go." \
  --options "Yes to all of it, and draft the Shimon message (recommended)|Yes to the credentials, but you will handle Shimon yourself|Not yet - tell me which one to leave" \
  --context "Verified 2026-09-16 01:45-02:08Z: AWS IAM inventory 2026-09-15T19:25:05Z shows github-actions-deployer holding AdministratorAccess with an Active key; a read-only Twilio GET on the OUTWORQ account returned HTTP 200; the old Stripe key sha 125deea8 still returns 200 in stripe-watch.log at 00:17Z; AI_GATEWAY_API_KEY sha 40566e066094 is identical across the live env and three backups." \
  --blocks "Credential hygiene across AWS, Twilio, Stripe and the AI gateway" --ages-days 1

$Q add --question "The shop's intrusion alarm cannot arm itself: the arming logic exists and is switched on, but it has fired once since 2026-08-03 because a helper boolean claims a worker is present - it was still reading present at 01:58Z today. Is that the rule you want, or should arming follow a time or a door instead?" \
  --recommendation "Let me fix the stuck input first, then test that a push with the clip actually reaches your phone - that test has never been proven and it is mine, not yours. If it still arms while you are in the back, I will bring you one narrow choice about what counts as empty." \
  --options "Fix the sensor first, then come back to me only if it still misfires (recommended)|Change the rule now - arm on a fixed time instead of presence|Leave it entirely alone" \
  --context "Measured 2026-09-16 01:58:57Z: input_boolean.phoenix_worker_is_here is on; automation.security_mode_auto_away_when_empty is on but last fired 2026-08-03; automation.security_occupancy_detected_while_away is on and pushes a snapshot via notify.mobile_app_zabz_waze (access_control.yaml:1634-1700)." \
  --blocks "Shop intrusion alerting" --ages-days 1

echo "== FINAL =="
$Q stats
