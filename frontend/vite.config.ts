/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

/**
 * Content-Security-Policy for the production build only: the dev server injects an inline script for React
 * Fast Refresh, which this policy would block. `connect-src` admits only this origin plus the API origin
 * (VITE_API_BASE_URL), so injected script could not exfiltrate to arbitrary hosts.
 */
function apiOrigin(baseUrl: string | undefined): string | null {
  if (!baseUrl?.trim()) return null;
  const url = new URL(baseUrl.trim()); // throws on a malformed value: fail the build, not the browser
  if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error(`VITE_API_BASE_URL must be http(s): ${baseUrl}`);
  return url.origin;
}

function contentSecurityPolicy(apiBaseUrl: string | undefined): Plugin {
  const origin = apiOrigin(apiBaseUrl);
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    origin ? `connect-src 'self' ${origin}` : "connect-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");
  return {
    name: "dof-ai-csp",
    apply: "build",
    transformIndexHtml: () => [
      { tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: policy }, injectTo: "head-prepend" },
    ],
  };
}

// In development the SPA calls the Django API through this proxy, so no CORS setup is needed locally.
// In production VITE_API_BASE_URL points at the API origin (see .env.example).
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), contentSecurityPolicy(loadEnv(mode, process.cwd(), "VITE_").VITE_API_BASE_URL)],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.VITE_DEV_API_PROXY ?? "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { sourcemap: false },
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
}));
