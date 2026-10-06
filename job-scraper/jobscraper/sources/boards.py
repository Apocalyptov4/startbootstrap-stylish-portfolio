"""Public job boards that aggregate many companies."""

from __future__ import annotations

import re

from ..models import Job, html_to_text, looks_remote, parse_datetime
from .base import Source


class RemoteOK(Source):
    """https://remoteok.com/api — their terms ask you to link back to RemoteOK when showing jobs."""

    name = "remoteok"

    def fetch(self, session):
        data = session.get_json("https://remoteok.com/api")
        for j in data:
            if "legal" in j or not j.get("id"):  # first element is a legal notice
                continue
            salary = ""
            if j.get("salary_min") and j.get("salary_max"):
                salary = f"USD {int(j['salary_min']):,}-{int(j['salary_max']):,}"
            yield Job(
                source=self.name,
                source_id=str(j["id"]),
                title=(j.get("position") or "").strip(),
                company=(j.get("company") or "").strip(),
                url=j.get("url") or j.get("apply_url", ""),
                location=j.get("location") or "Remote",
                remote=True,
                posted_at=parse_datetime(j.get("epoch") or j.get("date")),
                tags=list(j.get("tags") or []),
                salary=salary,
                description=html_to_text(j.get("description", "")),
            )


class Remotive(Source):
    """https://remotive.com/api/remote-jobs — asks for a link back and no more than ~4 calls/day."""

    name = "remotive"

    def fetch(self, session):
        data = session.get_json("https://remotive.com/api/remote-jobs")
        for j in data.get("jobs", []):
            yield Job(
                source=self.name,
                source_id=str(j["id"]),
                title=(j.get("title") or "").strip(),
                company=(j.get("company_name") or "").strip(),
                url=j.get("url", ""),
                location=j.get("candidate_required_location") or "Remote",
                remote=True,
                posted_at=parse_datetime(j.get("publication_date")),
                tags=[t for t in [j.get("category"), j.get("job_type"), *(j.get("tags") or [])] if t],
                salary=j.get("salary") or "",
                description=html_to_text(j.get("description", "")),
            )


class Arbeitnow(Source):
    """https://www.arbeitnow.com/api/job-board-api — mostly Europe / Germany, paginated."""

    name = "arbeitnow"

    def __init__(self, max_pages: int = 5):
        self.max_pages = max_pages

    def fetch(self, session):
        url = "https://www.arbeitnow.com/api/job-board-api"
        for _ in range(self.max_pages):
            data = session.get_json(url)
            for j in data.get("data", []):
                location = j.get("location") or ""
                yield Job(
                    source=self.name,
                    source_id=j.get("slug") or j.get("url", ""),
                    title=(j.get("title") or "").strip(),
                    company=(j.get("company_name") or "").strip(),
                    url=j.get("url", ""),
                    location=location,
                    remote=bool(j.get("remote")) or looks_remote(location),
                    posted_at=parse_datetime(j.get("created_at")),
                    tags=[*(j.get("tags") or []), *(j.get("job_types") or [])],
                    description=html_to_text(j.get("description", "")),
                )
            url = (data.get("links") or {}).get("next")
            if not url:
                break


class HackerNewsHiring(Source):
    """Top-level comments on the latest monthly "Ask HN: Who is hiring?" thread.

    Posts are free text; by convention the first line is
    ``Company | Role | Location | REMOTE/ONSITE | ...`` so we parse that heuristically.
    """

    name = "hackernews"
    ALGOLIA = "https://hn.algolia.com/api/v1"

    def fetch(self, session):
        search = session.get_json(
            f"{self.ALGOLIA}/search_by_date",
            params={"tags": "story,author_whoishiring", "query": "who is hiring", "hitsPerPage": 5},
        )
        story = next(
            (h for h in search.get("hits", []) if "who is hiring" in (h.get("title") or "").lower()),
            None,
        )
        if not story:
            return
        thread = session.get_json(f"{self.ALGOLIA}/items/{story['objectID']}")
        for c in thread.get("children", []):
            text = c.get("text") or ""
            if not text or c.get("author") is None:  # deleted / dead
                continue
            plain = html_to_text(text, limit=1500)
            first_line = plain.split("\n", 1)[0]
            parts = [p.strip() for p in re.split(r"\s*[|•]\s*|\s+-\s+", first_line) if p.strip()]
            company = parts[0] if parts else c["author"]
            role = _guess_role(parts[1:]) or first_line
            location = _guess_location(parts[1:])
            yield Job(
                source=self.name,
                source_id=str(c["id"]),
                title=role[:150],
                company=company[:80],
                url=f"https://news.ycombinator.com/item?id={c['id']}",
                location=location,
                remote=looks_remote(first_line),
                posted_at=parse_datetime(c.get("created_at_i") or c.get("created_at")),
                tags=[p for p in parts[1:] if p not in (role, location)][:6],
                description=plain[:500],
            )


_ROLE_HINT = re.compile(
    r"engineer|developer|scientist|designer|manager|lead|architect|analyst|devops|sre|"
    r"frontend|backend|full[- ]?stack|intern|product|marketing|sales|founding|head of|director",
    re.I,
)
_LOC_HINT = re.compile(
    r"remote|onsite|on-site|hybrid|\b(usa?|uk|eu|europe|nyc|sf|london|berlin|toronto|"
    r"new york|san francisco|seattle|boston|austin|paris|amsterdam)\b",
    re.I,
)


def _guess_role(parts):
    return next((p for p in parts if _ROLE_HINT.search(p)), "")


def _guess_location(parts):
    return next((p for p in parts if _LOC_HINT.search(p) and not _ROLE_HINT.search(p)), "")
