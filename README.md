# Fish Finder Outdoors — State-Agency-First Directory Build

This is the proper regional beta architecture.

## Search hierarchy

1. Approved state-agency and local verified records
2. Approved missing-water corrections
3. Official USGS geographic water names
4. Map fallback records with access warnings
5. Direct link to the correct official state fishing directory

The search no longer treats one national access dataset as a complete fishing directory.

## Sustainable correction workflow

Visitors can use `report-water.html` to report:

- A missing public fishing water
- A private or closed water shown in search
- Wrong access information
- Wrong name or map location

In `admin.html`, paste the correction email, resolve or edit coordinates, then approve it.

The admin downloads one replacement file:

`official_water_overrides.js`

That file stores both:

- Public water additions
- Hidden private/closed-water corrections

## Official directory page

`official-sources.html` lists the primary fishing directory and rules source for all nine states/areas.

## Upload

Upload every included file to the root of the existing report-generator GitHub repository.
Replace files with the same names and commit directly to `main`.

Do not change `.github/workflows/update-fishing-reports.yml`.
