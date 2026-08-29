import { describe, expect, it, vi } from "vitest";

vi.mock("@cloudflare/containers", () => ({
  Container: class {},
  ContainerProxy: class {},
}));

import {
  PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES,
  type PersonalResearchRequest,
} from "./personal_research_contract";
import { submitPersonalResearch } from "./personal_research_container";
import type { Env } from "./types";

const SHA = "a".repeat(64);
const REQUEST: PersonalResearchRequest = {
  job_id: "exact-four-container",
  snapshot_key: `research/personal/snapshots/sha256=${SHA}.sqlite`,
  snapshot_sha256: SHA,
  period_start: "2022-04-19",
  period_end: "2026-08-27",
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
  });
});
