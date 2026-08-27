import { describe, expect, it } from "vitest";
import { deploymentVersion, operationalEvent } from "./operational_event";

describe("JSDA operational events", () => {
  it("includes run, job, segment, dataset, generation, cursor, version, result, and reason", () => {
    const event = operationalEvent(
      {
        CF_VERSION_METADATA: {
          id: "version-abc",
          tag: "prod",
          timestamp: "2026-08-25T01:30:00.000Z",
        },
      },
      "jsda_queue_register_failed",
      {
        run_id: "jsda:v2:root:jsda_tokyo_repo_rates:cron:2026-08-25",
        job_id: "jsda:v2:file:example",
        segment_id: "file_trrts",
        dataset: "jsda_tokyo_repo_rates",
        generation: null,
        cursor: 0,
        result: "failed_transient",
        reason: "d1_unavailable",
      },
    );
    expect(event).toEqual({
      event: "jsda_queue_register_failed",
      worker: "ingestion-jsda",
      run_id: "jsda:v2:root:jsda_tokyo_repo_rates:cron:2026-08-25",
      job_id: "jsda:v2:file:example",
      segment_id: "file_trrts",
      dataset: "jsda_tokyo_repo_rates",
      generation: null,
      cursor: 0,
      deployment_version: "version-abc",
      result: "failed_transient",
      reason: "d1_unavailable",
    });
  });

  it("uses version id then tag and does not retain module-level request state", () => {
    expect(deploymentVersion(undefined)).toBeNull();
    expect(deploymentVersion({ id: "", tag: "staging" })).toBe("staging");
    const first = operationalEvent({}, "one", { job_id: "a" });
    const second = operationalEvent({}, "two", { job_id: "b" });
    expect(first.job_id).toBe("a");
    expect(second.job_id).toBe("b");
    expect(first.deployment_version).toBeNull();
  });
});
