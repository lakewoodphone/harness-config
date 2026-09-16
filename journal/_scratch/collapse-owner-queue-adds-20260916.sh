#!/bin/bash
# The three surviving owner questions. 2026-09-16 ~02:3xZ, ZABZ-YOGA.
Q="python3 $HOME/bin/owner-queue.py"

$Q add --severity high --age-days 1 --source "H366 / four triage slices 2026-09-16" \
  --question "Confirm the shop's real opening hours. Three public surfaces disagree and all are wrong: the site's visible copy says Mon-Thu 10:30-5:30, the site's structured data tells search engines 18:00-23:00 Sun-Thu, and Google Business Profile says Wednesday 10:30 AM. The shop is CLOSED Wednesday, so the first unstaffed Wednesday is tomorrow, 2026-09-16." \
  --recommendation "Give me the hours in one line, plus a Netlify deploy token so the fix can actually ship. I recommend Mon/Tue/Thu 10:30-17:30, Fri 10:30-13:00, Wed and Sat closed, Sun by appointment - and the token, because production is a manual deploy and without it the fix stays on a laptop." \
  --options "Give the hours and a Netlify token (recommended)|Give the hours only and run the deploy yourself|The hours differ from my guess - tell me what they are" \
  --context "Measured live 2026-09-16 01:28-01:47Z: the served HTML carries the 18:00-23:00 JSON-LD block; a real browser shows every /customer-portal/ URL landing on the homepage; production is a manual Netlify deploy and no reachable machine holds a token. Cost of silence measured conservatively: 3 lost walk-ins a month at an 85 average ticket is about 255 a month, plus a drive-over tomorrow." \
  --blocks "Public hours on the website, the structured data and Google Business Profile"

$Q add --severity high --age-days 1 --source "H366 / four triage slices 2026-09-16" \
  --question "May I retire the exposed credentials in one pass? Four exposures are still live: a leftover AWS deploy login that can do anything in the cloud account and that GitHub uses automatically; OUTWORQ's Twilio token sitting in a tracked repo file, confirmed live by a read-only API call; the OLD Stripe key still answering 200 after the rotation; and the AI gateway key that was printed into a session transcript." \
  --recommendation "One yes. I cut the AWS deploy login to deploy-only and delete the key, delete the old Stripe key once I have confirmed the counter card reader is on the new one, rotate the AI gateway key, and scrub every tracked copy - each verified before and after, with the reader alive throughout. Shimon's OUTWORQ token I cannot rotate: that needs you to ask him, or to tell me to draft the message for your go." \
  --options "Yes to all of it, and draft the Shimon message (recommended)|Yes to the credentials, but you handle Shimon yourself|Not yet - tell me which one to leave" \
  --context "Verified 2026-09-16 01:45-02:08Z: AWS IAM inventory 2026-09-15T19:25:05Z shows github-actions-deployer holding AdministratorAccess with an Active key; a read-only Twilio GET on the OUTWORQ account returned HTTP 200 friendly_name OUTWORQ LLC; the old Stripe key sha 125deea8 still returns 200 in stripe-watch.log at 00:17Z; AI_GATEWAY_API_KEY sha 40566e066094 is identical across the live env and three backups." \
  --blocks "Credential hygiene across AWS, Twilio, Stripe and the AI gateway"

$Q add --severity low --age-days 1 --source "H366 / four triage slices 2026-09-16" \
  --question "The shop's intrusion alarm cannot arm itself: the logic exists and is switched on, but it has fired once since 2026-08-03 because a helper boolean claims a worker is present - it still read present at 01:58Z today. Is presence the rule you want, or should arming follow a time or a door instead?" \
  --recommendation "Let me fix the stuck input first and prove that a push with the clip actually reaches your phone - that has never been tested and it is mine, not yours. Only if it then arms while you are in the back would I bring you one narrow choice about what counts as empty." \
  --options "Fix the sensor first, then come back only if it still misfires (recommended)|Change the rule now - arm on a fixed time instead of presence|Leave it entirely alone" \
  --context "Measured 2026-09-16 01:58:57Z: input_boolean.phoenix_worker_is_here is on; automation.security_mode_auto_away_when_empty is on but last fired 2026-08-03; automation.security_occupancy_detected_while_away is on and pushes a snapshot via notify.mobile_app_zabz_waze (access_control.yaml:1634-1700)." \
  --blocks "Shop intrusion alerting"

echo "== FINAL =="
$Q stats
