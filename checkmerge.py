import yaml, sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
cur = yaml.safe_load(Path(r"C:\Users\ezabz\.dsh\settings.yaml").read_text(encoding="utf-8"))
base = yaml.safe_load(Path("settings/base.yaml").read_text(encoding="utf-8"))
mach = yaml.safe_load(Path("settings/machines/ZABZ-YOGA.yaml").read_text(encoding="utf-8"))
def merge(a,b):
    o=dict(a)
    for k,v in (b or {}).items():
        o[k]=merge(o[k],v) if isinstance(v,dict) and isinstance(o.get(k),dict) else v
    return o
new = merge(base, mach)
print("=== CURRENT keys ==="); print(json.dumps(cur, indent=2, default=str))
print("\n=== NEW keys ==="); print(json.dumps(new, indent=2, default=str))
print("\n=== differences (value-level) ===")
def flat(d, p=""):
    out={}
    for k,v in (d or {}).items():
        key=f"{p}.{k}" if p else k
        if isinstance(v,dict): out.update(flat(v,key))
        else: out[key]=v
    return out
fc, fn = flat(cur), flat(new)
for k in sorted(set(fc)|set(fn)):
    if fc.get(k)!=fn.get(k):
        print(f"  {k}:  {fc.get(k)!r}  ->  {fn.get(k)!r}")
lost=[k for k in fc if k not in fn]
print("\nkeys lost:", lost or "none")
