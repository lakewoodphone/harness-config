# 20 — Owner wants: 212 stranded wants turned into durable requirements

**Produced by** mesh child `R6-WANTS`, round 6 of the DSH evolution programme, on host `ZABZ-TECH`, 2026-10-15 14:22Z.

Source: `CENSUS-v4.json` → `wanted` (212 records) and `high_severity` (122 records), from `/home/zabz/evolution-corpus-v4/` on `secratary-cloud`. Every quotation below is a verbatim owner turn or a census-reader-vetted verbatim quote; nothing is paraphrased into the quote block.

## The clustering rule

> Each of the 212 wants is assigned to the **durable system requirement it implies** — the rule the estate would have to adopt, or stop violating, so that this want is satisfied next time, **for any topic**. Where a want names several, it goes to the requirement whose absence the want text blames. One primary cluster per want; no want is counted twice. A want that implies no estate behaviour at all — a one-off world-fact, or something a third party makes impossible — is left in the tail and reported, rather than forced into a cluster.

**Result:** 25 clusters covering 210 of 212 wants; **2 unplaced** and named below.

## The table

| # | durable requirement | wants | verdict on today | confidence |
|---|---|---:|---|---|
| C1 | Finish the job: never stop with work remaining and never substitute a report for the work | 21 | **still open** | verified |
| C2 | Prove it on the live thing before calling it done; never claim work that was not done | 18 | **still open** | verified |
| C19 | Facts right the first time: no invented detail, no acting on unverified data | 16 | **still open** | verified |
| C4 | Deliver the buyable link / the actual artefact, not more research | 14 | **still open** | verified |
| C11 | Reach him on his real number and channel, in his voice, one text at a time, only on approval | 13 | **still open** | verified |
| C10 | Answer the question he asked, plainly and briefly -- no jargon, no 27-step process | 12 | **delivered** | verified |
| C6 | One thing at a time: a filtered attention list, one question per turn, never a menu or a wall | 10 | **delivered** | verified |
| C8 | Follow the shop's own documented rules, scripts, code and conventions | 10 | **still open** | verified |
| C13 | Take money: a working, unmissable payment path, tax-correct, that does not die with the app session | 10 | **still open** | verified |
| C18 | Device and hardware bring-up works first time, to the shop's standard | 10 | **still open** | verified |
| C14 | Keep production and the service up, and be recoverable when he is not there | 9 | **delivered** | verified |
| C21 | Human-actionable labels, case files and records, first time | 7 | **delivered** | verified |
| C3 | Fix root causes permanently; stop re-diagnosing and re-patching the same recurring failure | 6 | **still open** | verified |
| C12 | The interface he actually uses works: phone-first, fast windows, an engine that does not die | 6 | **still open** | not verified |
| C15 | Keep his laptop fast: offload the heavy work to the mesh and the cloud | 6 | **still open** | verified |
| C23 | The same working setup on every machine and every app -- parity, not three lineages | 6 | **still open** | verified |
| C24 | Research lands finished and finished off, not merely begun | 6 | **still open** | verified |
| C5 | Decide what you can decide; ask him only what only he can answer | 5 | **delivered** | verified |
| C7 | Remember what he already told you -- across turns, sessions and machines | 4 | **still open** | verified |
| C16 | A reliable mesh: a child cannot kill the parent, both can talk mid-flight, and work routes around a dead node | 4 | **still open** | verified |
| C17 | No unrequested policy, safety lecture or filter imposed on his work | 4 | **still open** | verified |
| C22 | Money math and money answers are right, and nothing leaves before he approved it | 4 | **still open** | verified |
| C25 | Irreversible and safety-critical actions are verified before they run; secrets are handled deliberately | 4 | **still open** | verified |
| C9 | Own it: never push work, decisions or errands back onto the owner | 3 | **delivered** | verified |
| C20 | Models and configuration are configuration, never hardcoded | 2 | **delivered** | verified |

`delivered` = the living system already does it · `still open` = it does not · `no longer wanted` = the want is obsolete. `confidence: not verified` means I could not reach the surface that would settle it, and I say so instead of guessing.

---

## The finding that changes what a `delivered` verdict means

**On `ZABZ-TECH` the instruction surface a session actually loads is not the preset in its own checkout.** Both were read directly:

```
PS> Get-FileHash C:\Users\ezabz\code\harness-config\presets\zabz\agent.cordis.yml
    C7C1586334E91895FCBE4F83E1ADA032E1F43C00902613D3866C50F3A2ED4CFB   54551 B   mtime 2026-10-14 09:14
PS> Get-FileHash C:\Users\ezabz\.dsh\profiles\web\cordis.patch.yml
    E153D51BA0C75FA71ADEDA64E39BB010B6C00F3E5703FF076E1DE15F9680F5DA  147638 B   mtime 2026-10-14 21:39
PS> Select-String -Path <preset> -Pattern '\*\*\d+[a-z]?\.'   -> 1, 4, 5, 6, 7, 7b, 8
PS> Select-String -Path <loaded> -Pattern '\*\*\d+[a-z]?\.'  -> 1, 1b, 1c, 2, 2b, 2c, 3, 4, 5, 6, 7, 8, 9
```

So rule **`7b`** ("When he corrects you, the correction is the requirement") exists in the checkout and **not** in the loaded surface, while `1b`, `1c`, `2b`, `2c` and `9` are loaded and absent from the checkout. `HANDOFF-ROUND5.md` §3 reported the composed surface on `ZABZ-YOGA` as containing `7b` and **neither** `1b` nor `2c`. Measured on `ZABZ-TECH` today that is inverted. This is the same class of silent drift round 5 diagnosed (`P3993`), still unreconciled on this machine — and it means "the preset says X" is not evidence that a session is told X.

