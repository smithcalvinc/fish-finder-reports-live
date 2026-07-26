#!/usr/bin/env python3
"""Build Washington Fish Finder Outdoors county data from official public sources.

This builder creates:
- all 39 Washington county shells in alphabetical order
- verified WDFW-managed water access sites
- WDFW shoreline fishing access sites
- WDFW public fishing piers
- lowland lakes with explicit WDFW shoreline or boat-ramp access
- recent official WDFW fish-plant records from Data.WA
- Washington search data/page and shared site integration

Public-access policy
--------------------
A water is published only when an official WDFW dataset explicitly identifies a
managed water-access site, shoreline fishing site, public fishing pier, shoreline
access, or boat ramp. A point verifies only the named facility/site. It never
declares an entire shoreline, river reach, road, or neighboring parcel public.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote_plus
from urllib.request import Request, urlopen

STATE = "Washington"
STATE_ABBR = "WA"
COUNTIES = [
    "Adams", "Asotin", "Benton", "Chelan", "Clallam", "Clark", "Columbia",
    "Cowlitz", "Douglas", "Ferry", "Franklin", "Garfield", "Grant",
    "Grays Harbor", "Island", "Jefferson", "King", "Kitsap", "Kittitas",
    "Klickitat", "Lewis", "Lincoln", "Mason", "Okanogan", "Pacific",
    "Pend Oreille", "Pierce", "San Juan", "Skagit", "Skamania", "Snohomish",
    "Spokane", "Stevens", "Thurston", "Wahkiakum", "Walla Walla", "Whatcom",
    "Whitman", "Yakima",
]
COUNTY_NUMBER = {name: index + 1 for index, name in enumerate(COUNTIES)}
COUNTY_LOOKUP = {
    re.sub(r"[^a-z0-9]+", " ", name.lower()).strip(): name for name in COUNTIES
}

USER_AGENT = "FishFinderOutdoors-WashingtonBuilder/1.0 (+https://fishfinderoutdoors.com)"
ARCGIS_ROOT = "https://geodataservices.wdfw.wa.gov/arcgis/rest/services"
LAYERS = {
    "water_access": f"{ARCGIS_ROOT}/ApplicationServices/Major_Fishing_Area/MapServer/0",
    "public_piers": f"{ARCGIS_ROOT}/ApplicationServices/Major_Fishing_Area/MapServer/1",
    "shore_fishing": f"{ARCGIS_ROOT}/FP_FishMaps/ShoreFishingSites/MapServer/0",
    "lowland_lakes": f"{ARCGIS_ROOT}/ApplicationServices/FishWA_2014_AllLakes_PROD/MapServer/2",
}
OFFICIAL_URLS = {
    "water_access_page": "https://wdfw.wa.gov/places-to-go/water-access-sites",
    "lowland_lakes_page": "https://wdfw.wa.gov/fishing/locations/lowland-lakes",
    "stocking_page": "https://wdfw.wa.gov/fishing/reports/stocking/trout-plants",
    "stocking_dataset": "https://data.wa.gov/resource/6fex-3r7d.json",
    "regulations": "https://wdfw.wa.gov/fishing/regulations",
}

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
    text = re.sub(r"\b(the|of|at|on|lake|reservoir|pond|river|creek|stream)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def slug(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", clean(value).lower()).strip("-")
    return text or "item"

def stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(clean(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"

def canonical_county(value: Any) -> str:
    text = clean(value)
    text = re.sub(r"\s+county$", "", text, flags=re.I)
    key = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    aliases = {
        "pendoreille": "Pend Oreille",
        "pend oreille": "Pend Oreille",
        "graysharbor": "Grays Harbor",
        "grays harbor": "Grays Harbor",
        "sanjuan": "San Juan",
        "san juan": "San Juan",
        "wallawalla": "Walla Walla",
        "walla walla": "Walla Walla",
    }
    return aliases.get(key) or COUNTY_LOOKUP.get(key, "")

def valid_lon_lat(lon: Any, lat: Any) -> bool:
    try:
        x, y = float(lon), float(lat)
    except (TypeError, ValueError):
        return False
    return -125.0 <= x <= -116.7 and 45.5 <= y <= 49.1

def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return round(float(value), 7)
    except (TypeError, ValueError):
        return None

def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) == 1
    return clean(value).lower() in {"1", "yes", "y", "true", "available"}

def request_bytes(url: str, retries: int = 4, timeout: int = 90) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*;q=0.8",
            })
            with urlopen(req, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Unable to retrieve {url}: {last_error}")

def request_json(url: str, retries: int = 4) -> Any:
    payload = json.loads(request_bytes(url, retries=retries).decode("utf-8", errors="replace"))
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"Official data service error for {url}: {payload['error']}")
    return payload

def arcgis_features(layer_url: str, page_size: int = 1800) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "f": "json",
        }
        payload = request_json(f"{layer_url}/query?{urlencode(params)}")
        page = payload.get("features") or []
        features.extend(page)
        if not page or len(page) < page_size or not payload.get("exceededTransferLimit"):
            break
        offset += len(page)
        if offset > 20000:
            raise RuntimeError(f"Unexpectedly large ArcGIS result from {layer_url}")
    return features

def attr(attributes: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in attributes:
            return attributes.get(name)
    lower = {str(key).lower(): value for key, value in attributes.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    for key, value in attributes.items():
        suffix = str(key).split(".")[-1].lower()
        if any(suffix == name.lower() for name in names):
            return value
    return None

def point_coordinates(feature: dict[str, Any], attributes: dict[str, Any]) -> tuple[float | None, float | None]:
    geometry = feature.get("geometry") or {}
    lon = safe_float(geometry.get("x"))
    lat = safe_float(geometry.get("y"))
    if not valid_lon_lat(lon, lat):
        lon = safe_float(attr(attributes, "Longitude", "longitude"))
        lat = safe_float(attr(attributes, "Latitude", "latitude"))
    if not valid_lon_lat(lon, lat):
        return None, None
    return lon, lat

def directions_url(lon: Any, lat: Any) -> str:
    if not valid_lon_lat(lon, lat):
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={float(lat):.7f},{float(lon):.7f}"

def water_type(name: str) -> str:
    lower = clean(name).lower()
    if "reservoir" in lower:
        return "reservoir"
    if re.search(r"\bpond\b", lower):
        return "pond"
    if re.search(r"\briver\b", lower):
        return "river"
    if re.search(r"\bcreek\b", lower):
        return "creek"
    if re.search(r"\bstream\b", lower):
        return "stream"
    if re.search(r"\bmarine\b|\bbay\b|\bharbor\b|\bsound\b|\bcoast\b|\bchannel\b", lower):
        return "marine water"
    if "lake" in lower:
        return "lake"
    return "public fishing water"

def access_record(
    *,
    water_name: str,
    county: str,
    access_name: str,
    source_name: str,
    source_url: str,
    method: str,
    evidence: str,
    details: str = "",
    lon: float | None = None,
    lat: float | None = None,
    amenities: dict[str, Any] | None = None,
    open_dates: str = "",
) -> dict[str, Any]:
    return {
        "access_id": stable_id("wa-access", county, water_name, access_name, source_url),
        "access_point_name": clean(access_name),
        "public_access_status": "verified_public",
        "entire_shoreline_public": False,
        "verification_method": method,
        "source_name": source_name,
        "source_type": "official_wdfw_public_access",
        "official_source_url": source_url,
        "verification_evidence": clip(evidence, 900),
        "access_details": clip(details, 1000),
        "county": county,
        "latitude": lat,
        "longitude": lon,
        "directions_url": directions_url(lon, lat),
        "current_status": "verify_current_conditions_before_travel",
        "open_dates": clean(open_dates),
        "amenities": amenities or {},
    }

def collect_managed_access() -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    features = arcgis_features(LAYERS["water_access"])
    for feature in features:
        a = feature.get("attributes") or {}
        county = canonical_county(attr(a, "CountyName"))
        facility = clean(attr(a, "FacilityName"))
        common = clean(attr(a, "CommonName"))
        if not county or not facility:
            warnings.append(f"Skipped managed access record with missing county/facility: {a}")
            continue
        water = common or facility
        lon, lat = point_coordinates(feature, a)
        launch_type = clean(attr(a, "LaunchType"))
        notes = " ".join(filter(None, [
            clean(attr(a, "PublicNotes")),
            clean(attr(a, "Comments")),
            clean(attr(a, "Directions")),
        ]))
        amenities = {
            "camping": truthy(attr(a, "Camping")),
            "restroom": truthy(attr(a, "Restrooms")),
            "boat_ramp": truthy(attr(a, "Launch")),
            "hand_launch": "hand" in launch_type.lower(),
            "launch_type": launch_type,
            "motorized": truthy(attr(a, "Motorized")),
            "horsepower_limit": clean(attr(a, "HorsePowerLimit")),
            "ada_parking": truthy(attr(a, "ADAParking")),
            "ada_restroom": truthy(attr(a, "ADARestroom")),
            "ada_dock": truthy(attr(a, "ADADock")),
            "ada_boat_launch": truthy(attr(a, "ADABoatLaunch")),
        }
        rows.append({
            "water_name": water,
            "county": county,
            "water_type": water_type(water),
            "latitude": lat,
            "longitude": lon,
            "metadata_source": "wdfw_managed_water_access_layer",
            "water_source_url": OFFICIAL_URLS["water_access_page"],
            "access": access_record(
                water_name=water,
                county=county,
                access_name=facility,
                source_name="Washington Department of Fish and Wildlife",
                source_url=LAYERS["water_access"],
                method="official_wdfw_managed_water_access_site",
                evidence="WDFW's official Water Access Sites layer identifies this managed public water-access facility.",
                details=notes,
                lon=lon,
                lat=lat,
                amenities=amenities,
                open_dates=clean(attr(a, "OpenDates")),
            ),
        })
    return rows, warnings

def collect_shore_sites() -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        features = arcgis_features(LAYERS["shore_fishing"])
    except RuntimeError as exc:
        return [], [str(exc)]
    for feature in features:
        a = feature.get("attributes") or {}
        county = canonical_county(attr(a, "County"))
        water = clean(attr(a, "LakeName"))
        if not county or not water:
            warnings.append(f"Skipped shoreline site with missing county/water: {a}")
            continue
        lon, lat = point_coordinates(feature, a)
        description = clean(attr(a, "Description"))
        rows.append({
            "water_name": water,
            "county": county,
            "water_type": water_type(water),
            "latitude": lat,
            "longitude": lon,
            "metadata_source": "wdfw_shore_fishing_sites_layer",
            "water_source_url": OFFICIAL_URLS["lowland_lakes_page"],
            "access": access_record(
                water_name=water,
                county=county,
                access_name=f"{water} shoreline fishing access",
                source_name="Washington Department of Fish and Wildlife",
                source_url=LAYERS["shore_fishing"],
                method="official_wdfw_shore_fishing_site",
                evidence="WDFW's official Shore Fishing Sites layer identifies pedestrian shoreline access for recreational fishing.",
                details=description,
                lon=lon,
                lat=lat,
                amenities={"shore_fishing": True},
            ),
        })
    return rows, warnings

def collect_public_piers() -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        features = arcgis_features(LAYERS["public_piers"])
    except RuntimeError as exc:
        return [], [str(exc)]
    for feature in features:
        a = feature.get("attributes") or {}
        county = canonical_county(attr(a, "CountyFIPSName", "CountyName"))
        pier = clean(attr(a, "PierName"))
        if not county or not pier:
            warnings.append(f"Skipped public pier with missing county/name: {a}")
            continue
        lon, lat = point_coordinates(feature, a)
        website = clean(attr(a, "WebsiteURL")) or LAYERS["public_piers"]
        rows.append({
            "water_name": pier,
            "county": county,
            "water_type": "public fishing pier",
            "latitude": lat,
            "longitude": lon,
            "metadata_source": "wdfw_public_fishing_pier_layer",
            "water_source_url": website,
            "access": access_record(
                water_name=pier,
                county=county,
                access_name=pier,
                source_name="Washington Department of Fish and Wildlife",
                source_url=website,
                method="official_wdfw_public_fishing_pier",
                evidence="WDFW's official Public Fishing Pier layer identifies a pier or overwater structure open to public pedestrian or fishing access.",
                lon=lon,
                lat=lat,
                amenities={"fishing_pier": True, "shore_fishing": True},
            ),
        })
    return rows, warnings

def collect_lowland_access() -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        features = arcgis_features(LAYERS["lowland_lakes"])
    except RuntimeError as exc:
        return [], [str(exc)]
    for feature in features:
        a = feature.get("attributes") or {}
        county = canonical_county(attr(a, "CountyName"))
        water = clean(attr(a, "LakeName"))
        shore = truthy(attr(a, "ShorelineAccess"))
        ramp = truthy(attr(a, "BoatRampAvailable"))
        if not county or not water or not (shore or ramp):
            continue
        lon, lat = point_coordinates(feature, a)
        website = clean(attr(a, "WebsiteURL")) or OFFICIAL_URLS["lowland_lakes_page"]
        features_text = []
        if shore:
            features_text.append("shoreline access")
        if ramp:
            features_text.append("boat ramp")
        detail = (
            f"WDFW lists {', '.join(features_text)}. "
            f"Lake management: {clean(attr(a, 'PublicManagementType')) or 'not specified'}. "
            f"Surface acres: {clean(attr(a, 'SurfaceAcres')) or 'not specified'}."
        )
        rows.append({
            "water_name": water,
            "county": county,
            "water_type": "lake",
            "latitude": lat,
            "longitude": lon,
            "metadata_source": "wdfw_lowland_lakes_layer",
            "water_source_url": website,
            "access": access_record(
                water_name=water,
                county=county,
                access_name=f"{water} WDFW-listed public access",
                source_name="Washington Department of Fish and Wildlife",
                source_url=website,
                method="official_wdfw_lowland_lake_access_flag",
                evidence="WDFW's official Lowland Lakes layer explicitly marks shoreline access and/or a boat ramp as available.",
                details=detail,
                lon=lon,
                lat=lat,
                amenities={"shore_fishing": shore, "boat_ramp": ramp},
            ),
        })
    return rows, warnings

def parse_date(value: Any) -> str:
    text = clean(value)
    match = re.match(r"(20\d{2}-\d{2}-\d{2})", text)
    return match.group(1) if match else ""

def freshness(value: str) -> str:
    try:
        age = (datetime.now(timezone.utc).date() - date.fromisoformat(value)).days
    except Exception:
        return "date_unknown"
    if age <= 14:
        return "very_current"
    if age <= 30:
        return "current"
    if age <= 90:
        return "recent"
    return "stale"

def collect_stocking() -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    year_floor = datetime.now(timezone.utc).year - 1
    params = {
        "$limit": 50000,
        "$where": f"release_year >= {year_floor}",
        "$order": "release_start_date DESC",
    }
    try:
        payload = request_json(f"{OFFICIAL_URLS['stocking_dataset']}?{urlencode(params)}")
    except RuntimeError as exc:
        return [], [str(exc)]
    if not isinstance(payload, list):
        return [], ["WDFW Fish Plants endpoint did not return a list"]
    reports: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        county = canonical_county(row.get("county"))
        water = clean(row.get("release_location"))
        report_date = parse_date(row.get("release_start_date") or row.get("release_end_date"))
        if not county or not water:
            continue
        species = clean(row.get("species") or row.get("species_type"))
        quantity = clean(
            row.get("number_released")
            or row.get("release_number")
            or row.get("quantity")
            or row.get("fish_released")
            or row.get("number")
        )
        facility = clean(row.get("facility"))
        summary_bits = []
        if quantity:
            summary_bits.append(f"{quantity} fish")
        if species:
            summary_bits.append(species)
        if facility:
            summary_bits.append(f"from {facility}")
        summary = "Stocking record: " + (", ".join(summary_bits) if summary_bits else "official WDFW fish plant")
        reports.append({
            "report_id": stable_id("wa-plant", county, water, report_date, species, quantity, facility),
            "state": STATE,
            "county": county,
            "counties": [county],
            "water_name": water,
            "report_date": report_date,
            "freshness": freshness(report_date),
            "source_type": "official_fish_plant",
            "source_name": "Washington Department of Fish and Wildlife / Data.WA",
            "official": True,
            "title": f"{water} — WDFW Fish Plant",
            "summary": summary,
            "species": species,
            "techniques": "",
            "source_url": OFFICIAL_URLS["stocking_page"],
        })
    unique = {row["report_id"]: row for row in reports}
    return sorted(
        unique.values(),
        key=lambda row: (row.get("report_date", ""), row.get("water_name", "")),
        reverse=True,
    ), warnings

def merge_access_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        county = canonical_county(row.get("county"))
        name = clean(row.get("water_name"))
        if not county or not name:
            continue
        key = (county, norm(name) or slug(name))
        base = grouped.setdefault(key, {
            "water_id": stable_id("wa-water", county, name),
            "state": STATE,
            "county": county,
            "counties": [county],
            "county_number": COUNTY_NUMBER[county],
            "water_name": name,
            "water_type": row.get("water_type") or water_type(name),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "species": "",
            "metadata_sources": [],
            "water_source_urls": [],
            "access_points": [],
            "publication_status": "published_verified_public_access",
        })
        if not valid_lon_lat(base.get("longitude"), base.get("latitude")) and valid_lon_lat(row.get("longitude"), row.get("latitude")):
            base["longitude"], base["latitude"] = row.get("longitude"), row.get("latitude")
        source = clean(row.get("metadata_source"))
        if source and source not in base["metadata_sources"]:
            base["metadata_sources"].append(source)
        source_url = clean(row.get("water_source_url"))
        if source_url and source_url not in base["water_source_urls"]:
            base["water_source_urls"].append(source_url)
        point = row.get("access")
        if point:
            base["access_points"].append(point)

    waters: list[dict[str, Any]] = []
    for base in grouped.values():
        points = {clean(point.get("access_id")): point for point in base["access_points"] if clean(point.get("access_id"))}
        base["access_points"] = sorted(points.values(), key=lambda point: clean(point.get("access_point_name")))
        base["public_access_verification"] = "; ".join(sorted({
            clean(point.get("verification_method")) for point in base["access_points"]
            if clean(point.get("verification_method"))
        }))
        waters.append(base)
    return sorted(waters, key=lambda row: (row["county_number"], row["water_name"].lower()))

def attach_reports(waters: list[dict[str, Any]], reports: list[dict[str, Any]]) -> None:
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        by_key[(clean(report.get("county")), norm(report.get("water_name")))].append(report)
    for water in waters:
        matches = by_key.get((water["county"], norm(water["water_name"])), [])
        matches.sort(key=lambda row: row.get("report_date", ""), reverse=True)
        water["reports"] = matches[:50]
        water["latest_report"] = matches[0] if matches else None
        water["report_status"] = matches[0].get("freshness") if matches else "no_current_report"

def build_database(waters: list[dict[str, Any]], reports: list[dict[str, Any]], generated_at: str, warnings: list[str], source_counts: dict[str, int]) -> dict[str, Any]:
    attach_reports(waters, reports)
    county_blocks: list[dict[str, Any]] = []
    flat_waters: list[dict[str, Any]] = []
    for number, county in enumerate(COUNTIES, start=1):
        county_waters = [dict(row) for row in waters if row["county"] == county]
        flat_waters.extend(county_waters)
        county_blocks.append({
            "county_number": number,
            "county": county,
            "public_water_count": len(county_waters),
            "verified_access_point_count": sum(len(row.get("access_points") or []) for row in county_waters),
            "coverage_status": "verified_records_available" if county_waters else "no_wdfw_verified_record_found",
            "coverage_note": (
                "Only official WDFW records with explicit public-access evidence are displayed."
                if county_waters else
                "The county remains searchable, but no qualifying WDFW public-access record was returned in this run."
            ),
            "waters": county_waters,
        })
    unique_access = {
        point["access_id"]
        for water in waters
        for point in (water.get("access_points") or [])
    }
    return {
        "metadata": {
            "state": STATE,
            "state_abbr": STATE_ABBR,
            "version": "1.0-official-wdfw-direct-data",
            "generated_at": generated_at,
            "public_access_only": True,
            "county_order": "alphabetical, 1 Adams through 39 Yakima",
            "access_policy": (
                "A water is displayed only when an official WDFW dataset identifies a managed "
                "water-access site, shoreline fishing site, public fishing pier, shoreline access, "
                "or boat ramp. The named facility does not make an entire shoreline or neighboring "
                "property public. Current closures, posted rules, tribal restrictions and fishing "
                "regulations always control."
            ),
            "sources": [
                {"name": "WDFW Water Access Sites", "type": "official_public_access", "url": LAYERS["water_access"]},
                {"name": "WDFW Shore Fishing Sites", "type": "official_public_access", "url": LAYERS["shore_fishing"]},
                {"name": "WDFW Public Fishing Piers", "type": "official_public_access", "url": LAYERS["public_piers"]},
                {"name": "WDFW Lowland Lakes", "type": "official_water_metadata_and_access", "url": LAYERS["lowland_lakes"]},
                {"name": "WDFW Fish Plants", "type": "official_stocking_reports", "url": OFFICIAL_URLS["stocking_dataset"]},
            ],
            "source_warnings": warnings,
            "source_counts": source_counts,
        },
        "county_count": 39,
        "public_water_count": len(waters),
        "verified_access_point_count": len(unique_access),
        "report_count": len(reports),
        "counties": county_blocks,
        "flat_waters": flat_waters,
        "flat_reports": reports,
    }

def validate_database(db: dict[str, Any]) -> dict[str, Any]:
    if db.get("county_count") != 39 or len(db.get("counties") or []) != 39:
        raise RuntimeError("Washington build did not create all 39 county shells")
    if [row.get("county") for row in db["counties"]] != COUNTIES:
        raise RuntimeError("Washington county order is incorrect")
    if db.get("public_water_count", 0) < 100:
        raise RuntimeError(f"Only {db.get('public_water_count')} verified public waters were produced")
    if db.get("verified_access_point_count", 0) < 150:
        raise RuntimeError(f"Only {db.get('verified_access_point_count')} verified access points were produced")
    bad: list[str] = []
    seen: set[str] = set()
    methods: set[str] = set()
    for water in db.get("flat_waters") or []:
        if water.get("publication_status") != "published_verified_public_access":
            bad.append(f"{water.get('water_name')}: invalid publication status")
        if water.get("county") not in COUNTY_NUMBER:
            bad.append(f"{water.get('water_name')}: invalid county")
        if not water.get("access_points"):
            bad.append(f"{water.get('water_name')}: missing access")
        lat, lon = water.get("latitude"), water.get("longitude")
        if (lat is None) != (lon is None):
            bad.append(f"{water.get('water_name')}: partial coordinates")
        if lat is not None and not valid_lon_lat(lon, lat):
            bad.append(f"{water.get('water_name')}: invalid coordinates")
        for point in water.get("access_points") or []:
            access_id = clean(point.get("access_id"))
            if access_id in seen:
                bad.append(f"{water.get('water_name')}: duplicate access id")
            seen.add(access_id)
            methods.add(clean(point.get("verification_method")))
            if point.get("public_access_status") != "verified_public":
                bad.append(f"{water.get('water_name')}: non-public access status")
            if point.get("entire_shoreline_public") is not False:
                bad.append(f"{water.get('water_name')}: unsafe shoreline claim")
            if not clean(point.get("official_source_url")).startswith("https://"):
                bad.append(f"{water.get('water_name')}: missing official source URL")
            if not clean(point.get("verification_evidence")):
                bad.append(f"{water.get('water_name')}: missing evidence")
    if bad:
        raise RuntimeError("Washington strict validation failed: " + "; ".join(bad[:20]))
    if len(methods) < 1:
        raise RuntimeError("No official public-access verification method was represented")
    return {
        "passed": True,
        "strict_public_access": True,
        "county_count": 39,
        "public_water_count": db["public_water_count"],
        "verified_access_point_count": db["verified_access_point_count"],
        "report_count": db["report_count"],
        "populated_counties": sum(1 for row in db["counties"] if row["public_water_count"] > 0),
        "access_verification_methods": sorted(methods),
    }

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")

def write_js(path: Path, variable: str, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"/* Automatically generated Washington data. Do not hand-edit. */\n"
        f"window.{variable} = {json.dumps(value, separators=(',', ':'), ensure_ascii=False)};\n",
        encoding="utf-8",
    )

def page_html() -> str:
    options = "".join(
        f'<option value="{html.escape(county)}">#{index + 1} {html.escape(county)} County</option>'
        for index, county in enumerate(COUNTIES)
    )
    template = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Washington Public Fishing Access | Fish Finder Outdoors</title>
<meta name="description" content="Search official WDFW public fishing access sites, shoreline access, boat ramps, piers and recent fish plants by Washington county.">
<style>
:root{--ink:#13251f;--muted:#5c6c65;--paper:#f3f1e7;--green:#184f3b;--gold:#d9a72e;--line:#d8d7cd}
*{box-sizing:border-box}
body{margin:0;background:linear-gradient(180deg,#123d30 0,#123d30 250px,var(--paper) 250px);font-family:Arial,Helvetica,sans-serif;color:var(--ink)}
header{max-width:1200px;margin:auto;padding:32px 18px 30px;color:#fff}
h1{font-size:clamp(2rem,5vw,4rem);margin:8px 0}
.eyebrow{color:#f2c85d;font-weight:800;letter-spacing:.12em;text-transform:uppercase}
.sub{max-width:900px;line-height:1.55}
.state-links{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
.state-links a{color:#fff;border:1px solid rgba(255,255,255,.4);border-radius:999px;padding:8px 12px;text-decoration:none;font-size:.9rem}
.state-links a.current{background:#fff;color:var(--green)}
main{max-width:1200px;margin:auto;padding:0 18px 60px}
.panel,.water-card{background:#fff;border-radius:18px;box-shadow:0 14px 40px rgba(0,0,0,.12);padding:20px;margin-bottom:20px}
.controls{display:grid;grid-template-columns:repeat(12,1fr);gap:12px}
.field{grid-column:span 4}.field.wide{grid-column:span 5}.field.small{grid-column:span 3}
label{display:block;font-weight:700;margin-bottom:6px}
select,input,button{width:100%;min-height:45px;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font:inherit}
button{background:var(--green);color:#fff;border:0;font-weight:800;cursor:pointer}
.checks{display:flex;flex-wrap:wrap;gap:12px;margin-top:14px}
.checks label{display:flex;align-items:center;gap:6px;font-weight:600}
.checks input{width:auto;min-height:auto}
.warning{background:#fff4cf;border-left:5px solid var(--gold);line-height:1.5}
.summary{display:flex;justify-content:space-between;gap:12px;align-items:center}
.muted{color:var(--muted)}
.water-card{border:1px solid var(--line);box-shadow:none}
.water-card h2{margin:0 0 8px;font-size:1.45rem}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:.78rem;padding:5px 8px;border-radius:999px;background:#edf1ed}
.details{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:14px}
.box{border-top:1px solid var(--line);padding-top:12px}
.box h3{margin:0 0 8px;font-size:1rem}
.access-point{background:#f7f7f2;border-radius:10px;padding:12px;margin-top:9px}
.verified{font-size:.78rem;font-weight:800;color:var(--green);text-transform:uppercase;letter-spacing:.04em}
.link{display:inline-block;text-decoration:none;font-weight:800;color:var(--green);margin:8px 10px 0 0}
.load{max-width:240px;margin:20px auto;display:block}
@media(max-width:760px){.field,.field.wide,.field.small{grid-column:1/-1}.details{grid-template-columns:1fr}.summary{display:block}}
</style>
</head>
<body>
<header>
<div class="eyebrow">Fish Finder Outdoors</div>
<h1>Washington Public Fishing Access</h1>
<p class="sub">Search official WDFW-managed water access sites, shoreline fishing locations, public piers and lowland lakes with explicit shoreline or boat-ramp access. Only the named facility is verified public.</p>
<nav class="state-links">
<a href="idaho-county-reports.html">Idaho</a>
<a href="montana-county-reports.html">Montana</a>
<a href="utah-county-reports.html">Utah</a>
<a href="colorado-county-reports.html">Colorado</a>
<a href="wyoming-county-reports.html">Wyoming</a>
<a href="nevada-county-reports.html">Nevada</a>
<a class="current" href="washington-county-reports.html">Washington</a>
</nav>
</header>
<main>
<section class="panel">
<div class="controls">
<div class="field"><label for="countySelect">County</label><select id="countySelect"><option value="">All 39 counties</option>__COUNTY_OPTIONS__</select></div>
<div class="field wide"><label for="waterSearch">Water or access feature</label><input id="waterSearch" placeholder="Lake, river, boat ramp, pier…"></div>
<div class="field small"><label>&nbsp;</label><button id="searchButton">Search Washington</button></div>
</div>
<div class="checks">
<label><input type="checkbox" id="boatRamp"> Boat ramp</label>
<label><input type="checkbox" id="shoreFishing"> Shore fishing</label>
<label><input type="checkbox" id="adaAccess"> ADA feature</label>
</div>
</section>
<section class="panel warning"><strong>Important:</strong> Official data verifies the named access site only—not every shoreline, road or nearby parcel. Check WDFW alerts, current regulations, posted signs, tribal rules, fees and seasonal closures before traveling.</section>
<section class="summary"><div><strong id="resultCount">Loading Washington records…</strong><div class="muted" id="generated"></div></div></section>
<div id="results"></div>
<button class="load" id="loadMore" hidden>Load more</button>
</main>
<script src="data/washington_fishing_report_database.js"></script>
<script>
(function(){
"use strict";
const db=window.WASHINGTON_FISHING_REPORT_DATABASE||{flat_waters:[],metadata:{}};
const $=id=>document.getElementById(id);
const county=$("countySelect"),search=$("waterSearch"),ramp=$("boatRamp"),shore=$("shoreFishing"),ada=$("adaAccess"),results=$("results"),count=$("resultCount"),generated=$("generated"),more=$("loadMore");
let filtered=[],shown=0;
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c]));
const label=v=>String(v||"").replaceAll("_"," ").replace(/\\b\\w/g,c=>c.toUpperCase());
function matches(w){
  if(county.value&&w.county!==county.value)return false;
  const points=w.access_points||[];
  if(ramp.checked&&!points.some(p=>p.amenities&&p.amenities.boat_ramp===true))return false;
  if(shore.checked&&!points.some(p=>p.amenities&&(p.amenities.shore_fishing===true||p.amenities.fishing_pier===true)))return false;
  if(ada.checked&&!points.some(p=>p.amenities&&(p.amenities.ada_parking||p.amenities.ada_restroom||p.amenities.ada_dock||p.amenities.ada_boat_launch)))return false;
  const q=search.value.toLowerCase().trim();
  if(q){
    const hay=[w.water_name,w.water_type,w.county,w.species,points.map(p=>[p.access_point_name,p.access_details,JSON.stringify(p.amenities||{})].join(" ")).join(" ")].join(" ").toLowerCase();
    if(!hay.includes(q))return false;
  }
  return true;
}
function pointCard(p){
  const map=p.directions_url?`<a class="link" href="${esc(p.directions_url)}" target="_blank" rel="noopener">Directions</a>`:"";
  const source=p.official_source_url?`<a class="link" href="${esc(p.official_source_url)}" target="_blank" rel="noopener">Official source</a>`:"";
  const features=Object.entries(p.amenities||{}).filter(([,v])=>v===true||(typeof v==="string"&&v)).map(([k,v])=>v===true?label(k):`${label(k)}: ${esc(v)}`).join(" · ");
  return `<div class="access-point"><div class="verified">Verified public access</div><strong>${esc(p.access_point_name)}</strong>${p.access_details?`<p>${esc(p.access_details)}</p>`:""}${features?`<div class="muted">${features}</div>`:""}${map}${source}</div>`;
}
function card(w){
  const report=w.latest_report;
  const reportHtml=report?`<strong>${esc(report.title)}</strong><p>${esc(report.summary)}</p><div class="muted">${esc(report.report_date||"Date not listed")}</div><a class="link" href="${esc(report.source_url)}" target="_blank" rel="noopener">Official stocking source</a>`:`<div class="muted">No recent WDFW fish-plant record matched to this water.</div>`;
  return `<article class="water-card"><h2>${esc(w.water_name)}</h2><div class="chips"><span class="chip">#${w.county_number} ${esc(w.county)} County</span><span class="chip">${esc(label(w.water_type))}</span><span class="chip">${(w.access_points||[]).length} access point(s)</span></div><div class="details"><div class="box"><h3>Recent official information</h3>${reportHtml}</div><div class="box"><h3>Verified access points</h3>${(w.access_points||[]).map(pointCard).join("")}</div></div></article>`;
}
function renderMore(){
  const next=filtered.slice(shown,shown+30);
  results.insertAdjacentHTML("beforeend",next.map(card).join(""));
  shown+=next.length;
  more.hidden=shown>=filtered.length;
}
function runSearch(){
  filtered=(db.flat_waters||[]).filter(matches);
  shown=0;
  results.innerHTML="";
  count.textContent=`${filtered.length.toLocaleString()} verified Washington public fishing records found`;
  renderMore();
}
$("searchButton").addEventListener("click",runSearch);
county.addEventListener("change",runSearch);
search.addEventListener("keydown",e=>{if(e.key==="Enter")runSearch()});
ramp.addEventListener("change",runSearch);
shore.addEventListener("change",runSearch);
ada.addEventListener("change",runSearch);
more.addEventListener("click",renderMore);
generated.textContent=db.metadata.generated_at?`Updated ${db.metadata.generated_at}`:"";
runSearch();
})();
</script>
<script src="brand-shell.js"></script>
<script src="pwa.js"></script>
</body>
</html>"""
    return template.replace("__COUNTY_OPTIONS__", options)

