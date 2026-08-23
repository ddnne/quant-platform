import { describe, expect, it } from "vitest";
import worker from "./index";

const RUN_TOKEN = "jsda-test-run-token-do-not-leak";

function testEnv(): {
  RAW_BUCKET: never;
  DB: never;
  INGESTION_RUN_TOKEN: string;
} {
  return {
    RAW_BUCKET: {} as never,
    DB: {} as never,
    INGESTION_RUN_TOKEN: RUN_TOKEN,
  };
}

describe("ingestion-jsda handlers", () => {
  it("exposes health fetch and scheduled cron handlers", () => {
    expect(typeof worker.fetch).toBe("function");
    expect(typeof worker.scheduled).toBe("function");
  });

  it("health and unauthorized run do not leak the run token", async () => {
    const env = testEnv();
    const health = await worker.fetch(
      new Request("https://ingestion-jsda.test/health"),
      env,
    );
    expect(health.status).toBe(200);
    const healthBody = await health.text();
    expect(healthBody).not.toContain(RUN_TOKEN);
    const healthJson = JSON.parse(healthBody) as { ok?: boolean; worker?: string };
    expect(healthJson.ok).toBe(true);
    expect(healthJson.worker).toBe("ingestion-jsda");

    const run = await worker.fetch(
      new Request("https://ingestion-jsda.test/v1/run"),
      env,
    );
    expect(run.status).toBe(401);
    const runBody = await run.text();
    expect(runBody).not.toContain(RUN_TOKEN);
    expect(runBody).not.toMatch(/INGESTION_RUN_TOKEN/i);
  });
});
