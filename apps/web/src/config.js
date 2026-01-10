/**
 * Application configuration
 * Reads from Vite environment variables
 * 
 * Environment Variables:
 * - VITE_API_BASE_URL: Backend API URL (default: /api via Vite proxy)
 * - VITE_DEPLOYMENT_MODE: "cloud" | "self-hosted" (default: "cloud")
 * - VITE_ENABLE_GOOGLE_AUTH: Enable Google OAuth (default: true)
 * - VITE_ENABLE_DEV_PAT: Show PAT generator in UI (default: false in prod)
 */

const getConfig = () => {
  const isDev = import.meta.env.DEV;

  // API Base URL - where to call the backend
  const originFallback =
    typeof window !== "undefined" && window.location?.origin
      ? window.location.origin
      : null;
  const defaultDevApiBaseUrl = "/api";
  const rawApiBaseUrl =
    import.meta.env.VITE_API_BASE_URL ||
    (isDev ? defaultDevApiBaseUrl : originFallback || defaultDevApiBaseUrl);
  const normalizedBaseUrl = rawApiBaseUrl.replace(/\/+$/, "");
  const apiBaseUrl = normalizedBaseUrl.replace(/\/api(?:\/v1)?$/, "");

  // Deployment mode
  const mode = import.meta.env.VITE_DEPLOYMENT_MODE || "cloud";

  // Feature flags
  const googleAuth = import.meta.env.VITE_ENABLE_GOOGLE_AUTH !== "false";
  
  // PAT generator: only show in dev or if explicitly enabled
  // In production builds, this should be false unless VITE_ENABLE_DEV_PAT=true
  const enableDevPat = import.meta.env.VITE_ENABLE_DEV_PAT === "true" || isDev;

  return {
    apiBaseUrl,
    mode,
    isDev,
    features: {
      googleAuth,
      enableDevPat,
    },
  };
};

// Export config object
export const config = getConfig();

// Export commonly used values for convenience
export const API_BASE_URL = config.apiBaseUrl;

// Log config in development (helps debugging)
// if (import.meta.env.DEV) {
//   console.log("🔧 App Config:", {
//     apiBaseUrl: config.apiBaseUrl,
//     mode: config.mode,
//     isDev: config.isDev,
//     features: config.features,
//   });
// }
