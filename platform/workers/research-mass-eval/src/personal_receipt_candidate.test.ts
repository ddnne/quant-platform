import { describe, expect, it, vi } from "vitest";

vi.mock("@cloudflare/containers", () => ({
  Container: class {},
  ContainerProxy: class {},
}));

import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  PERSONAL_SNAPSHOT_CONTAINER_NAME,
} from "./personal_research_contract";
import {
  EXACT_FOUR_PROFILE_ID,
} from "./controlled_pilot_contract";
import {
  parseReceiptCandidateRequest,
} from "./personal_receipt_candidate_contract";
import {
  submitPersonalReceiptCandidate,
} from "./personal_receipt_candidate";
import type { Env } from "./types";

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

const REQUEST = parseReceiptCandidateRequest({
  job_id: "cand-one",
  segments: [{ dataset: "equities_bars_daily", segment_id: "2023-01" }],
});
if (!REQUEST.ok) throw new Error(REQUEST.error);

describe("personal receipt candidate Worker dispatch", () => {
  it("rejects caller environment or extra fields", () => {
    const parsed = parseReceiptCandidateRequest({
      job_id: "cand-one",
      environment: "staging",
      segments: [{ dataset: "equities_bars_daily", segment_id: "2023-01" }],
    });
    expect(parsed.ok).toBe(false);
  });

  it("requires the configured product binding and Worker environment", async () => {
    const env = {
      ENVIRONMENT: "production",
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => null),
        put: vi.fn(async (key: string) => ({ key })),
      },
      PERSONAL_RESEARCH_CONTAINER: { getByName: vi.fn() },
    } as unknown as Env;
    const missing = await submitPersonalReceiptCandidate(env, REQUEST.value);
    expect(missing.status).toBe(503);
    expect(env.PERSONAL_RESEARCH_CONTAINER!.getByName).not.toHaveBeenCalled();
  });

  it("uses the snapshot Container and Worker-filled environment", async () => {
    const fetch = vi.fn(async (request: Request) =>
      new URL(request.url).pathname === "/ready"
        ? ready()
        : new Response('{"accepted":true}', { status: 202 }),
    );
    const getByName = vi.fn(() => ({ destroy: vi.fn(), fetch }));
    const env = {
      ENVIRONMENT: "staging",
      INGESTION_PREMIUM: {
        read_receipt_product_bytes: vi.fn(),
        describe_receipt_product_input: vi.fn(),
      },
      CF_VERSION_METADATA: { id: "deploy-1" },
      STRUCTURED_BUCKET: {
        get: vi.fn(async () => null),
        put: vi.fn(async (key: string) => ({ key })),
      },
      PERSONAL_RESEARCH_CONTAINER: { getByName },
    } as unknown as Env;
    const response = await submitPersonalReceiptCandidate(env, REQUEST.value);
    expect(response.status).toBe(202);
    expect(getByName).toHaveBeenCalledWith(PERSONAL_SNAPSHOT_CONTAINER_NAME);
    const posted = fetch.mock.calls.find(([request]) =>
      new URL(request.url).pathname === "/v1/materialize-receipt-candidate"
    );
    expect(posted).toBeDefined();
    const body = JSON.parse(await posted![0].text()) as Record<string, unknown>;
    expect(body.environment).toBe("staging");
    expect(body.profile_id).toBe(EXACT_FOUR_PROFILE_ID);
    expect(body.pending_ready).toBeUndefined();
    expect(body.ready).toBeUndefined();
    expect(body.go).toBeUndefined();
  });
});
