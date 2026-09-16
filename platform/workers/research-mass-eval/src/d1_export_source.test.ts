import { afterEach, describe, expect, it, vi } from "vitest";
import { d1ExportSourceOutbound } from "./d1_export_source";
import {
  D1_BACKUP_MAX_RESTORED_SQLITE_BYTES,
  STANDARD_4_PHYSICAL_DISK_BYTES,
  d1ExportDownloadUrlDenied,
  d1ExportUrlSha256,
  parseD1BackupEncryptRequest,
  parseD1ExportBundle,
} from "./d1_backup_encrypt_contract";

const ALLOWED =
  "https://acct.r2.cloudflarestorage.com/export.sql?X-Amz-Signature=not-for-logs";

const BUNDLE = {
  schema_version: "d1-export-bundle/v1",
  environment: "staging",
  database_name: "quant-ingest-staging",
  database_id: "d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb",
  at_bookmark: "bm-1",
  export_completed_at: "2026-09-16T05:00:00Z",
  download_host: "acct.r2.cloudflarestorage.com",
  signed_url: ALLOWED,
};

describe("d1 export Container outbound", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("separates accepted restored sqlite from standard-4 physical disk", () => {
    expect(D1_BACKUP_MAX_RESTORED_SQLITE_BYTES).toBe(5 * 1024 * 1024 * 1024);
    expect(STANDARD_4_PHYSICAL_DISK_BYTES).toBe(20 * 1024 * 1024 * 1024);
    expect(D1_BACKUP_MAX_RESTORED_SQLITE_BYTES).toBeLessThan(
      STANDARD_4_PHYSICAL_DISK_BYTES,
    );
  });

  it("rejects extra backup request fields that would carry a URL", () => {
    const parsed = parseD1BackupEncryptRequest({
      job_id: "d1b-one",
      environment: "staging",
      signed_url: ALLOWED,
    });
    expect(parsed.ok).toBe(false);
  });

  it("streams only when the job URL fingerprint matches the current bundle", async () => {
    const urlSha = await d1ExportUrlSha256(ALLOWED);
    const download = new Request("http://d1.export/v1/download", {
      headers: {
        "x-personal-job-id": "d1b-one",
        "x-personal-request-digest": `sha256:${"a".repeat(64)}`,
        "x-personal-job-kind": "d1-backup",
        "x-d1-export-url-sha256": urlSha,
      },
    });
    expect(d1ExportDownloadUrlDenied("https://example.invalid/export.sql", BUNDLE.download_host)).toBe(
      true,
    );
    expect(d1ExportDownloadUrlDenied(ALLOWED, BUNDLE.download_host)).toBe(false);

    const missing = await d1ExportSourceOutbound(download, {});
    expect(missing.status).toBe(409);

    const stale = await d1ExportSourceOutbound(download, {
      D1_BACKUP_EXPORT_BUNDLE: JSON.stringify({
        ...BUNDLE,
        signed_url: "https://acct.r2.cloudflarestorage.com/other.sql?X-Amz-Signature=stale",
      }),
    });
    expect(stale.status).toBe(409);
    expect(await stale.text()).not.toContain("X-Amz-Signature");

    const sql = new TextEncoder().encode("CREATE TABLE t(id INTEGER);\n");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        expect(String(input)).toBe(ALLOWED);
        return new Response(sql, {
          status: 200,
          headers: { "content-length": String(sql.byteLength) },
        });
      }),
    );
    const streamed = await d1ExportSourceOutbound(download, {
      D1_BACKUP_EXPORT_BUNDLE: JSON.stringify(BUNDLE),
    });
    expect(streamed.status).toBe(200);
    expect(new Uint8Array(await streamed.arrayBuffer())).toEqual(sql);

    const parsed = await parseD1ExportBundle(JSON.stringify(BUNDLE));
    expect(parsed.ok).toBe(true);

    const keyMissing = await d1ExportSourceOutbound(
      new Request("http://d1.export/v1/key", {
        headers: {
          "x-personal-job-id": "d1b-one",
          "x-personal-request-digest": `sha256:${"a".repeat(64)}`,
          "x-personal-job-kind": "d1-backup",
        },
      }),
      {},
    );
    expect(keyMissing.status).toBe(409);
  });
});
