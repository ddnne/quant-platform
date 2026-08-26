import { describe, expect, it } from "vitest";
import { json } from "./http_json";

describe("ingestion-secrets JSON response behavior", () => {
  it("returns a generic unauthorized body without readiness or credential claims", async () => {
    const response = json({ error: "unauthorized" }, 401);
    expect(response.status).toBe(401);
    const body = await response.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    expect(body).not.toContain("COMPLETE");
    expect(body).not.toContain("READY");
    expect(body).not.toContain("API_KEY");
  });

  it("sets JSON media type without silently adding proxy cache policy", () => {
    const response = json({ ok: true });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("application/json");
    expect(response.headers.get("cache-control")).toBeNull();
  });
});
