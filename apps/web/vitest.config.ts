import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],

  // Override PostCSS discovery. postcss.config.mjs uses Next's string-shorthand
  // plugin syntax, which raw Vite cannot parse. Component tests assert class
  // names rather than computed styles, so running Tailwind here would be
  // wasted work even if it did load.
  css: {
    postcss: { plugins: [] },
  },

  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
