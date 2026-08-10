const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const storage = new Map();
const context = {
  window: {},
  localStorage: {
    getItem(key) { return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { storage.set(key, String(value)); }
  },
  URL,
  URLSearchParams,
  AbortController,
  setTimeout,
  clearTimeout,
  console,
  fetch: async input => {
    const url = decodeURIComponent(String(input)).replace(/\+/g, " ");
    const features = [];
    if (url.includes("cartowfs.nationalmap.gov") && url.includes("LAKE OKEECHOBEE")) {
      features.push({
          attributes: {
            gaz_name: "Lake Okeechobee",
            gaz_featureclass: "Lake",
            state_alpha: "FL",
            county_name: "Palm Beach",
            gaz_id: 123456,
            isunknowncoords: 0
          },
          geometry: {x: -80.8, y: 26.9}
        });
    }
    if (url.includes("cartowfs.nationalmap.gov") && url.includes("CLEAR LAKE") && url.includes("state_alpha LIKE '%CA%'")) {
      features.push({
        attributes: {
          gaz_name: "Clear Lake",
          gaz_featureclass: "Lake",
          state_alpha: "CA",
          county_name: "Lake",
          gaz_id: 1658488,
          isunknowncoords: 0
        },
        geometry: {x: -122.75, y: 39.05}
      });
    }
    return {
      ok: true,
      json: async () => url.includes("nominatim.openstreetmap.org") ? [] : {features}
    };
  }
};
context.window.window = context.window;
vm.createContext(context);

for (const file of [
  "official_state_sources.js",
  "official_water_overrides.js",
  "official_access_index.js",
  "regional_water_search.js"
]) {
  vm.runInContext(fs.readFileSync(file, "utf8"), context, {filename: file});
}

async function main() {
  const search = context.window.FFO_REGION_SEARCH;
  const index = context.window.FFO_OFFICIAL_ACCESS_INDEX;
  const audit = await search.auditOfficialIndex();

  assert(audit.total >= 15500, `Expected at least 15,500 official access records; found ${audit.total}`);
  assert.equal(audit.reachable, audit.total, "Every official record must match its own canonical name");
  assert.deepEqual(audit.unreachable, []);

  for (const entry of index.states.California) {
    const rows = await search.search(`${entry.name} California`);
    assert(
      rows.some(row => row.name === entry.name && row.state === "California" && row.official_directory_match),
      `California official directory result was not searchable: ${entry.name}`
    );
  }

  for (const [stateName, entries] of Object.entries(index.states)) {
    const entry = entries[0];
    const rows = await search.search(`${entry.name} ${stateName}`);
    assert(
      rows.some(row => row.name === entry.name && row.state === stateName && row.official_directory_match),
      `Representative official directory result was not searchable in ${stateName}: ${entry.name}`
    );
  }

  const compactCases = [
    ["Clearlake CA", "Clear Lake", "California", "Lake"],
    ["LakeOroville CA", "Lake Oroville", "California", "Butte"]
  ];
  for (const [query, name, state, county] of compactCases) {
    const rows = await search.search(query);
    const matches = rows.filter(row => row.name === name && row.state === state && row.county === county);
    assert.equal(matches.length, 1, `${query} must return one ${name} official result`);
    assert.equal(matches[0].public_access_verified, true);
    assert.notEqual(matches[0].lat, 0, `${query} must not invent a zero latitude`);
    assert.notEqual(matches[0].lon, 0, `${query} must not invent a zero longitude`);
  }

  const famous = [
    "Clear Lake", "Eagle Lake", "Folsom Lake", "Lake Almanor",
    "Lake Berryessa", "Lake Oroville", "Lake Tahoe", "Shasta Lake", "Trinity Lake"
  ];
  for (const name of famous) {
    const rows = await search.search(`${name} CA`);
    assert(rows.some(row => row.name === name && row.state === "California"), `${name} must be searchable`);
  }

  const oregon = await search.search("Clear Lake OR");
  assert(oregon.some(row => row.name === "Clear Lake" && row.state === "Oregon"));
  assert(!oregon.some(row => row.state === "California"), "An explicit Oregon search must not return California");

  const nationwideCompact = await search.search("LakeOkeechobee FL");
  assert(
    nationwideCompact.some(row => row.name === "Lake Okeechobee" && row.state === "Florida"),
    "Camel-case compact water names must expand before the nationwide GNIS lookup"
  );

  console.log(`Official directory search regression: PASS (${audit.reachable}/${audit.total} names reachable)`);
}

main().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
