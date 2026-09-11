import { describe, expect, it } from "vitest";
import { json } from "./http_json";

describe("json helper is no-store presentation", () => {
  it("returns 200 application/json with cache-control no-store", async () => {
    const res = json({ ok: true, go: false });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type") ?? "").toContain("application/json");
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(await res.json()).toEqual({ ok: true, go: false });
  });

  it("forwards 401 without changing status", async () => {
    const res = json({ error: "unauthorized" }, 401);
    expect(res.status).toBe(401);
  });
});
