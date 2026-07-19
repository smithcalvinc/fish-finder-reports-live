/* Official state fishing directories used by Fish Finder Outdoors.
   These are the primary verification links. Search results may also use
   USGS official geographic names and map records to locate waters. */
window.FFO_STATE_SOURCES = {
  version: "2026-07-19-state-agency-first",
  updated_at: "2026-07-19",
  coverage_note: "Official state fishing directories are the primary verification sources. Each state publishes its data differently, so the site also uses official geographic names to help locate waters.",
  states: [
    {
      state:"Idaho",code:"ID",agency:"Idaho Department of Fish and Game",
      directory_url:"https://idfg.idaho.gov/ifwis/fishingPlanner/",
      rules_url:"https://idfg.idaho.gov/rules/fish",
      stocking_url:"https://idfg.idaho.gov/ifwis/fishingplanner/stocking/",
      description:"Fishing Planner with detailed water, species, facilities, stocking and rules information.",
      coverage_label:"12,000+ rivers, lakes and streams"
    },
    {
      state:"Montana",code:"MT",agency:"Montana Fish, Wildlife & Parks",
      directory_url:"https://myfwp.mt.gov/fishMT/explore",
      access_url:"https://fwp.mt.gov/fish/fishing-access",
      rules_url:"https://fwp.mt.gov/fish/regulations",
      description:"FishMT waterbody and Fishing Access Site explorer.",
      coverage_label:"Waterbodies and public Fishing Access Sites"
    },
    {
      state:"Wyoming",code:"WY",agency:"Wyoming Game and Fish Department",
      directory_url:"https://wgfd.wyo.gov/fishing-boating/places-fish-wyoming",
      rules_url:"https://wgfd.wyo.gov/regulations",
      description:"Interactive Wyoming Fishing Guide with waters, species and public access layers.",
      coverage_label:"State fishing guide and access layers"
    },
    {
      state:"Utah",code:"UT",agency:"Utah Division of Wildlife Resources",
      directory_url:"https://dwrapps.utah.gov/fishing/",
      search_template:"https://dwrapps.utah.gov/fishing/?NA={query}",
      rules_url:"https://wildlife.utah.gov/guidebooks?sec=10",
      description:"Fish Utah map with waters, species, forecasts, stocking and regulations.",
      coverage_label:"Statewide Fish Utah waterbody map"
    },
    {
      state:"Nevada",code:"NV",agency:"Nevada Department of Wildlife",
      directory_url:"https://fish.wildlifenv.com/",
      reports_url:"https://www.ndow.org/get-outside/fishing-stocking-reports/database/",
      rules_url:"https://www.ndow.org/rules-regulations/",
      description:"FishNV map and the official fishing and stocking reports database.",
      coverage_label:"541 mapped fishable waters"
    },
    {
      state:"Oregon",code:"OR",agency:"Oregon Department of Fish and Wildlife",
      directory_url:"https://myodfw.com/fishing",
      reports_url:"https://myodfw.com/recreation-report/fishing-report",
      rules_url:"https://myodfw.com/fishing/regulations",
      stocking_url:"https://myodfw.com/fishing/species/trout/stocking-schedule",
      description:"ODFW fishing zones, recreation reports, stocking maps and regulations.",
      coverage_label:"State fishing zones, reports and stocking resources"
    },
    {
      state:"Washington",code:"WA",agency:"Washington Department of Fish and Wildlife",
      directory_url:"https://wdfw.wa.gov/fishing/locations",
      access_url:"https://wdfw.wa.gov/places-to-go/water-access-sites",
      rules_url:"https://wdfw.wa.gov/fishing/regulations",
      description:"Lowland lakes, high lakes, marine areas and hundreds of managed water access sites.",
      coverage_label:"Fishing locations and water access areas"
    },
    {
      state:"California",code:"CA",agency:"California Department of Fish and Wildlife",
      directory_url:"https://wildlife.ca.gov/Fishing/Guide",
      rules_url:"https://wildlife.ca.gov/Regulations/Fishing",
      description:"Map-based Fishing Guide with fishing locations, regulations, planting and boat launches.",
      coverage_label:"Northern California coverage in this beta"
    },
    {
      state:"Colorado",code:"CO",agency:"Colorado Parks and Wildlife",
      directory_url:"https://cpw.state.co.us/fishing",
      rules_url:"https://cpw.state.co.us/rules-and-regulations",
      stocking_url:"https://cpw.state.co.us/activities/fishing/fishing-awards-and-records/fish-stocking-report",
      description:"Colorado Fishing Atlas with waters, access, species, ramps, regulations and stocking.",
      coverage_label:"Statewide Colorado Fishing Atlas"
    }
  ]
};

(function(api){
  const aliases={
    idaho:"Idaho",id:"Idaho",
    montana:"Montana",mt:"Montana",
    wyoming:"Wyoming",wy:"Wyoming",
    utah:"Utah",ut:"Utah",
    nevada:"Nevada",nv:"Nevada",
    oregon:"Oregon",or:"Oregon",
    washington:"Washington",wa:"Washington",
    california:"California",ca:"California",
    colorado:"Colorado",co:"Colorado"
  };
  const clean=value=>String(value||"").trim();
  const norm=value=>clean(value).toLowerCase().replace(/[^a-z0-9\s]/g," ").replace(/\s+/g," ").trim();

  api.byState=function(value){
    const key=norm(value);
    const canonical=aliases[key]||api.states.find(row=>norm(row.state)===key||norm(row.code)===key)?.state;
    return api.states.find(row=>row.state===canonical)||null;
  };

  api.detect=function(query,rows){
    for(const row of rows||[]){
      const found=api.byState(row.state);
      if(found)return found;
    }
    const text=` ${norm(query)} `;
    for(const row of api.states){
      if(text.includes(` ${norm(row.state)} `)||text.endsWith(` ${norm(row.code)} `))return row;
    }
    return null;
  };

  api.searchUrl=function(source,query){
    if(!source)return"";
    if(source.search_template){
      return source.search_template.replace("{query}",encodeURIComponent(clean(query)));
    }
    return source.directory_url;
  };
})(window.FFO_STATE_SOURCES);
