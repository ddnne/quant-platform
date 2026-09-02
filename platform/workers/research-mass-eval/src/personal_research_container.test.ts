import { describe, expect, it, vi } from "vitest";

const containerRegistry = vi.hoisted(() => ({
  outboundByHost: undefined as
    | Record<string, (...args: never[]) => unknown>
    | undefined,
  outboundHandlers: undefined as
    | Record<string, (...args: never[]) => unknown>
    | undefined,
}));

vi.mock("@cloudflare/containers", () => ({
  Container: class {
    schedules: Array<{ when: number; callback: string; payload: unknown }> = [];
    scheduleHistory: number[] = [];
    removedHosts: string[] = [];
    outboundClearCount = 0;
    destroyCount = 0;
    scheduleFailures = 0;
    outboundClearFailures = 0;
    destroyFailures = 0;

    async schedule(when: number, callback: string, payload: unknown) {
      if (this.scheduleFailures > 0) {
        this.scheduleFailures -= 1;
        throw new Error("schedule unavailable");
      }
      const item = { when, callback, payload };
      this.schedules.push(item);
      this.scheduleHistory.push(when);
      return item;
    }

    deleteSchedules(callback: string) {
      this.schedules = this.schedules.filter((item) => item.callback !== callback);
    }

    async removeOutboundByHost(host: string) {
      this.removedHosts.push(host);
    }

    async setOutboundByHosts(handlers: Record<string, unknown>) {
      if (this.outboundClearFailures > 0) {
        this.outboundClearFailures -= 1;
        throw new Error("outbound refresh unavailable");
      }
      if (Object.keys(handlers).length === 0) this.outboundClearCount += 1;
    }

    async destroy() {
      if (this.destroyFailures > 0) {
        this.destroyFailures -= 1;
        throw new Error("destroy unavailable");
      }
      this.destroyCount += 1;
    }

    static get outboundByHost() {
      return containerRegistry.outboundByHost;
    }

    static set outboundByHost(
      value: Record<string, (...args: never[]) => unknown>,
    ) {
      containerRegistry.outboundByHost = value;
    }

    static get outboundHandlers() {
      return containerRegistry.outboundHandlers;
    }

    static set outboundHandlers(
      value: Record<string, (...args: never[]) => unknown>,
    ) {
      containerRegistry.outboundHandlers = value;
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
import * as controlledPilot from "./controlled_pilot";
import {
  PersonalResearchContainer,
  submitPersonalResearch,
} from "./personal_research_container";
import { personalResearchR2Outbound } from "./personal_research_r2";
import type { Env } from "./types";

const SHA = "a".repeat(64);
const REQUEST: PersonalResearchRequest = {
  cohort_id: "diverse-core-am-pm-v1",
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

function controlledStorage() {
  const values = new Map<string, unknown>();
  return {
    values,
    storage: {
      get: async (key: string) => values.get(key),
      put: async (key: string, value: unknown) => { values.set(key, value); },
      delete: async (keys: string | string[]) => {
        for (const key of Array.isArray(keys) ? keys : [keys]) values.delete(key);
      },
    },
  };
}

type ControlledSchedule = {
  when: number;
  callback: string;
  payload: { job_id: string; next_due: number };
};

function takeActiveControlledSchedule(
  container: PersonalResearchContainer & { schedules: ControlledSchedule[] },
  values: Map<string, unknown>,
): ControlledSchedule {
  const activeDue = values.get("controlled_resume_next_due");
  const index = container.schedules.findIndex(
    (item) => item.payload.next_due === activeDue,
  );
  if (index < 0) throw new Error("missing active controlled schedule");
  return container.schedules.splice(index, 1)[0]!;
}

describe("personal research Container admission", () => {
  it("registers the private R2 handler through the Container base setter", () => {
    expect(containerRegistry.outboundByHost?.["research.r2"]).toBe(
      personalResearchR2Outbound,
    );
    expect(containerRegistry.outboundByHost?.["history.source"]).toBe(
      personalHistorySourceOutbound,
    );
    expect(containerRegistry.outboundByHost?.["controlled.r2"]).toBeDefined();
    expect(containerRegistry.outboundHandlers?.controlledPilotSnapshot).toBeDefined();
    expect(containerRegistry.outboundHandlers?.controlledPilotWriter).toBeDefined();
    expect(new PersonalResearchContainer().enableInternet).toBe(false);
    expect(
      Object.prototype.hasOwnProperty.call(
        PersonalResearchContainer,
        "outboundByHost",
      ),
    ).toBe(false);
  });

  it("uses the SDK scheduler and preserves one bounded controlled deadline", async () => {
    const { values, storage } = controlledStorage();
    const container = new PersonalResearchContainer();
    Object.assign(container as object, { ctx: { storage }, env: {} });
    const clock = vi.spyOn(Date, "now").mockReturnValue(1_000_000);

    await container.scheduleControlledPilot("controlled-job-schedule");
    const firstDeadline = values.get("controlled_resume_deadline");
    clock.mockReturnValue(1_001_000);
    await container.scheduleControlledPilot("controlled-job-schedule");

    const scheduled = (container as unknown as {
      schedules: ControlledSchedule[];
    }).schedules;
    expect(Object.prototype.hasOwnProperty.call(PersonalResearchContainer.prototype, "alarm")).toBe(false);
    expect(firstDeadline).toBe(values.get("controlled_resume_deadline"));
    expect(scheduled).toEqual([
      {
        when: 5,
        callback: "resumeControlledPilot",
        payload: { job_id: "controlled-job-schedule", next_due: 1_005_000 },
      },
      {
        when: 65,
        callback: "resumeControlledPilot",
        payload: { job_id: "controlled-job-schedule", next_due: 1_005_000 },
      },
    ]);
    const run = vi.spyOn(controlledPilot, "runControlledPilotJob").mockResolvedValue();
    let polls = 0;
    const status = vi.spyOn(controlledPilot, "controlledPilotStatus").mockImplementation(async () => {
      polls += 1;
      const phase = polls <= 13 ? "SUBMITTED" : polls === 14 ? "FINALIZE_RETRY" : "COMPLETED";
      return Response.json({ status: phase }, { status: phase === "COMPLETED" ? 200 : 202 });
    });
    for (let index = 0; index < 15; index += 1) {
      const active = takeActiveControlledSchedule(
        container as PersonalResearchContainer & { schedules: ControlledSchedule[] },
        values,
      );
      clock.mockReturnValue(active.payload.next_due);
      await container.resumeControlledPilot(active.payload);
    }
    expect(run).toHaveBeenCalledTimes(15);
    expect(status).toHaveBeenCalledTimes(15);
    expect(values.has("controlled_resume_deadline")).toBe(false);
    expect((container as unknown as { schedules: unknown[] }).schedules).toHaveLength(0);
    expect((container as unknown as { scheduleHistory: number[] }).scheduleHistory).toContain(60);
    expect((container as unknown as { outboundClearCount: number }).outboundClearCount).toBeGreaterThan(0);
    clock.mockRestore();
  });

  it("recovers a failed initial schedule on replay without moving a live due time", async () => {
    const { values, storage } = controlledStorage();
    const container = new PersonalResearchContainer() as PersonalResearchContainer & {
      scheduleFailures: number;
      schedules: Array<{ payload: { next_due: number } }>;
    };
    Object.assign(container as object, { ctx: { storage }, env: {} });
    const clock = vi.spyOn(Date, "now").mockReturnValue(1_000_000);
    container.scheduleFailures = 4;

    await expect(container.scheduleControlledPilot("controlled-job-recover")).rejects.toThrow(
      "controlled resume scheduler unavailable",
    );
    expect(values.has("controlled_resume_next_due")).toBe(false);
    container.scheduleFailures = 0;
    await container.scheduleControlledPilot("controlled-job-recover");
    const due = values.get("controlled_resume_next_due");
    expect(container.schedules).toHaveLength(2);

    clock.mockReturnValue(Number(due) + 30_000);
    await container.scheduleControlledPilot("controlled-job-recover");
    expect(container.schedules).toHaveLength(2);
    expect(values.get("controlled_resume_next_due")).toBe(due);
    clock.mockRestore();
  });

  it("prearms a same-generation watchdog before awaiting controlled work", async () => {
    const { values, storage } = controlledStorage();
    const container = new PersonalResearchContainer() as PersonalResearchContainer & {
      schedules: ControlledSchedule[];
    };
    Object.assign(container as object, { ctx: { storage }, env: {} });
    const clock = vi.spyOn(Date, "now").mockReturnValue(1_000_000);
    await container.scheduleControlledPilot("controlled-job-watchdog");
    const first = takeActiveControlledSchedule(container, values);
    const generation = first.payload.next_due;
    let releaseRun: (() => void) | undefined;
    const blockedRun = new Promise<void>((resolve) => { releaseRun = resolve; });
    vi.spyOn(controlledPilot, "runControlledPilotJob").mockReturnValue(blockedRun);
    vi.spyOn(controlledPilot, "controlledPilotStatus").mockResolvedValue(
      Response.json({ status: "SUBMITTED" }, { status: 202 }),
    );
    clock.mockReturnValue(generation);

    const resumed = container.resumeControlledPilot(first.payload);
    await vi.waitFor(() => {
      expect(
        container.schedules.filter((item) => item.payload.next_due === generation),
      ).toHaveLength(2);
    });
    expect(values.get("controlled_resume_next_due")).toBe(generation);

    releaseRun?.();
    await resumed;
    expect(values.get("controlled_resume_next_due")).not.toBe(generation);
    clock.mockRestore();
  });

  it("keeps cleanup durable until the container is destroyed and outbound is atomically cleared", async () => {
    const { values, storage } = controlledStorage();
    const container = new PersonalResearchContainer() as PersonalResearchContainer & {
      outboundClearFailures: number;
      destroyCount: number;
      schedules: Array<{ payload: { job_id: string; next_due: number } }>;
    };
    Object.assign(container as object, { ctx: { storage }, env: {} });
    const clock = vi.spyOn(Date, "now").mockReturnValue(1_000_000);
    const expire = vi.spyOn(controlledPilot, "expireControlledPilotJob").mockResolvedValue();
    await container.scheduleControlledPilot("controlled-job-cleanup");
    const first = takeActiveControlledSchedule(container, values);
    clock.mockReturnValue(1_000_000 + 180 * 60 * 1_000);
    container.outboundClearFailures = 2;

    await container.resumeControlledPilot(first.payload);
    expect(values.get("controlled_job_id")).toBe("controlled-job-cleanup");
    expect(container.destroyCount).toBe(1);
    expect(
      container.schedules.some(
        (item) => item.payload.next_due === values.get("controlled_resume_next_due"),
      ),
    ).toBe(true);

    const retry = takeActiveControlledSchedule(container, values);
    clock.mockReturnValue(retry.payload.next_due);
    await container.resumeControlledPilot(retry.payload);
    expect(values.has("controlled_job_id")).toBe(false);
    expect(container.destroyCount).toBe(2);
    expect(expire).toHaveBeenCalledTimes(2);
    expire.mockRestore();
    clock.mockRestore();
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
        "sha256:0c9fc5cba93c68cbfec3951a56f09949674c1a01cb4d4d4cf406082c01033c10",
      cohort_id: "diverse-core-am-pm-v1",
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      snapshot_key: REQUEST.snapshot_key,
      snapshot_sha256: SHA,
      universe_id: "topix500",
      universe_rule_digest:
        "sha256:8ca72cf8c134ad082605fd948cf005b73124643b106a68521174b009442046fb",
    });
  });

  it("forwards an AM request with exact schema, mode digest, and v15 runner", async () => {
    const request: PersonalResearchRequest = {
      ...REQUEST,
      cohort_id: "diverse-core-am-pm-v1",
      job_id: "am-core-container",
    };
    const { env, containerFetch } = testEnv(205 * 1024 * 1024);
    const response = await submitPersonalResearch(env, request);
    expect(response.status).toBe(202);
    const forwarded = containerFetch.mock.calls[1]?.[0] as Request;
    expect(new URL(forwarded.url).pathname).toBe("/v1/run");
    expect(await forwarded.json()).toMatchObject({
      cohort_digest:
        "sha256:0c9fc5cba93c68cbfec3951a56f09949674c1a01cb4d4d4cf406082c01033c10",
      cohort_id: "diverse-core-am-pm-v1",
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      universe_id: "topix500",
      universe_rule_digest:
        "sha256:8ca72cf8c134ad082605fd948cf005b73124643b106a68521174b009442046fb",
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
