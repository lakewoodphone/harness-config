#!/usr/bin/env python3
"""test_model_resolver.py - offline proof of the runtime model-resolution contract.

Runs with the stdlib only, no network, no gateway key:

  python3 scripts/frontier/test_model_resolver.py

Proves, each with an assertion:
  1. a configured id that the catalogue does NOT list is DROPPED (the exact failure that
     broke every live AI call for a week);
  2. a gateway route alias is PREFERRED over a configured concrete id;
  3. single-flight: 16 concurrent callers cause EXACTLY ONE fetch;
  4. fail-soft: an unreachable catalogue resolves from last-good disk cache, and the
     resolution is marked DEGRADED (not silent);
  5. a dead catalogue with NO cache raises, and the CLI exits 4 (it never guesses);
  6. the live path works end to end against a real local HTTP server.
"""

import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_resolver as mr  # noqa: E402

CATALOGUE = {
    "object": "list",
    "data": [{"id": "secretary-auto"}, {"id": "secretary-fast"}, {"id": "secretary-smart"},
             {"id": "ornith-1.0-397b"}],
}


class TestParse(unittest.TestCase):
    def test_openai_shape(self):
        self.assertIn("secretary-auto", mr.parse_catalogue(CATALOGUE))

    def test_plain_list_and_dict_of_keys(self):
        self.assertEqual(mr.parse_catalogue(["a", "b"]), {"a", "b"})
        self.assertEqual(mr.parse_catalogue({"m1": {}, "m2": {}}), {"m1", "m2"})


class TestResolve(unittest.TestCase):
    def test_unlisted_configured_id_is_dropped(self):
        ids = mr.parse_catalogue(CATALOGUE)
        r = mr.resolve(["secretary-auto"], ["ornith-1.0-397b", "ghost-model-2025"], ids)
        self.assertEqual(r.dropped, ["ghost-model-2025"])
        self.assertIn("ornith-1.0-397b", r.chain)

    def test_alias_is_preferred_over_concrete_id(self):
        ids = mr.parse_catalogue(CATALOGUE)
        r = mr.resolve(["secretary-fast", "secretary-auto"], ["ornith-1.0-397b"], ids)
        self.assertEqual(r.served, "secretary-fast")
        self.assertEqual(r.chain[0], "secretary-fast")

    def test_absent_alias_is_reported_not_silently_ignored(self):
        ids = mr.parse_catalogue(CATALOGUE)
        r = mr.resolve(["secretary-genius", "secretary-auto"], [], ids)
        self.assertEqual(r.aliases_absent, ["secretary-genius"])
        self.assertEqual(r.served, "secretary-auto")


class TestSingleFlight(unittest.TestCase):
    def test_concurrent_callers_cause_one_fetch(self):
        calls = {"n": 0}
        gate = threading.Event()

        def slow_fetch():
            calls["n"] += 1
            gate.wait(2.0)
            return set(mr.parse_catalogue(CATALOGUE))

        cache = mr.CatalogueCache(slow_fetch, ttl=60.0)
        results, errors = [], []

        def worker():
            try:
                ids, src = cache.get()
                results.append((len(ids), src))
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for t in threads:
            t.start()
        gate.set()
        for t in threads:
            t.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 16)
        self.assertEqual(cache.fetch_count, 1, "single-flight failed: %d fetches" % cache.fetch_count)
        self.assertEqual({r[0] for r in results}, {4})


class TestFailSoft(unittest.TestCase):
    def test_last_good_cache_is_used_and_marked_degraded(self):
        with tempfile.TemporaryDirectory() as d:
            cache_path = os.path.join(d, "cat.json")
            good = mr.CatalogueCache(lambda: set(mr.parse_catalogue(CATALOGUE)),
                                     ttl=0.0, path=Path(cache_path))
            ids, src = good.get()
            self.assertEqual(src, "live")

            def dead():
                raise mr.CatalogueUnavailable("connection refused")

            degraded = mr.CatalogueCache(dead, ttl=0.0, path=Path(cache_path))
            ids, src = degraded.get()
            self.assertEqual(src, "last-good")
            self.assertIn("secretary-auto", ids)

    def test_dead_catalogue_with_no_cache_raises(self):
        with tempfile.TemporaryDirectory() as d:
            def dead():
                raise mr.CatalogueUnavailable("connection refused")

            cache = mr.CatalogueCache(dead, ttl=0.0, path=Path(os.path.join(d, "none.json")))
            with self.assertRaises(mr.CatalogueUnavailable):
                cache.get()


class TestLiveHttp(unittest.TestCase):
    def test_end_to_end_against_local_server(self):
        payload = json.dumps(CATALOGUE).encode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/v1/models":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            fetcher = mr.default_fetcher("http://127.0.0.1:%d" % port, None, timeout=5.0)
            ids = fetcher()
            self.assertIn("secretary-smart", ids)
        finally:
            srv.shutdown()

    def test_http_error_is_not_swallowed(self):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_error(401)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(mr.CatalogueUnavailable):
                mr.default_fetcher("http://127.0.0.1:%d" % port, None, timeout=5.0)()
        finally:
            srv.shutdown()


class TestCliOutagePath(unittest.TestCase):
    """The unserved-catalogue path must be reachable from the CLI with NO config file.

    Before this test existed, `--config` was `required=True`, so the exact command the
    brief uses to prove "an AI outage is never silent" exited 2 (usage) and the loud
    exit-4 path was unreachable. A guard you cannot invoke is not a guard.
    """

    def test_no_config_flag_reaches_the_loud_outage_path(self):
        with tempfile.TemporaryDirectory() as d:
            rc = mr.main(["--base", "http://127.0.0.1:1", "--timeout", "1",
                          "--cache", os.path.join(d, "none.json"), "--json"])
        self.assertEqual(rc, mr.EXIT_NO_MODEL)

    def test_no_config_with_a_live_fixture_resolves_nothing_and_exits_4(self):
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as d:
            cat = os.path.join(d, "cat.json")
            Path(cat).write_text(json.dumps(CATALOGUE), "utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = mr.main(["--catalogue-file", cat, "--json"])
        self.assertEqual(rc, mr.EXIT_NO_MODEL)
        self.assertIn("NOTHING RESOLVED", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
