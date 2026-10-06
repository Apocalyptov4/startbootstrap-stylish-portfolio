"""Tests for ZIP/city lookup and job location placement (jobscraper/geo.py)."""

import unittest
from datetime import datetime, timezone

from jobscraper import geo
from jobscraper.models import Job
from jobscraper.scraper import add_coordinates, dedupe


class LookupTests(unittest.TestCase):
    def label(self, text):
        place = geo.lookup(text)
        return place.label if place else None

    def test_zip_codes(self):
        self.assertEqual(self.label("60614"), "60614")
        self.assertEqual(self.label("10001-1234"), "10001")
        self.assertIsNone(geo.lookup("99999"))  # not a real ZIP

    def test_city_forms(self):
        for text in ["Austin, TX", "austin texas", "Austin TX", "Austin, Texas"]:
            self.assertEqual(self.label(text), "Austin, TX", text)
        self.assertEqual(self.label("St. Louis, MO"), "Saint Louis, MO")
        self.assertEqual(self.label("West Chester, PA"), "West Chester, PA")
        self.assertEqual(self.label("NYC"), "New York, NY")
        self.assertEqual(self.label("Chicago"), "Chicago, IL")  # big city: state not needed

    def test_ambiguous_or_foreign_names_are_not_guessed(self):
        self.assertIsNone(geo.lookup("Springfield"))  # many small ones, no clear winner
        self.assertIsNone(geo.lookup("Paris"))
        self.assertIsNone(geo.lookup(""))


class LocateJobTests(unittest.TestCase):
    def label(self, text):
        place = geo.locate_job(text)
        return place.label if place else None

    def test_us_locations(self):
        cases = {
            "San Francisco, CA": "San Francisco, CA",
            "New York, NY, United States": "New York, NY",
            "Remote - New York, NY": "New York, NY",
            "Denver, CO (Hybrid)": "Denver, CO",
            "Seattle, WA; New York, NY": "Seattle, WA",
            "Mountain View, CA / Remote": "Mountain View, CA",
            "Chicago, IL 60601": "60601",
            "US-CA-San Jose": "San Jose, CA",
            "SF Bay Area": "San Francisco, CA",
            "San Francisco, California, USA": "San Francisco, CA",
        }
        for text, want in cases.items():
            self.assertEqual(self.label(text), want, text)

    def test_unplaceable_locations(self):
        for text in ["Remote - US", "Anywhere", "London, UK", "Berlin, Germany", "Toronto, Canada",
                     "Remote (Europe)", "London", "Dublin, Ireland", ""]:
            self.assertIsNone(geo.locate_job(text), text)

    def test_distance(self):
        nyc, chicago = geo.lookup("10001"), geo.lookup("60614")
        self.assertAlmostEqual(geo.miles_between(nyc.lat, nyc.lon, chicago.lat, chicago.lon), 712, delta=5)
        self.assertEqual(geo.miles_between(1, 2, 1, 2), 0)


class JobPlacementTests(unittest.TestCase):
    def job(self, title, location, company="Shop", **kw):
        return Job(source="t", source_id=title + location, title=title, company=company, url="u",
                   location=location, posted_at=datetime.now(timezone.utc), **kw)

    def test_add_coordinates_keeps_source_coordinates(self):
        a = self.job("Cashier", "Austin, TX")
        b = self.job("Cashier", "Somewhere", lat=1.0, lon=2.0)
        add_coordinates([a, b])
        self.assertAlmostEqual(a.lat, 30.307, places=2)
        self.assertEqual((b.lat, b.lon), (1.0, 2.0))

    def test_same_title_at_different_branches_is_kept(self):
        jobs = [self.job("Cashier", "Austin, TX"), self.job("Cashier", "Dallas, TX"),
                self.job("Cashier", "Austin, Texas")]  # same place written differently
        self.assertEqual(len(dedupe(jobs)), 2)


if __name__ == "__main__":
    unittest.main()
