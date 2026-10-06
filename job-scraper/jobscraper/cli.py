"""Command line entry point: `python -m jobscraper --help`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import output
from .scraper import Filters, run
from .sources import ALL_SOURCE_NAMES, build_sources
from .state import SeenStore

DEFAULT_CONFIG = {
    "boards": {"remoteok": True, "remotive": True, "arbeitnow": True, "hackernews": True},
    "companies": {},
}


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="jobscraper",
        description="Aggregate job openings from many job boards and company career pages.",
    )
    p.add_argument("-c", "--config", help="JSON config listing boards and companies (see sources.example.json)")
    p.add_argument("-k", "--keyword", action="append", default=[], help="keep jobs matching ANY keyword (repeatable)")
    p.add_argument("-x", "--exclude", action="append", default=[], help="drop jobs whose title contains this (repeatable)")
    p.add_argument("-l", "--location", action="append", default=[], help="keep jobs whose location contains this (repeatable; 'remote' also matches remote jobs)")
    p.add_argument("--remote", action="store_true", help="only remote jobs")
    p.add_argument("--days", type=float, help="only jobs posted in the last N days")
    p.add_argument("--title-only", action="store_true", help="match keywords against the title only")
    p.add_argument("-s", "--sources", help=f"comma-separated subset of sources to query: {','.join(ALL_SOURCE_NAMES)}")
    p.add_argument("-f", "--format", choices=output.FORMATS, default="table")
    p.add_argument("-o", "--output", help="write to this file instead of stdout")
    p.add_argument("-n", "--limit", type=int, help="show at most N jobs")
    p.add_argument("--new-only", action="store_true", help="only show jobs not seen in a previous --new-only run")
    p.add_argument("--state", default=".jobscraper-seen.json", help="file used by --new-only (default: %(default)s)")
    p.add_argument("--workers", type=int, default=8, help="parallel requests (default: %(default)s)")
    p.add_argument("-v", "--verbose", action="store_true", help="log per-source progress to stderr")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("urllib3").setLevel(logging.ERROR)  # retries are summarised per source instead

    config = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else dict(DEFAULT_CONFIG)
    # Adzuna codes can come from the environment so they never have to be written into a config file.
    az = dict(config.get("adzuna") or {})
    az.setdefault("app_id", os.environ.get("ADZUNA_APP_ID", ""))
    az.setdefault("app_key", os.environ.get("ADZUNA_APP_KEY", ""))
    config["adzuna"] = az
    only = {s.strip() for s in args.sources.split(",")} if args.sources else None
    if only and (unknown := only - set(ALL_SOURCE_NAMES)):
        print(f"unknown source(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    sources = build_sources(config, only)
    if not sources:
        print("no sources selected — check --sources and your config file", file=sys.stderr)
        return 2

    filters = Filters(
        keywords=args.keyword,
        exclude=args.exclude,
        locations=args.location,
        remote_only=args.remote,
        max_age_days=args.days,
        title_only=args.title_only,
    )
    result = run(sources, filters, workers=args.workers)
    jobs = result.jobs

    store = None
    if args.new_only:
        store = SeenStore(args.state)
        jobs = store.filter_new(jobs)
    if args.limit:
        jobs = jobs[: args.limit]

    text = output.render(jobs, args.format)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)

    if store:
        store.mark(jobs, still_listed=result.jobs)
        store.save()

    print(
        f"\n{len(jobs)} matching jobs (from {result.fetched} fetched across {len(sources)} sources"
        + (f", {len(result.errors)} failed" if result.errors else "")
        + ")",
        file=sys.stderr,
    )
    for label, err in result.errors.items():
        print(f"  ! {label}: {err}", file=sys.stderr)
    return 1 if result.errors and not result.fetched else 0
