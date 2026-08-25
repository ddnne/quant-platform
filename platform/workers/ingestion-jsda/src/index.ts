/// <reference types="@cloudflare/workers-types" />
/**
 * JSDA raw acquisition plane on Cloudflare (Phase 6.2.2).
 *
 * - Outbound host allowlist only (jsda.or.jp / www / market)
 * - Immutable raw keys: raw/jsda/{dataset}/{segment_id}/{sha256}.{ext}
 * - Archive discovery: year indexes + data files (not maxDataFiles=3 heuristic PASS)
 * - MAX_YEAR_PAGES default "1" is a rate/safety cap, not pagination exhaustion
 * - Structured XLS/XLSX parse stays trusted Python downstream (not TS)
 */

import { authorized } from "./authorized";
import {
  discoveryCapSemantics,
  parseDataFileCap,
  parseYearPageCap,
  type DiscoveryRunStatus,
} from "./discovery_caps";
import { json } from "./http_json";
import { sha256Hex } from "./sha256";

export interface Env {
  RAW_BUCKET: R2Bucket;
  DB: D1Database;
  JSDA_QUEUE: Queue<JsdaDatasetJob>;
  INGESTION_RUN_TOKEN?: string;
  USER_AGENT?: string;
  /** 0 = unlimited data-file fetches; small N is a rate/safety cap, not exhaustion. */
  MAX_DATA_FILES?: string;
  /** Rate/safety cap. Default "1". 0 = unlimited. Cap-hit is not exhaustion. */
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

export type DatasetId =
  | "jsda_otc_bond_reference_prices"
  | "jsda_tokyo_repo_rates"
  | "jsda_corporate_bond_transactions";

const DATASET_IDS = [
  "jsda_otc_bond_reference_prices",
  "jsda_tokyo_repo_rates",
  "jsda_corporate_bond_transactions",
] as const satisfies readonly DatasetId[];

const DATASET_ROOTS: Readonly<Record<DatasetId, string>> = {
  jsda_otc_bond_reference_prices: OTC_INDEX,
  jsda_tokyo_repo_rates: REPO_INDEX,
  jsda_corporate_bond_transactions: CORP_INDEX,
};

const DATASET_JOB_VERSION = "jsda-dataset-job/v1" as const;
const DATASET_JOB_KEYS = new Set([
  "version",
  "dataset",
  "requested_by",
  "requested_at",
  "job_id",
]);

export interface JsdaDatasetJob {
  version: typeof DATASET_JOB_VERSION;
  dataset: DatasetId;
  requested_by: "cron" | "manual";
  requested_at: string;
  job_id: string;
}

function isDatasetId(value: unknown): value is DatasetId {
  return (
    typeof value === "string" &&
    (DATASET_IDS as readonly string[]).includes(value)
  );
}

function isJsdaDatasetJob(value: unknown): value is JsdaDatasetJob {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  const keys = Object.keys(candidate);
  if (
    keys.length !== DATASET_JOB_KEYS.size ||
    keys.some((key) => !DATASET_JOB_KEYS.has(key))
  ) {
    return false;
  }
  if (
    candidate.version !== DATASET_JOB_VERSION ||
    !isDatasetId(candidate.dataset) ||
    (candidate.requested_by !== "cron" && candidate.requested_by !== "manual") ||
    typeof candidate.requested_at !== "string" ||
    typeof candidate.job_id !== "string" ||
    candidate.job_id.length < 1 ||
    candidate.job_id.length > 200 ||
    !/^[A-Za-z0-9:._-]+$/.test(candidate.job_id)
  ) {
    return false;
  }
  const requestedAt = new Date(candidate.requested_at);
  return (
    !Number.isNaN(requestedAt.getTime()) &&
    requestedAt.toISOString() === candidate.requested_at
  );
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
  status: DiscoveryRunStatus;
  expectedPages: number;
  fetchedPages: number;
  filesStored: number;
  keys: string[];
  detail: string;
  pagination_exhausted: boolean;
  year_page_cap_hit: boolean;
  data_file_cap_hit: boolean;
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
        pagination_exhausted: false,
        year_page_cap_hit: false,
        data_file_cap_hit: false,
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
    const yearPagesFound = rootLinks.filter(isYearArchive);
    // Prefer highest archive year first (list order on index is not reliable).
    let yearPages = yearPagesFound.slice().sort((a, b) => {
      const ya = Number(YEAR_ARCHIVE_RE.exec(new URL(a).pathname)?.[1] || 0);
      const yb = Number(YEAR_ARCHIVE_RE.exec(new URL(b).pathname)?.[1] || 0);
      return yb - ya;
    });
    const maxYearPages = parseYearPageCap(env.MAX_YEAR_PAGES);
    if (maxYearPages > 0) {
      yearPages = yearPages.slice(0, maxYearPages);
    }
    const dataFromRoot = rootLinks.filter(isDataUrl);

    // Crawl year archives when present (OTC style). Cap is a rate/safety limit.
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
    const maxFiles = parseDataFileCap(env.MAX_DATA_FILES);
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

    const sem = discoveryCapSemantics({
      yearPagesFound: yearPagesFound.length,
      maxYearPages,
      dataFilesDiscovered: allData.size,
      dataFilesStored: stored,
      maxDataFiles: maxFiles,
      fetchErrors: errors.length,
    });

    const manifestKey = await putManifest(env, dataset, `discovery_${day}`, {
      dataset,
      rootIndex,
      discovered_year_pages: yearPagesFound.length,
      fetched_year_pages: yearPages.length,
      discovered_data_files: allData.size,
      stored,
      year_page_cap_hit: sem.year_page_cap_hit,
      data_file_cap_hit: sem.data_file_cap_hit,
      pagination_exhausted: sem.pagination_exhausted,
      artifacts,
      errors: errors.slice(0, 20),
      fetched_at: new Date().toISOString(),
    });
    keys.push(manifestKey);

    return {
      dataset,
      status: sem.status,
      expectedPages: 1 + yearPagesFound.length,
      fetchedPages,
      filesStored: stored,
      keys,
      pagination_exhausted: sem.pagination_exhausted,
      year_page_cap_hit: sem.year_page_cap_hit,
      data_file_cap_hit: sem.data_file_cap_hit,
      detail:
        `years=${yearPages.length}/${yearPagesFound.length} data_discovered=${allData.size}` +
        ` stored=${stored} pagination_exhausted=${sem.pagination_exhausted}` +
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
      pagination_exhausted: false,
      year_page_cap_hit: false,
      data_file_cap_hit: false,
      detail: (e as Error).message || String(e),
    };
  }
}

