(function(){
  const button=document.querySelector('.ffo-menu-button');
  const nav=document.querySelector('.ffo-nav');
  let stateMenu=null;
  const stateLinks=[
    ['idaho-county-reports.html','Idaho Locations'],
    ['montana-county-reports.html','Montana Locations'],
    ['wyoming-county-reports.html','Wyoming Locations'],
    ['utah-county-reports.html','Utah Locations'],
    ['nevada-county-reports.html','Nevada Locations'],
    ['oregon-county-reports.html','Oregon Locations'],
    ['washington-county-reports.html','Washington Locations'],
    ['northern-california-county-reports.html','N. California Locations'],
    ['colorado-county-reports.html','Colorado Locations']
  ];


  function cleanEscapedReportMarkupText(value){
    return String(value??"")
      .replace(/<\s*(script|style)\b[^>]*>[\s\S]*?<\s*\/\s*\1\s*>/gi," ")
      .replace(/<\s*a\b[^>]*>\s*<\s*img\b[^>]*>\s*<\s*\/\s*a\s*>/gi,"Official source link")
      .replace(/<\s*img\b[^>]*>/gi,"Official source image")
      .replace(/<\s*\/?\s*(?:a|br|p|div|span|strong|em|b|i|ul|ol|li)\b[^>]*>/gi," ")
      .replace(/\s+([.,;:!?])/g,"$1")
      .replace(/Official source image\./gi,"Official source link.")
      .replace(/\s+/g," ")
      .trim();
  }

  function cleanEscapedReportMarkup(root){
    if(!root)return;
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
    const nodes=[];
    while(walker.nextNode())nodes.push(walker.currentNode);
    nodes.forEach(node=>{
      const original=node.nodeValue||"";
      if(!/<\s*\/?\s*(?:a|img|br|p|div|span|strong|em|b|i|ul|ol|li)\b/i.test(original))return;
      const cleaned=cleanEscapedReportMarkupText(original);
      if(cleaned&&cleaned!==original)node.nodeValue=cleaned;
    });
  }

  function installReportMarkupCleaner(){
    const reportGrid=document.getElementById("reportGrid");
    if(!reportGrid)return;
    cleanEscapedReportMarkup(reportGrid);
    const observer=new MutationObserver(mutations=>{
      mutations.forEach(mutation=>{
        if(mutation.type==="characterData"){
          cleanEscapedReportMarkup(mutation.target.parentNode);
          return;
        }
        mutation.addedNodes.forEach(node=>{
          cleanEscapedReportMarkup(node.nodeType===Node.TEXT_NODE?node.parentNode:node);
        });
      });
    });
    observer.observe(reportGrid,{childList:true,subtree:true,characterData:true});
  }

  const currentPage=(location.pathname.split('/').pop()||'index.html').toLowerCase();

  if(nav){
    nav.querySelectorAll('a[href="index.html"]').forEach(link=>{link.textContent='Fishing Locations';});
    nav.querySelectorAll('a[href="report-water.html"]').forEach(link=>{link.textContent='Add or Correct a Location';});
    const submit=nav.querySelector('a[href="submit-report.html"]');
    const priorStateMenu=nav.querySelector('.ffo-state-menu');
    const reusable=new Map();
    stateLinks.forEach(([href])=>{
      const matches=[...nav.querySelectorAll(`a[href="${href}"]`)];
      const keep=matches.find(link=>link.classList.contains('active'))||matches[0]||null;
      matches.forEach(link=>link.remove());
      if(keep)reusable.set(href,keep);
    });
    priorStateMenu?.remove();
    stateMenu=document.createElement('details');
    stateMenu.className="ffo-state-menu";
    const summary=document.createElement('summary');
    summary.textContent='State Locations';
    if(stateLinks.some(([href])=>currentPage===href))summary.classList.add('active');
    const panel=document.createElement('div');
    panel.className="ffo-state-menu-panel";
    panel.setAttribute('aria-label','Fishing locations by state');
    stateLinks.forEach(([href,text])=>{
      const link=reusable.get(href)||document.createElement('a');
      link.href=href;
      link.textContent=text;
      link.classList.toggle('active',currentPage===href);
      if(currentPage===href)link.setAttribute('aria-current','page');
      else link.removeAttribute('aria-current');
      panel.appendChild(link);
    });
    stateMenu.append(summary,panel);
    if(submit)nav.insertBefore(stateMenu,submit);else nav.appendChild(stateMenu);
  }

  if(button&&nav){
    button.innerHTML='<span></span>';
    button.addEventListener('click',()=>{
      const open=nav.classList.toggle('open');
      button.setAttribute('aria-expanded',open?'true':'false');
      button.classList.toggle('open',open);
      if(!open)stateMenu?.removeAttribute('open');
    });
    nav.querySelectorAll('a').forEach(link=>link.addEventListener('click',()=>{
      nav.classList.remove('open');
      button.setAttribute('aria-expanded','false');
      button.classList.remove('open');
      stateMenu?.removeAttribute('open');
    }));
    stateMenu?.addEventListener('keydown',event=>{
      if(event.key!=='Escape')return;
      stateMenu.removeAttribute('open');
      stateMenu.querySelector('summary')?.focus();
    });
    document.addEventListener('click',event=>{
      if(stateMenu?.open&&!stateMenu.contains(event.target))stateMenu.removeAttribute('open');
    });
  }

  const COUNTY_REPORT_STATES={
    'idaho-county-reports.html':'Idaho',
    'montana-county-reports.html':'Montana',
    'utah-county-reports.html':'Utah',
    'colorado-county-reports.html':'Colorado',
    'wyoming-county-reports.html':'Wyoming',
    'nevada-county-reports.html':'Nevada',
    'oregon-county-reports.html':'Oregon',
    'washington-county-reports.html':'Washington',
    'northern-california-county-reports.html':'Northern California'
  };

  const reportPageState=COUNTY_REPORT_STATES[currentPage];
  if(reportPageState){
    document.querySelectorAll('a[href="index.html"]').forEach(link=>{link.textContent='Fishing Locations';});
    document.querySelectorAll('a[href="report-water.html"]').forEach(link=>{link.textContent='Add or Correct a Location';});
    const betaBar=document.querySelector('.ffo-beta-bar');
    const betaText=[...(betaBar?.childNodes||[])].find(node=>node.nodeType===Node.TEXT_NODE);
    if(betaText)betaText.nodeValue='PUBLIC FISHING LOCATION DIRECTORY • DATED REPORTS SHOWN WHEN AVAILABLE • VERIFY ACCESS • ';

    const hero=document.querySelector('.hero');
    const stateName=reportPageState==='Northern California'?'Northern California':reportPageState;
    const heroKicker=hero?.querySelector('.kicker');
    const heroTitle=hero?.querySelector('h1');
    const heroDescription=hero?.querySelector('p');
    if(heroKicker)heroKicker.textContent=`${stateName} fishing location directory`;
    if(heroTitle)heroTitle.textContent='Public fishing locations, county by county.';
    if(heroDescription)heroDescription.textContent=`Search publicly accessible lakes, reservoirs, ponds, rivers, creeks and streams across ${stateName}. Open a location for maps, access details, known species, nearby amenities and an optional dated fishing report.`;
    hero?.querySelectorAll('.top-links a').forEach(link=>{
      if(link.getAttribute('href')==='index.html')link.textContent='← Main location finder';
      if(link.getAttribute('href')==='report-water.html')link.textContent='Add or correct a location';
    });

    const reportOnlyFilter=document.getElementById('currentOnly');
    reportOnlyFilter?.closest('.check')?.remove();
    const waterSearchLabel=document.querySelector('label[for="waterSearch"]');
    if(waterSearchLabel)waterSearchLabel.textContent='Water or species keyword';
    document.querySelectorAll('.ffo-footer-title').forEach(title=>{
      if((title.textContent||'').trim()==='Reports')title.textContent='Locations';
    });
    document.querySelectorAll('.ffo-footer-brand span span').forEach(tagline=>{
      if(/beginner\s+friendly/i.test(tagline.textContent||''))tagline.textContent='Beginner-friendly fishing locations and access information.';
    });

    const reportLinkStyle=document.createElement('style');
    reportLinkStyle.id='ffo-state-report-link-styles';
    reportLinkStyle.textContent=`
      .water-title-link{color:#1f4d3a;text-decoration:none}
      .water-title-link:hover{text-decoration:underline}
      .water-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
      .full-report-link{display:inline-flex;align-items:center;padding:10px 13px;border-radius:11px;background:#1f4d3a;color:#fff!important;text-decoration:none;font-weight:850}
      .full-report-link:hover{filter:brightness(1.08)}
      .water-card .chip.current,.water-card .chip.recent,.water-card .chip.stale,.water-card .chip.none{display:none}
    `;
    if(!document.getElementById(reportLinkStyle.id))document.head.appendChild(reportLinkStyle);

    const countyFromCard=card=>{
      const chip=[...card.querySelectorAll('.chip')]
        .map(node=>(node.textContent||'').trim())
        .find(value=>/^#\d+\s+/.test(value));
      return chip?chip.replace(/^#\d+\s+/,'').replace(/\s+County$/i,'').trim():'';
    };

    const reportHref=(waterName,countyName)=>{
      const queryState=reportPageState==='Northern California'?'California':reportPageState;
      const params=new URLSearchParams({
        q:[waterName,countyName,queryState].filter(Boolean).join(', '),
        open:'1',
        water:waterName,
        state:reportPageState
      });
      if(countyName)params.set('county',countyName);
      return `index.html?${params.toString()}`;
    };

    const enhanceWaterCard=card=>{
      if(!(card instanceof Element))return;
      const heading=card.querySelector('h2');
      if(!heading)return;
      let titleLink=heading.querySelector('a.water-title-link, a[href*="index.html?"]');
      const waterName=(titleLink?.textContent||heading.textContent||'').trim();
      if(!waterName)return;
      const href=reportHref(waterName,countyFromCard(card));
      if(!titleLink){
        titleLink=document.createElement('a');
        titleLink.textContent=waterName;
        heading.replaceChildren(titleLink);
      }
      titleLink.classList.add('water-title-link');
      titleLink.href=href;
      titleLink.title=`Open fishing location details for ${waterName}`;

      let actions=card.querySelector('.water-actions');
      if(!actions){
        actions=document.createElement('div');
        actions.className='water-actions';
        card.appendChild(actions);
      }
      let button=actions.querySelector('.full-report-link');
      if(!button){
        button=document.createElement('a');
        button.className='full-report-link';
        button.textContent='Open location details →';
        actions.appendChild(button);
      }
      button.href=href;

      const datedInfoBox=[...card.querySelectorAll('.details .box')].find(box=>{
        const title=box.querySelector('h3')?.textContent||'';
        return /(latest|recent|report|matched|official information)/i.test(title)&&!/access/i.test(title);
      });
      const datedInfoTitle=datedInfoBox?.querySelector('h3');
      if(datedInfoTitle)datedInfoTitle.textContent='Last dated fishing information (when available)';
      card.querySelectorAll('.muted').forEach(note=>{
        if(/^no (?:recent|current).*?(?:report|update|record)/i.test((note.textContent||'').trim()))note.textContent='Information not currently known. No dated fishing report has been matched to this location.';
      });
    };

    const enhanceAllWaterCards=root=>{
      if(root instanceof Element&&root.matches('.water-card'))enhanceWaterCard(root);
      root.querySelectorAll?.('.water-card').forEach(enhanceWaterCard);
    };
    enhanceAllWaterCards(document);
    new MutationObserver(mutations=>{
      mutations.forEach(mutation=>mutation.addedNodes.forEach(node=>{
        if(node instanceof Element)enhanceAllWaterCards(node);
      }));
    }).observe(document.body,{childList:true,subtree:true});
  }

  if(currentPage==='report-detail.html'){
    const canonical=document.querySelector('link[rel="canonical"]');
    const reportId=(new URLSearchParams(location.search).get('id')||'').trim();
    const baseUrl=new URL('report-detail.html',location.origin).href;
    const exactUrl=new URL(baseUrl);
    if(reportId)exactUrl.searchParams.set('id',reportId);

    const setMeta=(selector,value)=>{
      const meta=document.querySelector(selector);
      if(meta)meta.setAttribute('content',value);
    };

    const syncReportSeo=()=>{
      const missingPanel=document.getElementById('reportMissing');
      const reportArticle=document.getElementById('reportArticle');
      const isMissing=!reportId||Boolean(missingPanel&&!missingPanel.hidden);
      const isReady=Boolean(reportId&&reportArticle&&!reportArticle.hidden);
      const robotsValue=isMissing?'noindex, follow':'index, follow, max-image-preview:large';
      setMeta('meta[name="robots"]',robotsValue);
      setMeta('meta[name="googlebot"]',robotsValue);

      if(isMissing){
        if(canonical)canonical.href=baseUrl;
        setMeta('meta[property="og:url"]',baseUrl);
        return;
      }
      if(!isReady)return;

      const headline=(document.getElementById('reportHeadline')?.textContent||'').trim();
      const water=(document.getElementById('reportWater')?.textContent||'').trim();
      const title=headline&&headline!=='Fishing Report'
        ?`${headline} | Fish Finder Outdoors`
        :`${water||'Dated'} Fishing Report | Fish Finder Outdoors`;
      const description=water
        ?`View the dated fishing report for ${water}, including its source, species, conditions, and available report details. Verify current regulations and access before fishing.`
        :'View this dated Fish Finder Outdoors fishing report, including its source, species, conditions, and available details.';

      document.title=title;
      if(canonical)canonical.href=exactUrl.href;
      setMeta('meta[name="description"]',description);
      setMeta('meta[property="og:title"]',title);
      setMeta('meta[property="og:description"]',description);
      setMeta('meta[property="og:url"]',exactUrl.href);
      setMeta('meta[name="twitter:title"]',title);
      setMeta('meta[name="twitter:description"]',description);
    };

    [document.getElementById('reportMissing'),document.getElementById('reportArticle')]
      .filter(Boolean)
      .forEach(element=>new MutationObserver(syncReportSeo)
        .observe(element,{attributes:true,attributeFilter:['hidden'],childList:true,subtree:true}));
    syncReportSeo();
  }

  if(currentPage!=='index.html')return;

  document.title='Fishing Location Finder & Reports | Fish Finder Outdoors';

  const style=document.createElement('style');
  style.id='ffo-human-first-styles';
  style.textContent=`
    .ffo-human-hidden{display:none!important}
    main.wrap{padding-top:24px}
    .ffo-human-intro{
      margin:0 0 16px;
      padding:22px 24px;
      background:#fffdf8;
      border:1px solid #d8d4c8;
      border-left:6px solid #1F4D3A;
      border-radius:8px;
      box-shadow:none;
    }
    .ffo-human-intro .ffo-byline{
      display:block;
      margin-bottom:7px;
      color:#176354;
      font-size:13px;
      font-weight:800;
    }
    .ffo-human-intro h2{
      max-width:780px;
      margin:0 0 10px;
      color:#14211e;
      font-family:Bitter,Georgia,serif;
      font-size:clamp(30px,5vw,48px);
      line-height:1.08;
      letter-spacing:-.025em;
    }
    .ffo-human-intro p{
      max-width:850px;
      margin:0;
      color:#42514c;
      font-size:17px;
      line-height:1.65;
    }
    #report-search.search-panel{
      border-radius:8px;
      box-shadow:none;
      border-color:#c9c4b8;
    }
    #report-search>.ffo-section-label{background:none;padding:0;border-radius:0;text-transform:none;letter-spacing:0;font-size:13px}
    #report-search .ffo-beta-panel{margin:8px 0 16px;padding:0;border:0;border-radius:0;background:transparent;box-shadow:none}
    #report-search .ffo-beta-panel h2{font-size:clamp(25px,4vw,34px)}
    #report-search .tool-proof-line{margin:0 0 14px;color:#586069;font-size:13px;font-weight:700}
    .ffo-local-examples{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:11px 0 2px}
    .ffo-local-examples span{color:#61706b;font-size:13px;font-weight:700}
    .ffo-local-example{
      padding:7px 10px;
      border:1px solid #b9c5bf;
      border-radius:6px;
      background:#fff;
      color:#0d3c35;
      font-size:13px;
      font-weight:750;
      box-shadow:none;
    }
    .ffo-local-example:hover{transform:none;border-color:#176354;background:#f2f7f4}
    .ffo-outlook-humanized{display:block!important;border-left:6px solid #704484!important;background:#fbf8fc!important}
    .ffo-outlook-humanized .score{display:none!important}
    .ffo-outlook-humanized .score-label{font-size:25px;margin:4px 0 8px}
    .ffo-estimate-disclosure{margin:10px 0 0;padding:12px 14px;border:1px solid #d9cde1;border-radius:8px;background:#fff;color:#4f4057;font-size:14px}
    .ffo-estimate-disclosure strong{color:#3d2d45}
    .ffo-seo-cards{display:none!important}
    .ffo-seo-section{padding:38px 0}
    @media(max-width:600px){
      main.wrap{padding-top:16px}
      .ffo-human-intro{padding:18px}
      .ffo-human-intro p{font-size:16px}
      .ffo-local-examples{align-items:stretch;flex-direction:column}
      .ffo-local-example{width:100%;text-align:left}
    }
  `;
  document.head.appendChild(style);

  [
    document.querySelector('.ffo-beta-bar'),
    document.querySelector('.pwa-install-feature')
  ].forEach(element=>{
    if(element){
      element.classList.add('ffo-human-hidden');
      element.setAttribute('aria-hidden','true');
    }
  });

  const search=document.getElementById('report-search');
  const main=document.querySelector('main.wrap');
  if(search&&main&&!document.querySelector('.ffo-human-intro')){
    const intro=document.createElement('section');
    intro.className='ffo-human-intro';
    intro.innerHTML=`
      <span class="ffo-byline">Fish Finder Outdoors · Powered by Mountain Dog Enterprises</span>
      <h2>Search public fishing locations.</h2>
      <p>Search a water or town below. Each location brings together available public-access evidence, a map, live weather, known fish species, camping, boat launches, day-use areas within five miles, and the last dated fishing report when one exists.</p>
    `;
    main.insertBefore(intro,search);

    const sectionLabel=search.querySelector(':scope > .ffo-section-label');
    if(sectionLabel)sectionLabel.textContent='Nine-state public fishing location directory';

    const panel=search.querySelector('.ffo-beta-panel');
    if(panel){
      panel.innerHTML='<h2>Find a fishing water.</h2><p>Enter a lake, river, reservoir, pond, town, or coordinates. Start with the place you are actually considering—not a broad fishing question.</p>';
    }

    const proof=search.querySelector('.tool-proof-line');
    if(proof)proof.textContent='15,501 official access records • Maps & weather • Five-mile facilities • Optional dated reports';

    const hint=search.querySelector('.hint');
    if(hint)hint.textContent='Town searches look roughly 50 miles. Always open the official source and verify current access, regulations, emergency changes, and posted signs before traveling.';

    const form=document.getElementById('searchForm');
    const input=document.getElementById('locationInput');
    if(form&&input){
      const examples=document.createElement('div');
      examples.className='ffo-local-examples';
      examples.innerHTML=`
        <span>Try a featured fishing water:</span>
        <button class="ffo-local-example" type="button" data-water="American Falls Reservoir">American Falls Reservoir</button>
        <button class="ffo-local-example" type="button" data-water="Edson Fichter Pond">Edson Fichter Pond</button>
        <button class="ffo-local-example" type="button" data-water="Blackfoot Reservoir">Blackfoot Reservoir</button>
      `;
      form.insertAdjacentElement('afterend',examples);
      examples.querySelectorAll('[data-water]').forEach(example=>{
        example.addEventListener('click',()=>{
          input.value=example.getAttribute('data-water')||'';
          if(typeof form.requestSubmit==='function')form.requestSubmit();
          else form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
        });
      });
    }
  }

  document.querySelectorAll('.data-pill').forEach(pill=>{
    if(pill.textContent.includes('Conditions estimate')){
      const dot=pill.querySelector('.dot');
      pill.replaceChildren();
      if(dot)pill.appendChild(dot);
      pill.appendChild(document.createTextNode(' Weather-based planning information'));
    }
  });

  const seo=document.querySelector('.ffo-seo-section');
  if(seo){
    const label=seo.querySelector('.ffo-section-label');
    const heading=seo.querySelector('h2');
    const paragraphs=seo.querySelectorAll(':scope .ffo-seo-inner > div:first-child p');
    if(label)label.textContent='How the search works';
    if(heading)heading.textContent='What the location finder checks.';
    if(paragraphs[0])paragraphs[0].textContent='The finder checks managed-water records, official state directories, available maps, live weather, known species records, and nearby recreation facilities. A dated fishing report is shown only when one exists.';
    if(paragraphs[1])paragraphs[1].textContent='Unknown details are labeled, and every location can be corrected or added to as better public information becomes available.';
  }

  const humanizeOutlook=()=>{
    const card=document.querySelector('#reportGrid .score-card');
    if(!card||card.dataset.humanized==='true')return;
    card.dataset.humanized='true';
    card.classList.add('ffo-outlook-humanized');

    const eyebrow=card.querySelector('.eyebrow');
    if(eyebrow)eyebrow.textContent='Weather-based planning note — not a fishing report';

    const label=card.querySelector('.score-label');
    if(label){
      const original=label.textContent.trim();
      label.textContent=original?`${original} conditions`:'Conditions estimate';
    }

    const disclosure=document.createElement('div');
    disclosure.className='ffo-estimate-disclosure';
    disclosure.innerHTML='<strong>What this means:</strong> This note is calculated from available weather, nearby measurements, and general fishing patterns. It does not know whether fish are biting, and the old 0–100 score has been removed to avoid false precision.';
    const confidence=card.querySelector('.meta');
    if(confidence)confidence.insertAdjacentElement('afterend',disclosure);
    else card.appendChild(disclosure);
  };

  const refreshReportPresentation=()=>humanizeOutlook();

  const reportGrid=document.getElementById('reportGrid');
  if(reportGrid){
    new MutationObserver(refreshReportPresentation).observe(reportGrid,{childList:true,subtree:true});
    refreshReportPresentation();
  }


  /* Put search feedback, matching waters, and the selected report directly under the search bar. */
  const organizePrimarySearchFlow=()=>{
    const panel=document.getElementById('report-search');
    const form=document.getElementById('searchForm');
    const statusBox=document.getElementById('status');
    const resultBox=document.getElementById('results');
    const reportSection=document.getElementById('report');
    if(!panel||!form||!statusBox||!resultBox||!reportSection)return;

    form.insertAdjacentElement('afterend',statusBox);
    statusBox.insertAdjacentElement('afterend',resultBox);
    resultBox.insertAdjacentElement('afterend',reportSection);

    panel.classList.add('ffo-results-first-layout');
    reportSection.classList.add('ffo-inline-report');
  };

  const resultsFirstStyle=document.createElement('style');
  resultsFirstStyle.id='ffo-results-first-styles';
  resultsFirstStyle.textContent=`
    #report-search.ffo-results-first-layout #status{
      margin:12px 0 0;
      scroll-margin-top:12px;
    }
    #report-search.ffo-results-first-layout #results{
      margin:10px 0 0;
      scroll-margin-top:12px;
    }
    #report-search.ffo-results-first-layout #results:not(:empty){
      padding:12px;
      border:2px solid #176354;
      border-radius:12px;
      background:#f7fbf8;
    }
    #report-search.ffo-results-first-layout #results .result{
      margin:0 0 8px;
      border:2px solid #c8d8d0;
      border-radius:10px;
      background:#fff;
    }
    #report-search.ffo-results-first-layout #results .result:last-of-type{margin-bottom:0}
    #report-search.ffo-results-first-layout #results .result:hover,
    #report-search.ffo-results-first-layout #results .result:focus{
      border-color:#176354;
      background:#f2f8f5;
      transform:none;
    }
    #report-search.ffo-results-first-layout > #report.ffo-inline-report{
      margin:12px 0 0;
      padding:14px 0 8px;
      border-top:3px solid #0d3c35;
      scroll-margin-top:12px;
    }
    #report-search.ffo-results-first-layout > #report.ffo-inline-report.hidden{
      display:none!important;
    }
    #report-search.ffo-results-first-layout > .hint{
      margin-top:16px;
    }
    .ffo-results-reset{display:none}
    body.ffo-focused-results .ffo-beta-bar,
    body.ffo-focused-results .ffo-professional-hero,
    body.ffo-focused-results .ffo-trust-strip,
    body.ffo-focused-results .ffo-human-intro,
    body.ffo-focused-results main.wrap > .pwa-install-feature,
    body.ffo-focused-results main.wrap > .saved-panel,
    body.ffo-focused-results #beta-search-guide{
      display:none!important;
    }
    body.ffo-focused-results main.wrap{padding-top:14px}
    body.ffo-focused-results #report-search{
      margin-top:0;
      padding:16px;
      border-radius:12px;
      box-shadow:none;
    }
    body.ffo-focused-results #report-search > .ffo-section-label,
    body.ffo-focused-results #report-search > .ffo-beta-panel,
    body.ffo-focused-results #report-search > .tool-proof-line,
    body.ffo-focused-results #report-search > .ffo-local-examples,
    body.ffo-focused-results #report-search > .hint,
    body.ffo-focused-results #report-search > .nearby-quick-card,
    body.ffo-focused-results #report-search > .search-help,
    body.ffo-focused-results #report-search > .ffo-coverage-note,
    body.ffo-focused-results #report-search > .regional-coverage,
    body.ffo-focused-results #report-search > .legend,
    body.ffo-focused-results #report-search #nearMe,
    body.ffo-focused-results #report .report-actions button:not(#shareWater):not(#favoriteLocation){
      display:none!important;
    }
    body.ffo-focused-results #reportNextActions{display:flex!important}
    body.ffo-focused-results #reportNextActions #installFromReport{display:none!important}
    body.ffo-focused-results #report-search .search-row{
      grid-template-columns:minmax(0,1fr) auto auto;
    }
    body.ffo-focused-results .ffo-results-reset{
      display:inline-flex;
      align-items:center;
      justify-content:center;
    }
    body.ffo-focused-results #report{
      padding-bottom:18px;
    }
    @media(max-width:760px){
      #report-search.ffo-results-first-layout #results:not(:empty){padding:9px}
      #report-search.ffo-results-first-layout #results .result{padding:14px 12px}
      #report-search.ffo-results-first-layout > #report.ffo-inline-report{padding-top:10px}
      body.ffo-focused-results #report-search{padding:12px}
      body.ffo-focused-results #report-search .search-row{grid-template-columns:1fr}
    }
  `;
  document.head.appendChild(resultsFirstStyle);

  /* Shared visual layer for the professional FFO redesign. */
  if(!document.querySelector('link[data-ffo-professional-font]')){
    const fontLink=document.createElement('link');
    fontLink.rel='stylesheet';
    fontLink.href='https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&display=swap';
    fontLink.dataset.ffoProfessionalFont='';
    document.head.appendChild(fontLink);
  }

  const professionalTheme=document.createElement('style');
  professionalTheme.id='ffo-professional-theme-20260814';
  professionalTheme.textContent=`
    :root{
      --ffo-night:#052d27;
      --ffo-forest:#0b4437;
      --ffo-green:#17614e;
      --ffo-gold:#d6a92e;
      --ffo-paper:#f0ead2;
      --ffo-paper-light:#faf6e7;
      --ffo-ink:#17332c;
      --ffo-muted:#607067;
      --ffo-line:rgba(7,52,43,.20);
      --ffo-shadow:0 18px 46px rgba(4,39,32,.10);
    }
    html{scroll-padding-top:92px}
    body{
      background:var(--ffo-paper);
      color:var(--ffo-ink);
      font-family:Inter,Arial,sans-serif;
      line-height:1.62;
    }
    h1,h2,h3,h4,
    .ffo-wordmark,
    .ffo-nav,
    .ffo-kicker,
    .ffo-section-label,
    button,
    .primary,
    .secondary,
    .ffo-hero-primary,
    .ffo-hero-secondary,
    .ffo-footer-title{
      font-family:Oswald,"Arial Narrow",Arial,sans-serif;
    }
    a:focus-visible,button:focus-visible,input:focus-visible,summary:focus-visible{
      outline:3px solid var(--ffo-gold);
      outline-offset:3px;
    }
    .ffo-site-header{
      min-height:78px;
      border:0;
      border-bottom:1px solid rgba(214,169,46,.34);
      background:var(--ffo-night);
      box-shadow:0 8px 24px rgba(0,25,20,.15);
    }
    .ffo-header-inner{min-height:78px;max-width:1220px}
    .ffo-site-header .ffo-logo-link{
      color:#faf6e7!important;
    }
    .ffo-logo-link img{
      width:52px;
      height:52px;
      padding:2px;
      border:1px solid rgba(214,169,46,.58);
      border-radius:50%;
      background:#b7aa83;
      object-fit:contain;
    }
    .ffo-site-header .ffo-wordmark strong{
      color:#faf6e7!important;
      font-size:1.32rem;
      font-weight:650;
      letter-spacing:.045em;
      line-height:1;
      text-transform:uppercase;
    }
    .ffo-site-header .ffo-wordmark > span{
      color:#d6a92e!important;
      font-size:.71rem;
      font-weight:700;
      letter-spacing:.16em;
      text-transform:uppercase;
    }
    .ffo-nav{gap:4px}
    .ffo-site-header .ffo-nav a,
    .ffo-site-header .ffo-state-menu summary{
      padding:10px 11px;
      border:0;
      border-bottom:2px solid transparent;
      border-radius:0;
      color:rgba(255,253,243,.92)!important;
      font-size:.78rem;
      font-weight:600;
      letter-spacing:.045em;
      text-transform:uppercase;
    }
    .ffo-site-header .ffo-nav a:hover,
    .ffo-site-header .ffo-nav a.active,
    .ffo-site-header .ffo-state-menu summary:hover{
      border-bottom-color:var(--ffo-gold);
      background:transparent;
      color:#d6a92e!important;
    }
    .ffo-site-header .ffo-nav .ffo-nav-cta{
      border:1px solid var(--ffo-gold);
      background:var(--ffo-gold);
      color:#052d27!important;
    }
    .ffo-site-header .ffo-menu-button{
      width:48px;
      height:48px;
      border:1px solid rgba(214,169,46,.52);
      border-radius:2px;
      color:#faf6e7!important;
      background:transparent;
    }
    .ffo-menu-button span,
    .ffo-menu-button span::before,
    .ffo-menu-button span::after{background:var(--ffo-paper-light)}
    .ffo-beta-bar{
      min-height:44px;
      padding:8px 16px;
      border:0;
      background:var(--ffo-gold);
      color:var(--ffo-night);
      font-family:Oswald,"Arial Narrow",Arial,sans-serif;
      font-size:.78rem;
      font-weight:650;
      letter-spacing:.06em;
      text-transform:uppercase;
    }
    .ffo-beta-bar a{color:var(--ffo-night);font-weight:700;text-decoration:underline}
    .ffo-install-button{
      border:1px solid var(--ffo-night);
      border-radius:2px;
      background:var(--ffo-night);
      color:var(--ffo-paper-light);
    }
    .ffo-professional-hero{
      position:relative;
      overflow:hidden;
      padding:clamp(70px,9vw,118px) 20px;
      border:0;
      border-bottom:8px solid var(--ffo-gold);
      background:
        linear-gradient(90deg,rgba(2,30,25,.96) 0%,rgba(2,30,25,.80) 48%,rgba(2,30,25,.30) 82%),
        url("ffo-hero.jpg") center/cover no-repeat;
      color:var(--ffo-paper-light);
    }
    .ffo-professional-hero::after{
      content:"";
      position:absolute;
      inset:0;
      pointer-events:none;
      background:linear-gradient(0deg,rgba(2,30,25,.3),transparent 50%);
    }
    .ffo-hero-grid{
      position:relative;
      z-index:1;
      max-width:1180px;
      grid-template-columns:minmax(0,1fr) minmax(190px,300px);
      gap:50px;
    }
    .ffo-kicker{
      display:inline-flex;
      margin:0 0 20px;
      padding:0 0 12px;
      border:0;
      border-bottom:3px solid var(--ffo-gold);
      border-radius:0;
      background:transparent;
      color:var(--ffo-gold);
      font-size:.9rem;
      font-weight:650;
      letter-spacing:.13em;
      text-transform:uppercase;
    }
    .ffo-kicker img{display:none}
    .ffo-professional-hero h1{
      max-width:780px;
      margin:0 0 24px;
      color:var(--ffo-paper-light);
      font-family:Oswald,"Arial Narrow",Arial,sans-serif;
      font-size:clamp(4rem,8vw,7rem);
      font-weight:650;
      letter-spacing:-.025em;
      line-height:.89;
      text-transform:uppercase;
      text-shadow:0 7px 28px rgba(0,0,0,.28);
    }
    .ffo-professional-hero p{
      max-width:720px;
      color:rgba(255,253,243,.88);
      font-size:clamp(1rem,2vw,1.18rem);
      line-height:1.62;
    }
    .ffo-hero-logo{
      width:min(100%,270px);
      padding:4px;
      border:1px solid rgba(214,169,46,.48);
      border-radius:50%;
      background:#b7aa83;
      box-shadow:0 20px 48px rgba(0,0,0,.25);
    }
    .ffo-hero-actions{gap:10px;margin-top:26px}
    .ffo-hero-primary,.ffo-hero-secondary{
      min-height:48px;
      padding:12px 18px;
      border:2px solid var(--ffo-gold);
      border-radius:2px;
      font-weight:650;
      letter-spacing:.055em;
      text-transform:uppercase;
    }
    .ffo-hero-primary{background:var(--ffo-gold);color:var(--ffo-night)}
    .ffo-hero-secondary{background:transparent;color:var(--ffo-paper-light)}
    .ffo-trust-strip{
      padding:0;
      border:0;
      background:var(--ffo-forest);
      color:var(--ffo-paper-light);
    }
    .ffo-trust-inner{
      max-width:1180px;
      gap:0;
      padding:0 20px;
    }
    .ffo-trust-item{
      min-height:126px;
      padding:28px 24px;
      border:0;
      border-right:1px solid rgba(255,253,243,.17);
      border-radius:0;
      background:transparent;
    }
    .ffo-trust-item:last-child{border-right:0}
    .ffo-trust-item strong{
      color:var(--ffo-paper-light);
      font-family:Oswald,"Arial Narrow",Arial,sans-serif;
      font-size:1.18rem;
      letter-spacing:.045em;
      text-transform:uppercase;
    }
    .ffo-trust-item span{color:rgba(255,253,243,.68)}
    main.wrap{max-width:1180px;padding-top:clamp(42px,7vw,78px);padding-bottom:40px}
    body.ffo-finder-home main.wrap{display:flex;flex-direction:column}
    body.ffo-finder-home #report-search{order:1}
    body.ffo-finder-home .pwa-install-feature{order:2}
    body.ffo-finder-home .saved-panel{order:3}
    .search-panel,
    .pwa-install-feature,
    .saved-panel,
    .report,
    .ffo-detail-article,
    .ffo-detail-status{
      border:1px solid var(--ffo-line);
      border-radius:2px;
      background:var(--ffo-paper-light);
      box-shadow:none;
    }
    .search-panel{
      padding:clamp(24px,5vw,50px);
      border-top:8px solid var(--ffo-gold);
    }
    .ffo-section-label{
      color:var(--ffo-green);
      font-weight:650;
      letter-spacing:.12em;
      text-transform:uppercase;
    }
    .ffo-beta-panel{padding:0;border:0;background:transparent}
    .ffo-beta-panel h2{
      margin:8px 0 12px;
      color:var(--ffo-ink);
      font-family:Oswald,"Arial Narrow",Arial,sans-serif;
      font-size:clamp(2.8rem,6vw,5rem);
      font-weight:650;
      letter-spacing:-.015em;
      line-height:.94;
      text-transform:uppercase;
    }
    .ffo-beta-panel p{max-width:860px;color:var(--ffo-muted)}
    .tool-proof-line{
      margin:22px 0 16px;
      padding:12px 14px;
      border:0;
      border-left:5px solid var(--ffo-gold);
      border-radius:0;
      background:var(--ffo-paper);
      color:var(--ffo-ink);
      font-weight:750;
    }
    .search-row{
      gap:0;
      margin:18px 0 14px;
      border:2px solid var(--ffo-night);
      background:var(--ffo-night);
    }
    .search-row input{
      min-height:58px;
      border:0;
      border-radius:0;
      background:var(--ffo-paper-light);
      color:var(--ffo-ink);
      font-size:1rem;
    }
    .search-row button,
    button.primary,
    button.secondary,
    a.primary,
    a.secondary{
      min-height:46px;
      border-radius:2px;
      font-weight:650;
      letter-spacing:.04em;
    }
    .search-row button{border-radius:0}
    .search-row .primary,
    button.primary,
    a.primary{
      border-color:var(--ffo-gold);
      background:var(--ffo-gold);
      color:var(--ffo-night);
    }
    .search-row .secondary,
    button.secondary,
    a.secondary{
      border-color:var(--ffo-night);
      background:var(--ffo-night);
      color:var(--ffo-paper-light);
    }
    .search-row button:hover,
    button.primary:hover,
    a.primary:hover{filter:brightness(1.06)}
    .hint,.meta{color:var(--ffo-muted)}
    .nearby-quick-card{
      border:1px solid var(--ffo-line);
      border-radius:2px;
      background:var(--ffo-paper);
      box-shadow:none;
    }
    .nearby-quick-heading h3{
      color:var(--ffo-green);
      font-family:Oswald,"Arial Narrow",Arial,sans-serif;
      font-size:clamp(1.8rem,4vw,2.8rem);
      text-transform:uppercase;
    }
    .nearby-quick-status,
    .search-help,
    .ffo-coverage-note,
    .regional-coverage{
      border-radius:2px;
      box-shadow:none;
    }
    .regional-coverage{
      border:1px solid var(--ffo-line);
      background:var(--ffo-forest);
      color:var(--ffo-paper-light);
    }
    .regional-coverage > strong{color:var(--ffo-gold)}
    .state-chip,.data-pill{
      border:1px solid var(--ffo-line);
      border-radius:2px;
      background:var(--ffo-paper-light);
      color:var(--ffo-ink);
    }
    .state-expansion-request{color:rgba(255,253,243,.74)}
    .state-expansion-request a{color:var(--ffo-gold)}
    .pwa-install-feature{
      margin-top:26px;
      padding:24px;
      border-left:8px solid var(--ffo-green);
    }
    .pwa-install-feature h2,
    .saved-panel h2,
    .report h2{
      color:var(--ffo-ink);
      font-family:Oswald,"Arial Narrow",Arial,sans-serif;
      font-size:clamp(2rem,4vw,3rem);
      text-transform:uppercase;
    }
    .pwa-install-icon img{border-radius:2px}
    .saved-panel{margin-top:26px;padding:28px}
    .saved-group{
      border:1px solid var(--ffo-line);
      border-radius:2px;
      background:var(--ffo-paper);
    }
    .saved-chip{
      border-radius:2px;
      background:var(--ffo-paper-light);
    }
    #report-search.ffo-results-first-layout #results:not(:empty){
      border:2px solid var(--ffo-green);
      border-radius:2px;
      background:var(--ffo-paper);
    }
    #report-search.ffo-results-first-layout #results .result,
    .result{
      border:1px solid var(--ffo-line);
      border-left:6px solid var(--ffo-green);
      border-radius:2px;
      background:var(--ffo-paper-light);
      box-shadow:none;
    }
    .result h3,.result strong{color:var(--ffo-ink)}
    .result-badge,.chip,.badge,.species-tag,.catch-pill,.access-point-pill{
      border-radius:2px;
    }
    .report{
      border-top:8px solid var(--ffo-gold);
      background:var(--ffo-paper-light);
    }
    .report-next-actions{
      border-radius:2px;
      background:var(--ffo-night);
      color:var(--ffo-paper-light);
    }
    .report-next-actions h3{color:var(--ffo-paper-light)}
    .report-next-buttons a,.report-next-buttons button{
      border-radius:2px;
      background:var(--ffo-gold);
      color:var(--ffo-night);
    }
    .card,.metric,.official-record,.ffo-agency-panel,.access-point-item{
      border-color:var(--ffo-line);
      border-radius:2px;
      background:var(--ffo-paper-light);
      box-shadow:none;
    }
    .card h3,.card h4{
      color:var(--ffo-green);
      font-family:Oswald,"Arial Narrow",Arial,sans-serif;
      letter-spacing:.02em;
      text-transform:uppercase;
    }
    .ffo-seo-section{
      padding:clamp(54px,8vw,90px) 20px;
      background:var(--ffo-forest);
      color:var(--ffo-paper-light);
    }
    .ffo-seo-inner{max-width:1180px}
    .ffo-seo-section h2{
      color:var(--ffo-paper-light);
      font-family:Oswald,"Arial Narrow",Arial,sans-serif;
      font-size:clamp(2.8rem,6vw,5rem);
      line-height:.95;
      text-transform:uppercase;
    }
    .ffo-seo-section p{color:rgba(255,253,243,.75)}
    .ffo-seo-cards article,
    .ffo-faq details{
      border:1px solid rgba(255,253,243,.18);
      border-radius:2px;
      background:rgba(255,255,255,.055);
    }
    .ffo-seo-cards h3,.ffo-faq h2,.ffo-faq summary{color:var(--ffo-paper-light)}
    .ffo-faq details p{color:rgba(255,253,243,.75)}
    .ffo-site-footer{
      border:0;
      border-top:8px solid var(--ffo-gold);
      background:var(--ffo-night);
    }
    .ffo-footer-grid,.ffo-footer-fine{max-width:1180px}
    .ffo-footer-brand img{
      padding:3px;
      border:1px solid rgba(214,169,46,.5);
      border-radius:50%;
      background:#b7aa83;
    }
    .ffo-footer-brand strong,.ffo-footer-title{
      color:var(--ffo-paper-light);
      letter-spacing:.04em;
      text-transform:uppercase;
    }
    .ffo-footer-title{color:var(--ffo-gold)}
    .ffo-footer-links a{color:rgba(255,253,243,.72)}
    .ffo-footer-links a:hover{color:var(--ffo-gold)}
    .ffo-detail-wrap{max-width:1080px}
    .ffo-detail-article{border-top:8px solid var(--ffo-gold)}
    .ffo-detail-head h1{
      color:var(--ffo-ink);
      font-family:Oswald,"Arial Narrow",Arial,sans-serif;
      font-size:clamp(2.8rem,7vw,5.6rem);
      line-height:.94;
      text-transform:uppercase;
    }
    .ffo-detail-card,.ffo-detail-summary{
      border-color:var(--ffo-line);
      border-radius:2px;
      background:var(--ffo-paper);
    }
    body.ffo-focused-results main.wrap{padding-top:14px}
    body.ffo-focused-results #report-search{
      border-top-color:var(--ffo-gold);
      background:var(--ffo-paper-light);
    }
    @media(max-width:940px){
      .ffo-site-header,.ffo-header-inner{min-height:68px}
      .ffo-nav{
        border-bottom:6px solid var(--ffo-gold);
        background:var(--ffo-night);
        box-shadow:0 18px 30px rgba(0,20,16,.24);
      }
      .ffo-site-header .ffo-nav a,
      .ffo-site-header .ffo-state-menu summary{color:#faf6e7!important}
      .ffo-state-menu-panel{border-radius:2px;background:var(--ffo-night)}
      .ffo-hero-grid{grid-template-columns:minmax(0,1fr) 190px;gap:26px}
      .ffo-trust-inner{grid-template-columns:repeat(2,1fr)}
      .ffo-trust-item{border-bottom:1px solid rgba(255,253,243,.17)}
      .ffo-trust-item:nth-child(2){border-right:0}
    }
    @media(max-width:720px){
      .ffo-professional-hero{
        min-height:560px;
        padding:58px 18px;
        background:
          linear-gradient(90deg,rgba(2,30,25,.95),rgba(2,30,25,.63)),
          url("ffo-hero.jpg") center/cover no-repeat;
      }
      .ffo-hero-grid{display:block}
      .ffo-professional-hero h1{font-size:clamp(3.4rem,16vw,5rem)}
      .ffo-hero-logo{display:none}
      .ffo-hero-actions{align-items:stretch;flex-direction:column}
      .ffo-hero-actions a,.ffo-hero-actions button{width:100%;text-align:center}
      .ffo-trust-inner{grid-template-columns:1fr;padding:0}
      .ffo-trust-item{
        min-height:0;
        padding:22px 20px;
        border-right:0;
        border-bottom:1px solid rgba(255,253,243,.17);
      }
      main.wrap{padding-top:34px}
      .search-panel{padding:24px 18px}
      .search-row{display:grid;grid-template-columns:1fr!important;border:0;background:transparent}
      .search-row input{border:2px solid var(--ffo-night)}
      .search-row button{border:0;margin-top:7px}
      .nearby-quick-heading{align-items:stretch;flex-direction:column}
      .pwa-install-feature{display:grid;grid-template-columns:auto 1fr}
      .pwa-install-feature .pwa-install-primary{grid-column:1/-1;width:100%}
      .saved-head{align-items:stretch;flex-direction:column}
      .ffo-seo-cards{grid-template-columns:1fr}
    }
    @media(max-width:440px){
      .ffo-logo-link img{width:44px;height:44px}
      .ffo-wordmark strong{font-size:1.08rem}
      .ffo-beta-bar{font-size:.7rem}
      .ffo-professional-hero h1{font-size:clamp(3.2rem,15vw,4.1rem)}
      .ffo-professional-hero p{font-size:.94rem}
      .ffo-beta-panel h2{font-size:2.75rem}
      .pwa-install-feature{grid-template-columns:1fr;text-align:left}
    }
    @media(prefers-reduced-motion:reduce){
      *,*::before,*::after{
        scroll-behavior:auto!important;
        animation-duration:.01ms!important;
        animation-iteration-count:1!important;
        transition-duration:.01ms!important;
      }
    }
  `;
  document.head.appendChild(professionalTheme);

  organizePrimarySearchFlow();

  /* Keep the full landing page intact until search feedback or a report exists. */
  const installFocusedResultsMode=()=>{
    const form=document.getElementById('searchForm');
    const input=document.getElementById('locationInput');
    const statusBox=document.getElementById('status');
    const resultBox=document.getElementById('results');
    const reportSection=document.getElementById('report');
    const reportGrid=document.getElementById('reportGrid');
    if(!form||!input||!statusBox||!resultBox||!reportSection)return;

    let resetButton=document.getElementById('ffoResultsReset');
    if(!resetButton){
      resetButton=document.createElement('button');
      resetButton.id='ffoResultsReset';
      resetButton.className='secondary ffo-results-reset';
      resetButton.type='button';
      resetButton.textContent='Start a new search';
      form.appendChild(resetButton);
    }

    const hasActiveStatus=()=>
      !statusBox.classList.contains('hidden')&&Boolean(statusBox.textContent.trim());
    const syncMode=()=>{
      const active=hasActiveStatus()||resultBox.childElementCount>0||
        !reportSection.classList.contains('hidden');
      document.body.classList.toggle('ffo-focused-results',active);
    };

    const observer=new MutationObserver(syncMode);
    observer.observe(statusBox,{attributes:true,childList:true,subtree:true});
    observer.observe(resultBox,{childList:true,subtree:true});
    observer.observe(reportSection,{attributes:true,attributeFilter:['class']});

    resetButton.addEventListener('click',()=>{
      statusBox.className='status hidden';
      statusBox.replaceChildren();
      resultBox.replaceChildren();
      reportGrid?.replaceChildren();
      reportSection.classList.add('hidden');
      input.value='';
      history.replaceState(null,'',location.pathname);
      document.body.classList.remove('ffo-focused-results');
      input.focus();
      document.getElementById('report-search')?.scrollIntoView({behavior:'smooth',block:'start'});
    });

    syncMode();
  };

  installFocusedResultsMode();
  installReportMarkupCleaner();
})();
