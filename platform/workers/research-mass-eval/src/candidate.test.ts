import { describe, expect, it } from "vitest";
import { jobCandidateGrade } from "./candidate";

describe("jobCandidateGrade", () => {
  it("is false when expected is 0 or cells incomplete", () => {
    expect(
      jobCandidateGrade({ n_expected: 0, n_cells: 0, n_complete: 0 }),
    ).toBe(false);
    expect(
      jobCandidateGrade({ n_expected: 2, n_cells: 2, n_complete: 1 }),
    ).toBe(false);
    expect(
      jobCandidateGrade({ n_expected: 2, n_cells: 1, n_complete: 1 }),
    ).toBe(false);
  });

  it("is false when collapsed or broken", () => {
    expect(
      jobCandidateGrade({
        n_expected: 2,
        n_cells: 2,
        n_complete: 2,
        n_collapsed: 1,
      }),
    ).toBe(false);
    expect(
      jobCandidateGrade({
        n_expected: 2,
        n_cells: 2,
        n_complete: 2,
        n_broken: 1,
      }),
    ).toBe(false);
  });

  it("is true only when expected equals complete cells", () => {
    expect(
      jobCandidateGrade({ n_expected: 2, n_cells: 2, n_complete: 2 }),
    ).toBe(true);
  });
});
