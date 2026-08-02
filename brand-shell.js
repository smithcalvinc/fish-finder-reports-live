(function(){
  const button=document.querySelector('.ffo-menu-button');
  const nav=document.querySelector('.ffo-nav');
  const stateLinks=[
    ['idaho-county-reports.html','Idaho County Reports'],
    ['montana-county-reports.html','Montana County Reports'],
    ['utah-county-reports.html','Utah County Reports'],
    ['colorado-county-reports.html','Colorado County Reports'],
    ['wyoming-county-reports.html','Wyoming County Reports']
  ];

  if(nav){
    const submit=nav.querySelector('a[href="submit-report.html"]');
    stateLinks.forEach(([href,text])=>{
      if(!nav.querySelector(`a[href="${href}"]`)){
        const link=document.createElement('a');
        link.href=href;
        link.textContent=text;
        if(submit)nav.insertBefore(link,submit);else nav.appendChild(link);
      }
    });
  }

  if(button&&nav){
    button.innerHTML='<span></span>';
    button.addEventListener('click',()=>{
      const open=nav.classList.toggle('open');
      button.setAttribute('aria-expanded',open?'true':'false');
      button.classList.toggle('open',open);
    });
    nav.querySelectorAll('a').forEach(link=>link.addEventListener('click',()=>nav.classList.remove('open')));
  }

  const currentPage=(location.pathname.split('/').pop()||'index.html').toLowerCase();
  if(currentPage!=='index.html')return;

  document.title='Find Fishing Waters | Fish Finder Outdoors';

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
    document.querySelector('.ffo-professional-hero'),
    document.querySelector('.ffo-trust-strip'),
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
      <span class="ffo-byline">A note from Chris in Pocatello, Idaho</span>
      <h1>Find the water first. Check the facts before you go.</h1>
      <p>I built Fish Finder Outdoors because fishing information is scattered across agency sites, maps, and old social posts. Search a water or town below. The results separate official agency information, dated angler reports, and weather-based estimates so you can see what each claim is based on.</p>
    `;
    main.insertBefore(intro,search);

    const sectionLabel=search.querySelector(':scope > .ffo-section-label');
    if(sectionLabel)sectionLabel.textContent='Built in Pocatello by an Idaho angler';

    const panel=search.querySelector('.ffo-beta-panel');
    if(panel){
      panel.innerHTML='<h2>Find a fishing water.</h2><p>Enter a lake, river, reservoir, pond, town, or coordinates. Start with the place you are actually considering—not a broad fishing question.</p>';
    }

    const proof=search.querySelector('.tool-proof-line');
    if(proof)proof.textContent='Official agency links • Dated angler reports • Estimates clearly labeled';

    const hint=search.querySelector('.hint');
    if(hint)hint.textContent='Town searches look roughly 50 miles. Always open the official source and verify current access and regulations before traveling.';

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
      pill.appendChild(document.createTextNode(' Weather-based estimate (not a report)'));
    }
  });

  const seo=document.querySelector('.ffo-seo-section');
  if(seo){
    const label=seo.querySelector('.ffo-section-label');
    const heading=seo.querySelector('h2');
    const paragraphs=seo.querySelectorAll(':scope .ffo-seo-inner > div:first-child p');
    if(label)label.textContent='How the search works';
    if(heading)heading.textContent='What the search checks—and what it cannot promise.';
    if(paragraphs[0])paragraphs[0].textContent='The tool checks managed water records, official state directories, available measurements, and reviewed angler reports. Each type of information is labeled so you can judge it for yourself.';
    if(paragraphs[1])paragraphs[1].textContent='No search can guarantee public shoreline access, current road conditions, or whether fish are biting. Verify the agency source and posted signs before you make the drive.';
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

  const reportGrid=document.getElementById('reportGrid');
  if(reportGrid){
    new MutationObserver(humanizeOutlook).observe(reportGrid,{childList:true,subtree:true});
    humanizeOutlook();
  }
})();
