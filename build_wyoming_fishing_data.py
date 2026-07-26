#!/usr/bin/env python3
"""Build Wyoming Fish Finder Outdoors county data from official public sources.

This one-file state builder creates and maintains:
- the authoritative 23-county list
- Wyoming Game and Fish Department Fishing Guide waters with confirmed public access
- official Public Access Area and Walk-In Fishing records
- recent Wyoming Game and Fish stocking records
- the Wyoming county search page
- the shared multi-state admin dashboard feed
- navigation, sitemap and PWA cache integration

Public-access policy
--------------------
A water is published only when an official Wyoming Game and Fish source confirms a
public fishing opportunity or an official access facility can be safely matched to
the water. The builder never treats an entire shoreline, river reach, reservation,
park or neighboring parcel as public merely because a water appears in the Fishing
Guide. Blank, malformed or out-of-Wyoming coordinates never create a map link.
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
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

try:
    from bs4 import BeautifulSoup
except ImportError:  # installed by GitHub Actions
    BeautifulSoup = None

STATE = "Wyoming"
STATE_ABBR = "WY"
COUNTIES = [
    "Albany", "Big Horn", "Campbell", "Carbon", "Converse", "Crook",
    "Fremont", "Goshen", "Hot Springs", "Johnson", "Laramie", "Lincoln",
    "Natrona", "Niobrara", "Park", "Platte", "Sheridan", "Sublette",
    "Sweetwater", "Teton", "Uinta", "Washakie", "Weston",
]
COUNTY_NUMBER = {name: i + 1 for i, name in enumerate(COUNTIES)}
COUNTY_LOOKUP = {re.sub(r"[^a-z0-9]+", " ", name.lower()).strip(): name for name in COUNTIES}

USER_AGENT = "FishFinderOutdoors-WyomingBuilder/1.0 (+https://fishfinderoutdoors.com)"
ARCGIS_ORG = "https://services6.arcgis.com/cWzdqIyxbijuhPLw/ArcGIS/rest/services"
SERVICES = {
    "counties": f"{ARCGIS_ORG}/County_boundaries_public/FeatureServer",
    "lakes": f"{ARCGIS_ORG}/Lakes_FishingGuide_PublicView/FeatureServer",
    "streams": f"{ARCGIS_ORG}/Streams_FishingGuide_PublicView/FeatureServer",
    "facilities": f"{ARCGIS_ORG}/Facilities_FishingGuide_PublicView/FeatureServer",
    "paa_locations": f"{ARCGIS_ORG}/PAA_Locations/FeatureServer",
    "paa_access": f"{ARCGIS_ORG}/PAA_Access/FeatureServer",
    "wif_locations": f"{ARCGIS_ORG}/WIF_Locations_PublicService/FeatureServer",
    "wif_access": f"{ARCGIS_ORG}/WIF_Access/FeatureServer",
}
OFFICIAL_URLS = {
    "fishing": "https://wgfd.wyo.gov/fishing-boating",
    "places_to_fish": "https://wgfd.wyo.gov/fishing-boating/places-fish-wyoming",
    "public_access": "https://wgfd.wyo.gov/public-access",
    "paa": "https://wgfd.wyo.gov/public-access/public-access-areas",
    "wif": "https://wgfd.wyo.gov/public-access/walk-in-fishing",
    "stocking": "https://wgfapps.wyo.gov/FishStock/FishStock",
    "regulations": "https://wgfd.wyo.gov/regulations",
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
    text = re.sub(r"^(county\s+of)\s+", "", text, flags=re.I)
    text = re.sub(r"\s+county$", "", text, flags=re.I)
    aliases = {
        "bighorn": "Big Horn",
        "big horn": "Big Horn",
        "hot springs": "Hot Springs",
        "hot spring": "Hot Springs",
    }
    key = norm(text)
    return aliases.get(key) or COUNTY_LOOKUP.get(key, "")


def valid_lon_lat(lon: Any, lat: Any) -> bool:
    try:
        x, y = float(lon), float(lat)
    except (TypeError, ValueError):
        return False
    return -111.2 <= x <= -103.8 and 40.9 <= y <= 45.1


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


def resolve_first_layer(service_url: str) -> str:
    if re.search(r"/(?:FeatureServer|MapServer)/\d+$", service_url):
        return service_url
    payload = request_json(f"{service_url}?f=json")
    layers = payload.get("layers") or []
    if not layers:
        raise RuntimeError(f"No queryable layers found at {service_url}")
    return f"{service_url}/{layers[0]['id']}"


def validate_service_schema(service_url: str, minimum_fields: int = 3) -> dict[str, Any]:
    layer_url = resolve_first_layer(service_url)
    payload = request_json(f"{layer_url}?f=json")
    fields = payload.get("fields") or []
    if len(fields) < minimum_fields:
        raise RuntimeError(
            f"Official ArcGIS layer {layer_url} exposed only {len(fields)} fields"
        )
    return {
        "layer_url": layer_url,
        "field_count": len(fields),
        "geometry_type": clean(payload.get("geometryType")),
        "display_field": clean(payload.get("displayField")),
        "fields": [clean(row.get("name")) for row in fields],
    }


def arcgis_features(service_url: str, chunk_size: int = 50) -> list[dict[str, Any]]:
    """Download an official ArcGIS layer in short, WAF-safe requests."""
    layer_url = resolve_first_layer(service_url)
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
            "outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "json",
        })
        try:
            return request_json(url).get("features") or []
        except RuntimeError as exc:
            message = str(exc)
            if len(object_ids) > 5 and ("403" in message or "414" in message):
                midpoint = len(object_ids) // 2
                return fetch_chunk(object_ids[:midpoint]) + fetch_chunk(object_ids[midpoint:])
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
    value = "|".join(norm(part) for part in parts if clean(part))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


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
        "source_type": source_type,
        "source_name": source_name,
        "official": True,
        "title": clip(title, 220),
        "summary": clip(summary, 700),
        "species": clip(species, 260),
        "techniques": clip(techniques, 260),
        "access_notes": clip(access_notes, 520),
        "source_url": clean(source_url),
    }


def bool_from_text(value: Any, true_terms: tuple[str, ...]) -> bool | None:
    text = clean(value).lower()
    if not text:
        return None
    if text in {"0", "false", "no", "n", "none", "not available"}:
        return False
    if text in {"1", "true", "yes", "y"}:
        return True
    return any(term.lower() in text for term in true_terms)


def normalized_field_map(attrs: dict[str, Any]) -> dict[str, str]:
    return {
        re.sub(r"[^a-z0-9]+", "", clean(key).lower()): key
        for key in attrs
    }


def attr_value(attrs: dict[str, Any], *candidates: str) -> Any:
    fmap = normalized_field_map(attrs)
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", candidate.lower())
        if key in fmap and attrs.get(fmap[key]) not in (None, ""):
            return attrs.get(fmap[key])
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", candidate.lower())
        for normalized, original in fmap.items():
            if key and (key in normalized or normalized in key):
                value = attrs.get(original)
                if value not in (None, ""):
                    return value
    return ""


def attrs_text(attrs: dict[str, Any]) -> str:
    return clean(" ".join(clean(v) for v in attrs.values() if v not in (None, "")))


def feature_point(feature: dict[str, Any]) -> tuple[float | None, float | None]:
    geometry = feature.get("geometry") or {}
    if "x" in geometry and "y" in geometry:
        lon, lat = safe_float(geometry.get("x")), safe_float(geometry.get("y"))
        return (lat, lon) if valid_lon_lat(lon, lat) else (None, None)

    points: list[list[float]] = []
    for key in ("points",):
        points.extend(geometry.get(key) or [])
    for key in ("paths", "rings"):
        for part in geometry.get(key) or []:
            points.extend(part or [])
    usable = [
        pair for pair in points
        if isinstance(pair, (list, tuple)) and len(pair) >= 2
        and valid_lon_lat(pair[0], pair[1])
    ]
    if not usable:
        return None, None
    pair = usable[len(usable) // 2]
    return safe_float(pair[1]), safe_float(pair[0])


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
    records = []
    for feature in arcgis_features(SERVICES["counties"]):
        attrs = feature.get("attributes") or {}
        county = canonical_county(attr_value(attrs, "COUNTY", "COUNTYNAME", "NAME"))
        rings = polygon_rings(feature)
        if county and rings:
            records.append((county, rings))
    if len({county for county, _ in records}) != 23:
        raise RuntimeError(
            f"Official Wyoming county layer resolved {len({c for c, _ in records})} of 23 counties"
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


def clean_species(value: Any) -> str:
    text = clean(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s*[|;/]\s*", ", ", text)
    return clip(re.sub(r"\s+", " ", text).strip(" ,"), 300)


def access_area_base_name(value: Any) -> str:
    text = clean(value)
    text = re.sub(r"\b(public access area|walk[- ]?in fishing area|wif area|paa)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(area|access|details)\s*\d*\b", " ", text, flags=re.I)
    text = re.split(r"\s*[-–—]\s*", text, maxsplit=1)[0]
    return clean(text)


def explicit_public_access(attrs: dict[str, Any]) -> bool:
    """Accept only explicit access/ownership fields, never generic fishing content."""
    relevant = []
    for key, value in attrs.items():
        lowered = clean(key).lower()
        if any(term in lowered for term in (
            "access", "public", "recreation", "open", "ownership",
            "permission", "allowed", "status",
        )):
            relevant.append(clean(value))
    text = " ".join(relevant).lower()
    if not text:
        return False
    if any(term in text for term in (
        "private only", "private property", "no public", "not public",
        "closed", "no access", "prohibited",
    )):
        return False
    return any(term in text for term in (
        "public access", "open to public", "walk-in", "walk in",
        "public", "allowed", "yes",
    ))


def meaningful_name_tokens(value: Any) -> set[str]:
    generic = {
        "public", "access", "area", "walk", "in", "fishing", "site",
        "location", "property", "parcel", "details", "the", "of", "at", "on",
    }
    return {token for token in norm(value).split() if token not in generic and len(token) > 1}


def strong_access_name_match(access_name: Any, water_name: Any) -> bool:
    access_norm, water_norm = norm(access_name), norm(water_name)
    if not access_norm or not water_norm:
        return False
    if access_norm == water_norm:
        return True
    access_tokens = meaningful_name_tokens(access_name)
    water_tokens = meaningful_name_tokens(water_name)
    if len(access_tokens) < 2 or len(water_tokens) < 2:
        return False
    shared = access_tokens & water_tokens
    return len(shared) >= 2 and (
        access_tokens <= water_tokens or water_tokens <= access_tokens
    )


def access_details_from_attrs(attrs: dict[str, Any]) -> str:
    parts = []
    for label, fields in (
        ("Access dates", ("ACCESS_DATES", "OPEN_DATES", "DATES", "SEASON")),
        ("Recreation", ("RECREATION", "ACTIVITIES", "USES")),
        ("Rules", ("RULES", "REGULATIONS", "AREA_RULES")),
        ("Directions", ("DIRECTIONS", "LOCATION", "DESCRIPTION")),
        ("Stream miles", ("STREAM_MILES", "MILES")),
    ):
        value = clean(attr_value(attrs, *fields))
        if value:
            parts.append(f"{label}: {value}.")
    return clip(" ".join(parts), 700)


def source_link(attrs: dict[str, Any], fallback: str) -> str:
    for candidate in (
        "URL", "WEB_URL", "DETAILS_URL", "MAP_URL", "GEOPDF", "LINK", "WEBSITE",
    ):
        value = clean(attr_value(attrs, candidate))
        if value.startswith("http"):
            return value
    return fallback


def facility_point(attrs: dict[str, Any], lat: Any, lon: Any, fallback_url: str) -> dict[str, Any]:
    name = clean(attr_value(attrs, "FACILITY_NAME", "NAME", "FACILITY", "SITE_NAME")) or "WGFD fishing facility"
    all_text = attrs_text(attrs).lower()
    directions = source_link(attrs, "")
    if not directions and valid_lon_lat(lon, lat):
        directions = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    return {
        "access_point_name": name,
        "latitude": lat,
        "longitude": lon,
        "directions_url": directions,
        "amenities": {
            "camping": bool_from_text(all_text, ("camp",)),
            "restroom": bool_from_text(all_text, ("restroom", "toilet", "comfort station")),
            "boat_ramp": bool_from_text(all_text, ("boat ramp", "launch", "ramp")),
            "dock": bool_from_text(all_text, ("dock", "pier", "platform")),
            "ada_fishing": bool_from_text(all_text, ("ada", "accessible", "handicap")),
        },
        "access_flags": {
            "walk_in_fishing": "walk-in" in all_text or "walk in" in all_text,
            "public_access_area": "public access" in all_text,
        },
        "access_details": access_details_from_attrs(attrs),
        "official_source_url": source_link(attrs, fallback_url),
    }


def collect_access_service(
    service_key: str,
    *,
    access_type: str,
    fallback_url: str,
    county_polygons: list[tuple[str, list[list[list[float]]]]],
    require_fishing_text: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for feature in arcgis_features(SERVICES[service_key]):
        attrs = feature.get("attributes") or {}
        blob = attrs_text(attrs)
        if require_fishing_text and "fish" not in blob.lower():
            continue
        name = clean(attr_value(
            attrs, "WATER_NAME", "WATER", "PAA_NAME", "WIF_NAME", "AREA_NAME", "NAME",
        ))
        if not name:
            continue
        lat, lon = feature_point(feature)
        county = canonical_county(attr_value(attrs, "COUNTY", "COUNTYNAME"))
        county = county or county_for_point(lon, lat, county_polygons)
        if not county:
            continue
        species = clean_species(attr_value(
            attrs, "SPECIES", "FISH_SPECIES", "GAME_SPECIES", "COMMON_GAME_SPECIES",
        ))
        details = access_details_from_attrs(attrs)
        official_url = source_link(attrs, fallback_url)
        point = facility_point(attrs, lat, lon, official_url)
        sources.append({
            "county": county,
            "water_name": access_area_base_name(name) or name,
            "alternate_name": name,
            "water_type": water_type(name),
            "latitude": lat,
            "longitude": lon,
            "access_details": details,
            "verification": f"official_wgfd_{access_type}",
            "source_url": official_url,
            "species": species,
            "explicit_public_access": True,
            "access_point": point,
        })
        reports.append(make_report(
            source_type=f"official_{access_type}_reference",
            source_name="Wyoming Game and Fish Department",
            source_url=official_url,
            title=f"Official WGFD access information: {name}",
            summary=details or (
                f"Wyoming Game and Fish identifies {name} as an official "
                f"{access_type.replace('_', ' ')} fishing-access opportunity."
            ),
            water_name=access_area_base_name(name) or name,
            counties=[county],
            species=species,
            access_notes=details,
        ))
    return sources, reports


def collect_facilities(
    county_polygons: list[tuple[str, list[list[list[float]]]]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    sources: list[dict[str, Any]] = []
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for feature in arcgis_features(SERVICES["facilities"]):
        attrs = feature.get("attributes") or {}
        lat, lon = feature_point(feature)
        county = canonical_county(attr_value(attrs, "COUNTY", "COUNTYNAME"))
        county = county or county_for_point(lon, lat, county_polygons)
        water_name = clean(attr_value(
            attrs, "WATER_NAME", "WATERNAME", "WATER", "LAKE_NAME", "STREAM_NAME",
        ))
        water_id = clean(attr_value(attrs, "WATERID", "WATER_ID", "WATER_CODE"))
        if not county or not (water_name or water_id):
            continue
        official_url = source_link(attrs, OFFICIAL_URLS["places_to_fish"])
        point = facility_point(attrs, lat, lon, official_url)
        keys = {norm(water_name), norm(water_id)} - {""}
        for key in keys:
            index[(county, key)].append(point)
        if water_name:
            sources.append({
                "county": county,
                "water_name": water_name,
                "water_type": water_type(water_name),
                "latitude": lat,
                "longitude": lon,
                "access_details": access_details_from_attrs(attrs),
                "verification": "official_wgfd_fishing_facility",
                "source_url": official_url,
                "explicit_public_access": True,
                "access_point": point,
                "water_id": water_id,
            })
    return sources, index


def collect_fishing_guide(
    county_polygons: list[tuple[str, list[list[list[float]]]]],
    facility_index: dict[tuple[str, str], list[dict[str, Any]]],
    access_names_by_county: dict[str, set[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    sources: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    counts = {"guide_lake_features": 0, "guide_stream_features": 0, "guide_public_matches": 0}
    for service_key, kind in (("lakes", "lake"), ("streams", "stream")):
        features = arcgis_features(SERVICES[service_key])
        counts[f"guide_{kind}_features"] = len(features)
        for feature in features:
            attrs = feature.get("attributes") or {}
            name = clean(attr_value(
                attrs, "WATER_NAME", "WATERNAME", "NAME", "GNIS_NAME", "STREAM_NAME", "LAKE_NAME",
            ))
            water_id = clean(attr_value(attrs, "WATERID", "WATER_ID", "WATER_CODE", "WATERCODE"))
            if not name:
                continue
            lat, lon = feature_point(feature)
            county = canonical_county(attr_value(attrs, "COUNTY", "COUNTYNAME"))
            county = county or county_for_point(lon, lat, county_polygons)
            if not county:
                continue
            key_candidates = {norm(name), norm(water_id)} - {""}
            matched_points = []
            for key in key_candidates:
                matched_points.extend(facility_index.get((county, key), []))
            fuzzy_access = any(
                strong_access_name_match(candidate, name)
                for candidate in access_names_by_county.get(county, set())
            )
            confirmed = bool(matched_points) or explicit_public_access(attrs) or fuzzy_access
            if not confirmed:
                continue
            counts["guide_public_matches"] += 1
            species = clean_species(attr_value(
                attrs, "SPECIES", "FISH_SPECIES", "GAME_FISH", "FISH", "SPECIES_LIST",
            ))
            details = access_details_from_attrs(attrs)
            official_url = source_link(attrs, OFFICIAL_URLS["places_to_fish"])
            sources.append({
                "county": county,
                "water_name": name,
                "water_type": water_type(name, kind),
                "latitude": lat,
                "longitude": lon,
                "access_details": details,
                "verification": "official_wgfd_fishing_guide_confirmed_access",
                "source_url": official_url,
                "species": species,
                "explicit_public_access": True,
                "access_points": matched_points,
                "water_id": water_id,
            })
            reports.append(make_report(
                source_type="official_fishing_guide_reference",
                source_name="Wyoming Game and Fish Department",
                source_url=official_url,
                title=f"WGFD Fishing Guide: {name}",
                summary=(
                    f"Wyoming Game and Fish lists {name} in its interactive Fishing Guide "
                    f"and the builder matched an official public-access indicator or facility."
                    + (f" Access information: {details}" if details else "")
                ),
                water_name=name,
                counties=[county],
                species=species,
                access_notes=details,
            ))
    return sources, reports, counts


def discover_stocking_pages() -> list[str]:
    candidates = [
        OFFICIAL_URLS["stocking"],
        "https://wgfapps.wyo.gov/FishStock/FishStock",
    ]
    try:
        page = request_text(OFFICIAL_URLS["fishing"])
        if BeautifulSoup is not None:
            soup = BeautifulSoup(page, "html.parser")
            for anchor in soup.find_all("a", href=True):
                label = clean(anchor.get_text(" ", strip=True)).lower()
                href = urljoin(OFFICIAL_URLS["fishing"], anchor.get("href") or "")
                if "stock" in label or "stock" in href.lower():
                    candidates.insert(0, href)
    except Exception:
        pass
    ordered = []
    for value in candidates:
        if value and value not in ordered:
            ordered.append(value)
    return ordered



def stocking_form_fields(
    form: Any,
    submit_control: Any | None = None,
) -> list[tuple[str, str]]:
    """Reproduce successful controls for one browser-style button click."""
    fields: list[tuple[str, str]] = []

    for node in form.find_all("input"):
        name = clean(node.get("name"))
        if not name or node.has_attr("disabled"):
            continue
        input_type = clean(node.get("type") or "text").lower()
        if input_type in {"file", "reset", "button", "submit", "image"}:
            continue
        if input_type in {"checkbox", "radio"} and not node.has_attr("checked"):
            continue
        fields.append((name, clean(node.get("value"))))

    for select in form.find_all("select"):
        name = clean(select.get("name"))
        if not name or select.has_attr("disabled"):
            continue
        options = select.find_all("option")
        selected = [option for option in options if option.has_attr("selected")]
        chosen = selected or options[:1]
        if select.has_attr("multiple"):
            chosen = selected
        for option in chosen:
            fields.append((
                name,
                clean(option.get("value") or option.get_text(" ", strip=True)),
            ))

    for node in form.find_all("textarea"):
        name = clean(node.get("name"))
        if name and not node.has_attr("disabled"):
            fields.append((name, clean(node.get_text())))

    # A real browser submits only the button that was clicked. The earlier
    # collector submitted both WGFD buttons together, which returned the
    # filter page instead of the report.
    if submit_control is not None:
        name = clean(submit_control.get("name"))
        value = clean(
            submit_control.get("value")
            or submit_control.get_text(" ", strip=True)
            or submit_control.get("aria-label")
            or submit_control.get("title")
        )
        if name:
            fields.append((name, value))
            if clean(submit_control.get("type")).lower() == "image":
                fields.extend([(f"{name}.x", "1"), (f"{name}.y", "1")])

    return fields


def stocking_submit_controls(form: Any) -> list[Any]:
    """Return report/search buttons but never reset, clear or cancel buttons."""
    controls = []
    for node in form.find_all(["input", "button"]):
        node_type = clean(
            node.get("type")
            or ("submit" if node.name == "button" else "text")
        ).lower()
        if node_type not in {"submit", "image"} or node.has_attr("disabled"):
            continue
        label = clean(
            node.get("value")
            or node.get_text(" ", strip=True)
            or node.get("aria-label")
            or node.get("title")
            or node.get("id")
            or node.get("name")
        ).lower()
        if any(term in label for term in ("reset", "clear", "cancel")):
            continue
        controls.append(node)

    def priority(node: Any) -> tuple[int, str]:
        label = clean(
            node.get("value")
            or node.get_text(" ", strip=True)
            or node.get("aria-label")
            or node.get("title")
            or node.get("id")
            or node.get("name")
        ).lower()
        preferred = any(
            term in label
            for term in ("report", "search", "view", "run", "submit", "stock")
        )
        return (0 if preferred else 1, label)

    return sorted(controls, key=priority)


def find_stocking_form(soup: Any) -> Any:
    """Find the form that contains the WGFD stocking-report filters."""
    best = None
    best_score = -1
    for form in soup.find_all("form"):
        text_value = clean(form.get_text(" ", strip=True)).lower()
        controls = " ".join(
            clean(node.get("name") or node.get("id")).lower()
            for node in form.find_all(["input", "select", "button"])
        )
        combined = f"{text_value} {controls}"
        score = sum(
            1 for term in ("stocked from", "species", "county", "water", "year")
            if term in combined
        )
        if score > best_score:
            best, best_score = form, score
    return best if best_score >= 2 else None



def submit_stocking_report_form(base_url: str) -> list[tuple[str, str]]:
    """Follow each legitimate WGFD report button using browser semantics."""
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required")

    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json,text/csv,*/*;q=0.8",
    }

    landing_request = Request(base_url, headers=headers)
    with opener.open(landing_request, timeout=90) as response:
        landing_html = response.read().decode("utf-8", errors="replace")
        landing_url = response.geturl()

    soup = BeautifulSoup(landing_html, "html.parser")
    form = find_stocking_form(soup)
    if form is None:
        raise RuntimeError("The official WGFD stocking application form could not be found")

    default_action = urljoin(
        landing_url,
        clean(form.get("action")) or landing_url,
    )
    default_method = clean(form.get("method") or "get").lower()
    if default_method not in {"get", "post"}:
        default_method = "get"

    controls = stocking_submit_controls(form)
    click_options = controls or [None]
    pages: list[tuple[str, str]] = [(landing_url, landing_html)]
    attempted: set[tuple[str, str, str]] = set()

    for control in click_options:
        action_url = default_action
        method = default_method
        if control is not None:
            action_url = urljoin(
                landing_url,
                clean(control.get("formaction")) or default_action,
            )
            method = clean(control.get("formmethod") or default_method).lower()
            if method not in {"get", "post"}:
                method = default_method

        fields = stocking_form_fields(form, control)
        encoded = urlencode(fields, doseq=True)
        signature = (method, action_url, encoded)
        if signature in attempted:
            continue
        attempted.add(signature)

        submit_headers = dict(headers)
        submit_headers["Referer"] = landing_url

        if method == "post":
            submit_headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = Request(
                action_url,
                data=encoded.encode("utf-8"),
                headers=submit_headers,
                method="POST",
            )
        else:
            separator = "&" if "?" in action_url else "?"
            request = Request(
                action_url + (separator + encoded if encoded else ""),
                headers=submit_headers,
            )

        with opener.open(request, timeout=120) as response:
            payload = response.read()
            content_type = clean(response.headers.get("Content-Type")).lower()
            report_url = response.geturl()

        # The current WGFD report is HTML. Preserve JSON bootstrap payloads by
        # wrapping them in a script tag that the existing parser understands.
        decoded = payload.decode("utf-8", errors="replace")
        if "json" in content_type or decoded.lstrip().startswith(("{", "[")):
            decoded = (
                "<html><body><script type='application/json'>"
                + html.escape(decoded)
                + "</script></body></html>"
            )
        pages.append((report_url, decoded))

    return pages


def parse_stocking_rows(page_html: str, source_url: str) -> list[dict[str, str]]:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required")
    soup = BeautifulSoup(page_html, "html.parser")
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(values: dict[str, Any]) -> None:
        water = clean(values.get("water"))
        county = canonical_county(values.get("county"))
        species = clean_species(values.get("species"))
        report_date = parse_date(values.get("date"))
        number = clean(values.get("number"))
        length = clean(values.get("length"))
        if not water or not report_date:
            return
        key = (norm(water), county, norm(species), report_date)
        if key in seen:
            return
        seen.add(key)
        rows.append({
            "water_name": water,
            "county": county,
            "species": species,
            "report_date": report_date,
            "number": number,
            "length": length,
            "source_url": source_url,
        })

    # Semantic HTML tables.
    for table in soup.find_all("table"):
        header_cells = table.find_all("th")
        headers = [clean(cell.get_text(" ", strip=True)).lower() for cell in header_cells]
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if not cells:
                continue
            values = [clean(cell.get_text(" ", strip=True)) for cell in cells]
            mapping = {}
            for idx, value in enumerate(values):
                header = headers[idx] if idx < len(headers) else ""
                if "water" in header:
                    mapping["water"] = value
                elif "county" in header:
                    mapping["county"] = value
                elif "species" in header or "fish" in header:
                    mapping["species"] = value
                elif "date" in header:
                    mapping["date"] = value
                elif "number" in header or "quantity" in header:
                    mapping["number"] = value
                elif "length" in header or "size" in header:
                    mapping["length"] = value
            if not mapping and len(values) >= 6:
                # WGFD documents this report as date, species, number, length, water, county.
                if parse_date(values[0]) and canonical_county(values[5]):
                    mapping = {
                        "date": values[0],
                        "species": values[1],
                        "number": values[2],
                        "length": values[3],
                        "water": values[4],
                        "county": values[5],
                    }
                elif parse_date(values[-1]) and canonical_county(values[-2]):
                    mapping = {
                        "water": values[0],
                        "species": values[1],
                        "number": values[2],
                        "length": values[3],
                        "county": values[-2],
                        "date": values[-1],
                    }
            elif not mapping and len(values) >= 4:
                date_idx = next((i for i, v in enumerate(values) if parse_date(v)), -1)
                county_idx = next((i for i, v in enumerate(values) if canonical_county(v)), -1)
                if date_idx >= 0:
                    mapping["date"] = values[date_idx]
                if county_idx >= 0:
                    mapping["county"] = values[county_idx]
                remaining = [v for i, v in enumerate(values) if i not in {date_idx, county_idx} and v]
                if remaining:
                    mapping["water"] = remaining[-1]
                if len(remaining) > 1:
                    mapping["species"] = remaining[0]
            add(mapping)

    # Responsive cards with repeated labels.
    for node in soup.find_all(["article", "li", "div"]):
        text = clean(node.get_text(" ", strip=True))
        if len(text) > 1000 or "water" not in text.lower() or "date" not in text.lower():
            continue
        date_match = re.search(
            r"\b(?:20\d{2}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/20\d{2})\b", text
        )
        if not date_match:
            continue
        labels = {}
        for label in ("water", "county", "species", "number", "length", "date"):
            match = re.search(
                rf"\b{label}(?:\s+name|\s+stocked)?\b\s*[:|-]?\s*(.{{1,120}}?)(?=\s+\b(?:water|county|species|number|length|date)(?:\s+name|\s+stocked)?\b|$)",
                text, flags=re.I,
            )
            if match:
                labels[label] = clean(match.group(1))
        labels.setdefault("date", date_match.group(0))
        add(labels)

    # JSON embedded in script tags or API bootstrap payloads.
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            keys = {re.sub(r"[^a-z0-9]+", "", str(k).lower()): k for k in value}
            def pick(*names: str) -> Any:
                for name in names:
                    n = re.sub(r"[^a-z0-9]+", "", name.lower())
                    for normalized, original in keys.items():
                        if n == normalized or n in normalized:
                            if value.get(original) not in (None, ""):
                                return value.get(original)
                return ""
            candidate = {
                "water": pick("watername", "water"),
                "county": pick("county"),
                "species": pick("species", "fishspecies"),
                "date": pick("stockingdate", "stockdate", "date"),
                "number": pick("numberstocked", "quantity", "number"),
                "length": pick("length", "size"),
            }
            if candidate["water"] and candidate["date"]:
                add(candidate)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        raw = clean(raw)
        if not raw or ("water" not in raw.lower() and "stock" not in raw.lower()):
            continue
        for candidate in (raw, re.sub(r"^[^(]*\((.*)\)\s*;?$", r"\1", raw, flags=re.S)):
            try:
                visit(json.loads(candidate))
                break
            except Exception:
                continue

    return rows



def stocking_page_diagnostics(page_html: str, page_url: str) -> str:
    """Return concise structural clues from the live WGFD stocking application."""
    if BeautifulSoup is None:
        return "BeautifulSoup unavailable"

    soup = BeautifulSoup(page_html, "html.parser")
    chunks: list[str] = []
    title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    chunks.append(
        f"PAGE url={page_url} bytes={len(page_html.encode('utf-8', errors='ignore'))} "
        f"title={title!r} forms={len(soup.find_all('form'))} "
        f"tables={len(soup.find_all('table'))}"
    )

    for index, form in enumerate(soup.find_all("form")[:5], start=1):
        chunks.append(
            "FORM "
            + str(index)
            + " "
            + json.dumps({
                "action": clean(form.get("action")),
                "method": clean(form.get("method")),
                "id": clean(form.get("id")),
                "name": clean(form.get("name")),
                "target": clean(form.get("target")),
                "onsubmit": clip(form.get("onsubmit"), 300),
            }, ensure_ascii=False)
        )

        controls = []
        for node in form.find_all(["input", "button"])[:20]:
            controls.append({
                "tag": node.name,
                "type": clean(node.get("type")),
                "id": clean(node.get("id")),
                "name": clean(node.get("name")),
                "value": clip(node.get("value"), 160),
                "text": clip(node.get_text(" ", strip=True), 160),
                "formaction": clean(node.get("formaction")),
                "formmethod": clean(node.get("formmethod")),
                "onclick": clip(node.get("onclick"), 300),
            })
        chunks.append("CONTROLS " + json.dumps(controls, ensure_ascii=False))

        selects = []
        for node in form.find_all("select")[:12]:
            selected = node.find_all("option", selected=True)
            chosen = selected or node.find_all("option")[:1]
            selects.append({
                "id": clean(node.get("id")),
                "name": clean(node.get("name")),
                "selected": [
                    clean(option.get("value") or option.get_text(" ", strip=True))
                    for option in chosen[:3]
                ],
            })
        chunks.append("SELECTS " + json.dumps(selects, ensure_ascii=False))

    for index, table in enumerate(soup.find_all("table")[:8], start=1):
        headers = [
            clean(cell.get_text(" ", strip=True))
            for cell in table.find_all(["th", "td"])[:12]
        ]
        chunks.append(
            f"TABLE {index} rows={len(table.find_all('tr'))} "
            f"headers={headers!r}"
        )

    interesting_links = []
    for node in soup.find_all("a", href=True):
        href = urljoin(page_url, clean(node.get("href")))
        label = clean(node.get_text(" ", strip=True))
        blob = f"{href} {label}".lower()
        if any(term in blob for term in (
            "stock", "report", "export", "download", "csv", "excel", "pdf"
        )):
            interesting_links.append({"text": clip(label, 120), "href": href})
    chunks.append(
        "LINKS " + json.dumps(interesting_links[:20], ensure_ascii=False)
    )

    script_sources = [
        urljoin(page_url, clean(script.get("src")))
        for script in soup.find_all("script", src=True)
    ]
    chunks.append(
        "SCRIPT_SRCS " + json.dumps(script_sources[-20:], ensure_ascii=False)
    )

    script_clues = []
    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        lowered = raw.lower()
        if any(term in lowered for term in (
            "fishstock", "report", "window.open", "formaction",
            "ajax", "$.post", "$.get", "fetch(", "location.href",
            "submit(", "export", "download", ".csv", ".pdf"
        )):
            compact = clean(raw)
            script_clues.append(clip(compact, 900))
    chunks.append(
        "INLINE_SCRIPT_CLUES "
        + json.dumps(script_clues[:12], ensure_ascii=False)
    )

    route_pattern = re.compile(
        r"""(?:"|')([^"']*(?:FishStock|fishstock|Report|report|Export|export|Download|download|\.csv|\.pdf)[^"']*)(?:"|')"""
    )
    routes = []
    for match in route_pattern.finditer(page_html):
        value = clean(html.unescape(match.group(1)))
        if value and value not in routes and len(value) < 500:
            routes.append(value)
    chunks.append("ROUTE_CLUES " + json.dumps(routes[:40], ensure_ascii=False))

    return "\n".join(chunks)



