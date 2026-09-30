/**
 * Receipt-product metadata HTTP presentation.
 * DATA_EXPORT_TOKEN via X-Ingestion-Token; not ingest or legacy D1 export.
 */

import { json } from "./http_json";
import { ingestionTokenMatches } from "./ingestion_token";
import {
  describeReceiptProductInput,
  parseReceiptProductInputRequest,
  readBoundedBody,
} from "./receipt_product_input";

export type ExportEnv = Pick<Cloudflare.Env, "DB"> & {
  DATA_EXPORT_TOKEN?: string;
  OPS_PROJECTION_ENVIRONMENT?: string;
};

export async function handleExportReceiptProducts(
  env: ExportEnv,
  request: Request,
): Promise<Response> {
  if (request.method !== "POST") {
    return json({ error: "POST required" }, 405);
  }
  if (!(await ingestionTokenMatches(request, env.DATA_EXPORT_TOKEN))) {
    return json({ error: "unauthorized" }, 401);
  }
  const bounded = await readBoundedBody(request);
  if (!bounded.ok) {
    return json({ error: bounded.error }, 400);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(
      new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(
        bounded.bytes,
      ),
    );
  } catch {
    return json({ error: "invalid json" }, 400);
  }
  const closed = parseReceiptProductInputRequest(parsed);
  if (!closed.ok) {
    return json({ error: closed.error }, 400);
  }
  const result = await describeReceiptProductInput(env, closed.request);
  return json(result.body, result.httpStatus);
}

/** /v1/export/* dispatch. Unknown export paths return null. */
export async function handleExportPaths(
  request: Request,
  env: ExportEnv,
): Promise<Response | null> {
  const url = new URL(request.url);
  if (url.pathname === "/v1/export/receipt-products") {
    return handleExportReceiptProducts(env, request);
  }
  return null;
}
