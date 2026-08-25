import type { DatasetId } from "./queue_contract";

const OFFICIAL_HOSTS = new Set([
  "jsda.or.jp",
  "www.jsda.or.jp",
  "market.jsda.or.jp",
]);

const LINK_RE = /<a\s+[^>]*href=["']([^"']+)["']/gi;
const DATA_EXTENSIONS = [".csv", ".xlsx", ".xls"];
const YEAR_ARCHIVE_RE = /archive(20\d{2})\.html/i;
const REPO_NON_DATA_MARKERS = ["reference", "bessi", "kijun", "koubo", "youkou"];
const MAX_ARTIFACT_BYTES = 32 * 1024 * 1024;
const MAX_REDIRECTS = 5;

export class TransientAcquisitionError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string, message: string) {
    super(message);
    this.name = "TransientAcquisitionError";
    this.reasonCode = reasonCode;
  }
}

export class PermanentAcquisitionError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string, message: string) {
    super(message);
    this.name = "PermanentAcquisitionError";
    this.reasonCode = reasonCode;
  }
}

export interface FetchedArtifact {
  status: number;
  bytes: ArrayBuffer;
  contentType: string;
  finalUrl: string;
}

export function allowedHosts(): string[] {
  return [...OFFICIAL_HOSTS].sort();
}

export function hostAllowed(raw: string): boolean {
  try {
    const url = new URL(raw);
    return (
      url.protocol === "https:" &&
      url.username === "" &&
      url.password === "" &&
      (url.port === "" || url.port === "443") &&
      OFFICIAL_HOSTS.has(url.hostname.toLowerCase())
    );
  } catch {
    return false;
  }
}

export function absolutize(base: string, href: string): string | null {
  try {
    const url = new URL(href, base);
    url.hash = "";
    return hostAllowed(url.toString()) ? url.toString() : null;
  } catch {
    return null;
  }
}

export function isDataUrl(raw: string): boolean {
  const path = new URL(raw).pathname.toLowerCase();
  return DATA_EXTENSIONS.some((extension) => path.endsWith(extension));
}

function basename(raw: string): string {
  return new URL(raw).pathname.split("/").filter(Boolean).pop()?.toLowerCase() || "";
}

function preferredFormats(urls: readonly string[]): string[] {
  const priority = new Map([
    ["csv", 0],
    ["xlsx", 1],
    ["xls", 2],
  ]);
  const preferred = new Map<string, string>();
  for (const url of urls) {
    const path = new URL(url).pathname.toLowerCase();
    const extension = extensionOf(url);
    const stem = path.slice(0, -(extension.length + 1));
    const current = preferred.get(stem);
    if (
      current === undefined ||
      (priority.get(extension) ?? 99) <
        (priority.get(extensionOf(current)) ?? 99)
    ) {
      preferred.set(stem, url);
    }
  }
  return [...preferred.values()].sort();
}

/** Dataset-specific official file selection, aligned with trusted Python routing. */
export function selectDatasetDataUrls(
  dataset: DatasetId,
  links: readonly string[],
): string[] {
  const data = links.filter(isDataUrl);
  if (dataset === "jsda_otc_bond_reference_prices") {
    return preferredFormats(
      data.filter((url) => {
        const name = basename(url);
        return (
          !name.includes("matrix") &&
          !name.includes("csvheader") &&
          !/^r\d{6}\.(?:csv|xlsx|xls)$/.test(name)
        );
      }),
    );
  }
  if (dataset === "jsda_tokyo_repo_rates") {
    const rateFiles = data.filter((url) => {
      const name = basename(url);
      return !REPO_NON_DATA_MARKERS.some((marker) => name.includes(marker));
    });
    const timeSeries = rateFiles.filter((url) => {
      const name = basename(url);
      return name.includes("trr") &&
        (name.includes("ts") || name.includes("list") || name.includes("ichiran"));
    });
    const candidates = timeSeries.length > 0
      ? timeSeries
      : rateFiles.filter((url) => basename(url).includes("trr"));
    return candidates.length > 0 ? [preferredFormats(candidates)[0]] : [];
  }
  return preferredFormats(
    data.filter((url) => /^torihiki20\d{2}\.(?:csv|xlsx|xls)$/.test(basename(url))),
  );
}

