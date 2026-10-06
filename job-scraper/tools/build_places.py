"""Rebuild jobscraper/data/us_places.json from the zipcodes package (MIT), version 1.2.0.

Usage: pip download --no-deps --no-binary :all: zipcodes==1.2.0, extract it, then
    python tools/build_places.py <zipcodes-1.2.0>/zipcodes/zips.json.bz2 jobscraper/data/us_places.json
"""
import bz2, json, sys
from collections import defaultdict

src, out = sys.argv[1], sys.argv[2]
rows = json.loads(bz2.open(src).read())
zips, groups = {}, defaultdict(list)
for r in rows:
    if not r.get("active") or not r.get("lat") or not r.get("long"):
        continue
    lat, lon = round(float(r["lat"]), 3), round(float(r["long"]), 3)
    if lat == 0 and lon == 0:
        continue
    zips[r["zip_code"]] = [lat, lon, f'{r["city"].title()}, {r["state"]}']
    st = r["state"]
    for city in [r["city"], *r.get("acceptable_cities", [])]:
        groups[(city.lower(), st)].append((lat, lon, r["zip_code_type"] == "STANDARD"))
cities = {}
for (city, st), pts in groups.items():
    std = [p for p in pts if p[2]] or pts
    cities[f"{city}|{st}"] = [round(sum(p[0] for p in std) / len(std), 3), round(sum(p[1] for p in std) / len(std), 3), len(std)]
data = {
    "about": "US ZIP code and city centroids. Derived from the zipcodes Python package 1.2.0 (MIT License, data updated 2021-10-03).",
    "zips": zips,
    "cities": cities,
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(data, f, separators=(",", ":"))
print(len(zips), "zips", len(cities), "cities")
