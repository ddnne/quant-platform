import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  authorized,
  putChildrenThenManifest,
  putImmutableJson,
  putJsonCreateOnly,
  readBoundedJson,
  readBoundedRequestBytes,
  sha256Hex,
  verifyManifestChildDigest,
} from "./http";
import { CONTROLLED_PILOT_MAX_REQUEST_BYTES, dispatchMassEvalFetch } from "./http_routes";
import type { Env } from "./types";

function req(headers: Record<string, string>): Request {
  return new Request("https://example.test/v1/daily-path", { method: "POST", headers });
}

function countingStream(total: number, chunkSize: number, stats: { pulled: number; cancelled: boolean }) {
  let sent = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (stats.cancelled || sent >= total) {
        controller.close();
        return;
      }
      const n = Math.min(chunkSize, total - sent);
      sent += n;
      stats.pulled += n;
      controller.enqueue(new Uint8Array(n).fill(0x78));
    },
    cancel() {
      stats.cancelled = true;
    },
  });
}

describe("readBoundedRequestBytes", () => {
  it("rejects missing-header, chunked, false-small, and 8MiB bodies without pulling the full stream", async () => {
    const maximum = CONTROLLED_PILOT_MAX_REQUEST_BYTES;
    const huge = 8 * 1024 * 1024;
    const chunk = 64 * 1024;

    const noHeaderStats = { pulled: 0, cancelled: false };
    const noHeader = await readBoundedRequestBytes(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: countingStream(huge, chunk, noHeaderStats),
        duplex: "half",
      } as RequestInit),
      maximum,
    );
    expect(noHeader.ok).toBe(false);
    if (!noHeader.ok) {
      expect(noHeader.status).toBe(413);
    }
    expect(noHeaderStats.cancelled).toBe(true);
    expect(noHeaderStats.pulled).toBeLessThanOrEqual(maximum + chunk);
    expect(noHeaderStats.pulled).toBeLessThan(huge);

    const chunkedStats = { pulled: 0, cancelled: false };
    const chunked = await readBoundedRequestBytes(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "transfer-encoding": "chunked",
        },
        body: countingStream(huge, chunk, chunkedStats),
        duplex: "half",
      } as RequestInit),
      maximum,
    );
    expect(chunked.ok).toBe(false);
    if (!chunked.ok) {
      expect(chunked.status).toBe(413);
    }
    expect(chunkedStats.cancelled).toBe(true);
    expect(chunkedStats.pulled).toBeLessThan(huge);

    const falseSmallStats = { pulled: 0, cancelled: false };
    const falseSmall = await readBoundedRequestBytes(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": "4",
        },
        body: countingStream(huge, chunk, falseSmallStats),
        duplex: "half",
      } as RequestInit),
      maximum,
    );
    expect(falseSmall.ok).toBe(false);
    if (!falseSmall.ok) {
      expect([400, 413]).toContain(falseSmall.status);
    }
    expect(falseSmallStats.cancelled).toBe(true);
    expect(falseSmallStats.pulled).toBeLessThan(huge);

    const declaredHugeStats = { pulled: 0, cancelled: false };
    const declaredHuge = await readBoundedRequestBytes(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": String(huge),
        },
        body: countingStream(huge, chunk, declaredHugeStats),
        duplex: "half",
      } as RequestInit),
      maximum,
    );
    expect(declaredHuge.ok).toBe(false);
    if (!declaredHuge.ok) {
      expect(declaredHuge.status).toBe(413);
    }
    expect(declaredHugeStats.pulled).toBe(0);

    const atLimit = new Uint8Array(maximum).fill(0x20);
    atLimit.set(new TextEncoder().encode('{"ok":true}'));
    const exact = await readBoundedRequestBytes(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": String(maximum),
        },
        body: atLimit,
      }),
      maximum,
    );
    expect(exact.ok).toBe(true);
    if (exact.ok) {
      expect(exact.bytes.byteLength).toBe(maximum);
    }
  });
});

