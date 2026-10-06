"""Source registry: turns the config file into a list of fetchable sources."""

from __future__ import annotations

from .adzuna import Adzuna
from .ats import Ashby, Greenhouse, Lever
from .base import CompanySource, Source
from .boards import Arbeitnow, HackerNewsHiring, Remotive, RemoteOK

COMPANY_SOURCES: dict[str, type[CompanySource]] = {
    "greenhouse": Greenhouse,
    "lever": Lever,
    "ashby": Ashby,
}

BOARD_SOURCES: dict[str, type[Source]] = {
    "remoteok": RemoteOK,
    "remotive": Remotive,
    "arbeitnow": Arbeitnow,
    "hackernews": HackerNewsHiring,
}

ALL_SOURCE_NAMES = [*BOARD_SOURCES, *COMPANY_SOURCES, "adzuna"]


def build_sources(config: dict, only: set[str] | None = None) -> list[Source]:
    """Config shape (see sources.example.json):

    {
      "boards": {"remotive": true, "arbeitnow": {"max_pages": 3}},
      "companies": {
        "greenhouse": ["stripe", {"slug": "airbnb", "name": "Airbnb"}],
        "lever": [...], "ashby": [...]
      },
      "areas": [{"where": "60614", "miles": 25, "what": "nurse"}],   # searched on Adzuna
      "adzuna": {"app_id": "...", "app_key": "...", "max_pages": 10}
    }
    """
    sources: list[Source] = []

    for name, opts in (config.get("boards") or {}).items():
        if name not in BOARD_SOURCES:
            raise ValueError(f"unknown board source {name!r}; known: {', '.join(BOARD_SOURCES)}")
        if not opts or (only and name not in only):
            continue
        kwargs = opts if isinstance(opts, dict) else {}
        sources.append(BOARD_SOURCES[name](**kwargs))

    for ats, entries in (config.get("companies") or {}).items():
        if ats not in COMPANY_SOURCES:
            raise ValueError(f"unknown ATS {ats!r}; known: {', '.join(COMPANY_SOURCES)}")
        if only and ats not in only:
            continue
        for entry in entries or []:
            if isinstance(entry, str):
                sources.append(COMPANY_SOURCES[ats](entry))
            else:
                sources.append(COMPANY_SOURCES[ats](entry["slug"], entry.get("name")))

    if not only or "adzuna" in only:
        az = config.get("adzuna") or {}
        for area in config.get("areas") or []:
            sources.append(Adzuna(
                where=area["where"],
                miles=int(area.get("miles") or 25),
                what=area.get("what") or "",
                app_id=az.get("app_id", ""),
                app_key=az.get("app_key", ""),
                country=az.get("country", "us"),
                max_pages=int(az.get("max_pages") or 10),
                category=area.get("category") or "",
            ))

    return sources


__all__ = ["Source", "build_sources", "ALL_SOURCE_NAMES", "BOARD_SOURCES", "COMPANY_SOURCES"]
