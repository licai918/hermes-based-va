import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["{packages,services,eval}/**/*.test.ts"],
    environment: "node",
  },
});
