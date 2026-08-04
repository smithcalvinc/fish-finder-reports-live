/* Fish Finder Outdoors Fishing Reports PWA */
(function(){
  "use strict";

  let deferredInstallPrompt=null;
  let reloadingForUpdate=false;
  const isIOS=/iphone|ipad|ipod/i.test(navigator.userAgent);
  const isAndroid=/android/i.test(navigator.userAgent);
  const isStandalone=window.matchMedia("(display-mode: standalone)").matches||window.navigator.standalone===true;

  function installButtons(){
    return Array.from(document.querySelectorAll("[data-install-ffo-app]"));
  }

  function setButtonState(visible,text="Install App"){
    installButtons().forEach(button=>{
      button.hidden=!visible;
      button.textContent=text;
    });
  }

  function showInstallMessage(message){
    let panel=document.getElementById("ffoInstallMessage");
    if(!panel){
      panel=document.createElement("div");
      panel.id="ffoInstallMessage";
      panel.className="ffo-install-message";
      panel.setAttribute("role","status");
      document.body.appendChild(panel);
    }
    panel.innerHTML=`<button type="button" class="ffo-install-close" aria-label="Close install instructions">×</button><strong>Install FFO Fishing Reports</strong><p>${message}</p>`;
    panel.hidden=false;
    panel.querySelector(".ffo-install-close")?.addEventListener("click",()=>{panel.hidden=true;});
  }

  async function installApp(){
    if(isStandalone)return;
    if(deferredInstallPrompt){
      deferredInstallPrompt.prompt();
      const choice=await deferredInstallPrompt.userChoice;
      deferredInstallPrompt=null;
      if(choice.outcome==="accepted")setButtonState(false);
      return;
    }
    if(isIOS){
      showInstallMessage("On iPhone or iPad, open this page in Safari, tap the <b>Share</b> button, then choose <b>Add to Home Screen</b>.");
      return;
    }
    if(isAndroid){
      showInstallMessage("On Android, open your browser menu and choose <b>Install app</b> or <b>Add to Home screen</b>.");
      return;
    }
    showInstallMessage("On your computer, open the browser menu and choose <b>Install Fish Finder Outdoors</b> or <b>Install app</b>.");
  }

  document.addEventListener("click",event=>{
    const button=event.target.closest("[data-install-ffo-app]");
    if(!button)return;
    event.preventDefault();
    installApp();
  });

  window.addEventListener("beforeinstallprompt",event=>{
    event.preventDefault();
    deferredInstallPrompt=event;
    setButtonState(true,"Install App");
  });

  window.addEventListener("appinstalled",()=>{
    deferredInstallPrompt=null;
    setButtonState(false);
    document.documentElement.classList.add("ffo-app-installed");
  });

  function normalInstallLabel(){
    return window.matchMedia("(max-width:760px)").matches
      ?"Install App"
      :"Install Fishing Reports App";
  }

  if(isStandalone){
    document.documentElement.classList.add("ffo-standalone");
    setButtonState(false);
  }else{
    setButtonState(true,normalInstallLabel());
  }

  window.addEventListener("resize",()=>{
    if(!isStandalone)setButtonState(true,normalInstallLabel());
  });

  const displayModeQuery=window.matchMedia("(display-mode: standalone)");
  displayModeQuery.addEventListener?.("change",event=>{
    if(event.matches){
      document.documentElement.classList.add("ffo-standalone");
      setButtonState(false);
    }
  });

  if("launchQueue" in window&&window.launchQueue.setConsumer){
    window.launchQueue.setConsumer(launchParams=>{
      const target=launchParams?.targetURL;
      if(!target)return;
      try{
        const url=new URL(target);
        if(url.origin===window.location.origin&&window.location.href!==url.href){
          window.location.href=url.href;
        }
      }catch{}
    });
  }

  if("serviceWorker" in navigator){
    navigator.serviceWorker.addEventListener("controllerchange",()=>{
      if(reloadingForUpdate)return;
      reloadingForUpdate=true;
      window.location.reload();
    });

    window.addEventListener("load",async()=>{
      try{
        const registration=await navigator.serviceWorker.register("./service-worker.js",{
          scope:"./",
          updateViaCache:"none"
        });

        const activateWaiting=()=>{
          if(registration.waiting)registration.waiting.postMessage("SKIP_WAITING");
        };

        activateWaiting();

        registration.addEventListener("updatefound",()=>{
          const worker=registration.installing;
          if(!worker)return;
          worker.addEventListener("statechange",()=>{
            if(worker.state==="installed"&&navigator.serviceWorker.controller){
              worker.postMessage("SKIP_WAITING");
            }
          });
        });

        await registration.update().catch(()=>{});

        const checkForUpdates=()=>registration.update().catch(()=>{});
        window.addEventListener("focus",checkForUpdates);
        document.addEventListener("visibilitychange",()=>{
          if(document.visibilityState==="visible")checkForUpdates();
        });
        setInterval(checkForUpdates,15*60*1000);
      }catch(error){
        console.warn("FFO Reports service worker could not register.",error);
      }
    });
  }
})();
