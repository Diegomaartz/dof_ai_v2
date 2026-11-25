/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/**
 * Content-Security-Policy for the production build only: the dev server injects an inline script for React
 * Fast Refresh, which this policy would block. `connect-src https:` admits the API origin (VITE_API_BASE_URL).
 */
function contentSecurityPolicy(): Plugin {
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "connect-src 'self' https:",
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
export default defineConfig({
  plugins: [react(), tailwindcss(), contentSecurityPolicy()],
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
});
