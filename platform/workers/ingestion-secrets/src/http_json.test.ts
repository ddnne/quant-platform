import { describe, expect, it } from "vitest";
import { json } from "./http_json";

describe("ingestion-secrets JSON response behavior", () => {
  it("returns 401 unauthorized JSON", async () => {
    const response = json({ error: "unauthorized" }, 401);
    expect(response.status).toBe(401);
    const body = await response.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
  });

  it("sets JSON media type without silently adding proxy cache policy", () => {
    const response = json({ ok: true });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("application/json");
    expect(response.headers.get("cache-control")).toBeNull();
  });
});
