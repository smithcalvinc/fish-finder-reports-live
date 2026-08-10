#!/usr/bin/env python3
"""Build FFO's compact, water-specific species evidence index.

Only named-water records backed by the official state datasets already stored in
``data/`` are published. Statewide species lists are intentionally excluded.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUTPUT = ROOT / "official_species_index.js"
BUILD_DATE = date(2026, 8, 10)


STATE_AGENCIES = {
    "Idaho": "Idaho Fish and Game",
    "Utah": "Utah Division of Wildlife Resources",
    "Colorado": "Colorado Parks and Wildlife",
    "Montana": "Montana Fish, Wildlife & Parks",
    "Nevada": "Nevada Department of Wildlife",
    "Oregon": "Oregon Department of Fish and Wildlife",
    "Washington": "Washington Department of Fish and Wildlife",
    "California": "California Department of Fish and Wildlife",
    "Wyoming": "Wyoming Game and Fish Department",
}


UTAH_SPECIES = {
    "rainbow": "Rainbow Trout",
    "cutthroat": "Cutthroat Trout",
    "brook trout": "Brook Trout",
    "tiger trout": "Tiger Trout",
    "splake": "Splake",
    "lake trout": "Lake Trout",
    "walleye": "Walleye",
    "muskie tiger": "Tiger Muskie",
    "cutbow ctbl*rtwv": "Cutbow Trout",
    "wiper": "Wiper",
    "sucker": "Sucker",
    "brown trout": "Brown Trout",
    "channel catfish": "Channel Catfish",
    "bass white": "White Bass",
    "kokanee": "Kokanee",
    "grayling arctic": "Arctic Grayling",
    "dace": "Dace",
    "crappie black": "Black Crappie",
    "grass carp sterile": "Sterile Grass Carp",
    "chub": "Chub",
    "all trout": "Trout — exact species not specified",
    "crappie white": "White Crappie",
}


# Conservative terms used only against a named NDOW water's official report
# summary. Longer/more-specific phrases are evaluated first.
NEVADA_SPECIES_TERMS = [
    (r"\blahontan cutthroat(?: trout)?\b", "Lahontan Cutthroat Trout"),
    (r"\byellowstone cutthroat(?: trout)?\b", "Yellowstone Cutthroat Trout"),
    (r"\bcutthroat trout\b|\bcutthroats\b|\bcutthroat\b", "Cutthroat Trout"),
    (r"\brainbow(?:\s+and\s+(?:german\s+)?brown)?\s+trout\b|\brainbows\b", "Rainbow Trout"),
    (r"\bbrown trout\b", "Brown Trout"),
    (r"\btiger trout\b", "Tiger Trout"),
    (r"\bbrook trout\b", "Brook Trout"),
    (r"\bgolden trout\b", "Golden Trout"),
    (r"\bstriped bass\b|\bstripers\b|\bstriper\b", "Striped Bass"),
    (r"\bsmall[\s-]?mouth bass\b|\bsmallmouths\b", "Smallmouth Bass"),
    (r"\blarge[\s-]?mouth bass\b|\blargemouths\b", "Largemouth Bass"),
    (r"\bwhite bass\b", "White Bass"),
    (r"\bchannel catfish\b", "Channel Catfish"),
    (r"\bbluegill\b", "Bluegill"),
    (r"\bblack crappie\b", "Black Crappie"),
    (r"\bwhite crappie\b", "White Crappie"),
    (r"\bcrappie\b", "Crappie — exact species not specified"),
    (r"\byellow perch\b", "Yellow Perch"),
    (r"\bwalleye\b", "Walleye"),
    (r"\bkokanee\b", "Kokanee"),
    (r"\bsteelhead\b", "Steelhead"),
    (r"\bwhite sturgeon\b", "White Sturgeon"),
    (r"\bnorthern pike\b", "Northern Pike"),
    (r"\btiger musk(?:ie|y)\b", "Tiger Muskie"),
    (r"\bcarp\b", "Carp — exact species not specified"),
    (r"\bcatfish\b", "Catfish — exact species not specified"),
    (r"\bbass\b", "Bass — exact species not specified"),
    (r"\btrout\b", "Trout — exact species not specified"),
]


def load_json(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).strip()


def url_slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean(value).lower()).strip("-")


def title_species(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    lower = value.lower()
    fixed = {
        "usually catchable rainbow trout unless the official schedule states otherwise": "Rainbow Trout",
        "none": "",
        "no fish caught": "",
        "catchable trout": "Trout — exact species not specified",
        "trout — exact species not specified": "Trout — exact species not specified",
        "bass — exact species not specified": "Bass — exact species not specified",
        "catfish — exact species not specified": "Catfish — exact species not specified",
        "crappie — exact species not specified": "Crappie — exact species not specified",
        "carp — exact species not specified": "Carp — exact species not specified",
    }
    if lower in fixed:
        return fixed[lower]
    if lower in UTAH_SPECIES:
        return UTAH_SPECIES[lower]
    words = []
    for word in lower.split():
        if word in {"x", "×"}:
            words.append("×")
        else:
            words.append(word.capitalize())
    return " ".join(words)


def split_species(value: object) -> list[str]:
    if isinstance(value, list):
        raw = [clean(item) for item in value]
    else:
        raw = re.split(r"\s*[,;]\s*", clean(value)) if clean(value) else []
    found: list[str] = []
    seen: set[str] = set()
    for item in raw:
        label = title_species(item)
        key = norm(label)
        if label and key not in seen:
            seen.add(key)
            found.append(label)
    return found


def nevada_summary_species(value: object) -> list[str]:
    text = clean(value).lower()
    found: list[str] = []
    for pattern, label in NEVADA_SPECIES_TERMS:
        if not re.search(pattern, text):
            continue
        label_key = norm(label)
        existing_keys = [norm(existing) for existing in found]
        if any(key == label_key or key.endswith(" " + label_key) for key in existing_keys):
            continue
        if "exact species not specified" in label.lower():
            group = norm(label.split("—", 1)[0])
            if any(key == group or key.endswith(" " + group) for key in existing_keys):
                continue
        found.append(label)
    return found


def official_text_species(value: object) -> list[str]:
    """Extract explicit fish names from a named-water government page excerpt.

    The source builders store page text only after matching it to the named
    water. This parser deliberately uses the same conservative vocabulary as
    the NDOW report parser and never expands a general fish group into species.
    """
    return nevada_summary_species(value)


def trusted_official_url(value: object) -> bool:
    url = clean(value).lower()
    return url.startswith("https://") and not any(
        host in url for host in ("google.com/", "bing.com/", "duckduckgo.com/")
    )


def aliases_from_water_rows(filename: str) -> dict[tuple[str, str], list[str]]:
    data = load_json(filename)
    result: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in data.get("flat_waters", []):
        key = (clean(row.get("county")), norm(row.get("water_name")))
        for alias in row.get("alternate_names", []) or []:
            alias = clean(alias)
            if alias and norm(alias) != key[1] and alias not in result[key]:
                result[key].append(alias)
    return result


def add_record(store: dict, *, state: str, name: str, species: list[str],
               counties: list[str] | None, source_name: str, source_url: str,
               evidence_type: str, note: str, aliases: list[str] | None = None,
               latitude: object = None, longitude: object = None,
               specificity: str = "species") -> None:
    name = clean(name)
    species = split_species(species)
    if not name or not species or norm(name) in {"all bodies of water", "statewide", "all waters"}:
        return
    county_values = sorted({clean(item) for item in counties or [] if clean(item)})
    lat = lon = None
    try:
        candidate_lat = float(latitude)
        candidate_lon = float(longitude)
        if -90 <= candidate_lat <= 90 and -180 <= candidate_lon <= 180:
            lat = round(candidate_lat, 6)
            lon = round(candidate_lon, 6)
    except (TypeError, ValueError):
        pass
    # County is normally enough to distinguish duplicate water names. Some
    # official survey layers do not publish county, so retain a coordinate key
    # instead of collapsing unrelated "Echo Lake" or "Azalea Lake" records.
    coordinate_key = (round(lat, 4), round(lon, 4)) if not county_values and lat is not None and lon is not None else ()
    key = (state, norm(name), tuple(norm(item) for item in county_values), coordinate_key)
    record = store.get(key)
    if not record:
        record = {
            "name": name,
            "aliases": [],
            "counties": county_values,
            "species": [],
            "source_name": clean(source_name) or STATE_AGENCIES.get(state, "Official state fish and wildlife agency"),
            "source_url": clean(source_url),
            "evidence_type": evidence_type,
            "specificity": specificity,
            "note": note,
        }
        if lat is not None and lon is not None:
            record["lat"] = lat
            record["lon"] = lon
        store[key] = record
    for alias in aliases or []:
        alias = clean(alias)
        if alias and norm(alias) != norm(name) and alias not in record["aliases"]:
            record["aliases"].append(alias)
    existing = {norm(item) for item in record["species"]}
    for item in species:
        if norm(item) not in existing:
            existing.add(norm(item))
            record["species"].append(item)


def add_montana(store: dict) -> None:
    data = load_json("montana_public_fishing_access.json")
    for row in data.get("flat_records", []):
        urls = row.get("official_evidence_urls", []) or []
        add_record(
            store,
            state="Montana",
            name=row.get("water_name"),
            species=row.get("species", []),
            counties=[row.get("county")],
            source_name=STATE_AGENCIES["Montana"],
            source_url=urls[0] if urls else "https://myfwp.mt.gov/fishMT/explore",
            evidence_type="Official fish survey and stocking records",
            note="Species documented in Montana FWP fisheries records; this is not a current bite report.",
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
        )


def add_oregon(store: dict) -> None:
    data = load_json("oregon_public_fishing_access.json")
    for row in data.get("flat_waters", []):
        urls = row.get("water_source_urls", []) or []
        add_record(
            store,
            state="Oregon",
            name=row.get("water_name"),
            species=row.get("species", []),
            counties=row.get("counties") or [row.get("county")],
            source_name=STATE_AGENCIES["Oregon"],
            source_url=urls[0] if urls else "https://myodfw.com/fishing",
            evidence_type="Official fishing report or stocking record",
            note="Species named in the linked ODFW water report or stocking record; this is not a complete population survey.",
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
        )


def add_wyoming(store: dict) -> None:
    data = load_json("wyoming_public_fishing_access.json")
    for row in data.get("flat_waters", []):
        latest = row.get("latest_report") or {}
        add_record(
            store,
            state="Wyoming",
            name=row.get("water_name"),
            species=split_species(row.get("species")),
            counties=row.get("counties") or [row.get("county")],
            source_name=STATE_AGENCIES["Wyoming"],
            source_url=latest.get("source_url") or row.get("official_access_source_url") or "https://wgfd.wyo.gov/fishing-boating/places-fish-wyoming",
            evidence_type="Official Wyoming Fishing Guide record",
            note="Species listed for this named water in the Wyoming Fishing Guide.",
            aliases=row.get("alternate_names", []),
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
        )

        # WGFD's builder keeps the exact Fishing Guide species on its matched
        # report record as well as (for some waters) on the flattened water.
        # Read every official nested record so access-only records cannot erase
        # species that WGFD already supplied for this exact water.
        nested = [row.get("latest_report"), *(row.get("recent_reports") or []), *(row.get("reports") or [])]
        for report in nested:
            if not isinstance(report, dict) or report.get("official") is False:
                continue
            species = split_species(report.get("species"))
            source_url = clean(report.get("source_url"))
            if not species or not trusted_official_url(source_url):
                continue
            add_record(
                store,
                state="Wyoming",
                name=report.get("water_name") or row.get("water_name"),
                species=species,
                counties=report.get("counties") or row.get("counties") or [row.get("county")],
                source_name=report.get("source_name") or STATE_AGENCIES["Wyoming"],
                source_url=source_url,
                evidence_type="Official Wyoming Fishing Guide record",
                note="Species listed for this exact water in a Wyoming Game and Fish record.",
                aliases=row.get("alternate_names", []),
                latitude=row.get("latitude"),
                longitude=row.get("longitude"),
            )


def add_report_species(store: dict, state: str, filename: str,
                       *, exact_idaho_only: bool = False,
                       generic_group: bool = False) -> None:
    aliases = aliases_from_water_rows(filename)
    data = load_json(filename)
    for row in data.get("flat_reports", []):
        if not row.get("official", True):
            continue
        if exact_idaho_only and row.get("raw_source_reference") != "exact_or_alias":
            continue
        names = split_species(row.get("species"))
        if not names:
            continue
        counties = [clean(item) for item in row.get("counties", []) if clean(item)]
        water_name = clean(row.get("water_name"))
        row_aliases: list[str] = []
        for county in counties or [""]:
            row_aliases.extend(aliases.get((county, norm(water_name)), []))
        source_url = row.get("source_url")
        if state == "Colorado":
            source_url = "https://cpw.state.co.us/activities/fishing/fishing-awards-and-records/fish-stocking-report"
        add_record(
            store,
            state=state,
            name=water_name,
            species=names,
            counties=counties,
            source_name=row.get("source_name") or STATE_AGENCIES[state],
            source_url=source_url,
            evidence_type="Official stocking record" if "stock" in clean(row.get("source_type")).lower() else "Official agency report",
            note=(
                "The official record identifies a fish group but does not specify an exact species."
                if generic_group
                else "Species documented in a named-water agency stocking or report record; presence does not guarantee a current bite."
            ),
            aliases=row_aliases,
            specificity="group" if generic_group else "species",
        )


def add_nevada(store: dict) -> None:
    data = load_json("nevada_fishing_report_database.json")
    for row in data.get("flat_reports", []):
        species = nevada_summary_species(row.get("summary"))
        add_record(
            store,
            state="Nevada",
            name=row.get("water_name"),
            species=species,
            counties=row.get("counties", []),
            source_name=row.get("source_name") or STATE_AGENCIES["Nevada"],
            source_url=row.get("source_url"),
            evidence_type="Species named in official fishing report text",
            note="Species terms were taken from the linked NDOW report text for this named water; the list may not be complete.",
        )

    # Some verified-access waters come from another Nevada government page
    # rather than FishNV. Those pages can still explicitly name the fish in the
    # exact reservoir or pond. Keep that evidence instead of discarding it.
    for row in data.get("flat_waters", []):
        source_url = clean(row.get("official_access_source_url"))
        species = official_text_species(row.get("access_details"))
        if not species or not trusted_official_url(source_url):
            continue
        points = row.get("access_points") or []
        source_name = next(
            (clean(point.get("source_name")) for point in points if clean(point.get("source_name"))),
            "Nevada official managing agency",
        )
        add_record(
            store,
            state="Nevada",
            name=row.get("water_name"),
            species=species,
            counties=row.get("counties") or [row.get("county")],
            source_name=source_name,
            source_url=source_url,
            evidence_type="Official named-water page",
            note="Fish explicitly named on the linked Nevada government page for this water; the list may not be a complete biological survey.",
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
        )


def add_refreshed_official_pages(store: dict) -> None:
    path = DATA / "official_species_sources.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    for state, rows in (payload.get("states") or {}).items():
        for row in rows or []:
            if row.get("status") not in (None, "documented"):
                continue
            source_url = clean(row.get("source_url"))
            if not trusted_official_url(source_url):
                continue
            add_record(
                store,
                state=state,
                name=row.get("name"),
                species=row.get("species", []),
                counties=row.get("counties", []),
                source_name=row.get("source_name") or STATE_AGENCIES.get(state, "Official state fish and wildlife agency"),
                source_url=source_url,
                evidence_type=row.get("evidence_type") or "Exact official water page",
                note=row.get("note") or "Fish listed on the linked official page for this exact water.",
                aliases=row.get("aliases", []),
                latitude=row.get("lat"),
                longitude=row.get("lon"),
            )


def build_exact_lookups() -> dict[str, list[dict]]:
    """Build direct official water-page links used when species are refreshed.

    Idaho's public hydrography records expose the same WaterID used by the
    Fishing Planner URL. Preserving it fixes the previous data-loss path where
    FFO retained the lake name but discarded its exact agency page.
    """
    access = load_json("idaho_public_fishing_access.json")
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in access.get("flat_records", []):
        name = clean(row.get("water_name"))
        water_id = clean(row.get("source_water_id"))
        if not name or not re.fullmatch(r"\d{5,20}", water_id):
            continue
        counties = sorted({clean(value) for value in [row.get("county"), *(row.get("all_counties") or [])] if clean(value)})
        key = (norm(name), water_id, "|".join(norm(county) for county in counties))
        record = grouped.setdefault(
            key,
            {
                "name": name,
                "aliases": [],
                "counties": counties,
                "source_name": "Idaho Fish and Game — Fishing Planner",
                "source_url": f"https://idfg.idaho.gov/ifwis/fishingplanner/water/{water_id}",
                "verified": True,
            },
        )
        for alias in row.get("alternate_names", []) or []:
            alias = clean(alias)
            if alias and norm(alias) != norm(name) and alias not in record["aliases"]:
                record["aliases"].append(alias)
        try:
            record["lat"] = round(float(row.get("latitude")), 6)
            record["lon"] = round(float(row.get("longitude")), 6)
        except (TypeError, ValueError):
            pass
    idaho_rows = list(grouped.values())
    for row in idaho_rows:
        row["aliases"].sort(key=str.casefold)
    idaho_rows.sort(key=lambda row: (norm(row["name"]), tuple(norm(county) for county in row["counties"])))

    washington = load_json("washington_public_fishing_access.json")
    washington_rows: list[dict] = []
    for row in washington.get("flat_waters", []):
        name = clean(row.get("water_name"))
        county = clean(row.get("county"))
        water_type = clean(row.get("water_type")).lower()
        if not name or water_type not in {"lake", "pond", "reservoir"}:
            continue
        exact_urls = [
            clean(url) for url in row.get("water_source_urls") or []
            if "/fishing/locations/" in clean(url)
        ]
        base = "https://wdfw.wa.gov/fishing/locations/lowland-lakes/"
        guessed_urls = [
            base + url_slug(name) + ("-" + url_slug(county) if county else ""),
            base + url_slug(name),
        ]
        urls: list[str] = []
        for url in [*exact_urls, *guessed_urls]:
            if url and url not in urls:
                urls.append(url)
        record = {
            "name": name,
            "aliases": [],
            "counties": [county] if county else [],
            "source_name": "Washington Department of Fish and Wildlife",
            "source_url": urls[0],
            "alternate_source_urls": urls[1:],
            "verified": False,
        }
        try:
            record["lat"] = round(float(row.get("latitude")), 6)
            record["lon"] = round(float(row.get("longitude")), 6)
        except (TypeError, ValueError):
            pass
        washington_rows.append(record)
    washington_rows.sort(key=lambda row: (norm(row["name"]), tuple(norm(county) for county in row["counties"])))

    nevada = load_json("nevada_public_fishing_access.json")
    nevada_rows: list[dict] = []
    for row in nevada.get("flat_waters", []):
        name = clean(row.get("water_name"))
        county = clean(row.get("county"))
        urls: list[str] = []
        reports = [row.get("latest_report"), *(row.get("recent_reports") or [])]
        for candidate in [row.get("fishnv_source_url"), *(report.get("source_url") for report in reports if isinstance(report, dict))]:
            url = clean(candidate)
            if re.match(r"^https://(?:www\.)?ndow\.org/waters/[^/?#]+/?$", url, flags=re.I) and url not in urls:
                urls.append(url)
        if not name or not urls:
            continue
        record = {
            "name": name,
            "aliases": [],
            "counties": [county] if county else [],
            "source_name": "Nevada Department of Wildlife",
            "source_url": urls[0],
            "alternate_source_urls": urls[1:],
            "verified": True,
        }
        try:
            record["lat"] = round(float(row.get("latitude")), 6)
            record["lon"] = round(float(row.get("longitude")), 6)
        except (TypeError, ValueError):
            pass
        nevada_rows.append(record)
    nevada_rows.sort(key=lambda row: (norm(row["name"]), tuple(norm(county) for county in row["counties"])))
    colorado = load_json("colorado_fishing_report_database.json")
    colorado_rows: list[dict] = []
    seen_colorado: set[tuple[str, str]] = set()
    for report in colorado.get("flat_reports", []):
        name = clean(report.get("water_name"))
        source_url = clean(report.get("source_url"))
        if (
            report.get("official") is False
            or clean(report.get("source_type")) != "official_fishery_survey"
            or not re.match(r"^https://cpw\.state\.co\.us/.+\.pdf(?:[?#].*)?$", source_url, flags=re.I)
            or not name
            or name.startswith("[")
        ):
            continue
        key = (norm(name), source_url.lower())
        if key in seen_colorado:
            continue
        seen_colorado.add(key)
        colorado_rows.append({
            "name": name,
            "aliases": [],
            "counties": sorted({clean(value) for value in report.get("counties", []) if clean(value)}),
            "source_name": "Colorado Parks and Wildlife — Fishery Survey",
            "source_url": source_url,
            "verified": True,
        })
    colorado_rows.sort(key=lambda row: (norm(row["name"]), tuple(norm(county) for county in row["counties"])))

    return {
        "Colorado": colorado_rows,
        "Idaho": idaho_rows,
        "Nevada": nevada_rows,
        "Washington": washington_rows,
    }


def build() -> dict:
    records: dict[tuple, dict] = {}
    add_refreshed_official_pages(records)
    add_montana(records)
    add_oregon(records)
    add_wyoming(records)
    add_report_species(records, "Idaho", "idaho_fishing_report_database.json", exact_idaho_only=True)
    add_report_species(records, "California", "northern_california_fishing_report_database.json", generic_group=True)
    add_report_species(records, "Utah", "utah_fishing_report_database.json")
    add_report_species(records, "Colorado", "colorado_fishing_report_database.json", generic_group=True)
    add_nevada(records)

    states: dict[str, list[dict]] = defaultdict(list)
    for (state, *_), record in records.items():
        specific_text = " ".join(
            norm(item) for item in record["species"]
            if "exact species not specified" not in item.lower()
        )
        record["species"] = [
            item for item in record["species"]
            if "exact species not specified" not in item.lower()
            or norm(item.split("—", 1)[0]) not in specific_text
        ]
        record["aliases"].sort(key=str.casefold)
        record["species"].sort(key=str.casefold)
        states[state].append(record)
    for rows in states.values():
        rows.sort(key=lambda row: (norm(row["name"]), tuple(norm(c) for c in row["counties"])))

    counts = {state: len(rows) for state, rows in sorted(states.items())}
    return {
        "version": "2026.08.10-v57",
        "generated_at": BUILD_DATE.isoformat(),
        "coverage_note": "Named-water species evidence and exact official water-page lookups from state sources. Statewide species lists are excluded and never presented as if they apply to a lake.",
        "record_count": sum(counts.values()),
        "record_counts": counts,
        "lookups": build_exact_lookups(),
        "states": {state: states[state] for state in sorted(states)},
    }


def main() -> None:
    payload = build()
    output = "window.FFO_OFFICIAL_SPECIES_INDEX=" + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ) + ";\n"
    OUTPUT.write_text(output, encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "records": payload["record_count"], "states": payload["record_counts"]}, indent=2))


if __name__ == "__main__":
    main()
