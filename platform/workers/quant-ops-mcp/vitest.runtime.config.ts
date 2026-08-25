import {
  cloudflareTest,
  readD1Migrations,
} from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

const projectionMigrations = await readD1Migrations("./migrations/projection");
const quotaMigrations = await readD1Migrations("./migrations/quota");

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.test.toml" },
    }),
  ],
  test: {
    include: ["runtime/**/*.test.js"],
    provide: {
      opsProjectionD1Migrations: projectionMigrations,
      opsQuotaD1Migrations: quotaMigrations,
    },
    testTimeout: 20_000,
  },
});
