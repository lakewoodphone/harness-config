#!/usr/bin/env python3
"""FLAG SOURCE: a project checkout that can no longer be worked in, or has stopped advancing.

THE FAILURE THIS EXISTS FOR (measured on secratary, 2026-09-28)
--------------------------------------------------------------
The project loop revives a shift a day for `lpt-website` and `kosher-ai-filter`.
Both of their checkouts were found crippled the same way:

    project           repo                                  was at        behind  stale lock
    lpt-website       /home/zabz/repos/phone-and-tech-full   057cea451     426     .git/index.lock, 0 B, 2026-09-16 00:30
    kosher-ai-filter  /home/zabz/repos/kosher-filter-ai      d225385       222     .git/index.lock, 0 B, 2026-09-20 15:30

Both locks had no git process behind them: the debris of a crashed git
operation. The consequences compound, and that is the point:

  1. every git WRITE in the checkout fails, so a shift's work can be neither
     committed nor pushed. On the kosher checkout a shift's edit sat uncommitted
     for six days and was only saved by being superseded upstream -- luck, not
     safety;
  2. the checkout never advances, so the daily release spends itself working
     against an August tree while origin has moved 426 commits ahead;
  3. NOTHING ALARMS. `project-keepalive` reports `suppressed project-daily-cap
     1/1` and looks perfectly healthy while the repo underneath is unusable.
     A live-looking thing read as work-happening -- the pattern this system pays
     for repeatedly.

There is no second source on this question: `scripts/mesh/git-health-check.sh`
(cron */30) watches ONLY /home/zabz/personal-secretary-mvp, writes a log and
POSTs to the app's alert endpoint; it never raises a wake flag and never looks at
a project checkout. `journal-commit.sh` does look for `index.lock`, but it treats
ANY lock as a live git operation and skips -- correct for a committer, useless as
a sensor. This source is the sensor, and the difference between it and those two
is the liveness test below.

THE THREE SIGNALS, AND THE THRESHOLD FOR EACH
---------------------------------------------
A. STALE LOCK -- `.git/index.lock` exists AND no live git process owns it.
   Liveness is decided by scanning /proc, never by `pgrep -f`:
     * exact:  a process whose comm is `git`/`git-*` with the lock open
               (/proc/<pid>/fd -> <gitdir>/index.lock), which is what holding
               the lock actually means;
     * broad:  a git process whose cwd is inside the repo;
     * last:   if /proc could not be scanned at all, the lock's age decides
               (nothing younger than LOCK_GRACE_SEC is ever called stale).
   Measured on secratary 2026-09-28T17:15Z: `pgrep -f 'git '` matched 3
   processes and NONE of them was a git process (a dsh node session with the
   word "git" in its task text, a `bash -c` script body, and a `grep` whose
   pattern contained it). A liveness test built on `pgrep -f` reports "a git
   process holds this lock" whenever an unrelated session merely mentions git --
   the one reading that would have kept these two checkouts crippled. So /proc,
   by comm and by open descriptor.
   LOCK_GRACE_SEC=300: an index write is sub-second (measured `git fetch` 0.54 s
   and 0.95 s on these two repos), and 300 s is three orders of magnitude above
   it, so a lock still present after five minutes with no owner is debris.
   A LINKED WORKTREE has its OWN index.lock at
   <gitdir>/worktrees/<name>/index.lock, and every one of them is judged by the
   same grace and the same /proc test, with the broad cwd test run against that
   worktree's path. Measured 2026-09-28T22:05Z on secratary: a 0 B lock there
   (mtime 18:22:03Z, age 3.7 h, no git process holding it) had stranded
   /home/zabz/_verify_co_20260928 while the source read only <gitdir>/index.lock,
   found nothing and printed lock=none -- a green reading on a tree that could
   not be written. One worktree of the production checkout is enough.

B. STALENESS -- `git fetch` (bounded), then the commit count between HEAD and
   the upstream (`@{u}`, else `origin/HEAD`, else `origin/<branch>`, else
   `origin/main`, else `origin/test`). Flag at BEHIND_MIN=50.
   Measured healthy the same day: 0 (kosher) and 2 (lpt-website, fast-forwarded
   at 06:00Z). Measured abnormal: 222 and 426 -- 4.4x and 8.5x the threshold.
   origin/test gained 340 commits in the 14 days to 2026-09-28 (about 24/day), so
   50 is roughly two days of unmerged drift: the point at which a shift is
   plainly working on a tree nobody else has, and still well clear of the few
   commits that arrive between two shifts.
   FETCH_TIMEOUT=30 s, and the reason is the caller: run-wake-sources.sh wraps
   every source in `timeout 90`, so one hung fetch must not eat the budget of
   every project after it. Measured healthy fetch here is under 1 s, so 30 s is
   ~30x headroom against a network that is merely slow.

C. DIRTY TOO LONG -- uncommitted work whose OLDEST modified file is older than
   DIRTY_HOURS=24 (the shift's work that never landed). The AGE, not the dirty
   bit, is the signal: a tree dirty from a run happening right now is normal and
   must never be reported. Count and oldest-file age are both reported. Paths
   matching the project's optional `dirty_ignore` globs (or
   CHECKOUT_HEALTH_DIRTY_IGNORE) are excluded, so a generated artefact that is
   meant to stay uncommitted can be declared rather than alarming daily.
   Measured 2026-09-28T17:14Z: lpt-website dirty=1 (reconciliation_plan.json,
   mtime 2026-09-20 23:15, 186 h old), kosher clean.

NOT a signal, deliberately: a checkout that is AHEAD of its upstream. A shift
legitimately commits locally before it pushes, so "ahead" is normal for minutes
at a time and would fire on a healthy loop. It is printed on the stderr line so
drift stays visible, but it never raises a flag.

AND NOT A FLAG either: an unmeasurable signal. A fetch that fails or times out,
or an upstream that cannot be resolved, means staleness was NOT measured. That is
printed, counted, and makes the process exit 1 -- it is never turned into a wake
flag, because spending one of the day's four releases on a network blip is how an
alarm becomes noise. A commit count taken against a remote-tracking ref that the
failed fetch left stale is reported with `(stale ref)` and is likewise never a
reason to wake: a flag may only claim a measurement that was actually taken.

SUBJECT  checkout-health:<project>:<YYYYMMDD>   (UTC day)
    The subject IS the dedup key, so a broken checkout costs at most ONE session
    per day. The source is structurally capped at one row per project per day and
    keeps no counter of its own: the wake store is the only state.

OUTPUT DISCIPLINE
    stdout is frozen to the two words `_flag.run` owns (`quiet` / `flagged
    <subject>`). Exactly one line per project goes to stderr naming its verdict,
    and the reasons it names are the reasons it actually measured:

        checkout-health: kosher-ai-filter  quiet       lock=none behind=0 dirty=0 ...
        checkout-health: lpt-website       flagged     checkout-health:lpt-website:20260928  dirty-old; ...
        checkout-health: lpt-website       suppressed  dedup checkout-health:lpt-website:20260928 is already new
        checkout-health: waste-system      suppressed  disabled
        checkout-health: x                 unreadable  no directory at /home/zabz/repos/x

    A source that silently declines to file is indistinguishable from one that
    found nothing, so a project this source could not READ is named on stderr and
    makes the process exit 1 (run-wake-sources.sh logs it as FAILED rc=1 with the
    reason). Findings for the OTHER projects are still filed first: one
    unreadable project must not blind the rest.

WHAT THE FLAG HANDS THE WORKER
    The evidence it measured (lock path, size, mtime, age, owner-or-none; branch,
    HEAD sha and date, upstream target sha, commits behind and ahead; dirty count,
    every changed path and the oldest one's age) and the exact safe sequence, in
    order: check for a live git process FIRST, move the lock ASIDE (never delete)
    into /home/zabz/checkout-health-preserved/, preserve uncommitted work before
    touching anything, `git fetch`, `git merge --ff-only`, put the work back. It
    states the absolute prohibitions: never `git reset --hard`, never force, never
    discard uncommitted work, and /root is not writable as zabz.

RUN
    python3 sources/checkout-health.py [--dry-run]

ENVIRONMENT (all read at call time)
    CHECKOUT_HEALTH_REGISTRY        default <this dir>/projects.json
    CHECKOUT_HEALTH_FETCH_TIMEOUT   default 30   seconds, bounded on purpose
    CHECKOUT_HEALTH_BEHIND_MIN      default 50   commits behind upstream
    CHECKOUT_HEALTH_DIRTY_HOURS     default 24   age of the oldest dirty file
    CHECKOUT_HEALTH_LOCK_GRACE_SEC  default 300  a lock younger than this is never stale
    CHECKOUT_HEALTH_DIRTY_IGNORE    default ""   comma-separated extra globs
    CHECKOUT_HEALTH_COOLDOWN_SEC    default 3600 store cooldown for this subject
    CHECKOUT_HEALTH_PRESERVE_DIR    default /home/zabz/checkout-health-preserved
    SMS_INBOX_DB                    the wake store, via _flag.inbox_db()
    WAKE_PAUSE_FILE                 the store's kill switch, as project-keepalive resolves it

MUST NEVER
    * report a held lock as stale (a live `git commit` is normal, not a fault);
    * report a tree that is merely dirty right now, or one declared in
      `dirty_ignore`;
    * write to the checkout. It reads, and it runs `git fetch` (which writes only
      FETCH_HEAD and remote-tracking refs) and nothing else. It never adds,
      commits, merges, stashes, checks out, moves or deletes anything;
    * keep its own count of anything -- the wake store is the only state;
    * raise a flag from inside a woken session (the store refuses that itself);
    * touch cron, the caps, or the daily budget.
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flag                                                     # noqa: E402
from _flag import Finding, Unreadable                            # noqa: E402

SOURCE = "checkout-health"
HERE = Path(__file__).resolve().parent

DEFAULT_FETCH_TIMEOUT = 30
DEFAULT_BEHIND_MIN = 50
DEFAULT_DIRTY_HOURS = 24.0
DEFAULT_LOCK_GRACE_SEC = 300
DEFAULT_COOLDOWN_SEC = 3600
DEFAULT_PRESERVE_DIR = "/home/zabz/checkout-health-preserved"

# The store's own live states (wake.py LIVE_STATES). A row in one of these is the
# dedup guard working, and this source says so by name instead of calling it a
# fresh filing.
LIVE_STATES = ("new", "claimed")

# git hygiene for a sensor: never block on a credential prompt, never take an
# optional lock (that is what `git status` would otherwise do), never page.
_GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "cat",
    "LC_ALL": "C",
}

# Set when a project could not be READ. main() turns it into exit 1 after the
# readable projects have been filed -- an unreadable signal is never healthy, and
# one broken project must not blind the others.
_UNREADABLE: list[str] = []


# --------------------------------------------------------------------------- #
# environment
# --------------------------------------------------------------------------- #
def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        return default


def registry_path() -> Path:
    raw = os.environ.get("CHECKOUT_HEALTH_REGISTRY")
    return Path(raw).expanduser() if raw else (HERE / "projects.json")


def preserve_dir() -> Path:
    return Path(os.environ.get("CHECKOUT_HEALTH_PRESERVE_DIR")
                or DEFAULT_PRESERVE_DIR)


def fetch_timeout() -> int:
    return max(1, _env_int("CHECKOUT_HEALTH_FETCH_TIMEOUT", DEFAULT_FETCH_TIMEOUT))


def pause_file() -> Path:
    """The store's kill switch, resolved the way project-keepalive resolves it."""
    raw = os.environ.get("WAKE_PAUSE_FILE")
    if raw:
        return Path(raw).expanduser()
    return _flag.inbox_db().parent / "WAKE_PAUSED"


