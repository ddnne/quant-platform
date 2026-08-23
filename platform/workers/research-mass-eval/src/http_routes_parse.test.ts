import { describe, expect, it } from "vitest";
import { parseRequest } from "./parse_request";

describe("parseRequest", () => {
  it("rejects a non-object body", () => {
    const parsed = parseRequest("not-an-object");
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.error).toMatch(/JSON object/i);
  });

  it("requires job_id", () => {
    const parsed = parseRequest({
      seed: 1,
      logics: [{ logic_id: "x" }],
    });
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.error).toBe("job_id required");
  });

  it("rejects job_id with path separators", () => {
    const dots = parseRequest({
      job_id: "..",
      seed: 1,
      logics: [{ logic_id: "x" }],
    });
    expect(dots.ok).toBe(false);
    if (dots.ok) return;
    expect(dots.error).toBe("job_id must not contain path separators");

    const slash = parseRequest({
      job_id: "a/b",
      seed: 1,
      logics: [{ logic_id: "x" }],
    });
    expect(slash.ok).toBe(false);
    if (slash.ok) return;
    expect(slash.error).toBe("job_id must not contain path separators");
  });

  it("requires non-empty logics[]", () => {
    const parsed = parseRequest({ job_id: "j1", seed: 1, logics: [] });
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.error).toMatch(/logics\[\] required/);
  });

  it("requires logics item logic_id", () => {
    const parsed = parseRequest({
      job_id: "j1",
      seed: 1,
      logics: [{}],
    });
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.error).toMatch(/logic_id required/);
  });

  it("rejects unknown mode", () => {
    const parsed = parseRequest({
      job_id: "j1",
      seed: 1,
      logics: [{ logic_id: "x" }],
      mode: "nope",
    });
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.error).toBe(
      "mode must be synthetic | r2_panels | d1_bars | nets_only",
    );
  });

  it("accepts a minimal body with synthetic and write_artifacts defaults", () => {
    const parsed = parseRequest({
      job_id: "j1",
      seed: 1,
      logics: [{ logic_id: "x" }],
    });
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.mode).toBe("synthetic");
    expect(parsed.value.write_artifacts).toBe(true);
    expect(parsed.value.job_id).toBe("j1");
    expect(parsed.value.seed).toBe(1);
    expect(parsed.value.logics).toHaveLength(1);
    expect(parsed.value.logics[0]?.logic_id).toBe("x");
    const record = parsed.value as unknown as Record<string, unknown>;
    expect(record.go).not.toBe(true);
    expect(record.GO).not.toBe(true);
  });
});
