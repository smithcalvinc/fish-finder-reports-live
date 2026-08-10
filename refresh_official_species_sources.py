#!/usr/bin/env python3
"""Refresh exact-water fish species from official state agency pages.

This is a build-time importer for the static FFO site. Browsers cannot safely
scrape fifty unrelated agency sites because of CORS and inconsistent formats,
so state adapters normalize official pages into one checked-in cache. An
adapter publishes a species only when the page is tied to the exact named
water; statewide fish lists are never used as a substitute.

Implemented page adapters:
  * Idaho Fish and Game Fishing Planner (exact WaterID from IDFG hydrography)
  * Colorado Parks and Wildlife exact fishery-survey documents
  * Nevada Department of Wildlife exact water pages
  * Washington Department of Fish and Wildlife lowland-lake pages

The cache is additive and failure-safe: a temporary agency outage does not
delete a previously verified record.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUTPUT = DATA / "official_species_sources.json"
USER_AGENT = "FishFinderOutdoors-OfficialSpeciesBuilder/1.0 (+https://fishfinderoutdoors.com)"
STILL_WATERS = {"lake", "lake_or_reservoir", "pond", "reservoir"}
CALIFORNIA_HML_LAYER = (
    "https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/"
    "biosds102_fmu/FeatureServer/0"
)
JINA_READER = "https://r.jina.ai/"


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).strip()


def slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean(value).lower()).strip("-")


def unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = clean(value)
        key = norm(label)
        if not label or not key or key in seen:
            continue
        seen.add(key)
        result.append(label)
    return result


def species_label(value: Any) -> str:
    label = clean(value)
    label = re.sub(r"\s*\([^)]*[a-z]{2,}\s+[a-z]{2,}[^)]*\)\s*$", "", label)
    label = re.sub(r"\s+-\s+Triploid\b", " — Triploid", label, flags=re.I)
    label = re.sub(r"\s+observed\s+in\s+\d{4}.*$", "", label, flags=re.I)
    if not label or norm(label) in {"species", "no stocking records found"}:
        return ""
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9 /'()×—.-]+", label):
        label = label.title()
    replacements = {
        "Kokanee Salmon": "Kokanee",
        "Mackinaw": "Lake Trout (Mackinaw)",
        "Small Mouth Bass": "Smallmouth Bass",
        "Large Mouth Bass": "Largemouth Bass",
    }
    return replacements.get(label, label)


def observed_common_name(value: Any) -> str:
    text = re.sub(r"\s+observed\s+in\s+\d{4}.*$", "", clean(value), flags=re.I)
    match = re.match(
        r"^(.+?)\s+[A-Z][a-z]+(?:\s+(?:[a-z][a-z.-]*|x)){1,5}$",
        text,
    )
    return species_label(match.group(1) if match else text)


class PageEvents(HTMLParser):
    """Collect only headings, list items and table rows from an agency page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, Any]] = []
        self.heading_tag = ""
        self.heading_text: list[str] = []
        self.li_depth = 0
        self.li_text: list[str] = []
        self.p_depth = 0
        self.p_text: list[str] = []
        self.row: list[str] | None = None
        self.cell_depth = 0
        self.cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and not self.heading_tag:
            self.heading_tag = tag
            self.heading_text = []
        if tag == "li":
            self.li_depth += 1
            if self.li_depth == 1:
                self.li_text = []
        if tag == "p":
            self.p_depth += 1
            if self.p_depth == 1:
                self.p_text = []
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"} and self.row is not None:
            self.cell_depth += 1
            if self.cell_depth == 1:
                self.cell_text = []

    def handle_data(self, data: str) -> None:
        if self.heading_tag:
            self.heading_text.append(data)
        if self.li_depth:
            self.li_text.append(data)
        if self.p_depth:
            self.p_text.append(data)
        if self.cell_depth:
            self.cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self.heading_tag:
            self.events.append((tag, clean(" ".join(self.heading_text))))
            self.heading_tag = ""
            self.heading_text = []
        if tag == "li" and self.li_depth:
            self.li_depth -= 1
            if self.li_depth == 0:
                self.events.append(("li", clean(" ".join(self.li_text))))
                self.li_text = []
        if tag == "p" and self.p_depth:
            self.p_depth -= 1
            if self.p_depth == 0:
                self.events.append(("p", clean(" ".join(self.p_text))))
                self.p_text = []
        if tag in {"td", "th"} and self.cell_depth:
            self.cell_depth -= 1
            if self.cell_depth == 0 and self.row is not None:
                self.row.append(clean(" ".join(self.cell_text)))
                self.cell_text = []
        if tag == "tr" and self.row is not None:
            self.events.append(("row", self.row))
            self.row = None


