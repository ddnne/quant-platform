/// <reference types="@cloudflare/workers-types" />
/** JSDA acquisition: stable queue work graph, immutable raw, D1 progress. */

import { authorized } from "./authorized";
import type { JsdaWorkerEnv } from "./env";
import { json } from "./http_json";
import { consumeQueueMessage } from "./queue_consumer";
import {
  isDatasetId,
  type DatasetId,
  type JsdaQueueJob,
} from "./queue_contract";
import { enqueueRoots } from "./queue_producer";
import { allowedHosts } from "./source_http";

export type { JsdaQueueJob } from "./queue_contract";

export default {
  async fetch(request: Request, env: JsdaWorkerEnv): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      if (request.method !== "GET") return json({ error: "GET required" }, 405);
      return json({
        ok: true,
        worker: "ingestion-jsda",
        queue_contract: "jsda-acquisition-job/v2",
        hierarchy: ["discover_root", "discover_year", "fetch_file"],
        datasets: 3,
        allowlist: allowedHosts(),
        note: "immutable R2 raw and audit evidence; D1-authoritative queue progress",
      });
    }

    if (url.pathname === "/v1/run") {
      if (request.method !== "POST") return json({ error: "POST required" }, 405);
      if (!(await authorized(request, env.INGESTION_RUN_TOKEN))) {
        return json({ error: "unauthorized" }, 401);
      }
      const requestedDataset = url.searchParams.get("dataset");
      let dataset: DatasetId | undefined;
      if (url.searchParams.has("dataset")) {
        if (!isDatasetId(requestedDataset)) {
          return json({ error: "invalid dataset" }, 400);
        }
        dataset = requestedDataset;
      }
      const result = await enqueueRoots(env, "manual", dataset);
      return json(
        {
          accepted: true,
          mode: "cloudflare_queue_v2",
          queued: result.queued.length,
          datasets: result.selected,
          work_keys: result.queued.map((job) => job.work_key),
        },
        202,
      );
    }
    return json({ error: "not found" }, 404);
  },

  async scheduled(
    controller: ScheduledController,
    env: JsdaWorkerEnv,
    ctx: ExecutionContext,
  ): Promise<void> {
    ctx.waitUntil(
      enqueueRoots(
        env,
        "cron",
        undefined,
        new Date(controller.scheduledTime).toISOString(),
      ),
    );
  },

  async queue(
    batch: MessageBatch<unknown>,
    env: JsdaWorkerEnv,
    _ctx: ExecutionContext,
  ): Promise<void> {
    for (const message of batch.messages) {
      await consumeQueueMessage(message, env);
    }
  },
} satisfies ExportedHandler<JsdaWorkerEnv, JsdaQueueJob>;
