
(function(){
  const button=document.querySelector(".ffo-menu-button");
  const nav=document.querySelector(".ffo-nav");
  if(button&&nav){
    button.addEventListener("click",()=>{
      const open=nav.classList.toggle("open");
      button.setAttribute("aria-expanded",open?"true":"false");
    });
    nav.querySelectorAll("a").forEach(link=>link.addEventListener("click",()=>nav.classList.remove("open")));
  }
})();
