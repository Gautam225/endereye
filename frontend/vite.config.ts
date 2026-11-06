import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The backend (FastAPI). Requests to /api are proxied to it, so the browser sees one origin.
const backend = process.env.EOE_BACKEND_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: backend } },
  },
  preview: {
    port: 4173,
    proxy: { "/api": { target: backend } },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
