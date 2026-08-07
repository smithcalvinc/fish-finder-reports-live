#!/usr/bin/env python3
"""Build Utah Fish Finder Outdoors county data from official public sources.

This one-file state builder creates and maintains:
- the authoritative 29-county list
- conservative public fishing-water and access records
- current Utah DWR stocking and fishing-news records
- the Utah county search page
- the shared multi-state admin dashboard feed
- navigation, sitemap and PWA cache integration

Public-water policy
-------------------
A water is published only when it appears in an official Utah Division of
Wildlife Resources angler-facing source: the current/recent fish-stocking
report, the official community-fisheries GIS layer, the accessible-fishing
list, or a deliberately maintained official-access override. Blank or invalid
coordinates never create a map link.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse, parse_qs
from urllib.request import Request, urlopen

try:
    from bs4 import BeautifulSoup
except ImportError:  # installed by GitHub Actions
    BeautifulSoup = None

STATE = "Utah"
STATE_ABBR = "UT"
COUNTIES = [
    "Beaver", "Box Elder", "Cache", "Carbon", "Daggett", "Davis",
    "Duchesne", "Emery", "Garfield", "Grand", "Iron", "Juab", "Kane",
    "Millard", "Morgan", "Piute", "Rich", "Salt Lake", "San Juan",
    "Sanpete", "Sevier", "Summit", "Tooele", "Uintah", "Utah",
    "Wasatch", "Washington", "Wayne", "Weber",
]
COUNTY_NUMBER = {name: i + 1 for i, name in enumerate(COUNTIES)}

USER_AGENT = "FishFinderOutdoors-UtahBuilder/1.0 (+https://fishfinderoutdoors.com)"
STOCKING_URL = "https://dwrapps.utah.gov/fishstocking/Fish"
COMMUNITY_LAYER = (
    "https://dwrmapserv.utah.gov/arcgis/rest/services/Aquatics/"
    "Aquatics_Community_Fisheries/MapServer/0"
)
OFFICIAL_URLS = {
    "fishing": "https://wildlife.utah.gov/fishing",
    "fish_utah": "https://fish.utah.gov",
    "stocking": STOCKING_URL,
    "community": "https://wildlife.utah.gov/fishing/communityponds",
    "accessible": "https://wildlife.utah.gov/accessibility/fishing",
    "stream_access": "https://wildlife.utah.gov/streamaccess",
    "blue_ribbon": "https://wildlife.utah.gov/blueribbon",
    "news": "https://wildlife.utah.gov/news",
    "guidebooks": "https://wildlife.utah.gov/guidebooks",
}

NEWS_KEYWORDS = (
    "fish", "fishing", "angler", "trout", "salmon", "kokanee", "bass",
    "walleye", "muskie", "perch", "crappie", "catfish", "reservoir",
    "river", "lake", "creek", "stream", "pond", "stocking", "fishery",
    "waterbody", "water level", "daily limit", "blue ribbon",
)

STREAM_ACCESS_NAMES = (
    "Duchesne River", "Little Bear River", "Ogden River", "Provo River",
    "Salt Creek", "Sanpitch River", "Spanish Fork River", "Strawberry River",
    "Thistle Creek", "Weber River",
)

MANAGEMENT_SUFFIXES = {
    "FL", "NBS", "NCL", "BTN", "BTS", "EMW", "GR", "U", "G", "BR",
}
ABBREVIATIONS = {
    "L": "Lake", "R": "River", "CR": "Creek", "RES": "Reservoir",
    "FK": "Fork", "N": "North", "S": "South", "E": "East", "W": "West",
    "UPR": "Upper", "LWR": "Lower", "NO": "Number",
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


def canonical_county(value: Any) -> str:
    text = re.sub(r"\s+county$", "", clean(value), flags=re.I)
    key = norm(text)
    return {norm(name): name for name in COUNTIES}.get(key, "")


def valid_lon_lat(lon: Any, lat: Any) -> bool:
    try:
        x, y = float(lon), float(lat)
    except (TypeError, ValueError):
        return False
    return -114.3 <= x <= -108.7 and 36.7 <= y <= 42.2


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
                "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
            })
            with urlopen(req, timeout=timeout) as response:
                return response.read()
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
        raise RuntimeError(f"ArcGIS error for {url}: {payload['error']}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected JSON payload from {url}")
    return payload


def arcgis_query_url(layer_url: str, params: dict[str, Any]) -> str:
    return f"{layer_url}/query?{urlencode(params)}"


def arcgis_features(layer_url: str, chunk_size: int = 500) -> list[dict[str, Any]]:
    ids_payload = request_json(arcgis_query_url(layer_url, {
        "where": "1=1", "returnIdsOnly": "true", "f": "json",
    }))
    ids = sorted(set(ids_payload.get("objectIds") or []))
    rows: list[dict[str, Any]] = []
    for start in range(0, len(ids), chunk_size):
        chunk = ids[start:start + chunk_size]
        payload = request_json(arcgis_query_url(layer_url, {
            "objectIds": ",".join(str(v) for v in chunk),
            "outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "json",
        }))
        rows.extend(payload.get("features") or [])
    return rows


def smart_water_name(value: Any) -> str:
    raw = clean(value).upper()
    if not raw:
        return ""
    # Remove common DWR management suffixes only at the end of a name.
    raw = re.sub(r"\s+(?:[A-Z]{1,4}-\d+|NBS|NCL|BTN|BTS|EMW|FL)$", "", raw)
    for abbreviation, full in ABBREVIATIONS.items():
        raw = re.sub(rf"\b{re.escape(abbreviation)}\b", full.upper(), raw)
    raw = raw.replace("#", " #")
    text = raw.title()
    text = re.sub(r"\s+", " ", text).strip(" ,")
    return text


def water_type(name: str) -> str:
    lower = name.lower()
    for kind in ("reservoir", "lake", "pond", "river", "creek", "stream", "slough", "canal"):
        if re.search(rf"\b{kind}\b", lower):
            return kind
    return "waterbody"


def report_id(*parts: Any) -> str:
    raw = "|".join(clean(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:18]


def make_report(
    *, source_type: str, source_name: str, source_url: str, title: str,
    summary: str, report_date: str, water_name: str = "",
    counties: list[str] | None = None, species: str = "", techniques: str = "",
    access_notes: str = "", official: bool = True, observed_period: str = "",
    raw_source_reference: str = "", rating: str = "",
) -> dict[str, Any]:
    report_date = report_date or today_iso()
    counties = [c for c in (counties or []) if c in COUNTIES]
    return {
        "report_id": report_id(source_url, report_date, water_name, title, species),
        "source_type": source_type,
        "source_name": clean(source_name),
        "source_url": clean(source_url),
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
        "raw_source_reference": clean(raw_source_reference),
    }


def parse_quantity(value: Any) -> int | None:
    digits = re.sub(r"[^0-9]", "", clean(value))
    return int(digits) if digits else None


def collect_stocking(year: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required")
    url = f"{STOCKING_URL}?y={year}"
    soup = BeautifulSoup(request_text(url), "html.parser")
    events: list[dict[str, Any]] = []
    waters: dict[tuple[str, str], dict[str, Any]] = {}
    for tr in soup.find_all("tr"):
        cells = [clean(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
        if len(cells) < 6 or cells[0].lower().startswith("water"):
            continue
        raw_name, county_raw, species, quantity_raw, length_raw, date_raw = cells[:6]
        county = canonical_county(county_raw)
        report_date = parse_date(date_raw)
        if not raw_name or not county or not report_date:
            continue
        name = smart_water_name(raw_name)
        key = (county, norm(name))
        waters.setdefault(key, {
            "county": county,
            "water_name": name,
            "raw_names": [],
            "water_type": water_type(name),
            "verification": "official_utah_dwr_angler_stocking_report",
            "source_url": url,
        })
        if raw_name not in waters[key]["raw_names"]:
            waters[key]["raw_names"].append(raw_name)
        quantity = parse_quantity(quantity_raw)
        summary = f"Utah DWR stocked {quantity:,} {species.lower()}" if quantity is not None else f"Utah DWR stocked {species.lower()}"
        if length_raw:
            summary += f" averaging {length_raw} inches"
        summary += f" at {name} on {report_date}."
        events.append(make_report(
            source_type="official_stocking_update",
            source_name="Utah Division of Wildlife Resources",
            source_url=url,
            title=f"{name} fish stocking — {species.title()}",
            summary=summary,
            report_date=report_date,
            water_name=name,
            counties=[county],
            species=species.title(),
            techniques="Recent stocking information",
            raw_source_reference=raw_name,
        ))
    return list(waters.values()), events


def bool_from_text(text: Any, terms: tuple[str, ...]) -> bool | None:
    value = clean(text).lower()
    if not value:
        return None
    return any(term in value for term in terms)


def coordinates_from_href(href: str) -> tuple[float | None, float | None]:
    href = clean(href)
    if not href:
        return None, None
    decoded = href.replace("%2C", ",").replace("%20", " ")
    patterns = [
        r"(?:query|q|destination)=(-?\d{2,3}\.\d+)\s*,\s*(-?\d{2,3}\.\d+)",
        r"/@(-?\d{2,3}\.\d+),(-?\d{2,3}\.\d+)",
        r"(-?\d{2,3}\.\d+)\s*,\s*(-?\d{2,3}\.\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, decoded)
        if match:
            lat, lon = safe_float(match.group(1)), safe_float(match.group(2))
            if valid_lon_lat(lon, lat):
                return lat, lon
    return None, None


def collect_community_fisheries() -> list[dict[str, Any]]:
    results = []
    for feature in arcgis_features(COMMUNITY_LAYER):
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}
        county = canonical_county(attrs.get("County"))
        name = clean(attrs.get("WaterName") or attrs.get("WTRNAME"))
        if not county or not name:
            continue
        lon = safe_float(geom.get("x") or attrs.get("LONG_PARK"))
        lat = safe_float(geom.get("y") or attrs.get("LAT_PARK"))
        if not valid_lon_lat(lon, lat):
            lon, lat = None, None
        amenities_text = clean(attrs.get("Amenities"))
        handicap = clean(attrs.get("HandicapAc"))
        directions = clean(attrs.get("Directions"))
        google_url = clean(attrs.get("google_url"))
        if not google_url and lat is not None and lon is not None:
            google_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        amenities = {
            "camping": bool_from_text(amenities_text, ("camp",)),
            "restroom": bool_from_text(amenities_text, ("restroom", "toilet")),
            "boat_ramp": bool_from_text(amenities_text, ("boat ramp", "launch")),
            "dock": bool_from_text(amenities_text, ("dock", "pier")),
            "ada_fishing": True if handicap else bool_from_text(amenities_text, ("ada", "accessible", "handicap")),
        }
        results.append({
            "county": county,
            "water_name": name,
            "water_type": water_type(name),
            "latitude": lat,
            "longitude": lon,
            "species": clean(attrs.get("Species")),
            "acres": clean(attrs.get("Acres")),
            "access_details": " ".join(v for v in (directions, amenities_text, handicap) if v),
            "verification": "official_utah_dwr_community_fishery",
            "source_url": OFFICIAL_URLS["community"],
            "access_point": {
                "access_point_name": name,
                "latitude": lat,
                "longitude": lon,
                "directions_url": google_url,
                "amenities": amenities,
                "access_flags": {},
                "access_details": " ".join(v for v in (directions, amenities_text, handicap) if v),
                "official_source_url": OFFICIAL_URLS["community"],
            },
        })
    return results


def collect_accessible_fishing() -> list[dict[str, Any]]:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required")
    soup = BeautifulSoup(request_text(OFFICIAL_URLS["accessible"]), "html.parser")
    results = []
    seen = set()
    for li in soup.find_all("li"):
        text = clean(li.get_text(" ", strip=True))
        match = re.match(r"(.+?)\s*\(([^()]+?)\s+County\)", text, flags=re.I)
        if not match:
            continue
        name = clean(match.group(1)).rstrip(":-")
        county = canonical_county(match.group(2))
        if not name or not county:
            continue
        key = (county, norm(name))
        if key in seen:
            continue
        seen.add(key)
        anchor = li.find("a", href=True)
        href = urljoin(OFFICIAL_URLS["accessible"], anchor["href"]) if anchor else ""
        lat, lon = coordinates_from_href(href)
        results.append({
            "county": county,
            "water_name": name,
            "water_type": water_type(name),
            "latitude": lat,
            "longitude": lon,
            "access_details": "Utah DWR lists this water as accommodating anglers with physical challenges. Conditions and surface standards vary; verify before traveling.",
            "verification": "official_utah_dwr_accessible_fishing_list",
            "source_url": OFFICIAL_URLS["accessible"],
            "access_point": {
                "access_point_name": f"{name} accessible fishing area",
                "latitude": lat,
                "longitude": lon,
                "directions_url": href if href.startswith("http") else "",
                "amenities": {"camping": None, "restroom": None, "boat_ramp": None, "dock": None, "ada_fishing": True},
                "access_flags": {},
                "access_details": "Listed by Utah DWR for anglers with physical challenges.",
                "official_source_url": OFFICIAL_URLS["accessible"],
            },
        })
    return results


def dedupe_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for report in reports:
        rid = report.get("report_id") or report_id(report)
        current = unique.get(rid)
        if current is None or len(clean(report.get("summary"))) > len(clean(current.get("summary"))):
            unique[rid] = report
    return sorted(unique.values(), key=lambda r: (r.get("report_date") or "", r.get("title") or ""), reverse=True)


def collect_news(water_keys: dict[str, list[tuple[str, str]]]) -> list[dict[str, Any]]:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required")
    soup = BeautifulSoup(request_text(OFFICIAL_URLS["news"]), "html.parser")
    reports = []
    seen_urls = set()
    for heading in soup.find_all(["h2", "h3", "h4"]):
        title = clean(heading.get_text(" ", strip=True))
        if not title or not any(keyword in title.lower() for keyword in NEWS_KEYWORDS):
            continue
        anchor = heading.find("a", href=True) or heading.find_parent("a", href=True)
        if not anchor:
            anchor = heading.find_next("a", href=True)
        href = urljoin(OFFICIAL_URLS["news"], anchor["href"]) if anchor else OFFICIAL_URLS["news"]
        if href in seen_urls:
            continue
        seen_urls.add(href)
        container = heading.find_parent(["article", "div", "li"]) or heading.parent
        text = clean(container.get_text(" ", strip=True) if container else title)
        report_date = parse_date(text) or today_iso()
        summary = clip(text.replace(title, "", 1).strip(" -"), 520) or title
        matched: list[tuple[str, str]] = []
        haystack = norm(f"{title} {summary}")
        for key, records in water_keys.items():
            if len(key) >= 5 and re.search(rf"\b{re.escape(key)}\b", haystack):
                matched.extend(records)
        # Prefer the longest named match and avoid flooding a report across many waters.
        matched = sorted(set(matched), key=lambda row: len(norm(row[1])), reverse=True)[:7]
        if matched:
            for county, water_name in matched:
                reports.append(make_report(
                    source_type="official_fishing_news",
                    source_name="Utah Division of Wildlife Resources",
                    source_url=href,
                    title=title,
                    summary=summary,
                    report_date=report_date,
                    water_name=water_name,
                    counties=[county],
                ))
        else:
            reports.append(make_report(
                source_type="official_statewide_or_regional_update",
                source_name="Utah Division of Wildlife Resources",
                source_url=href,
                title=title,
                summary=summary,
                report_date=report_date,
            ))
    return reports


def merge_water_sources(source_rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    waters: dict[tuple[str, str], dict[str, Any]] = {}
    for source in source_rows:
        county = canonical_county(source.get("county"))
        name = clean(source.get("water_name"))
        if not county or not name:
            continue
        key = (county, norm(name))
        row = waters.setdefault(key, {
            "county_number": COUNTY_NUMBER[county],
            "county": county,
            "water_name": name,
            "water_type": source.get("water_type") or water_type(name),
            "latitude": None,
            "longitude": None,
            "drainage": "",
            "community_fishery": False,
            "accessible_fishing": False,
            "public_access_verification": [],
            "official_access_source_url": source.get("source_url") or OFFICIAL_URLS["fish_utah"],
            "access_details": "",
            "access_points": [],
            "alternate_names": [],
        })
        raw_names = source.get("raw_names") or []
        for raw_name in raw_names:
            if raw_name and raw_name not in row["alternate_names"]:
                row["alternate_names"].append(raw_name)
        verification = clean(source.get("verification"))
        if verification and verification not in row["public_access_verification"]:
            row["public_access_verification"].append(verification)
        lat, lon = source.get("latitude"), source.get("longitude")
        if valid_lon_lat(lon, lat) and not valid_lon_lat(row.get("longitude"), row.get("latitude")):
            row["latitude"], row["longitude"] = float(lat), float(lon)
        details = clean(source.get("access_details"))
        if details and details not in row["access_details"]:
            row["access_details"] = " ".join(v for v in (row["access_details"], details) if v)
        if "community" in verification:
            row["community_fishery"] = True
        if "accessible" in verification:
            row["accessible_fishing"] = True
        point = source.get("access_point")
        if point:
            signature = (norm(point.get("access_point_name")), point.get("latitude"), point.get("longitude"))
            existing = {(norm(p.get("access_point_name")), p.get("latitude"), p.get("longitude")) for p in row["access_points"]}
            if signature not in existing:
                row["access_points"].append(point)
    # Official stocking reports are angler-facing; stream names in the DWR guaranteed-access list get an extra verification marker.
    stream_keys = [norm(name) for name in STREAM_ACCESS_NAMES]
    for row in waters.values():
        key = norm(row["water_name"])
        if any(stream in key or key in stream for stream in stream_keys):
            marker = "official_utah_dwr_stream_access_information"
            if marker not in row["public_access_verification"]:
                row["public_access_verification"].append(marker)
    return waters


def assemble_database(waters: dict[tuple[str, str], dict[str, Any]], reports: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    reports = dedupe_reports(reports)
    reports_by_water: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    statewide_reports = []
    unmatched_reports = []
    for report in reports:
        water_name = clean(report.get("water_name"))
        counties = report.get("counties") or []
        if water_name and counties:
            for county in counties:
                reports_by_water[(county, norm(water_name))].append(report)
        elif water_name:
            unmatched_reports.append(report)
        else:
            statewide_reports.append(report)

    county_blocks = []
    flat_waters = []
    for number, county in enumerate(COUNTIES, start=1):
        county_waters = []
        for (water_county, key), base in sorted(waters.items(), key=lambda item: (item[0][0], item[1]["water_name"])):
            if water_county != county:
                continue
            candidate = dedupe_reports(reports_by_water.get((county, key), []))
            latest = candidate[0] if candidate else None
            row = dict(base)
            row["public_access_verification"] = "; ".join(row.get("public_access_verification") or [])
            row.update({
                "access_point_count": len(row.get("access_points") or []),
                "report_status": latest.get("freshness") if latest else "no_recent_public_report_found",
                "latest_report": latest,
                "recent_reports": candidate[:10],
                "report_count": len(candidate),
            })
            county_waters.append(row)
            flat_waters.append(row)
        county_reports = [r for r in reports if county in (r.get("counties") or [])]
        county_blocks.append({
            "county_number": number,
            "county": county,
            "public_water_count": len(county_waters),
            "waters_with_reports": sum(1 for w in county_waters if w["report_count"] > 0),
            "waters_without_reports": sum(1 for w in county_waters if w["report_count"] == 0),
            "public_access_point_count": sum(w["access_point_count"] for w in county_waters),
            "county_report_count": len(county_reports),
            "waters": county_waters,
        })

    return {
        "metadata": {
            "state": STATE,
            "title": "Utah Public Fishing Access and Current Fishing Reports",
            "version": "1.0",
            "generated_at": generated_at,
            "public_access_only": True,
            "county_order": "1 Beaver through 29 Weber",
            "access_policy": (
                "Waters are included from official Utah DWR angler-facing stocking, community-fishery, accessible-fishing, or official-access sources. "
                "A map button is shown only for a validated Utah coordinate or a validated official access point."
            ),
            "sources": [
                {"name": "Utah Division of Wildlife Resources — Fish Utah", "type": "official", "url": OFFICIAL_URLS["fish_utah"]},
                {"name": "Utah DWR Fish Stocking Report", "type": "official", "url": OFFICIAL_URLS["stocking"]},
                {"name": "Utah DWR Community Fisheries", "type": "official", "url": OFFICIAL_URLS["community"]},
                {"name": "Utah DWR Accessible Fishing", "type": "official", "url": OFFICIAL_URLS["accessible"]},
                {"name": "Utah DWR Stream Access", "type": "official", "url": OFFICIAL_URLS["stream_access"]},
                {"name": "Utah Wildlife News", "type": "official", "url": OFFICIAL_URLS["news"]},
            ],
        },
        "county_count": 29,
        "public_water_count": len(flat_waters),
        "report_count": len(reports),
        "statewide_reports": statewide_reports[:100],
        "unmatched_reports": unmatched_reports,
        "counties": county_blocks,
        "flat_waters": flat_waters,
        "flat_reports": reports,
    }



def validate_community_layer_schema() -> int:
    """Fail when Utah DWR changes or removes fields required by this builder."""
    payload = request_json(f"{COMMUNITY_LAYER}?f=pjson")
    fields = {
        clean(field.get("name")).lower()
        for field in (payload.get("fields") or [])
        if isinstance(field, dict)
    }
    if "county" not in fields:
        raise RuntimeError("Community-fisheries GIS schema is missing County")
    if not ({"watername", "wtrname"} & fields):
        raise RuntimeError("Community-fisheries GIS schema is missing WaterName/WTRNAME")
    geometry_type = clean(payload.get("geometryType")).lower()
    if geometry_type and "point" not in geometry_type:
        raise RuntimeError(
            f"Community-fisheries GIS geometry changed unexpectedly: {geometry_type}"
        )
    if len(fields) < 5:
        raise RuntimeError(
            f"Community-fisheries GIS returned only {len(fields)} fields"
        )
    return len(fields)


def validate_news_page() -> int:
    """Confirm the Utah DWR news page is healthy, even when no fishing story is current."""
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required")
    soup = BeautifulSoup(request_text(OFFICIAL_URLS["news"]), "html.parser")
    article_urls = set()
    for heading in soup.find_all(["h2", "h3", "h4"]):
        anchor = heading.find("a", href=True) or heading.find_parent("a", href=True)
        if not anchor:
            continue
        title = clean(heading.get_text(" ", strip=True))
        href = urljoin(OFFICIAL_URLS["news"], clean(anchor.get("href")))
        if title and href.startswith("http"):
            article_urls.add(href)
    if len(article_urls) < 5:
        raise RuntimeError(
            f"Utah DWR news page exposed only {len(article_urls)} article links"
        )
    return len(article_urls)


def current_year_stocking_minimums(month: int | None = None) -> tuple[int, int]:
    """Season-aware minimums so January is not treated like peak stocking season."""
    month = month or datetime.now(timezone.utc).month
    minimum_events = {
        1: 0, 2: 5, 3: 20, 4: 50, 5: 100, 6: 150,
        7: 200, 8: 225, 9: 250, 10: 275, 11: 300, 12: 300,
    }[month]
    minimum_waters = {
        1: 0, 2: 2, 3: 8, 4: 18, 5: 35, 6: 50,
        7: 70, 8: 75, 9: 80, 10: 85, 11: 90, 12: 90,
    }[month]
    return minimum_waters, minimum_events


def validate_map_data(db: dict[str, Any]) -> dict[str, int]:
    invalid_coordinates: list[str] = []
    invalid_urls: list[str] = []
    water_coordinate_count = 0
    access_coordinate_count = 0

    for water in db.get("flat_waters") or []:
        label = f"{clean(water.get('county'))}: {clean(water.get('water_name'))}"
        lat, lon = water.get("latitude"), water.get("longitude")
        has_lat = lat not in (None, "")
        has_lon = lon not in (None, "")
        if has_lat != has_lon:
            invalid_coordinates.append(f"{label} has only one coordinate")
        elif has_lat:
            if not valid_lon_lat(lon, lat):
                invalid_coordinates.append(f"{label} has out-of-Utah coordinates {lat},{lon}")
            else:
                water_coordinate_count += 1

        for point in water.get("access_points") or []:
            point_name = clean(point.get("access_point_name")) or label
            plat, plon = point.get("latitude"), point.get("longitude")
            has_plat = plat not in (None, "")
            has_plon = plon not in (None, "")
            if has_plat != has_plon:
                invalid_coordinates.append(f"{point_name} has only one coordinate")
            elif has_plat:
                if not valid_lon_lat(plon, plat):
                    invalid_coordinates.append(
                        f"{point_name} has out-of-Utah coordinates {plat},{plon}"
                    )
                else:
                    access_coordinate_count += 1

            directions = clean(point.get("directions_url"))
            lowered = directions.lower().replace("%2c", ",").replace("%20", " ")
            if any(token in lowered for token in (
                "query=null", "query=undefined", "query=,", "query=0,0",
                "destination=null", "destination=undefined",
            )):
                invalid_urls.append(f"{point_name}: {directions}")

    if invalid_coordinates:
        raise RuntimeError(
            "Invalid Utah coordinate data: " + "; ".join(invalid_coordinates[:10])
        )
    if invalid_urls:
        raise RuntimeError(
            "Invalid Utah map URLs: " + "; ".join(invalid_urls[:10])
        )

    return {
        "water_coordinates": water_coordinate_count,
        "access_coordinates": access_coordinate_count,
    }


def validate_live_build(
    db: dict[str, Any],
    source_counts: dict[str, int],
    failed_sources: list[str],
    current_year: int,
) -> dict[str, Any]:
    """Refuse partial, empty, malformed or geographically unsafe live builds."""
    if failed_sources:
        raise RuntimeError(
            "Required Utah source failures: " + " | ".join(failed_sources)
        )

    current_water_min, current_event_min = current_year_stocking_minimums()
    minimums = {
        f"stocking_{current_year}_waters": current_water_min,
        f"stocking_{current_year}_events": current_event_min,
        f"stocking_{current_year - 1}_waters": 150,
        f"stocking_{current_year - 1}_events": 500,
        "community_schema_fields": 5,
        "community_fisheries": 20,
        "accessible_fishing": 15,
        "utah_dwr_news_articles_scanned": 5,
    }

    shortfalls = []
    for key, minimum in minimums.items():
        actual = int(source_counts.get(key, 0) or 0)
        if actual < minimum:
            shortfalls.append(f"{key}={actual}, expected at least {minimum}")
    if shortfalls:
        raise RuntimeError("Utah source-count validation failed: " + "; ".join(shortfalls))

    counties = db.get("counties") or []
    if db.get("county_count") != 29 or len(counties) != 29:
        raise RuntimeError("Utah database did not create all 29 county shells")
    if [row.get("county") for row in counties] != COUNTIES:
        raise RuntimeError("Utah county order is not Beaver through Weber")

    public_water_count = int(db.get("public_water_count", 0) or 0)
    report_count = int(db.get("report_count", 0) or 0)
    if public_water_count < 200:
        raise RuntimeError(
            f"Utah build produced only {public_water_count} public waters"
        )
    if report_count < 500:
        raise RuntimeError(
            f"Utah build produced only {report_count} report records"
        )

    populated_counties = sum(
        1 for county in counties if int(county.get("public_water_count", 0) or 0) > 0
    )
    if populated_counties < 25:
        raise RuntimeError(
            f"Only {populated_counties} of 29 Utah counties contain water records"
        )

    map_counts = validate_map_data(db)
    page = county_page_html()
    required_page_tokens = (
        "function validCoordinate",
        "function mapPoint",
        "const mapHtml=map?",
        "36.7,42.2",
        "-114.3,-108.7",
    )
    missing_tokens = [token for token in required_page_tokens if token not in page]
    if missing_tokens:
        raise RuntimeError(
            "Utah map-safety code is incomplete: " + ", ".join(missing_tokens)
        )
    if "Number.isFinite(Number(w.latitude))" in page:
        raise RuntimeError("Old null-to-zero map-link logic is still present")

    return {
        "passed": True,
        "public_water_count": public_water_count,
        "report_count": report_count,
        "populated_counties": populated_counties,
        "source_minimums": minimums,
        **map_counts,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def write_outputs(root: Path, output_dir: Path, db: dict[str, Any], status: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "utah_fishing_report_database.json", db)
    (output_dir / "utah_fishing_report_database.js").write_text(
        "/* Automatically generated. Do not hand-edit. */\nwindow.UTAH_FISHING_REPORT_DATABASE = "
        + json.dumps(db, separators=(",", ":"), ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )
    write_json(output_dir / "utah_public_fishing_access.json", {
        "metadata": db["metadata"],
        "county_count": db["county_count"],
        "public_water_count": db["public_water_count"],
        "counties": db["counties"],
        "flat_waters": db["flat_waters"],
    })
    (output_dir / "utah_public_fishing_access.js").write_text(
        "/* Automatically generated. Do not hand-edit. */\nwindow.UTAH_PUBLIC_FISHING_ACCESS = "
        + json.dumps({"metadata": db["metadata"], "county_count": 29, "public_water_count": db["public_water_count"], "counties": db["counties"], "flat_waters": db["flat_waters"]}, separators=(",", ":"), ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )
    write_json(output_dir / "utah_project_status.json", status)
    write_json(root / "config/utah_counties.json", {"state": STATE, "county_count": 29, "counties": [{"county_number": i + 1, "county": c} for i, c in enumerate(COUNTIES)]})
    with (output_dir / "utah_counties.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle); writer.writerow(["county_number", "county"])
        writer.writerows((i + 1, c) for i, c in enumerate(COUNTIES))
    with (output_dir / "utah_fishing_report_database.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["report_id", "report_date", "freshness", "age_days", "county", "water_name", "source_type", "source_name", "official", "title", "summary", "species", "techniques", "source_url"]
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for report in db["flat_reports"]:
            counties = report.get("counties") or [""]
            for county in counties:
                writer.writerow({field: (county if field == "county" else report.get(field, "")) for field in fields})


def county_page_html() -> str:
    return r'''<!DOCTYPE html>
<html lang="en">
<head>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-W1278FPSQK"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-W1278FPSQK');</script>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><meta name="theme-color" content="#1F4D3A"/>
<meta name="description" content="Search verified public fishing waters, access points and recent fishing information across all 29 Utah counties."/>
<title>Utah County Fishing Reports & Public Access | Fish Finder Outdoors</title>
<link rel="icon" href="ffo-logo-main.png" type="image/png"/><link rel="apple-touch-icon" href="ffo-logo-main.png"/><link rel="manifest" href="manifest.json"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Bitter:wght@600;700;800&family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="brand-shell.css"/>
<style>
:root{--green:#1f4d3a;--paper:#f4f1e7;--card:#fffdf8;--line:#d8d3c7;--ink:#173029;--muted:#64716c;--warn:#7a5d1f;--danger:#96352c}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#e9f0ea,#f4f1e7 320px);color:var(--ink);font-family:Inter,Arial,sans-serif}.wrap{width:min(1180px,calc(100% - 28px));margin:auto}.hero{padding:38px 0 20px}.hero-grid{display:grid;grid-template-columns:1.25fr .75fr;gap:26px;align-items:center}.kicker{display:inline-flex;padding:7px 11px;border-radius:999px;background:#e2eee7;color:var(--green);font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}.hero h1{font-family:Bitter,Georgia,serif;font-size:clamp(36px,6vw,64px);line-height:1.02;margin:16px 0 12px}.hero p{font-size:18px;color:var(--muted);max-width:760px}.hero-logo{width:min(300px,100%);justify-self:end}.panel{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;margin:18px 0;box-shadow:0 10px 30px rgba(31,77,58,.07)}.controls{display:grid;grid-template-columns:1.2fr 1fr repeat(3,auto);gap:10px;align-items:end}.field label{display:block;font-size:12px;font-weight:900;margin:0 0 5px}.field select,.field input{width:100%;padding:12px 13px;border:1px solid #bfc7c1;border-radius:12px;background:white;font:inherit}.check{display:flex;align-items:center;gap:7px;padding:11px 10px;background:#eef4f0;border-radius:12px;font-size:12px;font-weight:800;white-space:nowrap}.check input{width:18px;height:18px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}button,.button{border:0;border-radius:12px;padding:11px 14px;font:inherit;font-weight:850;cursor:pointer;text-decoration:none}.primary{background:var(--green);color:white}.secondary{background:#e3ece7;color:var(--green)}.status{padding:12px 14px;border-radius:12px;background:#edf4f0;color:var(--green);font-weight:750;margin-top:13px}.status.warning{background:#fff5d9;color:var(--warn)}.status.error{background:#fae5e1;color:var(--danger)}.summary{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.metric{background:white;border:1px solid var(--line);border-radius:14px;padding:13px}.metric span{font-size:12px;color:var(--muted);font-weight:700}.metric b{display:block;font-size:25px;margin-top:4px}.water-list{display:grid;gap:13px}.water-card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px}.water-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}.water-head h2{font-family:Bitter,Georgia,serif;margin:0;font-size:25px}.chips{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0}.chip{display:inline-flex;padding:5px 8px;border-radius:999px;background:#e8f0eb;border:1px solid #c9dbd1;font-size:11px;font-weight:850}.chip.current{background:#daf1e4;color:#176354}.chip.recent{background:#fff0c5;color:#705319}.chip.stale{background:#f5dedb;color:#8d3029}.chip.none{background:#ecebe7;color:#666}.details{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:13px}.box{border:1px solid var(--line);border-radius:14px;padding:14px;background:white}.box h3{font-size:15px;margin:0 0 9px}.box p{margin:7px 0;color:#3f504a}.access{border-top:1px solid var(--line);padding-top:10px;margin-top:10px}.amenities{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}.amenity{font-size:11px;padding:5px 7px;border-radius:8px;background:#f0f3ef}.report-link{display:inline-flex;margin-top:8px;font-weight:850}.muted{color:var(--muted);font-size:13px}.empty{padding:28px;text-align:center;border:1px dashed #b9b3a6;border-radius:16px;background:#fbf8f1}.footer-note{font-size:13px;color:var(--muted);line-height:1.6}.top-links{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}.top-links a{display:inline-flex;padding:10px 12px;border-radius:12px;background:white;border:1px solid var(--line);font-weight:800;text-decoration:none}.load-more{display:block;margin:18px auto}.hidden{display:none!important}@media(max-width:900px){.hero-grid{grid-template-columns:1fr}.hero-logo{justify-self:start;max-width:220px}.controls{grid-template-columns:1fr 1fr}.summary{grid-template-columns:1fr 1fr}.details{grid-template-columns:1fr}}@media(max-width:600px){.controls{grid-template-columns:1fr}.summary{grid-template-columns:1fr 1fr}.water-head{display:block}.panel{padding:15px}.hero{padding-top:24px}}
</style></head>
<body>
<header class="ffo-site-header"><div class="ffo-header-inner"><a class="ffo-logo-link" href="https://fishfinderoutdoors.com"><img src="ffo-logo-main.png" alt="Fish Finder Outdoors logo"/><span class="ffo-wordmark"><strong>Fish Finder</strong><span>Outdoors</span></span></a><button class="ffo-menu-button" aria-label="Open menu" aria-expanded="false" type="button">☰</button><nav class="ffo-nav" aria-label="Fish Finder Outdoors"><a href="https://fishfinderoutdoors.com">Home</a><a href="index.html">Fishing Reports</a><a href="idaho-county-reports.html">Idaho County Reports</a><a href="montana-county-reports.html">Montana County Reports</a><a class="active" href="utah-county-reports.html">Utah County Reports</a><a href="submit-report.html">Submit Report</a><a href="official-sources.html">Official Sources</a></nav></div></header>
<div class="ffo-beta-bar">PUBLIC ACCESS ONLY • 29 UTAH COUNTIES • REPORT DATES AND SOURCES SHOWN • <button class="ffo-install-button" data-install-ffo-app hidden type="button">Install App</button></div>
<main><section class="hero"><div class="wrap hero-grid"><div><span class="kicker">Utah statewide directory</span><h1>Public fishing waters and current information, county by county.</h1><p>Search Utah DWR stocking waters, community fisheries and verified accessible fishing locations across all 29 counties. Map buttons appear only when a dependable Utah coordinate is available.</p><div class="top-links"><a href="index.html">← Main report generator</a><a href="submit-report.html">Submit a fishing report</a><a href="report-water.html">Report incorrect access</a></div></div><img class="hero-logo" src="ffo-logo-main.png" alt="Fish Finder Outdoors"/></div></section>
<div class="wrap"><section class="panel"><div class="controls"><div class="field"><label for="countySelect">County</label><select id="countySelect"><option value="">All 29 counties</option></select></div><div class="field"><label for="waterSearch">Water, species or report keyword</label><input id="waterSearch" placeholder="Lake, river, trout, stocking…"/></div><label class="check"><input id="currentOnly" type="checkbox"/> Current reports</label><label class="check"><input id="boatRamp" type="checkbox"/> Boat ramp</label><label class="check"><input id="adaFishing" type="checkbox"/> Accessible fishing</label></div><div class="actions"><button class="primary" id="searchButton" type="button">Search public waters</button><button class="secondary" id="clearButton" type="button">Clear filters</button></div><div class="status" id="status">Loading the Utah public-access database…</div></section>
<section class="panel"><div class="summary" id="summary"></div></section><section class="water-list" id="waterList"></section><button class="secondary load-more hidden" id="loadMore" type="button">Show more waters</button>
<section class="panel footer-note"><strong>How to read this page:</strong> Utah access, drought restrictions, emergency limits, water levels and roads can change. Stocking records are dated observations, not guarantees. Open the official source, check current Utah rules and obey posted signs before traveling.</section></div></main>
<footer class="ffo-site-footer"><div class="ffo-footer-grid"><div><a class="ffo-footer-brand" href="https://fishfinderoutdoors.com"><img src="ffo-logo-main.png" alt="Fish Finder Outdoors logo"/><span><strong>Fish Finder Outdoors</strong><br/><span style="color:#a9bbb3">Beginner friendly. Utah ready.</span></span></a></div><div><div class="ffo-footer-title">Reports</div><div class="ffo-footer-links"><a href="index.html">Main Report Generator</a><a href="idaho-county-reports.html">Idaho County Reports</a><a href="montana-county-reports.html">Montana County Reports</a><a href="utah-county-reports.html">Utah County Reports</a><a href="submit-report.html">Submit a Report</a><a href="official-sources.html">Official Sources</a></div></div></div><div class="ffo-footer-fine"><span>© 2026 Fish Finder Outdoors. Powered by Mountain Dog Enterprises.</span><span>Verify current regulations and access before fishing.</span></div></footer>
<script src="site_config.js"></script><script src="data/utah_fishing_report_database.js"></script><script>window.FFO_ACTIVE_FISHING_DATABASE=window.UTAH_FISHING_REPORT_DATABASE;</script><script src="fishing_report_search.js"></script>
<script>(function(){const $=id=>document.getElementById(id);const countySelect=$("countySelect"),waterSearch=$("waterSearch"),currentOnly=$("currentOnly"),boatRamp=$("boatRamp"),adaFishing=$("adaFishing"),status=$("status"),summary=$("summary"),waterList=$("waterList"),loadMore=$("loadMore");let filtered=[],shown=0;const PAGE_SIZE=25;const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));const label=value=>String(value||"").replace(/_/g," ").replace(/\b\w/g,c=>c.toUpperCase());function amenityText(a){const out=[];if(a?.boat_ramp===true)out.push("Boat ramp");if(a?.dock===true)out.push("Dock or pier");if(a?.restroom===true)out.push("Restroom");if(a?.camping===true)out.push("Camping");if(a?.ada_fishing===true)out.push("Accessible fishing");return out;}function validCoordinate(value,min,max){if(value===null||value===undefined||value==="")return false;const number=Number(value);return Number.isFinite(number)&&number>=min&&number<=max;}function mapPoint(w){if(validCoordinate(w.latitude,36.7,42.2)&&validCoordinate(w.longitude,-114.3,-108.7))return{lat:Number(w.latitude),lon:Number(w.longitude)};const p=(w.access_points||[]).find(p=>validCoordinate(p.latitude,36.7,42.2)&&validCoordinate(p.longitude,-114.3,-108.7));return p?{lat:Number(p.latitude),lon:Number(p.longitude)}:null;}function init(){const db=window.UTAH_FISHING_REPORT_DATABASE;if(!db||!Array.isArray(db.counties)){status.className="status error";status.textContent="The Utah fishing database could not be loaded.";return;}countySelect.innerHTML='<option value="">All 29 counties</option>'+db.counties.map(c=>`<option value="${esc(c.county)}">#${c.county_number} ${esc(c.county)} County</option>`).join("");status.textContent=`Database updated ${new Date(db.metadata.generated_at).toLocaleString()}. Choose a county or search a water.`;runSearch();}function runSearch(){const options={county:countySelect.value,query:waterSearch.value,boatRamp:boatRamp.checked,adaFishing:adaFishing.checked};filtered=window.FFO_FISHING_REPORT_SEARCH?.waters(options)||[];if(currentOnly.checked)filtered=filtered.filter(w=>["very_current","current"].includes(w.report_status));filtered.sort((a,b)=>(a.county_number-b.county_number)||String(a.water_name).localeCompare(String(b.water_name)));shown=0;waterList.innerHTML="";renderSummary();renderMore();status.className="status";status.textContent=`Found ${filtered.length.toLocaleString()} verified public water record${filtered.length===1?"":"s"}${countySelect.value?` in ${countySelect.value} County`:" statewide"}.`;}function renderSummary(){const reports=filtered.filter(w=>w.report_count>0).length;const access=filtered.reduce((n,w)=>n+(w.access_point_count||0),0);const ramps=filtered.filter(w=>(w.access_points||[]).some(p=>p.amenities?.boat_ramp===true)).length;const ada=filtered.filter(w=>(w.access_points||[]).some(p=>p.amenities?.ada_fishing===true)).length;summary.innerHTML=[["Public waters",filtered.length],["With reports",reports],["Access points",access],["With boat ramps",ramps],["Accessible fishing",ada]].map(([k,v])=>`<div class="metric"><span>${k}</span><b>${Number(v).toLocaleString()}</b></div>`).join("");}function renderMore(){const batch=filtered.slice(shown,shown+PAGE_SIZE);shown+=batch.length;if(!filtered.length)waterList.innerHTML='<div class="empty">No verified public waters matched these filters.</div>';else waterList.insertAdjacentHTML("beforeend",batch.map(card).join(""));loadMore.classList.toggle("hidden",shown>=filtered.length);}function card(w){const report=w.latest_report;const statusClass=w.report_status==="very_current"||w.report_status==="current"?"current":w.report_status==="recent"?"recent":w.report_status==="stale"?"stale":"none";const map=mapPoint(w);const mapHtml=map?`<a class="button secondary" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${map.lat},${map.lon}`)}" target="_blank" rel="noopener">Map</a>`:"";const points=(w.access_points||[]).map(p=>{const amenities=amenityText(p.amenities);return `<div class="access"><strong>${esc(p.access_point_name||"Public access point")}</strong>${p.access_details?`<p>${esc(p.access_details)}</p>`:""}${amenities.length?`<div class="amenities">${amenities.map(a=>`<span class="amenity">${esc(a)}</span>`).join("")}</div>`:""}${p.directions_url?`<a class="report-link" href="${esc(p.directions_url)}" target="_blank" rel="noopener">Directions</a>`:""}</div>`;}).join("");const reportHtml=report?`<strong>${esc(report.title||"Fishing update")}</strong><div class="chips"><span class="chip ${statusClass}">${esc(label(report.freshness))}</span><span class="chip">${esc(report.report_date||"")}</span><span class="chip">${esc(report.source_name||"")}</span></div><p>${esc(report.summary||"")}</p>${report.species?`<p><strong>Species:</strong> ${esc(report.species)}</p>`:""}${report.source_url?`<a class="report-link" href="${esc(report.source_url)}" target="_blank" rel="noopener">Open official source</a>`:""}`:'<div class="muted">No recent public fishing update was matched to this water.</div>';return `<article class="water-card"><div class="water-head"><div><h2>${esc(w.water_name)}</h2><div class="chips"><span class="chip">#${w.county_number} ${esc(w.county)} County</span><span class="chip">${esc(label(w.water_type))}</span><span class="chip ${statusClass}">${esc(label(w.report_status))}</span></div></div>${mapHtml}</div><div class="details"><div class="box"><h3>Latest fishing information</h3>${reportHtml}</div><div class="box"><h3>Verified public access</h3>${w.access_details?`<p>${esc(w.access_details)}</p>`:""}${points||'<div class="muted">No separately inventoried access point was matched. Check Fish Utah and posted signs.</div>'}${w.official_access_source_url?`<a class="report-link" href="${esc(w.official_access_source_url)}" target="_blank" rel="noopener">Official access source</a>`:""}</div></div></article>`;}$("searchButton").addEventListener("click",runSearch);$("clearButton").addEventListener("click",()=>{countySelect.value="";waterSearch.value="";currentOnly.checked=false;boatRamp.checked=false;adaFishing.checked=false;runSearch();});countySelect.addEventListener("change",runSearch);waterSearch.addEventListener("keydown",e=>{if(e.key==="Enter")runSearch();});loadMore.addEventListener("click",renderMore);init();})();</script><script src="brand-shell.js"></script><script src="pwa.js"></script></body></html>'''


def patch_site_files(root: Path) -> None:
    page = root / "utah-county-reports.html"
    page.write_text(county_page_html(), encoding="utf-8")

    brand = root / "brand-shell.js"
    if brand.exists():
        text = brand.read_text(encoding="utf-8")
        replacement = "const stateLinks=[['idaho-county-reports.html','Idaho County Reports'],['montana-county-reports.html','Montana County Reports'],['utah-county-reports.html','Utah County Reports']];"
        text = re.sub(r"const stateLinks=\[[^;]+;", replacement, text, count=1)
        brand.write_text(text, encoding="utf-8")

    worker = root / "service-worker.js"
    if worker.exists():
        text = worker.read_text(encoding="utf-8")
        version = re.search(r'ffo-reports-pwa-v(\d+)', text)
        if version:
            text = text.replace(version.group(0), f"ffo-reports-pwa-v{int(version.group(1)) + 1}", 1)
        if "./utah-county-reports.html" not in text:
            text = text.replace('"./montana-county-reports.html"', '"./montana-county-reports.html","./utah-county-reports.html"')
        for filename in (
            "utah_fishing_report_database.js", "utah_fishing_report_database.json",
            "utah_public_fishing_access.js", "utah_public_fishing_access.json",
        ):
            if filename not in text:
                text = text.replace('"montana_public_fishing_access.json"', f'"montana_public_fishing_access.json","{filename}"')
        worker.write_text(text, encoding="utf-8")

    sitemap = root / "sitemap.xml"
    if sitemap.exists():
        text = sitemap.read_text(encoding="utf-8")
        if "utah-county-reports.html" not in text:
            block = """  <url>\n    <loc>https://reports.fishfinderoutdoors.com/utah-county-reports.html</loc>\n    <changefreq>daily</changefreq>\n    <priority>0.9</priority>\n  </url>\n"""
            text = text.replace("</urlset>", block + "</urlset>")
            sitemap.write_text(text, encoding="utf-8")