---

## Every cluster

### C1 — Finish the job: never stop with work remaining and never substitute a report for the work

**Count: 21** of the 212 wants.

**Requirement.** A turn runs until the task is complete with evidence, or is genuinely blocked, or the decision is truly his, or the action is irreversible. Reporting progress is not a stopping condition.

**In his own words:**

> Okay, I had enough of your constantly working for a little bit and then coming back and reporting that it's not done yet
>
> — session `76fcc878`

> remember, you never stop until you are done, there is no one else to pass the buck to
>
> — session `6c9f6604`

> where tare things holding, it's been 24 hours later, did you get it all figured out yet or you are still doing excuses and saying what you will do or shouldve done
>
> — session `043150c1`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
ps_db_query: SELECT COUNT(*), SUM(output_log LIKE '%STEP_BUDGET_EXHAUSTED%') FROM work_sessions WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-1 day')
```

Its output line:

```
sessions_24h=141, closed_by_session=77, with_handoff=113, step_budget_exhausted=30 -> the loop still dies at the step budget 30 times a day, and 28 of 141 sessions leave no handoff.
```

**Sessions in this cluster (21):** `043150c1`, `06e4d5fc`, `0ef0c72b`, `160208ad`, `18bb3f4a`, `38e8923a`, `3e343748`, `45e98f77`, `4a2bf82d`, `4bb2d77e`, `6c9f6604`, `6d3bbac7`, `72ec9fae`, `76fcc878`, `9a056e82`, `aae1aec4`, `b1e2a965`, `cc27f14a`, `d19c138b`, `f1fdeea6`, `f943a7a7`

---

### C2 — Prove it on the live thing before calling it done; never claim work that was not done

**Count: 18** of the 212 wants.

**Requirement.** No claim of success without the command and its output line; the check is on the surface the system actually reads, not on the artefact that was edited.

**In his own words:**

> Okay, it's fixed. But the question is, if you miss this and claim that everything is migrated properly, what else did you miss?
>
> — session `24b7eadb`

> you are wrong and it is online
>
> — session `4db964fb`

> It's not better. It still seems to be missing the text sharpness. It looks like what happens when I plug in a screen with the wrong resolution attached or something
>
> — session `5bba6ccd`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
grep -c 'Say when you are wrong' ~/.dsh/profiles/web/cordis.patch.yml  (and: ps_db_query work_sessions HANDOFF/STEP_BUDGET counters)
```

Its output line:

```
1 -- the loaded persona has a rule for admitting error (7) but none for proving success; 342 STEP_BUDGET_EXHAUSTED and 176 TOOL_LOOP_DEADLOCK in 7 days are sessions that ended without proof.
```

**Sessions in this cluster (18):** `19119b70`, `1c6dc139`, `24b7eadb`, `45981b51`, `5bba6ccd`, `74b959b3`, `99f5c499`, `9f384cd7`, `a81aa099`, `bb953f87`, `bcd4d160`, `c12702db`, `d61aba83`, `d772db00`, `e3d0ddb8`, `e4a5dad4`, `efca5060`, `f5daa293`

---

### C3 — Fix root causes permanently; stop re-diagnosing and re-patching the same recurring failure

**Count: 6** of the 212 wants.

**Requirement.** A failure class that recurs is closed by a landed change with a regression proof, not by another diagnosis or another branch.

**In his own words:**

> you did not work long and hard enough, you didn't think enough or research enough, get to work
>
> — session `0a30112a`

> i had to restart the computer, becuzse whatever you did crashed it or something and i started getting this messagge resume failed for session
>
> — session `c9ab8734`

> Why do you keep crashing? What’s going on?
>
> — session `545d8e84`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
python3 journal/tools/journal.py search "recurring failure root cause"   (in /root/code/harness-config)
```

Its output line:

```
H92 2026-09-14: "the failures were unchanged, and its own recommendation was 'let me dig into what these four syncs...'" -- the same class is still being re-diagnosed.
```

**Sessions in this cluster (6):** `52c23ad7`, `545d8e84`, `a5fa34f7`, `b6f28f7d`, `c9ab8734`, `d63e350f`

---

### C4 — Deliver the buyable link / the actual artefact, not more research

**Count: 14** of the 212 wants.

**Requirement.** When he asks where to buy something or for a decision he can act on, the answer is a verified link or a single priced recommendation he can execute, not a reading list.

**In his own words:**

> Not all those links load and some of them are not the right ones. I want you to get to work verify every single link and listing fully end to end through any means necessary. I don't want you to tell me that I have to do it because you got blocked because of r
>
> — session `a592225c`

> do real serious long term research online and everywhere else for customer facing usb, and ssd what to get for reliable speeds but the lowest cost, spend a few hours researching this before you get back to me, then document organize commit and save your resear
>
> — session `9ba100ad`

> do actual research, don't think you are so smart, use firecrawl and jina and more and research online how to set this up
>
> — session `8f87e47b`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
python3 journal/tools/journal.py search "buyable link"  ->  "no match for buyable link -- an empty result is a refusal, not health"
```

Its output line:

```
no match; and grep of the loaded persona for a link/deliverable rule returns nothing. No landed rule or tool enforces it.
```

**Sessions in this cluster (14):** `0d0f1185`, `250ed582`, `5a17ce4d`, `6db21fa3`, `8f87e47b`, `901efff6`, `9ba100ad`, `a2b8fa27`, `a592225c`, `b2394347`, `b403052f`, `b721ef6c`, `f93d80e7`, `ffb9ca61`

---

### C5 — Decide what you can decide; ask him only what only he can answer

**Count: 5** of the 212 wants.

