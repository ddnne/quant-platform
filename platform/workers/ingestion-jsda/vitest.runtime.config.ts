import {
  cloudflareTest,
  readD1Migrations,
} from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";
import { denyTestOutbound } from "../../worker_support/test_outbound.mjs";

const d1Migrations = await readD1Migrations("../ingestion-premium/migrations");

export default defineConfig({
  plugins: [
    cloudflareTest({
      miniflare: { outboundService: denyTestOutbound },
      wrangler: { configPath: "./wrangler.test.toml" },
    }),
  ],
  test: {
    include: ["runtime/**/*.test.ts"],
    provide: { jsdaD1Migrations: d1Migrations },
    testTimeout: 20_000,
    hookTimeout: 20_000,
  },
});
