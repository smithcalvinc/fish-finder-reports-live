#!/usr/bin/env python3
"""
Clean Nevada-only Fish Finder Outdoors builder.

This runner intentionally does NOT recursively crawl NDOW "related water" links.
NDOW currently exposes hundreds of stale links that return 404 pages. Those dead
links are recorded as warnings and never treated as public-access evidence.

The existing build_nevada_fishing_data.py remains the shared parser/helper
library. This file owns the Nevada collection strategy, validation policy,
outputs, and website integration.
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import build_nevada_fishing_data as nv


MIN_METADATA_RECORDS = 300
MIN_PUBLIC_WATERS = 25
MIN_ACCESS_POINTS = 25
MIN_REPORTS = 100


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def discover_current_ndow_urls(
    report_html_pages: list[str],
    reports: list[dict[str, Any]],
) -> tuple[list[str], dict[str, int], list[str]]:
    """
    Build a fixed seed list from current official report pages and official
    sitemap files. Related-water links found inside individual water pages are
    deliberately ignored because NDOW retains many stale 404 links there.
    """
    urls: set[str] = set()
    warnings: list[str] = []

    for raw in report_html_pages:
        urls.update(nv.extract_ndow_water_urls(raw, nv.OFFICIAL_URLS["reports"]))

    for report in reports:
        source = nv.canonical_url(report.get("source_url", ""))
        parts = urlsplit(source)
        if (
            parts.netloc in nv.NDOW_WATER_HOSTS
            and re.fullmatch(r"/waters/[a-z0-9][a-z0-9\-]*/?", parts.path, flags=re.I)
        ):
            urls.add(source.rstrip("/") + "/")

    sitemap_checked = 0
    sitemap_failures = 0
    for sitemap_url in nv.NDOW_WATER_SITEMAP_CANDIDATES:
        try:
            xml = nv.request_text(sitemap_url, retries=2)
            sitemap_checked += 1
            for location in nv.xml_locs(xml):
                urls.update(nv.extract_ndow_water_urls(location, sitemap_url))
            urls.update(nv.extract_ndow_water_urls(xml, sitemap_url))
        except RuntimeError as exc:
            sitemap_failures += 1
            warnings.append(f"Official NDOW sitemap unavailable: {sitemap_url}: {exc}")

    return sorted(urls), {
        "ndow_water_seed_urls": len(urls),
        "ndow_water_sitemaps_checked": sitemap_checked,
        "ndow_water_sitemap_failures": sitemap_failures,
    }, warnings


def collect_current_ndow_inventory(
    urls: list[str],
    county_polygons: list[Any],
    workers: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], dict[str, int]]:
    """
    Parse the fixed current URL list exactly once.

    A page that returns 404, lacks a water name, or cannot be assigned to a
    Nevada county becomes an audit warning. It does not poison the valid
    statewide inventory and it is never published.
    """
    waters: list[dict[str, Any]] = []
    access_records: list[dict[str, Any]] = []
    warnings: list[str] = []

    max_workers = max(1, min(int(workers), 20))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(nv.parse_ndow_water_page, url, county_polygons): url
            for url in urls
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                water, page_access, _ignored_related_links, error = future.result()
            except Exception as exc:  # one broken source must not destroy the run
                water, page_access, error = None, [], f"{url}: {exc}"

            if water:
                waters.append(water)
                access_records.extend(page_access)
            elif error:
                warnings.append(error)

    # Deduplicate by canonical county + normalized water name.
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for water in waters:
        county = clean(water.get("county"))
        water_name = nv.norm(water.get("water_name"))
        if not county or not water_name:
            continue
        key = (county, water_name)
        existing = unique.get(key)
        if not existing or (
            not existing.get("fishnv_source_url")
            and water.get("fishnv_source_url")
        ):
            unique[key] = water

    waters = sorted(
        unique.values(),
        key=lambda row: (
            nv.COUNTY_NUMBER.get(clean(row.get("county")), 999),
            clean(row.get("water_name")),
        ),
    )
    access_unique = {
        clean(row.get("access_id")): row
        for row in access_records
        if clean(row.get("access_id"))
    }
    represented = {
        clean(row.get("county")) for row in waters if clean(row.get("county"))
    }

    return waters, list(access_unique.values()), warnings, {
        "ndow_water_pages_requested": len(urls),
        "ndow_water_metadata_records": len(waters),
        "ndow_water_metadata_counties": len(represented),
        "ndow_water_page_access_records": len(access_unique),
        "ndow_water_unresolved_pages": len(warnings),
        "ndow_dead_or_unusable_pages_ignored": len(warnings),
        "fishnv_map_links_from_ndow": sum(
            bool(row.get("fishnv_source_url")) for row in waters
        ),
    }


def validate_clean_build(
    db: dict[str, Any],
    source_counts: dict[str, int],
    audit: dict[str, Any],
) -> dict[str, Any]:
    counties = db.get("counties") or []
    if db.get("county_count") != 17 or len(counties) != 17:
        raise RuntimeError("Nevada build did not create all 17 county shells")
    if [row.get("county") for row in counties] != nv.COUNTIES:
        raise RuntimeError("Nevada county order is not Carson City through White Pine")
    if int(source_counts.get("county_polygons", 0)) != 17:
        raise RuntimeError("Nevada county boundary source did not return all 17 counties")

    metadata_records = int(source_counts.get("ndow_water_metadata_records", 0))
    metadata_counties = int(source_counts.get("ndow_water_metadata_counties", 0))
    pages_requested = int(source_counts.get("ndow_water_pages_requested", 0))
    unresolved_pages = int(source_counts.get("ndow_water_unresolved_pages", 0))

    if metadata_records < MIN_METADATA_RECORDS:
        raise RuntimeError(
            f"Current NDOW inventory produced only {metadata_records} valid water records; "
            f"minimum safety floor is {MIN_METADATA_RECORDS}"
        )
    if metadata_counties != 17:
        raise RuntimeError(
            f"Valid NDOW metadata represents only {metadata_counties} of 17 Nevada counties"
        )

    public_waters = int(db.get("public_water_count", 0))
    access_points = int(db.get("verified_access_point_count", 0))
    report_count = int(db.get("report_count", 0))
    if public_waters < MIN_PUBLIC_WATERS:
        raise RuntimeError(
            f"Only {public_waters} independently verified public waters were produced"
        )
    if access_points < MIN_ACCESS_POINTS:
        raise RuntimeError(
            f"Only {access_points} independently verified access points were produced"
        )
    if report_count < MIN_REPORTS:
        raise RuntimeError(f"Only {report_count} official Nevada report records were produced")

    bad_points: list[str] = []
    methods: set[str] = set()
    unique_access_ids: set[str] = set()
    for water in db.get("flat_waters") or []:
        if water.get("publication_status") != "published_verified_public_access":
            bad_points.append(f"{water.get('water_name')}: invalid publication status")
        points = water.get("access_points") or []
        if not points:
            bad_points.append(f"{water.get('water_name')}: no access point")
        for point in points:
            access_id = clean(point.get("access_id"))
            if access_id:
                unique_access_ids.add(access_id)
            method = clean(point.get("verification_method"))
            if method:
                methods.add(method)
            if point.get("public_access_status") != "verified_public":
                bad_points.append(f"{water.get('water_name')}: access not verified")
            if point.get("entire_shoreline_public") is not False:
                bad_points.append(f"{water.get('water_name')}: shoreline scope is unsafe")
            if not clean(point.get("access_point_name")):
                bad_points.append(f"{water.get('water_name')}: unnamed access point")
            if not clean(point.get("official_source_url")).startswith("https://"):
                bad_points.append(f"{water.get('water_name')}: missing official HTTPS source")
            if not clean(point.get("verification_evidence")):
                bad_points.append(f"{water.get('water_name')}: missing evidence")
            if "fishnv" in method.lower():
                bad_points.append(f"{water.get('water_name')}: FishNV used as access proof")
            if clean(point.get("access_point_name")).lower() == "fishnv mapped fishing location":
                bad_points.append(f"{water.get('water_name')}: forbidden generic access point")

    if bad_points:
        raise RuntimeError(
            "Strict Nevada public-access validation failed: " + "; ".join(bad_points[:20])
        )
    if len(methods) < 2:
        raise RuntimeError(
            f"Only {len(methods)} public-access verification method was represented"
        )
    if len(unique_access_ids) != access_points:
        raise RuntimeError(
            "Verified access-point total does not equal the unique access IDs"
        )

    populated = [
        row.get("county")
        for row in counties
        if int(row.get("public_water_count", 0) or 0) > 0
    ]
    without_verified_access = [
        row.get("county")
        for row in counties
        if int(row.get("public_water_count", 0) or 0) == 0
    ]

    map_counts = nv.validate_map_data(db)
    return {
        "passed": True,
        "complete_inventory_gate": True,
        "inventory_strategy": "fixed_current_official_sources_no_recursive_related_link_crawl",
        "dead_ndow_links_are_nonfatal_warnings": True,
        "strict_public_access": True,
        "fishnv_is_access_verification": False,
        "ndow_water_metadata_records": metadata_records,
        "ndow_water_metadata_counties": metadata_counties,
        "ndow_water_pages_requested": pages_requested,
        "ndow_water_unresolved_pages": unresolved_pages,
        "public_water_count": public_waters,
        "verified_access_point_count": access_points,
        "report_count": report_count,
        "populated_counties": len(populated),
        "populated_county_names": populated,
        "counties_without_verified_public_access": without_verified_access,
        "access_verification_methods": sorted(methods),
        "quarantined_unverified_waters": int(
            audit.get("matching", {}).get("quarantined_unverified_waters", 0)
        ),
        "orphan_official_access_records": int(
            audit.get("matching", {}).get("orphan_official_access_records", 0)
        ),
        **map_counts,
    }


def annotate_county_coverage(db: dict[str, Any]) -> None:
    for county in db.get("counties") or []:
        count = int(county.get("public_water_count", 0) or 0)
        if count:
            county["coverage_status"] = "verified_public_access_records_available"
            county["coverage_note"] = (
                "Only named public access supported by an official source is displayed."
            )
        else:
            county["coverage_status"] = "no_independently_verified_public_access_found"
            county["coverage_note"] = (
                "The county remains in the statewide search, but this run found no water "
                "with a named public access point independently verified by an official "
                "state or federal source. This is not proof that the county has no fishing."
            )


def run_self_test() -> None:
    assert len(nv.COUNTIES) == 17
    assert nv.COUNTIES[0] == "Carson City"
    assert nv.COUNTIES[-1] == "White Pine"
    assert MIN_METADATA_RECORDS == 300
    print("Clean Nevada runner self-test passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        # Preserve the original strict parser unit tests too.
        nv.run_self_tests()
        return 0

    root = Path(args.root).resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir

    generated_at = nv.now_iso()
    county_polygons = nv.load_county_polygons()
    reports, filter_water_names, report_html_pages, report_counts = nv.collect_ndow_reports()
    report_counts.pop("direct_urls", None)

    seed_urls, discovery_counts, discovery_warnings = discover_current_ndow_urls(
        report_html_pages, reports
    )
    ndow_waters, ndow_page_access, ndow_warnings, ndow_counts = (
        collect_current_ndow_inventory(seed_urls, county_polygons, args.workers)
    )
    ndow_counts.update(discovery_counts)

    access_records, access_counts, access_warnings = (
        nv.collect_all_verified_access(county_polygons)
    )
    access_records.extend(ndow_page_access)
    access_records = list(
        {
            clean(row.get("access_id")): row
            for row in access_records
            if clean(row.get("access_id"))
        }.values()
    )
    access_counts["ndow_water_page_access_records"] = len(ndow_page_access)
    access_counts["combined_official_access_records"] = len(access_records)

    verified_waters, unverified_waters, orphan_access, matching_counts = (
        nv.match_verified_access(ndow_waters, access_records)
    )
    matching_counts["quarantined_unverified_waters"] = len(unverified_waters)
    matching_counts["orphan_official_access_records"] = len(orphan_access)

    all_source_warnings = [
        *discovery_warnings,
        *ndow_warnings,
        *access_warnings,
    ]
    audit = {
        "state": nv.STATE,
        "generated_at": generated_at,
        "policy": (
            "Current official NDOW pages supply inventory metadata. Stale or broken "
            "NDOW links are audit warnings only. FishNV is never accepted as public-"
            "access verification. A water is published only with explicit official "
            "named public-access evidence."
        ),
        "inventory_strategy": (
            "fixed current official report and sitemap seeds; no recursive related-water crawl"
        ),
        "source_counts": {**ndow_counts, **access_counts},
        "matching": matching_counts,
        "source_warnings": all_source_warnings,
        "unresolved_ndow_water_page_samples": ndow_warnings[:100],
    }

    db = nv.build_database(verified_waters, reports, generated_at, audit)
    db["unverified_fishable_water_count"] = len(unverified_waters)
    db["metadata"]["version"] = "4.0-clean-nevada-current-sources-strict-access"
    db["metadata"]["inventory_strategy"] = audit["inventory_strategy"]
    db["metadata"]["dead_ndow_links_are_publication_blockers"] = False
    annotate_county_coverage(db)

    source_counts = {
        "county_polygons": len(county_polygons),
        **report_counts,
        **ndow_counts,
        **access_counts,
        **matching_counts,
        "official_filter_water_names": len(filter_water_names),
    }
    validation = validate_clean_build(db, source_counts, audit)

    status = {
        "state": nv.STATE,
        "generated_at": generated_at,
        "deployment_status": "validated_complete_ready_to_commit",
        "failed_sources": [],
        "source_warnings": all_source_warnings,
        "warnings": {
            "dead_or_unusable_ndow_page_count": len(ndow_warnings),
            "dead_or_unusable_ndow_page_samples": ndow_warnings[:100],
            "quarantined_unverified_water_count": len(unverified_waters),
            "orphan_official_access_record_count": len(orphan_access),
            "counties_without_verified_public_access": validation[
                "counties_without_verified_public_access"
            ],
        },
        "source_counts": source_counts,
        "validation": validation,
        "notes": [
            "All 17 Nevada county shells are always generated in order.",
            "Dead NDOW links are retained in the audit and do not invalidate good records.",
            "The clean runner does not recursively crawl NDOW related-water links.",
            "FishNV is an optional map reference and never public-access proof.",
            "Only named access supported by official evidence is published.",
            "A county with no verified record remains searchable and is clearly labeled.",
        ],
    }

    nv.write_outputs(
        root,
        output_dir,
        db,
        status,
        audit,
        unverified_waters,
        orphan_access,
    )
    nv.patch_site_files(root)

    print(
        json.dumps(
            {
                "state": nv.STATE,
                "county_shells": 17,
                "valid_ndow_water_records": len(ndow_waters),
                "dead_or_unusable_ndow_links_ignored": len(ndow_warnings),
                "verified_public_waters": db["public_water_count"],
                "verified_access_points": db["verified_access_point_count"],
                "quarantined_unverified_waters": len(unverified_waters),
                "official_reports": db["report_count"],
                "populated_counties": validation["populated_counties"],
                "counties_without_verified_public_access": validation[
                    "counties_without_verified_public_access"
                ],
                "generated_at": generated_at,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
