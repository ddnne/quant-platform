import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";
import { denyTestOutbound } from "../../worker_support/test_outbound.mjs";

export default defineConfig({
  plugins: [
    cloudflareTest({
      miniflare: { outboundService: denyTestOutbound },
      wrangler: { configPath: "./wrangler.test.toml" },
    }),
  ],
  test: {
    include: ["src/**/*.test.ts"],
  },
});
