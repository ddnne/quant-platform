import { env } from "cloudflare:workers";
import { reset } from "cloudflare:test";
import { afterEach, describe, expect, it } from "vitest";

import { CONTROLLED_PILOT_RUNNER_VERSION } from "../src/controlled_pilot_contract";
import {
  CONTROLLED_JSON_TYPE,
  CONTROLLED_LEASE_CLOCK_SKEW_SECONDS,
  CONTROLLED_LEASE_TTL_SECONDS,
  controlledContainerR2Outbound,
} from "../src/controlled_pilot_container_r2";

type RuntimeEnv = { STRUCTURED_BUCKET: R2Bucket };

const runtimeEnv = env as RuntimeEnv;
const jobId = "runtime-lease-1";
const requestDigest = `sha256:${"ab".repeat(32)}`;
const otherDigest = `sha256:${"cd".repeat(32)}`;
const leaseKey = `research/controlled_pilot/v1/jobs/${jobId}/container-lease.json`;
const terminalKey = `research/controlled_pilot/v1/jobs/${jobId}/container-terminal.json`;

const identityHeaders = {
  "content-type": CONTROLLED_JSON_TYPE,
  "x-personal-job-id": jobId,
  "x-personal-request-digest": requestDigest,
  "x-personal-runner-version": CONTROLLED_PILOT_RUNNER_VERSION,
  "x-personal-job-kind": "controlled-pilot",
};

function hex(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

async function sha256(bytes: Uint8Array): Promise<string> {
  return `sha256:${hex(await crypto.subtle.digest("SHA-256", bytes))}`;
}

function leaseDoc(owner: string, token: number, now = Date.now() / 1000) {
  return {
    identity: "controlled_pilot_v1",
    job_id: jobId,
    request_digest: requestDigest,
    execution_id: requestDigest,
    runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
    kind: "controlled-pilot",
    owner_nonce: owner,
    fencing_token: token,
    expires_at: now + CONTROLLED_LEASE_TTL_SECONDS,
    heartbeat_at: now,
    status: "CLAIMED",
  };
}

function fourRecords() {
  return [{ k: 1 }, { k: 2 }, { k: 3 }, { k: 4 }];
}

function terminalDoc(owner: string, token: number) {
  return {
    ok: true,
    identity: "controlled_pilot_v1",
    job_id: jobId,
    request_digest: requestDigest,
    execution_id: requestDigest,
    runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
    status: "COMPLETED",
    owner_nonce: owner,
    fencing_token: token,
    automatic_promotion: false,
    live_orders_enabled: false,
    ephemeral_cleaned: true,
    papers: fourRecords(),
    risks: fourRecords(),
    selection: { decision: "HOLD" },
    knowledge: { kind: "knowledge" },
    generation: 1,
    max_parallel: 2,
  };
}

function failedTerminalDoc(owner: string, token: number) {
  return {
    ok: false,
    identity: "controlled_pilot_v1",
    job_id: jobId,
    request_digest: requestDigest,
    execution_id: requestDigest,
    runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
    status: "FAILED",
    owner_nonce: owner,
    fencing_token: token,
    error: "controlled_execution_failed",
    go: false,
    automatic_promotion: false,
    live_orders_enabled: false,
  };
}

function encodeB64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i += 1) {
    binary += String.fromCharCode(bytes[i]!);
  }
  return btoa(binary);
}

async function outbound(key: string, init: RequestInit): Promise<Response> {
  const response = await controlledContainerR2Outbound(
    new Request(`http://research.r2/${key}`, init),
    runtimeEnv,
    key,
  );
  if (!response) throw new Error("router did not handle key");
  return response;
}

async function putJson(
  key: string,
  value: unknown,
  extra: Record<string, string> = {},
): Promise<Response> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  return outbound(key, {
    method: "PUT",
    headers: {
      ...identityHeaders,
      "content-length": String(bytes.byteLength),
      "x-content-sha256": await sha256(bytes),
      ...extra,
    },
    body: bytes,
  });
}

