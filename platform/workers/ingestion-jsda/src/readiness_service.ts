import { WorkerEntrypoint } from "cloudflare:workers";

import {
  loadV3CutoverStatus,
  PRODUCTION_V3_CUTOVER_PIN,
  type V3CutoverPin,
  type V3CutoverStatus,
} from "./cutover";
import { json } from "./http_json";
import { allowedHosts } from "./source_http";

type JsdaReadinessEnv = {
  DB: D1Database;
};

export async function handleJsdaReadinessRequest(
  request: Request,
  env: JsdaReadinessEnv,
  cutoverPin: V3CutoverPin = PRODUCTION_V3_CUTOVER_PIN,
): Promise<Response> {
  const url = new URL(request.url);
  if (
    request.method !== "GET"
    || (url.pathname !== "/health" && url.pathname !== "/health/ready")
  ) {
    return new Response(null, { status: 404 });
  }
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

/** Closed named capability used only for private readiness observation. */
export class JsdaReadinessService extends WorkerEntrypoint<JsdaReadinessEnv> {
  override fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (request.method !== "GET" || url.pathname !== "/health/ready") {
      return Promise.resolve(new Response(null, { status: 404 }));
    }
    return handleJsdaReadinessRequest(request, this.env);
  }
}
