import { describe, expect, it, vi } from "vitest";

import {
  durablePersonalJobStatus,
  personalJobStateKey,
  personalJobTerminalKey,
  submittedStateDocument,
  writeSubmittedState,
} from "./personal_job_state";
import { PERSONAL_RESEARCH_RUNNER_VERSION } from "./personal_research_contract";
import { PERSONAL_SVI_2023_RUNNER_VERSION } from "./personal_svi_2023_contract";
import {
  PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID,
  PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_RUNNER_VERSION,
  PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID,
  PERSONAL_INDEX_SMILE_TRANSPORT_2023_RUNNER_VERSION,
  PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
  PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION,
  PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
  PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION,
} from "./personal_index_vol_overlay_2023_contract";
import { PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION } from "./personal_vol_am_pm_panel_writer_contract";
import { PERSONAL_OPTION_SIDECAR_RUNNER_VERSION } from "./personal_option_sidecar_producer_contract";
import type { Env } from "./types";

const DIGEST_A = `sha256:${"a".repeat(64)}`;
const DIGEST_B = `sha256:${"b".repeat(64)}`;

type Stored = {
  bytes: Uint8Array;
  customMetadata: Record<string, string>;
};

class MemoryR2 {
  readonly values = new Map<string, Stored>();

  seed(key: string, value: unknown) {
    const bytes =
      typeof value === "string"
        ? new TextEncoder().encode(value)
        : new TextEncoder().encode(JSON.stringify(value));
    this.values.set(key, { bytes, customMetadata: {} });
  }

  object(key: string, stored: Stored) {
    return {
      key,
      size: stored.bytes.byteLength,
      customMetadata: stored.customMetadata,
      json: async () => JSON.parse(new TextDecoder().decode(stored.bytes)),
      arrayBuffer: async () => stored.bytes.slice().buffer,
    };
  }

  async get(key: string) {
    const stored = this.values.get(key);
    return stored ? this.object(key, stored) : null;
  }

  async head(key: string) {
    return this.get(key);
  }

  async put(
    key: string,
    value: ArrayBuffer | ArrayBufferView | string,
    options?: R2PutOptions,
  ) {
    if (
      options?.onlyIf &&
      "etagDoesNotMatch" in options.onlyIf &&
      options.onlyIf.etagDoesNotMatch === "*" &&
      this.values.has(key)
    ) {
      return null;
    }
    const bytes =
      typeof value === "string"
        ? new TextEncoder().encode(value)
        : ArrayBuffer.isView(value)
          ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength).slice()
          : new Uint8Array(value).slice();
    this.values.set(key, {
      bytes,
      customMetadata: options?.customMetadata ?? {},
    });
    return this.object(key, this.values.get(key)!);
  }

  asEnv(): Env {
    return { STRUCTURED_BUCKET: this as unknown as R2Bucket } as Env;
  }
}

