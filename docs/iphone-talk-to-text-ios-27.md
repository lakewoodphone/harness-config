# The owner's iPhone talk-to-text — the whole record, and does iOS 27.0.1 fix it

**Written:** 2026-10-13 · **Host:** SECRATARY-CLOUD · **Owner's device:** iPhone 15 Pro (A17 Pro, 8 GB RAM)

**Why this file exists:** the original research document from the 2026-09-30 session
(`/home/zabz/phone/iphone-dictation-research-2026-09-30.md`) is **gone from disk** and the lessons that
session claimed to append (L3190/L3191/L3192) **do not exist in the journal** — those ids now hold
unrelated entries. The findings survived only inside the session log itself
(`~/.dsh/sessions/--home-zabz-phone--/session-d05a9a77-aae2-4249-8e02-c226faa4f488/session.v3.jsonl.zstd`).
This file rebuilds the record into a durable place. Nothing here is inferred; every number comes from
the sources named.

---

## 1. The complaint, in his words (2026-09-30)

> "I find that the talk to text on my iPhone is exceptionally bad. It doesn't hear me right and if it's
> not, I guess 100% unclear in the words then it skips out some words and it gets garbled very easily.
> What can I do about this is there an app I can install to make this better or some sort of setting I
> change I hate it"

Two further facts he gave in that session: **no Bluetooth was connected**, and **English (United States)
was already the only dictation language** — so the two classic settings causes were eliminated by his
own answers, not by assumption.

## 2. It is not him, and it is not his phone's fault

His exact symptom — words appear correctly, then vanish when the mic stops — was, as of that research,
the most widely reported dictation defect of 2026: reported across MacRumors, TidBITS, AppleVis,
Hacker News and German, Chinese and Arabic forums, and still being reported *after* iOS 27 shipped.
Apple has made no public statement about it since February 2025.

**The cause is Apple's own, in Apple's own words.** Dictation runs on the model that powered Siri, which
Apple describes in its own WWDC developer session as working "well for short-form dictation". Apple then
built a dramatically better engine for iOS 26 — measured at **2.12 % word error rate against the old
engine's 9.02 %**, roughly four times fewer errors — and pointed it at Notes, Voice Memos and Journal.
Never at dictation. The live pass types your words; a second pass rewrites them; that second pass is
where words disappear.

## 3. The good engine now exists — and his phone cannot have it

iOS 27 finally attached that engine to dictation: **Advanced Dictation**, a ~20-billion-parameter model
running entirely on the phone, system-wide, no app and no keyboard switching. Apple's own human
evaluation scored it preferred **44.7 % to 17.6 %** over the current system across seven measures.

**The gate is hardware, at 12 GB of RAM.** It ships only on **iPhone 17 Pro, 17 Pro Max and iPhone Air**
(and "later"). The standard iPhone 17, the 16 Pro and the **15 Pro all have 8 GB and are excluded**. No
staged rollout, no announced change — Apple's iOS 27 feature page still reads "iPhone Air and iPhone 17
Pro models and later".

**It is also off by default**, even where it exists: Settings → General → Keyboard → Dictation →
Advanced Dictation (may read "Advanced Dictation Preview").

## 4. Why no third-party app can ever be "never think about it again"

Architectural, not a maturity problem: **iOS forbids a keyboard extension from opening the microphone**,
so every voice keyboard must hop out to its own app and back. iOS 26.4 removed the automatic return
(you swipe back by hand, every time) and iOS 26.5's toolbar covers all custom keyboards — reproducing in
Google's and Grammarly's alike. Every vendor pays the same tax.