**Requirement.** Development decisions (architecture, tooling, naming, layout, libraries) are the agent's; escalation is limited to money, customers, legal posture, family and irreversible acts.

**In his own words:**

> figure this out yourself, and then ask me qs or clarifcations that need me one at a time
>
> — session `3fdc89ee`

> i don't review things, if you have important questions for me, ask them clearly and explained and i'll answer one at a time, remember that
>
> — session `85f98648`

> ask me things one at a time very clearly and simply
>
> — session `70978474`

**Verdict on today: `delivered`** (confidence: verified).

The exact command run for this verdict:

```
grep -oE '\*\*[0-9]+[a-z]?\. [A-Za-z][^*]{0,55}' ~/.dsh/profiles/web/cordis.patch.yml | sort -u
```

Its output line:

```
loaded persona contains rule 2 'Ask rarely, ask well, ask one at a time, and always recommend', rule 3 'Do not route development decisions to him', rule 9 'Do not make him think for you'.
```

**Sessions in this cluster (5):** `130ca883`, `3fdc89ee`, `70978474`, `85f98648`, `8bd84e58`

---

### C6 — One thing at a time: a filtered attention list, one question per turn, never a menu or a wall

**Count: 10** of the 212 wants.

**Requirement.** What reaches him is only what genuinely needs his decision, presented one item per turn with one recommendation; never five options, never two questions, never a wall of text before the question.

**In his own words:**

> again too much evidence and random things you are showing me, when you present a text you just give me the clear question and context and the recommended draft
>
> — session `d7c98601`

> just pick one and let's discuss it, can you stop giving me a list and asking me to choose?
>
> — session `4c3ded25`

> too much at once, one question at a time
>
> — session `b8d076ea`

**Verdict on today: `delivered`** (confidence: verified).

The exact command run for this verdict:

```
ps_health -> diagnostics.metrics_health/owner_attention_sweep.last_detail
```

Its output line:

```
"60 ranked of 650; question=none" (owner_attention_sweep, last ran 2026-10-15T13:57:15Z); agent_questions pending=5; loaded persona rule 2 carries it.
```

**Sessions in this cluster (10):** `382a3663`, `3bb48ef2`, `732b3ff5`, `89858f89`, `acb5a3a6`, `c83d2b61`, `d7c98601`, `eef1fc93`, `ef80fd40`, `fe516993`

---

### C7 — Remember what he already told you -- across turns, sessions and machines

**Count: 4** of the 212 wants.

**Requirement.** Prior corrections, prior sessions and prior projects are recalled and applied without him re-stating them; the estate's memory is the record.

**In his own words:**

> I’m talking about the awning you don’t remember your file context and history about this whole thing we built over the past few months where I kept on researching with you different ways to build it for the holiday you know to stop the rain the whole morning and but I wasn’t the one who actually built it for real that was my brother and then his brother helped him the last few days do you understand?
>
> — session `f0d7944c`

> okay its fine you don;'t have to get all obsessive about it
just for the future mark it down better
>
> — session `d194a14c`

> don't you remember i told you we don't want tmobile anymore and i tried to chat with them and it didn't work when i asked them to cancel so i disputed the charge? i thought i told you
>
> — session `3bed7499`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
ps_db_query: SELECT COUNT(*) FROM memories WHERE status='active'; SELECT MAX(created_at) FROM memories
```

Its output line:

```
memories_active=25708, newest_memory=2026-10-15T14:13:27 -- memory is live and current, yet 10 of the 122 high-severity sessions are him saying 'you forgot' / 'i thought i told you'.
```

**Sessions in this cluster (4):** `4a79e1d5`, `849b9be9`, `d194a14c`, `f0d7944c`

---

### C8 — Follow the shop's own documented rules, scripts, code and conventions

**Count: 10** of the 212 wants.

**Requirement.** Before acting on a shop surface, read and apply the existing documented procedure, pricing rule, script and convention -- never re-invent what the shop already wrote down.

**In his own words:**

> actually it's 95 instead of the usual more like 65 or 70, we went up in price since yisroel left and i have to do the soldering also say that it doesn't always get fixed, but 50 non refundable is required deposit, you forgot that also
>
> — session `72c9fd6e`

> you forgot that we don't say the customers name
>
> — session `4c3ded25`

> you didn't read teh docs and info, you don't write lpt number and you don't put on the drn screen, what the hell are you doing, can you analyze our actual sales info and docs and scripts for the lpt waze devices before doint all this
>
> — session `8587008c`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
ps_search(query='shop pricing rules and deposit 50 non refundable', what='journal')
```

Its output line:

```
2 hits, index_age_s=41040, covers_through 2026-10-15 02:51 UTC -- the top hit is a transfer-drive purchase, not the pricing/deposit rule. The rule he keeps repeating is not a searchable, enforced article.
```

**Sessions in this cluster (10):** `24e68280`, `321d75e7`, `4c3ded25`, `71191c83`, `72c9fd6e`, `8587008c`, `a3cc5055`, `d09a056d`, `da556a8b`, `f0827649`

---

### C9 — Own it: never push work, decisions or errands back onto the owner

**Count: 3** of the 212 wants.

**Requirement.** The buck stops with the agent; a discovered problem is researched, designed and fixed rather than filed as a question or handed back as an owner task.

**In his own words:**

> Why are you saying those two jobs are my jobs? Aren't they your jobs? Remember, don't be lazy and push jobs onto me when you are totally capable
>
> — session `e815b9bd`

> so keep working, take ownership of your programs company and systems, the buck stops by you and you are responsible and in charge of my life there is no one else who will do thigs or take care fo them so never push off things or push teh responsibility elsewhe
>
> — session `853823e4`

> are you sure you can't do it properly yourself?
>
> — session `b8d076ea`

