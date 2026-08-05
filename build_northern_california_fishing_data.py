#!/usr/bin/env python3
"""Build Fish Finder Outdoors data for the user's Northern California boundary.

Scope is deliberately limited to 26 counties: Marin, Napa, Solano, Sacramento,
El Dorado, and every California county north of those boundary counties.
No county south of that boundary may be emitted by this builder.

Primary official sources
------------------------
* California State Parks Division of Boating and Waterways public boating
  facilities by county (public-access proof).
* California Department of Fish and Wildlife Fishing Guide / planting layer
  (fishing-water and fish-planting information; not access proof by itself).
* CDFW public fishing-location pages for Marin/Sonoma, Napa/Solano, and the
  Sacramento urban-fishing program.
* CDFW public piers dataset (named public marine fishing facilities).

A named facility verifies only that facility. It never declares an entire
shoreline, road, river reach, or neighboring parcel public.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

try:
    from bs4 import BeautifulSoup
except ImportError:  # installed in GitHub Actions
    BeautifulSoup = None

REGION = "Northern California"
STATE = "California"
STATE_ABBR = "CA"
BUILDER_VERSION = "1.0"

COUNTIES = [
    "Butte", "Colusa", "Del Norte", "El Dorado", "Glenn", "Humboldt",
    "Lake", "Lassen", "Marin", "Mendocino", "Modoc", "Napa", "Nevada",
    "Placer", "Plumas", "Sacramento", "Shasta", "Sierra", "Siskiyou",
    "Solano", "Sonoma", "Sutter", "Tehama", "Trinity", "Yolo", "Yuba",
]
COUNTY_NUMBER = {name: index + 1 for index, name in enumerate(COUNTIES)}
COUNTY_LOOKUP = {re.sub(r"[^a-z0-9]+", " ", c.lower()).strip(): c for c in COUNTIES}

# Explicitly excluded. This is validated on every build so a statewide source
# cannot silently expand the project southward.
EXCLUDED_COUNTIES = [
    "Alameda", "Alpine", "Amador", "Calaveras", "Contra Costa", "Fresno",
    "Imperial", "Inyo", "Kern", "Kings", "Los Angeles", "Madera",
    "Mariposa", "Merced", "Mono", "Monterey", "Orange", "Riverside",
    "San Benito", "San Bernardino", "San Diego", "San Francisco",
    "San Joaquin", "San Luis Obispo", "San Mateo", "Santa Barbara",
    "Santa Clara", "Santa Cruz", "Stanislaus", "Tulare", "Tuolumne",
    "Ventura",
]

USER_AGENT = "FishFinderOutdoors-NorthernCaliforniaBuilder/1.0 (+https://fishfinderoutdoors.com)"
OFFICIAL = {
    "cdfw_fishing_guide_page": "https://wildlife.ca.gov/Fishing/Guide",
    "cdfw_fishing_guide_service": "https://services2.arcgis.com/Uq9r85Potqm3MfRV/ArcGIS/rest/services/FishingGuide/FeatureServer",
    "cdfw_planting_layer": "https://services2.arcgis.com/Uq9r85Potqm3MfRV/ArcGIS/rest/services/biosds2897_fmu/FeatureServer/0",
    "cdfw_public_piers_layer": "https://services2.arcgis.com/Uq9r85Potqm3MfRV/ArcGIS/rest/services/biosds3090_fmu/FeatureServer/0",
    "cdfw_public_access_lands": "https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds3077_fpu/FeatureServer/0",
    "dbw_county_template": "https://dbw.parks.ca.gov/BoatingFacilities/County/{county}",
    "dbw_facility_root": "https://dbw.parks.ca.gov",
    "regulations": "https://wildlife.ca.gov/Regulations/Fishing",
    "low_flow": "https://wildlife.ca.gov/Fishing/Inland/Low-Flow",
    "marin_sonoma": "https://wildlife.ca.gov/Fishing-in-the-City/SF/Gofish/North",
    "napa_solano": "https://wildlife.ca.gov/Fishing-in-the-City/SF/Gofish/Northeast",
    "sacramento": "https://wildlife.ca.gov/Fishing-in-the-City/SAC",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).strip()


def slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean(value).lower()).strip("-")


def stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha1("|".join(clean(p) for p in parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def canonical_county(value: Any) -> str:
    text = norm(value).replace(" county", "").strip()
    return COUNTY_LOOKUP.get(text, "")


def is_scope_county(value: Any) -> bool:
    return bool(canonical_county(value))


def fetch_bytes(url: str, *, timeout: int = 45, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Could not download {url}: {last}")


def fetch_text(url: str, **kwargs: Any) -> str:
    return fetch_bytes(url, **kwargs).decode("utf-8", errors="replace")


def fetch_json(url: str, **kwargs: Any) -> dict[str, Any]:
    payload = json.loads(fetch_text(url, **kwargs))
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"ArcGIS error for {url}: {payload['error']}")
    return payload


def arcgis_url(base: str, **params: Any) -> str:
    return f"{base}?{urlencode(params, doseq=True)}"


def arcgis_all_features(layer_url: str, out_fields: str = "*") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    metadata = fetch_json(arcgis_url(layer_url, f="json"))
    oid = clean(metadata.get("objectIdField") or metadata.get("objectIdFieldName") or "OBJECTID")
    id_payload = fetch_json(arcgis_url(layer_url + "/query", where="1=1", returnIdsOnly="true", f="json"))
    object_ids = sorted(int(x) for x in (id_payload.get("objectIds") or []))
    if not object_ids:
        return [], metadata
    max_count = int(metadata.get("maxRecordCount") or 1000)
    chunk_size = max(50, min(max_count, 1000))
    features: list[dict[str, Any]] = []
    for start in range(0, len(object_ids), chunk_size):
        chunk = object_ids[start:start + chunk_size]
        payload = fetch_json(arcgis_url(
            layer_url + "/query",
            objectIds=",".join(map(str, chunk)),
            outFields=out_fields,
            returnGeometry="true",
            outSR=4326,
            f="json",
        ))
        features.extend(payload.get("features") or [])
    return features, {**metadata, "advertised_object_id_count": len(object_ids), "downloaded_feature_count": len(features), "oid": oid}


def first_attr(attrs: dict[str, Any], candidates: Iterable[str]) -> str:
    lookup = {norm(k).replace(" ", ""): v for k, v in attrs.items()}
    for candidate in candidates:
        key = norm(candidate).replace(" ", "")
        if key in lookup and clean(lookup[key]):
            return clean(lookup[key])
    return ""


def point_from_geometry(geometry: dict[str, Any] | None) -> tuple[float | None, float | None]:
    geometry = geometry or {}
    if "x" in geometry and "y" in geometry:
        try:
            return float(geometry["y"]), float(geometry["x"])
        except (TypeError, ValueError):
            return None, None
    return None, None


def parse_label_value(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*:\s*(.+?)(?=\n[A-Z][A-Za-z /-]+\s*:|$)", text, re.I | re.S)
    return clean(match.group(1)) if match else ""


def parse_dbw_county_page(page_html: str, base_url: str) -> list[dict[str, Any]]:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required for DBW parsing")
    soup = BeautifulSoup(page_html, "html.parser")
    rows: list[dict[str, Any]] = []
    for tr in soup.select("tr"):
        cells = [clean(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
        if len(cells) < 2 or cells[0].lower() in {"facility name", ""}:
            continue
        link = tr.find("a", href=re.compile(r"/BoatingFacilities/f/", re.I))
        if not link:
            continue
        access = cells[2] if len(cells) > 2 else ""
        rows.append({
            "facility_name": cells[0],
            "facility_type": cells[1],
            "access": access,
            "detail_url": urljoin(base_url, link.get("href")),
        })
    return rows


def parse_dbw_detail(page_html: str, detail_url: str, fallback: dict[str, Any]) -> dict[str, Any]:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required for DBW parsing")
    soup = BeautifulSoup(page_html, "html.parser")
    title = clean((soup.find("h1") or soup.find("title") or "").get_text(" ", strip=True) if (soup.find("h1") or soup.find("title")) else fallback.get("facility_name"))
    text = soup.get_text("\n", strip=True)
    county = canonical_county(parse_label_value(text, "County"))
    body = parse_label_value(text, "Body of Water")
    open_to = parse_label_value(text, "Open To") or fallback.get("access", "")
    facility_type = parse_label_value(text, "Type of Facility") or fallback.get("facility_type", "")
    jurisdiction = parse_label_value(text, "Jurisdiction/Authority")
    address = parse_label_value(text, "Facility Address")
    services_heading = soup.find(string=re.compile(r"^\s*Services\s*$", re.I))
    services: list[str] = []
    if services_heading:
        parent = services_heading.parent
        for node in parent.find_all_next(limit=20):
            value = clean(node.get_text(" ", strip=True))
            if value.lower().startswith("environmental services"):
                break
            if value and value.lower() not in {"services", "map"} and len(value) < 80:
                services.append(value)
    return {
        "facility_name": title or fallback.get("facility_name", "Public boating facility"),
        "facility_type": facility_type,
        "county": county,
        "body_of_water": body,
        "open_to": open_to,
        "jurisdiction": jurisdiction,
        "address": address,
        "services": sorted(set(services)),
        "detail_url": detail_url,
    }


def fetch_dbw_access() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    indexes: list[dict[str, Any]] = []
    county_failures: list[str] = []
    for county in COUNTIES:
        url = OFFICIAL["dbw_county_template"].format(county=quote(county))
        try:
            rows = parse_dbw_county_page(fetch_text(url), url)
            for row in rows:
                row["listed_county"] = county
            indexes.extend(rows)
        except Exception as exc:  # keep audit and continue
            county_failures.append(f"{county}: {exc}")

    detail_rows: list[dict[str, Any]] = []
    detail_failures: list[str] = []
    # Public in the county index is accepted, but the detail page is still read
    # to confirm county, water and public status.
    candidates = [row for row in indexes if norm(row.get("access")) in {"public", ""}]
    with ThreadPoolExecutor(max_workers=10) as pool:
        future_map = {pool.submit(fetch_text, row["detail_url"], timeout=35, retries=2): row for row in candidates}
        for future in as_completed(future_map):
            seed = future_map[future]
            try:
                detail = parse_dbw_detail(future.result(), seed["detail_url"], seed)
                if not detail["county"]:
                    detail["county"] = seed["listed_county"]
                if detail["county"] not in COUNTIES:
                    continue
                if norm(detail["open_to"]) != "public":
                    continue
                detail_rows.append(detail)
            except Exception as exc:
                detail_failures.append(f"{seed['detail_url']}: {exc}")

    unique: dict[str, dict[str, Any]] = {}
    for row in detail_rows:
        unique[row["detail_url"]] = row
    return sorted(unique.values(), key=lambda r: (r["county"], r["body_of_water"], r["facility_name"])), {
        "complete": not county_failures,
        "required": True,
        "source_name": "California State Parks Division of Boating and Waterways",
        "source_url": "https://dbw.parks.ca.gov/BoatingFacilities/",
        "county_pages_requested": len(COUNTIES),
        "county_page_failures": county_failures,
        "facility_links_found": len(indexes),
        "public_facilities_verified": len(unique),
        "detail_failures": detail_failures[:50],
    }


# A conservative checked-in baseline. Every row points to an official page and
# verifies only the named access/fishing location. Live builds add DBW facilities,
# CDFW public piers, Fishing Guide records and current planting information.
SEED_ACCESS = [
    # Napa
    ("Napa", "Napa River", "Napa River public riverfront/park access", OFFICIAL["napa_solano"], "CDFW identifies public fishing from the City of Napa downstream; use only designated public riverfront, park, pier, marina or boat access."),
    ("Napa", "Lake Berryessa", "Lake Berryessa public access", OFFICIAL["napa_solano"], "CDFW identifies Lake Berryessa as open to the public; fees, inspections and site restrictions may apply."),
    ("Napa", "Lake Hennessey", "Lake Hennessey public access and launch", OFFICIAL["napa_solano"], "CDFW identifies Lake Hennessey as open to the public with access and boat-launch fees and boating restrictions."),
    # Solano
    ("Solano", "Sacramento-San Joaquin Delta", "Grizzly and Joice Islands wildlife-area access", OFFICIAL["napa_solano"], "CDFW identifies good public access through the state-owned wildlife areas on Grizzly and Joice Islands; closures and restrictions must be checked."),
    ("Solano", "Lake Chabot", "Lake Chabot public fishing location", OFFICIAL["napa_solano"], "CDFW lists Lake Chabot in its public fishing locations for Solano County."),
    ("Solano", "Putah Creek / Lake Solano", "Highway 128 public access", OFFICIAL["napa_solano"], "CDFW states public access is good along the section from Monticello Dam to Lake Solano where Highway 128 parallels the creek."),
    # Marin
    ("Marin", "Walker Creek", "Keys Creek / Highway 1 fishing access", OFFICIAL["marin_sonoma"], "CDFW identifies public fishing access near the mouth at Keys Creek along Highway 1, subject to current seasons and special rules."),
    ("Marin", "Alpine Lake", "Alpine Lake shore access", OFFICIAL["marin_sonoma"], "CDFW lists Alpine Lake as a Marin County fishing location; boats and wading are not permitted."),
    ("Marin", "Bon Tempe Lake", "Bon Tempe Lake shore access", OFFICIAL["marin_sonoma"], "CDFW lists Bon Tempe Lake; a parking fee applies and boats and wading are not permitted."),
    ("Marin", "Lagunitas Lake", "Lagunitas Lake shore access", OFFICIAL["marin_sonoma"], "CDFW lists Lagunitas Lake with special gear, bait, bag and size rules; boats and wading are not permitted."),
    ("Marin", "Nicasio Lake", "Nicasio Lake roadside shore access", OFFICIAL["marin_sonoma"], "CDFW identifies easy shore access from Petaluma–Point Reyes Road and Nicasio Valley Road; boats and wading are not permitted."),
    ("Marin", "Phoenix Lake", "Phoenix Lake trail access", OFFICIAL["marin_sonoma"], "CDFW lists limited parking below Phoenix Lake and a hiking trail around the lake."),
    ("Marin", "Soulajule Reservoir", "Soulajule Reservoir dam parking access", OFFICIAL["marin_sonoma"], "CDFW identifies a small no-fee parking lot at the base of the dam; boats and wading are not permitted."),
    ("Marin", "Stafford Lake", "Stafford Lake County Park access", OFFICIAL["marin_sonoma"], "CDFW lists Stafford Lake at Stafford Lake County Park; parking fees apply and boats are not permitted."),
    ("Marin", "San Pablo Bay", "China Camp Pier", OFFICIAL["marin_sonoma"], "CDFW lists China Camp Pier as a Marin County public fishing location."),
    ("Marin", "San Francisco Bay", "East Fort Baker Pier", OFFICIAL["marin_sonoma"], "CDFW lists East Fort Baker Pier on the Marin side of the Golden Gate Bridge."),
    ("Marin", "San Francisco Bay", "Sausalito Pier", OFFICIAL["marin_sonoma"], "CDFW lists Sausalito Pier as a Marin County fishing location."),
    # Sonoma
    ("Sonoma", "Russian River", "Named public access communities", OFFICIAL["marin_sonoma"], "CDFW identifies public access at Jenner, Monte Rio, Guerneville, Forestville, Healdsburg and Cloverdale; low-flow rules apply seasonally."),
    ("Sonoma", "Gualala River", "Gualala Point / mouth-area public access", OFFICIAL["marin_sonoma"], "CDFW identifies public access near the mouth and at named road and park locations; low-flow rules apply seasonally."),
    ("Sonoma", "Salmon Creek", "Highway 1 tidewater access", OFFICIAL["marin_sonoma"], "CDFW identifies a small tidewater area open west of Highway 1; low-flow and species restrictions apply."),
    ("Sonoma", "Lake Ralphine", "Howarth Park access", OFFICIAL["marin_sonoma"], "CDFW lists Lake Ralphine in Howarth Park as a public fishing location."),
    ("Sonoma", "Spring Lake", "Spring Lake public fishing access", OFFICIAL["marin_sonoma"], "CDFW lists Spring Lake as a Sonoma County fishing location."),
    ("Sonoma", "Lake Sonoma", "Lake Sonoma dam and Yorty Creek launches", OFFICIAL["marin_sonoma"], "CDFW identifies a boat ramp near the dam and a car-topper launch at Yorty Creek; shore access is limited."),
    # Sacramento urban locations
    ("Sacramento", "Granite Regional Park Pond", "Granite Regional Park fishing access", OFFICIAL["sacramento"], "CDFW lists Granite Regional Park as a Fishing in the City location."),
    ("Sacramento", "North Natomas Regional Park Pond", "North Natomas Regional Park fishing access", OFFICIAL["sacramento"], "CDFW lists North Natomas Regional Park as a Fishing in the City location."),
    ("Sacramento", "Hagan Community Park Pond", "Hagan Community Park fishing access", OFFICIAL["sacramento"], "CDFW lists Hagan Community Park as a Fishing in the City location."),
    ("Sacramento", "Howe Park Pond", "Howe Park fishing access", OFFICIAL["sacramento"], "CDFW lists Howe Park as a Fishing in the City location."),
    ("Sacramento", "Mather Lake", "Mather Regional Park fishing access", OFFICIAL["sacramento"], "CDFW states it regularly stocks and provides fishing events at Mather Lake."),
    ("Sacramento", "Elk Grove Regional Park Pond", "Elk Grove Regional Park fishing access", OFFICIAL["sacramento"], "CDFW states Elk Grove Regional Park is open for fishing during its posted season."),
    ("Sacramento", "Florin Creek Park Pond", "Florin Creek Park fishing access", OFFICIAL["sacramento"], "CDFW identifies Florin Creek Park pond as a stocked community fishing location."),
    ("Sacramento", "Gibson Ranch Regional Park Pond", "Gibson Ranch Regional Park fishing access", OFFICIAL["sacramento"], "CDFW lists Gibson Ranch Regional Park as a stocked Fishing in the City pond."),
    ("Sacramento", "Southside Park Pond", "Southside Park fishing access", OFFICIAL["sacramento"], "CDFW lists Southside Park Pond in its Sacramento stocking and clinic information."),
    # El Dorado - official State Parks/DBW/Recreation.gov pages
    ("El Dorado", "Folsom Lake", "Brown's Ravine public ramps", "https://dbw.parks.ca.gov/BoatingFacilities/f/739", "California DBW lists Brown's Ravine ramps on Folsom Lake as open to the public."),
    ("El Dorado", "Folsom Lake", "Peninsula public ramp", "https://dbw.parks.ca.gov/BoatingFacilities/f/736", "California DBW lists the Peninsula ramp on Folsom Lake as open to the public."),
    ("El Dorado", "Lake Tahoe", "El Dorado Beach Boat Ramp", "https://www.parks.ca.gov/BoatingFacilities/f/709", "California DBW lists El Dorado Beach Boat Ramp on Lake Tahoe as open to the public."),
    ("El Dorado", "Sly Park Reservoir", "Sly Park public recreation and launch access", "https://www.recreation.gov/gateways/2279", "The official Recreation.gov page identifies public-use facilities, two launch ramps and fishing at Sly Park Reservoir."),
    ("El Dorado", "Wrights Lake", "Wrights Lake public launch", "https://www.parks.ca.gov/BoatingFacilities/f/1364", "California DBW lists Wrights Lake Access as a public US Forest Service launch."),
    ("El Dorado", "Echo Lake", "Echo Chalet public marina/launch", "https://www.parks.ca.gov/BoatingFacilities/f/726", "California DBW lists Echo Chalet as a public marina and launch on Echo Lake."),
    ("El Dorado", "American River — South Fork", "Henningsen-Lotus public boating access", "https://dbw.parks.ca.gov/BoatingFacilities/f/1204", "California DBW lists Henningsen-Lotus as public boating access on the South Fork American River."),
    # Official DBW county-directory baseline for every remaining in-scope county.
    # Each source page explicitly labels the named facility as Public.
    ("Butte", "Lake Oroville", "Lake Oroville SRA — Bidwell Canyon public launch", "https://dbw.parks.ca.gov/BoatingFacilities/County/Butte", "California DBW's Butte County directory lists Lake Oroville SRA at Bidwell Canyon as a public launch."),
    ("Colusa", "East Park Reservoir", "East Park Reservoir public ramp", "https://dbw.parks.ca.gov/BoatingFacilities/County/Colusa", "California DBW's Colusa County directory lists East Park Reservoir Ramp as public."),
    ("Del Norte", "Lake Earl", "Lake Earl public boat launch", "https://dbw.parks.ca.gov/BoatingFacilities/County/Del%20Norte", "California DBW's Del Norte County directory lists the Lake Earl Boat Launch Facility as public."),
    ("Glenn", "Stony Gorge Reservoir", "Stony Gorge Reservoir public launch", "https://dbw.parks.ca.gov/BoatingFacilities/County/Glenn", "California DBW's Glenn County directory lists Stony Gorge Reservoir as a public launch."),
    ("Humboldt", "Big Lagoon", "Big Lagoon County Park public boat ramp", "https://dbw.parks.ca.gov/BoatingFacilities/County/Humboldt", "California DBW's Humboldt County directory lists Big Lagoon County Park Boat Ramp as public."),
    ("Lake", "Clear Lake", "Clear Lake State Park public boat ramp", "https://dbw.parks.ca.gov/BoatingFacilities/County/Lake", "California DBW's Lake County directory lists Clear Lake State Park Boat Ramp as public."),
    ("Lassen", "Eagle Lake", "Eagle Lake Marina public launch", "https://dbw.parks.ca.gov/BoatingFacilities/County/Lassen", "California DBW's Lassen County directory lists Eagle Lake Marina as a public marina and launch."),
    ("Mendocino", "Lake Mendocino", "Lake Mendocino public launch", "https://dbw.parks.ca.gov/BoatingFacilities/County/Mendocino", "California DBW's Mendocino County directory lists Lake Mendocino as a public launch."),
    ("Modoc", "Big Sage Reservoir", "Big Sage Reservoir public launch", "https://dbw.parks.ca.gov/BoatingFacilities/County/Modoc", "California DBW's Modoc County directory lists Big Sage Reservoir as a public launch."),
    ("Nevada", "Boca Reservoir", "Boca Reservoir public launch", "https://dbw.parks.ca.gov/BoatingFacilities/County/Nevada", "California DBW's Nevada County directory lists Boca Reservoir as a public launch."),
    ("Placer", "Lake Clementine", "Lake Clementine public boat launch", "https://dbw.parks.ca.gov/BoatingFacilities/County/Placer", "California DBW's Placer County directory lists the Lake Clementine Boat Launch Facility as public."),
    ("Plumas", "Lake Almanor", "Lake Almanor public boat launching facility", "https://dbw.parks.ca.gov/BoatingFacilities/County/Plumas", "California DBW's Plumas County directory lists the Lake Almanor Boat Launching Facility as public."),
    ("Shasta", "Shasta Lake", "Shasta Lake Antlers public ramp", "https://dbw.parks.ca.gov/BoatingFacilities/County/Shasta", "California DBW's Shasta County directory lists Shasta Lake's Antlers Ramp as public."),
    ("Sierra", "Sardine Lake", "Sardine Lake public launch", "https://dbw.parks.ca.gov/BoatingFacilities/County/Sierra", "California DBW's Sierra County directory lists Sardine Lake as a public launch."),
    ("Siskiyou", "Lake Shastina", "Lake Shastina public fishing access and boat ramp", "https://dbw.parks.ca.gov/BoatingFacilities/County/Siskiyou", "California DBW's Siskiyou County directory lists Lake Shastina Fishing Access/Boat Ramp as public."),
    ("Sutter", "Live Oak Riverfront Park", "Live Oak Riverfront Park public launch", "https://dbw.parks.ca.gov/BoatingFacilities/County/Sutter", "California DBW's Sutter County directory lists Live Oak Riverfront Park as a public launch."),
    ("Tehama", "Black Butte Lake", "Black Butte Lake Buckhorn public ramp and marina", "https://dbw.parks.ca.gov/BoatingFacilities/County/Tehama", "California DBW's Tehama County directory lists Black Butte Lake's Buckhorn ramp and marina as public."),
    ("Trinity", "Trinity Lake", "Trinity Lake public recreation access", "https://dbw.parks.ca.gov/BoatingFacilities/County/Trinity", "California DBW's Trinity County directory lists Trinity Lake National Recreation Area as public."),
    ("Yolo", "Knights Landing Fishing Access", "Knights Landing public fishing access", "https://dbw.parks.ca.gov/BoatingFacilities/County/Yolo", "California DBW's Yolo County directory lists Knights Landing Fishing Access as public."),
    ("Yuba", "Bullards Bar Reservoir", "Bullards Bar Cottage Creek public boat launch", "https://dbw.parks.ca.gov/BoatingFacilities/County/Yuba", "California DBW's Yuba County directory lists Bullards Bar Reservoir's Cottage Creek Boat Launch Facility as public."),
]


def seed_access_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for county, water, access_name, url, evidence in SEED_ACCESS:
        rows.append({
            "facility_name": access_name,
            "facility_type": "official public fishing/access location",
            "county": county,
            "body_of_water": water,
            "open_to": "Public",
            "jurisdiction": "Official California public source",
            "address": "",
            "services": [],
            "detail_url": url,
            "verification_evidence": evidence,
            "verification_method": "official_named_public_location_baseline",
            "source_name": "California official public fishing/access source",
        })
    return rows


def fetch_public_piers() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        features, metadata = arcgis_all_features(OFFICIAL["cdfw_public_piers_layer"])
    except Exception as exc:
        return [], {"complete": False, "optional": True, "source_url": OFFICIAL["cdfw_public_piers_layer"], "error": str(exc)}
    rows: list[dict[str, Any]] = []
    for feature in features:
        attrs = feature.get("attributes") or {}
        county = canonical_county(first_attr(attrs, ["County", "COUNTY", "CountyName"]))
        if not county:
            continue
        name = first_attr(attrs, ["Pier", "Name", "NAME", "Location"])
        if not name:
            continue
        lat, lon = point_from_geometry(feature.get("geometry"))
        notes = first_attr(attrs, ["Notes", "NOTES", "Description"])
        rows.append({
            "facility_name": name,
            "facility_type": "public fishing pier, jetty or breakwater",
            "county": county,
            "body_of_water": first_attr(attrs, ["Water", "BodyOfWater", "Waterbody"]) or "Pacific coast / bay waters",
            "open_to": "Public",
            "jurisdiction": "California Department of Fish and Wildlife public-pier dataset",
            "address": "",
            "services": [],
            "detail_url": OFFICIAL["cdfw_public_piers_layer"],
            "latitude": lat,
            "longitude": lon,
            "verification_evidence": clean(notes) or "CDFW's public-pier dataset identifies this named public fishing location. Confirm current closure status before travel.",
            "verification_method": "official_cdfw_public_pier_dataset",
            "source_name": "California Department of Fish and Wildlife",
        })
    return rows, {
        "complete": len(features) == int(metadata.get("advertised_object_id_count", len(features))),
        "optional": True,
        "source_url": OFFICIAL["cdfw_public_piers_layer"],
        "advertised_object_id_count": metadata.get("advertised_object_id_count", 0),
        "downloaded_feature_count": len(features),
        "in_scope_records": len(rows),
    }


def fetch_plantings() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        features, metadata = arcgis_all_features(OFFICIAL["cdfw_planting_layer"])
    except Exception as exc:
        return [], {"complete": False, "optional": True, "source_url": OFFICIAL["cdfw_planting_layer"], "error": str(exc)}
    reports: list[dict[str, Any]] = []
    for feature in features:
        attrs = feature.get("attributes") or {}
        county = canonical_county(first_attr(attrs, ["County", "COUNTY", "CountyName", "CNTY_NAME"]))
        if not county:
            continue
        water = first_attr(attrs, ["WaterName", "Water_Name", "Location", "PlantingLocation", "Name", "NAME"])
        if not water:
            continue
        species = first_attr(attrs, ["Species", "SPECIES", "Fish", "FishSpecies"])
        raw_date: Any = ""
        for field in ["PlantDate", "Plant_Date", "Date", "DATE", "WeekOf", "PlantingDate"]:
            if field in attrs and attrs[field] not in (None, ""):
                raw_date = attrs[field]
                break
        report_date = ""
        if isinstance(raw_date, (int, float)):
            try:
                report_date = datetime.fromtimestamp(float(raw_date) / 1000, tz=timezone.utc).date().isoformat()
            except (ValueError, OSError, OverflowError):
                report_date = ""
        elif clean(raw_date):
            report_date = clean(raw_date)
        lat, lon = point_from_geometry(feature.get("geometry"))
        title = f"CDFW fish planting: {water}"
        summary = f"CDFW planting location for {water}"
        if species:
            summary += f" ({species})"
        reports.append({
            "report_id": stable_id("nca-report", county, water, report_date, species),
            "state": REGION,
            "jurisdiction_state": STATE,
            "county": county,
            "water_name": water,
            "report_date": report_date,
            "freshness": "official_schedule",
            "source_type": "official_cdfw_fish_planting",
            "source_name": "California Department of Fish and Wildlife",
            "official": True,
            "title": title,
            "summary": summary,
            "species": species,
            "techniques": "",
            "source_url": "https://nrm.dfg.ca.gov/FishPlants/",
            "latitude": lat,
            "longitude": lon,
        })
    return reports, {
        "complete": len(features) == int(metadata.get("advertised_object_id_count", len(features))),
        "optional": True,
        "source_url": OFFICIAL["cdfw_planting_layer"],
        "advertised_object_id_count": metadata.get("advertised_object_id_count", 0),
        "downloaded_feature_count": len(features),
        "in_scope_records": len(reports),
    }


def access_to_point(row: dict[str, Any]) -> dict[str, Any]:
    county = canonical_county(row.get("county"))
    name = clean(row.get("facility_name"))
    url = clean(row.get("detail_url"))
    evidence = clean(row.get("verification_evidence")) or (
        "California State Parks Division of Boating and Waterways identifies this named facility as open to the public. "
        "Confirm water levels, launch status, fees, inspections, seasonal closures and posted rules before travel."
    )
    services = row.get("services") or []
    amenity_text = " ".join(clean(x).lower() for x in services)
    facility_text = clean(row.get("facility_type")).lower()
    amenities: dict[str, Any] = {}
    if "restroom" in amenity_text:
        amenities["restroom"] = True
    if "camp" in amenity_text:
        amenities["camping"] = True
    if "picnic" in amenity_text:
        amenities["picnic"] = True
    if any(term in facility_text for term in ["launch", "marina"]):
        amenities["boat_ramp_or_marina"] = True
    if "pier" in facility_text or "pier" in name.lower():
        amenities["fishing_pier"] = True
    lat = row.get("latitude")
    lon = row.get("longitude")
    directions = ""
    if lat not in (None, "") and lon not in (None, ""):
        directions = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    elif row.get("address"):
        directions = "https://www.google.com/maps/search/?api=1&query=" + quote(clean(row["address"]))
    return {
        "access_id": stable_id("nca-access", county, name, url),
        "access_point_name": name,
        "public_access_status": "verified_public",
        "entire_shoreline_public": False,
        "verification_method": clean(row.get("verification_method")) or "official_california_dbw_public_facility_page",
        "source_name": clean(row.get("source_name")) or "California State Parks Division of Boating and Waterways",
        "source_type": "official_public_access",
        "official_source_url": url,
        "verification_evidence": evidence,
        "access_details": "; ".join(x for x in [
            f"Facility type: {clean(row.get('facility_type'))}" if row.get("facility_type") else "",
            f"Jurisdiction: {clean(row.get('jurisdiction'))}" if row.get("jurisdiction") else "",
            f"Address: {clean(row.get('address'))}" if row.get("address") else "",
        ] if x),
        "county": county,
        "latitude": lat,
        "longitude": lon,
        "directions_url": directions,
        "current_status": "verify_current_conditions_before_travel",
        "open_dates": "",
        "amenities": amenities,
    }


def build_database(access_rows: list[dict[str, Any]], reports: list[dict[str, Any]], audits: dict[str, Any], generated_at: str) -> dict[str, Any]:
    # Exact county boundary gate before any grouping.
    for row in access_rows:
        county = canonical_county(row.get("county"))
        if not county:
            raise ValueError(f"Out-of-scope or unknown county in access row: {row.get('county')!r}")
        row["county"] = county
    for report in reports:
        county = canonical_county(report.get("county"))
        if not county:
            raise ValueError(f"Out-of-scope or unknown county in report row: {report.get('county')!r}")
        report["county"] = county

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in access_rows:
        water = clean(row.get("body_of_water")) or clean(row.get("facility_name"))
        grouped[(row["county"], water)].append(row)

    report_index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        report_index[(report["county"], norm(report["water_name"]))].append(report)

    flat_waters: list[dict[str, Any]] = []
    for (county, water_name), rows in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        points = [access_to_point(row) for row in rows]
        # Deduplicate named facilities by stable ID.
        points = list({point["access_id"]: point for point in points}.values())
        matched_reports: list[dict[str, Any]] = []
        target = norm(water_name)
        for (report_county, report_water), candidates in report_index.items():
            if report_county != county:
                continue
            if report_water == target or report_water in target or target in report_water:
                matched_reports.extend(candidates)
        matched_reports.sort(key=lambda r: clean(r.get("report_date")), reverse=True)
        lat = next((p.get("latitude") for p in points if p.get("latitude") not in (None, "")), None)
        lon = next((p.get("longitude") for p in points if p.get("longitude") not in (None, "")), None)
        source_urls = sorted({p["official_source_url"] for p in points})
        water = {
            "water_id": stable_id("nca-water", county, water_name),
            "state": REGION,
            "jurisdiction_state": STATE,
            "county": county,
            "counties": [county],
            "county_number": COUNTY_NUMBER[county],
            "water_name": water_name,
            "water_type": "public fishing / boating water",
            "latitude": lat,
            "longitude": lon,
            "species": "",
            "metadata_sources": sorted({p["verification_method"] for p in points}),
            "water_source_urls": source_urls,
            "access_points": points,
            "publication_status": "published_verified_public_access",
            "access_point_count": len(points),
            "public_access_verification": "named official public facility or location only",
            "report_count": len(matched_reports),
            "reports": matched_reports,
            "latest_report": matched_reports[0] if matched_reports else None,
            "report_status": "official_update_available" if matched_reports else "none",
        }
        flat_waters.append(water)

    counties: list[dict[str, Any]] = []
    for county in COUNTIES:
        waters = [row for row in flat_waters if row["county"] == county]
        counties.append({
            "county_number": COUNTY_NUMBER[county],
            "county": county,
            "public_water_count": len(waters),
            "verified_access_point_count": sum(row["access_point_count"] for row in waters),
            "report_count": sum(row["report_count"] for row in waters),
            "waters": waters,
        })

    flat_reports = sorted(reports, key=lambda r: clean(r.get("report_date")), reverse=True)
    return {
        "metadata": {
            "state": REGION,
            "jurisdiction_state": STATE,
            "state_abbr": STATE_ABBR,
            "region_type": "substate_northern_county_boundary",
            "generated_at": generated_at,
            "public_access_only": True,
            "access_scope": "named official facility or location only",
            "county_scope_rule": "Marin, Napa, Solano, Sacramento and El Dorado counties, plus all California counties north of them",
            "included_counties": COUNTIES,
            "excluded_southern_counties": EXCLUDED_COUNTIES,
            "regulations_url": OFFICIAL["regulations"],
            "builder_version": BUILDER_VERSION,
            "source_audits": audits,
        },
        "county_count": len(COUNTIES),
        "public_water_count": len(flat_waters),
        "verified_access_point_count": sum(row["access_point_count"] for row in flat_waters),
        "report_count": len(flat_reports),
        "counties": counties,
        "flat_waters": flat_waters,
        "flat_reports": flat_reports,
    }


def validate_database(db: dict[str, Any], *, require_live_data: bool) -> dict[str, Any]:
    errors: list[str] = []
    if db.get("county_count") != 26:
        errors.append("county_count must equal 26")
    names = [row.get("county") for row in db.get("counties", [])]
    if names != COUNTIES:
        errors.append("county list/order does not match locked Northern California scope")
    emitted_counties = {row.get("county") for row in db.get("flat_waters", [])}
    forbidden = sorted(emitted_counties.intersection(EXCLUDED_COUNTIES))
    if forbidden:
        errors.append(f"southern/out-of-scope counties emitted: {forbidden}")
    for water in db.get("flat_waters", []):
        if water.get("county") not in COUNTIES:
            errors.append(f"out-of-scope water county: {water.get('county')}")
        if not water.get("access_points"):
            errors.append(f"water missing verified access: {water.get('water_name')}")
        for point in water.get("access_points", []):
            if point.get("public_access_status") != "verified_public":
                errors.append(f"access not verified public: {point.get('access_point_name')}")
            if point.get("entire_shoreline_public") is not False:
                errors.append(f"entire_shoreline_public must be false: {point.get('access_point_name')}")
            if not clean(point.get("official_source_url")).startswith("https://"):
                errors.append(f"missing official https source: {point.get('access_point_name')}")
    if require_live_data and db.get("public_water_count", 0) < 20:
        errors.append("live build produced fewer than 20 verified waters")
    unique_access = {
        point["access_id"]
        for water in db.get("flat_waters", [])
        for point in water.get("access_points", [])
    }
    if len(unique_access) != db.get("verified_access_point_count"):
        errors.append("verified_access_point_count does not equal unique access IDs")
    return {
        "passed": not errors,
        "errors": errors,
        "strict_public_access": True,
        "county_count": db.get("county_count", 0),
        "public_water_count": db.get("public_water_count", 0),
        "verified_access_point_count": db.get("verified_access_point_count", 0),
        "report_count": db.get("report_count", 0),
        "populated_counties": sum(1 for row in db.get("counties", []) if row.get("public_water_count", 0) > 0),
        "southern_counties_blocked": len(EXCLUDED_COUNTIES),
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_js(path: Path, variable: str, data: Any, comment: str = "Automatically generated data. Do not hand-edit.") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"/* {comment} */\nwindow.{variable} = {json.dumps(data, indent=2, ensure_ascii=False)};\n", encoding="utf-8")


def write_counties(root: Path, output_dir: Path) -> None:
    config = {"region": REGION, "state": STATE, "county_count": len(COUNTIES), "counties": [
        {"county_number": COUNTY_NUMBER[county], "county": county} for county in COUNTIES
    ], "excluded_southern_counties": EXCLUDED_COUNTIES}
    write_json(root / "config/northern_california_counties.json", config)
    with (output_dir / "northern_california_counties.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["county_number", "county"])
        for county in COUNTIES:
            writer.writerow([COUNTY_NUMBER[county], county])


def write_database_csv(path: Path, reports: list[dict[str, Any]]) -> None:
    fields = ["report_id", "report_date", "freshness", "county", "water_name", "source_type", "source_name", "official", "title", "summary", "species", "techniques", "source_url"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(reports)


def write_baseline_sources_csv(path: Path) -> None:
    fields = ["county", "water_name", "access_point_name", "official_source_url", "verification_evidence"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for county, water, access_name, url, evidence in SEED_ACCESS:
            writer.writerow({
                "county": county,
                "water_name": water,
                "access_point_name": access_name,
                "official_source_url": url,
                "verification_evidence": evidence,
            })


def _load_js_object(path: Path, variable: str) -> dict[str, Any]:
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


def rebuild_shared_feeds(root: Path, db: dict[str, Any]) -> None:
    generated = clean(db["metadata"]["generated_at"])
    row = {
        "state": REGION,
        "jurisdiction_state": STATE,
        "region_type": "substate_region",
        "report_count": int(db.get("report_count", 0)),
        "public_water_count": int(db.get("public_water_count", 0)),
        "county_count": int(db.get("county_count", 0)),
        "generated_at": generated,
    }
    recent_path = root / "recent_fishing_reports.js"
    recent = _load_js_object(recent_path, "window.FFO_RECENT_REPORTS")
    states = [item for item in recent.get("states", []) if clean(item.get("state")) != REGION]
    states.append(row)
    states.sort(key=lambda item: clean(item.get("state")))
    reports = [item for item in recent.get("reports", []) if clean(item.get("state")) != REGION]
    reports.extend(db.get("flat_reports", []))
    reports.sort(key=lambda item: clean(item.get("report_date")), reverse=True)
    recent.update({
        "version": f"{generated}-multi-state",
        "updated_at": max(clean(recent.get("updated_at")), generated),
        "states": states,
        "reports": reports,
    })
    write_js(recent_path, "FFO_RECENT_REPORTS", recent, "Automatically generated multi-state fishing report feed. Do not hand-edit.")

    status_path = root / "update_status.js"
    status = _load_js_object(status_path, "window.FFO_UPDATE_STATUS")
    status_rows = [item for item in status.get("states", []) if clean(item.get("state")) != REGION]
    status_rows.append(row)
    status_rows.sort(key=lambda item: clean(item.get("state")))
    status.update({
        "last_run": max(clean(status.get("last_run")), generated),
        "state_count": len(status_rows),
        "states": status_rows,
        # State-level report_count values in older datasets do not always equal
        # the deduplicated combined feed. Use the actual preserved report list.
        "reports_total": len(reports),
        "public_water_count": sum(int(item.get("public_water_count", 0) or 0) for item in status_rows),
        "county_count": sum(int(item.get("county_count", 0) or 0) for item in status_rows),
    })
    write_js(status_path, "FFO_UPDATE_STATUS", status, "Automatically generated multi-state admin status. Do not hand-edit.")


def write_outputs(root: Path, output_dir: Path, db: dict[str, Any], audits: dict[str, Any], validation: dict[str, Any], snapshot_type: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_counties(root, output_dir)
    write_json(output_dir / "northern_california_public_fishing_access.json", {
        "metadata": db["metadata"],
        "county_count": db["county_count"],
        "public_water_count": db["public_water_count"],
        "verified_access_point_count": db["verified_access_point_count"],
        "counties": db["counties"],
        "flat_waters": db["flat_waters"],
    })
    write_js(output_dir / "northern_california_public_fishing_access.js", "NORTHERN_CALIFORNIA_PUBLIC_FISHING_ACCESS", {
        "metadata": db["metadata"], "county_count": db["county_count"], "public_water_count": db["public_water_count"],
        "verified_access_point_count": db["verified_access_point_count"], "counties": db["counties"], "flat_waters": db["flat_waters"],
    })
    write_json(output_dir / "northern_california_fishing_report_database.json", db)
    write_js(output_dir / "northern_california_fishing_report_database.js", "NORTHERN_CALIFORNIA_FISHING_REPORT_DATABASE", db)
    write_database_csv(output_dir / "northern_california_fishing_report_database.csv", db["flat_reports"])
    write_baseline_sources_csv(output_dir / "northern_california_official_access_sources_2026-08-05.csv")
    write_json(output_dir / "northern_california_source_audit.json", {"region": REGION, "generated_at": db["metadata"]["generated_at"], "sources": audits})
    status = {
        "region": REGION,
        "jurisdiction_state": STATE,
        "generated_at": db["metadata"]["generated_at"],
        "deployment_status": "validated_complete_ready_to_commit" if validation["passed"] else "validation_failed",
        "snapshot_type": snapshot_type,
        "validation": validation,
        "scope": {"included_counties": COUNTIES, "excluded_southern_counties": EXCLUDED_COUNTIES},
        "source_counts": {
            "published_public_waters": db["public_water_count"],
            "verified_access_points": db["verified_access_point_count"],
            "official_reports": db["report_count"],
            "populated_counties": validation["populated_counties"],
            "all_county_shells": len(COUNTIES),
        },
    }
    write_json(output_dir / "northern_california_project_status.json", status)
    rebuild_shared_feeds(root, db)


def build_seed(root: Path, output_dir: Path) -> dict[str, Any]:
    generated = now_iso()
    audits = {
        "baseline": {
            "complete": True,
            "required": True,
            "source_name": "Individually verified official California public fishing/access pages",
            "record_count": len(SEED_ACCESS),
            "scope_note": "Checked-in safety baseline; daily workflow expands and refreshes it from official sources.",
        },
        "dbw_public_facilities": {"complete": False, "pending_first_live_refresh": True, "source_url": "https://dbw.parks.ca.gov/BoatingFacilities/"},
        "cdfw_fish_plantings": {"complete": False, "pending_first_live_refresh": True, "source_url": OFFICIAL["cdfw_planting_layer"]},
        "cdfw_public_piers": {"complete": False, "pending_first_live_refresh": True, "source_url": OFFICIAL["cdfw_public_piers_layer"]},
    }
    db = build_database(seed_access_rows(), [], audits, generated)
    validation = validate_database(db, require_live_data=False)
    if not validation["passed"]:
        raise RuntimeError("Seed validation failed: " + "; ".join(validation["errors"]))
    write_outputs(root, output_dir, db, audits, validation, "official_named_access_recovery_baseline")
    return db


def build_live(root: Path, output_dir: Path) -> dict[str, Any]:
    generated = now_iso()
    dbw_rows, dbw_audit = fetch_dbw_access()
    # DBW is the required live public-access source. Never replace the checked-in
    # baseline with a partial or unreachable county-index refresh.
    if not dbw_audit.get("complete") or int(dbw_audit.get("public_facilities_verified", 0) or 0) <= 0:
        raise RuntimeError("California DBW live refresh was incomplete; preserving the checked-in Northern California baseline")
    pier_rows, pier_audit = fetch_public_piers()
    reports, planting_audit = fetch_plantings()
    access_rows = seed_access_rows() + dbw_rows + pier_rows
    audits = {
        "dbw_public_facilities": dbw_audit,
        "cdfw_public_piers": pier_audit,
        "cdfw_fish_plantings": planting_audit,
        "baseline": {"complete": True, "record_count": len(SEED_ACCESS)},
    }
    db = build_database(access_rows, reports, audits, generated)
    validation = validate_database(db, require_live_data=True)
    if not validation["passed"]:
        raise RuntimeError("Northern California validation failed: " + "; ".join(validation["errors"]))
    write_outputs(root, output_dir, db, audits, validation, "live_official_california_refresh")
    return db


def self_test() -> None:
    if len(COUNTIES) != 26 or len(EXCLUDED_COUNTIES) != 32:
        raise AssertionError("County boundary must be 26 included and 32 excluded counties")
    assert canonical_county("El Dorado County") == "El Dorado"
    assert canonical_county("San Francisco") == ""
    assert set(COUNTIES).isdisjoint(EXCLUDED_COUNTIES)
    fixture = """
    <table><tr><th>Facility Name</th><th>Type</th><th>Access</th></tr>
    <tr><td><a href='/BoatingFacilities/f/739'>Brown's Ravine</a></td><td>Launch</td><td>Public</td></tr>
    <tr><td><a href='/BoatingFacilities/f/999'>Private Club</a></td><td>Marina</td><td>Private</td></tr></table>
    """
    if BeautifulSoup is not None:
        rows = parse_dbw_county_page(fixture, "https://dbw.parks.ca.gov/BoatingFacilities/County/El%20Dorado")
        assert len(rows) == 2 and rows[0]["detail_url"].endswith("/739")
        detail = """<h1>Brown's Ravine</h1><div>Facility Address: Brown's Ravine<br/>Body of Water: Folsom Lake<br/>County: El Dorado<br/>Type of Facility: Launch<br/>Open To: Public<br/>Jurisdiction/Authority: California State Parks</div>"""
        parsed = parse_dbw_detail(detail, rows[0]["detail_url"], rows[0])
        assert parsed["county"] == "El Dorado" and parsed["body_of_water"] == "Folsom Lake"
    audits = {"test": {"complete": True}}
    db = build_database(seed_access_rows(), [], audits, "2026-08-05T00:00:00Z")
    validation = validate_database(db, require_live_data=False)
    assert validation["passed"], validation
    assert db["county_count"] == 26
    assert all(row["county"] in COUNTIES for row in db["flat_waters"])
    assert not any(row["county"] in EXCLUDED_COUNTIES for row in db["flat_waters"])
    print("Northern California self-test passed")
    print("Included counties:", len(COUNTIES))
    print("Explicitly blocked southern counties:", len(EXCLUDED_COUNTIES))
    print("Seed verified waters:", db["public_water_count"])
    print("Seed verified access points:", db["verified_access_point_count"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--seed-baseline", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    root = args.root.resolve()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    db = build_seed(root, output_dir) if args.seed_baseline else build_live(root, output_dir)
    print(REGION, "counties:", db["county_count"])
    print(REGION, "verified waters:", db["public_water_count"])
    print(REGION, "verified access points:", db["verified_access_point_count"])
    print(REGION, "official reports:", db["report_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
