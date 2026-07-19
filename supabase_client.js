/* Fish Finder Outdoors shared Supabase browser client. */
(function () {
  const cfg = window.FFO_SITE_CONFIG || {};
  const url = String(cfg.supabase_url || "").trim();
  const key = String(cfg.supabase_publishable_key || "").trim();

  window.FFO_DB_READY = Boolean(
    url &&
    key &&
    window.supabase &&
    typeof window.supabase.createClient === "function"
  );

  window.FFO_DB = window.FFO_DB_READY
    ? window.supabase.createClient(url, key, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true
        }
      })
    : null;

  window.ffoDatabaseMessage = function () {
    if (!url || !key) {
      return "The Phase 7 database has not been connected yet. Add the Supabase Project URL and publishable key to site_config.js.";
    }
    if (!window.supabase) {
      return "The Supabase browser library could not load. Check the internet connection or content-blocking settings.";
    }
    return "";
  };
})();
