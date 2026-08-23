/// <reference types="@cloudflare/workers-types" />
/**
 * JSDA raw acquisition plane on Cloudflare (Phase 6.2.2).
 *
 * - Outbound host allowlist only (jsda.or.jp / www / market)
 * - Immutable raw keys: raw/jsda/{dataset}/{segment_id}/{sha256}.{ext}
 * - Archive discovery: year indexes + data files (not maxDataFiles=3 heuristic PASS)
 * - Structured XLS/XLSX parse stays trusted Python downstream (not TS)
 */

export interface Env {
  RAW_BUCKET: R2Bucket;
  DB: D1Database;
  INGESTION_RUN_TOKEN?: string;
  USER_AGENT?: string;
  /** 0 = unlimited data-file fetches; small N for min-segment runs. */
  MAX_DATA_FILES?: string;
  /** 0 = all year archive pages; small N for min-segment runs. */
  MAX_YEAR_PAGES?: string;
}

const UA =
  "quant-platform-ingest/0.1 (+personal-research; JSDA bond stats)";

const ALLOWED_HOSTS = new Set([
  "jsda.or.jp",
  "www.jsda.or.jp",
  "market.jsda.or.jp",
]);

const OTC_INDEX =
  "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/index.html";
const REPO_INDEX = "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/";
const CORP_INDEX =
  "https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/";

const LINK_RE = /<a\s+[^>]*href=["']([^"']+)["']/gi;
const DATA_EXT = [".csv", ".xlsx", ".xls"];
const YEAR_ARCHIVE_RE = /archive(20\d{2})\.html/i;
const NON_DATA = ["reference", "bessi", "kijun", "koubo", "youkou"];

type DatasetId =
  | "jsda_otc_bond_reference_prices"
  | "jsda_tokyo_repo_rates"
  | "jsda_corporate_bond_transactions";

function timingSafeEqualBytes(a: ArrayBuffer, b: ArrayBuffer): boolean {
  const x = new Uint8Array(a);
  const y = new Uint8Array(b);
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function tokenMatches(provided: string, expected: string): Promise<boolean> {
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(provided)),
    crypto.subtle.digest("SHA-256", enc.encode(expected)),
  ]);
  return timingSafeEqualBytes(a, b);
}

async function authorized(request: Request, expected?: string): Promise<boolean> {
  if (!expected) return false;
  const got = request.headers.get("X-Ingestion-Token") || "";
  return tokenMatches(got, expected);
}

const MAX_ARTIFACT_BYTES = 32 * 1024 * 1024; // 32 MiB hard cap per artifact

function hostAllowed(url: string): boolean {
  try {
    const u = new URL(url);
    if (u.protocol !== "https:" && u.protocol !== "http:") return false;
    return ALLOWED_HOSTS.has(u.hostname.toLowerCase());
  } catch {
    return false;
  }
}

function absolutize(base: string, href: string): string | null {
  try {
    const abs = new URL(href, base).toString();
    return hostAllowed(abs) ? abs : null;
  } catch {
    return null;
  }
}

function isDataUrl(url: string): boolean {
  const path = new URL(url).pathname.toLowerCase();
  if (NON_DATA.some((x) => path.includes(x))) return false;
  return DATA_EXT.some((ext) => path.endsWith(ext));
}

function isYearArchive(url: string): boolean {
  return YEAR_ARCHIVE_RE.test(new URL(url).pathname);
}

function basename(url: string): string {
  const path = new URL(url).pathname;
  return path.split("/").filter(Boolean).pop() || "index.html";
}

function extOf(url: string): string {
  const name = basename(url).toLowerCase();
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1) : "bin";
}

function extractLinks(html: string, base: string): string[] {
  const out: string[] = [];
  LINK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = LINK_RE.exec(html)) !== null) {
    const abs = absolutize(base, m[1].replace(/&amp;/g, "&").trim());
    if (abs) out.push(abs);
  }
  return [...new Set(out)];
}

