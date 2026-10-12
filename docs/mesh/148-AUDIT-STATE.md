# 148 — STATE ON DISK: login / session / profile / cookie / token audit

**Class hunted:** state a working system depends on that no health check watches — logins, sessions,
Chromium profiles, cookie jars, persisted tokens. These fail weeks later as "the site is asking me to
sign in again", or as a scraper silently returning nothing.

**Boxes**

| | office box (reference, READ-ONLY) | authority (live) |
|---|---|---|
| ssh | `secratary-ts` | `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` |
| app root | `/home/zabz/personal-secretary-mvp` | `/opt/company` |
| data dir | `/home/zabz/personal-secretary-mvp/data` | `/opt/company/data` |
| measured | 2026-10-11 15:40:44Z, load 0.00–0.18 | 2026-10-11 15:40:36Z, load 0.38 |

**Cutover:** 2026-10-11 05:43:36Z. Every "post-cutover" claim below is measured against that instant.

**Method and its limits.** Office box: metadata only (listings, `stat`, `sha256sum` of individual named
files). No recursive reads, no bulk hashing, load checked before and after every command — per
148's sibling rule that any multi-second office disk operation takes the company down. Authority: full
access. No secret or cookie *value* appears anywhere in this document — only names, sizes, mtimes and
truncated SHA-256 prefixes. Content identity is asserted only where two hashes were compared with each
other.

---

## §1 State inventory

Verdict key: **OK-USABLE** (present on the authority and exercised since cutover) · **OK-COPIED**
(present, byte-identical to the office copy, not yet exercised) · **STALE** (present but not written
since before the cutover) · **REGRESSION** (missing, partial, or destroyed) · **PRE-EXISTING** (absent
on *both* boxes — not a cutover miss).

### 1.1 Google Voice Chromium profiles — `data/google_voice_profiles/`

Read by `app/services/google_voice.py`; path from `app/config.py:649`
(`google_voice_profiles_dir = "data/google_voice_profiles"`).

| Path (relative to data dir) | Office mtime / size | Authority mtime / size | Verdict |
|---|---|---|---|
| `.../account_0/Default/Cookies` | 2026-10-11 00:28:41 / 20480 B · sha16 `e0a68e955df7b8d9` | **ABSENT** | **REGRESSION** — office only |
| `.../account_0/Default/Preferences` | 2026-10-11 00:28:41 / 20307 B | **ABSENT** | **REGRESSION** — office only |
| `.../account_0/Default/Login Data` | 2026-10-05 15:44:36 / 40960 B | **ABSENT** | **REGRESSION** — office only |
| `.../account_0/Local State` | 2026-10-11 00:28:41 / 4535 B | 2026-10-11 00:28:41 / 4535 B · same sha16 `ae02dcd8d5d856ef` | OK-COPIED (the only file of the four that moved) |
| `.../account_0/` (the directory) | 12 links (full profile) | **2 links (empty)** | **REGRESSION** |
| `.../account_1/Default/Cookies` | 2026-10-11 00:29:18 / 20480 B · sha16 `36b9b65bb6ae31c2` | present but **orphaned** at `account_1.broken-1791701529/Default/Cookies`, same sha16, mtime 00:29:18 | **REGRESSION** — the app itself archived it |
| `.../account_1/Default/Preferences` · `Login Data` | 20533 B / 40960 B | inside the same orphaned archive | **REGRESSION** |
| `.../account_1/` (live directory) | 13 links | **2 links (empty)** | **REGRESSION** |

The bytes for account_1 survive; the live path does not. The bytes for account_0 survive **nowhere on
the authority** — there is no `account_0*` directory with more than 3 links anywhere in the tree, and
the retention cap that would explain a deletion (`_GV_MAX_ARCHIVED_PROFILES_PER_KIND = 5`,
`google_voice.py:61`) has not been reached (exactly 5 empty `account_0.broken-*` shells exist).

### 1.2 Browser / Playwright profiles

