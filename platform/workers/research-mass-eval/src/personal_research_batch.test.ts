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

    static outboundHandlers: Record<string, (...args: never[]) => unknown> | undefined;
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
    cohort_id: "diverse-core-am-pm-v1",
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
        put: vi.fn(async (key: string) => ({ key })),
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

  it("keeps a draft factor cohort on one Container per job", async () => {
    const request = job("draft-factor-one");
    const fetch = vi.fn(async (incoming: Request) =>
      new URL(incoming.url).pathname === "/ready"
        ? ready()
        : new Response(
            JSON.stringify({
              accepted: true,
              purpose_id: "draft_factor_cohort_v1",
            }),
            {
              status: 202,
            },
          ),
    );
    const getByName = vi.fn(() => ({ destroy: vi.fn(), fetch }));
    const env = {
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => null),
        head: vi.fn(async () => ({ size: 2048 })),
        put: vi.fn(async (key: string) => ({ key })),
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
      cohort_id: "diverse-core-am-pm-v1",
      job_id: "draft-factor-one",
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
    });
  });

  it("forwards an AM cohort onto the closed /v1/run envelope", async () => {
    const request: PersonalResearchRequest = {
      ...job("am-core-batch"),
      cohort_id: "diverse-core-am-pm-v1",
    };
    const fetch = vi.fn(async (incoming: Request) =>
      new URL(incoming.url).pathname === "/ready"
        ? ready()
        : new Response(JSON.stringify({ accepted: true }), { status: 202 }),
    );
    const getByName = vi.fn(() => ({ destroy: vi.fn(), fetch }));
    const env = {
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => null),
        head: vi.fn(async () => ({ size: 2048 })),
        put: vi.fn(async (key: string) => ({ key })),
      },
      PERSONAL_RESEARCH_CONTAINER: { getByName },
    } as unknown as Env;
    const parsed = parsePersonalResearchBatchRequest({ jobs: [request] });
    expect(parsed.ok).toBe(true);
    const response = await submitPersonalResearch(env, request);
    expect(response.status).toBe(202);
    const posted = fetch.mock.calls.find(
      (call) => new URL((call[0] as Request).url).pathname === "/v1/run",
    )?.[0] as Request;
    expect(await posted.json()).toEqual({
      ...request,
      cohort_digest:
        "sha256:0c9fc5cba93c68cbfec3951a56f09949674c1a01cb4d4d4cf406082c01033c10",
      request_digest: expect.stringMatching(/^sha256:[0-9a-f]{64}$/),
      result_key: `research/personal/jobs/job=${request.job_id}/result.tar.gz`,
      manifest_key: `research/personal/jobs/job=${request.job_id}/manifest.json`,
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      universe_rule_digest:
        "sha256:ba0c9af6b51121e6c27d660ccd28ae3e1a7c8af1ae3ffcff4986bf3f31247fd9",
    });
  });
});
