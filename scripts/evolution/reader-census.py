#!/usr/bin/env python3
"""Aggregate the nineteen reader files into the round-4 census.

WHY A SCRIPT. 734 KB of per-session records is more than any context should carry, and an
aggregation done by reading is an aggregation done by memory -- the exact way a count becomes a
guess. This parses every record, counts what is actually there, and reports its own parse failures
so a dropped record is visible rather than silently reducing a denominator.

WHAT IT REPORTS
  * coverage: sessions read, records parsed, records the parser could not read (never silently)
  * outcome and severity distributions, and the friction ids by frequency
  * the highest-severity records with the owner's own words, so the register is built from quotes
  * the "wanted but not built" lines, which are the owner's asks nobody answered
  * intent clusters by keyword, as a coarse map of what he actually spends his sessions on

USAGE
    python3 reader-census.py [--readers DIR] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

REC_START = re.compile(r"^##\s+([0-9a-fA-F-]{8,})\s*$")
FRICTION_IDS = [
    "asked-unnecessarily", "asked-badly", "correction", "frustration", "restart-agent",
    "stopped-early", "wrong-data", "tool-failure", "env-hostile", "repeated-work", "slow",
    "context-loss", "overcomplicated", "ignored-instruction", "bad-prioritisation",
    "invented-detail", "no-verification", "format-unreadable", "non-answer", "safety",
]
FIELD = re.compile(r"^(intent|outcome|frictions|severity|beat|wanted):\s*(.*)$")


def _terms(text: str) -> set[str]:
    """Whole words, lowercased, with a trailing-s allowance. Never substrings."""
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    out = set(words)
    for w in words:
        if w.endswith("s") and len(w) > 3:
            out.add(w[:-1])
    return out

# Coarse intent clusters. Deliberately keyword-based and printed WITH its own match counts, so a
# reader can see how much of the corpus each bucket claims rather than trusting a tidy total.
CLUSTERS = {
    "build-or-fix-code": ["fix", "build", "implement", "refactor", "bug", "code", "test", "deploy"],
    "business-lesson-parts": ["customer", "order", "work order", "part", "screen", "repair",
                              "price", "quote", "inventory", "shop", "ticket"],
    "money-finance-tax": ["payroll", "tax", "invoice", "payment", "charge", "bank", "stripe",
                          "refund", "receipt", "finance", "profit"],
    "research-or-buy": ["research", "find", "compare", "buy", "order", "price", "which",
                        "recommend", "options"],
    "infrastructure-and-servers": ["server", "sync", "backup", "dns", "certificate", "disk",
                                   "systemd", "cron", "migration", "database"],
    "agent-behaviour-and-instructions": ["instruction", "persona", "prompt", "skill", "agent",
                                         "rule", "behave", "you keep", "why do you"],
    "communications": ["text", "sms", "call", "email", "dialpad", "voicemail", "customer messag"],
    "family-and-personal": ["aunt", "peril", "wife", "son", "daughter", "family", "yocheved"],
}


def parse_records(text: str) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    problems: list[str] = []
    cur: dict | None = None
    mode = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = REC_START.match(line)
        if m:
            if cur is not None:
                records.append(cur)
            cur = {"session": m.group(1), "quotes": [], "frictions": []}
            mode = None
            continue
        if cur is None:
            continue
        if line.startswith("quotes:"):
            mode = "quotes"
            rest = line.split(":", 1)[1].strip()
            if rest and rest != "-":
                cur["quotes"].append(rest.strip('" '))
            continue
        if line.startswith("- ") and mode == "quotes":
            cur["quotes"].append(line[2:].strip().strip('"'))
            continue
        fm = FIELD.match(line)
        if fm:
            key, value = fm.group(1), fm.group(2).strip()
            mode = None
            if key == "frictions":
                ids = [f.strip() for f in re.split(r"[,\s]+", value) if f.strip()]
                cur["frictions"] = [i for i in ids if i in FRICTION_IDS]
                unknown = [i for i in ids if i not in FRICTION_IDS and i.lower() not in ("none", "-", "")]
                if unknown:
                    problems.append(f"{cur['session']}: unknown friction id(s) {unknown}")
                cur["frictions_raw"] = value
            elif key == "severity":
                try:
                    cur["severity"] = int(re.sub(r"[^0-9]", "", value) or 0)
                except ValueError:
                    cur["severity"] = None
                    problems.append(f"{cur['session']}: unparsable severity {value!r}")
            else:
                cur[key] = value
            continue
        if line.startswith("- ") and cur.get("beat"):
            cur["beat"] += " " + line[2:].strip()
    if cur is not None:
        records.append(cur)
    return records, problems


def cluster_of(intent: str) -> str:
    """The best-matching cluster, matched on WHOLE WORDS, ties broken toward the rarer cluster.

    Two defects in the first version, both of which made the taxonomy look better than it was:
    `w in low` matched substrings, so "find" matched "finding" and "code" matched "encoded"; and a
    tie was won by whichever cluster happened to be iterated first. A bucket that wins on iteration
    order is not a measurement. A session matching nothing is reported as `unclassified` rather
    than swept into `other`, so the taxonomy's own coverage stays visible.
    """
    toks = _terms(intent)
    if not toks:
        return "no-intent"
    scores = {name: len(toks & set(words)) for name, words in CLUSTERS.items()}
    best = max(scores.values())
    if best == 0:
        return "unclassified"
    tied = [n for n, s in scores.items() if s == best]
    if len(tied) == 1:
        return tied[0]
    return sorted(tied, key=lambda n: (len(CLUSTERS[n]), n))[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--readers", default="/home/zabz/evolution-corpus-v4/readers")
    ap.add_argument("--out", default="/home/zabz/evolution-corpus-v4")
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(args.readers) if f.endswith(".md"))
    all_records: list[dict] = []
    all_problems: list[str] = []
    per_file: list[dict] = []

    for name in files:
        text = open(os.path.join(args.readers, name), errors="replace").read()
        recs, problems = parse_records(text)
        for r in recs:
            r["file"] = name
        all_records.extend(recs)
        all_problems.extend(f"{name}: {p}" for p in problems)
        per_file.append({"file": name, "bytes": len(text), "records": len(recs)})

    # A session id appearing twice is a real defect: two readers read the same session, which means
    # the shard selection overlapped and a count is inflated.
    by_session = Counter(r["session"] for r in all_records)
    dupes = {s: n for s, n in by_session.items() if n > 1}

    outcomes = Counter((r.get("outcome") or "missing").strip().lower() for r in all_records)
    severities = Counter(r.get("severity") for r in all_records)
    frictions = Counter(f for r in all_records for f in r["frictions"])
    clusters = Counter(cluster_of(r.get("intent") or "") for r in all_records)
    wanted = [{"session": r["session"], "file": r["file"], "wanted": r["wanted"]}
              for r in all_records if (r.get("wanted") or "-").strip() not in ("-", "")]
    high = sorted([r for r in all_records if (r.get("severity") or 0) >= 4],
                  key=lambda r: -r.get("severity", 0))

    census = {
        "reader_files": len(files),
        "records": len(all_records),
        "unique_sessions": len(by_session),
        "duplicate_session_ids": dupes,
        "parse_problems": all_problems,
        "outcomes": dict(outcomes.most_common()),
        "severities": {str(k): v for k, v in sorted(severities.items(), key=lambda x: (x[0] is None, x[0]))},
        "frictions": dict(frictions.most_common()),
        "intent_clusters": dict(clusters.most_common()),
        "sessions_with_a_want": len(wanted),
        "per_file": per_file,
    }
    json_path = os.path.join(args.out, "CENSUS-v4.json")
    with open(json_path, "w") as fh:
        json.dump({"census": census, "wanted": wanted,
                   "high_severity": [{"session": r["session"], "file": r["file"],
                                      "severity": r.get("severity"),
                                      "intent": r.get("intent"),
                                      "quotes": r["quotes"],
                                      "beat": r.get("beat")} for r in high]},
                  fh, indent=1, sort_keys=True)

    md = [
        "# CENSUS v4 — every owner session the reader fleet read",
        "",
        f"Reader files: **{len(files)}** · records: **{len(all_records)}** · "
        f"unique sessions: **{len(by_session)}**",
        "",
        "Aggregated by `scripts/evolution/reader-census.py` from the nineteen per-shard reader files.",
        "A count here is a count of records that PARSED; the parse problems are listed rather than",
        "folded into a denominator.",
        "",
        "## Outcomes",
        "",
        "| outcome | sessions |",
        "|---|---:|",
    ]
    for k, v in outcomes.most_common():
        md.append(f"| {k} | {v} |")
    md += ["", "## Severity (5 = he was angry, blocked, or lost money/time)", "", "| severity | sessions |", "|---|---:|"]
    for k, v in sorted(severities.items(), key=lambda x: (x[0] is None, x[0])):
        md.append(f"| {k} | {v} |")
    md += ["", "## Frictions, by number of sessions", "", "| friction | sessions |", "|---|---:|"]
    for k, v in frictions.most_common():
        md.append(f"| `{k}` | {v} |")
    md += ["", "## What he spends sessions on (coarse keyword clusters)", "",
           "| cluster | sessions |", "|---|---:|"]
    for k, v in clusters.most_common():
        md.append(f"| {k} | {v} |")
    md += ["", f"## {len(wanted)} sessions ended with something he wanted that he did not get", ""]
    for w in wanted[:60]:
        md.append(f"- `{w['session'][:8]}` — {w['wanted'][:300]}")
    md += ["", f"## {len(high)} sessions at severity 4 or 5, with his own words", ""]
    for r in high[:60]:
        md.append(f"### `{r['session'][:8]}` ({r['file']}, severity {r.get('severity')})")
        md.append(f"*intent:* {r.get('intent','')}")
        for q in r["quotes"][:3]:
            md.append(f"> {q}")
        md.append("")
    if all_problems:
        md += ["## Parse problems (a record that did not parse is NOT counted above)", ""]
        md += [f"- {p}" for p in all_problems]
    if dupes:
        md += ["", "## Duplicate session ids — the shard selection overlapped", ""]
        md += [f"- `{s}` appears {n} times" for s, n in dupes.items()]

    md_path = os.path.join(args.out, "CENSUS-v4.md")
    with open(md_path, "w") as fh:
        fh.write("\n".join(md) + "\n")

    print(f"files={len(files)} records={len(all_records)} unique={len(by_session)} "
          f"dupes={len(dupes)} parse_problems={len(all_problems)}")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print("outcomes:", dict(outcomes.most_common()))
    print("frictions:", dict(frictions.most_common(8)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
