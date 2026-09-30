#!/usr/bin/env python3
"""cap.py - the capability registry.

WHAT THIS ANSWERS, for every external capability this system pays for or owns:
  * what capability do we have      -> `list`
  * what does it cost               -> the COST column / `--report`
  * is it wired                     -> the WIRED flag, derived by searching code
  * can an agent actually reach it  -> the REACHABLE flag, derived from the seat
  * (and, on demand) is it alive    -> `--probe NAME`

THE PROVIDER KNOWLEDGE IS DATA. It lives in providers.json next to this file.
Adding a provider, retiring one, changing a price, a category, a credential
name or a probe is an edit to that file. This program contains no provider
list; it only knows how to read the table and how to turn a probe spec into a
request.

CREDENTIALS. This program reads credential FILES to answer "is a credential
present" and "which env var holds it". It NEVER prints a value. Every byte it
emits passes through a redactor loaded with the values it read, so even an
accidental echo is replaced with <redacted:NAME>.

stdlib only. No new dependencies. Python 3.8+.
"""

import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "providers.json"
VERSION = "1"

# Values shorter than this are not treated as secrets worth redacting: single
# characters and empty strings would redact the whole document.
MIN_SECRET_LEN = 8


# --------------------------------------------------------------------------
# output, with a redactor in front of it
# --------------------------------------------------------------------------

class SecretGuard:
    """Holds credential values ONLY to make sure they never reach stdout."""

    def __init__(self):
        self._values = []          # list of (env_name, value)
        self.count = 0

    def add(self, name, value):
        if value is None:
            return
        value = str(value).strip().strip('"').strip("'")
        if len(value) < MIN_SECRET_LEN:
            return
        self._values.append((name, value))
        self.count += 1

    def scrub(self, text):
        if not text:
            return text
        out = str(text)
        for name, value in self._values:
            if value and value in out:
                out = out.replace(value, "<redacted:%s>" % name)
        return out

    def leaked(self, text):
        """Names of credentials whose value is still visible in `text`."""
        hits = []
        for name, value in self._values:
            if value and value in str(text):
                hits.append(name)
        return sorted(set(hits))


GUARD = SecretGuard()


def emit(text=""):
    sys.stdout.write(GUARD.scrub(text) + "\n")


# --------------------------------------------------------------------------
# data + credentials
# --------------------------------------------------------------------------

def load_data(path=DATA_FILE):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def expand(p):
    if p is None:
        return None
    return os.path.expanduser(str(p))


def read_dotenv(path):
    """Return {NAME: VALUE}. Values are used for two things only: deciding
    whether a credential is present, and feeding the redactor."""
    out = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n").rstrip("\r")
                m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
                if not m:
                    continue
                name, value = m.group(1), m.group(2).strip()
                if value[:1] in ("'", '"') and value[-1:] == value[:1] and len(value) >= 2:
                    value = value[1:-1]
                out[name] = value
    except OSError:
        return None
    return out


class Credentials:
    def __init__(self, data, env_file_override=None):
        self.sources = []
        self.file_values = {}
        for src in data.get("credential_sources", []):
            if src.get("format") == "environ":
                self.sources.append({
                    "id": src.get("id"), "label": src.get("label"),
                    "path": None, "read": True, "kind": "environ",
                })
                continue
            path = expand(env_file_override or src.get("path"))
            values = read_dotenv(path) if path else None
            present_file = values is not None
            if values:
                self.file_values.update(values)
            self.sources.append({
                "id": src.get("id"), "label": src.get("label"),
                "path": path, "read": present_file, "kind": "dotenv",
                "names": len(values) if values else 0,
            })
            if values:
                for name, value in values.items():
                    GUARD.add(name, value)
        # the process environment, guarded by the names we care about
        for name, value in os.environ.items():
            GUARD.add(name, value)

    def status(self, names):
        """(present, present_names, empty_names, missing_names) - never values."""
        present_names, empty_names, missing_names = [], [], []
        for name in names:
            value = self.file_values.get(name)
            if value is None:
                value = os.environ.get(name)
            if value is None:
                missing_names.append(name)
            elif str(value).strip() == "":
                empty_names.append(name)
            else:
                present_names.append(name)
        return bool(present_names), present_names, empty_names, missing_names