def patch_brand_shell(root: Path) -> None:
    path = root / "brand-shell.js"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    entry = "['washington-county-reports.html','Washington County Reports']"
    if entry in text:
        return
    match = re.search(r"(const\s+stateLinks\s*=\s*\[)(.*?)(\];)", text, flags=re.S)
    if match:
        body = match.group(2).rstrip()
        if body and not body.endswith(","):
            body += ","
        body += entry
        text = text[:match.start(2)] + body + text[match.end(2):]
    path.write_text(text, encoding="utf-8")

def patch_service_worker(root: Path) -> None:
    path = root / "service-worker.js"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    version = re.search(r"ffo-reports-pwa-v(\d+)", text)
    if version:
        text = text.replace(version.group(0), f"ffo-reports-pwa-v{int(version.group(1)) + 1}", 1)
    page = '"./washington-county-reports.html"'
    if page not in text:
        text = text.replace('"./nevada-county-reports.html"', '"./nevada-county-reports.html",' + page)
    data_names = [
        "washington_fishing_report_database.js",
        "washington_fishing_report_database.json",
        "washington_public_fishing_access.js",
        "washington_public_fishing_access.json",
    ]
    for name in data_names:
        token = f'"{name}"'
        if token in text:
            continue
        marker = '"utah_fishing_report_database.js"'
        if marker in text:
            text = text.replace(marker, marker + "," + token, 1)
    path.write_text(text, encoding="utf-8")