| Path | Office | Authority | Read by | Verdict |
|---|---|---|---|---|
| `data/browser/seat_profile/Default/` | 2026-10-07 01:13, scaffold dirs only | identical (same mtimes, same entries) | `config.py:250` · `app/web_browser.py:245` · `app/chat_action_browser.py:87` | **PRE-EXISTING** — no Cookies, no Login Data, no Preferences on *either* box. Copied correctly; it never held a session. |
| `data/browser/sessions/` | empty | empty | `app/web_browser.py` | PRE-EXISTING (empty) |
| `data/browser_sessions/*.json` (4 files) | 9278 / 5838 / 11696 / 30 B, newest 2026-05-04 21:51 | identical names, sizes, mtimes | `app/services/browser_session.py` | **STALE** — untouched since May |
| `data/dialpad/chrome_profile/Default/Cookies` | 2026-10-07 03:55 / 20480 B · sha16 `c58a14bbef67a661` | identical, same sha16 | `app/services/dialpad_webcrawler.py` | **STALE** — cookie jar 4 days old at cutover, never refreshed |
| `data/dialpad/chrome_profile/Default/{Login Data,Preferences,Local State}` | 40960 / 19242 / 3580 B | identical | same | STALE |
| `data/dialpad/recording/` | 6110 files, listhash `cbd0df0213fe1b90` | same count, same listhash | Dialpad ingest | OK-COPIED (name+size fingerprint identical; not byte-hashed) |
| `data/dialpad/{voicemail,ui,ivr_audio}/` | 56 / 3 / 4 entries | same listhashes `630b602a…`, `ceaa16e2…`, `30dd46f8…` | Dialpad | OK-COPIED |
| **Chrome binary itself** | `/usr/bin/google-chrome`, `/opt/google/chrome` present | **no `google-chrome`, no `chromium`, no `chromium-browser`, no `/opt/google/chrome`, no `/root/.cache/ms-playwright`, no bundled Playwright browser anywhere on disk** | `app/web_browser.py:802` (channel `chrome`) | **REGRESSION** |

### 1.3 Google OAuth tokens

Read by `app/services/google_token_store.py`, `gmail_service.py`, `google_calendar.py`;
paths from `app/config.py:592,602`.

| Path | Office mtime / size | Authority mtime / size | Verdict |
|---|---|---|---|
| `data/calendar_tokens/` 5 files | 03:24:59 (4 files), 05:58:18 (`eliyahuzabrowsky…`) | **all five 2026-10-11 15:20:07**, sha16s all differ from office | **OK-USABLE — refreshed after cutover** |
| `data/gmail_tokens/` 5 files | same as above | **all five 15:20:07**, byte-identical to `calendar_tokens/` | **OK-USABLE — refreshed after cutover** |
| `data/google_calendar_credentials.json` | 2026-02-23 / 570 B · sha16 `f1a13e5ea69790e6` | identical sha16 | OK-COPIED (client secret; not rotated) |
| `data/copilot_auth.json` | 2026-08-29 / 560 B · sha16 `8dd27b9f3a271579` | **identical sha16, unchanged** | OK-COPIED but **never refreshed since 2026-08-29** |
| `data/token_archive/20260306_google_token_cleanup/` 17 files (7 retired account tokens + calendar tokens) | 2026-03-06, files 999–1034 B | **directory exists, EMPTY (0 entries)** | **REGRESSION** — archive only; no live code references `token_archive` |

The ten Gmail/Calendar token files were rewritten at 15:20:07Z — 9h37m after the cutover, with content
that matches nothing on the office box. That is a genuine post-cutover refresh, not a copied file with a
new mtime.

### 1.4 Identity / memory / session stores