async function sha256Hex(buf: BufferSource): Promise<string> {
  const dig = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(dig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function fetchAllowed(
  url: string,
  ua: string,
): Promise<{ status: number; bytes: ArrayBuffer; contentType: string; finalUrl: string }> {
  if (!hostAllowed(url)) {
    throw new Error(`host not allowlisted: ${url}`);
  }
  const resp = await fetch(url, {
    headers: { "User-Agent": ua, Accept: "*/*" },
    redirect: "manual",
  });
  // Follow redirects only within allowlist.
  if (resp.status >= 300 && resp.status < 400) {
    const loc = resp.headers.get("Location");
    if (!loc) throw new Error(`redirect without location from ${url}`);
    const next = absolutize(url, loc);
    if (!next) throw new Error(`redirect host not allowlisted from ${url}`);
    return fetchAllowed(next, ua);
  }
  const cl = resp.headers.get("content-length");
  if (cl && Number(cl) > MAX_ARTIFACT_BYTES) {
    throw new Error(`artifact too large content-length=${cl} url=${url}`);
  }
  // Bounded read: reject if body exceeds max even without Content-Length.
  const reader = resp.body?.getReader();
  if (!reader) {
    const bytes = await resp.arrayBuffer();
    if (bytes.byteLength > MAX_ARTIFACT_BYTES) {
      throw new Error(`artifact too large bytes=${bytes.byteLength}`);
    }
    return {
      status: resp.status,
      bytes,
      contentType: resp.headers.get("content-type") || "application/octet-stream",
      finalUrl: url,
    };
  }
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) {
      total += value.byteLength;
      if (total > MAX_ARTIFACT_BYTES) {
        try {
          await reader.cancel();
        } catch {
          /* ignore */
        }
        throw new Error(`artifact too large bytes>${MAX_ARTIFACT_BYTES}`);
      }
      chunks.push(value);
    }
  }
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const c of chunks) {
    merged.set(c, offset);
    offset += c.byteLength;
  }
  return {
    status: resp.status,
    bytes: merged.buffer,
    contentType: resp.headers.get("content-type") || "application/octet-stream",
    finalUrl: url,
  };
}

async function putImmutable(
  env: Env,
  dataset: DatasetId,
  segmentId: string,
  ext: string,
  body: ArrayBuffer,
  contentType: string,
  meta: Record<string, string>,
): Promise<{ key: string; digest: string }> {
  const digest = await sha256Hex(body);
  const key = `raw/jsda/${dataset}/${segmentId}/${digest}.${ext}`;
  // Immutable: if key exists, leave it (content-addressed).
  const existing = await env.RAW_BUCKET.head(key);
  if (!existing) {
    await env.RAW_BUCKET.put(key, body, {
      httpMetadata: { contentType },
      customMetadata: { ...meta, sha256: digest, source: "jsda", dataset },
    });
  }
  return { key, digest };
}

async function putManifest(
  env: Env,
  dataset: DatasetId,
  segmentId: string,
  manifest: Record<string, unknown>,
): Promise<string> {
  const text = JSON.stringify(manifest, null, 2);
  const bytes = new TextEncoder().encode(text);
  const digest = await sha256Hex(bytes);
  const key = `raw/jsda/${dataset}/${segmentId}/manifest-${digest.slice(0, 16)}.json`;
  await env.RAW_BUCKET.put(key, text, {
    httpMetadata: { contentType: "application/json" },
    customMetadata: { source: "jsda", dataset, segmentId },
  });
  // Also write a stable pointer for "current" discovery without losing history.
  await env.RAW_BUCKET.put(
    `raw/jsda/${dataset}/${segmentId}/MANIFEST_CURRENT.json`,
    text,
    { httpMetadata: { contentType: "application/json" } },
  );
  return key;
}

interface CollectResult {
  dataset: DatasetId;
  status: "pass" | "fail" | "partial";
  expectedPages: number;
  fetchedPages: number;
  filesStored: number;
  keys: string[];
  detail: string;
}