export function isYearArchive(raw: string): boolean {
  return YEAR_ARCHIVE_RE.test(new URL(raw).pathname);
}

export function extractLinks(html: string, base: string): string[] {
  const links: string[] = [];
  LINK_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = LINK_RE.exec(html)) !== null) {
    const url = absolutize(base, match[1].replace(/&amp;/g, "&").trim());
    if (url !== null) links.push(url);
  }
  return [...new Set(links)].sort();
}

export function extensionOf(raw: string): string {
  const name = new URL(raw).pathname.split("/").filter(Boolean).pop() || "artifact.bin";
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index + 1).toLowerCase() : "bin";
}

function classifyHttpFailure(status: number, url: string): never {
  if (status === 408 || status === 429 || status >= 500) {
    throw new TransientAcquisitionError(
      `http_${status}`,
      `transient JSDA HTTP ${status}: ${url}`,
    );
  }
  throw new PermanentAcquisitionError(
    `http_${status}`,
    `permanent JSDA HTTP ${status}: ${url}`,
  );
}

export async function fetchAllowed(
  raw: string,
  userAgent: string,
  redirectCount = 0,
): Promise<FetchedArtifact> {
  if (!hostAllowed(raw)) {
    throw new PermanentAcquisitionError(
      "host_not_allowlisted",
      `JSDA host is not allowlisted: ${raw}`,
    );
  }
  if (redirectCount > MAX_REDIRECTS) {
    throw new PermanentAcquisitionError(
      "redirect_limit",
      `JSDA redirect limit exceeded: ${raw}`,
    );
  }

  let response: Response;
  try {
    response = await fetch(raw, {
      headers: { "User-Agent": userAgent, Accept: "*/*" },
      redirect: "manual",
    });
  } catch (error) {
    throw new TransientAcquisitionError(
      "network_error",
      `JSDA network error: ${error instanceof Error ? error.message : String(error)}`,
    );
  }

  if (response.status >= 300 && response.status < 400) {
    const location = response.headers.get("Location");
    if (location === null) {
      throw new PermanentAcquisitionError(
        "redirect_without_location",
        `JSDA redirect has no Location header: ${raw}`,
      );
    }
    const target = absolutize(raw, location);
    if (target === null) {
      throw new PermanentAcquisitionError(
        "redirect_host_not_allowlisted",
        `JSDA redirect leaves the official host allowlist: ${raw}`,
      );
    }
    return fetchAllowed(target, userAgent, redirectCount + 1);
  }

  if (response.status >= 400) classifyHttpFailure(response.status, raw);

  const declaredLength = response.headers.get("content-length");
  if (declaredLength !== null && Number(declaredLength) > MAX_ARTIFACT_BYTES) {
    throw new PermanentAcquisitionError(
      "artifact_too_large",
      `JSDA artifact exceeds ${MAX_ARTIFACT_BYTES} bytes: ${raw}`,
    );
  }

  const reader = response.body?.getReader();
  if (reader === undefined) {
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength > MAX_ARTIFACT_BYTES) {
      throw new PermanentAcquisitionError(
        "artifact_too_large",
        `JSDA artifact exceeds ${MAX_ARTIFACT_BYTES} bytes: ${raw}`,
      );
    }
    return {
      status: response.status,
      bytes,
      contentType: response.headers.get("content-type") || "application/octet-stream",
      finalUrl: raw,
    };
  }

  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value === undefined) continue;
    total += value.byteLength;
    if (total > MAX_ARTIFACT_BYTES) {
      await reader.cancel();
      throw new PermanentAcquisitionError(
        "artifact_too_large",
        `JSDA artifact exceeds ${MAX_ARTIFACT_BYTES} bytes: ${raw}`,
      );
    }
    chunks.push(value);
  }
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return {
    status: response.status,
    bytes: merged.buffer,
    contentType: response.headers.get("content-type") || "application/octet-stream",
    finalUrl: raw,
  };
}