def page_events(html: str) -> list[tuple[str, Any]]:
    parser = PageEvents()
    parser.feed(html)
    return parser.events


def section_events(events: list[tuple[str, Any]], phrase: str) -> list[tuple[str, Any]]:
    target = norm(phrase)
    start = next(
        (index for index, (kind, value) in enumerate(events) if kind.startswith("h") and target in norm(value)),
        None,
    )
    if start is None:
        return []
    result: list[tuple[str, Any]] = []
    for event in events[start + 1:]:
        if event[0].startswith("h"):
            break
        result.append(event)
    return result


def parse_idaho(html: str, expected_name: str = "") -> list[str]:
    events = page_events(html)
    heading_text = next((value for kind, value in events if kind == "h1"), "")
    if expected_name and heading_text and norm(expected_name) not in norm(heading_text):
        return []

    species: list[str] = []
    for kind, value in section_events(events, "Recommended Game Fish"):
        if kind != "li":
            continue
        text = clean(value)
        species.append(species_label(text.split(" (", 1)[0]))

    for kind, value in section_events(events, "Species Observed in Surveys"):
        if kind == "li":
            species.append(observed_common_name(value))

    for kind, cells in section_events(events, "Fish Stocking Records"):
        if kind != "row":
            continue
        if len(cells) >= 2 and re.fullmatch(r"\d{4}[/-]\d{2}[/-]\d{2}", cells[0]):
            species.append(species_label(cells[1]))
    return unique([value for value in species if value])


def parse_washington(html: str, expected_name: str = "", county: str = "") -> list[str]:
    events = page_events(html)
    heading_text = next((value for kind, value in events if kind == "h1"), "")
    if expected_name and norm(expected_name) not in norm(heading_text):
        return []
    if county and "county" in norm(heading_text) and norm(county) not in norm(heading_text):
        return []
    species = [
        species_label(value)
        for kind, value in section_events(events, "Species you might catch")
        if kind == "li"
    ]
    return unique([value for value in species if value])


NEVADA_SPECIES_PATTERNS = [
    (r"\barctic grayling\b", "Arctic Grayling"),
    (r"\bblack crapp(?:ie|ies)\b", "Black Crappie"),
    (r"\bbluegill\b", "Bluegill"),
    (r"\bbrook trout\b", "Brook Trout"),
    (r"\bbrown trout\b", "Brown Trout"),
    (r"\bbull trout\b", "Bull Trout"),
    (r"\bburbot\b", "Burbot"),
    (r"\bchannel catfish\b", "Channel Catfish"),
    (r"\bchinook(?: salmon)?\b", "Chinook Salmon"),
    (r"\bcoho(?: salmon)?\b", "Coho Salmon"),
    (r"\bcommon carp\b|\bcarp\b", "Common Carp"),
    (r"\bcutthroat trout\b", "Cutthroat Trout"),
    (r"\bkokanee\b", "Kokanee"),
    (r"\blake trout\b|\bmackinaw\b", "Lake Trout (Mackinaw)"),
    (r"\blargemouth bass\b", "Largemouth Bass"),
    (r"\bmountain whitefish\b", "Mountain Whitefish"),
    (r"\bnorthern pike\b", "Northern Pike"),
    (r"\brainbow trout\b", "Rainbow Trout"),
    (r"\bsmallmouth bass\b", "Smallmouth Bass"),
    (r"\bspotted bass\b", "Spotted Bass"),
    (r"\bstriped bass\b|\bstriper(?:s)?\b", "Striped Bass"),
    (r"\btiger muskie\b", "Tiger Muskie"),
    (r"\btiger trout\b", "Tiger Trout"),
    (r"\bwalleye\b", "Walleye"),
    (r"\bwhite bass\b", "White Bass"),
    (r"\bwhite catfish\b", "White Catfish"),
    (r"\bwhite crapp(?:ie|ies)\b", "White Crappie"),
    (r"\bwhite sturgeon\b", "White Sturgeon"),
    (r"\bwiper(?:s)?\b", "Wiper"),
    (r"\byellow perch\b", "Yellow Perch"),
]

