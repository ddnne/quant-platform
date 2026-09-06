/// <reference types="@cloudflare/workers-types" />
/** JSDA acquisition: stable queue work graph, immutable raw, D1 progress. */

import { authorized } from "./authorized";
import {
  PRODUCTION_V3_CUTOVER_PIN,
  requireV3CutoverActive,
  type V3CutoverPin,
} from "./cutover";
import type { JsdaWorkerEnv } from "./env";
import { json } from "./http_json";
import { consumeDlqMessage, consumeQueueMessage } from "./queue_consumer";
import {
  isDatasetId,
  isJsdaDlqQueue,
  type DatasetId,
  type JsdaQueueJob,
} from "./queue_contract";
import { enqueueRoots } from "./queue_producer";
import { handleJsdaReadinessRequest } from "./readiness_service";

export type { JsdaQueueJob } from "./queue_contract";

export async function handleJsdaHttpRequest(
  request: Request,
  env: JsdaWorkerEnv,
  cutoverPin: V3CutoverPin = PRODUCTION_V3_CUTOVER_PIN,
): Promise<Response> {
  const url = new URL(request.url);
  if (url.pathname === "/health" || url.pathname === "/health/ready") {
    if (request.method !== "GET") return json({ error: "GET required" }, 405);
    return handleJsdaReadinessRequest(request, env, cutoverPin);
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
    try {
      await requireV3CutoverActive(env.DB, cutoverPin);
    } catch {
      return json({ error: "jsda_v3_cutover_pending" }, 503);
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
}

export function createJsdaWorker(
  cutoverPin: V3CutoverPin = PRODUCTION_V3_CUTOVER_PIN,
): ExportedHandler<JsdaWorkerEnv, JsdaQueueJob> {
  return {
    fetch(request: Request, env: JsdaWorkerEnv): Promise<Response> {
      return handleJsdaHttpRequest(request, env, cutoverPin);
    },

    async scheduled(
      controller: ScheduledController,
      env: JsdaWorkerEnv,
      ctx: ExecutionContext,
    ): Promise<void> {
      await requireV3CutoverActive(env.DB, cutoverPin);
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
      await requireV3CutoverActive(env.DB, cutoverPin);
      const dlq = isJsdaDlqQueue(batch.queue, env.JSDA_DLQ_QUEUE);
      for (const message of batch.messages) {
        if (dlq) await consumeDlqMessage(message, env, batch.queue);
        else await consumeQueueMessage(message, env);
      }
    },
  } satisfies ExportedHandler<JsdaWorkerEnv, JsdaQueueJob>;
}
