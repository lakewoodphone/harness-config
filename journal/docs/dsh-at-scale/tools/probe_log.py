import zstandard as zstd, json, sys, os
p = sys.argv[1]
d = zstd.ZstdDecompressor()
t = d.stream_reader(open(p, 'rb')).read().decode('utf8', 'replace')
needles = ['"usage"', 'prompt_tokens', 'cached_tokens', 'cache_hit',
           'prompt_cache', 'completion_tokens', 'total_tokens',
           'input_tokens', 'output_tokens', 'reasoning_tokens',
           'assistant/message', 'maxTokens', 'decodeTokens']
print('log bytes:', len(t))
for n in needles:
    print(f'{n:22} -> {t.count(n)}')
print()
# find a step/end and assistant/message carrying anything token-ish
for ln in t.splitlines():
    if 'assistant/message' in ln and len(ln) > 400:
        o = json.loads(ln)
        keys = list(o.get('data', {}).keys())
        print('assistant/message data keys:', keys)
        sub = o['data'].get('message') or {}
        if isinstance(sub, dict):
            print('  message keys:', list(sub.keys()))
        print()
        break
