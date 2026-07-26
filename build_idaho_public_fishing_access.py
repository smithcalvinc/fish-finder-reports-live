#!/usr/bin/env python3
"""
Build an upload-ready Idaho public fishing access database from official
Idaho Fish and Game ArcGIS services.

Outputs:
  data/idaho_public_fishing_access.json
  data/idaho_public_fishing_access.js
  data/idaho_public_fishing_access.csv
  data/idaho_public_fishing_access_summary.csv
  data/public_access_build_report.json

The builder uses only official public-access sources:
- IDFG's current “Lakes and Reservoirs - Public” layer;
- IDFG's current “Rivers and Stream - Public” layer;
- active IDFG-managed or co-managed fishing/boating access sites.

The deprecated 100k Streams layer is used only as optional enrichment for FFW,
RFW and WaterID fields. It is never used to decide whether a stream is public.

It does NOT call a water public merely because the water exists on a map.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

COUNTIES = [
    "Ada","Adams","Bannock","Bear Lake","Benewah","Bingham","Blaine","Boise",
    "Bonner","Bonneville","Boundary","Butte","Camas","Canyon","Caribou","Cassia",
    "Clark","Clearwater","Custer","Elmore","Franklin","Fremont","Gem","Gooding",
    "Idaho","Jefferson","Jerome","Kootenai","Latah","Lemhi","Lewis","Lincoln",
    "Madison","Minidoka","Nez Perce","Oneida","Owyhee","Payette","Power",
    "Shoshone","Teton","Twin Falls","Valley","Washington"
]
COUNTY_NUMBER = {name: i + 1 for i, name in enumerate(COUNTIES)}

SOURCES = {
    "idfg_access_sites": {
        "name": "IDFG Fishing and Boating Access Sites Public",
        "page": "https://idfg.idaho.gov/visit/fish-boat-guide",
        "layer": "https://gisportal-idfg.idaho.gov/hosting/rest/services/Access/IDFG_Fishing_and_Boating_Access_Sites_Public/MapServer/0",
        "query": "https://gisportal-idfg.idaho.gov/hosting/rest/services/Access/IDFG_Fishing_and_Boating_Access_Sites_Public/MapServer/0/query",
        "description": "Active fishing and boating access sites managed or co-managed by Idaho Fish and Game."
    },
    "idfg_public_lakes": {
        "name": "IDFG Hydrography — Lakes and Reservoirs - Public",
        "page": "https://services.arcgis.com/FjJI5xHF2dUPVrgK/ArcGIS/rest/services/Hydrography_Public/FeatureServer/0",
        "layer": "https://services.arcgis.com/FjJI5xHF2dUPVrgK/ArcGIS/rest/services/Hydrography_Public/FeatureServer/0",
        "query": "https://services.arcgis.com/FjJI5xHF2dUPVrgK/ArcGIS/rest/services/Hydrography_Public/FeatureServer/0/query",
        "description": "Current official IDFG public lake and reservoir layer. Every downloaded record is already classified by IDFG as public."
    },
    "idfg_public_streams": {
        "name": "IDFG Hydrography — Rivers and Stream - Public",
        "page": "https://services.arcgis.com/FjJI5xHF2dUPVrgK/ArcGIS/rest/services/Hydrography_Public/FeatureServer/1",
        "layer": "https://services.arcgis.com/FjJI5xHF2dUPVrgK/ArcGIS/rest/services/Hydrography_Public/FeatureServer/1",
        "query": "https://services.arcgis.com/FjJI5xHF2dUPVrgK/ArcGIS/rest/services/Hydrography_Public/FeatureServer/1/query",
        "description": "Current official IDFG public river, creek and stream layer, including county membership."
    },
    "idfg_stream_attributes": {
        "name": "IDFG Hydrography — 100k Streams (deprecated enrichment only)",
        "page": "https://gisportal-idfg.idaho.gov/hosting/rest/services/Hydrography/Hydrography_Public/MapServer/4",
        "layer": "https://gisportal-idfg.idaho.gov/hosting/rest/services/Hydrography/Hydrography_Public/MapServer/4",
        "query": "https://gisportal-idfg.idaho.gov/hosting/rest/services/Hydrography/Hydrography_Public/MapServer/4/query",
        "description": "Optional legacy enrichment for FFW, RFW and WaterID. It is not used to determine public-access status."
    },
    "idfg_family_lakes": {
        "name": "IDFG Family Fishing Waters — Lakes and Ponds",
        "page": "https://gisportal-idfg.idaho.gov/hosting/rest/services/Fisheries/Family_Fishing_Waters/FeatureServer/1",
        "layer": "https://gisportal-idfg.idaho.gov/hosting/rest/services/Fisheries/Family_Fishing_Waters/FeatureServer/1",
        "query": "https://gisportal-idfg.idaho.gov/hosting/rest/services/Fisheries/Family_Fishing_Waters/FeatureServer/1/query",
        "description": "Optional Family Fishing Water enrichment."
    },
    "idfg_family_streams": {
        "name": "IDFG Family Fishing Waters — Rivers and Streams",
        "page": "https://gisportal-idfg.idaho.gov/hosting/rest/services/Fisheries/Family_Fishing_Waters/FeatureServer/2",
        "layer": "https://gisportal-idfg.idaho.gov/hosting/rest/services/Fisheries/Family_Fishing_Waters/FeatureServer/2",
        "query": "https://gisportal-idfg.idaho.gov/hosting/rest/services/Fisheries/Family_Fishing_Waters/FeatureServer/2/query",
        "description": "Optional Family Fishing Water enrichment."
    }
}

USER_AGENT = "FishFinderOutdoors-PublicAccessBuilder/1.0 (+https://fishfinderoutdoors.com)"
PRIVATE_BLOCK_PATTERNS = (
    "no public access",
    "public access prohibited",
    "access is prohibited",
    "closed to public",
    "private access only",
)
WATER_TERMS = ("lake", "reservoir", "pond", "river", "creek", "stream", "slough", "canal")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def norm_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_text(value).lower())


def public_value(value: Any) -> bool:
    text = clean_text(value).lower()
    return text == "public" or text.startswith("public ")


def active_value(value: Any) -> bool:
    text = clean_text(value).lower()
    if not text:
        return True
    return text not in {"closed", "inactive", "retired", "deleted", "abandoned"}


def boolish(value: Any) -> bool | None:
    text = clean_text(value).lower()
    if not text:
        return None
    if text in {"yes", "y", "true", "1", "available", "accessible", "handicap accessible"}:
        return True
    if text in {"no", "n", "false", "0", "none", "not available"}:
        return False
    if any(x in text for x in ("yes", "available", "accessible")):
        return True
    if any(x in text for x in ("no", "none", "not available")):
        return False
    return None


def split_counties(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    text = re.sub(r"\bCount(?:y|ies)\b", "", text, flags=re.I)
    bits = re.split(r"\s*(?:,|;|/|&|\band\b)\s*", text)
    found: list[str] = []
    for bit in bits:
        key = norm_key(bit)
        for county in COUNTIES:
            if key == norm_key(county):
                if county not in found:
                    found.append(county)
                break
    # Some source values are a sentence or a compact list.
    if not found:
        lower = text.lower()
        for county in COUNTIES:
            if re.search(rf"\b{re.escape(county.lower())}\b", lower):
                found.append(county)
    return found


def water_type(name: str, default: str) -> str:
    n = name.lower()
    for term in ("reservoir", "lake", "pond", "river", "creek", "stream", "slough", "canal"):
        if re.search(rf"\b{term}\b", n):
            return term
    return default


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return round(float(value), 7)
    except (TypeError, ValueError):
        return None


def first_nonempty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def extract_water_name(site_name: str, notes: str) -> tuple[str, str]:
    combined = f"{site_name}. {notes}"
    patterns = [
        r"(?:provides?|offers?|allows?)\s+(?:public\s+)?access\s+to\s+(?:the\s+)?([^.;]+)",
        r"(?:located|situated)\s+(?:directly\s+)?(?:on|along|at)\s+(?:the\s+)?([^.;]+)",
        r"(?:access point|boat ramp|fishing access)\s+(?:on|for|to)\s+(?:the\s+)?([^.;]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, combined, flags=re.I)
        if match:
            candidate = clean_text(match.group(1))
            candidate = re.split(r"\s+(?:with|and includes|near|where)\s+", candidate, maxsplit=1, flags=re.I)[0]
            if any(term in candidate.lower() for term in WATER_TERMS):
                return candidate[:120], "parsed_from_official_notes"
    # Remove common access-site suffixes and use the remainder only when it still
    # resembles a named water.
    candidate = re.sub(
        r"\b(?:fishing|boating|boat|river|lake)?\s*(?:access|site|ramp|park|campground)\b.*$",
        "",
        site_name,
        flags=re.I,
    ).strip(" -–—,")
    if candidate and any(term in site_name.lower() for term in WATER_TERMS):
        return candidate[:120], "derived_from_access_site_name"
    return "", "not_identified"


def note_flags(notes: str) -> dict[str, bool]:
    n = notes.lower()
    return {
        "foot_access_only": any(x in n for x in ("foot traffic only", "walk-in only", "walk in only", "non-motorized access")),
        "day_use_only": "day use" in n or "day-use" in n,
        "pack_in_pack_out": any(x in n for x in ("pack it in", "pack out", "no garbage service")),
        "private_land_nearby": "private" in n,
        "seasonal_language": any(x in n for x in ("seasonal", "winter closure", "closed during", "open from", "open may")),
        "fee_language": any(x in n for x in ("fee", "daily use charge", "parking charge")),
    }


def request_json(url: str, params: dict[str, Any], retries: int = 4) -> dict[str, Any]:
    full_url = f"{url}?{urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = Request(full_url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urlopen(req, timeout=90) as response:
                raw = response.read().decode("utf-8")
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("error"):
                raise RuntimeError(f"ArcGIS error: {payload['error']}")
            return payload
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Unable to retrieve {url}: {last_error}")


def fetch_all(
    query_url: str,
    out_fields: str,
    *,
    where: str = "1=1",
    return_geometry: bool = False,
    page_size: int = 1800,
    order_field: str = "OBJECTID",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": str(return_geometry).lower(),
            "outSR": 4326,
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "orderByFields": order_field,
            "f": "json",
        }
        payload = request_json(query_url, params)
        features = payload.get("features") or []
        for feature in features:
            attrs = dict(feature.get("attributes") or {})
            if return_geometry:
                attrs["_geometry"] = feature.get("geometry")
            records.append(attrs)
        exceeded = bool(payload.get("exceededTransferLimit"))
        if not features or (len(features) < page_size and not exceeded):
            break
        offset += len(features)
        if len(features) == 0:
            break
    return records


def load_fixture(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return payload.get("features", payload.get("records", []))


def family_sets(lakes: list[dict[str, Any]], streams: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    lake_keys = {norm_key(first_nonempty(r.get("NAME"), r.get("Variant"))) for r in lakes}
    stream_keys = {norm_key(first_nonempty(r.get("NAME"), r.get("PName"))) for r in streams}
    lake_keys.discard("")
    stream_keys.discard("")
    return lake_keys, stream_keys


def make_lake_records(rows: list[dict[str, Any]], family_keys: set[str], generated_at: str) -> list[dict[str, Any]]:
    """Convert IDFG's already-public lake layer into county water records."""
    result = []
    for row in rows:
        notes = clean_text(row.get("NOTE"))
        # The source layer itself is authoritative, but do not publish a record if
        # its own note explicitly contradicts public access.
        if any(pattern in notes.lower() for pattern in PRIVATE_BLOCK_PATTERNS):
            continue
        name = first_nonempty(row.get("NAME"), row.get("GNIS_Name"), row.get("Variant"), row.get("VARIANT2"))
        if not name:
            continue
        counties = split_counties(row.get("COUNTY_NAME"))
        if not counties:
            continue
        lat = safe_float(first_nonempty(row.get("DD_Y"), row.get("LAT")))
        lon = safe_float(first_nonempty(row.get("DD_X"), row.get("LONG")))
        base = {
            "record_kind": "waterbody",
            "water_name": name,
            "alternate_names": [x for x in [clean_text(row.get("Variant")), clean_text(row.get("VARIANT2")), clean_text(row.get("GNIS_Name"))] if x and x.lower() != name.lower()],
            "water_type": water_type(name, "lake_or_reservoir"),
            "all_counties": counties,
            "drainage": first_nonempty(row.get("DRAINAGE_NAME"), row.get("BASIN_NAME")),
            "acres": safe_float(row.get("Acres")),
            "latitude": lat,
            "longitude": lon,
            "public_access": True,
            "public_access_verification": "official_IDFG_public_hydrography_layer",
            "family_fishing_water": boolish(row.get("FFW")) is True or norm_key(name) in family_keys,
            "recommended_fishing_water": boolish(row.get("RFW")),
            "facilities_inventoried": False,
            "access_details": notes,
            "amenities": {
                "camping": None, "restroom": None, "boat_ramp": None,
                "dock": None, "ada_fishing": None
            },
            "official_source_name": SOURCES["idfg_public_lakes"]["name"],
            "official_source_url": SOURCES["idfg_public_lakes"]["page"],
            "source_record_id": str(row.get("OBJECTID") or row.get("GlobalID") or ""),
            "source_water_id": clean_text(row.get("LLID")),
            "last_generated": generated_at,
        }
        for county in counties:
            rec = dict(base)
            rec["county_number"] = COUNTY_NUMBER[county]
            rec["county"] = county
            rec["record_id"] = f"water-lake-{norm_key(name)}-{norm_key(county)}-{rec['source_record_id']}"
            result.append(rec)
    return result

