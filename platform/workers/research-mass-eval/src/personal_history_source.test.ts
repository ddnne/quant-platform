import { describe, expect, it, vi } from "vitest";

import {
  parsePersonalHistorySourceRequest,
  personalHistorySourceOutbound,
} from "./personal_history_source";

const DIGEST = `sha256:${"a".repeat(64)}`;

function governed(dataset: string) {
  return {
    schema_version: "jquants-acquisition-rpc-request/v2",
    environment: "production",
    operation: "fetch_governed_page",
    dataset_id: dataset,
    segment_id: "2024-03",
    segment_start: "2024-03-01",
    segment_end: "2024-03-31",
    acquisition_nonce: "1".repeat(64),
    source_capability_digest: DIGEST,
    dataset_contract_digest: DIGEST,
    coverage_policy_digest: DIGEST,
    query_contract_digest: DIGEST,
    target_registry_digest: DIGEST,
    continuation_token: null,
  };
}

describe("personal history source allowlist", () => {
  it("admits only the four personal history datasets", () => {
    expect(parsePersonalHistorySourceRequest(governed("equities_bars_daily")).ok).toBe(
      true,
    );
    expect(parsePersonalHistorySourceRequest(governed("markets_calendar")).ok).toBe(
      true,
    );
    expect(parsePersonalHistorySourceRequest(governed("fins_details")).ok).toBe(
      false,
    );
  });

  it("rejects an arbitrary host, dataset, or extra header before RPC", async () => {
    const fetchGoverned = vi.fn(async () => new Response("ok"));
    const env = {
      JQUANTS_ACQUISITION: { fetch_governed_page: fetchGoverned },
    };
    const body = JSON.stringify(governed("equities_bars_daily"));
    const deniedHost = await personalHistorySourceOutbound(
      new Request("http://example.test/v1/fetch-governed-page", {
        method: "POST",
        headers: { "content-type": "application/json", "content-length": String(body.length) },
        body,
      }),
      env,
    );
    expect(deniedHost.status).toBe(403);
    const deniedDataset = await personalHistorySourceOutbound(
      new Request("http://history.source/v1/fetch-governed-page", {
        method: "POST",
        headers: { "content-type": "application/json", "content-length": String(JSON.stringify(governed("fins_details")).length) },
        body: JSON.stringify(governed("fins_details")),
      }),
      env,
    );
    expect(deniedDataset.status).toBe(403);
    const deniedHeader = await personalHistorySourceOutbound(
      new Request("http://history.source/v1/fetch-governed-page", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": String(body.length),
          "x-arbitrary-host": "https://example.test",
        },
        body,
      }),
      env,
    );
    expect(deniedHeader.status).toBe(403);
    expect(fetchGoverned).not.toHaveBeenCalled();
  });

  it("forwards a closed allowed request to the Service Binding", async () => {
    const payload = governed("fins_summary");
    const body = JSON.stringify(payload);
    const fetchGoverned = vi.fn(async () => new Response("raw-page", { status: 200 }));
    const response = await personalHistorySourceOutbound(
      new Request("http://history.source/v1/fetch-governed-page", {
        method: "POST",
        headers: {
          "content-type": "application/json; charset=utf-8",
          "content-length": String(body.length),
        },
        body,
      }),
      { JQUANTS_ACQUISITION: { fetch_governed_page: fetchGoverned } },
    );
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("raw-page");
    expect(fetchGoverned).toHaveBeenCalledWith(payload);
  });
});
