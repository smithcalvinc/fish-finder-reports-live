#!/usr/bin/env python3
"""Build Nevada Fish Finder Outdoors county data from official public sources.

This one-file state builder creates and maintains:
- the authoritative 17 Nevada county/county-equivalent list
- official NDOW server-rendered fishable-water records (FishNV retained only as an optional map link)
- official NDOW fishing reports and stocking updates
- public-access-only county search data
- the Nevada county search page
- the shared multi-state admin dashboard feeds
- navigation, sitemap and PWA cache integration

Strict public-access policy
---------------------------
NDOW server-rendered water pages supply the authoritative water inventory and county metadata. FishNV is retained only as an optional map link and never proves public access.
A water is published only after a separate official NDOW accessibility table,
Nevada State Parks page, National Park Service page, BLM recreation dataset,
USDA Forest Service recreation dataset, or Bureau of Reclamation boat-ramp dataset
verifies a named public access facility. Dynamic federal records must also fall inside an official Nevada county polygon. Unmatched waters are quarantined and are
not displayed. A verified facility does not make every shoreline or neighboring
parcel public; current signs, closures, tribal rules and regulations still control.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import json
import math
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

try:
    from bs4 import BeautifulSoup
except ImportError:  # installed by GitHub Actions
    BeautifulSoup = None

STATE = "Nevada"
STATE_ABBR = "NV"
COUNTIES = [
    "Carson City", "Churchill", "Clark", "Douglas", "Elko", "Esmeralda",
    "Eureka", "Humboldt", "Lander", "Lincoln", "Lyon", "Mineral", "Nye",
    "Pershing", "Storey", "Washoe", "White Pine",
]
COUNTY_NUMBER = {name: i + 1 for i, name in enumerate(COUNTIES)}
COUNTY_LOOKUP = {
    re.sub(r"[^a-z0-9]+", " ", name.lower()).strip(): name for name in COUNTIES
}

# Nevada has 17 county/county-equivalent shells, but some desert counties may
# legitimately have no independently verified public fishing access. These
# safety floors detect a collapsed build without inventing access just to fill
# every county.
MIN_NDOW_WATER_PAGES = 300
MIN_NDOW_METADATA_RECORDS = 300
MIN_VERIFIED_PUBLIC_WATERS = 25
MIN_VERIFIED_ACCESS_POINTS = 25
MIN_OFFICIAL_REPORTS = 100
MIN_POPULATED_COUNTIES = 10

USER_AGENT = "FishFinderOutdoors-NevadaBuilder/1.0 (+https://fishfinderoutdoors.com)"
OFFICIAL_URLS = {
    "reports": "https://www.ndow.org/get-outside/fishing-stocking-reports/database/?region=all&show_all=true",
    "reports_root": "https://www.ndow.org/get-outside/fishing-stocking-reports/",
    "fishnv": "https://www.fish.wildlifenv.com/",
    "planning": "https://www.ndow.org/get-outside/plan-your-fishing-trip/",
    "regulations": "https://www.ndow.org/get-outside/fishing-rules-regulations/",
    "licenses": "https://www.ndow.org/apply-buy/fishing/",
    "county_layer": "https://gis.dot.nv.gov/agsphs/rest/services/State_of_Nevada_County_Boundaries/FeatureServer/0",
}


# FishNV is deliberately NOT an access-verification source. It provides the
# water inventory, coordinates, species and report matching. Every published
# access point must come from one of the independent official sources below.
OFFICIAL_ACCESS_URLS = {
    "ndow_accessible_fishing": "https://www.ndow.org/apply-buy/fishing/",
    "usfs_recreation_sites": "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_RecInfraRecreationSites_02/MapServer/0",
    "blm_boat_ramps": "https://gis.blm.gov/arcgis/rest/services/recreation/BLM_Natl_Recs_pts/MapServer/1",
    "blm_boating_sites": "https://gis.blm.gov/arcgis/rest/services/recreation/BLM_Natl_Recreation_Sites_Facilities/MapServer/3",
    "usbr_boat_ramps_item": "4ba5ae78a1bf4195a78b46b3e23a60ba",
    "nps_lake_mead_fishing": "https://www.nps.gov/lake/planyourvisit/fishing.htm",
    "nps_lake_mead_conditions": "https://www.nps.gov/lake/planyourvisit/conditions.htm",
}


# The NDOW page is official and currently publishes these named accessible
# fishing facilities. The builder still re-fetches the live page each run and
# only accepts a row when both the water name and a distinctive facility phrase
# remain present. This fallback does not trust copied text by itself; it is a
# resilient parser for pages whose table markup may change.
NDOW_ACCESSIBLE_FALLBACK_ROWS = [
    ("Sparks Marina", "Washoe", "One fishing pier at the southwest end of the lake", "City of Sparks"),
    ("Paradise Pond", "Washoe", "Two concrete fishing platforms", "City of Sparks"),
    ("Virginia Lake", "Washoe", "One fishing pier on the east side", "City of Reno"),
    ("Marilyn's Pond", "Washoe", "One fishing pier", "Washoe County"),
    ("Verdi Pond at Crystal Peak Park", "Washoe", "Three accessible ramps and piers", "Washoe County"),
    ("Mitch Park Pond", "Douglas", "One concrete fishing platform", "Gardnerville Ranchos"),
    ("Baily Fishing Pond", "Carson City", "One fishing pier", "Carson City"),
    ("Hinkson Slough", "Lyon", "Good access along the front dikes", "Nevada Department of Wildlife"),
    ("Bass Pond", "Lyon", "Good access along the front dikes", "Nevada Department of Wildlife"),
    ("North Pond", "Lyon", "One ADA accessible boat ramp", "Nevada Department of Wildlife"),
    ("Cave Lake", "White Pine", "ADA pier and parking", "Nevada State Parks"),
    ("Eagle Valley Reservoir", "Lincoln", "Accessible fishing pier and boat ramp", "Nevada State Parks"),
    ("Veterans Park Fishing Pond", "Clark", "Accessible fishing around the pond via paved path", "Boulder City"),
    ("Sunset Park Pond", "Clark", "Accessible fishing around the pond via paved path", "Clark County"),
    ("Lorenzi Park Pond", "Clark", "Accessible fishing around the pond via paved path", "City of Las Vegas"),
    ("Floyd Lamb Park Ponds", "Clark", "Paved and hard dirt paths around ponds provide access", "City of Las Vegas"),
    ("Lake Mead", "Clark", "Access varies with lake level", "National Park Service"),
    ("Lake Mohave", "Clark", "ADA accessible boat docks", "National Park Service"),
]

NEVADA_QUERY_ENVELOPE = "-120.2,34.8,-113.8,42.2"
ACCESS_CLOSED_PATTERNS = (
    r"\bprivate\b", r"\bmembers only\b", r"\bno public access\b",
    r"\bpermanently closed\b", r"\binoperable\b", r"\bdecommissioned\b",
)

# These are conservative, named access pages. The builder re-fetches each page
# on every run and publishes the record only when the required evidence is still
# present. A stale hard-coded claim can therefore never silently pass validation.
VERIFIED_PAGE_RULES = [
    {
        "water_hints": ["Cave Lake"],
        "access_point_name": "Cave Lake State Park shoreline and boat access",
        "county_hint": "White Pine",
        "url": "https://parks.nv.gov/parks/cave-lake",
        "source_name": "Nevada State Parks",
        "source_type": "official_state_access_page",
        "required_groups": [["fishing is permitted", "anglers will find"], ["boat launch", "from the shore"]],
        "amenities": {"camping": True, "restroom": True, "boat_ramp": True, "dock": None, "ada_fishing": None},
    },
    {
        "water_hints": ["Echo Canyon Reservoir"],
        "access_point_name": "Echo Canyon State Park boat launch and shoreline access",
        "county_hint": "Lincoln",
        "url": "https://parks.nv.gov/parks/echo-canyon",
        "source_name": "Nevada State Parks",
        "source_type": "official_state_access_page",
        "required_groups": [["fishermen", "fishing"], ["boat launch", "launch ramp"]],
        "amenities": {"camping": True, "restroom": True, "boat_ramp": True, "dock": None, "ada_fishing": None},
    },
    {
        "water_hints": ["South Fork Reservoir"],
        "access_point_name": "South Fork State Recreation Area public fishing and boat access",
        "county_hint": "Elko",
        "url": "https://parks.nv.gov/parks/south-fork",
        "source_name": "Nevada State Parks",
        "source_type": "official_state_access_page",
        "required_groups": [["fishing", "fishery"], ["boat ramps are available", "open for public use"]],
        "amenities": {"camping": True, "restroom": True, "boat_ramp": True, "dock": None, "ada_fishing": None},
    },
    {
        "water_hints": ["Wild Horse Reservoir"],
        "access_point_name": "Wild Horse State Recreation Area boat ramp and shoreline access",
        "county_hint": "Elko",
        "url": "https://parks.nv.gov/parks/wild-horse",
        "source_name": "Nevada State Parks",
        "source_type": "official_state_access_page",
        "required_groups": [["fishing is a popular activity", "popular fishing site"], ["boat ramp"]],
        "amenities": {"camping": True, "restroom": True, "boat_ramp": True, "dock": None, "ada_fishing": None},
    },
    {
        "water_hints": ["Eagle Valley Reservoir"],
        "access_point_name": "Spring Valley State Park ramp, dock and fishing access",
        "county_hint": "Lincoln",
        "url": "https://parks.nv.gov/parks/spring-valley",
        "source_name": "Nevada State Parks",
        "source_type": "official_state_access_page",
        "required_groups": [["fisherman", "fishery"], ["a ramp, dock", "ramp, dock"]],
        "amenities": {"camping": True, "restroom": True, "boat_ramp": True, "dock": True, "ada_fishing": None},
    },
    {
        "water_hints": ["Lahontan Reservoir"],
        "access_point_name": "Lahontan State Recreation Area public shoreline and boating access",
        "county_hint": "Churchill",
        "url": "https://parks.nv.gov/parks/lahontan",
        "source_name": "Nevada State Parks",
        "source_type": "official_state_access_page",
        "required_groups": [["boat", "boating"], ["fish", "fishing"], ["shoreline"]],
        "amenities": {"camping": True, "restroom": True, "boat_ramp": True, "dock": None, "ada_fishing": None},
    },
    {
        "water_hints": ["Washoe Lake"],
        "access_point_name": "Washoe Lake State Park main, north-ramp and shore-fishing access",
        "county_hint": "Washoe",
        "url": "https://parks.nv.gov/parks/washoe-lake",
        "source_name": "Nevada State Parks",
        "source_type": "official_state_access_page",
        "required_groups": [["fishing"], ["boat launching ramps", "shore fishing opportunities"]],
        "amenities": {"camping": True, "restroom": True, "boat_ramp": True, "dock": None, "ada_fishing": None},
    },
    {
        "water_hints": ["Little Washoe Lake"],
        "access_point_name": "Little Washoe Lake State Park shore-fishing and launch access",
        "county_hint": "Washoe",
        "url": "https://parks.nv.gov/parks/washoe-lake",
        "source_name": "Nevada State Parks",
        "source_type": "official_state_access_page",
        "required_groups": [["little washoe"], ["fishing"], ["boat launching ramps", "shore fishing opportunities"]],
        "amenities": {"camping": True, "restroom": True, "boat_ramp": True, "dock": None, "ada_fishing": None},
    },
    {
        "water_hints": ["Rye Patch Reservoir"],
        "access_point_name": "Rye Patch State Recreation Area west-side boat ramp and public day use",
        "county_hint": "Pershing",
        "url": "https://parks.nv.gov/parks/rye-patch",
        "source_name": "Nevada State Parks",
        "source_type": "official_state_access_page",
        "required_groups": [["boat launching", "boat ramp"], ["reservoir"]],
        "amenities": {"camping": True, "restroom": True, "boat_ramp": True, "dock": True, "ada_fishing": None},
    },
    {
        "water_hints": ["Lake Tahoe"],
        "access_point_name": "Sand Harbor public boat ramps and fishing access",
        "county_hint": "Washoe",
        "url": "https://parks.nv.gov/parks/lake-tahoe-nevada-state-park",
        "source_name": "Nevada State Parks",
        "source_type": "official_state_access_page",
        "required_groups": [["fisherman", "fishing"], ["boat launch", "two ramps"]],
        "amenities": {"camping": False, "restroom": True, "boat_ramp": True, "dock": None, "ada_fishing": None},
    },
    {
        "water_hints": ["Lake Tahoe"],
        "access_point_name": "Cave Rock boat ramp and separate rocky-shore fishing area",
        "county_hint": "Douglas",
        "url": "https://parks.nv.gov/parks/lake-tahoe-nevada-state-park-2",
        "source_name": "Nevada State Parks",
        "source_type": "official_state_access_page",
        "required_groups": [["good location for fishing", "fishing"], ["boat launch", "double ramp"]],
        "amenities": {"camping": False, "restroom": True, "boat_ramp": True, "dock": True, "ada_fishing": None},
    },
    {
        "water_hints": ["Lake Mead"],
        "access_point_name": "Hemenway Harbor Launch Ramp",
        "county_hint": "Clark",
        "url": "https://www.nps.gov/places/hemenway-harbor-launch-ramp.htm",
        "supporting_urls": ["https://www.nps.gov/lake/planyourvisit/fishing.htm"],
        "source_name": "National Park Service",
        "source_type": "official_federal_access_page",
        "required_groups": [["operational status of launch ramp", "operable"], ["boat ramp"], ["fishing is allowed", "fishing"]],
        "reject_terms": ["inoperable"],
        "amenities": {"camping": None, "restroom": True, "boat_ramp": True, "dock": True, "ada_fishing": None},
    },
    {
        "water_hints": ["Lake Mead"],
        "access_point_name": "Callville Bay Launch Ramp",
        "county_hint": "Clark",
        "url": "https://www.nps.gov/places/callville-bay-launch-ramp.htm",
        "supporting_urls": ["https://www.nps.gov/lake/planyourvisit/fishing.htm"],
        "source_name": "National Park Service",
        "source_type": "official_federal_access_page",
        "required_groups": [["operational status of launch ramp", "operable"], ["boat ramp"], ["fishing is allowed", "fishing"]],
        "reject_terms": ["inoperable"],
        "amenities": {"camping": None, "restroom": True, "boat_ramp": True, "dock": True, "ada_fishing": None},
    },
    {
        "water_hints": ["Lake Mead"],
        "access_point_name": "Echo Bay Launch Ramp",
        "county_hint": "Clark",
        "url": "https://www.nps.gov/places/echo-bay-launch-ramp.htm",
        "supporting_urls": ["https://www.nps.gov/lake/planyourvisit/fishing.htm"],
        "source_name": "National Park Service",
        "source_type": "official_federal_access_page",
        "required_groups": [["operational status of launch ramp", "operable"], ["boat ramp"], ["fishing is allowed", "fishing"]],
        "reject_terms": ["inoperable"],
        "amenities": {"camping": None, "restroom": None, "boat_ramp": True, "dock": True, "ada_fishing": None},
    },
    {
        "water_hints": ["Lake Mohave"],
        "access_point_name": "Cottonwood Cove Launch Ramp",
        "county_hint": "Clark",
        "url": "https://www.nps.gov/places/cottonwood-cove-launch-ramp.htm",
        "supporting_urls": ["https://www.nps.gov/lake/planyourvisit/fishing.htm"],
        "source_name": "National Park Service",
        "source_type": "official_federal_access_page",
        "required_groups": [["operational status of launch ramp", "operable"], ["boat ramp"], ["fishing is allowed", "fishing"]],
        "reject_terms": ["inoperable"],
        "amenities": {"camping": True, "restroom": True, "boat_ramp": True, "dock": True, "ada_fishing": None},
    },
]
FISHNV_HOSTS = {"fish.wildlifenv.com", "www.fish.wildlifenv.com"}
PRIVATE_PATTERNS = (
    r"\bprivate property\b",
    r"\bprivate water\b",
    r"\bprivate pond\b",
    r"\bprivate lake\b",
    r"\bprivate reservoir\b",
    r"\bmembers only\b",
    r"\bpermission (?:is )?required\b",
    r"\bpermission only\b",
    r"\bno public access\b",
    r"\bnot open to the public\b",
    r"\bclosed to (?:public|fishing|angling)\b",
    r"\baccess prohibited\b",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def clip(value: Any, limit: int = 700) -> str:
    text = clean(value)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"


def norm(value: Any) -> str:
    text = clean(value).lower().replace("&", " and ")
    text = re.sub(r"\b(the|of|at|on|main stem|mainstem)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_county(value: Any) -> str:
    text = clean(value)
    text = re.sub(r"^(county\s+of)\s+", "", text, flags=re.I)
    text = re.sub(r"\s+county$", "", text, flags=re.I)
    key = norm(text)
    aliases = {
        "carson": "Carson City",
        "carson city county": "Carson City",
        "city of carson city": "Carson City",
        "whitepine": "White Pine",
        "white pine": "White Pine",
    }
    return aliases.get(key) or COUNTY_LOOKUP.get(key, "")


def valid_lon_lat(lon: Any, lat: Any) -> bool:
    try:
        x, y = float(lon), float(lat)
    except (TypeError, ValueError):
        return False
    return -120.2 <= x <= -113.8 and 34.8 <= y <= 42.2


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return round(float(value), 7)
    except (TypeError, ValueError):
        return None


def parse_date(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso:
        return iso.group(1)
    text = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text, flags=re.I)
    for fmt in (
        "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y",
        "%A, %B %d, %Y", "%A, %b %d, %Y",
    ):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})\b",
        text,
        flags=re.I,
    )
    if match:
        try:
            return datetime.strptime(" ".join(match.groups()), "%B %d %Y").date().isoformat()
        except ValueError:
            pass
    return ""


def age_days(value: str) -> int | None:
    try:
        return (datetime.now(timezone.utc).date() - date.fromisoformat(value)).days
    except Exception:
        return None


def freshness(value: str) -> str:
    age = age_days(value)
    if age is None:
        return "date_unknown"
    if age <= 14:
        return "very_current"
    if age <= 30:
        return "current"
    if age <= 90:
        return "recent"
    return "stale"


def request_bytes(url: str, retries: int = 4, timeout: int = 90) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/html,application/xhtml+xml,application/xml,text/xml,*/*;q=0.8",
            })
            with urlopen(req, timeout=timeout) as response:
                payload = response.read()
                encoding = clean(response.headers.get("Content-Encoding")).lower()
                if encoding == "gzip" or url.lower().endswith(".gz"):
                    try:
                        payload = gzip.decompress(payload)
                    except OSError:
                        pass
                return payload
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(2 ** (attempt + 1), 12))
    raise RuntimeError(f"Unable to retrieve {url}: {last_error}")


def request_text(url: str, retries: int = 4) -> str:
    return request_bytes(url, retries=retries).decode("utf-8", errors="replace")


def request_json(url: str, retries: int = 4) -> dict[str, Any]:
    payload = json.loads(request_text(url, retries=retries))
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"Official JSON source error for {url}: {payload['error']}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected JSON payload from {url}")
    return payload


def soup_for(text: str) -> Any:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required; GitHub Actions installs it automatically")
    return BeautifulSoup(text, "html.parser")


def canonical_url(url: str, base: str = "") -> str:
    absolute = urljoin(base, clean(url))
    parts = urlsplit(absolute)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


def water_id(*parts: Any) -> str:
    value = "|".join(norm(part) for part in parts if clean(part))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def report_id(*parts: Any) -> str:
    return water_id(*parts)


def water_type(name: str, extra: str = "") -> str:
    text = f"{name} {extra}".lower()
    if "reservoir" in text or re.search(r"\bres\b", text):
        return "reservoir"
    if "lake" in text:
        return "lake"
    if "pond" in text or "pit" in text:
        return "pond"
    if "river" in text or "fork" in text:
        return "river"
    if "creek" in text or "stream" in text or "wash" in text or "canal" in text:
        return "stream"
    return "water"


def make_report(
    *,
    source_type: str,
    source_name: str,
    source_url: str,
    title: str,
    summary: str,
    report_date: str = "",
    water_name: str = "",
    counties: list[str] | None = None,
    species: str = "",
    techniques: str = "",
    access_notes: str = "",
) -> dict[str, Any]:
    report_date = parse_date(report_date)
    return {
        "report_id": report_id(source_url, title, water_name, report_date),
        "report_date": report_date,
        "freshness": freshness(report_date),
        "age_days": age_days(report_date) if report_date else None,
        "counties": sorted(set(counties or []), key=lambda c: COUNTY_NUMBER.get(c, 999)),
        "water_name": clean(water_name),
        "source_type": clean(source_type),
        "source_name": clean(source_name),
        "official": True,
        "title": clip(title, 240),
        "summary": clip(summary, 900),
        "species": clip(species, 320),
        "techniques": clip(techniques, 320),
        "access_notes": clip(access_notes, 650),
        "source_url": canonical_url(source_url),
    }


def arcgis_features(layer_url: str) -> list[dict[str, Any]]:
    url = f"{layer_url}/query?" + urlencode({
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    })
    return request_json(url).get("features") or []


def attr_value(attrs: dict[str, Any], *candidates: str) -> Any:
    fmap = {
        re.sub(r"[^a-z0-9]+", "", clean(key).lower()): key for key in attrs
    }
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", candidate.lower())
        original = fmap.get(key)
        if original and attrs.get(original) not in (None, ""):
            return attrs.get(original)
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", candidate.lower())
        for normalized, original in fmap.items():
            if key and (key in normalized or normalized in key):
                value = attrs.get(original)
                if value not in (None, ""):
                    return value
    return ""


def polygon_rings(feature: dict[str, Any]) -> list[list[list[float]]]:
    return (feature.get("geometry") or {}).get("rings") or []


def point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        crosses = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi
        )
        if crosses:
            inside = not inside
        j = i
    return inside


def load_county_polygons() -> list[tuple[str, list[list[list[float]]]]]:
    records: list[tuple[str, list[list[list[float]]]]] = []
    for feature in arcgis_features(OFFICIAL_URLS["county_layer"]):
        attrs = feature.get("attributes") or {}
        state_abbr = clean(attr_value(attrs, "STATE_ABV", "STATEABV", "STATE"))
        state_name = clean(attr_value(attrs, "STATE_NAME", "STATENAME"))
        if state_abbr and state_abbr.upper() != "NV":
            continue
        if not state_abbr and state_name and state_name.lower() != "nevada":
            continue
        county = canonical_county(attr_value(attrs, "COUNTYNAME", "COUNTY", "NAME"))
        rings = polygon_rings(feature)
        if county and rings:
            records.append((county, rings))
    found = {county for county, _ in records}
    if found != set(COUNTIES):
        missing = sorted(set(COUNTIES) - found)
        raise RuntimeError(
            f"Official Nevada county layer resolved {len(found)} of 17 county-equivalents; missing {missing}"
        )
    return records


def county_for_point(
    lon: float | None,
    lat: float | None,
    county_polygons: list[tuple[str, list[list[list[float]]]]],
) -> str:
    if not valid_lon_lat(lon, lat):
        return ""
    x, y = float(lon), float(lat)
    for county, rings in county_polygons:
        if any(point_in_ring(x, y, ring) for ring in rings if len(ring) >= 4):
            return county
    return ""


def xml_locs(text: str) -> list[str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return re.findall(r"<loc>\s*(.*?)\s*</loc>", text, flags=re.I | re.S)
    return [clean(node.text) for node in root.iter() if node.tag.lower().endswith("loc") and clean(node.text)]


def extract_water_urls(text: str, base: str = "") -> set[str]:
    urls: set[str] = set()
    for match in re.findall(r"(?:https?://[^\s'\"<>]+)?/waters/\d+/?", text, flags=re.I):
        url = canonical_url(match, base or OFFICIAL_URLS["fishnv"])
        if urlsplit(url).netloc in FISHNV_HOSTS:
            urls.add(url.rstrip("/"))
    return urls


# FishNV does not currently publish a complete sitemap or a public list endpoint.
# Its official water record IDs are grouped into these established route blocks.
# The fallback below checks only FishNV itself and accepts only real /waters/<id>
# pages. It does not make any public-access claim; access remains independently
# verified later in the build.
FISHNV_ROUTE_RANGES = (
    (1000, 2099),
    (3000, 3499),
    (4000, 4099),
)


def probe_fishnv_water_url(url: str) -> bool:
    """Return True only when FishNV confirms an exact water-detail route.

    HEAD filters obvious missing routes, then a small ranged GET confirms the
    page is a real FishNV water record. Servers that reject HEAD fall through
    to the same ranged GET. Redirects to the homepage or another record are
    rejected.
    """
    expected = canonical_url(url).rstrip("/")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    }
    try:
        req = Request(expected, headers=headers, method="HEAD")
        with urlopen(req, timeout=20) as response:
            final = canonical_url(response.geturl()).rstrip("/")
            status = int(getattr(response, "status", 200) or 200)
        if status != 200 or final != expected:
            return False
    except HTTPError as exc:
        if exc.code not in {403, 405, 501}:
            return False
    except (URLError, TimeoutError, OSError):
        return False

    try:
        get_headers = dict(headers)
        get_headers["Range"] = "bytes=0-65535"
        req = Request(expected, headers=get_headers)
        with urlopen(req, timeout=25) as response:
            final = canonical_url(response.geturl()).rstrip("/")
            status = int(getattr(response, "status", 200) or 200)
            sample = response.read(65536).decode("utf-8", errors="replace")
        if status not in {200, 206} or final != expected:
            return False
        # A real record is server-rendered with a water heading and FishNV
        # water-detail labels. This rejects branded 404 or homepage responses.
        soup = soup_for(sample)
        headings = [clean(node.get_text(" ", strip=True)) for node in soup.find_all(["h1", "h2"])[:12]]
        water_headings = [heading for heading in headings if norm(heading) not in {"", "fishnv", "get online", "get outside"}]
        page_text = clean(soup.get_text(" ", strip=True)).lower()
        return bool(water_headings and ("nearby waters" in page_text or "water details" in page_text))
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError):
        return False


def probe_fishnv_route_blocks(workers: int = 12) -> tuple[set[str], int]:
    candidates = [
        canonical_url(f"/waters/{water_number}", OFFICIAL_URLS["fishnv"]).rstrip("/")
        for start, end in FISHNV_ROUTE_RANGES
        for water_number in range(start, end + 1)
    ]
    found: set[str] = set()
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 12))) as executor:
        future_map = {executor.submit(probe_fishnv_water_url, url): url for url in candidates}
        for future in as_completed(future_map):
            url = future_map[future]
            try:
                if future.result():
                    found.add(url)
            except Exception:
                pass
    return found, len(candidates)


def discover_fishnv_water_urls(
    extra_html: Iterable[str] = (),
    seed_urls: Iterable[str] = (),
    probe_workers: int = 12,
) -> tuple[list[str], dict[str, int]]:
    urls: set[str] = {
        canonical_url(url).rstrip("/")
        for url in seed_urls
        if re.search(r"/waters/\d+/?$", clean(url))
        and urlsplit(canonical_url(url)).netloc in FISHNV_HOSTS
    }
    sitemap_urls: set[str] = set()
    failed: list[str] = []
    probe_candidates = 0
    probe_hits = 0

    try:
        robots = request_text(urljoin(OFFICIAL_URLS["fishnv"], "robots.txt"), retries=2)
        for line in robots.splitlines():
            if line.lower().startswith("sitemap:"):
                sitemap_urls.add(clean(line.split(":", 1)[1]))
        urls.update(extract_water_urls(robots, OFFICIAL_URLS["fishnv"]))
    except RuntimeError as exc:
        failed.append(str(exc))

    for candidate in (
        "sitemap.xml", "sitemap_index.xml", "sitemap-index.xml",
        "sitemap/sitemap.xml", "sitemaps.xml",
    ):
        sitemap_urls.add(urljoin(OFFICIAL_URLS["fishnv"], candidate))

    queue = list(sitemap_urls)
    seen: set[str] = set()
    while queue and len(seen) < 100:
        sitemap_url = canonical_url(queue.pop(0))
        if sitemap_url in seen:
            continue
        seen.add(sitemap_url)
        try:
            text = request_text(sitemap_url, retries=2)
        except RuntimeError as exc:
            failed.append(str(exc))
            continue
        urls.update(extract_water_urls(text, sitemap_url))
        for loc in xml_locs(text):
            if "sitemap" in loc.lower() and canonical_url(loc) not in seen:
                queue.append(loc)
            elif re.search(r"/waters/\d+/?$", loc):
                urls.add(canonical_url(loc).rstrip("/"))

    for html_text in extra_html:
        urls.update(extract_water_urls(html_text, OFFICIAL_URLS["reports_root"]))

    if len(urls) < 400:
        try:
            home = request_text(OFFICIAL_URLS["fishnv"])
            urls.update(extract_water_urls(home, OFFICIAL_URLS["fishnv"]))
            soup = soup_for(home)
            for script in soup.find_all("script", src=True):
                src = canonical_url(script.get("src"), OFFICIAL_URLS["fishnv"])
                if src:
                    try:
                        urls.update(extract_water_urls(request_text(src, retries=2), src))
                    except RuntimeError:
                        pass
        except RuntimeError as exc:
            failed.append(str(exc))

    # The live FishNV deployment currently exposes no complete sitemap/list.
    # Probe the site's official, bounded water route blocks only when all lighter
    # discovery methods still produce an incomplete inventory.
    if len(urls) < 400:
        print(f"FishNV linked discovery found {len(urls)} records; checking official water route blocks...")
        probed, probe_candidates = probe_fishnv_route_blocks(probe_workers)
        probe_hits = len(probed)
        urls.update(probed)
        print(f"FishNV route check confirmed {probe_hits} official water pages.")

    return sorted(urls), {
        "fishnv_water_urls": len(urls),
        "sitemaps_checked": len(seen),
        "discovery_failures": len(failed),
        "fishnv_probe_candidates": probe_candidates,
        "fishnv_probe_hits": probe_hits,
    }


def structured_objects(soup: Any) -> list[Any]:
    values: list[Any] = []
    for script in soup.find_all("script"):
        script_type = clean(script.get("type")).lower()
        raw = script.string or script.get_text(" ", strip=False)
        if not raw or ("json" not in script_type and not raw.lstrip().startswith(("{", "["))):
            continue
        try:
            values.append(json.loads(raw))
        except Exception:
            match = re.search(r"(?:__NEXT_DATA__|window\.__INITIAL_STATE__|window\.__DATA__)\s*=\s*({.*?})\s*;?\s*$", raw, flags=re.S)
            if match:
                try:
                    values.append(json.loads(match.group(1)))
                except Exception:
                    pass
    return values


def walk_json(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            new_path = path + (clean(key).lower(),)
            yield new_path, child
            yield from walk_json(child, new_path)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child, path)


def values_for_keys(objects: list[Any], keys: set[str]) -> list[Any]:
    values: list[Any] = []
    for obj in objects:
        for path, value in walk_json(obj):
            if path and path[-1] in keys and value not in (None, "", [], {}):
                values.append(value)
    return values


def first_coordinate_pair(objects: list[Any], text: str) -> tuple[float | None, float | None]:
    lat_values = values_for_keys(objects, {"latitude", "lat", "y"})
    lon_values = values_for_keys(objects, {"longitude", "lon", "lng", "long", "x"})
    for lat in lat_values:
        for lon in lon_values:
            if valid_lon_lat(lon, lat):
                return safe_float(lat), safe_float(lon)
    patterns = (
        r"\b((?:3[5-9]|4[0-2])\.\d{3,8})\s*,\s*(-1(?:1[4-9]|20)\.\d{3,8})\b",
        r"\b(-1(?:1[4-9]|20)\.\d{3,8})\s*,\s*((?:3[5-9]|4[0-2])\.\d{3,8})\b",
    )
    match = re.search(patterns[0], text)
    if match and valid_lon_lat(match.group(2), match.group(1)):
        return safe_float(match.group(1)), safe_float(match.group(2))
    match = re.search(patterns[1], text)
    if match and valid_lon_lat(match.group(1), match.group(2)):
        return safe_float(match.group(2)), safe_float(match.group(1))
    return None, None


def text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [clean(x) for x in re.split(r"[,;|]", value) if clean(x)]
    if isinstance(value, dict):
        for key in ("name", "title", "label", "common_name", "commonName"):
            if clean(value.get(key)):
                return [clean(value.get(key))]
        return []
    if isinstance(value, list):
        result: list[str] = []
        for child in value:
            result.extend(text_list(child))
        return result
    return []


def extract_species(soup: Any, objects: list[Any]) -> list[str]:
    species: list[str] = []
    for value in values_for_keys(objects, {"species", "fishspecies", "fish_species", "commonname", "common_name"}):
        species.extend(text_list(value))
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        if norm(heading.get_text(" ", strip=True)) != "species":
            continue
        for sibling in heading.find_all_next(limit=40):
            if sibling is not heading and getattr(sibling, "name", "") and re.match(r"^h[1-6]$", sibling.name):
                break
            if getattr(sibling, "name", "") in {"li", "a", "span", "p"}:
                value = clean(sibling.get_text(" ", strip=True))
                if value and len(value) <= 80 and not re.search(r"layers|basemap|water details|nearby", value, flags=re.I):
                    species.append(value)
    excluded = {"species", "water details", "fish caught", "advisories"}
    unique = sorted({clean(x).lower() for x in species if clean(x) and norm(x) not in excluded})
    return unique[:40]


def county_values(objects: list[Any], visible_head: str) -> list[str]:
    result: list[str] = []
    for value in values_for_keys(objects, {"county", "counties", "countyname", "county_name"}):
        for item in text_list(value):
            county = canonical_county(item)
            if county:
                result.append(county)
    normalized = norm(visible_head)
    for county in COUNTIES:
        if re.search(rf"\b{re.escape(norm(county))}\b", normalized):
            result.append(county)
    return sorted(set(result), key=lambda c: COUNTY_NUMBER[c])


def section_excerpt(text: str, terms: tuple[str, ...], limit: int = 650) -> str:
    compact = clean(text)
    lower = compact.lower()
    positions = [lower.find(term.lower()) for term in terms if lower.find(term.lower()) >= 0]
    if not positions:
        return ""
    start = max(0, min(positions) - 120)
    return clip(compact[start:start + limit], limit)


def bool_from_text(text: str, terms: tuple[str, ...]) -> bool | None:
    lower = text.lower()
    if not lower:
        return None
    return True if any(term in lower for term in terms) else None


def explicit_private_warning(text: str) -> str:
    compact = clean(text).lower()
    for pattern in PRIVATE_PATTERNS:
        match = re.search(pattern, compact, flags=re.I)
        if match:
            return match.group(0)
    return ""



def extract_fishnv_water_name(soup: Any, objects: list[Any]) -> str:
    """Return the actual FishNV water name, never the FishNV brand heading."""
    rejected_exact = {
        "", "fishnv", "get online", "get outside", "species", "water details",
        "fish caught", "advisories", "nearby waters", "layers and basemaps",
        "open mobile navigation menu",
    }

    def acceptable(value: Any) -> str:
        candidate = clean(value)
        normalized = norm(candidate)
        if not candidate or normalized in rejected_exact:
            return ""
        if "find your next fishing spot" in normalized:
            return ""
        if len(candidate) > 180:
            return ""
        return candidate

    # FishNV currently renders the brand as the first H1 and the actual
    # water name as a later H1. Check every H1 rather than soup.find("h1").
    for heading in soup.find_all("h1"):
        candidate = acceptable(heading.get_text(" ", strip=True))
        if candidate:
            return candidate

    # Prefer explicitly water-named structured fields.
    for candidate in values_for_keys(
        objects,
        {"watername", "water_name", "waterbodyname", "water_body_name"},
    ):
        value = acceptable(candidate)
        if value:
            return value

    # Some deployments expose the record name in OpenGraph metadata.
    for selector in (
        ('meta', {'property': 'og:title'}),
        ('meta', {'name': 'twitter:title'}),
    ):
        node = soup.find(selector[0], attrs=selector[1])
        if node:
            value = acceptable(node.get("content"))
            if value:
                value = re.sub(r"\s*[|–—-]\s*FishNV.*$", "", value, flags=re.I).strip()
                value = re.sub(r"^FishNV\s*[|–—-]\s*", "", value, flags=re.I).strip()
                value = acceptable(value)
                if value:
                    return value

    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    candidates = []
    trailing = re.match(r"^(.*?)\s*[|–—-]\s*FishNV(?:\b.*)?$", title, flags=re.I)
    if trailing:
        candidates.append(trailing.group(1))
    leading = re.match(r"^FishNV\s*[|–—-]\s*(.*?)$", title, flags=re.I)
    if leading:
        candidates.append(leading.group(1))
    candidates.append(title)
    for candidate in candidates:
        value = acceptable(candidate)
        if value:
            return value
    return ""


def parse_fishnv_water_page(
    url: str,
    county_polygons: list[tuple[str, list[list[list[float]]]]],
) -> tuple[dict[str, Any] | None, str]:
    """Parse FishNV water metadata without claiming public access."""
    try:
        raw = request_text(url)
    except RuntimeError as exc:
        return None, str(exc)
    soup = soup_for(raw)
    objects = structured_objects(soup)
    visible = clean(soup.get_text(" ", strip=True))
    visible_head = visible.split("Nearby Waters", 1)[0][:12000]

    name = extract_fishnv_water_name(soup, objects)
    if not name:
        return None, f"FishNV page did not expose a water name: {url}"

    private_warning = explicit_private_warning(visible_head)
    if private_warning:
        return None, f"Excluded explicit non-public water {name}: {private_warning}"

    lat, lon = first_coordinate_pair(objects, visible_head)
    counties = county_values(objects, visible_head)
    if not counties and valid_lon_lat(lon, lat):
        county = county_for_point(lon, lat, county_polygons)
        counties = [county] if county else []
    if not counties:
        return None, f"FishNV water could not be assigned to a Nevada county: {name}"

    species = extract_species(soup, objects)
    region = ""
    for value in values_for_keys(objects, {"region", "regionname", "region_name"}):
        candidate = clean(value)
        if candidate.lower() in {"eastern", "southern", "western"}:
            region = candidate.title()
            break
    if not region:
        for candidate in ("Eastern", "Southern", "Western"):
            if re.search(rf"\b{candidate}\b", visible_head):
                region = candidate
                break

    primary_county = counties[0]
    return {
        "water_id": water_id(url, name),
        "county": primary_county,
        "counties": counties,
        "county_number": COUNTY_NUMBER[primary_county],
        "water_name": name,
        "water_type": water_type(name, visible_head),
        "region": region,
        "latitude": lat,
        "longitude": lon,
        "species": ", ".join(species),
        "fishnv_source_url": canonical_url(url),
        "fishnv_page_id": re.search(r"/waters/(\d+)", url).group(1) if re.search(r"/waters/(\d+)", url) else "",
        "access_points": [],
    }, ""


def html_text(url: str) -> tuple[str, Any]:
    raw = request_text(url)
    soup = soup_for(raw)
    return clean(soup.get_text(" ", strip=True)), soup


def first_page_coordinate(soup: Any, visible: str) -> tuple[float | None, float | None]:
    try:
        return first_coordinate_pair(structured_objects(soup), visible[:12000])
    except Exception:
        return None, None


def find_directions_url(soup: Any, base_url: str) -> str:
    for anchor in soup.find_all("a", href=True):
        label = norm(anchor.get_text(" ", strip=True))
        href = clean(anchor.get("href"))
        if "get directions" in label or "directions" == label or "google.com/maps" in href.lower():
            return canonical_url(href, base_url)
    return ""


def make_access_record(
    *,
    water_hints: list[str],
    access_point_name: str,
    source_name: str,
    source_type: str,
    official_source_url: str,
    verification_evidence: str,
    access_details: str = "",
    county_hint: str = "",
    latitude: Any = None,
    longitude: Any = None,
    directions_url: str = "",
    amenities: dict[str, Any] | None = None,
    supporting_source_urls: list[str] | None = None,
    current_status: str = "public_access_verified",
) -> dict[str, Any]:
    lat, lon = safe_float(latitude), safe_float(longitude)
    if not valid_lon_lat(lon, lat):
        lat, lon = None, None
    if not directions_url and valid_lon_lat(lon, lat):
        directions_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    return {
        "access_id": water_id(source_name, access_point_name, official_source_url, lat, lon),
        "water_hints": [clean(value) for value in water_hints if clean(value)],
        "county_hint": canonical_county(county_hint),
        "access_point_name": clean(access_point_name),
        "latitude": lat,
        "longitude": lon,
        "directions_url": canonical_url(directions_url) if directions_url else "",
        "amenities": amenities or {
            "camping": None, "restroom": None, "boat_ramp": None,
            "dock": None, "ada_fishing": None,
        },
        "public_access_status": "verified_public",
        "current_status": clean(current_status),
        "verification_method": clean(source_type),
        "verification_evidence": clip(verification_evidence, 900),
        "access_details": clip(access_details or verification_evidence, 900),
        "source_name": clean(source_name),
        "official_source_url": canonical_url(official_source_url),
        "supporting_source_urls": [canonical_url(url) for url in (supporting_source_urls or []) if clean(url)],
        "entire_shoreline_public": False,
    }


def split_water_names(value: str) -> list[str]:
    text = clean(value)
    if not text:
        return []
    parts = [clean(part) for part in re.split(r"\s*,\s*|\s*;\s*", text) if clean(part)]
    typed = [part for part in parts if water_type(part) != "water"]
    if len(parts) > 1 and len(typed) >= 2:
        return parts
    return [text]


def collect_ndow_accessible_fishing() -> tuple[list[dict[str, Any]], dict[str, int]]:
    visible, soup = html_text(OFFICIAL_ACCESS_URLS["ndow_accessible_fishing"])
    records: list[dict[str, Any]] = []
    row_count = 0

    def append_record(water_name: str, county: str, location: str, facility: str, authority: str, method: str) -> None:
        nonlocal row_count
        water_name = clean(water_name)
        if not water_name:
            return
        row_count += 1
        evidence = (
            f"Live NDOW accessible-fishing page lists {water_name}"
            f"{f' at {location}' if clean(location) else ''}: {facility}. "
            f"Managing authority: {authority}."
        )
        blob = f"{facility} {authority}".lower()
        records.append(make_access_record(
            water_hints=[water_name],
            access_point_name=f"{water_name} — {facility or 'accessible public fishing facility'}",
            source_name="Nevada Department of Wildlife",
            source_type=method,
            official_source_url=OFFICIAL_ACCESS_URLS["ndow_accessible_fishing"],
            verification_evidence=evidence,
            access_details=evidence,
            county_hint=county,
            directions_url=OFFICIAL_ACCESS_URLS["ndow_accessible_fishing"],
            amenities={
                "camping": None,
                "restroom": True if any(term in blob for term in ("restroom", "toilet")) else None,
                "boat_ramp": True if "boat ramp" in blob else None,
                "dock": True if any(term in blob for term in ("pier", "platform", "dock")) else None,
                "ada_fishing": True,
            },
        ))

    # First use actual table markup when the site exposes it.
    for table in soup.find_all("table"):
        headers = [norm(cell.get_text(" ", strip=True)) for cell in table.find_all(["th", "td"])]
        header_blob = " ".join(headers[:8])
        if "body of water" not in header_blob or "facility" not in header_blob:
            continue
        for row in table.find_all("tr"):
            cells = [clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["td", "th"])]
            if len(cells) < 3 or norm(cells[0]) in {"body of water", "water"}:
                continue
            water_cell = cells[0]
            location = cells[1] if len(cells) > 1 else ""
            facility = cells[2] if len(cells) > 2 else ""
            authority = cells[3] if len(cells) > 3 else "Nevada Department of Wildlife"
            for water_name in split_water_names(water_cell):
                append_record(water_name, "", location, facility, authority, "official_ndow_accessibility_table")

    # If responsive cards/divs replaced the table, verify each known official row
    # against the live page text. This is not a blind hard-coded publication.
    visible_norm = norm(visible)
    for water_name, county, facility, authority in NDOW_ACCESSIBLE_FALLBACK_ROWS:
        water_norm = norm(water_name)
        facility_norm = norm(facility)
        if water_norm not in visible_norm:
            continue
        # A distinctive facility fragment must still be on the current NDOW page.
        facility_tokens = [token for token in facility_norm.split() if len(token) >= 5]
        if facility_tokens and sum(token in visible_norm for token in facility_tokens) < min(2, len(facility_tokens)):
            continue
        append_record(
            water_name,
            county,
            "",
            facility,
            authority,
            "official_ndow_accessibility_live_text",
        )

    unique = {clean(row.get("access_id")): row for row in records if clean(row.get("access_id"))}
    return list(unique.values()), {
        "ndow_accessible_table_rows": row_count,
        "ndow_access_records": len(unique),
    }



def collect_verified_page_rules() -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    checked = 0
    for rule in VERIFIED_PAGE_RULES:
        checked += 1
        try:
            primary_visible, primary_soup = html_text(rule["url"])
            combined = primary_visible
            supporting_urls = rule.get("supporting_urls") or []
            for support_url in supporting_urls:
                support_visible, _ = html_text(support_url)
                combined += " " + support_visible
            lower = combined.lower()
            missing = [group for group in rule["required_groups"] if not any(term.lower() in lower for term in group)]
            rejected = [term for term in rule.get("reject_terms", []) if term.lower() in lower]
            if missing or rejected:
                warnings.append(
                    f"Skipped {rule['access_point_name']}: "
                    f"missing evidence groups={missing!r}; rejected terms={rejected!r}"
                )
                continue
            lat, lon = first_page_coordinate(primary_soup, primary_visible)
            directions_url = find_directions_url(primary_soup, rule["url"])
            evidence_groups = [next(term for term in group if term.lower() in lower) for group in rule["required_groups"]]
            evidence = (
                f"Live official page verification matched: {', '.join(evidence_groups)}. "
                "The page is rechecked on every automated run."
            )
            records.append(make_access_record(
                water_hints=rule["water_hints"],
                access_point_name=rule["access_point_name"],
                source_name=rule["source_name"],
                source_type=rule["source_type"],
                official_source_url=rule["url"],
                supporting_source_urls=supporting_urls,
                verification_evidence=evidence,
                access_details=section_excerpt(primary_visible, ("fishing", "boat", "launch", "shore", "public use"), 850) or evidence,
                county_hint=rule.get("county_hint", ""),
                latitude=lat,
                longitude=lon,
                directions_url=directions_url,
                amenities=rule.get("amenities"),
            ))
        except Exception as exc:
            warnings.append(f"Could not verify {rule['access_point_name']}: {exc}")
    return records, {"verified_pages_checked": checked, "verified_page_access_records": len(records)}, warnings


def arcgis_query_features(
    layer_url: str,
    *,
    where: str = "1=1",
    geometry_envelope: str = NEVADA_QUERY_ENVELOPE,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    offset = 0
    seen_oids: set[Any] = set()
    while True:
        params = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
            "resultOffset": str(offset),
            "resultRecordCount": str(page_size),
        }
        if geometry_envelope:
            params.update({
                "geometry": geometry_envelope,
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            })
        payload = request_json(f"{layer_url}/query?{urlencode(params)}")
        batch = payload.get("features") or []
        if not batch:
            break
        added = 0
        for feature in batch:
            attrs = feature.get("attributes") or {}
            oid = attr_value(attrs, "OBJECTID", "FID", "OID")
            key = oid if oid not in (None, "") else json.dumps(feature.get("geometry") or {}, sort_keys=True) + clean(attr_value(attrs, "NAME", "FET_NAME", "site_name", "RecAreaName"))
            if key in seen_oids:
                continue
            seen_oids.add(key)
            features.append(feature)
            added += 1
        if not payload.get("exceededTransferLimit") and len(batch) < page_size:
            break
        if added == 0:
            break
        offset += len(batch)
        if offset > 200000:
            raise RuntimeError(f"ArcGIS pagination runaway at {layer_url}")
    return features


def feature_lon_lat(feature: dict[str, Any], attrs: dict[str, Any]) -> tuple[float | None, float | None]:
    geometry = feature.get("geometry") or {}
    lon = safe_float(geometry.get("x"))
    lat = safe_float(geometry.get("y"))
    if not valid_lon_lat(lon, lat):
        lon = safe_float(attr_value(attrs, "LONG", "LONGITUDE", "RecAreaLongitude", "X"))
        lat = safe_float(attr_value(attrs, "LAT", "LATITUDE", "RecAreaLatitude", "Y"))
    return lat, lon


def record_is_closed(text: str) -> bool:
    lower = clean(text).lower()
    return any(re.search(pattern, lower) for pattern in ACCESS_CLOSED_PATTERNS)


def collect_usfs_access(county_polygons: list[tuple[str, list[list[list[float]]]]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    features = arcgis_query_features(OFFICIAL_ACCESS_URLS["usfs_recreation_sites"])
    records: list[dict[str, Any]] = []
    for feature in features:
        attrs = feature.get("attributes") or {}
        site_type = clean(attr_value(attrs, "site_type", "site_subtype"))
        activities = clean(attr_value(attrs, "activity_type_list"))
        services = clean(attr_value(attrs, "service_type_list"))
        status = clean(attr_value(attrs, "seasonal_operational_status", "development_status", "op_status_reason"))
        relevant_blob = f"{site_type} {activities} {services}".lower()
        if not any(term in relevant_blob for term in ("fishing", "boating", "boat launch", "water access")):
            continue
        if record_is_closed(status):
            continue
        name = clean(attr_value(attrs, "public_site_name", "site_name", "recarea_name"))
        if not name:
            continue
        recarea = clean(attr_value(attrs, "recarea_name", "complex_name"))
        description = clean(attr_value(attrs, "recarea_description", "important_info", "directions"))
        lat, lon = feature_lon_lat(feature, attrs)
        county_hint = county_for_point(lon, lat, county_polygons) if valid_lon_lat(lon, lat) else ""
        if not county_hint:
            continue
        source_url = clean(attr_value(attrs, "usda_portal_url", "rec1stop_url")) or OFFICIAL_ACCESS_URLS["usfs_recreation_sites"]
        evidence = f"USFS public recreation record: site type {site_type or 'not listed'}; activities {activities or 'not listed'}; status {status or 'listed as active/public'}."
        records.append(make_access_record(
            water_hints=[name, recarea],
            access_point_name=name,
            source_name="USDA Forest Service",
            source_type="official_usfs_fishing_or_boating_site",
            official_source_url=source_url,
            verification_evidence=evidence,
            access_details=description or evidence,
            county_hint=county_hint,
            latitude=lat,
            longitude=lon,
            amenities={
                "camping": True if "camp" in relevant_blob else None,
                "restroom": True if any(term in relevant_blob for term in ("restroom", "toilet")) else None,
                "boat_ramp": True if any(term in relevant_blob for term in ("boat launch", "boating site", "boat ramp")) else None,
                "dock": True if any(term in relevant_blob for term in ("dock", "pier")) else None,
                "ada_fishing": True if any(term in relevant_blob for term in ("accessible", "ada")) else None,
            },
            current_status=status or "official_public_recreation_site",
        ))
    return records, {"usfs_features_checked": len(features), "usfs_access_records": len(records)}


def collect_blm_boat_ramps(county_polygons: list[tuple[str, list[list[list[float]]]]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    features = arcgis_query_features(OFFICIAL_ACCESS_URLS["blm_boat_ramps"])
    records: list[dict[str, Any]] = []
    for feature in features:
        attrs = feature.get("attributes") or {}
        if clean(attr_value(attrs, "ADMIN_ST")).upper() not in {"", "NV"}:
            continue
        if clean(attr_value(attrs, "WEB_DISPLAY")).upper() == "NO":
            continue
        name = clean(attr_value(attrs, "FET_NAME", "NAME"))
        subtype = clean(attr_value(attrs, "FET_SUBTYPE"))
        description = clean(attr_value(attrs, "DESCRIPTION"))
        if not name or record_is_closed(f"{name} {description}"):
            continue
        lat, lon = feature_lon_lat(feature, attrs)
        county_hint = county_for_point(lon, lat, county_polygons) if valid_lon_lat(lon, lat) else ""
        if not county_hint:
            continue
        source_url = clean(attr_value(attrs, "WEB_LINK")) or OFFICIAL_ACCESS_URLS["blm_boat_ramps"]
        evidence = f"BLM national recreation layer classifies this named point as {subtype or 'Boat Ramp'} and displays it for public recreation."
        records.append(make_access_record(
            water_hints=[name],
            access_point_name=name,
            source_name="Bureau of Land Management",
            source_type="official_blm_boat_ramp",
            official_source_url=source_url,
            verification_evidence=evidence,
            access_details=description or evidence,
            county_hint=county_hint,
            latitude=lat,
            longitude=lon,
            amenities={"camping": None, "restroom": None, "boat_ramp": True, "dock": None, "ada_fishing": None},
        ))
    return records, {"blm_ramp_features_checked": len(features), "blm_boat_ramp_records": len(records)}


def collect_blm_boating_sites(county_polygons: list[tuple[str, list[list[list[float]]]]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    features = arcgis_query_features(OFFICIAL_ACCESS_URLS["blm_boating_sites"])
    records: list[dict[str, Any]] = []
    for feature in features:
        attrs = feature.get("attributes") or {}
        state = clean(attr_value(attrs, "State"))
        if state and state.upper() not in {"NV", "NEVADA"}:
            continue
        name = clean(attr_value(attrs, "RecAreaName"))
        description = clean(attr_value(attrs, "RecAreaDescription"))
        activities = clean(attr_value(attrs, "ActivityNames", "Keywords"))
        if not name or record_is_closed(f"{name} {description}"):
            continue
        if not any(term in f"{activities} {description}".lower() for term in ("boating", "fishing", "boat", "water access")):
            continue
        lat, lon = feature_lon_lat(feature, attrs)
        county_hint = county_for_point(lon, lat, county_polygons) if valid_lon_lat(lon, lat) else ""
        if not county_hint:
            continue
        source_url = clean(attr_value(attrs, "BLMRecURL", "RecAreaMapURL")) or OFFICIAL_ACCESS_URLS["blm_boating_sites"]
        evidence = f"BLM Recreation Information Database lists this public recreation area with boating/fishing activity: {activities or 'boating layer classification'}."
        records.append(make_access_record(
            water_hints=[name],
            access_point_name=name,
            source_name="Bureau of Land Management",
            source_type="official_blm_boating_recreation_site",
            official_source_url=source_url,
            verification_evidence=evidence,
            access_details=description or evidence,
            county_hint=county_hint,
            latitude=lat,
            longitude=lon,
            amenities={
                "camping": True if "camp" in f"{activities} {description}".lower() else None,
                "restroom": True if any(term in description.lower() for term in ("restroom", "toilet")) else None,
                "boat_ramp": True if any(term in f"{activities} {description}".lower() for term in ("boat ramp", "boat launch")) else None,
                "dock": True if any(term in description.lower() for term in ("dock", "pier")) else None,
                "ada_fishing": True if any(term in description.lower() for term in ("accessible", "ada")) else None,
            },
        ))
    return records, {"blm_boating_features_checked": len(features), "blm_boating_access_records": len(records)}


def resolve_arcgis_item_layer(item_id: str, name_terms: tuple[str, ...]) -> str:
    item = request_json(f"https://www.arcgis.com/sharing/rest/content/items/{item_id}?f=json")
    service_url = clean(item.get("url"))
    if not service_url:
        raise RuntimeError(f"ArcGIS item {item_id} did not provide a service URL")
    root = request_json(service_url.rstrip("/") + "?f=json")
    layers = root.get("layers") or []
    for layer in layers:
        name = clean(layer.get("name")).lower()
        if all(term.lower() in name for term in name_terms) or any(term.lower() in name for term in name_terms):
            return service_url.rstrip("/") + f"/{layer['id']}"
    if len(layers) == 1:
        return service_url.rstrip("/") + f"/{layers[0]['id']}"
    if service_url.rstrip("/").lower().endswith(("/0", "/1", "/2", "/3")):
        return service_url.rstrip("/")
    raise RuntimeError(f"ArcGIS item {item_id} had no matching boat-ramp layer")


def collect_usbr_boat_ramps(county_polygons: list[tuple[str, list[list[list[float]]]]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    layer = resolve_arcgis_item_layer(OFFICIAL_ACCESS_URLS["usbr_boat_ramps_item"], ("boat", "ramp"))
    features = arcgis_query_features(layer)
    records: list[dict[str, Any]] = []
    for feature in features:
        attrs = feature.get("attributes") or {}
        name = clean(attr_value(attrs, "NAME", "RAMP_NAME", "BOAT_RAMP_NAME", "ASSET_NAME", "FACILITY_NAME"))
        reservoir = clean(attr_value(attrs, "RESERVOIR", "RESERVOIR_NAME", "WATERBODY", "WATER_NAME", "PROJECT_NAME"))
        status = clean(attr_value(attrs, "STATUS", "OPERATION_STATUS", "ACTIVE"))
        owner = clean(attr_value(attrs, "OWNER", "OPERATED_BY", "MANAGER"))
        if not name:
            name = f"{reservoir} boat ramp" if reservoir else "Bureau of Reclamation boat ramp"
        if record_is_closed(f"{name} {status}"):
            continue
        lat, lon = feature_lon_lat(feature, attrs)
        county_hint = county_for_point(lon, lat, county_polygons) if valid_lon_lat(lon, lat) else ""
        if not county_hint:
            continue
        details = clean(attr_value(attrs, "DESCRIPTION", "NOTES", "COMMENTS"))
        evidence = f"Bureau of Reclamation enterprise asset inventory identifies this point as a boat ramp. Status: {status or 'listed'}; manager: {owner or 'USBR/partner'}."
        records.append(make_access_record(
            water_hints=[reservoir, name],
            access_point_name=name,
            source_name="Bureau of Reclamation",
            source_type="official_usbr_boat_ramp_asset",
            official_source_url=f"https://www.arcgis.com/home/item.html?id={OFFICIAL_ACCESS_URLS['usbr_boat_ramps_item']}",
            verification_evidence=evidence,
            access_details=details or evidence,
            county_hint=county_hint,
            latitude=lat,
            longitude=lon,
            amenities={"camping": None, "restroom": None, "boat_ramp": True, "dock": None, "ada_fishing": None},
            current_status=status or "official_asset_inventory",
        ))
    return records, {"usbr_ramp_features_checked": len(features), "usbr_boat_ramp_records": len(records)}


WATER_MATCH_ALIASES = {
    "lake tahoe": ["sand harbor", "cave rock"],
    "lake mead": ["hemenway harbor", "callville bay", "echo bay", "boulder basin", "overton arm"],
    "lake mohave": ["cottonwood cove", "searchlight"],
    "lahontan reservoir": ["lahontan state recreation area"],
    "south fork reservoir": ["south fork state recreation area"],
    "wild horse reservoir": ["wild horse state recreation area"],
    "eagle valley reservoir": ["spring valley state park"],
    "rye patch reservoir": ["rye patch state recreation area"],
    "washoe lake": ["washoe lake state park", "north ramp", "south beach"],
    "little washoe lake": ["little washoe"],
}


def haversine_miles(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> float | None:
    if not valid_lon_lat(lon1, lat1) or not valid_lon_lat(lon2, lat2):
        return None
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 3958.7613 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def distinctive_tokens(value: str) -> set[str]:
    stop = {
        "lake", "reservoir", "pond", "river", "creek", "stream", "fork", "north", "south", "east", "west",
        "upper", "lower", "little", "big", "state", "park", "recreation", "area", "boat", "ramp", "launch",
        "fishing", "site", "public", "access", "the", "and", "at", "of",
    }
    return {token for token in norm(value).split() if token not in stop and len(token) >= 4}


def access_match_score(water: dict[str, Any], access: dict[str, Any]) -> tuple[int, float]:
    water_name = clean(water.get("water_name"))
    wnorm = norm(water_name)
    hints = access.get("water_hints") or []
    # Matching is intentionally limited to explicit water/site names. Official
    # descriptions and evidence may mention nearby waters, so they are never
    # allowed to create a publication match. Coordinates only break ties after
    # an explicit name/alias match and can never establish access by themselves.
    blob = norm(" ".join([
        *hints,
        access.get("access_point_name", ""),
    ]))
    score = 0
    for hint in hints:
        hnorm = norm(hint)
        if not hnorm:
            continue
        if hnorm == wnorm:
            score = max(score, 140)
        elif len(wnorm) >= 5 and re.search(rf"(?:^| ){re.escape(wnorm)}(?: |$)", hnorm):
            score = max(score, 125)
        elif len(hnorm) >= 5 and re.search(rf"(?:^| ){re.escape(hnorm)}(?: |$)", wnorm):
            if distinctive_tokens(hnorm) & distinctive_tokens(wnorm):
                score = max(score, 115)
    if wnorm and re.search(rf"(?:^| ){re.escape(wnorm)}(?: |$)", blob):
        score = max(score, 120)
    for alias in WATER_MATCH_ALIASES.get(wnorm, []):
        if norm(alias) in blob:
            score = max(score, 105)
    shared = distinctive_tokens(water_name) & distinctive_tokens(blob)
    if shared:
        score = max(score, 72 + min(18, 6 * len(shared)))
    county_hint = clean(access.get("county_hint"))
    if county_hint and county_hint in (water.get("counties") or []):
        score += 4
    distance = haversine_miles(water.get("latitude"), water.get("longitude"), access.get("latitude"), access.get("longitude"))
    if distance is not None:
        if distance <= 0.5:
            score += 8
        elif distance <= 2:
            score += 5
        elif distance <= 10:
            score += 2
    return score, distance if distance is not None else 99999.0


def public_point(access: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in access.items() if key not in {"water_hints", "county_hint"}}


def match_verified_access(
    waters: list[dict[str, Any]],
    access_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    by_water: dict[str, list[dict[str, Any]]] = defaultdict(list)
    orphan_access: list[dict[str, Any]] = []
    matched_access_ids: set[str] = set()

    for access in access_records:
        scored = []
        for water in waters:
            score, distance = access_match_score(water, access)
            if score >= 100:
                scored.append((score, -distance, clean(water.get("water_id")), water))
        if not scored:
            orphan_access.append(access)
            continue
        scored.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
        winner = scored[0][3]
        by_water[clean(winner.get("water_id"))].append(access)
        matched_access_ids.add(clean(access.get("access_id")))

    verified: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    verified_by_norm: dict[str, dict[str, Any]] = {}
    for base in waters:
        points = by_water.get(clean(base.get("water_id")), [])
        unique_points = {clean(point.get("access_id")): point for point in points if clean(point.get("access_id"))}
        points = sorted(unique_points.values(), key=lambda row: (clean(row.get("source_name")), clean(row.get("access_point_name"))))
        if not points:
            unverified.append({
                "water_id": base.get("water_id"),
                "water_name": base.get("water_name"),
                "counties": base.get("counties") or [],
                "latitude": base.get("latitude"),
                "longitude": base.get("longitude"),
                "species": base.get("species"),
                "fishnv_source_url": base.get("fishnv_source_url"),
                "publication_status": "quarantined_unverified_public_access",
                "reason": "NDOW identifies a fishable water, but no separate explicit official named public-access source matched it.",
            })
            continue
        row = dict(base)
        row["access_points"] = [public_point(point) for point in points]
        row["access_point_count"] = len(points)
        row["public_access_verification"] = sorted({clean(point.get("verification_method")) for point in points})
        row["official_access_source_url"] = clean(points[0].get("official_source_url"))
        row["access_details"] = clip(" | ".join(clean(point.get("access_details")) for point in points if clean(point.get("access_details"))), 1500)
        row["publication_status"] = "published_verified_public_access"
        verified.append(row)
        verified_by_norm[norm(row.get("water_name"))] = row

    # Critical resilience rule: a live official access page is sufficient to
    # publish its explicitly named water even when FishNV metadata cannot be
    # matched. FishNV remains metadata-only and unmatched FishNV records remain
    # quarantined. Only single-name, county-resolved official records may seed.
    seed_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for access in orphan_access:
        hints = [clean(value) for value in (access.get("water_hints") or []) if clean(value)]
        county = canonical_county(access.get("county_hint"))
        method = clean(access.get("verification_method"))
        if len(hints) != 1 or not county:
            continue
        if method not in {
            "official_state_access_page",
            "official_federal_access_page",
            "official_ndow_accessibility_table",
            "official_ndow_accessibility_live_text",
            "official_ndow_water_access_page",
        }:
            continue
        hint = hints[0]
        if water_type(hint) == "water" and len(distinctive_tokens(hint)) < 1:
            continue
        seed_groups[norm(hint)].append(access)

    seeded_count = 0
    seeded_access_ids: set[str] = set()
    for normalized_name, points in seed_groups.items():
        if not normalized_name:
            continue
        # Merge into a FishNV-matched verified row if one already exists.
        if normalized_name in verified_by_norm:
            row = verified_by_norm[normalized_name]
            merged = {
                clean(point.get("access_id")): point
                for point in [*(row.get("access_points") or []), *points]
                if clean(point.get("access_id"))
            }
            row["access_points"] = [public_point(point) for point in sorted(merged.values(), key=lambda x: clean(x.get("access_point_name")))]
            row["access_point_count"] = len(row["access_points"])
            row["public_access_verification"] = sorted({clean(point.get("verification_method")) for point in row["access_points"]})
            seeded_access_ids.update(clean(point.get("access_id")) for point in points)
            continue

        first = points[0]
        water_name = clean((first.get("water_hints") or [""])[0])
        county = canonical_county(first.get("county_hint"))
        if not water_name or not county:
            continue
        lat = next((safe_float(point.get("latitude")) for point in points if safe_float(point.get("latitude")) is not None), None)
        lon = next((safe_float(point.get("longitude")) for point in points if safe_float(point.get("longitude")) is not None), None)
        unique_points = {
            clean(point.get("access_id")): point for point in points if clean(point.get("access_id"))
        }
        public_points = [public_point(point) for point in sorted(unique_points.values(), key=lambda x: clean(x.get("access_point_name")))]
        row = {
            "water_id": water_id("official-access-seed", water_name, county),
            "county": county,
            "counties": [county],
            "county_number": COUNTY_NUMBER[county],
            "water_name": water_name,
            "water_type": water_type(water_name),
            "region": "",
            "latitude": lat if valid_lon_lat(lon, lat) else None,
            "longitude": lon if valid_lon_lat(lon, lat) else None,
            "species": "",
            "fishnv_source_url": "",
            "fishnv_page_id": "",
            "metadata_source": "official_named_public_access_source",
            "access_points": public_points,
            "access_point_count": len(public_points),
            "public_access_verification": sorted({clean(point.get("verification_method")) for point in public_points}),
            "official_access_source_url": clean(public_points[0].get("official_source_url")) if public_points else "",
            "access_details": clip(" | ".join(clean(point.get("access_details")) for point in public_points if clean(point.get("access_details"))), 1500),
            "publication_status": "published_verified_public_access",
        }
        verified.append(row)
        verified_by_norm[normalized_name] = row
        seeded_count += 1
        seeded_access_ids.update(unique_points)

    remaining_orphans = [
        access for access in orphan_access
        if clean(access.get("access_id")) not in seeded_access_ids
    ]
    verified.sort(key=lambda row: (COUNTY_NUMBER.get(clean(row.get("county")), 999), clean(row.get("water_name"))))
    return verified, unverified, remaining_orphans, {
        "verified_unique_waters": len(verified),
        "official_access_seeded_waters": seeded_count,
        "quarantined_fishnv_waters": len(unverified),
        "quarantined_unverified_waters": len(unverified),
        "orphan_official_access_records": len(remaining_orphans),
        "verified_access_points": sum(len(row.get("access_points") or []) for row in verified),
    }



def collect_all_verified_access(county_polygons: list[tuple[str, list[list[list[float]]]]]) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    collectors = [
        ("NDOW accessible-fishing table", collect_ndow_accessible_fishing),
        ("verified state/federal access pages", collect_verified_page_rules),
        ("USFS recreation sites", lambda: collect_usfs_access(county_polygons)),
        ("BLM boat ramps", lambda: collect_blm_boat_ramps(county_polygons)),
        ("BLM boating sites", lambda: collect_blm_boating_sites(county_polygons)),
        ("Bureau of Reclamation boat ramps", lambda: collect_usbr_boat_ramps(county_polygons)),
    ]
    records: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    warnings: list[str] = []
    for name, collector in collectors:
        try:
            result = collector()
            if len(result) == 3:
                rows, source_counts, source_warnings = result
                warnings.extend(source_warnings)
            else:
                rows, source_counts = result
            records.extend(rows)
            counts.update(source_counts)
            counts[f"source_success_{norm(name).replace(' ', '_')}"] = 1
        except Exception as exc:
            warnings.append(f"{name} unavailable: {exc}")
            counts[f"source_success_{norm(name).replace(' ', '_')}"] = 0
    unique = {clean(row.get("access_id")): row for row in records if clean(row.get("access_id"))}
    return list(unique.values()), counts, warnings


def run_self_tests() -> None:
    waters = [
        {
            "water_id": "lake-tahoe", "water_name": "Lake Tahoe", "counties": ["Washoe", "Douglas"],
            "county": "Washoe", "latitude": 39.1, "longitude": -120.0, "species": "trout",
            "fishnv_source_url": "https://www.fish.wildlifenv.com/waters/1", "water_type": "lake", "region": "Western",
        },
        {
            "water_id": "private-pond", "water_name": "Private Pond", "counties": ["Clark"],
            "county": "Clark", "latitude": 36.1, "longitude": -115.0, "species": "bass",
            "fishnv_source_url": "https://www.fish.wildlifenv.com/waters/2", "water_type": "pond", "region": "Southern",
        },
    ]
    access = [make_access_record(
        water_hints=["Lake Tahoe"], access_point_name="Sand Harbor public boat ramp",
        source_name="Nevada State Parks", source_type="official_state_access_page",
        official_source_url="https://parks.nv.gov/parks/lake-tahoe-nevada-state-park",
        verification_evidence="Official page explicitly lists fishing and a boat launch.",
        amenities={"camping": False, "restroom": True, "boat_ramp": True, "dock": True, "ada_fishing": None},
    )]
    verified, unverified, orphan, counts = match_verified_access(waters, access)
    assert [row["water_name"] for row in verified] == ["Lake Tahoe"]
    assert [row["water_name"] for row in unverified] == ["Private Pond"]
    assert orphan == []
    assert counts["verified_access_points"] == 1
    point = verified[0]["access_points"][0]
    assert point["public_access_status"] == "verified_public"
    assert point["official_source_url"].startswith("https://parks.nv.gov/")
    assert point["access_point_name"] != "FishNV mapped fishing location"
    assert "fishnv" not in point["verification_method"]

    fishnv_heading_sample = soup_for(
        "<html><head><title>FishNV | Find your next fishing spot.</title></head>"
        "<body><h1>FishNV</h1><h1>Lahontan Reservoir</h1>"
        "<h2>Species</h2><h2>Nearby Waters</h2></body></html>"
    )
    assert extract_fishnv_water_name(fishnv_heading_sample, []) == "Lahontan Reservoir", (
        "The FishNV brand heading must never replace the actual water name"
    )

    seed_access_1 = make_access_record(
        water_hints=["Cave Lake"],
        access_point_name="Cave Lake public fishing pier",
        source_name="Nevada State Parks",
        source_type="official_state_access_page",
        official_source_url="https://parks.nv.gov/parks/cave-lake",
        verification_evidence="Live official page verifies public fishing and shore access.",
        county_hint="White Pine",
    )
    seeded, quarantined, remaining, seeded_counts = match_verified_access([], [seed_access_1])
    assert len(seeded) == 1 and seeded[0]["water_name"] == "Cave Lake"
    assert seeded[0]["publication_status"] == "published_verified_public_access"
    assert seeded_counts["official_access_seeded_waters"] == 1
    assert not quarantined and not remaining

    nearby_only = make_access_record(
        water_hints=["Mountain Overlook"],
        access_point_name="Mountain Overlook",
        source_name="Official Agency",
        source_type="official_test_site",
        official_source_url="https://example.gov/official-site",
        verification_evidence="This overlook is near Lake Tahoe but is not a named Lake Tahoe access site.",
        access_details="Views of nearby Lake Tahoe.",
    )
    score, _ = access_match_score(waters[0], nearby_only)
    assert score < 100, "Nearby-water descriptive text must never establish public access"
    ndow_sample = soup_for("""
    <html><body><main><h1>Lahontan Reservoir</h1>
    <a href='https://www.fish.wildlifenv.com/waters/4001'>View Map</a>
    <div>Region Western County Churchill Type of water Lake or Reservoir</div>
    <h2>Pertinent Information</h2><p>Lahontan Reservoir is entirely located within Lahontan State Park.
    Camping, restrooms, picnic tables, and boat launching facilities are available.</p>
    <h2>Other Bodies of Water</h2><a href='/waters/other-water/'>Other Water</a></main></body></html>
    """)
    sample_visible, sample_head = ndow_water_head(ndow_sample)
    sample_records = ndow_page_access_records(
        water_name="Lahontan Reservoir", county="Churchill",
        page_url="https://www.ndow.org/waters/lahontan-reservoir/",
        head_text=sample_head, latitude=None, longitude=None,
    )
    assert sample_records, "Explicit NDOW state-park and boat-launch language must create access evidence"
    assert any("Lahontan State Park" in row["access_point_name"] for row in sample_records)
    assert all(row["verification_method"] == "official_ndow_water_access_page" for row in sample_records)
    assert "Other Water" not in sample_head, "Related-water text must not contaminate the current water parser"

    weak_sample = "Fishing has been good. Shoreline vegetation is dense."
    assert not ndow_page_access_records(
        water_name="Test Pond", county="Clark", page_url="https://www.ndow.org/waters/test-pond/",
        head_text=weak_sample, latitude=None, longitude=None,
    ), "Fishing conditions alone must never prove public access"

    print("Nevada strict public-access self-tests passed.")

def option_water_candidates(soup: Any, base_url: str) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    urls: set[str] = set()
    for select in soup.find_all("select"):
        select_blob = norm(" ".join(filter(None, [select.get("name"), select.get("id"), select.get("aria-label")])))
        options = select.find_all("option")
        values = [clean(option.get_text(" ", strip=True)) for option in options]
        if "water" not in select_blob and sum(1 for value in values if water_type(value) != "water") < 20:
            continue
        for option in options:
            label = clean(option.get_text(" ", strip=True))
            value = clean(option.get("value"))
            if not label or label.lower() in {"body of water", "all bodies of water", "all waters", "select"}:
                continue
            names.add(label)
            if re.search(r"/waters/\d+", value):
                urls.add(canonical_url(value, base_url).rstrip("/"))
            elif value.isdigit():
                urls.add(canonical_url(f"/waters/{value}", OFFICIAL_URLS["fishnv"]).rstrip("/"))
    return names, urls


def card_report_candidates(soup: Any, page_url: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    generic = {
        "fishing hot spots", "fishing reports", "stocking updates", "fishnv tool",
        "fishing & stocking reports database", "calendar", "search",
    }
    for heading in soup.find_all(re.compile(r"^h[2-6]$")):
        name = clean(heading.get_text(" ", strip=True))
        if not name or norm(name) in generic or len(name) > 160:
            continue
        parent = heading
        for _ in range(4):
            if parent.parent is None:
                break
            candidate = clean(parent.parent.get_text(" ", strip=True))
            if re.search(r"Fishing Report|Stocking Update|Stocked:", candidate, flags=re.I) and len(candidate) < 5000:
                parent = parent.parent
                break
            parent = parent.parent
        text = clean(parent.get_text(" ", strip=True))
        kind_match = re.search(r"\b(Fishing Report|Stocking Update)\b", text, flags=re.I)
        stocked_match = re.search(r"\bStocked:\s*([^|]{1,160})", text, flags=re.I)
        if not kind_match and not stocked_match:
            continue
        date_match = re.search(r"\b(?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])[-/](?:20\d{2}|\d{2})\b", text)
        report_date = parse_date(date_match.group(0) if date_match else text)
        link = ""
        anchor = heading.find("a", href=True) or parent.find("a", href=True)
        if anchor:
            link = canonical_url(anchor.get("href"), page_url)
        if not link:
            link = canonical_url(page_url)
        summary = text
        summary = re.sub(re.escape(name), "", summary, count=1, flags=re.I).strip(" -|:")
        summary = re.sub(r"\b(?:Fishing Report|Stocking Update)\b", "", summary, count=1, flags=re.I).strip(" -|:")
        source_type = "official_stocking_update" if (kind_match and "stock" in kind_match.group(1).lower()) or stocked_match else "official_fishing_report"
        results.append(make_report(
            source_type=source_type,
            source_name="Nevada Department of Wildlife",
            source_url=link,
            title=f"{name} — {'Stocking Update' if source_type.endswith('stocking_update') else 'Fishing Report'}",
            summary=summary,
            report_date=report_date,
            water_name=name,
            species=stocked_match.group(1) if stocked_match else "",
        ))
    return results



NDOW_WATER_HOSTS = {"ndow.org", "www.ndow.org"}
NDOW_WATER_SITEMAP_CANDIDATES = (
    "https://www.ndow.org/wp-sitemap-posts-waters-1.xml",
    "https://www.ndow.org/wp-sitemap.xml",
    "https://www.ndow.org/waters-sitemap.xml",
)


def extract_ndow_water_urls(text: str, base_url: str = "https://www.ndow.org/") -> set[str]:
    """Extract only NDOW /waters/<slug>/ detail URLs."""
    urls: set[str] = set()
    soup = soup_for(text)
    candidates = [clean(anchor.get("href")) for anchor in soup.find_all("a", href=True)]
    candidates.extend(re.findall(r"https?://(?:www\.)?ndow\.org/waters/[a-z0-9][a-z0-9\-]*/?", text, flags=re.I))
    candidates.extend(re.findall(r"(?:href=[\"']?)?(/waters/[a-z0-9][a-z0-9\-]*/?)", text, flags=re.I))
    for value in candidates:
        url = canonical_url(value, base_url)
        parts = urlsplit(url)
        if parts.netloc not in NDOW_WATER_HOSTS:
            continue
        if not re.fullmatch(r"/waters/[a-z0-9][a-z0-9\-]*/?", parts.path, flags=re.I):
            continue
        urls.add(url.rstrip("/") + "/")
    return urls


def ndow_water_head(soup: Any) -> tuple[str, str]:
    """Return full visible text and the water-specific section before related waters."""
    scope = soup.find("main") or soup.find("article") or soup
    visible = clean(scope.get_text(" ", strip=True))
    head = re.split(r"\bOther Bodies of Water\b|\bRelated Waters\b", visible, maxsplit=1, flags=re.I)[0]
    return visible, head[:30000]


def labeled_value(text: str, label: str, stop_labels: tuple[str, ...]) -> str:
    stops = "|".join(re.escape(item) for item in stop_labels)
    match = re.search(rf"\b{re.escape(label)}\s+(.+?)(?=\s+(?:{stops})\b|$)", text, flags=re.I)
    return clean(match.group(1)) if match else ""


NEVADA_FISH_NAMES = (
    "Rainbow Trout", "Brown Trout", "Brook Trout", "Cutthroat Trout", "Lahontan Cutthroat Trout",
    "Tiger Trout", "Lake Trout", "Mackinaw", "Kokanee Salmon", "Channel Catfish", "White Catfish",
    "Largemouth Bass", "Smallmouth Bass", "Spotted Bass", "White Bass", "Striped Bass", "Wiper",
    "Bluegill", "Green Sunfish", "Sacramento Perch", "Yellow Perch", "Crappie", "White Crappie",
    "Black Crappie", "Walleye", "Carp", "Brown Bullhead", "Tiger Muskie", "Northern Pike",
    "Mountain Whitefish", "Redband Trout", "Bull Trout", "Tui Chub",
)


def ndow_species_from_text(text: str) -> list[str]:
    lower = text.lower()
    found = {name for name in NEVADA_FISH_NAMES if re.search(rf"\b{re.escape(name.lower())}\b", lower)}
    return sorted(found)


def ndow_access_excerpt(text: str) -> str:
    signals = (
        "public access", "public land", "state park", "state recreation area", "national recreation area",
        "wildlife management area", "national wildlife refuge", "recreation site", "boat ramp", "launch ramp",
        "boat launch", "fishing pier", "shore access", "access sites", "campground", "camping is allowed",
        "restrooms", "picnic areas", "managed by",
    )
    compact = clean(text)
    lower = compact.lower()
    positions = [lower.find(signal) for signal in signals if lower.find(signal) >= 0]
    if not positions:
        return ""
    start = max(0, min(positions) - 220)
    return clip(compact[start:start + 1400], 1400)


def named_access_facilities(text: str, water_name: str) -> list[str]:
    """Extract explicit named facilities from NDOW's own access description."""
    suffix = (
        r"State Recreation Area|State Park|National Recreation Area|National Wildlife Refuge|"
        r"Wildlife Management Area|Recreation Site|Campground|Marina|Harbor|Boat Ramp|"
        r"Launch Ramp|Fishing Pier|Beach|Cove|Park"
    )
    pattern = re.compile(
        rf"\b([A-Z][A-Za-z0-9’'&.\-/]*(?:\s+(?:[A-Z][A-Za-z0-9’'&.\-/]*|of|the|and)){{0,7}}\s+(?:{suffix}))\b"
    )
    excluded = {
        "Nevada Department of Wildlife", "Bureau of Land Management", "United States Forest Service",
        "U S Forest Service", "National Park Service", "Nevada Division of State Parks",
    }
    names = []
    for match in pattern.finditer(text):
        value = clean(match.group(1)).strip(" ,.;:")
        if value and value not in excluded and len(value) <= 100:
            names.append(value)

    # Named lists after access/facility phrases often omit a suffix, e.g.
    # "developed campgrounds occur at Boulder Beach, Callville Bay, and Echo Bay."
    list_pattern = re.compile(
        r"(?:campgrounds?|marinas?|launch ramps?|boat ramps?|access sites?|launching facilities)"
        r"[^.;]{0,80}?\b(?:at|include|in|are available at)\s+([^.;]{3,220})",
        flags=re.I,
    )
    for match in list_pattern.finditer(text):
        blob = re.sub(r"\([^)]*\)", "", match.group(1))
        for part in re.split(r",|\band\b|\bor\b", blob, flags=re.I):
            value = clean(part).strip(" ,.;:")
            value = re.sub(r"^(?:the|in|at)\s+", "", value, flags=re.I)
            if 2 <= len(value) <= 80 and re.search(r"[A-Z]", value) and not re.search(r"temperatures|water|trash|sanitation|facilities$", value, flags=re.I):
                names.append(value)

    # Deduplicate while preserving order.
    result: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result[:12]