def patch_sitemap(root: Path) -> None:
    path = root / "sitemap.xml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if "washington-county-reports.html" in text:
        return
    host = "https://fish-finder-reports-live.wasmer.app"
    host_match = re.search(r"<loc>(https?://[^/<]+)", text)
    if host_match:
        host = host_match.group(1)
    block = (
        f"\n  <url><loc>{host}/washington-county-reports.html</loc>"
        f"<lastmod>{datetime.now(timezone.utc).date().isoformat()}</lastmod>"
        f"<changefreq>daily</changefreq><priority>0.9</priority></url>\n"
    )
    text = text.replace("</urlset>", block + "</urlset>")
    path.write_text(text, encoding="utf-8")

def read_state_databases(root: Path) -> list[dict[str, Any]]:
    paths = list(root.glob("data/*_fishing_report_database.json")) + list(root.glob("*_fishing_report_database.json"))
    databases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        try:
            db = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        state = clean((db.get("metadata") or {}).get("state") or db.get("state"))
        if not state or state in seen:
            continue
        seen.add(state)
        databases.append(db)
    return databases

def rebuild_shared_feeds(root: Path) -> None:
    databases = read_state_databases(root)
    state_rows = []
    reports = []
    for db in databases:
        metadata = db.get("metadata") or {}
        state = clean(metadata.get("state") or db.get("state"))
        state_rows.append({
            "state": state,
            "report_count": int(db.get("report_count", 0) or 0),
            "public_water_count": int(db.get("public_water_count", 0) or 0),
            "county_count": int(db.get("county_count", 0) or 0),
            "generated_at": clean(metadata.get("generated_at")),
        })
        for report in db.get("flat_reports") or []:
            item = dict(report)
            item["state"] = state
            reports.append(item)
    state_rows.sort(key=lambda row: row["state"])
    reports.sort(key=lambda row: clean(row.get("report_date")), reverse=True)
    updated = max((row["generated_at"] for row in state_rows if row["generated_at"]), default=now_iso())
    recent = {
        "version": f"{updated}-multi-state",
        "updated_at": updated,
        "coverage_note": "Automatically generated from installed state county fishing databases.",
        "states": state_rows,
        "reports": reports,
    }
    status = {
        "last_run": updated,
        "mode": "multi-state-database",
        "state_count": len(state_rows),
        "states": state_rows,
        "reports_total": sum(row["report_count"] for row in state_rows),
        "public_water_count": sum(row["public_water_count"] for row in state_rows),
        "county_count": sum(row["county_count"] for row in state_rows),
        "unique_sources": len({
            clean(report.get("source_url")) for report in reports if clean(report.get("source_url"))
        }),
        "freshness": {
            "current": sum(1 for report in reports if report.get("freshness") in {"very_current", "current"}),
            "aging": sum(1 for report in reports if report.get("freshness") == "recent"),
            "stale": sum(1 for report in reports if report.get("freshness") == "stale"),
            "unknown": sum(1 for report in reports if report.get("freshness") == "date_unknown"),
        },
        "changed_reports": len(reports),
        "review_required": 0,
        "unreachable_sources": 0,
        "unmatched_report_count": 0,
        "sources": [],
    }
    write_js(root / "recent_fishing_reports.js", "FFO_RECENT_REPORTS", recent)
    write_js(root / "update_status.js", "FFO_UPDATE_STATUS", status)