# --------------------------------------------------------------------------
# the wiring scan
# --------------------------------------------------------------------------

def _skip_walk_error(_exc):
    """Windows raises WinError 448 on untrusted reparse points (npm junctions
    under node_modules). A scan must skip those, not die on them."""
    return


def _iter_files(root, extensions, skip_basenames, prune_dirs, prune_prefixes,
                prune_paths, max_bytes, max_files):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True,
                                                onerror=_skip_walk_error):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in prune_dirs
            and not d.startswith(".git")
            and not any(d.startswith(p) for p in prune_prefixes)
        )
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        if any(rel_dir == pp or rel_dir.startswith(pp + "/") for pp in prune_paths):
            dirnames[:] = []
            continue
        for fn in sorted(filenames):
            if fn in skip_basenames:
                continue
            if not any(fn.lower().endswith(ext) for ext in extensions):
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > max_bytes:
                    continue
            except OSError:
                continue
            count += 1
            if count > max_files:
                return
            yield full


def scan_for_wiring(data, providers):
    """Return (roots_report, matches) where matches[provider_id] = {root_id: [relpaths]}.

    WIRED is derived, not asserted: every provider carries `refs` (env var names
    and distinctive aliases) and we count the files that mention any of them.
    """
    scan = data.get("scan", {})
    extensions = [e.lower() for e in scan.get("extensions", [])]
    skip_basenames = set(scan.get("skip_basenames", []))
    max_bytes = int(scan.get("max_file_bytes", 2 * 1024 * 1024))
    max_files = int(scan.get("max_files_per_root", 40000))

    roots_report = []
    matches = {p["id"]: {} for p in providers}

    for root in data.get("search_roots", []):
        resolved = expand(root.get("path"))
        entry = {
            "id": root.get("id"), "label": root.get("label"),
            "declared_path": root.get("path"), "path": resolved,
            "role": root.get("role"), "exists": bool(resolved) and os.path.exists(resolved),
            "files_scanned": 0, "readable": True, "note": None,
        }
        if root.get("role") == "primary" and root.get("absent_ok"):
            entry["note"] = ("absent on this node" if not entry["exists"]
                             else "present on this node")
        if not entry["exists"]:
            roots_report.append(entry)
            continue
        if not os.path.isdir(resolved):
            entry["readable"] = False
            entry["note"] = "not a directory"
            roots_report.append(entry)
            continue

        prune = set(root.get("prune_dirs", []))
        prune_prefixes = list(root.get("prune_prefixes", []))
        prune_paths = [p.replace("\\", "/").strip("/") for p in root.get("prune_paths", [])]
        for full in _iter_files(resolved, extensions, skip_basenames, prune,
                                prune_prefixes, prune_paths, max_bytes, max_files):
            entry["files_scanned"] += 1
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
            except OSError:
                continue
            low = body.lower()
            for prov in providers:
                refs = prov.get("refs") or []
                if not refs:
                    continue
                for ref in refs:
                    if ref.lower() in low:
                        rel = os.path.relpath(full, resolved)
                        matches[prov["id"]].setdefault(root["id"], []).append(rel)
                        break
        roots_report.append(entry)

    return roots_report, matches


