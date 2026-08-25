import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { json } from "./http_json";

const here = dirname(fileURLToPath(import.meta.url));

describe("premium json helper", () => {
  it("returns 401 unauthorized JSON without COMPLETE / READY / GO", async () => {
    const res = json({ error: "unauthorized" }, 401);
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    expect(body).not.toContain("COMPLETE");
    expect(body).not.toContain("READY");
    expect(body).not.toContain("GO");
  });

  it("defaults status 200 for json({ ok: true })", async () => {
    const res = json({ ok: true });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
  });

  it("has application/json content-type and no cache-control", async () => {
    const res = json({ ok: true });
    expect(res.headers.get("content-type") ?? "").toContain("application/json");
    const cacheControl = res.headers.get("cache-control");
    expect(cacheControl === null || cacheControl === "").toBe(true);
  });

  it("callers import from http_json and do not declare local json()", () => {
    for (const name of ["index.ts", "http_export.ts"]) {
      const src = readFileSync(join(here, name), "utf8");
      expect(src, name).toContain('from "./http_json"');
      expect(src, name).not.toContain("function json(");
    }
  });

  it("http_json uses Response.json without gateway cache/charset headers", () => {
    const src = readFileSync(join(here, "http_json.ts"), "utf8");
    expect(src).toContain("Response.json");
    expect(src).not.toContain("cache-control");
    expect(src).not.toContain("no-store");
    expect(src).not.toContain("charset=utf-8");
  });
});