def write_outputs(root: Path, output_dir: Path, db: dict[str, Any], status: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "washington_fishing_report_database.json", db)
    write_js(output_dir / "washington_fishing_report_database.js", "WASHINGTON_FISHING_REPORT_DATABASE", db)
    access = {
        "metadata": db["metadata"],
        "county_count": db["county_count"],
        "public_water_count": db["public_water_count"],
        "verified_access_point_count": db["verified_access_point_count"],
        "counties": db["counties"],
        "flat_waters": db["flat_waters"],
    }
    write_json(output_dir / "washington_public_fishing_access.json", access)
    write_js(output_dir / "washington_public_fishing_access.js", "WASHINGTON_PUBLIC_FISHING_ACCESS", access)
    write_json(output_dir / "washington_source_audit.json", {
        "state": STATE,
        "generated_at": db["metadata"]["generated_at"],
        "source_counts": db["metadata"]["source_counts"],
        "source_warnings": db["metadata"]["source_warnings"],
    })
    write_json(output_dir / "washington_project_status.json", status)
    write_json(root / "config/washington_counties.json", {
        "state": STATE,
        "county_count": 39,
        "counties": [{"county_number": i + 1, "county": county} for i, county in enumerate(COUNTIES)],
    })
    with (output_dir / "washington_counties.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["county_number", "county"])
        writer.writerows((i + 1, county) for i, county in enumerate(COUNTIES))
    with (output_dir / "washington_fishing_report_database.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = [
            "county_number", "county", "water_name", "water_type",
            "access_point_name", "verification_method", "official_source_url",
            "latitude", "longitude", "directions_url", "access_details",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for water in db["flat_waters"]:
            for point in water.get("access_points") or []:
                writer.writerow({
                    "county_number": water["county_number"],
                    "county": water["county"],
                    "water_name": water["water_name"],
                    "water_type": water["water_type"],
                    "access_point_name": point["access_point_name"],
                    "verification_method": point["verification_method"],
                    "official_source_url": point["official_source_url"],
                    "latitude": point.get("latitude", ""),
                    "longitude": point.get("longitude", ""),
                    "directions_url": point.get("directions_url", ""),
                    "access_details": point.get("access_details", ""),
                })
    (root / "washington-county-reports.html").write_text(page_html(), encoding="utf-8")
    patch_brand_shell(root)
    patch_service_worker(root)
    patch_sitemap(root)
    rebuild_shared_feeds(root)

def run_self_tests() -> None:
    assert len(COUNTIES) == 39
    assert COUNTIES[0] == "Adams"
    assert COUNTIES[-1] == "Yakima"
    assert canonical_county("Pend Oreille County") == "Pend Oreille"
    assert canonical_county("Grays Harbor") == "Grays Harbor"
    assert valid_lon_lat(-122.33, 47.61)
    assert not valid_lon_lat(0, 0)
    assert truthy("Yes")
    assert water_type("Columbia River") == "river"
    print("Washington builder self-tests passed.")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        run_self_tests()
        return 0

    root = Path(args.root).resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    generated_at = now_iso()

    managed, managed_warnings = collect_managed_access()  # required source
    if len(managed) < 150:
        raise RuntimeError(f"WDFW managed water-access source returned only {len(managed)} usable records")

    shore, shore_warnings = collect_shore_sites()
    piers, pier_warnings = collect_public_piers()
    lowland, lowland_warnings = collect_lowland_access()
    reports, report_warnings = collect_stocking()

    all_rows = [*managed, *shore, *piers, *lowland]
    warnings = [
        *managed_warnings, *shore_warnings, *pier_warnings,
        *lowland_warnings, *report_warnings,
    ]
    source_counts = {
        "wdfw_managed_access_records": len(managed),
        "wdfw_shore_fishing_records": len(shore),
        "wdfw_public_pier_records": len(piers),
        "wdfw_lowland_lake_access_records": len(lowland),
        "wdfw_recent_fish_plant_records": len(reports),
        "source_warning_count": len(warnings),
    }
    waters = merge_access_rows(all_rows)
    db = build_database(waters, reports, generated_at, warnings, source_counts)
    validation = validate_database(db)
    status = {
        "state": STATE,
        "generated_at": generated_at,
        "deployment_status": "validated_complete_ready_to_commit",
        "source_counts": source_counts,
        "source_warnings": warnings,
        "validation": validation,
        "notes": [
            "The required source is WDFW's direct managed Water Access Sites GIS layer.",
            "Shore fishing sites, public piers, lowland lake access flags and fish plants are official optional enrichment sources.",
            "No recursive crawling or search-engine results are used.",
            "All 39 county shells are generated even when a county has no qualifying record.",
            "Only named official access points are published.",
        ],
    }
    write_outputs(root, output_dir, db, status)
    print(json.dumps({
        "state": STATE,
        "counties": 39,
        "verified_public_waters": db["public_water_count"],
        "verified_access_points": db["verified_access_point_count"],
        "recent_fish_plant_records": db["report_count"],
        "populated_counties": validation["populated_counties"],
        "generated_at": generated_at,
    }, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
