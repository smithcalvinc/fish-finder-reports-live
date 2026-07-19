/* Fish Finder Outdoors public configuration.
   Do not place passwords, API keys or private tokens in this file. */
window.FFO_SITE_CONFIG = {
  site_name: "Fish Finder Outdoors",
  site_url: "https://fishfinderoutdoors.com",
  powered_by_name: "Mountain Dog Enterprises",
  powered_by_url: "https://mountaindogenterprises.com",

  /* Optional: paste the public GitHub repository URL here so the admin
     dashboard can link directly to Actions and source files. */
  github_repository_url: "",

  /* Optional: a public form/webhook endpoint that accepts JSON POSTs.
     Leave blank to use safe local draft/export mode. */
  submission_endpoint: "",

  /* Reports older than these limits receive visible warnings. */
  current_report_days: 14,
  aging_report_days: 45
};
