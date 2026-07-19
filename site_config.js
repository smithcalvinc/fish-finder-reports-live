/* Fish Finder Outdoors public configuration.
   The Supabase URL and publishable key are safe to expose when Row Level
   Security is configured with the included SQL. Never place a secret key here. */
window.FFO_SITE_CONFIG = {
  site_name: "Fish Finder Outdoors",
  site_url: "https://fishfinderoutdoors.com",
  powered_by_name: "Mountain Dog Enterprises",
  powered_by_url: "https://mountaindogenterprises.com",

  github_repository_url: "https://github.com/smithcalvinc/fish-finder-reports-live",

  /* Phase 7 database connection.
     Paste values from Supabase:
     Project Settings → API → Project URL and Publishable key. */
  supabase_url: "",
  supabase_publishable_key: "",

  current_report_days: 14,
  aging_report_days: 45
};
