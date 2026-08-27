import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["src/authorized.test.ts", "src/http_json.test.ts"],
    environment: "node",
    setupFiles: ["./src/test-setup.ts"],
  },
});
