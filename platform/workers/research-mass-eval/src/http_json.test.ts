import { describe, expect, it } from "vitest";
import { json } from "./http_json";

describe("json helper is no-store presentation", () => {
  it("returns 200 application/json with cache-control no-store", async () => {
    const res = json({ ok: true, go: false });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type") ?? "").toContain("application/json");
    expect(res.headers.get("cache-control")).toBe("no-store");
    const body = (await res.json()) as { ok: boolean; go: boolean };
    expect(body.ok).toBe(true);
    expect(body.go).toBe(false);
  });

  it("forwards 401 without changing status", async () => {
    const res = json({ error: "unauthorized" }, 401);
    expect(res.status).toBe(401);
  });

  it("does not invent go:true; caller supplies go:false", async () => {
    const res = json({ go: false });
    const body = (await res.json()) as { go: boolean };
    expect(body.go).toBe(false);
    expect(body.go).not.toBe(true);
  });
});
