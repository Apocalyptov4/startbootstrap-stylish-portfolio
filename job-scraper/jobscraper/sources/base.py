from __future__ import annotations

from typing import Iterable

from ..http import Session
from ..models import Job


class Source:
    """One fetchable unit of work (a whole job board, or one company's board)."""

    name: str = "base"

    @property
    def label(self) -> str:
        return self.name

    def fetch(self, session: Session) -> Iterable[Job]:
        raise NotImplementedError


class CompanySource(Source):
    """A source that lists a single company's openings on an ATS (Greenhouse, Lever, Ashby...)."""

    def __init__(self, slug: str, company: str | None = None):
        self.slug = slug
        self.company = company or slug.replace("-", " ").title()

    @property
    def label(self) -> str:
        return f"{self.name}:{self.slug}"
