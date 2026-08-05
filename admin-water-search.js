(function(){
  "use strict";

  const index=window.FFO_ADMIN_WATER_INDEX||{};
  const status=window.FFO_UPDATE_STATUS||{};
  const waters=Array.isArray(index.waters)?index.waters:[];
  const states=Array.isArray(index.states)?index.states:[];
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??"").replace(/[&<>'"]/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
  const clean=value=>String(value??"").replace(/\s+/g," ").trim();
  const norm=value=>clean(value).toLowerCase().replace(/[^a-z0-9\s]/g," ").replace(/\s+/g," ").trim();
  const fmt=value=>Number(value||0).toLocaleString();
  const date=value=>{
    if(!value)return"—";
    const parsed=new Date(value);
    return Number.isNaN(parsed.getTime())?clean(value):parsed.toLocaleString([],{dateStyle:"medium",timeStyle:"short"});
  };

  function addStyles(){
    if($("ffo-admin-water-search-style"))return;
    const style=document.createElement("style");
    style.id="ffo-admin-water-search-style";
    style.textContent=`
      .admin-water-panel{border-left:6px solid #1F4D3A}
      .admin-water-panel h2{margin-bottom:6px}
      .admin-water-controls{display:grid;grid-template-columns:minmax(180px,.8fr) minmax(180px,.8fr) minmax(230px,1.25fr) auto auto;gap:10px;align-items:end;margin:16px 0 12px}
      .admin-water-controls label{display:grid;gap:6px;color:#31443e;font-size:12px;font-weight:850}
      .admin-water-controls input,.admin-water-controls select{width:100%;min-height:44px;border:1px solid #b8c5bf;border-radius:9px;background:#fff;padding:10px 11px;color:#17231f;font:inherit}
      .admin-water-controls button{min-height:44px}
      .admin-index-meta{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 14px}
      .admin-index-meta span{display:inline-flex;align-items:center;padding:6px 9px;border:1px solid #cad8d1;border-radius:999px;background:#f4f8f6;color:#29473e;font-size:12px;font-weight:800}
      .admin-integrity-note{margin:12px 0;padding:11px 13px;border-radius:10px;border:1px solid #d8c998;background:#fff8dc;color:#5f501e;font-size:13px;line-height:1.45}
      .admin-search-message{margin:10px 0;color:#52635d;font-size:13px}
      .admin-water-name{font-weight:850;color:#183d32}
      .admin-water-actions{display:flex;gap:6px;flex-wrap:wrap}
      .admin-water-actions a{display:inline-flex;align-items:center;padding:7px 9px;border:1px solid #b8c8c0;border-radius:8px;background:#fff;color:#174c3e;text-decoration:none;font-size:12px;font-weight:850;white-space:nowrap}
      .admin-water-actions a.primary-link{background:#1F4D3A;color:#fff;border-color:#1F4D3A}
      .admin-water-results td{vertical-align:top}
      .admin-water-results .meta{line-height:1.45}
      .admin-state-overview{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:14px}
      .admin-state-card{padding:12px;border:1px solid #d5ddd9;border-radius:11px;background:#fbfcfb}
      .admin-state-card strong{display:block;color:#173b31;margin-bottom:5px}
      .admin-state-card span{display:block;color:#5c6864;font-size:12px;line-height:1.45}
      .admin-source-empty{padding:14px;border:1px dashed #c6d1cc;border-radius:10px;background:#f8faf9;color:#53615c}
      @media(max-width:900px){.admin-water-controls{grid-template-columns:1fr 1fr}.admin-state-overview{grid-template-columns:1fr 1fr}}
      @media(max-width:620px){.admin-water-controls,.admin-state-overview{grid-template-columns:1fr}.admin-water-results th:nth-child(4),.admin-water-results td:nth-child(4){display:none}}
    `;
    document.head.appendChild(style);
  }

  function refreshDashboardSummary(){
    const summary=$("summary");
    if(summary){
      const fresh=status.freshness||{};
      const metrics=[
        ["Completed regions",status.state_count??index.state_count??states.length],
        ["County shells",status.county_count??index.county_shell_count??0],
        ["Public-water rows",status.public_water_count??index.source_public_water_rows??0],
        ["Unique water names",index.unique_water_count??waters.length],
        ["Unique report records",status.reports_total??index.aggregate_report_total??0],
        ["Review required",status.review_required??0]
      ];
      summary.innerHTML=metrics.map(([label,value])=>`<div class="metric"><span class="meta">${esc(label)}</span><b>${esc(fmt(value))}</b></div>`).join("");
    }
    const lastRun=$("lastRun");
    if(lastRun){
      const freshness=status.freshness||{};
      lastRun.textContent=`Last aggregate update: ${date(status.last_run||index.generated_at)} · ${fmt(status.unique_sources)} unique official sources · ${fmt(freshness.current)} current · ${fmt(freshness.aging)} aging · ${fmt(freshness.stale)} stale.`;
    }
  }

  function statePageFor(row){
    return clean(row.state_page)||"index.html";
  }

  function fullReportUrl(row){
    const county=(row.counties||[])[0]||"";
    const queryState=row.state==="Northern California"?"California":row.state;
    const params=new URLSearchParams({
      q:[row.water_name,county,queryState].filter(Boolean).join(", "),
      open:"1",
      water:row.water_name,
      state:row.state
    });
    if(county)params.set("county",county);
    if(Number.isFinite(Number(row.latitude))&&Number.isFinite(Number(row.longitude))){
      params.set("lat",String(row.latitude));
      params.set("lon",String(row.longitude));
      params.set("direct","1");
    }
    if(row.official_source_url)params.set("source",row.official_source_url);
    return `index.html?${params.toString()}`;
  }

  function insertPanel(){
    const main=document.querySelector("main.wrap");
    if(!main||$("adminWaterSearchPanel"))return;
    const summaryPanel=$("summary")?.closest("section.panel")||main.firstElementChild;
    const panel=document.createElement("section");
    panel.className="panel admin-water-panel";
    panel.id="adminWaterSearchPanel";
    panel.innerHTML=`
      <h2>Search the completed fishing database</h2>
      <p class="meta">Search all nine completed state and regional databases by state, body of water, or county. This index is generated from the same files used by the public state pages.</p>
      <div class="admin-index-meta">
        <span>${esc(fmt(index.state_count||states.length))} regions</span>
        <span>${esc(fmt(index.county_shell_count||0))} county shells</span>
        <span>${esc(fmt(index.source_public_water_rows||0))} public-water rows</span>
        <span>${esc(fmt(index.unique_water_count||waters.length))} unique water names</span>
        <span>Index updated ${esc(date(index.generated_at))}</span>
      </div>
      <form class="admin-water-controls" id="adminWaterSearchForm">
        <label>State or region<select id="adminStateFilter"><option value="">All completed regions</option>${states.map(row=>`<option value="${esc(row.state)}">${esc(row.state)} (${esc(fmt(row.unique_water_names))})</option>`).join("")}</select></label>
        <label>County<input id="adminCountyQuery" type="search" autocomplete="off" placeholder="Example: Fremont"></label>
        <label>Body of water<input id="adminWaterQuery" type="search" autocomplete="off" placeholder="Example: Beaver Creek"></label>
        <button class="primary" id="adminWaterSearch" type="submit">Search database</button>
        <button class="secondary" id="adminWaterClear" type="button">Clear</button>
      </form>
      <div id="adminIndexWarning"></div>
      <p class="admin-search-message" id="adminWaterMessage"></p>
      <div class="table-wrap"><table class="admin-water-results"><thead><tr><th>Body of water</th><th>State / counties</th><th>Type and access</th><th>Reports</th><th>Open</th></tr></thead><tbody id="adminWaterRows"></tbody></table></div>
      <div class="admin-state-overview" id="adminStateOverview"></div>
    `;
    if(summaryPanel?.nextSibling)main.insertBefore(panel,summaryPanel.nextSibling);else main.appendChild(panel);
  }

  function renderWarnings(){
    const box=$("adminIndexWarning");
    if(!box)return;
    const warnings=Array.isArray(index.warnings)?index.warnings:[];
    if(!warnings.length){box.innerHTML="";return;}
    box.innerHTML=warnings.map(value=>`<div class="admin-integrity-note"><strong>Database note:</strong> ${esc(value)}</div>`).join("");
  }

  function renderStateOverview(){
    const box=$("adminStateOverview");
    if(!box)return;
    box.innerHTML=states.map(row=>`
      <div class="admin-state-card">
        <strong>${esc(row.state)}</strong>
        <span>${esc(fmt(row.unique_water_names))} unique water names</span>
        <span>${esc(fmt(row.source_public_water_rows))} county-linked water rows</span>
        <span>${esc(fmt(row.report_count))} state report records</span>
        <span>${esc(fmt(row.county_count))} county shells</span>
      </div>
    `).join("");
  }

  function score(row,waterQuery,countyQuery){
    let value=0;
    const name=norm(row.water_name);
    if(waterQuery){
      if(name===waterQuery)value+=1000;
      else if(name.startsWith(waterQuery))value+=700;
      else if(name.includes(waterQuery))value+=500;
    }
    if(countyQuery&&(row.counties||[]).some(county=>norm(county)===countyQuery))value+=300;
    if(row.report_count)value+=Math.min(100,Number(row.report_count));
    return value;
  }

  function filteredRows(){
    const state=clean($("adminStateFilter")?.value);
    const waterQuery=norm($("adminWaterQuery")?.value);
    const countyQuery=norm($("adminCountyQuery")?.value);
    if(!state&&!waterQuery&&!countyQuery)return[];
    return waters
      .filter(row=>!state||row.state===state)
      .filter(row=>!waterQuery||norm(row.water_name).includes(waterQuery))
      .filter(row=>!countyQuery||(row.counties||[]).some(county=>norm(county).includes(countyQuery)))
      .map(row=>({row,score:score(row,waterQuery,countyQuery)}))
      .sort((a,b)=>b.score-a.score||a.row.state.localeCompare(b.row.state)||a.row.water_name.localeCompare(b.row.water_name))
      .map(item=>item.row);
  }

  function renderSearch(){
    const body=$("adminWaterRows");
    const message=$("adminWaterMessage");
    const overview=$("adminStateOverview");
    if(!body||!message)return;
    const state=clean($("adminStateFilter")?.value);
    const waterQuery=clean($("adminWaterQuery")?.value);
    const countyQuery=clean($("adminCountyQuery")?.value);
    if(!state&&!waterQuery&&!countyQuery){
      body.innerHTML='<tr><td colspan="5">Choose a state, enter a county, or enter a body of water, then click Search database.</td></tr>';
      message.textContent="You can use any one filter or combine all three. Pressing Enter also runs the search.";
      if(overview)overview.hidden=false;
      return;
    }
    if(overview)overview.hidden=true;
    const matches=filteredRows();
    const visible=matches.slice(0,250);
    message.textContent=matches.length>250
      ? `${fmt(matches.length)} matches found. Showing the first 250—narrow the water or county search for a shorter list.`
      : `${fmt(matches.length)} matching water record${matches.length===1?"":"s"}.`;
    body.innerHTML=visible.map(row=>{
      const counties=(row.counties||[]).join(", ")||"County not listed";
      const access=(row.access_names||[]).slice(0,3).join(" · ")||row.public_access_verification||"Verified public-water database record";
      const reports=Number(row.report_count||0);
      const latest=row.latest_report_date?`<div class="meta">Latest: ${esc(row.latest_report_date)}</div>`:"";
      return `<tr>
        <td><span class="admin-water-name">${esc(row.water_name)}</span>${row.official_source_url?`<div class="meta"><a href="${esc(row.official_source_url)}" target="_blank" rel="noopener">Official access source ↗</a></div>`:""}</td>
        <td><b>${esc(row.state)}</b><div class="meta">${esc(counties)}</div></td>
        <td>${esc(row.water_type||"Waterbody")}<div class="meta">${esc(access)}</div></td>
        <td>${esc(fmt(reports))}${latest}</td>
        <td><div class="admin-water-actions"><a class="primary-link" href="${esc(fullReportUrl(row))}" target="_blank" rel="noopener">Full report</a><a href="${esc(statePageFor(row))}" target="_blank" rel="noopener">State page</a></div></td>
      </tr>`;
    }).join("")||'<tr><td colspan="5">No water records match those filters.</td></tr>';
  }

  function repairEmptySourcePanel(){
    const reportRows=$("reportRows");
    const sourcePanel=reportRows?.closest("section.panel");
    if(!sourcePanel)return;
    const recent=window.FFO_RECENT_REPORTS?.reports||[];
    if(recent.length)return;
    const heading=sourcePanel.querySelector("h2");
    if(heading)heading.textContent="Official source monitoring";
    const wrap=sourcePanel.querySelector(".table-wrap");
    if(wrap){
      wrap.innerHTML=`<div class="admin-source-empty"><strong>The old recent-report table has no rows.</strong><p>The dashboard is now using the complete nine-state water index above. Aggregate monitoring currently shows ${esc(fmt(status.unique_sources))} unique official sources, ${esc(fmt(status.unreachable_sources))} unreachable sources, and ${esc(fmt(status.review_required))} records requiring review.</p></div>`;
    }
    const controls=$("sourceSearch")?.closest("section.panel");
    if(controls)controls.hidden=true;
  }

  function bind(){
    $("adminWaterSearchForm")?.addEventListener("submit",event=>{
      event.preventDefault();
      renderSearch();
    });
    $("adminWaterClear")?.addEventListener("click",()=>{
      $("adminStateFilter").value="";
      $("adminWaterQuery").value="";
      $("adminCountyQuery").value="";
      renderSearch();
      $("adminStateFilter").focus();
    });
  }

  function start(){
    addStyles();
    refreshDashboardSummary();
    insertPanel();
    renderWarnings();
    renderStateOverview();
    repairEmptySourcePanel();
    bind();
    renderSearch();
    if(!states.length||!waters.length){
      const message=$("adminWaterMessage");
      const button=$("adminWaterSearch");
      if(message)message.textContent="The Admin water index has not been generated yet. Run the Update Admin Water Search Index workflow once.";
      if(button)button.disabled=true;
    }
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});
  else start();
})();
