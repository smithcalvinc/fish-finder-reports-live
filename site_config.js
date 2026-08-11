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
  brand_tagline: "Nine-State Fishing Location Finder",
  location_snapshot_date: "2026-08-10",
  facility_radius_miles: 5,
  report_retention: "latest-dated-report-retained",

  // These thresholds are retained only for private admin labels. They do not
  // hide or expire a valid dated report in the public location finder.
  current_report_days: 14,
  aging_report_days: 45
};

/*
 * Main-site link migration.
 *
 * Older report-app pages still contain the former Wasmer homepage address in
 * their static navigation. Rewrite only those main-site URLs after the page
 * loads. State-agency sources, maps, forms, report data, and all search behavior remain unchanged.
 */
document.addEventListener("DOMContentLoaded", function () {
  var officialMainSite = "https://www.fishfinderoutdoors.com";
  var legacyMainHosts = new Set([
    "fishfinderoutdoors.wasmer.app",
    "www.fishfinderoutdoors.wasmer.app",
    "fishfinderoutdoors.com"
  ]);

  document.querySelectorAll("a[href]").forEach(function (link) {
    try {
      var destination = new URL(link.getAttribute("href"), window.location.href);

      if (legacyMainHosts.has(destination.hostname)) {
        link.href =
          officialMainSite +
          destination.pathname +
          destination.search +
          destination.hash;
      }
    } catch (error) {
      /* Leave malformed, mail, telephone, and other nonstandard links alone. */
    }
  });

  /*
   * The source-review dashboard is an internal management workflow and should
   * not be offered in public navigation. Removing the link is not authentication;
   * the admin page still needs true access control if private protection is wanted.
   */
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

  /*
   * Correct former main-site URLs embedded inside JSON-LD structured data.
   * Report-app canonical URLs and report-app image URLs use the public reports subdomain.
   */
  document
    .querySelectorAll('script[type="application/ld+json"]')
    .forEach(function (script) {
      if (!script.textContent.includes("fishfinderoutdoors.wasmer.app")) return;

      script.textContent = script.textContent.replaceAll(
        "https://fishfinderoutdoors.wasmer.app",
        officialMainSite
      );
    });
});