describe("durable personal job state", () => {
  it("returns SUBMITTED as PENDING and never fetches a Container", async () => {
    const mem = new MemoryR2();
    const env = mem.asEnv();
    const getByName = vi.fn();
    env.PERSONAL_RESEARCH_CONTAINER = {
      getByName,
    } as unknown as Env["PERSONAL_RESEARCH_CONTAINER"];
    const document = submittedStateDocument({
      jobId: "job-pending",
      requestDigest: DIGEST_A,
      kind: "research",
      deploymentId: "deploy-1",
      now: new Date("2026-08-30T00:00:00.000Z"),
    });
    expect(await writeSubmittedState(env, document)).toBeNull();
    const response = await durablePersonalJobStatus(
      env,
      "research",
      "job-pending",
      new Date("2026-08-30T00:01:00.000Z"),
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      durable: true,
      job: { job_id: "job-pending", status: "PENDING", request_digest: DIGEST_A },
    });
    expect(getByName).not.toHaveBeenCalled();
  });

  it("stamps the job-family runner identity on SUBMITTED state", () => {
    expect(
      submittedStateDocument({
        jobId: "svi-one",
        requestDigest: DIGEST_A,
        kind: "svi",
        deploymentId: "deploy-1",
        runnerVersion: PERSONAL_SVI_2023_RUNNER_VERSION,
      }).runner_version,
    ).toBe(PERSONAL_SVI_2023_RUNNER_VERSION);
    expect(
      submittedStateDocument({
        jobId: "overlay-one",
        requestDigest: DIGEST_A,
        kind: "overlay",
        deploymentId: "deploy-1",
        runnerVersion: PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION,
      }).runner_version,
    ).toBe(PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION);
    expect(
      submittedStateDocument({
        jobId: "overlay-am-pm-one",
        requestDigest: DIGEST_A,
        kind: "overlay",
        cohortId: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
        deploymentId: "deploy-1",
        runnerVersion: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION,
      }),
    ).toMatchObject({
      runner_version: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION,
      cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
    });
    expect(
      submittedStateDocument({
        jobId: "research-one",
        requestDigest: DIGEST_A,
        kind: "research",
        deploymentId: "deploy-1",
      }).runner_version,
    ).toBe(PERSONAL_RESEARCH_RUNNER_VERSION);
    expect(
      submittedStateDocument({
        jobId: "vol-panel-one",
        requestDigest: DIGEST_A,
        kind: "vol-panel",
        deploymentId: "deploy-1",
        runnerVersion: PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
      }).runner_version,
    ).toBe("personal-cloud-runner/v14");
    expect(
      submittedStateDocument({
        jobId: "sidecar-one",
        requestDigest: DIGEST_A,
        kind: "option-sidecar",
        deploymentId: "deploy-1",
        runnerVersion: PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
      }).runner_version,
    ).toBe("personal-cloud-runner/v14");
  });

  it("conflicts when the same job id carries a different request digest", async () => {
    const mem = new MemoryR2();
    const env = mem.asEnv();
    const first = submittedStateDocument({
      jobId: "job-conflict",
      requestDigest: DIGEST_A,
      kind: "snapshot",
      deploymentId: "deploy-1",
    });
    expect(await writeSubmittedState(env, first)).toBeNull();
    const conflict = await writeSubmittedState(env, {
      ...first,
      request_digest: DIGEST_B,
    });
    expect(conflict?.status).toBe(409);
  });

  it("finalizes an expired marker to a create-only FAILED terminal", async () => {
    const mem = new MemoryR2();
    const env = mem.asEnv();
    const getByName = vi.fn();
    env.PERSONAL_RESEARCH_CONTAINER = {
      getByName,
    } as unknown as Env["PERSONAL_RESEARCH_CONTAINER"];
    mem.seed(personalJobStateKey("snapshot", "job-expired"), {
      job_id: "job-expired",
      request_digest: DIGEST_A,
      kind: "snapshot",
      status: "SUBMITTED",
      submitted_at: "2026-08-30T00:00:00.000Z",
      expires_at: "2026-08-30T00:01:00.000Z",
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      deployment_id: "deploy-1",
    });
    const response = await durablePersonalJobStatus(
      env,
      "snapshot",
      "job-expired",
      new Date("2026-08-30T03:01:00.000Z"),
    );
    expect(response.status).toBe(200);
    const body = (await response.json()) as {
      job: { status: string; error: string };
    };
    expect(body.job.status).toBe("FAILED");
    expect(body.job.error).toContain("durable lifetime");
    expect(getByName).not.toHaveBeenCalled();
    const terminal = await mem.get(personalJobTerminalKey("snapshot", "job-expired"));
    expect(terminal).not.toBeNull();
  });

  it("finalizes an expired vol-panel marker to the panel-writer FAILED schema", async () => {
    const mem = new MemoryR2();
    const env = mem.asEnv();
    env.PERSONAL_RESEARCH_CONTAINER = {
      getByName: vi.fn(),
    } as unknown as Env["PERSONAL_RESEARCH_CONTAINER"];
    mem.seed(personalJobStateKey("vol-panel", "job-expired-panel"), {
      job_id: "job-expired-panel",
      request_digest: DIGEST_A,
      kind: "vol-panel",
      status: "SUBMITTED",
      submitted_at: "2026-08-30T00:00:00.000Z",
      expires_at: "2026-08-30T00:01:00.000Z",
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      deployment_id: "deploy-1",
    });
    const response = await durablePersonalJobStatus(
      env,
      "vol-panel",
      "job-expired-panel",
      new Date("2026-08-30T03:01:00.000Z"),
    );
    expect(await response.json()).toMatchObject({
      job: {
        status: "FAILED",
        schema_version: "personal-vol-ratio-am-pm-panel-writer-manifest/v1",
        producer_id: "personal-vol-ratio-am-pm-panel-writer/v1",
        kind: "vol-panel",
      },
    });
  });

  it("finalizes an expired option-sidecar marker to the producer FAILED schema", async () => {
    const mem = new MemoryR2();
    const env = mem.asEnv();
    env.PERSONAL_RESEARCH_CONTAINER = {
      getByName: vi.fn(),
    } as unknown as Env["PERSONAL_RESEARCH_CONTAINER"];
    mem.seed(personalJobStateKey("option-sidecar", "job-expired-sidecar"), {
      job_id: "job-expired-sidecar",
      request_digest: DIGEST_A,
      kind: "option-sidecar",
      status: "SUBMITTED",
      submitted_at: "2026-08-30T00:00:00.000Z",
      expires_at: "2026-08-30T00:01:00.000Z",
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      deployment_id: "deploy-1",
    });
    const response = await durablePersonalJobStatus(
      env,
      "option-sidecar",
      "job-expired-sidecar",
      new Date("2026-08-30T03:01:00.000Z"),
    );
    expect(await response.json()).toMatchObject({
      job: {
        status: "FAILED",
        schema_version: "personal-n225-option-sidecar-manifest/v1",
        producer_id: "personal-n225-option-sidecar-producer/v1",
        kind: "option-sidecar",
      },
    });
  });

  it("reads completed AM/PM overlay terminals from their exact family paths", async () => {
    const mem = new MemoryR2();
    const env = mem.asEnv();
    for (const [jobId, cohortId] of [
      [
        "overlay-am-pm-complete",
        PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
      ],
      [
        "smile-am-pm-complete",
        PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID,
      ],
    ] as const) {
      mem.seed(personalJobTerminalKey("overlay", jobId, cohortId), {
        job_id: jobId,
        cohort_id: cohortId,
        request_digest: DIGEST_A,
        status: "COMPLETED",
      });
      const response = await durablePersonalJobStatus(env, "overlay", jobId);
      expect(await response.json()).toMatchObject({
        ok: true,
        durable: true,
        job: { job_id: jobId, cohort_id: cohortId, status: "COMPLETED" },
      });
    }
  });

  it("finalizes an expired AM/PM overlay in its exact family path", async () => {
    const mem = new MemoryR2();
    const env = mem.asEnv();
    const jobId = "overlay-am-pm-expired";
    const cohortId = PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID;
    mem.seed(personalJobStateKey("overlay", jobId), {
      job_id: jobId,
      request_digest: DIGEST_A,
      kind: "overlay",
      cohort_id: cohortId,
      status: "SUBMITTED",
      submitted_at: "2026-08-30T00:00:00.000Z",
      expires_at: "2026-08-30T00:01:00.000Z",
      runner_version: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION,
      deployment_id: "deploy-1",
    });
    const response = await durablePersonalJobStatus(
      env,
      "overlay",
      jobId,
      new Date("2026-08-30T03:01:00.000Z"),
    );
    expect(await response.json()).toMatchObject({
      ok: false,
      durable: true,
      job: {
        status: "FAILED",
        schema_version: "personal-index-vol-overlay-am-pm-manifest/v1",
        cohort_id: cohortId,
      },
    });
    expect(
      await mem.get(personalJobTerminalKey("overlay", jobId, cohortId)),
    ).not.toBeNull();
    expect(await mem.get(personalJobTerminalKey("overlay", jobId))).toBeNull();
  });

  it("recovers all four overlay families from pre-cohort runner state", async () => {
    for (const [slug, cohortId, runnerVersion, schemaVersion] of [
      [
        "legacy-vol",
        PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
        PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION,
        "personal-index-vol-overlay-manifest/v1",
      ],
      [
        "legacy-smile",
        PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID,
        PERSONAL_INDEX_SMILE_TRANSPORT_2023_RUNNER_VERSION,
        "personal-index-smile-transport-manifest/v2",
      ],
      [
        "am-pm-vol",
        PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
        PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION,
        "personal-index-vol-overlay-am-pm-manifest/v1",
      ],
      [
        "am-pm-smile",
        PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID,
        PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_RUNNER_VERSION,
        "personal-index-smile-transport-am-pm-manifest/v1",
      ],
    ] as const) {
      const mem = new MemoryR2();
      const env = mem.asEnv();
      const jobId = `overlay-expired-${slug}`;
      mem.seed(personalJobStateKey("overlay", jobId), {
        job_id: jobId,
        request_digest: DIGEST_A,
        kind: "overlay",
        status: "SUBMITTED",
        submitted_at: "2026-08-30T00:00:00.000Z",
        expires_at: "2026-08-30T00:01:00.000Z",
        runner_version: runnerVersion,
        deployment_id: "deploy-1",
      });
      const response = await durablePersonalJobStatus(
        env,
        "overlay",
        jobId,
        new Date("2026-08-30T03:01:00.000Z"),
      );
      expect(await response.json()).toMatchObject({
        job: {
          status: "FAILED",
          schema_version: schemaVersion,
          cohort_id: cohortId,
        },
      });
      expect(
        await mem.get(personalJobTerminalKey("overlay", jobId, cohortId)),
      ).not.toBeNull();
    }
  });

  it("keeps the generic timeout shape when an old overlay family is unknowable", async () => {
    const mem = new MemoryR2();
    const env = mem.asEnv();
    const jobId = "overlay-expired-unknown-runner";
    mem.seed(personalJobStateKey("overlay", jobId), {
      job_id: jobId,
      request_digest: DIGEST_A,
      kind: "overlay",
      status: "SUBMITTED",
      submitted_at: "2026-08-30T00:00:00.000Z",
      expires_at: "2026-08-30T00:01:00.000Z",
      runner_version: "unknown-overlay-runner/v0",
      deployment_id: "deploy-1",
    });
    const response = await durablePersonalJobStatus(
      env,
      "overlay",
      jobId,
      new Date("2026-08-30T03:01:00.000Z"),
    );
    const body = (await response.json()) as { job: Record<string, unknown> };
    expect(body.job).toMatchObject({ status: "FAILED" });
    expect(body.job).not.toHaveProperty("schema_version");
    expect(body.job).not.toHaveProperty("cohort_id");
    expect(await mem.get(personalJobTerminalKey("overlay", jobId))).not.toBeNull();
  });

  it("does not overwrite an existing terminal when expiry races with completion", async () => {
    const mem = new MemoryR2();
    const env = mem.asEnv();
    mem.seed(personalJobStateKey("research", "job-raced"), {
      job_id: "job-raced",
      request_digest: DIGEST_A,
      kind: "research",
      status: "SUBMITTED",
      submitted_at: "2026-08-30T00:00:00.000Z",
      expires_at: "2026-08-30T00:01:00.000Z",
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      deployment_id: "deploy-1",
    });
    mem.seed(personalJobTerminalKey("research", "job-raced"), {
      job_id: "job-raced",
      request_digest: DIGEST_A,
      status: "COMPLETED",
    });
    const response = await durablePersonalJobStatus(
      env,
      "research",
      "job-raced",
      new Date("2026-08-30T03:01:00.000Z"),
    );
    expect(await response.json()).toMatchObject({
      ok: true,
      job: { status: "COMPLETED" },
    });
    const terminal = await mem.get(personalJobTerminalKey("research", "job-raced"));
    expect(await terminal!.json()).toMatchObject({ status: "COMPLETED" });
  });
});
