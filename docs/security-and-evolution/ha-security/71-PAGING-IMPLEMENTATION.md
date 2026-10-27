# 71 — Paging: state of the build, and the exact live locations that remain

**Updated 2026-10-27 22:4xZ.** The contract and the reasoning are in `70-PAGING.md`; this file is only what is done and
what is left, with the locations already located so nobody re-reads 122 KB of `sms_service.py` to find them again.

## Applied and verified on the authority

### 1. A security page can no longer be dropped by the owner's daily quota — DONE 2026-10-27 22:41Z

`/opt/company/app/sms_service.py`, live line **1867**. The quota condition now also tests
`bypass_owner_kill_switch` — the flag only the security-alert path sets, already documented as *"an intrusion must page
even while routine owner SMS are switched off"*. Before the change, after twenty owner sends in a UTC day, a page
addressed to the owner was refused while the extra recipients still received theirs.

| evidence | value |
|---|---|
| file mtime | `2026-10-27 22:41:14.883 UTC` |
| process start | `2026-10-27 22:41:20 UTC` |
| edited after the restart | no — `find -newermt <start>` returned nothing |
| `GET /health` | `200 in 0.036 s` |
| `POST /webhook/ha/security-alert`, no key | `401` |
| same, wrong key | `401` |
| `py_compile` | ok |
| backup | `app/sms_service.py.bak-quota-security-20261027T224114Z` (122,498 B) |

Patch and rationale: `patches/2026-10-27-quota-exemption/`. Rollback: copy the backup back and restart
`company-api.service`.

**What it does not prove:** no page was sent, and the branch was never exercised *while over quota*. It proves the
condition tests the flag, the module compiles, the service serves, and auth still refuses.

## Remaining

| # | fix | live location | note |
|---|---|---|---|
| 1 | **The picture has never travelled** | HA `phoenix_intrusion_evidence.yaml`, `shell_command.phoenix_verify_evidence_files` | a bare `for … done` is `exec`'d, not shell'd (`[Errno 2] … 'for'`). Needs a **file** write into `/config`; this machine has no route (only 8123 answers). **Blocked on the Samba/SSH add-on or a paste.** |
| 2 | **Retry amplification** | `app/sms_service.py` `send_security_alert_mms`, live **2967**; the arithmetic that decides `ok` is at its end, **past line 3031 — read the whole function before patching** | `ok` must mean *the owner got it*. HA retries on `ok == false` up to four more times, so a pessimistic `ok` re-pages everyone who already received it |
| 4 | **`paged` is hardcoded** | `app/main.py:9046` `"paged": true`, `:9048` `"media_ok": true` | HA gates on `ok`, so `ok` matters more than `paged`; both should stop lying |
| 5 | **No page identifier** | handler around `app/main.py:9133`; the payload already carries `avs_level` | mint an id, return it, accept it on cancel |
| 6 | **Nothing writes `security_action`** | writer belongs beside the send; table lives in `/root/authority.db` | one row per attempt so `security-digest` stops reporting zero pages |
| 7 | **Declared shop state** | `security-sentinel.py:260` | replace the 600-second presence latch, or level 3 stays unreachable while family sleep downstairs |

## Facts that save the next session a day

- **`/opt/company` is the deployment and it is not the repo.** Branch `keepalive/323-pickup-live-restore-20261021` at
  `7673b21f9`, **364 modified paths**. `sms_service.py` is 122,498 B there and 79,373 B in the repo. Never
  `git checkout`/`stash`/`reset` in it. Edit surgically, `cp -p` a timestamped backup first, `py_compile`, restart,
  and verify by **file mtime < process start** plus `/health`.
- **The service is `company-api.service`**, `uvicorn app.main:app --host 127.0.0.1 --port 8002`. It binds in about two
  seconds, but probing immediately after `restart` returns `000` — wait for `ss -lnt | grep 127.0.0.1:8002`.
- **Send a script over ssh as `tr -d '\r' | bash -s`.** A PowerShell here-string arrives with CRLF and bash then reads
  `app/sms_service.py\r`, which fails as a missing file.
- **`avs_level` is already in HA's payload and the handler ignores it.** That is the whole of the priority work on the
  wire; no Home Assistant file change is needed to honour it.
- **A level-3 decision is stored as `decision='ESCALATE'`, never `'ALARM'`.** Anything keyed on `ALARM` misses every
  level-3 event.
- **`send_owner_update` (the pager) is the wrong transport for a page:** `owner_sms_min_urgency` defaults to `urgent`
  and is unset live, `send_message` overwrites urgency to `normal` at its own gate, and a 20-minute rate floor plus a
  30-minute body dedupe would hold or swallow pages.
- **The kill switch is not in play:** `/opt/company/data/OWNER_SMS_KILL_SWITCH` and `/root/data/…` are both absent.

## The verification that still has to happen

In order, and the last one needs the owner's word on the exact body:

1. a harness that composes a page from a real `security_decision` row and asserts the routing decision **without
   sending**;
2. a `security_action` row written for that attempt;
3. **one real page**, body shown to the owner and approved first, then sent, and confirmed by him receiving it.
