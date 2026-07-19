# Fish Finder Outdoors Report Generator — Phase 5

Phase 5 expands actual official catch-report coverage and adds a map to every generated report.

## Map features

Every report now includes:

- An embedded OpenStreetMap map centered on the selected location
- Exact coordinates
- A full-map link
- A one-tap directions link
- A warning that a waterbody or catch-report area may be larger than the selected point

## Expanded actual-report coverage

The catch database now contains 34 dated agency reports covering selected locations in:

- Idaho
- Oregon
- Nevada
- Washington
- Wyoming

New coverage includes Lake Mead, Lake Mohave, Laughlin, Angel Lake, Wildhorse Reservoir,
South Fork Reservoir, Truckee River, James Kinney Pond, Lake Tahoe, Port Angeles,
Sekiu, Shilshole, Point Defiance, Kingston, Everett and Flaming Gorge.

## Accuracy rule

Reports appear only when the searched location matches a dated official agency record.
Unmatched locations still display “No dated catch report matched this location.”

## Update the live site

Upload these five files to the root of the existing GitHub repository:

- `index.html`
- `official_species_data.js`
- `recent_fishing_reports.js`
- `404.html`
- `README.md`

Commit the changes to `main`. The existing Wasmer app should update automatically.
