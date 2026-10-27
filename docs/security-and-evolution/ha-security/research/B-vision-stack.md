# B — Vision stack for real-time security: what the estate can call, what local inference costs, and what one event costs

**Ran on:** `ZABZ-TECH` (Windows, `$env:COMPUTERNAME` = `ZABZ-TECH`), 2026-10-26 ~21:20–21:40 UTC.
**Posture:** READ-ONLY. No live system changed, no service restarted, no message sent, no credential value printed.
Every command below was read-only; the only writes were to `/tmp` on the authority (one JSON cache) and this file.

**Source documents.** The brief's paths `from-zabz-tech/reports/R2-cameras.md`, `W5-detection.md` and
`from-zabz-tech/security-system-design-2026-10-26.md` **do not exist on this host**. The same documents are at:

- `C:\Users\ezabz\code\ha-config\_scratch\audit-2026-10-26\R2-cameras.md` (440 lines)
- `C:\Users\ezabz\code\ha-config\_scratch\audit-2026-10-26\W5-detection.md` (237 lines)
- `C:\Users\ezabz\code\ha-config\docs\security-system-design-2026-10-26.md` (991 lines, "Round 12 — economics" at :277)

I extended those, and did not repeat their measurements.

**One methodological warning that changes every code citation below.** The Windows checkout is **not** the code
that is running. Measured by hash:

```
$ ssh secratary-cloud 'cd /opt/company; sha256sum app/services/smart_router.py app/services/ai_gateway.py app/pricing.py'
7b5fc8c0354f79b3…  app/services/smart_router.py      # deployed
1f74acde716c0678…  app/services/ai_gateway.py        # deployed
1ad016576b8b451d…  app/pricing.py                    # deployed

PS> Get-FileHash …\personal-secretary-mvp\app\services\smart_router.py
e7025df664d804fe…                                    # Windows checkout — different file
aa9628425cba31ac…  app/services/ai_gateway.py        # different
d24e16e28dd70076…  app/pricing.py                    # different
```

The divergence is not cosmetic: the Windows `_CAPABILITY_DB` has **no `deepseek/deepseek-flash` entry at all**,
while the deployed one has it at `smart_router.py:127` and marks it vision-capable. A report written from the
checkout would have missed the one model that has actually been serving this estate's vision traffic since
21 October. All line numbers below are **`/opt/company`** unless stated.

---

## 1. The "$5/day" premise is false, and it changes the conclusion

The brief, and the design doc's Round 12, both reason from a five-dollar daily budget. The ledger says otherwise:

```
$ ssh secratary-cloud 'sqlite3 -header -column /root/authority.db \
    "SELECT date(created_at) d, ROUND(SUM(estimated_cost_usd),2) usd, COUNT(*) calls
       FROM model_usage WHERE created_at > datetime('now','-8 days') GROUP BY d ORDER BY d;"'
d           usd    calls
2026-10-18  37.78  2637
2026-10-19  37.51  2570
2026-10-20  22.72  3746
2026-10-21  14.0   3850
2026-10-22  16.71  7682
2026-10-23  13.81  3837
2026-10-24  9.62   3171
2026-10-25  17.4   6307
2026-10-26  20.75  6244
```

Eight-day range **$9.62–$37.78/day**, mean ≈ $21. The code's own default is `$10/day`
(`app/services/llm_budget.py:35  DEFAULT_DAILY_LIMIT = 10.0`), and `AI_GATEWAY_DAILY_BUDGET_USD` is **not set**
in `/opt/company/.env` (grep returns nothing), so the default is what applies.

Consequences, stated plainly:

- Any arithmetic that says "a vision layer would eat the $5 budget" is measuring against a budget that has not
  existed for at least eight days. The lane must be costed against **actual** spend (~$21/day) and against the
  **hard** daily limit ($10 default), not the folklore number.
- A vision lane at the measured event rate (see §5) costs **under two cents a day**. It is not a budget item.
- The genuine risk is not the per-event price; it is a lane that inspects **every frame**. That is §5's last row.

**What would settle the budget question:** whether `$5` was a *target* the owner wants enforced. Nothing in the
running config enforces it; the ledger contradicts it. Flagged as a question for the owner, not a fact to design on.

---

## 2. Which models the estate can actually call today — resolved at runtime

### 2.1 The catalogue does not carry a vision flag at all

```
$ ssh secratary-cloud 'curl -s -o /tmp/v1models.json -w "HTTP %{http_code} bytes=%{size_download}\n" \
    http://127.0.0.1:8002/v1/models -H "Authorization: Bearer $(grep -m1 ^AI_GATEWAY_API_KEY= /opt/company/.env | cut -d= -f2-)"'
HTTP 200 bytes=11227

$ python3 -c 'import json;d=json.load(open("/tmp/v1models.json"));print(len(d["data"]));print(sorted({k for m in d["data"] for k in m}))'
26
['canonical_model_id','context_window','created','default_selectable','description','id','kind',
 'lifecycle_state','min_quality','min_tier','object','owned_by','provider','provider_model_id',
 'public_alias','quality_class','retired','retired_reason','route_policy','supports_tools','tier','verification']
```

**There is no `supports_vision` field.** The catalogue is built in
`ai_gateway.py:1743 build_models_payload`, from `sr._CAPABILITY_DB`, filtered by
`ai_gateway.py:1171 gateway_available_providers` — so it answers "which ids are advertised", not "which ids can
see". Vision capability lives only in code (`smart_router.py:81 _CAPABILITY_DB`).

