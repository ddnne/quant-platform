import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["harness/**/*.test.ts"],
    environment: "node",
    setupFiles: ["../../worker_support/test_node_http.mjs"],
    testTimeout: 20_000,
  },
});