async function collectWithDiscovery(
  env: Env,
  dataset: DatasetId,
  rootIndex: string,
  ua: string,
): Promise<CollectResult> {
  const keys: string[] = [];
  const day = new Date().toISOString().slice(0, 10);
  try {
    // Root index
    const root = await fetchAllowed(rootIndex, ua);
    if (root.status >= 400) {
      return {
        dataset,
        status: "fail",
        expectedPages: 1,
        fetchedPages: 0,
        filesStored: 0,
        keys,
        detail: `root index HTTP ${root.status}`,
      };
    }
    const rootHtml = new TextDecoder().decode(root.bytes);
    const rootSeg = `index_root_${day}`;
    const rootPut = await putImmutable(
      env,
      dataset,
      rootSeg,
      "html",
      root.bytes,
      "text/html; charset=utf-8",
      { kind: "index", url: rootIndex },
    );
    keys.push(rootPut.key);

    const rootLinks = extractLinks(rootHtml, rootIndex);
    let yearPages = rootLinks.filter(isYearArchive);
    // Prefer highest archive year first (list order on index is not reliable).
    yearPages = yearPages.slice().sort((a, b) => {
      const ya = Number(YEAR_ARCHIVE_RE.exec(new URL(a).pathname)?.[1] || 0);
      const yb = Number(YEAR_ARCHIVE_RE.exec(new URL(b).pathname)?.[1] || 0);
      return yb - ya;
    });
    const maxYearPages = Math.max(
      0,
      Math.min(100, Number(env.MAX_YEAR_PAGES ?? "0") || 0),
    );
    if (maxYearPages > 0) {
      yearPages = yearPages.slice(0, maxYearPages);
    }
    const dataFromRoot = rootLinks.filter(isDataUrl);

    // Crawl year archives when present (OTC style).
    const pageUrls = [rootIndex, ...yearPages];
    const allData = new Set<string>(dataFromRoot);
    let fetchedPages = 1;
    for (const yearUrl of yearPages) {
      const page = await fetchAllowed(yearUrl, ua);
      fetchedPages++;
      if (page.status >= 400) continue;
      const html = new TextDecoder().decode(page.bytes);
      const yearMatch = YEAR_ARCHIVE_RE.exec(new URL(yearUrl).pathname);
      const year = yearMatch ? yearMatch[1] : "unknown";
      const seg = `archive_year_${year}`;
      const put = await putImmutable(
        env,
        dataset,
        seg,
        "html",
        page.bytes,
        "text/html; charset=utf-8",
        { kind: "year_index", url: yearUrl },
      );
      keys.push(put.key);
      for (const d of extractLinks(html, yearUrl).filter(isDataUrl)) {
        allData.add(d);
      }
      await new Promise((r) => setTimeout(r, 300));
    }

    // Fetch discovered data files. Optional max_files (query/env) for min-segment
    // evidence closure without multi-hour full-archive crawls.
    const maxFiles = Math.max(
      0,
      Math.min(10_000, Number(env.MAX_DATA_FILES ?? "0") || 0),
    );
    let stored = 0;
    const errors: string[] = [];
    const artifacts: { url: string; key: string; digest: string }[] = [];
    const sortedData = [...allData].sort();
    // Prefer newest-looking filenames first when limiting (reverse sort).
    const toFetch =
      maxFiles > 0 ? sortedData.slice().reverse().slice(0, maxFiles) : sortedData;
    for (const dataUrl of toFetch) {
      try {
        const file = await fetchAllowed(dataUrl, ua);
        if (file.status >= 400) {
          errors.push(`${basename(dataUrl)}:HTTP${file.status}`);
          continue;
        }
        const name = basename(dataUrl);
        // segment by filename identity (publication artifact)
        const seg = `file_${name.replace(/[^A-Za-z0-9._-]+/g, "_")}`;
        const put = await putImmutable(
          env,
          dataset,
          seg,
          extOf(dataUrl),
          file.bytes,
          file.contentType,
          { kind: "data", url: dataUrl, name },
        );
        keys.push(put.key);
        artifacts.push({ url: dataUrl, key: put.key, digest: put.digest });
        stored++;
        await new Promise((r) => setTimeout(r, 400));
      } catch (e) {
        errors.push(`${basename(dataUrl)}:${(e as Error).message}`);
      }
    }

    const manifestKey = await putManifest(env, dataset, `discovery_${day}`, {
      dataset,
      rootIndex,
      discovered_year_pages: yearPages.length,
      discovered_data_files: allData.size,
      stored,
      artifacts,
      errors: errors.slice(0, 20),
      fetched_at: new Date().toISOString(),
    });
    keys.push(manifestKey);

    // Complete acquisition only when discovery scope fully fetched without errors
    // and we observed at least the expected discovery surface.
    // Repo series may only expose a single timeseries file on root — that is OK
    // if all discovered data files were stored.
    let status: "pass" | "partial" | "fail" = "partial";
    if (allData.size === 0 && yearPages.length === 0) {
      status = "partial"; // index only; deeper discovery may be needed
    } else if (stored === allData.size && errors.length === 0 && stored > 0) {
      status = "pass";
    } else if (stored === 0) {
      status = "fail";
    } else {
      status = "partial";
    }

    return {
      dataset,
      status,
      expectedPages: pageUrls.length,
      fetchedPages,
      filesStored: stored,
      keys,
      detail:
        `years=${yearPages.length} data_discovered=${allData.size} stored=${stored}` +
        (errors.length ? ` errors=${errors.slice(0, 5).join("|")}` : ""),
    };
  } catch (e) {
    return {
      dataset,
      status: "fail",
      expectedPages: 1,
      fetchedPages: 0,
      filesStored: 0,
      keys,
      detail: (e as Error).message || String(e),
    };
  }
}

