import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";
import { denyTestOutbound } from "../../worker_support/test_outbound.mjs";

export default defineConfig({
  plugins: [
    cloudflareTest({
      miniflare: { outboundService: denyTestOutbound },
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