describe("readBoundedJson", () => {
  it("rejects missing content-length before buffering the body", async () => {
    const result = await readBoundedJson(
      {
        headers: {
          get(name: string) {
            return name.toLowerCase() === "content-length" ? null : "application/json";
          },
        },
        arrayBuffer: async () => {
          throw new Error("must not buffer a request without content-length");
        },
      } as unknown as Request,
      8 * 1024,
    );
    expect(result).toEqual({
      ok: false,
      status: 400,
      error: "content-length required",
    });
  });

  it("rejects oversized declared length before buffering", async () => {
    const result = await readBoundedJson(
      {
        headers: {
          get(name: string) {
            return name.toLowerCase() === "content-length" ? "8193" : null;
          },
        },
        arrayBuffer: async () => {
          throw new Error("must not buffer an oversized declared body");
        },
      } as unknown as Request,
      8 * 1024,
    );
    expect(result).toEqual({
      ok: false,
      status: 413,
      error: "request body exceeds the bound",
    });
  });
});

describe("authorized fail-closed", () => {
  it("denies when expected token is missing", async () => {
    expect(await authorized(req({ "X-Mass-Eval-Token": "x" }), undefined)).toBe(
      false,
    );
    expect(await authorized(req({}), "")).toBe(false);
  });

  it("denies when header missing", async () => {
    expect(await authorized(req({}), "secret")).toBe(false);
  });

  it("accepts matching token", async () => {
    expect(await authorized(req({ "X-Mass-Eval-Token": "secret" }), "secret")).toBe(
      true,
    );
  });

  it("rejects mismatched token", async () => {
    expect(await authorized(req({ "X-Mass-Eval-Token": "nope" }), "secret")).toBe(
      false,
    );
  });
});

describe("sha256Hex", () => {
  it("is stable for the same bytes", async () => {
    const enc = new TextEncoder();
    const a = await sha256Hex(enc.encode("abc"));
    const b = await sha256Hex(enc.encode("abc"));
    expect(a).toBe(b);
    expect(a).toHaveLength(64);
  });
});

type Stored = { body: Uint8Array; etag: string };

class MemR2 {
  readonly putOrder: string[] = [];
  private readonly objects = new Map<string, Stored>();

  async head(key: string) {
    const o = this.objects.get(key);
    if (!o) return null;
    return { key, size: o.body.byteLength, etag: o.etag };
  }

  async get(key: string) {
    const o = this.objects.get(key);
    if (!o) return null;
    const text = async () => new TextDecoder().decode(o.body);
    return {
      key,
      size: o.body.byteLength,
      etag: o.etag,
      text,
      json: async () => JSON.parse(await text()),
      arrayBuffer: async () => {
        const copy = new Uint8Array(o.body.byteLength);
        copy.set(o.body);
        return copy.buffer;
      },
    };
  }

  async put(
    key: string,
    value: ArrayBuffer | ArrayBufferView | string,
    options?: { onlyIf?: { etagDoesNotMatch?: string } },
  ) {
    if (options?.onlyIf?.etagDoesNotMatch === "*" && this.objects.has(key)) {
      return null;
    }
    let body: Uint8Array;
    if (typeof value === "string") body = new TextEncoder().encode(value);
    else if (value instanceof Uint8Array) body = value;
    else body = new Uint8Array(value as ArrayBuffer);
    const etag = `etag-${this.objects.size + 1}`;
    this.objects.set(key, { body, etag });
    this.putOrder.push(key);
    return { key, etag, size: body.byteLength };
  }

  asBucket(): R2Bucket {
    return this as unknown as R2Bucket;
  }
}

