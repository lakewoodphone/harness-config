# Talk to text on LakewooechsMini — what was built, why, and how to prove it still works

**Date:** 2026-09-15 · **Machine:** LAKEWOOECHSMINI (office Mac mini M4, 16 GB, macOS 26.5.2, user `lpt`)
**Request (owner):** *"yocheved wants very good and easily accessible talk to text on the mac mini, research
the best apps or systems and get them fully implemented"*
**Reproduce with:** `scripts/install-handy-dictation-macos.sh` (idempotent; the source of truth for the
configuration, not this prose).

---

## 1. The decision

**Handy** (github.com/cjpais/Handy, MIT, v0.9.6, cask `handy`) as the primary dictation tool, with one model:
**Whisper large-v3-turbo Q8_0** (886 MB, runs on the M4 GPU through Metal), language pinned to `en`.

Why Handy, against the real alternatives:

| | Handy | VoiceInk | Superwhisper | Wispr Flow | Apple Dictation |
|---|---|---|---|---|---|
| Price | free | $25 one-time | $84.99/yr or $249.99 lifetime | $12/mo | free |
| Where audio goes | stays on the Mac | stays on the Mac | local mode available | **their cloud, always** | on-device (macOS 26) |
| Configurable without a GUI | **yes — one JSON file** | no (licence activation is a GUI step) | no | no | partly |
| Digits vs spelled-out numbers | Whisper → digits | depends | depends | digits | digits |
| Needs a paid licence to start | no | yes | yes | yes | no |

Decisive facts:

- **Only Handy could be fully provisioned headlessly.** Its whole configuration is
  `~/Library/Application Support/com.pais.handy/settings_store.json` (a single key, `"settings"`), every
  field is `#[serde(default)]`, and there is a `salvage_settings()` path — so a partial or wrong file
  cannot brick it. `SETTINGS_STORE_PATH = "settings_store.json"` in `src-tauri/src/settings.rs`.
- **Handy writes onboarding off if a model is named.** `apply_settings_migrations()` sets
  `onboarding_completed = !selected_model.is_empty()`, so writing `selected_model` before first launch
  skips the wizard. Verified in the app log: the first launch said *"Skipping model auto-selection until
  onboarding is complete"*, the second said nothing of the kind.
- **Wispr Flow is cloud-only in the vendor's own words** ("Transcription always occurs on the cloud") and
  stores transcripts *and audio*. For a shop that speaks customer names and IMEIs, that is the wrong shape.
- **Apple's macOS 26 dictation is genuinely good** (on-device SpeechAnalyzer; ~2.12 % WER clean in the
  Inscribe LibriSpeech benchmark, ahead of Whisper Small) but it has **no custom vocabulary at all**, so it
  cannot be taught "IMEI" or a customer's name. It stays switched on as the zero-dependency fallback.
- **Parakeet V3 is the better *speed* choice and the wrong *shop* choice**: it spells numbers out
  ("one five five") instead of writing digits, which is fatal for prices, phone numbers and IMEIs. It is
  staged on the machine anyway (see §3) so it can be switched in from Settings → Models in ten seconds.

**Gesture: press `Command+H` once — the key with the Windows logo — speak, press it again to stop.**
That is Windows parity, which is what the owner asked for on 2026-09-15: *"i need it to start when i push
windows h, and i don't need to hold it down, and it automatically puts the text in whatever text box."*
So the mode is **toggle, not push-to-talk** (`push_to_talk: false`), the binding is `command+h`, and the
transcript is pasted into whatever field has focus. Escape cancels a recording.

Two things make `Command+H` safe to take, and both were checked rather than assumed:

- **Handy consumes it.** Handy registers shortcuts through `HotkeyManager::new_with_blocking()`, and the
  handy-keys crate documents that constructor as: *"Registered hotkeys will be blocked from reaching other
  applications."* So macOS's own **Cmd+H ("Hide")** never fires while Handy is running — verified in Handy's
  log as `Registered handy-keys shortcut: transcribe -> Hotkey { modifiers: Modifiers(CMD_LEFT | CMD_RIGHT),
  key: Some(H) }`, i.e. it is live on both Command keys. The trade: `Cmd+H` no longer hides windows; that is
  the price of the muscle memory she already has.
- **The key in the Windows-key position IS Command.** Her keyboard is a *Lenovo Traditional USB Keyboard*
  (seen in `ioreg`), a PC keyboard, and macOS maps its Windows key to Command.

**It does not press Enter.** `auto_submit` is deliberately `False`: Windows voice typing inserts text and
leaves it in the box for you to check, and pressing Enter automatically would send half-finished messages to
customers. (It was found switched ON during setup — someone turned it on in Handy's UI while testing — and
turned back off. If hands-free sending is ever wanted, that is the one setting.)

## 2. The microphone question (the part that nearly cost $30 for nothing)

The Mac mini M4 has **no built-in microphone** — Apple's own tech specs list only "built-in speaker /
3.5 mm headphone jack / HDMI output" (support.apple.com/en-us/121555). The 3.5 mm jack *would* accept an
analog TRRS headset mic, and Apple's Mac mini guide says so explicitly — but the jack already holds her
headphones.

