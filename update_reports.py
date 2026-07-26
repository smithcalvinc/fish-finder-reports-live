#!/usr/bin/env python3
"""
Fish Finder Outdoors admin-feed updater.

The statewide Idaho workflow already builds the authoritative county-by-county
database at data/idaho_fishing_report_database.json. This updater converts that
database into the two legacy JavaScript files used by admin.html:

- recent_fishing_reports.js
- update_status.js

Keeping this filename allows the existing "Update Fishing Report Sources"
GitHub workflow to continue working without restoring the old 45-report feed.
"""

from build_admin_dashboard_files import main


if __name__ == "__main__":
    raise SystemExit(main())