describe("putJsonCreateOnly", () => {
  it("existing key with different content is 409 and does not overwrite", async () => {
    const mem = new MemR2();
    const bucket = mem.asBucket();
    const first = await putJsonCreateOnly(bucket, "job/x.json", { n: 1 });
    const second = await putJsonCreateOnly(bucket, "job/x.json", { n: 2 });
    expect(first.created).toBe(true);
    expect(first.conflict).toBe(false);
    expect(second.created).toBe(false);
    expect(second.conflict).toBe(true);
    expect(second.status).toBe(409);
    expect(await (await mem.get("job/x.json"))!.json()).toEqual({ n: 1 });
    expect(mem.putOrder).toEqual(["job/x.json"]);
  });

  it("same digest retry is idempotent success", async () => {
    const mem = new MemR2();
    const bucket = mem.asBucket();
    const first = await putJsonCreateOnly(bucket, "job/x.json", { n: 1 });
    const second = await putJsonCreateOnly(bucket, "job/x.json", { n: 1 });
    expect(first.created).toBe(true);
    expect(second.created).toBe(false);
    expect(second.conflict).toBe(false);
    expect(second.status).toBeUndefined();
    expect(await (await mem.get("job/x.json"))!.json()).toEqual({ n: 1 });
    expect(mem.putOrder).toEqual(["job/x.json"]);
  });
});

describe("putChildrenThenManifest two-phase commit", () => {
  it("puts children before the job manifest", async () => {
    const mem = new MemR2();
    const bucket = mem.asBucket();
    const child = await putImmutableJson(bucket, "research/eval/artifacts", {
      kind: "cell",
      n: 1,
    });
    const got = await putChildrenThenManifest(
      bucket,
      [
        { key: "job/request.json", data: { job_id: "j1" } },
        { key: "job/summary.json", data: { n: 1 } },
        {
          key: "job/results.json",
          data: { artifact_digest: child.digest },
        },
      ],
      {
        key: "job/manifest.json",
        data: {
          artifact_digest: child.digest,
          artifact_key: child.key,
        },
      },
      child.digest,
    );
    expect(got.ok).toBe(true);
    expect(got.conflict).toBe(false);
    expect(got.manifest.created).toBe(true);
    expect(mem.putOrder.at(-1)).toBe("job/manifest.json");
    const before = mem.putOrder.slice(0, -1);
    expect(before).toContain("job/request.json");
    expect(before).toContain("job/summary.json");
    expect(before).toContain("job/results.json");
    expect(before).toContain(child.key);
  });

  it("does not treat manifest conflict as ok without child digest verify", async () => {
    const mem = new MemR2();
    const bucket = mem.asBucket();
    await putJsonCreateOnly(bucket, "job/manifest.json", { incomplete: true });
    const got = await putChildrenThenManifest(
      bucket,
      [{ key: "job/cell.json", data: { n: 1 } }],
      {
        key: "job/manifest.json",
        data: {
          artifact_digest: "sha256:deadbeef",
          artifact_key: "job/cell.json",
        },
      },
    );
    expect(got.conflict).toBe(true);
    expect(got.verified).toBe(false);
    expect(got.ok).toBe(false);
    expect(got.manifest.created).toBe(false);
    expect(await verifyManifestChildDigest(bucket, "job/manifest.json", "sha256:deadbeef")).toBe(
      false,
    );
  });

  it("conflict with missing child is not ok even if digest is named", async () => {
    const mem = new MemR2();
    const bucket = mem.asBucket();
    await putJsonCreateOnly(bucket, "job/manifest.json", {
      artifact_digest: "sha256:abc",
      artifact_key: "research/eval/artifacts/sha256=abc.json",
    });
    const got = await putChildrenThenManifest(
      bucket,
      [{ key: "job/cell.json", data: { n: 1 } }],
      {
        key: "job/manifest.json",
        data: {
          artifact_digest: "sha256:abc",
          artifact_key: "research/eval/artifacts/sha256=abc.json",
        },
      },
      "sha256:abc",
    );
    expect(got.ok).toBe(false);
    expect(got.conflict).toBe(true);
    expect(got.verified).toBe(false);
  });

  it("does not mint a manifest when an existing child digest mismatches", async () => {
    const mem = new MemR2();
    const bucket = mem.asBucket();
    await putJsonCreateOnly(bucket, "job/cell.json", { n: 1 });
    const got = await putChildrenThenManifest(
      bucket,
      [{ key: "job/cell.json", data: { n: 2 } }],
      {
        key: "job/manifest.json",
        data: {
          artifact_digest: "sha256:deadbeef",
          artifact_key: "job/cell.json",
        },
      },
    );
    expect(got.ok).toBe(false);
    expect(got.conflict).toBe(true);
    expect(got.verified).toBe(false);
    expect(got.manifest.created).toBe(false);
    expect(got.children[0]?.status).toBe(409);
    expect(mem.putOrder).not.toContain("job/manifest.json");
    expect(await (await mem.get("job/cell.json"))!.json()).toEqual({ n: 1 });
  });

  it("commits the manifest when every child is created or digest-equal", async () => {
    const mem = new MemR2();
    const bucket = mem.asBucket();
    await putJsonCreateOnly(bucket, "job/cell.json", { n: 1 });
    const artifact = await putImmutableJson(bucket, "research/eval/artifacts", {
      kind: "cell",
      n: 1,
    });
    const got = await putChildrenThenManifest(
      bucket,
      [{ key: "job/cell.json", data: { n: 1 } }],
      {
        key: "job/manifest.json",
        data: { artifact_digest: artifact.digest, artifact_key: artifact.key },
      },
      artifact.digest,
    );
    expect(got.ok).toBe(true);
    expect(got.conflict).toBe(false);
    expect(got.verified).toBe(true);
    expect(got.manifest.created).toBe(true);
    expect(got.children[0]?.created).toBe(false);
    expect(got.children[0]?.conflict).toBe(false);
    expect(mem.putOrder.at(-1)).toBe("job/manifest.json");
  });

  it("partial prior write cannot mint a manifest", async () => {
    const mem = new MemR2();
    const bucket = mem.asBucket();
    await putJsonCreateOnly(bucket, "job/a.json", { a: 1 });
    const got = await putChildrenThenManifest(
      bucket,
      [
        { key: "job/a.json", data: { a: 2 } },
        { key: "job/b.json", data: { b: 1 } },
      ],
      {
        key: "job/manifest.json",
        data: {
          artifact_digest: "sha256:deadbeef",
          artifact_key: "job/b.json",
        },
      },
    );
    expect(got.ok).toBe(false);
    expect(got.conflict).toBe(true);
    expect(got.verified).toBe(false);
    expect(got.manifest.created).toBe(false);
    expect(got.children.some((c) => c.status === 409)).toBe(true);
    expect(mem.putOrder).not.toContain("job/manifest.json");
    expect(await (await mem.get("job/a.json"))!.json()).toEqual({ a: 1 });
  });

  it("verified complete conflict is ok (idempotent replay)", async () => {
    const mem = new MemR2();
    const bucket = mem.asBucket();
    const child = await putImmutableJson(bucket, "research/eval/artifacts", {
      kind: "cell",
      n: 1,
    });
    const first = await putChildrenThenManifest(
      bucket,
      [{ key: "job/cell.json", data: { n: 1 } }],
      {
        key: "job/manifest.json",
        data: { artifact_digest: child.digest, artifact_key: child.key },
      },
      child.digest,
    );
    expect(first.ok).toBe(true);
    const replay = await putChildrenThenManifest(
      bucket,
      [{ key: "job/cell.json", data: { n: 1 } }],
      {
        key: "job/manifest.json",
        data: { artifact_digest: child.digest, artifact_key: child.key },
      },
      child.digest,
    );
    expect(replay.conflict).toBe(true);
    expect(replay.verified).toBe(true);
    expect(replay.ok).toBe(true);
    expect(replay.manifest.created).toBe(false);
  });
});

