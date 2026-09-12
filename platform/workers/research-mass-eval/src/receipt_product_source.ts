import type { ReceiptProductBytesRpc } from "../../ingestion-premium/src/receipt_product_bytes_rpc";
import { json, readBoundedJson } from "./http";

const FETCH_PATH = "/v1/read-receipt-product-bytes";
const DESCRIBE_PATH = "/v1/describe-receipt-product-input";
const MAX_REQUEST_BYTES = 16 * 1024;

export const RECEIPT_PRODUCT_HOST = "receipt.products";

type ProductEnv = {
  INGESTION_PREMIUM?: ReceiptProductBytesRpc | Service;
};

function productRpc(
  binding: ProductEnv["INGESTION_PREMIUM"],
): ReceiptProductBytesRpc | undefined {
  if (
    binding !== undefined &&
    "read_receipt_product_bytes" in binding &&
    typeof binding.read_receipt_product_bytes === "function"
  ) {
    return binding;
  }
  return undefined;
}

/** Narrow receipt-product byte capability exposed only to receipt.products. */
export async function receiptProductSourceOutbound(
  request: Request,
  env: ProductEnv,
): Promise<Response> {
  const url = new URL(request.url);
  if (
    url.hostname !== RECEIPT_PRODUCT_HOST ||
    url.search ||
    url.hash ||
    (url.pathname !== FETCH_PATH && url.pathname !== DESCRIBE_PATH)
  ) {
    return json({ error: "receipt product request denied" }, 403);
  }
  if (request.method !== "POST") {
    return json({ error: "POST required" }, 405);
  }
  const rpc = productRpc(env.INGESTION_PREMIUM);
  if (rpc === undefined) {
    return json({ error: "receipt product binding unavailable" }, 503);
  }
  const bounded = await readBoundedJson(request, MAX_REQUEST_BYTES);
  if (!bounded.ok) {
    return json({ error: bounded.error }, bounded.status);
  }
  if (url.pathname === DESCRIBE_PATH) {
    if (typeof rpc.describe_receipt_product_input !== "function") {
      return json({ error: "receipt product binding unavailable" }, 503);
    }
    return rpc.describe_receipt_product_input(bounded.value);
  }
  return rpc.read_receipt_product_bytes(bounded.value);
}
