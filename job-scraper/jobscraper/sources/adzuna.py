"""Adzuna (https://developer.adzuna.com): a job search engine that collects postings from
thousands of employers and job sites, searchable around a ZIP code or city.

Needs a free app ID and key. One source = one search area, for example
"within 25 miles of 60614", optionally narrowed by keywords.
"""

from __future__ import annotations

import threading
import time
from collections import deque

import requests

from ..geo import STATES
from ..models import Job, html_to_text, looks_remote, parse_datetime
from .base import Source

API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
PAGE_SIZE = 50
KM_PER_MILE = 1.609344
STATE_ABBREV = {name.title(): abbr for name, abbr in STATES.items()}


class _RateLimit:
    """Adzuna allows about 25 requests a minute; stay under it across all areas."""

    def __init__(self, calls: int = 20, per: float = 60.0):
        self.calls, self.per = calls, per
        self.sent: deque[float] = deque()
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            while self.sent and now - self.sent[0] > self.per:
                self.sent.popleft()
            if len(self.sent) >= self.calls:
                time.sleep(self.per - (now - self.sent[0]) + 0.1)
            self.sent.append(time.monotonic())


RATE_LIMIT = _RateLimit()


class AdzunaError(RuntimeError):
    pass


class Adzuna(Source):
    name = "adzuna"

    def __init__(self, where: str, miles: int = 25, what: str = "", app_id: str = "", app_key: str = "",
                 country: str = "us", max_pages: int = 10, max_days_old: int = 30, category: str = ""):
        self.where, self.miles, self.what, self.category = where, miles, what, category
        self.app_id, self.app_key = app_id, app_key
        self.country, self.max_pages, self.max_days_old = country, max_pages, max_days_old

    @property
    def label(self) -> str:
        detail = ", ".join(x for x in (self.category.replace("-jobs", "").replace("-", " "), self.what) if x)
        return f"adzuna:{self.where}" + (f" ({detail})" if detail else "")

    def fetch(self, session):
        if not (self.app_id and self.app_key):
            raise AdzunaError("Adzuna app ID and key are missing. Add them in Settings.")
        for page in range(1, self.max_pages + 1):
            RATE_LIMIT.wait()
            params = {
                "app_id": self.app_id,
                "app_key": self.app_key,
                "results_per_page": PAGE_SIZE,
                "where": self.where,
                "distance": round(self.miles * KM_PER_MILE),
                "sort_by": "date",
                "max_days_old": self.max_days_old,
            }
            if self.what:
                params["what"] = self.what
            if self.category:
                params["category"] = self.category  # e.g. "healthcare-nursing-jobs"
            try:
                resp = session.get(API.format(country=self.country, page=page), params=params)
            except requests.RequestException as e:
                # Never pass on the original message: it contains the request URL, including the key.
                raise AdzunaError(f"Couldn't reach Adzuna ({type(e).__name__}).") from None
            if resp.status_code in (401, 403):
                raise AdzunaError("Adzuna rejected the app ID or key. Check them in Settings.")
            if resp.status_code == 429:
                raise AdzunaError("Adzuna's free usage limit is used up for now. Try again later.")
            if resp.status_code >= 400:
                raise AdzunaError(f"Adzuna returned an error (HTTP {resp.status_code}).")
            data = resp.json()
            results = data.get("results") or []
            for j in results:
                yield self._job(j)
            if len(results) < PAGE_SIZE or page * PAGE_SIZE >= (data.get("count") or 0):
                break

    def _job(self, j: dict) -> Job:
        loc = j.get("location") or {}
        area = loc.get("area") or []
        # area is ["US", "Illinois", "Cook County", "Chicago"]; show "Chicago, IL"
        state = STATE_ABBREV.get(area[1], area[1]) if len(area) > 1 else ""
        city = area[-1] if len(area) > 2 else ""
        location = f"{city}, {state}" if city and state else (state or loc.get("display_name", ""))
        salary = ""
        lo, hi = j.get("salary_min"), j.get("salary_max")
        if lo and hi:
            salary = f"${lo:,.0f}" if round(lo) == round(hi) else f"${lo:,.0f} – ${hi:,.0f}"
            if str(j.get("salary_is_predicted")) == "1":
                salary = f"est. {salary}"
        title = html_to_text(j.get("title", ""), limit=200)
        description = html_to_text(j.get("description", ""))
        return Job(
            source=self.name,
            source_id=str(j.get("id")),
            title=title,
            company=((j.get("company") or {}).get("display_name") or "").strip(),
            url=j.get("redirect_url", ""),
            location=location,
            remote=looks_remote(title, location),
            posted_at=parse_datetime(j.get("created")),
            tags=[t for t in ((j.get("category") or {}).get("label"), _pretty(j.get("contract_time")),
                              _pretty(j.get("contract_type"))) if t],
            salary=salary,
            description=description,
            lat=j.get("latitude"),
            lon=j.get("longitude"),
            area=self.where,
            category=(j.get("category") or {}).get("tag") or "",
        )


def _pretty(value):
    return value.replace("_", " ").title() if value else ""


__all__ = ["Adzuna", "AdzunaError"]
