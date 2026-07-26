#!/usr/bin/env python3
"""Build Montana Fish Finder Outdoors county data from official public sources.

This one-file state builder creates and maintains:
- the authoritative 56-county list
- verified public fishing-access records
- current official fishing information and report records
- the Montana county search page
- the shared two-state admin dashboard feed
- navigation, sitemap and PWA cache integration

The public-water directory is deliberately conservative. A water is published as
public-access water only when an official FWP, BLM, BOR, Forest Service, or
city/county/local developed-access record can be tied to it. Official fishery
survey, stocking, restriction and news records that cannot be tied to a verified
access point remain available as unmatched fishery references/reports and are not
silently labeled public.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - installed in GitHub Actions
    BeautifulSoup = None

STATE = "Montana"
STATE_ABBR = "MT"
COUNTIES = [
    "Beaverhead", "Big Horn", "Blaine", "Broadwater", "Carbon", "Carter",
    "Cascade", "Chouteau", "Custer", "Daniels", "Dawson", "Deer Lodge",
    "Fallon", "Fergus", "Flathead", "Gallatin", "Garfield", "Glacier",
    "Golden Valley", "Granite", "Hill", "Jefferson", "Judith Basin", "Lake",
    "Lewis and Clark", "Liberty", "Lincoln", "Madison", "McCone", "Meagher",
    "Mineral", "Missoula", "Musselshell", "Park", "Petroleum", "Phillips",
    "Pondera", "Powder River", "Powell", "Prairie", "Ravalli", "Richland",
    "Roosevelt", "Rosebud", "Sanders", "Sheridan", "Silver Bow", "Stillwater",
    "Sweet Grass", "Teton", "Toole", "Treasure", "Valley", "Wheatland",
    "Wibaux", "Yellowstone",
]
COUNTY_NUMBER = {name: i + 1 for i, name in enumerate(COUNTIES)}

USER_AGENT = "FishFinderOutdoors-MontanaBuilder/1.0 (+https://fishfinderoutdoors.com)"
FISH_VIEWER = "https://fwp-gis.mt.gov/arcgis/rest/services/fish/fishViewer/MapServer"
COUNTY_LAYER = "https://gisservicemt.gov/arcgis/rest/services/MSDI_Framework/Boundaries/MapServer/8"
LAYER_URLS = {
    "restrictions": f"{FISH_VIEWER}/1",
    "stocking": f"{FISH_VIEWER}/38",
    "blm_access": f"{FISH_VIEWER}/45",
    "bor_access": f"{FISH_VIEWER}/46",
    "forest_access": f"{FISH_VIEWER}/47",
    "local_access": f"{FISH_VIEWER}/48",
    "current_surveys": f"{FISH_VIEWER}/51",
    "historic_surveys": f"{FISH_VIEWER}/52",
    "fwp_access": f"{FISH_VIEWER}/71",
}
ESTABLISHED_REPORT_SOURCES = [
    ("Montana Fish Reports", "https://www.montanafishreports.com/"),
    ("Montana Outdoor", "https://www.montanaoutdoor.com/"),
]

OFFICIAL_URLS = {
    "fishmt": "https://fwp.mt.gov/fish/",
    "access": "https://fwp.mt.gov/fish/fishing-access",
    "regulations": "https://fwp.mt.gov/fish/regulations",
    "restrictions": "https://fwp.mt.gov/news/current-closures-restrictions/waterbody-closures",
    "news": "https://fwp.mt.gov/news/allnews",
}
NEWS_KEYWORDS = (
    "fish", "fishing", "angler", "trout", "salmon", "kokanee", "bass",
    "walleye", "paddlefish", "sturgeon", "perch", "crappie", "catfish",
    "reservoir", "river", "lake", "creek", "stream", "pond", "stocking",
    "access site", "hoot owl", "waterbody", "closure",
)
GENERIC_WATER_WORDS = {
    "lake", "river", "creek", "stream", "pond", "reservoir", "fork", "water",
    "fishing", "access", "site", "campground", "launch", "boat", "recreation",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def clip(value: Any, limit: int = 520) -> str:
    text = clean(value)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"


def norm(value: Any) -> str:
    text = clean(value).lower().replace("&", " and ")
    text = re.sub(r"\b(the|of|at|on|main stem|mainstem)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def yes(value: Any) -> bool:
    return clean(value).lower() in {"y", "yes", "true", "1", "available", "allowed"}


def valid_lon_lat(lon: Any, lat: Any) -> bool:
    try:
        x = float(lon)
        y = float(lat)
    except (TypeError, ValueError):
        return False
    return -117.5 <= x <= -103.0 and 44.0 <= y <= 49.3


def epoch_to_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str) and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value):
        return value
    try:
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return datetime.fromtimestamp(number, timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return parse_date(clean(value))


def parse_date(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", value)
    if iso:
        return iso.group(1)
    value = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", value, flags=re.I)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%A, %B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    match = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})\b", value, re.I)
    if match:
        try:
            return datetime.strptime(" ".join(match.groups()), "%B %d %Y").date().isoformat()
        except ValueError:
            return ""
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


def request_bytes(url: str, *, retries: int = 4, timeout: int = 90) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
            })
            with urlopen(req, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(2 ** (attempt + 1), 12))
    raise RuntimeError(f"Unable to retrieve {url}: {last_error}")


def request_json(url: str, *, retries: int = 4) -> dict[str, Any]:
    payload = json.loads(request_bytes(url, retries=retries).decode("utf-8", errors="replace"))
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"ArcGIS error for {url}: {payload['error']}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected JSON payload from {url}")
    return payload


def arcgis_query_url(layer_url: str, params: dict[str, Any]) -> str:
    return f"{layer_url}/query?{urlencode(params)}"


def arcgis_features(
    layer_url: str,
    *,
    where: str = "1=1",
    out_fields: str = "*",
    return_geometry: bool = True,
    chunk_size: int = 500,
) -> list[dict[str, Any]]:
    """Download every feature using object-id chunks, not fragile page offsets."""
    id_payload = request_json(arcgis_query_url(layer_url, {
        "where": where,
        "returnIdsOnly": "true",
        "f": "json",
    }))
    ids = sorted(set(id_payload.get("objectIds") or []))
    if not ids:
        return []
    rows: list[dict[str, Any]] = []
    for start in range(0, len(ids), chunk_size):
        chunk = ids[start:start + chunk_size]
        payload = request_json(arcgis_query_url(layer_url, {
            "objectIds": ",".join(str(x) for x in chunk),
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
            "outSR": "4326",
            "f": "json",
        }))
        features = payload.get("features") or []
        if not isinstance(features, list):
            raise RuntimeError(f"ArcGIS layer returned malformed features: {layer_url}")
        rows.extend(features)
    return rows


def feature_point(feature: dict[str, Any]) -> tuple[float | None, float | None]:
    attrs = feature.get("attributes") or {}
    geom = feature.get("geometry") or {}
    candidates = [
        (geom.get("x"), geom.get("y")),
        (attrs.get("LONGITUDE"), attrs.get("LATITUDE")),
        (attrs.get("Longitude"), attrs.get("Latitude")),
        (attrs.get("LON"), attrs.get("LAT")),
    ]
    for lon, lat in candidates:
        if valid_lon_lat(lon, lat):
            return float(lon), float(lat)
    rings = geom.get("rings") or []
    coords = [pair for ring in rings for pair in ring if isinstance(pair, list) and len(pair) >= 2]
    if coords:
        lon = sum(float(p[0]) for p in coords) / len(coords)
        lat = sum(float(p[1]) for p in coords) / len(coords)
        if valid_lon_lat(lon, lat):
            return lon, lat
    return None, None


def ring_contains(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
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


def canonical_county_name(value: Any) -> str:
    """Return our canonical Montana county spelling for any official name variant."""
    text = clean(value)
    text = re.sub(r"\s+county$", "", text, flags=re.I)
    key = norm(text)
    return {norm(name): name for name in COUNTIES}.get(key, "")


def county_geometries(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for feature in features:
        attrs = feature.get("attributes") or {}
        name = canonical_county_name(
            attrs.get("NAME")
            or attrs.get("County")
            or attrs.get("NAMELABEL")
            or attrs.get("BASENAME")
        )
        if not name:
            continue
        rings = feature.get("geometry", {}).get("rings") or []
        points = [p for ring in rings for p in ring if isinstance(p, list) and len(p) >= 2]
        if not points:
            continue
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        results.append({
            "name": name,
            "rings": rings,
            "bbox": (min(xs), min(ys), max(xs), max(ys)),
        })

    deduped = {row["name"]: row for row in results}
    ordered = [deduped[name] for name in COUNTIES if name in deduped]
    missing = [name for name in COUNTIES if name not in deduped]
    if missing:
        observed = sorted({
            clean(
                (feature.get("attributes") or {}).get("NAME")
                or (feature.get("attributes") or {}).get("County")
                or (feature.get("attributes") or {}).get("NAMELABEL")
                or (feature.get("attributes") or {}).get("BASENAME")
            )
            for feature in features
        })
        raise RuntimeError(
            "Official county layer is missing: "
            + ", ".join(missing)
            + ". County names returned by the service: "
            + ", ".join(name for name in observed if name)
        )
    return ordered


def county_for_point(lon: float | None, lat: float | None, counties: list[dict[str, Any]]) -> str:
    if lon is None or lat is None:
        return ""
    for county in counties:
        xmin, ymin, xmax, ymax = county["bbox"]
        if not (xmin <= lon <= xmax and ymin <= lat <= ymax):
            continue
        if any(ring_contains(lon, lat, ring) for ring in county["rings"]):
            return county["name"]
    return ""


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def infer_water_type(name: str) -> str:
    n = norm(name)
    checks = (
        ("reservoir", "reservoir"), ("lake", "lake"), ("pond", "pond"),
        ("river", "river"), ("creek", "creek"), ("stream", "stream"),
        ("slough", "slough"), ("canal", "canal"), ("fork", "river"),
    )
    for token, label in checks:
        if re.search(rf"\b{token}\b", n):
            return label
    return "water"


def stripped_access_name(name: str) -> str:
    value = norm(name)
    phrases = (
        "fishing access site", "fishing access", "access site", "recreation site",
        "recreation area", "boat launch", "boat ramp", "day use area", "campground",
        "fas", "site",
    )
    for phrase in phrases:
        value = re.sub(rf"\b{re.escape(phrase)}\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def source_id(*parts: Any) -> str:
    return hashlib.sha256("|".join(clean(p) for p in parts).encode("utf-8")).hexdigest()[:18]


def directions_url(lon: float | None, lat: float | None) -> str:
    if lon is None or lat is None:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f}%2C{lon:.6f}"


def access_is_relevant(attrs: dict[str, Any], layer_key: str) -> bool:
    if layer_key in {"fwp_access", "local_access"}:
        return True
    text = norm(" ".join(clean(v) for v in attrs.values()))
    return any(token in text for token in (
        "fish", "angling", "boat", "launch", "ramp", "reservoir", "lake",
        "river", "creek", "stream", "pond", "water access",
    ))


def generic_amenities(attrs: dict[str, Any]) -> dict[str, bool | None]:
    text = norm(" ".join(clean(v) for v in attrs.values()))
    boat = yes(attrs.get("LAUNCH")) or "boat ramp" in text or "boat launch" in text or "launch ramp" in text
    if clean(attrs.get("BOAT_FAC")) and clean(attrs.get("BOAT_FAC")).lower() not in {"no", "none", "n/a"}:
        boat = True
    camping_value = clean(attrs.get("CAMPING"))
    camping = bool(camping_value and camping_value.lower() not in {"no", "none", "n/a", "not allowed"}) or "camping" in text
    dock = "dock" in text or "pier" in text
    restroom = any(token in text for token in ("restroom", "toilet", "latrine", "vault toilet"))
    ada = any(token in text for token in ("ada", "accessible fishing", "wheelchair", "handicap accessible", "barrier free"))
    return {
        "boat_ramp": bool(boat),
        "dock": bool(dock),
        "restroom": bool(restroom),
        "camping": bool(camping),
        "ada_fishing": bool(ada),
    }


def access_details(attrs: dict[str, Any], manager: str) -> str:
    pieces = [manager]
    for key in (
        "BOAT_FAC", "CAMPING", "ACCESSIBILITY", "ACCESSTYPE", "LOCATION",
        "DESCRIPTIO", "DESCRIPTION", "HUNT_ACCESS", "OWNER", "COMMENTS",
    ):
        value = clean(attrs.get(key))
        if value:
            pieces.append(f"{key.replace('_', ' ').title()}: {value}")
    return clip(". ".join(dict.fromkeys(pieces)), 650)


def official_access_url(attrs: dict[str, Any], fallback: str) -> str:
    for key in ("WEB_PAGE", "WEBPAGE", "URL", "PDFMAP", "WEBSITE", "LINK"):
        value = clean(attrs.get(key))
        if value.startswith("http"):
            return value
    return fallback


def make_access_point(feature: dict[str, Any], layer_key: str, counties: list[dict[str, Any]]) -> dict[str, Any] | None:
    attrs = feature.get("attributes") or {}
    if not access_is_relevant(attrs, layer_key):
        return None
    lon, lat = feature_point(feature)
    county = county_for_point(lon, lat, counties)
    if not county:
        return None
    manager_map = {
        "fwp_access": "Montana Fish, Wildlife & Parks Fishing Access Site",
        "blm_access": "Bureau of Land Management recreation site",
        "bor_access": "Bureau of Reclamation recreation site",
        "forest_access": "U.S. Forest Service recreation site",
        "local_access": "City, county, or local developed access site",
    }
    name = clean(
        attrs.get("NAME") or attrs.get("SITE_NAME") or attrs.get("SITENAME")
        or attrs.get("FWP_NAME") or attrs.get("DESCRIPTIO") or attrs.get("DESCRIPTION")
    )
    if not name:
        name = f"Public access site {attrs.get('OBJECTID', '')}".strip()
    manager = manager_map[layer_key]
    return {
        "record_kind": "access_point",
        "access_id": f"mt-{layer_key}-{attrs.get('OBJECTID', source_id(name, lon, lat))}",
        "county_number": COUNTY_NUMBER[county],
        "county": county,
        "access_point_name": name,
        "latitude": lon if False else lat,
        "longitude": lon,
        "directions_url": directions_url(lon, lat),
        "manager": manager,
        "amenities": generic_amenities(attrs),
        "access_flags": {
            "official_public_access_record": True,
            "public_access_only": True,
        },
        "access_details": access_details(attrs, manager),
        "official_source_url": official_access_url(attrs, LAYER_URLS[layer_key]),
        "layer_key": layer_key,
        "source_object_id": attrs.get("OBJECTID"),
        "raw_name_for_matching": name,
    }


def water_evidence_key(county: str, water_name: str) -> tuple[str, str]:
    return county, norm(water_name)


def add_evidence(
    water_map: dict[tuple[str, str], dict[str, Any]],
    *, county: str, water_name: str, lon: float | None, lat: float | None,
    evidence_type: str, source_url: str, species: str = "", event_date: str = "",
    details: str = "", raw: dict[str, Any] | None = None,
) -> None:
    water_name = clean(water_name)
    if not water_name or county not in COUNTY_NUMBER:
        return
    key = water_evidence_key(county, water_name)
    row = water_map.setdefault(key, {
        "county_number": COUNTY_NUMBER[county],
        "county": county,
        "water_name": water_name,
        "water_type": infer_water_type(water_name),
        "latitude": lat,
        "longitude": lon,
        "evidence_types": [],
        "species": [],
        "latest_survey_date": "",
        "latest_stocking_date": "",
        "current_restrictions": [],
        "official_evidence_urls": [],
        "evidence_count": 0,
        "evidence_examples": [],
    })
    if row.get("latitude") is None and lat is not None:
        row["latitude"] = lat
        row["longitude"] = lon
    if evidence_type not in row["evidence_types"]:
        row["evidence_types"].append(evidence_type)
    if species and species not in row["species"]:
        row["species"].append(species)
    if source_url and source_url not in row["official_evidence_urls"]:
        row["official_evidence_urls"].append(source_url)
    row["evidence_count"] += 1
    if evidence_type == "current_fish_survey" and event_date > row["latest_survey_date"]:
        row["latest_survey_date"] = event_date
    if evidence_type == "fish_stocking" and event_date > row["latest_stocking_date"]:
        row["latest_stocking_date"] = event_date
    if evidence_type == "current_restriction" and details:
        if details not in row["current_restrictions"]:
            row["current_restrictions"].append(details)
    if len(row["evidence_examples"]) < 8:
        row["evidence_examples"].append({
            "type": evidence_type,
            "date": event_date,
            "species": species,
            "details": clip(details, 260),
        })


def collect_official_gis(
    counties: list[dict[str, Any]],
    warnings: list[str],
    source_counts: dict[str, int],
    *, include_historic: bool,
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    water_map: dict[tuple[str, str], dict[str, Any]] = {}
    access_points: list[dict[str, Any]] = []
    raw_events: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def safe_layer(name: str, where: str = "1=1") -> list[dict[str, Any]]:
        try:
            rows = arcgis_features(LAYER_URLS[name], where=where)
            source_counts[name] = len(rows)
            return rows
        except Exception as exc:
            warnings.append(f"{name} layer failed: {exc}")
            source_counts[name] = 0
            return []

    for feature in safe_layer("current_surveys"):
        attrs = feature.get("attributes") or {}
        lon, lat = feature_point(feature)
        county = county_for_point(lon, lat, counties)
        event_date = epoch_to_date(attrs.get("SURVEYDATE"))
        species = clean(attrs.get("SPNAME"))
        water = clean(attrs.get("WATERNAME"))
        details = clip("; ".join(filter(None, [
            f"Section: {clean(attrs.get('SECNAME'))}" if clean(attrs.get("SECNAME")) else "",
            f"Count: {attrs.get('TOTAL_COUNT')}" if attrs.get("TOTAL_COUNT") not in (None, "") else "",
            f"Gear: {clean(attrs.get('GEAR'))}" if clean(attrs.get("GEAR")) else "",
        ])))
        add_evidence(water_map, county=county, water_name=water, lon=lon, lat=lat,
                     evidence_type="current_fish_survey", source_url=LAYER_URLS["current_surveys"],
                     species=species, event_date=event_date, details=details, raw=attrs)
        if water and county:
            raw_events["surveys"].append({"county": county, "water_name": water, "lon": lon, "lat": lat, "date": event_date, "species": species, "attrs": attrs})

    if include_historic:
        for feature in safe_layer("historic_surveys"):
            attrs = feature.get("attributes") or {}
            lon, lat = feature_point(feature)
            county = county_for_point(lon, lat, counties)
            add_evidence(water_map, county=county, water_name=clean(attrs.get("WATERNAME")), lon=lon, lat=lat,
                         evidence_type="historic_fish_survey", source_url=LAYER_URLS["historic_surveys"],
                         species=clean(attrs.get("SPNAME")), event_date=epoch_to_date(attrs.get("SURVEYDATE")),
                         details=clean(attrs.get("SECNAME")), raw=attrs)
    else:
        source_counts["historic_surveys"] = 0

    for feature in safe_layer("stocking"):
        attrs = feature.get("attributes") or {}
        lon, lat = feature_point(feature)
        county = county_for_point(lon, lat, counties)
        event_date = epoch_to_date(attrs.get("PLANTDATE"))
        water = clean(attrs.get("WATERBODY"))
        species = clean(attrs.get("SPECIES"))
        details = clip("; ".join(filter(None, [
            f"{attrs.get('NUMFISH')} fish" if attrs.get("NUMFISH") not in (None, "") else "",
            f"Average size {attrs.get('FISHSIZE')}" if attrs.get("FISHSIZE") not in (None, "") else "",
            clean(attrs.get("LOCCOMMENT")), clean(attrs.get("HATCHERY")),
        ])))
        add_evidence(water_map, county=county, water_name=water, lon=lon, lat=lat,
                     evidence_type="fish_stocking", source_url=LAYER_URLS["stocking"], species=species,
                     event_date=event_date, details=details, raw=attrs)
        if water and county:
            raw_events["stocking"].append({"county": county, "water_name": water, "lon": lon, "lat": lat, "date": event_date, "species": species, "attrs": attrs})

    for feature in safe_layer("restrictions"):
        attrs = feature.get("attributes") or {}
        lon, lat = feature_point(feature)
        county = county_for_point(lon, lat, counties)
        water = clean(attrs.get("WATERBODY"))
        event_date = epoch_to_date(attrs.get("UPDATEDATE") or attrs.get("CREATEDATE")) or today_iso()
        details = clip(" — ".join(filter(None, [clean(attrs.get("TITLE")), clean(attrs.get("LOCATION")), clean(attrs.get("DESCRIPTION"))])), 900)
        add_evidence(water_map, county=county, water_name=water, lon=lon, lat=lat,
                     evidence_type="current_restriction", source_url=clean(attrs.get("PRESSRELEASE")) or OFFICIAL_URLS["restrictions"],
                     event_date=event_date, details=details, raw=attrs)
        if water:
            raw_events["restrictions"].append({"county": county, "water_name": water, "lon": lon, "lat": lat, "date": event_date, "attrs": attrs, "details": details})

    for layer_key in ("fwp_access", "blm_access", "bor_access", "forest_access", "local_access"):
        for feature in safe_layer(layer_key):
            point = make_access_point(feature, layer_key, counties)
            if point:
                access_points.append(point)

    return water_map, access_points, raw_events


def match_access_to_waters(
    water_map: dict[tuple[str, str], dict[str, Any]],
    access_points: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_county: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in water_map.values():
        by_county[row["county"]].append(row)

    public_map: dict[tuple[str, str], dict[str, Any]] = {}
    unmatched_access: list[dict[str, Any]] = []
    for point in access_points:
        county = point["county"]
        candidates = by_county.get(county, [])
        stripped = stripped_access_name(point["access_point_name"])
        chosen: dict[str, Any] | None = None
        match_method = ""

        if stripped:
            exact = [w for w in candidates if stripped == norm(w["water_name"])]
            partial = [w for w in candidates if stripped in norm(w["water_name"]) or norm(w["water_name"]) in stripped]
            if exact:
                chosen = exact[0]
                match_method = "official_name_match"
            elif len(partial) == 1:
                chosen = partial[0]
                match_method = "official_partial_name_match"

        if chosen is None and point.get("longitude") is not None and point.get("latitude") is not None:
            distances = []
            for water in candidates:
                if water.get("longitude") is None or water.get("latitude") is None:
                    continue
                distance = haversine_km(point["longitude"], point["latitude"], water["longitude"], water["latitude"])
                distances.append((distance, water))
            distances.sort(key=lambda item: item[0])
            if distances and distances[0][0] <= 8.0:
                chosen = distances[0][1]
                match_method = f"official_gis_proximity_{distances[0][0]:.2f}_km"

        if chosen is None:
            shell_name = clean(point["access_point_name"])
            chosen = {
                "county_number": point["county_number"],
                "county": county,
                "water_name": shell_name,
                "water_type": "public fishing access site",
                "latitude": point.get("latitude"),
                "longitude": point.get("longitude"),
                "evidence_types": ["official_public_access_site"],
                "species": [],
                "latest_survey_date": "",
                "latest_stocking_date": "",
                "current_restrictions": [],
                "official_evidence_urls": [point["official_source_url"]],
                "evidence_count": 1,
                "evidence_examples": [],
            }
            match_method = "public_access_site_water_shell"
            unmatched_access.append(point)

        key = water_evidence_key(county, chosen["water_name"])
        public = public_map.setdefault(key, {
            **chosen,
            "record_kind": "water",
            "access_points": [],
            "access_point_count": 0,
            "public_access_verified": True,
            "public_access_verification": "official_public_access_inventory",
            "access_status": "open_or_conditions_apply",
            "access_details": "Verified public access site is inventoried by an official managing agency. Check current rules, closures, fees, posted signs, road conditions and site-specific requirements before travel.",
            "official_access_source_url": point["official_source_url"],
        })
        point_copy = {k: v for k, v in point.items() if k not in {"raw_name_for_matching"}}
        point_copy["water_match_method"] = match_method
        public["access_points"].append(point_copy)
        public["access_point_count"] = len(public["access_points"])
        if not public.get("official_access_source_url"):
            public["official_access_source_url"] = point["official_source_url"]

    public_waters = sorted(public_map.values(), key=lambda w: (w["county_number"], w["water_name"].lower()))
    return public_waters, unmatched_access


def report_record(
    *, source_type: str, source_name: str, source_url: str, title: str, summary: str,
    report_date: str, water_name: str = "", counties: list[str] | None = None,
    species: str = "", techniques: str = "", access_notes: str = "",
    official: bool = True, observed_period: str = "", rating: str = "",
) -> dict[str, Any]:
    report_date = report_date or today_iso()
    counties = [c for c in (counties or []) if c in COUNTY_NUMBER]
    return {
        "report_id": source_id(source_url, report_date, title, water_name),
        "source_type": source_type,
        "source_name": source_name,
        "source_url": source_url,
        "title": clean(title),
        "summary": clip(summary),
        "report_date": report_date,
        "freshness": freshness(report_date),
        "age_days": age_days(report_date),
        "water_name": clean(water_name),
        "counties": counties,
        "rating": clean(rating),
        "species": clean(species),
        "techniques": clean(techniques),
        "access_notes": clean(access_notes),
        "official": bool(official),
        "observed_period": clean(observed_period),
        "raw_source_reference": "",
    }


def latest_events(events: list[dict[str, Any]], public_keys: set[tuple[str, str]], *, keep_same_date: bool = False) -> list[dict[str, Any]]:
    latest_date: dict[tuple[str, str], str] = {}
    for event in events:
        key = water_evidence_key(event.get("county", ""), event.get("water_name", ""))
        if key not in public_keys:
            continue
        value = clean(event.get("date"))
        if value > latest_date.get(key, ""):
            latest_date[key] = value
    if keep_same_date:
        return [event for event in events if water_evidence_key(event.get("county", ""), event.get("water_name", "")) in public_keys and clean(event.get("date")) == latest_date.get(water_evidence_key(event.get("county", ""), event.get("water_name", "")), "")]
    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        key = water_evidence_key(event.get("county", ""), event.get("water_name", ""))
        if key in public_keys and clean(event.get("date")) == latest_date.get(key, "") and key not in chosen:
            chosen[key] = event
    return list(chosen.values())


def reports_from_gis(raw_events: dict[str, list[dict[str, Any]]], public_waters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public_keys = {water_evidence_key(w["county"], w["water_name"]) for w in public_waters}
    reports: list[dict[str, Any]] = []

    survey_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in latest_events(raw_events.get("surveys", []), public_keys, keep_same_date=True):
        survey_groups[(event["county"], event["water_name"], event.get("date") or "")].append(event)
    for (county, water, survey_date), events in survey_groups.items():
        species = sorted({clean(e.get("species")) for e in events if clean(e.get("species"))})
        total = sum(int((e.get("attrs") or {}).get("TOTAL_COUNT") or 0) for e in events)
        summary = f"Montana FWP's Fisheries Information System records a fish survey at {water}."
        if species:
            summary += " Species recorded include " + ", ".join(species[:12]) + "."
        if total:
            summary += f" The survey records represented {total:,} fish across the latest grouped records."
        reports.append(report_record(
            source_type="official_fwp_fish_survey", source_name="Montana Fish, Wildlife & Parks",
            source_url=LAYER_URLS["current_surveys"], title=f"Official fish survey record for {water}",
            summary=summary, report_date=survey_date or today_iso(), water_name=water,
            counties=[county], species=", ".join(species[:12]),
            techniques="Official FWP fisheries survey; survey gear and methods vary by record.",
        ))

    for event in latest_events(raw_events.get("stocking", []), public_keys):
        attrs = event.get("attrs") or {}
        count = attrs.get("NUMFISH")
        species = clean(event.get("species"))
        detail = f"Montana FWP records a stocking event at {event['water_name']}"
        if species:
            detail += f" involving {species}"
        if count not in (None, ""):
            detail += f" and {int(count):,} fish"
        detail += ". Stocking schedules and completed records can change; open the official source for details."
        reports.append(report_record(
            source_type="official_fwp_stocking_record", source_name="Montana Fish, Wildlife & Parks",
            source_url=LAYER_URLS["stocking"], title=f"Fish stocking record for {event['water_name']}",
            summary=detail, report_date=event.get("date") or today_iso(), water_name=event["water_name"],
            counties=[event["county"]], species=species,
            access_notes=clean(attrs.get("LOCCOMMENT")),
        ))

    for event in raw_events.get("restrictions", []):
        reports.append(report_record(
            source_type="official_current_water_restriction", source_name="Montana Fish, Wildlife & Parks",
            source_url=clean((event.get("attrs") or {}).get("PRESSRELEASE")) or OFFICIAL_URLS["restrictions"],
            title=clean((event.get("attrs") or {}).get("TITLE")) or f"Current restriction for {event.get('water_name')}",
            summary=event.get("details") or "Montana FWP lists a current restriction or closure for this waterbody.",
            report_date=event.get("date") or today_iso(), water_name=event.get("water_name", ""),
            counties=[event["county"]] if event.get("county") else [],
            access_notes=clean((event.get("attrs") or {}).get("LOCATION")), rating="restriction",
        ))
    return reports


def collect_news(water_names: list[str], county_by_water: dict[str, set[str]], warnings: list[str]) -> list[dict[str, Any]]:
    if BeautifulSoup is None:
        warnings.append("BeautifulSoup is unavailable; Montana FWP news collection was skipped.")
        return []
    try:
        base_html = request_bytes(OFFICIAL_URLS["news"]).decode("utf-8", errors="replace")
    except Exception as exc:
        warnings.append(f"Montana FWP news page failed: {exc}")
        return []
    soup = BeautifulSoup(base_html, "html.parser")
    links: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        title = clean(a.get_text(" ", strip=True))
        href = urljoin(OFFICIAL_URLS["news"], a.get("href"))
        if not title or "fwp.mt.gov" not in href or "/news/" not in href:
            continue
        if href.rstrip("/") in {OFFICIAL_URLS["news"].rstrip("/"), "https://fwp.mt.gov/news"}:
            continue
        if any(keyword in norm(title) for keyword in NEWS_KEYWORDS):
            links[href] = title
    reports: list[dict[str, Any]] = []
    normalized_waters = sorted(((norm(name), name) for name in water_names if len(norm(name)) >= 5), key=lambda pair: len(pair[0]), reverse=True)
    for url, fallback_title in list(links.items())[:50]:
        try:
            article_html = request_bytes(url, retries=2, timeout=45).decode("utf-8", errors="replace")
            article = BeautifulSoup(article_html, "html.parser")
            title = clean((article.find("h1") or {}).get_text(" ", strip=True) if article.find("h1") else fallback_title)
            text = clean(article.get_text(" ", strip=True))
            report_date = ""
            for tag in article.find_all(["time", "meta"]):
                candidate = tag.get("datetime") or tag.get("content") or tag.get_text(" ", strip=True)
                report_date = parse_date(clean(candidate))
                if report_date:
                    break
            if not report_date:
                report_date = parse_date(text[:900]) or today_iso()
            summary = ""
            meta_desc = article.find("meta", attrs={"name": "description"})
            if meta_desc:
                summary = clean(meta_desc.get("content"))
            if not summary:
                paragraphs = [clean(p.get_text(" ", strip=True)) for p in article.find_all("p")]
                summary = " ".join(p for p in paragraphs if len(p) > 50)[:1200]
            haystack = norm(title + " " + summary)
            matched_water = ""
            for normalized, original in normalized_waters:
                significant = [t for t in normalized.split() if t not in GENERIC_WATER_WORDS]
                if significant and normalized in haystack:
                    matched_water = original
                    break
            counties = sorted(county_by_water.get(norm(matched_water), set()), key=lambda c: COUNTY_NUMBER[c]) if matched_water else []
            reports.append(report_record(
                source_type="official_fwp_news", source_name="Montana Fish, Wildlife & Parks",
                source_url=url, title=title, summary=summary or title, report_date=report_date,
                water_name=matched_water, counties=counties,
            ))
        except Exception as exc:
            warnings.append(f"FWP news article failed ({url}): {exc}")
    return reports


def collect_established_reports(public_waters: list[dict[str, Any]], warnings: list[str], source_counts: dict[str, int]) -> list[dict[str, Any]]:
    if BeautifulSoup is None:
        warnings.append("BeautifulSoup is unavailable; established public fishing websites were skipped.")
        return []
    county_by_water: dict[str, set[str]] = defaultdict(set)
    original_by_norm: dict[str, str] = {}
    for water in public_waters:
        key = norm(water["water_name"])
        if key:
            county_by_water[key].add(water["county"])
            original_by_norm[key] = water["water_name"]
    normalized_waters = sorted(original_by_norm, key=len, reverse=True)
    reports: list[dict[str, Any]] = []
    for source_name, source_url in ESTABLISHED_REPORT_SOURCES:
        count_before = len(reports)
        key_name = re.sub(r"[^a-z0-9]+", "_", source_name.lower()).strip("_")
        try:
            homepage = request_bytes(source_url, retries=2, timeout=45).decode("utf-8", errors="replace")
            soup = BeautifulSoup(homepage, "html.parser")
            candidates: dict[str, str] = {}
            for a in soup.find_all("a", href=True):
                title = clean(a.get_text(" ", strip=True))
                href = urljoin(source_url, a.get("href"))
                if not title or not href.startswith("http"):
                    continue
                if any(keyword in norm(title) for keyword in NEWS_KEYWORDS):
                    candidates[href] = title
            for url, fallback_title in list(candidates.items())[:70]:
                try:
                    page = request_bytes(url, retries=1, timeout=35).decode("utf-8", errors="replace")
                    article = BeautifulSoup(page, "html.parser")
                    h1 = article.find("h1")
                    title = clean(h1.get_text(" ", strip=True) if h1 else fallback_title)
                    meta = article.find("meta", attrs={"name": "description"})
                    summary = clean(meta.get("content")) if meta else ""
                    if not summary:
                        paragraphs = [clean(p.get_text(" ", strip=True)) for p in article.find_all("p")]
                        summary = " ".join(p for p in paragraphs if len(p) > 45)[:1000]
                    haystack = norm(title + " " + summary)
                    matched = ""
                    for water_key in normalized_waters:
                        significant = [t for t in water_key.split() if t not in GENERIC_WATER_WORDS]
                        if significant and water_key in haystack:
                            matched = water_key
                            break
                    if not matched:
                        continue
                    report_date = ""
                    for tag in article.find_all(["time", "meta"]):
                        candidate = tag.get("datetime") or tag.get("content") or tag.get_text(" ", strip=True)
                        report_date = parse_date(clean(candidate))
                        if report_date:
                            break
                    if not report_date:
                        report_date = parse_date(clean(article.get_text(" ", strip=True))[:1000]) or today_iso()
                    water_name = original_by_norm[matched]
                    counties = sorted(county_by_water[matched], key=lambda c: COUNTY_NUMBER[c])
                    reports.append(report_record(
                        source_type="established_fishing_website", source_name=source_name,
                        source_url=url, title=title, summary=summary or title,
                        report_date=report_date, water_name=water_name, counties=counties,
                        official=False,
                    ))
                except Exception:
                    continue
        except Exception as exc:
            warnings.append(f"{source_name} collector failed: {exc}")
        source_counts[key_name + "_reports"] = len(reports) - count_before
    return reports


def load_public_social(path: Path, warnings: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "verified_public_post,state,county,water_name,report_date,source_name,source_url,title,summary,species,techniques,access_notes\n",
            encoding="utf-8",
        )
        return []
    reports = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            if clean(row.get("verified_public_post")).lower() not in {"true", "yes", "1"}:
                continue
            if clean(row.get("state")).lower() not in {"montana", "mt"}:
                continue
            county = clean(row.get("county"))
            url = clean(row.get("source_url"))
            if county not in COUNTY_NUMBER or not url.startswith("http"):
                warnings.append(f"Public social row {line_number} skipped: valid Montana county and public URL are required.")
                continue
            reports.append(report_record(
                source_type="verified_public_social_post", source_name=clean(row.get("source_name")) or "Public post",
                source_url=url, title=clean(row.get("title")) or f"Public fishing report for {clean(row.get('water_name'))}",
                summary=clean(row.get("summary")), report_date=clean(row.get("report_date")) or today_iso(),
                water_name=clean(row.get("water_name")), counties=[county], species=clean(row.get("species")),
                techniques=clean(row.get("techniques")), access_notes=clean(row.get("access_notes")), official=False,
            ))
    return reports


def dedupe_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    priority = {
        "official_current_water_restriction": 50,
        "official_fwp_fish_survey": 40,
        "official_fwp_stocking_record": 35,
        "official_fwp_news": 30,
        "established_fishing_website": 20,
        "verified_public_social_post": 10,
    }
    for report in reports:
        key = report["report_id"]
        existing = best.get(key)
        if existing is None or priority.get(report["source_type"], 0) > priority.get(existing["source_type"], 0):
            best[key] = report
    return sorted(best.values(), key=lambda r: (r.get("report_date") or "", r.get("title") or ""), reverse=True)


def build_access_database(
    public_waters: list[dict[str, Any]],
    fishery_references: list[dict[str, Any]],
    unmatched_access: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    county_blocks = []
    for number, county in enumerate(COUNTIES, start=1):
        waters = [w for w in public_waters if w["county"] == county]
        county_blocks.append({
            "county_number": number,
            "county": county,
            "public_water_count": len(waters),
            "public_access_point_count": sum(w.get("access_point_count", 0) for w in waters),
            "records": waters,
        })
    return {
        "metadata": {
            "title": "Montana Verified Public Fishing Access Directory",
            "state": STATE,
            "state_abbreviation": STATE_ABBR,
            "version": "1.0",
            "generated_at": generated_at,
            "public_access_only": True,
            "county_order": "1 Beaverhead through 56 Yellowstone",
            "access_policy": "A water appears in the public directory only when tied to an official FWP, BLM, BOR, Forest Service, or city/county/local developed public access record. Fishery records without verified access are retained separately and are not silently labeled public.",
            "official_sources": [
                {"name": "Montana State Library County Boundaries", "url": COUNTY_LAYER},
                {"name": "Montana FWP FishViewer", "url": FISH_VIEWER},
                {"name": "Montana FWP Fishing Access", "url": OFFICIAL_URLS["access"]},
            ],
        },
        "county_count": 56,
        "public_water_count": len(public_waters),
        "access_point_count": sum(w.get("access_point_count", 0) for w in public_waters),
        "fishery_reference_count": len(fishery_references),
        "unmatched_access_site_count": len(unmatched_access),
        "counties": county_blocks,
        "flat_records": public_waters,
        "unmatched_fishery_references": fishery_references,
    }


def build_report_database(access_db: dict[str, Any], reports: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    reports_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        for county in report.get("counties") or []:
            if report.get("water_name"):
                reports_by_key[water_evidence_key(county, report["water_name"])].append(report)

    flat_waters = []
    county_blocks = []
    for county in COUNTIES:
        waters = []
        for base in [w for w in access_db.get("flat_records", []) if w["county"] == county]:
            key = water_evidence_key(county, base["water_name"])
            candidates = list(reports_by_key.get(key, []))
            if not candidates:
                n = norm(base["water_name"])
                for (report_county, report_water), rows in reports_by_key.items():
                    if report_county == county and (n in report_water or report_water in n):
                        candidates.extend(rows)
            candidates = dedupe_reports(candidates)
            latest = candidates[0] if candidates else None
            row = dict(base)
            row.update({
                "report_status": latest.get("freshness") if latest else "no_recent_public_report_found",
                "latest_report": latest,
                "recent_reports": candidates[:10],
                "report_count": len(candidates),
            })
            waters.append(row)
            flat_waters.append(row)
        number = COUNTY_NUMBER[county]
        county_reports = [r for r in reports if county in (r.get("counties") or [])]
        county_blocks.append({
            "county_number": number,
            "county": county,
            "public_water_count": len(waters),
            "waters_with_reports": sum(w["report_count"] > 0 for w in waters),
            "waters_without_reports": sum(w["report_count"] == 0 for w in waters),
            "public_access_point_count": sum(w.get("access_point_count", 0) for w in waters),
            "county_report_count": len(county_reports),
            "waters": waters,
        })

    matched_ids = {r["report_id"] for w in flat_waters for r in w.get("recent_reports", [])}
    unmatched = [r for r in reports if r["report_id"] not in matched_ids and r.get("water_name")]
    statewide = [r for r in reports if not r.get("water_name") or not r.get("counties")]
    return {
        "metadata": {
            "title": "Montana Public Fishing Access and Current Fishing Reports",
            "state": STATE,
            "state_abbreviation": STATE_ABBR,
            "version": "2.0",
            "generated_at": generated_at,
            "public_access_only": True,
            "county_order": "1 Beaverhead through 56 Yellowstone",
            "report_policy": "Official Montana FWP restrictions, surveys, stocking records and news rank above manually verified public social posts. Reports do not create a public-access claim unless an official access record is present.",
            "facebook_policy": "Facebook Groups are not scraped. Only public URLs manually entered with verified_public_post=true are eligible.",
            "freshness_labels": {
                "very_current": "0-14 days old",
                "current": "15-30 days old",
                "recent": "31-90 days old",
                "stale": "More than 90 days old",
                "no_recent_public_report_found": "No matching public report was found",
            },
            "sources": [
                {"name": "Montana Fish, Wildlife & Parks FishMT", "type": "official", "url": OFFICIAL_URLS["fishmt"]},
                {"name": "Montana FWP FishViewer GIS", "type": "official", "url": FISH_VIEWER},
                {"name": "Montana FWP Current Waterbody Restrictions", "type": "official", "url": OFFICIAL_URLS["restrictions"]},
                {"name": "Montana FWP News", "type": "official", "url": OFFICIAL_URLS["news"]},
                {"name": "Manually verified public social posts", "type": "public_social_post", "url": ""},
            ],
        },
        "county_count": 56,
        "public_water_count": len(flat_waters),
        "report_count": len(reports),
        "statewide_reports": statewide[:100],
        "unmatched_reports": unmatched,
        "counties": county_blocks,
        "flat_waters": flat_waters,
        "flat_reports": reports,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def write_js(path: Path, variable: str, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "/* Automatically generated. Do not hand-edit. */\n"
        f"window.{variable} = " + json.dumps(value, separators=(",", ":"), ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )


def write_access_outputs(output_dir: Path, db: dict[str, Any], build_report: dict[str, Any]) -> None:
    write_json(output_dir / "montana_public_fishing_access.json", db)
    write_js(output_dir / "montana_public_fishing_access.js", "MONTANA_PUBLIC_FISHING_ACCESS", db)
    with (output_dir / "montana_public_fishing_access.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["county_number", "county", "water_name", "water_type", "latitude", "longitude", "public_access_verified", "access_point_count", "access_point_name", "manager", "boat_ramp", "dock", "restroom", "camping", "ada_fishing", "official_source_url", "access_details"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for water in db.get("flat_records", []):
            points = water.get("access_points") or [{}]
            for point in points:
                amenities = point.get("amenities") or {}
                writer.writerow({
                    "county_number": water.get("county_number"), "county": water.get("county"),
                    "water_name": water.get("water_name"), "water_type": water.get("water_type"),
                    "latitude": water.get("latitude"), "longitude": water.get("longitude"),
                    "public_access_verified": water.get("public_access_verified"),
                    "access_point_count": water.get("access_point_count"),
                    "access_point_name": point.get("access_point_name", ""), "manager": point.get("manager", ""),
                    "boat_ramp": amenities.get("boat_ramp", ""), "dock": amenities.get("dock", ""),
                    "restroom": amenities.get("restroom", ""), "camping": amenities.get("camping", ""),
                    "ada_fishing": amenities.get("ada_fishing", ""),
                    "official_source_url": point.get("official_source_url") or water.get("official_access_source_url"),
                    "access_details": point.get("access_details") or water.get("access_details"),
                })
    with (output_dir / "montana_public_fishing_access_summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["county_number", "county", "public_water_count", "public_access_point_count"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for county in db.get("counties", []):
            writer.writerow({field: county.get(field) for field in fields})
    write_json(output_dir / "montana_public_access_build_report.json", build_report)


def write_report_outputs(output_dir: Path, db: dict[str, Any], build_report: dict[str, Any]) -> None:
    write_json(output_dir / "montana_fishing_report_database.json", db)
    write_js(output_dir / "montana_fishing_report_database.js", "MONTANA_FISHING_REPORT_DATABASE", db)
    fields = ["report_id", "report_date", "freshness", "age_days", "county_number", "county", "water_name", "source_type", "source_name", "official", "rating", "title", "summary", "species", "techniques", "access_notes", "source_url", "observed_period"]
    with (output_dir / "montana_fishing_report_database.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for report in db.get("flat_reports", []):
            counties = report.get("counties") or [""]
            for county in counties:
                row = {field: report.get(field, "") for field in fields}
                row["county"] = county
                row["county_number"] = COUNTY_NUMBER.get(county, "")
                writer.writerow(row)
    with (output_dir / "montana_fishing_report_summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["county_number", "county", "public_water_count", "waters_with_reports", "waters_without_reports", "public_access_point_count", "county_report_count"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for county in db.get("counties", []):
            writer.writerow({field: county.get(field) for field in fields})
    write_json(output_dir / "montana_fishing_report_build_report.json", build_report)


def county_files(root: Path) -> None:
    config = root / "config"
    data = root / "data"
    config.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": STATE,
        "county_count": 56,
        "order": "alphabetical",
        "source": COUNTY_LAYER,
        "counties": [{"county_number": i + 1, "county": name} for i, name in enumerate(COUNTIES)],
    }
    write_json(config / "montana_counties.json", payload)
    with (data / "montana_counties.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["county_number", "county"])
        for number, name in enumerate(COUNTIES, start=1):
            writer.writerow([number, name])
    alias_path = config / "montana_water_aliases.json"
    if not alias_path.exists():
        write_json(alias_path, {"state": STATE, "aliases": {}})


def multi_state_admin_builder_text() -> str:
    return r'''#!/usr/bin/env python3
"""Build the Fish Finder Outdoors admin feed from every installed state database."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any