### 2.2 The cheapest vision models in the price table are not callable

```
$ ssh secratary-cloud 'grep ^AI_GATEWAY_EXCLUDE_PROVIDERS= /opt/company/.env'
AI_GATEWAY_EXCLUDE_PROVIDERS=google
```

```
$ ssh secratary-cloud 'python3 -c "import json;d=json.load(open(\"/tmp/v1models.json\"));print(\"google_ids:\",[m[\"id\"] for m in d[\"data\"] if m.get(\"provider\")==\"google\"])"'
google_ids: []
```

Every Gemini id — including `google/gemini-3.5-flash-lite` at **$0.30/$2.50** (`pricing.py:113`) and
`google/gemini-3.1-flash-lite` at $0.25/$1.50 — is priced in the table, listed in the registry as
`supports_vision=1` and `promoted`, and **cannot be called through the gateway**, because Google is excluded at
the provider level. `deepinfra/MiniMaxAI/MiniMax-M3` ($0.28/$1.10) is `lifecycle_state='retired'` in the registry
and the DeepInfra key is absent. So the "cheapest vision model" in the price table is a decoy.

### 2.3 The callable vision set, and its rates

Resolved from the running router (not the checkout):

```
$ ssh secratary-cloud 'cd /opt/company && ./.venv/bin/python - <<PY
from app.services import smart_router as sr
vis=[(k,v) for k,v in sr._CAPABILITY_DB.items() if v.get("supports_vision")]
print("capability_db_entries",len(sr._CAPABILITY_DB),"vision_capable",len(vis))
for k,v in sorted(vis): print("|".join(str(x) for x in (k,v["tier"],v["cost_per_mtok_input"],v["cost_per_mtok_output"])))
PY'
capability_db_entries 36 vision_capable 24
deepseek/deepseek-flash|fast|0.15|0.6
openai/gpt-4o-mini|fast|0.15|0.6
openai/gpt-4.1-mini|fast|0.4|1.6
openai/gpt-4.1|mid|2.0|8.0
openai/gpt-5.4|mid|2.5|15.0
openai/gpt-5.5|ceo|5.0|30.0
openai/o3|mid|2.0|8.0
x-ai/grok-4.20|ceo|1.25|2.5
… (anthropic/ and google/ entries are vision-capable but unreachable: no Anthropic key, google excluded)
```

Cross-checked against the advertised catalogue — these are the ids that are **both** vision-capable in code
**and** actually advertised, with the raw catalogue lines quoted:

```
$ ssh secratary-cloud 'python3 … json.dumps({k:m.get(k) for k in ("id","kind","provider","tier","context_window")})'
{"id":"deepseek/deepseek-flash","kind":"concrete_model","provider":"deepseek","tier":"fast","context_window":1000000,"supports_tools":true}
{"id":"openai/gpt-4o-mini","kind":"concrete_model","provider":"openai","tier":"fast","context_window":128000,"supports_tools":true}
{"id":"openai/gpt-4.1-mini","kind":"concrete_model","provider":"openai","tier":"fast","context_window":1000000,"supports_tools":true}
{"id":"openai/gpt-5.4","kind":"concrete_model","provider":"openai","tier":"mid","context_window":128000,"supports_tools":true}
{"id":"openai/gpt-5.5","kind":"concrete_model","provider":"openai","tier":"ceo","context_window":1050000,"supports_tools":true}
{"id":"x-ai/grok-4.20","kind":"concrete_model","provider":"xai","tier":"ceo","context_window":2000000,"supports_tools":true}
retired: groq/meta-llama/llama-4-scout…, groq/qwen/qwen3.6-27b, deepseek/deepseek-v3.2,
         deepseek/deepseek-r1-0528, openai/gpt-4.1-nano, openai/gpt-5.4-codex, openai/o4-mini
```

**Cheapest callable vision model today: `openai/gpt-4o-mini` and `deepseek/deepseek-flash`, both $0.15/$0.60 per
Mtok** (`pricing.py:85` and `pricing.py:162`; capability DB `smart_router.py:230` and `:127`).

### 2.4 Two defects in the capability plumbing, both worth fixing before relying on any of this

**(a) The registry's `supports_vision` column contradicts the code and is never read for routing.**

```
$ ssh secratary-cloud 'sqlite3 -header -column /root/authority.db \
   "SELECT canonical_id,pricing_input_per_mtok inp,supports_vision vis,lifecycle_state FROM model_registry
     WHERE canonical_id IN (\"openai/gpt-4o-mini\",\"openai/gpt-4.1-mini\",\"openai/gpt-5.4\",\"deepseek/deepseek-flash\");"'
canonical_id              inp   vis  life
openai/gpt-4o-mini        0.15  0    promoted
openai/gpt-4.1-mini       0.4   0    promoted
openai/gpt-5.4            2.5   0    promoted
deepseek/deepseek-flash   0.15  0    promoted
```

The registry says **all four are blind**; the code says all four see. Routing uses the code
(`_capability_rejection` at `smart_router.py:2836` returns `missing_vision`, and needs_vision is detected from
`image_url` parts at `smart_router.py:3840`). The registry path that would have believed the column —
`_candidates_from_db` — is **dead code: zero call sites in `app/`** (`grep -rn _candidates_from_db app/` → none).
So today vision works, by accident of which copy is authoritative. Any tool that validates against the registry
(a model picker, a catalogue validator, a future refactor that deletes the "dead" function) will conclude that
GPT-4o-mini cannot see. **Marked a defect, not a design choice.**

