"""Tests for the Adzuna area search, settings handling and keeping the codes private."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobscraper import site
from jobscraper.config import public_config, validate_config
from jobscraper.scraper import Filters, carry_over, run, scrub
from jobscraper.server import Store
from jobscraper.sources import build_sources
from jobscraper.sources.adzuna import Adzuna, AdzunaError

from .test_jobscraper import FakeSession

KEYS = {"app_id": "abc123", "app_key": "SECRETKEY99"}
CONFIG = {"boards": {}, "areas": [{"where": "60614", "miles": 10, "what": "nurse"}], "adzuna": {**KEYS, "max_pages": 3}}


class AdzunaSourceTests(unittest.TestCase):
    def fetch(self, **kw):
        session = FakeSession(**kw.pop("session_kw", {}))
        src = Adzuna("60614", miles=10, what="nurse", **{**KEYS, **kw})
        return list(src.fetch(session)), session

    def test_parses_jobs(self):
        jobs, session = self.fetch()
        nurse, cashier, warehouse = jobs
        self.assertEqual(nurse.title, "Registered Nurse - Night Shift")  # highlight tags removed
        self.assertEqual((nurse.company, nurse.location), ("Northside Clinic", "Chicago, IL"))
        self.assertEqual((nurse.lat, nurse.lon, nurse.area), (41.92, -87.65, "60614"))
        self.assertEqual(nurse.salary, "$70,000 – $90,000")
        self.assertEqual(cashier.salary, "est. $31,000")  # Adzuna's own estimate is labelled
        self.assertEqual(warehouse.location, "IL")
        self.assertIn("Healthcare & Nursing Jobs", nurse.tags)
        self.assertEqual(nurse.description, "We are hiring a caring team member & more...")

    def test_request_parameters(self):
        _, session = self.fetch()
        p = session.params[0]
        self.assertEqual((p["where"], p["what"], p["distance"], p["sort_by"]), ("60614", "nurse", 16, "date"))
        self.assertEqual(len(session.calls), 1)  # 3 results < page size: no second page

    def test_missing_or_rejected_codes(self):
        with self.assertRaisesRegex(AdzunaError, "missing"):
            list(Adzuna("60614").fetch(FakeSession()))
        with self.assertRaisesRegex(AdzunaError, "rejected"):
            self.fetch(session_kw={"status": {"adzuna": 401}})
        with self.assertRaisesRegex(AdzunaError, "limit"):
            self.fetch(session_kw={"status": {"adzuna": 429}})

    def test_errors_never_contain_the_key(self):
        result = run(build_sources(CONFIG), Filters(), session=FakeSession(fail=["adzuna"]))
        message = result.errors["adzuna:60614 (nurse)"]
        self.assertIn("Couldn't reach Adzuna", message)
        self.assertNotIn("SECRETKEY99", message)

    def test_scrub(self):
        self.assertEqual(scrub("x?app_id=a1&app_key=k2&where=1"), "x?app_id=***&app_key=***&where=1")


class SettingsTests(unittest.TestCase):
    def test_areas_are_validated(self):
        cfg = validate_config({"areas": [{"where": " 60614 ", "miles": "10"}, {"where": "60614"},
                                         {"where": "Austin, TX", "what": "cashier"}]})
        self.assertEqual(cfg["areas"], [{"where": "60614", "miles": 10, "what": ""},
                                        {"where": "Austin, TX", "miles": 25, "what": "cashier"}])
        for bad in [{"where": ""}, {"where": "<script>"}, {"where": "60614", "miles": 900}, {"where": "x", "what": "a<b"}]:
            with self.assertRaises(ValueError, msg=bad):
                validate_config({"areas": [bad]})

    def test_blank_codes_keep_saved_ones_and_are_never_shown(self):
        saved = validate_config(CONFIG)
        again = validate_config({**CONFIG, "adzuna": {"app_id": "", "app_key": ""}}, previous=saved)
        self.assertEqual((again["adzuna"]["app_id"], again["adzuna"]["app_key"]), ("abc123", "SECRETKEY99"))
        shown = public_config(again)
        self.assertEqual(shown["adzuna"], {"max_pages": 3, "has_keys": True})
        self.assertNotIn("SECRETKEY99", json.dumps(shown))
        with self.assertRaises(ValueError):
            validate_config({"adzuna": {"app_key": "not a key!"}})

    def test_app_never_sends_the_key_to_the_page(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d), session=FakeSession())
            shown = store.set_config(CONFIG)
            self.assertTrue(shown["adzuna"]["has_keys"])
            state = store.refresh()
            self.assertNotIn("SECRETKEY99", json.dumps(state))
            self.assertEqual(len(state["jobs"]), 3)
            # the key is still saved locally for the next refresh
            self.assertIn("SECRETKEY99", (Path(d) / "config.json").read_text(encoding="utf-8"))


class CarryOverTests(unittest.TestCase):
    def test_keeps_recent_jobs_from_searched_areas(self):
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        recent, old = (now - timedelta(days=2)).isoformat(), (now - timedelta(days=40)).isoformat()
        prev = [
            {"key": "a", "source": "adzuna", "area": "60614", "posted_at": recent},  # kept
            {"key": "b", "source": "adzuna", "area": "60614", "posted_at": old},     # too old
            {"key": "c", "source": "adzuna", "area": "10001", "posted_at": recent},  # area removed
            {"key": "d", "source": "lever", "area": "", "posted_at": recent},        # not an area search
            {"key": "e", "source": "adzuna", "area": "60614", "posted_at": recent},  # in the new run already
        ]
        new = [{"key": "e", "source": "adzuna", "area": "60614", "posted_at": recent}]
        out = carry_over(new, prev, [{"where": "60614"}], now=now)
        self.assertEqual([j["key"] for j in out], ["e", "a"])

    def test_website_never_publishes_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            public = {"boards": {}, "areas": CONFIG["areas"], "adzuna": {"max_pages": 3}}
            prev = [{"key": "old", "source": "adzuna", "area": "60614", "title": "Old",
                     "posted_at": datetime.now(timezone.utc).isoformat()}]
            payload = site.build(public, Path(d), session=FakeSession(), adzuna_keys=("abc123", "SECRETKEY99"),
                                 previous_jobs=prev)
            text = (Path(d) / "data.json").read_text(encoding="utf-8")
            self.assertNotIn("SECRETKEY99", text)
            self.assertNotIn("abc123", text)
            self.assertEqual(payload["carried_over"], 1)
            self.assertEqual(len(payload["jobs"]), 4)
            self.assertTrue(all("uid" not in j for j in payload["jobs"]))


if __name__ == "__main__":
    unittest.main()