| Path | Office | Authority | Read by | Verdict |
|---|---|---|---|---|
| `data/agent_identities.json` | 39,124,416 B @ 03:43 | 39,183,362 B @ **15:32:56** (plus `.bak`) | `config.py:930` | OK-USABLE (live, growing) |
| `data/neshama/` | 2 subdirs, 2026-10-06 15:32 | identical | `config.py:931` | OK-COPIED |
| `data/mem0/chroma.sqlite3` | 293,072,896 B @ 03:44 | 297,836,544 B @ **15:32:19** | `config.py:1177` | OK-USABLE (live) |
| `data/chromadb/` | 5 collections, 03:40 | 6 collections, **15:32:43** | `config.py:866` | OK-USABLE (live) |
| `data/*tokens*`, `data/identity*`, `data/*cookie*` | no such paths exist | no such paths exist | — | PRE-EXISTING (nothing to move) |

### 1.5 Action library, skills and media — data the DB rows point at

| Path | Office | Authority | Read by | Verdict |
|---|---|---|---|---|
| `data/tools/*.py` | **594 modules** | **3 modules** (`help.py`, `notification_dedupe_ledger.py`, `reminder_dispatch_ledger_enforcer.py`) | `app/tool_factory.py:34,504,686` · `app/chat_action_runtime.py:1427` → `chat_action_dynamic_tools._exec_dynamic_tool` → `tool_factory.run_tool` · `app/persistence_contract.py:775-783` | **REGRESSION** — see the app's own measurement below |
| `data/tool_registry.json` | 382,354 B @ 03:24 | 384,057 B @ **15:23** | `tool_factory._REGISTRY_PATH` | OK-USABLE (but describes tools that are not on disk) |
| `data/skills/*/SKILL.md` | 21 skill dirs (e.g. `gmail_oauth/SKILL.md` 1759 B) | **0 entries** | `app/skills_registry.py:20,63,98` (`_SKILLS_DIR.glob("*/SKILL.md")`) · `skills_importer.py:97` · `skills_to_tool.py` | **REGRESSION** |
| `data/skills_registry.json` | 9796 B @ Apr 10 | 9796 B @ Apr 10 | `skills_registry.py` | OK-COPIED |
| `data/sms_media/` | **6 MMS files** (5 written 2026-10-11 00:08–00:12, 1 on 2026-10-05) | **0 entries** | `twilio_mms_bridge.py`, `mms_media_bridge.py` | **REGRESSION** |
| `data/voice_recordings/` | 14 mp3 (Feb–Apr 2026) | 0 | voice services | **REGRESSION** (historical) |
| `data/voice_tts/` | 15 mp3 (Feb–Mar 2026) | 0 | voice services | **REGRESSION** (historical) |
| `data/voice_streams/` | empty | empty | — | PRE-EXISTING |
| `data/env-backups/` | 4 `.env*.bak` (19742–20501 B, Aug 30) | **1** (`.env.bak-20260830-evolution-on`) | ops scripts | **REGRESSION** — 3 credential-bearing `.env` backups office-only |
| `data/proposals/assistant-loop-v1.md` | 13576 B @ Feb 23 | 0 entries | — | REGRESSION (doc) |
| `data/specs/message-bus-v1.md` | 6162 B @ Feb 23 | 0 entries | — | REGRESSION (doc) |
| `data/waze-mdm/wallpapers/` | 1 subdir, 2026-06-29 | 0 entries | — | REGRESSION (static) |
| `data/sms_inbox_spool/` | empty | empty | Twilio ingest | PRE-EXISTING (empty) |

### 1.6 Credentials outside the data dir

