/* Fish Finder Outdoors — combined public-access and fishing-report search.
   Load data/idaho_fishing_report_database.js before this file. */
(function () {
  "use strict";

  function normalize(value) {
    return String(value || "").toLowerCase().replace(/\s+/g, " ").trim();
  }

  function db() {
    return window.IDAHO_FISHING_REPORT_DATABASE || { flat_waters: [], flat_reports: [] };
  }

  window.FFO_FISHING_REPORT_SEARCH = {
    counties: function () {
      return db().counties || [];
    },

    waters: function (options) {
      options = options || {};
      const county = normalize(options.county).replace(/\s+county$/, "");
      const query = normalize(options.query);
      const status = normalize(options.reportStatus);
      const needsRamp = options.boatRamp === true;
      const needsDock = options.dock === true;
      const needsRestroom = options.restroom === true;
      const needsCamping = options.camping === true;
      const needsAda = options.adaFishing === true;

      return (db().flat_waters || []).filter(function (water) {
        if (county && normalize(water.county) !== county) return false;
        if (status && normalize(water.report_status) !== status) return false;

        const points = water.access_points || [];
        if (needsRamp && !points.some(p => p.amenities && p.amenities.boat_ramp === true)) return false;
        if (needsDock && !points.some(p => p.amenities && p.amenities.dock === true)) return false;
        if (needsRestroom && !points.some(p => p.amenities && p.amenities.restroom === true)) return false;
        if (needsCamping && !points.some(p => p.amenities && p.amenities.camping === true)) return false;
        if (needsAda && !points.some(p => p.amenities && p.amenities.ada_fishing === true)) return false;

        if (!query) return true;
        const latest = water.latest_report || {};
        const haystack = normalize([
          water.water_name, water.water_type, water.county, water.drainage,
          water.access_details, latest.title, latest.summary, latest.species,
          latest.techniques, points.map(p => p.access_point_name).join(" ")
        ].join(" "));
        return haystack.includes(query);
      });
    },

    reports: function (options) {
      options = options || {};
      const county = normalize(options.county).replace(/\s+county$/, "");
      const query = normalize(options.query);
      const sourceType = normalize(options.sourceType);
      const currentOnly = options.currentOnly === true;

      return (db().flat_reports || []).filter(function (report) {
        if (county && !(report.counties || []).some(c => normalize(c) === county)) return false;
        if (sourceType && normalize(report.source_type) !== sourceType) return false;
        if (currentOnly && !["very_current", "current"].includes(report.freshness)) return false;
        if (!query) return true;
        return normalize([
          report.water_name, report.title, report.summary, report.species,
          report.techniques, report.source_name
        ].join(" ")).includes(query);
      });
    }
  };
})();
