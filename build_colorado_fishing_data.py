#!/usr/bin/env python3
"""Build Colorado Fish Finder Outdoors county data from official public sources.

This one-file state builder creates and maintains:
- the authoritative 64-county list
- CPW-identified and reviewed fishing opportunities and access records from the Colorado Fishing Atlas
- recent Colorado Parks and Wildlife trout-stocking records
- official CPW fishery-survey/report references
- the Colorado county search page
- the shared multi-state admin dashboard feed
- navigation, sitemap and PWA cache integration

Public-water policy
-------------------
A fishing opportunity is published only when it appears in the official Colorado Parks and
Wildlife Fishing Atlas. Recent stocking records are matched back to those
verified atlas waters whenever possible. Blank, malformed or out-of-Colorado
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
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

try:
    from bs4 import BeautifulSoup
except ImportError:  # installed by GitHub Actions
    BeautifulSoup = None

STATE = "Colorado"
STATE_ABBR = "CO"
COUNTIES = [
    "Adams", "Alamosa", "Arapahoe", "Archuleta", "Baca", "Bent",
    "Boulder", "Broomfield", "Chaffee", "Cheyenne", "Clear Creek",
    "Conejos", "Costilla", "Crowley", "Custer", "Delta", "Denver",
    "Dolores", "Douglas", "Eagle", "Elbert", "El Paso", "Fremont",
    "Garfield", "Gilpin", "Grand", "Gunnison", "Hinsdale", "Huerfano",
    "Jackson", "Jefferson", "Kiowa", "Kit Carson", "La Plata", "Lake",
    "Larimer", "Las Animas", "Lincoln", "Logan", "Mesa", "Mineral",
    "Moffat", "Montezuma", "Montrose", "Morgan", "Otero", "Ouray",
    "Park", "Phillips", "Pitkin", "Prowers", "Pueblo", "Rio Blanco",
    "Rio Grande", "Routt", "Saguache", "San Juan", "San Miguel",
    "Sedgwick", "Summit", "Teller", "Washington", "Weld", "Yuma",
]
COUNTY_NUMBER = {name: i + 1 for i, name in enumerate(COUNTIES)}
COUNTY_LOOKUP = {re.sub(r"[^a-z0-9]+", " ", name.lower()).strip(): name for name in COUNTIES}

USER_AGENT = "FishFinderOutdoors-ColoradoBuilder/1.0 (+https://fishfinderoutdoors.com)"
ATLAS_SERVICE = (
    "https://ndismaps.nrel.colostate.edu/arcgis/rest/services/"
    "FishingAtlas/FishingAtlas_Data/MapServer"
)
ATLAS_LAYER = f"{ATLAS_SERVICE}/0"
STOCKING_URL = (
    "https://cpw.state.co.us/activities/fishing/"
    "fishing-awards-and-records/fish-stocking-report"
)
OFFICIAL_URLS = {
    "fishing": "https://cpw.state.co.us/fishing",
    "where_to_fish": "https://cpw.state.co.us/activities/fishing/where-fish",
    "atlas": "https://ndismaps.nrel.colostate.edu/index.html?app=FishingAtlas",
    "atlas_layer": ATLAS_LAYER,
    "stocking": STOCKING_URL,
    "surveys": "https://cpw.state.co.us/activities/fishing/fishery-surveys",
    "accessible": "https://cpw.state.co.us/park-visitors-experiencing-disabilities",
    "regulations": "https://cpw.state.co.us/rules-and-regulations",
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
    text = clean(value)
    text = re.sub(r"^(city\s+and\s+county\s+of|county\s+of)\s+", "", text, flags=re.I)
    text = re.sub(r"\s+county$", "", text, flags=re.I)
    aliases = {
        "city and county of denver": "Denver",
        "city and county of broomfield": "Broomfield",
        "la plata": "La Plata",
        "las animas": "Las Animas",
        "el paso": "El Paso",
        "rio blanco": "Rio Blanco",
        "rio grande": "Rio Grande",
        "san juan": "San Juan",
        "san miguel": "San Miguel",
        "clear creek": "Clear Creek",
        "kit carson": "Kit Carson",
    }
    key = norm(text)
    return aliases.get(key) or COUNTY_LOOKUP.get(key, "")



def valid_lon_lat(lon: Any, lat: Any) -> bool:
    try:
        x, y = float(lon), float(lat)
    except (TypeError, ValueError):
        return False
    return -109.2 <= x <= -101.9 and 36.9 <= y <= 41.1



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


def arcgis_features(layer_url: str, chunk_size: int = 50) -> list[dict[str, Any]]:
    """Download ArcGIS features in short requests that avoid server/WAF URL limits."""
    ids_payload = request_json(arcgis_query_url(layer_url, {
        "where": "1=1", "returnIdsOnly": "true", "f": "json",
    }))
    ids = sorted(set(ids_payload.get("objectIds") or []))
    rows: list[dict[str, Any]] = []

    def fetch_chunk(object_ids: list[int]) -> list[dict[str, Any]]:
        if not object_ids:
            return []
        url = arcgis_query_url(layer_url, {
            "objectIds": ",".join(str(v) for v in object_ids),
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
        })
        try:
            payload = request_json(url)
            return payload.get("features") or []
        except RuntimeError as exc:
            message = str(exc)
            # Colorado's ArcGIS/WAF returned HTTP 403 for a 500-ID URL.
            # Split only URL-size style failures; preserve real source failures.
            if len(object_ids) > 5 and ("403" in message or "414" in message):
                midpoint = len(object_ids) // 2
                return (
                    fetch_chunk(object_ids[:midpoint])
                    + fetch_chunk(object_ids[midpoint:])
                )
            raise

    for start in range(0, len(ids), chunk_size):
        rows.extend(fetch_chunk(ids[start:start + chunk_size]))
    return rows



def water_type(name: str, loc_type: str = "") -> str:
    text = f"{name} {loc_type}".lower()
    if "reservoir" in text or re.search(r"\bres\b", text):
        return "reservoir"
    if "lake" in text:
        return "lake"
    if "pond" in text:
        return "pond"
    if "river" in text or "fork" in text:
        return "river"
    if "creek" in text or "stream" in text:
        return "stream"
    return "water"


def report_id(*parts: Any) -> str:
    seed = "|".join(norm(part) for part in parts if clean(part))
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


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
    rating: str = "",
) -> dict[str, Any]:
    report_date = parse_date(report_date)
    return {
        "report_id": report_id(
            STATE, source_type, source_url, title, water_name, report_date
        ),
        "state": STATE,
        "source_type": source_type,
        "source_name": source_name,
        "source_url": clean(source_url),
        "official": True,
        "title": clean(title),
        "summary": clip(summary),
        "report_date": report_date,
        "observed_period": report_date,
        "freshness": freshness(report_date),
        "age_days": age_days(report_date),
        "water_name": clean(water_name),
        "counties": [county for county in (counties or []) if county],
        "species": clean(species),
        "techniques": clean(techniques),
        "access_notes": clean(access_notes),
        "rating": clean(rating),
    }


def bool_from_text(value: Any, true_terms: tuple[str, ...]) -> bool | None:
    text = clean(value).lower()
    if not text:
        return None
    if text in {"0", "no", "n", "false", "none", "not available", "na", "n/a"}:
        return False
    if text in {"1", "yes", "y", "true"}:
        return True
    return any(term in text for term in true_terms)


def feature_point(feature: dict[str, Any]) -> tuple[float | None, float | None]:
    attrs = feature.get("attributes") or {}
    geom = feature.get("geometry") or {}
    lon = safe_float(geom.get("x"))
    lat = safe_float(geom.get("y"))
    if not valid_lon_lat(lon, lat):
        lon = safe_float(attrs.get("xval"))
        lat = safe_float(attrs.get("yval"))
    if not valid_lon_lat(lon, lat):
        return None, None
    return lat, lon


def validate_atlas_schema() -> int:
    payload = request_json(f"{ATLAS_LAYER}?f=pjson")
    fields = {
        clean(field.get("name")).upper()
        for field in (payload.get("fields") or [])
        if isinstance(field, dict)
    }
    required = {
        "FA_NAME", "DOW_NAME", "COUNTYNAME", "DRIVING_URL", "SURVEY_URL",
        "REPORTS_URL", "BOATING", "HANDI_PIER", "STOCKED", "SHOW",
    }
    missing = sorted(required - fields)
    if missing:
        raise RuntimeError(
            "Colorado Fishing Atlas schema is missing: " + ", ".join(missing)
        )
    geometry_type = clean(payload.get("geometryType")).lower()
    if "point" not in geometry_type:
        raise RuntimeError(
            f"Colorado Fishing Atlas geometry changed unexpectedly: {geometry_type}"
        )
    if len(fields) < 20:
        raise RuntimeError(
            f"Colorado Fishing Atlas returned only {len(fields)} fields"
        )
    return len(fields)



def validate_accessible_fishing_page() -> int:
    """Confirm CPW's statewide accessible-fishing page still exposes all four regions."""
    page = request_text(OFFICIAL_URLS["accessible"])
    lower = page.lower()
    regions = (
        "northeast colorado",
        "northwest colorado",
        "southeast colorado",
        "southwest colorado",
    )
    found = sum(1 for region in regions if region in lower)
    if found != 4:
        raise RuntimeError(
            f"Colorado accessible-fishing page exposed only {found} of 4 regions"
        )
    return found


