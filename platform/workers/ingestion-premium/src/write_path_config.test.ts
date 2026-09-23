import { describe, expect, it } from "vitest";
import { r2DatasetSegment, r2DateSegment } from "./write_path_config";

describe("r2DateSegment", () => {
  it("takes the calendar prefix from a JST timestamp and does not invent today when empty", () => {
    expect(r2DateSegment("2024-06-03T00:00:00+09:00")).toBe("2024-06-03");
    expect(r2DateSegment(null)).toBe("0000-01-01");
    expect(r2DateSegment(undefined)).toBe("0000-01-01");
    expect(r2DateSegment("")).toBe("0000-01-01");
  });
});

describe("r2DatasetSegment", () => {
  it("strips characters that are unsafe in an R2 key segment", () => {
    expect(r2DatasetSegment("foo/bar:baz")).toBe("foo_bar_baz");
  });
});
