/* Universal exact fishing-report viewer. */
(function(){
  "use strict";

  const official=Array.isArray(window.FFO_RECENT_REPORTS?.reports)
    ?window.FFO_RECENT_REPORTS.reports
    :[];
  const community=Array.isArray(window.FFO_COMMUNITY_REPORTS?.reports)
    ?window.FFO_COMMUNITY_REPORTS.reports
    :[];
  const reports=[...community,...official];

  const statePages={
    Colorado:"colorado-county-reports.html",
    Idaho:"idaho-county-reports.html",
    Montana:"montana-county-reports.html",
    Nevada:"nevada-county-reports.html",
    Utah:"utah-county-reports.html",
    Wyoming:"wyoming-county-reports.html"
  };

  const $=id=>document.getElementById(id);

  function escapeHtml(value){
    return String(value??"").replace(/[&<>"']/g,char=>({
      "&":"&amp;",
      "<":"&lt;",
      ">":"&gt;",
      '"':"&quot;",
      "'":"&#39;"
    }[char]));
  }

  function waterName(report){
    return report?.water_name||
      (Array.isArray(report?.names)?report.names[0]:"")||
      "Fishing water";
  }

  function reportKey(report){
    if(report?.report_id)return String(report.report_id);

    const source=[
      report?.state||"",
      waterName(report),
      report?.published_date||"",
      report?.headline||"",
      report?.source_url||""
    ].join("|");

    let hash=2166136261;
    for(let index=0;index<source.length;index++){
      hash^=source.charCodeAt(index);
      hash=Math.imul(hash,16777619);
    }

    return `r${(hash>>>0).toString(16)}`;
  }

  function formatDate(value){
    if(!value)return "Date unavailable";
    const date=new Date(`${value}T12:00:00`);
    if(Number.isNaN(date.getTime()))return String(value);
    return date.toLocaleDateString(undefined,{
      year:"numeric",
      month:"long",
      day:"numeric"
    });
  }

  function titleCase(value){
    return String(value||"")
      .replace(/_/g," ")
      .replace(/\b\w/g,letter=>letter.toUpperCase());
  }

  function valueText(value){
    if(value===null||value===undefined||value==="")return "";
    if(typeof value==="string"||typeof value==="number")return String(value);
    if(Array.isArray(value))return value.map(valueText).filter(Boolean).join(", ");
    if(typeof value==="object"){
      return Object.entries(value)
        .filter(([,entry])=>entry!==null&&entry!==undefined&&entry!=="")
        .map(([key,entry])=>`${titleCase(key)}: ${valueText(entry)}`)
        .join(" · ");
    }
    return String(value);
  }

  function addFact(list,label,value){
    const text=valueText(value);
    if(!text)return;
    list.push({label,text});
  }

  function directoryUrl(report){
    const state=String(report.state||"");
    const page=statePages[state];
    const water=waterName(report);
    const county=Array.isArray(report.counties)&&report.counties.length
      ?String(report.counties[0])
      :String(report.county||"");

    if(!page){
      return `index.html?q=${encodeURIComponent(
        water+(state?`, ${state}`:"")
      )}`;
    }

    const params=new URLSearchParams();
    params.set("q",water);
    if(county)params.set("county",county.replace(/\s+County$/i,""));
    return `${page}?${params.toString()}`;
  }

  function renderList(holder,items,section){
    if(!items.length){
      section.hidden=true;
      return;
    }

    holder.innerHTML=items.map(item=>`
      <div class="ffo-detail-item">
        <strong>${escapeHtml(item.title)}</strong>
        ${item.detail?`<span>${escapeHtml(item.detail)}</span>`:""}
      </div>
    `).join("");
    section.hidden=false;
  }

  function reportKind(report){
    const kind=String(report.report_kind||report.report_type||"");
    if(kind.includes("community"))return "Reviewed angler report";
    if(kind.includes("official")||report.agency)return "Official agency report";
    return "Dated fishing report";
  }

  function render(report){
    const water=waterName(report);
    const state=String(report.state||"");
    const counties=Array.isArray(report.counties)
      ?report.counties
      :report.county?[report.county]:[];
    const date=formatDate(report.published_date);
    const exactKey=reportKey(report);

    document.title=`${water} Fishing Report | Fish Finder Outdoors`;
    const canonical=document.querySelector('link[rel="canonical"]');
    if(canonical){
      canonical.href=
        `https://reports.fishfinderoutdoors.com/report-detail.html?id=${encodeURIComponent(exactKey)}`;
    }

    $("breadcrumbWater").textContent=water;
    $("reportKind").textContent=reportKind(report);
    $("reportHeadline").textContent=report.headline||`${water} Fishing Report`;
    $("reportWater").textContent=`${water}${state?` · ${state}`:""}`;

    const meta=[
      date,
      ...counties.map(county=>`${county} County`),
      report.species||"",
      report.freshness_status?`Freshness: ${titleCase(report.freshness_status)}`:""
    ].filter(Boolean);

    $("reportMeta").innerHTML=meta.map(item=>
      `<span>${escapeHtml(item)}</span>`
    ).join("");

    $("reportSummary").textContent=
      report.summary||
      "Open the original source for the available report details.";

    const catches=Array.isArray(report.catches)?report.catches:[];
    renderList(
      $("catchList"),
      catches.map(item=>({
        title:item.species||"Catch detail",
        detail:[item.metric,item.detail].filter(Boolean).join(" · ")
      })),
      $("catchSection")
    );

    const conditions=Array.isArray(report.conditions)?report.conditions:[];
    renderList(
      $("conditionList"),
      conditions.map((item,index)=>{
        if(typeof item==="string"){
          return{title:`Condition ${index+1}`,detail:item};
        }
        const entries=Object.entries(item||{});
        return{
          title:entries[0]?titleCase(entries[0][0]):`Condition ${index+1}`,
          detail:entries.map(([key,value])=>
            `${titleCase(key)}: ${valueText(value)}`
          ).join(" · ")
        };
      }),
      $("conditionSection")
    );

    const details=[];
    addFact(details,"Report type",report.report_type||report.report_kind);
    addFact(details,"Report period",report.report_period);
    addFact(details,"Species",report.species);
    addFact(details,"Techniques",report.techniques);
    addFact(details,"Rating",report.rating);
    addFact(details,"Specificity",report.specificity);

    renderList(
      $("detailList"),
      details.map(item=>({
        title:item.label,
        detail:item.text
      })),
      $("detailSection")
    );

    const officialReport=reportKind(report)==="Official agency report";
    $("sourceExplanation").textContent=officialReport
      ?"This record came from the listed government fish or wildlife agency. Open the original source for the agency’s complete context."
      :"This record came from a manually reviewed angler submission. It is not independently verified by Fish Finder Outdoors.";

    const sourceFacts=[];
    addFact(sourceFacts,"Agency or source",report.agency||"Reviewed report feed");
    addFact(sourceFacts,"Published",date);
    addFact(sourceFacts,"Last checked",report.last_checked_at);
    addFact(sourceFacts,"Source status",report.source_status);
    addFact(sourceFacts,"Report ID",exactKey);

    $("sourceFacts").innerHTML=sourceFacts.flatMap(item=>[
      `<dt>${escapeHtml(item.label)}</dt>`,
      `<dd>${escapeHtml(item.text)}</dd>`
    ]).join("");

    const sourceLink=$("officialSourceLink");
    if(report.source_url){
      sourceLink.href=report.source_url;
      sourceLink.hidden=false;
    }else{
      sourceLink.hidden=true;
    }

    $("waterDirectoryLink").href=directoryUrl(report);

    $("shareReport").addEventListener("click",async()=>{
      const data={
        title:document.title,
        text:`View the dated ${water} fishing report on Fish Finder Outdoors.`,
        url:window.location.href
      };

      try{
        if(navigator.share){
          await navigator.share(data);
          return;
        }
        await navigator.clipboard.writeText(data.url);
        $("shareReport").textContent="Report Link Copied";
        window.setTimeout(()=>$("shareReport").textContent="Share Report",1800);
      }catch(error){
        if(error?.name!=="AbortError"){
          window.prompt("Copy this report link:",data.url);
        }
      }
    });

    $("reportLoading").hidden=true;
    $("reportMissing").hidden=true;
    $("reportArticle").hidden=false;
  }

  const id=String(
    new URLSearchParams(window.location.search).get("id")||""
  ).trim();
  const report=reports.find(item=>reportKey(item)===id);

  if(!id||!report){
    $("reportLoading").hidden=true;
    $("reportMissing").hidden=false;
    return;
  }

  render(report);
})();
