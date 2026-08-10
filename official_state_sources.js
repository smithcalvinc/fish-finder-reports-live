/* Official state fishing sources used by Fish Finder Outdoors.
   Every state is represented so a national search always reaches the
   responsible fish and wildlife agency. Species are still displayed only
   when FFO has evidence tied to the exact named water. */
window.FFO_STATE_SOURCES = {
  version: "2026.08.10-v57-all-states",
  updated_at: "2026-08-10",
  coverage_note: "All 50 states link to their official fish and wildlife source. Exact-water species are published only when a state record, survey, stocking entry, or official water page names that water.",
  states: [
    {state:"Alabama",code:"AL",agency:"Alabama Division of Wildlife and Freshwater Fisheries",directory_url:"https://www.outdooralabama.com/freshwater-fishing",official_domains:["outdooralabama.com"]},
    {state:"Alaska",code:"AK",agency:"Alaska Department of Fish and Game",directory_url:"https://www.adfg.alaska.gov/index.cfm?adfg=fishing.main",official_domains:["adfg.alaska.gov"]},
    {state:"Arizona",code:"AZ",agency:"Arizona Game and Fish Department",directory_url:"https://www.azgfd.com/fishing-2/where-to-fish/",official_domains:["azgfd.com"]},
    {state:"Arkansas",code:"AR",agency:"Arkansas Game and Fish Commission",directory_url:"https://www.agfc.com/fishing/where-fish/",official_domains:["agfc.com"]},
    {
      state:"California",code:"CA",agency:"California Department of Fish and Wildlife",
      directory_url:"https://wildlife.ca.gov/Fishing/Guide",rules_url:"https://wildlife.ca.gov/Regulations/Fishing",
      official_domains:["wildlife.ca.gov","apps.wildlife.ca.gov","parks.ca.gov"],
      description:"Map-based Fishing Guide with fishing locations, regulations, planting and boat launches.",
      coverage_label:"Official statewide fishing source"
    },
    {
      state:"Colorado",code:"CO",agency:"Colorado Parks and Wildlife",
      directory_url:"https://cpw.state.co.us/bodies-water-finder",rules_url:"https://cpw.state.co.us/rules-and-regulations",
      stocking_url:"https://cpw.state.co.us/activities/fishing/fishing-awards-and-records/fish-stocking-report",
      official_domains:["cpw.state.co.us"],
      description:"Bodies of Water Finder, fishery surveys, stocking information and regulations.",
      coverage_label:"Official statewide fishing source"
    },
    {state:"Connecticut",code:"CT",agency:"Connecticut DEEP Fisheries Division",directory_url:"https://portal.ct.gov/deep/fishing/freshwater/freshwater-fishing",official_domains:["portal.ct.gov"]},
    {state:"Delaware",code:"DE",agency:"Delaware Division of Fish and Wildlife",directory_url:"https://dnrec.delaware.gov/fish-wildlife/fishing/",official_domains:["dnrec.delaware.gov"]},
    {state:"Florida",code:"FL",agency:"Florida Fish and Wildlife Conservation Commission",directory_url:"https://myfwc.com/fishing/freshwater/sites-forecasts/",official_domains:["myfwc.com"]},
    {state:"Georgia",code:"GA",agency:"Georgia Wildlife Resources Division",directory_url:"https://georgiawildlife.com/fishing/locations",official_domains:["georgiawildlife.com"]},
    {state:"Hawaii",code:"HI",agency:"Hawaii Division of Aquatic Resources",directory_url:"https://dlnr.hawaii.gov/dar/fishing/",official_domains:["dlnr.hawaii.gov"]},
    {
      state:"Idaho",code:"ID",agency:"Idaho Department of Fish and Game",
      directory_url:"https://idfg.idaho.gov/ifwis/fishingPlanner/",rules_url:"https://idfg.idaho.gov/rules/fish",
      stocking_url:"https://idfg.idaho.gov/ifwis/fishingplanner/stocking/",official_domains:["idfg.idaho.gov"],
      description:"Fishing Planner with detailed water, species, facilities, stocking and rules information.",
      coverage_label:"12,000+ rivers, lakes and streams"
    },
    {state:"Illinois",code:"IL",agency:"Illinois Department of Natural Resources",directory_url:"https://dnr.illinois.gov/fishing.html",official_domains:["dnr.illinois.gov"]},
    {state:"Indiana",code:"IN",agency:"Indiana Division of Fish and Wildlife",directory_url:"https://www.in.gov/dnr/fish-and-wildlife/fishing/",official_domains:["in.gov"]},
    {state:"Iowa",code:"IA",agency:"Iowa Department of Natural Resources",directory_url:"https://www.iowadnr.gov/things-to-do/fishing",official_domains:["iowadnr.gov"]},
    {state:"Kansas",code:"KS",agency:"Kansas Department of Wildlife and Parks",directory_url:"https://ksoutdoors.com/Fishing/Where-to-Fish-in-Kansas",official_domains:["ksoutdoors.com"]},
    {state:"Kentucky",code:"KY",agency:"Kentucky Department of Fish and Wildlife Resources",directory_url:"https://fw.ky.gov/Fish/Pages/default.aspx",official_domains:["fw.ky.gov"]},
    {state:"Louisiana",code:"LA",agency:"Louisiana Department of Wildlife and Fisheries",directory_url:"https://www.wlf.louisiana.gov/page/recreational-fishing",official_domains:["wlf.louisiana.gov"]},
    {state:"Maine",code:"ME",agency:"Maine Department of Inland Fisheries and Wildlife",directory_url:"https://www.maine.gov/ifw/fishing-boating/fishing/index.html",official_domains:["maine.gov"]},
    {state:"Maryland",code:"MD",agency:"Maryland Department of Natural Resources",directory_url:"https://dnr.maryland.gov/fisheries/pages/hotspots.aspx",official_domains:["dnr.maryland.gov"]},
    {state:"Massachusetts",code:"MA",agency:"Massachusetts Division of Fisheries and Wildlife",directory_url:"https://www.mass.gov/freshwater-fishing",official_domains:["mass.gov"]},
    {state:"Michigan",code:"MI",agency:"Michigan Department of Natural Resources",directory_url:"https://www.michigan.gov/dnr/things-to-do/fishing/where",official_domains:["michigan.gov"]},
    {state:"Minnesota",code:"MN",agency:"Minnesota Department of Natural Resources",directory_url:"https://www.dnr.state.mn.us/lakefind/index.html",official_domains:["dnr.state.mn.us"]},
    {state:"Mississippi",code:"MS",agency:"Mississippi Department of Wildlife, Fisheries and Parks",directory_url:"https://www.mdwfp.com/fishing-boating",official_domains:["mdwfp.com"]},
    {state:"Missouri",code:"MO",agency:"Missouri Department of Conservation",directory_url:"https://mdc.mo.gov/fishing/where-fish",official_domains:["mdc.mo.gov"]},
    {
      state:"Montana",code:"MT",agency:"Montana Fish, Wildlife and Parks",
      directory_url:"https://myfwp.mt.gov/fishMT/explore",access_url:"https://fwp.mt.gov/fish/fishing-access",
      rules_url:"https://fwp.mt.gov/fish/regulations",official_domains:["fwp.mt.gov","myfwp.mt.gov","fwp-gis.mt.gov"],
      description:"FishMT waterbody and Fishing Access Site explorer.",coverage_label:"Waterbodies and public Fishing Access Sites"
    },
    {state:"Nebraska",code:"NE",agency:"Nebraska Game and Parks Commission",directory_url:"https://outdoornebraska.gov/fish/",official_domains:["outdoornebraska.gov"]},
    {
      state:"Nevada",code:"NV",agency:"Nevada Department of Wildlife",
      directory_url:"https://fish.wildlifenv.com/",reports_url:"https://www.ndow.org/get-outside/fishing-stocking-reports/database/",
      rules_url:"https://www.ndow.org/rules-regulations/",official_domains:["ndow.org","fish.wildlifenv.com"],
      description:"FishNV map and the official fishing and stocking reports database.",coverage_label:"Official statewide fishing source"
    },
    {state:"New Hampshire",code:"NH",agency:"New Hampshire Fish and Game Department",directory_url:"https://www.wildlife.nh.gov/fishing-new-hampshire",official_domains:["wildlife.nh.gov"]},
    {state:"New Jersey",code:"NJ",agency:"New Jersey Fish and Wildlife",directory_url:"https://dep.nj.gov/njfw/fishing/freshwater/",official_domains:["dep.nj.gov"]},
    {state:"New Mexico",code:"NM",agency:"New Mexico Department of Game and Fish",directory_url:"https://wildlife.dgf.nm.gov/fishing/",official_domains:["wildlife.dgf.nm.gov"]},
    {state:"New York",code:"NY",agency:"New York State Department of Environmental Conservation",directory_url:"https://dec.ny.gov/things-to-do/freshwater-fishing/places-to-fish",official_domains:["dec.ny.gov"]},
    {state:"North Carolina",code:"NC",agency:"North Carolina Wildlife Resources Commission",directory_url:"https://www.ncwildlife.gov/Fishing/Where-to-Fish",official_domains:["ncwildlife.gov"]},
    {state:"North Dakota",code:"ND",agency:"North Dakota Game and Fish Department",directory_url:"https://gf.nd.gov/fishing/where-to-fish",official_domains:["gf.nd.gov"]},
    {state:"Ohio",code:"OH",agency:"Ohio Division of Wildlife",directory_url:"https://ohiodnr.gov/go-and-do/plan-a-visit/find-a-property",official_domains:["ohiodnr.gov"]},
    {state:"Oklahoma",code:"OK",agency:"Oklahoma Department of Wildlife Conservation",directory_url:"https://www.wildlifedepartment.com/fishing/wheretofish",official_domains:["wildlifedepartment.com"]},
    {
      state:"Oregon",code:"OR",agency:"Oregon Department of Fish and Wildlife",
      directory_url:"https://myodfw.com/fishing",reports_url:"https://myodfw.com/recreation-report/fishing-report",
      rules_url:"https://myodfw.com/fishing/regulations",stocking_url:"https://myodfw.com/fishing/species/trout/stocking-schedule",
      official_domains:["myodfw.com","oregon.gov"],description:"ODFW fishing zones, recreation reports, stocking maps and regulations.",
      coverage_label:"State fishing zones, reports and stocking resources"
    },
    {state:"Pennsylvania",code:"PA",agency:"Pennsylvania Fish and Boat Commission",directory_url:"https://www.pa.gov/agencies/fishandboat/fishing/all-about-fish/fishing-locations",official_domains:["pa.gov","fishandboat.com"]},
    {state:"Rhode Island",code:"RI",agency:"Rhode Island Department of Environmental Management",directory_url:"https://dem.ri.gov/natural-resources-bureau/fish-wildlife/freshwater-fishing",official_domains:["dem.ri.gov"]},
    {state:"South Carolina",code:"SC",agency:"South Carolina Department of Natural Resources",directory_url:"https://www.dnr.sc.gov/lakes/",official_domains:["dnr.sc.gov"]},
    {state:"South Dakota",code:"SD",agency:"South Dakota Game, Fish and Parks",directory_url:"https://gfp.sd.gov/fishing-areas/",official_domains:["gfp.sd.gov"]},
    {state:"Tennessee",code:"TN",agency:"Tennessee Wildlife Resources Agency",directory_url:"https://www.tn.gov/twra/fishing/where-to-fish.html",official_domains:["tn.gov"]},
    {state:"Texas",code:"TX",agency:"Texas Parks and Wildlife Department",directory_url:"https://tpwd.texas.gov/fishboat/fish/recreational/lakes/",official_domains:["tpwd.texas.gov"]},
    {
      state:"Utah",code:"UT",agency:"Utah Division of Wildlife Resources",
      directory_url:"https://dwrapps.utah.gov/fishing/",search_template:"https://dwrapps.utah.gov/fishing/?NA={query}",
      rules_url:"https://wildlife.utah.gov/guidebooks?sec=10",official_domains:["wildlife.utah.gov","dwrapps.utah.gov"],
      description:"Fish Utah map with waters, species, forecasts, stocking and regulations.",coverage_label:"Statewide Fish Utah waterbody map"
    },
    {state:"Vermont",code:"VT",agency:"Vermont Fish and Wildlife Department",directory_url:"https://vtfishandwildlife.com/fish/fishing-opportunities",official_domains:["vtfishandwildlife.com"]},
    {state:"Virginia",code:"VA",agency:"Virginia Department of Wildlife Resources",directory_url:"https://dwr.virginia.gov/fishing/",official_domains:["dwr.virginia.gov"]},
    {
      state:"Washington",code:"WA",agency:"Washington Department of Fish and Wildlife",
      directory_url:"https://wdfw.wa.gov/fishing/locations",access_url:"https://wdfw.wa.gov/places-to-go/water-access-sites",
      rules_url:"https://wdfw.wa.gov/fishing/regulations",official_domains:["wdfw.wa.gov"],
      description:"Lowland lakes, high lakes, marine areas and managed water access sites.",coverage_label:"Fishing locations and water access areas"
    },
    {state:"West Virginia",code:"WV",agency:"West Virginia Division of Natural Resources",directory_url:"https://wvdnr.gov/fishing/",official_domains:["wvdnr.gov"]},
    {state:"Wisconsin",code:"WI",agency:"Wisconsin Department of Natural Resources",directory_url:"https://dnr.wisconsin.gov/topic/Fishing/lakemaps",official_domains:["dnr.wisconsin.gov"]},
    {
      state:"Wyoming",code:"WY",agency:"Wyoming Game and Fish Department",
      directory_url:"https://wgfd.wyo.gov/fishing-boating/places-fish-wyoming",rules_url:"https://wgfd.wyo.gov/regulations",
      official_domains:["wgfd.wyo.gov","wgfapps.wyo.gov"],description:"Interactive Wyoming Fishing Guide with waters, species and public access layers.",
      coverage_label:"State fishing guide and access layers"
    }
  ]
};

(function(api){
  const clean=value=>String(value||"").trim();
  const norm=value=>clean(value).toLowerCase().replace(/[^a-z0-9\s]/g," ").replace(/\s+/g," ").trim();
  const aliases={};

  for(const row of api.states){
    aliases[norm(row.state)]=row.state;
    aliases[norm(row.code)]=row.state;
    row.description=row.description||`${row.agency} fishing locations, water information and agency resources.`;
    row.coverage_label=row.coverage_label||"Official state fishing source";
    row.official_domains=[...new Set((row.official_domains||[]).map(domain=>clean(domain).toLowerCase()).filter(Boolean))];
  }

  api.byState=function(value){
    const canonical=aliases[norm(value)];
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
    if(source.search_template)return source.search_template.replace("{query}",encodeURIComponent(clean(query)));
    return source.directory_url;
  };

  api.googleOfficialSearchUrl=function(source,waterName){
    const terms=(source?.official_domains||[]).map(domain=>`site:${domain}`).join(" OR ");
    const query=[terms&&`(${terms})`,`"${clean(waterName)}"`,"fish species"].filter(Boolean).join(" ");
    return`https://www.google.com/search?q=${encodeURIComponent(query)}`;
  };
})(window.FFO_STATE_SOURCES);