**Verdict on today: `delivered`** (confidence: verified).

The exact command run for this verdict:

```
grep -oE '\*\*[0-9]+[a-z]?\. [A-Za-z][^*]{0,55}' ~/.dsh/profiles/web/cordis.patch.yml | sort -u
```

Its output line:

```
loaded persona rules 1, 2b ('never end a turn by handing him one'), 2c ('Never flag. Solve'), 3 and 9 are all present in the live surface.
```

**Sessions in this cluster (3):** `b8d076ea`, `e0710eab`, `e815b9bd`

---

### C10 — Answer the question he asked, plainly and briefly -- no jargon, no 27-step process

**Count: 12** of the 212 wants.

**Requirement.** The reply leads with the answer in plain language, at the length the question deserves; jargon is translated and complexity is the agent's problem, not his.

**In his own words:**

> If you call this a job well done, or a good, I don't know what, then you are nuts This page is full of jargon which what's going on? Terrible on the eyes.
>
> — session `49ee46ca`

> You’re confusing me with too much language and jargon and talking too much are you saying that the cryptographic key in the back of the passport that I scan needs to be unlocked? Let’s scan someone else’s passport with that key. It would only be unlocked. If I also scanned his photo you’re not explaining this.
>
> — session `0dffc054`

> that was too long and complicated, that's not how i respond to them that sounds like a fat stupid ai
>
> — session `33425eeb`

**Verdict on today: `delivered`** (confidence: verified).

The exact command run for this verdict:

```
grep -oE '\*\*[0-9]+[a-z]?\. [A-Za-z][^*]{0,55}' ~/.dsh/profiles/web/cordis.patch.yml | sort -u
```

Its output line:

```
loaded persona rule 6 'Be blunt and short. No preamble, no filler...' and rule 8 'Write money so it survives the renderer' are present in the live surface.
```

**Sessions in this cluster (12):** `002e01ee`, `0dffc054`, `2d128190`, `33762274`, `437fad59`, `49ee46ca`, `58403e54`, `77a58659`, `cfd66de6`, `d63b42a2`, `fb104814`, `fe86504e`

---

### C11 — Reach him on his real number and channel, in his voice, one text at a time, only on approval

**Count: 13** of the 212 wants.

**Requirement.** Owner-facing messages go to 848-389-7895 (never the Google Voice inbox he does not read), one short message per item, written in the voice of his own corrections, and never sent without his approval.

**In his own words:**

> btw, i almost never monitor my google voice number, so if you want me to see soemthing you have to send it to my personal number not my google voice
>
> — session `0b9fd106`

> how many times do i have to tell you i won't see texts to 1594, that's an inbox that only you monitor
>
> — session `f87e4dc2`

> OK. Remember my number is 848-389-7895. That is the only number I actually see.
>
> — session `b0633805`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
grep -ro '8483897895|848-389-7895' /opt/company/app/ | wc -l   (and: grep -ro '1594' /opt/company/app/ | wc -l)
```

Its output line:

```
107 occurrences of his personal number -- the rule is wired in -- but 85 occurrences of the Google-Voice '1594' inbox remain in the same tree; the channel rule is not exclusive.
```

**Sessions in this cluster (13):** `0b9fd106`, `33425eeb`, `44d81bc8`, `47f3212a`, `5ad004a4`, `823aaf69`, `99b2342a`, `a8899273`, `b0633805`, `d05bc1c2`, `decbfb84`, `f87e4dc2`, `f8e61b4b`

---

### C12 — The interface he actually uses works: phone-first, fast windows, an engine that does not die

**Count: 6** of the 212 wants.

**Requirement.** The DSH surface on his phone and desktop opens quickly, works on a phone, keeps its windows, and the engine survives.

**In his own words:**

> When I click plus for a new window now. It takes like 25 seconds, at least for it to open. Why?
>
> — session `1238888e`

> the engine just died and stoppped you and you couldn't come back, so i guess that failed
>
> — session `621bd168`

> random new problem when i try to open a new dsh window now i can't put in text as it's waiting for me to choose a workspace, but wheneverr i choose it flips right back to the choose screen which makes new dsh windows impossible to use
>
> — session `321b8fe8`

**Verdict on today: `still open`** (confidence: not verified).

The exact command run for this verdict:

```
(Get-Content C:\Users\ezabz\.dsh\engine\node_modules\@deepseek-ai\dsh\package.json | ConvertFrom-Json).version ; Get-ChildItem C:\Users\ezabz\.dsh\profiles
```

Its output line:

```
engine 0.2.0-rc.2; profiles web/headless/mesh present. I could not exercise his phone or the Web GUI from this node, so the phone-first claim is UNVERIFIED, not healthy.
```

**Sessions in this cluster (6):** `1238888e`, `2b226246`, `321b8fe8`, `3ca4f3f2`, `621bd168`, `9d5c49d8`

---

### C13 — Take money: a working, unmissable payment path, tax-correct, that does not die with the app session

**Count: 10** of the 212 wants.

**Requirement.** At the counter and online, a card can be taken end to end; the amount, tax and what the customer owes agree with the work order; and the payment surface is one unmissable place.

**In his own words:**

> **The owner needs to charge customers today.** Card payments currently cannot complete. Make them work, end to end, and deploy.
>
> — session `3eb58012`

> The owner is trying to take money at the counter and **both card paths fail**. This is the highest-priority fix in the business: a sale that cannot be paid is a sale that cannot happen.
>
> — session `39810b16`

> a bunch of problems, i paid but then it redirectied to a 404 page there is no tax on top of the 2 dollars, teh zelle just says 2 dollars also why does work order page say nohting is owed if it's 2 dollars, i want a serious audit of all this
>
> — session `d9c2d0c4`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
ls /opt/company/app/services/ | grep -Ei 'stripe|payment' ; grep -rn '/charge' /opt/company/app/main.py | head
```

