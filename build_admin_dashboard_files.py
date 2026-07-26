#!/usr/bin/env python3
"""Build the admin dashboard files from the current Idaho statewide database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def map_freshness(value: str) -> str:
    value = clean(value).lower()
    if value in {"very_current", "current"}:
        return "current"
    if value == "recent":
        return "aging"
    return "stale"


def report_for_admin(
    report: dict[str, Any],
    generated_at: str,
    unmatched_ids: set[str],
) -> dict[str, Any]:
    water_name = clean(report.get("water_name"))
    title = clean(report.get("title")) or "Fishing update"
    species = clean(report.get("species"))
    rating = clean(report.get("rating"))
    techniques = clean(report.get("techniques"))
    access_notes = clean(report.get("access_notes"))
    source_url = clean(report.get("source_url"))
    report_id = clean(report.get("report_id"))

    catches = []
    if species:
        catches.append({
            "species": species,
            "metric": rating or "Reported",
            "detail": techniques,
        })

    return {
        "report_kind": clean(report.get("source_type")) or "official",
        "report_id": report_id,
        "state": "Idaho",
        "counties": report.get("counties") or [],
        "names": [water_name] if water_name else ["Statewide Idaho"],
        "water_name": water_name,
        "agency": clean(report.get("source_name")) or "Idaho fishing source",
        "report_type": (
            clean(report.get("source_type")).replace("_", " ").title()
            or "Fishing report"
        ),
        "published_date": clean(report.get("report_date")),
        "report_period": clean(report.get("observed_period")),
        "headline": title,
        "summary": clean(report.get("summary")),
        "catches": catches,
        "conditions": [
            value for value in (access_notes, techniques) if value
        ],
        "rating": rating,
        "species": species,
        "techniques": techniques,
        "source_url": source_url,
        "specificity": (
            "Matched Idaho public water"
            if water_name
            else "Statewide or multi-water Idaho report"
        ),
        "freshness_status": map_freshness(clean(report.get("freshness"))),
        "freshness_days": report.get("age_days"),
        "last_checked_at": generated_at,
        "source_status": "available" if source_url else "source-not-linked",
        "source_error": "",
        "review_required": report_id in unmatched_ids,
    }


def write_js(
    path: Path,
    comment: str,
    variable: str,
    value: dict[str, Any],
) -> None:
    path.write_text(
        f"/* {comment} */\n"
        f"window.{variable} = "
        + json.dumps(value, indent=2, ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        default="data/idaho_fishing_report_database.json",
    )
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    database = json.loads(
        Path(args.database).read_text(encoding="utf-8")
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = database.get("metadata") or {}
    generated_at = clean(metadata.get("generated_at"))
    unmatched = database.get("unmatched_reports") or []
    unmatched_ids = {
        clean(row.get("report_id"))
        for row in unmatched
        if isinstance(row, dict) and clean(row.get("report_id"))
    }

    reports = [
        report_for_admin(report, generated_at, unmatched_ids)
        for report in (database.get("flat_reports") or [])
        if isinstance(report, dict)
    ]
    reports.sort(
        key=lambda row: (
            clean(row.get("published_date")),
            clean(row.get("headline")),
        ),
        reverse=True,
    )

    current = sum(
        row["freshness_status"] == "current" for row in reports
    )
    aging = sum(
        row["freshness_status"] == "aging" for row in reports
    )
    stale = sum(
        row["freshness_status"] == "stale" for row in reports
    )
    review = sum(bool(row["review_required"]) for row in reports)
    source_keys = {
        clean(row.get("source_url")) or clean(row.get("agency"))
        for row in reports
        if clean(row.get("source_url")) or clean(row.get("agency"))
    }

    recent_file = {
        "version": f"{generated_at or 'current'}-idaho-statewide",
        "updated_at": generated_at,
        "coverage_note": (
            "Automatically generated from the Idaho county-by-county "
            "public-water and fishing-report database."
        ),
        "reports": reports,
    }
    status_file = {
        "last_run": generated_at,
        "mode": "idaho-statewide-database",
        "reports_total": len(reports),
        "public_water_count": database.get("public_water_count", 0),
        "county_count": database.get("county_count", 0),
        "unique_sources": len(source_keys),
        "freshness": {
            "current": current,
            "aging": aging,
            "stale": stale,
            "unknown": 0,
        },
        "changed_reports": len(reports),
        "review_required": review,
        "unreachable_sources": 0,
        "unmatched_report_count": len(unmatched),
        "sources": [],
    }

    write_js(
        output_dir / "recent_fishing_reports.js",
        (
            "Automatically generated from the Idaho statewide fishing "
            "database. Do not hand-edit."
        ),
        "FFO_RECENT_REPORTS",
        recent_file,
    )
    write_js(
        output_dir / "update_status.js",
        (
            "Automatically generated Idaho admin dashboard status. "
            "Do not hand-edit."
        ),
        "FFO_UPDATE_STATUS",
        status_file,
    )

    print(json.dumps({
        "reports_written": len(reports),
        "current": current,
        "aging": aging,
        "stale": stale,
        "review_required": review,
        "public_water_count": database.get("public_water_count", 0),
        "county_count": database.get("county_count", 0),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