describe("real Miniflare R2 lease CAS", () => {
  afterEach(async () => {
    await reset();
  });

  it("create -> same-owner renew -> terminal uses raw R2 etag and quoted HTTP etag", async () => {
    const created = await putJson(leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-none-match": "*",
    });
    expect(created.status).toBe(201);
    expect(created.status).not.toBe(500);
    const createdBody = (await created.json()) as { etag: string };
    expect(createdBody.etag).toMatch(/^"[^"]+"$/);

    const stored = await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey);
    expect(stored).toBeTruthy();
    expect(stored!.etag.includes('"')).toBe(false);
    expect(stored!.httpEtag).toBe(`"${stored!.etag}"`);
    expect(createdBody.etag).toBe(stored!.httpEtag);

    await expect(
      runtimeEnv.STRUCTURED_BUCKET.put(leaseKey, await stored!.arrayBuffer(), {
        onlyIf: { etagMatches: stored!.httpEtag },
      }),
    ).rejects.toThrow(/quotes/i);

    const renewed = await putJson(leaseKey, leaseDoc("owner-nonce-1", 1, Date.now() / 1000 + 1), {
      "if-match": createdBody.etag,
    });
    expect(renewed.status).toBe(200);
    expect(renewed.status).not.toBe(500);
    const renewedBody = (await renewed.json()) as { etag: string };
    expect(renewedBody.etag).toMatch(/^"[^"]+"$/);
    expect(renewedBody.etag).not.toBe(createdBody.etag);

    const stale = await putJson(leaseKey, leaseDoc("owner-nonce-1", 1, Date.now() / 1000 + 2), {
      "if-match": createdBody.etag,
    });
    expect(stale.status).toBe(412);
    expect(stale.status).not.toBe(500);

    const staleTerminal = await putJson(terminalKey, terminalDoc("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
      "x-personal-lease-etag": createdBody.etag,
    });
    expect(staleTerminal.status).toBe(409);
    expect(staleTerminal.status).not.toBe(500);

    const published = await putJson(terminalKey, terminalDoc("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
      "x-personal-lease-etag": renewedBody.etag,
    });
    expect(published.status).toBe(201);
    expect(published.status).not.toBe(500);
  });

  it("cross-digest GET does not reveal the lease and cannot forge terminal", async () => {
    expect(
      (await putJson(leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const attacker = {
      ...identityHeaders,
      "x-personal-request-digest": otherDigest,
    };
    const leak = await outbound(leaseKey, { method: "GET", headers: attacker });
    const leakBody = await leak.text();
    expect([403, 404]).toContain(leak.status);
    expect(leak.headers.get("etag")).toBeNull();
    expect(leakBody).not.toContain("owner-nonce-1");
    expect(leakBody).not.toContain(requestDigest);

    const forged = await putJson(terminalKey, terminalDoc("owner-nonce-1", 1), {
      "x-personal-request-digest": otherDigest,
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(forged.status).not.toBe(201);
    expect([403, 404, 409]).toContain(forged.status);
    const stored = await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey);
    const parsed = JSON.parse(new TextDecoder().decode(await stored!.arrayBuffer())) as {
      status: string;
    };
    expect(parsed.status).toBe("CLAIMED");
  });

  it("directly seeded malformed CLAIMED objects cannot terminal-transition; exact closed lease can", async () => {
    const closed = leaseDoc("owner-nonce-1", 1);
    const missing = { ...closed };
    delete (missing as { heartbeat_at?: number }).heartbeat_at;
    const overflowToken = Number.MAX_SAFE_INTEGER + 1;
    const cases: Array<{ label: string; doc: Record<string, unknown> }> = [
      {
        label: "extra field and string fencing token",
        doc: { ...closed, extra: true, fencing_token: "1" },
      },
      { label: "missing heartbeat_at", doc: missing },
      {
        label: "MAX_SAFE overflow fencing token",
        doc: { ...closed, fencing_token: overflowToken },
      },
      {
        label: "wrong request_digest",
        doc: { ...closed, request_digest: otherDigest },
      },
      {
        label: "wrong execution_id",
        doc: { ...closed, execution_id: otherDigest },
      },
      {
        label: "expired lease",
        doc: {
          ...closed,
          heartbeat_at: Date.now() / 1000 - CONTROLLED_LEASE_TTL_SECONDS - 5,
          expires_at: Date.now() / 1000 - 5,
        },
      },
      {
        label: "noncanonical status",
        doc: { ...closed, status: "claimed" },
      },
      {
        label: "reversed lease times",
        doc: {
          ...closed,
          expires_at: Number(closed.heartbeat_at) - 1,
        },
      },
      {
        label: "over-TTL lease times",
        doc: {
          ...closed,
          expires_at:
            Number(closed.heartbeat_at) + CONTROLLED_LEASE_TTL_SECONDS + 1,
        },
      },
      {
        label: "future heartbeat",
        doc: {
          ...closed,
          heartbeat_at:
            Date.now() / 1000 + CONTROLLED_LEASE_CLOCK_SKEW_SECONDS + 1,
          expires_at:
            Date.now() / 1000 +
            CONTROLLED_LEASE_CLOCK_SKEW_SECONDS +
            CONTROLLED_LEASE_TTL_SECONDS,
        },
      },
    ];

    for (const seeded of cases) {
      await reset();
      const bytes = new TextEncoder().encode(JSON.stringify(seeded.doc));
      const put = await runtimeEnv.STRUCTURED_BUCKET.put(leaseKey, bytes, {
        httpMetadata: { contentType: CONTROLLED_JSON_TYPE },
      });
      expect(put, seeded.label).toBeTruthy();
      const rawEtag = put!.etag;
      expect(rawEtag.includes('"'), seeded.label).toBe(false);
      const before = await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey);
      expect(before, seeded.label).toBeTruthy();
      expect(before!.etag, seeded.label).toBe(rawEtag);
      const beforeBytes = new Uint8Array(await before!.arrayBuffer());

      const heartbeatGet = await outbound(leaseKey, { method: "GET", headers: identityHeaders });
      if (seeded.label === "expired lease" || seeded.label === "wrong execution_id") {
        expect(heartbeatGet.status, seeded.label).toBe(200);
      } else {
        expect([403, 404, 409], seeded.label).toContain(heartbeatGet.status);
        expect(heartbeatGet.status, seeded.label).not.toBe(200);
      }

      const denied = await putJson(terminalKey, terminalDoc("owner-nonce-1", 1), {
        "x-personal-lease-owner": "owner-nonce-1",
        "x-personal-fencing-token":
          seeded.label === "MAX_SAFE overflow fencing token" ? String(overflowToken) : "1",
        "x-personal-lease-etag": `"${rawEtag}"`,
      });
      expect(denied.status, seeded.label).not.toBe(201);
      expect(denied.status, seeded.label).not.toBe(200);
      expect([400, 403, 409, 412], seeded.label).toContain(denied.status);

      const after = await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey);
      expect(after, seeded.label).toBeTruthy();
      expect(after!.etag, seeded.label).toBe(rawEtag);
      const afterBytes = new Uint8Array(await after!.arrayBuffer());
      expect(afterBytes, seeded.label).toEqual(beforeBytes);
      const parsed = JSON.parse(new TextDecoder().decode(afterBytes)) as Record<string, unknown>;
      expect(parsed.status, seeded.label).not.toBe("TERMINAL");
      expect(parsed.status, seeded.label).toBe(seeded.doc.status);
    }

    await reset();
    const exact = leaseDoc("owner-nonce-1", 1);
    const exactBytes = new TextEncoder().encode(JSON.stringify(exact));
    const exactPut = await runtimeEnv.STRUCTURED_BUCKET.put(leaseKey, exactBytes, {
      httpMetadata: { contentType: CONTROLLED_JSON_TYPE },
    });
    expect(exactPut).toBeTruthy();
    expect(exactPut!.etag.includes('"')).toBe(false);
    const exactGet = await outbound(leaseKey, { method: "GET", headers: identityHeaders });
    expect(exactGet.status).toBe(200);
    expect(exactGet.headers.get("etag")).toBe(`"${exactPut!.etag}"`);
    const published = await putJson(terminalKey, terminalDoc("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
      "x-personal-lease-etag": `"${exactPut!.etag}"`,
    });
    expect(published.status).toBe(201);
    const stored = await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey);
    const terminalLease = JSON.parse(
      new TextDecoder().decode(await stored!.arrayBuffer()),
    ) as { status: string; fencing_token: unknown; extra?: unknown };
    expect(terminalLease.status).toBe("TERMINAL");
    expect(terminalLease.fencing_token).toBe(1);
    expect(terminalLease.extra).toBeUndefined();
    const got = await outbound(terminalKey, { method: "GET", headers: identityHeaders });
    expect(got.status).toBe(200);
  });

  it("rejects duplicate-key CLAIMED and permits takeover of an expired valid claim", async () => {
    const closed = leaseDoc("owner-nonce-1", 1);
    const duplicate = new TextEncoder().encode(
      JSON.stringify(closed).replace(
        '"status":"CLAIMED"',
        '"status":"CLAIMED","status":"CLAIMED"',
      ),
    );
    const duplicatePut = await runtimeEnv.STRUCTURED_BUCKET.put(
      leaseKey,
      duplicate,
      { httpMetadata: { contentType: CONTROLLED_JSON_TYPE } },
    );
    expect(duplicatePut).toBeTruthy();
    const duplicateEtag = duplicatePut!.etag;
    const beforeDuplicate = new Uint8Array(
      await (await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey))!.arrayBuffer(),
    );
    const duplicateGet = await outbound(leaseKey, {
      method: "GET",
      headers: identityHeaders,
    });
    expect(duplicateGet.status).toBe(403);
    expect(duplicateGet.headers.get("etag")).toBeNull();
    const duplicateTerminal = await putJson(
      terminalKey,
      terminalDoc("owner-nonce-1", 1),
      {
        "x-personal-lease-owner": "owner-nonce-1",
        "x-personal-fencing-token": "1",
        "x-personal-lease-etag": `"${duplicateEtag}"`,
      },
    );
    expect([400, 403, 409, 412]).toContain(duplicateTerminal.status);
    const afterDuplicate = await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey);
    expect(afterDuplicate!.etag).toBe(duplicateEtag);
    expect(new Uint8Array(await afterDuplicate!.arrayBuffer())).toEqual(
      beforeDuplicate,
    );

    await reset();
    const now = Date.now() / 1000;
    const expired = {
      ...leaseDoc("owner-nonce-1", 1, now - 60),
      expires_at: now - 1,
    };
    const expiredBytes = new TextEncoder().encode(JSON.stringify(expired));
    const expiredPut = await runtimeEnv.STRUCTURED_BUCKET.put(
      leaseKey,
      expiredBytes,
      { httpMetadata: { contentType: CONTROLLED_JSON_TYPE } },
    );
    expect(expiredPut).toBeTruthy();
    const expiredGet = await outbound(leaseKey, {
      method: "GET",
      headers: identityHeaders,
    });
    expect(expiredGet.status).toBe(200);
    expect(expiredGet.headers.get("etag")).toBe(`"${expiredPut!.etag}"`);
    const expiredHead = await outbound(leaseKey, {
      method: "HEAD",
      headers: identityHeaders,
    });
    expect(expiredHead.status).toBe(200);
    const beforeTakeover = new Uint8Array(
      await (await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey))!.arrayBuffer(),
    );
    const staleTerminal = await putJson(
      terminalKey,
      terminalDoc("owner-nonce-1", 1),
      {
        "x-personal-lease-owner": "owner-nonce-1",
        "x-personal-fencing-token": "1",
        "x-personal-lease-etag": `"${expiredPut!.etag}"`,
      },
    );
    expect(staleTerminal.status).toBe(409);
    const afterStale = await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey);
    expect(afterStale!.etag).toBe(expiredPut!.etag);
    expect(new Uint8Array(await afterStale!.arrayBuffer())).toEqual(beforeTakeover);
    const takeover = await putJson(
      leaseKey,
      leaseDoc("owner-nonce-2", 2),
      { "if-match": `"${expiredPut!.etag}"` },
    );
    expect(takeover.status).toBe(200);
    const taken = JSON.parse(
      new TextDecoder().decode(
        await (await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey))!.arrayBuffer(),
      ),
    ) as { owner_nonce: string; fencing_token: number };
    expect(taken.owner_nonce).toBe("owner-nonce-2");
    expect(taken.fencing_token).toBe(2);
  });

  it("keeps an expired valid TERMINAL readable and replay-idempotent", async () => {
    const logical = terminalDoc("owner-nonce-1", 1);
    const payload = new TextEncoder().encode(JSON.stringify(logical));
    const heartbeat = Date.now() / 1000 - CONTROLLED_LEASE_TTL_SECONDS - 10;
    const envelope = {
      ...leaseDoc("owner-nonce-1", 1, heartbeat),
      expires_at: heartbeat + CONTROLLED_LEASE_TTL_SECONDS,
      status: "TERMINAL",
      terminal_digest: await sha256(payload),
      terminal_status: "COMPLETED",
      terminal_payload_b64: encodeB64(payload),
    };
    const bytes = new TextEncoder().encode(JSON.stringify(envelope));
    const seeded = await runtimeEnv.STRUCTURED_BUCKET.put(leaseKey, bytes, {
      httpMetadata: { contentType: CONTROLLED_JSON_TYPE },
    });
    expect(seeded).toBeTruthy();
    const rawEtag = seeded!.etag;
    const before = new Uint8Array(
      await (await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey))!.arrayBuffer(),
    );
    const get = await outbound(terminalKey, {
      method: "GET",
      headers: identityHeaders,
    });
    expect(get.status).toBe(200);
    expect(get.headers.get("etag")).toBe(`"${rawEtag}"`);
    const head = await outbound(terminalKey, {
      method: "HEAD",
      headers: identityHeaders,
    });
    expect(head.status).toBe(200);
    const leaseGet = await outbound(leaseKey, {
      method: "GET",
      headers: identityHeaders,
    });
    expect(leaseGet.status).toBe(200);
    const replay = await putJson(
      terminalKey,
      terminalDoc("owner-nonce-1", 1),
      {
        "x-personal-lease-owner": "owner-nonce-1",
        "x-personal-fencing-token": "1",
      },
    );
    expect(replay.status).toBe(200);
    const after = await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey);
    expect(after!.etag).toBe(rawEtag);
    expect(new Uint8Array(await after!.arrayBuffer())).toEqual(before);
  });

  it("rejects a digest-consistent malformed preexisting TERMINAL on GET/HEAD/lease/replay", async () => {
    const logical = {
      identity: "controlled_pilot_v1",
      job_id: jobId,
      request_digest: requestDigest,
      execution_id: requestDigest,
      runner_version: "evil-runner",
      status: "COMPLETED",
      owner_nonce: "owner-nonce-1",
      fencing_token: 1,
      ok: false,
      papers: "bad",
    };
    const payload = new TextEncoder().encode(JSON.stringify(logical));
    const doc = {
      identity: "controlled_pilot_v1",
      job_id: jobId,
      request_digest: requestDigest,
      execution_id: requestDigest,
      runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
      kind: "controlled-pilot",
      owner_nonce: "owner-nonce-1",
      fencing_token: "1",
      expires_at: "not-a-time",
      heartbeat_at: null,
      status: "TERMINAL",
      terminal_digest: await sha256(payload),
      terminal_status: "COMPLETED",
      terminal_payload_b64: encodeB64(payload),
    };
    const bytes = new TextEncoder().encode(JSON.stringify(doc));
    const put = await runtimeEnv.STRUCTURED_BUCKET.put(leaseKey, bytes, {
      httpMetadata: { contentType: CONTROLLED_JSON_TYPE },
    });
    expect(put).toBeTruthy();
    const rawEtag = put!.etag;
    const before = new Uint8Array(await (await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey))!.arrayBuffer());

    const get = await outbound(terminalKey, { method: "GET", headers: identityHeaders });
    expect(get.status).toBe(403);
    expect(get.headers.get("etag")).toBeNull();
    const head = await outbound(terminalKey, { method: "HEAD", headers: identityHeaders });
    expect(head.status).toBe(403);
    expect(head.headers.get("etag")).toBeNull();
    const leaseGet = await outbound(leaseKey, { method: "GET", headers: identityHeaders });
    expect(leaseGet.status).toBe(403);
    expect(leaseGet.headers.get("etag")).toBeNull();
    const replay = await putJson(terminalKey, terminalDoc("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(replay.status).not.toBe(200);
    expect(replay.status).not.toBe(201);
    expect([400, 403, 409, 412]).toContain(replay.status);

    const after = await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey);
    expect(after!.etag).toBe(rawEtag);
    expect(new Uint8Array(await after!.arrayBuffer())).toEqual(before);
  });

  it("publishes a closed FAILED terminal and rejects a schema-valid CLAIMED from terminalizing a malformed logical", async () => {
    const created = await putJson(leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-none-match": "*",
    });
    expect(created.status).toBe(201);
    const malformed = {
      ...terminalDoc("owner-nonce-1", 1),
      runner_version: "evil-runner",
      ok: false,
      papers: "bad",
    };
    const denied = await putJson(terminalKey, malformed, {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(denied.status).not.toBe(201);
    expect(denied.status).not.toBe(200);
    const storedClaimed = await runtimeEnv.STRUCTURED_BUCKET.get(leaseKey);
    expect(
      (JSON.parse(new TextDecoder().decode(await storedClaimed!.arrayBuffer())) as { status: string })
        .status,
    ).toBe("CLAIMED");

    const failed = await putJson(terminalKey, failedTerminalDoc("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(failed.status).toBe(201);
    const got = await outbound(terminalKey, { method: "GET", headers: identityHeaders });
    expect(got.status).toBe(200);
    expect((JSON.parse(await got.text()) as { ok: boolean }).ok).toBe(false);
    const replay = await putJson(terminalKey, failedTerminalDoc("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(replay.status).toBe(200);

    const wrong = await outbound(terminalKey, {
      method: "GET",
      headers: { ...identityHeaders, "x-personal-request-digest": otherDigest },
    });
    expect(wrong.status).toBe(403);
    expect(wrong.headers.get("etag")).toBeNull();
  });
});
