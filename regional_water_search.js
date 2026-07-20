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

  const OFFICIAL_FINDERS = {
    Idaho:"https://idfg.idaho.gov/ifwis/fishingplanner/",
    Montana:"https://fwp.mt.gov/fish",
    Wyoming:"https://wgfd.wyo.gov/fishing-boating",
    Utah:"https://dwrapps.utah.gov/fishing/",
    Nevada:"https://www.ndow.org/get-outside/fishing-stocking-reports/database/",
    Oregon:"https://myodfw.com/recreation-report/fishing-report",
    Washington:"https://wdfw.wa.gov/fishing/locations",
    California:"https://wildlife.ca.gov/Fishing/Guide",
    Colorado:"https://cpw.state.co.us/maps-and-gis"
  };

  const STATE_BY_CODE = Object.fromEntries(REGION_STATES.map(s => [s.code, s]));
  const CACHE_KEY_PREFIX = "ffo:access-balanced:v2:";
  const ACCESS_CACHE_PREFIX = "ffo:padus-access:v2:";
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
    if(chosen.code === "CA" && Number(lat) < 35.0) return null;
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
      if(state.code==="CA"&&lat<35)continue;

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

  async function padUsAccess(row){
    const lat=Number(row?.lat),lon=Number(row?.lon);
    if(!Number.isFinite(lat)||!Number.isFinite(lon))return null;

    const key=`${lat.toFixed(5)},${lon.toFixed(5)}`;
    const cached=cacheRead(ACCESS_CACHE_PREFIX,key,ACCESS_CACHE_AGE_MS);
    if(cached!==null)return cached;

    const params=new URLSearchParams({
      geometry:`${lon},${lat}`,
      geometryType:"esriGeometryPoint",
      inSR:"4326",
      spatialRel:"esriSpatialRelIntersects",
      outFields:"Pub_Access,BndryName,Unit_Nm,MngNm_Desc,ST_Name",
      returnGeometry:"false",
      f:"json"
    });

    try{
      const body=await fetchJson(`${PADUS_QUERY}?${params}`);
      const features=body.features||[];
      const open=features.find(feature=>feature.attributes?.Pub_Access==="OA");
      const closed=features.find(feature=>feature.attributes?.Pub_Access==="XA");
      const restricted=features.find(feature=>feature.attributes?.Pub_Access==="RA");

      const result=open?{
        status:"open",
        boundary:clean(open.attributes?.BndryName || open.attributes?.Unit_Nm),
        manager:clean(open.attributes?.MngNm_Desc),
        source:"USGS PAD-US Public Access"
      }:closed?{
        status:"closed",
        boundary:clean(closed.attributes?.BndryName || closed.attributes?.Unit_Nm),
        source:"USGS PAD-US Public Access"
      }:restricted?{
        status:"restricted",
        boundary:clean(restricted.attributes?.BndryName || restricted.attributes?.Unit_Nm),
        source:"USGS PAD-US Public Access"
      }:{
        status:"unknown",
        source:"USGS PAD-US Public Access"
      };

      cacheWrite(ACCESS_CACHE_PREFIX,key,result);
      return result;
    }catch{
      return null;
    }
  }

  async function verifyPublicAccess(row){
    if(!row||!isWater(row))return null;

    if(row.public_access_verified){
      return{
        ...row,
        access_status:"open",
        public_access_verified:true,
        public_access_note:row.public_access_note||
          "Public fishing access is documented by the listed state or managing agency.",
        public_access_method:row.public_access_method||"agency-verified"
      };
    }

    if(privateSignal(row))return null;

    if(explicitPublicSignal(row)){
      return{
        ...row,
        access_status:"open",
        public_access_verified:true,
        public_access_note:"Public access is explicitly identified in the map record.",
        public_access_source:"Public map access record",
        public_access_method:"explicit-map-access"
      };
    }

    const access=await padUsAccess(row);

    if(access?.status==="closed")return null;

    if(access?.status==="open"){
      const details=[access.boundary,access.manager].filter(Boolean).join(" · ");
      return{
        ...row,
        access_status:"open",
        public_access_verified:true,
        public_access_note:details
          ?`Open public land or recreation access is documented here: ${details}.`
          :"Open public land or recreation access is documented here.",
        public_access_source:"USGS PAD-US Public Access",
        public_access_source_url:
          "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-web-services",
        public_access_method:"pad-us-open"
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
        const rank={open:3,restricted:2,unknown:1};
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
    return state?{state:state.name,url:OFFICIAL_FINDERS[state.name]}:null;
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

    if(!state)return[];

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
        const accessRank={open:3,restricted:2,unknown:1};
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
    service_name:"USGS GNIS names + PAD-US access screening",
    service_url:"https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-web-services",
    refreshed_label:"Location-aware nearby waters + official state sources"
  };
})();