# Exact CPW survey summaries can name both sport fish and forage/native fish.
# Keep this vocabulary conservative and species-level: a generic word such as
# "trout" or "warmwater" is never expanded into a made-up list.
COLORADO_SPECIES_PATTERNS = [
    (r"\barctic grayling\b", "Arctic Grayling"),
    (r"\bblack bullhead\b", "Black Bullhead"),
    (r"\bblack crapp(?:ie|ies)\b", "Black Crappie"),
    (r"\bbluegill\b", "Bluegill"),
    (r"\bbluehead sucker\b", "Bluehead Sucker"),
    (r"\bbrook trout\b", "Brook Trout"),
    (r"\bbrown bullhead\b", "Brown Bullhead"),
    (r"\bbrown trout\b", "Brown Trout"),
    (r"\bchannel catfish\b", "Channel Catfish"),
    (r"\bcolorado river cutthroat(?: trout)?\b", "Colorado River Cutthroat Trout"),
    (r"\bcommon carp\b", "Common Carp"),
    (r"\bcreek chub\b", "Creek Chub"),
    (r"\bcutbow(?: trout)?\b", "Cutbow Trout"),
    (r"\bfathead minnow\b", "Fathead Minnow"),
    (r"\bfreshwater drum\b", "Freshwater Drum"),
    (r"\bgizzard shad\b", "Gizzard Shad"),
    (r"\bgolden shiner\b", "Golden Shiner"),
    (r"\bgolden trout\b", "Golden Trout"),
    (r"\bgrass carp\b", "Grass Carp"),
    (r"\bgreen sunfish\b", "Green Sunfish"),
    (r"\bgreenback cutthroat(?: trout)?\b", "Greenback Cutthroat Trout"),
    (r"\bkokanee(?: salmon)?\b", "Kokanee"),
    (r"\blake chub\b", "Lake Chub"),
    (r"\blake trout\b|\bmackinaw\b", "Lake Trout (Mackinaw)"),
    (r"\blargemouth bass\b", "Largemouth Bass"),
    (r"\blongnose dace\b", "Longnose Dace"),
    (r"\blongnose sucker\b", "Longnose Sucker"),
    (r"\bmountain sucker\b", "Mountain Sucker"),
    (r"\bmountain whitefish\b", "Mountain Whitefish"),
    (r"\bnorthern pike\b", "Northern Pike"),
    (r"\bplains killifish\b", "Plains Killifish"),
    (r"\brainbow trout\b", "Rainbow Trout"),
    (r"\bred shiner\b", "Red Shiner"),
    (r"\brio grande chub\b", "Rio Grande Chub"),
    (r"\brio grande cutthroat(?: trout)?\b", "Rio Grande Cutthroat Trout"),
    (r"\broundtail chub\b", "Roundtail Chub"),
    (r"\bsauger\b", "Sauger"),
    (r"\bsaugeye\b", "Saugeye"),
    (r"\bsmallmouth bass\b", "Smallmouth Bass"),
    (r"\bsnake river cutthroat(?: trout)?\b", "Snake River Cutthroat Trout"),
    (r"\bspeckled dace\b", "Speckled Dace"),
    (r"\bsplake\b", "Splake"),
    (r"\bspotted bass\b", "Spotted Bass"),
    (r"\btiger musk(?:ie|y)\b", "Tiger Muskie"),
    (r"\btiger trout\b", "Tiger Trout"),
    (r"\bwalleye\b", "Walleye"),
    (r"\bwhite bass\b", "White Bass"),
    (r"\bwhite crapp(?:ie|ies)\b", "White Crappie"),
    (r"\bwhite sucker\b", "White Sucker"),
    (r"\bwiper(?:s)?\b|\bhybrid striped bass\b", "Wiper"),
    (r"\byellow bullhead\b", "Yellow Bullhead"),
    (r"\byellow perch\b", "Yellow Perch"),
    (r"\bcutthroat trout\b", "Cutthroat Trout"),
]


def parse_nevada(html: str, expected_name: str = "") -> list[str]:
    events = page_events(html)
    heading_text = next((value for kind, value in events if kind == "h1"), "")
    if expected_name and norm(expected_name) not in norm(heading_text):
        return []
    evidence: list[str] = []
    for phrase in ("Fishing Report", "Stocking Updates", "Pertinent Information"):
        for kind, value in section_events(events, phrase):
            if kind in {"p", "li"}:
                evidence.append(clean(value))
            elif kind == "row":
                evidence.extend(clean(cell) for cell in value)
    text = " ".join(evidence)
    return [label for pattern, label in NEVADA_SPECIES_PATTERNS if re.search(pattern, text, flags=re.I)]


