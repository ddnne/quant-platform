import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { after, before, test } from "node:test";
import { createTestHarness } from "wrangler";

const root = new URL("../", import.meta.url);
const server = createTestHarness({
  root: root.pathname,
  workers: [
    {
      config: {
        name: "quant-platform-jquants-acquisition-caller-test",
        main: "harness/acquisition_caller.ts",
        compatibility_date: "2026-08-01",
        workers_dev: false,
        services: [
          {
            binding: "JQUANTS_ACQUISITION",
            service: "quant-platform-jquants-acquisition-target-test",
          },
        ],
      },
    },
    {
      config: {
        name: "quant-platform-jquants-acquisition-target-test",
        main: "harness/acquisition_target.ts",
        compatibility_date: "2026-08-01",
        workers_dev: false,
      },
    },
  ],
});

function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value).sort().map(
    (key) => `${JSON.stringify(key)}:${canonical(value[key])}`,
  ).join(",")}}`;
}

function digest(value) {
  const bytes = typeof value === "string" || value instanceof Uint8Array
    ? value
    : canonical(value);
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

async function registry() {
  const source = await readFile(
    new URL(
      "../../../../packages/data_plane/data_contracts/"
        + "jquants_acquisition_target_registry.generated.json",
      import.meta.url,
    ),
    "utf8",
  );
  return JSON.parse(source);
}

function nullable(value) {
  return value === "NONE" ? null : value;
}

function integer(value) {
  return value === "NONE" ? null : Number(value);
}

function responseMetadata(headers) {
  return {
    schema_version: "jquants-acquisition-rpc-response-metadata/v2",
    evidence_state: headers.get("x-quant-acquisition-evidence-state"),
    environment: nullable(headers.get("x-quant-acquisition-environment")),
    dataset_id: nullable(headers.get("x-quant-acquisition-dataset")),
    segment_id: nullable(headers.get("x-quant-acquisition-segment")),
    segment_start: nullable(headers.get("x-quant-acquisition-segment-start")),
    segment_end: nullable(headers.get("x-quant-acquisition-segment-end")),
    request_digest: nullable(headers.get("x-quant-acquisition-request-digest")),
    request_identity_digest: nullable(headers.get("x-quant-acquisition-request-identity-digest")),
    previous_request_digest: nullable(headers.get("x-quant-acquisition-previous-request-digest")),
    acquisition_id: nullable(headers.get("x-quant-acquisition-acquisition-id")),
    acquisition_issued_at: nullable(headers.get("x-quant-acquisition-acquisition-issued-at")),
    acquisition_expires_at: nullable(headers.get("x-quant-acquisition-acquisition-expires-at")),
    target_registry_digest: nullable(headers.get("x-quant-acquisition-registry-digest")),
    source_capability_digest: nullable(headers.get("x-quant-acquisition-source-capability-digest")),
    dataset_contract_digest: nullable(headers.get("x-quant-acquisition-dataset-contract-digest")),
    coverage_policy_digest: nullable(headers.get("x-quant-acquisition-coverage-policy-digest")),
    query_contract_digest: nullable(headers.get("x-quant-acquisition-query-contract-digest")),
    cursor_key_id: nullable(headers.get("x-quant-acquisition-cursor-key-id")),
    slice_date: nullable(headers.get("x-quant-acquisition-slice-date")),
    query_digest: nullable(headers.get("x-quant-acquisition-query-digest")),
    page_ordinal: integer(headers.get("x-quant-acquisition-page-ordinal")),
    slice_ordinal: integer(headers.get("x-quant-acquisition-slice-ordinal")),
    provider_page_ordinal: integer(headers.get("x-quant-acquisition-provider-page-ordinal")),
    provider_pagination_state: headers.get("x-quant-acquisition-provider-pagination-state"),
    upstream_http_status: integer(headers.get("x-quant-acquisition-upstream-status")),
    body_digest: headers.get("x-quant-acquisition-body-digest"),
    body_kind: headers.get("x-quant-acquisition-body-kind"),
    pagination_state: headers.get("x-quant-acquisition-pagination-state"),
    continuation_token: nullable(headers.get("x-quant-acquisition-continuation")),
    content_type: headers.get("content-type"),
    redirect_count: Number(headers.get("x-quant-acquisition-redirect-count")),
    previous_chain_digest: nullable(headers.get("x-quant-acquisition-previous-chain-digest")),
    chain_digest: nullable(headers.get("x-quant-acquisition-chain-digest")),
  };
}

before(async () => {
  await server.listen();
});

after(async () => {
  await server.close();
});

test("separate-isolate Service Binding preserves exact Response bytes and metadata", async () => {
  const document = await registry();
  const row = document.datasets.find(
    (item) => item.canonical_dataset.dataset_id === "indices_bars_daily_topix",
  );
  assert.ok(row);
  const request = {
    schema_version: "jquants-acquisition-rpc-request/v2",
    environment: "production",
    operation: "fetch_governed_page",
    dataset_id: "indices_bars_daily_topix",
    segment_id: "2024-02",
    segment_start: "2024-02-01",
    segment_end: "2024-02-29",
    acquisition_nonce: "c".repeat(64),
    source_capability_digest: digest(row.source_capability),
    dataset_contract_digest: digest({
      canonical_dataset: row.canonical_dataset,
      premium_contract: row.premium_contract,
    }),
    coverage_policy_digest: digest(row.coverage_policy),
    query_contract_digest: digest(row.query_resolution),
    target_registry_digest: document.registry_digest,
    continuation_token: null,
  };
  const response = await server.fetch("/acquire", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
  });
  const expected = new Uint8Array([0x00, 0xff, 0x80, 0x0a, 0x4a, 0x51]);
  const actual = new Uint8Array(await response.arrayBuffer());
  assert.deepEqual(actual, expected);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("x-quant-acquisition-body-digest"), digest(actual));
  assert.equal(response.headers.get("x-quant-acquisition-pagination-state"), "UNKNOWN");
  assert.equal(response.headers.get("x-quant-acquisition-evidence-state"), "RAW_ONLY");
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("server"), null);

  const schema = JSON.parse(await readFile(
    new URL("../../../../specs/authorities/jquants_acquisition_rpc.schema.json", import.meta.url),
    "utf8",
  ));
  const requiredHeaders = schema.$defs.response_headers.required;
  for (const name of requiredHeaders) {
    assert.notEqual(response.headers.get(name), null, `missing ${name}`);
  }
  const fixedSurface = [...response.headers.keys()].filter(
    (name) => name.startsWith("x-quant-acquisition-") ||
      ["cache-control", "content-type", "x-content-type-options"].includes(name),
  );
  assert.deepEqual(fixedSurface.sort(), [...requiredHeaders].sort());
  const metadata = responseMetadata(response.headers);
  assert.equal(
    response.headers.get("x-quant-acquisition-metadata-digest"),
    digest(metadata),
  );
});