describe("index.ts write order pin", () => {
  it("mass-eval and daily-path commit children before job manifest", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const src = readFileSync(join(here, "index.ts"), "utf8");
    const mass = src.slice(
      src.indexOf("async function runMassEval"),
      src.indexOf("async function runDailyPath"),
    );
    const daily = src.slice(src.indexOf("async function runDailyPath"));
    const massHelper = mass.indexOf("putChildrenThenManifest");
    const massRequest = mass.indexOf("manifest.keys.request");
    const massManifest = mass.indexOf("manifest.keys.manifest");
    expect(massHelper).toBeGreaterThan(0);
    expect(massRequest).toBeGreaterThan(massHelper);
    expect(massManifest).toBeGreaterThan(massRequest);
    expect(daily.indexOf("putImmutableJson")).toBeGreaterThan(0);
    expect(daily.indexOf("putChildrenThenManifest")).toBeGreaterThan(
      daily.indexOf("putImmutableJson"),
    );
  });
});

describe("http_routes.ts fetch dispatch", () => {
  it("exposes POST /v1/children-then-manifest with X-Mass-Eval-Token", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const src = readFileSync(join(here, "http_routes.ts"), "utf8");
    expect(src).toContain('url.pathname === "/v1/children-then-manifest"');
    expect(src).toContain("putChildrenThenManifest");
    expect(src).toContain("authorized(request, env.MASS_EVAL_TOKEN)");
  });
});

