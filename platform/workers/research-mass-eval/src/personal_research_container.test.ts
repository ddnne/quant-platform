import { describe, expect, it, vi } from "vitest";

const containerRegistry = vi.hoisted(() => ({
  outboundByHost: undefined as
    | Record<string, (...args: never[]) => unknown>
    | undefined,
}));

vi.mock("@cloudflare/containers", () => ({
  Container: class {
    static get outboundByHost() {
      return containerRegistry.outboundByHost;
    }

    static set outboundByHost(
      value: Record<string, (...args: never[]) => unknown>,
    ) {
      containerRegistry.outboundByHost = value;
    }
  },
  ContainerProxy: class {},
}));

import {
  PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES,
  type PersonalResearchRequest,
} from "./personal_research_contract";
import {
  PersonalResearchContainer,
  submitPersonalResearch,
} from "./personal_research_container";
import { personalResearchR2Outbound } from "./personal_research_r2";
import type { Env } from "./types";

const SHA = "a".repeat(64);
const REQUEST: PersonalResearchRequest = {
  cohort_id: "diverse-core-v1",
  job_id: "exact-four-container",
  snapshot_key: `research/personal/snapshots/sha256=${SHA}.sqlite`,
  snapshot_sha256: SHA,
  period_start: "2022-04-19",
  period_end: "2026-08-27",
  universe_id: "topix500",
};

function snapshot(size: number): R2Object {
  return { size } as R2Object;
}

function testEnv(snapshotSize: number | null): {
  env: Env;
  containerFetch: ReturnType<typeof vi.fn>;
} {
  const containerFetch = vi.fn(
    async () => new Response('{"accepted":true}', { status: 202 }),
  );
  return {
    env: {
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => null),
        head: vi.fn(async () =>
          snapshotSize === null ? null : snapshot(snapshotSize),
        ),
      } as unknown as R2Bucket,
      PERSONAL_RESEARCH_CONTAINER: {
        getByName: vi.fn(() => ({ fetch: containerFetch })),
      } as unknown as Env["PERSONAL_RESEARCH_CONTAINER"],
    } as Env,
    containerFetch,
  };
}

describe("personal research Container admission", () => {
  it("registers the private R2 handler through the Container base setter", () => {
    expect(containerRegistry.outboundByHost?.["research.r2"]).toBe(
      personalResearchR2Outbound,
    );
    expect(
      Object.prototype.hasOwnProperty.call(
        PersonalResearchContainer,
        "outboundByHost",
      ),
    ).toBe(false);
  });

  it("rejects a missing snapshot before starting the Container", async () => {
    const { env, containerFetch } = testEnv(null);
    const response = await submitPersonalResearch(env, REQUEST);
    expect(response.status).toBe(404);
    expect(containerFetch).not.toHaveBeenCalled();
  });

  it("rejects a snapshot above the fixed ephemeral-disk bound", async () => {
    const { env, containerFetch } = testEnv(
      PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES + 1,
    );
    const response = await submitPersonalResearch(env, REQUEST);
    expect(response.status).toBe(413);
    expect(containerFetch).not.toHaveBeenCalled();
  });

  it("starts one bounded Container for an admitted snapshot", async () => {
    const { env, containerFetch } = testEnv(2 * 1024 * 1024 * 1024);
    const response = await submitPersonalResearch(env, REQUEST);
    expect(response.status).toBe(202);
    expect(containerFetch).toHaveBeenCalledTimes(1);
    const forwarded = containerFetch.mock.calls[0]?.[0];
    expect(forwarded).toBeInstanceOf(Request);
    const body = await (forwarded as Request).json();
    expect(body).toMatchObject({
      cohort_digest:
        "sha256:ea37baf3423e5d84e61d4c80c59bdfe8184342dd3dee28646bd339cd45085a84",
      cohort_id: "diverse-core-v1",
      runner_version: "personal-cloud-runner/v5",
      universe_id: "topix500",
      universe_rule_digest:
        "sha256:5034530267f4a358a80d9426fcfedfb1162b9f71c1024b54b4b39fe3547d53c6",
    });
  });
});