def ndow_page_access_records(
    *, water_name: str, county: str, page_url: str, head_text: str,
    latitude: float | None, longitude: float | None,
) -> list[dict[str, Any]]:
    """Create access evidence only from explicit, named NDOW access language."""
    lower = head_text.lower()
    public_context = any(term in lower for term in (
        "public access", "public land", "state park", "state recreation area", "national recreation area",
        "wildlife management area", "national wildlife refuge", "recreation site", "u.s. forest service",
        "us forest service", "bureau of land management", " blm ", "managed by nevada division of state parks",
    ))
    facility_context = any(term in lower for term in (
        "boat ramp", "launch ramp", "boat launch", "boat launching", "fishing pier", "shore access",
        "access sites", "campground", "camping is allowed", "restrooms", "picnic areas", "marina",
    ))
    waterwide_public = any(term in lower for term in (
        "lies entirely on public land", "located entirely on public land", "entirely located within",
        "entirely within a state park", "entirely within the state park",
    ))
    facilities = named_access_facilities(head_text, water_name)
    if not facilities and not ((public_context and facility_context) or waterwide_public):
        return []

    if not facilities:
        if "boat ramp" in lower or "launch ramp" in lower or "boat launching" in lower:
            facilities = [f"{water_name} boat-launch access"]
        elif "fishing pier" in lower:
            facilities = [f"{water_name} fishing pier"]
        elif "shore access" in lower:
            facilities = [f"{water_name} shoreline access"]
        elif "public land" in lower:
            facilities = [f"{water_name} public-land sections"]
        else:
            facilities = [f"{water_name} public recreation access"]

    excerpt = ndow_access_excerpt(head_text)
    amenities = {
        "camping": True if re.search(r"\bcamp(?:ing|ground|sites?)\b", lower) else None,
        "restroom": True if re.search(r"\brestrooms?|bathroom facilities|toilets?\b", lower) else None,
        "boat_ramp": True if re.search(r"\bboat (?:launch(?:ing)?|ramp)|launch ramps?\b", lower) else None,
        "dock": True if re.search(r"\bdocks?\b", lower) else None,
        "ada_fishing": True if re.search(r"\baccessible fishing|ada fishing|wheelchair.{0,30}(?:pier|platform|fishing)\b", lower) else None,
    }
    rows = []
    for facility in facilities:
        rows.append(make_access_record(
            water_hints=[water_name],
            access_point_name=facility,
            source_name="Nevada Department of Wildlife",
            source_type="official_ndow_water_access_page",
            official_source_url=page_url,
            verification_evidence=excerpt or f"NDOW's official {water_name} page explicitly identifies this public recreation access.",
            access_details=excerpt,
            county_hint=county,
            latitude=latitude,
            longitude=longitude,
            amenities=amenities,
            current_status="verify_current_conditions_before_travel",
        ))
    return rows


