import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.AOS_API_URL ?? "http://localhost:8000" },
  },
  test: {
    // Unit tests only; Playwright's web/e2e/*.spec.ts run with `npm run e2e`.
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    environmentOptions: {
      jsdom: { url: "http://localhost/" },
    },
    setupFiles: ["./src/test/setup.ts"],
  },
});
