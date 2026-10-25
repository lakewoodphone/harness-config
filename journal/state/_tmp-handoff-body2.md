Owner asked (2026-10-23, ZABZ-YOGA) to pull up the tutor system and "the system to teach me to sing", then rejected the full app as too much: "i want a simple one, i want to practice keeping on tone now / so measure my tones and help tutor me". Everything below was built to that.

## What exists now: `C:\Users\ezabz\code\tutor\toner`

One page, one meter, one file of measured frames — no lesson-plan machinery.

| file | what it is |
|---|---|
| `serve.py` | stdlib `http.server`. `TONER_PORT` (default 8010), `TONER_DATA` (default `data`). Routes: `/` page, `/drill` reads `<data>/drill.json` fresh every request, `/sample` appends NDJSON frames to `<data>/toner-<date>.jsonl`, `/sink` reports that file's size |
| `toner.html` | the whole UI + logic, ~600 lines, no build step |
| `pitch.js` | autocorrelation detector, 2048 samples, 55–900 Hz, octave guard, parabolic peak |
| `summary.py` | per-take report: sound, duration, voicing, in-tune %, longest hold, median/mean cents, robust spread, drift c/s, onset-vs-settled, ±50c distribution. `--last N`, `--date`, `--data <dir>` |
| `data/drill.json` | **the tutor writes this; the open page re-reads it every 3 s** and reconfigures itself. No reload, no restart |
| `data-yocheved/` | second instance's drill + frames, kept separate on purpose |
| `start-eliyahu.cmd` / `start-yocheved.cmd` | relaunch either instance if it stops |
| Desktop `*.url` | "Eliyahu - Keep On Tone" → 8010, "Yocheved - Keep On Tone" → 8011 |

Drill schema: `mode`, `target` (MIDI: 43 = G2, 57 = A3), `hold` (seconds, auto-stop), `sounds[] {syllable, hint}`, `rules[]`, `pass {in_tune, present}`, `preview` (obsolete: 0). Each take sings the current sound; pass or fail advances the chip.

## Both instances are LIVE and detached

`pythonw serve.py` via the two `.cmd` files, so they outlive this session (pids 15532 + one more). Verified 2026-10-23: `8010/sink -> 200`, `8011/sink -> 200`, `8011 GET / -> 200 28268 bytes`. If a port is dead, run the matching `.cmd`.

## What the measurements actually say (his voice)

- First free take: 12 s, median **G2 −188c** vs an A2 target, spread 17c, drift −4.3c/s. He was not off; the target was.
- Ten 4-second takes at G2: in tune **4 → 15 → 57 → 66 → 94 → 94 → 83 → 99 → 97 → 97%**. Sag gone at 4 s.
- Five 6-second takes: in tune 52, 73, 50, 4%; medians −22, −15, −16, −44 → **louder and present, but sitting flat**.
- Five vowels, twice: reliable = **eeh, goo** (74–85%, medians −2 / +12); **gah collapsed to −54c, 0%**.
- Transfer drill (ooh→goo→gah→gah): **gah improved to −22/−23c, 48/51%**. Fault moved to drift; ooh came in **+178c** (sang from memory a whole tone high).
- After "aim a hair higher": **103 Hz = +82c above G2, 0% in tune** — a whole semitone overshoot. The cue was too vague; correct cue is "land inside the green band, 97.9–98.6 Hz".
- Recorded range from the old tutor app's `student_state.json`: G2–D5.

## Defects found and fixed while measuring (each proved, not assumed)

1. **Octave/click frames inflated the failure rate.** 19–21% of frames in his quiet takes were jumps; a take 30c flat read as "36% in tune". Now a frame >250c from the recent median is dropped, recorded with `jumped: true` + `raw_hz`, and 8 consecutive rejects re-lock. Proved with a tone blipping an octave every 800 ms → 100% in tune / 96% present.
2. **A single weak onset frame seeded the reference.** His take had one 596 Hz frame at clarity 0.54 while history was empty; everything after was measured against it. Frames under **0.70 clarity** are now rejected outright.
3. **The needle parked at centre when there was no tone** — reads as "you're in tune" while the readout said "—". It now fades to 12% opacity with no pitch, the bar spans **±100 cents** (was ±50, which clamped +80 at the edge), and the cents figure is coloured.
4. **`ctx.sampleRate` dereferenced after `stop()`** → `TypeError: Cannot read properties of null` on late frames. Now a captured `sr` with `if (!sr) return;`, set at start and zeroed at stop. Verified: no page errors after a full take.
5. **A 98 Hz reference sounded like "a tiny hum that sounds like a machine"** — below what a laptop speaker moves. The reference is now synthesised piano (10 stretched partials, each decaying faster than the one below, plus 12 ms hammer noise) played in the **330–700 Hz band**, so a G2 drill plays **G4** and the card says so.
6. **Start used to play the reference**; owner asked for the split: **Play** plays (3 s, each strike rings ~3.2 s, button busy 5.7 s while the tail sounds), **Start** records and makes no sound.
7. `python -m tutor curriculum` died with `UnicodeEncodeError` on cp1252; fixed in `src/tutor/__main__.py`.

## Still open

- ScriptProcessorNode is deprecated (warns, works). AudioWorklet would need a separate module file.
- No automated test suite; every claim above was checked through Playwright against the live page with synthetic input (sines, harmonic stacks, octave blips, silence, mic-denied).
- His frame file is ~1 MB/day; nothing prunes it.
- The big music-tutor app (`python -m tutor`, port 8000) was stopped to free the microphone and is not running.
