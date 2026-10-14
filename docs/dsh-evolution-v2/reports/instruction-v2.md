HOST: zabz-tech-linux

# 10 — The instruction and identity surface, audited (round 2)

**Prepared:** 2026-10-14T01:00–01:30Z · **Ran on:** `zabz-tech-linux` (Linux `6.8.0-111-generic` x86_64,
user `zabz`) — **not** the Windows node `ZABZ-TECH` the node contract named. `bash`, `ssh`, `python3`
all worked here; no PowerShell was needed for the local half. All four estate-preset machines and the
authority were reachable over ssh and were read live.

**Method.** Every size below is a measured byte count with the command that produced it (see
`EVIDENCE LOG`). Every "landed / not landed" names the machine **and** the file it was read on. The
round-1 documents are not in any working tree; they were read from the only branch that contains them
(`remotes/zabz-yoga/main` on the authority's `harness-config`), and `docs/dsh-evolution-v2/PROGRAM.md`
was read from ZABZ-YOGA where it exists untracked.

> **A note on the round-1 reference set.** The task said to read
> `docs/dsh-evolution/{10-instruction-surface-audit,05-instruction-redesign,08-changes-made}.md`,
> `docs/dsh-evolution-v2/PROGRAM.md`, and `AGENTS.md`. On the live working trees, **only
> `AGENTS.md` exists.** The round-1 documents live only on the git branch `remotes/zabz-yoga/main`
> (`git ls-tree -r remotes/zabz-yoga/main` lists them). `docs/dsh-evolution-v2/` exists **only** as an
> untracked directory on ZABZ-YOGA. This is finding §4.0 below, not a footnote: the audit's own
> evidence base is missing from three of the four machines it audits.

---

## 1. Inventory, with bytes

### 1.1 The canonical revision (the only one that contains round‑1's changes)

This is `remotes/zabz-yoga/main` @ `de0796c1` on the authority's `harness-config`. It is the revision
round 1 wrote and the revision the other three machines' **loaded** surfaces mostly match. It is **not**
what any machine's checked-out branch contains.

| path | bytes | mtime | what it is | always‑on? |
|---|---:|---|---|---|
| `presets/zabz/agent.cordis.yml` | **56,297** | commit 2026‑10‑13 | persona + Cordis composition (CRLF working copy) | prefix only |
| ↳ persona prefix (lines 22–201) | **25,657** | — | the text injected every step | **yes** |
| ↳ composition rows (line 202→765) | 30,640 | — | tool/plugin rows, not re-sent | no |
| `presets/yocheved/agent.cordis.yml` | 34,258 | commit | Yocheved's persona + composition | prefix only |
| `presets/cordis-bg/agent.cordis.yml` | 21,048 | commit | background persona + composition | prefix only |
| `presets/zabz/preset.yml` | 354 | commit | display metadata | no |
| `presets/yocheved/preset.yml` | 570 | commit | display metadata | no |
| `presets/cordis-bg/preset.yml` | 235 | commit | display metadata | no |
| `presets/zabz/skills/cordis-plugin-development/SKILL.md` | 20,923 | d614c297 | skill body | no (description yes) |
| `presets/zabz/skills/editing-cordis-compositions/SKILL.md` | 14,413 | d614c297 | skill body | no (description yes) |
| `presets/zabz/skills/estate-systems/SKILL.md` | 5,824 | a7977f20 | skill body | no (description yes) |
| `presets/zabz/skills/fast-search/SKILL.md` | 9,707 | e4b5bdeb | skill body | no (description yes) |
| `presets/zabz/skills/lpt-label-printing/SKILL.md` | 9,430 | 4df01530 | skill body | no (description yes) |
| `presets/zabz/skills/lpt-production-case-work/SKILL.md` | 11,878 | a95c3c77 | skill body | no (description yes) |
| `presets/zabz/skills/parallel-agent-orchestration/SKILL.md` | 13,275 | a7977f20 | skill body | no (description yes) |
| `presets/zabz/skills/read-sessions/SKILL.md` | 3,684 | a25a090d | skill body | no (description yes) |
| `presets/zabz/skills/secretary-wake/SKILL.md` | 18,621 | a7977f20 | skill body | no (description yes) |
| **9 skill bodies, total** | **107,755** | — | — | — |
| ↳ 9 skill `description:` lines, total | **4,538** | — | the catalog text | **yes** |
| `AGENTS.md` (harness-config root) | **20,126** | commit | estate rules §0–§7 | only when cwd is under repo |
| `settings/machines/host-posture.tsv` | 5,687 | commit | the one posture authority | no |
| `docs/outbound-comms-hard-stop.md` | 4,157 | commit | outbound procedure | no |
| `journal/README.md` | 14,613 | commit | journal map | no |

**Always-on for `zabz`:** persona prefix **25,657** + `AGENTS.md` **20,126** + skill descriptions
**4,538** = **50,321 B (~12.6k tokens) per step, before the first token of work.** (Round 1's number was
45,474; see §5.3 — it went **up**, not down.)

**Correction to the round-1 numbers the task asked me to verify.** Round 1's `PROGRAM.md` says
"persona 25,531 B + 9 skills ≈ 116 KB". Measured: persona prefix **25,657 B** (round 1's 25,531 is
within extraction method; the whole file is 56,297). The nine skill bodies total **107,755 B**, not
116 KB. There is no revision I can find whose nine `zabz` skill bodies sum to 116 KB — the closest is
ZABZ-TECH's uncommitted working tree (114,731 B, §1.3). Round 1's own audit table said 102,363 B for the
nine, so the two round-1 documents disagree with each other; both are below today's canonical 107,755.

### 1.2 What each machine LOADS (measured on the machine, `~/.dsh`)

Machines that load an estate preset: **ZABZ-TECH**, **ZABZ-YOGA**, **secratary-cloud**,
**lakewooechsmini**. `zabz-tech-linux` loads **no** preset: it has no `~/.dsh/.agent-presets/` and no
`~/.dsh/skills/` (this is the deliberate configuration round 1 recorded).

| file (loaded) | ZABZ-TECH | ZABZ-YOGA | secratary‑cloud | lakewooechsmini |
|---|---:|---:|---:|---:|
| `.agent-presets/zabz/agent.cordis.yml` | **58,677** ⚠ | 56,297 | 56,297 | 56,297 |
| ↳ mtime (UTC) | 2026‑10‑13T17:17:07Z | 2026‑10‑13T14:21:27Z | 2026‑10‑13T14:13:51Z | 2026‑10‑13T10:23:52Z |
| `.agent-presets/yocheved/agent.cordis.yml` | **33,498** ⚠ | 34,258 | 34,258 | 34,258 |
| `.agent-presets/cordis-bg/agent.cordis.yml` | 21,048 | 21,048 | 21,048 | 21,048 |
| `.agent-presets/zabz/preset.yml` | 354 | 354 | 354 | 354 |
| `.dsh/skills/` catalog, 9 bodies total | **108,160** ⚠ | 107,755 | 107,755 | 107,755 |

⚠ = differs from the canonical revision. The per-skill catalog differences on ZABZ-TECH are:
`estate-systems` 4,552 (vs 5,824), `lpt-label-printing` 9,884 (vs 9,430),
`lpt-production-case-work` 17,221 (vs 11,878), `parallel-agent-orchestration` 10,802 (vs 13,275),
`secretary-wake` 16,974 (vs 18,621). `cordis-plugin-development` (20,923), `editing-cordis-compositions`
(14,413), `fast-search` (9,707) and `read-sessions` (3,684) match on all four machines.

**Which machines load which:** every one of the four loads the **same namespace**,
`~/.dsh/.agent-presets/<preset>/` plus the shared `~/.dsh/skills/` catalog. The repo-level `AGENTS.md`
is loaded from the working tree when the agent's cwd is under `harness-config`; `personal-secretary-mvp`
has its own `AGENTS.md` (see §1.4).

### 1.3 The repo each machine actually has (working tree vs HEAD)

None of the four checkouts is on `main`, and three are dirty. This is why "correct in a file" and
"loaded" disagree.

| machine | branch @ HEAD | worktree | HEAD `presets/zabz/agent.cordis.yml` | HEAD `AGENTS.md` |
|---|---|---|---|---|
| ZABZ‑TECH | `mesh/broker-host-cloud-default-20261013` @ `5c8f46ea` | **dirty** (persona + 5 skills + generated patches + `sync.py` modified) | **58,677** (old) | 13,027 (old) |
| ZABZ‑YOGA | `fix/shop-device-icons-20261013` @ `77b09b7a` | dirty (`yocheved` persona + skill) | 56,297 (corrected) | 20,126 (canonical) |
| secratary‑cloud | `hk/28-refresh-deployed-sources-20261013` @ `37c62333` | dirty (`AGENTS.md` + others) | **59,119** (old) | **8,663** (short lineage) |
| lakewooechsmini | `master` @ `88cec13a` | clean | **47,097** (old, 3 skills only) | **absent from HEAD** |

The canonical branch `remotes/zabz-yoga/main` exists on none of these as a checkout.

### 1.4 Every `AGENTS.md`

| path | bytes | mtime | note |
|---|---:|---|---|
| `harness-config/AGENTS.md` canonical | 20,126 | commit | has §6–§7 (round‑1 additions) |
| ↳ ZABZ‑TECH working tree / HEAD | 13,027 | 2026‑10‑11 | §0–§5 only; §1 still names `secratary` |
| ↳ secratary‑cloud working tree | 8,663 (dirty; `.pre-archcorr-…` backup present) | 2026‑10‑13 | short lineage |
| ↳ lakewooechsmini repo | absent from `HEAD` | — | `git cat-file` fatal: path does not exist |
| `personal-secretary-mvp/AGENTS.md` (ZABZ‑TECH) | 45,498 | 2026‑09‑11 | |
| `personal-secretary-mvp/AGENTS.md` (`/opt/company`, authority) | 44,923 | 2026‑10‑10 | 575 B different from ZABZ‑TECH |
| `personal-secretary-mvp/app/AGENTS.md` | 12,847 / 12,719 (authority) | 2026‑07‑01 | |
| `personal-secretary-mvp/lpt-hub/AGENTS.md` | 9,679 | 2026‑10‑13 | |
| `personal-secretary-mvp/lpt-hub/.github/AGENTS.md` | 3,911 | 2026‑04‑10 | |

### 1.5 Generated files they depend on

| path | canonical bytes | ZABZ‑TECH worktree | what generates it |
|---|---:|---:|---|
| `profiles/web/presets.generated.patch.yml` | 78,660 | 79,920 (dirty) | `node scripts/make-preset-rows.mjs --install` |
| `profiles/web/cordis.patch.yml` (managed block) | 117,598 | 119,436 (dirty) | same |
| `~/.dsh/.agent-presets/*` (all machines) | — | — | `scripts/sync.py` (via `scripts/autosync.ps1`) |
| `~/.dsh/skills/*` + `.installed-by-harness-config.json` | — | — | `scripts/sync.py`; manifest on ZABZ‑TECH records all 9 installed from `zabz` |

### 1.6 Surface that only exists on one machine

`docs/dsh-evolution/` (11 files, the round-1 evidence base) exists as a working tree **only on
ZABZ-YOGA**. `ls <repo>/docs/dsh-evolution` returns the 11 files on ZABZ-YOGA, and `ABSENT` on
ZABZ-TECH, lakewooechsmini and secratary-cloud. The canonical persona (line 171) tells every agent
"the evidence base for your own behaviour is `~/code/harness-config/docs/dsh-evolution/`".

---

## 2. What is generated vs authored

| path | kind | regeneration command | hazard |
|---|---|---|---|
| `presets/zabz/agent.cordis.yml` | **nominally generated, actually hand‑edited** | `python scripts/make_zabz_preset.py` | The generator (`scripts/make_zabz_preset.py`, 50,000 B) still produces the **old** persona: it contains `runs on a Linux server called \`secratary\`` (1×), `macOS mini for his employee` (1×), `Your working directory is {{cwd}}.` inside the PERSONA, and neither "The one you must not get wrong" nor "look before you redo". Running it would silently re‑introduce every fact round 1 corrected. The file itself carries a hand‑edit warning **as a YAML composition comment** (line 496, in the composition, never injected): *"EDITED BY HAND, DELIBERATELY, AND THIS FILE MUST NOT BE REGENERATED until `scripts/make_zabz_preset.py` is fixed."* A `--force`‑guarded overwrite check (added 2026‑10‑08, refuses with exit 3 if a bold rule paragraph would be lost) is the only mechanical protection. |
| `profiles/web/presets.generated.patch.yml` | **generated** | `node scripts/make-preset-rows.mjs --install` | `--check` is the CI verifier; `sync.py` runs it and refuses the profile step on DRIFT. |
| `profiles/web/cordis.patch.yml` (managed block) | **generated** (same command) | same | same |
| `~/.dsh/.agent-presets/**` and `~/.dsh/skills/**` | **generated install target** | `python scripts/sync.py` (scheduled via `scripts/autosync.ps1`; task `PersonalSecretary-HarnessSync`) | Never edit by hand; `sync.py` plans from the repo, writing LF. |
| `presets/zabz/agent.cordis.yml`'s *content* | authored in `make_zabz_preset.py`'s `PERSONA` today, but the live corrected text is **authored by hand** | — | Two contradictory instructions about one file: the generator says "GENERATED OUTPUT… NEVER hand‑edit", the file comment says "EDITED BY HAND… MUST NOT BE REGENERATED". |
| `AGENTS.md`, all `SKILL.md`, `docs/**`, `host-posture.tsv` | **authored** | — | — |

`presets/zabz/rows/{persona.row.yml,delegation.rows.yml,mcp.rows.yml}` exist in ZABZ‑YOGA's **loaded**
`.agent-presets/zabz/rows/` but are **not in the canonical git tree** — stale generator artifacts, not
part of the deployed surface.

---

## 3. Did round 1's changes land, on every machine?

**Short answer: no — not on ZABZ-TECH, and the repo side is stale everywhere.**

Round 1's own claim table (`08-changes-made.md` §2) and the live state. "Loaded" = the file the machine
actually injects; "repo" = the machine's working‑tree file.

| # | round-1 claim | ZABZ‑TECH | ZABZ‑YOGA | secratary‑cloud | lakewooechsmini | verdict |
|---|---|---|---|---|---|---|
| 1 | persona 28,697 → **25,531 B** | loaded prefix **28,037** (old) | loaded 25,657 | loaded 25,657 | loaded 25,657 | **canonical yes; ZABZ‑TECH no** |
| 2 | new **"The one you must not get wrong"** rule | loaded: **absent** (0 hits) | loaded: present | present | present | **ZABZ‑TECH no** |
| 3 | `{cwd}` templating bug killed | loaded: **1 literal `{cwd}`** ⚠ | 0 | 0 | 0 | **ZABZ‑TECH no** |
| 4 | three authority statements corrected | loaded: still `a Linux server called \`secratary\``, `secratary-cloud` ×3 | `secratary-cloud` ×6 | ×6 | ×6 | **ZABZ‑TECH no** |
| 5 | fleet list corrected | loaded: still `macOS mini for his employee` ×1 | 0 | 0 | 0 | **ZABZ‑TECH no** |
| 6 | `AGENTS.md` §1 fixed | repo/wt: **13,027**, §1 still `cron on secratary` + `ssh secratary-ts` | repo: 20,126 with §6–§7 | repo: 8,663, no §6–§7 | repo: **no AGENTS.md** | **only ZABZ‑YOGA has it** |
| 7 | four skills extended | loaded catalog old on 5 skills | canonical | canonical (skills) | canonical (skills) | **3 skills, not 4; see below** |

**The "four skills extended" claim is wrong.** Commit `a7977f20` touched exactly **three**:
`estate-systems`, `parallel-agent-orchestration`, `secretary-wake`. The fourth, `editing-cordis-compositions`,
was the intended home of rule A9 (the generator hazard) and is **byte‑identical to its pre‑round‑1
revision** (14,413 B, last touched `d614c297`); it mentions "generat" only in the unrelated phrase
"a standing generation that lives until the process exits". **A9 did not land anywhere.**

**Reproducing preset-drift.** I ran round 1's own `scripts/preset-drift.py` (15,597 B, from
`remotes/zabz-yoga/main`) on each machine with its own `--repo` and `--dsh-home`. It is read‑only
without `--apply`; `--apply` was never passed.