const noopHandlers = {
  runMassEval: async () => {
    throw new Error("mass-eval must not run");
  },
  runDailyPath: async () => {
    throw new Error("daily-path must not run");
  },
};

function denyByDefaultEnv(bucket: R2Bucket): Env {
  return {
    STRUCTURED_BUCKET: bucket,
    MASS_EVAL_TOKEN: "secret",
    MASS_RESEARCH: "NO-GO",
    PHASE7: "OFF",
    READY_DECLARED: "false",
    OPERATIONAL_GO: "false",
    CONTINUOUS_PAPER: "UNARMED",
  } as Env;
}

type CapabilityDenied = {
  ok: boolean;
  error: string;
  capability: string;
  go: boolean;
  not_a_pass: boolean;
};

describe("POST /v1/propose-thesis", () => {
  it("returns 403 generation under deny-by-default with matching token", async () => {
    const mem = new MemR2();
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/propose-thesis", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Mass-Eval-Token": "secret",
        },
        body: "{}",
      }),
      denyByDefaultEnv(mem.asBucket()),
      noopHandlers,
    );
    expect(res.status).toBe(403);
    const payload = (await res.json()) as CapabilityDenied;
    expect(payload.ok).toBe(false);
    expect(payload.error).toBe("capability_missing");
    expect(payload.capability).toBe("generation");
    expect(payload.go).toBe(false);
    expect(payload.not_a_pass).toBe(true);
    expect(mem.putOrder).toEqual([]);
  });

  it("rejects GET with 405", async () => {
    const mem = new MemR2();
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/propose-thesis", { method: "GET" }),
      denyByDefaultEnv(mem.asBucket()),
      noopHandlers,
    );
    expect(res.status).toBe(405);
  });

  it("returns 401 when token header is missing and MASS_EVAL_TOKEN is bound", async () => {
    const mem = new MemR2();
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/propose-thesis", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
      }),
      denyByDefaultEnv(mem.asBucket()),
      noopHandlers,
    );
    expect(res.status).toBe(401);
  });
});

describe("POST /v1/mass-eval capability gate", () => {
  it("returns 403 mass_screen under deny-by-default with matching token", async () => {
    const mem = new MemR2();
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/mass-eval", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Mass-Eval-Token": "secret",
        },
        body: "{}",
      }),
      denyByDefaultEnv(mem.asBucket()),
      noopHandlers,
    );
    expect(res.status).toBe(403);
    const payload = (await res.json()) as CapabilityDenied;
    expect(payload.ok).toBe(false);
    expect(payload.error).toBe("capability_missing");
    expect(payload.capability).toBe("mass_screen");
    expect(payload.go).toBe(false);
    expect(payload.not_a_pass).toBe(true);
    expect(mem.putOrder).toEqual([]);
  });

  it("rejects GET with 405", async () => {
    const mem = new MemR2();
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/mass-eval", { method: "GET" }),
      denyByDefaultEnv(mem.asBucket()),
      noopHandlers,
    );
    expect(res.status).toBe(405);
  });
});

