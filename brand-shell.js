(function(){
  const button=document.querySelector('.ffo-menu-button');
  const nav=document.querySelector('.ffo-nav');

  if(nav&&!nav.querySelector('a[href="idaho-county-reports.html"]')){
    const link=document.createElement('a');
    link.href='idaho-county-reports.html';
    link.textContent='Idaho County Reports';
    const submit=nav.querySelector('a[href="submit-report.html"]');
    if(submit)nav.insertBefore(link,submit);
    else nav.appendChild(link);
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
})();
