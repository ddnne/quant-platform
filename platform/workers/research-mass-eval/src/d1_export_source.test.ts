import { afterEach, describe, expect, it, vi } from "vitest";
import { d1ExportDownloadUrlDenied, d1ExportSourceOutbound } from "./d1_export_source";
import { parseD1BackupEncryptRequest } from "./d1_backup_encrypt_contract";

const JOB_HEADERS = {
  "x-personal-job-id": "d1b-one",
  "x-personal-request-digest": `sha256:${"a".repeat(64)}`,
  "x-personal-job-kind": "d1-backup",
};

const ALLOWED =
  "https://acct.r2.cloudflarestorage.com/export.sql?X-Amz-Signature=not-for-logs";

describe("d1 export Container outbound", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rejects extra backup request fields that would carry a URL", () => {
    const parsed = parseD1BackupEncryptRequest({
      job_id: "d1b-one",
      environment: "staging",
      signed_url: ALLOWED,
    });
    expect(parsed.ok).toBe(false);
  });

  it("denies absent config, bad hosts, and streams an allowed signed_url", async () => {
    const download = new Request("http://d1.export/v1/download", {
      headers: JOB_HEADERS,
    });
    expect(d1ExportDownloadUrlDenied("https://example.invalid/export.sql")).toBe(
      true,
    );
    expect(d1ExportDownloadUrlDenied(ALLOWED)).toBe(false);

    const missing = await d1ExportSourceOutbound(download, {});
    expect(missing.status).toBe(409);
    const missingBody = await missing.text();
    expect(missingBody).not.toContain("r2.cloudflarestorage.com");
    expect((JSON.parse(missingBody) as { error: string }).error).toBe(
      "export_not_authorized",
    );

    const deniedHost = await d1ExportSourceOutbound(download, {
      D1_BACKUP_EXPORT_SIGNED_URL: "https://example.invalid/export.sql",
    });
    expect(deniedHost.status).toBe(403);
    expect(await deniedHost.text()).not.toContain("example.invalid");

    const sql = new TextEncoder().encode("CREATE TABLE t(id INTEGER);\n");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const href = String(input);
        expect(href.startsWith("https://acct.r2.cloudflarestorage.com/")).toBe(
          true,
        );
        return new Response(sql, {
          status: 200,
          headers: { "content-length": String(sql.byteLength) },
        });
      }),
    );
    const streamed = await d1ExportSourceOutbound(download, {
      D1_BACKUP_EXPORT_SIGNED_URL: ALLOWED,
    });
    expect(streamed.status).toBe(200);
    expect(new Uint8Array(await streamed.arrayBuffer())).toEqual(sql);

    const keyMissing = await d1ExportSourceOutbound(
      new Request("http://d1.export/v1/key", { headers: JOB_HEADERS }),
      {},
    );
    expect(keyMissing.status).toBe(409);
    const rawKey = new Uint8Array(32).map((_, i) => i + 1);
    const keyOk = await d1ExportSourceOutbound(
      new Request("http://d1.export/v1/key", { headers: JOB_HEADERS }),
      { D1_BACKUP_KEY: new TextDecoder("latin1").decode(rawKey) },
    );
    expect(keyOk.status).toBe(200);
    expect(new Uint8Array(await keyOk.arrayBuffer())).toEqual(rawKey);
  });
});