| machine | compared | match | drift | divergent‑in‑repo | exit |
|---|---:|---:|---:|---:|---:|
| ZABZ‑YOGA | 15 | 14 | 1 | 2 | 1 |
| ZABZ‑TECH | 15 | 8 | 7 | 1 | 1 |
| secratary‑cloud | 14 | 8 | 6 | 1 | 1 |
| lakewooechsmini | 9 | 5 | 4 | 1 | 1 |

**Round 1's "15 compared / 15 match / 0 drift" is refuted on every machine**, including ZABZ‑YOGA (1
drift + 2 repo-internal divergences). The "compared" count itself is not constant: it is 15 only where
all 9 skills exist in the checkout; secratary-cloud's checkout lacks `lpt-label-printing` (14), and
lakewooechsmini's `master` has only 3 skills and no `AGENTS.md` (9). This is exactly the caveat
`preset-drift.py` documents: `sync.py` and this detector answer different questions.

**Why ZABZ‑TECH's loaded surface is stale (root cause).** `scripts/autosync.ps1` (35,269 B) — the thing
the scheduled task `PersonalSecretary-HarnessSync` actually runs — "NEVER touches a dirty working tree",
and applies `scripts/sync.py` from a **committed snapshot** (`$apply = & $python (Join-Path $snapshot
'scripts\sync.py')`). ZABZ‑TECH's checkout is dirty; its committed `HEAD` still holds the **58,677‑byte**
persona and the 13,027‑byte `AGENTS.md`. So the corrected working‑tree file is never committed and never
deployed, while the loaded copy stays at `HEAD`'s old content. The machine's sync returned
`Last Result: 0` at 2026‑10‑13 21:02 local — a success that deployed the old instructions. **The one
machine whose own working tree contains the correction is the one machine still loading the old one.**

