/** Caller-facing named-entrypoint RPC. No Worker Env types. */
export type ReceiptCandidatePublicationPointer = {
  job_id: string;
  environment: "production" | "staging";
};

export type ReadyPublicationResult =
  | {
      ok: true;
      status: "VERIFIED_PILOT_READINESS";
      ready_declared: false;
      operational_go: false;
      mass_research: "NO-GO";
      automatic_promotion: false;
      live_orders_enabled: false;
      attestation_id: string;
      snapshot_id: string;
      immutable_db_digest: string;
      envelope_key: string;
      attestation_key: string;
      published_at: string;
    }
  | {
      ok: false;
      status: "PENDING" | "HOLD" | "REJECTED";
      error: string;
      ready_declared: false;
      operational_go: false;
    };

export interface PilotReadyPublicationRpc {
  publishAdmittedReceiptCandidate(
    pointer: ReceiptCandidatePublicationPointer,
  ): Promise<ReadyPublicationResult>;
}
