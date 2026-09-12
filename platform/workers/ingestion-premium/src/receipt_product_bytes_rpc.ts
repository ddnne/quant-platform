/** Caller-facing named-entrypoint RPC. No Worker Env types. */
export interface ReceiptProductBytesRpc {
  read_receipt_product_bytes(request: unknown): Promise<Response>;
}