async function enqueueRootDiscovery(env: Env): Promise<number> {
  const now = new Date().toISOString();
  const plans: { dataset: DatasetId; url: string }[] = [
    { dataset: "jsda_otc_bond_reference_prices", url: OTC_INDEX },
    { dataset: "jsda_tokyo_repo_rates", url: REPO_INDEX },
    { dataset: "jsda_corporate_bond_transactions", url: CORP_INDEX },
  ];
  let n = 0;
  for (const plan of plans) {
    const jobId = `discover:${plan.dataset}:${now.slice(0, 10)}`;
    try {
      await env.DB.prepare(
        `INSERT OR IGNORE INTO jsda_acquisition_jobs
         (job_id, dataset, job_type, target_url, segment_id, state, attempt, priority, created_at, updated_at)
         VALUES (?, ?, 'discover_root', ?, NULL, 'pending', 0, 10, ?, ?)`,
      )
        .bind(jobId, plan.dataset, plan.url, now, now)
        .run();
      n++;
    } catch {
      // Table may not be migrated yet — ignore.
    }
  }
  return n;
}

const CRON_JOB_BATCH = 3;

async function drainJobBatch(
  env: Env,
  ua: string,
): Promise<Record<string, unknown>> {
  const now = new Date().toISOString();
  let jobs: { job_id: string; dataset: string; job_type: string; target_url: string }[] = [];
  try {
    const res = await env.DB.prepare(
      `SELECT job_id, dataset, job_type, target_url FROM jsda_acquisition_jobs
       WHERE state IN ('pending','retry')
       ORDER BY priority ASC, created_at ASC LIMIT ?`,
    )
      .bind(CRON_JOB_BATCH)
      .all();
    jobs = (res.results || []) as typeof jobs;
  } catch (e) {
    return {
      mode: "job_queue",
      error: (e as Error).message,
      note: "jsda_acquisition_jobs missing — apply migration 0008",
    };
  }
  const results = [];
  for (const job of jobs) {
    await env.DB.prepare(
      `UPDATE jsda_acquisition_jobs SET state='running', attempt=attempt+1, updated_at=? WHERE job_id=?`,
    )
      .bind(now, job.job_id)
      .run();
    try {
      if (job.job_type === "discover_root") {
        const r = await collectWithDiscovery(
          env,
          job.dataset as DatasetId,
          job.target_url,
          ua,
        );
        const state = r.status === "pass" ? "pass" : r.status === "fail" ? "fail" : "partial";
        await env.DB.prepare(
          `UPDATE jsda_acquisition_jobs SET state=?, detail=?, updated_at=? WHERE job_id=?`,
        )
          .bind(state, r.detail.slice(0, 500), new Date().toISOString(), job.job_id)
          .run();
        results.push({ job_id: job.job_id, ...r });
      } else {
        await env.DB.prepare(
          `UPDATE jsda_acquisition_jobs SET state='fail', reason_code='unsupported_job_type', updated_at=? WHERE job_id=?`,
        )
          .bind(new Date().toISOString(), job.job_id)
          .run();
        results.push({ job_id: job.job_id, status: "fail", detail: "unsupported" });
      }
    } catch (e) {
      await env.DB.prepare(
        `UPDATE jsda_acquisition_jobs SET state='retry', detail=?, updated_at=? WHERE job_id=?`,
      )
        .bind((e as Error).message.slice(0, 500), new Date().toISOString(), job.job_id)
        .run();
      results.push({ job_id: job.job_id, status: "retry", detail: (e as Error).message });
    }
  }
  return { mode: "job_queue", drained: results.length, results };
}

