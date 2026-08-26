/**
 * Tailwind CSS v4 is configured in CSS (`@theme inline` in globals.css), not in
 * a JS config file. This plugin is the entire build integration.
 */
const config = {
  plugins: ["@tailwindcss/postcss"],
};

export default config;
