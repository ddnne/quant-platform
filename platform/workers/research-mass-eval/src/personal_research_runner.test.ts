import { describe, expect, it, vi } from "vitest";

import { PERSONAL_RESEARCH_RUNNER_VERSION } from "./personal_research_contract";
import { verifiedPersonalResearchContainer } from "./personal_research_runner";
import type { Env } from "./types";

const RUNNER_NAME = "personal-v13-research-exact-four-test";

function readyResponse(service: string): Response {
  const body = JSON.stringify({ ok: true, service });
  return new Response(body, {
    status: 200,
    headers: {
      "content-length": String(new TextEncoder().encode(body).byteLength),
      "content-type": "application/json; charset=utf-8",
    },
  });
}

function runnerStub(service: string) {
  const destroy = vi.fn(async () => undefined);
  const fetch = vi.fn(async () => readyResponse(service));
  return { destroy, fetch };
}

function runnerEnv(...stubs: Array<ReturnType<typeof runnerStub>>) {
  const getByName = vi.fn();
  for (const stub of stubs) getByName.mockReturnValueOnce(stub);
  return {
    env: {
      PERSONAL_RESEARCH_CONTAINER: { getByName },
    } as unknown as Env,
    getByName,
  };
}

describe("personal research runner identity gate", () => {
  it("admits the exact runner without destroying it", async () => {
    const current = runnerStub(PERSONAL_RESEARCH_RUNNER_VERSION);
    const { env, getByName } = runnerEnv(current);

    await expect(verifiedPersonalResearchContainer(env, RUNNER_NAME)).resolves.toBe(current);

    expect(getByName).toHaveBeenCalledOnce();
    expect(getByName).toHaveBeenCalledWith(RUNNER_NAME);
    expect(getByName).not.toHaveBeenCalledWith("personal-research-v12");
    expect(current.destroy).not.toHaveBeenCalled();
  });

  it("replaces one positively identified old runner before admission", async () => {
    const old = runnerStub("personal-cloud-runner/v6");
    const current = runnerStub(PERSONAL_RESEARCH_RUNNER_VERSION);
    const { env, getByName } = runnerEnv(old, current);

    await expect(verifiedPersonalResearchContainer(env, RUNNER_NAME)).resolves.toBe(current);

    expect(getByName).toHaveBeenCalledTimes(2);
    expect(old.destroy).toHaveBeenCalledOnce();
    expect(current.destroy).not.toHaveBeenCalled();
  });

  it("fails closed after one replacement when a positive mismatch persists", async () => {
    const old = runnerStub("personal-cloud-runner/v6");
    const staleReplacement = runnerStub("personal-cloud-runner/v6");
    const { env } = runnerEnv(old, staleReplacement);

    await expect(verifiedPersonalResearchContainer(env, RUNNER_NAME)).rejects.toThrow(
      "runner identity mismatch persisted after one replacement",
    );

    expect(old.destroy).toHaveBeenCalledOnce();
    expect(staleReplacement.destroy).toHaveBeenCalledOnce();
  });

  it("does not destroy a runner when the first identity probe is unknown", async () => {
    const destroy = vi.fn(async () => undefined);
    const fetch = vi.fn(
      async () => new Response("temporarily unavailable", { status: 503 }),
    );
    const getByName = vi.fn(() => ({ destroy, fetch }));
    const env = {
      PERSONAL_RESEARCH_CONTAINER: { getByName },
    } as unknown as Env;

    await expect(verifiedPersonalResearchContainer(env, RUNNER_NAME)).rejects.toThrow(
      "runner readiness unknown: probe returned HTTP 503",
    );

    expect(getByName).toHaveBeenCalledOnce();
    expect(destroy).not.toHaveBeenCalled();
  });

  it("does not destroy a replacement whose reprobe is unknown", async () => {
    const old = runnerStub("personal-cloud-runner/v6");
    const replacementDestroy = vi.fn(async () => undefined);
    const replacementFetch = vi.fn(
      async () => new Response("starting", { status: 503 }),
    );
    const replacement = {
      destroy: replacementDestroy,
      fetch: replacementFetch,
    };
    const { env } = runnerEnv(old, replacement);

    await expect(verifiedPersonalResearchContainer(env, RUNNER_NAME)).rejects.toThrow(
      "runner readiness reprobe unknown: probe returned HTTP 503",
    );

    expect(old.destroy).toHaveBeenCalledOnce();
    expect(replacementDestroy).not.toHaveBeenCalled();
  });
});