| Path | Office | Authority | Verdict |
|---|---|---|---|
| `~/.git-credentials` | 149 B, 2 entries (`x-access-token` GitHub + one org), mtime 2026-10-11 06:22 | **ABSENT**; `/root/.gitconfig` (33 B) has no `credential.helper` | **REGRESSION** (latent — see §3) |
| `~/.netrc`, `~/.config/git/` | absent | absent | PRE-EXISTING |
| `~/.ssh/id_rsa_linux_pc` | present, referenced in `~/.ssh/config` | **ABSENT** | **REGRESSION** |
| `~/.ssh/id_ed25519_mesh` | present | **ABSENT** | **REGRESSION** |
| `~/.ssh/id_ed25519_lpt-apps` | present | **ABSENT** | **REGRESSION** |
| `~/.ssh/ha-mesh-key` | present | **ABSENT** | **REGRESSION** |
| `~/.ssh/config` `IdentityFile` directives | 5 declared, **all 5 files present** | **0 declared** — the authority's config names no `IdentityFile` at all | **REGRESSION** |
| `LINUX_PC_SSH_KEY_PATH` (`.env:4`) | `~/.ssh/id_rsa_linux_pc` → resolves | `/home/zabz/.ssh/id_rsa_linux_pc` → **path does not exist** | **REGRESSION** |
| `QB_AGENT_REPO_PATH` (`.env:339`) | `/home/zabz/repos/quickbooks-agent` → exists | `/home/zabz/repos/quickbooks-agent` → **absent** | **REGRESSION** |
| `quickbooks-agent` repo (3 candidate paths) | all 3 exist (`/home/zabz/quickbooks-agent`, `/home/zabz/repos/…`, `…/domains/finance/…`) | **all 3 absent** (whole-filesystem search, depth 5, found nothing) | **REGRESSION** |
| `/opt/company/.env` | — | 24,199 B @ 2026-10-11 01:18 (pre-cutover), `DATABASE_URL=sqlite:////root/authority.db` | OK (single writer confirmed) |

**Measured by the application itself**, run in the authority's own venv against its own settings
(`build_persistence_drift_report(settings)`, 2026-10-11 ~15:50Z):

```
{"key": "dynamic_tools", "ok": false, "issue_count": 600,
 "registry_entry_count": 603, "tracked_file_count": 603, "disk_file_count": 3}
missing_on_disk: 600  ['__list_actions__.py', 'action_health_monitor.py',
                       'active_conversation_auto_reply_suppressor.py', ...]
```

The company's own contract checker calls this drift. 600 of 603 registered actions have no
implementation file on the authority. Note the nuance: tool *creation* still works (3 new tools were
written after the cutover — `help.py` 08:34, `notification_dedupe_ledger.py` 10:31,
`reminder_dispatch_ledger_enforcer.py` 12:20). It is the pre-existing library that is gone.

---

## §2 REGRESSIONS

### R1 — Google Voice sign-in state is destroyed on the authority; account 0's copy exists only on the office box
**What is wrong.** Two failures stacked. (a) The authority has **no Chrome binary and no Playwright
browser payload**, so every `launch_persistent_context` fails. (b) `app/services/google_voice.py`
treats a *launch* failure as a *broken profile*: `_repair_profile_from_auth_state` (line ~518) renames
the profile to `account_N.broken-<epoch>`, rebuilds it from "minimal auth state" (Local State plus
`.gv_internal_auth.json`), and `_restore`/`legacy-reset` (line ~581) does the same under a second name.
So the missing browser **destroys the session state it was supposed to reuse**.

Verbatim from `journalctl -u company-api` on the authority:
`GV --headless=new launch failed for account 0 (BrowserType.launch_persistent_context: Chromium distribution 'chrome' is not found at /opt/google/chrome/chrome` … `Rebuilt GV profile …/account_0 from minimal auth state; archived original at …/account_0.broken-1791730965`.

The loop is still running: quarantine/recreate cycles at 06:52, 08:14, 08:15, 13:13, 14:18, 15:02 —
46 paths under `google_voice_profiles/` written after the cutover. Both live profiles are now empty
2-link shells.

**What breaks.** Google Voice: no profile means the sign-in page, which means SMS send/receive, call
placement and voicemail through Voice. account_1's cookie jar still exists as
`account_1.broken-1791701529/Default/Cookies` (sha16 matches the office original), so account 1 is
recoverable by putting the archive back and giving the box a browser. **account 0 is not recoverable
from the authority** — its `Cookies` (20480 B, sha16 `e0a68e955df7b8d9`), `Preferences` and
`Login Data` exist only on the frozen office box.

**When it surfaces.** It is already surfaced — broken since roughly 06:52Z, 9 hours before this audit.
Every ~45 min it destroys one more generation and logs a warning nobody reads.

