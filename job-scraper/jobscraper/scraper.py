"""Fetch every source in parallel, then filter, de-duplicate and sort."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from . import geo
from .categories import add_categories
from .http import Session
from .models import Job
from .sources import Source

log = logging.getLogger("jobscraper")


@dataclass
class Filters:
    keywords: list[str] = field(default_factory=list)   # match ANY (title/company/tags/description)
    exclude: list[str] = field(default_factory=list)    # drop if ANY appears in title
    locations: list[str] = field(default_factory=list)  # match ANY, substring of location
    remote_only: bool = False
    max_age_days: float | None = None
    title_only: bool = False                            # keywords only match the title

    def __post_init__(self):
        self._kw = [_word_re(k) for k in self.keywords]
        self._ex = [_word_re(k) for k in self.exclude]

    def matches(self, job: Job, now: datetime | None = None) -> bool:
        if self.remote_only and not job.remote:
            return False
        if self.locations:
            loc = job.location.lower()
            if not any(l.lower() in loc for l in self.locations) and not (
                job.remote and any(l.lower() == "remote" for l in self.locations)
            ):
                return False
        if self.max_age_days is not None and job.posted_at:
            now = now or datetime.now(timezone.utc)
            if job.posted_at < now - timedelta(days=self.max_age_days):
                return False
        if self._ex and any(r.search(job.title) for r in self._ex):
            return False
        if self._kw:
            hay = job.title if self.title_only else " ".join(
                [job.title, job.company, " ".join(job.tags), job.description]
            )
            if not any(r.search(hay) for r in self._kw):
                return False
        return True


def _word_re(term: str) -> re.Pattern:
    # Whole-word-ish match so "go" doesn't hit "Google" and "java" doesn't hit "javascript".
    return re.compile(rf"(?<![\w+#]){re.escape(term.strip())}(?![\w+#])", re.I)


@dataclass
class RunResult:
    jobs: list[Job]
    fetched: int
    errors: dict[str, str]


def fetch_all(sources: Iterable[Source], session: Session | None = None, workers: int = 8) -> tuple[list[Job], dict[str, str]]:
    session = session or Session()
    jobs: list[Job] = []
    errors: dict[str, str] = {}
    sources = list(sources)

    def fetch_one(src: Source) -> list[Job]:
        return list(src.fetch(session))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch_one, s): s for s in sources}
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                got = fut.result()
                log.info("%-28s %4d jobs", src.label, len(got))
                jobs.extend(got)
            except Exception as e:  # one broken board must not kill the whole run
                errors[src.label] = scrub(f"{type(e).__name__}: {e}")
                log.warning("%-28s FAILED (%s)", src.label, errors[src.label])
    return jobs, errors


_SECRET_RE = re.compile(r"((?:app_)?(?:id|key|token|secret)=)[^&\s'\")]+", re.I)


def scrub(message: str) -> str:
    """Blank out anything that looks like a credential in a URL query string."""
    return _SECRET_RE.sub(r"\1***", message)


def dedupe(jobs: Iterable[Job]) -> list[Job]:
    """Keep one job per (company, title); prefer the most recently posted copy."""
    best: dict[tuple[str, str], Job] = {}
    for j in jobs:
        key = j.dedup_key
        cur = best.get(key)
        if cur is None or _ts(j) > _ts(cur):
            best[key] = j
    return list(best.values())


def _ts(job: Job) -> float:
    return job.posted_at.timestamp() if job.posted_at else 0.0


def add_coordinates(jobs: Iterable[Job]) -> None:
    """Place jobs on the map from their location text, unless the source already did."""
    for j in jobs:
        if j.lat is None and (place := geo.locate_job(j.location)):
            j.lat, j.lon = place.lat, place.lon


CARRY_OVER_DAYS = 21


def carry_over(new: list[dict], old: list[dict], areas: list[dict], max_age_days: float = CARRY_OVER_DAYS,
               now: datetime | None = None) -> list[dict]:
    """Add area-search jobs from an earlier run that this run didn't return again.

    Area searches only fetch the newest few hundred postings each time, so older
    ones would otherwise drop off. Kept only while their area is still searched
    and they are under `max_age_days` old. Returns `new` followed by the kept jobs.
    """
    wanted = {a["where"].lower() for a in areas}
    have = {j["key"] for j in new}
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=max_age_days)).isoformat()
    kept = [
        dict(j) for j in old
        if j.get("source") == "adzuna"
        and (j.get("area") or "").lower() in wanted
        and j.get("key") not in have
        and (j.get("posted_at") or "") >= cutoff
    ]
    return new + kept


def run(sources: Iterable[Source], filters: Filters, session: Session | None = None, workers: int = 8) -> RunResult:
    raw, errors = fetch_all(sources, session=session, workers=workers)
    now = datetime.now(timezone.utc)
    kept = [j for j in dedupe(raw) if filters.matches(j, now)]
    add_coordinates(kept)
    add_categories(kept)
    kept.sort(key=_ts, reverse=True)
    return RunResult(jobs=kept, fetched=len(raw), errors=errors)
