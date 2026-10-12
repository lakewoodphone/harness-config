# 164 — The frozen office box's last non-unit writer, and the config layers that still face the old world

Session: mesh child on host `zabz-tech` (Windows), thread remote-b6402599-b3f5-4717-b579-af932343142c.
All times UTC unless marked local. Every claim below carries the command that produced it.

## 1. WHAT pid 373763 IS, AND WHO OWNS IT

```
$ ps -o pid,ppid,lstart,stat,user,args -p 373763      # on secratary (ssh secratary-ts)
373763 373762 Sun Oct 11 20:53:20 2026  Ssl  zabz
  /home/zabz/personal-secretary-mvp/.venv/bin/python
  /home/zabz/personal-secretary-mvp/scripts/ps_mcp_server.py
```
- cwd `/home/zabz`; fd 0/1/2 are pipes to its sshd session; started 20:53:20Z.
- Parent chain: `373763` -> `373762 sshd-session: zabz@notty` -> `373715 sshd-session: zabz [priv]` -> sshd listener.
- `SSH_CONNECTION=100.85.153.96 7960 100.84.72.88 22`; `tailscale status` -> `100.85.153.96  zabz-tech` (windows). Self tailnet ip `100.84.72.88` = `secratary`.

So it is an **MCP stdio bridge over ssh**: a `ps_mcp_server.py` spoken to over the ssh channel.
The client end, on zabz-tech:
```
$ Get-CimInstance Win32_Process -Filter "Name='ssh.exe'"
PID=39856 PPID=31380 START=10/11/2026 16:53:19
  ssh -T -o BatchMode=yes ... secretary-ts
    /home/zabz/personal-secretary-mvp/.venv/bin/python
    /home/zabz/personal-secretary-mvp/scripts/ps_mcp_server.py
PID=31380  node.exe  C:\Users\ezabz\.dsh\engine\...\dsh\lib\bin.js web --port 3099 --no-open
  START=10/11/2026 14:28:27
```
**CONCLUSION: it is NOT an abandoned session.** The owner is a live DSH engine
(PID 31380) on zabz-tech; the TCP session is still ESTABLISHED
(`sudo ss -tnp state established '( sport = :22 )'` -> `100.84.72.88:22  100.85.153.96:7960
users:(("sshd-session",pid=373762,fd=9))`). Killing it as "stray" is therefore NOT
the sanctioned action. It is a live agent's tool server.

It is also **not this session's** bridge. Measured with this session's own MCP tool:
```
ps_db_query("SELECT * FROM pragma_database_list()")
-> {"seq":0,"name":"main","file":"/root/authority.db"}
```
This session reads the authority. The office-box bridge belongs to a *different, older*
session in the same engine.

## 2. THE ROUTING ANSWER: NO, AND THE SCRIPT ITSELF WAS THE OLD WORLD

Office copy, measured:
```
$ md5sum /home/zabz/personal-secretary-mvp/scripts/ps_mcp_server.py
b865698f1232ddb07e001b3bbb882d8d
$ stat -c 'mtime=%y size=%s' ...
mtime=2026-10-08 02:31:11 +0000 size=34994      # git HEAD 26678993
$ sed -n '65p' ...
DB_PATH = ROOT / "data" / "secretary.db"
```
`ROOT = Path(__file__).parent.parent` (line 36) -> `/home/zabz/personal-secretary-mvp/data/secretary.db`
= **23,691,915,264 B, mtime 2026-10-11 22:33:19Z, inode 4724729**. Hardcoded: env is not consulted,
and the office `.env` declares none of `DATABASE_URL` / `SECRETARY_DB` / `PS_SECRETARY_DB`
(grep of key names only). There is no config on that box that could redirect it.

**The cloud copy is already fixed, and says so in its own comment:**
```
/opt/company/scripts/ps_mcp_server.py
# The store is a DEPLOYMENT fact, not a repo fact. ... Measured 2026-10-11 on secratary-cloud:
# resolving ROOT/data/secretary.db there found a 1.8 MB file last written 2026-10-11T01:18Z
# - a stale leftover - while the live authority store was /root/authority.db at 23.9 GB ...
def _resolve_db_path() -> Path:      # SECRETARY_DB/PS_SECRETARY_DB -> sqlite DATABASE_URL -> local default
DB_PATH = _resolve_db_path()         # line 92
```
So the office box runs a **pre-fix checkout of the same script**. Same class as the rest of the
migration: a path still facing the old world. (And the fixed resolver would NOT save the office box
either — with no `SECRETARY_DB` and no `DATABASE_URL` there, it still resolves to the local file.)

