#!/usr/bin/env python3
"""
Fish Finder Outdoors source monitor.

This script checks every unique source URL in recent_fishing_reports.js,
updates report freshness and source-health metadata, and writes:
- recent_fishing_reports.js
- update_status.js
- source_check_log.json

It intentionally does NOT rewrite catch totals or fishing claims from arbitrary
webpage text. A changed source is flagged for human review so bad extraction
cannot silently become a published fishing report.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPORTS_FILE = ROOT / "recent_fishing_reports.js"
STATUS_FILE = ROOT / "update_status.js"
LOG_FILE = ROOT / "source_check_log.json"

USER_AGENT = (
    "FishFinderOutdoorsSourceMonitor/1.0 "
    "(+https://fishfinderoutdoors.com; public fishing-report freshness checker)"
)
CURRENT_DAYS = 14
AGING_DAYS = 45

OFFICIAL_DIRECTORY_SOURCES = {
    "Idaho": "https://idfg.idaho.gov/ifwis/fishingPlanner/",
    "Montana": "https://myfwp.mt.gov/fishMT/explore",
    "Wyoming": "https://wgfd.wyo.gov/fishing-boating/places-fish-wyoming",
    "Utah": "https://dwrapps.utah.gov/fishing/",
    "Nevada": "https://www.ndow.org/get-outside/fishing-stocking-reports/database/",
    "Oregon": "https://myodfw.com/fishing",
    "Washington": "https://wdfw.wa.gov/fishing/locations",
    "California": "https://wildlife.ca.gov/Fishing/Guide",
    "Colorado": "https://cpw.state.co.us/fishing",
}


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(value: dt.datetime | None = None) -> str:
    return (value or utc_now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_js_object(path: Path, variable_name: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"window\.{re.escape(variable_name)}\s*=\s*(\{{.*\}})\s*;\s*$",
        text,
        flags=re.S,
    )
    if not match:
        raise ValueError(f"Could not parse {variable_name} from {path.name}")
    data = json.loads(match.group(1))
    if not isinstance(data, dict):
        raise TypeError(f"{variable_name} must contain an object")
    return data


def write_js_object(path: Path, variable_name: str, data: dict[str, Any], comment: str) -> None:
    rendered = (
        f"/* {comment} */\n"
        f"window.{variable_name} = "
        + json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)
        + ";\n"
    )
    path.write_text(rendered, encoding="utf-8")


def strip_visible_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", " ", raw_html)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def first_match(patterns: list[str], value: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.I | re.S)
        if match:
            return html.unescape(match.group(1)).strip()
    return None


def page_metadata(raw_html: str) -> dict[str, str | None]:
    title = first_match([r"<title[^>]*>(.*?)</title>"], raw_html)
    published = first_match(
        [
            r'<meta[^>]+(?:property|name)=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']article:published_time["\']',
            r'"datePublished"\s*:\s*"([^"]+)"',
            r'<time[^>]+datetime=["\']([^"\']+)["\']',
        ],
        raw_html,
    )
    modified = first_match(
        [
            r'<meta[^>]+(?:property|name)=["\']article:modified_time["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']article:modified_time["\']',
            r'"dateModified"\s*:\s*"([^"]+)"',
        ],
        raw_html,
    )
    return {"title": title, "published": published, "modified": modified}


def fetch_source(url: str, timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "identity",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(5_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            visible = strip_visible_text(text)
            metadata = page_metadata(text)
            return {
                "ok": True,
                "http_status": int(getattr(response, "status", 200)),
                "final_url": response.geturl(),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "content_hash": hashlib.sha256(visible.encode("utf-8")).hexdigest(),
                "title": metadata["title"],
                "page_published": metadata["published"],
                "page_modified": metadata["modified"],
                "excerpt": visible[:500],
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "http_status": exc.code,
            "final_url": url,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "error": f"HTTP {exc.code}: {exc.reason}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "http_status": None,
            "final_url": url,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def parse_date(value: Any) -> dt.date | None:
    if not value:
        return None
    raw = str(value).strip()
    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


def freshness(published_date: Any, today: dt.date) -> tuple[str, int | None]:
    parsed = parse_date(published_date)
    if parsed is None:
        return "unknown", None
    days = max(0, (today - parsed).days)
    if days <= CURRENT_DAYS:
        return "current", days
    if days <= AGING_DAYS:
        return "aging", days
    return "stale", days


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Recalculate freshness without requesting source pages.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-source request timeout in seconds.",
    )
    args = parser.parse_args()

    data = load_js_object(REPORTS_FILE, "FFO_RECENT_REPORTS")
    reports = data.get("reports")
    if not isinstance(reports, list):
        raise TypeError("recent_fishing_reports.js must contain a reports list")

    run_time = utc_now()
    today = run_time.date()
    checked_at = iso_utc(run_time)

    report_urls = sorted(
        {
            str(report.get("source_url", "")).strip()
            for report in reports
            if str(report.get("source_url", "")).strip()
        }
    )
    directory_urls = sorted(set(OFFICIAL_DIRECTORY_SOURCES.values()))
    unique_urls = sorted(set(report_urls + directory_urls))

    fetched: dict[str, dict[str, Any]] = {}
    if not args.offline:
        for index, url in enumerate(unique_urls, start=1):
            print(f"[{index}/{len(unique_urls)}] Checking {url}", flush=True)
            fetched[url] = fetch_source(url, timeout=args.timeout)
            time.sleep(0.35)

    changed_count = 0
    review_count = 0
    unreachable_count = 0
    freshness_counts = {"current": 0, "aging": 0, "stale": 0, "unknown": 0}

    for report in reports:
        status, age_days = freshness(report.get("published_date"), today)
        report["freshness_status"] = status
        report["freshness_days"] = age_days
        freshness_counts[status] = freshness_counts.get(status, 0) + 1

        url = str(report.get("source_url", "")).strip()
        result = fetched.get(url)

        if args.offline:
            report.setdefault("last_checked_at", checked_at)
            report.setdefault("source_status", "not_checked")
            report.setdefault("review_required", False)
            continue

        report["last_checked_at"] = checked_at

        if not result or not result.get("ok"):
            unreachable_count += 1
            report["source_status"] = "unreachable"
            report["source_http_status"] = result.get("http_status") if result else None
            report["source_error"] = result.get("error") if result else "No source result"
            report["review_required"] = bool(report.get("review_required", False))
            continue

        previous_hash = str(report.get("source_content_hash", "") or "")
        current_hash = str(result.get("content_hash", "") or "")
        changed = bool(previous_hash and current_hash and previous_hash != current_hash)

        report["source_status"] = "changed" if changed else ("ok" if previous_hash else "baseline")
        report["source_http_status"] = result.get("http_status")
        report["source_error"] = None
        report["source_final_url"] = result.get("final_url")
        report["source_etag"] = result.get("etag")
        report["source_last_modified"] = result.get("last_modified")
        report["source_page_title"] = result.get("title")
        report["source_page_published"] = result.get("page_published")
        report["source_page_modified"] = result.get("page_modified")
        report["source_content_hash"] = current_hash
        report["source_excerpt"] = result.get("excerpt")
        report["source_response_ms"] = result.get("elapsed_ms")

        # Once a change is flagged, keep it flagged until a person reviews the
        # report and manually sets review_required to false.
        if changed:
            report["review_required"] = True
            changed_count += 1
        else:
            report["review_required"] = bool(report.get("review_required", False))

        if report["review_required"]:
            review_count += 1

    data["version"] = f"{today.isoformat()}-phase6-monitor"
    data["updated_at"] = today.isoformat()
    data["source_monitor_last_run"] = checked_at
    data["source_monitor_mode"] = "offline" if args.offline else "live"
    write_js_object(
        REPORTS_FILE,
        "FFO_RECENT_REPORTS",
        data,
        "Dated official fishing reports with automatic freshness and source-health metadata.",
    )

    source_rows = []
    directory_by_url = {url: state for state, url in OFFICIAL_DIRECTORY_SOURCES.items()}
    for url in unique_urls:
        related = [r for r in reports if str(r.get("source_url", "")).strip() == url]
        first = related[0] if related else {}
        result = fetched.get(url, {})
        directory_state = directory_by_url.get(url)
        source_rows.append(
            {
                "source_url": url,
                "source_type": "official_state_directory" if directory_state else "fishing_report_source",
                "state": directory_state,
                "agency": first.get("agency") or (f"{directory_state} official fishing directory" if directory_state else None),
                "report_count": len(related),
                "status": (
                    "not_checked"
                    if args.offline
                    else ("ok" if result.get("ok") else "unreachable")
                ),
                "http_status": result.get("http_status"),
                "title": result.get("title"),
                "last_modified": result.get("last_modified"),
                "page_published": result.get("page_published"),
                "page_modified": result.get("page_modified"),
                "elapsed_ms": result.get("elapsed_ms"),
                "error": result.get("error"),
            }
        )

    status_data = {
        "last_run": checked_at,
        "mode": "offline" if args.offline else "live",
        "reports_total": len(reports),
        "unique_sources": len(unique_urls),
        "official_directories_total": len(OFFICIAL_DIRECTORY_SOURCES),
        "official_directories_unreachable": sum(
            1 for url in OFFICIAL_DIRECTORY_SOURCES.values()
            if not args.offline and not fetched.get(url, {}).get("ok")
        ),
        "freshness": freshness_counts,
        "changed_reports": changed_count,
        "review_required": sum(1 for r in reports if r.get("review_required")),
        "unreachable_sources": unreachable_count,
        "sources": source_rows,
        "note": (
            "Source changes are flagged for review. Catch numbers are never "
            "automatically rewritten from unstructured webpage text."
        ),
    }
    write_js_object(
        STATUS_FILE,
        "FFO_UPDATE_STATUS",
        status_data,
        "Automatic source-monitor status used by the public site and review dashboard.",
    )
    LOG_FILE.write_text(json.dumps(status_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({k: v for k, v in status_data.items() if k != "sources"}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Source monitor failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
