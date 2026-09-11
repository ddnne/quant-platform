import { describe, expect, it } from "vitest";
import { tokenMatches } from "../../../worker_support/header_token";

describe("tokenMatches", () => {
  it.each([
    { name: "correct", provided: "secret", expected: "secret" as string | undefined, want: true },
    { name: "wrong different length", provided: "no", expected: "secret", want: false },
    { name: "undefined expected", provided: "secret", expected: undefined, want: false },
    { name: "empty expected", provided: "", expected: "", want: false },
    { name: "null provided", provided: null, expected: "secret", want: false },
    { name: "empty provided", provided: "", expected: "secret", want: false },
  ])("$name", async ({ provided, expected, want }) => {
    expect(await tokenMatches(provided, expected)).toBe(want);
  });
});