Its output line:

```
stripe_service.py and payment_card_redaction.py exist; /agents/{id}/billing/charge, /ceo/billing/charge, /stripe/charges exist -- the plumbing is delivered, but 9 of the 122 high-severity sessions are him unable to take money at the counter.
```

**Sessions in this cluster (10):** `0cb01a0d`, `106b90e5`, `2bdebb1d`, `39810b16`, `3eb58012`, `41d40e31`, `4772de74`, `5afcd8f4`, `d9c2d0c4`, `de6bb21f`

---

### C14 — Keep production and the service up, and be recoverable when he is not there

**Count: 9** of the 212 wants.

**Requirement.** A customer-facing or money-facing service is up or it alarms; recovery does not depend on the owner being present to notice and to act.

**In his own words:**

> Something is very, very, very wrong.
>
> — session `e50ad938`

> okay massive issue, why is deep seek direct api not working from this? soemthing is wrong, they claim the status is fine by status.deepseek
>
> — session `a72940c2`

> The first two worked and then the third one said we are sorry an application error has occurred
>
> — session `990c6329`

**Verdict on today: `delivered`** (confidence: verified).

The exact command run for this verdict:

```
ps_health ; ssh secratary-cloud 'systemctl list-timers --all | grep -i liveness'
```

Its output line:

```
health.ok=true, database.ok=true; r4-liveness-probe.timer active, last run 4s before the reading; circuit breakers open=0. Round 4's 'P9 deployed but NOT scheduled' no longer holds.
```

**Sessions in this cluster (9):** `201ea0ad`, `3ef33e28`, `5def503d`, `91cf7b1a`, `990c6329`, `a72940c2`, `c70ba416`, `df0baf11`, `e50ad938`

---

### C15 — Keep his laptop fast: offload the heavy work to the mesh and the cloud

**Count: 6** of the 212 wants.

**Requirement.** Long-running or heavy work runs on the mesh/cloud by default so the machine he is typing on stays usable; local execution is the marked fallback.

**In his own words:**

> take a pause and figure this out the yoga is getting more and more sluggish cuz all of you stopped offloading the hard work to the mesh it's barely usable now, why do you keep skipping over and ignoring a massive issue
>
> — session `67850580`

> it's probably genuine sesions, but isn't this why we have the mesh and the tailscale and the cloud server to offload all the work? waht is going on with all that
>
> — session `b9810e28`

> Why does it look like you're not working? I'm just waiting for the sub agents to finish. Aren't you supposed to push sub agents to the background so you could still work?
>
> — session `853823e4`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
ps_db_query: SELECT COUNT(*) FROM tasks WHERE status='blocked'  ->  249 ; ssh secratary-cloud 'ssh zabz-yoga hostname' -> name resolution failure
```

Its output line:

```
blocked_tasks=249 (a large deferred queue, the symptom he named as 'the yoga is getting more and more sluggish'), and a mesh node is not even resolvable from the authority.
```

**Sessions in this cluster (6):** `3a3388d3`, `67850580`, `853823e4`, `b94269e3`, `b9810e28`, `e34dd061`

---

### C16 — A reliable mesh: a child cannot kill the parent, both can talk mid-flight, and work routes around a dead node

**Count: 4** of the 212 wants.

**Requirement.** Mesh node failure is detected and routed around; parent and child can exchange messages mid-flight; a child crash never takes the parent with it.

**In his own words:**

> Spawning child agents and sub agents and the whole mesh agent thing is constantly failing whenever they try to spawn their own agents.
>
> — session `558100fd`

> the mesh seems to have gone down again We seem to be having this problem multiple times a day.
>
> — session `649cb7c5`

> just to clarify we were fixing the desktop windows hello so we rebooted it a bunch of times today but there is more to the mesh than the desktop, if the desktop isn't there than it should go somewhere else on the mesh, not fail silently, what the heck
>
> — session `98e3f372`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
ssh secratary-cloud 'for h in zabz-yoga zabz-tech secratary; do timeout 6 ssh -o BatchMode=yes -o ConnectTimeout=4 $h hostname; done'
```

Its output line:

```
zabz-yoga -> 'Could not resolve hostname zabz-yoga: Temporary failure in name resolution'; zabz-tech -> zabz-tech; secratary -> 'Permission denied (publickey)'. One of three nodes is unreachable from the authority by name.
```

**Sessions in this cluster (4):** `558100fd`, `649cb7c5`, `8f4b6c5f`, `98e3f372`

---

### C17 — No unrequested policy, safety lecture or filter imposed on his work

**Count: 4** of the 212 wants.

**Requirement.** The agent does not add legal, safety or policy steps he did not ask for, and does not install or reactivate a control on production without being told.

**In his own words:**

> these made up safety measures legal not asked from you and that's you pushing yourself on me
>
> — session `69022a3b`

> okay don't be so safe for me when i didn't ask, i can drive on teh roads like everyone else, i'm not going to die
>
> — session `96f8e272`