def make_stream_records(
    public_rows: list[dict[str, Any]],
    attribute_rows: list[dict[str, Any]],
    family_keys: set[str],
    generated_at: str,
) -> list[dict[str, Any]]:
    """Build streams from the current IDFG public layer.

    The deprecated 100k layer is joined only for optional FFW/RFW/WaterID
    enrichment. Its Access and STATUS fields are deliberately ignored.
    """
    attributes_by_llid: dict[str, dict[str, Any]] = {}
    attributes_by_name: dict[str, dict[str, Any]] = {}
    for row in attribute_rows:
        llid = clean_text(row.get("LLID"))
        if llid and llid not in attributes_by_llid:
            attributes_by_llid[llid] = row
        key = norm_key(first_nonempty(row.get("NAME"), row.get("PNAME"), row.get("VARIANT2")))
        if key and key not in attributes_by_name:
            attributes_by_name[key] = row

    result = []
    for row in public_rows:
        name = first_nonempty(row.get("NAME"), row.get("PName"))
        if not name:
            continue
        counties = split_counties(row.get("Counties"))
        if not counties:
            continue
        legacy = attributes_by_llid.get(clean_text(row.get("LLID"))) or attributes_by_name.get(norm_key(name)) or {}
        notes = clean_text(legacy.get("NOTE"))
        # Do not carry a stale legacy note that contradicts the current public layer.
        if any(pattern in notes.lower() for pattern in PRIVATE_BLOCK_PATTERNS):
            notes = ""
        alternates = []
        for candidate in (
            row.get("Variants"), row.get("PName"), legacy.get("VARIANT"),
            legacy.get("VARIANT2"), legacy.get("PNAME")
        ):
            value = clean_text(candidate)
            if value and value.lower() != name.lower() and value not in alternates:
                alternates.append(value)
        base = {
            "record_kind": "waterbody",
            "water_name": name,
            "alternate_names": alternates,
            "water_type": water_type(name, "river_creek_or_stream"),
            "all_counties": counties,
            "drainage": clean_text(row.get("Drainage")),
            "acres": None,
            "latitude": None,
            "longitude": None,
            "public_access": True,
            "public_access_verification": "official_IDFG_public_hydrography_layer",
            "family_fishing_water": boolish(legacy.get("FFW")) is True or norm_key(name) in family_keys,
            "recommended_fishing_water": boolish(legacy.get("RFW")),
            "facilities_inventoried": False,
            "access_details": notes,
            "amenities": {
                "camping": None, "restroom": None, "boat_ramp": None,
                "dock": None, "ada_fishing": None
            },
            "official_source_name": SOURCES["idfg_public_streams"]["name"],
            "official_source_url": SOURCES["idfg_public_streams"]["page"],
            "source_record_id": str(row.get("OBJECTID") or row.get("GlobalID") or ""),
            "source_water_id": first_nonempty(legacy.get("WaterID"), row.get("LLID")),
            "last_generated": generated_at,
        }
        for county in counties:
            rec = dict(base)
            rec["county_number"] = COUNTY_NUMBER[county]
            rec["county"] = county
            rec["record_id"] = f"water-stream-{norm_key(name)}-{norm_key(county)}-{rec['source_record_id']}"
            result.append(rec)
    return result

