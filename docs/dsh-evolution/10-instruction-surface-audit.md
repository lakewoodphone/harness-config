# 10 — The instruction and identity surface, audited

**Prepared:** 2026-10-13 · **Method:** one mesh child read the whole surface at `harness-config` and
returned an evidenced audit; every claim below is its finding, and the manager reproduced the
`{cwd}`, authority and duplication findings directly.
**Subject:** every byte of standing instruction that shapes how an agent on this estate behaves.

> **Note on revision.** The child landed on `lakewooechsmini`, whose `harness-config` checkout is
> `master 88cec13a` with a **47,097-byte** `zabz` persona and **3 skills** — not the 58,677-byte,
> 9-skill revision this audit was written against. It hunted for the real revision on the fleet
> branches (`_fleet/authority-order` @ `5aa15b97`, `_worktrees/*/frontier-gap`, `project-loop`,
> `weekly-evolution`) and read `authority-order`. **That divergence is itself finding #0:** the
> instruction surface is not the same on two machines, and the machine whose `zabz` it read first was
> three weeks and 11,580 bytes behind.

---

## 0. The surface, measured

| file | bytes | what it is | always-on per step |
|---|---:|---|---:|
| `presets/zabz/agent.cordis.yml` | 58,677 | persona 27,555 + Cordis composition 31,122 | **27,555** |
| `presets/zabz/skills/*/SKILL.md` (9) | 102,363 | skill bodies, largest 20,923 | **0** on demand; **4,892** of descriptions in the catalog |
| `AGENTS.md` (repo root) | 13,027 | estate rules §0-§5 | **13,027** when cwd is under the repo, else 0 |
| `settings/machines/host-posture.tsv` | 5,687 | the one service-state authority | 0 |
| `journal/README.md` | 14,613 | journal map | 0 |
| `docs/outbound-comms-hard-stop.md` | 4,157 | outbound procedure | 0 |
| `presets/yocheved/agent.cordis.yml` | 33,498 | persona 16,076 + composition | 16,076 |
| `presets/cordis-bg/agent.cordis.yml` | 21,048 | persona 3,054 + composition | 3,054 |

**Always-on for `zabz`: 45,474 bytes (~11.4k tokens) before the first token of work** — 27,555 of
persona, 13,027 of `AGENTS.md`, 4,892 of skill descriptions. Only 47% of the 58,677-byte persona file
is instruction; the other 31,122 bytes are Cordis composition, which is not re-sent.

At the persona's own cited 900-step session that is **~41 MB re-billed**, against the measured fact
that the three most expensive sessions were 52.5% of a day's spend.

---

## 1. Load-bearing rules — each with the evidence it claims

Verified as present with a real incident behind it:

- **Rule 1 / 1b / 1c — finish the job; orchestrate by default; `subagent` is the mesh.** 9.9% of his
  messages were "keep going" (2,283 turns); owner verbatim 2026-09-15; "measured 2026-09-17: zero new
  node processes locally during a dispatch" (`docs/mesh/91-resident-dispatch-proof.md`).
- **Rules 2 / 2b / 2c / 3 — ask once, never a document, never flag, decide dev questions.** Percentages
  4.2 / 2.2 / 2.6 / 2.8% plus owner verbatim 2026-09-11 and *"these are dev questions, their not boss
  qs."*
- **Rule 5 — record decisions.** "He asked for documentation in 4.1% of turns, and repeatedly had to
  ask again because it was skipped."
- **Rules 8 / 9 — dollar signs break the renderer; do not make him think.** Owner verbatim 2026-09-24:
  *"why do you keep writing like this in funny font and no spaces"*; *"can you actually damn think
  about this instead of proposing all different ideas."*
- **Background-first shell** — the 120,000 ms default / 600,000 ms cap is a mechanism fact, no incident.
- **Prefer in-process file tools** — n=30 measurement on ZABZ-YOGA, `read` p50 0.76 ms vs `pwsh` ~700 ms.
- **Indexed search** — 100,075 ms vs 20 ms on `secratary`, 2026-10-08.
- **Heavy work asks the governor** — "seventeen sessions were generating simultaneously… commit at
  37 GB against 31.6 GB physical", 2026-09-16.
- **Short sessions / journal handoff** — the 52.5%-of-$54.92 measurement.
- **AI models never hardcoded** — owner verbatim 2026-09-15 plus the week-long silent failure.
- **Never destroy data / outbound hard-stop** — "lost customer data twice"; ticket #73890; pain P2477.
- **Owner queue** — "595 messages reached him as 'waiting for the owner' when 383 of them were
  engineering faults."

**Present with no evidence stated (the rule is probably right; as written it is unearned):** rule 6
("be blunt and short"), rule 7 ("say when you are wrong"), "one source of truth per thing", "verify,
do not assume", "provenance, always".

