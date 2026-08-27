import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["harness/**/*.test.ts"],
    environment: "node",
    testTimeout: 20_000,
  },
});
