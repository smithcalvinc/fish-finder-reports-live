(function(){
  const button=document.querySelector('.ffo-menu-button');
  const nav=document.querySelector('.ffo-nav');
  const stateLinks=[['idaho-county-reports.html','Idaho County Reports'],['montana-county-reports.html','Montana County Reports'],['utah-county-reports.html','Utah County Reports'],['colorado-county-reports.html','Colorado County Reports'],['wyoming-county-reports.html','Wyoming County Reports']];
  if(nav){
    const submit=nav.querySelector('a[href="submit-report.html"]');
    stateLinks.forEach(([href,text])=>{
      if(!nav.querySelector(`a[href="${href}"]`)){
        const link=document.createElement('a');link.href=href;link.textContent=text;
        if(submit)nav.insertBefore(link,submit);else nav.appendChild(link);
      }
    });
  }
  if(button&&nav){button.innerHTML='<span></span>';button.addEventListener('click',()=>{const open=nav.classList.toggle('open');button.setAttribute('aria-expanded',open?'true':'false');button.classList.toggle('open',open);});nav.querySelectorAll('a').forEach(link=>link.addEventListener('click',()=>nav.classList.remove('open')));}
})();
