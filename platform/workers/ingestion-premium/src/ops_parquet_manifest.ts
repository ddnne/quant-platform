/**
 * Parquet-manifest v1 bridge: index R2 JSONL structured objects for Artifacts.
 * True Arrow Parquet encoding is not available in Workers; this writes a
 * machine-readable manifest that a later converter/Artifacts job can consume.
 */

import { sha256HexFromString } from "./sha256";

export interface ParquetManifestEnv {
  STRUCTURED_BUCKET: R2Bucket;
  INGESTION_RUN_TOKEN?: string;
}

function authorized(request: Request, expected: string | undefined): boolean {
  if (!expected) return false;
  const header = request.headers.get("X-Ingestion-Token") || "";
  return header === expected;
}

export async function handleParquetManifest(
  request: Request,
  env: ParquetManifestEnv,
): Promise<Response> {
  if (request.method !== "POST") {
    return Response.json({ error: "POST required" }, { status: 405 });
  }
  if (!authorized(request, env.INGESTION_RUN_TOKEN)) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const url = new URL(request.url);
  const prefix = url.searchParams.get("prefix") || "structured/jsonl/";
  const maxKeys = Math.min(
    1000,
    Math.max(1, parseInt(url.searchParams.get("limit") || "200", 10) || 200),
  );

  const listed = await env.STRUCTURED_BUCKET.list({
    prefix,
    limit: maxKeys,
  });

  const objects = [];
  for (const obj of listed.objects) {
    objects.push({
      key: obj.key,
      size: obj.size,
      etag: obj.etag,
      uploaded: obj.uploaded?.toISOString?.() ?? null,
      customMetadata: obj.customMetadata ?? null,
    });
  }

  const prefixHash = (await sha256HexFromString(prefix)).slice(0, 16);
  const truncated = Boolean(
    (listed as { truncated?: boolean }).truncated,
  );
  const cursor =
    truncated && "cursor" in listed
      ? String((listed as { cursor?: string }).cursor ?? "")
      : null;
  const manifest = {
    schema: "parquet-manifest/v1",
    note:
      "Bridge only: lists JSONL structured objects. True Parquet conversion is a follow-on Artifacts job.",
    prefix,
    generated_at: new Date().toISOString(),
    truncated,
    cursor,
    object_count: objects.length,
    objects,
  };

  const manifestKey =
    `structured/parquet_manifest/${prefixHash}.json`;
  await env.STRUCTURED_BUCKET.put(
    manifestKey,
    JSON.stringify(manifest, null, 2),
    {
      httpMetadata: { contentType: "application/json" },
      customMetadata: {
        schema: "parquet-manifest/v1",
        prefix_hash: prefixHash,
        count: String(objects.length),
      },
    },
  );

  return Response.json({
    ok: true,
    manifest_key: manifestKey,
    object_count: objects.length,
    truncated: listed.truncated,
    schema: "parquet-manifest/v1",
  });
}