def extra_ignores() -> list[str]:
    raw = os.environ.get("CHECKOUT_HEALTH_DIRTY_IGNORE") or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


# --------------------------------------------------------------------------- #
# reading the registry (the same validation discipline as project-keepalive)
# --------------------------------------------------------------------------- #
def load_registry() -> list[dict]:
    path = registry_path()
    if not path.is_file():
        raise Unreadable(f"no project registry at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Unreadable(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise Unreadable(f"{path} is not valid JSON: {exc}") from exc

    if isinstance(raw, list):
        projects = raw
    elif isinstance(raw, dict):
        projects = raw.get("projects")
    else:
        raise Unreadable(f"{path}: top level must be a list or an object")
    if not isinstance(projects, list) or not projects:
        raise Unreadable(f"{path}: 'projects' must be a non-empty list")

    seen: set[str] = set()
    for idx, project in enumerate(projects):
        if not isinstance(project, dict):
            raise Unreadable(f"{path}: projects[{idx}] is not an object")
        pid = project.get("id")
        if not isinstance(pid, str) or not pid.strip():
            raise Unreadable(f"{path}: projects[{idx}] has no id")
        if pid in seen:
            raise Unreadable(f"{path}: duplicate project id {pid!r}")
        seen.add(pid)
        if not isinstance(project.get("enabled"), bool):
            raise Unreadable(f"{path}: project {pid!r} needs a boolean 'enabled'")
        ignore = project.get("dirty_ignore", [])
        if not isinstance(ignore, list) or any(not isinstance(x, str) for x in ignore):
            raise Unreadable(
                f"{path}: project {pid!r} has a bad dirty_ignore: {ignore!r}")
    return projects


# --------------------------------------------------------------------------- #
# git
# --------------------------------------------------------------------------- #
class GitResult:
    __slots__ = ("rc", "out", "err", "timed_out")

    def __init__(self, rc: int, out: str, err: str, timed_out: bool = False):
        self.rc = rc
        self.out = out
        self.err = err
        self.timed_out = timed_out

    @property
    def ok(self) -> bool:
        return self.rc == 0


def run_git(repo: Path, args: list[str], timeout: int = 30) -> GitResult:
    """Run one git command. A timeout is a RESULT (rc=124), not an exception."""
    env = {**os.environ, **_GIT_ENV}
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, errors="replace",
            timeout=timeout, env=env)
    except FileNotFoundError as exc:
        raise Unreadable(f"git is not available: {exc}") from exc
    except subprocess.TimeoutExpired:
        return GitResult(124, "", f"git {' '.join(args)} timed out after {timeout}s",
                         timed_out=True)
    # Only NEWLINES are trimmed, never whitespace: `git status --porcelain` puts
    # the two status columns first, so a modified-and-unstaged file is the line
    # " M path" -- and a leading .strip() eats that space, shifting every path by
    # one character ("reconciliation_plan.json" became "econciliation_plan.json"
    # and every age came back unreadable). Measured on secratary 2026-09-28.
    out = (proc.stdout or "").replace("\r\n", "\n").rstrip("\n")
    err = (proc.stderr or "").replace("\r\n", "\n").rstrip("\n")
    return GitResult(proc.returncode, out, err)


