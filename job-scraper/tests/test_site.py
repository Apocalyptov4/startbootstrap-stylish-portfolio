"""Tests for the static website build (jobscraper/site.py)."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from jobscraper import site

from .test_jobscraper import FakeSession, RunTests


class SiteBuildTests(unittest.TestCase):
    def test_build_writes_page_and_data(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "site"
            payload = site.build(RunTests.config, out, session=FakeSession(), repo="me/repo")
            self.assertEqual(sorted(p.name for p in out.iterdir()), [".nojekyll", "app.js", "data.json", "index.html", "places.json", "style.css"])
            self.assertIn("window.JOB_RADAR_STATIC = true", (out / "index.html").read_text(encoding="utf-8"))
            data = json.loads((out / "data.json").read_text(encoding="utf-8"))
            self.assertEqual(data, payload)
            self.assertTrue(data["static"])
            self.assertEqual(data["repo"], "me/repo")
            self.assertEqual(len(data["jobs"]), 11)
            self.assertTrue(all(j["key"] for j in data["jobs"]))

    def test_cli_fails_when_nothing_was_fetched(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "cfg.json"
            cfg.write_text(json.dumps({"boards": {"remotive": True}}), encoding="utf-8")
            with mock.patch("jobscraper.scraper.Session", lambda: FakeSession(fail=["remotive"])), redirect_stderr(io.StringIO()):
                self.assertEqual(site.main(["-c", str(cfg), "-o", str(Path(d) / "out")]), 1)
            with mock.patch("jobscraper.scraper.Session", FakeSession), redirect_stderr(io.StringIO()):
                self.assertEqual(site.main(["-c", str(cfg), "-o", str(Path(d) / "out")]), 0)

    def test_repository_config_is_valid(self):
        cfg = json.loads((Path(__file__).parents[1] / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(site.validate_config(cfg)["boards"], cfg["boards"])


if __name__ == "__main__":
    unittest.main()