def find_mounts(providers):
    """Which MCP server ids are named in a preset/profile that exists on disk.

    This is evidence for REACHABLE, not the flag itself: a row can be mounted in
    a preset that this seat's profile never loads.
    """
    homes = [expand("~/Code/harness-config"), expand("~/.dsh")]
    subs = [
        ("repo-presets", "presets"),
        ("repo-profiles", "profiles"),
        ("dsh-agent-presets", ".agent-presets"),
        ("dsh-profiles", "profiles"),
    ]
    prune = {"node_modules", ".git", "__pycache__", "sessions", "storages",
             "attachments", "tools", "tmp", "metrics"}
    mounts = {}
    for home in homes:
        if not home or not os.path.isdir(home):
            continue
        for kind, sub in subs:
            base = os.path.join(home, sub)
            if not os.path.isdir(base):
                continue
            for dirpath, dirnames, filenames in os.walk(base, topdown=True,
                                                        onerror=_skip_walk_error):
                dirnames[:] = sorted(d for d in dirnames if d not in prune)
                for fn in sorted(filenames):
                    if not fn.lower().endswith((".yml", ".yaml")):
                        continue
                    path = os.path.join(dirpath, fn)
                    try:
                        with open(path, "r", encoding="utf-8", errors="replace") as fh:
                            body = fh.read()
                    except OSError:
                        continue
                    for prov in providers:
                        for mcp_id in prov.get("mcp_ids") or []:
                            if mcp_id in body:
                                mounts.setdefault(prov["id"], []).append({
                                    "mcp_id": mcp_id, "where": kind,
                                    "file": os.path.relpath(path, home),
                                })
    return mounts


# --------------------------------------------------------------------------
# the two derived flags
# --------------------------------------------------------------------------

def derive(provider, matches, seat, mounts):
    wired_by_root = matches.get(provider["id"], {})
    examples = []
    total = 0
    for root_id, rels in sorted(wired_by_root.items()):
        total += len(rels)
        for rel in rels[:2]:
            examples.append("%s:%s" % (root_id, rel))
    wired = total > 0

    basis, near_misses = [], []
    native = provider.get("native_tool")
    if native:
        if native in (seat.get("observed_tools") or []):
            basis.append("native-tool:%s (in this seat's tool plane)" % native)
        else:
            near_misses.append("native-tool:%s is declared but is NOT in this seat's "
                               "observed tool plane" % native)
    observed_mcp = set(seat.get("observed_mcp_tools") or [])
    for mcp_id in provider.get("mcp_ids") or []:
        if mcp_id in observed_mcp:
            basis.append("mcp:%s (mounted in this seat's tool plane)" % mcp_id)
    for m in mounts.get(provider["id"], []):
        if m["mcp_id"] not in observed_mcp:
            near_misses.append(
                "mcp row %s IS mounted in %s/%s, but not in this seat's observed "
                "tool plane" % (m["mcp_id"], m["where"], m["file"]))

    reachable = bool(basis)
    if reachable:
        detail = "; ".join(basis)
    elif near_misses:
        detail = "no path in this seat; " + "; ".join(near_misses)
    else:
        detail = "no wired invocation path for this seat"

    return {
        "wired": {"value": wired, "files": total,
                  "by_root": {k: len(v) for k, v in sorted(wired_by_root.items())},
                  "examples": examples},
        "reachable": {"value": reachable, "basis": basis,
                      "near_misses": near_misses, "detail": detail},
    }