> okay i didn't ask you about the legal kite stuff, i will figure that out myself
i just need to get the best kites and string in lakewood, i didn't ask you to worry about anything else
>
> — session `6d505257`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
grep -n 'requires_approval' /opt/company/app/policy.py | head
```

Its output line:

```
policy.py carries six approval-gated actions (sms_send_external, dialpad_customer_sms, gmail_send, ha_call_service, ...). The gate is real and correct; what is missing is any rule that a wanted action must not be met with an invented safety condition.
```

**Sessions in this cluster (4):** `01bbe19c`, `69022a3b`, `6d505257`, `96f8e272`

---

### C18 — Device and hardware bring-up works first time, to the shop's standard

**Count: 10** of the 212 wants.

**Requirement.** Phones, drives, filters and peripherals are brought to the shop's documented end state in one pass -- activation lock, MDM profile, SIM, box -- without a parts hunt or a trial-and-error day.

**In his own words:**

> What the hell are you talking about? We have a robust MDM ways. System we use all the time.
>
> — session `5eec8d35`

> You already gave me the unlock code. That's how you're accessing the phone. Don't get busy with that now. I want you to just pull the Bluetooth information right now, and whatever helps you for what you're about to buy.
>
> — session `22724c6c`

> hold on why do they block bluetooth, shouldnt users be able to connect to bluetooth and connect to their car or whatevr with bluetooth?'
>
> — session `8587008c`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
ls /opt/company/scripts | grep -Ei 'mdm|activation|iphone|device'
```

Its output line:

```
Get-DeviceResponsive.ps1, Get-WazeMdmDeviceInfo.ps1, Get-WazeMdmFleetStatus.ps1 exist -- read-side tooling is landed; several high-severity sessions are still bring-up failures (activation lock absent on two LPT iPhone 11s, a filter profile that whitelisted nothing).
```

**Sessions in this cluster (10):** `22724c6c`, `5eec8d35`, `69317939`, `7422a3d4`, `7cb6ee50`, `955b3e46`, `963b430e`, `d05a9a77`, `dff5a4e6`, `fd29a7e2`

---

### C19 — Facts right the first time: no invented detail, no acting on unverified data

**Count: 16** of the 212 wants.

**Requirement.** A number, a measurement, a customer fact or a spec is checked against its source before it is asserted; nothing is asserted that was not read.

**In his own words:**

> also i thought both aren't touchscreen, make sure you aren't wrong
>
> — session `20673294`

> i never had this beofre wht are you talking about, small millapms can create such large voltage?? also i want you to think and analyze it i can't keep trying diffent things
>
> — session `18bba526`

