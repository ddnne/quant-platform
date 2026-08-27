/// <reference types="@cloudflare/workers-types" />

import { createJsdaWorker } from "./worker";

export type { JsdaQueueJob } from "./queue_contract";

export default createJsdaWorker();
