"""US place lookup: ZIP codes and "City, ST" to map coordinates, and distances between them.

The data (data/us_places.json) maps every US ZIP code to its centre point and every
"city|ST" to the average of its ZIP codes. It is used both to understand what the
user typed in the "Near" box and to place each job on the map.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PLACES_FILE = Path(__file__).parent / "data" / "us_places.json"

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "puerto rico": "PR",
}
ABBREVS = set(STATES.values())
ALIASES = {  # common ways job ads name big cities
    "nyc": "new york|NY", "new york city": "new york|NY", "manhattan": "new york|NY",
    "sf": "san francisco|CA", "la": "los angeles|CA", "dc": "washington|DC",
    "washington dc": "washington|DC", "washington d.c.": "washington|DC", "philly": "philadelphia|PA",
    "bay area": "san francisco|CA", "sf bay area": "san francisco|CA", "san francisco bay area": "san francisco|CA",
}
# A bare city name with no state is only trusted for big cities, so "London" or
# "Paris" in a foreign job ad don't land in London, KY or Paris, TX.
BIG_CITY_MIN_ZIPS = 15
NON_US = re.compile(
    r"\b(uk|united kingdom|england|scotland|ireland|germany|deutschland|france|spain|italy|netherlands|"
    r"canada|mexico|brazil|india|china|japan|singapore|australia|poland|portugal|sweden|switzerland|"
    r"austria|belgium|denmark|norway|finland|israel|emea|apac|latam|europe)\b",
    re.I,
)
ZIP_RE = re.compile(r"(?<!\d)(\d{5})(?:-\d{4})?(?!\d)")
CITY_STATE_RE = re.compile(r"([A-Za-z][A-Za-z .'\-]*?)\s*,\s*([A-Za-z][A-Za-z .]*?)(?=\s*(?:,|\(|$|\d|/|;|\|| - ))")


@dataclass(frozen=True)
class Place:
    lat: float
    lon: float
    label: str


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(PLACES_FILE.read_text(encoding="utf-8"))


def _city(name: str, state: str | None) -> Place | None:
    name = re.sub(r"\s+", " ", name.strip().lower())
    if not state and name in ALIASES:
        return _alias(name)
    name = re.sub(r"^(greater|downtown|metro)\s+", "", name)
    name = re.sub(r"^(st\.?|ste\.?)\s+", "saint ", name)  # the data spells out "Saint"
    name = re.sub(r"\s+(area|metro area|metropolitan area)$", "", name)
    cities = _data()["cities"]
    if state:
        hit = cities.get(f"{name}|{state}")
        return Place(hit[0], hit[1], f"{name.title()}, {state}") if hit else None
    if name in ALIASES:
        return _alias(name)
    best = _biggest_by_name().get(name)
    if best and cities[best][2] >= BIG_CITY_MIN_ZIPS:
        city, st = best.split("|")
        return Place(cities[best][0], cities[best][1], f"{city.title()}, {st}")
    return None


def _alias(name: str) -> Place:
    key = ALIASES[name]
    lat, lon, _ = _data()["cities"][key]
    city, st = key.split("|")
    return Place(lat, lon, f"{city.title()}, {st}")


@lru_cache(maxsize=1)
def _biggest_by_name() -> dict[str, str]:
    """city name -> "city|ST" of the largest US city with that name."""
    best: dict[str, str] = {}
    cities = _data()["cities"]
    for key, (_, _, n) in cities.items():
        name = key.split("|")[0]
        if name not in best or n > cities[best[name]][2]:
            best[name] = key
    return best


def _state(text: str) -> str | None:
    t = text.strip().rstrip(".")
    if t.upper() in ABBREVS:
        return t.upper()
    return STATES.get(t.lower())


def lookup(text: str) -> Place | None:
    """Understand what someone typed: "60614", "Austin, TX", "Austin Texas", "Chicago"."""
    t = (text or "").strip()
    if not t:
        return None
    if m := re.fullmatch(r"(\d{5})(?:-\d{4})?", t):
        z = _data()["zips"].get(m.group(1))
        return Place(z[0], z[1], m.group(1)) if z else None
    if "," in t:
        city, _, rest = t.partition(",")
        st = _state(rest.split(",")[0])
        return _city(city, st) if st else None
    # "Austin TX" / "Austin Texas" / "New York New York"
    words = t.split()
    for n in (2, 1):
        if len(words) > n and (st := _state(" ".join(words[-n:]))):
            if hit := _city(" ".join(words[:-n]), st):
                return hit
    return _city(t, None)


@lru_cache(maxsize=20000)
def locate_job(location: str) -> Place | None:
    """Best-effort map position for a job's free-text location (None if unknown or not in the US)."""
    if not location:
        return None
    # Workday style: "US-CA-San Jose"
    if m := re.match(r"(?i)^usa?-([A-Z]{2})-(.+)$", location.strip()):
        if (st := _state(m.group(1))) and (hit := _city(m.group(2), st)):
            return hit
    text = re.sub(r"(?i)\b(remote|hybrid|on-?site|in[- ]office)\b\s*[-–:(]?\s*", " ", location)
    text = re.sub(r"(?i),?\s*\b(united states( of america)?|usa|u\.s\.a?\.?|us)\b\.?", "", text)
    if NON_US.search(text):
        return None
    if m := ZIP_RE.search(text):
        z = _data()["zips"].get(m.group(1))
        if z:
            return Place(z[0], z[1], m.group(1))
    for part in re.split(r"\s*(?:;|\||/| or | & |\n)\s*", text):
        part = part.strip(" ,-()")
        if not part:
            continue
        for m in CITY_STATE_RE.finditer(part + " "):
            st = _state(m.group(2))
            if st and (hit := _city(m.group(1), st)):
                return hit
        if hit := lookup(part):
            return hit
    return None


def miles_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8  # Earth radius in miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