One honest caveat, **corrected 2026-10-13**: in September no independent comparison could be found. One now
exists — **Wirecutter's "The Best Dictation Software"** (updated 2026-06-22; 50 hours, 19 tools, Apple's own
dictation included) rates **Wispr Flow at 98 % accurate, Apple's dictation at 94 % on both iOS and macOS**,
and calls **Willow the most accurate app tested** ("missed only four words"). Treat that number for Apple
with suspicion: it does not reproduce the disappearing-words defect this owner actually suffers, so raw
accuracy is not the axis his complaint lives on. The vendor benchmarks circulating in the same market
(Willow 95 %, Wispr Flow 90 %, Apple 48 %) are marketing, not measurement.

## 5. What was set up on his phone (2026-09-30)

**Superwhisper** — App Store, free tier genuinely unlimited, Whisper running **on the phone** (no word
cap, no account, audio never leaves the device), established (4.4 across ~834 ratings, v2.24.1, SOC 2),
and the same licence covers his Windows laptop. Paid tier swaps in cloud models: **8.49 a month, or
84.99 a year** — not worth buying until the free tier is tested against real messages.

Install: keyboard + **Allow Full Access** (mandatory), then
**Settings → Action Button → Shortcut → "Toggle Superwhisper Dictation"**. Two ways in:

- **Action Button** — hold, talk, release. Works in any app; text lands on the **clipboard**, so paste.
- **Superwhisper keyboard** (hold the globe key) — types straight into the field.

Places that are **not** worth his time: **Aiko** (a file transcriber, cannot do live dictation) and
**Superwhisper on old advice / Gboard** — Gboard was downgraded in that session once the mic-restriction
architecture was understood. **Wispr Flow is cloud-only in the vendor's own words** and stores transcripts
*and audio* — wrong shape for a shop that speaks customer names and IMEIs.

## 6. ⚠ OPEN — the thread was never closed

His last message in that session: *"I think I did all the instructions, but I'm not sure what happened. I
don't know. It looks like talk to text isn't working at all through Apple or the other one."*

My reply diagnosed **one cause, not two**: the orange dot in his screenshot was lit, meaning something
was holding the microphone — most likely a Superwhisper recording left running, which locks out Apple's
dictation completely and looks exactly like "both are broken". I asked for one screenshot. **He never
replied, and no session since has returned to it.** As of 2026-10-13 this is unresolved — see the
journal pain entry filed the same day.

Most likely causes, in order: (1) Superwhisper holding the mic → force-quit it, then restart the phone;
(2) looking for Apple's mic key while a third-party keyboard is showing — Apple's mic key **does not
exist on third-party keyboards**; (3) `Settings → General → Keyboard → Dictation → Enable Dictation`
actually switched off.

---

## 7. THE ANSWER: does updating to iOS 27.0.1 fix it?

**No.** Checked 2026-10-13 against Apple's own release notes and current reporting.

**iOS 27.0.1** (build 24A446, released 2026-09-28; iOS 27.0 shipped 2026-09-14) contains exactly three
fixes, quoted from Apple: iPhone 18 Pro / 18 Pro Max restarting when Face ID fails; a colour artifact on
2× photos at f/1.48 on a small number of those devices; and an unresponsive touchscreen when
Notification Center and Control Center are opened together. Apple's security page: *"This update has no
published CVE entries."* **Nothing about dictation, speech-to-text, the disappearing-words bug, or
Advanced Dictation.** There is no iOS 27.0.2.

**The hardware gate has not moved.** Apple's iOS 27 page still restricts accurate on-device dictation to
"iPhone Air and iPhone 17 Pro models and later". No Apple statement and no credible report that the 12 GB
requirement will open to the 15 Pro, 16 Pro or standard 17.

**Post-27.0.1 user reports show it still broken**, including a German comment dated 29 September 2026 —
the day after 27.0.1: *"Seit iOS 27 ist die Diktierfunktion nahezu unbrauchbar… Ich hoffe, Apple behebt das
Problem mit dem nächsten Update."* One French outlet claims the French dictation fault was fixed in
27.0.1, but the same MacRumors thread's original poster says the fix actually arrived in the **27.2 public
beta** — 27.2 is expected the week of 26 October 2026 and its developer notes contain **no dictation or
Screen Time entries**.