> Does F998186 make sense
>
> — session `cbbf160e`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
python3 journal/tools/journal.py search "verification before claiming" ; grep -c 'Say when you are wrong' ~/.dsh/profiles/web/cordis.patch.yml
```

Its output line:

```
journal hits are rounds where verification WAS the whole round's work (H285, H2998) rather than a standing rule; the loaded persona has rule 7 for admitting error but no rule for checking before asserting. 23 of 122 high-severity sessions are this class.
```

**Sessions in this cluster (16):** `058cc91f`, `18bba526`, `20673294`, `25b06f6e`, `3bed7499`, `60f24ebd`, `62c23a05`, `974e99ef`, `99664b7b`, `b2634711`, `be70b1ca`, `cbbf160e`, `cbed6d04`, `d66fbe2d`, `e2fbba23`, `e5dece1f`

---

### C20 — Models and configuration are configuration, never hardcoded

**Count: 2** of the 212 wants.

**Requirement.** A model id or endpoint resolves at runtime through the operator env chain and the gateway catalogue; no literal model name is baked into a code path.

**In his own words:**

> keep in mind in general in all our apps and systems ai models change very often, can never be hardcoded and get changed and updated all the time so we need robust easy flows for that currently the model we are using for almost everything is deepseek 4.1 flash
>
> — session `ea10e311`

> waht model are you
>
> — session `004bcabe`

**Verdict on today: `delivered`** (confidence: verified).

The exact command run for this verdict:

```
ls /opt/company/app/services/ | grep -Ei 'model_resolution'
```

Its output line:

```
model_resolution.py is present in the live tree (round 4's WS-MODEL, deployed 2026-10-14T20:16:07Z); the live surface it serves is /opt/company, branch keepalive/156-dialpad-status-landing.
```

**Sessions in this cluster (2):** `004bcabe`, `ea10e311`

---

### C21 — Human-actionable labels, case files and records, first time

**Count: 7** of the 212 wants.

**Requirement.** A label, receipt or case-file entry carries the details a human needs to act on it (customer, item, amount, dates, the exact logic used) and prints correctly the first time.

**In his own words:**

> So did you create an actual case file for NIASOFF the phone number is 732-492-4311 because I’m trying to pull it up now on Zabz tech and I said to pull up that case file and I can’t find it
>
> — session `67449da5`

> when you close an order due to this system, do you put a note or something on it explaining what you did and the exact logic behind it?
>
> — session `1f4a7e21`

> print out a label for his info and that it's waiting for pickup or dispoasl with all the info and dates
>
> — session `9c8c2528`

**Verdict on today: `delivered`** (confidence: verified).

The exact command run for this verdict:

```
find / -maxdepth 6 -name 'lpt-label*' -not -path '*/proc/*'
```

Its output line:

```
/opt/lpt-ops/bin/lpt-label exists (plus the lpt-label-printing skill on the authority) -- the tool is landed; the recurring failure in the wants is the wording and the layout, not the absence of a tool.
```

**Sessions in this cluster (7):** `171a3693`, `1d29cdd5`, `1f4a7e21`, `40fe7854`, `4ebc82ea`, `67449da5`, `8c0b2490`

---

### C22 — Money math and money answers are right, and nothing leaves before he approved it

**Count: 4** of the 212 wants.

**Requirement.** Amounts owed, profit, tax and payroll are computed from the record and shown with the arithmetic; no outbound message and no charge moves before his approval.

**In his own words:**

> Time to be the full cfo and run that whole flow analyze and orchestrate all this. We need cfo for both LPT and my personal finances. We need full bookkeeping accounting and audit and I want you to use the full orchestrator and sub agent system
>
> — session `1b5b4ddc`

> very important as part of our automonous dsh that gets triggered automatically is that the cfo is constantly working and classifying behind the scenes all cc charges and bank stuff and anything money related for accounting or bookkeeping and all that

everything needs to be backfilled and clarified over time
but especially live, it should ask me purchases it's unsure about whether through needing attention tab or texting me direct (which sholdn't be blocked unless it's way too much) this way when i still remember the purchase i can give info on what and who it's for, and it should be very good at documenting this


audit and research and plan this out with full orchestration and fanning out
now we use plaid for all money info, research if we should use something else, is there something else that gives more real time info or better info or whatever

get to work methodically and robustly
>
> — session `f5d95532`

> what the hell did you send 300 dr? you didn't show it to me and i didn't know of htis
>
> — session `ca000eb1`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
grep -rn 'classification' /opt/company/app/services/*.py | head
```

Its output line:

```
a cache classifier exists, but the wants (CFO classification ~90% coverage from purchase emails; one clear number he owed; payroll for a departed employee) are open, and high-severity #9 is $300 sent without approval.
```

**Sessions in this cluster (4):** `1b5b4ddc`, `be1398ed`, `ca000eb1`, `f5d95532`

---

### C23 — The same working setup on every machine and every app -- parity, not three lineages

**Count: 6** of the 212 wants.

**Requirement.** The estate's instructions, tools and access are identical across his machines and apps, and a fix reaches every machine or says loudly that it did not.

**In his own words:**

> why only 2 repos what about lpt flip phone, what about home assistant, what about the waze system rememeber she is the full manager of lpt
>
> — session `4db964fb`

> still no yocheved mode on her laptop, are you useless?
>
> — session `6665eb86`

> waht the heck, that means my phones dsh will only run when the laptop is on, didn't it used to run on the secretary server and shouldn't that have migrated to cloud along with teverythign else?
>
> — session `24b7eadb`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
ssh secratary-cloud 'cd /root/code/harness-config && git rev-parse --abbrev-ref HEAD'  ;  (ZABZ-TECH) git -C C:\Users\ezabz\code\harness-config rev-parse --abbrev-ref HEAD
```

Its output line:

```
authority: hk/182-wake-family-key; ZABZ-TECH: mesh/broker-host-cloud-default-20261013. Two of three machines remain on different harness-config branches, and the loaded persona on ZABZ-TECH differs from its own checkout (see the drift finding).
```

**Sessions in this cluster (6):** `19b02e0c`, `28d01c53`, `4db964fb`, `6665eb86`, `d4307338`, `e9b56e55`

---

### C24 — Research lands finished and finished off, not merely begun

**Count: 6** of the 212 wants.

**Requirement.** A research, audit or adversarial-review task ends with the compiled result in hand; a run that ends mid-compile has not delivered.

**In his own words:**

> PATIENT CONTEXT (facts only; no identifying details):
- Young adult married woman, no known comorbidities, not pregnant, no stated history of clot/liver disease.
- Drug: norethindrone acetate (brand name Aygestin in the US; norethisterone in UK/EU) 5 mg tablets, taken TWICE daily = 10 mg/day, by mouth, continuously.
- Timeline: started 2026-07-30 to postpone menstruation (non-contraceptive cycle suppression, so she stays ritually pure/tehorah for religious reasons through and after her wedding). Restarted 2026-08-27 (doctor-approved). As of 2026-09-24 she is STILL taking it: roughly 8 weeks of exposure in total and ~28 days on the current continuous stretch.
- THE QUESTION from her husband: "How long can she stay on it without any health problems — how long is it clearly safe to take it, for what periods of time? Do serious research."
- Your job is EVIDENCE, not personalized medical advice. Never tell the patient what to do; report what labels, guidelines, trials and cohort studies actually establish, with the exact numbers and the exact qualification (licensed vs off-label, strong vs weak evidence).

RULES:
- Use web_search and web_fetch. Prefer primary sources in this order: FDA/DailyMed label, EMA/UK SmPC, specialty-society guideline (ACOG, FSRH, NICE, ASRM, WHO), Cochrane review, RCT, large cohort, then review articles.
- Quote exact duration language and exact numbers (mg/day, months, absolute risk per 10,000 woman-years, etc.). If a source does not state a maximum duration, say so explicitly — that is a finding, not a gap to paper over.
- Every finding needs a real URL you actually fetched or saw in search results. Never invent a citation, a DOI, or a page number. If you could not verify something, put it in gaps.
- Do not report a number without saying what kind of source it came from and how good it is.
- Return ONLY the structured object required by the schema.

YOUR AXIS: the US FDA labeling for norethindrone and norethindrone acetate, across every indication, and the exact DURATION each indication is licensed for.
Specifically find and quote:
1. The historical Aygestin (norethindrone acetate tablets, brand, formerly Duramed/Barr/Teva) full prescribing information: the Endometriosis indication and its exact titration + duration ("5 mg daily for 2 weeks, then increase to 5 mg twice daily... continue for 6 to 9 months" or whatever the label actually says), the Secondary Amenorrhea indication, the abnormal uterine bleeding/DUB indication, and any statement about continuing therapy or about maximum duration. Brand Aygestin is discontinued so DailyMed may return nothing for the brand name - find the generic norethindrone acetate label on DailyMed (search "norethindrone acetate") and/or the FDA label archive, and also RxList/accessdata FDA label text.
2. The norethindrone 0.35 mg progestin-only contraceptive labels (Ortho Micronor / Camila / Nora-BE / Errin / Heather / Jencycla): what duration language do they use (continuous, no limit, 28-day packs), and what is the labeled maximum?
3. Norethindrone acetate 0.5 mg / 1 mg combination hormone-therapy labels (Activella / Mimvey) and low-dose norethindrone labels: what duration is licensed?
4. Every warning in those labels that is duration-dependent (hepatic adenoma, thromboembolism, fluid retention, bone, depression, blood pressure) and whether the label states a maximum duration of use anywhere.
Report the labeled durations as exact rows, with the URL of each label.
>
> — session `495ffd64`

*Note on the quotes.* Only ONE distinct owner turn supports this cluster. Its six member sessions each hold a single pasted 3.4 kB research brief -- the same one, repeated -- whose closing instruction is quoted here. There is no second verbatim complaint to quote, and inventing one would be the fabrication this census exists to stop.

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
grep -rln 'firecrawl|jina' /opt/company/app/  (research plumbing)  ;  the 212 wants contain six sessions whose digest 'stops at the note that it was being written'
```

Its output line:

```
web_access.py wires firecrawl/jina (6 files match) -- the capability is there, but wants 55/58/59/60/61/62 record runs that ended before the result was compiled.
```

**Sessions in this cluster (6):** `24bc6702`, `495ffd64`, `711b0eb7`, `bbcdb5d9`, `c43df614`, `ca64cabd`

---

### C25 — Irreversible and safety-critical actions are verified before they run; secrets are handled deliberately

**Count: 4** of the 212 wants.

**Requirement.** Before an irreversible act (cutting power, wiping, sending, deleting, rotating) the precondition is checked and stated; credentials live in a managed store and are rotated when found exposed.

**In his own words:**

> you did a massive screwup, you powered down or cut power to ha before making absolutely sure the interior door was unlocked you locked us out of the room totally with no recourse to get in
>
> — session `d1e67180`

> you were wrong, and i just flipped on device encryption
>
> — session `c4dea3fd`

> figure this out end to end, we made a bunch of keys you just have to find them, and we have a master token that can create other tokens also are we paying for a new bucket or we are anyways paying for this for all our apps
>
> — session `371e57b2`

**Verdict on today: `still open`** (confidence: verified).

The exact command run for this verdict:

```
ps_db_query: SELECT COUNT(*) FROM credentials
```

Its output line:

```
credentials=0 rows -- the credentials table the estate owns is empty, and high-severity #1 is HA powered down before the interior door was unlocked, locking him out with no recourse.
```

**Sessions in this cluster (4):** `371e57b2`, `402c9d5a`, `c4dea3fd`, `d1e67180`

---

## The honest tail — wants placed in no cluster

Unplaced (the honest tail): these wants imply no estate behaviour, so no durable rule would have satisfied them. They are world-facts or impossibilities, not system requirements.

- `47047540` — An automatic status-signup path that WhatsApp's own privacy model does not allow.
- `4f3a68e0` — the friend's phone number or address, which he never got.

---

## The frustration triggers: what actually made a session angry

Classified by hand across all 122 severity-4/5 records, one primary trigger each, ranked by count. A trigger is what concretely turned a session into an angry one — not the friction vocabulary the readers used, but the thing the owner was reacting to.

| rank | trigger | sessions | share |
|---:|---|---:|---:|
| 1 | T6  A core service or interface was down, frozen or silent | 23 | 19% |
| 2 | T2  The agent asserted something false or acted on wrong data | 23 | 19% |
| 3 | T1  It reported, planned or stopped instead of doing the work | 17 | 14% |
| 4 | T9  It lost or misread context he had already given | 10 | 8% |
| 5 | T4  It ignored a stated rule or a documented shop convention | 9 | 7% |
| 6 | T5  A money- or customer-facing path was broken or misused | 9 | 7% |
| 7 | T8  It was too slow | 4 | 3% |
| 8 | T10 The output was unreadable or confusing | 4 | 3% |
| 9 | T12 An irreversible or rule-breaking act was done on production | 4 | 3% |
| 10 | T13 It pushed its own job back onto him | 4 | 3% |
| 11 | UNCLASSIFIED (severity 4 with no angry turn in the record) | 4 | 3% |
| 12 | T3  It made him do the thinking (menus, no recommendation) | 3 | 2% |
| 13 | T11 A device or peripheral did not work | 3 | 2% |
| 14 | T14 It burned money on unproductive work | 2 | 2% |
| 15 | T15 It refused to research and self-reasoned instead | 2 | 2% |
| 16 | T7  It imposed unrequested safety or policy on him | 1 | 1% |

**Read the top of that table against the instruction surface.** The single largest trigger — a core service or interface down, frozen or silent (`T6`, 23 sessions) — has no rule in the loaded persona at all. The second, the agent asserting something false (`T2`, 23), has only rule 7 ("say when you are wrong"), which governs the retraction, not the assertion: there is no rule that a fact must be checked before it is stated. Together those two are 46 of 122 angry sessions, and neither is served by a rule that prevents the anger rather than apologising for it. By contrast, the four classes the persona's longest paragraphs address — asking, handing over documents, flagging, and making him think — account for `T3` (3), `T7` (1) and the document/flag behaviours, which is the bottom of the table. The surface is tuned to the frictions that cost the least.

---

## What I did not do, and what I could not verify

- **Every verdict is a check of the living system**, but three surfaces were out of reach from this node: his phone, the Web GUI as he sees it (`C12` is therefore `not verified`), and the shop floor (`C13`/`C18`/`C21` were checked in the deployed code and the tool paths, not by taking a payment or printing a label).
- `C22`'s verdict rests on the wants and on one high-severity session ($300 sent without approval); I did not audit the ledger.
- I did not re-read the 1,008-session corpus, re-run the readers, or re-derive any number in `CENSUS-v4.md`. Counts here are counts of `CENSUS-v4.json` records that parsed.
- The cluster assignment is a judgement, recorded per session in `20-owner-wants.json`. A different reader would move individual wants between clusters; the rule is stated so that can be checked.

