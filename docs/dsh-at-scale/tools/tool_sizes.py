"""Measure tool-result payload sizes and how much of them survive into context.

The thresholds are READ FROM THE LIVE PRESET, not hardcoded. The first version of this
script hardcoded 8192/4096/1024 (a copy of what the preset said at the time), so after the
2026-09-16 tightening it kept reporting 76.7 % and could not verify anything -- a
measurement tool that duplicates the config it measures is worse than none, because it
looks like evidence.

Usage:
  python tool_sizes.py                 # the 3 largest session logs, live preset values
  python tool_sizes.py <log> [...]     # specific logs
  python tool_sizes.py --threshold 2000 --head 800 --tail 400 [...]   # what-if
"""
import collections, json, os, re, sys
import zstandard as zstd

PRESET = r"C:\Users\ezabz\code\harness-config\presets\zabz\agent.cordis.yml"


def from_preset() -> tuple[int, int, int]:
    """Read the pruner's live values. Falls back to the shipped defaults if unreadable."""
    try:
        text = open(PRESET, encoding="utf-8").read()
        def val(key: str, default: int) -> int:
            m = re.search(r"^\s*%s:\s*(\d+)" % key, text, re.M)
            return int(m.group(1)) if m else default
        return val("thresholdChars", 8192), val("headChars", 4096), val("tailChars", 1024)
    except OSError:
        return 8192, 4096, 1024


argv = sys.argv[1:]
if "--threshold" in argv:
    RUNGGES = int(argv[argv.index("--threshold") + 1])
    HEAD = int(argv[argv.index("--head") + 1])
    TAIL = int(argv[argv.index("--tail") + 1])
    for flag in ("--threshold", "--head", "--tail"):
        i = argv.index(flag)
        del argv[i:i + 2]
else:
    RUNGGES, HEAD, TAIL = from_preset()

d = zstd.ZstdDecompressor()

paths = argv
if not paths:
    sess = r"C:\Users\ezabz\.dsh\sessions\--C-Users-ezabz-code--"
    biggest = []
    for dirpath, _dn, fns in os.walk(sess):
        for fn in fns:
            if fn.startswith("session."):
                p = os.path.join(dirpath, fn)
                biggest.append((os.path.getsize(p), p))
    biggest.sort(reverse=True)
    paths = [p for _s, p in biggest[:3]]

grand_raw = grand_kept = 0
per = []
for p in paths:
    text = d.stream_reader(open(p, "rb")).read().decode("utf-8", "replace")
    raw = kept = 0
    n = over = 0
    sizes = []
    for ln in text.splitlines():
        if '"tool/result"' not in ln:
            continue
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("type") != "tool/result":
            continue
        body = json.dumps(o.get("data"))
        L = len(body)
        raw += L
        n += 1
        sizes.append(L)
        if L > RUNGGES:
            over += 1
            kept += HEAD + TAIL
        else:
            kept += L
    per.append((os.path.basename(os.path.dirname(p)), n, raw, kept, over, sizes))
    grand_raw += raw
    grand_kept += kept

print(f"pruner config: thresholdChars={RUNGGES} headChars={HEAD} tailChars={TAIL}")
print()
for sid, n, raw, kept, over, sizes in per:
    sizes.sort(reverse=True)
    print(f"{sid[:46]}")
    print(f"   tool/result events      : {n}")
    print(f"   raw payload chars       : {raw:,}")
    print(f"   over {RUNGGES} chars             : {over} ({100*over/max(n,1):.1f}%)")
    print(f"   chars after pruning     : {kept:,}  ({100*kept/max(raw,1):.1f}% of raw)")
    if sizes:
        print(f"   largest result chars    : {sizes[0]:,}")
        print(f"   top10 share of raw      : {100*sum(sizes[:10])/max(raw,1):.1f}%")
    print()
print(f"ALL FILES: raw={grand_raw:,} chars  pruned={grand_kept:,} chars "
      f"({100*grand_kept/max(grand_raw,1):.1f}%)")
print(f"  => pruner suppresses {grand_raw-grand_kept:,} chars "
      f"(~{(grand_raw-grand_kept)//4:,} tokens at 4 chars/token)")
