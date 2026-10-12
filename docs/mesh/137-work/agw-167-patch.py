#!/usr/bin/env python3
"""167 -- make `ai-gateway-health.py`'s closing line honest.

THE DEFECT THIS FIXES.  When the whole verdict is a CONDITION the report prints:

    "-> CONDITION, not fault (exit 3): every finding above is an external provider
     account/deployment condition (billing, or an id the provider no longer deploys).
     Nothing here is ours to fix; runs.tsv records rc=3 so this cannot be mistaken
     for a code fault."

On the cloud authority that sentence is FALSE, because `tier-collapse` -- model_tier1,
model_tier2 and model_tier3 all pointing at ONE literal -- is graded a CONDITION only
because the host sets AI_GATEWAY_HEALTH_TIER_COLLAPSE_IS_CONDITION=1 (see
`promote_tier_collapse`).  A tier collapse is OURS and the script's own detail text says
so ("three tiers on one literal is how the 2026-09-17 outage ran for a week with nothing
red").  A closing line that says "nothing here is ours to fix" while listing an
ours-to-fix finding is exactly the failure mode `sources/cron-failures.py` names:
"A permanently red job trains everyone to ignore this source."

WHAT THIS CHANGES.  Printed text only, plus one additive key on the verdict dict
(`tier_collapse_promoted`, which also appears in `--json`).  `verdict_of()` and therefore
the exit code are NOT touched: the rc is computed before the print, and the promotion of
tier-collapse into the problems list is unchanged.

Idempotent and re-runnable: applying it twice is a no-op.
"""
import hashlib
import sys

TARGET = sys.argv[1] if len(sys.argv) > 1 else "/usr/local/bin/ai-gateway-health.py"
ARROW = "\u2192"

# ---------------------------------------------------------------- edit 1: mark the verdict
OLD_MARK = ('        verdict["problems"].append(n)\n'
            '    return verdict\n'
            '\n'
            '\n'
            'def _read_key() -> str:')

NEW_MARK = ('        verdict["problems"].append(n)\n'
            '    # The closing line this module prints is derived from this verdict, and it must not\n'
            '    # claim that every finding is external when the promotion ABOVE is what produced the\n'
            '    # CONDITION. MEASURED 2026-10-11: tier-collapse -- three configured tiers on one\n'
            '    # literal -- is OURS, yet the line read "Nothing here is ours to fix".\n'
            '    verdict["tier_collapse_promoted"] = True\n'
            '    return verdict\n'
            '\n'
            '\n'
            'def _read_key() -> str:')

# ---------------------------------------------------------------- edit 2: the closing line
OLD_CLOSE = ('        elif rc == CONDITION_EXIT:\n'
             '            print("  ' + ARROW + ' CONDITION, not fault (exit %d): every finding above is an external provider "\n'
             '                  "account/deployment condition (billing, or an id the provider no longer deploys). "\n'
             '                  "Nothing here is ours to fix; runs.tsv records rc=%d so this cannot be mistaken for "\n'
             '                  "a code fault." % (CONDITION_EXIT, CONDITION_EXIT))\n')

NEW_CLOSE = ('        elif rc == CONDITION_EXIT:\n'
             '            if verdict.get("tier_collapse_promoted"):\n'
             '                _why = ("NOT every finding above is external, and this line must not be read as "\n'
             '                        "`nothing here is ours to fix`. The tier-collapse finding is OURS -- three "\n'
             '                        "configured tiers pointing at one literal -- and it is graded a CONDITION only "\n'
             '                        "because AI_GATEWAY_HEALTH_TIER_COLLAPSE_IS_CONDITION=1 is set on this host "\n'
             '                        "(see promote_tier_collapse). The provider account/deployment findings are "\n'
             '                        "external; that one is not. A CONDITION is not the same as nothing to do;")\n'
             '            else:\n'
             '                _why = ("every finding above is an external provider account/deployment condition "\n'
             '                        "(billing, or an id the provider no longer deploys). Nothing here is ours to "\n'
             '                        "fix;")\n'
             '            print("  ' + ARROW + ' CONDITION, not fault (exit %d): %s runs.tsv records rc=%d so this "\n'
             '                  "cannot be mistaken for a code fault." % (CONDITION_EXIT, _why, CONDITION_EXIT))\n')

