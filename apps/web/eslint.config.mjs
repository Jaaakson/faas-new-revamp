import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({
  baseDirectory: dirname(fileURLToPath(import.meta.url)),
});

const config = [
  // jsx-a11y comes from next/core-web-vitals; accessibility is enforced in CI,
  // not deferred to a hardening phase (docs/04-design-system.md §9).
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts"],
  },
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // `any` defeats the generated API types that make a backend rename a
      // compile error. Warn rather than error so it surfaces without blocking.
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
];

export default config;
