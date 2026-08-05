#!/usr/bin/env python3
"""Build Washington Fish Finder Outdoors data from official WDFW sources.

This replacement fixes the fragile Washington build by:
- downloading ArcGIS records by object ID in small chunks;
- verifying that every advertised object ID was actually returned;
- treating the WDFW-managed Water Access Sites layer as required;
- treating shoreline sites, public piers, lowland-lake access, and fish plants
  as optional enrichment sources;
- validating data integrity instead of relying on brittle exact record totals;
- producing all 39 Washington county shells in alphabetical order.

Only named facilities or sites explicitly supported by official WDFW data are
published. A point never proves that an entire shoreline, road, or neighboring
parcel is public.
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
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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
COUNTY_NUMBER = {county: index + 1 for index, county in enumerate(COUNTIES)}
COUNTY_LOOKUP = {
    re.sub(r"[^a-z0-9]+", " ", county.lower()).strip(): county
    for county in COUNTIES
}

USER_AGENT = "FishFinderOutdoors-WashingtonBuilder/2.0 (+https://fishfinderoutdoors.com)"
ARCGIS_ROOT = "https://geodataservices.wdfw.wa.gov/arcgis/rest/services"
LAYERS = {
    "water_access": f"{ARCGIS_ROOT}/FP_Projects/MajorFishingArea/MapServer/0",
    "public_piers": f"{ARCGIS_ROOT}/FP_Projects/MajorFishingArea/MapServer/1",
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

MIN_REQUIRED_ACCESS_RECORDS = 25
MIN_POPULATED_COUNTIES = 10


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def clip(value: Any, limit: int = 800) -> str:
    text = clean(value)
    if len(text) <= limit:
        return text
    shortened = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return shortened + "…"


def norm(value: Any) -> str:
    text = clean(value).lower().replace("&", " and ")
    text = re.sub(r"\b(the|of|at|on)\b", " ", text)
    text = re.sub(r"\b(lake|reservoir|pond|river|creek|stream)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slug(value: Any) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", clean(value).lower()).strip("-")
    return result or "item"


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(clean(part) for part in parts)
    return f"{prefix}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def canonical_county(value: Any) -> str:
    text = re.sub(r"\s+county$", "", clean(value), flags=re.I)
    key = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    compact = key.replace(" ", "")
    aliases = {
        "pendoreille": "Pend Oreille",
        "graysharbor": "Grays Harbor",
        "sanjuan": "San Juan",
        "wallawalla": "Walla Walla",
    }
    return aliases.get(compact) or COUNTY_LOOKUP.get(key, "")


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return round(float(value), 7)
    except (TypeError, ValueError):
        return None


def valid_lon_lat(lon: Any, lat: Any) -> bool:
    try:
        x, y = float(lon), float(lat)
    except (TypeError, ValueError):
        return False
    return -125.0 <= x <= -116.7 and 45.5 <= y <= 49.1


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) == 1
    return clean(value).lower() in {"1", "yes", "y", "true", "available"}


def parse_date(value: Any) -> str:
    match = re.match(r"(20\d{2}-\d{2}-\d{2})", clean(value))
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


def attr(attributes: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in attributes:
            return attributes.get(name)
    lowered = {str(key).lower(): value for key, value in attributes.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    wanted = {name.lower() for name in names}
    for key, value in attributes.items():
        if str(key).split(".")[-1].lower() in wanted:
            return value
    return None


def request_bytes(url: str, retries: int = 4, timeout: int = 90) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json,text/plain,*/*;q=0.8",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Unable to retrieve {url}: {last_error}")


def request_json(url: str, retries: int = 4) -> Any:
    raw = request_bytes(url, retries=retries).decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Official source returned invalid JSON for {url}: {exc}") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"Official data service error for {url}: {payload['error']}")
    return payload


def arcgis_query_url(layer_url: str, params: dict[str, Any]) -> str:
    return f"{layer_url}/query?{urlencode(params)}"


def arcgis_layer_info(layer_url: str) -> dict[str, Any]:
    payload = request_json(f"{layer_url}?f=json")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected ArcGIS layer metadata from {layer_url}")
    fields = payload.get("fields") or []
    oid = next((field.get("name") for field in fields if field.get("type") == "esriFieldTypeOID"), "")
    if not oid:
        raise RuntimeError(f"ArcGIS layer did not expose an object-ID field: {layer_url}")
    return {
        "layer_url": layer_url,
        "name": clean(payload.get("name")),
        "object_id_field": clean(oid),
        "field_names": [clean(field.get("name")) for field in fields],
        "max_record_count": int(payload.get("maxRecordCount") or 0),
        "supports_pagination": bool((payload.get("advancedQueryCapabilities") or {}).get("supportsPagination")),
    }


def _fetch_arcgis_chunk(layer_url: str, object_ids: list[int], retries: int = 4) -> list[dict[str, Any]]:
    if not object_ids:
        return []
    params = {
        "objectIds": ",".join(str(item) for item in object_ids),
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    url = arcgis_query_url(layer_url, params)
    try:
        payload = request_json(url, retries=retries)
    except RuntimeError as exc:
        message = str(exc)
        if len(object_ids) > 1 and any(code in message for code in ("403", "414", "429", "502", "503", "504")):
            middle = len(object_ids) // 2
            return _fetch_arcgis_chunk(layer_url, object_ids[:middle], retries) + _fetch_arcgis_chunk(layer_url, object_ids[middle:], retries)
        raise
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected ArcGIS feature payload from {layer_url}")
    return payload.get("features") or []


def arcgis_features(layer_url: str, chunk_size: int = 50) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Download a whole ArcGIS layer in small, checked object-ID chunks."""
    info = arcgis_layer_info(layer_url)
    ids_payload = request_json(arcgis_query_url(layer_url, {
        "where": "1=1",
        "returnIdsOnly": "true",
        "f": "json",
    }))
    if not isinstance(ids_payload, dict):
        raise RuntimeError(f"Unexpected ArcGIS object-ID response from {layer_url}")
    object_ids = sorted({int(item) for item in (ids_payload.get("objectIds") or [])})
    if not object_ids:
        raise RuntimeError(f"Official ArcGIS layer returned no object IDs: {layer_url}")

    features: list[dict[str, Any]] = []
    for start in range(0, len(object_ids), chunk_size):
        features.extend(_fetch_arcgis_chunk(layer_url, object_ids[start:start + chunk_size]))

    oid_name = info["object_id_field"]
    returned: dict[int, dict[str, Any]] = {}
    for feature in features:
        attributes = feature.get("attributes") or {}
        value = attr(attributes, oid_name)
        try:
            returned[int(value)] = feature
        except (TypeError, ValueError):
            continue

    missing = [item for item in object_ids if item not in returned]
    if missing:
        for item in missing:
            for feature in _fetch_arcgis_chunk(layer_url, [item], retries=5):
                attributes = feature.get("attributes") or {}
                value = attr(attributes, oid_name)
                try:
                    returned[int(value)] = feature
                except (TypeError, ValueError):
                    pass
        missing = [item for item in object_ids if item not in returned]
    if missing:
        raise RuntimeError(
            f"Incomplete ArcGIS download from {layer_url}: expected {len(object_ids)} records, "
            f"received {len(returned)}; missing object IDs {missing[:12]}"
        )

    ordered = [returned[item] for item in object_ids]
    audit = {
        **info,
        "advertised_object_id_count": len(object_ids),
        "downloaded_feature_count": len(ordered),
        "complete": len(ordered) == len(object_ids),
        "chunk_size": chunk_size,
    }
    return ordered, audit


