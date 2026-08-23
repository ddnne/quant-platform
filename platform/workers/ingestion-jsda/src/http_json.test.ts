import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { json } from "./http_json";

const here = dirname(fileURLToPath(import.meta.url));

describe("jsda json helper", () => {
  it("returns 401 unauthorized JSON without COMPLETE / READY", async () => {
    const res = json({ error: "unauthorized" }, 401);
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    expect(body).not.toContain("COMPLETE");
    expect(body).not.toContain("READY");
  });

  it("defaults status 200, application/json, cache-control absent", async () => {
    const res = json({ ok: true });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type") ?? "").toContain("application/json");
    const cacheControl = res.headers.get("cache-control");
    expect(cacheControl === null || cacheControl === "").toBe(true);
    expect(await res.json()).toEqual({ ok: true });
  });

  it("index.ts imports from http_json and does not contain Response.json", () => {
    const src = readFileSync(join(here, "index.ts"), "utf8");
    expect(src).toContain('from "./http_json"');
    expect(src).not.toContain("Response.json");
  });

  it("http_json uses Response.json without gateway cache/charset headers", () => {
    const src = readFileSync(join(here, "http_json.ts"), "utf8");
    expect(src).toContain("Response.json");
    expect(src).not.toContain("cache-control");
    expect(src).not.toContain("no-store");
    expect(src).not.toContain("charset=utf-8");
  });
});