## 3. THE MULTI-MACHINE CHECK (the more valuable finding)

Every `ps_mcp_server.py` on zabz-tech, from the same `ssh.exe` listing:

| local ssh pid | target host | script |
|---|---|---|
| 39856 | **secretary-ts** | `/home/zabz/personal-secretary-mvp/scripts/ps_mcp_server.py` |
| 42440, 41884, 36432, 10164 | secratary-cloud | `/opt/company/scripts/ps_mcp_server.py` |

**Exactly one of five points at the frozen box.** The live composition rows on zabz-tech now all
say `secratary-cloud` / `/opt/company/...`:
`~/.dsh/profiles/web/cordis.patch.yml` and `~/.dsh/profiles/headless/cordis.patch.yml:63-65`
(win32 row) and `~/.dsh/.agent-presets/zabz/agent.cordis.yml:588-611` (edited 20:12:15Z) and
`.agent-presets/yocheved/agent.cordis.yml:489`.

**Why a stale spawn still happened at 20:53:20Z: the engine is older than the fix.**
Engine PID 31380 started **18:28:27Z**; the presets were corrected at **20:12:15Z** and the live
headless row at **20:44:43Z**. Engine 31380 therefore holds a **pre-fix composition generation in
memory** and spawned the office-box bridge from that stale row. The on-disk cause is fixed; the
running process is the generation that preceded the fix.

## 4. THE LAST LIVE CONFIG PATH THAT STILL FACES THE OLD WORLD

`~/.dsh/profiles/headless/cordis.patch.yml` — the live `headless` profile, which is **the profile every
mesh subagent runs**:
```
69:    - id: mcp-secretary-linux
71:      disabled: !!js process.platform !== 'linux'
75:        command: /home/zabz/personal-secretary-mvp/.venv/bin/python
77:          - /home/zabz/personal-secretary-mvp/scripts/ps_mcp_server.py
```
The win32 row above it (lines 30-67) was retargeted to `secratary-cloud` + `/opt/company/...`. The
**linux row was not**. Its gate is "am I Linux", not "am I the authority" — so on the *frozen office
box* (Linux, and where `secratary-ts` lands) it resolves to a real file and opens the frozen box's
local store. On the cloud authority the same path does not exist, so the bridge fails silently
(`failOnStartupError: false`) and headless children get no `ps_*` tools.

## 5. WHAT I CHANGED — CONFIG ONLY. NO DB, NO UNIT, NO CRON, NO GUARD.

**5a. zabz-tech — the LIVE `headless` profile (the profile every mesh subagent runs).**
`~/.dsh/profiles/headless/cordis.patch.yml`, `mcp-secretary-linux`:
`/home/zabz/personal-secretary-mvp/.venv/bin/python` + `.../scripts/ps_mcp_server.py`
-> `/opt/company/.venv/bin/python` + `/opt/company/scripts/ps_mcp_server.py`.
Backup: `~/.dsh/profiles/headless/cordis.patch.yml.bak-office-row-20261011T2245Z`
(sha256 both `817397E7C6C85E43EB50C1AFEA74030846C520C3415F86E3255C74B0BB7E2449`).
`ls -ld /opt/company` on `secratary` -> *No such file or directory*, so on the frozen box this
row now **fails closed** instead of opening the local store; on the cloud it becomes the cloud's
own bridge, which it never was.

**5b. The frozen box's OWN two live profiles — its bridge rows are now disabled.**
This was not known before this session: the office box carries its own copies and they still
named its own store.
- `/home/zabz/.dsh/profiles/headless/cordis.patch.yml` — `mcp-secretary` (line 36) and
  `mcp-secretary-linux` (line 63) now `disabled: true`.
- `/home/zabz/.dsh/profiles/web/cordis.patch.yml` — `mcp-secretary` (1439, 2465) and
  `mcp-secretary-linux` (2495) now `disabled: true`.
Backups: each file pre-copied to `<same path>.bak-office-bridge-disabled-20261011T2248Z`.
Both files re-parsed as valid YAML after the edit (`yaml.load` with a loader that tolerates the
`!!js` tag): `OK ... (top-level list)`.