def registry(data, env_file=None):
    providers = data.get("providers", [])
    creds = Credentials(data, env_file_override=env_file)
    roots, matches = scan_for_wiring(data, providers)
    mounts = find_mounts(providers)
    seat = data.get("seat", {})

    rows = []
    for prov in providers:
        names = prov.get("cred_env") or []
        present, present_names, empty_names, missing_names = creds.status(names)
        flags = derive(prov, matches, seat, mounts)
        rows.append({
            "id": prov["id"],
            "name": prov["name"],
            "category": prov.get("category", "other"),
            "credential": {
                "env": names,
                "present": present,
                "present_names": present_names,
                "empty_names": empty_names,
                "missing_names": missing_names,
            },
            "wired": flags["wired"],
            "reachable": flags["reachable"],
            "cost": prov.get("cost", ""),
            "billable": bool(prov.get("billable", False)),
            "alias": prov.get("alias", ""),
            "notes": prov.get("notes", ""),
            "mcp_ids": prov.get("mcp_ids") or [],
            "native_tool": prov.get("native_tool"),
            "probe_available": bool(prov.get("probe", {}).get("kind", "none") != "none"),
        })
    return {
        "registry": "capability-registry",
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": socket.gethostname(),
        "seat": seat,
        "searched": roots,
        "mounts_found": mounts,
        "credentials": {
            "sources": creds.sources,
            "values_guarded": GUARD.count,
            "values_are_never_printed": True,
        },
        "providers": rows,
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def yn(flag, count=None):
    if not flag:
        return "no"
    if count is None:
        return "yes"
    return "yes(%d)" % count


def render_list(reg):
    rows = reg["providers"]
    w_name = max([len("PROVIDER")] + [len(r["name"]) for r in rows]) + 1
    w_cat = max([len("CATEGORY")] + [len(r["category"]) for r in rows]) + 1
    w_cred = max([len("CREDENTIAL (env var NAME)")]
                 + [len(",".join(r["credential"]["env"]) or "-") for r in rows]) + 1
    head = "%-*s %-*s %-*s %-5s %-9s %-5s %s" % (
        w_name, "PROVIDER", w_cat, "CATEGORY", w_cred, "CREDENTIAL (env var NAME)",
        "CRED", "WIRED", "REACH", "COST")
    emit(head)
    emit("-" * len(head))
    for r in sorted(rows, key=lambda x: (x["category"], x["name"].lower())):
        cred = ",".join(r["credential"]["env"]) or "-"
        emit("%-*s %-*s %-*s %-5s %-9s %-5s %s" % (
            w_name, r["name"], w_cat, r["category"], w_cred, cred,
            "yes" if r["credential"]["present"] else "NO",
            yn(r["wired"]["value"], r["wired"]["files"]),
            "yes" if r["reachable"]["value"] else "no",
            r["cost"]))

    emit("")
    emit("WIRED = some scanned code/config references it (alias or env var name). "
         "REACHABLE = a path that exists in THIS seat's tool plane today; it is "
         "not the same as 'we hold a key'.")
    emit("")
    emit("PATHS SEARCHED (the flags above are derived from these, so they are auditable):")
    for root in reg["searched"]:
        state = "scanned %d files" % root["files_scanned"] if root["exists"] else "ABSENT on this node"
        role = root["role"] or "?"
        note = ("  [%s]" % root["note"]) if root.get("note") else ""
        emit("  - %-16s %-9s %-34s %s%s" % (root["id"], role, root["path"], state, note))
    emit("")
    emit("SEAT: %s" % reg["seat"].get("name", "?"))
    emit("  observed %s via %s" % (reg["seat"].get("observed_at", "?"),
                                   reg["seat"].get("how_observed", "?")))
    emit("  native tools seen: %d;  mcp__* tools seen: %d"
         % (len(reg["seat"].get("observed_tools") or []),
            len(reg["seat"].get("observed_mcp_tools") or [])))
    emit("  credentials read for the CRED column: %s"
         % ", ".join(s["label"] for s in reg["credentials"]["sources"]))
    emit("  %d credential values loaded into the redactor; 0 are ever printed."
         % reg["credentials"]["values_guarded"])
    emit("")
    emit("WIRED evidence per provider (first 2 files per root):")
    for r in rows:
        if not r["wired"]["value"]:
            continue
        emit("  - %s: %s" % (r["name"], ", ".join(r["wired"]["examples"])))
    emit("")
    emit("REACH evidence per provider:")
    for r in rows:
        emit("  - %-22s %s" % (r["name"], r["reachable"]["detail"]))


def render_report(reg):
    rows = reg["providers"]
    present_unreachable = [r for r in rows if r["credential"]["present"] and not r["reachable"]["value"]]
    reachable_nocred = [r for r in rows if r["reachable"]["value"] and not r["credential"]["present"]]
    billable = [r for r in rows if r["billable"]]
    hand_only = [r for r in present_unreachable if r["probe_available"]]

    out = []
    out.append("### Capability registry - %s" % reg["generated_at"][:10])
    out.append("")
    out.append("Derived on `%s` from: %s"
               % (reg["host"],
                  " | ".join("%s(%s)" % (s["id"], "scanned" if s["exists"] else "ABSENT")
                             for s in reg["searched"])))
    out.append("Seat: %s - %d native tools, %d mounted MCP tools."
               % (reg["seat"].get("name", "?"),
                  len(reg["seat"].get("observed_tools") or []),
                  len(reg["seat"].get("observed_mcp_tools") or [])))
    out.append("")
    out.append("**Present but unreachable (%d)** - we hold a credential and an agent "
               "in this seat still cannot call it:" % len(present_unreachable))
    if present_unreachable:
        for r in present_unreachable:
            out.append("- **%s** (%s) - key `%s` - %s"
                       % (r["name"], r["category"],
                          ",".join(r["credential"]["present_names"]),
                          r["reachable"]["detail"]))
    else:
        out.append("- none")
    out.append("")
    out.append("**Reachable but has no credential (%d)**:" % len(reachable_nocred))
    if reachable_nocred:
        for r in reachable_nocred:
            out.append("- **%s** (%s) - %s"
                       % (r["name"], r["category"], r["reachable"]["detail"]))
    else:
        out.append("- none")
    out.append("")
    out.append("**Costs money (%d of %d providers)** - every billable row, whether or "
               "not it is reachable:" % (len(billable), len(rows)))
    shown = 0
    for r in billable:
        if shown >= 12:
            out.append("- ... and %d more (see `list`)" % (len(billable) - shown))
            break
        out.append("- %s - %s%s"
                   % (r["name"], r["cost"],
                      "" if r["credential"]["present"] else "  **[no credential]**"))
        shown += 1
    out.append("")
    out.append("Callable only by hand (credential present, no mounted tool, but a "
               "registry probe recipe exists): %s."
               % (", ".join(r["name"] for r in hand_only) if hand_only else "none"))
    return "\n".join(out)


# --------------------------------------------------------------------------
# probing
# --------------------------------------------------------------------------

def _get_path(obj, path):
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return None
    return cur


def _detail(spec, payload, raw, text):
    kind = (spec or {}).get("kind", "static")
    label = (spec or {}).get("label", "result")
    path = (spec or {}).get("path", "")
    if kind == "static":
        return str(label)
    if kind == "list_len":
        node = _get_path(payload, path)
        if isinstance(node, list):
            return "%s=%d" % (label, len(node))
        if isinstance(node, dict):
            return "%s=present(1)" % label
        return "%s=present but not a list" % label
    if kind == "key_present":
        node = _get_path(payload, path)
        if node is None:
            return "%s=absent" % label
        if isinstance(node, (dict, list)):
            return "%s=present" % label
        return "%s=%s" % (label, node)
    if kind == "text_len":
        return "%s=%d" % (label, len(text or raw or ""))
    return str(label)


def do_probe(provider, creds, seat_tools):
    spec = provider.get("probe") or {}
    kind = spec.get("kind", "none")
    name = provider["name"]

    if kind == "none":
        return {"provider": provider["id"], "name": name, "status": "NOT PROBED",
                "latency_ms": None, "result": spec.get("reason", "no probe defined")}

    if kind == "file":
        paths = [expand(p) for p in spec.get("paths", [])]
        found = [p for p in paths if p and os.path.exists(p)]
        require = spec.get("require", "any")
        ok = (len(found) == len(paths)) if require == "all" else bool(found)
        return {"provider": provider["id"], "name": name,
                "status": "OK" if ok else "FAIL", "latency_ms": None,
                "result": "%s: %d/%d paths present%s"
                          % (spec.get("label", "files"), len(found), len(paths),
                             "" if ok else " (" + "; ".join(os.path.basename(p) for p in paths if p not in found) + " missing)")}

    if kind == "tcp_from_dsn":
        env = spec.get("dsn_env")
        dsn = os.environ.get(env) or creds.file_values.get(env) or ""
        if not dsn:
            return {"provider": provider["id"], "name": name, "status": "NOT PROBED",
                    "latency_ms": None,
                    "result": "%s is empty, so there is no host to reach" % env}
        host, port = None, int(spec.get("default_port", 5432))
        try:
            parsed = urllib.parse.urlparse(dsn)
            if parsed.hostname:
                host = parsed.hostname
                port = parsed.port or port
            else:
                m = re.search(r"@([^/:]+)(?::(\d+))?/", dsn)
                if m:
                    host = m.group(1)
                    port = int(m.group(2)) if m.group(2) else port
        except Exception:
            host = None
        if not host:
            return {"provider": provider["id"], "name": name, "status": "NOT PROBED",
                    "latency_ms": None,
                    "result": "could not parse a host:port out of the DSN (value not shown)"}
        start = time.time()
        try:
            with socket.create_connection((host, port), timeout=8):
                ms = int((time.time() - start) * 1000)
            return {"provider": provider["id"], "name": name, "status": "OK",
                    "latency_ms": ms, "result": "TCP connect to %s:%d succeeded" % (host, port)}
        except OSError as exc:
            ms = int((time.time() - start) * 1000)
            return {"provider": provider["id"], "name": name, "status": "FAIL",
                    "latency_ms": ms,
                    "result": "TCP connect to %s:%d failed: %s" % (host, port, type(exc).__name__)}

    if kind != "http":
        return {"provider": provider["id"], "name": name, "status": "NOT PROBED",
                "latency_ms": None, "result": "unknown probe kind %r" % kind}

    # ---- http -----------------------------------------------------------
    auth = spec.get("auth") or {}
    url = spec.get("url")
    if not url and spec.get("url_from_env"):
        base = os.environ.get(spec["url_from_env"]) or creds.file_values.get(spec["url_from_env"])
        if not base:
            return {"provider": provider["id"], "name": name, "status": "NOT PROBED",
                    "latency_ms": None,
                    "result": "%s is empty, so the endpoint is unknown" % spec["url_from_env"]}
        url = base.rstrip("/") + spec.get("url_suffix", "")
    if not url:
        return {"provider": provider["id"], "name": name, "status": "NOT PROBED",
                "latency_ms": None, "result": "no URL defined"}

    env_name = auth.get("env")
    secret = None
    if env_name:
        secret = os.environ.get(env_name) or creds.file_values.get(env_name)
    if auth.get("type") and auth.get("type") != "none" and not auth.get("optional") and not secret:
        return {"provider": provider["id"], "name": name, "status": "NOT PROBED",
                "latency_ms": None,
                "result": "no credential in %s, so nothing to authenticate with" % env_name}

    headers = {"User-Agent": "cap-registry/%s" % VERSION, "Accept": "*/*"}
    headers.update(spec.get("headers") or {})
    data = None
    atype = auth.get("type")
    if atype == "bearer" and secret:
        headers["Authorization"] = "Bearer " + secret
    elif atype == "header" and secret:
        headers[auth.get("name", "Authorization")] = secret
    elif atype == "basic":
        import base64
        user = os.environ.get(auth.get("user_env")) or creds.file_values.get(auth.get("user_env")) or ""
        pwd = os.environ.get(auth.get("pass_env")) or creds.file_values.get(auth.get("pass_env")) or ""
        headers["Authorization"] = "Basic " + base64.b64encode(
            ("%s:%s" % (user, pwd)).encode()).decode()
    elif atype == "query" and secret:
        sep = "&" if "?" in url else "?"
        url = "%s%s%s=%s" % (url, sep, auth.get("param", "key"),
                             urllib.parse.quote(secret, safe=""))

    body = spec.get("body")
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=spec.get("method", "GET"))
    start = time.time()
    status_code, payload, raw = None, None, ""
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status_code = resp.status
            raw = resp.read(400000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        try:
            raw = exc.read(400000).decode("utf-8", "replace")
        except Exception:
            raw = ""
    except Exception as exc:
        ms = int((time.time() - start) * 1000)
        return {"provider": provider["id"], "name": name, "status": "FAIL",
                "latency_ms": ms,
                "result": "request failed before a status: %s" % type(exc).__name__}
    ms = int((time.time() - start) * 1000)

    try:
        payload = json.loads(raw)
    except Exception:
        payload = None

    ok_status = spec.get("ok_status", [200])
    if status_code in ok_status:
        result = _detail(spec.get("detail"), payload, raw, raw)
        if spec.get("ok_note"):
            result = "%s (%s)" % (result, spec["ok_note"])
        return {"provider": provider["id"], "name": name, "status": "OK",
                "latency_ms": ms, "result": result}
    if status_code in (401, 403):
        result = "HTTP %s - credential rejected" % status_code
    elif status_code == 402:
        result = "HTTP 402 - payment/credits required"
    elif status_code == 429:
        result = "HTTP 429 - rate limited (endpoint and key are alive)"
    else:
        result = "HTTP %s - unexpected" % status_code
    return {"provider": provider["id"], "name": name, "status": "FAIL",
            "latency_ms": ms, "result": result}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="cap.py",
        description="Capability registry: what we have, what it costs, whether it "
                    "is wired and whether an agent can reach it.")
    parser.add_argument("command", nargs="?", default="list",
                        choices=["list", "probe", "report", "selftest"],
                        help="list (default) | probe | report | selftest")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output for the same data")
    parser.add_argument("--probe", metavar="NAME", action="append", default=None,
                        help="health-check a provider by id or name (repeatable; "
                             "'all' probes every provider that has a recipe)")
    parser.add_argument("--report", action="store_true",
                        help="publishable markdown block")
    parser.add_argument("--env-file", metavar="PATH", default=None,
                        help="override the credential file")
    parser.add_argument("--data", metavar="PATH", default=str(DATA_FILE),
                        help="override the provider data file")
    args = parser.parse_args(argv)

    data = load_data(args.data)
    reg = registry(data, env_file=args.env_file)

    probes = list(args.probe or [])
    if args.command == "probe" and not probes:
        parser.error("probe needs --probe NAME (or --probe all)")

    if args.report or args.command == "report":
        text = render_report(reg)
        if args.json:
            emit(json.dumps({"markdown": text}, indent=2))
        else:
            emit(text)
        return 0

    if probes:
        by_id = {p["id"]: p for p in data["providers"]}
        by_name = {p["name"].lower(): p for p in data["providers"]}
        wanted = []
        for token in probes:
            if token == "all":
                wanted = [p for p in data["providers"]]
                break
            prov = by_id.get(token) or by_name.get(token.lower())
            if prov is None:
                emit("NOT PROBED  %s - no such provider in %s"
                     % (token, os.path.basename(args.data)))
                continue
            wanted.append(prov)

        creds = Credentials(data, env_file_override=args.env_file)
        results = [do_probe(p, creds, reg["seat"].get("observed_tools") or [])
                   for p in wanted]
        if args.json:
            emit(json.dumps({"host": reg["host"], "probes": results}, indent=2))
        else:
            for r in results:
                lat = "-" if r["latency_ms"] is None else "%dms" % r["latency_ms"]
                emit("%-10s %-22s %-8s %s"
                     % (r["status"], r["name"], lat, r["result"]))
        return 1 if any(r["status"] == "FAIL" for r in results) else 0

    if args.command == "selftest":
        # Prove the redactor works: take every guarded value, run it through the
        # renderers, and assert none survives.
        blob = render_list(reg) + render_report(reg) + json.dumps(
            {k: v for k, v in reg.items()})
        leaks = GUARD.leaked(blob)
        if leaks:
            emit("REDACTION FAILURE: %s visible" % ", ".join(leaks))
            return 2
        emit("ok: %d credential values loaded, 0 leaked into list/report/json"
             % GUARD.count)
        return 0

    if args.json:
        emit(json.dumps(reg, indent=2))
    else:
        render_list(reg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
