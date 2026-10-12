import hashlib, pathlib, sys, datetime

P = pathlib.Path("/usr/local/bin/ai-gateway-health.py")
src = P.read_text(encoding="utf-8")
h_before = hashlib.sha256(src.encode()).hexdigest()
print("sha256 before:", h_before)

def sub(old, new, label):
    global src
    n = src.count(old)
    if n != 1:
        print("ANCHOR FAILED (%s): count=%d" % (label, n)); sys.exit(1)
    src = src.replace(old, new)
    print("anchor ok:", label)

# 1. restore the pristine condition list -- `invalid model id` is NOT a provider condition.
sub('               r"not deployed|no such model|invalid model id", re.I),',
    '               r"not deployed|no such model", re.I),',
    "remove false condition pattern")

# 2. the sentinel constant, next to CONDITION_EXIT.
const = "\n".join([
 'CONDITION_EXIT = 3',
 '',
 '#: The literal a CALLER writes into `model_usage.model` when its own failure path cannot name the',
 '#: model it tried (`app/code_self_edit.py`: `_record_llm_usage(..., model="unknown", success=False)`).',
 '#: It is the ABSENCE of an attribution, not a model id, so grading it as a failing lane asserts more',
 '#: than the row can support. MEASURED 2026-10-11: the whole bucket was `agent_id=self_improvement`',
 '#: rows naming OUR ids offered to the wrong provider (openai `400 invalid model ID` for',
 '#: `deepseek/deepseek-v4-flash`, anthropic `404 model: deepseek-v4-flash`); the caller defect behind',
 '#: them was repaired 2026-10-07T20:06Z and no such row has been written since 2026-10-07T16:52Z.',
 '#: A bucket with NO traffic in the recent window is an ATTRIBUTION note; one WITH recent failures',
 '#: keeps the normal grading, so a recurrence is still a FAULT within a single run. See 161-.',
 'UNATTRIBUTED_MODEL = "unknown"',
])
sub('CONDITION_EXIT = 3\n', const + "\n", "sentinel constant")

# 3. grade the sentinel honestly, before the recent/historical split.
block = "\n".join([
 '        # AN UNATTRIBUTABLE BUCKET IS NOT A LANE. `unknown` is not a model id: it is the literal',
 '        # the CALLER writes when its failure path cannot name the model it tried, so the bucket is',
 '        # the absence of an attribution and a finding about it is a finding about the LOGGER. It is',
 '        # reported as a note (history stays visible) and only while there is no live traffic; the',
 '        # recent-traffic path below is untouched, so a recurrence is still a FAULT.',
 '        if m["model"] == UNATTRIBUTED_MODEL and m.get("recent_calls", 0) == 0:',
 '            if m["failed"]:',
 '                notes.append({',
 '                    "kind": "unattributed-calls",',
 '                    "model": m["model"],',
 '                    "detail": "%d of %d calls over %dd were recorded as `%s` by the caller, so they "',
 '                              "name no lane at all; last seen %s. %d of the failures match OUR error "',
 '                              "text rather than a provider condition. This is NOT a failing model: it "',
 '                              "is the caller logging a failure without the model it tried "',
 '                              "(app/code_self_edit.py records model=unknown on its failure path)."',
 '                              % (m["failed"], m["calls"], data["days"], UNATTRIBUTED_MODEL,',
 '                                 m["last_seen"], m.get("window_fault", 0))})',
 '            continue',
 '        recent_calls = m.get("recent_calls", 0)',
 '        recent_failed = m.get("recent_failed", 0)',
])
sub('        recent_calls = m.get("recent_calls", 0)\n        recent_failed = m.get("recent_failed", 0)\n',
    block + "\n", "sentinel grading")

# 4. negative controls for both halves of the new rule.
tests = "\n".join([
 '    # MUST NOT FIRE: an unattributable bucket is the ABSENCE of a model, not a failing one.',
 '    # MEASURED 2026-10-11: `model=unknown` held this job at rc=1 for a whole day, and every row in',
 '    # it was the caller own failure-path literal naming ids of ours offered to the wrong provider.',
 '    v = evaluate({"models": [_m("unknown", 24, 24)], "min_calls": 20, "days": 7,',
 '                  "recent_hours": 6}, {}, 0.20)',
 '    check("an unattributable `unknown` bucket does NOT fire as a lane", v["problems"], [])',
 '    check("...and is reported as an unattributed-calls note",',
 '          [n["kind"] for n in v["notes"]], ["unattributed-calls"])',
 '',
 '    # MUST STILL FIRE: the same bucket with LIVE failures is a fault, not a note.',
 '    check("a LIVE unattributable bucket still fires",',
 '          kinds({"models": [_m("unknown", 24, 24, recent_calls=3, recent_failed=3)],',
 '                 "min_calls": 20, "days": 7, "recent_hours": 6}),',
 '          ["failing-now"])',
 '',
 '    # The restored rule, as a negative control on the pattern list itself: a 400 that names OUR',
 '    # malformed id must NOT be waved through as an external condition.',
 '    check("`invalid model ID` is NOT a condition (it was measured to be OUR id)",',
 '          _is_condition_error("openai attempt 1/3: Error code: 400 - invalid model ID"), False)',
 '',
 '    # MUST FIRE: configured tier with no traffic at all',
])
sub('    # MUST FIRE: configured tier with no traffic at all', tests, "self-tests")

P.write_text(src, encoding="utf-8")
h_after = hashlib.sha256(src.encode()).hexdigest()
print("sha256 after: ", h_after)
print("bytes:", len(src.encode()))
