import {
  AcquisitionRequestRejected,
  decodeRequest,
} from "../../ingestion-secrets/src/jquants_acquisition_registry";
import type {
  JquantsAcquisitionRequestV2,
  JquantsAcquisitionRpc,
} from "../../ingestion-secrets/src/jquants_acquisition_types";

export const PERSONAL_HISTORY_DATASETS = [
  "markets_calendar",
  "equities_master",
  "fins_summary",
  "equities_bars_daily",
] as const;

export type PersonalHistoryDataset = (typeof PERSONAL_HISTORY_DATASETS)[number];

const ALLOWED_DATASETS = new Set<string>(PERSONAL_HISTORY_DATASETS);
const FETCH_PATH = "/v1/fetch-governed-page";
const MAX_REQUEST_BYTES = 16 * 1024;

export const HISTORY_SOURCE_HOST = "history.source";
export const HISTORY_SOURCE_USER_AGENT = "quant-personal-history/v13";
export const HISTORY_SOURCE_FIXED_HEADERS: Record<string, string> = {
  accept: "application/json",
  "accept-encoding": "identity",
  connection: "close",
  "content-type": "application/json; charset=utf-8",
  "user-agent": HISTORY_SOURCE_USER_AGENT,
};

type HistoryEnv = {
  JQUANTS_ACQUISITION?: JquantsAcquisitionRpc | Service;
};

function acquisitionRpc(
  binding: HistoryEnv["JQUANTS_ACQUISITION"],
): JquantsAcquisitionRpc | undefined {
  if (
    binding !== undefined &&
    "fetch_governed_page" in binding &&
    typeof binding.fetch_governed_page === "function"
  ) {
    return binding;
  }
  return undefined;
}

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function headerName(name: string): string {
  return name.trim().toLowerCase();
}

export function historySourceHeadersAreClosed(request: Request): boolean {
  const seen = new Set<string>();
  for (const [name, value] of request.headers) {
    const key = headerName(name);
    if (seen.has(key)) return false;
    seen.add(key);
    if (key === "host") {
      if (value !== HISTORY_SOURCE_HOST) return false;
      continue;
    }
    if (key === "content-length") {
      if (!/^\d+$/.test(value)) return false;
      continue;
    }
    const expected = HISTORY_SOURCE_FIXED_HEADERS[key];
    if (expected === undefined || expected !== value) return false;
  }
  for (const required of Object.keys(HISTORY_SOURCE_FIXED_HEADERS)) {
    if (!seen.has(required)) return false;
  }
  if (!seen.has("host") || !seen.has("content-length")) return false;
  return true;
}

function contentLength(request: Request): number | null {
  const raw = request.headers.get("content-length");
  if (!raw || !/^\d+$/.test(raw)) return null;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1 || value > MAX_REQUEST_BYTES) {
    return null;
  }
  return value;
}

export function isPersonalHistoryDataset(
  value: string,
): value is PersonalHistoryDataset {
  return ALLOWED_DATASETS.has(value);
}

export function parsePersonalHistorySourceRequest(
  body: unknown,
): { ok: true; value: JquantsAcquisitionRequestV2 } | { ok: false; error: string } {
  try {
    const request = decodeRequest(body);
    if (!isPersonalHistoryDataset(request.dataset_id)) {
      return { ok: false, error: "dataset_not_allowed" };
    }
    return { ok: true, value: request };
  } catch {
    return { ok: false, error: "request_rejected" };
  }
}

/** Narrow governed-page capability exposed only to history.source. */
export async function personalHistorySourceOutbound(
  request: Request,
  env: HistoryEnv,
): Promise<Response> {
  const url = new URL(request.url);
  if (
    url.hostname !== HISTORY_SOURCE_HOST ||
    url.search ||
    url.hash ||
    url.pathname !== FETCH_PATH
  ) {
    return responseJson({ error: "history source request denied" }, 403);
  }
  if (request.method !== "POST") {
    return responseJson({ error: "POST required" }, 405);
  }
  if (!historySourceHeadersAreClosed(request)) {
    return responseJson({ error: "history source headers denied" }, 403);
  }
  const length = contentLength(request);
  if (length === null) {
    return responseJson({ error: "invalid history source length" }, 400);
  }
  const rpc = acquisitionRpc(env.JQUANTS_ACQUISITION);
  if (rpc === undefined) {
    return responseJson({ error: "history source binding unavailable" }, 503);
  }
  let parsed: unknown;
  try {
    const bytes = new Uint8Array(await request.arrayBuffer());
    if (bytes.byteLength !== length) {
      return responseJson({ error: "history source length mismatch" }, 400);
    }
    parsed = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return responseJson({ error: "history source body is not JSON" }, 400);
  }
  const decoded = parsePersonalHistorySourceRequest(parsed);
  if (!decoded.ok) {
    return responseJson({ error: decoded.error }, 403);
  }
  return rpc.fetch_governed_page(decoded.value);
}