**`preset-drift.py` is not even present on three machines.** It exists only on ZABZ‑YOGA (15,597 B).
secratary-cloud, lakewooechsmini and ZABZ‑TECH lack it, so `sync.py`'s `verify_loaded_surface()` — which
would have caught all of this and filed a journal alarm — prints `verify: SKIPPED — scripts/preset-drift.py
is not in this checkout`. The three older `sync.py` copies (30,364 / 13,787 / 41,017 B) predate that
function entirely. Only ZABZ‑YOGA's `sync.py` (45,597 B) has it. It is not scheduled anywhere.

---

## 4. Contradictions and stale facts (wrong **now**)

### 4.0 The evidence base is missing from the machines that are told to use it
The canonical persona line 171 points every agent at `~/code/harness-config/docs/dsh-evolution/`;
that directory exists only on ZABZ‑YOGA. On the other three preset machines the pointer is dead. Same
class as round 1's §7b item 11 ("the broken pointer to `secretary-replacement-audit/`") — the fix
replaced one missing path with another that is present on only one machine.

### 4.1 `secratary` named where `secratary-cloud` is the authority
- `presets/zabz/skills/parallel-agent-orchestration/SKILL.md:137` — table row
  `| \`secratary\` | Linux authority | — | prefer it for anything that must not depend on a laptop… |`.
  The office box is `frozen`; the authority is `secratary-cloud`. Round 1's own method ("find every
  surface that states it") fixed `estate-systems` but missed this copy.
