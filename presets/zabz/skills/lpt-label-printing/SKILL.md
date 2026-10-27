---
name: lpt-label-printing
description: Use whenever a label has to be printed for Lakewood Phone & Tech — a work-order drop-off tag, a hold tag on a customer's item, a shelf or parts label, or anything the owner calls "a label". Covers the one tool that prints (lpt-label on the authority), the loaded roll, the layout traps, and the only honest proof that tape came out. Also use BEFORE designing any label, so the house format is reused rather than re-invented.
---

# Printing a shop label

The shop's labels come out of one printer, and exactly one tool prints to it. This skill exists
because a session on 2026-10-12 spent eleven tool calls hand-rolling a Windows `PrintDocument` route,
sent a job on the wrong media size, and **froze the printer hard enough that the owner had to
power-cycle it** — for a job that takes one command. Read this before the first design sentence.

## 1. The one command

Run it on **`secratary`** (the ssh alias `secratary-ts` resolves to the same box), the only
always-on machine on the office LAN. **That box is the FROZEN ROLLBACK ANCHOR — posture
`read-only` in `harness-config/settings/machines/host-posture.tsv`** (the authority moved to
`secratary-cloud` at the 2026-10-11 cutover). Printing from it is legitimate: the tool reads its
own code and speaks TCP to the printer, and it writes nothing but `/tmp`. **Writing to that box is
not** — no deploy, no edit, no `git pull`, no service verb. A session on 2026-10-12 deployed a
fixed `label_printer.py` into `~/lpt-ops` there and had to revert it by sha256 (§6).

```bash
ssh secratary-ts 'lpt-label --ticket 2652 --customer "Reifman" --device "Kyocera Cadence" --issue "charging port fixed"'
```

For anything with an apostrophe in it — and most shop names have one — use the stdin JSON path,
which crosses PowerShell → ssh → bash quoting intact:

```bash
echo '<json>' | ssh secratary-ts "lpt-label print -"
```

| | |
|---|---|
| the printer | **Brother QL-820NWB**, serial `H3G354844`, firmware 1.25, on the office LAN. Address is DHCP (`192.168.50.60` at the time of writing) and **never trusted** — `lpt-label find` makes the device identify itself by model before anything is sent. |
| the roll | **DK-2210 endless, 29 mm.** It reports as `media  Not Empty 29mm`. There is a 62 mm roll for it too; the printer moves between rooms. |
| how it prints | raw Brother raster over **TCP 9100**, sent from the authority |
| source | `lpt-ops/bin/lpt-label`, `lpt-ops/lpt_ops/label_printer.py`, `lpt-ops/docs/label-printer.md` |
| the laptop | **cannot print locally** — it has pillow but not `python-barcode`/`brother-ql`, and `render()` calls `_require()` even for a dry run |

## 2. What you can honestly claim after a print

**Corrected 2026-10-12, measured on this printer. The old claim here — that a print is proven by the
status page going `READY → PRINTING → READY` — is not usable:**

- The status page's own `Auto Refresh Interval` is **60000 ms**, and the page read `READY`
  immediately before and after a 33 mm job. A poll loop run concurrently with the job (60 samples,
  150 ms apart) saw **`READY` in every single sample**. A small label is fed faster than the page can
  be re-read, so the transition is simply not observable. Do not spend calls on it.
- The printer's only counter is **`Total Print Length(m)`** on `information.html` — an **integer
  metre** (`11` at the time of writing). A 33 mm label cannot move it, so it cannot prove one label
  either. `lpt-label find` therefore reports nothing about tape.

So the honest report after sending a job is exactly this, and no more: **the printer was identified
by model and serial, it was `READY` with the 29 mm roll loaded, and the transport accepted the job
(`instructions_sent: true`)**. Tape is proven by the tape — the roll in the printer, or the person
standing next to it. Say which of those you have; if you have neither, say the print is unproven.

**`brother_ql`'s `did_print` is `false` by construction on this model** — it reads a status register
over 9100 that this printer never answers. It is `false` even when the tape comes out. Do not report
a print from the tool's word alone, and do not report a failure from `did_print`.

One more, for the record: a print is 33 mm of tape at 25.6 mm of image, and the job is over in about
a second — so a job cannot be caught mid-flight by a page that refreshes once a minute.

## 3. Before you spend tape

```bash
echo '<json>' | ssh secratary-ts "lpt-label print - --dry-run --out /tmp/x.png"
# then copy the PNG back and LOOK at it
```

A dry run still requires the printer to be **findable**, so a successful dry run already proves
discovery.

## 4. The layout contract, and the traps — all measured

The JSON keys the stdin path accepts: `title`, `heading`, `ticket`, `customer`, `device`, `issue`,
`dropped`, plus `lines` (a list) and `no_title` / `show_title`.

- **`--ticket` prints `#<n>` BIG as the heading, and adds NO barcode.** The shop stopped using
  barcodes on labels on 2026-10-09 — labels are read by eye. Leave `--barcode` empty.
- **Positional `info` lines are IGNORED whenever `--ticket`, `--customer` or `--device` is present**
  — the work-order branch wins. You cannot mix the two forms.
