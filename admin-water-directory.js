/* Fish Finder Outdoors managed-water admin dashboard */
(function(){
"use strict";

const $=id=>document.getElementById(id);
const clone=value=>JSON.parse(JSON.stringify(value));
const managedData=window.FFO_MANAGED_WATER_DIRECTORY||{records:[]};
const initialOverrides=window.FFO_WATER_OVERRIDES||{records:[]};
const stateApi=window.FFO_ADMIN_WATER_STATE||null;

let workingManaged=clone(managedData.records||[]);
let fallbackOverrides=clone(initialOverrides.records||[]);
let editorMode="new";
let editorKey="";
let editorSource="managed";
let liveLookupRows=[];

function clean(value){return String(value??"").replace(/[\r\n]+/g," ").replace(/\s+/g," ").trim();}
function normalize(value){return clean(value).toLowerCase().replace(/[^a-z0-9\s]/g," ").replace(/\s+/g," ").trim();}
function key(row){return`${normalize(row?.name)}|${normalize(row?.state)}`;}
function esc(value){return String(value??"").replace(/[&<>'"]/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));}
function numberOrNull(value){const number=Number(value);return Number.isFinite(number)?number:null;}
function currentOverrides(){return stateApi?stateApi.getOverrides():clone(fallbackOverrides);}
function setOverrides(rows){fallbackOverrides=clone(rows||[]);if(stateApi)stateApi.setOverrides(rows);}
function publicOverride(row){return row.visibility!=="hidden"&&!["private","closed"].includes(row.access_status);}
function hiddenOverride(row){return row.visibility==="hidden"||["private","closed"].includes(row.access_status);}

function mergedDirectory(){
  const baseMap=new Map();
  workingManaged.forEach(row=>baseMap.set(key(row),{...clone(row),_record_source:"managed"}));

  const overrides=currentOverrides();
  overrides.filter(publicOverride).forEach(row=>{
    const recordKey=key(row);
    const existing=baseMap.get(recordKey);
    baseMap.set(recordKey,{
      ...(existing||{}),
      ...clone(row),
      _record_source:existing?"approved-edit":"approved",
      _override_record:true
    });
  });

  overrides.filter(hiddenOverride).forEach(row=>{
    const recordKey=key(row);
    const existing=baseMap.get(recordKey);
    baseMap.set(recordKey,{
      ...(existing||{}),
      ...clone(row),
      visibility:"hidden",
      _record_source:"hidden",
      _hidden_record:true
    });
  });

  return Array.from(baseMap.values()).sort((a,b)=>
    String(a.state||"").localeCompare(String(b.state||""))||
    String(a.name||"").localeCompare(String(b.name||""))
  );
}

function sourceLabel(row){
  if(row._record_source==="hidden")return["Hidden/private block","source-hidden"];
  if(row._record_source==="approved"||row._record_source==="approved-edit")return["Approved addition/edit","source-approved"];
  return["Managed directory","source-managed"];
}

function accessLabel(row){
  const status=row.visibility==="hidden"?(row.access_status||"private"):(row.access_status||"unknown");
  const labels={
    open:"Public/open",
    restricted:"Public with conditions",
    unknown:"Needs verification",
    private:"Private",
    closed:"Closed"
  };
  return[labels[status]||status,`access-${status}`];
}

function downloadText(filename,text,mime="application/javascript"){
  const blob=new Blob([text],{type:mime});
  const anchor=document.createElement("a");
  anchor.href=URL.createObjectURL(blob);
  anchor.download=filename;
  anchor.click();
  setTimeout(()=>URL.revokeObjectURL(anchor.href),1000);
}

function managedFileText(){
  const date=new Date().toISOString().slice(0,10);
  const file={
    version:`${date}-managed-directory`,
    updated_at:date,
    coverage_note:"Waters directly managed by Fish Finder Outdoors. Live external results are not automatically added.",
    records:workingManaged
  };
  return "/* Fish Finder Outdoors managed water directory. */\nwindow.FFO_MANAGED_WATER_DIRECTORY = "+JSON.stringify(file,null,2)+";\n";
}

function overrideFileText(){
  const date=new Date().toISOString().slice(0,10);
  const file={
    version:`${date}-approved-corrections`,
    updated_at:date,
    coverage_note:"Manually reviewed missing-water additions, edits, and private/closed-water corrections.",
    records:currentOverrides()
  };
  return "/* Approved Fish Finder Outdoors water-directory corrections. */\nwindow.FFO_WATER_OVERRIDES = "+JSON.stringify(file,null,2)+";\n";
}

function downloadManaged(){
  downloadText("managed_water_directory.js",managedFileText());
}

function downloadOverrides(){
  downloadText("official_water_overrides.js",overrideFileText());
}

function stateOptions(rows){
  const selected=$("waterDirectoryState").value||"all";
  const states=[...new Set(rows.map(row=>row.state).filter(Boolean))].sort();
  $("waterDirectoryState").innerHTML=
    '<option value="all">All states</option>'+
    states.map(state=>`<option value="${esc(state)}">${esc(state)}</option>`).join("");
  $("waterDirectoryState").value=states.includes(selected)?selected:"all";
}

function renderSummary(rows){
  const baseKeys=new Set(workingManaged.map(key));
  const overrides=currentOverrides();
  const additions=overrides.filter(row=>publicOverride(row)&&!baseKeys.has(key(row))).length;
  const hidden=overrides.filter(hiddenOverride).length;
  const searchable=rows.filter(row=>row.visibility!=="hidden"&&!["private","closed"].includes(row.access_status)).length;
  const states=new Set(rows.filter(row=>row.visibility!=="hidden").map(row=>row.state).filter(Boolean)).size;

  $("waterDirectorySummary").innerHTML=[
    ["Managed records",workingManaged.length],
    ["Approved additions",additions],
    ["Hidden / blocked",hidden],
    ["Searchable records",searchable],
    ["States represented",states]
  ].map(item=>`<div class="water-metric"><span class="meta">${item[0]}</span><b>${item[1]}</b></div>`).join("");
}

function filteredRows(rows){
  const query=normalize($("waterDirectorySearch").value);
  const state=$("waterDirectoryState").value;
  const access=$("waterDirectoryAccess").value;
  const source=$("waterDirectorySource").value;

  return rows.filter(row=>{
    if(query&&!normalize(JSON.stringify(row)).includes(query))return false;
    if(state!=="all"&&row.state!==state)return false;
    const rowAccess=row.visibility==="hidden"?(row.access_status||"private"):(row.access_status||"unknown");
    if(access!=="all"&&rowAccess!==access)return false;
    if(source==="managed"&&row._record_source!=="managed")return false;
    if(source==="approved"&&!["approved","approved-edit"].includes(row._record_source))return false;
    if(source==="hidden"&&row._record_source!=="hidden")return false;
    return true;
  });
}

function renderDirectory(){
  const allRows=mergedDirectory();
  stateOptions(allRows);
  renderSummary(allRows);
  const rows=filteredRows(allRows);

  $("waterDirectoryStatus").textContent=
    `Showing ${rows.length} of ${allRows.length} FFO-controlled directory records. `+
    `Live outside results are inspected separately below.`;

  $("waterDirectoryRows").innerHTML=rows.length?rows.map(row=>{
    const [sourceText,sourceClass]=sourceLabel(row);
    const [accessText,accessClass]=accessLabel(row);
    const coordinates=Number.isFinite(Number(row.lat))&&Number.isFinite(Number(row.lon))
      ?`${Number(row.lat).toFixed(5)}, ${Number(row.lon).toFixed(5)}`
      :"Not set";
    const town=row.nearby_town_label||((row.nearby_towns||[])[0])||"—";
    const official=row.official_url
      ?`<a href="${esc(row.official_url)}" target="_blank" rel="noopener">Open source ↗</a>`
      :'<span class="meta">Not entered</span>';
    const recordKey=key(row);

    let actions=`<button class="secondary" data-water-action="edit" data-water-key="${esc(recordKey)}">Edit</button>`;
    if(row._record_source==="hidden"){
      actions+=`<button class="secondary" data-water-action="restore" data-water-key="${esc(recordKey)}">Restore</button>`;
    }else{
      actions+=`<button class="danger-button" data-water-action="private" data-water-key="${esc(recordKey)}">Mark private</button>`;
      actions+=`<button class="danger-button" data-water-action="closed" data-water-key="${esc(recordKey)}">Mark closed</button>`;
    }
    if(row._record_source==="approved"){
      actions+=`<button class="danger-button" data-water-action="delete-approved" data-water-key="${esc(recordKey)}">Delete addition</button>`;
    }

    return`<tr>
      <td><b>${esc(row.name||"Unnamed water")}</b><div class="meta">${esc(row.county||row.display_name||"")}</div></td>
      <td>${esc(row.state||"—")}<div class="meta">${esc(town)}</div></td>
      <td>${esc(row.type||"water")}</td>
      <td><span class="pill ${accessClass}">${esc(accessText)}</span></td>
      <td><span class="directory-source-badge ${sourceClass}">${esc(sourceText)}</span></td>
      <td>${esc(coordinates)}</td>
      <td>${official}</td>
      <td><div class="directory-table-actions">${actions}</div></td>
    </tr>`;
  }).join(""):'<tr><td colspan="8">No managed waters match these filters.</td></tr>';

  document.querySelectorAll("[data-water-action]").forEach(button=>{
    button.addEventListener("click",()=>handleDirectoryAction(button.dataset.waterAction,button.dataset.waterKey));
  });
}

function recordByKey(recordKey){
  return mergedDirectory().find(row=>key(row)===recordKey)||null;
}

function editorValues(){
  const aliases=$("directoryEditAliases").value.split(",").map(clean).filter(Boolean);
  const nearbyTowns=$("directoryEditNearbyTowns").value.split(",").map(clean).filter(Boolean);
  const name=clean($("directoryEditName").value);
  const state=clean($("directoryEditState").value);
  const lat=numberOrNull($("directoryEditLat").value);
  const lon=numberOrNull($("directoryEditLon").value);
  const access=clean($("directoryEditAccess").value)||"unknown";

  if(!name||!state)throw new Error("Water name and state are required.");
  if(!Number.isFinite(lat)||!Number.isFinite(lon))throw new Error("Valid latitude and longitude are required.");

  return{
    name,
    aliases:aliases.length?aliases:[name],
    display_name:`${name}${$("directoryEditCounty").value?`, ${clean($("directoryEditCounty").value)}`:""}, ${state}`,
    lat,lon,state,
    county:clean($("directoryEditCounty").value),
    category:"water",
    type:clean($("directoryEditType").value)||"water",
    nearby_towns:nearbyTowns,
    nearby_town_label:clean($("directoryEditTown").value),
    official_url:clean($("directoryEditUrl").value),
    public_access_verified:["open","restricted"].includes(access),
    access_status:access,
    public_access_note:clean($("directoryEditNote").value)||
      "Verify current access, regulations, and posted signs before traveling.",
    public_access_source:clean($("directoryEditSourceText").value)||
      "Fish Finder Outdoors directory review",
    visibility:["private","closed"].includes(access)?"hidden":"public"
  };
}

function openEditor(record=null,source="managed"){
  editorMode=record?"edit":"new";
  editorKey=record?key(record):"";
  editorSource=source;
  const row=record||{};

  $("waterEditorTitle").textContent=record?`Edit ${row.name}`:"Add a managed water";
  $("waterEditorHelp").textContent=
    source==="approved"||source==="approved-edit"
      ?"This record is stored in official_water_overrides.js. Saving downloads that correction file."
      :"This record is stored in managed_water_directory.js. Saving downloads the managed directory file.";

  $("directoryEditName").value=row.name||"";
  $("directoryEditState").value=row.state||"";
  $("directoryEditTown").value=row.nearby_town_label||"";
  $("directoryEditCounty").value=row.county||"";
  $("directoryEditType").value=row.type||"water";
  $("directoryEditAccess").value=row.visibility==="hidden"?(row.access_status||"private"):(row.access_status||"unknown");
  $("directoryEditLat").value=Number.isFinite(Number(row.lat))?row.lat:"";
  $("directoryEditLon").value=Number.isFinite(Number(row.lon))?row.lon:"";
  $("directoryEditAliases").value=(row.aliases||[]).join(", ");
  $("directoryEditNearbyTowns").value=(row.nearby_towns||[]).join(", ");
  $("directoryEditUrl").value=row.official_url||"";
  $("directoryEditSourceText").value=row.public_access_source||"";
  $("directoryEditNote").value=row.public_access_note||"";

  $("waterDirectoryEditor").classList.remove("hidden");
  $("waterDirectoryEditor").scrollIntoView({behavior:"smooth",block:"start"});
}

function closeEditor(){
  $("waterDirectoryEditor").classList.add("hidden");
}

function saveEditor(){
  try{
    const record=editorValues();
    const newKey=key(record);

    if(editorSource==="approved"||editorSource==="approved-edit"){
      let overrides=currentOverrides().filter(row=>key(row)!==editorKey&&key(row)!==newKey);
      const existing=currentOverrides().find(row=>key(row)===editorKey)||{};
      overrides.unshift({
        ...existing,
        ...record,
        correction_id:existing.correction_id||`admin-${Date.now()}`,
        approved_at:new Date().toISOString(),
        approved_override:true,
        visibility:record.visibility
      });
      setOverrides(overrides);
      downloadOverrides();
      alert("The updated official_water_overrides.js file was downloaded. Replace that file in GitHub.");
    }else{
      workingManaged=workingManaged.filter(row=>key(row)!==editorKey&&key(row)!==newKey);
      workingManaged.unshift({
        ...record,
        directory_id:record.directory_id||`ffo-managed-${Date.now()}`,
        managed_source:"Fish Finder Outdoors managed directory"
      });
      workingManaged.sort((a,b)=>String(a.state).localeCompare(String(b.state))||String(a.name).localeCompare(String(b.name)));
      downloadManaged();
      alert("The updated managed_water_directory.js file was downloaded. Replace that file in GitHub.");
    }

    closeEditor();
    renderDirectory();
  }catch(error){
    alert(error.message||"The water record could not be saved.");
  }
}

async function resolveEditorCoordinates(){
  const name=clean($("directoryEditName").value);
  const state=clean($("directoryEditState").value);
  if(!name) return alert("Enter the water name first.");

  const button=$("resolveDirectoryCoordinates");
  button.disabled=true;
  button.textContent="Searching…";
  try{
    const rows=await window.FFO_REGION_SEARCH.search(`${name}${state?`, ${state}`:""}`);
    const exact=rows.find(row=>normalize(row.name)===normalize(name))||rows[0];
    if(!exact)throw new Error("No geographic-name result was found.");
    $("directoryEditName").value=exact.name||name;
    $("directoryEditState").value=exact.state||state;
    $("directoryEditType").value=exact.type||$("directoryEditType").value;
    $("directoryEditLat").value=Number(exact.lat).toFixed(6);
    $("directoryEditLon").value=Number(exact.lon).toFixed(6);
    if(!$("directoryEditUrl").value&&exact.official_url)$("directoryEditUrl").value=exact.official_url;
  }catch(error){
    alert(error.message||"Coordinates could not be resolved.");
  }finally{
    button.disabled=false;
    button.textContent="Find coordinates automatically";
  }
}

function markHidden(recordKey,status){
  const row=recordByKey(recordKey);
  if(!row)return;
  let overrides=currentOverrides().filter(item=>key(item)!==recordKey);
  overrides.unshift({
    ...clone(row),
    correction_id:row.correction_id||`admin-${Date.now()}`,
    approved_at:new Date().toISOString(),
    previous_access_status:row.access_status||"unknown",
    visibility:"hidden",
    access_status:status,
    public_access_verified:false,
    public_access_note:row.public_access_note||`Marked ${status} in the FFO admin directory.`
  });
  setOverrides(overrides);
  downloadOverrides();
  renderDirectory();
  alert(`Marked ${row.name} as ${status}. The updated official_water_overrides.js file was downloaded.`);
}

function restoreRecord(recordKey){
  const baseExists=workingManaged.some(row=>key(row)===recordKey);
  let overrides=currentOverrides();
  const hidden=overrides.find(row=>key(row)===recordKey);

  if(baseExists){
    overrides=overrides.filter(row=>key(row)!==recordKey);
  }else if(hidden){
    overrides=overrides.filter(row=>key(row)!==recordKey);
    overrides.unshift({
      ...hidden,
      visibility:"public",
      access_status:hidden.previous_access_status||"unknown",
      public_access_verified:["open","restricted"].includes(hidden.previous_access_status)
    });
  }

  setOverrides(overrides);
  downloadOverrides();
  renderDirectory();
  alert("The record was restored. The updated official_water_overrides.js file was downloaded.");
}

function deleteApproved(recordKey){
  const row=recordByKey(recordKey);
  if(!row||!confirm(`Delete the approved addition “${row.name}”?`))return;
  setOverrides(currentOverrides().filter(item=>key(item)!==recordKey));
  downloadOverrides();
  renderDirectory();
  alert("The approved addition was removed. The updated official_water_overrides.js file was downloaded.");
}

function handleDirectoryAction(action,recordKey){
  const row=recordByKey(recordKey);
  if(action==="edit"&&row){
    openEditor(row,row._record_source);
  }else if(action==="private"){
    markHidden(recordKey,"private");
  }else if(action==="closed"){
    markHidden(recordKey,"closed");
  }else if(action==="restore"){
    restoreRecord(recordKey);
  }else if(action==="delete-approved"){
    deleteApproved(recordKey);
  }
}

function exportCsv(){
  const rows=mergedDirectory();
  const columns=[
    "name","state","nearby_town_label","county","type","access_status","visibility",
    "lat","lon","official_url","public_access_source","public_access_note","_record_source"
  ];
  const csv=[
    columns.join(","),
    ...rows.map(row=>columns.map(column=>{
      const value=String(row[column]??"").replace(/"/g,'""');
      return`"${value}"`;
    }).join(","))
  ].join("\n");
  downloadText("ffo-water-directory.csv",csv,"text/csv");
}

async function runLiveLookup(){
  const query=clean($("liveWaterQuery").value);
  if(!query)return alert("Enter a town or water name.");
  const button=$("runLiveWaterLookup");
  button.disabled=true;
  button.textContent="Searching…";
  $("liveWaterLookupStatus").textContent="Searching outside geographic and official-source data…";

  try{
    liveLookupRows=await window.FFO_REGION_SEARCH.search(query);
    $("liveWaterLookupStatus").textContent=
      `${liveLookupRows.length} temporary result${liveLookupRows.length===1?"":"s"} returned. `+
      `Nothing is saved until you choose Add to managed directory.`;

    $("liveWaterLookupRows").innerHTML=liveLookupRows.length?liveLookupRows.map((row,index)=>{
      const distance=Number.isFinite(Number(row.distance_miles))?`${Number(row.distance_miles).toFixed(1)} mi`:"—";
      const source=row.name_source||row.public_access_source||row.source_type||"Outside lookup";
      return`<tr>
        <td><b>${esc(row.name||"Unnamed water")}</b></td>
        <td>${esc(row.state||"—")}</td>
        <td>${esc(row.type||"water")}</td>
        <td>${esc(distance)}</td>
        <td>${esc(row.access_status||"unknown")}</td>
        <td>${esc(source)}</td>
        <td><button class="primary" data-live-add="${index}">Add to managed directory</button></td>
      </tr>`;
    }).join(""):'<tr><td colspan="7">No live results were returned.</td></tr>';

    document.querySelectorAll("[data-live-add]").forEach(button=>{
      button.addEventListener("click",()=>{
        const row=liveLookupRows[Number(button.dataset.liveAdd)];
        if(!row)return;
        openEditor({
          ...row,
          aliases:row.aliases||[row.name],
          nearby_towns:row.nearby_towns||[],
          public_access_note:row.public_access_note||
            "Added from the live lookup inspector. Verify current access before publishing.",
          public_access_source:row.public_access_source||row.name_source||
            "Live geographic-name lookup"
        },"managed");
      });
    });
  }catch(error){
    liveLookupRows=[];
    $("liveWaterLookupStatus").textContent=error.message||"The live lookup could not connect.";
    $("liveWaterLookupRows").innerHTML='<tr><td colspan="7">The live lookup could not connect.</td></tr>';
  }finally{
    button.disabled=false;
    button.textContent="Search live waters";
  }
}

["waterDirectorySearch","waterDirectoryState","waterDirectoryAccess","waterDirectorySource"].forEach(id=>{
  $(id).addEventListener(id==="waterDirectorySearch"?"input":"change",renderDirectory);
});
$("addManagedWater").addEventListener("click",()=>openEditor(null,"managed"));
$("closeWaterEditor").addEventListener("click",closeEditor);
$("saveWaterDirectoryRecord").addEventListener("click",saveEditor);
$("resolveDirectoryCoordinates").addEventListener("click",resolveEditorCoordinates);
$("exportManagedDirectory").addEventListener("click",downloadManaged);
$("exportWaterOverrides").addEventListener("click",downloadOverrides);
$("exportWaterCsv").addEventListener("click",exportCsv);
$("runLiveWaterLookup").addEventListener("click",runLiveLookup);
$("liveWaterQuery").addEventListener("keydown",event=>{
  if(event.key==="Enter"){event.preventDefault();runLiveLookup();}
});

renderDirectory();
})();