- `presets/zabz/skills/secretary-wake/SKILL.md:12` — "The secretary server (`secratary`) is now the
  half of you that never sleeps." Plus `ssh secratary-ts …` at lines 111, 133, 134, 135, 136, 179, 180.
  Round 1 extended this skill (A7) and left its host stale.
- `presets/zabz/agent.cordis.yml:630` (composition comment) — `ssh secratary-ts ...`.
- `presets/yocheved/agent.cordis.yml:119–120, 462–465` — `secratary-ts` aliases in commands; the line‑462
  comment names `secratary-cloud` as `root@100.73.176.126` while `host-posture.tsv` gives
  `178.156.194.1`.
- ZABZ‑TECH's **loaded** persona still says "a Linux server called `secratary`".

### 4.2 A machine described as something it is not
ZABZ‑TECH's loaded persona contains `macOS mini for his employee Yisroel` (1×); canonical corrected it
to `lakewooechsmini`. `host-posture.tsv` is correct on every machine (it is the repo copy).

### 4.3 The archive's store path
Canonical `AGENTS.md:54` is corrected (`/opt/company/archive/lpt-transcripts` on `secratary-cloud`).
ZABZ‑TECH's working‑tree `AGENTS.md` still says `secratary:/home/zabz/lpt-transcripts/`, `cron` on
`secratary`, and `ssh secratary-ts`. The authority's working‑tree `AGENTS.md` (8,663 B) is a different,
shorter lineage and was not read for this path. **This is loaded**: the repo‑root `AGENTS.md` is what a
session with cwd under `harness-config` reads.

### 4.4 A model name hardcoded
`settings/machines/LAKEWOOECHSMINI.yaml:62` and `DESKTOP-FGV6KMH.yaml:79` still carry
`model: deepseek-v4-flash-vision-exp` (round 1 §2.8). The adjacent comments explain why it is the
vision default, but the always‑on persona says "AI models are never hardcoded — resolve them at
runtime". Unchanged by round 1.

### 4.5 Undated numbers in the always‑on persona
Canonical persona line 127: `(18 agents, ~130 ticks/day, 203 tables)`; line 136: `FastAPI (618 routes),
199 services, 203 tables`. Round 1 §5 flagged these and §7 explicitly listed the numeric corrections as
"not yet done". They are still there, with no date, re‑billed every step.

### 4.6 Two copies of every skill in the loaded tree
`~/.dsh/.agent-presets/<preset>/skills/` and `~/.dsh/skills/` both exist. On lakewooechsmini and
secratary-cloud the per‑preset copy is stale (e.g. `lpt-production-case-work` 6,010 B vs the catalog's
11,878 B; on mac-mini the `zabz` preset dir has only 3 skills). `sync.py`'s `plan_skills` writes the
catalog and reports the per‑preset copies as a separate namespace; an agent reading the wrong root gets
an old rule. This is a duplication with two different load paths.

---

## 5. Duplication and dead weight

### 5.1 Rules that appear in more than one surface (each copy measured)

| rule | copies (bytes) | always‑on cost |
|---|---|---|
| outbound hard‑stop | persona ¶+bullets **1,611** · `AGENTS.md` §4 **383** · `docs/outbound-comms-hard-stop.md` **4,157** · `yocheved` ~**287** | 1,994 B of the always‑on surface; the 4,157 B doc is reference |
| "ask one question, never a document" | persona rules 2/2b/2c/9 **3,123** · `AGENTS.md` §2 **415** · §3 **343** | ~3,881 B |
| background‑first shell | persona **433** · `yocheved` **2,342** · (round 1 also cited `cordis-bg`) | 2,775 B across presets |
| memory/journal mechanics | persona **2,221** · `journal/README.md` **14,613** | 2,221 B always‑on |
| fast‑search + measurements | persona **826** · `fast-search` skill **9,707** | 826 B |
| parallel orchestration | persona ¶1b **968** · `parallel-agent-orchestration` skill **13,275** | 968 B |
| authority / posture | persona **1,091** fleet + **647** one‑source · `AGENTS.md` §5 **3,196** + §0 **1,655** · `host-posture.tsv` **5,687** | ~1,738 B always‑on |
| the two‑failures story | `AGENTS.md` §0 **1,655** · `estate-systems` | 1,655 B |
| generator hazard | persona comment line 496 · canonical `AGENTS.md` §7 **475** · **absent** from `editing-cordis-compositions` | 475 B (only on ZABZ‑YOGA) |

