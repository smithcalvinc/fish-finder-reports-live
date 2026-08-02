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
    setButtonState(true, "Install Fishing Reports App");
  }

  const displayModeQuery = window.matchMedia("(display-mode: standalone)");
  displayModeQuery.addEventListener?.("change", event => {
    if (event.matches) {
      document.documentElement.classList.add("ffo-standalone");
      setButtonState(false);
    }
  });

  if ("launchQueue" in window && window.launchQueue.setConsumer) {
    window.launchQueue.setConsumer(launchParams => {
      const target = launchParams?.targetURL;
      if (!target) return;
      try {
        const url = new URL(target);
        if (url.origin === window.location.origin) {
          const current = window.location.href;
          if (current !== url.href) window.location.href = url.href;
        }
      } catch {}
    });
  }

  /*
   * Facebook-safe water sharing.
   * Facebook was replacing water-specific URLs with the fixed canonical home URL.
   * Shared reports now use a neutral bridge page that preserves all water parameters,
   * then redirects the visitor to the exact report in a normal browser.
   */
  function sharedWaterUrl() {
    const params = new URLSearchParams(window.location.search);
    [
      "fbclid",
      "gclid",
      "utm_source",
      "utm_medium",
      "utm_campaign",
      "utm_content",
      "utm_term"
    ].forEach(key => params.delete(key));

    const bridge = new URL("./share-water.html", window.location.href);
    bridge.search = params.toString();
    return bridge.href;
  }

  function currentWaterName() {
    return (
      document.getElementById("reportTitle")?.textContent?.trim() ||
      new URLSearchParams(window.location.search).get("name") ||
      "Fishing water"
    );
  }

  async function copyWaterLink(button) {
    const url = sharedWaterUrl();
    try {
      await navigator.clipboard.writeText(url);
      const original = button.textContent;
      button.textContent = "Link Copied";
      window.setTimeout(() => {
        button.textContent = original || "Copy Report Link";
      }, 1800);
    } catch {
      window.prompt("Copy this water link:", url);
    }
  }

  async function shareWater(button) {
    const name = currentWaterName();
    const data = {
      title: `${name} Fishing Report | Fish Finder Outdoors`,
      text: `Check ${name} in the free Fish Finder Outdoors report tool. Official sources, access notes, conditions and reviewed reports are linked in one place.`,
      url: sharedWaterUrl()
    };

    try {
      if (navigator.share) {
        await navigator.share(data);
        return;
      }
      await navigator.clipboard.writeText(data.url);
      const original = button.textContent;
      button.textContent = "Water Link Copied";
      window.setTimeout(() => {
        button.textContent = original || "Share This Water";
      }, 1800);
    } catch (error) {
      if (error?.name !== "AbortError") {
        window.prompt("Copy this water link:", data.url);
      }
    }
  }

  document.addEventListener(
    "click",
    event => {
      const shareButton = event.target.closest("#shareWater");
      const copyButton = event.target.closest("#copyLink");
      if (!shareButton && !copyButton) return;

      const params = new URLSearchParams(window.location.search);
      if (!params.get("name") && !params.get("auto")) return;

      event.preventDefault();
      event.stopImmediatePropagation();

      if (shareButton) shareWater(shareButton);
      else copyWaterLink(copyButton);
    },
    true
  );

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