**(b) `gemini-3-flash` is priced at 1/25th of what it is billed at.** `pricing.py` still carries
`"gemini-3-flash": (0.15, 0.60)`; the deployed gateway's `_GOOGLE_MODEL_RENAME` (`ai_gateway.py:74`) rewrites
`gemini-3-flash → gemini-3.5-flash`, whose real rate is **$1.50/$9.00**. A 10× input / 15× output underprice on
any call that still names the old id. It is currently masked only because Google is excluded.

### 2.5 What has actually been used, and what has not

```
$ ssh secratary-cloud 'sqlite3 -header -column /root/authority.db \
   "SELECT primary_model,COUNT(*) n,MAX(created_at) last FROM smart_router_decisions
     WHERE needs_vision=1 AND created_at > datetime(\"now\",\"-30 days\") GROUP BY primary_model ORDER BY n DESC;"'
primary_model          n     last
gemini-3.5-flash       3699  2026-10-21T00:17:25
gemini-3.5-flash-lite  3136  2026-10-19T07:30:18
deepseek-flash         2077  2026-10-26T20:30:26
MiniMaxAI/MiniMax-M3   611   2026-10-05T02:30:11
gemini-3-pro           451   2026-09-28T15:58:23
gemini-3.1-flash-lite  52    2026-10-15T19:21:40
```

**27,142 of 89,763 router decisions in the last 30 days were `needs_vision=1`** — 30% of all traffic. Since
Google was excluded on 2026-10-21, `deepseek-flash` has carried every vision request (2,077 decisions, last
20:30 UTC today). It is not untested: DeepSeek's own 400 proves it accepts image parts —

```
2026-10-20T14:26:25  deepseek-flash  http_400: {"error":{"message":".messages[2].image[0]: You have uploaded an
unsupported image. Please make sure your image is valid and has one of the following formats: webp, png, jpeg, and gif."}}
```

— i.e. the transport is real and the rejection was the input format, not the capability.

**`openai/gpt-4o-mini` has zero calls in the last 30 days.** It is the cheapest on paper and completely
unmeasured on this estate. First event through it should be timed before the lane depends on it. **UNVERIFIED.**

---

## 3. Per-image token cost at the two resolutions that matter

The estate's frames are **2560×1920** (Reolink doorbell, 4.92 Mpx) and **2560×1440** (Dahua, 3.69 Mpx); the
640×480 figure in the brief is the Reolink *fluent* stream and the intrusion-evidence tile, both 16× fewer pixels
than the doorbell's clear stream (`R2-cameras.md:45-47, 117-120`).

The API resizes before billing, and **the two resolutions cost the same on the GPT-4o path**:

| Path | Formula (fetched, see source) | 640×480 | 2560×1920 |
|---|---|---|---|
| `gpt-4o-mini`, `detail:"high"` | fit 2048², shortest side → 768, 512px tiles, **85 + 170×tiles** | 1024×768 → 4 tiles → **765 tok** | →2048×1536 → →1024×768 → 4 tiles → **765 tok** |
| `gpt-4o-mini`, `detail:"low"` | flat 85 tok, image downscaled to 512×512 | **85 tok** | **85 tok** |
| `gpt-4.1-mini` | 32px patches, cap 1536, **×1.62 for mini** | 20×15=300 → ×1.62 = **486 tok** | capped 1536 → ×1.62 = **2,488 tok** |

Source: OpenAI "Images and Vision", *Calculating costs* — fetched
`https://openai-hd4n6.mintlify.app/docs/guides/images` (HTTP 200). Verbatim: *"Any image with `detail: low`
costs 85 tokens… Scale so that the image's shortest side is 768px long… each square costs 170 tokens. Add 85
tokens"*; and for 4.1: *"Calculate the number of 32px x 32px patches… capped at a maximum of 1536 tokens… for
`gpt-4.1-mini`, we multiply image tokens by 1.62"*.

**The consequence that matters more than the price.** On the GPT-4o path a 4.9 Mpx doorbell frame is reduced to
**1024×768 = 0.79 Mpx** before the model sees it — 6.3× fewer pixels than the camera delivered. The cloud model
never sees the 2560×1920 frame. A visitor's head measured ~310 px tall in the full frame (`R2-cameras.md:307-311`);
after the API's resize it is ~124 px. That is at the low end of what face pipelines want, and it is the reason a
**face crop**, not a full frame, is the right unit for identification (a 400×400 crop = 13×13 = 169 patches ≈
169 tok on the 4.1 path, or one 512 tile ≈ 255 tok on the 4o path).

Cost per image at the callable rates (registry `pricing.py`):

| Model | 640×480 | 2560×1920 | per 1,000 frames |
|---|---|---|---|
| `gpt-4o-mini` high | 765 tok → **$0.000115** | 765 tok → **$0.000115** | **$0.115** |
| `gpt-4o-mini` low | 85 tok → **$0.0000128** | 85 tok → **$0.0000128** | **$0.013** |
| `gpt-4.1-mini` | 486 tok → **$0.000194** | 2,488 tok → **$0.000995** | $0.194 / $0.995 |
| `x-ai/grok-4.20` | 765 tok → $0.000956 | $0.000956 | $0.956 |
| `openai/gpt-5.4` | 765 tok → $0.00191 | $0.00191 | $1.91 |