function newDatasetJob(
  dataset: DatasetId,
  requestedBy: JsdaDatasetJob["requested_by"],
  requestedAt: string,
): JsdaDatasetJob {
  return {
    version: DATASET_JOB_VERSION,
    dataset,
    requested_by: requestedBy,
    requested_at: requestedAt,
    job_id: `jsda:${dataset}:${requestedAt}:${crypto.randomUUID()}`,
  };
}

async function enqueueDatasetJobs(
  env: Env,
  requestedBy: JsdaDatasetJob["requested_by"],
  onlyDataset?: DatasetId,
): Promise<readonly DatasetId[]> {
  const datasets = onlyDataset ? [onlyDataset] : [...DATASET_IDS];
  const requestedAt = new Date().toISOString();
  await env.JSDA_QUEUE.sendBatch(
    datasets.map((dataset) => ({
      body: newDatasetJob(dataset, requestedBy, requestedAt),
      contentType: "json",
    })),
  );
  return datasets;
}

async function recordJobState(
  env: Env,
  job: JsdaDatasetJob,
  state: "running" | "pass" | "partial" | "fail" | "retry",
  attempt: number,
  detail: string,
  reasonCode: string | null = null,
): Promise<void> {
  const now = new Date().toISOString();
  try {
    await env.DB.prepare(
      `INSERT INTO jsda_acquisition_jobs
       (job_id, dataset, job_type, target_url, segment_id, state, attempt, priority,
        reason_code, detail, created_at, updated_at)
       VALUES (?, ?, 'discover_root', ?, NULL, ?, ?, 10, ?, ?, ?, ?)
       ON CONFLICT(job_id) DO UPDATE SET
         state=excluded.state,
         attempt=excluded.attempt,
         reason_code=excluded.reason_code,
         detail=excluded.detail,
         updated_at=excluded.updated_at`,
    )
      .bind(
        job.job_id,
        job.dataset,
        DATASET_ROOTS[job.dataset],
        state,
        attempt,
        reasonCode,
        detail.slice(0, 500),
        job.requested_at,
        now,
      )
      .run();
  } catch (error) {
    // Acquisition remains governed by Queue retry/DLQ even before migration 0008.
    console.error("jsda_job_audit_write_failed", {
      job_id: job.job_id,
      dataset: job.dataset,
      state,
      error: (error as Error).message,
    });
  }
}

