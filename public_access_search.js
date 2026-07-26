/* Fish Finder Outdoors — public-access search helper.
   Load data/idaho_public_fishing_access.js before this file. */
(function () {
  "use strict";

  function normalized(value) {
    return String(value || "").toLowerCase().replace(/\s+/g, " ").trim();
  }

  function amenityMatches(record, filters) {
    const a = record.amenities || {};
    if (filters.boatRamp === true && a.boat_ramp !== true) return false;
    if (filters.dock === true && a.dock !== true) return false;
    if (filters.restroom === true && a.restroom !== true) return false;
    if (filters.camping === true && a.camping !== true) return false;
    if (filters.adaFishing === true && a.ada_fishing !== true) return false;
    return true;
  }

  window.FFO_PUBLIC_ACCESS_SEARCH = {
    all: function () {
      const db = window.IDAHO_PUBLIC_FISHING_ACCESS;
      return db && Array.isArray(db.flat_records) ? db.flat_records : [];
    },

    byCounty: function (county) {
      const target = normalized(county).replace(/\s+county$/, "");
      return this.all().filter((record) => normalized(record.county) === target);
    },

    search: function (options) {
      options = options || {};
      const query = normalized(options.query);
      const county = normalized(options.county).replace(/\s+county$/, "");
      const kind = normalized(options.recordKind);
      const type = normalized(options.waterType);
      const filters = options.amenities || {};

      return this.all().filter((record) => {
        if (county && normalized(record.county) !== county) return false;
        if (kind && normalized(record.record_kind) !== kind) return false;
        if (type && normalized(record.water_type) !== type) return false;
        if (!amenityMatches(record, filters)) return false;

        if (!query) return true;
        const haystack = normalized([
          record.water_name,
          record.access_point_name,
          record.county,
          record.water_type,
          record.access_details,
          record.access_category
        ].join(" "));
        return haystack.includes(query);
      });
    }
  };
})();