def make_access_records(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if clean_text(row.get("status")).lower() != "active":
            continue
        counties = split_counties(row.get("county"))
        if not counties:
            continue
        site = clean_text(row.get("site_name"))
        if not site:
            continue
        notes = clean_text(row.get("public_info_notes"))
        water_name, match_status = extract_water_name(site, notes)
        amenities = {
            "camping": boolish(row.get("camp")),
            "restroom": boolish(row.get("rest")),
            "boat_ramp": boolish(row.get("ramp")),
            "dock": boolish(row.get("dock")),
            "ada_fishing": boolish(row.get("ada_fish")),
        }
        raw_amenities = {
            "camping": clean_text(row.get("camp")),
            "restroom": clean_text(row.get("rest")),
            "boat_ramp": clean_text(row.get("ramp")),
            "dock": clean_text(row.get("dock")),
            "ada_fishing": clean_text(row.get("ada_fish")),
        }
        flags = note_flags(notes)
        lat = safe_float(row.get("dd_y"))
        lon = safe_float(row.get("dd_x"))
        base = {
            "record_kind": "access_point",
            "access_point_name": site,
            "water_name": water_name,
            "water_name_match_status": match_status,
            "water_type": water_type(water_name or site, "unknown"),
            "all_counties": counties,
            "access_status": "Active",
            "access_category": clean_text(row.get("fishing_boating")) or "Fishing/Boating",
            "public_access": True,
            "public_access_verification": "active_official_IDFG_managed_or_co_managed_access_site",
            "latitude": lat,
            "longitude": lon,
            "directions_url": f"https://www.google.com/maps/search/?api=1&query={lat},{lon}" if lat is not None and lon is not None else "",
            "access_details": notes,
            "amenities": amenities,
            "amenities_raw": raw_amenities,
            "access_flags": flags,
            "official_source_name": SOURCES["idfg_access_sites"]["name"],
            "official_source_url": SOURCES["idfg_access_sites"]["page"],
            "official_layer_url": SOURCES["idfg_access_sites"]["layer"],
            "source_record_id": str(row.get("objectid") or ""),
            "source_site_id": str(row.get("ID") or ""),
            "last_generated": generated_at,
        }
        for county in counties:
            rec = dict(base)
            rec["county_number"] = COUNTY_NUMBER[county]
            rec["county"] = county
            rec["record_id"] = f"access-{norm_key(site)}-{norm_key(county)}-{rec['source_record_id']}"
            result.append(rec)
    return result


def dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated hydrography segments into one water per county/name."""
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in sorted(
        records,
        key=lambda r: (
            r.get("county_number", 999),
            r.get("record_kind", ""),
            r.get("water_name", ""),
            r.get("access_point_name", ""),
            r.get("source_record_id", ""),
        ),
    ):
        if record.get("record_kind") == "waterbody":
            key = (
                record.get("county"),
                "waterbody",
                norm_key(record.get("water_name")),
                record.get("water_type"),
            )
        else:
            key = (
                record.get("county"),
                record.get("record_kind"),
                norm_key(record.get("water_name")),
                norm_key(record.get("access_point_name")),
                record.get("source_record_id"),
            )
        existing = merged.get(key)
        if existing is None:
            merged[key] = record
            continue
        # Preserve useful enrichment when multiple source segments describe the
        # same named water in the same county.
        existing["family_fishing_water"] = bool(existing.get("family_fishing_water") or record.get("family_fishing_water"))
        if existing.get("recommended_fishing_water") is not True and record.get("recommended_fishing_water") is True:
            existing["recommended_fishing_water"] = True
        for field in ("latitude", "longitude", "acres", "drainage", "access_details", "source_water_id"):
            if existing.get(field) in (None, "") and record.get(field) not in (None, ""):
                existing[field] = record[field]
        names = list(existing.get("alternate_names") or [])
        for value in record.get("alternate_names") or []:
            if value and value not in names:
                names.append(value)
        existing["alternate_names"] = names
    return list(merged.values())

def write_outputs(output_dir: Path, records: list[dict[str, Any]], generated_at: str, build_report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["county"]].append(record)

    counties = []
    for number, county in enumerate(COUNTIES, start=1):
        county_records = grouped.get(county, [])
        waters = [r for r in county_records if r["record_kind"] == "waterbody"]
        access_points = [r for r in county_records if r["record_kind"] == "access_point"]
        counties.append({
            "county_number": number,
            "county": county,
            "water_count": len(waters),
            "access_point_count": len(access_points),
            "waters": waters,
            "access_points": access_points,
        })

    payload = {
        "metadata": {
            "title": "Idaho Public Fishing Waters and Access Points",
            "version": "1.1",
            "generated_at": generated_at,
            "county_order": "1 Ada through 44 Washington",
            "public_only": True,
            "scope": (
                "Officially documented Idaho Fish and Game public-access waters "
                "and active IDFG-managed or co-managed fishing/boating access sites."
            ),
            "important_limit": (
                "No statewide source proves every lawful access point managed by every "
                "federal, tribal, county, city, irrigation, utility, or private-easement "
                "owner. Records without explicit public-access evidence are excluded."
            ),
            "sources": SOURCES,
        },
        "county_count": len(COUNTIES),
        "record_count": len(records),
        "counties": counties,
        "flat_records": records,
    }

    json_path = output_dir / "idaho_public_fishing_access.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    js_path = output_dir / "idaho_public_fishing_access.js"
    js_path.write_text(
        "/* Automatically generated. Do not hand-edit. */\n"
        "window.IDAHO_PUBLIC_FISHING_ACCESS = "
        + json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )

    csv_fields = [
        "county_number","county","record_kind","water_name","water_type",
        "access_point_name","access_status","access_category","latitude","longitude",
        "camping","restroom","boat_ramp","dock","ada_fishing",
        "foot_access_only","day_use_only","pack_in_pack_out","private_land_nearby",
        "public_access_verification","water_name_match_status","access_details",
        "directions_url","official_source_name","official_source_url",
        "source_record_id","source_water_id","source_site_id","last_generated"
    ]
    with (output_dir / "idaho_public_fishing_access.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        for r in records:
            amenities = r.get("amenities") or {}
            flags = r.get("access_flags") or {}
            writer.writerow({
                "county_number": r.get("county_number"),
                "county": r.get("county"),
                "record_kind": r.get("record_kind"),
                "water_name": r.get("water_name"),
                "water_type": r.get("water_type"),
                "access_point_name": r.get("access_point_name", ""),
                "access_status": r.get("access_status", ""),
                "access_category": r.get("access_category", ""),
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude"),
                "camping": amenities.get("camping"),
                "restroom": amenities.get("restroom"),
                "boat_ramp": amenities.get("boat_ramp"),
                "dock": amenities.get("dock"),
                "ada_fishing": amenities.get("ada_fishing"),
                "foot_access_only": flags.get("foot_access_only"),
                "day_use_only": flags.get("day_use_only"),
                "pack_in_pack_out": flags.get("pack_in_pack_out"),
                "private_land_nearby": flags.get("private_land_nearby"),
                "public_access_verification": r.get("public_access_verification"),
                "water_name_match_status": r.get("water_name_match_status", ""),
                "access_details": r.get("access_details", ""),
                "directions_url": r.get("directions_url", ""),
                "official_source_name": r.get("official_source_name"),
                "official_source_url": r.get("official_source_url"),
                "source_record_id": r.get("source_record_id"),
                "source_water_id": r.get("source_water_id", ""),
                "source_site_id": r.get("source_site_id", ""),
                "last_generated": r.get("last_generated"),
            })

    with (output_dir / "idaho_public_fishing_access_summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["county_number","county","water_count","access_point_count","total_records"])
        writer.writeheader()
        for block in counties:
            writer.writerow({
                "county_number": block["county_number"],
                "county": block["county"],
                "water_count": block["water_count"],
                "access_point_count": block["access_point_count"],
                "total_records": block["water_count"] + block["access_point_count"],
            })

    (output_dir / "public_access_build_report.json").write_text(
        json.dumps(build_report, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data")
    parser.add_argument(
        "--fixtures-dir",
        help="Offline testing directory containing access_sites.json, lakes.json, "
             "stream_access.json, stream_counties.json, family_lakes.json, family_streams.json",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    generated_at = now_iso()
    report: dict[str, Any] = {
        "generated_at": generated_at,
        "success": False,
        "source_counts": {},
        "warnings": [],
        "errors": [],
    }

    try:
        if args.fixtures_dir:
            fdir = Path(args.fixtures_dir)
            access_sites = load_fixture(fdir / "access_sites.json")
            lakes = load_fixture(fdir / "lakes.json")
            stream_attributes = load_fixture(fdir / "stream_access.json")
            stream_public = load_fixture(fdir / "stream_counties.json")
            family_lakes = load_fixture(fdir / "family_lakes.json")
            family_streams = load_fixture(fdir / "family_streams.json")
        else:
            access_sites = fetch_all(
                SOURCES["idfg_access_sites"]["query"],
                "region,status,site_name,public_info_notes,county,dd_x,dd_y,camp,rest,ramp,dock,ada_fish,fishing_boating,objectid,ID",
                order_field="objectid",
            )
            lakes = fetch_all(
                SOURCES["idfg_public_lakes"]["query"],
                "OBJECTID,NAME,Variant,VARIANT2,LLID,DRAINAGE_NAME,COUNTY_NAME,Acres,LONG,LAT,DD_X,DD_Y,NOTE,RFW,FFW,Access,GNIS_ID,GNIS_Name,GlobalID",
                order_field="OBJECTID",
            )
            stream_public = fetch_all(
                SOURCES["idfg_public_streams"]["query"],
                "OBJECTID,HydroID,LLID,NAME,Variants,PName,Drainage,Counties,Regions,Status,GlobalID",
                order_field="OBJECTID",
            )
            try:
                stream_attributes = fetch_all(
                    SOURCES["idfg_stream_attributes"]["query"],
                    "OBJECTID,LLID,NAME,PNAME,VARIANT,VARIANT2,NOTE,FFW,RFW,WaterID",
                    order_field="OBJECTID",
                )
            except Exception as exc:
                stream_attributes = []
                report["warnings"].append(
                    "Deprecated stream enrichment layer unavailable; current public streams "
                    f"will still be included without FFW/RFW enrichment: {exc}"
                )
            # These two Family Fishing Waters layers are useful enrichment, but
            # they are not required to build the verified public-access database.
            # IDFG's ArcGIS service can occasionally return a 400 query error for
            # these helper layers. The primary lake and stream sources already
            # include the official FFW field, so continue safely when either helper
            # layer is temporarily unavailable.
            try:
                family_lakes = fetch_all(
                    SOURCES["idfg_family_lakes"]["query"],
                    "OBJECTID,NAME,Variant,VARIANT2,LLID,COUNTY_NAME,REGION_ID,LONG,LAT",
                    order_field="OBJECTID",
                )
            except Exception as exc:
                family_lakes = []
                report["warnings"].append(
                    "Family Fishing Waters lake helper layer unavailable; "
                    f"using the official FFW field from the main lake source instead: {exc}"
                )

            try:
                family_streams = fetch_all(
                    SOURCES["idfg_family_streams"]["query"],
                    "OBJECTID,HydroID,LLID,NAME,Variants,Counties,Regions",
                    order_field="OBJECTID",
                )
            except Exception as exc:
                family_streams = []
                report["warnings"].append(
                    "Family Fishing Waters stream helper layer unavailable; "
                    f"using the official FFW field from the main stream source instead: {exc}"
                )

        report["source_counts"] = {
            "access_sites_downloaded": len(access_sites),
            "lakes_downloaded": len(lakes),
            "public_stream_rows_downloaded": len(stream_public),
            "stream_attribute_rows_downloaded": len(stream_attributes),
            "stream_access_rows_downloaded": len(stream_attributes),
            "stream_county_rows_downloaded": len(stream_public),
            "family_lakes_downloaded": len(family_lakes),
            "family_streams_downloaded": len(family_streams),
        }

        family_lake_keys, family_stream_keys = family_sets(family_lakes, family_streams)
        records = []
        records.extend(make_lake_records(lakes, family_lake_keys, generated_at))
        records.extend(make_stream_records(stream_public, stream_attributes, family_stream_keys, generated_at))
        records.extend(make_access_records(access_sites, generated_at))
        records = dedupe(records)

        invalid_counties = sorted({r.get("county") for r in records if r.get("county") not in COUNTIES})
        if invalid_counties:
            raise ValueError(f"Unknown county names in output: {invalid_counties}")

        report["output_record_count"] = len(records)
        report["water_record_count"] = sum(1 for r in records if r["record_kind"] == "waterbody")
        report["access_point_record_count"] = sum(1 for r in records if r["record_kind"] == "access_point")
        report["counties_with_no_records"] = [
            county for county in COUNTIES if not any(r["county"] == county for r in records)
        ]
        report["unmatched_access_point_water_names"] = sum(
            1 for r in records
            if r["record_kind"] == "access_point" and not r.get("water_name")
        )
        if report["counties_with_no_records"]:
            report["warnings"].append(
                "A county with zero records indicates a source-coverage gap or no matching "
                "explicit public-access record; it must not be interpreted as proof that "
                "the county has no public fishing."
            )
        report["success"] = True
        write_outputs(output_dir, records, generated_at, report)
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        report["errors"].append(str(exc))
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "public_access_build_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