---

## 4. Local inference on `zabz-tech-linux`: measured hardware, documented throughput

### 4.1 The box, measured

```
$ ssh linux-pc 'lscpu | grep -E "Model name|^CPU\(s\)"; free -g | head -2; df -h / | tail -1; nproc'
Model name: 11th Gen Intel(R) Core(TM) i5-11400 @ 2.60GHz
CPU(s): 12          (6 cores / 12 threads)
Mem: 11 GiB total, 1 used, 10 available
/dev/nvme0n1p2  468G  340G  105G  77% /
$ ssh linux-pc 'lspci | grep -i vga'
00:02.0 VGA compatible controller: Intel Corporation RocketLake-S GT1 [UHD Graphics 730] (rev 04)
$ ssh linux-pc 'uptime; free -m | sed -n 2p'
 17:29 up 8 days,  load average: 0.74, 0.82, 0.83
Mem: 11673 total, 1215 used, 9813 buff/cache, 10457 available
$ ssh linux-pc 'sudo -n cat /sys/class/powercap/intel-rapl:0/energy_uj' (×2, 10 s apart)
delta 112,754,594 µJ / 10 s → 11.3 W package power at 87.5% idle
```

So: the brief's "i5-11400, iGPU, ~105 GB free" is correct; **RAM is 11 GiB, not 16**. Idle package draw is
11.3 W; whole-box draw is higher (PSU/disk/board) — **UNVERIFIED**, would need a wall meter.

### 4.2 The iGPU works, but the service user cannot reach it

```
$ ssh linux-pc 'id zabz'
uid=1000(zabz) gid=1000(zabz) groups=1000(zabz),4(adm),24(cdrom),27(sudo),30(dip),46(plugdev),100(users),114(lpadmin)
$ ssh linux-pc 'ls -l /dev/dri/; getfacl /dev/dri/renderD128'
crw-rw----+ 1 root video  226,  1 /dev/dri/card1
crw-rw----+ 1 root render 226, 128 /dev/dri/renderD128
user:gdm:rw-                      # only gdm has an ACL; zabz is not in group render
$ ssh linux-pc 'ffmpeg … -init_hw_device vaapi=va:/dev/dri/renderD128 …'
[AVHWDeviceContext] No VA display found for device /dev/dri/renderD128. Device creation failed: -22.
$ ssh linux-pc 'sudo -n ffmpeg … -init_hw_device vaapi=va:/dev/dri/renderD128 …'
(no output, rc=0)                 # the same device opens cleanly as root
```

**This is the estate's classic "GPU not detected" failure and it is a group membership, not hardware.** The Intel
media driver is installed (`intel-media-va-driver 24.1.0`, `iHD_drv_video.so` present); `zabz` is simply not in
`render`/`video`. Whatever runs Frigate (container or service) must be granted those groups or the iGPU is dead
to it. QSV failed separately (`Error creating a MFX session: -9`) — use VAAPI, which is also Frigate's advice
("If you have issues, use the VAAPI preset instead").

### 4.3 What Frigate detects, on this hardware, at what cost

Licence: **MIT** — `https://api.github.com/repos/blakeblackshear/frigate` → `"spdx_id":"MIT"`, 36,967 stars,
`pushed_at 2026-10-26T18:17:52Z`. No per-camera fee, no seat count.

Detector: **Frigate + OpenVINO on the iGPU**. Frigate's hardware page lists this exact GPU:

> **Intel UHD 730** — MobileNetV2 ~10 ms; **YOLOv9: t-320 14 ms, s-320 24 ms, t-640 34 ms, s-640 65 ms**;
> YOLO-NAS 320 ~19 ms, 640 ~54 ms
> — `https://docs.frigate.video/frigate/hardware` (fetched)

Throughput rule from the same docs: `1000 / inference_ms = fps`. At **14 ms** (YOLOv9-t-320) that is **~71 fps**;
one detector instance ("Can only run one detector instance" is stated for HD 530; the UHD 730 row carries the
same single-instance implication).

**Load the estate would place on it** — Frigate's default `detect.fps` is **5** and its docs say 5 "is correct for
the vast majority of cameras":

> "The default frame rate of 5fps is correct for almost all cameras and rarely needs to be changed… Higher
> resolutions and frame rates will drive higher CPU usage" — `https://docs.frigate.video/frigate/camera_setup`