describe("POST /v1/daily-path capability gate", () => {
  it("returns 403 mass_screen under deny-by-default with matching token", async () => {
    const mem = new MemR2();
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/daily-path", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Mass-Eval-Token": "secret",
        },
        body: "{}",
      }),
      denyByDefaultEnv(mem.asBucket()),
      noopHandlers,
    );
    expect(res.status).toBe(403);
    const payload = (await res.json()) as CapabilityDenied;
    expect(payload.ok).toBe(false);
    expect(payload.error).toBe("capability_missing");
    expect(payload.capability).toBe("mass_screen");
    expect(payload.go).toBe(false);
    expect(payload.not_a_pass).toBe(true);
    expect(mem.putOrder).toEqual([]);
  });

  it("rejects GET with 405", async () => {
    const mem = new MemR2();
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/daily-path", { method: "GET" }),
      denyByDefaultEnv(mem.asBucket()),
      noopHandlers,
    );
    expect(res.status).toBe(405);
  });
});

describe("POST /v1/children-then-manifest", () => {
  it("denies when token missing", async () => {
    const mem = new MemR2();
    const env = {
      STRUCTURED_BUCKET: mem.asBucket(),
      MASS_EVAL_TOKEN: "secret",
    } as Env;
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/children-then-manifest", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          children: [{ key: "job/child.json", data: { n: 1 } }],
          manifest: { key: "job/manifest.json", data: { n: 1 } },
        }),
      }),
      env,
      noopHandlers,
    );
    expect(res.status).toBe(401);
    expect(mem.putOrder).toEqual([]);
  });

  it("rejects GET with 405", async () => {
    const mem = new MemR2();
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/children-then-manifest", {
        method: "GET",
      }),
      denyByDefaultEnv(mem.asBucket()),
      noopHandlers,
    );
    expect(res.status).toBe(405);
  });

  it("denies when token unbound", async () => {
    const mem = new MemR2();
    const env = {
      STRUCTURED_BUCKET: mem.asBucket(),
    } as Env;
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/children-then-manifest", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Mass-Eval-Token": "secret",
        },
        body: JSON.stringify({
          children: [{ key: "job/child.json", data: { n: 1 } }],
          manifest: { key: "job/manifest.json", data: { n: 1 } },
        }),
      }),
      env,
      noopHandlers,
    );
    expect(res.status).toBe(503);
    expect(mem.putOrder).toEqual([]);
  });

  it("puts children then manifest when authorized", async () => {
    const mem = new MemR2();
    const env = {
      STRUCTURED_BUCKET: mem.asBucket(),
      MASS_EVAL_TOKEN: "secret",
    } as Env;
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/children-then-manifest", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Mass-Eval-Token": "secret",
        },
        body: JSON.stringify({
          children: [{ key: "job/child.json", data: { n: 1 } }],
          manifest: {
            key: "job/manifest.json",
            data: { artifact_key: "job/child.json" },
          },
        }),
      }),
      env,
      noopHandlers,
    );
    expect(res.status).toBe(200);
    const payload = (await res.json()) as {
      ok: boolean;
      conflict: boolean;
      go: boolean;
      manifest: { created: boolean; key: string };
    };
    expect(payload.ok).toBe(true);
    expect(payload.conflict).toBe(false);
    expect(payload.go).toBe(false);
    expect(payload.manifest.created).toBe(true);
    expect(mem.putOrder).toEqual(["job/child.json", "job/manifest.json"]);
  });
});