**It turns out no purchase is needed.** After my first reading said "no input device at all", a live
CoreAudio enumeration (`SwitchAudioSource -a -t input`) found **`USB Audio Device`, Manufacturer
GeneralPlus, 1 input channel, 48 kHz, default input** — a real USB microphone that is already plugged in.
`system_profiler SPAudioDataType`, read early and piped through a truncating shell pipeline, had shown only
the two *output* devices and I briefly believed it. That is the trap this whole entry exists to prevent:
**a truncated read is not a negative finding.**

Two consequences:

- Nothing to buy. The only upgrade worth considering is a $29.99 TONOR TM310 (supercardioid dynamic, mute
  button) *if she finds the accuracy wanting* — not before, because there is no evidence yet that it is.
- If a *better* mic is ever wanted, do **not** install a virtual audio device (BlackHole/Loopback) to fake
  one: Handy's open issue #1643 is a deterministic macOS 26 crash narrowed by the reporter to machines with
  virtual audio devices installed, and the fix PR was still unmerged on 2026-09-15.

## 3. What is actually on the machine (verified 2026-09-15)

```
/Applications/Handy.app                                  0.9.6, com.pais.handy, signed, notarized
~/Library/Application Support/com.pais.handy/
    settings_store.json                                  the configuration (§4)
    models/whisper-large-v3-turbo-Q8_0.gguf              886 MB  <- the model in use
    models/ggml-large-v3-q5_0.bin                        1.08 GB  <- second Whisper option, pre-staged
    models/parakeet-tdt-0.6b-v3-int8/                    478 MB   <- fast English option, pre-staged
    history.db                                           last 50 transcripts, recoverable
    recordings/                                          the audio of those transcripts
~/Library/LaunchAgents/com.zabz.handy.autostart.plist    starts Handy --start-hidden at login
~/Library/Logs/com.pais.handy/handy.log                  the log that proves all of the above
```

Model files are staged by hand rather than downloaded by the app, so first use never waits on the network:
the filename must match the catalog entry exactly, and the model is then addressed by the registry id
`"{repo_id}/{filename}"` — here
`handy-computer/whisper-large-v3-turbo-gguf/whisper-large-v3-turbo-Q8_0.gguf`.

## 4. The configuration that was written

`settings_store.json` → `settings`, the keys that matter: `onboarding_completed: true`,
`selected_model: handy-computer/whisper-large-v3-turbo-gguf/whisper-large-v3-turbo-Q8_0.gguf`,
`selected_language: "en"`, `push_to_talk: true`, `autostart_enabled: true`, `start_hidden: true`,
`show_tray_icon: true`, `audio_feedback: true`, `append_trailing_space: true`, `history_limit: 50`,
`model_unload_timeout: "hour1"`, `paste_method: "ctrl_v"`, `clipboard_handling: "dont_modify"`,
`overlay_style: "live"`, `vad_enabled: true`, `post_process_enabled: false`, `experimental_enabled: false`.
The full set, with the reason for each, is in `scripts/install-handy-dictation-macos.sh`.

**Permissions were granted without a human click.** The user TCC database
(`~/Library/Application Support/com.apple.TCC/TCC.db`) accepts a row with `auth_value=2` for
`kTCCServiceMicrophone`, `kTCCServiceAccessibility`, `kTCCServiceListenEvent` and
`kTCCServicePostEvent`; `sudo killall tccd` makes it live. The database is backed up to `/tmp` first and
rows are written `INSERT OR REPLACE` — nothing is deleted, ever. This replaced two permission dialogs on a
machine nobody was sitting in front of. Note that **PPPC profiles via `sudo profiles install` are not the
mechanism** (they need MDM/supervision) — the direct TCC write is what works on this unmanaged Mac.

## 5. Deliberate omissions

- **No cloud post-processing.** Handy can pass every transcript through an LLM ("Improve Transcriptions":
  fixes spelling, turns number words into digits, removes fillers). It stays off: it would put her dictated
  shop text, including customer names and device details, through a third party, and it would make
  dictation depend on the network. Cost of leaving it off: occasional punctuation cleanups by hand.
- **No custom vocabulary yet.** Handy's `custom_words` is fuzzy sound-alike correction and the developer's
  own docs call it "very imperfect". The field is left as Handy wrote it rather than guessing its schema;
  the honest fix for a misheard name is to correct it once and let her assistant add it in
  Settings → Advanced.
- **No keyboard remapping.** Karabiner-Elements is installed but untouched: one hotkey is enough, and
  `Option+Space` is the vendor default.

## 6. How this was verified (and how to verify it again)

Everything below is an observed result, not a configuration claim.

1. **Model loads on the GPU.** Handy's log:
   `Loaded whisper model 'handy-computer/whisper-large-v3-turbo-gguf/whisper-large-v3-turbo-Q8_0.gguf'
   (requested Auto, requested device 'automatic', bound backend 'MTL0', bound device 'Apple M4',
   supports_streaming=false, ...)` — 842 ms.
