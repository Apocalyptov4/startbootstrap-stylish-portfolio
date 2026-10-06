"""Tests for the Adzuna area search, settings handling and keeping the codes private."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobscraper import site
from jobscraper.categories import guess_category
from jobscraper.config import MAX_AREAS, public_config, validate_config, with_area
from jobscraper.scraper import Filters, carry_over, run, scrub
from jobscraper.server import Store
from jobscraper.sources import build_sources
from jobscraper.sources.adzuna import Adzuna, AdzunaError

from .test_jobscraper import FakeSession, RunTests

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
            summary = site.area_summary(payload)
            self.assertTrue(summary[0].startswith("area 60614 (10 mi): 4 jobs, 2 on the map"), summary[0])
            self.assertIn("Healthcare & Nursing 3", summary[1])


class KindOfJobTests(unittest.TestCase):
    def test_adzuna_category_is_kept_and_can_be_searched(self):
        session = FakeSession()
        src = Adzuna("08088", miles=50, category="healthcare-nursing-jobs", **KEYS)
        jobs = list(src.fetch(session))
        self.assertEqual(session.params[0]["category"], "healthcare-nursing-jobs")
        self.assertEqual(jobs[0].category, "healthcare-nursing-jobs")
        self.assertEqual(src.label, "adzuna:08088 (healthcare nursing)")

    def test_other_sources_get_a_guess_from_the_title(self):
        cases = {"Registered Nurse": "healthcare-nursing-jobs", "Retail Sales Associate": "retail-jobs",
                 "Forklift Operator": "logistics-warehouse-jobs", "Senior Backend Engineer": "it-jobs",
                 "Line Cook": "hospitality-catering-jobs", "Account Executive": "sales-jobs", "Chief of Staff": ""}
        for title, want in cases.items():
            self.assertEqual(guess_category(title), want, title)
        result = run(build_sources(RunTests.config), Filters(), session=FakeSession())
        by_title = {j.title: j.category for j in result.jobs}
        self.assertEqual(by_title["Frontend Developer"], "it-jobs")
        self.assertEqual(by_title["Account Executive"], "sales-jobs")

    def test_area_category_is_validated(self):
        cfg = validate_config({"areas": [{"where": "08088", "category": "retail-jobs"}, {"where": "08088"}]})
        self.assertEqual(cfg["areas"], [{"where": "08088", "miles": 25, "what": "", "category": "retail-jobs"},
                                        {"where": "08088", "miles": 25, "what": ""}])
        with self.assertRaises(ValueError):
            validate_config({"areas": [{"where": "08088", "category": "Bad Category!"}]})


class InstantSearchTests(unittest.TestCase):
    def test_with_area_replaces_same_search_and_keeps_home(self):
        cfg = {"areas": [{"where": "08088", "miles": 50, "what": ""}]}
        areas = with_area(cfg, {"where": "08088", "miles": 25, "what": ""})
        self.assertEqual(areas, [{"where": "08088", "miles": 25, "what": ""}])
        full = {"areas": [{"where": f"{10000 + i}", "miles": 10, "what": ""} for i in range(MAX_AREAS)]}
        areas = with_area(full, {"where": "19103", "miles": 5, "what": ""})
        self.assertEqual(len(areas), MAX_AREAS)
        self.assertEqual(areas[0]["where"], "10000")      # home kept
        self.assertEqual(areas[-1]["where"], "19103")     # newest last
        self.assertNotIn("10001", [a["where"] for a in areas])  # oldest other one dropped

    def test_search_adds_jobs_without_losing_others(self):
        with tempfile.TemporaryDirectory() as d:
            session = FakeSession()
            store = Store(Path(d), session=session)
            store.set_config({**RunTests.config, "adzuna": KEYS})
            before = store.refresh()
            self.assertEqual(len(before["jobs"]), 11)
            session.calls.clear()
            after = store.search({"where": "19103", "miles": 10, "category": "retail-jobs"})
            self.assertTrue(all("adzuna" in url for url in session.calls))  # only Adzuna was asked
            self.assertEqual(len(after["jobs"]), 14)                         # 11 kept + 3 found
            self.assertIn({"where": "19103", "miles": 10, "what": "", "category": "retail-jobs"}, after["config"]["areas"])
            self.assertIn("adzuna:19103 (retail)", after["sources"])
            self.assertNotIn("SECRETKEY99", json.dumps(after))

    def test_search_validation_and_demo(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d), session=FakeSession())
            with self.assertRaises(ValueError):
                store.search({"where": "<b>"})
            with self.assertRaisesRegex(ValueError, "demo"):
                Store(Path(d), demo_mode=True).search({"where": "08088"})


if __name__ == "__main__":
    unittest.main()