def parse_ndow_water_page(
    url: str,
    county_polygons: list[tuple[str, list[list[list[float]]]]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], set[str], str]:
    """Parse one server-rendered NDOW water page and its explicit access evidence."""
    try:
        raw = request_text(url)
    except RuntimeError as exc:
        return None, [], set(), str(exc)
    soup = soup_for(raw)
    children = extract_ndow_water_urls(raw, url)
    visible, head = ndow_water_head(soup)
    heading = soup.find("h1")
    name = clean(heading.get_text(" ", strip=True)) if heading else ""
    if not name:
        return None, [], children, f"NDOW water page did not expose a water name: {url}"

    county = ""
    county_match = re.search(
        r"\bCounty\s+(Carson City|Churchill|Clark|Douglas|Elko|Esmeralda|Eureka|Humboldt|Lander|Lincoln|Lyon|Mineral|Nye|Pershing|Storey|Washoe|White Pine)\b",
        head,
        flags=re.I,
    )
    if county_match:
        county = canonical_county(county_match.group(1))

    objects = structured_objects(soup)
    lat, lon = first_coordinate_pair(objects, head)
    if not county and valid_lon_lat(lon, lat):
        county = county_for_point(lon, lat, county_polygons)
    if not county:
        return None, [], children, f"NDOW water page could not be assigned to a Nevada county: {name} ({url})"

    region_match = re.search(r"\bRegion\s+(Eastern|Southern|Western)\b", head, flags=re.I)
    region = region_match.group(1).title() if region_match else ""
    type_match = re.search(
        r"\bType of water\s+(.+?)(?=\s+(?:Fishing Report|Stocking Updates?|Pertinent Information|Other Bodies of Water)\b|$)",
        head,
        flags=re.I,
    )
    type_text = clean(type_match.group(1)) if type_match else ""

    fishnv_url = ""
    for anchor in soup.find_all("a", href=True):
        href = canonical_url(anchor.get("href"), url)
        if urlsplit(href).netloc in FISHNV_HOSTS and re.search(r"/waters/\d+/?", urlsplit(href).path):
            fishnv_url = href.rstrip("/")
            break

    species = ndow_species_from_text(head)
    water = {
        "water_id": water_id("ndow-water-page", url, name),
        "county": county,
        "counties": [county],
        "county_number": COUNTY_NUMBER[county],
        "water_name": name,
        "water_type": water_type(name, type_text),
        "region": region,
        "latitude": lat,
        "longitude": lon,
        "species": ", ".join(species),
        "fishnv_source_url": fishnv_url,
        "fishnv_page_id": re.search(r"/waters/(\d+)", fishnv_url).group(1) if re.search(r"/waters/(\d+)", fishnv_url) else "",
        "ndow_water_source_url": canonical_url(url),
        "metadata_source": "official_ndow_server_rendered_water_page",
        "access_points": [],
    }
    access = ndow_page_access_records(
        water_name=name,
        county=county,
        page_url=canonical_url(url),
        head_text=head,
        latitude=lat,
        longitude=lon,
    )
    return water, access, children, ""


