#!/usr/bin/env python3
"""Build the compact browser index used to enrich water-search access results.

The source JSON files are generated from official state-agency access layers.
This index keeps only matching and source-attribution fields; it does not turn
an entire shoreline public when an agency documents only a named access site.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "official_access_index.js"

STATE_SOURCES = [
    ("Idaho", "idaho", "Idaho Department of Fish and Game", "https://idfg.idaho.gov/ifwis/fishingPlanner/"),
    ("Montana", "montana", "Montana Fish, Wildlife & Parks", "https://fwp.mt.gov/fish/fishing-access"),
    ("Wyoming", "wyoming", "Wyoming Game and Fish Department", "https://wgfd.wyo.gov/fishing-boating/places-fish-wyoming"),
    ("Utah", "utah", "Utah Division of Wildlife Resources", "https://dwrapps.utah.gov/fishing/"),
    ("Nevada", "nevada", "Nevada Department of Wildlife", "https://fish.wildlifenv.com/"),
    ("Oregon", "oregon", "Oregon Department of Fish and Wildlife", "https://myodfw.com/fishing"),
    ("Washington", "washington", "Washington Department of Fish and Wildlife", "https://wdfw.wa.gov/places-to-go/water-access-sites"),
    ("California", "northern_california", "California Department of Fish and Wildlife", "https://wildlife.ca.gov/Fishing/Guide"),
    ("Colorado", "colorado", "Colorado Parks and Wildlife", "https://cpw.state.co.us/fishing"),
]

CONDITIONAL_PATTERN = re.compile(
    r"\b(?:entrance|parking|access|launch|day[- ]use|camping) fee\b|"
    r"\bfee applies\b|\bpermit required\b|\breservation required\b|"
    r"\bprivate property\b|\bproperty:\s*private\b|\bresort\b|"
    r"\bmembers? only\b|\bcustomers? only\b|\bseasonal(?:ly)?\b|"
    r"\baccess dates?\b|\blimited to\b|\bwalk[- ]in\b",
    re.I,
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).strip()


def short(value: Any, limit: int = 420) -> str:
    text = clean(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return round(float(value), 7)
    except (TypeError, ValueError):
        return None


def unique(values: list[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean(value)
        key = norm(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def access_points(row: dict[str, Any]) -> list[dict[str, Any]]:
    points = list(row.get("access_points") or [])
    if row.get("record_kind") == "access_point" or row.get("access_point_name"):
        points.insert(0, row)

    output: list[dict[str, Any]] = []
    for point in points:
        name = clean(point.get("access_point_name") or point.get("site_name") or point.get("name"))
        url = clean(point.get("official_source_url") or point.get("source_url") or point.get("url"))
        details = short(
            point.get("access_details")
            or point.get("verification_evidence")
            or point.get("description"),
            320,
        )
        if not (name or url or details):
            continue
        output.append(
            {
                "name": name,
                "source_url": url,
                "details": details,
                "lat": number(point.get("latitude")),
                "lon": number(point.get("longitude")),
            }
        )
    return output


def group_key(row: dict[str, Any]) -> str:
    name = norm(row.get("water_name"))
    source_id = clean(
        row.get("source_water_id")
        or row.get("water_id")
        or row.get("source_record_id")
    )
    lat = number(row.get("latitude"))
    lon = number(row.get("longitude"))
    county = norm(row.get("county"))
    if source_id:
        return f"{name}|source:{source_id}"
    if lat is not None and lon is not None:
        return f"{name}|point:{lat:.3f},{lon:.3f}"
    return f"{name}|county:{county}"


def exact_water_url(state: str, row: dict[str, Any]) -> str:
    """Return an exact agency water page when the official record exposes it."""
    if state == "Idaho":
        water_id = clean(row.get("source_water_id"))
        if re.fullmatch(r"\d{5,20}", water_id):
            return f"https://idfg.idaho.gov/ifwis/fishingplanner/water/{water_id}"
    for candidate in row.get("water_source_urls") or []:
        url = clean(candidate)
        if "/fishing/locations/" in url:
            return url
    return ""


def build_state(
    state: str,
    slug: str,
    default_source_name: str,
    default_source_url: str,
) -> list[dict[str, Any]]:
    source_path = ROOT / "data" / f"{slug}_public_fishing_access.json"
    database = json.loads(source_path.read_text(encoding="utf-8"))
    rows = database.get("flat_records") or database.get("flat_waters") or []
    grouped: dict[str, dict[str, Any]] = {}

    for row in rows:
        if row.get("public_access") is False:
            continue
        water_name = clean(row.get("water_name"))
        if len(norm(water_name)) < 2:
            continue

        key = group_key(row)
        entry = grouped.setdefault(
            key,
            {
                "name": water_name,
                "aliases": [],
                "counties": [],
                "type": clean(row.get("water_type") or "water"),
                "lat": number(row.get("latitude")),
                "lon": number(row.get("longitude")),
                "details": "",
                "verification": "",
                "source_name": "",
                "source_url": "",
                "water_url": exact_water_url(state, row),
                "access_sites": [],
            },
        )

        entry["aliases"] = unique(entry["aliases"] + list(row.get("alternate_names") or []))
        entry["counties"] = unique(
            entry["counties"]
            + [row.get("county")]
            + list(row.get("counties") or [])
            + list(row.get("all_counties") or [])
        )
        if entry["lat"] is None:
            entry["lat"] = number(row.get("latitude"))
        if entry["lon"] is None:
            entry["lon"] = number(row.get("longitude"))
        if not entry["details"]:
            entry["details"] = short(row.get("access_details"), 420)
        if not entry["verification"]:
            entry["verification"] = clean(row.get("public_access_verification"))
        if not entry["source_name"]:
            entry["source_name"] = clean(row.get("official_source_name"))
        if not entry["source_url"]:
            entry["source_url"] = clean(
                row.get("official_source_url") or row.get("official_access_source_url")
            )
        if not entry["water_url"]:
            entry["water_url"] = exact_water_url(state, row)
        entry["access_sites"].extend(access_points(row))

    output: list[dict[str, Any]] = []
    for entry in grouped.values():
        sites: list[dict[str, Any]] = []
        seen_sites: set[str] = set()
        for site in entry.pop("access_sites"):
            key = norm(site.get("name")) + "|" + clean(site.get("source_url"))
            if key in seen_sites:
                continue
            seen_sites.add(key)
            sites.append(site)
            if len(sites) == 5:
                break

        source_name = entry.pop("source_name") or next(
            (clean(site.get("source_name")) for site in sites if site.get("source_name")),
            "",
        ) or default_source_name
        source_url = entry.pop("source_url") or next(
            (clean(site.get("source_url")) for site in sites if site.get("source_url")),
            "",
        ) or default_source_url
        details = entry.pop("details")
        verification = entry.pop("verification")
        combined = " ".join(
            [details, verification]
            + [f"{site.get('name', '')} {site.get('details', '')}" for site in sites]
        )
        restricted = bool(CONDITIONAL_PATTERN.search(combined))

        site_names = unique([site.get("name") for site in sites])[:3]
        output.append(
            {
                **entry,
                "access_status": "restricted" if restricted else "open",
                "evidence": short(
                    next((site.get("details") for site in sites if site.get("details")), "")
                    or details,
                    320,
                ),
                "access_site_names": site_names,
                "source_name": source_name,
                "source_url": source_url,
                "method": f"official-{slug.replace('_', '-')}-access-index",
            }
        )

    output.sort(key=lambda item: (norm(item["name"]), ",".join(item["counties"]), item["lat"] or 0))
    return output


def main() -> None:
    states: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    for state, slug, agency, url in STATE_SOURCES:
        states[state] = build_state(state, slug, agency, url)
        counts[state] = len(states[state])

    sources: list[dict[str, str]] = []
    source_ids: dict[tuple[str, str], int] = {}
    for entries in states.values():
        for entry in entries:
            source_key = (entry.pop("source_name"), entry.pop("source_url"))
            if source_key not in source_ids:
                source_ids[source_key] = len(sources)
                sources.append({"name": source_key[0], "url": source_key[1]})
            entry["source"] = source_ids[source_key]

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "version": "2026-08-10-official-access-v1",
        "generated_at": generated_at,
        "coverage": list(states),
        "record_counts": counts,
        "sources": sources,
        "states": states,
    }
    text = (
        "/* Generated by build_official_access_index.py from official state access datasets. */\n"
        "window.FFO_OFFICIAL_ACCESS_INDEX="
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )
    OUTPUT.write_text(text, encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "states": counts, "bytes": len(text.encode("utf-8"))}, indent=2))


if __name__ == "__main__":
    main()
