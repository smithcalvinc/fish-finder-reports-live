/* Fish Finder Outdoors public configuration.
   Do not place passwords, API keys or private tokens in this file. */
window.FFO_SITE_CONFIG = {
  site_name: "Fish Finder Outdoors",
  site_url: "https://www.fishfinderoutdoors.com",
  report_site_url: "https://reports.fishfinderoutdoors.com",
  powered_by_name: "Mountain Dog Enterprises",
  powered_by_url: "https://mountaindogenterprises.com",

  github_repository_url: "https://github.com/smithcalvinc/fish-finder-reports-live",
  submission_email: "mountain.dog.enterprises@gmail.com",
  beta_mode: true,
  beta_feedback_email: "mountain.dog.enterprises@gmail.com",
  brand_tagline: "Idaho Built. Northwest Ready.",

  current_report_days: 14,
  aging_report_days: 45
};

document.addEventListener("DOMContentLoaded", function () {
  var officialMainSite = "https://www.fishfinderoutdoors.com";
  var officialReportSite = "https://reports.fishfinderoutdoors.com";

  var legacyMainHosts = new Set([
    "fishfinderoutdoors.wasmer.app",
    "www.fishfinderoutdoors.wasmer.app",
    "fishfinderoutdoors.com"
  ]);

  var legacyReportHosts = new Set([
    "fish-finder-reports-live.wasmer.app"
  ]);

  function migrateUrl(value) {
    if (!value) return value;

    try {
      var destination = new URL(value, window.location.href);

      if (legacyMainHosts.has(destination.hostname)) {
        return (
          officialMainSite +
          destination.pathname +
          destination.search +
          destination.hash
        );
      }

      if (legacyReportHosts.has(destination.hostname)) {
        return (
          officialReportSite +
          destination.pathname +
          destination.search +
          destination.hash
        );
      }
    } catch (error) {
      return value;
    }

    return value;
  }

  document.querySelectorAll("a[href]").forEach(function (link) {
    link.href = migrateUrl(link.getAttribute("href"));
  });

  document.querySelectorAll("link[href]").forEach(function (link) {
    link.href = migrateUrl(link.getAttribute("href"));
  });

  document.querySelectorAll("meta[content]").forEach(function (meta) {
    var original = meta.getAttribute("content");
    var migrated = migrateUrl(original);
    if (migrated !== original) meta.setAttribute("content", migrated);
  });

  document
    .querySelectorAll('a[href="admin.html"], a[href$="/admin.html"]')
    .forEach(function (link) {
      var label = String(link.textContent || "").toLowerCase();

      if (
        label.includes("source review") ||
        label.includes("admin") ||
        label.includes("dashboard")
      ) {
        link.remove();
      }
    });

  document
    .querySelectorAll('script[type="application/ld+json"]')
    .forEach(function (script) {
      script.textContent = script.textContent
        .split("https://fishfinderoutdoors.wasmer.app")
        .join(officialMainSite)
        .split("https://fish-finder-reports-live.wasmer.app")
        .join(officialReportSite);
    });
});
