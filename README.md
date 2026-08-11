# Fish Finder Outdoors — Fishing Location Finder

Fish Finder Outdoors is a location-first directory for publicly accessible fishing waters in nine western states. It is designed for all anglers. Fishing reports are optional historical context, not the product's main focus.

## Current coverage

The bundled official-access snapshot was assembled on August 10, 2026 and contains 15,501 named location records:

| Region | Records |
| --- | ---: |
| Idaho | 12,096 |
| Montana | 739 |
| Wyoming | 468 |
| Utah | 860 |
| Nevada | 26 |
| Oregon | 52 |
| Washington | 176 |
| Northern California | 57 |
| Colorado | 1,027 |

The directory searches imported state-agency and other public-access records first. Records without dependable coordinates remain searchable, but the app does not invent a map marker or substitute `0,0`.

## What each location can show

- Location map and directions when dependable coordinates are known
- Current weather when a mapped location is opened and the weather service responds
- Known fish species tied to the named water
- Camping, boat launches, day-use areas and public shoreline access at the location or within five miles
- The newest approved fishing report and its original report date, when one exists
- Official source and regulation links when available

Missing data is stated plainly as **Information not currently known.**

Live weather and nearby amenity lookups happen only when a visitor opens a location. They do not rewrite the stored location or report data.

## Fishing-report policy

Visitors can submit reports through `submit-report.html`. Submissions are reviewed before publication. Once approved, a report remains available as that location's last dated report until a newer approved report replaces it. The app does not create placeholder reports, change report dates or remove a valid report merely because it is old.

Approved reports live in `community_fishing_reports.js`. Agency report snapshots can remain in `recent_fishing_reports.js` as dated historical information.

## Add or correct a location

Visitors can use `report-water.html` to report:

- A missing publicly accessible fishing water
- A private or closed water shown in search
- Wrong public-access or facility information
- An incorrect name, water type or map location

After review, approved additions and corrections are stored in `official_water_overrides.js`.

## Data maintenance

All GitHub Actions in `.github/workflows/` are manual-only (`workflow_dispatch`). There are no scheduled or push-triggered data refreshes. An administrator can run a state builder deliberately when an official source has materially changed, review the generated diff, and then publish it.

`official-sources.html` lists the responsible fish-and-wildlife source for each state. The search fallback warns users when access is not verified and directs them to the appropriate agency source.

## Installable app

The site is a Progressive Web App named **FFO Finder**. It provides an offline app shell while keeping current weather, maps and live nearby-amenity lookups network-first.

## Local verification

Run the location-finder acceptance checks before publication:

```bash
python tests/verify_location_finder.py
```