def _oneline(text: object, limit: int = 200) -> str:
    """One line, always: git's own errors are multi-line and the output contract
    gives this source exactly one stderr line per project."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


# --------------------------------------------------------------------------- #
# lock liveness -- /proc, by comm and by open descriptor
# --------------------------------------------------------------------------- #
def scan_processes() -> tuple[list[tuple[int, str, str | None]], bool]:
    """(git processes as (pid, comm, cwd), whether /proc was readable at all).

    `pgrep -f 'git '` is deliberately NOT used: measured on secratary
    2026-09-28T17:15Z it matched three processes and none of them was git (a dsh
    node session whose task text contained "git", a `bash -c` script body, and a
    `grep` whose pattern contained it). Comm is what tells us a process really IS
    git; a command line is a text field anyone can write "git" into.
    """
    procs: list[tuple[int, str, str | None]] = []
    readable = 0
    try:
        entries = os.listdir("/proc")
    except OSError:
        return procs, False
    for entry in entries:
        if not entry.isdigit():
            continue
        base = f"/proc/{entry}"
        try:
            comm = Path(base, "comm").read_text(
                encoding="utf-8", errors="replace").strip()
        except OSError:
            continue                     # died between listdir and read
        readable += 1
        if comm == "git" or comm.startswith("git-"):
            try:
                cwd: str | None = os.readlink(f"{base}/cwd")
            except OSError:
                cwd = None
            procs.append((int(entry), comm, cwd))
    return procs, readable > 0


def lock_owner(lock: Path, repo: Path,
               procs: list[tuple[int, str, str | None]]) -> str:
    """A description of the live git process that owns `lock`, or "".

    Holding the lock means having it open, so the descriptor test is the exact
    one and goes first. A git process working inside the repo is the broad test.
    Both consider only processes whose comm says git, so a bystander that merely
    mentions git in its command line cannot produce a false "held".
    """
    want = str(lock)
    prefix = str(repo).rstrip("/") + "/"
    for pid, comm, _cwd in procs:
        fddir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fddir)
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(f"{fddir}/{fd}")
            except OSError:
                continue
            if target == want:
                return f"pid {pid} ({comm}) holds it open as fd {fd}"
    for pid, comm, cwd in procs:
        if cwd and (cwd == str(repo) or cwd.startswith(prefix)):
            return f"pid {pid} ({comm}) is running in {cwd}"
    return ""


# --------------------------------------------------------------------------- #
# one project
# --------------------------------------------------------------------------- #
def check_project(project: dict, now: datetime, opts: dict) -> dict[str, Any]:
    """Read one checkout and return what was measured. Raises Unreadable.

    `reasons` are flag-worthy. `unmeasured` is loud but is NOT a flag: it says
    this source could not measure something, which is a different thing from
    finding a fault, and must not spend a release.
    """
    pid = project["id"]
    raw_repo = project.get("repo")
    if not isinstance(raw_repo, str) or not raw_repo.strip():
        raise Unreadable(f"project {pid!r}: no 'repo' path in the registry")
    repo = Path(raw_repo.strip()).expanduser()

    if not repo.is_dir():
        raise Unreadable(f"project {pid!r}: no directory at {repo}")

    inside = run_git(repo, ["rev-parse", "--is-inside-work-tree"])
    if not inside.ok or inside.out != "true":
        raise Unreadable(
            f"project {pid!r}: {repo} is not a git working tree "
            f"({inside.err or inside.out or 'rc=%d' % inside.rc})")

    gitdir_res = run_git(repo, ["rev-parse", "--absolute-git-dir"])
    if not gitdir_res.ok:
        raise Unreadable(
            f"project {pid!r}: cannot resolve the git dir of {repo}: "
            f"{gitdir_res.err or 'rc=%d' % gitdir_res.rc}")
    gitdir = Path(gitdir_res.out)

    report: dict[str, Any] = {
        "pid": pid,
        "title": str(project.get("title") or pid),
        "repo": repo,
        "gitdir": gitdir,
        "reasons": [],        # flag-worthy
        "unmeasured": [],     # loud, exit 1, never a flag
        "notes": [],          # measured and reported, but not a fault
    }

    # --- A. the lock ------------------------------------------------------- #
    def _read_lock(lock: Path, repo_for_owner: Path, label: str,
                   strict: bool = False) -> dict[str, Any]:
        """Classify one index.lock and append its reasons/notes to `report`.

        Factored out of the main-checkout path so a LINKED WORKTREE's lock gets
        exactly the same liveness test. The broad "cwd inside the repo" probe is
        run against `repo_for_owner` (the worktree's own path for a worktree
        lock), because a git process holding a worktree lock is working there.
        """
        info: dict[str, Any] = {"path": lock, "exists": lock.exists()}
        if not info["exists"]:
            info["state"] = "none"
            return info
        procs, trustworthy = scan_processes()
        try:
            st = lock.stat()
        except OSError as exc:
            if strict:
                raise Unreadable(
                    f"project {pid!r}: cannot stat {lock}: {exc}") from exc
            info["state"] = "unstattable"
            report["notes"].append(
                f"{label}lock {lock}: cannot stat it ({exc}) -- lock NOT judged")
            return info
        age = (now - datetime.fromtimestamp(st.st_mtime, timezone.utc)).total_seconds()
        owner = lock_owner(lock, repo_for_owner, procs)
        info.update({
            "age_sec": age,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc),
            "owner": owner,
            "proc_scan": trustworthy,
            "procs_seen": len(procs),
        })
        grace = opts["lock_grace_sec"]
        young = -grace < age < grace           # a future mtime counts as young
        if owner:
            info["state"] = "held"
            report["notes"].append(
                f"{label}lock held by {owner} -- a live git operation, normal, not a fault")
        elif young:
            info["state"] = "young"
            report["notes"].append(
                f"{label}lock is {age:.0f}s old, inside the {grace}s grace, and no git "
                f"process owns it -- not called stale yet")
        elif not trustworthy:
            info["state"] = "unverified"
            report["notes"].append(
                f"{label}lock is {age:.0f}s old and no git process owns it, but /proc "
                f"could not be scanned -- liveness NOT verified")
            report["reasons"].append("lock-stale-unverified")
        else:
            info["state"] = "stale"
            report["reasons"].append("lock-stale")
        return info

    lock = gitdir / "index.lock"
    report["lock"] = _read_lock(lock, repo, "", strict=True)

    # A linked worktree keeps its own index and index.lock under
    # <gitdir>/worktrees/<name>/index.lock. Those are the locks of the OTHER
    # trees a shift may be working in; a stale one strands that worktree while
    # <gitdir>/index.lock is perfectly absent. Judge each by the same rule.
    report["worktree_locks"] = []
    try:
        wt_root = gitdir / "worktrees"
        wt_dirs = (sorted(p for p in wt_root.glob("*") if p.is_dir())
                   if wt_root.is_dir() else [])
    except OSError as exc:
        report["notes"].append(
            f"cannot list worktrees under {gitdir}/worktrees: {exc}")
        wt_dirs = []
    for wt_gitdir in wt_dirs:
        wt_lock = wt_gitdir / "index.lock"
        if not wt_lock.is_file():
            continue
        wt_repo = repo
        try:
            raw_gitdir = (wt_gitdir / "gitdir").read_text(
                encoding="utf-8", errors="replace").strip()
            if raw_gitdir:
                wt_repo = Path(raw_gitdir).parent
        except OSError:
            pass
        info = _read_lock(wt_lock, wt_repo, f"worktree {wt_gitdir.name}: ")
        info["worktree"] = str(wt_repo)
        info["worktree_name"] = wt_gitdir.name
        if info["state"] in ("stale", "unverified"):
            report["notes"].append(
                f"stale lock in WORKTREE {wt_repo} -- it strands that worktree, "
                f"not the main checkout")
        report["worktree_locks"].append(info)

    # --- B. fetch, then staleness ------------------------------------------ #
    fetch = run_git(repo, ["fetch", "--quiet", "origin"],
                    timeout=opts["fetch_timeout"])
    branch_res = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    if not branch_res.ok:
        raise Unreadable(
            f"project {pid!r}: cannot read HEAD of {repo}: "
            f"{branch_res.err or 'rc=%d' % branch_res.rc}")
    branch = branch_res.out
    head_sha = run_git(repo, ["rev-parse", "--short", "HEAD"]).out
    head_date = run_git(repo, ["log", "-1", "--format=%cI"]).out

    upstream, upstream_how = resolve_upstream(repo, branch)
    behind: int | None = None
    ahead: int | None = None
    target_sha = ""
    if upstream:
        behind_res = run_git(repo, ["rev-list", "--count", f"HEAD..{upstream}"])
        ahead_res = run_git(repo, ["rev-list", "--count", f"{upstream}..HEAD"])
        if behind_res.ok and behind_res.out.isdigit():
            behind = int(behind_res.out)
        if ahead_res.ok and ahead_res.out.isdigit():
            ahead = int(ahead_res.out)
        target_sha = run_git(repo, ["rev-parse", "--short", upstream]).out

    report["staleness"] = {
        "branch": branch,
        "head_sha": head_sha,
        "head_date": head_date,
        "upstream": upstream,
        "upstream_how": upstream_how,
        "target_sha": target_sha,
        "behind": behind,
        "ahead": ahead,
        "fetched": fetch.ok,
        "fetch_error": "" if fetch.ok else (fetch.err or f"rc={fetch.rc}"),
        "timed_out": fetch.timed_out,
    }

    if fetch.timed_out:
        report["unmeasured"].append(
            f"fetch TIMED OUT after {opts['fetch_timeout']}s -- staleness NOT MEASURED")
    elif not fetch.ok:
        report["unmeasured"].append(
            f"fetch FAILED ({_oneline(report['staleness']['fetch_error'])}) -- "
            f"staleness NOT MEASURED")
    if upstream is None:
        report["unmeasured"].append(
            "no upstream resolvable (@{u}, origin/HEAD, "
            f"origin/{branch}, origin/main, origin/test) -- staleness NOT MEASURED")
    elif behind is None:
        report["unmeasured"].append(
            f"cannot count commits between HEAD and {upstream} -- "
            f"staleness NOT MEASURED")
    elif behind >= opts["behind_min"]:
        if fetch.ok:
            report["reasons"].append("behind")
        else:
            # The count is against a remote-tracking ref that nothing refreshed,
            # so it may under- or over-state the drift. Report it; never flag it:
            # a flag may only claim a measurement that was actually taken.
            report["notes"].append(
                f"behind={behind} counted against a STALE local {upstream} ref "
                f"(the fetch failed) -- reported, not flagged")

    # --- C. dirty, and for how long ---------------------------------------- #
    status = run_git(repo, ["status", "--porcelain", "--", "."])
    if not status.ok:
        raise Unreadable(
            f"project {pid!r}: cannot read the working tree of {repo}: "
            f"{status.err or 'rc=%d' % status.rc}")
    ignores = list(project.get("dirty_ignore") or []) + opts["ignores"]
    changed: list[dict[str, Any]] = []
    for line in status.out.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()      # a rename: the new name
        path = path.strip('"')
        full = repo / path
        try:
            age: float | None = (now - datetime.fromtimestamp(
                full.stat().st_mtime, timezone.utc)).total_seconds()
        except OSError:
            age = None
        ignored = any(fnmatch.fnmatch(path, pat)
                      or fnmatch.fnmatch(Path(path).name, pat) for pat in ignores)
        changed.append({"code": line[:2], "path": path, "age_sec": age,
                        "ignored": ignored})

    counted = [c for c in changed if not c["ignored"]]
    ages = [c["age_sec"] for c in counted if c["age_sec"] is not None]
    oldest = max(ages) if ages else None
    report["dirty"] = {
        "total": len(changed),
        "counted": len(counted),
        "ignored": [c["path"] for c in changed if c["ignored"]],
        "files": counted,
        "oldest_age_sec": oldest,
        "unstattable": [c["path"] for c in counted if c["age_sec"] is None],
    }
    if counted and oldest is not None and oldest > opts["dirty_hours"] * 3600:
        report["reasons"].append("dirty-old")

    return report


def resolve_upstream(repo: Path, branch: str) -> tuple[str | None, str]:
    """The ref HEAD should be compared against, and how it was chosen."""
    direct = run_git(repo, ["rev-parse", "--abbrev-ref", "--symbolic-full-name",
                            "@{u}"])
    if direct.ok and direct.out and direct.out != "@{u}":
        return direct.out, "configured upstream (@{u})"

    candidates: list[tuple[str, str]] = []
    symbol = run_git(repo, ["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"])
    if symbol.ok and symbol.out:
        candidates.append((symbol.out, "origin/HEAD"))
    candidates.append((f"origin/{branch}", f"origin/{branch} (the branch name)"))
    candidates.append(("origin/main", "origin/main (fallback)"))
    candidates.append(("origin/test", "origin/test (fallback)"))
    for ref, how in candidates:
        if run_git(repo, ["rev-parse", "--verify", "--quiet", ref]).ok:
            return ref, how
    return None, "none"


# --------------------------------------------------------------------------- #
# the prompt the woken session is handed
# --------------------------------------------------------------------------- #
def _fmt_age(seconds: float | None) -> str:
    if seconds is None:
        return "age unknown"
    hours = seconds / 3600.0
    if hours < 1:
        return f"{seconds / 60.0:.0f} min"
    if hours < 48:
        return f"{hours:.1f} h"
    return f"{hours / 24.0:.1f} days"


def worker_prompt(project: dict, report: dict, now: datetime) -> str:
    """The exact fix and its evidence -- not a diagnosis task."""
    pid = report["pid"]
    repo = report["repo"]
    lock = report["lock"]
    stale = report["staleness"]
    dirty = report["dirty"]
    preserve = preserve_dir()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    lines = [
        f"CHECKOUT HEALTH - `{pid}` (`{repo}`). You are a woken session with no",
        "history of this project. Nothing here needs diagnosing: the measurements",
        "below were taken by the checkout-health source, and the fix is the sequence",
        "in STEP-BY-STEP below. Work through it, then prove the checkout is healthy.",
        "",
        f"raised at {now.strftime('%Y-%m-%d %H:%M')}Z   reasons: "
        f"{', '.join(report['reasons'])}",
        "",
        "WHAT WAS MEASURED",
        f"  repo         {repo}",
        f"  branch       {stale['branch']}",
        f"  HEAD         {stale['head_sha'] or '?'}"
        + (f"  (committed {stale['head_date']})" if stale["head_date"] else ""),
        f"  upstream     {stale['upstream'] or 'NONE'} (chosen via "
        f"{stale['upstream_how']}) at {stale['target_sha'] or '?'}",
        f"  behind       {stale['behind'] if stale['behind'] is not None else 'NOT MEASURED'}"
        + ("" if stale["fetched"] or stale["behind"] is None
           else " (against a STALE local ref: the fetch failed)")
        + f" commits    ahead {stale['ahead'] if stale['ahead'] is not None else '?'}",
        f"  fetch        {'ok' if stale['fetched'] else 'FAILED: ' + _oneline(stale['fetch_error'], 300)}",
    ]

    if lock["exists"]:
        when = lock.get("mtime")
        lines.append(
            f"  lock         {lock['path']} EXISTS, {lock.get('size', '?')} bytes, "
            f"written {when.strftime('%Y-%m-%d %H:%M:%SZ') if when else '?'}, "
            f"age {_fmt_age(lock.get('age_sec'))}")
        lines.append(
            "               owner: " + (lock.get("owner") or
                                      "NO live git process owns it (measured via /proc)"))
    else:
        lines.append(f"  lock         none at {lock['path']}")

    for w in report.get("worktree_locks", []):
        when = w.get("mtime")
        lines.append(
            f"  lock(wt)     {w['path']} EXISTS, {w.get('size', '?')} bytes, "
            f"written {when.strftime('%Y-%m-%d %H:%M:%SZ') if when else '?'}, "
            f"age {_fmt_age(w.get('age_sec'))}, worktree {w.get('worktree', '?')}")
        lines.append(
            "               owner: " + (w.get("owner") or
                                      "NO live git process owns it (measured via /proc)"))

    if dirty["counted"]:
        lines.append(
            f"  dirty        {dirty['counted']} uncommitted path(s), oldest "
            f"{_fmt_age(dirty['oldest_age_sec'])}"
            + (f"; mtime unreadable: {', '.join(dirty['unstattable'])}"
               if dirty["unstattable"] else ""))
        for item in dirty["files"][:20]:
            lines.append(
                f"               {item['code']} {item['path']}  ({_fmt_age(item['age_sec'])})")
        if len(dirty["files"]) > 20:
            lines.append(f"               ... and {len(dirty['files']) - 20} more")
    else:
        lines.append("  dirty        none")

    if dirty["ignored"]:
        lines.append(f"  dirty_ignore {', '.join(dirty['ignored'])} (declared; not counted)")
    for note in report["notes"] + report["unmeasured"]:
        lines.append(f"  note         {note}")

    target = stale["upstream"] or f"origin/{stale['branch']}"

    lines += [
        "",
        "STEP 0 - CHECK FOR A LIVE GIT PROCESS FIRST. Do not skip this, and do not",
        "use `pgrep -f 'git '` -- it matches any process that merely has the word in",
        "its command line, including your own session. Use the exact test:",
        "    pgrep -a -x git                        # comm is exactly git",
        "    ls -l /proc/*/fd 2>/dev/null | grep -F .git/index.lock",
        "If either shows a git process actually holding the lock, STOP: a running git",
        "operation owns it and it must be left alone. Report that and finish.",
        "",
        "STEP 1 - MOVE THE LOCK ASIDE, never delete it, and only if STEP 0 was clean:",
        "    TS=$(date -u +%Y%m%dT%H%M%SZ)",
        f"    mkdir -p {preserve}",
        f"    mv {lock['path']} {preserve}/{pid}-index.lock.$TS",
        *[f"    mv {w['path']} {preserve}/{pid}-wt-"
          f"{w.get('worktree_name', 'wt')}-index.lock.$TS"
          for w in report.get("worktree_locks", [])
          if w.get("state") in ("stale", "young", "unverified")],
        f"  ({preserve} is under /home/zabz. /root is NOT writable as zabz, and",
        "   nothing may be deleted: a moved-aside lock is evidence, a deleted one is not.)",
        "",
        "STEP 2 - PRESERVE UNCOMMITTED WORK BEFORE ANYTHING TOUCHES THE TREE.",
        "  Only when the dirty list above is non-empty, and before you fetch or merge:",
        f"    DEST={preserve}/{pid}-work-$TS",
        '    mkdir -p "$DEST"',
        f'    git -C {repo} status --porcelain > "$DEST/status.txt"',
        f'    git -C {repo} diff > "$DEST/uncommitted.diff"',
        f'    git -C {repo} diff --cached >> "$DEST/uncommitted.diff"',
        f'    git -C {repo} stash push --include-untracked -m "checkout-health {stamp}"',
        f'    git -C {repo} stash show -p "stash@{{0}}" > "$DEST/stash.patch"',
        "  A stash is a real object: nothing is thrown away, and `git stash list` finds",
        "  it. Copy anything else that looks like a person's work into $DEST first. If",
        "  the stash itself fails, stop there and report -- do not work around it by",
        "  checking files out.",
        "",
        "STEP 3 - BRING THE CHECKOUT CURRENT:",
        f"    git -C {repo} fetch origin",
        f"    git -C {repo} merge --ff-only {target}",
        "  `--ff-only` is the point: if it refuses, the branch has diverged and that is",
        "  a decision for a person, not a licence to force anything. Report it.",
        "",
        "STEP 4 - PUT THE PRESERVED WORK BACK onto the now-current tree:",
        f"    git -C {repo} stash pop",
        "  If the pop conflicts, leave the stash in place, report the conflict, and",
        "  STOP. Do not resolve it by discarding either side.",
        "",
    ]

    # STEP 5 only says what the evidence supports: abandoned work is a different
    # thing from a tree that is dirty because a session is touching it right now.
    if "dirty-old" in report["reasons"]:
        lines += [
            "STEP 5 - LAND OR ESCALATE THE UNCOMMITTED WORK. It has been sitting there",
            f"  {_fmt_age(dirty['oldest_age_sec'])}, which is why this flag exists: work that never",
            "  landed is work nobody is paying for. If it is a shift's real change, commit",
            "  it on a branch and push it. If it is a generated artefact (a report a tool",
            "  rewrites), keep the copy in $DEST, restore the tracked file with",
            f"      git -C {repo} checkout -- <path>",
            "  and then declare it so it never alarms again: add the path to that project's",
            f"  \"dirty_ignore\" list in {registry_path()}.",
            "  If you cannot tell which it is, say so and leave it exactly as it is.",
        ]
    elif dirty["counted"]:
        lines += [
            "STEP 5 - THE DIRTY FILES ARE RECENT, NOT ABANDONED. The oldest is",
            f"  {_fmt_age(dirty['oldest_age_sec'])} old, which is inside the 24 h the source allows for a",
            "  run in progress. Preserve it (STEP 2), merge (STEP 3), put it back (STEP 4),",
            "  and do NOT commit or discard a change you did not make and do not own.",
        ]
    else:
        lines += [
            "STEP 5 - nothing is uncommitted, so the only work here was the lock and the",
            "  merge above. If the checkout is now current there is nothing to land.",
        ]

    lines += [
        "",
        "PROHIBITIONS - these are absolute:",
        "  * never `git reset --hard`, never `git push --force`, never `git clean -fdx`;",
        "  * never discard, revert or delete uncommitted work you do not understand;",
        "  * never delete a lock file or a preserved copy -- move files, never remove them;",
        "  * never deploy, never touch the database, never contact a customer or the owner;",
        "  * never raise a wake flag yourself, and do not touch cron or the caps.",
        "",
        "PROOF YOU MUST REPORT, as commands with their output, not as claims:",
        f"    ls -l {lock['path']}                              # moved aside, never deleted",
        f"    git -C {repo} rev-list --count HEAD..{target}     # 0",
        f"    git -C {repo} status --porcelain                  # what the tree holds now",
        f"    git -C {repo} rev-parse --short HEAD              # the new HEAD",
        "    python3 /home/zabz/bin/sources/checkout-health.py --dry-run",
        "The last one must show this project as `quiet` (or name the condition that is",
        "genuinely still true). If a condition survives you, say which and why.",
        "",
        "THEN: the project's own daily shift continues under project-keepalive; this flag",
        "exists so that shift lands commits instead of working against a tree nobody",
        "else has.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# the source
# --------------------------------------------------------------------------- #
def collect(args) -> list[Finding]:
    now = _flag.now_utc()
    today = now.strftime("%Y%m%d")

    opts = {
        "fetch_timeout": fetch_timeout(),
        "behind_min": max(1, _env_int("CHECKOUT_HEALTH_BEHIND_MIN", DEFAULT_BEHIND_MIN)),
        "dirty_hours": max(0.0, _env_float("CHECKOUT_HEALTH_DIRTY_HOURS",
                                           DEFAULT_DIRTY_HOURS)),
        "lock_grace_sec": max(0, _env_int("CHECKOUT_HEALTH_LOCK_GRACE_SEC",
                                          DEFAULT_LOCK_GRACE_SEC)),
        "cooldown": max(0, _env_int("CHECKOUT_HEALTH_COOLDOWN_SEC",
                                    DEFAULT_COOLDOWN_SEC)),
        "ignores": extra_ignores(),
    }

    projects = load_registry()

    # The store is read once, read-only, for the two things this source must
    # report honestly: whether the day's budget is already spent (the row is
    # filed and waits), and whether the subject of the day is already live.
    live_subjects: dict[str, str] = {}
    released_today, global_cap = 0, _env_int("WAKE_MAX_PER_DAY", 500)
    conn = _flag.ro_connect(_flag.inbox_db())
    try:
        for table in ("wake", "wake_budget"):
            if not _flag.table_exists(conn, table):
                raise Unreadable(f"the wake store has no {table} table")
        row = conn.execute("SELECT released FROM wake_budget WHERE day=?",
                           (now.strftime("%Y-%m-%d"),)).fetchone()
        released_today = int(row["released"]) if row else 0
        for r in conn.execute(
                "SELECT subject, state FROM wake WHERE subject LIKE 'checkout-health:%'"
        ).fetchall():
            if str(r["state"]) in LIVE_STATES:
                live_subjects[str(r["subject"])] = str(r["state"])
    finally:
        conn.close()

    paused_at = pause_file()
    lines: list[str] = []
    findings: list[Finding] = []
    suppressed = 0

    for project in projects:
        pid = str(project["id"])

        if not project["enabled"]:
            lines.append(f"{pid}  suppressed  disabled")
            suppressed += 1
            continue

        raw_repo = project.get("repo")
        if not isinstance(raw_repo, str) or not raw_repo.strip():
            reason = "no 'repo' path in the registry (nothing to check)"
            lines.append(f"{pid}  unreadable  {reason}")
            _UNREADABLE.append(f"{pid}: {reason}")
            continue

        try:
            report = check_project(project, now, opts)
        except Unreadable as exc:
            lines.append(f"{pid}  unreadable  {exc}")
            _UNREADABLE.append(f"{pid}: {exc}")
            continue

        stale = report["staleness"]
        lock = report["lock"]
        dirty = report["dirty"]
        lock_bits: list[str] = []
        if lock["exists"]:
            main_state = lock.get("state", "unknown")
            if main_state not in ("none", "held"):
                main_state = f"{main_state} {_fmt_age(lock.get('age_sec'))}"
            lock_bits.append(main_state)
        for wt in report.get("worktree_locks", []):
            wt_state = wt.get("state", "unknown")
            if wt_state not in ("none", "held"):
                wt_state = f"{wt_state} {_fmt_age(wt.get('age_sec'))}"
            lock_bits.append(f"wt:{wt.get('worktree_name', '?')}:{wt_state}")
        lock_state = ",".join(lock_bits) if lock_bits else "none"
        dirty_txt = f"dirty={dirty['counted']}"
        if dirty["ignored"]:
            # Declared-and-excluded is still REPORTED: a project that declared a
            # path away must not look identical to one with a clean tree.
            dirty_txt += f" (declared: {','.join(dirty['ignored'])})"
        behind_txt = ("NOT MEASURED" if stale["behind"] is None
                      else f"{stale['behind']}" + ("" if stale["fetched"] else " (stale ref)"))
        measured = (
            f"branch={stale['branch']} head={stale['head_sha'] or '?'} "
            f"behind={behind_txt} "
            f"ahead={stale['ahead'] if stale['ahead'] is not None else '?'} "
            f"lock={lock_state} {dirty_txt}"
            + (f" oldest={_fmt_age(dirty['oldest_age_sec'])}" if dirty["counted"] else "")
            + (f" unmeasured: {'; '.join(report['unmeasured'])}"
               if report["unmeasured"] else ""))

        if not report["reasons"]:
            if report["unmeasured"]:
                detail = "; ".join(report["unmeasured"])
                lines.append(f"{pid}  unreadable  {detail}  ({measured})")
                _UNREADABLE.append(f"{pid}: {detail}")
            else:
                lines.append(f"{pid}  quiet       {measured}")
            continue

        subject = f"{SOURCE}:{pid}:{today}"
        reasons = ",".join(report["reasons"])
        # A condition was found and part of the signal was unreadable: say both.
        if report["unmeasured"]:
            _UNREADABLE.append(f"{pid}: {'; '.join(report['unmeasured'])}")

        if paused_at.exists():
            lines.append(f"{pid}  suppressed  paused (the store's kill switch "
                         f"{paused_at} exists)  [due: {subject} {reasons}]")
            suppressed += 1
            continue

        if subject in live_subjects:
            lines.append(f"{pid}  suppressed  dedup {subject} is already "
                         f"{live_subjects[subject]}  ({measured})")
            suppressed += 1
            continue

        cap_note = ""
        if released_today >= global_cap:
            cap_note = (f" (capped: {released_today}/{global_cap} releases today -- the row "
                        f"is filed and waits for the next budget slot)")
        findings.append(Finding(
            subject=subject,
            prompt=worker_prompt(project, report, now),
            context=f"{SOURCE}: {pid} {reasons}; {measured}",
            priority=str(project.get("priority") or "normal"),
            kind="bug",
            cooldown_seconds=opts["cooldown"],
        ))
        lines.append(f"{pid}  flagged     {subject}  {reasons}; {measured}{cap_note}")

    # One line per project, on stderr: a source that declines to file has to say so
    # and name the reason, or `quiet` hides a broken cap or a broken project.
    for line in lines:
        print(f"{SOURCE}: {line}", file=sys.stderr)
    print(f"{SOURCE}: {len(findings)} flag(s) to raise, {suppressed} suppression(s), "
          f"{len(_UNREADABLE)} unreadable/unmeasured project(s), system-wide releases "
          f"today {released_today}/{global_cap}", file=sys.stderr)
    return findings


def main() -> int:
    """The house rule: an unreadable signal is never healthy.

    `_flag.run` files what was readable and returns 0, so unreadable projects are
    turned into exit 1 here, AFTER the readable ones have been filed. One missing
    directory must not blind the other project's checkout.
    """
    rc = _flag.run(SOURCE, collect)
    if _UNREADABLE:
        return 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
