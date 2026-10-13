#!/usr/bin/env python3
"""model_resolver.py - resolve AI model ids at RUNTIME from the gateway catalogue.

WHY THIS FILE EXISTS
--------------------
A hardcoded model name once broke every live AI call in this estate for over a week,
silently, because a deterministic fallback hid the failure. The contract this module
implements, and that every agent-side caller of the gateway must obey:

  1. AI models are NEVER hardcoded in agent code.
  2. Resolve at runtime from the gateway catalogue (`GET <base>/v1/models`).
  3. PREFER the gateway's own route aliases (secretary-auto / -fast / -smart).
  4. VALIDATE every configured id against the catalogue and DROP what is not listed.
  5. Cache, with single-flight: N concurrent callers cause exactly ONE fetch.
  6. Fail SOFT (last-good cache) but NEVER SILENTLY: a degraded or dead catalogue is
     published in the output and is a non-zero exit.
  7. PUBLISH which model actually served the request.

Exit contract (so a dispatcher can gate on it, and silence is impossible):
  0  resolved from a live or cached catalogue
  2  usage / environment error
  3  DEGRADED - catalogue unreachable, resolved from last-good cache (loud)
  4  NOTHING RESOLVED - catalogue unreachable and no cache (loud; never a silent pass)

Usage:
  python3 scripts/frontier/model_resolver.py --config cfg.json --base https://gw:8443 \
      --key-env SECRETARY_AI_KEY --cache ~/.cache/psm-models.json --json
  python3 scripts/frontier/model_resolver.py --catalogue-file fixture.json --config cfg.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DEGRADED = 3
EXIT_NO_MODEL = 4

DEFAULT_TTL = 300.0
DEFAULT_TIMEOUT = 8.0


class CatalogueUnavailable(RuntimeError):
    """The catalogue could not be fetched. Never swallowed."""


class NoResolvableModel(RuntimeError):
    """The catalogue was reachable (or cached) but yielded no usable model id."""


# --------------------------------------------------------------------------- parsing


def parse_catalogue(payload) -> set:
    """Accept every shape a gateway has actually returned, and return bare ids."""
    ids = set()

    def _add(v):
        if isinstance(v, str) and v.strip():
            ids.add(v.strip())

    if isinstance(payload, dict):
        for key in ("data", "models", "result", "items"):
            v = payload.get(key)
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, str):
                        _add(it)
                    elif isinstance(it, dict):
                        for k in ("id", "name", "model", "slug"):
                            if isinstance(it.get(k), str):
                                _add(it[k])
                                break
        if not ids:
            for k in payload.keys():
                if k not in ("error", "object", "detail"):
                    _add(k)
    elif isinstance(payload, list):
        for it in payload:
            if isinstance(it, str):
                _add(it)
            elif isinstance(it, dict):
                for k in ("id", "name", "model", "slug"):
                    if isinstance(it.get(k), str):
                        _add(it[k])
                        break
    return ids


def default_fetcher(base: str, key: str | None, timeout: float = DEFAULT_TIMEOUT):
    """Return a zero-arg fetcher that reads GET <base>/v1/models."""

    def _fetch() -> set:
        url = base.rstrip("/") + "/v1/models"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        if key:
            req.add_header("Authorization", "Bearer " + key)
            req.add_header("x-ps-api-key", key)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise CatalogueUnavailable("HTTP %s from %s: %s" % (e.code, url, e.reason))
        except Exception as e:  # URLError, timeout, DNS, TLS, ...
            raise CatalogueUnavailable("%s from %s" % (e.__class__.__name__, url))
        try:
            payload = json.loads(body)
        except ValueError as e:
            raise CatalogueUnavailable("catalogue at %s is not JSON: %s" % (url, e))
        if isinstance(payload, dict) and payload.get("error"):
            raise CatalogueUnavailable("gateway refused catalogue: %s" % (payload["error"],))
        ids = parse_catalogue(payload)
        if not ids:
            raise CatalogueUnavailable("catalogue at %s listed zero models" % url)
        return ids

    return _fetch


# ----------------------------------------------------------------------- single-flight


@dataclass
class CatalogueCache:
    """Single-flight, TTL'd, disk-backed last-good cache for the model catalogue."""

    fetcher: object
    ttl: float = DEFAULT_TTL
    path: Path | None = None
    timeout: float = DEFAULT_TIMEOUT

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _flight: dict | None = field(default=None, repr=False)
    _ids: set | None = field(default=None, repr=False)
    _at: float = field(default=0.0, repr=False)
    fetch_count: int = field(default=0, repr=False)

    def _load_disk(self):
        if not self.path:
            return None
        try:
            blob = json.loads(Path(self.path).read_text("utf-8"))
            ids = set(blob.get("ids") or [])
            return ids or None
        except Exception:
            return None

    def _save_disk(self, ids):
        if not self.path:
            return
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(json.dumps({"ids": sorted(ids), "at": time.time()}), "utf-8")
            os.replace(tmp, p)
        except Exception:
            pass  # a cache write must never take the caller down

    def get(self, force: bool = False):
        """Return (ids, source) where source is live|memory|singleflight|last-good."""
        with self._lock:
            now = time.time()
            if not force and self._ids is not None and (now - self._at) < self.ttl:
                return set(self._ids), "memory"
            if self._flight is not None:
                fl = self._flight
                leader = False
            else:
                fl = {"event": threading.Event(), "ids": None, "err": None}
                self._flight = fl
                leader = True

        if not leader:
            # A follower: it must NOT fetch. It waits on the leader's single fetch.
            fl["event"].wait(self.timeout + 5.0)
            if fl["ids"] is not None:
                return set(fl["ids"]), "singleflight"
            disk = self._load_disk() or self._ids
            if disk:
                return set(disk), "last-good"
            raise fl["err"] or CatalogueUnavailable("catalogue unavailable")

        try:
            self.fetch_count += 1
            ids = set(self.fetcher())
            if not ids:
                raise CatalogueUnavailable("fetcher returned zero ids")
        except Exception as e:
            err = e if isinstance(e, CatalogueUnavailable) else CatalogueUnavailable(str(e))
            with self._lock:
                self._flight = None
                last = self._ids
            fl["err"] = err
            fl["event"].set()
            disk = set(last) if last else self._load_disk()
            if disk:
                return disk, "last-good"
            raise err

        with self._lock:
            self._ids = ids
            self._at = time.time()
            self._flight = None
        self._save_disk(ids)
        fl["ids"] = ids
        fl["event"].set()
        return set(ids), "live"


