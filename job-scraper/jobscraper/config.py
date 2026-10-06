"""Settings: which job sites, companies and search areas to use, and the Adzuna codes.

The same shape is used by the app (saved in ~/.jobscraper/config.json) and the
website (job-scraper/sources.json, with the Adzuna codes coming from GitHub secrets).
"""

from __future__ import annotations

import copy
import re

from .sources import BOARD_SOURCES, COMPANY_SOURCES

SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
WHERE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,'\-]{0,79}$")
WHAT_RE = re.compile(r"^[\w .,'&+#/\-]{0,100}$")
CATEGORY_RE = re.compile(r"^[a-z0-9-]{0,60}$")
ANTHROPIC_KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{10,300}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{1,100}$")
MAX_AREAS = 10

DEFAULT_CONFIG = {
    "boards": {name: True for name in BOARD_SOURCES},
    "companies": {ats: [] for ats in COMPANY_SOURCES},
    "areas": [{"where": "08088", "miles": 50, "what": ""}],
    "adzuna": {"app_id": "", "app_key": "", "max_pages": 10},
    "anthropic": {"api_key": ""},
}


def validate_config(cfg: dict, previous: dict | None = None) -> dict:
    """Normalise settings; raises ValueError with a readable message on bad input.

    Adzuna codes left blank keep the ones already saved in `previous`.
    """
    if not isinstance(cfg, dict):
        raise ValueError("config must be an object")
    boards_in = cfg.get("boards") or {}
    companies_in = cfg.get("companies") or {}
    boards = {name: bool(boards_in.get(name)) for name in BOARD_SOURCES}
    companies: dict[str, list] = {}
    for ats in COMPANY_SOURCES:
        entries, seen = [], set()
        for e in companies_in.get(ats) or []:
            slug = e if isinstance(e, str) else (e or {}).get("slug")
            name = None if isinstance(e, str) else (e or {}).get("name")
            slug = (slug or "").strip()
            if not SLUG_RE.match(slug):
                raise ValueError(f"'{slug}' is not a valid {ats} company id (letters, digits, - _ . only)")
            if slug.lower() in seen:
                continue
            seen.add(slug.lower())
            name = (name or "").strip()[:100]
            entries.append({"slug": slug, "name": name} if name else slug)
        companies[ats] = entries

    areas, seen = [], set()
    for a in cfg.get("areas") or []:
        if not isinstance(a, dict):
            raise ValueError("each search area must be an object")
        where = re.sub(r"\s+", " ", str(a.get("where") or "")).strip()
        what = re.sub(r"\s+", " ", str(a.get("what") or "")).strip()
        category = str(a.get("category") or "").strip()
        if not CATEGORY_RE.match(category):
            raise ValueError(f"'{category}' is not a known kind of job")
        if not WHERE_RE.match(where):
            raise ValueError(f"'{where}' doesn't look like a ZIP code or city")
        if not WHAT_RE.match(what):
            raise ValueError(f"'{what}' has characters that can't be searched")
        try:
            miles = int(a.get("miles") or 25)
        except (TypeError, ValueError):
            raise ValueError("distance must be a number of miles") from None
        if not 1 <= miles <= 200:
            raise ValueError("distance must be between 1 and 200 miles")
        key = (where.lower(), what.lower(), category)
        if key in seen:
            continue
        seen.add(key)
        area = {"where": where, "miles": miles, "what": what}
        if category:
            area["category"] = category
        areas.append(area)
    if len(areas) > MAX_AREAS:
        raise ValueError(f"at most {MAX_AREAS} search areas")

    az_in = cfg.get("adzuna") or {}
    az_prev = (previous or {}).get("adzuna") or {}
    adzuna = {}
    for field in ("app_id", "app_key"):
        value = str(az_in.get(field) or "").strip() or az_prev.get(field, "")
        if value and not KEY_RE.match(value):
            raise ValueError(f"the Adzuna {field.replace('_', ' ')} should be letters and digits only")
        adzuna[field] = value
    try:
        adzuna["max_pages"] = max(1, min(50, int(az_in.get("max_pages") or az_prev.get("max_pages") or 10)))
    except (TypeError, ValueError):
        raise ValueError("max_pages must be a number") from None

    an_in = cfg.get("anthropic") or {}
    an_key = str(an_in.get("api_key") or "").strip() or ((previous or {}).get("anthropic") or {}).get("api_key", "")
    if an_in.get("clear"):
        an_key = ""
    if an_key and not ANTHROPIC_KEY_RE.match(an_key):
        raise ValueError("That doesn't look like an Anthropic API key. It should start with sk-ant-")

    return {"boards": boards, "companies": companies, "areas": areas, "adzuna": adzuna,
            "anthropic": {"api_key": an_key}}


def same_area(a: dict, b: dict) -> bool:
    """Same place, keywords and kind of job (the distance may differ)."""
    def norm(x):
        return (str(x.get("where") or "").strip().lower(), str(x.get("what") or "").strip().lower(),
                str(x.get("category") or ""))
    return norm(a) == norm(b)


def with_area(cfg: dict, area: dict) -> list[dict]:
    """The config's areas with `area` added last (replacing the same search), oldest dropped if full.

    The first area is treated as home and always kept.
    """
    areas = [a for a in cfg.get("areas") or [] if not same_area(a, area)]
    if len(areas) >= MAX_AREAS:
        areas = areas[:1] + areas[-(MAX_AREAS - 2):]
    return [*areas, area]


def public_config(cfg: dict) -> dict:
    """The settings minus the Adzuna codes, safe to show in a page or publish."""
    out = copy.deepcopy(cfg)
    az = out.get("adzuna") or {}
    has_keys = bool(az.pop("app_id", "")) & bool(az.pop("app_key", ""))
    out["adzuna"] = {**az, "has_keys": has_keys}
    out["anthropic"] = {"has_key": bool((out.get("anthropic") or {}).get("api_key"))}
    return out