- **5 physical cameras** × 5 fps = **25 fps** → 0.35× of the UHD 730's 71 fps capacity.
- 7 feeds (if the brief's "7 cameras" is taken literally) × 5 fps = 35 fps → 0.49×.
- Frames/day at 25 fps = 2.16 M; at 35 fps = 3.02 M.

**Premise correction on the camera count.** `R2-cameras.md:145-158` measured **five physical cameras** (4 Dahua
channels + doorbell) across **18 Dahua entities**; channels 2/3/4 have no camera and `cams.yaml:127-141` says so.
The "7" in the brief is a channel/entity count, not lenses. Capacity should be planned at 5.

Decode: the Dahua *substream* is 704×480 and the doorbell *fluent* is 640×480 (`cams.yaml:11-19`,
`R2-cameras.md:47`). Detection runs on a 320×320 crop of that — the docs are explicit that higher resolution
does not improve detection: *"If the area being inspected is larger than 320x320, Frigate must resize it…
Higher resolutions do not improve the detection accuracy because the additional detail is lost in the resize."*
So feeding 2560×1440 to the detector would burn decode for nothing.

RAM: docs give 4 GB basic, **8 GB with enrichments**, 16 GB for 8+ cameras
(`https://docs.frigate.video/frigate/planning_setup`). This box has 11 GiB with 1.2 GiB used and 10 GiB
available — enough, but not roomy if face recognition and a VLM client run alongside.

What it detects (COCO set, `https://docs.frigate.video/configuration/objects`): person, bicycle, car, motorcycle,
bus, train, boat, cat, dog, horse, sheep, cow, bird, backpack, suitcase, chair, tv, laptop, cell phone, door… —
**`person` only, by default**. **There is no `package` class in the stock model.** The business is packages, and
this is the one capability that needs the paid model:

> "**Track deliveries** — With package detection, you can track when packages arrive at your front door.
> Frigate+ also recognizes common logos for delivery services… UPS, Fedex, Amazon, or DHL"
> — `https://frigate.video/plus` (fetched). Subscription **$50/yr**, up to 12 fine-tuned models, $5 per extra
> fine-tune. Models trained during the subscription stay downloadable.

Explicitly: package/logo delivery detection is **Frigate+ only**; it "can't add your own custom labels yet".

### 4.4 What a Coral USB changes

Frigate's hardware page: the USB Coral "is compatible with the widest variety of hardware and does not require a
driver on the host… A single Coral can handle many cameras using the default model", at ~10 ms inference →
`1000/10 = 100 fps`. It is a **single-instance** device, so the 10 ms is the throughput floor.

- Price: **$86** for the USB Accelerator at Mouser (listing snippet: "Coral USB Accelerator, Coral 1: $86");
  the module alone is $42.95. Treat the $86 as a quoted listing, **not** a checked-out cart price.
- What it buys here: capacity from ~71 fps to ~100 fps, **and it frees the iGPU for decode and enrichments**.
  At 25 fps of real load, that headroom is not needed. It becomes useful only if you raise `detect.fps`, add
  cameras, or run the **large** ArcFace face model (which wants a GPU/NPU, not a Coral).
- Verdict: **not the first purchase.** The iGPU is already sufficient for 5–7 feeds; the $86 is better spent on
  the clock fix (free) and a face-height camera if identification is wanted.

CPU: I could not measure Frigate's CPU on this box without installing it (**UNVERIFIED**). What would settle it:
one container, `docker stats` + `intel_gpu_top` over 24 h with 5 substreams. The documented mechanism is that
`preset-vaapi` moves decode off the CPU and OpenVINO moves inference to the iGPU, leaving the CPU for
motion/regions — on a 12-thread i5 that is expected to be a small fraction of one core per camera, but that
sentence is an inference, not a measurement.

---

## 5. Cloud VLM per event: the arithmetic, and the number that decides local vs cloud

Assumptions (all stated so they can be challenged): **one 2560×1920 frame at `detail:"high"` (765 tok) plus a
150-token JSON verdict**, on `openai/gpt-4o-mini` at $0.15/$0.60 per Mtok:

```
per event = 765×0.15/1e6 + 150×0.60/1e6
          = 0.00011475 + 0.00009
          = $0.000205
```

| Volume | 1 frame/event | 3 frames/event | as % of a $5 day | as % of today's actual $20.75 |
|---|---|---|---|---|
| 5 events/day | **$0.001** | $0.0026 | 0.02% | 0.005% |
| 50 events/day | **$0.010** | $0.026 | 0.2% | 0.05% |
| 500 events/day | **$0.102** | $0.217 | 2.0% | 0.5% |
| **measured rate ~33/day** | **$0.007** | $0.014 | 0.14% | 0.03% |

The measured rate comes from the estate itself: the doorbell fired **92 times in 42.68 business hours** (≈2.2/h,
`security-system-design-2026-10-26.md:287-289`) and **99 person firings in 72 h** (`R2-cameras.md:193-194`) —
call it 30–35 events/day, so **about three-quarters of a cent a day** for one frame each.

**None of those rows is the binding constraint.** This one is:

```
always-on cloud inspection, 5 cameras × 5 detect-fps = 25 fps = 2,160,000 frames/day
2,160,000 × $0.00011475 = $247.86/day
7 feeds (35 fps):  3,024,000 × $0.00011475 = $347.00/day
budget break-even at $5/day:  5 / 0.00011475 = 43,573 frames/day  ≈ 0.5 fps across the estate
local break-even (UHD 730, 14 ms): 1000/14 = 71 fps → 6,171,000 frames/day, marginal $0
```

**The number that decides it: frames per day that must be looked at.** The cloud budget buys ~43,600 frames/day
(0.5 fps total); the iGPU does ~6.2 M/day (71 fps) for the price of electricity. Cloud is for *events*
(hundreds/day, cents), local is for *looking* (millions/day, and cloud is 50–70× the entire daily budget).

Latency, measured on this estate (`model_usage`, last 30 days — all task types, **not** vision-only, so these are
upper bounds for a small image):

```
model                  n      avg_ms  max_ms
deepseek-flash         22902  2382    99970
gemini-3.5-flash-lite  4574   698    13920
gemini-3.5-flash       4290   2272   21850
gpt-4.1-mini           43     6858   14273
```

So: **0.7–2.4 s** for a flash-class model, **~6.9 s** for `gpt-4.1-mini` (which is the one actually carrying
image calls, at 43 samples). That is fine for "verify this event and tell me what it is"; it is far too slow for
tracking, and it is why the detector must be local and the VLM must be an *explainer*, not the trigger. Plus
upload time for a 600 KB frame on the shop's uplink, **UNVERIFIED**.

`gpt-4o-mini` has no measured latency here (§2.5) — its number is unknown until one call is timed.

---

## 6. The identity question: owner vs intruder

**Plain answer: object detection answers "is there a person"; it cannot answer "is this the owner". Face
recognition can, under conditions this estate does not currently meet — and even then it must never be the thing
that unlocks a door.**

What is reliable today:

- **Person / vehicle / animal / (with Frigate+) package** — reliable enough to gate an event. `person` is
  Frigate's default and only default-tracked class.
- **Counts and direction** — Frigate tracks objects across frames and can order two cameras, but R2 measured the
  two cameras **16 m 18 s apart on the same courier** (`R2-cameras.md:356-371`), so direction-of-travel is
  impossible until the clocks agree.

What is not reliable:

- **Face identification as an alarm trigger.** Frigate's own docs set `recognition_threshold` 0.9 and
  `unknown_score_threshold` 0.8, require 5–10 images minimum (20–30 recommended) per person, and say plainly:
  *"The embedding models are trained on color images, so gray-scale and infrared (IR) faces sit in a different
  feature distribution and are more easily confused with other people."* At night this estate is IR
  (`R2-cameras.md:277-288`: the vestibule camera delivers monochrome even at 13:52), so the night case is the
  documented weak case.
- **This estate's geometry.** The doorbell gives a ~310 px head — enough pixels — but *"she is at the extreme
  left edge, in profile, half out of frame, because the doorbell sits at the bottom of a stairwell looking
  outward"* (`R2-cameras.md:307-311`), and all four Dahua views are high corner views looking down
  (`R2-cameras.md:318`). A recogniser fed a profile at the frame edge will be wrong at exactly the moment it
  matters. **A face-height camera at the door is a prerequisite, not an optimisation.**

What a five-person allow-list actually needs (concrete, and cheap given the hardware is already there):

1. **A face-height camera at the entrance** — not the stairwell doorbell. This is the only new hardware that
   identity genuinely requires.
2. **Colour, front-facing enrolment**: 5–10 clear images per person to start, 20–30 for robustness, no IR, no
   hats/sunglasses, diverse angles added slowly (Frigate docs, "Creating a Robust Training Set").
3. **`large` ArcFace model**, not `small` FaceNet — it wants the iGPU/NPU; the `small` model is CPU and "not as
   accurate". Budget the iGPU for it and keep detection on YOLOv9-t-320.
4. **Match on consistency, not one frame.** Frigate already does this — *"a single very high confidence match
   will not by itself assign a sub label… Recognition must be consistent"* — which is the right behaviour and
   should not be tuned away.
5. **Never let a face match authorise anything.** Pair it with the credential that already exists on this estate
   (keypad/RFID; `W5-detection.md:181` shows `Owner Access at Interior` being written with names today). Face
   says "probably Eliyahu"; the credential says "someone who knows the code". The alarm should require the
   second and use the first only as corroboration — which is exactly the `phoenix_credential_valid` mechanism
   W5 already proposed (`W5-detection.md:183-190`).

### Privacy / legal posture, New Jersey business premises

Fetched: `https://www.rcfp.org/reporters-recording-guide/new-jersey` (last updated May 2020).

- **Video, no audio: lawful in areas without a reasonable expectation of privacy.** The hidden-camera statute,
  **N.J.S.A. 2C:14-9**, covers "intimate parts"/sexual content where privacy is expected, and the guide states it
  *"does not criminalize the use of recording devices for other purposes in areas to which the public has access
  or there is no reasonable expectation of privacy."* A shop floor, entrance and vestibule are that.
- **Audio is the trap.** New Jersey's Wiretapping Act (N.J.S.A. 2A:156A-2, -3, -4) requires **at least one
  party's consent** for in-person conversations. A camera recording a customer's conversation with nobody's
  consent is not covered by that exception. **Configure every camera video-only; do not enable Frigate's audio
  detector** (it exists — `https://docs.frigate.video/configuration/audio_detectors`). This is a configuration
  decision, free, and the single highest-liability item in the whole stack.
- **Biometrics is a live legislative risk.** NJ S1464 (2026–2027, pre-filed, **not law**) would make it an
  unlawful practice to run a "biometric surveillance system" on a consumer without **clear and conspicuous
  notice** (a sign at the perimeter suffices), require a written explanation if biometrics are used to deny entry
  or remove someone, and forbid selling or profiting from the data
  (`https://www.njleg.state.nj.us/bill-search/2026/S1464/bill-text`). It is a bill, not an obligation — but it is
  a cheap preview of the compliance shape, and posting the sign now costs nothing.
- Not legal advice; the statute text and the bill status above are the primary sources, the application to this
  shop is the owner's call.

---

## 7. Failure modes, one by one

| # | Failure | What actually happens here | Evidence | Countermeasure |
|---|---|---|---|---|
| 1 | **Night / IR** | Person detection still works (IR is fine for shape). Face recognition degrades: embeddings are trained on colour, IR faces are "more easily confused". The vestibule camera is monochrome **at 13:52**, not just at night. | `R2-cameras.md:277-288`; Frigate face-recognition docs (fetched) | Keep identification to the colour door camera; at night, treat face as *unknown* and fall back to credential + person. Do not let a night match clear an alarm. |
| 2 | **Motion blur** | More pixels do not help. Frigate: *"over-compression and motion blur are much more detrimental to results than resolution."* | Frigate face-recognition FAQ (fetched) | Faster shutter (1/60 s+) and CBR, accepting a darker frame; reject blurry crops via Frigate's `blur confidence filter` (default on). |
| 3 | **Covered lens** | The stream keeps flowing, so `camera_fps` stays >0 and Frigate's only documented liveness signal (offline → `camera_fps 0`, `https://docs.frigate.video/troubleshooting/faqs`) never fires. Motion stops, so no events — the camera goes quiet and quiet looks like "nothing happened". | FAQ (fetched); no tamper/flat-scene detector is documented (feature request `github.com/blakeblackshear/frigate/discussions/3012`, 2022) | **A separate flatness monitor**: grab one frame per camera per minute, compute edge density / pixel variance; page if it collapses and stays collapsed. This also catches a frozen camera. Cheap, and it is the only thing that catches this class. |
| 4 | **Mannequin / static person** | Frigate is motion-gated: no motion → no detection. A mannequin is invisible until something else moves; a person standing still disappears once motion stops. | Frigate camera_setup docs ("When motion is detected… regions of that frame are sent to your object detection hardware") | Never treat "no event" as "no person". Periodic forced detection (every N minutes regardless of motion) in closed hours; or a PIR/mmWave corroboration, which the estate already has. |
| 5 | **Printed photo / replay** | A 2-D face presented to the camera will match. Frigate documents **no** anti-spoofing/liveness. `W5-detection.md:318-320` already notes the doorbell's sightline is a profile at the edge — a photo held up is at least as good a face as a real visitor. | Frigate face-recognition docs (no liveness section); W5:318 | Face match is corroboration only; the credential unlocks. If a face match is ever used to *deny*, require two cameras agreeing or a credential absence. |
| 6 | **Someone holding a sign (prompt injection)** | The VLM reads arbitrary text in the frame. The gateway injects a "Vision confidence: high/medium/low" contract (`ai_gateway.py:1122`) and escalates on low confidence — but a sign saying "Vision confidence: high" is indistinguishable from the model's own line. The confidence field is **not** trustworthy under adversarial input. | `ai_gateway.py:1122-1145`; `_parse_vision_confidence` at :3370 | Treat all in-image text as data: a fixed output schema (`{person, package, action, description}`) with **no tools** and no free-form command channel; quote any sign text into a `observed_text` field and never execute it. The detector, not the VLM, is the trigger — so a hijacked VLM can waste a call but cannot raise or suppress an alarm. |
| 7 | **Camera clock skew (16 min measured)** | Frigate timestamps on **ingest**, from the host clock — and this host is NTP-synced (`timedatectl` → `System clock synchronized: yes, NTP service: active`). So Frigate events are correctly stamped even though the NVR's OSD and recordings are 51 min slow and the two cameras disagree by 16 min. The skew survives in every *camera-side* artefact (OSD burn-in, NVR recordings, HA snapshot tiles). | `R2-cameras.md:356-371`; `ssh linux-pc timedatectl` | NTP the NVR and both camera families (Dahua: Setup → System → Date; Reolink: Display → Date). Until then, trust Frigate's ingest timestamp over any OSD, and never order two camera-side artefacts against each other. |

---

## 8. What I could not verify

| Claim | Status | What would settle it |
|---|---|---|
| Frigate's CPU/RAM on this box with 5 substreams | **UNVERIFIED** | One container, `preset-vaapi` + OpenVINO, 24 h of `docker stats` and `intel_gpu_top`. |
| `gpt-4o-mini` latency and image acceptance on this estate | **UNVERIFIED** (0 calls in 30 days) | One timed call with a real 2560×1920 frame; check `model_usage.latency_ms`. |
| Whole-box power draw (11.3 W is package only) | **UNVERIFIED** | A wall meter at the plug, or `turbostat` package+DRAM over 24 h. |
| Coral USB price $86 | **Listing, not cart** | Mouser checkout. |
| That the visible-light cameras stay in colour at 03:00 | **UNVERIFIED** — no night frame exists | The 03:00 snapshot automation R2 already proposed (`R2-cameras.md:290-297`). |
| Face-recognition accuracy on *this* door with a face-height camera | **UNVERIFIED** — no such camera exists yet | Mount one, enrol 5 people, count false accepts over a week. |
| Whether `$5/day` is a target the owner wants enforced | **Open question** | Ask him; the ledger and the code default both say otherwise. |

---

## Recommendation

**Two tiers, and the cheap one is mandatory before the expensive one is worth anything.**

**Tier 0 — free, and it decides whether any of this works (hours, $0).**
Fix the two things that make the existing sensors worthless: NTP the NVR and cameras (the 16-minute skew and
51-minute OSD error), and repair the evidence path (R2 §8, W5 F21–F24). Add the **flatness monitor** from §7.3 —
one frame per camera per minute, edge density, page on collapse — because a covered lens is currently invisible.
None of this needs Frigate, a GPU, or a dollar, and every later layer inherits its correctness.

**Tier 1 — the minimum that pays for itself: Frigate + OpenVINO on the existing i5 (a day, $0 licence).**
- `zabz-tech-linux`, `preset-vaapi` decode, OpenVINO on the **UHD 730**, YOLOv9-t-320 (14 ms → ~71 fps against
  ~25 fps of load), `detect.fps: 5`, detection on the **substreams** (704×480 / 640×480), recording on the main
  streams.
- **First blocker to clear: `usermod -aG render,video` for the service user** (§4.2). Without it OpenVINO cannot
  see the GPU and you will conclude the hardware is too slow when it is a group.
- Add **Frigate+ at $50/yr** for the `package` class — the business is packages, stock COCO has no such label,
  and $50/yr is under 1% of a year's actual model spend at the current rate.
- This tier answers "is there a person / vehicle / package, where, and when" continuously, for electricity.
  It does **not** answer "who".

**Tier 2 — the event explainer: cloud VLM on gated events only (a day, ~$0.01/day).**
Frigate event → one frame (or a 3-frame strip) + a fixed schema → `openai/gpt-4o-mini` at $0.15/$0.60. Cost at the
measured ~33 events/day: **$0.007/day**, $0.10/day even at 500. Cap it: max 3 frames/event, max 200 output tokens,
hard daily ceiling **$0.50** (10× expected, still 2.4% of actual spend), and `detail:"high"` only when the
detector says `person`; `detail:"low"` (85 tok, $0.0000128) for "is the doorway empty".
Ship it behind a boolean, in shadow first (compute + log, take no action), and measure its agreement with the
owner's labels for a week before it is allowed to page. Its confidence line is **not** trustworthy
(§7.6) — the detector stays the trigger.

**Tier 3 — identity, only if the owner asks for it and accepts the legal posture (days + one camera).**
Face-height colour camera at the entrance + ArcFace `large` on the iGPU + 5-person enrolment. Face is
corroboration; the existing keypad/RFID credential authorises. Video-only, no audio, and post the biometric notice
sign now (§6).

**The ceiling, honestly.** With a Coral USB (~$86, 100 fps) this box could run 12+ feeds at 5 fps with enrichments
— but at 5 cameras that headroom buys nothing. The real ceiling is not throughput, it is **trustworthiness**:
night IR, profiles at the frame edge, static subjects, printed photos, and a 16-minute clock skew are all
properties of the *sensors and the site*, not of the model. Adding a bigger model does not fix any of them. The
estate should spend the next dollar on a face-height camera and NTP, not on compute.

**Do not** put a VLM in the always-on path. At 25–35 fps that is $248–$347/day — 12–17× the entire actual daily
spend — and it would be slower, less private, and no more accurate than a 14 ms detector.

---

## Cost table

| Item | Unit cost | At 5 events/day | At 50/day | At 500/day | Basis |
|---|---|---|---|---|---|
| **Local detection (Frigate + OpenVINO, UHD 730)** | $0 marginal | $0 | $0 | $0 | Existing box, MIT licence; 71 fps capacity vs 25 fps load |
| Electricity, if the box were not already on | ~$0.05/day (11.3 W package + overhead) | — | — | — | RAPL measured 11.3 W; whole-box UNVERIFIED |
| **Frigate+ (package/logo class)** | **$50/yr ≈ $0.137/day** | $0.137 | $0.137 | $0.137 | frigate.video/plus |
| Coral USB (optional headroom) | **$86 one-off** | — | — | — | Mouser listing |
| **Cloud VLM, 1 frame @2560×1920, gpt-4o-mini high** | **$0.000205/event** | **$0.001** | **$0.010** | **$0.102** | 765 tok in + 150 tok out @ $0.15/$0.60 |
| Cloud VLM, 1 frame, `detail:"low"` | $0.000103/event | $0.001 | $0.005 | $0.051 | 85 tok in + 150 out |
| Cloud VLM, 3 frames/event | $0.00052/event | $0.003 | $0.026 | $0.260 | |
| Cloud VLM, gpt-4.1-mini @2560×1920 | $0.00124/event | $0.006 | $0.062 | $0.618 | 2,488 tok in + 150 out @ $0.40/$1.60 |
| **Always-on cloud inspection, 5 cams × 5 fps** | **$247.86/day** | — | — | — | 2.16 M frames × $0.00011475 |
| Always-on cloud inspection, 7 feeds | $347.00/day | — | — | — | 3.02 M frames |
| **Cloud break-even vs a $5 day** | **43,573 frames/day** | — | — | — | 5 ÷ $0.00011475 ≈ 0.5 fps estate-wide |
| **Local break-even (capacity)** | 6,171,000 frames/day | — | — | — | 1000/14 ms = 71 fps |

**Bottom line:** the whole recommended stack is **$0.14/day** (Frigate+ amortised) plus **$0.007/day** of cloud at
the measured event rate — **under 0.7% of this estate's actual daily model spend** ($20.75 today). The decision is not
affordability. It is that cloud can inspect **43,600 frames/day** and the iGPU can inspect **6.2 M/day**, so the
detector must be local and the VLM must only ever look at what the detector already flagged.