- **`--issue` is silently TRUNCATED at the font floor.** A line that is too long renders short with
  no error and no warning. Keep each line to roughly 22 characters on the 29 mm roll and check the
  dry-run PNG.
- **`--issue` does reach the tape as several lines if you put a real newline (`\n`) in it.**
- **`--no-title` omits the masthead**; an empty `--title` does NOT — it falls back to
  `LAKEWOOD PHONE & TECH`.
- **What goes on a label.** The owner, verbatim: *"it's for my secretary to read the labels also so
  she needs this info."* A label has to let someone find the job and know what to hand over and what
  to collect. That means **ticket number and a device/job identity** — a name, a phone and a price
  alone is unusable.
- **A line starting with `!` is drawn as a HEADLINE** (bold, sized to the tape, never wrapped) — but
  **only by the newer renderer**. The copy deployed on `secratary` is the older one, where `!` prints
  literally and each line is sized on its own (so a short line blows up). Either use the §6 route, or
  design without `!` in the house style the shop's existing labels already use.
- **When the shop has already printed the thing you are about to design, print it again — do not
  design it.** Previously printed labels are on disk under `~/code/_labelprinter/out/`.

## 5. Never route a shop label through a Windows printer driver

The QL-820NWB is offered to Windows over WSD as **"Brother QL-820NWB Printer"**, and it is a trap:

- The Windows driver's default page size is the **die-cut 28 × 90 mm** (`1.1" x 3.5"`), while the
  loaded roll is 29 mm **endless**. Sending a job on the die-cut size raises the printer's own media
  error and **can freeze the device until it is power-cycled** (2026-10-12).
- Windows reports that media mismatch through WMI as `DetectedErrorState=4`, which reads as
  **"No Paper"** — so "the printer is empty" is frequently the wrong conclusion.
- `PrintDocument.Print()` returns successfully while the printer sits in that error. A pre-flight
  check on the WMI state is not enough; the state does not clear until the media matches.

If you ever must print from Windows, the continuous rolls are the **width-only** paper names in the
driver's list (`1.1"` = 29 mm, `2.4"` = 62 mm) and the names carrying a length (`1.1" x 3.5"`,
`Standard Address Label`) are the die-cut ones. But use `lpt-label`.

PowerShell trap hit while failing at this, worth one line: **variable names are case-insensitive**,
so a local `$paper` and a `[string]`-typed parameter `$Paper` are the same variable, and every object
assigned to it is silently stringified.

## 6. The renderer on the anchor is a revision behind — run the new one read-only

Measured 2026-10-12. `~/lpt-ops` on `secratary` is a plain copy, not a checkout, and the commit that
added uniform body size, DP word wrap, `!` headline lines and `--roll-mm` (`f40f0e6` in
`lakewoodphone/lpt-ops`) was **never deployed to it**. The symptom, seen on the first dry run of that
day: the `!` marker printed literally, and short lines were sized per-line, so `discarded.` came out
as a headline next to 15 px body text.

Do not fix that by writing to the anchor. The newer code already sits on that box in the git checkout
`~/code/lpt-ops`; run the entry script straight out of it with the venv the wrapper already uses, and
stop Python writing bytecode into the checkout:

```bash
ssh secratary-ts 'PYTHONDONTWRITEBYTECODE=1 /home/zabz/.local/lib/lpt-label/venv/bin/python \
  /home/zabz/code/lpt-ops/bin/lpt-label print - --dry-run --out /tmp/x.png' < /tmp/x.json
```

Verified: byte-identical output to the temporarily-deployed file (sha256 `0483d786…`, 33.2 mm of
tape), and nothing written outside `/tmp`.

`secratary-cloud`, the authority, **cannot** print: the office LAN is not routed to it
(`curl http://192.168.50.60/…` → `000`) and it has no `lpt-label`. The printer is an office-LAN
device, so the office box is the only print host there is — which is why printing there is accepted
despite the freeze. Moving the labeler off the anchor is a decision about the anchor: bring it, do
not improvise it.

**CORRECTED 2026-10-27 — "the only print host there is" was wrong, and here is the measurement.**
`zabz-tech-linux` is *also* an office box. Cloned `lpt-ops` (`de45f34`) there, ran
`install-label.sh` (private venv at `~/.local/lib/lpt-label/venv`, launcher at
`~/.local/bin/lpt-label`, symlinked to `/usr/local/bin/lpt-label` — additive, touches no system
Python), and its own proof step answered:

```
tried: mDNS BRW4CD5775ED835.local -> 192.168.50.60
Brother QL-820NWB at 192.168.50.60
  state READY · media Not Empty 29mm · serial H3G354844 · firmware 1.25
  print target tcp://192.168.50.60:9100
install-label: printer found - PROVEN.
```

**So a frozen box is not required to print.** The rule this replaces was built on the assumption
that the anchor was the only LAN-reachable always-on host; it is the only *always-on* one, not the
only reachable one.

**What is still the owner's decision, unchanged:** which host is the shop's print host. Two now exist
and only one should. **Nothing was printed from `zabz-tech-linux`** — a print is 33 mm of tape and
the honest proof is that tape, so the first one should be sent with a person standing there. Until he
says which host wins, **print from `secratary-ts` exactly as above**; the second install is dormant
and harmless.
