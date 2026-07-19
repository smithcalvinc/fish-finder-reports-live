# Fish Finder Outdoors Report Generator — Static Live Build

Upload `index.html` to the root of a clean GitHub repository and import that repository into Wasmer.

Wasmer detects a root `index.html` as a static website. Open the main `.wasmer.app` address directly. This build does not use `/health`.

The browser retrieves live data from OpenStreetMap Nominatim, the National Weather Service, USGS Water Services, and NOAA Tides & Currents. The report remains usable when an individual source is unavailable.