def parse_colorado(text: str, expected_name: str = "") -> list[str]:
    """Read fish names only from a survey document for the exact named water."""
    normalized = norm(text)
    expected = norm(expected_name)
    if expected and expected not in normalized:
        # Survey titles sometimes omit the trailing water-type word.
        shortened = re.sub(r"\b(lake|reservoir|pond|impoundment)s?\b", "", expected)
        shortened = clean(shortened)
        if len(shortened) < 5 or shortened not in normalized:
            return []
    species = unique([
        label for pattern, label in COLORADO_SPECIES_PATTERNS
        if re.search(pattern, text, flags=re.I)
    ])
    if any(label.endswith("Cutthroat Trout") and label != "Cutthroat Trout" for label in species):
        species = [label for label in species if label != "Cutthroat Trout"]
    return species


def request_text(url: str, retries: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.7",
                },
            )
            with urlopen(request, timeout=35) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Unable to retrieve {url}: {last_error}")


def request_json(url: str, params: dict[str, Any] | None = None) -> dict:
    target = url + ("?" + urlencode(params or {}) if params else "")
    payload = json.loads(request_text(target))
    if not isinstance(payload, dict) or payload.get("error"):
        raise RuntimeError(f"Invalid ArcGIS response for {url}: {payload.get('error') if isinstance(payload, dict) else 'not an object'}")
    return payload


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def idaho_candidates() -> list[dict]:
    database = load_json(DATA / "idaho_public_fishing_access.json")
    grouped: dict[str, dict] = {}
    for row in database.get("flat_records", []):
        water_type = clean(row.get("water_type")).lower()
        water_id = clean(row.get("source_water_id"))
        name = clean(row.get("water_name"))
        if water_type not in STILL_WATERS or not name or not re.fullmatch(r"\d{5,20}", water_id):
            continue
        url = f"https://idfg.idaho.gov/ifwis/fishingplanner/water/{water_id}"
        record = grouped.setdefault(
            url,
            {
                "state": "Idaho",
                "name": name,
                "aliases": [],
                "counties": [],
                "lat": row.get("latitude"),
                "lon": row.get("longitude"),
                "urls": [url],
                "source_name": "Idaho Fish and Game — Fishing Planner",
                "parser": parse_idaho,
            },
        )
        record["aliases"] = unique(record["aliases"] + list(row.get("alternate_names") or []))
        record["counties"] = unique(
            record["counties"] + [row.get("county")] + list(row.get("all_counties") or [])
        )
    return sorted(grouped.values(), key=lambda row: (norm(row["name"]), row["urls"][0]))


def washington_candidates() -> list[dict]:
    database = load_json(DATA / "washington_public_fishing_access.json")
    candidates: list[dict] = []
    for row in database.get("flat_waters", []):
        water_type = clean(row.get("water_type")).lower()
        name = clean(row.get("water_name"))
        county = clean(row.get("county"))
        if water_type not in {"lake", "pond", "reservoir"} or not name:
            continue
        exact = [
            clean(url) for url in row.get("water_source_urls") or []
            if "/fishing/locations/" in clean(url)
        ]
        base = "https://wdfw.wa.gov/fishing/locations/lowland-lakes/"
        guessed = [base + slug(name) + ("-" + slug(county) if county else ""), base + slug(name)]
        candidates.append(
            {
                "state": "Washington",
                "name": name,
                "aliases": [],
                "counties": [county] if county else [],
                "county": county,
                "lat": row.get("latitude"),
                "lon": row.get("longitude"),
                "urls": unique(exact + guessed),
                "source_name": "Washington Department of Fish and Wildlife",
                "parser": parse_washington,
            }
        )
    return sorted(candidates, key=lambda row: (norm(row["name"]), norm(row.get("county"))))


