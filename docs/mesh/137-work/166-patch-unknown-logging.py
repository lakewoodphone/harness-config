#!/usr/bin/env python3
"""166: stop app/code_self_edit.py writing the constant model="unknown" on its failure path.

WHY: `_invoke_llm`'s exception handler recorded `model="unknown"` (l.908) although the provider leg
knows the model it tried. That literal produced 123 unattributable `model_usage` rows (all
agent_id=self_improvement), named no lane, and held ai-gateway-health at rc=1 for 25 consecutive runs
on 2026-10-11. Fixing the ROUTING (2026-10-07) stopped new ones; this fixes the LOGGER, so a future
failure is attributable instead of anonymous.

READ-ONLY w.r.t. the database: this touches one .py file only.
Idempotent. Backs up first. py_compile. Extracts and unit-tests the helper in isolation.
"""
import hashlib
import py_compile
import shutil
import sys
import types

P = "/opt/company/app/code_self_edit.py"
BACKUP = "/root/out/migration-review/166-code_self_edit.py.before-unknown-model-logging-fix"

HELPER = '''#: The model each provider leg would have attempted for this tier. Mirrors the literals chosen in
#: `_call_deepinfra` (incl. its Fireworks switch), `_call_deepseek`, `_call_openai` and
#: `_call_anthropic`. It exists so the FAILURE path can name the model it tried: until 2026-10-11 that
#: path wrote the constant string "unknown", which is why `model_usage` held 123 unattributable rows
#: (all `agent_id=self_improvement`) that named no lane at all and held ai-gateway-health at rc=1 for
#: 25 consecutive runs. Keep in step with those call sites; artifact 166 carries the equality test.
def _attempted_model(settings, provider, llm_tier=None):
    tier = "ceo" if str(llm_tier or "").strip().lower() == "ceo" else "fast"
    if provider == "deepseek":
        return "deepseek-v4-pro" if tier == "ceo" else "deepseek-v4-flash"
    if provider == "openai":
        return "gpt-5.4" if tier == "ceo" else "gpt-5.4-mini"
    if provider == "anthropic":
        return "claude-opus-4-6" if tier == "ceo" else "claude-sonnet-4-5"
    if provider == "deepinfra":
        fireworks = bool(
            not getattr(settings, "deepinfra_api_key", None)
            and getattr(settings, "fireworks_api_key", None)
        )
        if fireworks:
            return ("accounts/fireworks/models/deepseek-v4-pro-0813" if tier == "ceo"
                    else "accounts/fireworks/models/deepseek-v4-flash-0731")
        return ("deepseek-ai/DeepSeek-V4-Pro-0813" if tier == "ceo"
                else "deepseek-ai/DeepSeek-V4-Flash-0731")
    # An unknown provider is named as such rather than collapsed to a constant: a label that says
    # which leg failed is still an attribution.
    return "%s:%s" % (provider, tier)


'''

OLD = '                    model="unknown",\n'
NEW = '                    model=_attempted_model(settings, prov_name, llm_tier),\n'

src = open(P, encoding="utf-8").read()
before = hashlib.sha256(src.encode()).hexdigest()

if "_attempted_model(" in src:
    print("ALREADY PATCHED; nothing to do. sha256=%s" % before)
    sys.exit(0)

anchor = "def _call_deepinfra("
assert src.count(anchor) == 1, "anchor _call_deepinfra not found exactly once: %d" % src.count(anchor)
assert src.count(OLD) == 1, "expected exactly one model=\"unknown\" literal, found %d" % src.count(OLD)

shutil.copy2(P, BACKUP)
print("backed up -> %s" % BACKUP)

src = src.replace(anchor, HELPER + anchor, 1)
src = src.replace(OLD, NEW, 1)
open(P, "w", encoding="utf-8").write(src)
after = hashlib.sha256(src.encode()).hexdigest()
print("before sha256 = %s" % before)
print("after  sha256 = %s" % after)

py_compile.compile(P, doraise=True)
print("py_compile: OK")

# --- isolate and unit-test the helper (no app imports, no side effects) -------------------------
start = src.index("def _attempted_model(")
body = src[start:src.index("\n\n\ndef ", start)]
ns = {}
exec(compile(body, "<helper>", "exec"), ns)
fn = ns["_attempted_model"]


class S:
    def __init__(self, d=None, f=None):
        self.deepinfra_api_key = d
        self.fireworks_api_key = f


cases = [
    ((S("k", None), "deepseek", None), "deepseek-v4-flash"),
    ((S("k", None), "deepseek", "ceo"), "deepseek-v4-pro"),
    ((S("k", None), "deepseek", "FAST"), "deepseek-v4-flash"),
    ((S("k", None), "openai", None), "gpt-5.4-mini"),
    ((S("k", None), "openai", "ceo"), "gpt-5.4"),
    ((S("k", None), "anthropic", None), "claude-sonnet-4-5"),
    ((S("k", None), "anthropic", "ceo"), "claude-opus-4-6"),
    ((S("k", None), "deepinfra", None), "deepseek-ai/DeepSeek-V4-Flash-0731"),
    ((S("k", None), "deepinfra", "ceo"), "deepseek-ai/DeepSeek-V4-Pro-0813"),
    ((S(None, "f"), "deepinfra", None), "accounts/fireworks/models/deepseek-v4-flash-0731"),
    ((S(None, "f"), "deepinfra", "ceo"), "accounts/fireworks/models/deepseek-v4-pro-0813"),
    ((S("k", None), "copilot", None), "copilot:fast"),
]
bad = 0
for (args, want) in cases:
    got = fn(*args)
    if got != want:
        bad += 1
        print("FAIL  %s -> %r want %r" % (args[1:], got, want))
    # every literal the helper can return must actually appear in the file's call sites
    if want.startswith(("deepseek-", "gpt-", "claude-", "accounts/", "deepseek-ai/")):
        if want not in src:
            bad += 1
            print("FAIL  literal %r is not present anywhere in the patched file" % want)
print("helper cases: %d/%d ok" % (len(cases) - bad, len(cases)))
print("RESULT: %s" % ("PASS" if bad == 0 else "FAIL"))
sys.exit(1 if bad else 0)
