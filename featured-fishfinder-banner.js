/* Track featured fish finder affiliate clicks. */
(function(){
  "use strict";

  document.addEventListener("click",function(event){
    const link=event.target.closest("[data-ffo-product-affiliate]");
    if(!link)return;

    const eventData={
      affiliate_network:"Amazon Associates",
      item_name:"Garmin STRIKER Vivid 7sv",
      link_url:"https://amzn.to/4wHzwXl",
      placement:link.getAttribute("data-placement")||"unknown"
    };

    if(typeof window.gtag==="function"){
      window.gtag("event","affiliate_click",eventData);
    }else if(Array.isArray(window.dataLayer)){
      window.dataLayer.push({event:"affiliate_click",...eventData});
    }
  });
})();