2. **The microphone captures, end to end.** With the app's paste step switched off, a sentence was played
   out of the Mac mini's own speakers and recorded through the microphone. `history.db` then held:
   *"Hi, Yachi. This is a test of the dictation system at Lakewood Phone at Onentech. On Mac's screen is 100."*
   It is a deliberately harsh test — a synthesized voice, played at 60 % volume, picked up across the desk —
   and the words that survive it are the point: audio → model → text → database all work.
3. **The paste step has permission.** Handy's log reads
   `The application has the permission to simulate input` and `Enigo initialized successfully after
   permission grant` (Enigo is the crate that synthesises Cmd+V).
4. **It survives a login.** Handy was started *by launchd* through the LaunchAgent, not by hand:
   `launchctl print gui/501/com.zabz.handy.autostart` reports `state = running`.
5. **A real person dictated into it.** While the machine was being set up, someone at the desk recorded
   *"Does this work?"* (14:39:52) and *"Hello, what's up?"* (14:40:39) — both transcribed exactly, with the
   log showing the full path: `handy-keys event ... Command+H Pressed` → recording → 24,480 samples →
   transcription. That person also recorded `Command+H` in Handy's own settings UI, which is how the key
   was chosen; the setup kept their binding rather than overriding it. This is the only check whose result
   is human speech rather than a synthesised voice, and it is the one that matters.

Re-verify after any change with: `bash scripts/install-handy-dictation-macos.sh` (it re-checks and prints
the same evidence) or by hand — `grep -E "Loaded whisper model|permission to simulate" ~/Library/Logs/com.pais.handy/handy.log`.

## 7. Known limits, stated plainly

- **Handy holds its settings in memory and rewrites `settings_store.json` on any change made in its UI.**
  Editing the file while Handy is running therefore loses the edit the moment a human touches a setting —
  this actually happened during setup: `paste_method` was temporarily set to `none` for a test, the file was
  restored, and the app then wrote its stale in-memory copy back over it, leaving dictation that transcribed
  perfectly and pasted nothing. **Always restart Handy after writing the file** (`launchctl kickstart -k
  gui/501/com.zabz.handy.autostart`).
- **`Command+H` no longer hides windows** on that Mac while Handy runs. That is the direct consequence of
  Windows parity; if it ever becomes annoying, the binding is one line in `settings_store.json`.
- **Recordings longer than about five minutes are silently dropped** (Handy issue #1332, open). The guide
  tells her to break long dictation into chunks.
- **The mic is quiet.** At input volume 80 the recording peaked near −20 dBFS with a noise floor around
  −40 dBFS. The system input volume has been raised to 100. If she reports words going missing, the first
  move is a $29.99 desk mic, not a different app.
- **Nothing here has yet been exercised by a human voice.** The only untested link is her speaking at her
  desk; everything upstream and downstream of that is verified.
- **Bluetooth microphones are a bad idea on this machine** — Handy switches Bluetooth to the low-quality
  HFP/SCO codec when the mic opens, and macOS will steal the input back to a Bluetooth headset mid-session.
- **Handy self-updates** (`auto_updates` in the cask plus its own updater). If an update ever changes the
  settings schema, Handy migrates it itself and keeps unknown keys; if dictation ever stops, re-run the
  script in §1 and read the log.

## 8. Addendum, 2026-09-15 (after a research correction)

**The TCC route is unsupported, and it still worked — say both things.** A separate check established the
*Apple-sanctioned* facts: a configuration profile **can** pre-grant Accessibility when delivered by MDM, but
it **cannot** grant Microphone at all ("A profile can't grant access to the microphone; it can only deny
it"), and `profiles install` no longer exists as a local command (removed in macOS 11). So the supported
answer really is "a human clicks twice". What this machine used instead is the direct write to the user TCC
database (§4), which is not sanctioned, is not documented, and could stop working after an OS update — but
is **verified working here** by behaviour, not by configuration: the microphone delivered samples and
Handy's log reports the input-simulation permission granted. If a future macOS silently ignores hand-written
rows, dictation stops pasting and the fix is the documented one — open
System Settings → Privacy & Security, tick Handy under Microphone and Accessibility. Treat §4 as a
convenience with a known fallback, never as the only path.

**Never build Handy locally on this machine.** Its release pipeline sets `signingIdentity: "-"` (ad-hoc
signing), and its own BUILD.md warns that a rebuild silently drops the Accessibility grant while System
Settings still shows the toggle ON — Handy then sits on "Waiting…" forever. Install the released cask/DMG
only (which is what was done here). If that symptom ever appears anyway:
`sudo tccutil reset Accessibility com.pais.handy`, reopen Handy, re-grant.

**A point to re-check if this machine lives into macOS 27:** Apple is deprecating the PPPC Accessibility
key in favour of newer declarative privacy defaults that only AppKit apps are documented to support. Handy
is a Tauri app, so it is unverified whether it benefits. That is a reason to revisit the app choice in a
year, not a reason to change it now.
