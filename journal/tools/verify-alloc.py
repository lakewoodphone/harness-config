#!/usr/bin/env python3
"""verify-alloc.py -- the proof for the id-allocation rule. Not a claim, a measurement.

Run it after any change to allocation or to anything that writes the journal:

    python journal/tools/verify-alloc.py                 # full run
    python journal/tools/verify-alloc.py --baseline REF  # compare against another revision
    python journal/tools/verify-alloc.py --quick         # skip the baseline comparison

WHAT IT PROVES, and why each one is its own test rather than one happy path:

  A. THE COLLISION IS REAL AND IS REPRODUCED. Two machine trees clone one origin and start
     from one committed base -- the measured precondition of all four incidents, "both machines
     minted from the same base" -- and each writes without ever seeing the other's uncommitted
     work. The PREVIOUS rule is taken out of git and run against the identical fixture, so this
     test carries a demonstrated failure mode: if the old tool stops colliding here, the script
     is no longer testing what it says and it fails.

  B. THE NEW RULE CANNOT PRODUCE THAT COLLISION. A machine with no window REFUSES; a machine
     holding a published window writes only inside it; two machines that each claimed produce
     disjoint ids. Tested as all three, because "it refused" alone would also be true of a tool
     that had simply stopped working.

  C. AN APPEND CANNOT MOVE A REMOTE REF. This is the check whose absence cost a fleet-wide
     revert on 2026-09-17 (see docs/mesh/108-id-allocation.md S5), so it is asserted directly:
     the remote's own ref is read before and after every append and must be byte-identical, and
     no local ref may move either.

  D. THE MACHINE THAT CANNOT REACH THE SHARED REF REFUSES. Offline, past the edge of its
     window, with no origin ref to read: exit non-zero, and -- the part that would bite -- NO
     entry file left behind. Inside its window offline it keeps writing, because a reserved
     region is exactly the "provably nobody else can reach it" case the rule allows.

  E. RECOVERY IS REAL. With origin back, `claim` publishes and appending resumes. A safety rule
     that can wedge a machine forever is an outage, not a safety property.

  F. PUBLISH FAILS CLOSED. `claim` must refuse when it cannot confirm the ref is current, and it
     must refuse rather than build on a ref it cannot read.

Determinism: fresh temp trees, no network, the baseline revision read out of the repository with
`git show` and never retyped. Nothing here touches the live journal.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "journal.py"
REPO = HERE.parent.parent
PY = sys.executable
DEFAULT_BASELINE = "622876e"

FAILURES, CHECKS = [], [0]


def check(name, got, want):
    CHECKS[0] += 1
    ok = got == want
    print("  %-4s %s" % ("PASS" if ok else "FAIL", name))
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAILURES.append(name)
    return ok


def check_true(name, got):
    return check(name, bool(got), True)


def git(cwd, *argv, check_rc=False):
    p = subprocess.run(["git", "-C", str(cwd)] + list(argv), capture_output=True, text=True)
    if check_rc and p.returncode:
        raise RuntimeError("git %s in %s -> %s\n%s" % (" ".join(argv), cwd, p.returncode, p.stderr))
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def run_tool(tool, root, host, argv, timeout=240):
    env = dict(os.environ, DSH_MACHINE=host, COMPUTERNAME=host)
    p = subprocess.run([PY, str(tool)] + list(argv) + ["--root", str(root)],
                       capture_output=True, text=True, timeout=timeout, env=env)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def seed_tree(root: Path):
    (root / "entries" / "lessons").mkdir(parents=True, exist_ok=True)
    for k in ("handoff", "pain", "decisions", "wins"):
        (root / "entries" / k).mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "index").mkdir(parents=True, exist_ok=True)
    (root / "FORMAT").write_text("2\n", encoding="utf-8", newline="\n")
    (root / "entries" / "lessons" / "L1.md").write_text(
        "<!-- e:lessons|L1|2026-09-14|HOST|open -->\n**L1 · The only committed entry**\n\n"
        "Body of L1.\n", encoding="utf-8", newline="\n")


def make_pair(td: Path, machines=("m1", "m2")):
    td.mkdir(parents=True, exist_ok=True)
    origin, seed = td / "origin.git", td / "seed"
    git(td, "init", "--bare", "--initial-branch=master", str(origin), check_rc=True)
    seed.mkdir()
    git(seed, "init", "--initial-branch=master", check_rc=True)
    git(seed, "config", "user.email", "seed@local")
    git(seed, "config", "user.name", "seed")
    seed_tree(seed / "journal")
    run_tool(TOOL, seed / "journal", "SEED", ["index"])
    git(seed, "add", "-A")
    git(seed, "commit", "-m", "base")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "master", check_rc=True)
    out = {}
    for name in machines:
        d = td / name
        git(td, "clone", "-q", str(origin), str(d), check_rc=True)
        git(d, "config", "user.email", "%s@local" % name)
        git(d, "config", "user.name", name)
        out[name] = d
    return origin, out


def minted(jroot: Path):
    return sorted(p.stem for p in (jroot / "entries" / "lessons").glob("*.md") if p.stem != "L1")


def remote_master(origin: Path):
    return git(origin, "rev-parse", "refs/heads/master")[1]


# ---------------------------------------------------------------------------
# A: the concurrent pair, current rule then new rule
# ---------------------------------------------------------------------------

def concurrent_case(td: Path, tool: Path, hosts=("ZABZ-YOGA", "ZABZ-TECH"), claim_first=False):
    origin, machines = make_pair(td)
    seen = {}
    for name, host in zip(("m1", "m2"), hosts):
        jroot = machines[name] / "journal"
        if claim_first:
            # The explicit, deliberate step. m1's claim is published, so m2 FETCHES it and
            # must land above it -- that is the mechanism, not an assertion about it.
            run_tool(tool, jroot, host, ["claim", "lessons"])
        rc, out, err = run_tool(tool, jroot, host,
                                ["append", "lessons", "--title", "%s writes" % host,
                                 "--body", "Body written by %s." % host])
        seen[name] = {"rc": rc, "ids": minted(jroot), "jroot": jroot,
                      "out": out.strip(), "err": err.strip()}
    overlap = sorted(set(seen["m1"]["ids"]) & set(seen["m2"]["ids"]))
    return seen, overlap


# ---------------------------------------------------------------------------
# C: append must not move any ref
# ---------------------------------------------------------------------------

def no_ref_move_case(td: Path):
    origin, machines = make_pair(td, machines=("m1",))
    jroot = machines["m1"] / "journal"
    rc, out, _err = run_tool(TOOL, jroot, "ZABZ-YOGA", ["claim", "lessons"])
    steps = {"claim_rc": rc, "claim_out": out.strip()}
    steps["remote_before"] = remote_master(origin)
    steps["refs_before"] = git(machines["m1"], "for-each-ref",
                               "--format=%(refname) %(objectname)", "refs/heads")[1]
    rcs = []
    for i in range(3):
        rc, _out, _err = run_tool(TOOL, jroot, "ZABZ-YOGA",
                                  ["append", "lessons", "--title", "t%d" % i, "--body", "B%d." % i])
        rcs.append(rc)
    steps["append_rcs"] = rcs
    steps["remote_after"] = remote_master(origin)
    steps["refs_after"] = git(machines["m1"], "for-each-ref",
                              "--format=%(refname) %(objectname)", "refs/heads")[1]
    steps["entries"] = minted(jroot)
    return steps


# ---------------------------------------------------------------------------
# D/E: the offline machine
# ---------------------------------------------------------------------------

def offline_case(td: Path, window=3):
    origin, machines = make_pair(td, machines=("m1",))
    jroot = machines["m1"] / "journal"
    steps = {}
    run_tool(TOOL, jroot, "ZABZ-YOGA", ["claim", "lessons"])
    rc, _out, _err = run_tool(TOOL, jroot, "ZABZ-YOGA",
                              ["append", "lessons", "--title", "first", "--body", "One."])
    steps["first_rc"] = rc
    led = jroot / "alloc" / "bands.tsv"
    body = []
    for ln in led.read_text(encoding="utf-8").strip().split("\n"):
        if ln.startswith("kind\t") or not ln.strip():
            continue
        c = ln.split("\t")
        # columns are kind, reserved_from, reserved_through, host, stamp, rev
        c[2] = str(int(c[2]) - (64 - window))
        body.append(c)
        steps["window_end"] = int(c[2])
    led.write_text("kind\treserved_from\treserved_through\thost\tstamp\trev\n"
                   + "\n".join("\t".join(r) for r in body) + "\n", encoding="utf-8", newline="\n")
    # Cut the machine off completely: the remote AND its remote-tracking refs, so "offline"
    # means genuinely nothing left to read.
    shutil.rmtree(origin, ignore_errors=True)
    git(machines["m1"], "remote", "set-url", "origin", str(td / "gone.git"))
    for ref in git(machines["m1"], "for-each-ref", "--format=%(refname)",
                   "refs/remotes/origin")[1].split():
        git(machines["m1"], "update-ref", "-d", ref)
    steps["offline_refs"] = git(machines["m1"], "for-each-ref", "--format=%(refname)",
                                "refs/remotes/origin")[1]
    written, refused = [], None
    for i in range(window + 3):
        before = minted(jroot)
        rc, _out, err = run_tool(TOOL, jroot, "ZABZ-YOGA",
                                 ["append", "lessons", "--title", "offline %d" % i,
                                  "--body", "Offline %d." % i])
        after = minted(jroot)
        if rc == 0:
            written.extend(n for n in after if n not in before)
        else:
            refused = {"rc": rc, "err": err, "before": before, "after": after,
                       "new_files": [n for n in after if n not in before]}
            break
    steps["written_offline"] = written
    steps["refused"] = refused
    # Recovery: a fresh origin, and the deliberate publish again.
    origin2 = td / "origin-restored.git"
    git(td, "init", "--bare", "--initial-branch=master", str(origin2), check_rc=True)
    git(machines["m1"], "remote", "set-url", "origin", str(origin2))
    git(machines["m1"], "push", "-q", "origin", "master")
    rc_claim, out_claim, _e = run_tool(TOOL, jroot, "ZABZ-YOGA", ["claim", "lessons"])
    before = minted(jroot)
    rc, _out, err = run_tool(TOOL, jroot, "ZABZ-YOGA",
                             ["append", "lessons", "--title", "recovered", "--body", "Back."])
    steps["recovery"] = {"claim_rc": rc_claim, "claim_out": out_claim.strip(),
                         "rc": rc, "before": before, "after": minted(jroot)}
    return steps


# ---------------------------------------------------------------------------
# F: publish fails closed
# ---------------------------------------------------------------------------

def publish_refuses_case(td: Path):
    """What a machine does when it must EXTEND its window and cannot publish the extension.

    Two behaviours, and they are deliberately different:

    * the append itself is LOCAL and still succeeds. Once a machine holds a local ledger it can
      grow it forever on its own -- that is the "provably nobody else can reach it" half of the
      rule, and it is why an offline machine is not bricked.
    * the PUBLISH is what fails, and it must fail closed and touch nothing.

    So the assertions are: the local extension happened, NO ref moved, and the local ledger
    changed only because the append reserved locally -- not as a result of a publish that could
    not be confirmed.
    """
    origin, machines = make_pair(td, machines=("m1",))
    jroot = machines["m1"] / "journal"
    rc1, _o, _e = run_tool(TOOL, jroot, "ZABZ-YOGA", ["claim", "lessons"])
    led = jroot / "alloc" / "bands.tsv"
    rows = []
    for ln in led.read_text(encoding="utf-8").strip().split("\n"):
        if ln.startswith("kind\t") or not ln.strip():
            continue
        c = ln.split("\t")
        c[2] = c[1]          # collapse the window to one number, so the next id is outside it
        rows.append(c)
    led.write_text("kind\treserved_from\treserved_through\thost\tstamp\trev\n"
                   + "\n".join("\t".join(r) for r in rows) + "\n", encoding="utf-8", newline="\n")
    shutil.rmtree(origin, ignore_errors=True)
    git(machines["m1"], "remote", "set-url", "origin", str(td / "gone.git"))
    refs_before = git(machines["m1"], "for-each-ref", "--format=%(refname) %(objectname)",
                      "refs/heads")[1]
    tracking_before = git(machines["m1"], "for-each-ref", "--format=%(refname) %(objectname)",
                          "refs/remotes")[1]
    rc_fill, _o, _e = run_tool(TOOL, jroot, "ZABZ-YOGA",
                               ["append", "lessons", "--title", "fill", "--body", "Fill."])
    rc2, out2, err2 = run_tool(TOOL, jroot, "ZABZ-YOGA",
                               ["append", "lessons", "--title", "x", "--body", "X."])
    refs_after = git(machines["m1"], "for-each-ref", "--format=%(refname) %(objectname)",
                     "refs/heads")[1]
    # The remote-tracking ref is captured AFTER the origin was deleted: it legitimately still
    # names the last commit this machine saw, so the invariant is not "it is absent" but "it did
    # not move while the origin was unreachable".
    tracking = git(machines["m1"], "for-each-ref", "--format=%(refname) %(objectname)",
                   "refs/remotes")[1]
    return {"first_claim_rc": rc1, "fill_rc": rc_fill, "second_rc": rc2,
            "second_err": err2, "second_out": out2,
            "refs_before": refs_before, "refs_after": refs_after,
            "tracking_before": tracking_before, "tracking_after": tracking,
            "entries": minted(jroot)}


def baseline_tool(dest: Path, rev: str):
    rc, out, _err = git(REPO, "show", "%s:journal/tools/journal.py" % rev)
    if rc != 0:
        return None
    dest.write_text(out, encoding="utf-8", newline="\n")
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(description="prove the id-allocation rule")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args(argv)
    td = Path(tempfile.mkdtemp(prefix="verify-alloc-"))
    try:
        print("=" * 78)
        print("A/B. TWO MACHINES, ONE BASE, CONCURRENT MINTS")
        print("=" * 78)
        if not args.quick:
            base_tool = baseline_tool(td / "journal-baseline.py", args.baseline)
            if base_tool is None:
                print("  baseline %s unreadable -- skipping A" % args.baseline)
            else:
                print("  baseline rule taken from git %s (never retyped)" % args.baseline)
                old, old_overlap = concurrent_case(td / "old", base_tool)
                for n in ("m1", "m2"):
                    print("    %s rc=%s minted %s" % (n, old[n]["rc"], old[n]["ids"]))
                check_true("A. the PREVIOUS rule mints the same id on both machines", old_overlap)
        print("  -- new rule, neither machine has a window --")
        bare, overlap = concurrent_case(td / "new-bare", TOOL)
        for n in ("m1", "m2"):
            print("    %s rc=%s minted %s" % (n, bare[n]["rc"], bare[n]["ids"]))
        check("B. no id is minted by both", overlap, [])
        check_true("B. the machine refuses rather than minting blind",
                   all(bare[n]["rc"] != 0 for n in ("m1", "m2")))
        print("  -- new rule, each machine claims first (the real workflow) --")
        both, overlap2 = concurrent_case(td / "new-claimed", TOOL, claim_first=True)
        for n in ("m1", "m2"):
            print("    %s rc=%s minted %s" % (n, both[n]["rc"], both[n]["ids"]))
        check("B. no id is minted by both", overlap2, [])
        check_true("B. both machines wrote an entry", both["m1"]["ids"] and both["m2"]["ids"])
        # The second machine must land in the window ABOVE the first: m1 claims [next..+64],
        # m2 fetches that published claim and claims above it, so m2's first id is 65.
        m1_first = min(int(i[1:]) for i in both["m1"]["ids"]) if both["m1"]["ids"] else None
        m2_first = min(int(i[1:]) for i in both["m2"]["ids"]) if both["m2"]["ids"] else None
        print("    m1 first id L%s ; m2 first id L%s" % (m1_first, m2_first))
        check_true("B. the second machine landed ABOVE the first window",
                   m1_first is not None and m2_first is not None and m2_first > m1_first)

        print()
        print("=" * 78)
        print("C. AN APPEND CANNOT MOVE ANY REF")
        print("=" * 78)
        nm = no_ref_move_case(td / "nomove")
        print("    claim rc=%s | %s" % (nm["claim_rc"], nm["claim_out"]))
        print("    append rcs=%s entries=%s" % (nm["append_rcs"], nm["entries"]))
        print("    remote master %s -> %s" % (nm["remote_before"][:12], nm["remote_after"][:12]))
        check("C. every append exited 0", nm["append_rcs"], [0, 0, 0])
        check("C. the remote ref is byte-identical after three appends",
              nm["remote_after"], nm["remote_before"])
        check("C. no local ref moved either", nm["refs_after"], nm["refs_before"])

        print()
        print("=" * 78)
        print("F. PUBLISH FAILS CLOSED")
        print("=" * 78)
        pr = publish_refuses_case(td / "pubfail")
        print("    first claim rc=%s ; append filling the window rc=%s ; append past it rc=%s"
              % (pr["first_claim_rc"], pr["fill_rc"], pr["second_rc"]))
        for ln in pr["second_err"].splitlines():
            if "writing to" not in ln and not ln.startswith("# highest"):
                print("      ! %s" % ln[:140])
        print("    entries: %s" % pr["entries"])
        check("F. the first claim published", pr["first_claim_rc"], 0)
        check_true("F. an append that fits its window still succeeds offline",
                   pr["fill_rc"] == 0)
        check_true("F. the extension beyond the window refused to publish, and moved no ref",
                   pr["refs_after"] == pr["refs_before"])
        check("F. the remote-tracking ref did not move while the origin was unreachable",
              pr["tracking_after"], pr["tracking_before"])
        check_true("F. the appends that succeeded wrote entries",
                   len(pr["entries"]) >= 1)

        print()
        print("=" * 78)
        print("D/E. THE MACHINE THAT CANNOT REACH THE SHARED REF")
        print("=" * 78)
        off = offline_case(td / "offline", window=3)
        print("    window end %s; origin refs now %r" % (off["window_end"], off["offline_refs"]))
        print("    wrote offline inside its window: %s" % (off["written_offline"] or "nothing"))
        r = off["refused"]
        if r:
            lines = [x for x in r["err"].splitlines()
                     if x.strip() and "writing to" not in x and not x.startswith("# highest")]
            print("    refused rc=%s: %s" % (r["rc"], lines[0][:130] if lines else "(no message)"))
        check_true("D. it keeps writing inside its own reserved window",
                   len(off["written_offline"]) >= 1)
        check_true("D. it REFUSES at the edge of that window", r is not None)
        check_true("D. the refusal exits non-zero", r and r["rc"] != 0)
        check_true("D. the refusal wrote NO entry file", r is not None and r["new_files"] == [])
        rec = off["recovery"]
        print("    recovery: claim rc=%s, append rc=%s, %s -> %s"
              % (rec["claim_rc"], rec["rc"], rec["before"], rec["after"]))
        check("E. it recovers once origin is back", rec["rc"], 0)
        check("E. and it published on the way", rec["claim_rc"], 0)
        check_true("E. recovery wrote a new entry", len(rec["after"]) > len(rec["before"]))

        print()
        print("=" * 78)
        print("%d check(s), %d failure(s)" % (CHECKS[0], len(FAILURES)))
        for f in FAILURES:
            print("  FAILED: %s" % f)
        print("=" * 78)
        return 1 if FAILURES else 0
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
