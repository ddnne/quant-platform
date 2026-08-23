/**
 * Prune sealed ingestion_change_log tails. Keeps newest `keep` rows per dataset.
 * Does not touch receipts / coverage / raw retention.
 */

export interface PruneEnv {
  DB: D1Database;
  INGESTION_RUN_TOKEN?: string;
}

function authorized(request: Request, expected: string | undefined): boolean {
  if (!expected) return false;
  const header = request.headers.get("X-Ingestion-Token") || "";
  return header === expected;
}

export async function handlePruneChangelog(
  request: Request,
  env: PruneEnv,
): Promise<Response> {
  if (request.method !== "POST") {
    return Response.json({ error: "POST required" }, { status: 405 });
  }
  if (!authorized(request, env.INGESTION_RUN_TOKEN)) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  const url = new URL(request.url);
  const keep = Math.max(
    16,
    Math.min(10_000, Math.floor(Number(url.searchParams.get("keep") || "64") || 64)),
  );
  const datasetFilter = url.searchParams.get("dataset") || "";
  const maxDelete = Math.max(
    100,
    Math.min(50_000, Math.floor(Number(url.searchParams.get("max_delete") || "5000") || 5000)),
  );

  let datasets: string[];
  if (datasetFilter) {
    datasets = [datasetFilter];
  } else {
    const dsRes = await env.DB.prepare(
      `SELECT dataset, COUNT(*) AS cnt
         FROM ingestion_change_log
        GROUP BY dataset
       HAVING cnt > ?
        ORDER BY cnt DESC
        LIMIT 40`,
    ).bind(keep * 2).all();
    datasets = ((dsRes.results ?? []) as Array<{ dataset: string }>).map(
      (r) => r.dataset,
    );
  }

  const report: Array<{
    dataset: string;
    deleted: number;
    before: number;
    after: number;
  }> = [];

  for (const dataset of datasets) {
    const beforeRow = await env.DB.prepare(
      `SELECT COUNT(*) AS c FROM ingestion_change_log WHERE dataset = ?`,
    ).bind(dataset).first<{ c: number }>();
    const before = Number(beforeRow?.c ?? 0);
    if (before <= keep * 2) {
      report.push({ dataset, deleted: 0, before, after: before });
      continue;
    }

    // Delete oldest rows beyond keep, capped per call for D1 safety.
    const del = await env.DB.prepare(
      `DELETE FROM ingestion_change_log
        WHERE dataset = ?
          AND change_seq IN (
            SELECT change_seq FROM ingestion_change_log
             WHERE dataset = ?
             ORDER BY change_seq ASC
             LIMIT ?
          )`,
    ).bind(dataset, dataset, maxDelete).run();

    const deleted = (del.meta?.changes ?? 0) as number;
    const afterRow = await env.DB.prepare(
      `SELECT COUNT(*) AS c FROM ingestion_change_log WHERE dataset = ?`,
    ).bind(dataset).first<{ c: number }>();
    report.push({
      dataset,
      deleted,
      before,
      after: Number(afterRow?.c ?? before - deleted),
    });
  }

  return Response.json({ keep, max_delete: maxDelete, datasets: report });
}