# ---------------------------------------------------------------- edit 3: negative controls
OLD_END = ('    print()\n'
           '    print("SELF-TEST %s" % ("PASSED" if ok else "FAILED"))\n'
           '    return 0 if ok else 1\n')

NEW_END = ('    # -- The closing line must not over-claim --------------------------------------------\n'
           '    # MEASURED 2026-10-11. The line is printed FROM the verdict, so when the promotion\n'
           '    # happened the verdict has to CARRY that fact; otherwise the line says "every finding\n'
           '    # above is an external provider account/deployment condition ... Nothing here is ours\n'
           '    # to fix" while tier-collapse -- three tiers on one literal -- is ours. Both states\n'
           '    # are tested, because the OFF state is the office copy and must keep the old wording.\n'
           '    _flag = "AI_GATEWAY_HEALTH_TIER_COLLAPSE_IS_CONDITION"\n'
           '    _prev = os.environ.get(_flag)\n'
           '    try:\n'
           '        os.environ[_flag] = "1"\n'
           '        promoted = promote_tier_collapse({"problems": [], "notes": [\n'
           '            {"kind": "tier-collapse", "detail": "x", "model": "m"}]})\n'
           '        check("a promoted tier-collapse is MARKED as ours, not external",\n'
           '              promoted.get("tier_collapse_promoted"), True)\n'
           '        check("...and it still grades as a CONDITION",\n'
           '              verdict_of(promoted["problems"]), CONDITION_EXIT)\n'
           '        os.environ.pop(_flag, None)\n'
           '        unpromoted = promote_tier_collapse({"problems": [], "notes": [\n'
           '            {"kind": "tier-collapse", "detail": "x", "model": "m"}]})\n'
           '        check("with the host flag OFF nothing is claimed as ours-to-fix",\n'
           '              unpromoted.get("tier_collapse_promoted"), None)\n'
           '    finally:\n'
           '        if _prev is None:\n'
           '            os.environ.pop(_flag, None)\n'
           '        else:\n'
           '            os.environ[_flag] = _prev\n'
           '\n'
           '    print()\n'
           '    print("SELF-TEST %s" % ("PASSED" if ok else "FAILED"))\n'
           '    return 0 if ok else 1\n')


def main() -> int:
    with open(TARGET, encoding="utf-8") as fh:
        src = fh.read()

    before = hashlib.sha256(src.encode("utf-8")).hexdigest()

    if 'verdict["tier_collapse_promoted"] = True' in src:
        print("ALREADY PATCHED -- live sha256 %s" % before)
        return 0

    edits = [("verdict mark", OLD_MARK, NEW_MARK),
             ("closing line", OLD_CLOSE, NEW_CLOSE),
             ("self-test", OLD_END, NEW_END)]

    out = src
    for label, old, new in edits:
        n = out.count(old)
        if n != 1:
            print("ABORT: anchor %r matched %d times, expected exactly 1" % (label, n))
            return 2
        out = out.replace(old, new)

    # A guard that the two edits are coherent: the print reads a key the promotion writes.
    assert "tier_collapse_promoted" in out
    assert out.count("tier_collapse_promoted") == 4, out.count("tier_collapse_promoted")

    with open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(out)

    after = hashlib.sha256(out.encode("utf-8")).hexdigest()
    print("PATCHED %s" % TARGET)
    print("  before sha256 %s" % before)
    print("  after  sha256 %s" % after)
    return 0


if __name__ == "__main__":
    sys.exit(main())