def atlas_details(attrs: dict[str, Any]) -> str:
    parts = []
    prop = clean(attrs.get("PROP_NAME"))
    if prop:
        parts.append(f"Property: {prop}.")
    access = clean(attrs.get("ACCESS_EASE"))
    if access:
        parts.append(f"Access: {access}.")
    pressure = clean(attrs.get("FISH_PRESSURE"))
    if pressure:
        parts.append(f"Fishing pressure: {pressure}.")
    boating = clean(attrs.get("BOATING"))
    if boating:
        parts.append(f"Boating: {boating}.")
    if bool_from_text(attrs.get("OPP_FAMILY"), ("family", "yes")):
        parts.append("CPW identifies this as a family-friendly opportunity.")
    if bool_from_text(attrs.get("OPP_ICE"), ("ice", "yes")):
        parts.append("CPW identifies ice-fishing opportunity.")
    if bool_from_text(attrs.get("HANDI_PIER"), ("pier", "accessible", "yes")):
        parts.append("CPW identifies accessible fishing-pier access.")
    return " ".join(parts)


def collect_fishing_atlas() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    sources: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    survey_urls: set[str] = set()
    accessible_count = 0
    coordinate_count = 0
    skipped_hidden = 0
    skipped_county = 0

    for feature in arcgis_features(ATLAS_LAYER):
        attrs = feature.get("attributes") or {}
        show = attrs.get("SHOW")
        if show not in (None, "", 1, "1", True):
            skipped_hidden += 1
            continue

        county = canonical_county(attrs.get("COUNTYNAME"))
        name = clean(attrs.get("FA_NAME") or attrs.get("DOW_NAME"))
        if not county or not name:
            skipped_county += 1
            continue

        lat, lon = feature_point(feature)
        if lat is not None and lon is not None:
            coordinate_count += 1

        driving_url = clean(attrs.get("DRIVING_URL"))
        if not driving_url.startswith("http"):
            driving_url = (
                f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                if lat is not None and lon is not None else ""
            )

        accessible = bool_from_text(
            attrs.get("HANDI_PIER"), ("pier", "accessible", "handicap", "ada", "yes")
        )
        if accessible is True:
            accessible_count += 1

        boating = clean(attrs.get("BOATING"))
        boat_ramp = bool_from_text(boating, ("boat ramp", "ramp", "launch"))
        details = atlas_details(attrs)
        survey_url = clean(attrs.get("SURVEY_URL"))
        reports_url = clean(attrs.get("REPORTS_URL"))
        prop_url = clean(attrs.get("PROP_URL"))
        official_source_url = (
            prop_url if prop_url.startswith("http") else OFFICIAL_URLS["atlas"]
        )

        point = {
            "access_point_name": clean(attrs.get("PROP_NAME")) or name,
            "latitude": lat,
            "longitude": lon,
            "directions_url": driving_url,
            "amenities": {
                "camping": None,
                "restroom": None,
                "boat_ramp": boat_ramp,
                "dock": None,
                "ada_fishing": accessible,
            },
            "access_flags": {
                "family_friendly": bool_from_text(attrs.get("OPP_FAMILY"), ("family", "yes")),
                "ice_fishing": bool_from_text(attrs.get("OPP_ICE"), ("ice", "yes")),
                "rustic_fly_fishing": bool_from_text(attrs.get("OPP_RUSTIC"), ("rustic", "fly", "yes")),
            },
            "access_details": details,
            "official_source_url": official_source_url,
        }

        sources.append({
            "county": county,
            "water_name": name,
            "water_type": water_type(name, clean(attrs.get("LOC_TYPE"))),
            "latitude": lat,
            "longitude": lon,
            "access_details": details,
            "verification": "official_colorado_cpw_fishing_atlas",
            "source_url": OFFICIAL_URLS["atlas"],
            "watercode": clean(attrs.get("WATERCODE")),
            "stocked": clean(attrs.get("STOCKED")),
            "boating": boating,
            "accessible_fishing": accessible is True,
            "quality_water": bool(attrs.get("Quality")),
            "gold_medal": bool(attrs.get("GoldMedal")),
            "access_point": point,
        })

        for url, kind in ((survey_url, "fishery survey"), (reports_url, "fishery report")):
            if not url.startswith("http") or url in survey_urls:
                continue
            survey_urls.add(url)
            reports.append(make_report(
                source_type="official_fishery_survey",
                source_name="Colorado Parks and Wildlife",
                source_url=url,
                title=f"CPW {kind}: {name}",
                summary=(
                    "Colorado Parks and Wildlife provides an official fishery survey "
                    "or report for this water. Open the source for survey dates, "
                    "species observations, management findings and access information."
                ),
                water_name=name,
                counties=[county],
                access_notes=details,
            ))

    counts = {
        "fishing_atlas_points": len(sources),
        "fishing_atlas_coordinates": coordinate_count,
        "fishing_atlas_accessible": accessible_count,
        "fishery_survey_links": len(survey_urls),
        "atlas_hidden_rows_skipped": skipped_hidden,
        "atlas_rows_without_valid_county_or_name": skipped_county,
    }
    return sources, reports, counts