def nevada_candidates() -> list[dict]:
    database = load_json(DATA / "nevada_public_fishing_access.json")
    candidates: list[dict] = []
    for row in database.get("flat_waters", []):
        name = clean(row.get("water_name"))
        county = clean(row.get("county"))
        reports = [row.get("latest_report"), *(row.get("recent_reports") or [])]
        urls: list[str] = []
        for candidate in [row.get("fishnv_source_url"), *(report.get("source_url") for report in reports if isinstance(report, dict))]:
            url = clean(candidate)
            if re.match(r"^https://(?:www\.)?ndow\.org/waters/[^/?#]+/?$", url, flags=re.I) and url not in urls:
                urls.append(url)
        if not name or not urls:
            continue
        candidates.append(
            {
                "state": "Nevada",
                "name": name,
                "aliases": [],
                "counties": [county] if county else [],
                "lat": row.get("latitude"),
                "lon": row.get("longitude"),
                "urls": urls,
                "source_name": "Nevada Department of Wildlife",
                "parser": parse_nevada,
            }
        )
    return sorted(candidates, key=lambda row: (norm(row["name"]), norm(row.get("counties"))))


def colorado_candidates() -> list[dict]:
    database = load_json(DATA / "colorado_fishing_report_database.json")
    grouped: dict[tuple[str, str], dict] = {}
    for row in database.get("flat_reports", []):
        name = clean(row.get("water_name"))
        url = clean(row.get("source_url"))
        if (
            row.get("official") is False
            or clean(row.get("source_type")) != "official_fishery_survey"
            or not re.match(r"^https://cpw\.state\.co\.us/.+\.pdf(?:[?#].*)?$", url, flags=re.I)
            or not name
            or name.startswith("[")
        ):
            continue
        counties = unique(list(row.get("counties") or []))
        key = (norm(name), url.lower())
        grouped[key] = {
            "state": "Colorado",
            "name": name,
            "aliases": [],
            "counties": counties,
            "urls": [url],
            "source_name": "Colorado Parks and Wildlife — Fishery Survey",
            "parser": parse_colorado,
            "reader": True,
            "evidence_type": "Exact CPW fishery-survey document",
            "note": "Fish named in the linked CPW survey for this exact water; a survey may be historical or incomplete and does not guarantee a current bite.",
        }
    return sorted(grouped.values(), key=lambda row: (norm(row["name"]), row["urls"][0]))


def california_high_mountain_lake_records() -> list[dict]:
    fields = "OBJECTID,SpeciesName,LakeName,SurveyDate,FishNotPresent,LatLong_X,LatLong_Y,CaLakesID,HML_ID"
    features: list[dict] = []
    offset = 0
    while True:
        payload = request_json(
            CALIFORNIA_HML_LAYER + "/query",
            {
                "where": "SpeciesName IS NOT NULL AND SpeciesName <> '' AND (FishNotPresent IS NULL OR FishNotPresent <> 'Y')",
                "outFields": fields,
                "returnGeometry": "false",
                "orderByFields": "OBJECTID",
                "resultOffset": offset,
                "resultRecordCount": 2000,
                "f": "json",
            },
        )
        batch = payload.get("features") or []
        features.extend(batch)
        if not payload.get("exceededTransferLimit") or not batch:
            break
        offset += len(batch)

    grouped: dict[tuple, dict] = {}
    for feature in features:
        attrs = feature.get("attributes") or {}
        name = clean(attrs.get("LakeName"))
        species = species_label(attrs.get("SpeciesName"))
        try:
            lat = round(float(attrs.get("LatLong_Y")), 6)
            lon = round(float(attrs.get("LatLong_X")), 6)
        except (TypeError, ValueError):
            continue
        lake_id = clean(attrs.get("CaLakesID") or attrs.get("HML_ID"))
        if not name or not species or not lake_id:
            continue
        key = (lake_id, norm(name), lat, lon)
        record = grouped.setdefault(
            key,
            {
                "name": name,
                "aliases": [],
                "counties": [],
                "species": [],
                "source_name": "California Department of Fish and Wildlife — High Mountain Lakes Fish Survey",
                "source_url": CALIFORNIA_HML_LAYER,
                "source_dataset": "cdfw_high_mountain_lakes_ds102",
                "source_record_id": lake_id,
                "evidence_type": "Exact named-water CDFW fish survey record",
                "note": "Fish observed in a CDFW survey of this exact named lake. Survey observations do not guarantee a current bite or a complete present-day inventory.",
                "status": "documented",
                "checked_at": datetime.now(timezone.utc).date().isoformat(),
                "lat": lat,
                "lon": lon,
                "survey_dates": [],
            },
        )
        record["species"] = unique(record["species"] + [species])
        raw_date = attrs.get("SurveyDate")
        if isinstance(raw_date, (int, float)):
            try:
                observed = datetime.fromtimestamp(float(raw_date) / 1000, tz=timezone.utc).date().isoformat()
                record["survey_dates"] = unique(record["survey_dates"] + [observed])
            except (ValueError, OSError, OverflowError):
                pass
    rows = list(grouped.values())
    for row in rows:
        row["species"].sort(key=str.casefold)
        row["survey_dates"].sort(reverse=True)
    return sorted(rows, key=lambda row: (norm(row["name"]), row["lat"], row["lon"]))


