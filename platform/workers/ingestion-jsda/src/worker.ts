/// <reference types="@cloudflare/workers-types" />
/** JSDA acquisition: stable queue work graph, immutable raw, D1 progress. */

import { authorized } from "./authorized";
import {
  loadV3CutoverStatus,
  PRODUCTION_V3_CUTOVER_PIN,
  requireV3CutoverActive,
  type V3CutoverPin,
  type V3CutoverStatus,
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
import { allowedHosts } from "./source_http";

export type { JsdaQueueJob } from "./queue_contract";

export function createJsdaWorker(
  cutoverPin: V3CutoverPin = PRODUCTION_V3_CUTOVER_PIN,
): ExportedHandler<JsdaWorkerEnv, JsdaQueueJob> {
  return {
  async fetch(request: Request, env: JsdaWorkerEnv): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health" || url.pathname === "/health/ready") {
      if (request.method !== "GET") return json({ error: "GET required" }, 405);
      let status: V3CutoverStatus = {
        productReady: false,
        cutover: "UNKNOWN",
        activatedSourceSha: null,
        cutoverConfigDigest: null,
        drainEvidenceDigest: null,
      };
      try {
        status = await loadV3CutoverStatus(env.DB, cutoverPin);
      } catch {
        // Liveness stays observable while readiness fails closed.
      }
      const body = {
        ok: true,
        liveness: true,
        product_ready: status.productReady,
        cutover: status.cutover,
        activated_source_sha: status.activatedSourceSha,
        cutover_config_digest: status.cutoverConfigDigest,
        drain_evidence_digest: status.drainEvidenceDigest,
        worker: "ingestion-jsda",
        queue_contract: "jsda-acquisition-job/v2",
        hierarchy: ["discover_root", "discover_year", "fetch_file"],
        datasets: 3,
        allowlist: allowedHosts(),
        note: "source-object/observation/artifact identities; D1-authoritative queue progress",
      };
      if (url.pathname === "/health/ready") {
        return json(
          { ...body, ok: status.productReady },
          status.productReady ? 200 : 503,
        );
      }
      return json(body);
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