### R2 — Every browser-driven integration is dead on the authority
**What is wrong.** No `/usr/bin/google-chrome`, no `chromium`, no `/opt/google/chrome`, no
`/root/.cache/ms-playwright`, and a depth-6 whole-filesystem search finds no `chrome-linux`,
`headless_shell` or `chrome-headless-shell` payload. Playwright 1.54.0 is installed in the venv; its
browsers are not. `app/web_browser.py:802` requests `channel: "chrome"` and `BROWSER_CHANNEL` is set in
`.env:51`; the office box satisfies both, the authority satisfies neither.
**What breaks.** Google Voice (R1), the Dialpad UI crawl (`dialpad_webcrawler.py` — a stale 2026-10-07
cookie jar behind a browser that cannot launch), `browser_vision.py`, `cua_agent.py`,
`workspace_search.py`, `mcp_manager.py`, `self_healing_monitor.py`, `portable_workspace.py`, and the
seat-profile browsing in `web_browser.py`. All Playwright-based bank scrapers.
**When it surfaces.** Now. Silent in every case: the failure is an exception inside a service, so the
caller sees an empty result, not an outage. R1 is the only one loud enough to reach a log.

### R3 — 600 of 603 dynamic actions have no implementation on the authority
**What is wrong.** `data/tools/` holds 3 `.py` files where the office held 594. The registry moved
intact (603 entries, every one naming `data/tools/<name>.py`). The running app's own contract checker
reports `ok: false, issue_count: 600`.
**What breaks.** `chat_action_runtime.py:1427` routes any action not handled inline to
`_exec_dynamic_tool` → `tool_factory.run_tool`, which loads `data/tools/<name>.py`. With the file gone
the action cannot run. The missing set includes the whole autopilot's working library:
`action_health_monitor`, `active_conversation_auto_reply_suppressor`, `unified_reminder_deduplicator`,
`owner_reply_dedup_guard`, `confidential_topic_guard`, `mms_media_bridge`,
`owner_charge_context_resolver`, `data_feed_freshness_monitor`, `dhl_fleet_health_diagnostic`, and
`__list_actions__` itself.
**When it surfaces.** The first time each action is invoked — for the in-process autopilot
(`AUTOPILOT_INTERVAL_SEC=900`) that is today, one action at a time. The initial symptom is not an
error: it is a guard that stops guarding. I measured the file/registry drift and the app's own verdict;
I did **not** capture a live action failure, because invoking production actions risks outbound side
effects.

### R4 — The QuickBooks/bank scraper repo and its Playwright sessions are absent
**What is wrong.** `QB_AGENT_REPO_PATH=/home/zabz/repos/quickbooks-agent` (`.env:339`) does not exist on
the authority, nor does `_DEFAULT_QB_REPO` (`<repo>/domains/finance/quickbooks-agent`,
`app/services/{boa,chase,amex,amazon,ebay}_bank_service.py:47-49`), nor `/home/zabz/quickbooks-agent`.
A depth-5 filesystem search finds no `quickbooks-agent` directory at all. All three paths exist on the
office box.
**What breaks.** The purchase and bank feeds — BoA, Chase, Amex, Amazon, eBay, PayPal. These services
wrap Playwright scrapers that live in that repo and keep their login state beside it. The services
return `quickbooks-agent repo not found at <path>` and an empty result, which is exactly the
"scraper silently returning nothing" failure this audit was commissioned to find.
**When it surfaces.** At the next statement/reconciliation cycle (the recurring charge and card
attribution jobs consume this data). Silent: an empty feed reads as "no transactions".

### R5 — The authority cannot reach two of the four worker nodes
**What is wrong.** Measured from the authority with its default key (`/root/.ssh/id_ed25519`,
`BatchMode=yes`, 8 s timeout):

| target | result |
|---|---|
| `zabz-tech` | **reachable** (returns `zabz-tech`) |
| `linux-pc-ts` | **reachable** (returns `zabz-tech-linux`) |
| `secratary-ts` | **reachable** (returns `secratary`) |
| `zabz-yoga-1` | **Permission denied (publickey,password,keyboard-interactive)** |
| `mac-mini-ts` | **Permission denied (publickey,password,keyboard-interactive)** |

