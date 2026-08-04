/* Open a statewide county-report page directly to a requested water. */
(function(){
  "use strict";

  function fixedHeaderOffset(){
    const header=document.querySelector(".ffo-site-header");
    const height=header?.getBoundingClientRect().height||0;
    return Math.max(84,Math.round(height+14));
  }

  function scrollToResults(){
    const target=
      document.querySelector("#waterList .water-card")||
      document.getElementById("waterList")||
      document.getElementById("status");

    if(!target)return;

    window.setTimeout(()=>{
      const top=
        target.getBoundingClientRect().top+
        window.scrollY-
        fixedHeaderOffset();

      window.scrollTo({
        top:Math.max(0,top),
        behavior:"smooth"
      });
    },140);
  }

  function openRequestedWater(){
    const params=new URLSearchParams(window.location.search);
    const query=String(params.get("q")||"").trim();
    const requestedCounty=String(params.get("county")||"").trim();

    if(!query)return;

    const waterSearch=document.getElementById("waterSearch");
    const countySelect=document.getElementById("countySelect");
    const searchButton=document.getElementById("searchButton");

    if(!waterSearch||!searchButton)return;

    waterSearch.value=query;

    if(requestedCounty&&countySelect){
      const normalized=requestedCounty.toLowerCase();
      const option=Array.from(countySelect.options).find(item=>
        String(item.value||"").trim().toLowerCase()===normalized
      );
      if(option)countySelect.value=option.value;
    }

    searchButton.click();
    scrollToResults();
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",openRequestedWater,{once:true});
  }else{
    openRequestedWater();
  }
})();
