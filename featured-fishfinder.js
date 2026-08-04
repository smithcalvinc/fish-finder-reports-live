/* Fish Finder Outdoors featured fish finder affiliate card. */
(function(){
  "use strict";

  const affiliateUrl='https://amzn.to/4wHzwXl';
  const productName="Garmin STRIKER Vivid 7sv";

  function cardMarkup(placement){
    return `
      <section class="ffo-affiliate-card" aria-labelledby="ffoAffiliateTitle-${placement}">
        <div class="ffo-affiliate-visual" aria-hidden="true">
          <svg viewBox="0 0 300 215" role="img">
            <defs>
              <linearGradient id="ffoSonarScreen-${placement}" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#0d2f29"/>
                <stop offset=".55" stop-color="#176354"/>
                <stop offset="1" stop-color="#d95d39"/>
              </linearGradient>
              <linearGradient id="ffoSonarBottom-${placement}" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" stop-color="#d6a443"/>
                <stop offset="1" stop-color="#f4c867"/>
              </linearGradient>
            </defs>
            <rect x="30" y="15" width="240" height="158" rx="18" fill="#12211e"/>
            <rect x="43" y="28" width="214" height="132" rx="10" fill="url(#ffoSonarScreen-${placement})"/>
            <g opacity=".24" stroke="#fff" stroke-width="1">
              <path d="M43 61h214M43 94h214M43 127h214"/>
              <path d="M86 28v132M129 28v132M172 28v132M215 28v132"/>
            </g>
            <path d="M43 145 C78 125,112 151,146 132 S215 122,257 139 L257 160 L43 160 Z"
                  fill="url(#ffoSonarBottom-${placement})" opacity=".95"/>
            <g fill="none" stroke="#dff4eb" stroke-width="3" stroke-linecap="round">
              <path d="M80 78c14-12 29-12 43 0"/>
              <path d="M93 69c6-5 12-5 18 0"/>
              <path d="M181 103c13-11 27-11 40 0"/>
            </g>
            <g fill="#fff">
              <path d="M125 89c12-8 27-7 37 1-10 9-25 10-37 2l-9 7 2-13z"/>
              <circle cx="151" cy="89" r="1.8" fill="#17372e"/>
              <path d="M72 112c9-6 21-5 28 1-8 7-19 8-28 1l-7 5 2-10z"/>
              <circle cx="91" cy="112" r="1.5" fill="#17372e"/>
              <path d="M191 68c9-6 21-5 28 1-8 7-19 8-28 1l-7 5 2-10z"/>
              <circle cx="210" cy="68" r="1.5" fill="#17372e"/>
            </g>
            <rect x="123" y="173" width="54" height="18" rx="6" fill="#12211e"/>
            <path d="M102 200h96" stroke="#12211e" stroke-width="12" stroke-linecap="round"/>
            <circle cx="244" cy="176" r="7" fill="#d95d39"/>
          </svg>
        </div>

        <div class="ffo-affiliate-copy">
          <span class="ffo-affiliate-eyebrow">Featured Fish Finder</span>
          <h2 id="ffoAffiliateTitle-${placement}">Garmin STRIKER Vivid 7sv</h2>
          <p class="ffo-affiliate-intro">
            A polished step-up choice for boat anglers who want a larger screen,
            GPS, and a clearer look at fish and underwater structure below and
            beside the boat.
          </p>
          <div class="ffo-affiliate-features" aria-label="Highlighted features">
            <span>7-inch display</span>
            <span>Built-in GPS</span>
            <span>CHIRP sonar</span>
            <span>ClearVü + SideVü</span>
          </div>
          <a
            class="ffo-affiliate-button"
            href="${affiliateUrl}"
            target="_blank"
            rel="sponsored nofollow noopener"
            data-ffo-affiliate-link
            data-placement="${placement}"
          >See Current Price on Amazon <span aria-hidden="true">↗</span></a>
          <p class="ffo-affiliate-disclosure">
            Paid link. As an Amazon Associate I earn from qualifying purchases.
            Price and availability can change.
          </p>
        </div>
      </section>
    `;
  }

  document.querySelectorAll("[data-ffo-affiliate-slot]").forEach((slot,index)=>{
    const placement=String(
      slot.getAttribute("data-ffo-affiliate-slot")||`placement-${index+1}`
    ).replace(/[^a-z0-9-]/gi,"-").toLowerCase();

    slot.innerHTML=cardMarkup(placement);
  });

  document.addEventListener("click",event=>{
    const link=event.target.closest("[data-ffo-affiliate-link]");
    if(!link)return;

    const eventData={
      affiliate_network:"Amazon Associates",
      item_name:productName,
      link_url:affiliateUrl,
      placement:link.getAttribute("data-placement")||"unknown"
    };

    if(typeof window.gtag==="function"){
      window.gtag("event","affiliate_click",eventData);
    }else if(Array.isArray(window.dataLayer)){
      window.dataLayer.push({
        event:"affiliate_click",
        ...eventData
      });
    }
  });
})();