The office `~/.ssh/config` declared 5 `IdentityFile`s, all present. The authority's config declares
none, and the four mesh keys that carried the fleet (`id_ed25519_mesh`, `id_ed25519_lpt-apps`,
`id_rsa_linux_pc`, `ha-mesh-key`) do not exist on it.
**What breaks.** Any authority-side job that pushes to or pulls from the Yoga laptop or the Mac mini:
the transcript/session archive pull for those two machines, and anything that reaches Home Assistant
through `ha-mesh-key`. The Yoga laptop is where the owner works at night.
**When it surfaces.** At the next hourly archive pull, as SILENCE (exit 2) rather than GAP — which
per the archive's own design means "cannot be judged from here", i.e. it will not raise an alarm.

### R6 — 21 installed skills are gone
**What is wrong.** `data/skills/` is empty on the authority (0 entries); the office holds 21 skill
directories each with a `SKILL.md`. `app/skills_registry.py:98` builds the installed-skill list by
globbing `data/skills/*/SKILL.md`, so the list is now empty while `data/skills_registry.json` still
advertises the 21.
**What breaks.** `list_skills` returns nothing; `skills_to_tool.py` (which compiles a skill into a
dynamic tool) has no input; anything that resolves an OpenClaw-style skill by key fails.
**When it surfaces.** The first time a skill is listed or invoked.

### R7 — The database references media files that are not there
**What is wrong.** `data/sms_media/` is empty on the authority; 6 MMS files sit on the office box,
**5 of them written between 2026-10-11 00:08 and 00:12** — minutes before the freeze. `data/voice_recordings/`
(14 mp3) and `data/voice_tts/` (15 mp3) are likewise empty versus populated.
**What breaks.** The database moved whole, so the rows referencing these files are on the authority
while the bytes are not. An MMS row resolves to a missing file: the thread shows the message, the photo
does not load. The unverified part is the row-level link — see §3.
**When it surfaces.** When someone opens one of those MMS threads — i.e. on the first customer or
family message whose picture matters.

### R8 — Recovery material that quietly did not move
`data/token_archive/` is empty (17 retired account tokens, 7 accounts, including
`abletelsolutions@`, `yadmichoel@`, `ezshidduch1@`); 3 of 4 `data/env-backups/*.env.bak` are
office-only; `~/.git-credentials` is absent. None of these break anything today and none have live code
reading them — `token_archive` is matched by **no** file under `/opt/company`. They matter only at the
moment of a recovery, which is the worst moment to find them missing. **When it surfaces:** on the
first revoked token, the first need to re-consent an account at its historical scope, or the first
HTTPS git operation on the authority.

### R9 — Stale-but-present session state that will read as "signed out" later
`data/dialpad/chrome_profile/Default/Cookies` (2026-10-07 03:55) and `data/browser_sessions/*.json`
(2026-05-04) came across intact and identical, but neither has been written since well before the
cutover. `data/browser/seat_profile/Default/` holds **no** cookie jar on either box — it is a scaffold
(Extension Rules/Scripts/State, Local Storage, Session Storage, Site Characteristics Database, Sync
Data, shared_proto_db) with no `Cookies`, `Login Data` or `Preferences` — so this is a pre-existing
condition, not a cutover miss. **When it surfaces:** the first integration that actually needs a
logged-in seat will ask for a sign-in, and the honest reading then is "it was never signed in", not
"the migration lost it".

### R10 — Not a state miss, but the same shape: a second live SQLite
`data/secretary.db` (1,826,816 B, **145 tables**, `-shm` touched 2026-10-11 15:35Z) exists on the
authority as an empty stub on the office (43,683 B). `DATABASE_URL=sqlite:////root/authority.db`, so
this is not the configured authority. It is reachable through literal defaults that bypass settings —
`app/services/drn_reliability_api.py:1983,2180` (`db_path: str = "data/secretary.db"`) and
`chat_action_runtime.py:2590,2655` (`getattr(settings, "database_url", "data/secretary.db")`). I did
not identify which caller is writing it. Flagged only because two live SQLites on one host is
split-brain state, and because a state audit that stays silent about it is not doing its job.