describe("POST /v1/controlled-pilot request byte cap", () => {
  function controlledEnv(): Env {
    return {
      MASS_EVAL_TOKEN: "secret",
      STRUCTURED_BUCKET: {} as R2Bucket,
      AI_GATEWAY: {} as Env["AI_GATEWAY"],
    } as Env;
  }

  const validJson = JSON.stringify({
    idempotency_key: "controlled-job-1",
    ready_attestation_id: "attestation-cloud-1",
    snapshot_id: `sha256:${"ab".repeat(32)}`,
  });

  it("keeps unauthorized requests at 401 before the handler", async () => {
    const submit = async () => new Response("should-not-run", { status: 200 });
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: validJson,
      }),
      controlledEnv(),
      { ...noopHandlers, submitControlledPilot: submit },
    );
    expect(res.status).toBe(401);
  });

  it("rejects no-header, chunked, false-small, and 8MiB bodies without forwarding full bytes", async () => {
    const seen: number[] = [];
    const submit = async (
      _env: Env,
      _body: unknown,
      _ctx?: ExecutionContext,
      rawBytes?: Uint8Array,
    ) => {
      seen.push(rawBytes?.byteLength ?? -1);
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    };
    const handlers = { ...noopHandlers, submitControlledPilot: submit };
    const env = controlledEnv();
    const huge = 8 * 1024 * 1024;
    const chunk = 64 * 1024;

    const noHeaderStats = { pulled: 0, cancelled: false };
    const noHeader = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Mass-Eval-Token": "secret",
        },
        body: countingStream(huge, chunk, noHeaderStats),
        duplex: "half",
      } as RequestInit),
      env,
      handlers,
    );
    expect(noHeader.status).toBe(413);
    expect(noHeaderStats.cancelled).toBe(true);
    expect(noHeaderStats.pulled).toBeLessThan(huge);

    const chunkedStats = { pulled: 0, cancelled: false };
    const chunked = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "transfer-encoding": "chunked",
          "X-Mass-Eval-Token": "secret",
        },
        body: countingStream(huge, chunk, chunkedStats),
        duplex: "half",
      } as RequestInit),
      env,
      handlers,
    );
    expect(chunked.status).toBe(413);
    expect(chunkedStats.cancelled).toBe(true);
    expect(chunkedStats.pulled).toBeLessThan(huge);

    const falseSmallStats = { pulled: 0, cancelled: false };
    const falseSmall = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": "4",
          "X-Mass-Eval-Token": "secret",
        },
        body: countingStream(huge, chunk, falseSmallStats),
        duplex: "half",
      } as RequestInit),
      env,
      handlers,
    );
    expect([400, 413]).toContain(falseSmall.status);
    expect(falseSmallStats.cancelled).toBe(true);
    expect(falseSmallStats.pulled).toBeLessThan(huge);

    const eightMibStats = { pulled: 0, cancelled: false };
    const eightMib = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": String(huge),
          "X-Mass-Eval-Token": "secret",
        },
        body: countingStream(huge, chunk, eightMibStats),
        duplex: "half",
      } as RequestInit),
      env,
      handlers,
    );
    expect(eightMib.status).toBe(413);
    expect(eightMibStats.pulled).toBeLessThan(huge);
    expect(seen).toEqual([]);

    let mockPulled = 0;
    let mockCancelled = false;
    const declaredMock = {
      method: "POST",
      url: "https://example.test/v1/controlled-pilot",
      headers: {
        get(name: string) {
          const key = name.toLowerCase();
          if (key === "content-length") return String(huge);
          if (key === "x-mass-eval-token") return "secret";
          if (key === "content-type") return "application/json";
          return null;
        },
      },
      body: {
        cancel: async () => {
          mockCancelled = true;
        },
        getReader() {
          mockPulled += 1;
          throw new Error("must not read a declared oversized controlled body");
        },
      },
    } as unknown as Request;
    const declared = await dispatchMassEvalFetch(declaredMock, env, handlers);
    expect(declared.status).toBe(413);
    expect(mockCancelled).toBe(true);
    expect(mockPulled).toBe(0);
    expect(seen).toEqual([]);
  });

  it("forwards an at-limit valid body", async () => {
    const pad = CONTROLLED_PILOT_MAX_REQUEST_BYTES - validJson.length;
    expect(pad).toBeGreaterThan(0);
    const body = validJson + " ".repeat(pad);
    const seen: Uint8Array[] = [];
    const submit = async (
      _env: Env,
      _body: unknown,
      _ctx?: ExecutionContext,
      rawBytes?: Uint8Array,
    ) => {
      if (rawBytes) seen.push(rawBytes);
      return new Response(JSON.stringify({ ok: true, accepted: true }), { status: 200 });
    };
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": String(body.length),
          "X-Mass-Eval-Token": "secret",
        },
        body,
      }),
      controlledEnv(),
      { ...noopHandlers, submitControlledPilot: submit },
    );
    expect(res.status).toBe(200);
    expect(seen).toHaveLength(1);
    expect(seen[0]?.byteLength).toBe(CONTROLLED_PILOT_MAX_REQUEST_BYTES);
  });
});
