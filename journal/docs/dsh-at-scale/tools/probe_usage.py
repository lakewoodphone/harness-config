import zstandard as zstd, json, sys, collections
p = sys.argv[1]
d = zstd.ZstdDecompressor()
t = d.stream_reader(open(p, 'rb')).read().decode('utf8', 'replace')
shapes = collections.Counter()
samples = []
for ln in t.splitlines():
    if '"usage"' not in ln:
        continue
    try:
        o = json.loads(ln)
    except Exception:
        continue
    u = o.get('data', {}).get('usage')
    if not isinstance(u, dict):
        continue
    shapes[(o.get('type'), tuple(sorted(u.keys())))] += 1
    if len(samples) < 4:
        samples.append((o.get('type'), u))
for k, v in shapes.most_common(20):
    print(f'{v:6d}  {k[0]}  {list(k[1])}')
print()
for ty, u in samples:
    print(ty, json.dumps(u)[:600])
    print()
