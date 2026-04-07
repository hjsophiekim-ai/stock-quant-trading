// Runtime config for desktop app (do not store secrets here).
// TODO: Replace with secure environment injection at packaging time.
window.RUNTIME_CONFIG = {
  BACKEND_URL: "http://localhost:8000",
  APP_ENV: "development",
};
