"""Applicant-tracking systems that expose public, per-company job board APIs.

Most tech companies host their careers page on one of these, so adding a company
is just adding its board slug (the bit in the URL) to the config file:

    boards.greenhouse.io/<slug>   -> greenhouse
    jobs.lever.co/<slug>          -> lever
    jobs.ashbyhq.com/<slug>       -> ashby
"""

from __future__ import annotations

import html

from ..models import Job, html_to_text, looks_remote, parse_datetime
from .base import CompanySource


class Greenhouse(CompanySource):
    name = "greenhouse"

    def fetch(self, session):
        data = session.get_json(
            f"https://boards-api.greenhouse.io/v1/boards/{self.slug}/jobs",
            params={"content": "true"},
        )
        for j in data.get("jobs", []):
            location = (j.get("location") or {}).get("name", "")
            depts = [d.get("name", "") for d in j.get("departments") or [] if d.get("name")]
            # `content` is HTML that has itself been HTML-escaped.
            description = html_to_text(html.unescape(j.get("content") or ""))
            yield Job(
                source=self.name,
                source_id=str(j["id"]),
                title=j.get("title", "").strip(),
                company=j.get("company_name") or self.company,
                url=j.get("absolute_url", ""),
                location=location,
                remote=looks_remote(location, j.get("title", "")),
                posted_at=parse_datetime(j.get("first_published") or j.get("updated_at")),
                tags=depts,
                description=description,
            )


class Lever(CompanySource):
    name = "lever"

    def fetch(self, session):
        data = session.get_json(
            f"https://api.lever.co/v0/postings/{self.slug}", params={"mode": "json"}
        )
        for j in data:
            cats = j.get("categories") or {}
            location = cats.get("location") or ", ".join(cats.get("allLocations") or [])
            workplace = (j.get("workplaceType") or "").lower()
            salary = ""
            sr = j.get("salaryRange") or {}
            if sr.get("min") and sr.get("max"):
                salary = f"{sr.get('currency', '')} {sr['min']:,}-{sr['max']:,} {sr.get('interval', '')}".strip()
            yield Job(
                source=self.name,
                source_id=j["id"],
                title=j.get("text", "").strip(),
                company=self.company,
                url=j.get("hostedUrl", ""),
                location=location,
                remote=workplace == "remote" or looks_remote(location),
                posted_at=parse_datetime(j.get("createdAt")),
                tags=[t for t in (cats.get("team"), cats.get("department"), cats.get("commitment")) if t],
                salary=salary,
                description=(j.get("descriptionPlain") or "")[:500],
            )


class Ashby(CompanySource):
    name = "ashby"

    def fetch(self, session):
        data = session.get_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{self.slug}",
            params={"includeCompensation": "true"},
        )
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            location = j.get("location", "")
            comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
            yield Job(
                source=self.name,
                source_id=j["id"],
                title=j.get("title", "").strip(),
                company=self.company,
                url=j.get("jobUrl", ""),
                location=location,
                remote=bool(j.get("isRemote")) or looks_remote(location),
                posted_at=parse_datetime(j.get("publishedAt")),
                tags=[t for t in (j.get("department"), j.get("team"), j.get("employmentType")) if t],
                salary=comp,
                description=(j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")))[:500],
            )