### 5.2 Always‑on bytes by theme (canonical `zabz` prefix, 57 paragraphs)

| theme | bytes | share |
|---|---:|---:|
| rules 1–9 ("ask less" / autonomy / docs / style) | **7,503** | **30.2%** |
| memory / journal | 3,851 | 15.5% |
| outbound hard‑stop | 1,568 | 6.3% |
| wrong‑data + "look before you redo" (new in round 1) | 1,761 | 7.1% |
| AI models runtime | 1,124 | 4.5% |
| fleet / machines | 1,034 | 4.2% |
| systems owned | 970 | 3.9% |
| technical discipline (shell/search/governor/cost) | 3,191 | 12.8% |
| owner queue + ask‑counterparty | 2,168 | 8.7% |
| identity / provenance / verify / never‑destroy | 1,086 | 4.4% |
| unsourced pointers / headers | ~966 | 3.9% |

Round 1's headline ("~a third of the always‑on budget goes to *ask less* while the #1 failure had no
rule") is still true of the *ratio*: the two least frequent failures (asked‑unnecessarily 1.8%,
asked‑badly 1.5%) still get **30.2%**, and the #1 failure (`wrong-data`, 11.4%) now has **7.1%**.

### 5.3 The always‑on budget went **up**, not down
Round 1's measured always‑on total was **45,474 B** (persona 27,555 + `AGENTS.md` 13,027 +
descriptions 4,892). Today, on the canonical revision: **25,657 + 20,126 + 4,538 = 50,321 B** — a net
**+4,847 B**. The persona shrank ~3,000 B, but `AGENTS.md` grew from 13,027 to 20,126 B (**+7,099**:
§1 rewritten to 8,970 B, §5 4,364 B, §6 3,197 B, §7 475 B added). The redesign's target was
"≤ 22,000 B"; the actual movement was away from it.

### 5.4 Dead weight that no longer matches reality
- `docs/dsh-evolution/` pointer in the persona (dead on 3 machines).
- `AGENTS.md` §1's archive table (9 KB) describes machinery that only one lineage of the repo has.
- `presets/zabz/rows/*.yml` in the loaded tree: stale generator output, absent from git.
- The `secratary-ts` alias in 8 places across 3 skills/presets, after the box was frozen.

---

## 6. The three‑tier question, answered with evidence

| tier | what is in it | bytes | where the boundary is enforced |
|---|---|---:|---|
| **1 — always‑on** | `zabz` persona prefix (25,657) + `AGENTS.md` when cwd is under the repo (20,126) + 9 skill `description:` lines (4,538) | **50,321** | preset composition `prefix:` row; `AGENTS.md` discovery by cwd; skill catalog = `~/.dsh/skills/` |
| **2 — task‑loaded skills** | the 9 skill bodies | **107,755** | loaded when the task triggers; `sync.py plan_skills()` mirrors `presets/*/skills` into `~/.dsh/skills/`; `$(DSH_HOME)/skills` is live‑watched |
| **3 — reference docs** | `docs/outbound-comms-hard-stop.md` 4,157 · `journal/README.md` 14,613 · `host-posture.tsv` 5,687 · `docs/dsh-evolution/*` (ZABZ‑YOGA only) · `docs/mesh/*` | — | reachable by command/read, never injected |

**Where the boundary actually holds:** the persona/composition split is enforced by the preset schema
(the `prefix:` row is injected, the plugin rows are not). The skill split is enforced by `sync.py`'s
mirror into the one live‑watched root.

**Where it does not:** (a) skill *descriptions* are always‑on but 4,538 B of them are written as
prose summaries that restate rule text; (b) `AGENTS.md` is "always‑on when cwd is under the repo",
which on these machines is most sessions, and its §1+§5 = 13,334 B are incident narrative; (c) tier‑3
pointers are dead on three machines, so tier‑3 content is not reachable where agents are told it is.

---

## 7. What is missing (round‑1 friction list vs the live text)

Round 1's ranked session census (945 sessions):

| # | friction | % | is there a rule **now** in the live surface? |
|---|---:|---:|---|
| 1 | `wrong-data` | 11.4% | **yes** — "The one you must not get wrong" (persona 73–98), loaded on 3 of 4 machines |
| 2 | `tool-failure` | 10.2% | **no general rule.** The only failure‑handling rule is mesh‑specific (persona §1c, "when a `subagent` call fails"). Nothing says what to do when a tool/command exits non‑zero, times out, or returns garbage. |
| 3 | `repeated-work` | 9.4% | yes — "look before you redo" |
| 4 | `env-hostile` | 7.2% | **no rule.** "Prefer in‑process tools" and "search the index" are efficiency rules; nothing addresses an unreachable host, a missing binary, a broken path, or a wrong OS. |
| 5 | `false-completion` | 5.2% | partly — "Never complete something you have not run" |
| 6 | `stopped-early` | 4.7% | yes, heavily (rules 1/1b/1c) |
| 7 | `slow` | 4.7% | partly — background‑first + cost rules |
| 8 | `ignored-instruction` | 4.3% | no direct rule (nearest is `AGENTS.md` §6.3, loaded on one machine) |
| 9 | `context-loss` | 3.4% | yes (journal handoff) |
| 10 | `asked-unnecessarily` | 1.8% | over‑covered |
| 11 | `asked-badly` | 1.5% | over‑covered |

