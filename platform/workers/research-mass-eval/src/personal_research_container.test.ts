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
  PERSONAL_RESEARCH_LEGACY_CONTAINER_NAME,
  PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES,
  PERSONAL_RESEARCH_RUNNER_VERSION,
  type PersonalResearchRequest,
  personalJobContainerName,
} from "./personal_research_contract";
import { personalHistorySourceOutbound } from "./personal_history_source";
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
  snapshot_key: `research/personal/snapshots/sha256=${SHA}.sqlite.gz`,
  snapshot_sha256: SHA,
  period_start: "2022-04-19",
  period_end: "2026-08-27",
  universe_id: "topix500",
};

function snapshot(size: number): R2Object {
  return { size } as R2Object;
}

function runnerReadyResponse(
  service = PERSONAL_RESEARCH_RUNNER_VERSION,
): Response {
  const body = JSON.stringify({ ok: true, service });
  return new Response(body, {
    status: 200,
    headers: {
      "content-length": String(new TextEncoder().encode(body).byteLength),
      "content-type": "application/json; charset=utf-8",
    },
  });
}

function testEnv(
  snapshotSize: number | null,
  options: {
    ready?: () => Response | Promise<Response>;
    post?: () => Response | Promise<Response>;
  } = {},
): {
  env: Env;
  containerByName: ReturnType<typeof vi.fn>;
  containerDestroy: ReturnType<typeof vi.fn>;
  containerFetch: ReturnType<typeof vi.fn>;
} {
  const containerFetch = vi.fn(async (request: Request) =>
    new URL(request.url).pathname === "/ready"
      ? (options.ready?.() ?? runnerReadyResponse())
      : (options.post?.() ??
        new Response('{"accepted":true}', { status: 202 })),
  );
  const containerDestroy = vi.fn(async () => undefined);
  const containerByName = vi.fn(() => ({
    destroy: containerDestroy,
    fetch: containerFetch,
  }));
  return {
    env: {
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => null),
        head: vi.fn(async () =>
          snapshotSize === null ? null : snapshot(snapshotSize),
        ),
        put: vi.fn(async (key: string) => ({ key })),
      } as unknown as R2Bucket,
      PERSONAL_RESEARCH_CONTAINER: {
        getByName: containerByName,
      } as unknown as Env["PERSONAL_RESEARCH_CONTAINER"],
    } as Env,
    containerByName,
    containerDestroy,
    containerFetch,
  };
}

function routeRunner(
  ready: () => Response | Promise<Response>,
  post = () => new Response('{"accepted":true}', { status: 202 }),
) {
  const destroy = vi.fn(async () => undefined);
  const fetch = vi.fn(async (request: Request) =>
    new URL(request.url).pathname === "/ready" ? ready() : post(),
  );
  return { destroy, fetch };
}

function sequentialRunnerEnv(
  ...runners: Array<ReturnType<typeof routeRunner>>
): { env: Env; containerByName: ReturnType<typeof vi.fn> } {
  const containerByName = vi.fn();
  for (const runner of runners) containerByName.mockReturnValueOnce(runner);
  return {
    env: {
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => null),
        head: vi.fn(async () => snapshot(205 * 1024 * 1024)),
        put: vi.fn(async (key: string) => ({ key })),
      } as unknown as R2Bucket,
      PERSONAL_RESEARCH_CONTAINER: {
        getByName: containerByName,
      } as unknown as Env["PERSONAL_RESEARCH_CONTAINER"],
    } as Env,
    containerByName,
  };
}