def point_coordinates(feature: dict[str, Any], attributes: dict[str, Any]) -> tuple[float | None, float | None]:
    geometry = feature.get("geometry") or {}
    lon = safe_float(geometry.get("x"))
    lat = safe_float(geometry.get("y"))
    if not valid_lon_lat(lon, lat):
        lon = safe_float(attr(attributes, "Longitude"))
        lat = safe_float(attr(attributes, "Latitude"))
    if not valid_lon_lat(lon, lat):
        return None, None
    return lon, lat


def directions_url(lon: Any, lat: Any) -> str:
    if not valid_lon_lat(lon, lat):
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={float(lat):.7f},{float(lon):.7f}"


def water_type(name: str) -> str:
    lower = clean(name).lower()
    for token, kind in (
        ("reservoir", "reservoir"), ("pond", "pond"), ("river", "river"),
        ("creek", "creek"), ("stream", "stream"), ("lake", "lake"),
    ):
        if re.search(rf"\b{token}\b", lower):
            return kind
    if re.search(r"\b(bay|harbor|sound|channel|marine|coast)\b", lower):
        return "marine water"
    return "public fishing water"


def access_record(
    *,
    water_name: str,
    county: str,
    access_name: str,
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
        "source_name": "Washington Department of Fish and Wildlife",
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


def collect_managed_access() -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    features, audit = arcgis_features(LAYERS["water_access"])
    launch_types = {1: "Concrete", 2: "Gravel", 3: "Hand Launch", 4: "Unimproved"}
    for feature in features:
        attributes = feature.get("attributes") or {}
        county = canonical_county(attr(attributes, "CountyName"))
        facility = clean(attr(attributes, "FacilityName"))
        common = clean(attr(attributes, "CommonName"))
        if not county or not facility:
            warnings.append(f"Skipped managed access record missing county/facility: {clip(attributes, 300)}")
            continue
        water = common or facility
        lon, lat = point_coordinates(feature, attributes)
        raw_launch_type = attr(attributes, "LaunchType")
        try:
            launch_type = launch_types.get(int(raw_launch_type), clean(raw_launch_type))
        except (TypeError, ValueError):
            launch_type = clean(raw_launch_type)
        notes = " ".join(filter(None, [
            clean(attr(attributes, "PublicNotes")),
            clean(attr(attributes, "Comments")),
            clean(attr(attributes, "Directions")),
        ]))
        amenities = {
            "camping": truthy(attr(attributes, "Camping")),
            "restroom": truthy(attr(attributes, "Restrooms")),
            "boat_ramp": truthy(attr(attributes, "Launch")),
            "hand_launch": "hand" in launch_type.lower(),
            "launch_type": launch_type,
            "motorized": truthy(attr(attributes, "Motorized")),
            "horsepower_limit": clean(attr(attributes, "HorsePowerLimit")),
            "ada_parking": truthy(attr(attributes, "ADAParking")),
            "ada_restroom": truthy(attr(attributes, "ADARestroom")),
            "ada_dock": truthy(attr(attributes, "ADADock")),
            "ada_boat_launch": truthy(attr(attributes, "ADABoatLaunch")),
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
                source_url=LAYERS["water_access"],
                method="official_wdfw_managed_water_access_site",
                evidence="WDFW's official Water Access Sites layer identifies this managed public water-access facility.",
                details=notes,
                lon=lon,
                lat=lat,
                amenities=amenities,
                open_dates=clean(attr(attributes, "OpenDates")),
            ),
        })
    audit["usable_records"] = len(rows)
    audit["skipped_records"] = len(warnings)
    return rows, warnings, audit


