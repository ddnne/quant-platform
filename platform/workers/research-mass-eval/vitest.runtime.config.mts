import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: {
        configPath: "../../../tests/fixtures/research_mass_lease_runtime.toml",
      },
    }),
  ],
  test: {
    include: ["runtime/**/*.test.ts"],
    testTimeout: 30_000,
  },
});
