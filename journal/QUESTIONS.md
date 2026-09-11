# QUESTIONS — asked of the owner, not yet answered

**Rule:** when you ask the owner something, it goes here with the date. When he answers, the answer
is recorded in `DECISIONS.md` and the line here is marked answered. This file exists so the same
question is never asked twice — the previous system accumulated **313 pending questions, none created
after 19 July, the oldest 131 days old**, because nothing tracked them.

Check this file before asking anything. If the question is already here unanswered, the correct move
is usually to decide it yourself (see the persona: development questions are yours) or to escalate it
loudly rather than re-ask quietly.

| Asked | Question | Status |
|---|---|---|
| 2026-09-11 | The HA security system is blind: two door contacts are offline (since 2026-09-11 01:48) and every camera snapshot fails. Attempt a remote recovery now (reload Zigbee, retry the devices), or wait until someone is at the office on Sunday? | **open** — recommendation: remote recovery attempt now, because the failure is device-level and a reload is reversible; physical re-pair on Sunday if it does not take |
| 2026-09-11 | Phone access: Tailscale-only, or a public login-gated endpoint as well? | **open** — recommendation given (Tailscale); no answer needed until the console is reachable |
| 2026-09-11 | At the office on `ZABZ-TECH`, is it one long session per day or many short ones? | **open** — shapes how continuity should behave |
| 2026-09-11 | Why did Copilot usage collapse after April 2026 (May −75%, June −78%, July ≈0)? | **open** — never answered; the single most informative unknown about what he actually needs |
| 2026-09-11 | The company recorded **zero ticks for twelve consecutive days, 2026-07-23 .. 2026-08-03**. Was that a deliberate shutdown, or an outage nobody noticed? | **ANSWERED** — he did not know and asked for an investigation. Done: the host was **up and healthy every day**; the **work loop was dead** for **13d 17h**. Written up and labelled. → `DECISIONS.md` D16, `personal-secretary-mvp/docs/postmortem/2026-07-22-thirteen-day-silence.md` |
| 2026-09-11 | Multi-window: **one engine with 8-12 windows, or one engine per window?** Measured: an engine with its five MCP bridges costs ~1.4 GB, so 12 engines ≈ 17 GB against 7.7 GB free. Recommendation: one engine, many windows (`mode` switch keeps the other option). | **open** — question 1 of `docs/multi-window/QUESTIONS.md` |
| 2026-09-11 | Multi-window: **restore a window straight to a specific session?** A session is not addressable by URL today, so a restored window needs one click. Recommendation: accept the click now, and commission the client-side plugin that reads a session id from the URL as the next real piece of work. | **open** — question 3 |
| 2026-09-11 | Multi-window: **where should the windows sit, and what should "new window" be?** Default is a 4x2 grid on the primary display; the machine has three more 2560x1440 panels. Recommendation: keep the grid, add a desktop shortcut + hotkey for `dshw new`. | **open** — questions 2 and 4 |
**Answered and recorded elsewhere:**
- 2026-09-11 · Who the CEO is and what it owns → `DECISIONS.md` D1
- 2026-09-11 · Where the CEO sits relative to the secretary → D2
- 2026-09-11 · Sync architecture → D4
- 2026-09-11 · Deployment placement → D6
- 2026-09-11 · Harness source of truth → D7
- 2026-09-11 · Was the twelve-day silence deliberate? → **D16** (investigated: host up, work loop dead, 13d 17h)

| 2026-09-11 | Modesty model (A-BACK-014): keep it on HOLD, or should I get it *ready* to fund? Recommendation: prepare it for free (labelling spec, attribute rules layer, dataset plan, and a small labelled sample to prove the 5 attributes are learnable), then come back with a fixed price instead of the $850–1,600 band. Context: on 2026-09-09 the spend was refused while the on-device ML pipeline was **unverified** — it has since been verified on a real android-34 runtime (and the pipeline turned out to be *crashing* on first use, now fixed), so the layer the model slots into is now known to work. Options put to him: (1) prepare, don't spend [recommended]; (2) fund now, ~$1,200 over 5–6 weeks; (3) drop the custom model and ship Levels 1–3 on the existing NSFW/pose cascade. | **open** |

| 2026-09-11 | **Privacy posture for the modesty path: may family screenshots leave the device at all?** Options put to him: (1) **on-device only** — geometry + tiny classifiers, no VLM ever, attributes 3–5 capped at what geometry can measure; (2) **self-hosted arbiter** (recommended) — nothing to Google/OpenAI, ambiguous frames escalate to our own broker running a small open VLM, which the existing provider chain already supports via Ollama; (3) **third-party cloud** — cheapest and simplest, but private family screenshots reach a vendor API, where a third-party analysis found 14 of 25 OpenAI endpoints ZDR-ineligible as of Aug 2026. Created by the re-analysis in `docs/research/015-ai-capability-reanalysis-2026-09-11.md` §9: it only exists because the cost collapse made a cloud VLM the cheapest path, and the Feb-2026 plan never had to ask. | **open** |
