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

Run it **on the authority**, which is the only always-on box on the office LAN:

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

## 2. The only honest proof that tape came out

`lpt-label find` reads the **printer's own status page**. A print is proven by that page going
`READY → PRINTING → READY` with the roll still loaded:

```bash
cat /tmp/x.json | lpt-label print -
for i in $(seq 1 12); do lpt-label find 2>/dev/null | grep -E "^  state|^  media"; sleep 0.7; done
```

**`brother_ql`'s `did_print` is `false` by construction on this model** — it reads a status register
over 9100 that this printer never answers. It is `false` even when the tape comes out. Do not report
a print from the tool's word alone, and do not report a failure from `did_print`.

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