**The measured gap:** `tool-failure` + `env-hostile` = **16 of the top‑4, 160 sessions**, and neither
has a rule. Round 1's nine added rules covered A1–A9 (git safety, credentials, generator, owner
channel) and A10/A11 (hang, cheap‑tool‑last) — none of which is the #2 or #4 friction. The `--fresh`/
exit‑code discipline in `fast-search` is the closest thing, and it is task‑loaded, not always‑on.

---

## 8. Ranked concrete edits (propose, do not apply)

Ranked by (blocks work → recurs → owner‑visible). Byte deltas are measured against the canonical
revision; "always‑on" deltas are per step for a `zabz` session with cwd under the repo.

1. **Commit, then deploy, the corrected working tree on ZABZ‑TECH** — do not leave the fix uncommitted
   while a dirty‑tree‑averse deployer ships `HEAD`.
   *File:* ZABZ‑TECH's `harness-config` working tree (`presets/zabz/agent.cordis.yml` 56,297 B,
   `presets/yocheved/agent.cordis.yml`, 5 skills, `profiles/web/*.patch.yml`).
   *Change:* commit the corrected files on the machine's branch (or converge the branch onto the
   canonical lineage), then run the scheduled sync; verify with `preset-drift.py`.
   *Bytes:* moves ~2,380 B of the loaded persona from the old text to the corrected text; **no
   always‑on delta** (it is the same file, right revision).
   *Expected effect:* removes the live `{cwd}` artefact and restores the `wrong-data` rule on the
   primary machine — the single highest‑impact edit.
   **Why it matters:** this is the only one of the four machines still loading the pre‑round‑1 persona.

2. **Deploy `scripts/preset-drift.py` to all four checkouts and wire it into the scheduled job.**
   *File:* each checkout's `scripts/preset-drift.py` (15,597 B) + `scripts/sync.py`'s
   `verify_loaded_surface()`.
   *Change:* add the detector to the snapshot the syncer runs, so a refusal/DRIFT reaches the journal.
   *Bytes:* +15,597 B in the repo; 0 always‑on.
   *Expected effect:* the failure that has now recurred twice (round 1, and ZABZ‑TECH today) becomes
   self‑reporting.

3. **Fix the authority in `parallel-agent-orchestration` line 137.**
   *File:* `presets/zabz/skills/parallel-agent-orchestration/SKILL.md`.
   *Change:* replace the table row `\`secratary\` | Linux authority` with `\`secratary-cloud\` | Linux
   authority (the office box \`secratary\` is frozen)`.
   *Bytes:* ~−20/+60 B in a task‑loaded skill.
   *Expected effect:* stops a skill that round 1 itself edited from teaching the exact alias confusion
   the 2026‑10‑11 incident was about.

4. **Fix the host in `secretary-wake` (line 12 + seven `secratary-ts` commands).**
   *File:* `presets/zabz/skills/secretary-wake/SKILL.md`.
   *Change:* name `secratary-cloud` as the secretary server and change the ssh targets to
   `secratary-cloud`.
   *Bytes:* ~±150 B in a task‑loaded skill.
   *Expected effect:* the wake/queue commands stop pointing at a frozen box.

5. **Put the generator hazard into `editing-cordis-compositions` (rule A9, still missing).**
   *File:* `presets/zabz/skills/editing-cordis-compositions/SKILL.md`.
   *Change:* add a short section: `presets/zabz/agent.cordis.yml` is nominally generated by
   `scripts/make_zabz_preset.py`; the generator is stale and running it would revert the authority/
   machine/rule corrections; the live file is hand‑edited on purpose; `--check` reporting DRIFT is
   expected.
   *Bytes:* ~+500 B in a task‑loaded skill; 0 always‑on.
   *Expected effect:* moves a load‑bearing warning out of a never‑injected YAML comment and out of a
   document that exists on one machine.

6. **Add the two missing friction rules — as skills, not the persona.**
   *File:* `presets/zabz/skills/estate-systems/SKILL.md` (env‑hostile) and a new/expanded
   shell section (tool‑failure).
   *Change:* (a) tool‑failure: read the exit code, quote the tool's own diagnostic, distinguish
   "the tool failed" from "the answer is empty", retry once with a different tool/host before falling
   back; (b) env‑hostile: detect OS/alias/path, prefer an in‑process or indexed route, never report a
   command's failure as a fact about the system.
   *Bytes:* ~+600 B task‑loaded; 0 always‑on.
   *Expected effect:* addresses frictions #2 and #4 (16.4% of sessions) that the current surface does
   not mention.

