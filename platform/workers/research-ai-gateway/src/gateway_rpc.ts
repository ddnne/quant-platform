/** Shared Gateway provider RPC. Mass typechecks against this contract. */
export interface GatewayRpc {
  complete(
    body: unknown,
    options?: { idempotency_key?: string },
  ): Promise<{ http_status: number; body: unknown }>;
}