def clean(value: Any) -> str:
    return " ".join(str(value or "").split())

def map_freshness(value: str) -> str:
    value=clean(value).lower()
    if value in {"very_current","current"}: return "current"
    if value=="recent": return "aging"
    return "stale"

def report_for_admin(report, generated_at, unmatched_ids, state):
    water=clean(report.get("water_name")); title=clean(report.get("title")) or "Fishing update"
    species=clean(report.get("species")); rating=clean(report.get("rating")); techniques=clean(report.get("techniques")); access=clean(report.get("access_notes")); url=clean(report.get("source_url")); rid=clean(report.get("report_id"))
    catches=[]
    if species: catches.append({"species":species,"metric":rating or "Reported","detail":techniques})
    return {"report_kind":clean(report.get("source_type")) or "official","report_id":rid,"state":state,"counties":report.get("counties") or [],"names":[water] if water else [f"Statewide {state}"],"water_name":water,"agency":clean(report.get("source_name")) or f"{state} fishing source","report_type":clean(report.get("source_type")).replace("_"," ").title() or "Fishing report","published_date":clean(report.get("report_date")),"report_period":clean(report.get("observed_period")),"headline":title,"summary":clean(report.get("summary")),"catches":catches,"conditions":[v for v in (access,techniques) if v],"rating":rating,"species":species,"techniques":techniques,"source_url":url,"specificity":f"Matched {state} public water" if water else f"Statewide or multi-water {state} report","freshness_status":map_freshness(clean(report.get("freshness"))),"freshness_days":report.get("age_days"),"last_checked_at":generated_at,"source_status":"available" if url else "source-not-linked","source_error":"","review_required":rid in unmatched_ids}