**5c. The frozen box's copy of the bridge itself now refuses to serve.**
`/home/zabz/personal-secretary-mvp/scripts/ps_mcp_server.py` — the hardcoded
`DB_PATH = ROOT / "data" / "secretary.db` replaced with the authority's `_resolve_db_path()`
(`SECRETARY_DB`/`PS_SECRETARY_DB` -> sqlite `DATABASE_URL` -> **refuse**), i.e. the same shape the
authority's copy already carries, except that on this host the unnamed default is a hard refusal
rather than a silent fallback. Backup:
`scripts/ps_mcp_server.py.bak-office-frozen-20261011T2250Z` (34994 B, md5 `b865698f1232ddb07e001b3bbb882d8d`
= the original). New md5 `0103817f32257b4e5e2e43b2f73ec326`. `py_compile` -> COMPILES OK.
Behaviour test (bounded, DEVNULL stdin):
```
exit_code= 78
stderr= REFUSED: this is the FROZEN office box and no store is declared. ... /root/authority.db
stdout_bytes= 0
```
Exit 78 is EX_CONFIG and stdout is empty, so there is no JSON-RPC surface at all.

## 6. VERIFICATION (all measured after the changes, on `secratary`)

```
secretary-api          enabled=masked     active=inactive
dialpad-sms-ws         enabled=masked     active=inactive
secretary-dashboard    enabled=masked     active=inactive
phone-engine           enabled=masked     active=inactive
cron                   enabled=masked     active=inactive     <- untouched by me
cloudflared            enabled=disabled   active=inactive
```
Scan of every `/proc/<pid>/fd` for targets matching `*.db`, `*.db-wal`, `*.db-shm`:
`NONE (no zabz-owned process holds any database file open)`.
The only company process left on the box is `373763 ps_mcp_server.py` — a bridge, not a unit.
Local store unchanged since before this session: `size=23691915264 mtime=2026-10-11 22:33:19.091004233
inode=4724729` at `now=2026-10-11T22:45:54Z` — i.e. **no write in the 12.5 minutes measured**.
**Frozen anchor identical**: `size=23622823936 mtime=2026-10-11 04:27:31.355878968 inode=8694592`
— same size, same mtime, same inode as at the start of this session and as the previous child
recorded.

## 7. THE ONE REMAINING RECURRENCE RISK — AND L3511 WAS WRONG ABOUT THE WEB LAYER

Journal `L3511` checked the layers and concluded all were correct except the live `headless` one.
That is not what is on disk for `web`. Still stale, in the MANAGED REPO:
- `harness-config/profiles/web/cordis.patch.yml` — line **1515** `secretary-ts`, **1516-1517**
  `/home/zabz/personal-secretary-mvp/...`, gated `win32` and NOT commented out (a live row in an
  active sequence); also line **962-964**. Committed (not in `git status`).
- `harness-config/profiles/web/presets.generated.patch.yml` — line **862-864**.
- `harness-config/journal/presets/{zabz,yocheved}/agent.cordis.yml` — lines 529-552 / 466-468
  (the journal's own stale mirror).
The source preset `harness-config/presets/zabz/agent.cordis.yml` **is** correct (line 609), and the
live `~/.dsh/profiles/web/cordis.patch.yml` is correct (its `mcp-secretary` at 2465 names
`secratary-cloud`). So the risk is specifically: **re-applying the repo's `profiles/web/*` to the
live profile re-introduces `secretary-ts`.** I did NOT hand-edit those two, because they are
generated/committed artifacts and rewriting a generated file by hand is a new drift of its own.
Fix belongs in whatever regenerates them.

## 8. WHAT I DID NOT DO, AND WHY

- **I did not kill pid 373763, and I did not kill its ssh client.** Measured owner: local
  `ssh.exe` PID 39856, parent `node.exe` PID 31380 (`dsh ... web --port 3099`) — still alive at
  22:52Z, alongside four sibling mesh dispatches and this session's own cloud bridge (PID 42440).
  The TCP session is still ESTABLISHED. That is a **live agent's tool server, not an abandoned
  session**, which is the case the task reserves for `sudo -n kill`. It is, however, a bridge of a
  **superseded composition generation** — the row it came from no longer exists in any live config
  — so it disappears when engine 31380 restarts; it is read-only in the meantime and has written
  nothing in the window measured.
- Not touched: the frozen anchor, the four masked units, `cron`, the service-state guard, the
  cloud's `company-api`/`cloudflared`/`secretary-dashboard`/`phone-redirector`. No database,
  `-wal`, `-shm` or backup was deleted, overwritten or moved.
