# Fish Finder Outdoors — Regional Public-Only Search

This build applies one access rule across the full coverage region:

**No water appears in normal search results unless open public access is verified.**

## Coverage

- Idaho
- Montana
- Wyoming
- Utah
- Nevada
- Oregon
- Washington
- Northern California
- Colorado

## How verification works

1. Existing state-agency verified local waters are accepted.
2. Official water names come from USGS GNIS.
3. Access is checked against the USGS PAD-US Public Access layer.
4. Only `Open Access` results pass.
5. `Private`, `Closed`, `Restricted`, and `Unknown/Unverified` results are hidden.
6. OpenStreetMap fallback results also have to pass the same access gate.

## Important tradeoff

This is intentionally conservative. It can hide a genuinely public water when no reliable public-access record exists. That is better than recommending a private or questionable pond.

## Upload

Upload every included file to the root of the existing report-generator GitHub repository.
Replace matching files and commit directly to `main`.

Do not modify:

`.github/workflows/update-fishing-reports.yml`