**What updating does get him:** nothing for dictation. iOS 27 adds voice-editing commands ("Capitalize X",
"Replace X with Y") which Apple's own developer notes concede "might not work reliably", an
auto-punctuation toggle, and a Messages dictation-button control. He is in the Siri AI tier for a 15 Pro,
but that does not change the dictation engine — any claim that it does is unconfirmed.

**Practical position:** update if he wants general housekeeping; do not expect it to change his dictation.
The fix remains the Superwhisper route already installed, starting with whatever is holding his mic.

**Sources:** [Apple — About iOS 27 Updates](https://support.apple.com/en-us/149076) (29 Sep 2026) ·
[Apple — Security Releases](https://support.apple.com/en-us/100100) (28 Sep 2026) ·
[Apple — iOS feature availability](https://www.apple.com/ios/feature-availability/) ·
[MacRumors — Advanced AI Dictation not enabled by default](https://www.macrumors.com/2026/06/22/advanced-ai-dictation-not-enabled-by-default/) (22 Jun 2026) ·
[MacRumors — text dictation still removes words](https://forums.macrumors.com/threads/text-dictation-still-removes-words.2489440/) (15 Sep 2026) ·
[MacRumors — iPhone 18 Pro and voice dictation bug](https://forums.macrumors.com/threads/iphone-18-pro-and-voice-dictation-bug.2490281/) (23 Sep 2026) ·
[MacObserver — iOS 27's three tiers](https://www.macobserver.com/tips/round-ups/ios-27-three-tiers-which-iphone-gets-what/) (10 Sep 2026) ·
[iphone-ticker.de](https://www.iphone-ticker.de/siri-probleme-mit-diktaten-und-langen-homepod-wartezeiten-287189/) (comments 29 Sep 2026) ·
[9to5Mac — iOS 27.2](https://9to5mac.com/2026/10/07/ios-27-2-release-date-new-iphone-features-are-coming-soon/) (7 Oct 2026)

**Could not be confirmed, stated rather than hidden:** no Apple acknowledgement of the bug in any release
note or advisory; no 15 Pro–specific dictation report dated after 27.0.1; no vendor-independent accuracy
benchmark for 27.0.1; Reddit and Apple Support Communities content was bot-blocked and is not relied on.

---

## 8. The other thing he asked the same night — iOS 27 Screen Time

**Is it significant? Mixed — and the consequential part is the gate, not the features.**

**Genuinely new:** *Ask to Browse* (a child must get approval before opening a new website; the request
arrives in Messages; approved sites join an allow list; unanswered requests expire in 24 h) · *per-new-contact
approval* (a message from a stranger cannot be read until a parent approves) · *Communication Safety
extended to gore and violent content, including live FaceTime* · *one-tap Pause Device Use / Allow
Unlimited Use* · an app-picker during Child Account setup · faster cross-device sync on a rebuilt iCloud
architecture.

**Mostly a rename:** *App Limits → Time Allowances* (same idea, now a shared daily total plus per-category
budgets, custom categories and age-based guidance) · *Downtime → folded into Screen Time Schedules* (new:
choosing which apps per window, and a school-hours option) · dashboard redesign + quick actions.

**The gate is the story.** Nothing changes until **every device in the Family Sharing group** — every
iPhone, iPad, Mac, Watch and Vision Pro — is on version 27 **and** a parent runs a one-time per-child
"update parental controls" step. That is where families got stuck for weeks, and Apple has acknowledged it:
*"we're continuing to improve the rollout of the new parental controls… we're working to resolve delays
some families are seeing"* (Apple spokesperson Katie Lowry, 6 Oct 2026). Reported fallout: setup blocked by
one un-updated MacBook, ghost devices that had to be *removed* from the account, apps blocked even when
allowed, limits firing after five minutes instead of an hour, inconsistent reports between devices. iOS
27.0.1 contains no Screen Time change.

**Hardware: nothing here is gated.** All of it sits in the base iOS 27 tier — **his iPhone 15 Pro gets every
piece of it**. Only Siri voice customisation and Advanced Dictation need the 12 GB phones. The one
non-hardware gotcha: legacy devices in the family group, which may have to be removed rather than merely
ignored.

**27.2 adds nothing to Screen Time** — its developer notes contain zero Screen Time, FamilyControls or
ManagedSettings entries.

**Sources:** [Apple — About iOS 27 Updates](https://support.apple.com/en-us/149076) (29 Sep 2026) ·
[Apple Newsroom — new child safety features](https://www.apple.com/newsroom/2026/09/apples-new-child-safety-features-now-available/) (14 Sep 2026) ·
[Apple Support 127512 — Ask to Browse](https://support.apple.com/en-us/127512) (14 Sep 2026) ·
[Apple Support 108806 — parental controls](https://support.apple.com/en-us/108806) (22 Sep 2026) ·
[The Verge — Screen Time update struggles](https://www.theverge.com/tech/1005193/apple-screen-time-update-struggles-ios-27-parental-controls) (6 Oct 2026) ·
[BGR — parental control update problems](https://www.bgr.com/2283944/apple-parental-control-update-problems-for-users/) (12 Oct 2026) ·
[9to5Mac — what's new in parental controls](https://9to5mac.com/2026/09/14/heres-whats-new-with-parental-control-features-in-ios-27-ipados-27-and-macos-27/) (14 Sep 2026) ·
[Notebookcheck](https://www.notebookcheck.net/iOS-27-Apple-s-new-parental-controls-wait-for-a-setup-step.1409237.0.html) (28 Sep 2026) ·
[MacObserver — hardware gates](https://www.macobserver.com/tips/round-ups/ios-27-hardware-gates-features-that-need-other-devices/) (11 Sep 2026)

**Unconfirmed:** whether any Screen Time fix is scheduled for 27.2; per-feature region availability beyond
the two Messages Communication Safety rows Apple publishes; whether Screen Distance changed at all.

---

## 9. SETTLED CONFIGURATION (2026-10-13) — re-verified, and one September claim corrected

He confirmed on 2026-10-13, in his words: **"Apple dictation is just plain bad."** That closes the
diagnosis — nothing is broken, the engine is the whole problem, and the fast mic fix is not needed.

**What changed since September, verified against the vendor's own pages on 2026-10-13:**

- **Superwhisper moved 2.24.1 → 2.25.2** (released 2026-10-09; 4.4 stars, 842 ratings, needs iOS 26.0+).
  Four releases, no change to how it works.
- **The best-quality *local* model is now free.** The vendor made all Whisper models free for everyone on
  **2026-08-27**, including **Whisper Large v3 Turbo (1.6 GB)**. The free tier is *unlimited* dictation with
  local Whisper, custom vocabulary, text replacements, two modes — and in the vendor's own words,
  **"Nothing you dictate leaves your device."** Only the non-Whisper engines (Cohere Transcribe, Parakeet)
  and the AI cleanup modes sit behind Pro. This is the fact that decides the configuration.
- **The keyboard mechanics are unchanged and confirmed for iOS 27.0.1:** *Allow Full Access* is still
  required, and the app still hops out to itself to grab the microphone because Apple forbids keyboard
  extensions the mic — then **you swipe back yourself**. The vendor names Apple's own bug
  (feedback FB22247647) and says it affects every third-party keyboard.
- **Prices unchanged:** 8.49 a month, 84.99 a year (≈7.08 a month), 249.99 lifetime.
- **No iOS 27 or 27.0.1 issue is named anywhere** in Superwhisper's docs or changelog — no known breakage
  and no claimed fix. Its own docs never mention iOS 27 at all.

**THE CONFIGURATION — one mode, one model, free:**

1. Superwhisper → **Mode: Voice to Text (Transcription)**.
2. **Model: Whisper Large v3 Turbo**, the local one. *This is the step that matters* — a cloud mode would
   send his customers' names and serial numbers off the phone, and it is also the step that would silently
   try to sell him Pro.
3. Settings → General → Keyboard → Keyboards → **Superwhisper → Allow Full Access ON**.
4. **Settings → Action Button → Shortcut → "Toggle Superwhisper Dictation"** — this is the everyday path:
   hold, talk, release, then paste. Vendor docs do not state the clipboard behaviour; the vendor's own
   social post tells users to "just select paste like you normally would", and every third-party guide
   agrees. Treat clipboard-paste as expected but unproven by the vendor.

**Cost of living with it:** one swipe back after starting, every time. That is Apple's restriction, not
Superwhisper's, and every competitor pays it.

**WHEN TO PAY, decided in advance so it does not become a question later:** only if the free local Whisper
is not clean enough after real use. Then **84.99 a year**, and even then **pin the mode to a local Whisper
model** so audio stays on the phone. Do not buy Pro for the cloud models — his own calls are already
transcribed in the cloud by Dialpad, so cloud is not a new exposure, but there is nothing to gain that
justifies moving customer speech off the device for free.

**Backups, only if Superwhisper fails him:** **Spokenly** (free tier unlimited, offline Whisper and
Parakeet, iOS keyboard, Pro 99.99 a year, Local+ 19 one-time — but 61 ratings and its own developer warns
local models "can struggle on older devices" inside a keyboard). **Google AI Edge Eloquent** is free and
on-device but its App Store description still says *"Keyboard coming soon"* — useless here until it ships.
**Wispr Flow** (free tier only 1,000 words a week, cloud-only, 15 a month) and **Willow** (free unlimited
but cloud) are both accurate and both wrong for a shop that says serial numbers out loud.

**ESCALATION PATH, recorded as a decision rather than raised as a question:** if he will neither accept the
swipe nor pay, the one channel where friction can be removed entirely is his own chat with me — a
record-and-transcribe button in the phone GUI, using the company's existing Whisper transcription service
(`personal-secretary-mvp/app/services/transcription.py`). It bypasses Apple's engine altogether with no
keyboard switching. **Not built**, because it covers only that one channel and Superwhisper covers every
app; build it only if Superwhisper is rejected.


### 10.1 OUTCOME, same day — Whisper Small (English) is as fast as the cloud, and he has switched to it

His own report, 2026-10-13, verbatim: *"I tried the small model and it's way way faster. It takes like the
same three seconds probably even faster than the cloud model. Drops less accurate but I think that's worth
it as I'm changing to it."*

**This is the only real iPhone latency measurement that exists for any of these models** -- nobody else,
vendor included, has published one. Recorded as such: **iPhone 15 Pro (A17 Pro, 8 GB), Whisper Small
(English), 500 MB -> roughly three seconds or better**, against ~15 seconds for Whisper Large v3 Turbo
(1.6 GB) on the same phone in the same session. The vendor's speed rating (Small 8/10, Turbo 8/10) predicted
this correctly; **the size, not the speed rating, was the thing that mattered** -- consistent with the vendor's
own statement that model load time is the first cause of slow dictation.

**The trade he accepted knowingly:** accuracy 5/10 for Small against 8/10 for Turbo. Consequence worth
keeping in view, and already a standing lesson (L1930): **a dictated serial number, IMEI or part number is
not evidence** -- re-read it off the device before ordering. He was told once and it is his call; do not
re-raise it.

**Settled configuration, final:** Superwhisper 2.25.x, free tier, mode **Voice to Text**, model **Whisper
Small (English)** (old in-app name **Standard**), `Allow Full Access` on, notifications off, Live Activities
off, no Shortcut, Action Button left on Silent mode. Superwhisper Pro is **not** being bought -- the free
local model beat the cloud on latency.
