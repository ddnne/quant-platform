import { describe, expect, it } from "vitest";
import { json } from "./http_json";

describe("jsda json helper", () => {
  it("returns 401 unauthorized JSON", async () => {
    const res = json({ error: "unauthorized" }, 401);
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
  });

  it("defaults status 200, application/json, cache-control absent", async () => {
    const res = json({ ok: true });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type") ?? "").toContain("application/json");
    const cacheControl = res.headers.get("cache-control");
    expect(cacheControl === null || cacheControl === "").toBe(true);
    expect(await res.json()).toEqual({ ok: true });
  });
});
