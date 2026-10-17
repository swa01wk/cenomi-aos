import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The kernel API runs on :8000; the dev server proxies /api so the browser sees one origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.AOS_API_URL ?? "http://localhost:8000" },
  },
});
