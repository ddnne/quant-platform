import type { JsdaQueueJob } from "./queue_contract";

/** Generated bindings are the base; only secret and Queue body typing are refined. */
export type JsdaWorkerEnv = Omit<Cloudflare.Env, "JSDA_QUEUE"> & {
  JSDA_QUEUE: Queue<JsdaQueueJob>;
  JSDA_DLQ_QUEUE: string;
  INGESTION_RUN_TOKEN?: string;
};
