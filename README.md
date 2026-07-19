# Fish Finder Outdoors — Phase 6.2

Phase 6.2 replaces one-water-at-a-time search patches with full regional water-name coverage.

## Coverage region

- Idaho
- Montana
- Wyoming
- Utah
- Nevada
- Oregon
- Washington
- Northern California
- Colorado

## How location search now works

1. Verified local aliases are checked first.
2. The official USGS Geographic Names Information System is searched for hydrographic points and lines.
3. OpenStreetMap is used as a fallback for towns, access areas and names not returned by GNIS.
4. Coordinates remain supported.

The official GNIS search covers lakes, reservoirs, ponds, rivers, streams, canals, bays and other named water features across the entire region. It also accepts common shorthand such as Res., Lk. and Rvr.

## Important distinction

GNIS verifies the official water name and location. It does not prove public access, fishing conditions, fish species or current regulations. The report still links to the appropriate state fish and wildlife agency for those details.

## Upload

Upload every file in this package to the root of the existing GitHub repository.
Replace files with the same names and commit directly to `main`.

Do not edit or replace:

`.github/workflows/update-fishing-reports.yml`

This package contains no workflow file and no Supabase files.