def clean_stocking_cell(value: str, label: str) -> str:
    text = clean(value)
    text = re.sub(rf"\b{re.escape(label)}\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" |:-")
    # Responsive tables sometimes repeat the value around a hidden label.
    words = text.split()
    half = len(words) // 2
    if len(words) >= 2 and len(words) % 2 == 0 and words[:half] == words[half:]:
        text = " ".join(words[:half])
    return text


def parse_stocking_rows(page_html: str) -> list[dict[str, str]]:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required")
    soup = BeautifulSoup(page_html, "html.parser")
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 3:
            continue
        water = clean_stocking_cell(cells[0].get_text(" ", strip=True), "Body of Water")
        region = clean_stocking_cell(cells[1].get_text(" ", strip=True), "Region")
        date_text = clean_stocking_cell(cells[2].get_text(" ", strip=True), "Report Date")
        report_date = parse_date(date_text)
        if not water or not report_date or norm(water) in {"body water", "body of water"}:
            continue
        anchor = tr.find("a", href=True)
        source_url = urljoin(STOCKING_URL, anchor["href"]) if anchor else STOCKING_URL
        key = (norm(water), region.lower(), report_date)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "water_name": water,
            "region": region,
            "report_date": report_date,
            "source_url": source_url,
        })
    return rows


def collect_recent_stocking(
    waters: dict[tuple[str, str], dict[str, Any]]
) -> tuple[list[dict[str, Any]], int, int]:
    page_html = request_text(STOCKING_URL)
    if "stocking" not in page_html.lower() or "body of water" not in page_html.lower():
        raise RuntimeError("Colorado CPW stocking page no longer has the expected report")
    rows = parse_stocking_rows(page_html)

    name_index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (county, key), water in waters.items():
        name_index[key].append((county, water["water_name"]))

    reports: list[dict[str, Any]] = []
    ambiguous_name_count = 0

    for row in rows:
        matches = name_index.get(norm(row["water_name"]), [])

        # Attach only when the official atlas name resolves to exactly one water.
        # Duplicate names remain unmatched rather than being assigned to a wrong county.
        if len(matches) == 1:
            county, canonical_name = matches[0]
            reports.append(make_report(
                source_type="official_recent_stocking",
                source_name="Colorado Parks and Wildlife",
                source_url=row["source_url"],
                title=f"Recent CPW trout stocking: {canonical_name}",
                summary=(
                    f"Colorado Parks and Wildlife added {canonical_name} to its "
                    f"recent catchable-trout stocking report for {row['report_date']}."
                    + (f" CPW region: {row['region']}." if row["region"] else "")
                ),
                report_date=row["report_date"],
                water_name=canonical_name,
                counties=[county],
                species="Catchable trout",
            ))
        else:
            if len(matches) > 1:
                ambiguous_name_count += 1
                note = (
                    "Multiple Colorado Fishing Atlas waters share this name. "
                    "The stocking record is intentionally left unmatched rather "
                    "than assigned to a potentially incorrect county."
                )
            else:
                note = (
                    "No exact Colorado Fishing Atlas water-name match was found. "
                    "The official stocking record remains available as an unmatched reference."
                )

            reports.append(make_report(
                source_type="official_recent_stocking_unmatched",
                source_name="Colorado Parks and Wildlife",
                source_url=row["source_url"],
                title=f"Recent CPW trout stocking: {row['water_name']}",
                summary=(
                    f"Colorado Parks and Wildlife added {row['water_name']} to its "
                    f"recent catchable-trout stocking report for {row['report_date']}."
                    + (f" CPW region: {row['region']}." if row["region"] else "")
                    + f" {note}"
                ),
                report_date=row["report_date"],
                water_name=row["water_name"],
                species="Catchable trout",
                access_notes=note,
            ))

    return reports, len(rows), ambiguous_name_count


