/* Fish Finder Outdoors — Phase 6.2 regional water-name search
   Uses the official USGS Geographic Names Information System (GNIS)
   Hydro Points and Hydro Lines services, then returns standardized water names
   and coordinates for the Northwest and Mountain West coverage region. */
(function(){
  "use strict";

  const SERVICE_ROOT =
    "https://cartowfs.nationalmap.gov/arcgis/rest/services/geonames/MapServer";

  const REGION_STATES = [
    {name:"Idaho", code:"ID"},
    {name:"Montana", code:"MT"},
    {name:"Wyoming", code:"WY"},
    {name:"Utah", code:"UT"},
    {name:"Nevada", code:"NV"},
    {name:"Oregon", code:"OR"},
    {name:"Washington", code:"WA"},
    {name:"California", code:"CA", northOnly:true},
    {name:"Colorado", code:"CO"}
  ];

  const STATE_BY_CODE = Object.fromEntries(REGION_STATES.map(s => [s.code, s]));
  const STATE_BY_NAME = Object.fromEntries(REGION_STATES.map(s => [s.name.toLowerCase(), s]));
  const CACHE_KEY_PREFIX = "ffo:gnis62:";
  const CACHE_AGE_MS = 7 * 24 * 60 * 60 * 1000;

  function clean(value){
    return String(value || "")
      .replace(/[’‘]/g, "'")
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalize(value){
    return clean(value)
      .toLowerCase()
      .replace(/&/g, " and ")
      .replace(/[^a-z0-9\s']/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function expandCommonTerms(value){
    return clean(value)
      .replace(/\bres(?:erv)?\.?\b/gi, "Reservoir")
      .replace(/\brsvr\.?\b/gi, "Reservoir")
      .replace(/\bresevoir\b/gi, "Reservoir")
      .replace(/\bresivoir\b/gi, "Reservoir")
      .replace(/\blk\.?\b/gi, "Lake")
      .replace(/\brvr\.?\b/gi, "River")
      .replace(/\bcr\.?\b/gi, "Creek")
      .replace(/\bstrm\.?\b/gi, "Stream")
      .replace(/\bpd\.?\b/gi, "Pond")
      .replace(/\bedson\s+fitcher\b/gi, "Edson Fichter")
      .replace(/\s+/g, " ")
      .trim();
  }

  function explicitState(query){
    const text = clean(query);
    const lower = text.toLowerCase();

    for(const state of REGION_STATES){
      if(new RegExp(`\\b${state.name.toLowerCase()}\\b`, "i").test(lower)){
        return state;
      }
    }

    const abbreviation = text.match(/(?:,|\s)\s*(ID|MT|WY|UT|NV|OR|WA|CA|CO)\s*$/i);
    return abbreviation ? STATE_BY_CODE[abbreviation[1].toUpperCase()] : null;
  }

  function stripState(query){
    let text = clean(query);
    for(const state of REGION_STATES){
      text = text.replace(new RegExp(`\\b${state.name}\\b`, "ig"), " ");
    }
    text = text.replace(/(?:,|\s)\s*(ID|MT|WY|UT|NV|OR|WA|CA|CO)\s*$/i, " ");
    return clean(text.replace(/\s*,\s*$/, ""));
  }

  function searchTerms(query){
    const stripped = stripState(query);
    const expanded = expandCommonTerms(stripped);
    const terms = [expanded, stripped];

    const withoutGeneric = expanded
      .replace(/\b(reservoir|lake|pond|river|creek|stream|canal|bay|channel|lagoon|inlet|harbor|harbour)\b/gi, " ")
      .replace(/\s+/g, " ")
      .trim();

    if(withoutGeneric.length >= 3) terms.push(withoutGeneric);

    return [...new Set(
      terms.map(clean).filter(term => term.length >= 2)
    )].slice(0, 2);
  }

  function sqlLiteral(value){
    return String(value || "").replace(/'/g, "''").toUpperCase();
  }

  function stateWhere(state){
    if(state) return `state_alpha LIKE '%${state.code}%'`;
    return "(" + REGION_STATES
      .map(item => `state_alpha LIKE '%${item.code}%'`)
      .join(" OR ") + ")";
  }

  function cacheRead(key){
    try{
      const record = JSON.parse(localStorage.getItem(CACHE_KEY_PREFIX + key) || "null");
      if(record && Date.now() - record.saved_at < CACHE_AGE_MS) return record.rows;
    }catch{}
    return null;
  }

  function cacheWrite(key, rows){
    try{
      localStorage.setItem(
        CACHE_KEY_PREFIX + key,
        JSON.stringify({saved_at:Date.now(), rows})
      );
    }catch{}
  }

  async function fetchJson(url, timeoutMs=10000){
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try{
      const response = await fetch(url, {
        headers:{Accept:"application/json"},
        signal:controller.signal,
        mode:"cors"
      });
      if(!response.ok) throw new Error(`GNIS returned ${response.status}`);
      const body = await response.json();
      if(body.error) throw new Error(body.error.message || "GNIS query failed");
      return body;
    }finally{
      clearTimeout(timeout);
    }
  }

  function geometryPoint(geometry){
    if(!geometry) return null;
    if(Number.isFinite(geometry.x) && Number.isFinite(geometry.y)){
      return {lon:Number(geometry.x), lat:Number(geometry.y)};
    }
    if(Array.isArray(geometry.points) && geometry.points.length){
      const point = geometry.points.find(row =>
        Array.isArray(row) && Number.isFinite(Number(row[0])) && Number.isFinite(Number(row[1]))
      );
      if(point) return {lon:Number(point[0]), lat:Number(point[1])};
    }
    return null;
  }

  function stateCodes(value){
    const upper = String(value || "").toUpperCase();
    return REGION_STATES.map(state => state.code).filter(code =>
      new RegExp(`(^|[^A-Z])${code}([^A-Z]|$)`).test(upper)
    );
  }

  function stateForFeature(attributes, explicit, lat){
    const codes = stateCodes(attributes.state_alpha);
    let chosen = explicit && codes.includes(explicit.code) ? explicit : STATE_BY_CODE[codes[0]];
    if(!chosen) return null;

    // The previously agreed California coverage is Northern California.
    if(chosen.code === "CA" && Number(lat) < 35.0) return null;
    return chosen;
  }

  function featureType(value){
    const type = clean(value || "Water").toLowerCase();
    if(type.includes("reservoir")) return "reservoir";
    if(type.includes("lake")) return "lake";
    if(type.includes("stream")) return "river";
    if(type.includes("canal")) return "canal";
    if(type.includes("bay")) return "bay";
    if(type.includes("channel")) return "channel";
    if(type.includes("harbor")) return "harbor";
    if(type.includes("sea")) return "sea";
    return type || "water";
  }

  function mapFeature(feature, explicit){
    const attributes = feature.attributes || {};
    const point = geometryPoint(feature.geometry);
    if(!point) return null;

    const state = stateForFeature(attributes, explicit, point.lat);
    if(!state) return null;

    const name = clean(attributes.gaz_name);
    if(!name) return null;

    const county = clean(attributes.county_name);
    const featureClass = clean(attributes.gaz_featureclass || "Water");
    const countyText = county
      ? `${county}${/county$/i.test(county) ? "" : " County"}, `
      : "";

    return {
      name,
      display_name:`${name}, ${countyText}${state.name}`,
      lat:point.lat,
      lon:point.lon,
      state:state.name,
      county,
      category:"water",
      type:featureType(featureClass),
      gnis_official:true,
      name_source:"USGS Geographic Names Information System",
      name_source_url:SERVICE_ROOT,
      gnis_id:String(attributes.gaz_id || ""),
      gnis_feature_class:featureClass
    };
  }

  async function queryLayer(layerId, term, state){
    const where =
      `UPPER(gaz_name) LIKE '%${sqlLiteral(term)}%' AND ${stateWhere(state)} AND isunknowncoords = 0`;

    const params = new URLSearchParams({
      where,
      outFields:"gaz_name,gaz_featureclass,state_alpha,county_name,gaz_id,isunknowncoords",
      returnGeometry:"true",
      outSR:"4326",
      resultRecordCount:"60",
      orderByFields:"gaz_name ASC",
      f:"json"
    });

    const body = await fetchJson(`${SERVICE_ROOT}/${layerId}/query?${params}`);
    return (body.features || []).map(feature => mapFeature(feature, state)).filter(Boolean);
  }

  function score(row, query, state){
    const target = normalize(stripState(expandCommonTerms(query)));
    const name = normalize(row.name);
    let points = 0;

    if(name === target) points += 500;
    else if(name.startsWith(target)) points += 350;
    else if(name.includes(target)) points += 250;
    else{
      const words = target.split(" ").filter(word => word.length > 1);
      const matched = words.filter(word => name.includes(word)).length;
      points += matched * 45;
    }

    if(state && row.state === state.name) points += 100;
    if(row.gnis_official) points += 120;

    const generic = /\b(lake|reservoir|pond|river|creek|stream|canal|bay|channel)\b/i;
    if(generic.test(row.name)) points += 30;

    return points;
  }

  function dedupe(rows){
    const seen = new Set();
    const output = [];
    for(const row of rows){
      const key = [
        normalize(row.name),
        row.state,
        Number(row.lat).toFixed(4),
        Number(row.lon).toFixed(4)
      ].join("|");
      if(seen.has(key)) continue;
      seen.add(key);
      output.push(row);
    }
    return output;
  }

  async function search(query){
    const q = clean(query);
    const state = explicitState(q);
    const key = `${normalize(q)}|${state ? state.code : "REGION"}`;
    const cached = cacheRead(key);
    if(cached) return cached;

    const terms = searchTerms(q);
    const rows = [];

    for(const term of terms){
      const settled = await Promise.allSettled([
        queryLayer(4, term, state), // Hydro Points: lakes, reservoirs, ponds, bays, etc.
        queryLayer(3, term, state)  // Hydro Lines: rivers, streams, canals, channels, etc.
      ]);

      for(const result of settled){
        if(result.status === "fulfilled") rows.push(...result.value);
      }

      if(rows.some(row => normalize(row.name) === normalize(expandCommonTerms(stripState(q))))) break;
    }

    const sorted = dedupe(rows)
      .sort((a,b) => score(b,q,state) - score(a,q,state))
      .slice(0,18);

    cacheWrite(key, sorted);
    return sorted;
  }

  window.FFO_REGION_SEARCH = {
    search,
    states:REGION_STATES.map(state => state.name),
    service_name:"USGS Geographic Names Information System",
    service_url:SERVICE_ROOT,
    refreshed_label:"Official federal water-name service"
  };
})();