async function recordRunResult(
  env: Env,
  job: JsdaDatasetJob,
  result: CollectResult,
  attempt: number,
): Promise<void> {
  const status = queueOutcome(result);
  try {
    await env.DB.prepare(
      `INSERT INTO ingestion_run_log (ran_at, source, runtime, status, detail)
       VALUES (?, 'jsda', 'cloudflare', ?, ?)`,
    )
      .bind(
        job.requested_at,
        status,
        JSON.stringify({
          mode: "cloudflare_queue",
          job_id: job.job_id,
          requested_by: job.requested_by,
          attempt,
          ...result,
          status,
        }),
      )
      .run();
  } catch (error) {
    console.error("jsda_run_log_write_failed", {
      job_id: job.job_id,
      dataset: job.dataset,
      error: (error as Error).message,
    });
  }
}

function queueOutcome(result: CollectResult): DiscoveryRunStatus {
  const strictPass =
    result.status === "pass" &&
    result.pagination_exhausted === true &&
    result.filesStored > 0;
  if (strictPass) return "pass";
  return result.status === "fail" ? "fail" : "partial";
}

async function consumeDatasetMessage(
  message: Message<unknown>,
  env: Env,
): Promise<void> {
  if (!isJsdaDatasetJob(message.body)) {
    console.error("jsda_queue_message_rejected", {
      message_id: message.id,
      attempt: message.attempts,
      reason: "invalid_dataset_job",
    });
    // Invalid schemas are permanent failures; do not poison the retry/DLQ path.
    message.ack();
    return;
  }

  const job = message.body;
  try {
    await recordJobState(env, job, "running", message.attempts, "queue consumer started");
    const result = await collectWithDiscovery(
      env,
      job.dataset,
      DATASET_ROOTS[job.dataset],
      env.USER_AGENT || UA,
    );
    await recordRunResult(env, job, result, message.attempts);
    const outcome = queueOutcome(result);
    if (outcome === "pass") {
      await recordJobState(env, job, "pass", message.attempts, result.detail);
      message.ack();
      return;
    }

    await recordJobState(
      env,
      job,
      outcome,
      message.attempts,
      result.detail,
      `discovery_${outcome}`,
    );
    message.retry();
  } catch (error) {
    await recordJobState(
      env,
      job,
      "retry",
      message.attempts,
      (error as Error).message || String(error),
      "consumer_exception",
    );
    message.retry();
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      if (request.method !== "GET") {
        return json({ error: "GET required" }, 405);
      }
      return json({
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
        return json({ error: "POST required" }, 405);
      }
      if (!(await authorized(request, env.INGESTION_RUN_TOKEN))) {
        return json({ error: "unauthorized" }, 401);
      }
      const requestedDataset = url.searchParams.get("dataset");
      if (url.searchParams.has("dataset") && !isDatasetId(requestedDataset)) {
        return json({ error: "invalid dataset" }, 400);
      }
      const datasets = await enqueueDatasetJobs(
        env,
        "manual",
        requestedDataset as DatasetId | undefined,
      );
      return json(
        {
          accepted: true,
          mode: "cloudflare_queue",
          queued: datasets.length,
          datasets,
        },
        202,
      );
    }
    return json({ error: "not found" }, 404);
  },

  async scheduled(
    _controller: ScheduledController,
    env: Env,
    ctx: ExecutionContext,
  ): Promise<void> {
    ctx.waitUntil(enqueueDatasetJobs(env, "cron"));
  },

  async queue(batch: MessageBatch<unknown>, env: Env): Promise<void> {
    // Keep JSDA outbound acquisition polite and bounded within each batch.
    for (const message of batch.messages) {
      await consumeDatasetMessage(message, env);
    }
  },
} satisfies ExportedHandler<Env, unknown>;