def collect_shore_sites() -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    features, audit = arcgis_features(LAYERS["shore_fishing"])
    for feature in features:
        attributes = feature.get("attributes") or {}
        county = canonical_county(attr(attributes, "County"))
        water = clean(attr(attributes, "LakeName"))
        if not county or not water:
            warnings.append(f"Skipped shoreline site missing county/water: {clip(attributes, 300)}")
            continue
        lon, lat = point_coordinates(feature, attributes)
        rows.append({
            "water_name": water,
            "county": county,
            "water_type": water_type(water),
            "latitude": lat,
            "longitude": lon,
            "metadata_source": "wdfw_shore_fishing_sites_layer",
            "water_source_url": LAYERS["shore_fishing"],
            "access": access_record(
                water_name=water,
                county=county,
                access_name=f"{water} shoreline fishing access",
                source_url=LAYERS["shore_fishing"],
                method="official_wdfw_shore_fishing_site",
                evidence="WDFW's official Shore Fishing Sites layer identifies pedestrian shoreline access for recreational fishing.",
                details=clean(attr(attributes, "Description")),
                lon=lon,
                lat=lat,
                amenities={"shore_fishing": True},
            ),
        })
    audit["usable_records"] = len(rows)
    audit["skipped_records"] = len(warnings)
    return rows, warnings, audit


def collect_public_piers() -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    features, audit = arcgis_features(LAYERS["public_piers"])
    for feature in features:
        attributes = feature.get("attributes") or {}
        county = canonical_county(attr(attributes, "CountyFIPSName", "CountyName"))
        pier = clean(attr(attributes, "PierName"))
        if not county or not pier:
            warnings.append(f"Skipped public pier missing county/name: {clip(attributes, 300)}")
            continue
        lon, lat = point_coordinates(feature, attributes)
        website = clean(attr(attributes, "WebsiteURL")) or LAYERS["public_piers"]
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
                source_url=website,
                method="official_wdfw_public_fishing_pier",
                evidence="WDFW's official Public Fishing Pier layer identifies a pier or overwater structure open to public pedestrian or fishing access.",
                lon=lon,
                lat=lat,
                amenities={"fishing_pier": True, "shore_fishing": True},
            ),
        })
    audit["usable_records"] = len(rows)
    audit["skipped_records"] = len(warnings)
    return rows, warnings, audit


def collect_lowland_access() -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    features, audit = arcgis_features(LAYERS["lowland_lakes"])
    for feature in features:
        attributes = feature.get("attributes") or {}
        county = canonical_county(attr(attributes, "CountyName"))
        water = clean(attr(attributes, "LakeName"))
        shore = truthy(attr(attributes, "ShorelineAccess"))
        ramp = truthy(attr(attributes, "BoatRampAvailable"))
        if not county or not water or not (shore or ramp):
            continue
        lon, lat = point_coordinates(feature, attributes)
        website = clean(attr(attributes, "WebsiteURL")) or OFFICIAL_URLS["lowland_lakes_page"]
        listed = []
        if shore:
            listed.append("shoreline access")
        if ramp:
            listed.append("boat ramp")
        details = (
            f"WDFW lists {', '.join(listed)}. "
            f"Lake management: {clean(attr(attributes, 'PublicManagementType')) or 'not specified'}. "
            f"Surface acres: {clean(attr(attributes, 'SurfaceAcres')) or 'not specified'}."
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
                source_url=website,
                method="official_wdfw_lowland_lake_access_flag",
                evidence="WDFW's official Lowland Lakes layer explicitly marks shoreline access and/or a boat ramp as available.",
                details=details,
                lon=lon,
                lat=lat,
                amenities={"shore_fishing": shore, "boat_ramp": ramp},
            ),
        })
    audit["usable_records"] = len(rows)
    audit["skipped_records"] = len(warnings)
    return rows, warnings, audit


def collect_stocking() -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    warnings: list[str] = []
    reports: list[dict[str, Any]] = []
    year_floor = datetime.now(timezone.utc).year - 1
    page_size = 5000
    offset = 0
    total_raw = 0
    select_fields = ",".join([
        "facility", "release_year", "release_start_date", "release_end_date",
        "release_location", "county", "species_type", "species", "number_released",
        "number_of_fish_per_pound", "total_pounds", "lifestage",
    ])
    while True:
        params = {
            "$select": select_fields,
            "$where": f"release_year >= {year_floor}",
            "$order": "release_start_date DESC",
            "$limit": page_size,
            "$offset": offset,
        }
        payload = request_json(f"{OFFICIAL_URLS['stocking_dataset']}?{urlencode(params)}")
        if not isinstance(payload, list):
            raise RuntimeError("WDFW Fish Plants endpoint did not return a JSON list")
        total_raw += len(payload)
        for row in payload:
            if not isinstance(row, dict):
                continue
            county = canonical_county(row.get("county"))
            water = clean(row.get("release_location"))
            report_date = parse_date(row.get("release_start_date") or row.get("release_end_date"))
            if not county or not water:
                continue
            species = clean(row.get("species") or row.get("species_type"))
            quantity = clean(row.get("number_released"))
            facility = clean(row.get("facility"))
            bits = []
            if quantity:
                bits.append(f"{quantity} fish")
            if species:
                bits.append(species)
            if facility:
                bits.append(f"from {facility}")
            summary = "Stocking record: " + (", ".join(bits) if bits else "official WDFW fish plant")
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
        if len(payload) < page_size:
            break
        offset += page_size
        if offset > 100000:
            raise RuntimeError("WDFW Fish Plants pagination exceeded the expected recent-record range")
    unique = {row["report_id"]: row for row in reports}
    output = sorted(unique.values(), key=lambda row: (row.get("report_date", ""), row.get("water_name", "")), reverse=True)
    return output, warnings, {
        "dataset": OFFICIAL_URLS["stocking_dataset"],
        "year_floor": year_floor,
        "downloaded_rows": total_raw,
        "usable_reports": len(output),
        "complete": True,
    }


def merge_access_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
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
            base["longitude"] = row.get("longitude")
            base["latitude"] = row.get("latitude")
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
        points = {
            clean(point.get("access_id")): point
            for point in base["access_points"]
            if clean(point.get("access_id"))
        }
        base["access_points"] = sorted(points.values(), key=lambda item: clean(item.get("access_point_name")))
        base["access_point_count"] = len(base["access_points"])
        base["public_access_verification"] = "; ".join(sorted({
            clean(point.get("verification_method"))
            for point in base["access_points"]
            if clean(point.get("verification_method"))
        }))
        waters.append(base)
    return sorted(waters, key=lambda row: (row["county_number"], row["water_name"].lower()))


