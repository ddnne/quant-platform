import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { jobCandidateGrade } from "./candidate";
import {
  CANONICAL_FIELDS,
  EVALUATION_IR_VERSION,
  decodeEvaluationIR,
  encodeEvaluationIR,
  jobCandidateGrade as irGrade,
} from "./evaluation_ir";

describe("Evaluation IR golden vectors", () => {
  it("canonical fields, version, and jobCandidateGrade identity", () => {
    expect(EVALUATION_IR_VERSION).toBe("evaluation-ir/v1");
    expect(CANONICAL_FIELDS).toEqual([
      "return",
      "cost",
      "turnover",
      "coverage",
      "collapsed",
      "candidate",
      "failure_reason",
    ]);
    expect(irGrade).toBe(jobCandidateGrade);
  });

  it("partial job candidate is false", () => {
    const payload = encodeEvaluationIR({
      return_value: 0.12,
      cost: 0.01,
      turnover: 0.4,
      coverage: 0.75,
      collapsed: 0,
      n_expected: 4,
      n_cells: 4,
      n_complete: 3,
    });
    expect(payload.version).toBe(EVALUATION_IR_VERSION);
    expect(payload.candidate).toBe(false);
    expect(payload.failure_reason).toBe("partial_incomplete");
    const decoded = decodeEvaluationIR(payload);
    expect(decoded.candidate).toBe(false);
    expect(decoded.return_value).toBe(0.12);
  });

  it("complete job candidate is true", () => {
    const payload = encodeEvaluationIR({
      return_value: 0.08,
      cost: 0.02,
      turnover: 0.15,
      coverage: 1.0,
      collapsed: 0,
      n_expected: 4,
      n_cells: 4,
      n_complete: 4,
      n_collapsed: 0,
      n_broken: 0,
    });
    expect(payload.candidate).toBe(true);
    expect(payload.failure_reason).toBeNull();
    const decoded = decodeEvaluationIR(payload);
    expect(decoded.candidate).toBe(true);
    expect(decoded.toDict().candidate).toBe(true);
  });

  it("collapsed or broken or empty expected is false", () => {
    expect(
      encodeEvaluationIR({
        n_expected: 4,
        n_cells: 4,
        n_complete: 4,
        n_collapsed: 1,
      }).candidate,
    ).toBe(false);
    expect(
      encodeEvaluationIR({
        n_expected: 4,
        n_cells: 4,
        n_complete: 4,
        n_broken: 1,
      }).candidate,
    ).toBe(false);
    expect(
      encodeEvaluationIR({ n_expected: 0, n_cells: 0, n_complete: 0 })
        .candidate,
    ).toBe(false);
    expect(
      encodeEvaluationIR({ n_expected: 4, n_cells: 3, n_complete: 3 })
        .candidate,
    ).toBe(false);
  });

  it("unknown field is rejected", () => {
    const good = encodeEvaluationIR({
      return_value: 0.0,
      cost: 0.0,
      turnover: 0.0,
      coverage: 1.0,
      collapsed: 0,
      n_expected: 2,
      n_cells: 2,
      n_complete: 2,
    });
    expect(() => decodeEvaluationIR({ ...good, go: true })).toThrow(
      /unknown field/,
    );
    expect(() =>
      decodeEvaluationIR({ ...good, operator_override: true }),
    ).toThrow(/unknown field/);
  });

  it("smuggled candidate true on partial is rejected", () => {
    const partial = encodeEvaluationIR({
      n_expected: 4,
      n_cells: 4,
      n_complete: 3,
    });
    const forged = { ...partial, candidate: true };
    expect(() => decodeEvaluationIR(forged)).toThrow(/job_candidate_grade/);
  });

  it("encode candidate is jobCandidateGrade; daily-path payload uses IR candidate", () => {
    const complete = {
      n_expected: 4,
      n_cells: 4,
      n_complete: 4,
      n_collapsed: 0,
      n_broken: 0,
    };
    const partial = { n_expected: 4, n_cells: 4, n_complete: 3 };
    expect(encodeEvaluationIR(complete).candidate).toBe(
      jobCandidateGrade(complete),
    );
    expect(encodeEvaluationIR(partial).candidate).toBe(
      jobCandidateGrade(partial),
    );
    // index.ts runDailyPath: candidate_grade = encodeEvaluationIR(...).candidate
    const src = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "index.ts"),
      "utf8",
    );
    const daily = src.slice(src.indexOf("async function runDailyPath"));
    expect(daily).toContain("encodeEvaluationIR");
    expect(daily).toContain("candidate_grade: evaluation_ir.candidate");
    expect(daily).not.toMatch(/candidate_grade:\s*jobCandidateGrade/);
    expect(src).toMatch(/screen_kind: "period_net"[\s\S]*candidate_grade: false/);
  });
});
