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

  const STATE_RULES={
    Idaho:{
      agency:'Idaho Fish and Game',
      rules:'https://idfg.idaho.gov/rules/fish'
    },
    Montana:{
      agency:'Montana Fish, Wildlife & Parks',
      rules:'https://fwp.mt.gov/fish/regulations'
    },
    Wyoming:{
      agency:'Wyoming Game and Fish Department',
      rules:'https://wgfd.wyo.gov/Regulations/Fish/Fishing-Regulation'
    },
    Utah:{
      agency:'Utah Division of Wildlife Resources',
      rules:'https://wildlife.utah.gov/guidebooks?sec=03',
      emergency:'https://wildlife.utah.gov/guidebooks?sec=03'
    },
    Nevada:{
      agency:'Nevada Department of Wildlife',
      rules:'https://www.ndow.org/rules-regulations/'
    },
    Oregon:{
      agency:'Oregon Department of Fish & Wildlife',
      rules:'https://myodfw.com/fishing/regulations',
      emergency:'https://myodfw.com/articles/regulation-updates'
    },
    Washington:{
      agency:'Washington Department of Fish & Wildlife',
      rules:'https://wdfw.wa.gov/fishing/regulations',
      emergency:'https://wdfw.wa.gov/fishing/regulations/emergency-rules'
    },
    California:{
      agency:'California Department of Fish and Wildlife',
      rules:'https://wildlife.ca.gov/Regulations/Fishing',
      emergency:'https://wildlife.ca.gov/Fishing/Inland/Low-Flow'
    },
    'Northern California':{
      agency:'California Department of Fish and Wildlife',
      rules:'https://wildlife.ca.gov/Regulations/Fishing',
      emergency:'https://wildlife.ca.gov/Fishing/Inland/Low-Flow'
    },
    Colorado:{
      agency:'Colorado Parks and Wildlife',
      rules:'https://cpw.state.co.us/rules-and-regulations'
    }
  };

  /*
   * These records are restrictions verified from an official water-specific
   * agency page or current emergency-rule notice. They do not create bait
   * recommendations. They only make known restrictions visible.
   */
  const VERIFIED_METHOD_RULES={
    'idaho|daniels reservoir':{
      status:'restricted',
      summary:'No bait allowed. Barbless hooks are required.',
      source:'https://idfg.idaho.gov/ifwis/fishingplanner/water/1124478423573',
      reviewed:'2026-08-02'
    },
    'idaho|treasureton reservoir':{
      status:'restricted',
      summary:'No bait allowed. Barbless hooks are required.',
      source:'https://idfg.idaho.gov/ifwis/fishingplanner/water/1118537422370',
      reviewed:'2026-08-02'
    },
    'utah|minersville reservoir':{
      status:'restricted',
      summary:'Bait is not allowed during the current emergency-rule period. Verify the effective dates before fishing.',
      source:'https://wildlife.utah.gov/news/2026/07/02/dwr-increases-daily-fishing-limits-at-pineview-reservoir-and-other-waterbodies-due-to-low-water-levels',
      reviewed:'2026-08-02'
    },
    'nevada|tonkin reservoir':{
      status:'restricted',
      summary:'Artificial lures only.',
      source:'https://www.ndow.org/waters/tonkin-reservoir/',
      reviewed:'2026-08-02'
    },
    'wyoming|gray reef':{
      status:'restricted',
      summary:'Artificial flies and lures only in the regulated section; single-point barbless hooks are required. Confirm the exact section before fishing.',
      source:'https://wgfd.wyo.gov/news-events/fishing-regulation-changes-taking-effect-2026',
      reviewed:'2026-08-02'
    }
  };

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
    document.title=`${reportPageState} Fishing Locations | Fish Finder Outdoors`;
    const descriptionMeta=document.querySelector('meta[name="description"]');
    if(descriptionMeta)descriptionMeta.content=`Search publicly accessible fishing locations, maps, facilities, known species and optional dated reports across ${reportPageState}.`;

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
      if(/beginner\s+friendly/i.test(tagline.textContent||''))tagline.textContent='Western fishing locations and access information.';
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

  if(currentPage!=='index.html')return;

  document.title='Fishing Location Finder | Fish Finder Outdoors';

  /*
   * Safety gate: the original function generated bait/lure ideas from species,
   * water type and weather. That is not enough to establish legality. Returning
   * no guides prevents the screen, copied report and shared report text from
   * recommending a method until a water-specific legal record exists.
   */
  const safeBuildBaitSuggestions=()=>({
    guides:[],
    adjustment:'No bait, lure, fly, hook or presentation recommendation is shown until current water-specific rules are verified from the responsible state agency.',
    based_on:'verified water-specific legal-method rules only'
  });
  try{
    if(typeof buildBaitSuggestions==='function')buildBaitSuggestions=safeBuildBaitSuggestions;
  }catch(error){
    console.warn('FFO legal-method safety gate could not replace the legacy suggestion function.',error);
  }

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
    .ffo-human-intro h1{
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
    .ffo-human-safety{
      margin-top:12px!important;
      padding-top:12px;
      border-top:1px solid #d8d4c8;
      font-size:15px!important;
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
    .bait-card.ffo-legal-method-card{
      border:2px solid #a85c33;
      background:#fff9f3;
    }
    .ffo-method-status{
      display:inline-flex;
      margin:0 0 10px;
      padding:5px 9px;
      border-radius:999px;
      background:#f6e5d8;
      color:#7b391e;
      font-size:11px;
      font-weight:900;
      letter-spacing:.04em;
      text-transform:uppercase;
    }
    .ffo-method-status.verified{
      background:#f2dfd6;
      color:#7f2f20;
    }
    .ffo-legal-method-card h3{font-family:Bitter,Georgia,serif;font-size:clamp(24px,4vw,32px);margin:0 0 8px}
    .ffo-legal-method-card p{max-width:900px}
    .ffo-legal-rule{
      margin:14px 0;
      padding:14px 16px;
      border-left:5px solid #a53a2f;
      border-radius:8px;
      background:#fff;
      color:#4c2c23;
    }
    .ffo-legal-rule strong{display:block;margin-bottom:4px}
    .ffo-rule-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
    .ffo-rule-actions a{
      display:inline-flex;
      padding:10px 12px;
      border:1px solid #b7aaa0;
      border-radius:8px;
      background:#fff;
      color:#0d3c35;
      font-size:13px;
      font-weight:850;
      text-decoration:none;
    }
    .ffo-rule-actions a:hover{border-color:#176354}
    .ffo-rule-warning{margin-top:12px;color:#6b5549;font-size:13px}
    .ffo-seo-cards{display:none!important}
    .ffo-seo-section{padding:38px 0}
    @media(max-width:600px){
      main.wrap{padding-top:16px}
      .ffo-human-intro{padding:18px}
      .ffo-human-intro p{font-size:16px}
      .ffo-local-examples{align-items:stretch;flex-direction:column}
      .ffo-local-example{width:100%;text-align:left}
      .ffo-rule-actions{display:grid}
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
      <h1>Fishing Location Finder</h1>
      <p>Search a water or town below. Each location brings together available public-access evidence, a map, live weather, known fish species, camping, boat launches, day-use areas within five miles, and the last dated fishing report when one exists.</p>
      <p class="ffo-human-safety"><strong>Legal-method rule:</strong> FFO will not recommend bait, lures, flies, hooks, or presentations unless the exact water's current rules have been verified from the responsible state agency.</p>
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
        <span>Try a real Idaho water:</span>
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
    if(heading)heading.textContent='What the search checks—and what it cannot promise.';
    if(paragraphs[0])paragraphs[0].textContent='The finder checks managed-water records, official state directories, available maps, live weather, known species records, and nearby recreation facilities. A dated fishing report is shown only when one exists.';
    if(paragraphs[1])paragraphs[1].textContent='No directory can guarantee every shoreline, current road condition, or open facility. Unknown details are labeled, and anglers should verify the official source and posted signs before traveling.';
  }

  const parseLocation=()=>{
    const text=(document.getElementById('reportTitle')?.textContent||'').trim();
    const parts=text.split('·').map(part=>part.trim()).filter(Boolean);
    return{
      water:parts[0]||'this water',
      state:parts[1]||''
    };
  };

  const normalize=value=>String(value||'').toLowerCase().replace(/[’']/g,'').replace(/\s+/g,' ').trim();

  const exactMethodRule=(state,water)=>{
    const exact=VERIFIED_METHOD_RULES[`${normalize(state)}|${normalize(water)}`];
    if(exact)return exact;
    const waterNorm=normalize(water);
    const stateNorm=normalize(state);
    return Object.entries(VERIFIED_METHOD_RULES)
      .find(([key])=>{
        const [recordState,recordWater]=key.split('|');
        return recordState===stateNorm&&(waterNorm===recordWater||waterNorm.startsWith(recordWater+' ')||waterNorm.includes('('+recordWater+')'));
      })?.[1]||null;
  };

  const officialWaterLink=()=>{
    const links=[...document.querySelectorAll('#reportGrid .official-record a')];
    return links.find(link=>/official fishing|official.*access|official.*page/i.test(link.textContent))?.href||links[0]?.href||'';
  };

  const enforceLegalMethodGate=()=>{
    const card=document.querySelector('#reportGrid .bait-card');
    if(!card||card.dataset.legalGate==='true')return;
    const {water,state}=parseLocation();
    const stateRule=STATE_RULES[state]||null;
    const exact=exactMethodRule(state,water);
    const waterLink=officialWaterLink();

    card.dataset.legalGate='true';
    card.classList.add('ffo-legal-method-card');

    const actions=[];
    if(exact?.source)actions.push(`<a href="${exact.source}" target="_blank" rel="noopener">Open verified water rule ↗</a>`);
    else if(waterLink)actions.push(`<a href="${waterLink}" target="_blank" rel="noopener">Open official water page ↗</a>`);
    if(stateRule?.rules)actions.push(`<a href="${stateRule.rules}" target="_blank" rel="noopener">Open current ${state} regulations ↗</a>`);
    if(stateRule?.emergency&&stateRule.emergency!==stateRule.rules)actions.push(`<a href="${stateRule.emergency}" target="_blank" rel="noopener">Check emergency changes ↗</a>`);

    if(exact){
      card.innerHTML=`
        <span class="ffo-method-status verified">Verified restriction</span>
        <h3>Check this rule before choosing tackle.</h3>
        <p>Fish Finder Outdoors is not recommending a bait or lure for <strong>${water}</strong>. A current official source contains a method restriction that matters here.</p>
        <div class="ffo-legal-rule"><strong>${exact.summary}</strong><span>Source reviewed by FFO: ${exact.reviewed}</span></div>
        <div class="ffo-rule-actions">${actions.join('')}</div>
        <p class="ffo-rule-warning">The official rule, emergency changes, and posted signs control. This notice is a safety flag—not a substitute for the regulations.</p>
      `;
    }else{
      card.innerHTML=`
        <span class="ffo-method-status">Legality not verified</span>
        <h3>No bait or lure recommendation shown.</h3>
        <p>FFO has not yet verified the current water-specific method rules for <strong>${water}</strong>${state?` in <strong>${state}</strong>`:''}. That means the app will not suggest worms, PowerBait, salmon eggs, live bait, artificial lures, flies, hook types, or presentations for this result.</p>
        <div class="ffo-legal-rule"><strong>No verified rule record = no recommendation.</strong><span>This protects anglers from special-rule waters, seasonal restrictions, emergency changes, and section-specific regulations.</span></div>
        <div class="ffo-rule-actions">${actions.join('')}</div>
        <p class="ffo-rule-warning">Open the official water page and current state regulations before selecting tackle. Emergency rules and posted signs can override the printed guidebook.</p>
      `;
    }

    document.querySelectorAll('#reportGrid .report-note').forEach(note=>{
      if(/conditions score/i.test(note.textContent)){
        note.innerHTML='<strong>Recent catches and the weather-based planning note are different.</strong> The catch card shows dated reported results; the weather note is an estimate and does not say whether fish are biting.';
      }
    });
  };

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

  const refreshReportSafety=()=>{
    humanizeOutlook();
    enforceLegalMethodGate();
  };

  const reportGrid=document.getElementById('reportGrid');
  if(reportGrid){
    new MutationObserver(refreshReportSafety).observe(reportGrid,{childList:true,subtree:true});
    refreshReportSafety();
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
