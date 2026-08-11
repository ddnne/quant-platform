/**
 * Artifacts join plan (read-only). No Mass research. Returns R2 keys + D1 SQL.
 */

export interface ArtifactsPlanEnv {
  STRUCTURED_BUCKET: R2Bucket;
  DB: D1Database;
  INGESTION_RUN_TOKEN?: string;
}

function authorized(request: Request, expected: string | undefined): boolean {
  if (!expected) return false;
  const url = new URL(request.url);
  const header = request.headers.get("X-Ingestion-Token") || "";
  const query = url.searchParams.get("token") || "";
  return header === expected || query === expected;
}

export async function handleArtifactsJoinPlan(
  request: Request,
  env: ArtifactsPlanEnv,
): Promise<Response> {
  if (!authorized(request, env.INGESTION_RUN_TOKEN)) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  const url = new URL(request.url);
  const datasetsRaw = url.searchParams.get("datasets") || "";
  const datasets = datasetsRaw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (datasets.length === 0) {
    return Response.json(
      { error: "datasets required (comma-separated)" },
      { status: 400 },
    );
  }
  const from = url.searchParams.get("from") || "1970-01-01";
  const to = url.searchParams.get("to") || "9999-12-31";

  const perDataset: Record<string, unknown> = {};
  for (const ds of datasets.slice(0, 10)) {
    const jsonlPrefix = `structured/jsonl/${ds}/`;
    const archivePrefix = `archive/jquants_records/${ds}/`;
    const scd2Prefix =
      ds === "equities_master" ? "structured/scd2/equities_master/" : null;

    const [jsonl, archive] = await Promise.all([
      env.STRUCTURED_BUCKET.list({ prefix: jsonlPrefix, limit: 50 }),
      env.STRUCTURED_BUCKET.list({ prefix: archivePrefix, limit: 50 }),
    ]);
    let scd2Keys: string[] = [];
    if (scd2Prefix) {
      const scd2 = await env.STRUCTURED_BUCKET.list({
        prefix: scd2Prefix,
        limit: 50,
      });
      scd2Keys = scd2.objects.map((o) => o.key);
    }

    const hot = await env.DB.prepare(
      `SELECT COUNT(*) AS n,
              MIN(substr(event_time,1,10)) AS mn,
              MAX(substr(event_time,1,10)) AS mx
         FROM jquants_records
        WHERE dataset = ?
          AND substr(event_time,1,10) >= ?
          AND substr(event_time,1,10) <= ?`,
    )
      .bind(ds, from, to)
      .first<{ n: number; mn: string | null; mx: string | null }>();

    perDataset[ds] = {
      r2_jsonl_keys: jsonl.objects.map((o) => o.key),
      r2_archive_keys: archive.objects.map((o) => o.key),
      r2_scd2_keys: scd2Keys,
      r2_jsonl_truncated: jsonl.truncated,
      r2_archive_truncated: archive.truncated,
      d1_hot: {
        count: Number(hot?.n ?? 0),
        min_event: hot?.mn ?? null,
        max_event: hot?.mx ?? null,
        sql:
          `SELECT source, dataset, natural_key, event_time, available_at, payload ` +
          `FROM jquants_records WHERE dataset='${ds.replace(/'/g, "''")}' ` +
          `AND substr(event_time,1,10) >= '${from}' AND substr(event_time,1,10) <= '${to}' ` +
          `ORDER BY event_time, natural_key LIMIT 10000`,
      },
    };
  }

  return Response.json({
    schema: "artifacts-join-plan/v1",
    mass_research: "NO-GO",
    from,
    to,
    datasets,
    plan: perDataset,
    join_notes: [
      "Hot window: query D1 jquants_records with provided SQL (bounded).",
      "Cold history: read R2 JSONL/archive keys; optional SCD2 CURRENT for master.",
      "Evidence: do not invent segments; use coverage_segments + collection_receipts.",
      "True Parquet JOIN is a follow-on; use parquet-manifest/v1 for discovery.",
    ],
  });
}
