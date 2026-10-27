# Applied 2026-10-27 22:41Z — a security page can no longer be dropped by the owner's daily quota

**What this fixes, in the owner's terms.** Every owner-bound SMS shares a 20-a-day ceiling
(`OWNER_SMS_DAILY_QUOTA=20`, live on the authority). A security page went through the same ceiling, so after twenty
ordinary owner texts in a UTC day an intrusion page addressed to him was **refused** — while his wife and his mother,
who are not the owner number, still received theirs. The one person the page exists for was the one who could miss it,
and nothing said so: the caller got a suppression string, not an error.

**Why this shape.** The exemption mechanism already existed and was already security-only.
`send_message(bypass_owner_kill_switch=True)` is set by exactly one caller — `send_security_alert_mms`, the security-alert
path — and the flag's documented meaning is already *"an intrusion must page even while routine owner SMS are
switched off"*. The quota branch simply never tested it. So the change is one condition, not a new concept, and it
inherits a flag whose semantics were already reviewed and agreed.

**What was deliberately not done.**
- **No second sender.** The page still goes through `POST /webhook/ha/security-alert` →
  `send_security_alert_mms` → `send_message`. See `70-PAGING.md` §1c: a Python pager would have been the second one.
- **No change to the quota for anything else.** Ordinary autonomous owner texts still stop at 20. Only a caller that
  has already declared itself a life-safety page is exempt.
- **No change to the per-number 10/hour limit, the burst ceiling, or the dedupe.** Those are separate findings
  (`70-PAGING.md` §1b) and none of them was silently altered here.
- **No Home Assistant change.** This is entirely on the API side, which is where the ceiling lives.

**Evidence, gathered after the restart rather than asserted.**

| what | value |
|---|---|
| file mtime | `2026-10-27 22:41:14.883 UTC` |
| process start (`ActiveEnterTimestamp`) | `2026-10-27 22:41:20 UTC` |
| edited after the restart? | **no** — `find -newermt <start>` returned nothing, so the loaded code is the patched code |
| `GET /health` | **200 in 0.036 s** |
| `POST /webhook/ha/security-alert` with no key | **401** |
| `POST /webhook/ha/security-alert` with a wrong key | **401** |
| `py_compile` before restart | ok |
| backup | `app/sms_service.py.bak-quota-security-20261027T224114Z` (122,498 B), restored automatically if the restart had failed |

**How to roll back.** `cp -p app/sms_service.py.bak-quota-security-20261027T224114Z app/sms_service.py && systemctl
restart company-api.service`. The backup sits beside the file on the authority.

**What this does NOT prove.** No page has been sent. The quota branch was never exercised while over quota — that
would need twenty real owner texts in a day, or a unit test with a stubbed counter. So this is *"the condition now
tests the flag, the module compiles, the service serves, and the endpoint still refuses bad auth"*, not *"a page got
through while over quota"*. The remaining verification is the harness in `70-PAGING.md` §7, which sends nothing.

**A note for whoever edits `/opt/company` next.** That tree is a git checkout on
`keepalive/323-pickup-live-restore-20261021` at `7673b21f9` with **364 modified paths** — the deployment is what is on
disk, not what is in git. Do not `git checkout`, `git stash` or `git reset` there. Edit surgically, back up the file
first, and record the diff here.