ADAPTERS: dict[str, Callable[[], list[dict]]] = {
    "Colorado": colorado_candidates,
    "Idaho": idaho_candidates,
    "Nevada": nevada_candidates,
    "Washington": washington_candidates,
}
BULK_ADAPTERS: dict[str, Callable[[], list[dict]]] = {
    "California": california_high_mountain_lake_records,
}


def checked_recently(record: dict, days: int) -> bool:
    try:
        checked = datetime.fromisoformat(clean(record.get("checked_at"))).date()
    except ValueError:
        return False
    return datetime.now(timezone.utc).date() - checked < timedelta(days=days)


def fetch_candidate(candidate: dict) -> tuple[dict | None, str]:
    errors: list[str] = []
    for url in candidate["urls"]:
        try:
            html = request_text((JINA_READER + url) if candidate.get("reader") else url)
            parser = candidate["parser"]
            if candidate["state"] == "Washington":
                species = parser(html, candidate["name"], candidate.get("county", ""))
            else:
                species = parser(html, candidate["name"])
            record = {
                "name": candidate["name"],
                "aliases": candidate.get("aliases", []),
                "counties": candidate.get("counties", []),
                "species": species,
                "source_name": candidate["source_name"],
                "source_url": url,
                "evidence_type": candidate.get("evidence_type") or "Exact official state water page",
                "note": candidate.get("note") or "Fish listed on the linked official page for this exact water; stocking or past survey evidence does not guarantee a current bite.",
                "status": "documented" if species else "no_species_published",
                "checked_at": datetime.now(timezone.utc).date().isoformat(),
            }
            for field in ("lat", "lon"):
                try:
                    record[field] = round(float(candidate.get(field)), 6)
                except (TypeError, ValueError):
                    pass
            return record, ""
        except Exception as error:  # keep trying exact candidate URLs
            errors.append(f"{url}: {error}")
    return None, " | ".join(errors)


def refresh(states: list[str], max_pages: int, workers: int, max_age_days: int) -> dict:
    payload = load_json(OUTPUT) if OUTPUT.exists() else {
        "version": "2026.08.10-v1",
        "generated_at": "",
        "coverage_note": "Exact official state water pages only.",
        "states": {},
    }
    payload.setdefault("states", {})
    summary: dict[str, dict] = {}
    updated_any = False

    for state in states:
        if state in BULK_ADAPTERS:
            existing_rows = payload["states"].get(state, []) or []
            dataset = "cdfw_high_mountain_lakes_ds102"
            current_dataset_rows = [row for row in existing_rows if row.get("source_dataset") == dataset]
            if current_dataset_rows and all(checked_recently(row, max_age_days) for row in current_dataset_rows):
                summary[state] = {
                    "requested": 0,
                    "documented": len(current_dataset_rows),
                    "failed": 0,
                    "cached_records": len(existing_rows),
                }
                continue
            try:
                records = BULK_ADAPTERS[state]()
            except Exception as error:
                summary[state] = {
                    "requested": 1,
                    "documented": 0,
                    "failed": 1,
                    "cached_records": len(existing_rows),
                    "failure_examples": [str(error)],
                }
                continue
            preserved = [row for row in existing_rows if row.get("source_dataset") != dataset]
            payload["states"][state] = sorted(
                preserved + records,
                key=lambda row: (norm(row.get("name")), clean(row.get("source_record_id")), clean(row.get("source_url"))),
            )
            summary[state] = {
                "requested": 1,
                "documented": len(records),
                "failed": 0,
                "cached_records": len(payload["states"][state]),
            }
            updated_any = True
            continue
        candidates = ADAPTERS[state]()
        existing_rows = payload["states"].get(state, []) or []
        existing = {clean(row.get("source_url")): row for row in existing_rows if clean(row.get("source_url"))}
        pending = [
            candidate for candidate in candidates
            if not any(checked_recently(existing.get(url, {}), max_age_days) for url in candidate["urls"])
        ]
        if max_pages > 0:
            pending = pending[:max_pages]

        refreshed: dict[str, dict] = dict(existing)
        failures: list[str] = []
        documented = empty = 0
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 12))) as executor:
            jobs = {executor.submit(fetch_candidate, candidate): candidate for candidate in pending}
            for future in as_completed(jobs):
                record, error = future.result()
                if record:
                    refreshed[record["source_url"]] = record
                    updated_any = True
                    if record["status"] == "documented":
                        documented += 1
                    else:
                        empty += 1
                elif error:
                    failures.append(error)

        rows = sorted(refreshed.values(), key=lambda row: (norm(row.get("name")), clean(row.get("source_url"))))
        payload["states"][state] = rows
        summary[state] = {
            "candidates": len(candidates),
            "requested": len(pending),
            "documented": documented,
            "no_species_published": empty,
            "failed": len(failures),
            "cached_records": len(rows),
            "failure_examples": failures[:5],
        }

    payload["version"] = "2026.08.10-v1"
    if updated_any or not payload.get("generated_at"):
        payload["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload["coverage_note"] = (
        "Water-specific species copied only from exact official government water pages. "
        "Empty or failed lookups are not converted into statewide assumptions."
    )
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT)
    return summary


