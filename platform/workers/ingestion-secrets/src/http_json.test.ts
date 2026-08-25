import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { json } from "./http_json";

const here = dirname(fileURLToPath(import.meta.url));

describe("ingestion-secrets json helper", () => {
  it("returns 401 unauthorized without COMPLETE / READY / API key leak strings", async () => {
    const res = json({ error: "unauthorized" }, 401);
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    expect(body).not.toContain("COMPLETE");
    expect(body).not.toContain("READY");
    expect(body).not.toContain("API_KEY");
    expect(body).not.toContain("JQUANTS_API_KEY");
    expect(body).not.toContain("x-api-key");
  });

  it("helper itself has no COMPLETE / READY / API key leak strings", () => {
    const src = readFileSync(join(here, "http_json.ts"), "utf8");
    expect(src).not.toContain("COMPLETE");
    expect(src).not.toContain("READY");
    expect(src).not.toContain("API_KEY");
    expect(src).not.toContain("JQUANTS_API_KEY");
    expect(src).not.toContain("x-api-key");
  });

  it("cache-control is absent on json()", async () => {
    const res = json({ ok: true });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type") ?? "").toContain("application/json");
    const cacheControl = res.headers.get("cache-control");
    expect(cacheControl === null || cacheControl === "").toBe(true);
  });

  it("index.ts imports http_json; JSON paths do not use Response.json", () => {
    const src = readFileSync(join(here, "index.ts"), "utf8");
    expect(src).toContain('from "./http_json"');
    expect(src).not.toContain("Response.json");
    expect(src).toContain("new Response(upstream.body");
  });

  it("index.ts still has cache-control no-store on the proxy success path", () => {
    const src = readFileSync(join(here, "index.ts"), "utf8");
    expect(src).toContain("new Response(upstream.body");
    expect(src).toContain('"cache-control": "no-store"');
  });

  it("http_json.ts has no no-store", () => {
    const src = readFileSync(join(here, "http_json.ts"), "utf8");
    expect(src).toContain("Response.json");
    expect(src).not.toContain("no-store");
    expect(src).not.toContain("cache-control");
  });
});
