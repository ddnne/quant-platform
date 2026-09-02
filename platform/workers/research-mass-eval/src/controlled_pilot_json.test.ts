import { describe, expect, it } from "vitest";

import vectors from "../../../../specs/ready/controlled_json_canonical_vectors.json";
import { canonicalJson, StrictJsonError } from "./controlled_pilot_json";

function runtimeNumber(name: string): number {
  const values: Record<string, number> = {
    NaN: Number.NaN,
    Infinity: Number.POSITIVE_INFINITY,
    "-Infinity": Number.NEGATIVE_INFINITY,
  };
  return values[name]!;
}

describe("Controlled canonical JSON", () => {
  it("matches the Python/Worker golden vectors", () => {
    expect(vectors.schema_version).toBe("controlled-json-canonical-v1");
    for (const vector of vectors.vectors) {
      const value = "input_json" in vector
        ? JSON.parse(vector.input_json)
        : runtimeNumber(vector.runtime_number);
      if ("reject" in vector) {
        expect(() => canonicalJson(value)).toThrow(StrictJsonError);
      } else {
        expect(canonicalJson(value)).toBe(vector.canonical_json);
      }
    }
  });

  it("rejects values outside the closed JSON type", () => {
    expect(() => canonicalJson(undefined)).toThrow(StrictJsonError);
    expect(() => canonicalJson({ x: undefined })).toThrow(StrictJsonError);
    expect(() => canonicalJson(1n)).toThrow(StrictJsonError);
  });
});
