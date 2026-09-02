/** Shared Gateway provider RPC. Mass typechecks against this contract. */
export type ControlledPaperBudgetRpcInput = {
  idempotency_key: string;
  request_digest: string;
  lease_id?: string;
};

export interface GatewayRpc {
  complete(
    body: unknown,
    options?: { idempotency_key?: string },
  ): Promise<{ http_status: number; body: unknown }>;
  reserveControlledPaper(
    input: ControlledPaperBudgetRpcInput,
  ): Promise<{ http_status: number; body: unknown }>;
  finalizeControlledPaper(
    input: ControlledPaperBudgetRpcInput,
  ): Promise<{ http_status: number; body: unknown }>;
  cancelControlledPaper(
    input: ControlledPaperBudgetRpcInput,
  ): Promise<{ http_status: number; body: unknown }>;
  heartbeatControlledPaper(
    input: ControlledPaperBudgetRpcInput,
  ): Promise<{ http_status: number; body: unknown }>;
  queryControlledPaper(
    input: ControlledPaperBudgetRpcInput,
  ): Promise<{ http_status: number; body: unknown }>;
}