def collect_ndow_water_inventory(
    report_html_pages: Iterable[str],
    reports: Iterable[dict[str, Any]],
    county_polygons: list[tuple[str, list[list[list[float]]]]],
    workers: int = 12,
    max_pages: int = 750,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], dict[str, int]]:
    """Crawl NDOW's official water pages, including related-water links."""
    queue: set[str] = set()
    for raw in report_html_pages:
        queue.update(extract_ndow_water_urls(raw, OFFICIAL_URLS["reports"]))
    for report in reports:
        source = canonical_url(report.get("source_url", ""))
        if urlsplit(source).netloc in NDOW_WATER_HOSTS and re.fullmatch(r"/waters/[a-z0-9][a-z0-9\-]*/?", urlsplit(source).path, flags=re.I):
            queue.add(source.rstrip("/") + "/")

    sitemap_checked = 0
    sitemap_failures = 0
    for sitemap_url in NDOW_WATER_SITEMAP_CANDIDATES:
        try:
            xml = request_text(sitemap_url, retries=2)
            sitemap_checked += 1
            for loc in xml_locs(xml):
                queue.update(extract_ndow_water_urls(loc, sitemap_url))
            queue.update(extract_ndow_water_urls(xml, sitemap_url))
        except RuntimeError:
            sitemap_failures += 1

    seen: set[str] = set()
    waters: list[dict[str, Any]] = []
    access_records: list[dict[str, Any]] = []
    warnings: list[str] = []
    while queue and len(seen) < max_pages:
        batch = sorted(queue - seen)[: max(1, min(workers, 24)) * 3]
        if not batch:
            break
        seen.update(batch)
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 24))) as executor:
            futures = {executor.submit(parse_ndow_water_page, url, county_polygons): url for url in batch}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    water, page_access, children, error = future.result()
                except Exception as exc:
                    water, page_access, children, error = None, [], set(), f"{url}: {exc}"
                queue.update(child for child in children if child not in seen)
                if water:
                    waters.append(water)
                    access_records.extend(page_access)
                elif error:
                    warnings.append(error)

    # Deduplicate canonical NDOW pages and exact county/name records.
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for water in waters:
        key = (clean(water.get("county")), norm(water.get("water_name")))
        if key[0] and key[1]:
            existing = unique.get(key)
            if not existing or (not existing.get("fishnv_source_url") and water.get("fishnv_source_url")):
                unique[key] = water
    waters = sorted(unique.values(), key=lambda row: (COUNTY_NUMBER.get(row.get("county"), 999), clean(row.get("water_name"))))
    access_unique = {clean(row.get("access_id")): row for row in access_records if clean(row.get("access_id"))}
    represented_counties = {clean(row.get("county")) for row in waters if clean(row.get("county"))}
    return waters, list(access_unique.values()), warnings, {
        "ndow_water_seed_urls": len({url for url in seen if url}),
        "ndow_water_pages_requested": len(seen),
        "ndow_water_metadata_records": len(waters),
        "ndow_water_metadata_counties": len(represented_counties),
        "ndow_water_page_access_records": len(access_unique),
        "ndow_water_unresolved_pages": len(warnings),
        "ndow_water_sitemaps_checked": sitemap_checked,
        "ndow_water_sitemap_failures": sitemap_failures,
        "fishnv_map_links_from_ndow": sum(bool(row.get("fishnv_source_url")) for row in waters),
    }