def self_test() -> None:
    idaho = """
    <h1>Fixture Reservoir</h1><h4>Recommended Game Fish</h4>
    <ul><li>Rainbow Trout (Oncorhynchus mykiss)</li><li>Smallmouth Bass (Micropterus dolomieu)</li></ul>
    <h4>Species Observed in Surveys</h4><ul><li>Yellow Perch Perca flavescens observed in 2024</li></ul>
    <h4>Fish Stocking Records</h4><table><tr><th>Date</th><th>Species</th></tr>
    <tr><td>2026/06/03</td><td>White Sturgeon</td></tr></table><h4>Fishing Rules</h4>
    """
    assert parse_idaho(idaho, "Fixture Reservoir") == [
        "Rainbow Trout", "Smallmouth Bass", "Yellow Perch", "White Sturgeon"
    ]
    washington = """
    <h1>Fixture Lake (Mason County)</h1><h2>Species you might catch:</h2>
    <ul><li>Black crappie</li><li>Rainbow trout</li></ul><h2>Fishing resources</h2>
    """
    assert parse_washington(washington, "Fixture Lake", "Mason") == ["Black Crappie", "Rainbow Trout"]
    assert parse_washington(washington, "Fixture Lake", "King") == []
    nevada = """
    <h1>Fixture Reservoir</h1><h5>Fishing Report</h5><p>Walleye and channel catfish are active.</p>
    <h4>Stocking Updates</h4><table><tr><th>Stocked</th><th>Species</th></tr>
    <tr><td>2000</td><td>Wiper</td></tr></table><h2>Pertinent Information</h2>
    <p>Primary game fish include white bass and largemouth bass.</p>
    """
    assert parse_nevada(nevada, "Fixture Reservoir") == [
        "Channel Catfish", "Largemouth Bass", "Walleye", "White Bass", "Wiper"
    ]
    colorado = """
    # Fixture Reservoir Fishery Survey
    CPW sampled Fixture Reservoir in 2025. Rainbow trout, walleye, bluegill,
    and gizzard shad were recorded. Warmwater fish were also discussed.
    """
    assert parse_colorado(colorado, "Fixture Reservoir") == [
        "Bluegill", "Gizzard Shad", "Rainbow Trout", "Walleye"
    ]
    assert parse_colorado(colorado, "Different Reservoir") == []
    print("Official species page parser self-test passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    adapter_states = sorted(set(ADAPTERS) | set(BULK_ADAPTERS))
    parser.add_argument("--state", action="append", choices=adapter_states, help="State adapter to refresh; repeat as needed")
    parser.add_argument("--max-pages", type=int, default=0, help="Limit uncached page requests per state; 0 means all")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--max-age-days", type=int, default=120)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    states = args.state or adapter_states
    print(json.dumps(refresh(states, args.max_pages, args.workers, args.max_age_days), indent=2))


if __name__ == "__main__":
    main()