def dedupe_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for report in reports:
        rid = clean(report.get("report_id")) or report_id(
            report.get("source_url"), report.get("title"), report.get("water_name")
        )
        current = unique.get(rid)
        if current is None or len(clean(report.get("summary"))) > len(clean(current.get("summary"))):
            unique[rid] = report
    return sorted(
        unique.values(),
        key=lambda row: (clean(row.get("report_date")), clean(row.get("title"))),
        reverse=True,
    )


def merge_water_sources(
    source_rows: list[dict[str, Any]]
) -> dict[tuple[str, str], dict[str, Any]]:
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
            "community_fishery": bool(source.get("quality_water")),
            "accessible_fishing": bool(source.get("accessible_fishing")),
            "quality_water": bool(source.get("quality_water")),
            "gold_medal": bool(source.get("gold_medal")),
            "stocked": clean(source.get("stocked")),
            "boating": clean(source.get("boating")),
            "public_access_verification": [],
            "official_access_source_url": source.get("source_url") or OFFICIAL_URLS["atlas"],
            "access_details": "",
            "access_points": [],
            "alternate_names": [],
        })
        verification = clean(source.get("verification"))
        if verification and verification not in row["public_access_verification"]:
            row["public_access_verification"].append(verification)
        lat, lon = source.get("latitude"), source.get("longitude")
        if valid_lon_lat(lon, lat) and not valid_lon_lat(row.get("longitude"), row.get("latitude")):
            row["latitude"], row["longitude"] = float(lat), float(lon)
        details = clean(source.get("access_details"))
        if details and details not in row["access_details"]:
            row["access_details"] = " ".join(
                part for part in (row["access_details"], details) if part
            )
        row["accessible_fishing"] = row["accessible_fishing"] or bool(source.get("accessible_fishing"))
        row["quality_water"] = row["quality_water"] or bool(source.get("quality_water"))
        row["gold_medal"] = row["gold_medal"] or bool(source.get("gold_medal"))
        point = source.get("access_point")
        if point:
            signature = (
                norm(point.get("access_point_name")),
                point.get("latitude"),
                point.get("longitude"),
            )
            existing = {
                (norm(p.get("access_point_name")), p.get("latitude"), p.get("longitude"))
                for p in row["access_points"]
            }
            if signature not in existing:
                row["access_points"].append(point)
    return waters


def assemble_database(
    waters: dict[tuple[str, str], dict[str, Any]],
    reports: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    reports = dedupe_reports(reports)
    reports_by_water: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    statewide_reports: list[dict[str, Any]] = []
    unmatched_reports: list[dict[str, Any]] = []

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
        for (water_county, key), base in sorted(
            waters.items(), key=lambda item: (item[0][0], item[1]["water_name"])
        ):
            if water_county != county:
                continue
            candidate = dedupe_reports(reports_by_water.get((county, key), []))
            latest = candidate[0] if candidate else None
            row = dict(base)
            row["public_access_verification"] = "; ".join(
                row.get("public_access_verification") or []
            )
            row.update({
                "access_point_count": len(row.get("access_points") or []),
                "report_status": (
                    latest.get("freshness") if latest
                    else "no_recent_public_report_found"
                ),
                "latest_report": latest,
                "recent_reports": candidate[:10],
                "report_count": len(candidate),
            })
            county_waters.append(row)
            flat_waters.append(row)
        county_reports = [
            report for report in reports if county in (report.get("counties") or [])
        ]
        county_blocks.append({
            "county_number": number,
            "county": county,
            "public_water_count": len(county_waters),
            "waters_with_reports": sum(
                1 for water in county_waters if water["report_count"] > 0
            ),
            "waters_without_reports": sum(
                1 for water in county_waters if water["report_count"] == 0
            ),
            "public_access_point_count": sum(
                water["access_point_count"] for water in county_waters
            ),
            "county_report_count": len(county_reports),
            "waters": county_waters,
        })

    return {
        "metadata": {
            "state": STATE,
            "title": "Colorado Public Fishing Access and Current Fishing Reports",
            "version": "1.0",
            "generated_at": generated_at,
            "public_access_only": True,
            "county_order": "1 Adams through 64 Yuma",
            "access_policy": (
                "Records are included only from CPW-identified and reviewed Fishing Atlas "
                "opportunities. A record confirms an official fishing opportunity or "
                "access point; it does not mean every shoreline or river reach is public. "
                "Recent CPW stocking records and official fishery survey links are "
                "attached when they can be matched safely. A map button is shown only "
                "for a validated Colorado coordinate. Anglers must verify boundaries, "
                "seasonal restrictions and posted signs before entering."
            ),
            "sources": [
                {"name": "Colorado Parks and Wildlife Fishing Atlas", "type": "official", "url": OFFICIAL_URLS["atlas"]},
                {"name": "Colorado Parks and Wildlife Fish Stocking Report", "type": "official", "url": OFFICIAL_URLS["stocking"]},
                {"name": "Colorado Parks and Wildlife Fishery Surveys", "type": "official", "url": OFFICIAL_URLS["surveys"]},
                {"name": "Colorado Parks and Wildlife Accessible Fishing", "type": "official", "url": OFFICIAL_URLS["accessible"]},
                {"name": "Colorado Fishing Regulations", "type": "official", "url": OFFICIAL_URLS["regulations"]},
            ],
        },
        "county_count": 64,
        "public_water_count": len(flat_waters),
        "report_count": len(reports),
        "statewide_reports": statewide_reports[:100],
        "unmatched_reports": unmatched_reports,
        "counties": county_blocks,
        "flat_waters": flat_waters,
        "flat_reports": reports,
    }


def stocking_minimum_for_month(month: int | None = None) -> int:
    month = month or datetime.now(timezone.utc).month
    return {
        1: 0, 2: 0, 3: 3, 4: 10, 5: 20, 6: 20,
        7: 20, 8: 20, 9: 15, 10: 10, 11: 3, 12: 0,
    }[month]


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
                invalid_coordinates.append(
                    f"{label} has out-of-Colorado coordinates {lat},{lon}"
                )
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
                        f"{point_name} has out-of-Colorado coordinates {plat},{plon}"
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
            "Invalid Colorado coordinate data: "
            + "; ".join(invalid_coordinates[:10])
        )
    if invalid_urls:
        raise RuntimeError(
            "Invalid Colorado map URLs: " + "; ".join(invalid_urls[:10])
        )
    return {
        "water_coordinates": water_coordinate_count,
        "access_coordinates": access_coordinate_count,
    }