7. **Correct `docs/dsh-evolution/` reachability or the pointer.**
   *File:* `presets/zabz/agent.cordis.yml` line 171 and/or the repo layout.
   *Change:* either land the 11 round‑1 docs on every checkout (they are only on
   `remotes/zabz-yoga/main` and ZABZ‑YOGA's working tree), or change the sentence to name the branch
   and the command to read them from git.
   *Bytes:* ~±40 B always‑on.
   *Expected effect:* the evidence base stops 404‑ing on three of four machines.

8. **Reconcile the four repo lineages; one of them must be `main`.**
   *File:* all four checkouts (ZABZ‑TECH `mesh/…`, ZABZ‑YOGA `fix/…`, secratary‑cloud `hk/…`,
   lakewooechsmini `master`).
   *Change:* converge onto the canonical `zabz-yoga/main` content (or a merge of it), commit, and let
   `autosync.ps1` deploy a clean tree.
   *Bytes:* eliminates the 3 duplicate `agent.cordis.yml`/skill lineages; the loaded totals stop
   disagreeing (108,160 vs 107,755).
   *Expected effect:* removes the root cause of both the stale ZABZ‑TECH surface and the repo‑internal
   DIVERGENT reports (`parallel-agent-orchestration` 10,802/7,852/13,275).

9. **Add dates to (or delete) the undated numbers in the persona.**
   *File:* `presets/zabz/agent.cordis.yml` lines 127 and 136.
   *Change:* state the measurement date, or state the shape and drop the count.
   *Bytes:* ~±60 B always‑on.
   *Expected effect:* removes two claims that go false silently, at a cost of ~60 B.

10. **Fix the hardcoded model ids or record the exception.**
    *File:* `settings/machines/DESKTOP-FGV6KMH.yaml:79`, `settings/machines/LAKEWOOECHSMINI.yaml:62`.
    *Change:* resolve via the gateway catalog/alias, or add one explicit sentence in the persona's
    AI‑models rule naming this vision exception if it is deliberate.
    *Bytes:* 0 always‑on if the exception is recorded in a machine file.
    *Expected effect:* the always‑on rule stops contradicting the machine config.

11. **Remove the stale per‑preset `skills/` copies from the loaded tree (or make the catalog the only
    read root).**
    *File:* `~/.dsh/.agent-presets/<preset>/skills/**` via `sync.py`.
    *Change:* after mirroring into `~/.dsh/skills/`, do not also leave the older per‑preset copies
    where a session can read them.
    *Bytes:* removes ~6 KB of contradictory, stale skill text on mac-mini/authority.
    *Expected effect:* one skill namespace, one age.

12. **Move the incidence narrative out of `AGENTS.md` §5 / §1.**
    *File:* `AGENTS.md` line 116 (`§5` worked example, 4,364 B; §1 table 8,970 B).
    *Change:* keep the rule sentence and a pointer; move the 2026‑10‑11 incident and the archive table
    detail to `docs/mesh/142` / `docs/mesh/163`.
    *Bytes:* up to ~−10,000 B always‑on for repo sessions (the only edit here with a large budget
    effect).
    *Expected effect:* reverses the +4,847 B regression in §5.3 without losing a rule.

---

## WHAT I COULD NOT DETERMINE

- **The exact rendered prefix byte count the runtime injects.** I measured the `prefix: |-` YAML block
  (25,657 B) and the whole file (56,297 B); I could not read the live compiled system prompt of a running
  session on each machine, so "persona bytes" is the block, not the runtime-rendered string (which
  substitutes `{{cwd}}`/`{{model}}` and may normalise whitespace). Round 1's 25,531 vs my 25,657 is
  within that uncertainty.
- **Whether `docs/dsh-evolution/` was ever deployed and then removed, or never deployed.** I can see it
  is absent from three working trees and present on ZABZ-YOGA; I did not inspect every git reflog or the
  sync logs for a deletion event.
- **The authority's working-tree `AGENTS.md` content (8,663 B).** I measured its size but did not read
  its §1, because it is a different, short lineage and I focused on the canonical and ZABZ-TECH copies.
- **Whether the round-2 corpus/reader fleet is writing generated surfaces that also reach agents.** I
  saw `/home/zabz/evolution-corpus-v2/reports/company-failures.md` appear at 01:09Z during this audit;
  it is a report, not an instruction surface, and I did not audit it.
- **The full content of ZABZ-TECH's uncommitted skill revisions** (`lpt-label-printing` 10,275 B,
  `lpt-production-case-work` 18,009 B), which are larger than the canonical and may contain rules the
  canonical lacks. I measured sizes and hashes, not the text.
- **`sync.py --dry-run` behaviour on each machine.** I read the script and deliberately did **not** run
  it: even `--dry-run` can reach `_alarm_once`/journal paths in some branches, and the task forbade
  changing anything. `preset-drift.py` (read-only without `--apply`) was run instead.

## EVIDENCE LOG

All times UTC, 2026-10-14. `LOCAL` = `zabz-tech-linux`. Commands are `ssh -o BatchMode=yes`.

**Host / reachability**
- `hostname` → `zabz-tech-linux`; `uname -a` → `Linux zabz-tech-linux 6.8.0-111-generic x86_64`.
- `for h in desktop laptop-ts mac-mini secratary-cloud: ssh $h hostname` → `zabz-tech`,
  `zabz-yoga`, `LakewooechsMini`, `secratary-cloud` (all rc=0).
- `laptop` (LAN, 192.168.50.244) → `No route to host`; reached via `laptop-ts` (Tailscale).

**Round-1 reference docs**
- `git ls-tree -r remotes/zabz-yoga/main --name-only | grep dsh-evolution` → 11 files
  (`00-SYNTHESIS`, `01-corpus`, `05-instruction-redesign`, `07-pain-register`, `07-target-system`,
  `08-changes-made`, `10-instruction-surface-audit`, `20-memory-continuity`, `30-systems-and-autonomy`,
  `PROGRAM`, `READER-BRIEF.template`).
- `git branch -a --contains 75ffbeef` → only `remotes/zabz-yoga/main`.
- `ls <repo>/docs/dsh-evolution` → present on ZABZ-YOGA (11 names); `ABSENT` on ZABZ-TECH,
  lakewooechsmini, secratary-cloud.
- ZABZ-YOGA `dir /b /s …\docs\dsh-evolution-v2` → `PROGRAM.md` (8,982 B, untracked).
- `git show remotes/zabz-yoga/main:AGENTS.md | wc -c` → 20,126.

**Canonical sizes**
- `git ls-tree -r -l remotes/zabz-yoga/main -- presets profiles/web settings/machines AGENTS.md`
  → `56297` zabz persona, `34258` yocheved, `21048` cordis-bg; skills
  `20923, 14413, 5824, 9707, 9430, 11878, 13275, 3684, 18621` (sum 107,755); `20126` AGENTS.md;
  generated `117598` / `78660`.
- Persona prefix extraction (Python, `prefix: |-` block): canonical **25,657**, ZABZ-TECH loaded
  **28,037**, secratary-cloud repo **29,181**, mac-mini repo **21,766**.
- Skill description sum (Python, frontmatter `description:`) → **4,538**.
- `AGENTS.md` section sizes (Python, `^## ` split) → header 322, §0 1,655, §1 **8,970**, §2 416,
  §3 344, §4 383, §5 **4,364**, §6 3,197, §7 475.

**Loaded-surface measurements**
- ZABZ-TECH `Get-ChildItem … | Length` → `zabz\agent.cordis.yml|58677|2026-10-13T17:17:07Z`;
  `yocheved|33498`; catalog `estate-systems 4552, lpt-label-printing 9884,
  lpt-production-case-work 17221, parallel-agent-orchestration 10802, secretary-wake 16974`.
