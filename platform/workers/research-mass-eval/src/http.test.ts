import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  authorized,
  putChildrenThenManifest,
  putImmutableJson,
  putJsonCreateOnly,
  sha256Hex,
  verifyManifestChildDigest,
} from "./http";

function req(headers: Record<string, string>): Request {
  return new Request("https://example.test/v1/daily-path", { method: "POST", headers });
}

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
  it("denies mass_screen and generation with 403", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const src = readFileSync(join(here, "http_routes.ts"), "utf8");
    expect(src).toContain('capability: "mass_screen"');
    expect(src).toContain('capability: "generation"');
    expect(src).toContain("403");
    expect(src).toContain("authorized");
  });
});
