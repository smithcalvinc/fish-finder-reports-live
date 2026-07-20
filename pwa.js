/* Fish Finder Outdoors Fishing Reports PWA */
(function () {
  "use strict";

  let deferredInstallPrompt = null;
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;

  function installButtons() {
    return Array.from(document.querySelectorAll("[data-install-ffo-app]"));
  }

  function setButtonState(visible, text = "Install App") {
    installButtons().forEach(button => {
      button.hidden = !visible;
      button.textContent = text;
    });
  }

  function showInstallMessage(message) {
    let panel = document.getElementById("ffoInstallMessage");
    if (!panel) {
      panel = document.createElement("div");
      panel.id = "ffoInstallMessage";
      panel.className = "ffo-install-message";
      panel.setAttribute("role", "status");
      document.body.appendChild(panel);
    }

    panel.innerHTML = `
      <button type="button" class="ffo-install-close" aria-label="Close install instructions">×</button>
      <strong>Install FFO Fishing Reports</strong>
      <p>${message}</p>
    `;
    panel.hidden = false;
    panel.querySelector(".ffo-install-close")?.addEventListener("click", () => {
      panel.hidden = true;
    });
  }

  async function installApp() {
    if (isStandalone) return;

    if (deferredInstallPrompt) {
      deferredInstallPrompt.prompt();
      const choice = await deferredInstallPrompt.userChoice;
      deferredInstallPrompt = null;
      if (choice.outcome === "accepted") setButtonState(false);
      return;
    }

    if (isIOS) {
      showInstallMessage(
        "In Safari, tap the Share button, then choose <b>Add to Home Screen</b>. " +
        "The app will open without the normal browser controls."
      );
      return;
    }

    showInstallMessage(
      "Open your browser menu and choose <b>Install app</b> or <b>Add to Home screen</b>. " +
      "Chrome and Edge may also show an install icon in the address bar."
    );
  }

  document.addEventListener("click", event => {
    const button = event.target.closest("[data-install-ffo-app]");
    if (!button) return;
    event.preventDefault();
    installApp();
  });

  window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    deferredInstallPrompt = event;
    setButtonState(true, "Install App");
  });

  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    setButtonState(false);
    document.documentElement.classList.add("ffo-app-installed");
  });

  if (isStandalone) {
    document.documentElement.classList.add("ffo-standalone");
    setButtonState(false);
  } else if (isIOS) {
    setButtonState(true, "Install App");
  } else {
    setButtonState(false);
    window.setTimeout(() => {
      if (!deferredInstallPrompt && !isStandalone) {
        setButtonState(true, "Install App");
      }
    }, 2500);
  }

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", async () => {
      try {
        const registration = await navigator.serviceWorker.register("./service-worker.js", {
          scope: "./",
          updateViaCache: "none"
        });

        registration.addEventListener("updatefound", () => {
          const worker = registration.installing;
          if (!worker) return;
          worker.addEventListener("statechange", () => {
            if (worker.state === "installed" && navigator.serviceWorker.controller) {
              let notice = document.getElementById("ffoUpdateNotice");
              if (!notice) {
                notice = document.createElement("button");
                notice.id = "ffoUpdateNotice";
                notice.className = "ffo-update-notice";
                notice.type = "button";
                notice.textContent = "App update ready — tap to refresh";
                document.body.appendChild(notice);
                notice.addEventListener("click", () => {
                  worker.postMessage("SKIP_WAITING");
                  window.location.reload();
                });
              }
            }
          });
        });
      } catch (error) {
        console.warn("FFO Reports service worker could not register.", error);
      }
    });
  }
})();
