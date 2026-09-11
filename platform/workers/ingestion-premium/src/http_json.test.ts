import { describe, expect, it } from "vitest";
import { json } from "./http_json";

describe("premium json helper", () => {
  it("returns 401 unauthorized JSON", async () => {
    const res = json({ error: "unauthorized" }, 401);
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
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
});
