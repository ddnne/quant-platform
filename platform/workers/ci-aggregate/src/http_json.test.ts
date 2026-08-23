import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { json } from "./http_json";
import { handleRequest } from "./index";

const here = dirname(fileURLToPath(import.meta.url));

describe("ci-aggregate json helper", () => {
  it("returns 200 application/json with cache-control no-store", async () => {
    const res = json({ ok: true, go: false });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type") ?? "").toContain("application/json");
    expect(res.headers.get("cache-control")).toBe("no-store");
    const body = (await res.json()) as { ok: boolean; go: boolean };
    expect(body.go).not.toBe(true);
  });

  it("returns 401 unauthorized without COMPLETE / READY as coverage claims", async () => {
    const res = json({ error: "unauthorized" }, 401);
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    expect(body).not.toContain("COMPLETE");
    expect(body).not.toContain("READY");
  });

  it("index.ts imports from http_json and does not declare local json()", () => {
    const src = readFileSync(join(here, "index.ts"), "utf8");
    expect(src).toContain('from "./http_json"');
    expect(src).not.toContain("function json(");
  });

  it("http_json.ts has cache-control no-store and charset=utf-8", () => {
    const src = readFileSync(join(here, "http_json.ts"), "utf8");
    expect(src).toContain("cache-control");
    expect(src).toContain("no-store");
    expect(src).toContain("charset=utf-8");
  });

  it("GET /health has cache-control no-store", async () => {
    const res = await handleRequest(
      new Request("https://ci-aggregate.test/health", { method: "GET" }),
      {},
    );
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
  });
});