def collect_ndow_reports() -> tuple[list[dict[str, Any]], set[str], list[str], dict[str, int]]:
    reports: list[dict[str, Any]] = []
    water_names: set[str] = set()
    fishnv_urls: set[str] = set()
    html_pages: list[str] = []
    queue = [OFFICIAL_URLS["reports"]]
    seen: set[str] = set()

    while queue and len(seen) < 25:
        url = canonical_url(queue.pop(0))
        if url in seen:
            continue
        seen.add(url)
        raw = request_text(url)
        html_pages.append(raw)
        soup = soup_for(raw)
        names, urls = option_water_candidates(soup, url)
        water_names.update(names)
        fishnv_urls.update(urls)
        fishnv_urls.update(extract_water_urls(raw, url))
        reports.extend(card_report_candidates(soup, url))
        for anchor in soup.find_all("a", href=True):
            label = norm(anchor.get_text(" ", strip=True))
            href = canonical_url(anchor.get("href"), url)
            if urlsplit(href).netloc == urlsplit(OFFICIAL_URLS["reports_root"]).netloc and (
                label in {"next", "next »"} or re.search(r"/page/\d+", href) or "paged=" in href
            ):
                if href not in seen:
                    queue.append(href)

    unique: dict[str, dict[str, Any]] = {}
    for report in reports:
        unique[report["report_id"]] = report
    reports = sorted(
        unique.values(),
        key=lambda row: (clean(row.get("report_date")), clean(row.get("title"))),
        reverse=True,
    )
    return reports, water_names, html_pages, {
        "ndow_report_pages": len(seen),
        "ndow_report_records": len(reports),
        "ndow_water_filter_names": len(water_names),
        "ndow_direct_fishnv_links": len(fishnv_urls),
        "direct_urls": fishnv_urls,
    }