describe("personal research Container admission", () => {
  it("registers the private R2 handler through the Container base setter", () => {
    expect(containerRegistry.outboundByHost?.["research.r2"]).toBe(
      personalResearchR2Outbound,
    );
    expect(containerRegistry.outboundByHost?.["history.source"]).toBe(
      personalHistorySourceOutbound,
    );
    expect(new PersonalResearchContainer().enableInternet).toBe(false);
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

  it("fails closed when the Container binding is absent", async () => {
    const { env } = testEnv(205 * 1024 * 1024);
    delete env.PERSONAL_RESEARCH_CONTAINER;

    const response = await submitPersonalResearch(env, REQUEST);

    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({
      error: "personal_research_container_unavailable",
      detail: "PERSONAL_RESEARCH_CONTAINER not bound",
      job_id: REQUEST.job_id,
    });
  });

  it("starts one bounded Container for an admitted snapshot", async () => {
    const { env, containerByName, containerDestroy, containerFetch } = testEnv(
      205 * 1024 * 1024,
    );
    const response = await submitPersonalResearch(env, REQUEST);
    expect(response.status).toBe(202);
    expect(containerByName).toHaveBeenCalledOnce();
    expect(containerByName).toHaveBeenCalledWith(
      await personalJobContainerName("research", REQUEST.job_id),
    );
    expect(containerByName).not.toHaveBeenCalledWith(
      PERSONAL_RESEARCH_LEGACY_CONTAINER_NAME,
    );
    expect(containerFetch).toHaveBeenCalledTimes(2);
    expect(containerDestroy).not.toHaveBeenCalled();
    const ready = containerFetch.mock.calls[0]?.[0] as Request;
    expect(new URL(ready.url).pathname).toBe("/ready");
    const forwarded = containerFetch.mock.calls[1]?.[0];
    expect(forwarded).toBeInstanceOf(Request);
    const body = await (forwarded as Request).json();
    expect(body).toMatchObject({
      cohort_digest:
        "sha256:ea37baf3423e5d84e61d4c80c59bdfe8184342dd3dee28646bd339cd45085a84",
      cohort_id: "diverse-core-v1",
      runner_version: "personal-cloud-runner/v13",
      snapshot_key: REQUEST.snapshot_key,
      snapshot_sha256: SHA,
      universe_id: "topix500",
      universe_rule_digest:
        "sha256:5034530267f4a358a80d9426fcfedfb1162b9f71c1024b54b4b39fe3547d53c6",
    });
  });

  it("preserves an active matching runner when POST reports busy", async () => {
    const { env, containerDestroy, containerFetch } = testEnv(
      205 * 1024 * 1024,
      {
        post: () =>
          new Response('{"error":"container_busy"}', { status: 409 }),
      },
    );

    const response = await submitPersonalResearch(env, REQUEST);

    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ error: "container_busy" });
    expect(containerFetch).toHaveBeenCalledTimes(2);
    expect(containerDestroy).not.toHaveBeenCalled();
  });

  it("fails closed without destroying an accepted runner on a transient readiness failure", async () => {
    const post = vi.fn(() =>
      new Response('{"accepted":true}', { status: 202 }),
    );
    const { env, containerDestroy, containerFetch } = testEnv(
      205 * 1024 * 1024,
      {
        ready: () => new Response("temporarily unavailable", { status: 503 }),
        post,
      },
    );

    const response = await submitPersonalResearch(env, REQUEST);

    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({
      error: "personal_research_container_unavailable",
      detail: "runner readiness unknown: probe returned HTTP 503",
    });
    expect(containerFetch).toHaveBeenCalledOnce();
    expect(post).not.toHaveBeenCalled();
    expect(containerDestroy).not.toHaveBeenCalled();
  });

  it("destroys one positively identified v6 runner, then posts only to v7", async () => {
    const old = routeRunner(() => runnerReadyResponse("personal-cloud-runner/v6"));
    const currentPost = vi.fn(
      () => new Response('{"accepted":true}', { status: 202 }),
    );
    const current = routeRunner(
      () => runnerReadyResponse(PERSONAL_RESEARCH_RUNNER_VERSION),
      currentPost,
    );
    const { env, containerByName } = sequentialRunnerEnv(old, current);

    const response = await submitPersonalResearch(env, REQUEST);

    expect(response.status).toBe(202);
    expect(containerByName).toHaveBeenCalledTimes(2);
    expect(old.destroy).toHaveBeenCalledOnce();
    expect(old.fetch).toHaveBeenCalledOnce();
    expect(current.fetch).toHaveBeenCalledTimes(2);
    expect(currentPost).toHaveBeenCalledOnce();
    expect(current.destroy).not.toHaveBeenCalled();
  });

  it("destroys two positive v6 mismatches and never posts", async () => {
    const first = routeRunner(() =>
      runnerReadyResponse("personal-cloud-runner/v6"),
    );
    const second = routeRunner(() =>
      runnerReadyResponse("personal-cloud-runner/v6"),
    );
    const { env } = sequentialRunnerEnv(first, second);

    const response = await submitPersonalResearch(env, REQUEST);

    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({
      error: "personal_research_container_unavailable",
      detail: "runner identity mismatch persisted after one replacement",
    });
    expect(first.destroy).toHaveBeenCalledOnce();
    expect(second.destroy).toHaveBeenCalledOnce();
    expect(first.fetch).toHaveBeenCalledOnce();
    expect(second.fetch).toHaveBeenCalledOnce();
  });

  it.each([
    [
      "missing content length",
      () =>
        new Response(
          JSON.stringify({
            ok: true,
            service: PERSONAL_RESEARCH_RUNNER_VERSION,
          }),
          { status: 200 },
        ),
    ],
    [
      "malformed JSON",
      () =>
        new Response("{", {
          status: 200,
          headers: { "content-length": "1" },
        }),
    ],
  ])("treats %s as unknown without destroying or posting", async (_label, ready) => {
    const post = vi.fn(
      () => new Response('{"accepted":true}', { status: 202 }),
    );
    const runner = routeRunner(ready, post);
    const { env } = sequentialRunnerEnv(runner);

    const response = await submitPersonalResearch(env, REQUEST);

    expect(response.status).toBe(503);
    expect(runner.fetch).toHaveBeenCalledOnce();
    expect(runner.destroy).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
});