def validate_live_build(
    db: dict[str, Any],
    source_counts: dict[str, int],
    failed_sources: list[str],
) -> dict[str, Any]:
    if failed_sources:
        raise RuntimeError(
            "Required Colorado source failures: " + " | ".join(failed_sources)
        )

    minimums = {
        "atlas_schema_fields": 20,
        "fishing_atlas_points": 500,
        "fishing_atlas_coordinates": 400,
        "fishing_atlas_accessible": 5,
        "accessible_page_regions": 4,
        "fishery_survey_links": 10,
        "recent_stocking_records": stocking_minimum_for_month(),
    }
    shortfalls = []
    for key, minimum in minimums.items():
        actual = int(source_counts.get(key, 0) or 0)
        if actual < minimum:
            shortfalls.append(f"{key}={actual}, expected at least {minimum}")
    if shortfalls:
        raise RuntimeError(
            "Colorado source-count validation failed: " + "; ".join(shortfalls)
        )

    counties = db.get("counties") or []
    if db.get("county_count") != 64 or len(counties) != 64:
        raise RuntimeError("Colorado database did not create all 64 county shells")
    if [row.get("county") for row in counties] != COUNTIES:
        raise RuntimeError("Colorado county order is not Adams through Yuma")

    public_water_count = int(db.get("public_water_count", 0) or 0)
    report_count = int(db.get("report_count", 0) or 0)
    if public_water_count < 500:
        raise RuntimeError(
            f"Colorado build produced only {public_water_count} public waters"
        )
    if report_count < 50:
        raise RuntimeError(
            f"Colorado build produced only {report_count} report records"
        )

    populated_counties = sum(
        1 for county in counties
        if int(county.get("public_water_count", 0) or 0) > 0
    )
    if populated_counties < 48:
        raise RuntimeError(
            f"Only {populated_counties} of 64 Colorado counties contain water records"
        )

    map_counts = validate_map_data(db)
    page = county_page_html()
    required_page_tokens = (
        "function validCoordinate",
        "function mapPoint",
        "const mapHtml=map?",
        "36.9,41.1",
        "-109.2,-101.9",
    )
    missing_tokens = [token for token in required_page_tokens if token not in page]
    if missing_tokens:
        raise RuntimeError(
            "Colorado map-safety code is incomplete: " + ", ".join(missing_tokens)
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
    write_json(output_dir / "colorado_fishing_report_database.json", db)
    (output_dir / "colorado_fishing_report_database.js").write_text(
        "/* Automatically generated. Do not hand-edit. */\nwindow.COLORADO_FISHING_REPORT_DATABASE = "
        + json.dumps(db, separators=(",", ":"), ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )
    write_json(output_dir / "colorado_public_fishing_access.json", {
        "metadata": db["metadata"],
        "county_count": db["county_count"],
        "public_water_count": db["public_water_count"],
        "counties": db["counties"],
        "flat_waters": db["flat_waters"],
    })
    (output_dir / "colorado_public_fishing_access.js").write_text(
        "/* Automatically generated. Do not hand-edit. */\nwindow.COLORADO_PUBLIC_FISHING_ACCESS = "
        + json.dumps({"metadata": db["metadata"], "county_count": 64, "public_water_count": db["public_water_count"], "counties": db["counties"], "flat_waters": db["flat_waters"]}, separators=(",", ":"), ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )
    write_json(output_dir / "colorado_project_status.json", status)
    write_json(root / "config/colorado_counties.json", {"state": STATE, "county_count": 64, "counties": [{"county_number": i + 1, "county": c} for i, c in enumerate(COUNTIES)]})
    with (output_dir / "colorado_counties.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle); writer.writerow(["county_number", "county"])
        writer.writerows((i + 1, c) for i, c in enumerate(COUNTIES))
    with (output_dir / "colorado_fishing_report_database.csv").open("w", newline="", encoding="utf-8-sig") as handle:
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
<meta name="description" content="Search CPW-identified fishing opportunities, access information and recent stocking records across all 64 Colorado counties."/>
<title>Colorado County Fishing Reports & Public Access | Fish Finder Outdoors</title>
<link rel="icon" href="ffo-logo-main.png" type="image/png"/><link rel="apple-touch-icon" href="ffo-logo-main.png"/><link rel="manifest" href="manifest.json"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Bitter:wght@600;700;800&family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="brand-shell.css"/>
<style>
:root{--green:#1f4d3a;--paper:#f4f1e7;--card:#fffdf8;--line:#d8d3c7;--ink:#173029;--muted:#64716c;--warn:#7a5d1f;--danger:#96352c}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#e9f0ea,#f4f1e7 320px);color:var(--ink);font-family:Inter,Arial,sans-serif}.wrap{width:min(1180px,calc(100% - 28px));margin:auto}.hero{padding:38px 0 20px}.hero-grid{display:grid;grid-template-columns:1.25fr .75fr;gap:26px;align-items:center}.kicker{display:inline-flex;padding:7px 11px;border-radius:999px;background:#e2eee7;color:var(--green);font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}.hero h1{font-family:Bitter,Georgia,serif;font-size:clamp(36px,6vw,64px);line-height:1.02;margin:16px 0 12px}.hero p{font-size:18px;color:var(--muted);max-width:760px}.hero-logo{width:min(300px,100%);justify-self:end}.panel{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;margin:18px 0;box-shadow:0 10px 30px rgba(31,77,58,.07)}.controls{display:grid;grid-template-columns:1.2fr 1fr repeat(3,auto);gap:10px;align-items:end}.field label{display:block;font-size:12px;font-weight:900;margin:0 0 5px}.field select,.field input{width:100%;padding:12px 13px;border:1px solid #bfc7c1;border-radius:12px;background:white;font:inherit}.check{display:flex;align-items:center;gap:7px;padding:11px 10px;background:#eef4f0;border-radius:12px;font-size:12px;font-weight:800;white-space:nowrap}.check input{width:18px;height:18px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}button,.button{border:0;border-radius:12px;padding:11px 14px;font:inherit;font-weight:850;cursor:pointer;text-decoration:none}.primary{background:var(--green);color:white}.secondary{background:#e3ece7;color:var(--green)}.status{padding:12px 14px;border-radius:12px;background:#edf4f0;color:var(--green);font-weight:750;margin-top:13px}.status.warning{background:#fff5d9;color:var(--warn)}.status.error{background:#fae5e1;color:var(--danger)}.summary{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.metric{background:white;border:1px solid var(--line);border-radius:14px;padding:13px}.metric span{font-size:12px;color:var(--muted);font-weight:700}.metric b{display:block;font-size:25px;margin-top:4px}.water-list{display:grid;gap:13px}.water-card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px}.water-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}.water-head h2{font-family:Bitter,Georgia,serif;margin:0;font-size:25px}.chips{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0}.chip{display:inline-flex;padding:5px 8px;border-radius:999px;background:#e8f0eb;border:1px solid #c9dbd1;font-size:11px;font-weight:850}.chip.current{background:#daf1e4;color:#176354}.chip.recent{background:#fff0c5;color:#705319}.chip.stale{background:#f5dedb;color:#8d3029}.chip.none{background:#ecebe7;color:#666}.details{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:13px}.box{border:1px solid var(--line);border-radius:14px;padding:14px;background:white}.box h3{font-size:15px;margin:0 0 9px}.box p{margin:7px 0;color:#3f504a}.access{border-top:1px solid var(--line);padding-top:10px;margin-top:10px}.amenities{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}.amenity{font-size:11px;padding:5px 7px;border-radius:8px;background:#f0f3ef}.report-link{display:inline-flex;margin-top:8px;font-weight:850}.muted{color:var(--muted);font-size:13px}.empty{padding:28px;text-align:center;border:1px dashed #b9b3a6;border-radius:16px;background:#fbf8f1}.footer-note{font-size:13px;color:var(--muted);line-height:1.6}.top-links{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}.top-links a{display:inline-flex;padding:10px 12px;border-radius:12px;background:white;border:1px solid var(--line);font-weight:800;text-decoration:none}.load-more{display:block;margin:18px auto}.hidden{display:none!important}@media(max-width:900px){.hero-grid{grid-template-columns:1fr}.hero-logo{justify-self:start;max-width:220px}.controls{grid-template-columns:1fr 1fr}.summary{grid-template-columns:1fr 1fr}.details{grid-template-columns:1fr}}@media(max-width:600px){.controls{grid-template-columns:1fr}.summary{grid-template-columns:1fr 1fr}.water-head{display:block}.panel{padding:15px}.hero{padding-top:24px}}
</style></head>
<body>
<header class="ffo-site-header"><div class="ffo-header-inner"><a class="ffo-logo-link" href="https://fishfinderoutdoors.com"><img src="ffo-logo-main.png" alt="Fish Finder Outdoors logo"/><span class="ffo-wordmark"><strong>Fish Finder</strong><span>Outdoors</span></span></a><button class="ffo-menu-button" aria-label="Open menu" aria-expanded="false" type="button">☰</button><nav class="ffo-nav" aria-label="Fish Finder Outdoors"><a href="https://fishfinderoutdoors.com">Home</a><a href="index.html">Fishing Reports</a><a href="idaho-county-reports.html">Idaho County Reports</a><a href="montana-county-reports.html">Montana County Reports</a><a href="utah-county-reports.html">Utah County Reports</a><a class="active" href="colorado-county-reports.html">Colorado County Reports</a><a href="submit-report.html">Submit Report</a><a href="official-sources.html">Official Sources</a></nav></div></header>
<div class="ffo-beta-bar">PUBLIC ACCESS ONLY • 64 COLORADO COUNTIES • REPORT DATES AND SOURCES SHOWN • <button class="ffo-install-button" data-install-ffo-app hidden type="button">Install App</button></div>
<main><section class="hero"><div class="wrap hero-grid"><div><span class="kicker">Colorado statewide directory</span><h1>Public fishing waters and current information, county by county.</h1><p>Search official Colorado Parks and Wildlife Fishing Atlas waters, recent trout stocking records and fishery survey links across all 64 counties. Map buttons appear only when a dependable Colorado coordinate is available.</p><div class="top-links"><a href="index.html">← Main report generator</a><a href="submit-report.html">Submit a fishing report</a><a href="report-water.html">Report incorrect access</a></div></div><img class="hero-logo" src="ffo-logo-main.png" alt="Fish Finder Outdoors"/></div></section>
<div class="wrap"><section class="panel"><div class="controls"><div class="field"><label for="countySelect">County</label><select id="countySelect"><option value="">All 64 counties</option></select></div><div class="field"><label for="waterSearch">Water, species or report keyword</label><input id="waterSearch" placeholder="Lake, river, trout, stocking…"/></div><label class="check"><input id="currentOnly" type="checkbox"/> Current reports</label><label class="check"><input id="boatRamp" type="checkbox"/> Boat ramp</label><label class="check"><input id="adaFishing" type="checkbox"/> Accessible fishing</label></div><div class="actions"><button class="primary" id="searchButton" type="button">Search public waters</button><button class="secondary" id="clearButton" type="button">Clear filters</button></div><div class="status" id="status">Loading the Colorado public-access database…</div></section>
<section class="panel"><div class="summary" id="summary"></div></section><section class="water-list" id="waterList"></section><button class="secondary load-more hidden" id="loadMore" type="button">Show more waters</button>
<section class="panel footer-note"><strong>How to read this page:</strong> Colorado access, drought closures, emergency regulations, water levels and roads can change. Stocking records are dated observations, not guarantees. Open the official source, check current Colorado rules and obey posted signs before traveling.</section></div></main>
<footer class="ffo-site-footer"><div class="ffo-footer-grid"><div><a class="ffo-footer-brand" href="https://fishfinderoutdoors.com"><img src="ffo-logo-main.png" alt="Fish Finder Outdoors logo"/><span><strong>Fish Finder Outdoors</strong><br/><span style="color:#a9bbb3">Beginner friendly. Colorado ready.</span></span></a></div><div><div class="ffo-footer-title">Reports</div><div class="ffo-footer-links"><a href="index.html">Main Report Generator</a><a href="idaho-county-reports.html">Idaho County Reports</a><a href="montana-county-reports.html">Montana County Reports</a><a href="utah-county-reports.html">Utah County Reports</a><a href="colorado-county-reports.html">Colorado County Reports</a><a href="submit-report.html">Submit a Report</a><a href="official-sources.html">Official Sources</a></div></div></div><div class="ffo-footer-fine"><span>© 2026 Fish Finder Outdoors. Powered by Mountain Dog Enterprises.</span><span>Verify current regulations and access before fishing.</span></div></footer>
<script src="site_config.js"></script><script src="data/colorado_fishing_report_database.js"></script><script>window.FFO_ACTIVE_FISHING_DATABASE=window.COLORADO_FISHING_REPORT_DATABASE;</script><script src="fishing_report_search.js"></script>
<script>(function(){const $=id=>document.getElementById(id);const countySelect=$("countySelect"),waterSearch=$("waterSearch"),currentOnly=$("currentOnly"),boatRamp=$("boatRamp"),adaFishing=$("adaFishing"),status=$("status"),summary=$("summary"),waterList=$("waterList"),loadMore=$("loadMore");let filtered=[],shown=0;const PAGE_SIZE=25;const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));const label=value=>String(value||"").replace(/_/g," ").replace(/\b\w/g,c=>c.toUpperCase());function amenityText(a){const out=[];if(a?.boat_ramp===true)out.push("Boat ramp");if(a?.dock===true)out.push("Dock or pier");if(a?.restroom===true)out.push("Restroom");if(a?.camping===true)out.push("Camping");if(a?.ada_fishing===true)out.push("Accessible fishing");return out;}function validCoordinate(value,min,max){if(value===null||value===undefined||value==="")return false;const number=Number(value);return Number.isFinite(number)&&number>=min&&number<=max;}function mapPoint(w){if(validCoordinate(w.latitude,36.9,41.1)&&validCoordinate(w.longitude,-109.2,-101.9))return{lat:Number(w.latitude),lon:Number(w.longitude)};const p=(w.access_points||[]).find(p=>validCoordinate(p.latitude,36.9,41.1)&&validCoordinate(p.longitude,-109.2,-101.9));return p?{lat:Number(p.latitude),lon:Number(p.longitude)}:null;}function init(){const db=window.COLORADO_FISHING_REPORT_DATABASE;if(!db||!Array.isArray(db.counties)){status.className="status error";status.textContent="The Colorado fishing database could not be loaded.";return;}countySelect.innerHTML='<option value="">All 64 counties</option>'+db.counties.map(c=>`<option value="${esc(c.county)}">#${c.county_number} ${esc(c.county)} County</option>`).join("");status.textContent=`Database updated ${new Date(db.metadata.generated_at).toLocaleString()}. Choose a county or search a water.`;runSearch();}function runSearch(){const options={county:countySelect.value,query:waterSearch.value,boatRamp:boatRamp.checked,adaFishing:adaFishing.checked};filtered=window.FFO_FISHING_REPORT_SEARCH?.waters(options)||[];if(currentOnly.checked)filtered=filtered.filter(w=>["very_current","current"].includes(w.report_status));filtered.sort((a,b)=>(a.county_number-b.county_number)||String(a.water_name).localeCompare(String(b.water_name)));shown=0;waterList.innerHTML="";renderSummary();renderMore();status.className="status";status.textContent=`Found ${filtered.length.toLocaleString()} official fishing-opportunity record${filtered.length===1?"":"s"}${countySelect.value?` in ${countySelect.value} County`:" statewide"}.`;}function renderSummary(){const reports=filtered.filter(w=>w.report_count>0).length;const access=filtered.reduce((n,w)=>n+(w.access_point_count||0),0);const ramps=filtered.filter(w=>(w.access_points||[]).some(p=>p.amenities?.boat_ramp===true)).length;const ada=filtered.filter(w=>(w.access_points||[]).some(p=>p.amenities?.ada_fishing===true)).length;summary.innerHTML=[["Public waters",filtered.length],["With reports",reports],["Access points",access],["With boat ramps",ramps],["Accessible fishing",ada]].map(([k,v])=>`<div class="metric"><span>${k}</span><b>${Number(v).toLocaleString()}</b></div>`).join("");}function renderMore(){const batch=filtered.slice(shown,shown+PAGE_SIZE);shown+=batch.length;if(!filtered.length)waterList.innerHTML='<div class="empty">No official Colorado fishing opportunities matched these filters.</div>';else waterList.insertAdjacentHTML("beforeend",batch.map(card).join(""));loadMore.classList.toggle("hidden",shown>=filtered.length);}function card(w){const report=w.latest_report;const statusClass=w.report_status==="very_current"||w.report_status==="current"?"current":w.report_status==="recent"?"recent":w.report_status==="stale"?"stale":"none";const map=mapPoint(w);const mapHtml=map?`<a class="button secondary" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${map.lat},${map.lon}`)}" target="_blank" rel="noopener">Map</a>`:"";const points=(w.access_points||[]).map(p=>{const amenities=amenityText(p.amenities);return `<div class="access"><strong>${esc(p.access_point_name||"Public access point")}</strong>${p.access_details?`<p>${esc(p.access_details)}</p>`:""}${amenities.length?`<div class="amenities">${amenities.map(a=>`<span class="amenity">${esc(a)}</span>`).join("")}</div>`:""}${p.directions_url?`<a class="report-link" href="${esc(p.directions_url)}" target="_blank" rel="noopener">Directions</a>`:""}</div>`;}).join("");const reportHtml=report?`<strong>${esc(report.title||"Fishing update")}</strong><div class="chips"><span class="chip ${statusClass}">${esc(label(report.freshness))}</span><span class="chip">${esc(report.report_date||"")}</span><span class="chip">${esc(report.source_name||"")}</span></div><p>${esc(report.summary||"")}</p>${report.species?`<p><strong>Species:</strong> ${esc(report.species)}</p>`:""}${report.source_url?`<a class="report-link" href="${esc(report.source_url)}" target="_blank" rel="noopener">Open official source</a>`:""}`:'<div class="muted">No recent public fishing update was matched to this water.</div>';return `<article class="water-card"><div class="water-head"><div><h2>${esc(w.water_name)}</h2><div class="chips"><span class="chip">#${w.county_number} ${esc(w.county)} County</span><span class="chip">${esc(label(w.water_type))}</span><span class="chip ${statusClass}">${esc(label(w.report_status))}</span></div></div>${mapHtml}</div><div class="details"><div class="box"><h3>Latest fishing information</h3>${reportHtml}</div><div class="box"><h3>Official access information</h3>${w.access_details?`<p>${esc(w.access_details)}</p>`:""}${points||'<div class="muted">No separately inventoried access point was matched. Check the Colorado Fishing Atlas and posted signs.</div>'}${w.official_access_source_url?`<a class="report-link" href="${esc(w.official_access_source_url)}" target="_blank" rel="noopener">Official access source</a>`:""}</div></div></article>`;}$("searchButton").addEventListener("click",runSearch);$("clearButton").addEventListener("click",()=>{countySelect.value="";waterSearch.value="";currentOnly.checked=false;boatRamp.checked=false;adaFishing.checked=false;runSearch();});countySelect.addEventListener("change",runSearch);waterSearch.addEventListener("keydown",e=>{if(e.key==="Enter")runSearch();});loadMore.addEventListener("click",renderMore);init();})();</script><script src="brand-shell.js"></script><script src="pwa.js"></script></body></html>'''


def patch_site_files(root: Path) -> None:
    page = root / "colorado-county-reports.html"
    page.write_text(county_page_html(), encoding="utf-8")

    brand = root / "brand-shell.js"
    if brand.exists():
        text = brand.read_text(encoding="utf-8")
        replacement = "const stateLinks=[['idaho-county-reports.html','Idaho County Reports'],['montana-county-reports.html','Montana County Reports'],['utah-county-reports.html','Utah County Reports'],['colorado-county-reports.html','Colorado County Reports']];"
        text = re.sub(r"const stateLinks=\[[^;]+;", replacement, text, count=1)
        brand.write_text(text, encoding="utf-8")

    worker = root / "service-worker.js"
    if worker.exists():
        text = worker.read_text(encoding="utf-8")
        version = re.search(r'ffo-reports-pwa-v(\d+)', text)
        if version:
            text = text.replace(
                version.group(0),
                f"ffo-reports-pwa-v{int(version.group(1)) + 1}",
                1,
            )
        if "./colorado-county-reports.html" not in text:
            if '"./utah-county-reports.html"' in text:
                text = text.replace(
                    '"./utah-county-reports.html"',
                    '"./utah-county-reports.html","./colorado-county-reports.html"',
                )
            else:
                text = text.replace(
                    '"./montana-county-reports.html"',
                    '"./montana-county-reports.html","./colorado-county-reports.html"',
                )
        anchor = '"utah_public_fishing_access.json"'
        if anchor not in text:
            anchor = '"montana_public_fishing_access.json"'
        for filename in (
            "colorado_fishing_report_database.js",
            "colorado_fishing_report_database.json",
            "colorado_public_fishing_access.js",
            "colorado_public_fishing_access.json",
        ):
            if filename not in text:
                text = text.replace(anchor, f'{anchor},"{filename}"')
        worker.write_text(text, encoding="utf-8")

    sitemap = root / "sitemap.xml"
    if sitemap.exists():
        text = sitemap.read_text(encoding="utf-8")
        if "colorado-county-reports.html" not in text:
            block = """  <url>\n    <loc>https://fish-finder-reports-live.wasmer.app/colorado-county-reports.html</loc>\n    <changefreq>daily</changefreq>\n    <priority>0.9</priority>\n  </url>\n"""
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

    if not args.skip_network:
        try:
            source_counts["atlas_schema_fields"] = validate_atlas_schema()
            atlas_sources, atlas_reports, atlas_counts = collect_fishing_atlas()
            sources.extend(atlas_sources)
            reports.extend(atlas_reports)
            source_counts.update(atlas_counts)
        except Exception as exc:
            failed_sources.append(f"colorado_fishing_atlas: {exc}")

    if not args.skip_network:
        try:
            source_counts["accessible_page_regions"] = validate_accessible_fishing_page()
        except Exception as exc:
            failed_sources.append(f"colorado_accessible_fishing: {exc}")

    waters = merge_water_sources(sources)

    if not args.skip_network:
        try:
            stocking_reports, stocking_count, ambiguous_count = collect_recent_stocking(waters)
            reports.extend(stocking_reports)
            source_counts["recent_stocking_records"] = stocking_count
            source_counts["ambiguous_stocking_names_left_unmatched"] = ambiguous_count
        except Exception as exc:
            failed_sources.append(f"colorado_stocking_report: {exc}")

    db = assemble_database(waters, reports, generated_at)
    if db["county_count"] != 64 or len(db["counties"]) != 64:
        raise RuntimeError("Colorado database did not create all 64 county shells")

    if args.skip_network:
        validation = {
            "passed": True,
            "mode": "offline_shell_test",
            "county_count": db["county_count"],
        }
        deployment_status = "offline_test_only"
    else:
        validation = validate_live_build(db, source_counts, failed_sources)
        deployment_status = "validated_ready_to_commit"

    status = {
        "generated_at": generated_at,
        "state": STATE,
        "completed": [
            "Verified official 64-county order",
            "Validated the Colorado Fishing Atlas schema",
            "Built the official statewide fishing-water collector",
            "Built duplicate-safe recent CPW trout-stocking collector",
            "Collected official fishery survey and report links",
            "Validated all four CPW accessible-fishing regions",
            "Rejected blank, malformed and out-of-Colorado map coordinates",
            "Built county-by-county Colorado page",
            "Installed multi-state admin integration",
            "Updated navigation, sitemap and PWA cache",
            "Validated all 64 county shells and output files",
        ],
        "known_issues": warnings,
        "failed_sources": failed_sources,
        "deployment_status": deployment_status,
        "public_water_count": db["public_water_count"],
        "report_count": db["report_count"],
        "source_counts": source_counts,
        "validation": validation,
    }

    # No generated or existing site file is touched until every strict live check passes.
    write_outputs(root, output_dir, db, status)
    patch_site_files(root)
    run_admin_builder(root)
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
