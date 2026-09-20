"""Read-only scan of DSH session logs for per-request token accounting.

Usage:  python scan_sessions.py [--root DIR] [--since YYYY-MM-DD] [--dump-keys]
Prints: per-file token totals + which JSON keys carry usage. Writes nothing.
"""
import argparse, collections, json, os, re, sys, datetime

try:
    import zstandard as zstd
except ImportError:
    sys.exit("need zstandard")

ROOT = r"C:\Users\ezabz\.dsh\sessions"
USAGE_KEY_HINTS = (
    "usage", "prompt_tokens", "completion_tokens", "total_tokens",
    "cached_tokens", "cache_hit", "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens", "input_tokens", "output_tokens",
    "reasoning_tokens", "cost",
)

dctx = zstd.ZstdDecompressor()


def read_lines(path):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return []
    if path.endswith(".zstd"):
        # DSH writes MULTI-FRAME zstd (append-only). ZstdDecompressor.decompress()
        # stops at the first frame and silently returns almost nothing.
        try:
            with open(path, "rb") as fh:
                with dctx.stream_reader(fh) as reader:
                    raw = reader.read()
        except Exception as exc:
            print(f"  !! cannot decompress {path}: {exc}", file=sys.stderr)
            return []
    return raw.decode("utf-8", "replace").splitlines()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--since", default=None)
    ap.add_argument("--dump-keys", action="store_true")
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    since = None
    if args.since:
        since = datetime.datetime.fromisoformat(args.since).replace(
            tzinfo=datetime.timezone.utc)

    files = []
    for dirpath, _dirnames, filenames in os.walk(args.root):
        for fn in filenames:
            if fn.startswith("session.") and fn.endswith(".jsonl.zstd"):
                p = os.path.join(dirpath, fn)
                files.append((os.path.getmtime(p), p))
    files.sort(reverse=True)
    print(f"# session log files found: {len(files)}", file=sys.stderr)

    key_counter = collections.Counter()
    per_file = []          # (mtime, path, requests, ptok, ctok, cache_hit, cache_miss)
    usage_shapes = collections.Counter()
    samples = []

    for mtime, path in files:
        if since and datetime.datetime.utcfromtimestamp(mtime) < since:
            continue
        lines = read_lines(path)
        reqs = 0
        ptok = ctok = chi = cmiss = 0
        for ln in lines:
            if '"usage"' not in ln and "prompt_tokens" not in ln:
                continue
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            stack = [obj]
            found = None
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    if "usage" in cur and isinstance(cur["usage"], dict):
                        found = cur["usage"]
                    for k, v in cur.items():
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(cur, list):
                    stack.extend(cur)
            if not found:
                continue
            reqs += 1
            usage_shapes[tuple(sorted(found.keys()))] += 1
            for k in found:
                key_counter[k] += 1
            d = found
            ptok += int(d.get("prompt_tokens") or d.get("input_tokens") or 0)
            ctok += int(d.get("completion_tokens") or d.get("output_tokens") or 0)
            hit = d.get("cached_tokens")
            if hit is None:
                hit = d.get("prompt_cache_hit_tokens")
            miss = d.get("prompt_cache_miss_tokens")
            if hit is None and isinstance(d.get("prompt_tokens_details"), dict):
                hit = d["prompt_tokens_details"].get("cached_tokens")
            chi += int(hit or 0)
            if miss is not None:
                cmiss += int(miss or 0)
            elif hit is not None:
                cmiss += int((d.get("prompt_tokens") or 0)) - int(hit or 0)
            if len(samples) < 6:
                samples.append((path, found))
        if reqs:
            ts = datetime.datetime.utcfromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            per_file.append((mtime, path, reqs, ptok, ctok, chi, cmiss))
            print(f"{ts}Z reqs={reqs:5d} in={ptok:10d} out={ctok:8d} "
                  f"hit={chi:10d} miss={cmiss:10d}  {os.path.basename(os.path.dirname(path))}")

    tot = [sum(x[i] for x in per_file) for i in (2, 3, 4, 5, 6)]
    print()
    print("=== TOTALS over scanned files ===")
    print(f"files with usage : {len(per_file)}")
    print(f"requests         : {tot[0]}")
    print(f"prompt tokens    : {tot[1]}")
    print(f"completion tokens: {tot[2]}")
    print(f"cache hit tokens : {tot[3]}")
    print(f"cache miss tokens: {tot[4]}")
    print()
    print("=== usage keys actually present ===")
    for k, n in key_counter.most_common():
        print(f"  {k:34s} {n}")
    print()
    print("=== distinct usage object shapes ===")
    for shape, n in usage_shapes.most_common(12):
        print(f"  {n:6d}  {list(shape)}")
    print()
    print("=== sample raw usage objects ===")
    for path, s in samples:
        print(f"  {os.path.basename(os.path.dirname(path))}: {json.dumps(s)}")


if __name__ == "__main__":
    main()