---

## 2. Stale, wrong, or unverifiable — **reproduced by the manager**

**2.1 `{cwd}` is a live templating bug.** `presets/zabz/agent.cordis.yml` line 24 renders
`Your working directory is {cwd}.` — single braces — while the composition's own `suffix` at line 20
already emits the same sentence with `{{cwd}}`, which is what the file's header documents and what
`yocheved` and `cordis-bg` use. **Confirmed live in the running session:** the manager's own system
prompt contains the literal `{cwd}`. Cost: 38 bytes of nonsense in every prompt of every step, on
every `zabz` session.

**2.2 Three statements name the wrong authority.** The persona says the autonomous company runs on
"a Linux server called `secratary`" (line 28), "The company's authoritative database is on `secratary`"
(line 89), and lists `secratary` as "Linux server, office LAN… and the authoritative database"
(line 110). `settings/machines/host-posture.tsv` says `secratary|frozen|…|FROZEN ROLLBACK ANCHOR.
cron is masked ON PURPOSE.` and `secratary-cloud|writable|…|THE AUTHORITY.` **The persona teaches the
exact alias confusion that the 2026-10-11 incident was about** — an agent read a masked unit on the
frozen box as breakage and re-enabled the company's writers there, creating 5,129 rows the authority
does not have.

**2.3 A machine is misidentified.** Line 111 calls `zabz-tech-linux` "a macOS mini for his employee
Yisroel". `host-posture.tsv` line 39: `zabz-tech-linux` = "Compute worker and vault"; line 43:
`lakewooechsmini` = "Yisroel's Mac mini".

**2.4 `AGENTS.md` §1 is wrong three ways.** It places the archive and the hourly scheduler on
`secratary` — a box whose cron is masked on purpose — while `transcript-archive-pull.py` line 63 and
`transcript-archive-server.py` line 666 name `secratary-cloud`. It names `scripts/push_vscode_chats.py`
and `scripts/vscode_chat_extractor.py`, **neither of which exists**. And it promises a complete archive
that pain `P2945` (2026-10-11) refutes: "holds no Copilot chat bytes at all, and ~11% of DSH sessions."

**2.5 `estate-systems` line 39** says "`secratary-cloud` and `secratary` hold the authority" — only
`secratary-cloud` does.

**2.6 `yocheved` contradicts its own config.** Line 51 says the company runs on `secratary`; the same
file's composition line 460 says `RETARGETED 2026-10-11: the authority moved from the office box
(`secratary-ts`) to `secratary-cloud`."

**2.7 `LakewooechsMini` ownership conflicts.** `yocheved` line 36 calls it "her main workstation now";
`host-posture.tsv` line 43 calls it "Yisroel's Mac mini… one-shot children only." Unresolved.

**2.8 Hardcoded model ids** are absent from the presets (good) but present in machine route config:
`settings/machines/LAKEWOOECHSMINI.yaml:62` and `DESKTOP-FGV6KMH.yaml:79` carry
`model: deepseek-v4-flash-vision-exp`.

---

## 3. Duplication — ~40% of the always-on persona restates something already written down

A 50-character shingle test found almost no *verbatim* overlap, so this is semantic restatement, not
copy-paste. The measured duplications:

| rule | where it is written | bytes |
|---|---|---|
| background-first shell | `zabz` line 65 (439 B) · `yocheved` 178-189 (1,299 B) · `cordis-bg` 32-44 (1,601 B) — the last two are **1,290 of 1,299 bytes identical** | ~3,300 |
| outbound hard-stop | `zabz` 96-102 (1,568) + `AGENTS.md` §4 (381) + `yocheved` rule 4 (~230) + `docs/outbound-comms-hard-stop.md` (4,157) | ~2,200 |
| "ask one question, never a document" | `zabz` rules 2/2b/2c/9 (~3,000) + `AGENTS.md` §2 (414) + §3 (342) | ~3,700 |
| the two-failures story | `AGENTS.md` §0 (1,648) + `estate-systems` lines 8-24 | ~1,200 |
| host-posture / authority | `zabz` line 89 (332) + `AGENTS.md` §5 (4,357, with the worked incident) + `host-posture.tsv` + `guard-service-state.sh` + `estate-systems` | ~4,700 |
| fast-search, **including its measurements** | `zabz` line 69 (1,265) restates the 9,707-byte skill | ~1,265 |
| parallel orchestration | `zabz` line 38 (1,235) restates rule 1b in the 10,802-byte skill | ~1,235 |
| "lost customer data twice" | `zabz` line 94 · `yocheved` 124 and 161 · `AGENTS.md` line 47 | ~300 |
| the two planes | `cordis-bg` 24-30 (~1,000) restates `editing-cordis-compositions` (14,413) | ~1,000 |
| within one persona | `zabz` line 165 repeats 143 (~215); `yocheved` 169 repeats 106 (~230) | ~445 |

