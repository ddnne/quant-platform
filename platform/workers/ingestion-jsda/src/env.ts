import type { JsdaQueueJob } from "./queue_contract";

/** Generated bindings are the base; only secret and Queue body typing are refined. */
export type JsdaWorkerEnv = Omit<Env, "JSDA_QUEUE"> & {
  JSDA_QUEUE: Queue<JsdaQueueJob>;
  INGESTION_RUN_TOKEN?: string;
  USER_AGENT?: string;
};