def run_admin_builder(root: Path) -> None:
    builder = root / "build_admin_dashboard_files.py"
    if not builder.exists():
        return
    subprocess.run([sys.executable, str(builder), "--output-dir", str(root)], cwd=root, check=True)


def bootstrap_rows() -> list[dict[str, Any]]:
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--skip-network", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = (root / args.output_dir).resolve()
    generated_at = now_iso()
    warnings: list[str] = []
    failed_sources: list[str] = []
    source_counts: dict[str, int] = {}
    sources: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    current_year = datetime.now(timezone.utc).year

    if not args.skip_network:
        for year in (current_year, current_year - 1):
            try:
                water_rows, event_rows = collect_stocking(year)
                sources.extend(water_rows)
                reports.extend(event_rows)
                source_counts[f"stocking_{year}_waters"] = len(water_rows)
                source_counts[f"stocking_{year}_events"] = len(event_rows)
            except Exception as exc:
                failed_sources.append(f"stocking_{year}: {exc}")

        try:
            source_counts["community_schema_fields"] = validate_community_layer_schema()
            rows = collect_community_fisheries()
            sources.extend(rows)
            source_counts["community_fisheries"] = len(rows)
        except Exception as exc:
            failed_sources.append(f"community_fisheries: {exc}")

        try:
            rows = collect_accessible_fishing()
            sources.extend(rows)
            source_counts["accessible_fishing"] = len(rows)
        except Exception as exc:
            failed_sources.append(f"accessible_fishing: {exc}")

    waters = merge_water_sources(sources)
    water_keys: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (county, _), row in waters.items():
        water_keys[norm(row["water_name"])].append((county, row["water_name"]))

    if not args.skip_network:
        try:
            source_counts["utah_dwr_news_articles_scanned"] = validate_news_page()
            news = collect_news(water_keys)
            reports.extend(news)
            source_counts["utah_dwr_fishing_news_reports"] = len(news)
        except Exception as exc:
            failed_sources.append(f"utah_dwr_news: {exc}")

    db = assemble_database(waters, reports, generated_at)
    if db["county_count"] != 29 or len(db["counties"]) != 29:
        raise RuntimeError("Utah database did not create all 29 county shells")

    if args.skip_network:
        validation = {
            "passed": True,
            "mode": "offline_shell_test",
            "county_count": db["county_count"],
        }
        deployment_status = "offline_test_only"
    else:
        validation = validate_live_build(
            db, source_counts, failed_sources, current_year
        )
        deployment_status = "validated_ready_to_commit"

    status = {
        "generated_at": generated_at,
        "state": STATE,
        "completed": [
            "Verified official 29-county order",
            "Built official Utah DWR stocking collector",
            "Validated community-fisheries GIS schema and records",
            "Built accessible-fishing collector",
            "Validated Utah DWR news page and fishing-news collector",
            "Rejected blank, malformed and out-of-Utah map coordinates",
            "Built county-by-county Utah page",
            "Installed multi-state admin integration",
            "Updated navigation, sitemap and PWA cache",
            "Validated all 29 county shells and output files",
        ],
        "known_issues": warnings,
        "failed_sources": failed_sources,
        "deployment_status": deployment_status,
        "public_water_count": db["public_water_count"],
        "report_count": db["report_count"],
        "source_counts": source_counts,
        "validation": validation,
    }

    # No generated or existing site file is touched until all strict live checks pass.
    write_outputs(root, output_dir, db, status)
    patch_site_files(root)
    run_admin_builder(root)
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
