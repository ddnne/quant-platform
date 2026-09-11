import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
    setupFiles: ["../../worker_support/test_node_crypto.ts"],
  },
});
