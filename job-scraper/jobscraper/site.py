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

from . import demo
from .scraper import Filters, dedupe, run
from .server import WEB_DIR, validate_config
from .sources import build_sources
from .state import SeenStore

STATIC_FLAG = '<script>window.JOB_RADAR_STATIC = true;</script>\n  <script src="app.js"></script>'


def build(config: dict, out_dir: Path, session=None, repo: str | None = None, use_demo: bool = False) -> dict:
    config = validate_config(config)
    if use_demo:
        raw = demo.jobs()
        jobs, fetched, errors, labels = dedupe(raw), len(raw), {}, ["demo"]
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
        "config": config,
        "jobs": [{**j.to_dict(), "key": SeenStore.key(j)} for j in jobs],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("app.js", "style.css"):
        shutil.copy(WEB_DIR / name, out_dir / name)
    page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert '<script src="app.js"></script>' in page
    (out_dir / "index.html").write_text(page.replace('<script src="app.js"></script>', STATIC_FLAG), encoding="utf-8")
    (out_dir / "data.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return payload


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m jobscraper.site", description=__doc__.split("\n")[0])
    p.add_argument("-c", "--config", required=True, help="JSON file listing job sites and companies")
    p.add_argument("-o", "--out", default="_site", help="output folder (default: %(default)s)")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/name, for the 'edit settings' link")
    p.add_argument("--demo", action="store_true", help="use made-up sample jobs")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    payload = build(json.loads(Path(args.config).read_text(encoding="utf-8")), Path(args.out), repo=args.repo, use_demo=args.demo)
    print(f"{len(payload['jobs'])} jobs from {len(payload['sources'])} sources written to {args.out}/", file=sys.stderr)
    for label, err in payload["errors"].items():
        print(f"  ! {label}: {err}", file=sys.stderr)
    if not payload["jobs"]:
        # Don't replace a working website with an empty one.
        print("No jobs at all, so treating this as a failure.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
