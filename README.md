# Fish Finder Outdoors Report Generator — Phase 3

Phase 3 replaces species guesses with a separate exact-waterbody database built from official state fish-and-wildlife sources.

## New
- Exact official waterbody matching
- Separate labels for agency-recommended fish, survey observations, stocking records and other documented fish
- Exact source link and source-check date
- Initial official records for selected waters in Idaho, Montana, Wyoming, Utah, Nevada, Oregon, Washington, northern California and Colorado
- No statewide species fallback
- Separate `official_species_data.js` file for adding more waters safely

This is the official-data foundation, not complete coverage of every water. Unmatched waters show no species.

## Upload
Replace/upload these four root files in the existing GitHub repository:
- `index.html`
- `official_species_data.js`
- `404.html`
- `README.md`

Commit to `main`; the existing Wasmer app should update automatically.