def attach_report_counties(reports: list[dict[str, Any]], waters: list[dict[str, Any]]) -> None:
    exact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for water in waters:
        exact[norm(water.get("water_name"))].append(water)
    for report in reports:
        key = norm(report.get("water_name"))
        candidates = exact.get(key, [])
        if not candidates and key:
            for water_key, rows in exact.items():
                if key == water_key or (len(key) >= 8 and (key in water_key or water_key in key)):
                    candidates.extend(rows)
        report["counties"] = sorted(
            {county for water in candidates for county in (water.get("counties") or [water.get("county")]) if county},
            key=lambda c: COUNTY_NUMBER.get(c, 999),
        )


def dedupe_reports(reports: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for report in reports:
        unique[clean(report.get("report_id")) or report_id(report)] = report
    return sorted(
        unique.values(),
        key=lambda row: (clean(row.get("report_date")), clean(row.get("title"))),
        reverse=True,
    )


def build_database(
    waters: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    generated_at: str,
    audit: dict[str, Any],
) -> dict[str, Any]:
    attach_report_counties(reports, waters)
    reports_by_water: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        reports_by_water[norm(report.get("water_name"))].append(report)

    county_blocks: list[dict[str, Any]] = []
    flat_waters: list[dict[str, Any]] = []
    for number, county in enumerate(COUNTIES, start=1):
        county_waters: list[dict[str, Any]] = []
        for base in sorted(waters, key=lambda row: clean(row.get("water_name"))):
            if county not in (base.get("counties") or [base.get("county")]):
                continue
            candidates = dedupe_reports(reports_by_water.get(norm(base.get("water_name")), []))
            latest = candidates[0] if candidates else None
            row = dict(base)
            row["county"] = county
            row["county_number"] = number
            row["public_access_verification"] = "; ".join(row.get("public_access_verification") or [])
            row.update({
                "access_point_count": len(row.get("access_points") or []),
                "report_status": latest.get("freshness") if latest else "no_recent_public_report_found",
                "latest_report": latest,
                "recent_reports": candidates[:10],
                "report_count": len(candidates),
            })
            county_waters.append(row)
            flat_waters.append(row)
        county_reports = [report for report in reports if county in (report.get("counties") or [])]
        county_blocks.append({
            "county_number": number,
            "county": county,
            "public_water_count": len(county_waters),
            "waters_with_reports": sum(1 for water in county_waters if water["report_count"] > 0),
            "waters_without_reports": sum(1 for water in county_waters if water["report_count"] == 0),
            "public_access_point_count": sum(water["access_point_count"] for water in county_waters),
            "county_report_count": len(county_reports),
            "waters": county_waters,
        })

    matched_ids = {
        report["report_id"]
        for water in flat_waters
        for report in (water.get("recent_reports") or [])
    }
    unmatched_reports = [report for report in reports if report["report_id"] not in matched_ids]
    statewide_reports = [report for report in reports if not report.get("counties")]
    unique_water_count = len({clean(water.get("water_id")) for water in waters})
    unique_access_count = len({
        clean(point.get("access_id"))
        for water in waters
        for point in (water.get("access_points") or [])
        if clean(point.get("access_id"))
    })

    return {
        "metadata": {
            "state": STATE,
            "title": "Nevada Independently Verified Public Fishing Access and Current Fishing Reports",
            "version": "3.0-ndow-complete-inventory-strict-access",
            "generated_at": generated_at,
            "public_access_only": True,
            "fishnv_is_access_verification": False,
            "county_order": "1 Carson City through 17 White Pine",
            "access_policy": (
                "NDOW server-rendered water pages supply the statewide water name, county, type, report context and optional FishNV map link. "
                "FishNV is never accepted as access verification. A water is published only when an explicit named public-access facility or area "
                "is verified by an official NDOW access statement, Nevada State Parks page, National Park Service page, BLM recreation dataset, "
                "USDA Forest Service recreation dataset, or Bureau of Reclamation boat-ramp dataset. Waters without explicit access evidence are "
                "quarantined and never displayed as public access. A verified facility still does not make every shoreline or neighboring parcel public; "
                "anglers must follow posted signs, current closures, tribal rules and fishing regulations."
            ),
            "sources": [
                {"name": "NDOW official water pages", "type": "official_water_metadata", "url": OFFICIAL_URLS["reports"]},
                {"name": "FishNV optional map links (not access verification)", "type": "official_map_link", "url": OFFICIAL_URLS["fishnv"]},
                {"name": "NDOW Accessible Fishing in Nevada", "type": "official_access", "url": OFFICIAL_ACCESS_URLS["ndow_accessible_fishing"]},
                {"name": "Nevada State Parks named access pages", "type": "official_access", "url": "https://parks.nv.gov/parks"},
                {"name": "National Park Service Lake Mead access pages", "type": "official_access", "url": OFFICIAL_ACCESS_URLS["nps_lake_mead_fishing"]},
                {"name": "USDA Forest Service recreation sites", "type": "official_access", "url": OFFICIAL_ACCESS_URLS["usfs_recreation_sites"]},
                {"name": "BLM boat ramps and boating sites", "type": "official_access", "url": OFFICIAL_ACCESS_URLS["blm_boat_ramps"]},
                {"name": "Bureau of Reclamation boat-ramp assets", "type": "official_access", "url": f"https://www.arcgis.com/home/item.html?id={OFFICIAL_ACCESS_URLS['usbr_boat_ramps_item']}"},
                {"name": "NDOW Fishing and Stocking Reports Database", "type": "official_report", "url": OFFICIAL_URLS["reports"]},
                {"name": "Nevada DOT county boundaries", "type": "official_boundary", "url": OFFICIAL_URLS["county_layer"]},
            ],
        },
        "county_count": 17,
        "public_water_count": unique_water_count,
        "county_linked_water_record_count": len(flat_waters),
        "verified_access_point_count": unique_access_count,
        "unverified_fishable_water_count": int(audit.get("matching", {}).get("quarantined_fishnv_waters", 0)),
        "report_count": len(reports),
        "statewide_reports": statewide_reports[:100],
        "unmatched_reports": unmatched_reports,
        "counties": county_blocks,
        "flat_waters": flat_waters,
        "flat_reports": reports,
    }

def validate_map_data(db: dict[str, Any]) -> dict[str, int]:
    invalid_coordinates: list[str] = []
    invalid_urls: list[str] = []
    water_coordinate_count = 0
    access_coordinate_count = 0
    for water in db.get("flat_waters") or []:
        label = f"{clean(water.get('county'))}: {clean(water.get('water_name'))}"
        lat, lon = water.get("latitude"), water.get("longitude")
        has_lat, has_lon = lat not in (None, ""), lon not in (None, "")
        if has_lat != has_lon:
            invalid_coordinates.append(f"{label} has only one coordinate")
        elif has_lat:
            if not valid_lon_lat(lon, lat):
                invalid_coordinates.append(f"{label} has out-of-Nevada coordinates {lat},{lon}")
            else:
                water_coordinate_count += 1
        for point in water.get("access_points") or []:
            plat, plon = point.get("latitude"), point.get("longitude")
            has_plat, has_plon = plat not in (None, ""), plon not in (None, "")
            if has_plat != has_plon:
                invalid_coordinates.append(f"{label} access point has only one coordinate")
            elif has_plat:
                if not valid_lon_lat(plon, plat):
                    invalid_coordinates.append(f"{label} access point has invalid coordinates {plat},{plon}")
                else:
                    access_coordinate_count += 1
            url = clean(point.get("directions_url")).lower().replace("%2c", ",")
            if any(token in url for token in ("query=null", "query=undefined", "query=0,0", "query=,")):
                invalid_urls.append(f"{label}: {url}")
    if invalid_coordinates or invalid_urls:
        raise RuntimeError(
            "Nevada map validation failed: "
            + "; ".join((invalid_coordinates + invalid_urls)[:20])
        )
    return {
        "water_coordinate_count": water_coordinate_count,
        "access_coordinate_count": access_coordinate_count,
    }


def validate_build(db: dict[str, Any], source_counts: dict[str, int], audit: dict[str, Any]) -> dict[str, Any]:
    counties = db.get("counties") or []
    if db.get("county_count") != 17 or len(counties) != 17:
        raise RuntimeError("Nevada database did not create all 17 county/county-equivalent shells")
    if [row.get("county") for row in counties] != COUNTIES:
        raise RuntimeError("Nevada county order is not Carson City through White Pine")
    if int(source_counts.get("county_polygons", 0)) != 17:
        raise RuntimeError("Nevada official county polygon source did not return all 17 county-equivalents")

    metadata_records = int(source_counts.get("ndow_water_metadata_records", 0) or 0)
    metadata_counties = int(source_counts.get("ndow_water_metadata_counties", 0) or 0)
    pages_requested = int(source_counts.get("ndow_water_pages_requested", 0) or 0)
    unresolved_pages = int(source_counts.get("ndow_water_unresolved_pages", 0) or 0)
    if pages_requested < MIN_NDOW_WATER_PAGES:
        raise RuntimeError(f"NDOW water discovery reached only {pages_requested} water pages; expected at least {MIN_NDOW_WATER_PAGES}")
    if metadata_records < MIN_NDOW_METADATA_RECORDS:
        raise RuntimeError(f"NDOW water parser produced only {metadata_records} metadata records; expected at least {MIN_NDOW_METADATA_RECORDS}")
    if metadata_counties != 17:
        raise RuntimeError(f"NDOW water metadata represents only {metadata_counties} of 17 Nevada county-equivalents")
    allowed_unresolved = max(25, int(pages_requested * 0.15))
    if unresolved_pages > allowed_unresolved:
        raise RuntimeError(
            f"NDOW water parser left {unresolved_pages} of {pages_requested} pages unresolved; maximum allowed is {allowed_unresolved}"
        )

    unique_water_count = int(db.get("public_water_count", 0) or 0)
    access_count = int(db.get("verified_access_point_count", 0) or 0)
    report_count = int(db.get("report_count", 0) or 0)
    if unique_water_count < MIN_VERIFIED_PUBLIC_WATERS:
        raise RuntimeError(f"Strict verification produced only {unique_water_count} independently verified public waters")
    if access_count < MIN_VERIFIED_ACCESS_POINTS:
        raise RuntimeError(f"Strict verification produced only {access_count} official public access points")
    if report_count < MIN_OFFICIAL_REPORTS:
        raise RuntimeError(f"Nevada build produced only {report_count} official report/update records")

    bad_points: list[str] = []
    source_methods: set[str] = set()
    unique_seen: set[str] = set()
    for water in db.get("flat_waters") or []:
        wid = clean(water.get("water_id"))
        if wid in unique_seen:
            continue
        unique_seen.add(wid)
        points = water.get("access_points") or []
        if not points:
            bad_points.append(f"{water.get('water_name')}: no verified access points")
        for point in points:
            method = clean(point.get("verification_method"))
            source_methods.add(method)
            if point.get("public_access_status") != "verified_public":
                bad_points.append(f"{water.get('water_name')}: non-verified status")
            if not clean(point.get("official_source_url")):
                bad_points.append(f"{water.get('water_name')}: missing official source URL")
            if not clean(point.get("verification_evidence")):
                bad_points.append(f"{water.get('water_name')}: missing evidence")
            if clean(point.get("access_point_name")).lower() == "fishnv mapped fishing location":
                bad_points.append(f"{water.get('water_name')}: forbidden generic FishNV access point")
            if "fishnv" in method.lower():
                bad_points.append(f"{water.get('water_name')}: FishNV used as access verification")
    if bad_points:
        raise RuntimeError("Strict public-access validation failed: " + "; ".join(bad_points[:20]))
    if len(source_methods) < 2:
        raise RuntimeError(f"Only {len(source_methods)} independent access-verification method was used")

    populated_counties = sum(1 for county in counties if int(county.get("public_water_count", 0) or 0) > 0)
    missing_public_counties = [county.get("county") for county in counties if int(county.get("public_water_count", 0) or 0) == 0]
    if populated_counties < MIN_POPULATED_COUNTIES:
        raise RuntimeError(
            f"Verified public-access results cover only {populated_counties} county-equivalents; "
            f"expected at least {MIN_POPULATED_COUNTIES}. Empty desert counties are allowed when no named official access is verified. "
            f"Currently empty: {missing_public_counties}"
        )
    map_counts = validate_map_data(db)
    return {
        "passed": True,
        "complete_inventory_gate": True,
        "strict_public_access": True,
        "fishnv_is_access_verification": False,
        "ndow_water_metadata_records": metadata_records,
        "ndow_water_metadata_counties": metadata_counties,
        "ndow_water_pages_requested": pages_requested,
        "ndow_water_unresolved_pages": unresolved_pages,
        "public_water_count": unique_water_count,
        "verified_access_point_count": access_count,
        "report_count": report_count,
        "populated_counties": populated_counties,
        "access_verification_methods": sorted(source_methods),
        "quarantined_unverified_waters": int(audit.get("matching", {}).get("quarantined_unverified_waters", 0)),
        "orphan_official_access_records": int(audit.get("matching", {}).get("orphan_official_access_records", 0)),
        **map_counts,
    }

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def write_js(path: Path, comment: str, variable: str, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"/* {comment} */\nwindow.{variable} = "
        + json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )


def write_outputs(
    root: Path,
    output_dir: Path,
    db: dict[str, Any],
    status: dict[str, Any],
    audit: dict[str, Any],
    unverified: list[dict[str, Any]],
    orphan_access: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "nevada_fishing_report_database.json", db)
    write_js(output_dir / "nevada_fishing_report_database.js", "Automatically generated strict public-access database. Do not hand-edit.", "NEVADA_FISHING_REPORT_DATABASE", db)
    access = {
        "metadata": db["metadata"],
        "county_count": db["county_count"],
        "public_water_count": db["public_water_count"],
        "verified_access_point_count": db["verified_access_point_count"],
        "counties": db["counties"],
        "flat_waters": db["flat_waters"],
    }
    write_json(output_dir / "nevada_public_fishing_access.json", access)
    write_js(output_dir / "nevada_public_fishing_access.js", "Automatically generated strict public-access data. Do not hand-edit.", "NEVADA_PUBLIC_FISHING_ACCESS", access)
    write_json(output_dir / "nevada_unverified_fishable_waters.json", {
        "metadata": {
            "state": STATE,
            "generated_at": db["metadata"]["generated_at"],
            "publication_status": "not_published",
            "reason": "Official NDOW water metadata exists, but no explicit official named public-access source matched.",
        },
        "count": len(unverified),
        "waters": unverified,
    })
    write_json(output_dir / "nevada_access_source_audit.json", {
        **audit,
        "orphan_official_access_records": orphan_access,
    })
    write_json(output_dir / "nevada_project_status.json", status)
    write_json(root / "config/nevada_counties.json", {
        "state": STATE,
        "county_count": 17,
        "counties": [{"county_number": i + 1, "county": county} for i, county in enumerate(COUNTIES)],
    })
    with (output_dir / "nevada_counties.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["county_number", "county"])
        writer.writerows((i + 1, county) for i, county in enumerate(COUNTIES))
    with (output_dir / "nevada_fishing_report_database.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = [
            "report_id", "report_date", "freshness", "age_days", "county",
            "water_name", "source_type", "source_name", "official", "title",
            "summary", "species", "techniques", "source_url",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for report in db["flat_reports"]:
            counties = report.get("counties") or [""]
            for county in counties:
                writer.writerow({
                    field: county if field == "county" else report.get(field, "")
                    for field in fields
                })

def county_page_html() -> str:
    county_options = "".join(
        f'<option value="{html.escape(county)}">#{i + 1} {html.escape(county)}</option>'
        for i, county in enumerate(COUNTIES)
    )
    template = r'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta name="theme-color" content="#1F4D3A"/>
<meta name="description" content="Search independently verified public fishing access and official NDOW fishing updates across all 17 Nevada county-equivalents."/>
<title>Nevada Fishing Reports & Public Access | Fish Finder Outdoors</title>
<link rel="icon" href="ffo-logo-main.png" type="image/png"/><link rel="apple-touch-icon" href="ffo-logo-main.png"/>
<link rel="manifest" href="manifest.json"/><link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Bitter:wght@600;700;800&family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="brand-shell.css?v=34"/>
<style>
:root{--green:#1f4d3a;--paper:#f4f1e7;--card:#fffdf8;--line:#d8d3c7;--ink:#173029;--muted:#64716c;--gold:#c79b3b;--warn:#7a5d1f}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#e9f0ea,#f4f1e7 320px);color:var(--ink);font-family:Inter,Arial,sans-serif}.wrap{width:min(1180px,calc(100% - 28px));margin:auto}.hero{padding:38px 0 20px}.hero-grid{display:grid;grid-template-columns:1.25fr .75fr;gap:26px;align-items:center}.kicker{display:inline-flex;padding:7px 11px;border-radius:999px;background:#e2eee7;color:var(--green);font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}.hero h1{font-family:Bitter,Georgia,serif;font-size:clamp(36px,6vw,64px);line-height:1.02;margin:16px 0 12px}.hero p{font-size:18px;color:var(--muted);max-width:800px}.hero-logo{width:min(300px,100%);justify-self:end}.panel{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;margin:18px 0;box-shadow:0 10px 30px rgba(31,77,58,.07)}.controls{display:grid;grid-template-columns:1fr 1.4fr repeat(3,auto);gap:10px;align-items:end}.field label{display:block;font-size:12px;font-weight:900;margin:0 0 5px}.field select,.field input{width:100%;padding:12px 13px;border:1px solid #bfc7c1;border-radius:12px;background:white;font:inherit}.check{display:flex;align-items:center;gap:7px;padding:11px 10px;background:#eef4f0;border-radius:12px;font-size:12px;font-weight:800;white-space:nowrap}.check input{width:18px;height:18px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}button{border:0;border-radius:12px;padding:11px 14px;font:inherit;font-weight:850;cursor:pointer}.primary{background:var(--green);color:white}.secondary{background:#e3ece7;color:var(--green)}.status{padding:12px 14px;border-radius:12px;background:#edf4f0;color:var(--green);font-weight:750;margin-top:13px}.summary{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.metric{background:white;border:1px solid var(--line);border-radius:14px;padding:13px}.metric span{font-size:12px;color:var(--muted);font-weight:700}.metric b{display:block;font-size:25px;margin-top:4px}.water-list{display:grid;gap:13px}.water-card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px}.water-card h2{font-family:Bitter,Georgia,serif;margin:0;font-size:25px}.water-title-link{color:var(--green);text-decoration:none}.water-title-link:hover{text-decoration:underline}.water-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.full-report-link{display:inline-flex;align-items:center;padding:10px 13px;border-radius:11px;background:var(--green);color:white!important;text-decoration:none;font-weight:850}.full-report-link:hover{filter:brightness(1.08)}.chips,.amenities{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0}.chip,.amenity{display:inline-flex;padding:5px 8px;border-radius:999px;background:#e8f0eb;border:1px solid #c9dbd1;font-size:11px;font-weight:850}.details{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:13px}.box{border:1px solid var(--line);border-radius:14px;padding:14px;background:white}.box h3{font-size:15px;margin:0 0 9px}.box p{margin:7px 0;color:#3f504a}.access{border-top:1px solid var(--line);padding-top:10px;margin-top:10px}.access:first-of-type{border-top:0;padding-top:0;margin-top:0}.link{display:inline-flex;margin-top:8px;font-weight:850}.muted{color:var(--muted);font-size:13px}.warning{background:#fff5d9;color:var(--warn);line-height:1.55}.load-more{display:block;margin:18px auto}.hidden{display:none!important}.top-links{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}.top-links a{display:inline-flex;padding:10px 12px;border-radius:12px;background:white;border:1px solid var(--line);font-weight:800;text-decoration:none}@media(max-width:950px){.controls{grid-template-columns:1fr 1fr}.hero-grid{grid-template-columns:1fr}.hero-logo{justify-self:start;max-width:220px}.details{grid-template-columns:1fr}}@media(max-width:600px){.controls,.summary{grid-template-columns:1fr}.panel{padding:15px}}
</style></head><body>
<header class="ffo-site-header"><div class="ffo-header-inner"><a class="ffo-logo-link" href="https://fishfinderoutdoors.com"><img src="ffo-logo-main.png" alt="Fish Finder Outdoors logo"/><span class="ffo-wordmark"><strong>Fish Finder</strong><span>Outdoors</span></span></a><button class="ffo-menu-button" aria-label="Open menu" aria-expanded="false" type="button">☰</button><nav class="ffo-nav" aria-label="Fish Finder Outdoors"><a href="https://fishfinderoutdoors.com">Home</a><a href="index.html">Fishing Reports</a><a href="idaho-county-reports.html">Idaho</a><a href="montana-county-reports.html">Montana</a><a href="utah-county-reports.html">Utah</a><a href="colorado-county-reports.html">Colorado</a><a href="wyoming-county-reports.html">Wyoming</a><a class="active" aria-current="page" href="nevada-county-reports.html">Nevada</a><a href="oregon-county-reports.html">Oregon</a><a href="washington-county-reports.html">Washington</a><a href="northern-california-county-reports.html">Northern California</a><a href="submit-report.html">Submit Report</a></nav></div></header>
<div class="ffo-beta-bar">VERIFIED PUBLIC ACCESS • 17 NEVADA COUNTY-EQUIVALENTS • OFFICIAL NDOW & PUBLIC-LAND SOURCES • <button class="ffo-install-button" data-install-ffo-app hidden type="button">Install App</button></div>
<main><section class="hero"><div class="wrap hero-grid"><div><span class="kicker">Nevada statewide directory</span><h1>Verified public fishing access, county by county.</h1><p>Search named public access facilities verified by Nevada or federal agencies, then review matched NDOW fishing reports and stocking updates. Every listed water opens its full Fish Finder Outdoors report.</p><div class="top-links"><a href="index.html">← Main report generator</a><a href="submit-report.html">Submit a fishing report</a><a href="report-water.html">Report incorrect access</a></div></div><img class="hero-logo" src="ffo-logo-main.png" alt="Fish Finder Outdoors"/></div></section>
<div class="wrap"><section class="panel"><div class="controls"><div class="field"><label for="countySelect">County</label><select id="countySelect"><option value="">All 17 county-equivalents</option>__COUNTY_OPTIONS__</select></div><div class="field"><label for="waterSearch">Water or access keyword</label><input id="waterSearch" placeholder="Lake Mead, trout, boat ramp…"/></div><label class="check"><input id="currentOnly" type="checkbox"/> Current reports</label><label class="check"><input id="boatRamp" type="checkbox"/> Boat ramp</label><label class="check"><input id="adaFishing" type="checkbox"/> ADA fishing</label></div><div class="actions"><button class="primary" id="searchButton" type="button">Search Nevada</button><button class="secondary" id="clearButton" type="button">Clear filters</button></div><div class="status" id="status">Loading the Nevada verified-access database…</div></section>
<section class="panel warning"><strong>Important:</strong> A named public ramp, park, pier, platform, or recreation site does not make every shoreline, road, or nearby parcel public. FishNV water records and NDOW fishing reports do not prove access by themselves. Verify current closures, water levels, fees, tribal rules, and posted signs before traveling.</section><section class="panel"><div class="summary" id="summary"></div></section><section class="water-list" id="waterList"></section><button class="secondary load-more hidden" id="loadMore" type="button">Show more waters</button>
<div class="ffo-county-product-banner"><section aria-labelledby="ffo-product-title-nevada-county" class="ffo-product-banner"><div class="ffo-product-banner-copy"><span class="ffo-product-banner-kicker">FEATURED FISH FINDER</span><h2 id="ffo-product-title-nevada-county">See more. Find structure. Fish smarter.</h2><p class="ffo-product-banner-name">Garmin STRIKER Vivid 7sv</p><p class="ffo-product-banner-text">A strong 7-inch setup with built-in GPS, CHIRP sonar, ClearVü, and SideVü for anglers who want a better look below and beside the boat.</p><div aria-label="Fish finder highlights" class="ffo-product-banner-features"><span>7-inch display</span><span>Built-in GPS</span><span>CHIRP sonar</span><span>ClearVü + SideVü</span></div><a class="ffo-product-banner-button" data-ffo-product-affiliate data-placement="nevada-county" href="https://amzn.to/4wHzwXl" rel="sponsored nofollow noopener" target="_blank">Check Price on Amazon <span aria-hidden="true">↗</span></a><p class="ffo-product-banner-disclosure">Paid link. As an Amazon Associate I earn from qualifying purchases. Price and availability can change.</p></div><a aria-label="View the Garmin STRIKER Vivid 7sv on Amazon" class="ffo-product-banner-photo" data-ffo-product-affiliate data-placement="nevada-county" href="https://amzn.to/4wHzwXl" rel="sponsored nofollow noopener" target="_blank"><img alt="Fish finder display mounted beside a mountain lake" decoding="async" height="596" loading="lazy" src="assets/garmin-striker-vivid-7sv-banner.webp" width="1460"/><span>View on Amazon <b aria-hidden="true">↗</b></span></a></section></div>
</div></main>
<footer class="ffo-site-footer"><div class="ffo-footer-grid"><div><a class="ffo-footer-brand" href="https://fishfinderoutdoors.com"><img src="ffo-logo-main.png" alt="Fish Finder Outdoors logo"/><span><strong>Fish Finder Outdoors</strong><br/><span style="color:#a9bbb3">Beginner friendly. Nevada ready.</span></span></a></div><div><div class="ffo-footer-title">Reports</div><div class="ffo-footer-links"><a href="index.html">Main Report Generator</a><a href="nevada-county-reports.html">Nevada County Reports</a><a href="submit-report.html">Submit a Report</a><a href="official-sources.html">Official Sources</a></div></div></div><div class="ffo-footer-fine"><span>© 2026 Fish Finder Outdoors. Powered by Mountain Dog Enterprises.</span><span>Verify current regulations and access before fishing.</span></div></footer>
<script src="site_config.js"></script><script src="data/nevada_fishing_report_database.js"></script>
<script>
(function(){"use strict";const db=window.NEVADA_FISHING_REPORT_DATABASE||{flat_waters:[],metadata:{}};const $=id=>document.getElementById(id);const county=$("countySelect"),query=$("waterSearch"),current=$("currentOnly"),ramp=$("boatRamp"),ada=$("adaFishing"),status=$("status"),summary=$("summary"),list=$("waterList"),more=$("loadMore");let filtered=[],shown=0;const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));const label=v=>String(v||"").replace(/_/g," ").replace(/\b\w/g,c=>c.toUpperCase());function matches(w){if(county.value&&w.county!==county.value)return false;const q=query.value.trim().toLowerCase();if(current.checked&&!['very_current','current','recent'].includes(w.report_status))return false;if(q&&!JSON.stringify([w.water_name,w.water_type,w.county,w.region,w.species,w.latest_report,w.access_points]).toLowerCase().includes(q))return false;const points=w.access_points||[];if(ramp.checked&&!points.some(p=>p.amenities?.boat_ramp===true))return false;if(ada.checked&&!points.some(p=>p.amenities?.ada_fishing===true))return false;return true}function pointCard(p){const a=p.amenities||{};const features=Object.entries(a).filter(([,v])=>v===true||typeof v==="string"&&v).map(([k,v])=>`<span class="amenity">${esc(v===true?label(k):`${label(k)}: ${v}`)}</span>`).join("");const map=p.directions_url?`<a class="link" href="${esc(p.directions_url)}" target="_blank" rel="noopener">Map this access point</a>`:"";return `<div class="access"><strong>${esc(p.access_point_name)}</strong>${p.current_status?`<p><b>Status:</b> ${esc(label(p.current_status))}</p>`:""}${p.access_details?`<p>${esc(p.access_details)}</p>`:""}<div class="amenities">${features}</div>${map}<br/><a class="link" href="${esc(p.official_source_url)}" target="_blank" rel="noopener">Official public-access source</a></div>`}function reportUrl(w){const p=new URLSearchParams({q:`${w.water_name}, Nevada`,open:"1",water:w.water_name,state:"Nevada",county:w.county});return `index.html?${p.toString()}`}function card(w){const r=w.latest_report;const url=reportUrl(w);const report=r?`<strong>${esc(r.title)}</strong><p>${esc(r.summary)}</p><div class="muted">${esc(r.report_date||"Date not listed")} · ${esc(label(r.freshness||"official update"))}</div>${r.source_url?`<a class="link" href="${esc(r.source_url)}" target="_blank" rel="noopener">Official NDOW source</a>`:""}`:`<div class="muted">No current NDOW fishing report or stocking update matched exactly to this verified-access water.</div>`;return `<article class="water-card"><h2><a class="water-title-link" href="${esc(url)}" title="Open the full fishing report for ${esc(w.water_name)}">${esc(w.water_name)}</a></h2><div class="chips"><span class="chip">#${esc(w.county_number)} ${esc(w.county)}</span><span class="chip">${esc(label(w.water_type))}</span><span class="chip">${esc(w.access_point_count)} verified access site${w.access_point_count===1?"":"s"}</span>${w.report_count?`<span class="chip">${esc(w.report_count)} official update${w.report_count===1?"":"s"}</span>`:""}</div>${w.species?`<p><strong>Species:</strong> ${esc(w.species)}</p>`:""}<div class="details"><div class="box"><h3>Named public access</h3>${(w.access_points||[]).map(pointCard).join("")}</div><div class="box"><h3>Latest matched Nevada update</h3>${report}${w.fishnv_source_url?`<a class="link" href="${esc(w.fishnv_source_url)}" target="_blank" rel="noopener">FishNV water details</a>`:""}<p class="muted">FishNV and fishing reports supply water information, not proof of public entry. Only the named official access facility is treated as verified.</p></div></div><div class="water-actions"><a class="full-report-link" href="${esc(url)}">Open full fishing report →</a></div></article>`}function renderSummary(){const waters=filtered.length,access=filtered.reduce((n,w)=>n+(w.access_point_count||0),0),reports=filtered.reduce((n,w)=>n+(w.report_count||0),0),counties=new Set(filtered.map(w=>w.county)).size,generated=db.metadata?.generated_at||"Unavailable";summary.innerHTML=`<div class="metric"><span>Matching waters</span><b>${waters}</b></div><div class="metric"><span>Verified access sites</span><b>${access}</b></div><div class="metric"><span>Official updates</span><b>${reports}</b></div><div class="metric"><span>Counties represented</span><b>${counties}</b></div><div class="metric"><span>Database generated</span><b style="font-size:14px">${esc(generated.replace('T',' ').replace('Z',' UTC'))}</b></div>`}function render(reset=true){filtered=(db.flat_waters||[]).filter(matches);if(reset)shown=0;shown=Math.min(filtered.length,shown+18);list.innerHTML=filtered.slice(0,shown).map(card).join("");more.classList.toggle("hidden",shown>=filtered.length);status.textContent=`Showing ${shown} of ${filtered.length} independently verified Nevada waters/access areas.`;renderSummary()}$("searchButton").addEventListener("click",()=>render(true));$("clearButton").addEventListener("click",()=>{county.value="";query.value="";current.checked=ramp.checked=ada.checked=false;render(true)});query.addEventListener("keydown",e=>{if(e.key==="Enter")render(true)});more.addEventListener("click",()=>render(false));render(true)})();
</script><script src="brand-shell.js?v=34"></script><script src="featured-fishfinder-banner.js"></script><script src="pwa.js"></script></body></html>'''
    return template.replace("__COUNTY_OPTIONS__", county_options)

def patch_brand_shell(root: Path) -> None:
    path = root / "brand-shell.js"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    match = re.search(r"const\s+stateLinks\s*=\s*(\[[^;]+\]);", text)
    if not match:
        raise RuntimeError("Could not locate the shared stateLinks list")
    block = match.group(1)
    entry = "['nevada-county-reports.html','Nevada County Reports']"
    if "nevada-county-reports.html" not in block:
        for marker in (
            "['oregon-county-reports.html','Oregon County Reports']",
            "['washington-county-reports.html','Washington County Reports']",
        ):
            if marker in block:
                block = block.replace(marker, entry + "," + marker, 1)
                break
        else:
            block = block[:-1] + ("," if block != "[" else "") + entry + "]"
        text = text[:match.start(1)] + block + text[match.end(1):]
    path.write_text(text, encoding="utf-8")

def patch_service_worker(root: Path) -> None:
    path = root / "service-worker.js"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    changed = False

    page_entry = '"./nevada-county-reports.html"'
    if page_entry not in text:
        marker = '"./oregon-county-reports.html"' if '"./oregon-county-reports.html"' in text else '"./washington-county-reports.html"'
        text = text.replace(marker, page_entry + ",\n  " + marker, 1)
        changed = True

    entries = [
        '"nevada_public_fishing_access.json"',
        '"nevada_public_fishing_access.js"',
        '"nevada_fishing_report_database.json"',
        '"nevada_fishing_report_database.js"',
    ]
    marker = '"oregon_public_fishing_access.json"'
    for entry in reversed(entries):
        if entry in text:
            continue
        if marker in text:
            text = text.replace(marker, entry + "," + marker, 1)
        else:
            match = re.search(r"const NETWORK_FIRST_FILES=\[(.*?)\];", text, flags=re.S)
            if not match:
                raise RuntimeError("Could not locate NETWORK_FIRST_FILES")
            body = match.group(1).rstrip()
            body += ("," if body and not body.endswith(",") else "") + "\n  " + entry
            text = text[:match.start(1)] + body + text[match.end(1):]
        changed = True

    if changed:
        version = re.search(r"ffo-reports-pwa-v(\d+)", text)
        if version:
            text = text.replace(version.group(0), f"ffo-reports-pwa-v{int(version.group(1)) + 1}", 1)
    path.write_text(text, encoding="utf-8")

def patch_sitemap(root: Path) -> None:
    path = root / "sitemap.xml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if "nevada-county-reports.html" in text:
        return
    host_match = re.search(r"<loc>(https?://[^/<]+)(?:/[^<]*)?</loc>", text)
    host = host_match.group(1) if host_match else "https://fishfinderoutdoors.wasmer.app"
    block = f"\n  <url><loc>{host}/nevada-county-reports.html</loc><lastmod>{datetime.now(timezone.utc).date().isoformat()}</lastmod></url>\n"
    if "</urlset>" in text:
        text = text.replace("</urlset>", block + "</urlset>")
    path.write_text(text, encoding="utf-8")


def admin_report(report: dict[str, Any], generated_at: str, unmatched_ids: set[str], state: str) -> dict[str, Any]:
    raw = clean(report.get("freshness"))
    mapped = "current" if raw in {"very_current", "current", "recent"} else "stale" if raw == "stale" else "aging"
    return {
        "state": state,
        "report_id": clean(report.get("report_id")),
        "published_date": clean(report.get("report_date")),
        "freshness_status": mapped,
        "headline": clean(report.get("title")),
        "summary": clean(report.get("summary")),
        "water_name": clean(report.get("water_name")),
        "counties": report.get("counties") or [],
        "agency": clean(report.get("source_name")),
        "source_url": clean(report.get("source_url")),
        "review_required": clean(report.get("report_id")) in unmatched_ids,
        "generated_at": generated_at,
    }


def rebuild_shared_feeds(root: Path) -> None:
    paths = sorted((root / "data").glob("*_fishing_report_database.json"))
    reports: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    last_runs: list[str] = []
    unmatched_total = 0
    for path in paths:
        try:
            db = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = db.get("metadata") or {}
        state = clean(meta.get("state")) or path.name.split("_", 1)[0].title()
        generated = clean(meta.get("generated_at"))
        last_runs.append(generated)
        unmatched = db.get("unmatched_reports") or []
        unmatched_ids = {clean(row.get("report_id")) for row in unmatched if isinstance(row, dict)}
        unmatched_total += len(unmatched)
        reports.extend(admin_report(row, generated, unmatched_ids, state) for row in (db.get("flat_reports") or []) if isinstance(row, dict))
        state_rows.append({
            "state": state,
            "report_count": db.get("report_count", 0),
            "public_water_count": db.get("public_water_count", 0),
            "county_count": db.get("county_count", 0),
            "generated_at": generated,
        })
    unique = {(row.get("state"), row.get("report_id")): row for row in reports}
    reports = sorted(unique.values(), key=lambda row: (clean(row.get("published_date")), clean(row.get("headline"))), reverse=True)
    state_rows.sort(key=lambda row: clean(row.get("state")))
    current = sum(row["freshness_status"] == "current" for row in reports)
    aging = sum(row["freshness_status"] == "aging" for row in reports)
    stale = sum(row["freshness_status"] == "stale" for row in reports)
    review = sum(bool(row["review_required"]) for row in reports)
    source_keys = {clean(row.get("source_url")) or clean(row.get("agency")) for row in reports if clean(row.get("source_url")) or clean(row.get("agency"))}
    updated = max((value for value in last_runs if value), default="")
    recent = {
        "version": f"{updated or 'current'}-multi-state",
        "updated_at": updated,
        "coverage_note": "Automatically generated from every installed state county-by-county fishing database.",
        "states": state_rows,
        "reports": reports,
    }
    status = {
        "last_run": updated,
        "mode": "multi-state-database",
        "state_count": len(state_rows),
        "states": state_rows,
        "reports_total": len(reports),
        "public_water_count": sum(int(row["public_water_count"] or 0) for row in state_rows),
        "county_count": sum(int(row["county_count"] or 0) for row in state_rows),
        "unique_sources": len(source_keys),
        "freshness": {"current": current, "aging": aging, "stale": stale, "unknown": 0},
        "changed_reports": len(reports),
        "review_required": review,
        "unreachable_sources": 0,
        "unmatched_report_count": unmatched_total,
        "sources": [],
    }
    write_js(root / "recent_fishing_reports.js", "Automatically generated multi-state fishing report feed. Do not hand-edit.", "FFO_RECENT_REPORTS", recent)
    write_js(root / "update_status.js", "Automatically generated multi-state admin status. Do not hand-edit.", "FFO_UPDATE_STATUS", status)


def patch_site_files(root: Path) -> None:
    (root / "nevada-county-reports.html").write_text(county_page_html(), encoding="utf-8")
    patch_brand_shell(root)
    patch_service_worker(root)
    patch_sitemap(root)
    rebuild_shared_feeds(root)


def validate_existing_baseline(root: Path, output_dir: Path) -> dict[str, Any]:
    database_path = output_dir / "nevada_fishing_report_database.json"
    access_path = output_dir / "nevada_public_fishing_access.json"
    status_path = output_dir / "nevada_project_status.json"
    required_files = (
        database_path,
        access_path,
        status_path,
        root / "config/nevada_counties.json",
        root / "nevada-county-reports.html",
        root / "brand-shell.js",
        root / "service-worker.js",
    )
    for required in required_files:
        if not required.is_file() or required.stat().st_size == 0:
            raise RuntimeError(f"Missing checked-in Nevada baseline file: {required}")

    db = json.loads(database_path.read_text(encoding="utf-8"))
    access = json.loads(access_path.read_text(encoding="utf-8"))
    config = json.loads((root / "config/nevada_counties.json").read_text(encoding="utf-8"))

    if db.get("county_count") != 17 or access.get("county_count") != 17 or config.get("county_count") != 17:
        raise RuntimeError("Nevada baseline does not contain all 17 county/county-equivalent shells")
    if [row.get("county") for row in db.get("counties", [])] != COUNTIES:
        raise RuntimeError("Nevada county order is not Carson City through White Pine")

    waters = db.get("flat_waters") or []
    if int(db.get("public_water_count", 0) or 0) < MIN_VERIFIED_PUBLIC_WATERS:
        raise RuntimeError("Nevada checked-in baseline lost too many verified public waters")
    if int(db.get("verified_access_point_count", 0) or 0) < MIN_VERIFIED_ACCESS_POINTS:
        raise RuntimeError("Nevada checked-in baseline lost too many verified access points")
    if int(db.get("report_count", 0) or 0) < MIN_OFFICIAL_REPORTS:
        raise RuntimeError("Nevada checked-in baseline lost too many official reports")

    populated = sum(1 for row in db.get("counties", []) if int(row.get("public_water_count", 0) or 0) > 0)
    if populated < MIN_POPULATED_COUNTIES:
        raise RuntimeError(f"Nevada baseline represents only {populated} populated county-equivalents")

    access_ids: set[str] = set()
    for water in waters:
        if water.get("publication_status") != "published_verified_public_access":
            raise RuntimeError(f"Unverified Nevada water was published: {water.get('water_name')}")
        points = water.get("access_points") or []
        if not points:
            raise RuntimeError(f"Nevada water has no named verified access point: {water.get('water_name')}")
        for point in points:
            access_id = clean(point.get("access_id"))
            if not access_id or access_id in access_ids:
                raise RuntimeError(f"Duplicate or missing Nevada access ID: {access_id}")
            access_ids.add(access_id)
            if point.get("public_access_status") != "verified_public":
                raise RuntimeError(f"Nevada access point is not verified public: {point.get('access_point_name')}")
            if point.get("entire_shoreline_public") is not False:
                raise RuntimeError(f"Nevada access point improperly claims an entire shoreline: {point.get('access_point_name')}")
            if not clean(point.get("official_source_url")).startswith("https://"):
                raise RuntimeError(f"Nevada access point lacks an HTTPS official source: {point.get('access_point_name')}")
            if not clean(point.get("verification_evidence")):
                raise RuntimeError(f"Nevada access point lacks verification evidence: {point.get('access_point_name')}")

    if len(access_ids) != int(db.get("verified_access_point_count", 0) or 0):
        raise RuntimeError("Nevada unique access-ID total does not match the database total")

    page = (root / "nevada-county-reports.html").read_text(encoding="utf-8")
    required_page_markers = (
        'class="ffo-site-header"',
        'class="water-title-link"',
        'class="full-report-link"',
        'function reportUrl(w)',
        'Open full fishing report',
    )
    if any(marker not in page for marker in required_page_markers):
        raise RuntimeError("Nevada state page is missing the compact header or clickable full-report links")
    if 'class="ffo-professional-hero"' in page:
        raise RuntimeError("Nevada state page must not contain the main search-page hero")

    brand = (root / "brand-shell.js").read_text(encoding="utf-8")
    for state_page in (
        "nevada-county-reports.html",
        "oregon-county-reports.html",
        "washington-county-reports.html",
        "northern-california-county-reports.html",
    ):
        if state_page not in brand:
            raise RuntimeError(f"Shared state navigation is missing {state_page}")
    if "document.querySelector('.ffo-professional-hero')" in brand:
        raise RuntimeError("Shared JavaScript is trying to hide the main hero again")

    worker = (root / "service-worker.js").read_text(encoding="utf-8")
    for marker in (
        "nevada-county-reports.html",
        "nevada_public_fishing_access.json",
        "nevada_fishing_report_database.json",
    ):
        if marker not in worker:
            raise RuntimeError(f"PWA service worker is missing Nevada resource: {marker}")

    result = {
        "state": STATE,
        "county_shells": 17,
        "populated_counties": populated,
        "verified_public_waters": int(db.get("public_water_count", 0) or 0),
        "verified_access_points": len(access_ids),
        "official_reports": int(db.get("report_count", 0) or 0),
        "baseline_validation": "passed",
    }
    print(json.dumps(result, indent=2))
    return result

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Fish Finder Outdoors repository root")
    parser.add_argument("--output-dir", default="data", help="Generated data directory, relative to root unless absolute")
    parser.add_argument("--workers", type=int, default=12, help="Concurrent official NDOW page requests")
    parser.add_argument("--max-waters", type=int, default=0, help="Optional development crawl cap; zero means complete inventory")
    parser.add_argument("--self-test", action="store_true", help="Run strict public-access unit tests without internet access")
    parser.add_argument("--validate-existing", action="store_true", help="Validate the checked-in Nevada baseline without internet access")
    args = parser.parse_args()

    if args.self_test:
        run_self_tests()
        return 0

    root = Path(args.root).resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    if args.validate_existing:
        validate_existing_baseline(root, output_dir)
        return 0
    generated_at = now_iso()

    county_polygons = load_county_polygons()
    reports, filter_water_names, report_html_pages, report_counts = collect_ndow_reports()
    report_counts.pop("direct_urls", None)

    crawl_cap = args.max_waters if args.max_waters > 0 else 750
    ndow_waters, ndow_page_access, ndow_warnings, ndow_counts = collect_ndow_water_inventory(
        report_html_pages,
        reports,
        county_polygons,
        workers=args.workers,
        max_pages=crawl_cap,
    )

    access_records, access_counts, access_warnings = collect_all_verified_access(county_polygons)
    access_records.extend(ndow_page_access)
    # Deduplicate after combining independent official sources with NDOW page evidence.
    access_records = list({clean(row.get("access_id")): row for row in access_records if clean(row.get("access_id"))}.values())
    access_counts["ndow_water_page_access_records"] = len(ndow_page_access)
    access_counts["combined_official_access_records"] = len(access_records)

    verified_waters, unverified_waters, orphan_access, matching_counts = match_verified_access(ndow_waters, access_records)
    matching_counts["quarantined_unverified_waters"] = len(unverified_waters)

    audit = {
        "state": STATE,
        "generated_at": generated_at,
        "policy": "NDOW water pages supply inventory metadata. FishNV is only an optional map link. Only explicit official named access evidence may publish a water.",
        "source_counts": {**ndow_counts, **access_counts},
        "matching": matching_counts,
        "source_warnings": [*ndow_warnings, *access_warnings],
        "unresolved_ndow_water_page_samples": ndow_warnings[:50],
    }
    db = build_database(verified_waters, reports, generated_at, audit)
    source_counts = {
        "county_polygons": len(county_polygons),
        **report_counts,
        **ndow_counts,
        **access_counts,
        **matching_counts,
        "official_filter_water_names": len(filter_water_names),
    }
    diagnostic_snapshot = {
        "ndow_water_pages_requested": ndow_counts.get("ndow_water_pages_requested", 0),
        "ndow_water_metadata_records": len(ndow_waters),
        "ndow_water_metadata_counties": sorted({row.get("county") for row in ndow_waters if row.get("county")}),
        "ndow_water_sample_names": [clean(row.get("water_name")) for row in ndow_waters[:30]],
        "unresolved_ndow_pages": len(ndow_warnings),
        "unresolved_samples": ndow_warnings[:15],
        "official_access_records": len(access_records),
        "ndow_page_access_records": len(ndow_page_access),
        "matching_counts": matching_counts,
        "verified_public_counties": sorted({row.get("county") for row in verified_waters if row.get("county")}),
    }
    print("NEVADA_DIAGNOSTIC_BEGIN")
    print(json.dumps(diagnostic_snapshot, indent=2, sort_keys=True))
    print("NEVADA_DIAGNOSTIC_END")

    validation = validate_build(db, source_counts, audit)
    status = {
        "state": STATE,
        "generated_at": generated_at,
        "deployment_status": "validated_public_access_ready_to_commit",
        "failed_sources": [],
        "source_warnings": [*ndow_warnings, *access_warnings],
        "warnings": {
            "unresolved_ndow_water_page_count": len(ndow_warnings),
            "unresolved_ndow_water_page_samples": ndow_warnings[:50],
            "quarantined_unverified_water_count": len(unverified_waters),
            "orphan_official_access_record_count": len(orphan_access),
        },
        "source_counts": source_counts,
        "validation": validation,
        "notes": [
            "NDOW server-rendered water pages are the primary inventory and county source.",
            "FishNV is retained only as an optional map link and is never accepted as access verification.",
            "Every published water has at least one explicit official named public access point or area.",
            "Waters without explicit access evidence are quarantined and not displayed.",
            "A named public facility does not make all shoreline or neighboring land public; current posted restrictions still control.",
        ],
    }
    write_outputs(root, output_dir, db, status, audit, unverified_waters, orphan_access)
    patch_site_files(root)
    print(json.dumps({
        "state": STATE,
        "counties": 17,
        "ndow_water_metadata_records": len(ndow_waters),
        "ndow_water_metadata_counties": validation["ndow_water_metadata_counties"],
        "verified_public_waters": db["public_water_count"],
        "verified_access_points": db["verified_access_point_count"],
        "quarantined_unverified_waters": len(unverified_waters),
        "official_reports": db["report_count"],
        "populated_counties": validation["populated_counties"],
        "unresolved_ndow_pages": len(ndow_warnings),
        "generated_at": generated_at,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
