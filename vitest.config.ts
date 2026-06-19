import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["{packages,services,apps,eval}/**/*.test.ts"],
    environment: "node",
  },
});
