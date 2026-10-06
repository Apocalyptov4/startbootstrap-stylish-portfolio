"""Common data model shared by every source."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Job:
    source: str            # e.g. "greenhouse", "remotive"
    source_id: str         # the id the site uses for this posting
    title: str
    company: str
    url: str
    location: str = ""
    remote: bool = False
    posted_at: Optional[datetime] = None
    tags: list[str] = field(default_factory=list)
    salary: str = ""
    description: str = ""  # plain text, possibly truncated
    lat: Optional[float] = None   # map position, when the location is a known US place
    lon: Optional[float] = None
    area: str = ""         # for area searches (Adzuna): the ZIP/city searched around
    category: str = ""     # kind of job, as an Adzuna category tag such as "retail-jobs"

    @property
    def uid(self) -> str:
        """Stable id, unique across sources."""
        return f"{self.source}:{self.source_id}"

    @property
    def dedup_key(self) -> tuple[str, str, str]:
        """Same role at the same place, posted on several boards, collapses to one entry.

        The place is part of the key so a chain hiring for one title at many
        branches keeps one listing per branch.
        """
        from . import geo

        place = geo.locate_job(self.location)
        if place:
            where = place.label.lower()
        elif self.remote:
            where = "remote"
        else:
            where = _norm(self.location)
        return (_norm(self.company), _norm(self.title), where)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["uid"] = self.uid
        d["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        return d


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def parse_datetime(value) -> Optional[datetime]:
    """Accept ISO strings, epoch seconds or epoch milliseconds. Always returns UTC-aware."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            ts = float(value)
            if ts > 1e12:  # milliseconds
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(html: str, limit: int = 500) -> str:
    """Very small HTML stripper, good enough for search + previews."""
    import html as _html

    if not html:
        return ""
    text = re.sub(r"(?i)<\s*(br|/p|/li|/div)\s*/?>", "\n", html)
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(text)
    text = "\n".join(_WS_RE.sub(" ", line).strip() for line in text.splitlines())
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text[:limit]


REMOTE_RE = re.compile(r"\b(remote|anywhere|distributed|work from home|wfh)\b", re.I)


def looks_remote(*texts: str) -> bool:
    return any(t and REMOTE_RE.search(t) for t in texts)
