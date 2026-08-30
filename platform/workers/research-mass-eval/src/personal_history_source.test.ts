import { describe, expect, it, vi } from "vitest";

import {
  HISTORY_SOURCE_FIXED_HEADERS,
  HISTORY_SOURCE_HOST,
  HISTORY_SOURCE_USER_AGENT,
  historySourceHeadersAreClosed,
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

function pythonGeneratedHeaders(contentLength: number): HeadersInit {
  return {
    ...HISTORY_SOURCE_FIXED_HEADERS,
    "content-length": String(contentLength),
    host: HISTORY_SOURCE_HOST,
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

  it("forwards the actual Python closed header set to the Service Binding", async () => {
    const payload = governed("fins_summary");
    const body = JSON.stringify(payload);
    const fetchGoverned = vi.fn(async () => new Response("raw-page", { status: 200 }));
    const request = new Request("http://history.source/v1/fetch-governed-page", {
      method: "POST",
      headers: pythonGeneratedHeaders(body.length),
      body,
    });
    expect(historySourceHeadersAreClosed(request)).toBe(true);
    expect(HISTORY_SOURCE_USER_AGENT).toBe("quant-personal-history/v13");
    const response = await personalHistorySourceOutbound(request, {
      JQUANTS_ACQUISITION: { fetch_governed_page: fetchGoverned },
    });
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("raw-page");
    expect(fetchGoverned).toHaveBeenCalledWith(payload);
  });

  it("rejects mutated transport values, extra names, hosts, and datasets", async () => {
    const fetchGoverned = vi.fn(async () => new Response("ok"));
    const env = { JQUANTS_ACQUISITION: { fetch_governed_page: fetchGoverned } };
    const body = JSON.stringify(governed("equities_bars_daily"));
    const headers = pythonGeneratedHeaders(body.length);
    const deniedHost = await personalHistorySourceOutbound(
      new Request("http://example.test/v1/fetch-governed-page", {
        method: "POST",
        headers,
        body,
      }),
      env,
    );
    expect(deniedHost.status).toBe(403);
    const deniedUa = await personalHistorySourceOutbound(
      new Request("http://history.source/v1/fetch-governed-page", {
        method: "POST",
        headers: { ...headers, "user-agent": "Python-urllib/3.12" },
        body,
      }),
      env,
    );
    expect(deniedUa.status).toBe(403);
    const deniedExtra = await personalHistorySourceOutbound(
      new Request("http://history.source/v1/fetch-governed-page", {
        method: "POST",
        headers: { ...headers, authorization: "Bearer secret" },
        body,
      }),
      env,
    );
    expect(deniedExtra.status).toBe(403);
    const deniedDataset = await personalHistorySourceOutbound(
      new Request("http://history.source/v1/fetch-governed-page", {
        method: "POST",
        headers: pythonGeneratedHeaders(JSON.stringify(governed("fins_details")).length),
        body: JSON.stringify(governed("fins_details")),
      }),
      env,
    );
    expect(deniedDataset.status).toBe(403);
    expect(fetchGoverned).not.toHaveBeenCalled();
  });
});
