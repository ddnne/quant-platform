import type { ControlledPhysicalSnapshot } from "./controlled_pilot_contract";

export const CONTROLLED_R2_HOST = "controlled.r2";

export type ControlledOutboundParams = ControlledPhysicalSnapshot;

type OutboundCtx = {
  containerId?: string;
  params?: ControlledOutboundParams;
};

function responseJson(value: unknown, status: number): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function physicalFromCtx(ctx?: { params?: unknown }): ControlledPhysicalSnapshot | null {
  const params = ctx?.params as ControlledOutboundParams | undefined;
  if (
    !params ||
    typeof params.key !== "string" ||
    typeof params.digest !== "string" ||
    !Number.isSafeInteger(params.size) ||
    params.size < 1 ||
    !params.digest.startsWith("sha256:")
  ) {
    return null;
  }
  return params;
}

/** Stream one verified physical snapshot. Never buffers SQLite in Worker memory. */
export async function controlledPilotR2Outbound(
  request: Request,
  env: { STRUCTURED_BUCKET: R2Bucket },
  ctx?: { containerId?: string; params?: unknown },
): Promise<Response> {
  const url = new URL(request.url);
  const key = url.pathname.startsWith("/") ? url.pathname.slice(1) : url.pathname;
  if (url.hostname !== CONTROLLED_R2_HOST || url.search || url.hash || key.includes("%")) {
    return responseJson({ error: "controlled R2 request denied" }, 403);
  }
  if (request.method !== "GET" && request.method !== "HEAD") {
    return responseJson({ error: "controlled R2 method denied" }, 403);
  }
  const allow = physicalFromCtx(ctx);
  if (!allow || allow.key !== key) {
    return responseJson({ error: "controlled snapshot is not bound" }, 403);
  }
  const hex = allow.digest.slice("sha256:".length);
  if (request.method === "HEAD") {
    const object = await env.STRUCTURED_BUCKET.head(key);
    if (!object) return responseJson({ error: "controlled snapshot not found" }, 404);
    if (object.size !== allow.size) {
      return responseJson({ error: "controlled snapshot size mismatch" }, 409);
    }
    return new Response(null, {
      status: 200,
      headers: {
        "content-length": String(object.size),
        "content-type": "application/vnd.sqlite3",
        "x-content-sha256": hex,
        "x-r2-immutable": "true",
      },
    });
  }
  const object = await env.STRUCTURED_BUCKET.get(key);
  if (!object || !object.body) return responseJson({ error: "controlled snapshot not found" }, 404);
  if (object.size !== allow.size) {
    return responseJson({ error: "controlled snapshot size mismatch" }, 409);
  }
  const headers = new Headers({
    "content-length": String(object.size),
    "content-type": "application/vnd.sqlite3",
    "x-content-sha256": hex,
    "x-r2-immutable": "true",
  });
  const body = object.body.pipeThrough(new FixedLengthStream(object.size));
  return new Response(body, { status: 200, headers });
}

export function denyControlledPilotR2Outbound(
  request: Request,
): Response {
  void request;
  return responseJson({ error: "controlled snapshot is not bound" }, 403);
}