def collect_recent_stocking(
    waters: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int, str]:
    current_year = datetime.now(timezone.utc).year
    page_errors = []
    parsed: list[dict[str, str]] = []
    used_url = ""
    checked_pages: list[str] = []
    for base_url in discover_stocking_pages():
        try:
            if "wgfapps.wyo.gov/fishstock" in base_url.lower():
                pages = submit_stocking_report_form(base_url)
            else:
                pages = [(base_url, request_text(base_url))]
            for url, page in pages:
                candidate = parse_stocking_rows(page, url)
                title = ""
                if BeautifulSoup is not None:
                    parsed_page = BeautifulSoup(page, "html.parser")
                    title = clean(parsed_page.title.get_text(" ", strip=True)) if parsed_page.title else ""
                checked_pages.append(
                    f"{url} bytes={len(page.encode('utf-8', errors='ignore'))} "
                    f"title={title!r} rows={len(candidate)}"
                )
                if len(candidate) > len(parsed):
                    parsed, used_url = candidate, url
        except Exception as exc:
            page_errors.append(f"{base_url}: {exc}")
    if not parsed:
        diagnostic_pages: list[str] = []
        for base_url in discover_stocking_pages():
            if "wgfapps.wyo.gov/fishstock" not in base_url.lower():
                continue
            try:
                for url, page in submit_stocking_report_form(base_url):
                    diagnostic_pages.append(stocking_page_diagnostics(page, url))
            except Exception as exc:
                diagnostic_pages.append(f"DIAGNOSTIC RETRIEVAL FAILED: {exc}")
        raise RuntimeError(
            "WYOMING_STOCKING_DIAGNOSTIC_START\n"
            + "\n---\n".join(diagnostic_pages[-4:])
            + "\nWYOMING_STOCKING_DIAGNOSTIC_END\n"
            + "No stocking records were published. Existing site files remain untouched."
        )

    name_index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (county, key), water in waters.items():
        name_index[key].append((county, water["water_name"]))

    reports: list[dict[str, Any]] = []
    ambiguous = 0
    for row in parsed:
        key = norm(row["water_name"])
        matches = name_index.get(key, [])
        county = canonical_county(row.get("county"))
        if county:
            county_matches = [item for item in matches if item[0] == county]
            if len(county_matches) == 1:
                matches = county_matches
        if len(matches) == 1:
            match_county, canonical_name = matches[0]
            counties = [match_county]
            source_type = "official_recent_stocking"
            note = ""
        else:
            counties = [county] if county else []
            canonical_name = row["water_name"]
            source_type = "official_recent_stocking_unmatched"
            if len(matches) > 1:
                ambiguous += 1
                note = "Multiple Wyoming waters share this name; the record was not guessed onto one water."
            else:
                note = "No exact Fishing Guide water-name match was found."
        detail = []
        if row.get("number"):
            detail.append(f"Number stocked: {row['number']}.")
        if row.get("length"):
            detail.append(f"Reported length: {row['length']}.")
        reports.append(make_report(
            source_type=source_type,
            source_name="Wyoming Game and Fish Department",
            source_url=row["source_url"],
            title=f"Recent WGFD stocking: {canonical_name}",
            summary=(
                f"Wyoming Game and Fish reports stocking {canonical_name} on "
                f"{row['report_date']}."
                + (f" Species: {row['species']}." if row.get("species") else "")
                + (" " + " ".join(detail) if detail else "")
                + (f" {note}" if note else "")
            ),
            report_date=row["report_date"],
            water_name=canonical_name,
            counties=counties,
            species=row.get("species", ""),
            access_notes=note,
        ))
    return reports, len(parsed), ambiguous, used_url


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
            "species": clean_species(source.get("species")),
            "public_access_verification": [],
            "official_access_source_url": source.get("source_url") or OFFICIAL_URLS["places_to_fish"],
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
            "title": "Wyoming Public Fishing Access and Current Fishing Reports",
            "version": "1.0",
            "generated_at": generated_at,
            "public_access_only": True,
            "county_order": "1 Albany through 23 Weston",
            "access_policy": (
                "Records are included only when an official Wyoming Game and Fish "
                "public-access source, Walk-In Fishing agreement, Public Access Area, "
                "or fishing facility confirms an opportunity. A record does not make "
                "every shoreline, streambed or neighboring parcel public. Walk-In Fishing "
                "access is limited to the posted dates, species, boundaries and foot-travel "
                "rules. Stocking records are attached only when matched safely. Anglers "
                "must verify current maps, regulations and posted signs before entering."
            ),
            "sources": [
                {"name": "Wyoming Game and Fish Interactive Fishing Guide", "type": "official", "url": OFFICIAL_URLS["places_to_fish"]},
                {"name": "WGFD Fishing Guide lakes ArcGIS service", "type": "official", "url": SERVICES["lakes"]},
                {"name": "WGFD Fishing Guide streams ArcGIS service", "type": "official", "url": SERVICES["streams"]},
                {"name": "Wyoming Game and Fish Public Access Areas", "type": "official", "url": OFFICIAL_URLS["paa"]},
                {"name": "Wyoming Game and Fish Walk-In Fishing", "type": "official", "url": OFFICIAL_URLS["wif"]},
                {"name": "Wyoming Game and Fish Stocking Report", "type": "official", "url": OFFICIAL_URLS["stocking"]},
                {"name": "Wyoming Fishing Regulations", "type": "official", "url": OFFICIAL_URLS["regulations"]},
            ],
        },
        "county_count": 23,
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
        1: 1, 2: 1, 3: 5, 4: 10, 5: 15, 6: 15,
        7: 10, 8: 5, 9: 8, 10: 8, 11: 3, 12: 1,
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
                    f"{label} has out-of-Wyoming coordinates {lat},{lon}"
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
                        f"{point_name} has out-of-Wyoming coordinates {plat},{plon}"
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
            "Invalid Wyoming coordinate data: "
            + "; ".join(invalid_coordinates[:10])
        )
    if invalid_urls:
        raise RuntimeError(
            "Invalid Wyoming map URLs: " + "; ".join(invalid_urls[:10])
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
            "Required Wyoming source failures: " + " | ".join(failed_sources)
        )

    minimums = {
        "county_polygons": 23,
        "lakes_schema_fields": 3,
        "streams_schema_fields": 3,
        "facilities_schema_fields": 3,
        "paa_locations_schema_fields": 3,
        "wif_locations_schema_fields": 3,
        "guide_lake_features": 100,
        "guide_stream_features": 100,
        "official_access_records": 40,
        "guide_public_matches": 30,
        "recent_stocking_records": stocking_minimum_for_month(),
    }
    shortfalls = []
    for key, minimum in minimums.items():
        actual = int(source_counts.get(key, 0) or 0)
        if actual < minimum:
            shortfalls.append(f"{key}={actual}, expected at least {minimum}")
    if shortfalls:
        raise RuntimeError(
            "Wyoming source-count validation failed: " + "; ".join(shortfalls)
        )

    counties = db.get("counties") or []
    if db.get("county_count") != 23 or len(counties) != 23:
        raise RuntimeError("Wyoming database did not create all 23 county shells")
    if [row.get("county") for row in counties] != COUNTIES:
        raise RuntimeError("Wyoming county order is not Albany through Weston")

    public_water_count = int(db.get("public_water_count", 0) or 0)
    report_count = int(db.get("report_count", 0) or 0)
    if public_water_count < 100:
        raise RuntimeError(
            f"Wyoming build produced only {public_water_count} confirmed public fishing opportunities"
        )
    if report_count < 50:
        raise RuntimeError(
            f"Wyoming build produced only {report_count} official report/reference records"
        )

    populated_counties = sum(
        1 for county in counties
        if int(county.get("public_water_count", 0) or 0) > 0
    )
    if populated_counties < 18:
        raise RuntimeError(
            f"Only {populated_counties} of 23 Wyoming counties contain confirmed access records"
        )

    map_counts = validate_map_data(db)
    page = county_page_html()
    required_page_tokens = (
        "function validCoordinate",
        "function mapPoint",
        "const mapHtml=map?",
        "40.9,45.1",
        "-111.2,-103.8",
    )
    missing_tokens = [token for token in required_page_tokens if token not in page]
    if missing_tokens:
        raise RuntimeError(
            "Wyoming map-safety code is incomplete: " + ", ".join(missing_tokens)
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
    write_json(output_dir / "wyoming_fishing_report_database.json", db)
    (output_dir / "wyoming_fishing_report_database.js").write_text(
        "/* Automatically generated. Do not hand-edit. */\nwindow.WYOMING_FISHING_REPORT_DATABASE = "
        + json.dumps(db, separators=(",", ":"), ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )
    write_json(output_dir / "wyoming_public_fishing_access.json", {
        "metadata": db["metadata"],
        "county_count": db["county_count"],
        "public_water_count": db["public_water_count"],
        "counties": db["counties"],
        "flat_waters": db["flat_waters"],
    })
    (output_dir / "wyoming_public_fishing_access.js").write_text(
        "/* Automatically generated. Do not hand-edit. */\nwindow.WYOMING_PUBLIC_FISHING_ACCESS = "
        + json.dumps({"metadata": db["metadata"], "county_count": 23, "public_water_count": db["public_water_count"], "counties": db["counties"], "flat_waters": db["flat_waters"]}, separators=(",", ":"), ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )
    write_json(output_dir / "wyoming_project_status.json", status)
    write_json(root / "config/wyoming_counties.json", {"state": STATE, "county_count": 23, "counties": [{"county_number": i + 1, "county": c} for i, c in enumerate(COUNTIES)]})
    with (output_dir / "wyoming_counties.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle); writer.writerow(["county_number", "county"])
        writer.writerows((i + 1, c) for i, c in enumerate(COUNTIES))
    with (output_dir / "wyoming_fishing_report_database.csv").open("w", newline="", encoding="utf-8-sig") as handle:
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
<meta name="description" content="Search confirmed Wyoming Game and Fish public fishing opportunities, access areas and recent stocking records across all 23 counties."/>
<title>Wyoming County Fishing Reports & Public Access | Fish Finder Outdoors</title>
<link rel="icon" href="ffo-logo-main.png" type="image/png"/><link rel="apple-touch-icon" href="ffo-logo-main.png"/><link rel="manifest" href="manifest.json"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Bitter:wght@600;700;800&family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="brand-shell.css"/>
<style>
:root{--green:#1f4d3a;--paper:#f4f1e7;--card:#fffdf8;--line:#d8d3c7;--ink:#173029;--muted:#64716c;--warn:#7a5d1f;--danger:#96352c}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#e9f0ea,#f4f1e7 320px);color:var(--ink);font-family:Inter,Arial,sans-serif}.wrap{width:min(1180px,calc(100% - 28px));margin:auto}.hero{padding:38px 0 20px}.hero-grid{display:grid;grid-template-columns:1.25fr .75fr;gap:26px;align-items:center}.kicker{display:inline-flex;padding:7px 11px;border-radius:999px;background:#e2eee7;color:var(--green);font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}.hero h1{font-family:Bitter,Georgia,serif;font-size:clamp(36px,6vw,64px);line-height:1.02;margin:16px 0 12px}.hero p{font-size:18px;color:var(--muted);max-width:760px}.hero-logo{width:min(300px,100%);justify-self:end}.panel{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;margin:18px 0;box-shadow:0 10px 30px rgba(31,77,58,.07)}.controls{display:grid;grid-template-columns:1.2fr 1fr repeat(3,auto);gap:10px;align-items:end}.field label{display:block;font-size:12px;font-weight:900;margin:0 0 5px}.field select,.field input{width:100%;padding:12px 13px;border:1px solid #bfc7c1;border-radius:12px;background:white;font:inherit}.check{display:flex;align-items:center;gap:7px;padding:11px 10px;background:#eef4f0;border-radius:12px;font-size:12px;font-weight:800;white-space:nowrap}.check input{width:18px;height:18px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}button,.button{border:0;border-radius:12px;padding:11px 14px;font:inherit;font-weight:850;cursor:pointer;text-decoration:none}.primary{background:var(--green);color:white}.secondary{background:#e3ece7;color:var(--green)}.status{padding:12px 14px;border-radius:12px;background:#edf4f0;color:var(--green);font-weight:750;margin-top:13px}.status.warning{background:#fff5d9;color:var(--warn)}.status.error{background:#fae5e1;color:var(--danger)}.summary{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.metric{background:white;border:1px solid var(--line);border-radius:14px;padding:13px}.metric span{font-size:12px;color:var(--muted);font-weight:700}.metric b{display:block;font-size:25px;margin-top:4px}.water-list{display:grid;gap:13px}.water-card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px}.water-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}.water-head h2{font-family:Bitter,Georgia,serif;margin:0;font-size:25px}.chips{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0}.chip{display:inline-flex;padding:5px 8px;border-radius:999px;background:#e8f0eb;border:1px solid #c9dbd1;font-size:11px;font-weight:850}.chip.current{background:#daf1e4;color:#176354}.chip.recent{background:#fff0c5;color:#705319}.chip.stale{background:#f5dedb;color:#8d3029}.chip.none{background:#ecebe7;color:#666}.details{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:13px}.box{border:1px solid var(--line);border-radius:14px;padding:14px;background:white}.box h3{font-size:15px;margin:0 0 9px}.box p{margin:7px 0;color:#3f504a}.access{border-top:1px solid var(--line);padding-top:10px;margin-top:10px}.amenities{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}.amenity{font-size:11px;padding:5px 7px;border-radius:8px;background:#f0f3ef}.report-link{display:inline-flex;margin-top:8px;font-weight:850}.muted{color:var(--muted);font-size:13px}.empty{padding:28px;text-align:center;border:1px dashed #b9b3a6;border-radius:16px;background:#fbf8f1}.footer-note{font-size:13px;color:var(--muted);line-height:1.6}.top-links{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}.top-links a{display:inline-flex;padding:10px 12px;border-radius:12px;background:white;border:1px solid var(--line);font-weight:800;text-decoration:none}.load-more{display:block;margin:18px auto}.hidden{display:none!important}@media(max-width:900px){.hero-grid{grid-template-columns:1fr}.hero-logo{justify-self:start;max-width:220px}.controls{grid-template-columns:1fr 1fr}.summary{grid-template-columns:1fr 1fr}.details{grid-template-columns:1fr}}@media(max-width:600px){.controls{grid-template-columns:1fr}.summary{grid-template-columns:1fr 1fr}.water-head{display:block}.panel{padding:15px}.hero{padding-top:24px}}
</style></head>
<body>
<header class="ffo-site-header"><div class="ffo-header-inner"><a class="ffo-logo-link" href="https://fishfinderoutdoors.com"><img src="ffo-logo-main.png" alt="Fish Finder Outdoors logo"/><span class="ffo-wordmark"><strong>Fish Finder</strong><span>Outdoors</span></span></a><button class="ffo-menu-button" aria-label="Open menu" aria-expanded="false" type="button">☰</button><nav class="ffo-nav" aria-label="Fish Finder Outdoors"><a href="https://fishfinderoutdoors.com">Home</a><a href="index.html">Fishing Reports</a><a href="idaho-county-reports.html">Idaho County Reports</a><a href="montana-county-reports.html">Montana County Reports</a><a href="utah-county-reports.html">Utah County Reports</a><a href="colorado-county-reports.html">Colorado County Reports</a><a class="active" href="wyoming-county-reports.html">Wyoming County Reports</a><a href="submit-report.html">Submit Report</a><a href="official-sources.html">Official Sources</a></nav></div></header>
<div class="ffo-beta-bar">PUBLIC ACCESS ONLY • 23 WYOMING COUNTIES • REPORT DATES AND SOURCES SHOWN • <button class="ffo-install-button" data-install-ffo-app hidden type="button">Install App</button></div>
<main><section class="hero"><div class="wrap hero-grid"><div><span class="kicker">Wyoming statewide directory</span><h1>Public fishing waters and current information, county by county.</h1><p>Search official confirmed Wyoming Game and Fish fishing opportunities, recent trout stocking records and official public-access records across all 23 counties. Map buttons appear only when a dependable Wyoming coordinate is available.</p><div class="top-links"><a href="index.html">← Main report generator</a><a href="submit-report.html">Submit a fishing report</a><a href="report-water.html">Report incorrect access</a></div></div><img class="hero-logo" src="ffo-logo-main.png" alt="Fish Finder Outdoors"/></div></section>
<div class="wrap"><section class="panel"><div class="controls"><div class="field"><label for="countySelect">County</label><select id="countySelect"><option value="">All 23 counties</option></select></div><div class="field"><label for="waterSearch">Water, species or report keyword</label><input id="waterSearch" placeholder="Lake, river, trout, stocking…"/></div><label class="check"><input id="currentOnly" type="checkbox"/> Current reports</label><label class="check"><input id="boatRamp" type="checkbox"/> Boat ramp</label><label class="check"><input id="adaFishing" type="checkbox"/> Accessible fishing</label></div><div class="actions"><button class="primary" id="searchButton" type="button">Search public waters</button><button class="secondary" id="clearButton" type="button">Clear filters</button></div><div class="status" id="status">Loading the Wyoming public-access database…</div></section>
<section class="panel"><div class="summary" id="summary"></div></section><section class="water-list" id="waterList"></section><button class="secondary load-more hidden" id="loadMore" type="button">Show more waters</button>
<section class="panel footer-note"><strong>How to read this page:</strong> Wyoming access, drought closures, emergency regulations, water levels and roads can change. Stocking records are dated observations, not guarantees. Open the official source, check current Wyoming rules and obey posted signs before traveling.</section></div></main>
<footer class="ffo-site-footer"><div class="ffo-footer-grid"><div><a class="ffo-footer-brand" href="https://fishfinderoutdoors.com"><img src="ffo-logo-main.png" alt="Fish Finder Outdoors logo"/><span><strong>Fish Finder Outdoors</strong><br/><span style="color:#a9bbb3">Beginner friendly. Wyoming ready.</span></span></a></div><div><div class="ffo-footer-title">Reports</div><div class="ffo-footer-links"><a href="index.html">Main Report Generator</a><a href="idaho-county-reports.html">Idaho County Reports</a><a href="montana-county-reports.html">Montana County Reports</a><a href="utah-county-reports.html">Utah County Reports</a><a href="wyoming-county-reports.html">Wyoming County Reports</a><a href="submit-report.html">Submit a Report</a><a href="official-sources.html">Official Sources</a></div></div></div><div class="ffo-footer-fine"><span>© 2026 Fish Finder Outdoors. Powered by Mountain Dog Enterprises.</span><span>Verify current regulations and access before fishing.</span></div></footer>
<script src="site_config.js"></script><script src="data/wyoming_fishing_report_database.js"></script><script>window.FFO_ACTIVE_FISHING_DATABASE=window.WYOMING_FISHING_REPORT_DATABASE;</script><script src="fishing_report_search.js"></script>
<script>(function(){const $=id=>document.getElementById(id);const countySelect=$("countySelect"),waterSearch=$("waterSearch"),currentOnly=$("currentOnly"),boatRamp=$("boatRamp"),adaFishing=$("adaFishing"),status=$("status"),summary=$("summary"),waterList=$("waterList"),loadMore=$("loadMore");let filtered=[],shown=0;const PAGE_SIZE=25;const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));const label=value=>String(value||"").replace(/_/g," ").replace(/\b\w/g,c=>c.toUpperCase());function amenityText(a){const out=[];if(a?.boat_ramp===true)out.push("Boat ramp");if(a?.dock===true)out.push("Dock or pier");if(a?.restroom===true)out.push("Restroom");if(a?.camping===true)out.push("Camping");if(a?.ada_fishing===true)out.push("Accessible fishing");return out;}function validCoordinate(value,min,max){if(value===null||value===undefined||value==="")return false;const number=Number(value);return Number.isFinite(number)&&number>=min&&number<=max;}function mapPoint(w){if(validCoordinate(w.latitude,40.9,45.1)&&validCoordinate(w.longitude,-111.2,-103.8))return{lat:Number(w.latitude),lon:Number(w.longitude)};const p=(w.access_points||[]).find(p=>validCoordinate(p.latitude,40.9,45.1)&&validCoordinate(p.longitude,-111.2,-103.8));return p?{lat:Number(p.latitude),lon:Number(p.longitude)}:null;}function init(){const db=window.WYOMING_FISHING_REPORT_DATABASE;if(!db||!Array.isArray(db.counties)){status.className="status error";status.textContent="The Wyoming fishing database could not be loaded.";return;}countySelect.innerHTML='<option value="">All 23 counties</option>'+db.counties.map(c=>`<option value="${esc(c.county)}">#${c.county_number} ${esc(c.county)} County</option>`).join("");status.textContent=`Database updated ${new Date(db.metadata.generated_at).toLocaleString()}. Choose a county or search a water.`;runSearch();}function runSearch(){const options={county:countySelect.value,query:waterSearch.value,boatRamp:boatRamp.checked,adaFishing:adaFishing.checked};filtered=window.FFO_FISHING_REPORT_SEARCH?.waters(options)||[];if(currentOnly.checked)filtered=filtered.filter(w=>["very_current","current"].includes(w.report_status));filtered.sort((a,b)=>(a.county_number-b.county_number)||String(a.water_name).localeCompare(String(b.water_name)));shown=0;waterList.innerHTML="";renderSummary();renderMore();status.className="status";status.textContent=`Found ${filtered.length.toLocaleString()} official fishing-opportunity record${filtered.length===1?"":"s"}${countySelect.value?` in ${countySelect.value} County`:" statewide"}.`;}function renderSummary(){const reports=filtered.filter(w=>w.report_count>0).length;const access=filtered.reduce((n,w)=>n+(w.access_point_count||0),0);const ramps=filtered.filter(w=>(w.access_points||[]).some(p=>p.amenities?.boat_ramp===true)).length;const ada=filtered.filter(w=>(w.access_points||[]).some(p=>p.amenities?.ada_fishing===true)).length;summary.innerHTML=[["Public waters",filtered.length],["With reports",reports],["Access points",access],["With boat ramps",ramps],["Accessible fishing",ada]].map(([k,v])=>`<div class="metric"><span>${k}</span><b>${Number(v).toLocaleString()}</b></div>`).join("");}function renderMore(){const batch=filtered.slice(shown,shown+PAGE_SIZE);shown+=batch.length;if(!filtered.length)waterList.innerHTML='<div class="empty">No confirmed Wyoming public fishing opportunities matched these filters.</div>';else waterList.insertAdjacentHTML("beforeend",batch.map(card).join(""));loadMore.classList.toggle("hidden",shown>=filtered.length);}function card(w){const report=w.latest_report;const statusClass=w.report_status==="very_current"||w.report_status==="current"?"current":w.report_status==="recent"?"recent":w.report_status==="stale"?"stale":"none";const map=mapPoint(w);const mapHtml=map?`<a class="button secondary" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${map.lat},${map.lon}`)}" target="_blank" rel="noopener">Map</a>`:"";const points=(w.access_points||[]).map(p=>{const amenities=amenityText(p.amenities);return `<div class="access"><strong>${esc(p.access_point_name||"Public access point")}</strong>${p.access_details?`<p>${esc(p.access_details)}</p>`:""}${amenities.length?`<div class="amenities">${amenities.map(a=>`<span class="amenity">${esc(a)}</span>`).join("")}</div>`:""}${p.directions_url?`<a class="report-link" href="${esc(p.directions_url)}" target="_blank" rel="noopener">Directions</a>`:""}</div>`;}).join("");const reportHtml=report?`<strong>${esc(report.title||"Fishing update")}</strong><div class="chips"><span class="chip ${statusClass}">${esc(label(report.freshness))}</span><span class="chip">${esc(report.report_date||"")}</span><span class="chip">${esc(report.source_name||"")}</span></div><p>${esc(report.summary||"")}</p>${report.species?`<p><strong>Species:</strong> ${esc(report.species)}</p>`:""}${report.source_url?`<a class="report-link" href="${esc(report.source_url)}" target="_blank" rel="noopener">Open official source</a>`:""}`:'<div class="muted">No recent public fishing update was matched to this water.</div>';return `<article class="water-card"><div class="water-head"><div><h2>${esc(w.water_name)}</h2><div class="chips"><span class="chip">#${w.county_number} ${esc(w.county)} County</span><span class="chip">${esc(label(w.water_type))}</span><span class="chip ${statusClass}">${esc(label(w.report_status))}</span></div></div>${mapHtml}</div><div class="details"><div class="box"><h3>Latest fishing information</h3>${reportHtml}</div><div class="box"><h3>Official access information</h3>${w.access_details?`<p>${esc(w.access_details)}</p>`:""}${points||'<div class="muted">No separately inventoried access point was matched. Check the Wyoming Game and Fish Fishing Guide and posted signs.</div>'}${w.official_access_source_url?`<a class="report-link" href="${esc(w.official_access_source_url)}" target="_blank" rel="noopener">Official access source</a>`:""}</div></div></article>`;}$("searchButton").addEventListener("click",runSearch);$("clearButton").addEventListener("click",()=>{countySelect.value="";waterSearch.value="";currentOnly.checked=false;boatRamp.checked=false;adaFishing.checked=false;runSearch();});countySelect.addEventListener("change",runSearch);waterSearch.addEventListener("keydown",e=>{if(e.key==="Enter")runSearch();});loadMore.addEventListener("click",renderMore);init();})();</script><script src="brand-shell.js"></script><script src="pwa.js"></script></body></html>'''


def patch_site_files(root: Path) -> None:
    page = root / "wyoming-county-reports.html"
    page.write_text(county_page_html(), encoding="utf-8")

    brand = root / "brand-shell.js"
    if brand.exists():
        text = brand.read_text(encoding="utf-8")
        replacement = "const stateLinks=[['idaho-county-reports.html','Idaho County Reports'],['montana-county-reports.html','Montana County Reports'],['utah-county-reports.html','Utah County Reports'],['colorado-county-reports.html','Colorado County Reports'],['wyoming-county-reports.html','Wyoming County Reports']];"
        text = re.sub(r"const stateLinks=\[[^;]+;", replacement, text, count=1)
        brand.write_text(text, encoding="utf-8")

    worker = root / "service-worker.js"
    if worker.exists():
        text = worker.read_text(encoding="utf-8")
        version = re.search(r"ffo-reports-pwa-v(\d+)", text)
        if version:
            text = text.replace(
                version.group(0),
                f"ffo-reports-pwa-v{int(version.group(1)) + 1}",
                1,
            )
        if "./wyoming-county-reports.html" not in text:
            anchor = '"./colorado-county-reports.html"'
            if anchor in text:
                text = text.replace(
                    anchor,
                    anchor + ',"./wyoming-county-reports.html"',
                    1,
                )
            else:
                text = text.replace(
                    '"./utah-county-reports.html"',
                    '"./utah-county-reports.html","./wyoming-county-reports.html"',
                    1,
                )
        data_anchor = '"colorado_public_fishing_access.json"'
        for filename in (
            "wyoming_fishing_report_database.js",
            "wyoming_fishing_report_database.json",
            "wyoming_public_fishing_access.js",
            "wyoming_public_fishing_access.json",
        ):
            if filename not in text:
                text = text.replace(data_anchor, f'{data_anchor},"{filename}"', 1)
        worker.write_text(text, encoding="utf-8")

    sitemap = root / "sitemap.xml"
    if sitemap.exists():
        text = sitemap.read_text(encoding="utf-8")
        if "wyoming-county-reports.html" not in text:
            block = """  <url>\n    <loc>https://fish-finder-reports-live.wasmer.app/wyoming-county-reports.html</loc>\n    <changefreq>daily</changefreq>\n    <priority>0.9</priority>\n  </url>\n"""
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

    if args.skip_network:
        county_polygons: list[tuple[str, list[list[list[float]]]]] = []
    else:
        try:
            for key in ("lakes", "streams", "facilities", "paa_locations", "wif_locations"):
                schema = validate_service_schema(SERVICES[key])
                source_counts[f"{key}_schema_fields"] = schema["field_count"]
            county_polygons = load_county_polygons()
            source_counts["county_polygons"] = len({county for county, _ in county_polygons})
        except Exception as exc:
            county_polygons = []
            failed_sources.append(f"wyoming_official_arcgis_schema: {exc}")

    if not args.skip_network and county_polygons:
        access_sources: list[dict[str, Any]] = []
        access_reports: list[dict[str, Any]] = []
        access_jobs = (
            ("paa_locations", "public_access_area", OFFICIAL_URLS["paa"], True, True),
            ("wif_locations", "walk_in_fishing", OFFICIAL_URLS["wif"], False, True),
            ("paa_access", "public_access_area", OFFICIAL_URLS["paa"], True, False),
            ("wif_access", "walk_in_fishing", OFFICIAL_URLS["wif"], False, False),
        )
        for key, access_type, url, require_fishing, required in access_jobs:
            try:
                found_sources, found_reports = collect_access_service(
                    key,
                    access_type=access_type,
                    fallback_url=url,
                    county_polygons=county_polygons,
                    require_fishing_text=require_fishing,
                )
                access_sources.extend(found_sources)
                access_reports.extend(found_reports)
                source_counts[f"{key}_records"] = len(found_sources)
            except Exception as exc:
                if required:
                    failed_sources.append(f"wyoming_{key}: {exc}")
                else:
                    warnings.append(f"Optional Wyoming access enrichment unavailable ({key}): {exc}")
        sources.extend(access_sources)
        reports.extend(access_reports)
        source_counts["official_access_records"] = len(access_sources)

        try:
            facility_sources, facility_index = collect_facilities(county_polygons)
            sources.extend(facility_sources)
            source_counts["fishing_facilities"] = len(facility_sources)
        except Exception as exc:
            facility_index = defaultdict(list)
            failed_sources.append(f"wyoming_fishing_facilities: {exc}")

        access_names_by_county: dict[str, set[str]] = defaultdict(set)
        for row in access_sources:
            county = canonical_county(row.get("county"))
            name = clean(row.get("water_name"))
            if county and name:
                access_names_by_county[county].add(name)
        try:
            guide_sources, guide_reports, guide_counts = collect_fishing_guide(
                county_polygons, facility_index, access_names_by_county
            )
            sources.extend(guide_sources)
            reports.extend(guide_reports)
            source_counts.update(guide_counts)
        except Exception as exc:
            failed_sources.append(f"wyoming_fishing_guide: {exc}")

    waters = merge_water_sources(sources)

    if not args.skip_network:
        try:
            stocking_reports, stocking_count, ambiguous_count, stocking_url = (
                collect_recent_stocking(waters)
            )
            reports.extend(stocking_reports)
            source_counts["recent_stocking_records"] = stocking_count
            source_counts["ambiguous_stocking_names_left_unmatched"] = ambiguous_count
            source_counts["stocking_source_url_resolved"] = 1 if stocking_url else 0
        except Exception as exc:
            failed_sources.append(f"wyoming_stocking_report: {exc}")

    db = assemble_database(waters, reports, generated_at)
    if db["county_count"] != 23 or len(db["counties"]) != 23:
        raise RuntimeError("Wyoming database did not create all 23 county shells")

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
            "Verified official 23-county order",
            "Validated official WGFD ArcGIS schemas",
            "Collected Fishing Guide lakes and streams",
            "Collected Public Access Area records",
            "Collected Walk-In Fishing records",
            "Collected official fishing facilities",
            "Built duplicate-safe WGFD stocking collector",
            "Rejected blank, malformed and out-of-Wyoming map coordinates",
            "Built county-by-county Wyoming page",
            "Installed five-state admin integration",
            "Updated navigation, sitemap and PWA cache",
            "Validated all 23 county shells and output files",
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
