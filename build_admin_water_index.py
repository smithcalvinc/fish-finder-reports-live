#!/usr/bin/env python3
"""Build the private Fish Finder Outdoors Admin water-search index.

The public state databases remain the source of truth. This script creates a
compact, deduplicated index for admin.html so the private dashboard can search
all completed states without downloading every full report database in the
browser.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

STATE_SOURCES = [
    ("Idaho", "idaho", "idaho-county-reports.html", "Idaho"),
    ("Montana", "montana", "montana-county-reports.html", "Montana"),
    ("Utah", "utah", "utah-county-reports.html", "Utah"),
    ("Colorado", "colorado", "colorado-county-reports.html", "Colorado"),
    ("Wyoming", "wyoming", "wyoming-county-reports.html", "Wyoming"),
    ("Nevada", "nevada", "nevada-county-reports.html", "Nevada"),
    ("Oregon", "oregon", "oregon-county-reports.html", "Oregon"),
    ("Washington", "washington", "washington-county-reports.html", "Washington"),
    ("Northern California", "northern_california", "northern-california-county-reports.html", "California"),
]

MINIMUM_STATE_COUNT = 9
MINIMUM_SOURCE_WATER_ROWS = 15_000
MINIMUM_UNIQUE_WATERS = 10_000
EXPECTED_COUNTY_SHELLS = 334


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(value).lower())).strip()


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values: Iterable[Any] = [value]
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = clean(item)
        if not text:
            continue
        key = normalize(text)
        if key and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def county_names(row: dict[str, Any]) -> list[str]:
    values = row.get("counties")
    if not values:
        values = [row.get("county")]
    result = []
    for value in string_list(values):
        value = re.sub(r"\s+County$", "", value, flags=re.I).strip()
        if value:
            result.append(value)
    return result


def access_names(row: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for point in row.get("access_points") or []:
        if isinstance(point, str):
            name = clean(point)
        elif isinstance(point, dict):
            name = clean(
                point.get("name")
                or point.get("access_name")
                or point.get("site_name")
                or point.get("facility_name")
            )
        else:
            name = ""
        if name:
            names.append(name)
    return string_list(names)


def source_url(row: dict[str, Any]) -> str:
    candidates: list[Any] = [
        row.get("official_access_source_url"),
        row.get("fishnv_source_url"),
        row.get("metadata_source"),
        row.get("official_url"),
    ]
    water_urls = row.get("water_source_urls") or row.get("metadata_sources") or []
    if isinstance(water_urls, str):
        candidates.append(water_urls)
    else:
        candidates.extend(water_urls)
    for point in row.get("access_points") or []:
        if isinstance(point, dict):
            candidates.extend(
                [point.get("source_url"), point.get("official_url"), point.get("verification_url")]
            )
    for candidate in candidates:
        text = clean(candidate)
        if text.startswith("https://"):
            return text
    return ""


def latest_report(row: dict[str, Any]) -> dict[str, str]:
    report = row.get("latest_report") or {}
    if not isinstance(report, dict):
        return {"date": "", "title": "", "source_url": ""}
    return {
        "date": clean(report.get("report_date") or report.get("published_date") or report.get("date")),
        "title": clean(report.get("headline") or report.get("title") or report.get("summary")),
        "source_url": clean(report.get("source_url")),
    }


def load_status() -> dict[str, Any]:
    path = ROOT / "update_status.js"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    match = re.search(r"window\.FFO_UPDATE_STATUS\s*=\s*(\{[\s\S]*?\})\s*;?\s*$", text)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def stable_id(state: str, water_name: str) -> str:
    digest = hashlib.sha1(f"{state}|{normalize(water_name)}".encode("utf-8")).hexdigest()[:14]
    return f"water-{digest}"


def build_index(root: Path = ROOT) -> dict[str, Any]:
    data_dir = root / "data"
    entries: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    total_source_rows = 0
    total_county_shells = 0
    total_state_report_records = 0

    for state, stem, state_page, query_state in STATE_SOURCES:
        path = data_dir / f"{stem}_fishing_report_database.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing required state database: {path.relative_to(root)}")
        database = json.loads(path.read_text(encoding="utf-8"))
        rows = database.get("flat_waters") or []
        if not isinstance(rows, list):
            raise ValueError(f"{path.name}: flat_waters must be a list")
        source_public_count = integer(database.get("public_water_count")) or len(rows)
        county_count = integer(database.get("county_count")) or len(database.get("counties") or [])
        report_count = integer(database.get("report_count"))
        total_source_rows += len(rows)
        total_county_shells += county_count
        total_state_report_records += report_count

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            water_name = clean(row.get("water_name") or row.get("name"))
            if not water_name:
                continue
            key = normalize(water_name)
            if not key:
                continue
            entry = grouped.setdefault(
                key,
                {
                    "state": state,
                    "water_name": water_name,
                    "counties": set(),
                    "water_types": set(),
                    "latitude": None,
                    "longitude": None,
                    "report_count": 0,
                    "access_names": set(),
                    "access_point_count": 0,
                    "public_access_verification": "",
                    "official_source_url": "",
                    "latest_report_date": "",
                    "state_page": state_page,
                },
            )
            entry["counties"].update(county_names(row))
            water_type = clean(row.get("water_type") or row.get("type"))
            if water_type:
                entry["water_types"].add(water_type)
            lat = number(row.get("latitude") if row.get("latitude") is not None else row.get("lat"))
            lon = number(row.get("longitude") if row.get("longitude") is not None else row.get("lon"))
            if entry["latitude"] is None and lat is not None and lon is not None:
                entry["latitude"] = round(lat, 6)
                entry["longitude"] = round(lon, 6)
            # The same report can be attached to multiple county-linked rows. Max avoids double counting.
            row_report_count = integer(row.get("report_count")) or len(row.get("reports") or [])
            entry["report_count"] = max(entry["report_count"], row_report_count)
            entry["access_names"].update(access_names(row))
            entry["access_point_count"] = max(
                entry["access_point_count"],
                integer(row.get("access_point_count")) or len(row.get("access_points") or []),
            )
            verification = clean(
                row.get("public_access_verification")
                or row.get("access_status")
                or row.get("publication_status")
            )
            if verification and not entry["public_access_verification"]:
                entry["public_access_verification"] = verification
            if not entry["official_source_url"]:
                entry["official_source_url"] = source_url(row)
            latest = latest_report(row)
            if latest["date"] and latest["date"] >= entry["latest_report_date"]:
                entry["latest_report_date"] = latest["date"]

        state_entries: list[dict[str, Any]] = []
        for entry in grouped.values():
            counties = sorted(entry.pop("counties"), key=str.casefold)
            water_types = sorted(entry.pop("water_types"), key=str.casefold)
            access = sorted(entry.pop("access_names"), key=str.casefold)
            entry["counties"] = counties
            entry["water_type"] = ", ".join(water_types)
            entry["access_names"] = access[:3]
            state_entries.append(entry)
        state_entries.sort(key=lambda row: (normalize(row["water_name"]), row["water_name"]))
        entries.extend(state_entries)
        states.append(
            {
                "state": state,
                "state_page": state_page,
                "source_public_water_rows": source_public_count,
                "unique_water_names": len(state_entries),
                "county_count": county_count,
                "report_count": report_count,
                "generated_at": clean((database.get("metadata") or {}).get("generated_at")),
            }
        )

    entries.sort(key=lambda row: (normalize(row["state"]), normalize(row["water_name"])))
    states.sort(key=lambda row: normalize(row["state"]))
    status = load_status() if root == ROOT else {}
    aggregate_total = integer(status.get("reports_total")) if status else 0
    warnings: list[str] = []
    if aggregate_total and aggregate_total != total_state_report_records:
        difference = total_state_report_records - aggregate_total
        warnings.append(
            f"State databases contain {total_state_report_records:,} report records while the aggregate status shows "
            f"{aggregate_total:,}. Difference: {difference:+,}; aggregate generation may deduplicate records."
        )

    generated_values = [clean(row.get("generated_at")) for row in states if clean(row.get("generated_at"))]
    generated_at = max(generated_values) if generated_values else datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "version": "2026-08-admin-water-index-v1",
        "generated_at": generated_at,
        "state_count": len(states),
        "county_shell_count": total_county_shells,
        "source_public_water_rows": total_source_rows,
        "unique_water_count": len(entries),
        "state_report_record_total": total_state_report_records,
        "aggregate_report_total": aggregate_total,
        "warnings": warnings,
        "states": states,
        "waters": entries,
    }
    validate_payload(payload)
    return payload


def validate_payload(payload: dict[str, Any]) -> None:
    states = payload.get("states") or []
    waters = payload.get("waters") or []
    if len(states) != MINIMUM_STATE_COUNT:
        raise ValueError(f"Expected {MINIMUM_STATE_COUNT} states/regions, found {len(states)}")
    if integer(payload.get("county_shell_count")) < EXPECTED_COUNTY_SHELLS:
        raise ValueError(
            f"County-shell safety floor failed: {payload.get('county_shell_count')} < {EXPECTED_COUNTY_SHELLS}"
        )
    if integer(payload.get("source_public_water_rows")) < MINIMUM_SOURCE_WATER_ROWS:
        raise ValueError("Source water-row safety floor failed")
    if len(waters) < MINIMUM_UNIQUE_WATERS:
        raise ValueError("Unique-water safety floor failed")
    keys: set[tuple[str, str]] = set()
    for row in waters:
        for required in ("state", "water_name", "state_page"):
            if not clean(row.get(required)):
                raise ValueError(f"Admin index row is missing {required}: {row!r}")
        key = (normalize(row["state"]), normalize(row["water_name"]))
        if key in keys:
            raise ValueError(f"Duplicate state/water index key: {key}")
        keys.add(key)
        if row.get("official_source_url") and not str(row["official_source_url"]).startswith("https://"):
            raise ValueError(f"Unsafe official source URL: {row['official_source_url']}")


def write_payload(payload: dict[str, Any], root: Path = ROOT) -> None:
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    json_path = data_dir / "admin_water_index.json"
    js_path = data_dir / "admin_water_index.js"
    json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    json_path.write_text(json_text, encoding="utf-8")
    js_path.write_text(
        "/* Generated from all completed state fishing databases. Do not hand-edit. */\n"
        f"window.FFO_ADMIN_WATER_INDEX={compact};\n",
        encoding="utf-8",
    )


def self_test() -> None:
    fixture = {
        "state_count": 9,
        "county_shell_count": 334,
        "source_public_water_rows": 15_000,
        "unique_water_count": 10_000,
        "states": [{"state": f"S{i}"} for i in range(9)],
        "waters": [
            {
                "state": "Test",
                "water_name": f"Water {i}",
                "state_page": "test.html",
                "official_source_url": "https://example.gov/water",
            }
            for i in range(10_000)
        ],
    }
    validate_payload(fixture)
    print("ADMIN_WATER_INDEX_SELF_TEST_OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.validate_only:
        path = DATA_DIR / "admin_water_index.json"
        if not path.exists():
            raise FileNotFoundError(path)
        validate_payload(json.loads(path.read_text(encoding="utf-8")))
        print("ADMIN_WATER_INDEX_VALID")
        return 0
    payload = build_index(ROOT)
    write_payload(payload, ROOT)
    print(
        "ADMIN_WATER_INDEX_BUILT "
        f"states={payload['state_count']} counties={payload['county_shell_count']} "
        f"source_rows={payload['source_public_water_rows']} unique_waters={payload['unique_water_count']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ADMIN_WATER_INDEX_ERROR: {exc}", file=sys.stderr)
        raise
