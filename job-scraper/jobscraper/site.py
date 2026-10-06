"""Build the website version of Job Radar: a folder of static files any web host can serve.

    python -m jobscraper.site -c sources.json -o _site

It fetches every source once, writes the results to data.json and copies the
app's page next to it. On the website, saved/applied/hidden marks are kept in
each visitor's browser, and the job list is rebuilt on a schedule
(see .github/workflows/job-radar-website.yml).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import demo, geo
from .categories import CATEGORIES, add_categories
from .config import public_config, validate_config
from .http import Session
from .scraper import Filters, add_coordinates, carry_over, dedupe, run
from .server import WEB_DIR
from .sources import build_sources
from .state import SeenStore

MAX_JOBS = 25000          # keeps data.json a reasonable download on a phone
DESCRIPTION_CHARS = 300
STATIC_FLAG = '<script>window.JOB_RADAR_STATIC = true;</script>\n  <script src="app.js"></script>'


def build(config: dict, out_dir: Path, session=None, repo: str | None = None, use_demo: bool = False,
          adzuna_keys: tuple[str, str] | None = None, previous_jobs: list[dict] | None = None) -> dict:
    config = validate_config(config)
    if adzuna_keys:
        config["adzuna"]["app_id"], config["adzuna"]["app_key"] = adzuna_keys
    if use_demo:
        raw = demo.jobs()
        jobs, fetched, errors, labels = dedupe(raw), len(raw), {}, ["demo"]
        add_coordinates(jobs)
        add_categories(jobs)
    else:
        sources = build_sources(config)
        result = run(sources, Filters(), session=session)
        jobs, fetched, errors, labels = result.jobs, result.fetched, result.errors, [s.label for s in sources]

    payload = {
        "static": True,
        "demo": use_demo,
        "repo": repo,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetched": fetched,
        "errors": errors,
        "sources": labels,
        "config": public_config(config),  # never publish the Adzuna codes
        "categories": CATEGORIES,
        "jobs": [],
    }
    fresh = [_slim({**j.to_dict(), "key": SeenStore.key(j)}) for j in jobs]
    combined = carry_over(fresh, previous_jobs or [], config["areas"])
    combined.sort(key=lambda j: j.get("posted_at") or "", reverse=True)
    payload["jobs"] = combined[:MAX_JOBS]
    payload["carried_over"] = len(combined) - len(fresh)

    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("app.js", "style.css"):
        shutil.copy(WEB_DIR / name, out_dir / name)
    page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert '<script src="app.js"></script>' in page
    (out_dir / "index.html").write_text(page.replace('<script src="app.js"></script>', STATIC_FLAG), encoding="utf-8")
    (out_dir / "data.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    shutil.copy(geo.PLACES_FILE, out_dir / "places.json")
    return payload


def _slim(job: dict) -> dict:
    """Drop what the page doesn't use, to keep data.json small."""
    for field in ("uid", "source_id"):
        job.pop(field, None)
    job["description"] = (job.get("description") or "")[:DESCRIPTION_CHARS]
    for field in ("lat", "lon"):
        if job.get(field) is not None:
            job[field] = round(job[field], 3)
    return job


def fetch_previous(url: str) -> list[dict]:
    """Jobs from the currently published site, so recent area-search results carry over."""
    try:
        resp = Session(timeout=30).get(url)
        resp.raise_for_status()
        return resp.json().get("jobs") or []
    except Exception as e:  # first run, site down, ...: just start fresh
        print(f"(no previous job list: {type(e).__name__})", file=sys.stderr)
        return []


def default_site_url(repo: str | None) -> str | None:
    if not repo or "/" not in repo:
        return None
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m jobscraper.site", description=__doc__.split("\n")[0])
    p.add_argument("-c", "--config", required=True, help="JSON file listing job sites and companies")
    p.add_argument("-o", "--out", default="_site", help="output folder (default: %(default)s)")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/name, for the 'edit settings' link")
    p.add_argument("--demo", action="store_true", help="use made-up sample jobs")
    p.add_argument("--previous", help="URL of the published site, to carry over recent area-search jobs "
                                      "(default: this repository's GitHub Pages address)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    # The Adzuna codes come from the environment (GitHub secrets), never from the public sources.json.
    keys = (os.environ.get("ADZUNA_APP_ID", "").strip(), os.environ.get("ADZUNA_APP_KEY", "").strip())
    site_url = args.previous or default_site_url(args.repo)
    previous = fetch_previous(site_url.rstrip("/") + "/data.json") if site_url and not args.demo else []
    payload = build(json.loads(Path(args.config).read_text(encoding="utf-8")), Path(args.out), repo=args.repo,
                    use_demo=args.demo, adzuna_keys=keys if all(keys) else None, previous_jobs=previous)
    print(f"{len(payload['jobs'])} jobs from {len(payload['sources'])} sources written to {args.out}/"
          f" ({payload['carried_over']} kept from earlier runs)", file=sys.stderr)
    for label, err in payload["errors"].items():
        print(f"  ! {label}: {err}", file=sys.stderr)
    if not payload["jobs"]:
        # Don't replace a working website with an empty one.
        print("No jobs at all, so treating this as a failure.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
