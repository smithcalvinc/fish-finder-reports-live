/* Fish Finder Outdoors polished report homepage */
(function(){
  "use strict";

  const mainInput=document.getElementById("locationInput");
  const mainForm=document.getElementById("searchForm");
  const heroInput=document.getElementById("heroLocationInput");
  const heroForm=document.getElementById("heroSearchForm");

  const mainWrap=document.querySelector("main.wrap");
  const searchPanel=document.getElementById("report-search");
  const statusBox=document.getElementById("status");
  const resultsBox=document.getElementById("results");
  const reportSection=document.getElementById("report");

  // The search tool remains the first content block on phones and computers.
  if(mainWrap&&searchPanel&&mainWrap.firstElementChild!==searchPanel){
    mainWrap.prepend(searchPanel);
  }

  function fixedHeaderOffset(){
    const header=document.querySelector(".ffo-site-header");
    const height=header?.getBoundingClientRect().height||0;
    return Math.max(84,Math.round(height+14));
  }

  function scrollPrimaryContent(element,behavior="smooth"){
    if(!element)return;
    const top=element.getBoundingClientRect().top+window.scrollY-fixedHeaderOffset();
    window.scrollTo({top:Math.max(0,top),behavior});
  }

  let awaitingSearchResults=false;
  let awaitingFullReport=false;
  let searchScrollTimer=0;
  let reportScrollTimer=0;

  function scheduleSearchScroll(target){
    window.clearTimeout(searchScrollTimer);
    searchScrollTimer=window.setTimeout(()=>{
      scrollPrimaryContent(target||searchPanel);
    },90);
  }

  function scheduleReportScroll(){
    window.clearTimeout(reportScrollTimer);
    reportScrollTimer=window.setTimeout(()=>{
      if(reportSection&&!reportSection.classList.contains("hidden")){
        scrollPrimaryContent(reportSection);
        awaitingFullReport=false;
      }
    },110);
  }

  mainForm?.addEventListener("submit",()=>{
    awaitingSearchResults=true;
    scheduleSearchScroll(searchPanel);
  },true);

  resultsBox?.addEventListener("click",event=>{
    if(event.target.closest(".result")){
      awaitingFullReport=true;
      scheduleReportScroll();
    }
  },true);

  if(resultsBox){
    new MutationObserver(()=>{
      if(!awaitingSearchResults)return;
      if(resultsBox.children.length){
        awaitingSearchResults=false;
        scheduleSearchScroll(resultsBox);
      }
    }).observe(resultsBox,{childList:true,subtree:true});
  }

  if(statusBox){
    new MutationObserver(()=>{
      if(!awaitingSearchResults)return;
      if(!statusBox.classList.contains("hidden")&&statusBox.textContent.trim()){
        scheduleSearchScroll(statusBox);
      }
    }).observe(statusBox,{
      childList:true,
      subtree:true,
      characterData:true,
      attributes:true,
      attributeFilter:["class"]
    });
  }

  if(reportSection){
    new MutationObserver(()=>{
      if(awaitingFullReport&&!reportSection.classList.contains("hidden")){
        scheduleReportScroll();
      }
    }).observe(reportSection,{
      childList:true,
      subtree:true,
      attributes:true,
      attributeFilter:["class"]
    });
  }

  function runMainSearch(query){
    const value=String(query||"").trim();
    if(!value||!mainInput||!mainForm)return;
    mainInput.value=value;
    awaitingSearchResults=true;
    scrollPrimaryContent(searchPanel);
    window.setTimeout(()=>{
      if(typeof mainForm.requestSubmit==="function")mainForm.requestSubmit();
      else mainForm.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}));
    },260);
  }

  heroForm?.addEventListener("submit",event=>{
    event.preventDefault();
    runMainSearch(heroInput?.value);
  });

  document.querySelectorAll(".ffo-hero-examples a").forEach(link=>{
    link.addEventListener("click",event=>{
      const url=new URL(link.href,window.location.href);
      const query=url.searchParams.get("q");
      if(!query)return;
      event.preventDefault();
      if(heroInput)heroInput.value=query;
      runMainSearch(query);
    });
  });

  const holder=document.getElementById("latestReportCards");
  if(!holder)return;

  const official=Array.isArray(window.FFO_RECENT_REPORTS?.reports)?window.FFO_RECENT_REPORTS.reports:[];
  const community=Array.isArray(window.FFO_COMMUNITY_REPORTS?.reports)?window.FFO_COMMUNITY_REPORTS.reports:[];
  const today=new Date();
  today.setHours(23,59,59,999);
  const earliest=new Date(today);
  earliest.setFullYear(today.getFullYear()-2);

  const blockedHeadline=/bear|attack|fatal|commission|bag limit|closure|emergency rule|harvest rule|press release/i;
  const usefulKind=/stocking|fishing|community|angler|catch/i;
  const imageFiles=["ffo-report-card-1.jpg","ffo-report-card-2.jpg","ffo-report-card-3.jpg"];

  function parseDate(value){
    const date=new Date(String(value||"")+"T12:00:00");
    return Number.isNaN(date.getTime())?null:date;
  }

  function waterName(report){
    return report.water_name||(Array.isArray(report.names)?report.names[0]:"")||"Fishing water";
  }

  function countyLabel(report){
    if(Array.isArray(report.counties)&&report.counties.length)return report.counties[0]+" County";
    return report.county||"";
  }

  function cleanSpecies(value){
    const text=String(value||"").trim();
    if(!text||text.length>58||/usually catchable|unless the official/i.test(text))return "";
    return text;
  }

  function summaryText(report){
    const text=String(report.summary||"").replace(/\s+/g," ").trim();
    if(!text)return "Open the report to review the newest available details and official source.";
    return text.length>210?text.slice(0,207).trim()+"…":text;
  }

  function escapeHtml(value){
    return String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  }

  const candidates=[...community,...official]
    .map(report=>({report,date:parseDate(report.published_date)}))
    .filter(item=>item.date&&item.date>=earliest&&item.date<=today)
    .filter(item=>usefulKind.test(String(item.report.report_kind||item.report.report_type||"")))
    .filter(item=>!blockedHeadline.test(String(item.report.headline||"")))
    .sort((a,b)=>{
      const idaho=Number(b.report.state==="Idaho")-Number(a.report.state==="Idaho");
      return idaho||b.date-a.date;
    });

  const selected=[];
  const seen=new Set();
  for(const item of candidates){
    const key=waterName(item.report).toLowerCase();
    if(seen.has(key))continue;
    seen.add(key);
    selected.push(item);
    if(selected.length===3)break;
  }

  if(!selected.length){
    holder.innerHTML='<article class="ffo-report-preview"><img src="ffo-report-card-1.jpg" alt="Illustrative fishing water"><div><span class="ffo-report-kind">Report feed</span><h3>Search a water to see the newest available information.</h3><p>The report tool links official sources, access details, weather, and dated updates when available.</p><a href="#report-search">Search Fishing Waters</a></div></article>';
    return;
  }

  holder.innerHTML=selected.map((item,index)=>{
    const report=item.report;
    const water=waterName(report);
    const state=String(report.state||"");
    const county=countyLabel(report);
    const species=cleanSpecies(report.species||(report.catches?.[0]?.species));
    const label=String(report.report_type||report.report_kind||"Fishing update").replace(/_/g," ");
    const date=item.date.toLocaleDateString(undefined,{year:"numeric",month:"long",day:"numeric"});
    const query=encodeURIComponent(water+(state?", "+state:""));
    return `<article class="ffo-report-preview">
      <a class="ffo-report-image-link" href="?q=${query}" aria-label="Search ${escapeHtml(water)}"><img src="${imageFiles[index]}" alt="Illustrative scenic fishing water image" loading="lazy"></a>
      <div class="ffo-report-preview-copy">
        <span class="ffo-report-kind">${escapeHtml(label)}</span>
        <h3><a href="?q=${query}">${escapeHtml(report.headline||water)}</a></h3>
        <div class="ffo-report-meta"><span>● ${escapeHtml(state)}</span>${county?`<span>● ${escapeHtml(county)}</span>`:""}${species?`<span>● ${escapeHtml(species)}</span>`:""}</div>
        <div class="ffo-report-date">${escapeHtml(date)}</div>
        <p>${escapeHtml(summaryText(report))}</p>
        <div class="ffo-report-preview-footer"><span>Source: ${escapeHtml(report.agency||"Reviewed report feed")}</span><a href="?q=${query}">Open Report</a></div>
      </div>
    </article>`;
  }).join("");
})();