**Conservatively 10-12 KB of the always-on `zabz` surface — about 40% of the 27.5 KB persona — is a
second copy of a rule that already lives in a skill or a doc.**

**Sections read once and never needed again**, all already written down elsewhere: journal mechanics
lines 120-139 (**4,682 B**, in the 14,613-byte `journal/README.md`); fleet + systems lines 106-118
(**1,111 B**, in `host-posture.tsv` and the systems register); outbound hardenings 96-102 (**1,568 B**,
already a doc); fast-search / governor / in-process measurements 67-71 (**3,588 B**, already in their
skills); mesh mechanics line 40 (**1,311 B**, already in the orchestration skill); the duplicate
paragraph (**215 B**); the broken `{cwd}` line (**38 B**). Moving those seven items roughly halves the
persona to ~14 KB **without losing a single rule** — keep the rule sentence plus a pointer.

---

## 4. Missing — rules the journal proves were learned the hard way, absent from the surface

1. **`L33` / pain `P13` — never `git add -A` in a shared working tree.** Eight concurrent sessions
   committed each other's files. Absent everywhere. (Rule 1b mandates fan-out and never says it.)
2. **`L217` — a `git worktree` is not a copy.** "Untracked files stay behind… the wrong control for
   environment-sensitive behaviour." The orchestration skill mandates worktrees and omits this.
3. **`L1462` / `P3135` — `origin` is a diverged two-URL remote.** `origin` fetches from
   `secretary-ts:` (the **frozen** box) and pushes to both that and GitHub; "every push half-fails."
4. **`P2938` / `L44` / `P13b` — never print a credential value.** The rule is an exact-key allow-list
   plus a shape assert, after a name-pattern mask leaked live API keys and a password-bearing DSN into
   the permanent transcript. The surface cites the leak only as archive-redaction precedent.
5. **`P3141` / `P3139` — mesh children land on nodes that do not have the repository.** Three of four
   children landed on such machines, so nothing that builds can be delegated. Rule 1c says fan out;
   nothing says check the landing.
6. **`P3136` / `P3140` / `P2947` — the authority is memory-bound.** ~7.4 GB peak on a 7.7/15 GiB box,
   14 OOM kills in 24 h, one unclean reset. **Nothing says "no heavy work on the authority."**
7. **`P2942` — the owner channel is gated.** 160 pending questions, 78 unanswered texts; the surface
   says "read the queue" but not that the reply path is blocked.
8. **`L1490` — a rule in one surface is not a rule.** "Check the surface the caller actually reads."
9. **The generator hazard** lives only in YAML comments (`agent.cordis.yml` 461-468) and is never
   injected into a session.

---

## 5. Cost, and what to do about it

**Always-on: 45,474 B (~11.4k tokens) for `zabz`; re-sent every step.** The measured cost rule on this
estate is `steps × mean context`, and the three most expensive sessions were 395-957 steps at
417-480k mean context — 52.5% of a day's $54.92.

**Recommended changes, in priority order** (the manager's ranking, on the child's evidence):

1. **Delete `zabz` line 24** (`{cwd}`). −38 B; removes an artefact from every prompt.
2. **Fix the authority in `zabz` lines 28, 89, 110** to `secratary-cloud`, and state that `secratary`
   is the frozen rollback anchor. This is the difference between a rule and a trap.
3. **Fix the machine list (line 111)** — `zabz-tech-linux` is not the Mac mini.
4. **Reconcile `AGENTS.md` §1** — correct host, drop the two scripts that do not exist, stop promising
   an archive `P2945` measures as incomplete.
5. **Move the journal-mechanics block (120-139) into `journal/README.md`.** −4.7 KB.
6. **Move lines 67-71's measurements into `fast-search` and a shell doc.** −3.6 KB.
7. **Replace lines 96-102 with one rule sentence plus the doc pointer.** −1.4 KB.
8. **Delete the duplicate paragraph at line 165.** −215 B.
9. **Move `AGENTS.md` §5's 4,357-byte incident narrative to `docs/mesh/142`.** −3.5 KB per repo session.
10. **Add the nine missing rules — into skills, not the always-on persona.**
11. **Deduplicate the shell policy across presets** — `yocheved` should inherit, not restate 1.3 KB.
12. **Fix `estate-systems` line 39** and the `LakewooechsMini` contradiction in `yocheved` line 36.

**Expected effect: always-on instruction from ~45.5 KB to ~20 KB, with no rule lost.**
