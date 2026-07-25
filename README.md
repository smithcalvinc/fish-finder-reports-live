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


## Location-aware nearby-water shortcuts

The old fixed Southeast Idaho shortcut buttons have been removed.

The search page now:

- Shows a **Fishing Waters Near You** section
- Uses browser location only after permission is granted
- Automatically refreshes nearby waters on later visits when permission is already granted
- Searches approximately 50 miles around the visitor
- Updates the shortcut buttons after any town search
- Shows no Idaho-specific buttons to visitors in other states
- Falls back to the official state directory when nearby data is incomplete


## Installable app / PWA

The Fishing Reports beta is now a complete Progressive Web App.

- Opens in standalone app mode after installation
- Uses the approved `ffo-logo-main.png` branding
- Includes Android, desktop, iPhone and iPad installation support
- Includes a service worker and offline app shell
- Keeps live fishing, weather and map data network-first
- Provides an Install App button when supported
- Provides Add to Home Screen instructions for iPhone and iPad
- Includes app shortcuts for Nearby Waters, Submit Report and Official Sources


## Nearby-water reliability fix

Location lookup no longer depends on receiving a state name from reverse geocoding.
Verified local directory records are calculated directly from the visitor's coordinates
and displayed immediately. The broader GNIS nearby-water query then adds more results.