- ZABZ-YOGA same → `zabz 56297 @14:21:27Z`, `yocheved 34258`, catalog = canonical sizes.
- secratary-cloud `find … -printf` → `zabz 56297 @14:13:51Z`, `yocheved 34258`, catalog = canonical.
- lakewooechsmini `find … -exec stat` → `zabz 56297 @10:23:52Z`, `yocheved 34258`, catalog = canonical.
- Marker table (Python/grep over fetched files): ZABZ-TECH loaded `{cwd}=1, wrong-data=0,
  look-before-redo=0, macOS-mini=1, secratary-cloud=3`; ZABZ-TECH repo and all other loaded files
  `{cwd}=0, wrong-data=1, look-before-redo=1, macOS-mini=0, secratary-cloud=6`.

**Repo lineage / dirt**
- ZABZ-TECH: `git rev-parse --abbrev-ref HEAD` → `mesh/broker-host-cloud-default-20261013`;
  `--short HEAD` → `5c8f46ea`; `git status --porcelain` → 22 `M` incl. `presets/zabz/agent.cordis.yml`,
  `presets/yocheved/agent.cordis.yml`, 5 skills, both generated patches, `scripts/sync.py`;
  `git cat-file -s HEAD:presets/zabz/agent.cordis.yml` → **58677**; `HEAD:AGENTS.md` → **13027**.
- ZABZ-YOGA: `fix/shop-device-icons-20261013` @ `77b09b7a`; HEAD persona **56297**, HEAD AGENTS **20126**;
  dirty `presets/yocheved/agent.cordis.yml`.
- secratary-cloud: `hk/28-refresh-deployed-sources-20261013` @ `37c62333`; HEAD persona **59119**,
  HEAD AGENTS **8663**.
- lakewooechsmini: `master` @ `88cec13a`; HEAD persona **47097**;
  `git cat-file -s HEAD:AGENTS.md` → `fatal: path 'AGENTS.md' does not exist in 'HEAD'`.

**preset-drift.py (read-only; run from `remotes/zabz-yoga/main` copy, 15,597 B)**
- ZABZ-YOGA → `compared 15 match=14 drift=1 divergent-in-repo=2`, exit **1**
  (`yocheved [34945B vs 34258B]`).
- ZABZ-TECH → `compared 15 match=8 drift=7`, exit **1**.
- secratary-cloud → `compared 14 match=8 drift=6 divergent-in-repo=1`, exit **1**.
- lakewooechsmini → `compared 9 match=5 drift=4 divergent-in-repo=1`, exit **1**.
- All four: `DIVERGENT skill/parallel-agent-orchestration (10802/7852/13275 in canonical)`.
- `ls scripts/preset-drift.py` → present only on ZABZ-YOGA (15,597); ABSENT on the other three.
- `sync.py` sizes: ZABZ-TECH 41,017 (dirty), ZABZ-YOGA 45,597, secratary-cloud 30,364,
  lakewooechsmini 13,787; only ZABZ-YOGA grep-matches `verify_loaded_surface`/`preset-drift`.

**Deploy root cause**
- `schtasks /query /tn PersonalSecretary-HarnessSync /v /fo LIST` on both Windows machines →
  `Task To Run: wscript.exe … PersonalSecretary-HarnessSync.vbs`, `Last Run 10/13/2026 9:02:01 PM`,
  `Last Result: 0`.
- `type PersonalSecretary-HarnessSync.vbs` → runs `pwsh -File …\scripts\autosync.ps1`.
- `autosync.ps1` (35,269 B): docstring "NEVER touches a dirty working tree"; line 520
  `$apply = & $python (Join-Path $snapshot 'scripts\sync.py')`; line 532 verify uses the snapshot.

**Contradiction greps (canonical revision)**
- `grep secratary parallel-agent-orchestration.SKILL.md` → line 137 `| \`secratary\` | Linux authority |`.
- `grep secratary secretary-wake.SKILL.md` → line 12 `The secretary server (\`secratary\`)`; 8,621 B body;
  `secratary-ts` at 111,133,134,135,136,179,180.
- `grep secratary yocheved-agent.canonical.yml` → line 51 correct (`secratary-cloud`); 119–120, 462–465
  `secratary-ts`.
- `grep 'a Linux server called' canon` → `secratary-cloud`; ZABZ-TECH loaded → `secratary`.
- `grep -n model settings/machines/{DESKTOP-FGV6KMH,LAKEWOOECHSMINI}.yaml` → line 79 / line 62
  `model: deepseek-v4-flash-vision-exp`.
- `grep 618 routes|199 services|203 tables canon persona` → lines 127 and 136.
- `editing-cordis-compositions` generator search → only "a standing generation"; last touched `d614c297`.
- `git show --stat a7977f20 -- presets/zabz/skills` → exactly 3 files
  (`estate-systems` +19, `parallel-agent-orchestration` +37, `secretary-wake` +23).

**Always-on arithmetic**
- Round 1: `27,555 + 13,027 + 4,892 = 45,474` (from `10-instruction-surface-audit.md` §0).
- Today canonical: `25,657 + 20,126 + 4,538 = 50,321`; net **+4,847**.
- Theme split of the canonical prefix (57 paragraphs): rules 1–9 **7,503 B / 30.2%**; memory 3,851 /
  15.5%; technical discipline 3,191 / 12.8%; outbound 1,568 / 6.3%; wrong-data+repeat **1,761 / 7.1%**;
  fleet 1,034 / 4.2%; systems 970 / 3.9%; AI-models 1,124 / 4.5%.

---

*Written to `/home/zabz/evolution-corpus-v2/reports/instruction-v2.md` on `secratary-cloud` and
returned in the final message. No repository file, `~/.dsh` file, or journal entry was modified.
`preset-drift.py` was run without `--apply`; `sync.py` was read, not run.*
