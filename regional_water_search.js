/* Fish Finder Outdoors — Regional Public-Only Water Search
   Official water names: USGS Geographic Names Information System (GNIS)
   Public-access verification: USGS Protected Areas Database (PAD-US)
   Conservative rule: water results are hidden unless open public access is verified. */
(function(){
  "use strict";

  const GNIS_ROOT =
    "https://cartowfs.nationalmap.gov/arcgis/rest/services/geonames/MapServer";
  const PADUS_QUERY =
    "https://services.arcgis.com/v01gqwM5QqNysAAi/ArcGIS/rest/services/PADUS_Public_Access/FeatureServer/0/query";
  const NOMINATIM_SEARCH =
    "https://nominatim.openstreetmap.org/search";

  const REGION_STATES = [
    {name:"Alabama",code:"AL"},{name:"Alaska",code:"AK"},
    {name:"Arizona",code:"AZ"},{name:"Arkansas",code:"AR"},
    {name:"California",code:"CA"},{name:"Colorado",code:"CO"},
    {name:"Connecticut",code:"CT"},{name:"Delaware",code:"DE"},
    {name:"Florida",code:"FL"},{name:"Georgia",code:"GA"},
    {name:"Hawaii",code:"HI"},{name:"Idaho",code:"ID"},
    {name:"Illinois",code:"IL"},{name:"Indiana",code:"IN"},
    {name:"Iowa",code:"IA"},{name:"Kansas",code:"KS"},
    {name:"Kentucky",code:"KY"},{name:"Louisiana",code:"LA"},
    {name:"Maine",code:"ME"},{name:"Maryland",code:"MD"},
    {name:"Massachusetts",code:"MA"},{name:"Michigan",code:"MI"},
    {name:"Minnesota",code:"MN"},{name:"Mississippi",code:"MS"},
    {name:"Missouri",code:"MO"},{name:"Montana",code:"MT"},
    {name:"Nebraska",code:"NE"},{name:"Nevada",code:"NV"},
    {name:"New Hampshire",code:"NH"},{name:"New Jersey",code:"NJ"},
    {name:"New Mexico",code:"NM"},{name:"New York",code:"NY"},
    {name:"North Carolina",code:"NC"},{name:"North Dakota",code:"ND"},
    {name:"Ohio",code:"OH"},{name:"Oklahoma",code:"OK"},
    {name:"Oregon",code:"OR"},{name:"Pennsylvania",code:"PA"},
    {name:"Rhode Island",code:"RI"},{name:"South Carolina",code:"SC"},
    {name:"South Dakota",code:"SD"},{name:"Tennessee",code:"TN"},
    {name:"Texas",code:"TX"},{name:"Utah",code:"UT"},
    {name:"Vermont",code:"VT"},{name:"Virginia",code:"VA"},
    {name:"Washington",code:"WA"},{name:"West Virginia",code:"WV"},
    {name:"Wisconsin",code:"WI"},{name:"Wyoming",code:"WY"}
  ];

  const STATE_BY_CODE = Object.fromEntries(REGION_STATES.map(s => [s.code, s]));
  const STATE_CODE_PATTERN = REGION_STATES.map(state=>state.code).join("|");
  const CACHE_KEY_PREFIX = "ffo:nearby-reliable:v5:";
  const ACCESS_CACHE_PREFIX = "ffo:padus-access:v3:";
  const SEARCH_CACHE_AGE_MS = 7 * 24 * 60 * 60 * 1000;
  const ACCESS_CACHE_AGE_MS = 30 * 24 * 60 * 60 * 1000;
  const WATER_WORDS = /\b(lake|reservoir|res\.?|pond|river|creek|stream|canal|bay|channel|lagoon|inlet|harbor|harbour)\b/i;
  const WATER_TYPES = new Set([
    "water","lake","reservoir","pond","river","stream","canal",
    "bay","channel","lagoon","inlet","harbor","harbour","sea"
  ]);

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

    const abbreviation = text.match(new RegExp(`(?:,|\\s)\\s*(${STATE_CODE_PATTERN})\\s*$`,"i"));
    return abbreviation ? STATE_BY_CODE[abbreviation[1].toUpperCase()] : null;
  }

  function stripState(query){
    let text = clean(query);
    for(const state of REGION_STATES){
      text = text.replace(new RegExp(`\\b${state.name}\\b`, "ig"), " ");
    }
    text = text.replace(new RegExp(`(?:,|\\s)\\s*(${STATE_CODE_PATTERN})\\s*$`,"i"), " ");
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

  function cacheRead(prefix,key,maxAge){
    try{
      const record = JSON.parse(localStorage.getItem(prefix + key) || "null");
      if(record && Date.now() - record.saved_at < maxAge) return record.value;
    }catch{}
    return null;
  }

  function cacheWrite(prefix,key,value){
    try{
      localStorage.setItem(
        prefix + key,
        JSON.stringify({saved_at:Date.now(), value})
      );
    }catch{}
  }

  async function fetchJson(url, timeoutMs=12000){
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try{
      const response = await fetch(url, {
        headers:{Accept:"application/json"},
        signal:controller.signal,
        mode:"cors"
      });
      if(!response.ok) throw new Error(`Data source returned ${response.status}`);
      const body = await response.json();
      if(body.error) throw new Error(body.error.message || "Data query failed");
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

    const collections=[
      geometry.points,
      ...(Array.isArray(geometry.paths)?geometry.paths:[]),
      ...(Array.isArray(geometry.rings)?geometry.rings:[])
    ].filter(Array.isArray);

    for(const collection of collections){
      if(!collection.length)continue;
      const candidates=Array.isArray(collection[0])&&Array.isArray(collection[0][0])
        ?collection.flat()
        :collection;
      const valid=candidates.filter(row=>
        Array.isArray(row)&&Number.isFinite(Number(row[0]))&&Number.isFinite(Number(row[1]))
      );
      if(valid.length){
        const point=valid[Math.floor(valid.length/2)];
        return{lon:Number(point[0]),lat:Number(point[1])};
      }
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
    return chosen;
  }

  function stateFromAddress(address){
    const stateName = clean(address?.state).toLowerCase();
    const code = clean(address?.["ISO3166-2-lvl4"] || "").split("-").pop().toUpperCase();
    return REGION_STATES.find(state =>
      state.name.toLowerCase() === stateName || state.code === code
    ) || null;
  }

  function featureType(value){
    const type = clean(value || "Water").toLowerCase();
    if(type.includes("reservoir")) return "reservoir";
    if(type.includes("lake")) return "lake";
    if(type.includes("pond")) return "pond";
    if(type.includes("stream")) return "river";
    if(type.includes("river")) return "river";
    if(type.includes("canal")) return "canal";
    if(type.includes("bay")) return "bay";
    if(type.includes("channel")) return "channel";
    if(type.includes("harbor")) return "harbor";
    if(type.includes("sea")) return "sea";
    return type || "water";
  }

  function isWater(row){
    return WATER_TYPES.has(String(row?.type || "").toLowerCase()) ||
      String(row?.category || "").toLowerCase() === "water";
  }

  function overrideKey(row){
    return `${normalize(row?.name)}|${normalize(row?.state)}`;
  }

  function blockedByApprovedCorrection(row){
    const records=window.FFO_WATER_OVERRIDES?.records||[];
    const key=overrideKey(row);
    return records.some(item=>
      (item.visibility==="hidden"||item.access_status==="private"||item.access_status==="closed")&&
      overrideKey(item)===key
    );
  }

  function approvedPublicOverride(row){
    const records=window.FFO_WATER_OVERRIDES?.records||[];
    const rowState=normalize(row?.state);
    const rowNames=new Set([row?.name,...(row?.aliases||[])]
      .map(name=>normalize(expandCommonTerms(name)))
      .filter(Boolean));
    if(!rowState||!rowNames.size)return null;

    const rowCounty=normalize(row?.county).replace(/\bcounty\b/g,"").trim();
    const lat=Number(row?.lat),lon=Number(row?.lon);
    return records
      .filter(item=>
        item.public_access_verified===true&&
        item.access_points_only!==true&&
        item.visibility!=="hidden"&&
        item.access_status!=="private"&&
        item.access_status!=="closed"&&
        normalize(item.state)===rowState&&
        [item.name,...(item.aliases||[])]
          .map(name=>normalize(expandCommonTerms(name)))
          .some(name=>rowNames.has(name))
      )
      .map(item=>{
        const itemCounty=normalize(item.county).replace(/\bcounty\b/g,"").trim();
        const itemLat=Number(item.lat),itemLon=Number(item.lon);
        const hasDistance=[lat,lon,itemLat,itemLon].every(Number.isFinite);
        const distance=hasDistance?distanceMiles(lat,lon,itemLat,itemLon):null;
        const countyMatch=!!(rowCounty&&itemCounty&&rowCounty===itemCounty);
        return{item,distance,plausible:!hasDistance||distance<=50||countyMatch};
      })
      .filter(match=>match.plausible)
      .sort((a,b)=>(a.distance??Number.MAX_SAFE_INTEGER)-(b.distance??Number.MAX_SAFE_INTEGER))[0]?.item||null;
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
      name_source_url:GNIS_ROOT,
      gnis_id:String(attributes.gaz_id || ""),
      gnis_feature_class:featureClass
    };
  }

  async function queryLayerByName(layerId, term, state){
    const where =
      `UPPER(gaz_name) LIKE '%${sqlLiteral(term)}%' AND ${stateWhere(state)} AND isunknowncoords = 0`;

    const params = new URLSearchParams({
      where,
      outFields:"gaz_name,gaz_featureclass,state_alpha,county_name,gaz_id,isunknowncoords",
      returnGeometry:"true",
      outSR:"4326",
      resultRecordCount:"80",
      orderByFields:"gaz_name ASC",
      f:"json"
    });

    const body = await fetchJson(`${GNIS_ROOT}/${layerId}/query?${params}`);
    return (body.features || []).map(feature => mapFeature(feature, state)).filter(Boolean);
  }

  function bbox(lat,lon,radiusMiles=45){
    const latDelta = radiusMiles / 69;
    const lonDelta = radiusMiles / Math.max(10,69 * Math.cos(lat * Math.PI / 180));
    return {
      xmin:lon-lonDelta,
      ymin:lat-latDelta,
      xmax:lon+lonDelta,
      ymax:lat+latDelta
    };
  }

  async function queryNearbyLayer(layerId,place,state,radiusMiles=45){
    const box=bbox(place.lat,place.lon,radiusMiles);
    const where=`${stateWhere(state)} AND isunknowncoords = 0`;
    const params=new URLSearchParams({
      where,
      geometry:`${box.xmin},${box.ymin},${box.xmax},${box.ymax}`,
      geometryType:"esriGeometryEnvelope",
      inSR:"4326",
      spatialRel:"esriSpatialRelIntersects",
      outFields:"gaz_name,gaz_featureclass,state_alpha,county_name,gaz_id,isunknowncoords",
      returnGeometry:"true",
      outSR:"4326",
      resultRecordCount:layerId===4?"180":"120",
      f:"json"
    });

    const body=await fetchJson(`${GNIS_ROOT}/${layerId}/query?${params}`);
    return(body.features||[])
      .map(feature=>mapFeature(feature,state))
      .filter(Boolean)
      .map(row=>({
        ...row,
        town_search:true,
        nearby_town_label:place.label,
        distance_miles:distanceMiles(place.lat,place.lon,row.lat,row.lon)
      }));
  }

  async function queryNearbyHydroFeatures(place,state,radiusMiles=45){
    const settled=await Promise.allSettled([
      queryNearbyLayer(4,place,state,radiusMiles),
      queryNearbyLayer(3,place,state,radiusMiles)
    ]);
    const rows=[];
    for(const result of settled){
      if(result.status==="fulfilled")rows.push(...result.value);
    }
    return dedupe(rows).sort((a,b)=>a.distance_miles-b.distance_miles);
  }

  async function geocodeTown(query,explicit){
    const params = new URLSearchParams({
      q:query,
      format:"jsonv2",
      addressdetails:"1",
      namedetails:"1",
      countrycodes:"us",
      limit:"8"
    });
    const rows = await fetchJson(`${NOMINATIM_SEARCH}?${params}`);

    for(const row of rows || []){
      const lat=Number(row.lat),lon=Number(row.lon);
      if(!Number.isFinite(lat)||!Number.isFinite(lon))continue;
      const state=stateFromAddress(row.address||{});
      if(!state)continue;
      if(explicit&&state.code!==explicit.code)continue;
      const type=String(row.type||"").toLowerCase();
      const category=String(row.category||row.class||"").toLowerCase();
      const townish=["city","town","village","hamlet","municipality","county","administrative"].some(x=>type.includes(x)) ||
        ["place","boundary"].includes(category);
      if(!townish)continue;

      return {
        lat,lon,state,
        label:clean(row.name || row.namedetails?.name || row.display_name?.split(",")[0] || query)
      };
    }
    return null;
  }

  function privateSignal(row){
    const values=[
      row?.access,row?.ownership,row?.operator,row?.owner,
      row?.extratags?.access,row?.extratags?.ownership,
      row?.extratags?.operator,row?.extratags?.owner
    ].map(value=>normalize(value)).filter(Boolean);

    if(values.some(value=>
      /\b(private|no access|members only|residents only|customers only|employee only)\b/.test(value)
    ))return true;

    const name=normalize(row?.name);
    const display=normalize(row?.display_name);
    const combined=`${name} ${display}`;

    return /\b(private|country club|golf course|homeowners|homeowner association|hoa|members club|private club|residential subdivision|wastewater|sewage|tailings|industrial pond)\b/.test(combined);
  }

  function explicitPublicSignal(row){
    const access=normalize(row?.access || row?.extratags?.access);
    const ownership=normalize(row?.ownership || row?.extratags?.ownership);
    const operator=normalize(row?.operator || row?.extratags?.operator);
    const owner=normalize(row?.owner || row?.extratags?.owner);
    const combined=`${ownership} ${operator} ${owner}`;

    if(["yes","public","permissive","designated"].includes(access))return true;
    return /\b(city|county|state|federal|municipal|public|parks?|fish and game|wildlife|forest service|blm|bureau of reclamation)\b/.test(combined);
  }

  function paidAccessCandidate(row){
    const extra=row?.extratags||{};
    const access=normalize(row?.access||extra.access);
    const fee=normalize(row?.fee||extra.fee);
    const operator=clean(row?.operator||extra.operator||row?.owner||extra.owner);
    const website=clean(row?.website||extra.website||extra["contact:website"]||extra.url);
    const combined=normalize(`${row?.name||""} ${row?.display_name||""} ${operator}`);
    const customerAccess=["yes","public","permissive","designated","customers","customer"].includes(access);
    const commercial=/\b(resort|marina|campground|rv park|lodge|outfitter)\b/.test(combined);
    const feeRequired=["yes","required","paid","fee"].includes(fee);
    if(!website||!customerAccess||(!commercial&&!feeRequired))return null;
    return{
      ...row,
      access_status:"fee-candidate",
      public_access_verified:false,
      access_check_required:true,
      public_access_note:`The map record indicates customer or fee-based access${operator?` through ${operator}`:""}. FFO has not confirmed that fishing, parking, shoreline, or launch access is currently offered; check the operator website and posted rules before traveling.`,
      public_access_source:"Map-listed private or fee access — confirm with operator",
      public_access_source_url:website,
      public_access_method:"map-paid-access-candidate"
    };
  }

  const officialAccessLookups=new Map();
  let officialAccessIndexPromise=null;

  function ensureOfficialAccessIndex(){
    if(window.FFO_OFFICIAL_ACCESS_INDEX)return Promise.resolve(window.FFO_OFFICIAL_ACCESS_INDEX);
    if(officialAccessIndexPromise)return officialAccessIndexPromise;
    if(typeof document==="undefined")return Promise.resolve(null);
    officialAccessIndexPromise=new Promise(resolve=>{
      const script=document.createElement("script");
      let finished=false;
      const finish=()=>{
        if(finished)return;
        finished=true;
        clearTimeout(timeout);
        resolve(window.FFO_OFFICIAL_ACCESS_INDEX||null);
      };
      const timeout=setTimeout(finish,8000);
      script.src="official_access_index.js?v=56";
      script.async=true;
      script.onload=finish;
      script.onerror=finish;
      document.head.appendChild(script);
    });
    return officialAccessIndexPromise;
  }

  function officialAccessLookup(stateName){
    if(officialAccessLookups.has(stateName))return officialAccessLookups.get(stateName);
    const entries=window.FFO_OFFICIAL_ACCESS_INDEX?.states?.[stateName]||[];
    const lookup=new Map();
    entries.forEach(entry=>{
      [entry.name,...(entry.aliases||[])].forEach(name=>{
        const key=normalize(expandCommonTerms(name));
        if(!key)return;
        if(!lookup.has(key))lookup.set(key,[]);
        lookup.get(key).push(entry);
      });
    });
    officialAccessLookups.set(stateName,lookup);
    return lookup;
  }

  function materializeOfficialAccess(entry){
    if(!entry)return null;
    const indexedSource=window.FFO_OFFICIAL_ACCESS_INDEX?.sources?.[entry.source]||{};
    const sourceName=entry.source_name||indexedSource.name||"Official public-access inventory";
    const sourceUrl=entry.source_url||indexedSource.url||"";
    const sites=(entry.access_site_names||[]).filter(Boolean);
    let note=entry.note||`${sourceName} ${sites.length
      ?`documents public fishing or boating access at ${sites.join(", ")}.`
      :"includes this water in an official public fishing or access inventory."}`;
    if(entry.evidence)note+=` ${entry.evidence}`;
    note+=" The record confirms the listed water or named access site, not every shoreline or road; verify current signs, closures, hours, fees, and site rules.";
    return{...entry,note,source_name:sourceName,source_url:sourceUrl};
  }

  async function officialAccessRecord(row){
    await ensureOfficialAccessIndex();
    const stateName=clean(row?.state);
    if(!stateName)return null;
    const lookup=officialAccessLookup(stateName);
    if(!lookup.size)return null;

    const keys=[row?.name,...(row?.aliases||[])]
      .map(name=>normalize(expandCommonTerms(name)))
      .filter(Boolean);
    const candidates=[...new Set(keys.flatMap(key=>lookup.get(key)||[]))];
    if(!candidates.length)return null;

    const rowCounty=normalize(row?.county).replace(/\bcounty\b/g,"").trim();
    const lat=Number(row?.lat),lon=Number(row?.lon);
    const kind=String(row?.type||row?.category||"").toLowerCase();
    const maximumDistance=/river|stream|creek|canal/.test(kind)?60:
      /pond|lagoon/.test(kind)?8:35;

    const ranked=candidates.map(entry=>{
      const canonical=normalize(expandCommonTerms(entry.name));
      const exact=keys.includes(canonical);
      const countyMatch=rowCounty&&
        (entry.counties||[]).some(county=>normalize(county).replace(/\bcounty\b/g,"").trim()===rowCounty);
      const entryLat=Number(entry.lat),entryLon=Number(entry.lon);
      const hasDistance=[lat,lon,entryLat,entryLon].every(Number.isFinite);
      const distance=hasDistance?distanceMiles(lat,lon,entryLat,entryLon):null;
      const plausible=!hasDistance||distance<=maximumDistance||countyMatch;
      const score=(exact?500:300)+(countyMatch?180:0)+
        (distance===null?0:Math.max(0,160-distance*4));
      return{entry,plausible,score,distance};
    }).filter(item=>item.plausible).sort((a,b)=>b.score-a.score);

    if(!ranked.length)return null;
    if(ranked.length>1&&ranked[0].score===ranked[1].score&&ranked[0].distance===null)return null;
    return materializeOfficialAccess(ranked[0].entry);
  }

  function padUsUnitName(feature){
    const attributes=feature?.attributes||{};
    return clean(attributes.Unit_Nm||attributes.BndryName);
  }

  function padUsNameMatchesWater(feature,row){
    const unit=normalize(expandCommonTerms(padUsUnitName(feature)));
    if(!unit)return false;
    return[row?.name,...(row?.aliases||[])]
      .map(name=>normalize(expandCommonTerms(name)))
      .filter(name=>name.length>=4&&/[^\d\s]/.test(name))
      .some(name=>unit===name||unit.includes(name)||name.includes(unit));
  }

  function classifyPadUsFeatures(features,row,association){
    const eligible=association==="named-nearby"
      ?(features||[]).filter(feature=>padUsNameMatchesWater(feature,row))
      :(features||[]);
    const open=eligible.find(feature=>feature.attributes?.Pub_Access==="OA");
    const restricted=eligible.find(feature=>feature.attributes?.Pub_Access==="RA");
    const closed=eligible.find(feature=>feature.attributes?.Pub_Access==="XA");
    const feature=open||restricted||closed;
    if(!feature)return{status:"unknown",source:"USGS PAD-US Public Access"};
    return{
      status:open?"open":restricted?"restricted":"closed",
      boundary:padUsUnitName(feature),
      manager:clean(feature.attributes?.MngNm_Desc),
      source:"USGS PAD-US Public Access",
      association
    };
  }

  async function padUsAccess(row){
    const lat=Number(row?.lat),lon=Number(row?.lon);
    if(!Number.isFinite(lat)||!Number.isFinite(lon))return null;

    const key=`${lat.toFixed(5)},${lon.toFixed(5)}`;
    const cached=cacheRead(ACCESS_CACHE_PREFIX,key,ACCESS_CACHE_AGE_MS);
    if(cached!==null)return cached;

    try{
      const baseParams={
        geometry:`${lon},${lat}`,
        geometryType:"esriGeometryPoint",
        inSR:"4326",
        spatialRel:"esriSpatialRelIntersects",
        outFields:"Pub_Access,BndryName,Unit_Nm,MngNm_Desc,ST_Name",
        returnGeometry:"false",
        resultRecordCount:"200",
        f:"json"
      };
      const directBody=await fetchJson(`${PADUS_QUERY}?${new URLSearchParams(baseParams)}`);
      let result=classifyPadUsFeatures(directBody.features||[],row,"intersects-water-point");

      if(result.status==="unknown"){
        const nearbyParams=new URLSearchParams({
          ...baseParams,
          distance:"16000",
          units:"esriSRUnit_Meter"
        });
        const nearbyBody=await fetchJson(`${PADUS_QUERY}?${nearbyParams}`);
        result=classifyPadUsFeatures(nearbyBody.features||[],row,"named-nearby");
      }

      cacheWrite(ACCESS_CACHE_PREFIX,key,result);
      return result;
    }catch{
      return null;
    }
  }

  async function verifyPublicAccess(row){
    if(!row||!isWater(row))return null;

    const approvedOverride=approvedPublicOverride(row);
    if(approvedOverride){
      return{
        ...row,
        ...approvedOverride,
        aliases:[...new Set([...(row.aliases||[]),...(approvedOverride.aliases||[])])],
        public_access_verified:true,
        access_status:approvedOverride.access_status==="restricted"?"restricted":"open",
        access_check_required:false,
        approved_override:true,
        local_directory:true
      };
    }

    if(row.public_access_verified){
      return{
        ...row,
        access_status:row.access_status==="restricted"?"restricted":"open",
        public_access_verified:true,
        public_access_note:row.public_access_note||
          "Public fishing access is documented by the listed state or managing agency.",
        public_access_method:row.public_access_method||"agency-verified"
      };
    }

    const officialRecord=await officialAccessRecord(row);
    if(officialRecord){
      return{
        ...row,
        access_status:officialRecord.access_status==="restricted"?"restricted":"open",
        public_access_verified:true,
        public_access_note:officialRecord.note,
        public_access_source:officialRecord.source_name,
        public_access_source_url:officialRecord.source_url,
        public_access_method:officialRecord.method||"official-state-access-index",
        official_access_sites:officialRecord.access_site_names||[],
        official_url:officialRecord.water_url||row.official_url||officialRecord.source_url
      };
    }

    const paidCandidate=paidAccessCandidate(row);
    if(paidCandidate)return paidCandidate;

    if(privateSignal(row))return null;

    if(explicitPublicSignal(row)){
      const sourceUrl=clean(row.map_source_url||row.website||row.extratags?.website);
      return{
        ...row,
        access_status:"map-candidate",
        public_access_verified:false,
        access_check_required:true,
        public_access_note:"The map record labels this water or its manager as public. FFO has not matched that label to an official shoreline, launch, park, or road-access source; confirm the exact access point and posted rules before traveling.",
        public_access_source:"Map-listed public access — official confirmation still needed",
        public_access_source_url:sourceUrl,
        public_access_method:"explicit-map-access-candidate"
      };
    }

    const access=await padUsAccess(row);

    if(access?.status==="closed")return null;

    if(access?.status==="open"){
      const details=[access.boundary,access.manager].filter(Boolean).join(" · ");
      const namedNearby=access.association==="named-nearby";
      return{
        ...row,
        access_status:namedNearby?"restricted":"open",
        public_access_verified:true,
        public_access_note:namedNearby
          ?`USGS PAD-US identifies ${details||"a same-name public recreation area"} near this mapped water. This supports a public access option, but confirm the exact shoreline, entrance, fees, hours, and current park rules before traveling.`
          :details
            ?`Open public land or recreation access is documented at the mapped point: ${details}. Confirm the specific shoreline, launch, road, and current site rules.`
            :"Open public land or recreation access is documented at the mapped point. Confirm the specific shoreline, launch, road, and current site rules.",
        public_access_source:"USGS PAD-US Public Access",
        public_access_source_url:
          "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-web-services",
        public_access_method:namedNearby?"pad-us-named-nearby":"pad-us-open"
      };
    }

    if(access?.status==="restricted"){
      return{
        ...row,
        access_status:"restricted",
        public_access_verified:true,
        public_access_note:
          "This is public or managed recreation land, but access may require a permit, fee, registration, seasonal opening, or designated access point. Verify before traveling.",
        public_access_source:"USGS PAD-US Public Access",
        public_access_source_url:
          "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-web-services",
        public_access_method:"pad-us-restricted"
      };
    }

    return{
      ...row,
      access_status:"unknown",
      public_access_verified:false,
      access_check_required:true,
      public_access_note:
        "No private or closed-access evidence was found, but public shoreline or launch access was not confirmed by the available national data. Check the state fishing map before traveling.",
      public_access_source:"Access not confirmed",
      public_access_method:"no-private-evidence"
    };
  }

  async function filterPublic(rows,maxResults=18){
    const input=dedupe((rows||[]).filter(isWater).filter(row=>!blockedByApprovedCorrection(row))).slice(0,60);
    const output=[];

    for(let start=0;start<input.length;start+=6){
      const batch=input.slice(start,start+6);
      const settled=await Promise.allSettled(batch.map(verifyPublicAccess));
      for(const result of settled){
        if(result.status==="fulfilled"&&result.value)output.push(result.value);
      }
      if(output.length>=maxResults*2)break;
    }

    return dedupe(output)
      .sort((a,b)=>{
        const rank={open:3,restricted:2,"fee-candidate":2,"map-candidate":1,unknown:1};
        return(rank[b.access_status]||0)-(rank[a.access_status]||0);
      })
      .slice(0,maxResults);
  }

  function score(row,query,state){
    const target=normalize(stripState(expandCommonTerms(query)));
    const name=normalize(row.name);
    let points=0;

    if(name===target)points+=600;
    else if(name.startsWith(target))points+=400;
    else if(name.includes(target))points+=280;
    else{
      const words=target.split(" ").filter(word=>word.length>1);
      points+=words.filter(word=>name.includes(word)).length*45;
    }

    if(state&&row.state===state.name)points+=100;
    if(row.access_status==="open")points+=360;
    else if(row.access_status==="restricted")points+=220;
    else if(row.access_status==="fee-candidate")points+=170;
    else if(row.access_status==="map-candidate")points+=80;
    else if(row.access_status==="unknown")points+=50;
    if(row.public_access_verified)points+=80;
    if(row.gnis_official)points+=120;
    if(row.type==="river"||row.type==="stream")points+=35;
    if(Number.isFinite(row.distance_miles))points+=Math.max(0,150-row.distance_miles*2.5);

    return points;
  }

  function distanceMiles(a,b,c,d){
    const R=3958.7613;
    const rad=value=>value*Math.PI/180;
    const p1=rad(a),p2=rad(c),dp=rad(c-a),dl=rad(d-b);
    const h=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
    return 2*R*Math.asin(Math.sqrt(h));
  }

  function dedupe(rows){
    const seen=new Set(),output=[];
    for(const row of rows||[]){
      const key=[
        normalize(row.name),
        row.state,
        Number(row.lat).toFixed(4),
        Number(row.lon).toFixed(4)
      ].join("|");
      if(seen.has(key))continue;
      seen.add(key);
      output.push(row);
    }
    return output;
  }

  async function exactWaterSearch(query,state){
    const rows=[];
    for(const term of searchTerms(query)){
      const settled=await Promise.allSettled([
        queryLayerByName(4,term,state),
        queryLayerByName(3,term,state)
      ]);
      for(const result of settled){
        if(result.status==="fulfilled")rows.push(...result.value);
      }
      if(rows.some(row=>normalize(row.name)===normalize(expandCommonTerms(stripState(query)))))break;
    }

    const ranked=dedupe(rows)
      .sort((a,b)=>score(b,query,state)-score(a,query,state))
      .slice(0,35);

    return filterPublic(ranked,18);
  }

  async function nearbyTownSearch(query,state){
    let place;
    try{place=await geocodeTown(query,state);}catch{return[];}
    if(!place)return[];

    let candidates;
    try{candidates=await queryNearbyHydroFeatures(place,place.state,50);}catch{return[];}

    const publicRows=await filterPublic(candidates,18);
    return publicRows
      .map(row=>({
        ...row,
        town_search:true,
        nearby_public:true,
        nearby_town_label:place.label
      }))
      .sort((a,b)=>a.distance_miles-b.distance_miles);
  }

  function officialFinder(query){
    const state=explicitState(query);
    const source=state
      ?window.FFO_STATE_SOURCES?.byState?.(state.name)
      :window.FFO_STATE_SOURCES?.detect?.(query,[]);
    if(source)return{
      state:source.state,
      agency:source.agency,
      url:window.FFO_STATE_SOURCES.searchUrl(source,query)
    };
    return null;
  }

  async function search(query){
    const q=clean(query);
    const state=explicitState(q);
    const key=`${normalize(q)}|${state?state.code:"REGION"}`;
    const cached=cacheRead(CACHE_KEY_PREFIX,key,SEARCH_CACHE_AGE_MS);
    if(cached)return cached;

    const exact=await exactWaterSearch(q,state);
    let nearby=[];

    if(!WATER_WORDS.test(q)||exact.length<3){
      nearby=await nearbyTownSearch(q,state);
    }

    const combined=dedupe([...exact,...nearby])
      .sort((a,b)=>score(b,q,state)-score(a,q,state))
      .slice(0,18);

    cacheWrite(CACHE_KEY_PREFIX,key,combined);
    return combined;
  }

  async function nearbyByCoordinates(lat,lon,stateName,label="Your location",radiusMiles=50){
    const latitude=Number(lat),longitude=Number(lon);
    if(!Number.isFinite(latitude)||!Number.isFinite(longitude))return[];

    const state=
      REGION_STATES.find(item=>normalize(item.name)===normalize(stateName))||
      REGION_STATES.find(item=>normalize(item.code)===normalize(stateName))||
      null;

    // A reverse-geocoding service may return no state even when the phone
    // supplied valid coordinates. Do not fail in that case. The geographic
    // envelope already limits the query, and each GNIS feature identifies
    // its own state.
    const place={
      lat:latitude,
      lon:longitude,
      state,
      label:clean(label)||"Your location"
    };

    let candidates=[];
    try{
      candidates=await queryNearbyHydroFeatures(place,state,Math.max(5,Math.min(75,Number(radiusMiles)||50)));
    }catch{
      return[];
    }

    const screened=await filterPublic(candidates,24);
    return screened
      .map(row=>({
        ...row,
        town_search:true,
        nearby_public:true,
        nearby_town_label:place.label,
        distance_miles:Number.isFinite(row.distance_miles)
          ?row.distance_miles
          :distanceMiles(latitude,longitude,row.lat,row.lon)
      }))
      .sort((a,b)=>{
        const accessRank={open:3,restricted:2,"fee-candidate":2,"map-candidate":1,unknown:1};
        const rankDifference=(accessRank[b.access_status]||0)-(accessRank[a.access_status]||0);
        return rankDifference||a.distance_miles-b.distance_miles;
      })
      .slice(0,18);
  }

  window.FFO_REGION_SEARCH={
    search,
    nearbyByCoordinates,
    filterPublic,
    verifyPublicAccess,
    officialFinder,
    states:REGION_STATES.map(state=>state.name),
    public_only:false,
    private_water_filter:true,
    service_name:"Nationwide USGS GNIS names + official state access records + PAD-US screening",
    service_url:"https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-web-services",
    refreshed_label:"All-result access checks + official state records + nationwide public-land screening"
  };
})();