---

## §3 What I could not determine

1. **Why `account_0` transferred only 1 of its 4 files.** `Local State` moved; `Cookies`,
   `Preferences` and `Login Data` did not, and no `account_0*` directory with content exists anywhere on
   the authority — not at the live path, not in any `.broken-*` or `.legacy-reset-*` archive. The
   retention cap (5) has not been reached, so pruning does not explain it. Whether this was a partial
   copy, a permissions skip, or an in-place rebuild that discarded the files, I cannot say. **Cause
   UNKNOWN; the absence itself is certain.**
2. **Whether the office-only Google Voice session for account 0 is still valid.** Its cookie jar was
   last written 2026-10-11 00:28Z. I did not attempt a sign-in (that is an outbound action against
   Google, and a login attempt on a stale session can itself invalidate it).
3. **Whether `copilot_auth.json` is still valid.** Byte-identical on both boxes, unchanged since
   2026-08-29, no refresh observed anywhere. Present ≠ working.
4. **Whether the missing `~/.git-credentials` breaks anything today.** No measured breakage: the
   authority's only git checkout, `/root/code/harness-config`, has a local bundle as `origin` and an
   ssh remote `vault`, so nothing on the authority currently needs an HTTPS credential. Latent, not
   active.
5. **Byte-level completeness of the large media stores.** `data/dialpad/recording` (6110 files),
   `voicemail`, `ui` and `ivr_audio` were verified by an identical list fingerprint (names + sizes
   hashed together, `cbd0df0213fe1b90` etc.) — **not** by content hashing every file. Identical
   fingerprints do not exclude a same-size, different-content substitution.
6. **Whether all 600 missing tools were live.** I measured file/registry drift and the app's own
   `issue_count: 600` (measured against the deployed code, not my reading of it). I did not
   establish which of those actions the autopilot actually called during the last 24 hours on the office
   box — so "600 broken actions" overstates it slightly; "600 registered actions with no implementation,
   some of which were certainly in use" is what is proven.
7. **The row-level consequences for R7.** That the SMS/voice DB rows reference the missing media is
   inferred from how the bridges write files, not measured — verifying it needs a `LIKE` scan of the
   23.6 GB authority database, which I declined to run against a live writer.
8. **`data/secretary.db`'s writer** (R10) — 145 tables, live `-shm`, not the configured authority DB.
9. **The office box was not bulk-read.** Per its standing rule, every office number here is metadata
   only (listings, `stat`, and `sha256sum` of individual named files). I did not verify the office's own
   internal consistency.
10. **`data/neshama`, `data/mem0`, `data/chromadb`** were checked for existence, mtime and freshness —
    all three are live on the authority — but not for the logical completeness of individual records.
11. **Whether the authority's `id_ed25519` is authorized elsewhere.** I measured which workers answer
    and which refuse (R5). I did not enumerate the other direction — which keys on the workers still
    trust the authority.

---

## Provenance

| Reading | Where it came from |
|---|---|
| Office metadata | `ssh secratary-ts` — `ls`/`stat`/`find -maxdepth`, `sha256sum` of named files only; load 0.00–0.18 before and after |
| Authority metadata | `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` — full access |
| Chrome failure | `journalctl -u company-api --since "2026-10-11 05:43"` on the authority, lines timestamped 15:02:44–15:02:48Z |
| Tool drift | `build_persistence_drift_report(settings)` executed in `/opt/company/.venv` on the authority, 2026-10-11 ~15:50Z |
| Worker reachability | `ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=8 <host> hostname` from the authority, ~15:55Z |
| Code references | `grep -rn` over `/opt/company` (`--exclude-dir=.venv`), 2026-10-11 15:40–15:55Z |

Written 2026-10-11. Office box read-only throughout; nothing on either machine was modified.