async function runAll(
  env: Env,
  triggeredBy: "cron" | "manual",
  onlyDataset?: DatasetId,
): Promise<Record<string, unknown>> {
  const ua = env.USER_AGENT || UA;
  const startedAt = new Date().toISOString();

  // Cron: durable bounded path — enqueue roots + drain a small batch.
  if (triggeredBy === "cron") {
    const enqueued = await enqueueRootDiscovery(env);
    const drain = await drainJobBatch(env, ua);
    const summary = {
      startedAt,
      finishedAt: new Date().toISOString(),
      status: "partial",
      triggeredBy,
      mode: "durable_job_queue",
      enqueued,
      ...drain,
    };
    try {
      await env.DB.prepare(
        `INSERT INTO ingestion_run_log (ran_at, source, runtime, status, detail)
         VALUES (?, 'jsda', 'cloudflare', ?, ?)`,
      )
        .bind(startedAt, "partial", JSON.stringify(summary))
        .run();
    } catch {
      /* ignore */
    }
    return summary;
  }

  // Manual: full discovery still available for ops backfill.
  // Optional onlyDataset short-circuits to one source for min-segment runs.
  const allPlans: { dataset: DatasetId; url: string }[] = [
    { dataset: "jsda_otc_bond_reference_prices", url: OTC_INDEX },
    { dataset: "jsda_tokyo_repo_rates", url: REPO_INDEX },
    { dataset: "jsda_corporate_bond_transactions", url: CORP_INDEX },
  ];
  const plans = onlyDataset
    ? allPlans.filter((p) => p.dataset === onlyDataset)
    : allPlans;
  const results: CollectResult[] = [];
  for (const plan of plans) {
    results.push(await collectWithDiscovery(env, plan.dataset, plan.url, ua));
  }
  const passed = results.filter((r) => r.status === "pass").length;
  const failed = results.filter((r) => r.status === "fail").length;
  const partial = results.filter((r) => r.status === "partial").length;
  const finishedAt = new Date().toISOString();
  const status =
    failed > 0 ? "partial" : partial > 0 ? "partial" : passed === results.length ? "pass" : "partial";
  const summary = {
    startedAt,
    finishedAt,
    status,
    triggeredBy,
    mode: "manual_full_discovery",
    datasetCount: results.length,
    passed,
    failed,
    partial,
    results,
  };
  try {
    await env.DB.prepare(
      `INSERT INTO ingestion_run_log (ran_at, source, runtime, status, detail)
       VALUES (?, 'jsda', 'cloudflare', ?, ?)`,
    )
      .bind(startedAt, summary.status, JSON.stringify(summary))
      .run();
  } catch (e) {
    (summary as Record<string, unknown>).d1Error = (e as Error).message;
  }
  return summary;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({
        ok: true,
        worker: "ingestion-jsda",
        datasets: 3,
        allowlist: [...ALLOWED_HOSTS],
        note:
          "immutable raw R2 acquisition; structured parse is trusted Python downstream",
      });
    }
    if (url.pathname === "/v1/run") {
      if (request.method !== "POST") {
        return Response.json({ error: "POST required" }, { status: 405 });
      }
      if (!(await authorized(request, env.INGESTION_RUN_TOKEN))) {
        return Response.json({ error: "unauthorized" }, { status: 401 });
      }
      const ds = url.searchParams.get("dataset") || "";
      const allowed: DatasetId[] = [
        "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates",
        "jsda_corporate_bond_transactions",
      ];
      const only =
        ds && (allowed as string[]).includes(ds) ? (ds as DatasetId) : undefined;
      const summary = await runAll(env, "manual", only);
      return Response.json({ ok: summary.status === "pass", summary });
    }
    return Response.json({ error: "not found" }, { status: 404 });
  },

  async scheduled(
    _event: ScheduledEvent,
    env: Env,
    ctx: ExecutionContext,
  ): Promise<void> {
    ctx.waitUntil(runAll(env, "cron"));
  },
};
