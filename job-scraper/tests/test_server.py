"""Tests for the web app's HTTP API, using the offline fixtures from test_jobscraper."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from jobscraper.server import Store, make_server, validate_config

from .test_jobscraper import FakeSession, RunTests

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # talk to localhost directly


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name), session=FakeSession())
        self.store.set_config(RunTests.config)
        self.server = make_server(self.store, port=0)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, path, body=None, method=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method or ("POST" if data else "GET"))
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with opener.open(req, timeout=10) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if "json" in r.headers["Content-Type"] else raw.decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_serves_the_page_and_assets(self):
        for path, needle in [("/", "<title>Job Radar</title>"), ("/app.js", "function render"), ("/style.css", ":root")]:
            status, body = self.call(path)
            self.assertEqual(status, 200)
            self.assertIn(needle, body)
        status, places = self.call("/places.json")
        self.assertEqual(status, 200)
        self.assertEqual(places["zips"]["60614"], [41.922, -87.649, "Chicago, IL"])
        self.assertEqual(self.call("/nope")[0], 404)

    def test_refresh_then_state(self):
        status, state = self.call("/api/state")
        self.assertEqual((status, state["jobs"], state["fetched_at"]), (200, [], None))

        status, state = self.call("/api/refresh", {})
        self.assertEqual(status, 200)
        self.assertEqual(len(state["jobs"]), 11)
        self.assertEqual(state["errors"], {})
        self.assertFalse(any(j["is_new"] for j in state["jobs"]))  # first refresh: nothing is "new"
        self.assertTrue(all(j["key"] for j in state["jobs"]))

        # results survive a restart
        again = Store(Path(self.tmp.name)).state()
        self.assertEqual(len(again["jobs"]), 11)

    def test_new_jobs_are_flagged_on_later_refreshes(self):
        self.call("/api/refresh", {})
        # pretend one job was never seen before
        key = next(iter(self.store.tracking))
        del self.store.tracking[key]
        _, state = self.call("/api/refresh", {})
        self.assertEqual([j["key"] for j in state["jobs"] if j["is_new"]], [key])

    def test_status_roundtrip(self):
        _, state = self.call("/api/refresh", {})
        key = state["jobs"][0]["key"]
        self.assertEqual(self.call("/api/status", {"key": key, "status": "saved"})[0], 200)
        _, state = self.call("/api/state")
        self.assertEqual(state["jobs"][0]["status"], "saved")
        self.call("/api/status", {"key": key, "status": None})
        _, state = self.call("/api/state")
        self.assertIsNone(state["jobs"][0]["status"])
        self.assertEqual(self.call("/api/status", {"key": key, "status": "bogus"})[0], 400)

    def test_config_validation(self):
        status, cfg = self.call("/api/config", {"boards": {"remotive": True}, "companies": {"lever": ["spotify", "Spotify", {"slug": "plaid", "name": "Plaid"}]}}, "PUT")
        self.assertEqual(status, 200)
        self.assertEqual(cfg["boards"], {"remoteok": False, "remotive": True, "arbeitnow": False, "hackernews": False})
        self.assertEqual(cfg["companies"]["lever"], ["spotify", {"slug": "plaid", "name": "Plaid"}])
        status, err = self.call("/api/config", {"companies": {"lever": ["../../etc"]}}, "PUT")
        self.assertEqual(status, 400)
        self.assertIn("not a valid", err["error"])

    def test_search_route(self):
        self.store.set_config({**RunTests.config, "adzuna": {"app_id": "abc", "app_key": "def"}})
        status, state = self.call("/api/search", {"where": "08088", "miles": 50, "category": ""})
        self.assertEqual(status, 200)
        self.assertEqual(len(state["jobs"]), 3)
        self.assertIn("categories", state)
        self.assertEqual(self.call("/api/search", {"where": ""})[0], 400)

    def test_rejects_cross_site_writes(self):
        status, _ = self.call("/api/refresh", {}, headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        req = urllib.request.Request(self.base + "/api/refresh", data=b"{}", method="POST")
        req.add_header("Content-Type", "text/plain")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            opener.open(req, timeout=10)
        self.assertEqual(ctx.exception.code, 415)

    def test_failed_sources_are_reported(self):
        self.store.session = FakeSession(fail=["remotive", "lever"])
        _, state = self.call("/api/refresh", {})
        self.assertEqual(sorted(state["errors"]), ["lever:globex", "remotive"])
        self.assertEqual(len(state["jobs"]), 8)


class PageScriptTests(unittest.TestCase):
    def test_every_event_handler_exists(self):
        """Catches a handler being renamed or deleted, which a syntax check doesn't."""
        import re
        from jobscraper.server import WEB_DIR

        js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        handlers = set(re.findall(r'addEventListener\("\w+", (\w+)\)', js))
        self.assertIn("searchHere", handlers)
        for name in handlers:
            self.assertRegex(js, rf"(async )?function {name}\(", name)


class DemoTests(unittest.TestCase):
    def test_demo_mode_has_unique_jobs(self):
        with tempfile.TemporaryDirectory() as d:
            state = Store(Path(d), demo_mode=True).refresh()
            keys = [j["key"] for j in state["jobs"]]
            self.assertTrue(state["demo"])
            self.assertGreater(len(keys), 30)
            self.assertEqual(len(keys), len(set(keys)))
            self.assertTrue((Path(d) / "demo" / "jobs.json").exists())


class ValidateConfigTests(unittest.TestCase):
    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            validate_config([])


if __name__ == "__main__":
    unittest.main()