# ------------------------------------------------------------------------ resolution


@dataclass
class Resolution:
    served: str | None = None
    chain: list = field(default_factory=list)
    dropped: list = field(default_factory=list)
    aliases_absent: list = field(default_factory=list)
    catalogue_size: int = 0
    source: str = ""
    degraded: bool = False

    def as_dict(self):
        return asdict(self)


def resolve(preferred_aliases, configured_models, catalogue_ids) -> Resolution:
    """Prefer aliases, then validated configured ids. Drop anything not in the catalogue."""
    ids = set(catalogue_ids)
    r = Resolution(catalogue_size=len(ids))
    for m in preferred_aliases:
        if m in ids:
            if m not in r.chain:
                r.chain.append(m)
        else:
            r.aliases_absent.append(m)
    for m in configured_models:
        if m in ids:
            if m not in r.chain:
                r.chain.append(m)
        else:
            r.dropped.append(m)
    r.served = r.chain[0] if r.chain else None
    return r


def load_config(path: Path) -> dict:
    try:
        cfg = json.loads(Path(path).read_text("utf-8"))
    except Exception as e:
        raise SystemExit("model_resolver: cannot read config %s: %s" % (path, e))
    if not isinstance(cfg, dict):
        raise SystemExit("model_resolver: config must be a JSON object")
    return {
        "preferred_aliases": [str(x) for x in (cfg.get("preferred_aliases") or [])],
        "configured_models": [str(x) for x in (cfg.get("configured_models") or [])],
        "forbidden": [str(x) for x in (cfg.get("forbidden") or [])],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="resolve AI model ids from the gateway catalogue")
    ap.add_argument("--config", default=None,
                    help="JSON config: preferred_aliases, configured_models. "
                         "OPTIONAL: with no config nothing is pre-trusted, but the "
                         "catalogue/outage path is still exercised (and still exits 4 "
                         "when nothing can be resolved)")
    ap.add_argument("--base", default=os.environ.get("SECRETARY_API_BASE", ""),
                    help="gateway base URL (default $SECRETARY_API_BASE)")
    ap.add_argument("--key-env", default="SECRETARY_AI_KEY",
                    help="env var holding the gateway API key (never pass a key on argv)")
    ap.add_argument("--catalogue-file", default=None, help="offline catalogue fixture (no network)")
    ap.add_argument("--cache", default=os.path.expanduser("~/.cache/psm-model-catalogue.json"))
    ap.add_argument("--ttl", type=float, default=DEFAULT_TTL)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    ap.add_argument("--force", action="store_true", help="ignore the TTL and re-fetch")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    # An absent --config is a valid probe: nothing is pre-trusted, and a dead catalogue
    # must still fail LOUDLY (exit 4). Requiring the flag made the outage path
    # unreachable from the CLI, which is exactly the silent-failure shape this module
    # exists to prevent.
    if args.config:
        cfg = load_config(Path(args.config))
    else:
        cfg = {"preferred_aliases": [], "configured_models": [], "forbidden": []}

    if args.catalogue_file:
        try:
            payload = json.loads(Path(args.catalogue_file).read_text("utf-8"))
        except Exception as e:
            print("model_resolver: cannot read catalogue fixture: %s" % e, file=sys.stderr)
            return EXIT_USAGE
        ids = parse_catalogue(payload)
        source = "fixture"
        cache = None
    else:
        if not args.base:
            print("model_resolver: no --base and $SECRETARY_API_BASE is unset "
                  "(or use --catalogue-file)", file=sys.stderr)
            return EXIT_USAGE
        key = os.environ.get(args.key_env) or None
        cache = CatalogueCache(default_fetcher(args.base, key, args.timeout),
                               ttl=args.ttl, path=Path(args.cache), timeout=args.timeout)
        try:
            ids, source = cache.get(force=args.force)
        except CatalogueUnavailable as e:
            print("model_resolver: CATALOGUE UNAVAILABLE AND NO LAST-GOOD CACHE (%s); "
                  "NOTHING RESOLVED - refusing to guess a model id" % e, file=sys.stderr)
            out = {"ok": False, "exit": EXIT_NO_MODEL, "source": "unavailable",
                   "error": str(e), "served": None}
            print(json.dumps(out) if args.json else out)
            return EXIT_NO_MODEL

    # A configured id that is explicitly forbidden is dropped even if the catalogue lists it.
    forbidden = set(cfg["forbidden"])
    configured = [m for m in cfg["configured_models"] if m not in forbidden]

    res = resolve(cfg["preferred_aliases"], configured, ids)
    res.source = source
    res.degraded = source == "last-good"
    res.dropped += [m for m in cfg["configured_models"] if m in forbidden]

    out = {"ok": res.served is not None, "exit": EXIT_DEGRADED if res.degraded else EXIT_OK,
           "served": res.served, "resolution": res.as_dict(),
           "catalogue_source": source, "fetch_count": (cache.fetch_count if cache else 0)}

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print("served_model: %s" % res.served)
        print("catalogue:    %d ids from %s" % (res.catalogue_size, source))
        if res.dropped:
            print("dropped (configured, not in catalogue): %s" % ", ".join(res.dropped))
        if res.aliases_absent:
            print("aliases absent from catalogue: %s" % ", ".join(res.aliases_absent))
        if res.degraded:
            print("DEGRADED: served from last-good cache; the catalogue was unreachable",
                  file=sys.stderr)

    if res.served is None:
        print("model_resolver: catalogue had %d ids but none matched the configured chain "
              "- NOTHING RESOLVED" % res.catalogue_size, file=sys.stderr)
        return EXIT_NO_MODEL
    return EXIT_DEGRADED if res.degraded else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
