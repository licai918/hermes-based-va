import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Workbench-local Vitest project: React components and BFF route handlers run in
// jsdom (the root vitest.config.ts stays node-only for the pure TS packages). The
// root vitest.workspace.ts composes both so a single `pnpm test` covers all.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    name: "workbench",
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: [
      "app/**/*.test.{ts,tsx}",
      "components/**/*.test.{ts,tsx}",
      "lib/**/*.test.{ts,tsx}",
      "instrumentation.test.ts",
    ],
  },
});
