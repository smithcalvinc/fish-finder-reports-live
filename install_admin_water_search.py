#!/usr/bin/env python3
"""Install the private Admin water search into the current repository files.

This patcher is intentionally idempotent. It reads the exact admin.html and
service-worker.js present in GitHub Actions, preserving all other code.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ADMIN = ROOT / "admin.html"
SERVICE_WORKER = ROOT / "service-worker.js"
ADMIN_SCRIPTS = (
    '<script src="data/admin_water_index.js"></script>\n'
    '<script src="admin-water-search.js"></script>\n'
)


def install_admin() -> None:
    text = ADMIN.read_text(encoding="utf-8")
    if 'src="admin-water-search.js"' not in text:
        marker = '<script src="brand-shell.js"></script>'
        if marker not in text:
            raise RuntimeError("admin.html brand-shell insertion point not found")
        text = text.replace(marker, ADMIN_SCRIPTS + marker, 1)
    if 'src="data/admin_water_index.js"' not in text:
        marker = '<script src="admin-water-search.js"></script>'
        text = text.replace(marker, '<script src="data/admin_water_index.js"></script>\n' + marker, 1)
    if text.count('src="admin-water-search.js"') != 1:
        raise RuntimeError("admin-water-search.js was inserted more than once")
    if text.count('src="data/admin_water_index.js"') != 1:
        raise RuntimeError("admin_water_index.js was inserted more than once")
    ADMIN.write_text(text, encoding="utf-8")


def add_array_entry(text: str, constant: str, entry: str) -> str:
    if entry in text:
        return text
    match = re.search(rf"(const\s+{re.escape(constant)}\s*=\s*\[)", text)
    if not match:
        raise RuntimeError(f"service-worker.js {constant} array not found")
    position = match.end()
    return text[:position] + f'\n  "{entry}",' + text[position:]


def install_service_worker() -> None:
    text = SERVICE_WORKER.read_text(encoding="utf-8")
    version_match = re.search(r'const CACHE_VERSION="ffo-reports-pwa-v(\d+)";', text)
    if not version_match:
        raise RuntimeError("service-worker cache version not found")
    current = int(version_match.group(1))
    target = max(current, 39)
    text = text[: version_match.start()] + f'const CACHE_VERSION="ffo-reports-pwa-v{target}";' + text[version_match.end() :]
    # Admin files are deliberately network-first rather than precached in the public PWA shell.
    for entry in ("admin.html", "admin-water-search.js", "data/admin_water_index.js"):
        text = add_array_entry(text, "NETWORK_FIRST_FILES", entry)
    SERVICE_WORKER.write_text(text, encoding="utf-8")


def validate() -> None:
    admin = ADMIN.read_text(encoding="utf-8")
    sw = SERVICE_WORKER.read_text(encoding="utf-8")
    for required in ('src="data/admin_water_index.js"', 'src="admin-water-search.js"'):
        if required not in admin:
            raise RuntimeError(f"Admin installation validation failed: {required}")
    for required in ("admin.html", "admin-water-search.js", "data/admin_water_index.js"):
        if required not in sw:
            raise RuntimeError(f"Service-worker installation validation failed: {required}")


def main() -> int:
    if not ADMIN.exists() or not SERVICE_WORKER.exists():
        raise FileNotFoundError("admin.html and service-worker.js must exist in the repository root")
    install_admin()
    install_service_worker()
    validate()
    print("ADMIN_WATER_SEARCH_INSTALLED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ADMIN_WATER_SEARCH_INSTALL_ERROR: {exc}", file=sys.stderr)
        raise