def attach_reports(waters: list[dict[str, Any]], reports: list[dict[str, Any]]) -> None:
    by_county_name: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        key = (canonical_county(report.get("county")), norm(report.get("water_name")))
        if all(key):
            by_county_name[key].append(report)
    for water in waters:
        matches = by_county_name.get((water["county"], norm(water["water_name"])), [])
        matches.sort(key=lambda item: item.get("report_date", ""), reverse=True)
        water["report_count"] = len(matches)
        water["reports"] = matches[:10]
        water["latest_report"] = matches[0] if matches else None
        water["report_status"] = matches[0].get("freshness", "date_unknown") if matches else "none"
        species = sorted({clean(item.get("species")) for item in matches if clean(item.get("species"))})
        water["species"] = ", ".join(species)


def build_database(waters: list[dict[str, Any]], reports: list[dict[str, Any]], audits: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    attach_reports(waters, reports)
    county_rows = []
    for county in COUNTIES:
        county_waters = [water for water in waters if water["county"] == county]
        county_reports = [report for report in reports if report["county"] == county]
        county_rows.append({
            "county_number": COUNTY_NUMBER[county],
            "county": county,
            "public_water_count": len(county_waters),
            "verified_access_point_count": sum(water["access_point_count"] for water in county_waters),
            "report_count": len(county_reports),
            "waters": county_waters,
        })
    return {
        "metadata": {
            "state": STATE,
            "state_abbr": STATE_ABBR,
            "generated_at": now_iso(),
            "public_access_only": True,
            "access_scope": "named official facility or site only",
            "regulations_url": OFFICIAL_URLS["regulations"],
            "builder_version": "2.0",
            "source_audits": audits,
            "warning_count": len(warnings),
        },
        "county_count": len(COUNTIES),
        "public_water_count": len(waters),
        "verified_access_point_count": sum(water["access_point_count"] for water in waters),
        "report_count": len(reports),
        "counties": county_rows,
        "flat_waters": waters,
        "flat_reports": reports,
    }


def validate_database(db: dict[str, Any], audits: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if db.get("county_count") != 39:
        errors.append("county_count is not 39")
    if [row.get("county") for row in db.get("counties", [])] != COUNTIES:
        errors.append("county order or membership is incorrect")
    if db.get("metadata", {}).get("public_access_only") is not True:
        errors.append("public_access_only metadata is not true")

    required_audit = audits.get("water_access") or {}
    if required_audit.get("complete") is not True:
        errors.append("required WDFW managed-access layer was not downloaded completely")
    if int(required_audit.get("usable_records") or 0) < MIN_REQUIRED_ACCESS_RECORDS:
        errors.append(
            f"required managed-access layer produced fewer than {MIN_REQUIRED_ACCESS_RECORDS} usable records"
        )

    unique_ids: set[str] = set()
    methods: set[str] = set()
    for water in db.get("flat_waters", []):
        if water.get("publication_status") != "published_verified_public_access":
            errors.append(f"{water.get('water_name')}: invalid publication status")
        points = water.get("access_points") or []
        if not points:
            errors.append(f"{water.get('water_name')}: no verified access point")
        for point in points:
            access_id = clean(point.get("access_id"))
            if not access_id:
                errors.append(f"{water.get('water_name')}: missing access ID")
            elif access_id in unique_ids:
                errors.append(f"duplicate access ID: {access_id}")
            else:
                unique_ids.add(access_id)
            if point.get("public_access_status") != "verified_public":
                errors.append(f"{water.get('water_name')}: access point not verified_public")
            if point.get("entire_shoreline_public") is not False:
                errors.append(f"{water.get('water_name')}: unsafe entire-shoreline claim")
            if not clean(point.get("access_point_name")):
                errors.append(f"{water.get('water_name')}: missing access point name")
            if not clean(point.get("official_source_url")).startswith("https://"):
                errors.append(f"{water.get('water_name')}: invalid official source URL")
            if not clean(point.get("verification_evidence")):
                errors.append(f"{water.get('water_name')}: missing verification evidence")
            method = clean(point.get("verification_method"))
            if method:
                methods.add(method)

    if len(unique_ids) != db.get("verified_access_point_count"):
        errors.append("verified access point count does not equal unique access IDs")
    populated = sum(1 for row in db.get("counties", []) if row.get("public_water_count", 0) > 0)
    if populated < MIN_POPULATED_COUNTIES:
        errors.append(f"fewer than {MIN_POPULATED_COUNTIES} counties contain verified access records")
    if errors:
        raise RuntimeError("Washington strict validation failed: " + "; ".join(errors[:25]))
    return {
        "passed": True,
        "strict_public_access": True,
        "county_count": 39,
        "public_water_count": db["public_water_count"],
        "verified_access_point_count": db["verified_access_point_count"],
        "report_count": db["report_count"],
        "populated_counties": populated,
        "access_verification_methods": sorted(methods),
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def write_js(path: Path, variable: str, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "/* Automatically generated data. Do not hand-edit. */\n"
        f"window.{variable} = {json.dumps(value, separators=(',', ':'), ensure_ascii=False)};\n",
        encoding="utf-8",
    )


def page_html() -> str:
    options = "".join(
        f'<option value="{html.escape(county)}">#{index + 1} {html.escape(county)} County</option>'
        for index, county in enumerate(COUNTIES)
    )
    template = r'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta name="theme-color" content="#1F4D3A"/>
<meta name="description" content="Search official WDFW public fishing access sites, shoreline fishing locations, public piers, lowland-lake access and recent fish plants across all 39 Washington counties."/>
<title>Washington Fishing Reports & Public Access | Fish Finder Outdoors</title>
<link rel="icon" href="ffo-logo-main.png" type="image/png"/><link rel="apple-touch-icon" href="ffo-logo-main.png"/>
<link rel="manifest" href="manifest.json"/><link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Bitter:wght@600;700;800&family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="brand-shell.css"/>
<style>
:root{--green:#1f4d3a;--paper:#f4f1e7;--card:#fffdf8;--line:#d8d3c7;--ink:#173029;--muted:#64716c;--gold:#c79b3b;--warn:#7a5d1f}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#e9f0ea,#f4f1e7 320px);color:var(--ink);font-family:Inter,Arial,sans-serif}.wrap{width:min(1180px,calc(100% - 28px));margin:auto}.hero{padding:38px 0 20px}.hero-grid{display:grid;grid-template-columns:1.25fr .75fr;gap:26px;align-items:center}.kicker{display:inline-flex;padding:7px 11px;border-radius:999px;background:#e2eee7;color:var(--green);font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}.hero h1{font-family:Bitter,Georgia,serif;font-size:clamp(36px,6vw,64px);line-height:1.02;margin:16px 0 12px}.hero p{font-size:18px;color:var(--muted);max-width:800px}.hero-logo{width:min(300px,100%);justify-self:end}.panel{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;margin:18px 0;box-shadow:0 10px 30px rgba(31,77,58,.07)}.controls{display:grid;grid-template-columns:1fr 1.4fr repeat(3,auto);gap:10px;align-items:end}.field label{display:block;font-size:12px;font-weight:900;margin:0 0 5px}.field select,.field input{width:100%;padding:12px 13px;border:1px solid #bfc7c1;border-radius:12px;background:white;font:inherit}.check{display:flex;align-items:center;gap:7px;padding:11px 10px;background:#eef4f0;border-radius:12px;font-size:12px;font-weight:800;white-space:nowrap}.check input{width:18px;height:18px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}button{border:0;border-radius:12px;padding:11px 14px;font:inherit;font-weight:850;cursor:pointer}.primary{background:var(--green);color:white}.secondary{background:#e3ece7;color:var(--green)}.status{padding:12px 14px;border-radius:12px;background:#edf4f0;color:var(--green);font-weight:750;margin-top:13px}.summary{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.metric{background:white;border:1px solid var(--line);border-radius:14px;padding:13px}.metric span{font-size:12px;color:var(--muted);font-weight:700}.metric b{display:block;font-size:25px;margin-top:4px}.water-list{display:grid;gap:13px}.water-card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px}.water-card h2{font-family:Bitter,Georgia,serif;margin:0;font-size:25px}.chips,.amenities{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0}.chip,.amenity{display:inline-flex;padding:5px 8px;border-radius:999px;background:#e8f0eb;border:1px solid #c9dbd1;font-size:11px;font-weight:850}.details{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:13px}.box{border:1px solid var(--line);border-radius:14px;padding:14px;background:white}.box h3{font-size:15px;margin:0 0 9px}.box p{margin:7px 0;color:#3f504a}.access{border-top:1px solid var(--line);padding-top:10px;margin-top:10px}.link{display:inline-flex;margin-top:8px;font-weight:850}.muted{color:var(--muted);font-size:13px}.warning{background:#fff5d9;color:var(--warn);line-height:1.55}.load-more{display:block;margin:18px auto}.hidden{display:none!important}.top-links{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}.top-links a{display:inline-flex;padding:10px 12px;border-radius:12px;background:white;border:1px solid var(--line);font-weight:800;text-decoration:none}@media(max-width:950px){.controls{grid-template-columns:1fr 1fr}.hero-grid{grid-template-columns:1fr}.hero-logo{justify-self:start;max-width:220px}.details{grid-template-columns:1fr}}@media(max-width:600px){.controls,.summary{grid-template-columns:1fr}.panel{padding:15px}}
</style></head><body>
<header class="ffo-site-header"><div class="ffo-header-inner"><a class="ffo-logo-link" href="https://fishfinderoutdoors.com"><img src="ffo-logo-main.png" alt="Fish Finder Outdoors logo"/><span class="ffo-wordmark"><strong>Fish Finder</strong><span>Outdoors</span></span></a><button class="ffo-menu-button" aria-label="Open menu" aria-expanded="false" type="button">☰</button><nav class="ffo-nav" aria-label="Fish Finder Outdoors"><a href="https://fishfinderoutdoors.com">Home</a><a href="index.html">Fishing Reports</a><a href="idaho-county-reports.html">Idaho</a><a href="montana-county-reports.html">Montana</a><a href="utah-county-reports.html">Utah</a><a href="colorado-county-reports.html">Colorado</a><a href="wyoming-county-reports.html">Wyoming</a><a href="nevada-county-reports.html">Nevada</a><a class="active" href="washington-county-reports.html">Washington</a><a href="submit-report.html">Submit Report</a></nav></div></header>
<div class="ffo-beta-bar">PUBLIC ACCESS ONLY • 39 WASHINGTON COUNTIES • OFFICIAL WDFW SOURCES • <button class="ffo-install-button" data-install-ffo-app hidden type="button">Install App</button></div>
<main><section class="hero"><div class="wrap hero-grid"><div><span class="kicker">Washington statewide directory</span><h1>Verified public fishing access, county by county.</h1><p>Search verified WDFW public fishing access and recent official information. Use the official source link on every result to confirm current conditions before traveling.</p><div class="top-links"><a href="index.html">← Main report generator</a><a href="submit-report.html">Submit a fishing report</a><a href="report-water.html">Report incorrect access</a></div></div><img class="hero-logo" src="ffo-logo-main.png" alt="Fish Finder Outdoors"/></div></section>
<div class="wrap"><section class="panel"><div class="controls"><div class="field"><label for="countySelect">County</label><select id="countySelect"><option value="">All 39 counties</option>__COUNTY_OPTIONS__</select></div><div class="field"><label for="waterSearch">Water or access keyword</label><input id="waterSearch" placeholder="Lake, river, pier, ramp…"/></div><label class="check"><input id="boatRamp" type="checkbox"/> Boat ramp</label><label class="check"><input id="shoreFishing" type="checkbox"/> Shore fishing</label><label class="check"><input id="adaAccess" type="checkbox"/> ADA feature</label></div><div class="actions"><button class="primary" id="searchButton" type="button">Search Washington</button><button class="secondary" id="clearButton" type="button">Clear filters</button></div><div class="status" id="status">Loading the Washington public-access database…</div></section>
<section class="panel warning"><strong>Important:</strong> Official data verifies only the named access facility or site—not every shoreline, road, or nearby parcel. Check current WDFW regulations, emergency rules, closures, tribal rules, fees, and posted signs before traveling.</section><section class="panel"><div class="summary" id="summary"></div></section><section class="water-list" id="waterList"></section><button class="secondary load-more hidden" id="loadMore" type="button">Show more waters</button></div></main>
<footer class="ffo-site-footer"><div class="ffo-footer-grid"><div><a class="ffo-footer-brand" href="https://fishfinderoutdoors.com"><img src="ffo-logo-main.png" alt="Fish Finder Outdoors logo"/><span><strong>Fish Finder Outdoors</strong><br/><span style="color:#a9bbb3">Beginner friendly. Washington ready.</span></span></a></div><div><div class="ffo-footer-title">Reports</div><div class="ffo-footer-links"><a href="index.html">Main Report Generator</a><a href="washington-county-reports.html">Washington County Reports</a><a href="submit-report.html">Submit a Report</a><a href="official-sources.html">Official Sources</a></div></div></div><div class="ffo-footer-fine"><span>© 2026 Fish Finder Outdoors. Powered by Mountain Dog Enterprises.</span><span>Verify current regulations and access before fishing.</span></div></footer>
<script src="site_config.js"></script><script src="data/washington_fishing_report_database.js"></script>
<script>
(function(){"use strict";const db=window.WASHINGTON_FISHING_REPORT_DATABASE||{flat_waters:[],metadata:{}};const $=id=>document.getElementById(id);const county=$("countySelect"),query=$("waterSearch"),ramp=$("boatRamp"),shore=$("shoreFishing"),ada=$("adaAccess"),status=$("status"),summary=$("summary"),list=$("waterList"),more=$("loadMore");let filtered=[],shown=0;const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));const label=v=>String(v||"").replace(/_/g," ").replace(/\b\w/g,c=>c.toUpperCase());function hasAda(p){const a=p.amenities||{};return a.ada_parking===true||a.ada_restroom===true||a.ada_dock===true||a.ada_boat_launch===true||a.ada_fishing===true}function matches(w){if(county.value&&w.county!==county.value)return false;const q=query.value.trim().toLowerCase();if(q&&!JSON.stringify([w.water_name,w.water_type,w.county,w.species,w.access_points]).toLowerCase().includes(q))return false;const points=w.access_points||[];if(ramp.checked&&!points.some(p=>p.amenities?.boat_ramp===true))return false;if(shore.checked&&!points.some(p=>p.amenities?.shore_fishing===true))return false;if(ada.checked&&!points.some(hasAda))return false;return true}function pointCard(p){const a=p.amenities||{};const features=Object.entries(a).filter(([,v])=>v===true||typeof v==="string"&&v).map(([k,v])=>`<span class="amenity">${esc(v===true?label(k):`${label(k)}: ${v}`)}</span>`).join("");const map=p.directions_url?`<a class="link" href="${esc(p.directions_url)}" target="_blank" rel="noopener">Map this access point</a>`:"";return `<div class="access"><strong>${esc(p.access_point_name)}</strong>${p.open_dates?`<p><b>Open dates:</b> ${esc(p.open_dates)}</p>`:""}${p.access_details?`<p>${esc(p.access_details)}</p>`:""}<div class="amenities">${features}</div>${map}<br/><a class="link" href="${esc(p.official_source_url)}" target="_blank" rel="noopener">Official access source</a></div>`}function card(w){const r=w.latest_report;const report=r?`<strong>${esc(r.title)}</strong><p>${esc(r.summary)}</p><div class="muted">${esc(r.report_date||"Date not listed")}</div><a class="link" href="${esc(r.source_url)}" target="_blank" rel="noopener">Official stocking source</a>`:`<div class="muted">No recent WDFW fish-plant record matched exactly to this water.</div>`;return `<article class="water-card"><h2>${esc(w.water_name)}</h2><div class="chips"><span class="chip">#${w.county_number} ${esc(w.county)} County</span><span class="chip">${esc(label(w.water_type))}</span><span class="chip">${w.access_point_count} access point(s)</span></div><div class="details"><div class="box"><h3>Recent official information</h3>${report}</div><div class="box"><h3>Verified access points</h3>${(w.access_points||[]).map(pointCard).join("")}</div></div></article>`}function renderSummary(){const access=filtered.reduce((n,w)=>n+(w.access_point_count||0),0),reports=filtered.filter(w=>w.report_count>0).length,ramps=filtered.filter(w=>(w.access_points||[]).some(p=>p.amenities?.boat_ramp===true)).length,shoreCount=filtered.filter(w=>(w.access_points||[]).some(p=>p.amenities?.shore_fishing===true)).length;summary.innerHTML=[["Waters / access areas",filtered.length],["Access points",access],["With reports",reports],["With boat ramps",ramps],["Shore fishing",shoreCount]].map(([k,v])=>`<div class="metric"><span>${k}</span><b>${Number(v).toLocaleString()}</b></div>`).join("")}function renderMore(){const next=filtered.slice(shown,shown+25);list.insertAdjacentHTML("beforeend",next.map(card).join(""));shown+=next.length;more.classList.toggle("hidden",shown>=filtered.length)}function run(){filtered=(db.flat_waters||[]).filter(matches);shown=0;list.innerHTML="";renderSummary();renderMore();status.textContent=`Found ${filtered.length.toLocaleString()} verified Washington public fishing access record${filtered.length===1?"":"s"}${county.value?` in ${county.value} County`:" statewide"}. Database updated ${db.metadata.generated_at?new Date(db.metadata.generated_at).toLocaleString():"date unavailable"}.`}function clear(){county.value="";query.value="";ramp.checked=false;shore.checked=false;ada.checked=false;run()}$("searchButton").addEventListener("click",run);$("clearButton").addEventListener("click",clear);county.addEventListener("change",run);query.addEventListener("keydown",e=>{if(e.key==="Enter")run()});ramp.addEventListener("change",run);shore.addEventListener("change",run);ada.addEventListener("change",run);more.addEventListener("click",renderMore);run()})();
</script><script src="brand-shell.js"></script><script src="pwa.js"></script></body></html>'''
    return template.replace("__COUNTY_OPTIONS__", options)


def patch_brand_shell(root: Path) -> None:
    path = root / "brand-shell.js"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    entry = "['washington-county-reports.html','Washington County Reports']"
    changed = False
    if entry not in text:
        match = re.search(r"(const\s+stateLinks\s*=\s*\[)(.*?)(\];)", text, flags=re.S)
        if match:
            body = match.group(2).rstrip()
            if body and not body.endswith(","):
                body += ","
            body += entry
            text = text[:match.start(2)] + body + text[match.end(2):]
            changed = True
    if changed:
        path.write_text(text, encoding="utf-8")


def patch_service_worker(root: Path) -> None:
    path = root / "service-worker.js"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    original = text

    page = '"./washington-county-reports.html"'
    if page not in text:
        marker = '"./wyoming-county-reports.html"'
        if marker in text:
            text = text.replace(marker, marker + ",\n  " + page, 1)

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
        marker = '"wyoming_fishing_report_database.js"'
        if marker in text:
            text = text.replace(marker, marker + ",\n  " + token, 1)

    if text != original:
        version = re.search(r"ffo-reports-pwa-v(\d+)", text)
        if version:
            text = text.replace(
                version.group(0),
                f"ffo-reports-pwa-v{int(version.group(1)) + 1}",
                1,
            )
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
        f"\n  <url>\n"
        f"    <loc>{host}/washington-county-reports.html</loc>\n"
        f"    <lastmod>{datetime.now(timezone.utc).date().isoformat()}</lastmod>\n"
        f"    <changefreq>daily</changefreq>\n"
        f"    <priority>0.9</priority>\n"
        f"  </url>\n"
    )
    text = text.replace("</urlset>", block + "</urlset>")
    path.write_text(text, encoding="utf-8")


def read_state_databases(root: Path) -> list[dict[str, Any]]:
    paths = list(root.glob("data/*_fishing_report_database.json"))
    paths += list(root.glob("*_fishing_report_database.json"))
    databases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(paths):
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


def _load_existing_js_object(path: Path, variable: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    match = re.search(re.escape(variable) + r"\s*=\s*(\{.*\})\s*;\s*$", text, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def rebuild_shared_feeds(root: Path) -> None:
    """Replace only Washington in shared feeds; preserve every other state verbatim."""
    db_path = root / "data/washington_fishing_report_database.json"
    if not db_path.exists():
        return
    db = json.loads(db_path.read_text(encoding="utf-8-sig"))
    metadata = db.get("metadata") or {}
    generated_at = clean(metadata.get("generated_at")) or now_iso()
    washington_row = {
        "state": STATE,
        "report_count": int(db.get("report_count", 0) or 0),
        "public_water_count": int(db.get("public_water_count", 0) or 0),
        "county_count": int(db.get("county_count", 0) or 0),
        "generated_at": generated_at,
    }

    recent_path = root / "recent_fishing_reports.js"
    recent = _load_existing_js_object(recent_path, "window.FFO_RECENT_REPORTS")
    state_rows = [row for row in recent.get("states", []) if clean(row.get("state")) != STATE]
    state_rows.append(washington_row)
    state_rows.sort(key=lambda row: clean(row.get("state")))
    reports = [row for row in recent.get("reports", []) if clean(row.get("state")) != STATE]
    for report in db.get("flat_reports") or []:
        item = dict(report)
        item["state"] = STATE
        reports.append(item)
    reports.sort(key=lambda row: clean(row.get("report_date")), reverse=True)
    updated = max(clean(recent.get("updated_at")), generated_at)
    recent.update({
        "version": f"{updated}-multi-state",
        "updated_at": updated,
        "coverage_note": "Automatically generated from every installed state county-by-county fishing database.",
        "states": state_rows,
        "reports": reports,
    })
    write_js(recent_path, "FFO_RECENT_REPORTS", recent)

    status_path = root / "update_status.js"
    status = _load_existing_js_object(status_path, "window.FFO_UPDATE_STATUS")
    status_rows = [row for row in status.get("states", []) if clean(row.get("state")) != STATE]
    status_rows.append(washington_row)
    status_rows.sort(key=lambda row: clean(row.get("state")))
    status.update({
        "last_run": max(clean(status.get("last_run")), generated_at),
        "mode": "multi-state-database",
        "state_count": len(status_rows),
        "states": status_rows,
        "reports_total": len(reports),
        "public_water_count": sum(int(row.get("public_water_count", 0) or 0) for row in status_rows),
        "county_count": sum(int(row.get("county_count", 0) or 0) for row in status_rows),
        "changed_reports": len(reports),
    })
    write_js(status_path, "FFO_UPDATE_STATUS", status)

def write_outputs(root: Path, output_dir: Path, db: dict[str, Any], audit: dict[str, Any], status: dict[str, Any]) -> None:
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
    write_json(output_dir / "washington_source_audit.json", audit)
    write_json(output_dir / "washington_project_status.json", status)
    write_json(root / "config/washington_counties.json", {
        "state": STATE,
        "county_count": len(COUNTIES),
        "counties": [{"county_number": index + 1, "county": county} for index, county in enumerate(COUNTIES)],
    })
    with (output_dir / "washington_counties.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["county_number", "county"])
        writer.writerows((index + 1, county) for index, county in enumerate(COUNTIES))
    with (output_dir / "washington_fishing_report_database.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["report_id", "report_date", "freshness", "county", "water_name", "source_type", "source_name", "official", "title", "summary", "species", "techniques", "source_url"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for report in db["flat_reports"]:
            writer.writerow({field: report.get(field, "") for field in fields})
    (root / "washington-county-reports.html").write_text(page_html(), encoding="utf-8")
    patch_brand_shell(root)
    patch_service_worker(root)
    patch_sitemap(root)
    rebuild_shared_feeds(root)


def try_optional(name: str, collector: Callable[[], tuple[list[dict[str, Any]], list[str], dict[str, Any]]], warnings: list[str], audits: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        rows, source_warnings, audit = collector()
        warnings.extend(source_warnings)
        audits[name] = audit
        return rows
    except RuntimeError as exc:
        warnings.append(f"Optional source {name} unavailable: {exc}")
        audits[name] = {"complete": False, "optional": True, "error": str(exc)}
        return []


def build(root: Path, output_dir: Path) -> dict[str, Any]:
    warnings: list[str] = []
    audits: dict[str, Any] = {}
    managed, managed_warnings, managed_audit = collect_managed_access()
    warnings.extend(managed_warnings)
    audits["water_access"] = managed_audit
    access_rows = list(managed)
    access_rows.extend(try_optional("shore_fishing", collect_shore_sites, warnings, audits))
    access_rows.extend(try_optional("public_piers", collect_public_piers, warnings, audits))
    access_rows.extend(try_optional("lowland_lakes", collect_lowland_access, warnings, audits))
    try:
        reports, report_warnings, stocking_audit = collect_stocking()
        warnings.extend(report_warnings)
        audits["fish_plants"] = stocking_audit
    except RuntimeError as exc:
        reports = []
        warnings.append(f"Optional source fish_plants unavailable: {exc}")
        audits["fish_plants"] = {"complete": False, "optional": True, "error": str(exc)}
    waters = merge_access_rows(access_rows)
    db = build_database(waters, reports, audits, warnings)
    validation = validate_database(db, audits)
    status = {
        "state": STATE,
        "generated_at": db["metadata"]["generated_at"],
        "deployment_status": "validated_complete_ready_to_commit",
        "validation": validation,
        "warnings": warnings,
        "optional_source_failures": [name for name, item in audits.items() if item.get("optional") and not item.get("complete")],
    }
    write_outputs(root, output_dir, db, {"sources": audits, "warnings": warnings}, status)
    return status


def self_test() -> None:
    assert len(COUNTIES) == 39
    assert COUNTIES == sorted(COUNTIES)
    assert canonical_county("Pend Oreille County") == "Pend Oreille"
    assert canonical_county("GraysHarbor") == "Grays Harbor"
    assert truthy("Yes") and truthy(1) and not truthy(0)
    assert valid_lon_lat(-122.3, 47.5)
    assert not valid_lon_lat(-110, 47.5)
    assert norm("The Blue Lake") == "blue"
    fixture_rows = [
        {
            "water_name": "Test Lake",
            "county": "King",
            "water_type": "lake",
            "latitude": 47.5,
            "longitude": -122.3,
            "metadata_source": "fixture",
            "water_source_url": "https://example.invalid/source",
            "access": access_record(
                water_name="Test Lake", county="King", access_name="Test Ramp",
                source_url="https://example.invalid/access", method="fixture_method",
                evidence="Fixture official evidence", lon=-122.3, lat=47.5,
                amenities={"boat_ramp": True},
            ),
        }
    ]
    waters = merge_access_rows(fixture_rows)
    reports = [{
        "report_id": "fixture-report", "state": STATE, "county": "King", "counties": ["King"],
        "water_name": "Test Lake", "report_date": "2026-01-01", "freshness": "stale",
        "source_type": "official_fish_plant", "source_name": "Fixture", "official": True,
        "title": "Fixture", "summary": "Fixture", "species": "Rainbow trout", "techniques": "",
        "source_url": "https://example.invalid/report",
    }]
    audits = {"water_access": {"complete": True, "usable_records": MIN_REQUIRED_ACCESS_RECORDS}}
    db = build_database(waters, reports, audits, [])
    # Lower populated-county rule only inside this isolated fixture validation.
    global MIN_POPULATED_COUNTIES
    original = MIN_POPULATED_COUNTIES
    MIN_POPULATED_COUNTIES = 1
    try:
        result = validate_database(db, audits)
        assert result["passed"] is True
        assert db["flat_waters"][0]["latest_report"]["report_id"] == "fixture-report"
    finally:
        MIN_POPULATED_COUNTIES = original
    assert "All 39 counties" in page_html()
    print("Washington builder self-test passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Fish Finder Outdoors repository root")
    parser.add_argument("--output-dir", default="data", help="Output directory, relative to root unless absolute")
    parser.add_argument("--self-test", action="store_true", help="Run offline safety tests only")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    root = Path(args.root).resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    status = build(root, output_dir)
    validation = status["validation"]
    print(f"Washington verified waters: {validation['public_water_count']}")
    print(f"Washington verified access points: {validation['verified_access_point_count']}")
    print(f"Washington fish-plant records: {validation['report_count']}")
    print(f"Washington populated counties: {validation['populated_counties']}")
    if status["optional_source_failures"]:
        print("Optional sources unavailable: " + ", ".join(status["optional_source_failures"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
