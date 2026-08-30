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
  PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS,
  PERSONAL_RESEARCH_RUNNER_VERSION,
  type PersonalResearchRequest,
  personalJobContainerName,
} from "./personal_research_contract";
import { parsePersonalResearchBatchRequest } from "./personal_research_batch";
import {
  submitPersonalResearch,
  submitPersonalResearchJobs,
} from "./personal_research_container";
import type { Env } from "./types";

const SHA = "a".repeat(64);

function job(jobId: string): PersonalResearchRequest {
  return {
    cohort_id: "diverse-core-v1",
    job_id: jobId,
    snapshot_key: `research/personal/snapshots/sha256=${SHA}.sqlite.gz`,
    snapshot_sha256: SHA,
    period_start: "2022-04-19",
    period_end: "2024-12-31",
    universe_id: "topix_all",
  };
}

function ready(): Response {
  const body = JSON.stringify({
    ok: true,
    service: PERSONAL_RESEARCH_RUNNER_VERSION,
  });
  return new Response(body, {
    status: 200,
    headers: { "content-length": String(new TextEncoder().encode(body).byteLength) },
  });
}

describe("personal research bounded batch", () => {
  it("accepts eight unique jobs and rejects nine before dispatch", () => {
    const eight = parsePersonalResearchBatchRequest({
      jobs: Array.from({ length: 8 }, (_, index) => job(`job-${index}`)),
    });
    expect(eight.ok).toBe(true);
    const nine = parsePersonalResearchBatchRequest({
      jobs: Array.from({ length: 9 }, (_, index) => job(`job-${index}`)),
    });
    expect(nine.ok).toBe(false);
    if (nine.ok) throw new Error("expected rejection");
    expect(nine.error).toContain(String(PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS));
  });

  it("isolates job-scoped names and keeps one failure from cancelling another", async () => {
    const first = job("batch-one");
    const second = job("batch-two");
    const fetch = vi.fn(async (request: Request) => {
      if (new URL(request.url).pathname === "/ready") return ready();
      const body = (await request.clone().json()) as { job_id?: string };
      if (body.job_id === "batch-two") {
        return new Response(JSON.stringify({ error: "boom" }), { status: 500 });
      }
      return new Response(JSON.stringify({ accepted: true }), { status: 202 });
    });
    const getByName = vi.fn(() => ({ destroy: vi.fn(), fetch }));
    const env = {
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => null),
        head: vi.fn(async () => ({ size: 1024 })),
      },
      PERSONAL_RESEARCH_CONTAINER: { getByName },
    } as unknown as Env;

    const results = await submitPersonalResearchJobs(env, [first, second]);
    expect(results.map((item) => item.state)).toEqual(["accepted", "rejected"]);
    expect(getByName).toHaveBeenCalledWith(
      await personalJobContainerName("research", "batch-one"),
    );
    expect(getByName).toHaveBeenCalledWith(
      await personalJobContainerName("research", "batch-two"),
    );
    expect(getByName.mock.calls.map((call) => call[0])).not.toContain(
      "personal-research-v12",
    );
  });

  it("keeps exact-four on one Container per job", async () => {
    const request = job("exact-four-one");
    const fetch = vi.fn(async (incoming: Request) =>
      new URL(incoming.url).pathname === "/ready"
        ? ready()
        : new Response(JSON.stringify({ accepted: true, exact_four: true }), {
            status: 202,
          }),
    );
    const getByName = vi.fn(() => ({ destroy: vi.fn(), fetch }));
    const env = {
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => null),
        head: vi.fn(async () => ({ size: 2048 })),
      },
      PERSONAL_RESEARCH_CONTAINER: { getByName },
    } as unknown as Env;
    const response = await submitPersonalResearch(env, request);
    expect(response.status).toBe(202);
    expect(getByName).toHaveBeenCalledOnce();
    const posted = fetch.mock.calls.find(
      (call) => new URL((call[0] as Request).url).pathname === "/v1/run",
    )?.[0] as Request;
    expect(await posted.json()).toMatchObject({
      cohort_id: "diverse-core-v1",
      job_id: "exact-four-one",
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
    });
  });
});
