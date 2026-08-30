import {
  AcquisitionRequestRejected,
  decodeRequest,
} from "../../ingestion-secrets/src/jquants_acquisition_registry";
import type { JquantsAcquisitionRequestV2 } from "../../ingestion-secrets/src/jquants_acquisition_types";
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
const ALLOWED_REQUEST_HEADERS = new Set([
  "accept",
  "content-length",
  "content-type",
  "host",
]);

type HistoryEnv = {
  JQUANTS_ACQUISITION?: unknown;
};

type AcquisitionBinding = {
  fetch_governed_page(request: JquantsAcquisitionRequestV2): Promise<Response>;
};

function acquisitionBinding(env: HistoryEnv): AcquisitionBinding | null {
  const value = env.JQUANTS_ACQUISITION;
  if (
    typeof value !== "object" ||
    value === null ||
    !("fetch_governed_page" in value) ||
    typeof value.fetch_governed_page !== "function"
  ) {
    return null;
  }
  return value as AcquisitionBinding;
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

function headersAreClosed(request: Request): boolean {
  for (const [name] of request.headers) {
    if (!ALLOWED_REQUEST_HEADERS.has(headerName(name))) return false;
  }
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
  } catch (error) {
    if (error instanceof AcquisitionRequestRejected) {
      return { ok: false, error: "request_rejected" };
    }
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
    url.hostname !== "history.source" ||
    url.search ||
    url.hash ||
    url.pathname !== FETCH_PATH
  ) {
    return responseJson({ error: "history source request denied" }, 403);
  }
  if (request.method !== "POST") {
    return responseJson({ error: "POST required" }, 405);
  }
  if (!headersAreClosed(request)) {
    return responseJson({ error: "history source headers denied" }, 403);
  }
  const length = contentLength(request);
  if (length === null) {
    return responseJson({ error: "invalid history source length" }, 400);
  }
  const binding = acquisitionBinding(env);
  if (!binding) {
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
  return binding.fetch_governed_page(decoded.value);
}
