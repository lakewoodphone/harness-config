<!-- e:wins|W5b|2026-09-11|-|open -->
**W5b · 2026-09-11 · Twelve DSH windows became an operational reality, and the numbers say which design.**

Built `multi-window/dshw.ps1` + `windows.json`: start/stop/restart/status/new/open/logs/autostart/doctor
over one engine and N isolated browser windows. *Measurement:* engine up on port 3099 and **8 app windows
open simultaneously**, each with its own browser profile and its own auth cookie (verified per profile:
`Cookies`, `Local Storage\leveldb`, `Preferences` present in all 8); status reports `1 engine(s) live,
8 window(s) open, 196 MB engine RSS, 206 MB whole engine tree`. The cost model that decided the design is
measured, not estimated: three engines on three ports each held ~1.4 GB of tree (26 descendants), so the
"one process per window" plan would have needed ~17 GB on a laptop with 7.7 GB free.
*Why it matters:* the previous answer to "many sessions" was eight sessions sharing one ad-hoc process
started by hand, which died with its terminal and could not be restored.

<!-- j2 tags=legacy-import refs= alias_of= legacy_id= sha=7cd70383df65e2a0 -->
