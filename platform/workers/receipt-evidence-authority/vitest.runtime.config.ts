import {
  cloudflareTest,
  readD1Migrations,
} from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

const d1Migrations = await readD1Migrations("../ingestion-premium/migrations");

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.test.toml" },
    }),
  ],
  test: {
    include: ["runtime/**/*.test.ts"],
    provide: { receiptD1Migrations: d1Migrations },
    testTimeout: 30_000,
  },
});
