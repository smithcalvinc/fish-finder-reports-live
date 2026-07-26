FISH FINDER OUTDOORS
COMPLETE IDAHO PUBLIC-ACCESS AND FISHING-REPORT DATABASE

THIS REPLACES THE EARLIER PACKAGE
---------------------------------
Use this complete package instead of the earlier public-access-only package.

WHAT IT BUILDS
--------------
One GitHub workflow builds both parts of the report page:

1. VERIFIED PUBLIC ACCESS
   - Lakes, reservoirs, ponds, rivers, creeks and streams whose official Idaho
     Fish and Game record explicitly says public
   - Active IDFG-managed or co-managed public fishing/boating access points
   - Coordinates, directions, ramps, docks, restrooms, camping, ADA access,
     walking-only restrictions, day-use notes and private-land warnings

2. CURRENT FISHING REPORTS
   - Idaho Fish and Game fishing news and updates
   - IDFG stocking forecasts
   - IDFG Chinook and steelhead harvest reports
   - Current Idaho reports from Sportsman's Warehouse
   - Manually verified public Facebook or other social-media post links

EVERY PUBLIC WATER REMAINS IN THE DATABASE
------------------------------------------
A public water is not removed simply because no one has posted a recent report.
Its report_status will say:

  no_recent_public_report_found

That is accurate and much safer than inventing a report.

FACEBOOK LIMIT
--------------
Facebook Groups cannot be dependably downloaded automatically. Meta removed the
Groups API. Public Page access also requires an approved Meta app and tokens.

To include a useful public Facebook post:
1. Open data/public_social_reports.csv.
2. Duplicate the template row.
3. Enter the public post URL, date, county, water and your own short summary.
4. Set active=true.
5. Set verified_public_post=true.
6. Commit the CSV to GitHub.
7. Run the workflow again.

Do not copy an entire Facebook post. Use a short factual summary and link back
to the original public post.

UPLOAD AND RUN
--------------
1. Unzip this package.
2. Upload every unzipped file and folder into the ROOT of the existing
   fish-finder-reports-live GitHub repository.
3. Preserve the folder structure, especially:
      .github/workflows/
      config/
      data/
4. Open GitHub Actions.
5. Select "Update All Idaho Fishing Data."
6. Click "Run workflow."
7. Wait for the action to turn green.

The workflow then runs automatically every day.

FILES FOR THE WEBSITE
---------------------
Load these in this order:

<script src="data/idaho_fishing_report_database.js"></script>
<script src="fishing_report_search.js"></script>

Search Ada County:

const waters = FFO_FISHING_REPORT_SEARCH.waters({
  county: "Ada"
});

Only waters with current reports:

const waters = FFO_FISHING_REPORT_SEARCH.waters({
  county: "Ada",
  reportStatus: "current"
});

Find public waters with a boat ramp:

const waters = FFO_FISHING_REPORT_SEARCH.waters({
  county: "Ada",
  boatRamp: true
});

OUTPUT FILES
------------
data/idaho_public_fishing_access.json
data/idaho_public_fishing_access.js
data/idaho_public_fishing_access.csv
data/idaho_fishing_report_database.json
data/idaho_fishing_report_database.js
data/idaho_fishing_report_database.csv
data/idaho_fishing_report_summary.csv
data/public_access_build_report.json
data/fishing_report_build_report.json

IMPORTANT
---------
A fishing report is an observation, not a guarantee. Conditions, closures,
water levels, access routes and landowner agreements may change quickly. The
site should always display the report date, source link and freshness label.
