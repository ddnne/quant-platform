import { describe, expect, it, vi } from "vitest";

vi.mock("@cloudflare/containers", () => ({
  Container: class {},
  ContainerProxy: class {},
}));

import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  PERSONAL_SNAPSHOT_CONTAINER_NAME,
} from "./personal_research_contract";
import { parsePersonalSnapshotBuildRequest } from "./personal_snapshot_contract";
import {
  personalSnapshotBuildStatus,
  submitPersonalSnapshotBuild,
} from "./personal_snapshot";
import type { Env } from "./types";

const NOW = new Date("2026-08-30T03:00:00.000Z");
const REQUEST = parsePersonalSnapshotBuildRequest(
  {
    job_id: "snapshot-one",
    period_start: "2023-01-01",
    period_end: "2024-12-31",
  },
  NOW,
);
if (!REQUEST.ok) throw new Error(REQUEST.error);

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

describe("personal snapshot build dispatch", () => {
  it("is idempotent for the same job and conflicts on digest drift", async () => {
    const manifest = {
      job_id: REQUEST.value.job_id,
      request_digest: await (await import("./personal_snapshot_contract")).personalSnapshotRequestDigest(
        REQUEST.value,
      ),
      status: "COMPLETED",
    };
    const env = {
      ENVIRONMENT: "production",
      JQUANTS_ACQUISITION: { fetch_governed_page: vi.fn() },
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => ({
          size: 100,
          json: async () => manifest,
        })),
      },
      PERSONAL_RESEARCH_CONTAINER: { getByName: vi.fn() },
    } as unknown as Env;
    const first = await submitPersonalSnapshotBuild(env, REQUEST.value);
    expect(first.status).toBe(200);
    expect(await first.json()).toMatchObject({ idempotent: true, ok: true });
    expect(env.PERSONAL_RESEARCH_CONTAINER!.getByName).not.toHaveBeenCalled();

    const conflictEnv = {
      ...env,
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => ({
          size: 100,
          json: async () => ({ ...manifest, request_digest: "sha256:" + "b".repeat(64) }),
        })),
      },
    } as unknown as Env;
    const conflict = await submitPersonalSnapshotBuild(conflictEnv, REQUEST.value);
    expect(conflict.status).toBe(409);
  });

  it("uses the singleton snapshot runner, not a legacy research name", async () => {
    const fetch = vi.fn(async (request: Request) =>
      new URL(request.url).pathname === "/ready"
        ? ready()
        : new Response('{"accepted":true}', { status: 202 }),
    );
    const getByName = vi.fn(() => ({ destroy: vi.fn(), fetch }));
    const env = {
      ENVIRONMENT: "production",
      JQUANTS_ACQUISITION: { fetch_governed_page: vi.fn() },
      CF_VERSION_METADATA: { id: "deploy-1" },
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => null),
        put: vi.fn(async (key: string) => ({ key })),
      },
      PERSONAL_RESEARCH_CONTAINER: { getByName },
    } as unknown as Env;
    const response = await submitPersonalSnapshotBuild(env, REQUEST.value);
    expect(response.status).toBe(202);
    expect(getByName).toHaveBeenCalledWith(PERSONAL_SNAPSHOT_CONTAINER_NAME);
    expect(getByName).not.toHaveBeenCalledWith("personal-research-v12");
  });

  it("reads durable status without downloading a snapshot object", async () => {
    const env = {
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => ({
          size: 80,
          json: async () => ({
            job_id: "snapshot-one",
            status: "FAILED",
            research_state: "PERSONAL_DRAFT",
          }),
        })),
      },
      PERSONAL_RESEARCH_CONTAINER: { getByName: vi.fn() },
    } as unknown as Env;
    const response = await personalSnapshotBuildStatus(env, "snapshot-one");
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      durable: true,
      ok: false,
    });
    expect(env.PERSONAL_RESEARCH_CONTAINER!.getByName).not.toHaveBeenCalled();
  });
});
