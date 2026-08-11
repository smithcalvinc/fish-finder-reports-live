/* Fish Finder Outdoors — named fishing-access directory and free live discovery.
   Curated entries are source-backed. Nearby USGS/OpenStreetMap facilities remain
   candidates until an agency or operator confirms fishing, shoreline, or launch access. */
(function(){
  "use strict";

  const USGS_CAMPGROUND_QUERY=
    "https://carto.nationalmap.gov/arcgis/rest/services/structures/MapServer/25/query";
  const USGS_STRUCTURES_SOURCE=
    "https://carto.nationalmap.gov/arcgis/rest/services/structures/MapServer/25";
  const OVERPASS_QUERY="https://overpass-api.de/api/interpreter";
  const AMENITY_RADIUS_MILES=5;
  const CACHE_PREFIX="ffo:location-amenities:v2:";
  const CACHE_AGE_MS=7*24*60*60*1000;
  const VERIFIED_STATUSES=new Set([
    "agency-verified","operator-verified","publisher-documented","official-state-inventory"
  ]);
  const STATUS_PRIORITY={
    "agency-verified":6,
    "operator-verified":5,
    "publisher-documented":4,
    "official-state-inventory":3,
    "official-map-candidate":2,
    "open-map-candidate":1
  };

  function clean(value){
    return String(value||"").replace(/[’‘]/g,"'").replace(/\s+/g," ").trim();
  }

  function normalize(value){
    return clean(value).toLowerCase().replace(/&/g," and ")
      .replace(/[^a-z0-9\s']/g," ").replace(/\s+/g," ").trim();
  }

  function number(value){
    if(value===null||value===undefined||value==="")return null;
    const parsed=Number(value);
    return Number.isFinite(parsed)?parsed:null;
  }

  function safeWebUrl(value){
    const text=clean(value);
    if(!text)return"";
    try{
      const url=new URL(text,window.location?.href||"https://reports.fishfinderoutdoors.com/");
      return /^https?:$/.test(url.protocol)?url.href:"";
    }catch{return"";}
  }

  function miles(lat1,lon1,lat2,lon2){
    const values=[lat1,lon1,lat2,lon2].map(number);
    if(values.some(value=>value===null))return null;
    const [a,b,c,d]=values,R=3958.7613,toRad=value=>value*Math.PI/180;
    const p1=toRad(a),p2=toRad(c),dp=toRad(c-a),dl=toRad(d-b);
    const h=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
    return 2*R*Math.asin(Math.sqrt(h));
  }

  function radiusMiles(location){
    return AMENITY_RADIUS_MILES;
  }

  function directionsUrl(lat,lon){
    const latitude=number(lat),longitude=number(lon);
    return latitude===null||longitude===null?"":
      `https://www.google.com/maps/dir/?api=1&destination=${latitude.toFixed(6)},${longitude.toFixed(6)}`;
  }

  function googleLookup(location,pointName,extra=""){
    const query=[pointName,extra,location?.name,location?.state].map(clean).filter(Boolean).join(" ");
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
  }

  function verificationLabel(status){
    return({
      "agency-verified":"Agency-verified access",
      "operator-verified":"Operator-verified access",
      "publisher-documented":"Published access information",
      "official-state-inventory":"Official state access listing",
      "official-map-candidate":"Official map candidate — access not confirmed",
      "open-map-candidate":"Open-map candidate — access not confirmed"
    })[status]||"Access details require confirmation";
  }

  function accessTypeLabel(type){
    return({
      "public":"Public access",
      "public-fee":"Public access · fees or conditions may apply",
      "private-pay":"Private pay-to-use access",
      "concession":"Public site operated by concession or partner",
      "shoreline":"Shoreline fishing access",
      "boat-ramp":"Boat ramp",
      "day-use":"Day-use area",
      "private-or-restricted":"Private or restricted candidate",
      "customer-access":"Customer access candidate",
      "pay-to-use-candidate":"Possible pay-to-use access",
      "nearby-facility-candidate":"Nearby facility candidate",
      "map-candidate":"Mapped facility candidate"
    })[type]||clean(type)||"Fishing access point";
  }

  function enhancePoint(raw,location){
    const point={...(raw||{})};
    point.name=clean(point.name||point.access_point_name||"Unnamed access point");
    point.access_type=clean(point.access_type||"map-candidate");
    point.verification_status=clean(point.verification_status||"open-map-candidate");
    point.amenities=[...new Set((point.amenities||[]).map(clean).filter(Boolean))];
    point.operator=clean(point.operator);
    point.source_name=clean(point.source_name);
    point.source_url=safeWebUrl(point.source_url);
    point.operator_url=safeWebUrl(point.operator_url);
    point.fee_note=clean(point.fee_note);
    point.note=clean(point.note);
    point.lat=number(point.lat??point.latitude);
    point.lon=number(point.lon??point.longitude);
    point.distance_miles=number(point.distance_miles);
    if(point.distance_miles===null){
      point.distance_miles=miles(location?.lat,location?.lon,point.lat,point.lon);
    }
    point.directions_url=safeWebUrl(point.directions_url)||directionsUrl(point.lat,point.lon);
    point.google_url=safeWebUrl(point.google_url)||googleLookup(location,point.name);
    point.verification_label=verificationLabel(point.verification_status);
    point.access_type_label=accessTypeLabel(point.access_type);
    point.verified=VERIFIED_STATUSES.has(point.verification_status);
    return point;
  }

  function samePoint(a,b){
    if(normalize(a.name)!==normalize(b.name))return false;
    const separation=miles(a.lat,a.lon,b.lat,b.lon);
    return separation===null||separation<=0.2;
  }

  function mergePoints(points,location){
    const output=[];
    for(const raw of points||[]){
      const point=enhancePoint(raw,location);
      if(!point.name)continue;
      const existingIndex=output.findIndex(existing=>samePoint(existing,point));
      if(existingIndex===-1){output.push(point);continue;}
      const existing=output[existingIndex];
      const preferred=(STATUS_PRIORITY[point.verification_status]||0)>
        (STATUS_PRIORITY[existing.verification_status]||0)?point:existing;
      const other=preferred===point?existing:point;
      output[existingIndex]=enhancePoint({
        ...other,...preferred,
        amenities:[...(preferred.amenities||[]),...(other.amenities||[])],
        source_url:preferred.source_url||other.source_url,
        operator_url:preferred.operator_url||other.operator_url,
        note:preferred.note||other.note,
        fee_note:preferred.fee_note||other.fee_note
      },location);
    }
    return output.sort((a,b)=>{
      const verifiedDifference=Number(b.verified)-Number(a.verified);
      if(verifiedDifference)return verifiedDifference;
      const statusDifference=(STATUS_PRIORITY[b.verification_status]||0)-
        (STATUS_PRIORITY[a.verification_status]||0);
      if(statusDifference)return statusDifference;
      const distanceA=a.distance_miles===null?Number.MAX_SAFE_INTEGER:a.distance_miles;
      const distanceB=b.distance_miles===null?Number.MAX_SAFE_INTEGER:b.distance_miles;
      return distanceA-distanceB||a.name.localeCompare(b.name);
    });
  }

  function locationNames(location){
    return new Set([location?.name,...(location?.aliases||[])]
      .map(normalize).filter(Boolean));
  }

  function matchingOverridePoints(location){
    const names=locationNames(location),state=normalize(location?.state);
    if(!names.size||!state)return[];
    const records=window.FFO_WATER_OVERRIDES?.records||[];
    const record=records.find(item=>
      normalize(item.state)===state&&
      [item.name,...(item.aliases||[])].map(normalize).some(name=>names.has(name))
    );
    return record?.access_points||[];
  }

  function officialIndexPoints(location){
    const state=clean(location?.state),entries=window.FFO_OFFICIAL_ACCESS_INDEX?.states?.[state]||[];
    const sources=window.FFO_OFFICIAL_ACCESS_INDEX?.sources||[];
    const selectedNames=locationNames(location),selected=normalize(location?.name);
    const maximumDistance=radiusMiles(location),points=[];
    for(const entry of entries){
      const entryNames=[entry.name,...(entry.aliases||[])].map(normalize).filter(Boolean);
      const exact=entryNames.some(name=>selectedNames.has(name));
      const related=!exact&&entryNames.some(name=>
        selected.length>=5&&(name.startsWith(`${selected} `)||selected.startsWith(`${name} `))
      );
      if(!exact&&!related)continue;
      const distance=miles(location?.lat,location?.lon,entry.lat,entry.lon);
      if(related&&(distance===null||distance>maximumDistance))continue;
      const source=sources[entry.source]||{};
      const base={
        access_type:entry.access_status==="restricted"?"public-fee":"public",
        verification_status:"official-state-inventory",
        source_name:source.name||"Official state access inventory",
        source_url:source.url||"",
        note:clean(entry.evidence)||"This named site appears in an official state fishing or boating access inventory. Confirm current hours, fees, closures, and posted rules."
      };
      const siteNames=(entry.access_site_names||[]).map(clean)
        .filter(name=>name&&normalize(name)!=="unknown");
      if(exact){
        siteNames.forEach(name=>points.push({...base,name}));
      }else{
        points.push({...base,name:entry.name,lat:entry.lat,lon:entry.lon});
      }
    }
    return points;
  }

  function knownForWater(location){
    const provided=[...(location?.access_points||[])];
    const officialSites=(location?.official_access_sites||location?.access_site_names||[])
      .map(name=>({
        name,
        access_type:location?.access_status==="restricted"?"public-fee":"public",
        verification_status:"official-state-inventory",
        source_name:location?.public_access_source||"Official state access inventory",
        source_url:location?.public_access_source_url||location?.official_url||"",
        note:"This named site appears in the official access record matched to this water. Confirm the exact entrance, current conditions, fees, and posted rules."
      }));
    return mergePoints([
      ...provided,
      ...matchingOverridePoints(location),
      ...officialSites,
      ...officialIndexPoints(location)
    ],location);
  }

  function discoveryLinks(location){
    const place=[location?.name,location?.state].map(clean).filter(Boolean).join(", ");
    const link=(label,query)=>({
      label,
      url:`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${query} near ${place}`)}`
    });
    return[
      link("Find boat launches within 5 miles","boat launches boat ramps fishing access within 5 miles"),
      link("Find camping within 5 miles","campgrounds campsites fishing access within 5 miles"),
      link("Find day-use areas within 5 miles","day-use areas picnic sites parks within 5 miles"),
      link("Find public shoreline access","public parks public land fishing access within 5 miles")
    ];
  }

  function cacheRead(key){
    try{
      const record=JSON.parse(localStorage.getItem(CACHE_PREFIX+key)||"null");
      if(record&&Date.now()-record.saved_at<CACHE_AGE_MS)return record.value;
    }catch{}
    return null;
  }

  function cacheWrite(key,value){
    try{localStorage.setItem(CACHE_PREFIX+key,JSON.stringify({saved_at:Date.now(),value}));}catch{}
  }

  async function fetchJson(url,timeoutMs=9000){
    const controller=typeof AbortController!=="undefined"?new AbortController():null;
    const timeout=controller?setTimeout(()=>controller.abort(),timeoutMs):null;
    try{
      const response=await fetch(url,{headers:{Accept:"application/json"},signal:controller?.signal});
      if(!response.ok)throw new Error(`Access source returned ${response.status}`);
      const body=await response.json();
      if(body?.error)throw new Error(body.error.message||"Access source query failed");
      return body;
    }finally{if(timeout)clearTimeout(timeout);}
  }

  function bounds(location,radius){
    const lat=number(location?.lat),lon=number(location?.lon);
    if(lat===null||lon===null)return null;
    const y=radius/69;
    const x=radius/Math.max(10,69*Math.cos(lat*Math.PI/180));
    return{west:lon-x,south:lat-y,east:lon+x,north:lat+y};
  }

  async function queryUsgsCampgrounds(location){
    const radius=radiusMiles(location),box=bounds(location,radius);
    if(!box)return[];
    const parameters=new URLSearchParams({
      where:"FCODE = 82008",
      geometry:`${box.west},${box.south},${box.east},${box.north}`,
      geometryType:"esriGeometryEnvelope",
      inSR:"4326",
      spatialRel:"esriSpatialRelIntersects",
      outFields:"NAME,FCODE,ADMINTYPE,SOURCE_ORIGINATOR,ADDRESS,CITY,STATE",
      returnGeometry:"true",
      outSR:"4326",
      resultRecordCount:"60",
      f:"json"
    });
    const body=await fetchJson(`${USGS_CAMPGROUND_QUERY}?${parameters}`);
    const ownership={1:"Federal",2:"Tribal",3:"State",4:"Regional",5:"County",6:"Municipal",7:"Private"};
    return(body.features||[]).map(feature=>{
      const attributes=feature.attributes||{};
      const name=clean(attributes.NAME||attributes.name);
      const lat=number(feature.geometry?.y),lon=number(feature.geometry?.x);
      const distance=miles(location?.lat,location?.lon,lat,lon);
      const ownerCode=number(attributes.ADMINTYPE??attributes.admintype);
      const owner=ownership[ownerCode]||"Ownership not specified";
      if(!name||distance===null||distance>radius)return null;
      return{
        name,
        lat,lon,distance_miles:distance,
        access_type:ownerCode===7?"private-or-restricted":"nearby-facility-candidate",
        verification_status:"official-map-candidate",
        amenities:["Camping"],
        operator:clean(attributes.SOURCE_ORIGINATOR||attributes.source_originator),
        source_name:"USGS National Structures Dataset",
        source_url:USGS_STRUCTURES_SOURCE,
        fee_note:ownerCode===7?"USGS identifies private ownership; fees or permission may apply.":"Fees and access conditions were not supplied by this map record.",
        note:`USGS maps this ${owner.toLowerCase()} campground about ${distance.toFixed(1)} miles from the selected water. This confirms the facility location, not fishing, shoreline, road, or launch access.`,
        last_checked:new Date().toISOString()
      };
    }).filter(Boolean);
  }

  function osmKind(tags){
    if(tags.leisure==="slipway")return{name:"Mapped boat ramp",type:"boat-ramp",amenities:["Boat ramp"]};
    if(tags.leisure==="marina")return{name:"Mapped marina",type:"map-candidate",amenities:["Marina or moorage"]};
    if(tags.tourism==="camp_site"||tags.tourism==="caravan_site")return{name:"Mapped campground",type:"map-candidate",amenities:["Camping"]};
    if(tags.tourism==="picnic_site"||tags.leisure==="park"||tags.leisure==="recreation_ground")return{name:"Mapped day-use area",type:"day-use",amenities:["Day use"]};
    if(tags.man_made==="pier"||tags.man_made==="jetty")return{name:"Mapped pier",type:"map-candidate",amenities:["Dock or pier"]};
    return{name:"Mapped fishing area",type:"map-candidate",amenities:["Fishing area"]};
  }

  function osmAccessType(tags,kind){
    const access=normalize(tags.access);
    if(access==="private"||access==="no")return"private-or-restricted";
    if(access==="customers"||access==="destination")return"customer-access";
    if(normalize(tags.fee)==="yes"||clean(tags.charge))return"pay-to-use-candidate";
    return kind.type;
  }

  async function queryOpenMap(location){
    const lat=number(location?.lat),lon=number(location?.lon),radius=radiusMiles(location);
    if(lat===null||lon===null)return[];
    const meters=Math.round(radius*1609.344);
    const query=`[out:json][timeout:7];(
      nwr(around:${meters},${lat},${lon})["leisure"~"^(slipway|marina|fishing|park|recreation_ground)$"];
      nwr(around:${meters},${lat},${lon})["tourism"~"^(camp_site|caravan_site|picnic_site)$"];
      nwr(around:${meters},${lat},${lon})["sport"="fishing"];
      nwr(around:${meters},${lat},${lon})["man_made"~"^(pier|jetty)$"]["name"];
    );out center 80;`;
    const body=await fetchJson(`${OVERPASS_QUERY}?data=${encodeURIComponent(query)}`,9000);
    return(body.elements||[]).map(element=>{
      const tags=element.tags||{},kind=osmKind(tags);
      const pointLat=number(element.lat??element.center?.lat);
      const pointLon=number(element.lon??element.center?.lon);
      const distance=miles(lat,lon,pointLat,pointLon);
      if(pointLat===null||pointLon===null||distance===null||distance>radius)return null;
      const amenities=[...kind.amenities];
      if(tags.toilets==="yes")amenities.push("Restrooms");
      if(tags.drinking_water==="yes")amenities.push("Drinking water");
      if(tags.parking==="yes")amenities.push("Parking");
      if(tags.shower==="yes")amenities.push("Showers");
      const accessType=osmAccessType(tags,kind);
      const mapUrl=`https://www.openstreetmap.org/${encodeURIComponent(element.type)}/${encodeURIComponent(element.id)}`;
      return{
        name:clean(tags.name)||kind.name,
        lat:pointLat,lon:pointLon,distance_miles:distance,
        access_type:accessType,
        verification_status:"open-map-candidate",
        amenities,
        operator:clean(tags.operator||tags.brand),
        operator_url:safeWebUrl(tags.website||tags["contact:website"]||tags.url),
        source_name:"OpenStreetMap contributor map",
        source_url:mapUrl,
        fee_note:accessType==="pay-to-use-candidate"?"The map indicates a fee or charge; confirm the current amount with the operator.":accessType==="private-or-restricted"?"The map indicates private or restricted access; permission may be required.":"Fees and access conditions were not confirmed.",
        note:`This facility is mapped about ${distance.toFixed(1)} miles from the selected water. FFO has not confirmed that it provides legal fishing, shoreline, launch, parking, or road access.`,
        last_checked:new Date().toISOString()
      };
    }).filter(Boolean);
  }

  async function enrich(location,{live=true}={}){
    const known=knownForWater(location),links=discoveryLinks(location);
    if(!live)return{...location,access_points:known,access_discovery_links:links,access_search:{live:false}};
    const lat=number(location?.lat),lon=number(location?.lon);
    if(lat===null||lon===null)return{...location,access_points:known,access_discovery_links:links,access_search:{live:false,reason:"coordinates-unavailable"}};
    const key=`${lat.toFixed(3)},${lon.toFixed(3)}|${radiusMiles(location)}`;
    const cached=cacheRead(key);
    if(cached){
      return{
        ...location,
        access_points:mergePoints([...known,...(cached.points||[])],location),
        access_discovery_links:links,
        access_search:{...(cached.search||{}),cached:true}
      };
    }
    const settled=await Promise.allSettled([
      queryUsgsCampgrounds(location),
      queryOpenMap(location)
    ]);
    const livePoints=settled.flatMap(result=>result.status==="fulfilled"?result.value:[]);
    const search={
      live:true,
      checked_at:new Date().toISOString(),
      radius_miles:radiusMiles(location),
      usgs_structures: settled[0].status==="fulfilled"?"checked":"unavailable",
      open_map: settled[1].status==="fulfilled"?"checked":"unavailable"
    };
    if(settled.every(result=>result.status==="fulfilled"))cacheWrite(key,{points:livePoints,search});
    return{
      ...location,
      access_points:mergePoints([...known,...livePoints],location),
      access_discovery_links:links,
      access_search:search
    };
  }

  window.FFO_ACCESS_POINTS={
    version:"2026-08-10-five-mile-location-amenities-v2",
    amenityRadiusMiles:AMENITY_RADIUS_MILES,
    knownForWater,
    enrich,
    discoveryLinks,
    verificationLabel,
    accessTypeLabel,
    mergePoints,
    sources:{
      usgs_structures:USGS_STRUCTURES_SOURCE,
      open_map:"https://www.openstreetmap.org/",
      google_maps:"https://www.google.com/maps"
    }
  };
})();