def write_js(path, comment, variable, value):
    path.write_text(f"/* {comment} */\nwindow.{variable} = "+json.dumps(value,indent=2,ensure_ascii=False)+";\n",encoding="utf-8")

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--database",action="append",default=[]); parser.add_argument("--output-dir",default="."); args=parser.parse_args()
    discovered=sorted(Path("data").glob("*_fishing_report_database.json"))
    paths=[]
    for item in [Path(p) for p in args.database]+discovered:
        if item.exists() and item not in paths: paths.append(item)
    if not paths: raise FileNotFoundError("No state fishing report databases were found.")
    reports=[]; state_rows=[]; last_runs=[]; unmatched_total=0
    for path in paths:
        db=json.loads(path.read_text(encoding="utf-8")); meta=db.get("metadata") or {}; state=clean(meta.get("state")) or clean(meta.get("title")).split(" ")[0] or path.name.split("_")[0].title(); generated=clean(meta.get("generated_at")); last_runs.append(generated)
        unmatched=db.get("unmatched_reports") or []; unmatched_ids={clean(r.get("report_id")) for r in unmatched if isinstance(r,dict)}; unmatched_total+=len(unmatched)
        reports.extend(report_for_admin(r,generated,unmatched_ids,state) for r in (db.get("flat_reports") or []) if isinstance(r,dict))
        state_rows.append({"state":state,"report_count":db.get("report_count",0),"public_water_count":db.get("public_water_count",0),"county_count":db.get("county_count",0),"generated_at":generated})
    unique={}
    for row in reports: unique[(row.get("state"),row.get("report_id"))]=row
    reports=list(unique.values()); reports.sort(key=lambda r:(clean(r.get("published_date")),clean(r.get("headline"))),reverse=True)
    current=sum(r["freshness_status"]=="current" for r in reports); aging=sum(r["freshness_status"]=="aging" for r in reports); stale=sum(r["freshness_status"]=="stale" for r in reports); review=sum(bool(r["review_required"]) for r in reports)
    source_keys={clean(r.get("source_url")) or clean(r.get("agency")) for r in reports if clean(r.get("source_url")) or clean(r.get("agency"))}; updated=max((x for x in last_runs if x),default="")
    recent={"version":f"{updated or 'current'}-multi-state","updated_at":updated,"coverage_note":"Automatically generated from every installed state county-by-county fishing database.","states":state_rows,"reports":reports}
    status={"last_run":updated,"mode":"multi-state-database","state_count":len(state_rows),"states":state_rows,"reports_total":len(reports),"public_water_count":sum(int(s["public_water_count"] or 0) for s in state_rows),"county_count":sum(int(s["county_count"] or 0) for s in state_rows),"unique_sources":len(source_keys),"freshness":{"current":current,"aging":aging,"stale":stale,"unknown":0},"changed_reports":len(reports),"review_required":review,"unreachable_sources":0,"unmatched_report_count":unmatched_total,"sources":[]}
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True); write_js(out/"recent_fishing_reports.js","Automatically generated multi-state fishing report feed. Do not hand-edit.","FFO_RECENT_REPORTS",recent); write_js(out/"update_status.js","Automatically generated multi-state admin status. Do not hand-edit.","FFO_UPDATE_STATUS",status)
    print(json.dumps({"states":state_rows,"reports_written":len(reports),"public_waters":status["public_water_count"],"counties":status["county_count"]},indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
'''


def generic_search_text() -> str:
    return r'''/* Fish Finder Outdoors — multi-state public-access and fishing-report search. */
(function(){"use strict";
function normalize(value){return String(value||"").toLowerCase().replace(/\s+/g," ").trim();}
function db(){return window.FFO_ACTIVE_FISHING_DATABASE||window.MONTANA_FISHING_REPORT_DATABASE||window.IDAHO_FISHING_REPORT_DATABASE||{flat_waters:[],flat_reports:[],counties:[]};}
window.FFO_FISHING_REPORT_SEARCH={
counties:function(){return db().counties||[];},
waters:function(options){options=options||{};const county=normalize(options.county).replace(/\s+county$/,"");const query=normalize(options.query);const status=normalize(options.reportStatus);const needsRamp=options.boatRamp===true,needsDock=options.dock===true,needsRestroom=options.restroom===true,needsCamping=options.camping===true,needsAda=options.adaFishing===true;return(db().flat_waters||[]).filter(function(water){if(county&&normalize(water.county)!==county)return false;if(status&&normalize(water.report_status)!==status)return false;const points=water.access_points||[];if(needsRamp&&!points.some(p=>p.amenities&&p.amenities.boat_ramp===true))return false;if(needsDock&&!points.some(p=>p.amenities&&p.amenities.dock===true))return false;if(needsRestroom&&!points.some(p=>p.amenities&&p.amenities.restroom===true))return false;if(needsCamping&&!points.some(p=>p.amenities&&p.amenities.camping===true))return false;if(needsAda&&!points.some(p=>p.amenities&&p.amenities.ada_fishing===true))return false;if(!query)return true;const latest=water.latest_report||{};const haystack=normalize([water.water_name,water.water_type,water.county,water.drainage,water.access_details,latest.title,latest.summary,latest.species,latest.techniques,points.map(p=>p.access_point_name).join(" ")].join(" "));return haystack.includes(query);});},
reports:function(options){options=options||{};const county=normalize(options.county).replace(/\s+county$/,"");const query=normalize(options.query);const sourceType=normalize(options.sourceType);const currentOnly=options.currentOnly===true;return(db().flat_reports||[]).filter(function(report){if(county&&!(report.counties||[]).some(c=>normalize(c)===county))return false;if(sourceType&&normalize(report.source_type)!==sourceType)return false;if(currentOnly&&!["very_current","current"].includes(report.freshness))return false;if(!query)return true;return normalize([report.water_name,report.title,report.summary,report.species,report.techniques,report.source_name].join(" ")).includes(query);});}
};})();
'''


def brand_shell_text() -> str:
    return r'''(function(){
  const button=document.querySelector('.ffo-menu-button');
  const nav=document.querySelector('.ffo-nav');
  const stateLinks=[['idaho-county-reports.html','Idaho County Reports'],['montana-county-reports.html','Montana County Reports']];
  if(nav){
    const submit=nav.querySelector('a[href="submit-report.html"]');
    stateLinks.forEach(([href,text])=>{
      if(!nav.querySelector(`a[href="${href}"]`)){
        const link=document.createElement('a');link.href=href;link.textContent=text;
        if(submit)nav.insertBefore(link,submit);else nav.appendChild(link);
      }
    });
  }
  if(button&&nav){button.innerHTML='<span></span>';button.addEventListener('click',()=>{const open=nav.classList.toggle('open');button.setAttribute('aria-expanded',open?'true':'false');button.classList.toggle('open',open);});nav.querySelectorAll('a').forEach(link=>link.addEventListener('click',()=>nav.classList.remove('open')));}
})();
'''


def service_worker_text() -> str:
    return r'''const CACHE_VERSION="ffo-reports-pwa-v5";const STATIC_CACHE=`${CACHE_VERSION}-static`;const PAGE_CACHE=`${CACHE_VERSION}-pages`;
const APP_SHELL=["./","./index.html","./idaho-county-reports.html","./montana-county-reports.html","./brand-shell.css","./brand-shell.js","./pwa.js","./manifest.json","./app-icon-192.png","./app-icon-512.png","./app-icon-maskable-512.png","./apple-touch-icon.png","./ffo-logo-main.png","./ffo-hero.jpg","./ffo-water-divider.jpg","./official-sources.html","./submit-report.html","./report-water.html","./404.html","./site_config.js","./official_state_sources.js","./official_water_overrides.js","./regional_water_search.js","./official_species_data.js","./fishing_report_search.js"];
const FRESH_DATA_FILES=["recent_fishing_reports.js","community_fishing_reports.js","update_status.js","regional_water_search.js","official_water_overrides.js","idaho_fishing_report_database.js","idaho_fishing_report_database.json","montana_fishing_report_database.js","montana_fishing_report_database.json","montana_public_fishing_access.js","montana_public_fishing_access.json"];
self.addEventListener("install",event=>{event.waitUntil(caches.open(STATIC_CACHE).then(cache=>cache.addAll(APP_SHELL)).then(()=>self.skipWaiting()));});
self.addEventListener("activate",event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>![STATIC_CACHE,PAGE_CACHE].includes(key)).map(key=>caches.delete(key)))).then(()=>self.clients.claim()));});
async function networkFirst(request,cacheName){const cache=await caches.open(cacheName);try{const response=await fetch(request);if(response&&response.ok)cache.put(request,response.clone());return response;}catch(error){const cached=await cache.match(request);if(cached)return cached;if(request.mode==="navigate")return(await caches.match("./index.html"))||Response.error();throw error;}}
async function cacheFirst(request){const cached=await caches.match(request);if(cached)return cached;const response=await fetch(request);if(response&&response.ok){const cache=await caches.open(STATIC_CACHE);cache.put(request,response.clone());}return response;}
self.addEventListener("fetch",event=>{const request=event.request;if(request.method!=="GET")return;const url=new URL(request.url);if(url.origin!==self.location.origin)return;if(request.mode==="navigate"){event.respondWith(networkFirst(request,PAGE_CACHE));return;}if(FRESH_DATA_FILES.some(name=>url.pathname.endsWith(name))){event.respondWith(networkFirst(request,PAGE_CACHE));return;}event.respondWith(cacheFirst(request));});
self.addEventListener("message",event=>{if(event.data==="SKIP_WAITING")self.skipWaiting();});
'''


def build_montana_page(root: Path) -> None:
    source = root / "idaho-county-reports.html"
    if not source.exists():
        raise FileNotFoundError("idaho-county-reports.html is required as the verified page template.")
    text = source.read_text(encoding="utf-8")
    replacements = [
        ("across all 44 Idaho counties", "across all 56 Montana counties"),
        ("Idaho County Fishing Reports & Public Access", "Montana County Fishing Reports & Public Access"),
        ('<a class="active" href="idaho-county-reports.html">Idaho County Reports</a>', '<a href="idaho-county-reports.html">Idaho County Reports</a><a class="active" href="montana-county-reports.html">Montana County Reports</a>'),
        ("44 IDAHO COUNTIES", "56 MONTANA COUNTIES"),
        ("Idaho statewide directory", "Montana statewide directory"),
        ("all 44 Idaho counties", "all 56 Montana counties"),
        ('aria-label="Idaho county fishing search"', 'aria-label="Montana county fishing search"'),
        ("All 44 counties", "All 56 counties"),
        ("Loading the Idaho public-access database", "Loading the Montana public-access database"),
        ("current Idaho fishing rules", "current Montana fishing rules"),
        ("Beginner friendly. Idaho built.", "Beginner friendly. Montana ready."),
        ('<a href="idaho-county-reports.html">Idaho County Reports</a><a href="submit-report.html">', '<a href="idaho-county-reports.html">Idaho County Reports</a><a href="montana-county-reports.html">Montana County Reports</a><a href="submit-report.html">'),
        ('<script src="data/idaho_fishing_report_database.js"></script>\n<script src="fishing_report_search.js"></script>', '<script src="data/montana_fishing_report_database.js"></script>\n<script>window.FFO_ACTIVE_FISHING_DATABASE=window.MONTANA_FISHING_REPORT_DATABASE;</script>\n<script src="fishing_report_search.js"></script>'),
        ("window.IDAHO_FISHING_REPORT_DATABASE", "window.MONTANA_FISHING_REPORT_DATABASE"),
        ("No separately inventoried IDFG access point", "No separately inventoried Montana FWP access point"),
        ("Idaho public-access database", "Montana public-access database"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    (root / "montana-county-reports.html").write_text(text, encoding="utf-8")


def update_sitemap(root: Path) -> None:
    path = root / "sitemap.xml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    entries = []
    for filename, priority in (("idaho-county-reports.html", "0.9"), ("montana-county-reports.html", "0.9")):
        url = f"https://fish-finder-reports-live.wasmer.app/{filename}"
        if url not in text:
            entries.append(f"  <url>\n    <loc>{url}</loc>\n    <changefreq>daily</changefreq>\n    <priority>{priority}</priority>\n  </url>\n")
    if entries:
        text = text.replace("</urlset>", "".join(entries) + "</urlset>")
        path.write_text(text, encoding="utf-8")


def install_site_integration(root: Path) -> None:
    (root / "build_admin_dashboard_files.py").write_text(multi_state_admin_builder_text(), encoding="utf-8")
    (root / "fishing_report_search.js").write_text(generic_search_text(), encoding="utf-8")
    (root / "brand-shell.js").write_text(brand_shell_text(), encoding="utf-8")
    (root / "service-worker.js").write_text(service_worker_text(), encoding="utf-8")
    build_montana_page(root)
    update_sitemap(root)


def validate(access_db: dict[str, Any], report_db: dict[str, Any], root: Path) -> None:
    assert access_db["county_count"] == 56
    assert report_db["county_count"] == 56
    assert len(access_db["counties"]) == 56
    assert len(report_db["counties"]) == 56
    assert [row["county_number"] for row in report_db["counties"]] == list(range(1, 57))
    assert report_db["counties"][0]["county"] == "Beaverhead"
    assert report_db["counties"][-1]["county"] == "Yellowstone"
    assert report_db["metadata"]["public_access_only"] is True
    assert (root / "montana-county-reports.html").exists()
    assert (root / "build_admin_dashboard_files.py").exists()


def bootstrap_databases(generated_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
    access = build_access_database([], [], [], generated_at)
    reports = build_report_database(access, [], generated_at)
    return access, reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--social-file", default="data/montana_public_social_reports.csv")
    parser.add_argument("--skip-network", action="store_true", help="Create and validate the 56-county bootstrap files without downloading GIS data.")
    parser.add_argument("--include-historic-surveys", action="store_true", help="Also download the large historic survey layer. Current surveys, stocking and access are always included.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = (root / args.output_dir).resolve()
    social_path = (root / args.social_file).resolve()
    generated_at = now_iso()
    warnings: list[str] = []
    errors: list[str] = []
    source_counts: dict[str, int] = {}
    county_files(root)

    try:
        if args.skip_network:
            access_db, report_db = bootstrap_databases(generated_at)
            source_counts["mode"] = 0
        else:
            county_features = arcgis_features(COUNTY_LAYER, out_fields="NAME,County,NAMELABEL", return_geometry=True)
            source_counts["official_county_polygons"] = len(county_features)
            county_shapes = county_geometries(county_features)
            water_map, access_points, raw_events = collect_official_gis(
                county_shapes, warnings, source_counts, include_historic=args.include_historic_surveys
            )
            public_waters, unmatched_access = match_access_to_waters(water_map, access_points)
            public_keys = {water_evidence_key(w["county"], w["water_name"]) for w in public_waters}
            fishery_references = [w for key, w in water_map.items() if key not in public_keys]
            access_db = build_access_database(public_waters, fishery_references, unmatched_access, generated_at)

            reports = reports_from_gis(raw_events, public_waters)
            county_by_water: dict[str, set[str]] = defaultdict(set)
            for water in public_waters:
                county_by_water[norm(water["water_name"])].add(water["county"])
            news = collect_news([w["water_name"] for w in public_waters], county_by_water, warnings)
            source_counts["fwp_news_reports"] = len(news)
            reports.extend(news)
            established = collect_established_reports(public_waters, warnings, source_counts)
            reports.extend(established)
            social = load_public_social(social_path, warnings)
            source_counts["verified_public_social_posts"] = len(social)
            reports.extend(social)
            reports = dedupe_reports(reports)
            report_db = build_report_database(access_db, reports, generated_at)

        access_build = {
            "generated_at": generated_at,
            "success": True,
            "state": STATE,
            "county_count": 56,
            "source_counts": source_counts,
            "public_water_count": access_db.get("public_water_count", 0),
            "access_point_count": access_db.get("access_point_count", 0),
            "fishery_reference_count": access_db.get("fishery_reference_count", 0),
            "counties_with_no_public_access_records": [c["county"] for c in access_db.get("counties", []) if c.get("public_water_count", 0) == 0],
            "warnings": warnings,
            "errors": errors,
        }
        report_build = {
            "generated_at": generated_at,
            "success": True,
            "state": STATE,
            "source_counts": source_counts,
            "public_water_count": report_db.get("public_water_count", 0),
            "report_count": report_db.get("report_count", 0),
            "unmatched_report_count": len(report_db.get("unmatched_reports", [])),
            "warnings": warnings,
            "errors": errors,
        }
        write_access_outputs(output_dir, access_db, access_build)
        write_report_outputs(output_dir, report_db, report_build)
        install_site_integration(root)
        validate(access_db, report_db, root)

        status = {
            "generated_at": generated_at,
            "state": STATE,
            "completed": [
                "Verified official 56-county order",
                "Built official public-access collector",
                "Built official survey, stocking, restriction and news collectors",
                "Built county-by-county public page",
                "Installed multi-state admin dashboard builder",
                "Updated navigation, sitemap and PWA cache",
                "Validated all 56 county shells and output files",
            ],
            "known_issues": warnings,
            "failed_sources": [w for w in warnings if "failed" in w.lower()],
            "deployment_status": "ready_to_commit" if not args.skip_network else "bootstrap_validated",
            "public_water_count": access_db.get("public_water_count", 0),
            "report_count": report_db.get("report_count", 0),
        }
        write_json(output_dir / "montana_project_status.json", status)

        # Rebuild the existing admin feed from Idaho + Montana when at least one state DB has reports.
        if not args.skip_network:
            import subprocess
            subprocess.run([sys.executable, str(root / "build_admin_dashboard_files.py"), "--output-dir", str(root)], cwd=root, check=True)

        print(json.dumps({
            "state": STATE,
            "county_count": 56,
            "public_water_count": access_db.get("public_water_count", 0),
            "access_point_count": access_db.get("access_point_count", 0),
            "report_count": report_db.get("report_count", 0),
            "warnings": len(warnings),
            "mode": "bootstrap" if args.skip_network else "live",
        }, indent=2))
        return 0
    except Exception as exc:
        errors.append(str(exc))
        write_json(output_dir / "montana_project_status.json", {
            "generated_at": generated_at,
            "state": STATE,
            "deployment_status": "failed",
            "known_issues": warnings,
            "errors": errors,
        })
        raise


if __name__ == "__main__":
    raise SystemExit(main())
