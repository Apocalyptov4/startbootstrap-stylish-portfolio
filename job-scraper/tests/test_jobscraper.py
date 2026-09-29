"""Offline tests: every HTTP call is served from tests/fixtures.

Run from the job-scraper directory:  python -m unittest -v
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from jobscraper import cli, output
from jobscraper.models import Job, html_to_text, parse_datetime
from jobscraper.scraper import Filters, dedupe, run
from jobscraper.sources import build_sources
from jobscraper.sources.ats import Ashby, Greenhouse, Lever
from jobscraper.sources.boards import Arbeitnow, HackerNewsHiring, Remotive, RemoteOK
from jobscraper.state import SeenStore

FIXTURES = Path(__file__).parent / "fixtures"

ROUTES = [
    ("https://boards-api.greenhouse.io/v1/boards/", "greenhouse.json"),
    ("https://api.lever.co/v0/postings/", "lever.json"),
    ("https://api.ashbyhq.com/posting-api/job-board/", "ashby.json"),
    ("https://remoteok.com/api", "remoteok.json"),
    ("https://remotive.com/api/remote-jobs", "remotive.json"),
    ("https://www.arbeitnow.com/api/job-board-api?page=2", "arbeitnow_p2.json"),
    ("https://www.arbeitnow.com/api/job-board-api", "arbeitnow_p1.json"),
    ("https://hn.algolia.com/api/v1/search_by_date", "hn_search.json"),
    ("https://hn.algolia.com/api/v1/items/", "hn_item.json"),
]


class FakeSession:
    def __init__(self, fail=()):
        self.fail = fail
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append(url)
        if any(f in url for f in self.fail):
            raise ConnectionError(f"boom: {url}")
        for prefix, name in ROUTES:
            if url.startswith(prefix):
                return json.loads((FIXTURES / name).read_text())
        raise AssertionError(f"unexpected URL {url}")


def fetch(source, **kw):
    return list(source.fetch(FakeSession(**kw)))


class SourceParsingTests(unittest.TestCase):
    def test_greenhouse(self):
        jobs = fetch(Greenhouse("acme"))
        self.assertEqual(len(jobs), 2)
        j = jobs[0]
        self.assertEqual((j.title, j.company, j.source_id), ("Senior Backend Engineer (Python)", "Acme", "101"))
        self.assertTrue(j.remote)
        self.assertEqual(j.posted_at, datetime(2026, 9, 25, 14, tzinfo=timezone.utc))
        self.assertEqual(j.description, "We use Python & Postgres.")
        self.assertFalse(jobs[1].remote)

    def test_lever(self):
        a, b = fetch(Lever("globex", "Globex"))
        self.assertEqual(a.company, "Globex")
        self.assertEqual(a.location, "Berlin, Germany")
        self.assertFalse(a.remote)
        self.assertEqual(a.salary, "EUR 70,000-90,000 per-year-salary")
        self.assertIn("Full-time", a.tags)
        self.assertTrue(b.remote)
        self.assertEqual(b.location, "Anywhere")

    def test_ashby_skips_unlisted(self):
        jobs = fetch(Ashby("initech"))
        self.assertEqual([j.title for j in jobs], ["Machine Learning Engineer"])
        self.assertEqual(jobs[0].salary, "$200K – $260K")
        self.assertEqual(jobs[0].company, "Initech")

    def test_remoteok_skips_legal_notice(self):
        jobs = fetch(RemoteOK())
        self.assertEqual(len(jobs), 2)
        self.assertTrue(all(j.remote for j in jobs))
        self.assertEqual(jobs[0].salary, "USD 120,000-160,000")

    def test_remotive(self):
        (j,) = fetch(Remotive())
        self.assertEqual((j.company, j.location), ("Umbrella", "Europe"))
        self.assertEqual(j.posted_at.tzinfo, timezone.utc)

    def test_arbeitnow_follows_pagination(self):
        session = FakeSession()
        jobs = list(Arbeitnow(max_pages=5).fetch(session))
        self.assertEqual([j.title for j in jobs], ["Java Developer", "JavaScript Engineer"])
        self.assertEqual(len(session.calls), 2)

    def test_arbeitnow_respects_max_pages(self):
        self.assertEqual(len(fetch(Arbeitnow(max_pages=1))), 1)

    def test_hackernews_parses_first_line(self):
        a, b = fetch(HackerNewsHiring())
        self.assertEqual((a.company, a.title, a.location), ("Initech", "Senior Rust Engineer", "Remote (US)"))
        self.assertTrue(a.remote)
        self.assertEqual(a.url, "https://news.ycombinator.com/item?id=5001")
        self.assertEqual((b.company, b.title, b.location), ("Vandelay Industries", "Product Designer", "London, UK"))
        self.assertFalse(b.remote)


def job(title="Engineer", company="Co", **kw):
    kw.setdefault("posted_at", datetime.now(timezone.utc))
    return Job(source=kw.pop("source", "t"), source_id=kw.pop("source_id", title), title=title,
               company=company, url="u", **kw)


class FilterTests(unittest.TestCase):
    def test_keywords_are_whole_word(self):
        f = Filters(keywords=["java", "go"], title_only=True)
        self.assertTrue(f.matches(job("Java Developer")))
        self.assertFalse(f.matches(job("JavaScript Engineer")))
        self.assertFalse(f.matches(job("Google Ads Specialist")))
        self.assertTrue(f.matches(job("Go / Rust Engineer")))

    def test_symbols_in_keywords(self):
        f = Filters(keywords=["c++", "c#"], title_only=True)
        self.assertTrue(f.matches(job("C++ Developer")))
        self.assertTrue(f.matches(job("Senior C# Engineer")))
        self.assertFalse(f.matches(job("C Developer")))

    def test_keywords_search_tags_and_description(self):
        f = Filters(keywords=["kubernetes"])
        self.assertTrue(f.matches(job("SRE", description="We run Kubernetes")))
        self.assertTrue(f.matches(job("SRE", tags=["kubernetes"])))
        self.assertFalse(Filters(keywords=["kubernetes"], title_only=True).matches(job("SRE", tags=["kubernetes"])))

    def test_exclude(self):
        f = Filters(exclude=["senior", "staff"])
        self.assertFalse(f.matches(job("Senior Engineer")))
        self.assertTrue(f.matches(job("Engineer")))

    def test_location_and_remote(self):
        f = Filters(locations=["berlin", "remote"])
        self.assertTrue(f.matches(job(location="Berlin, DE")))
        self.assertTrue(f.matches(job(location="Anywhere", remote=True)))
        self.assertFalse(f.matches(job(location="Paris")))
        self.assertFalse(Filters(remote_only=True).matches(job(location="Paris")))

    def test_max_age(self):
        f = Filters(max_age_days=7)
        old = datetime.now(timezone.utc) - timedelta(days=30)
        self.assertFalse(f.matches(job(posted_at=old)))
        self.assertTrue(f.matches(job()))
        self.assertTrue(f.matches(job(posted_at=None)))  # unknown date is kept

    def test_dedupe_prefers_newest(self):
        now = datetime.now(timezone.utc)
        a = job("Backend Engineer", "Acme Inc", source="x", posted_at=now - timedelta(days=3))
        b = job("backend engineer!", "ACME inc", source="y", posted_at=now)
        c = job("Frontend Engineer", "Acme Inc")
        kept = dedupe([a, b, c])
        self.assertEqual(len(kept), 2)
        self.assertIn(b, kept)


class RunTests(unittest.TestCase):
    config = {
        "boards": {"remoteok": True, "remotive": True, "arbeitnow": {"max_pages": 2}, "hackernews": True},
        "companies": {"greenhouse": ["acme"], "lever": [{"slug": "globex", "name": "Globex"}], "ashby": ["initech"]},
    }

    def test_build_sources(self):
        labels = sorted(s.label for s in build_sources(self.config))
        self.assertEqual(labels, ["arbeitnow", "ashby:initech", "greenhouse:acme", "hackernews",
                                  "lever:globex", "remoteok", "remotive"])
        self.assertEqual([s.label for s in build_sources(self.config, {"lever"})], ["lever:globex"])
        with self.assertRaises(ValueError):
            build_sources({"boards": {"monster": True}})

    def test_run_merges_dedupes_and_sorts(self):
        result = run(build_sources(self.config), Filters(), session=FakeSession(), workers=4)
        self.assertEqual(result.errors, {})
        self.assertEqual(result.fetched, 12)
        # "Senior Backend Engineer (Python)" at Acme appears on Greenhouse and RemoteOK
        self.assertEqual(len(result.jobs), 11)
        dates = [j.posted_at for j in result.jobs if j.posted_at]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_one_failing_source_does_not_abort(self):
        result = run(build_sources(self.config), Filters(), session=FakeSession(fail=["remotive"]))
        self.assertIn("remotive", result.errors)
        self.assertEqual(result.fetched, 11)


class OutputTests(unittest.TestCase):
    jobs = [job("Dev | Ops <b>", "A&B", location="Remote", tags=["x"])]

    def test_all_formats_render(self):
        for fmt in output.FORMATS:
            self.assertIn("Dev", output.render(self.jobs, fmt), fmt)

    def test_escaping(self):
        self.assertIn("Dev \\| Ops", output.to_markdown(self.jobs))
        html = output.to_html(self.jobs)
        self.assertIn("&lt;b&gt;", html)
        self.assertIn("A&amp;B", html)
        self.assertEqual(json.loads(output.to_json(self.jobs))[0]["company"], "A&B")


class StateTests(unittest.TestCase):
    def test_new_only_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "seen.json"
            a, b = job("A"), job("B")
            store = SeenStore(path)
            self.assertEqual(store.filter_new([a]), [a])
            store.mark([a])
            store.save()
            store = SeenStore(path)
            self.assertEqual(store.filter_new([a, b]), [b])
            # the same role found on a different board is not "new"
            self.assertEqual(store.filter_new([job("A", source="other", source_id="zzz")]), [])


class CliTests(unittest.TestCase):
    def test_end_to_end_with_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "cfg.json"
            cfg.write_text(json.dumps(RunTests.config))
            out_file = Path(d) / "jobs.csv"
            with mock.patch("jobscraper.scraper.Session", FakeSession), redirect_stderr(io.StringIO()) as err:
                code = cli.main(["-c", str(cfg), "-k", "python", "-k", "rust", "--remote", "-f", "csv", "-o", str(out_file)])
            self.assertEqual(code, 0)
            rows = out_file.read_text().splitlines()
            self.assertEqual(rows[0].split(",")[:3], ["posted_at", "title", "company"])
            titles = "\n".join(rows[1:])
            self.assertIn("Senior Rust Engineer", titles)
            self.assertIn("Senior Backend Engineer (Python)", titles)
            self.assertNotIn("Machine Learning", titles)  # not remote
            self.assertIn("matching jobs", err.getvalue())

    def test_unknown_source(self):
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["-s", "monster"]), 2)


class HelperTests(unittest.TestCase):
    def test_parse_datetime(self):
        expected = datetime(2025, 9, 27, 19, 6, 40, tzinfo=timezone.utc)
        self.assertEqual(parse_datetime(1759000000), expected)
        self.assertEqual(parse_datetime(1759000000000), expected)
        self.assertEqual(parse_datetime("1759000000"), expected)
        self.assertEqual(parse_datetime("2025-09-27T19:06:40Z"), expected)
        self.assertIsNone(parse_datetime("not a date"))
        self.assertIsNone(parse_datetime(None))

    def test_html_to_text(self):
        self.assertEqual(html_to_text("<p>a &amp; b</p><p>c</p>"), "a & b\nc")


if __name__ == "__main__":
    unittest.main()
