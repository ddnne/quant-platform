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
  type EvaluationIREncodeArgs,
} from "./evaluation_ir";

const REPO_ROOT = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../../..",
);
const GOLDEN_PATH = join(REPO_ROOT, "specs/evaluation_ir/golden.jsonl");

type GoldenRow = {
  id: string;
  op: "roundtrip" | "decode";
  args?: EvaluationIREncodeArgs;
  payload?: Record<string, unknown>;
  expect?: { candidate: boolean; failure_reason: string | null };
  expect_error?: string;
};

function loadGolden(): GoldenRow[] {
  return readFileSync(GOLDEN_PATH, "utf8")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as GoldenRow);
}

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

  it("shared golden vectors match jobCandidateGrade and round-trip", () => {
    const rows = loadGolden();
    expect(rows.length).toBeGreaterThanOrEqual(8);
    const ids = new Set(rows.map((row) => row.id));
    for (const required of [
      "n_expected_zero",
      "n_cells_mismatch",
      "collapsed",
      "broken",
      "smuggled_candidate_partial",
    ]) {
      expect(ids.has(required), required).toBe(true);
    }
    for (const row of rows) {
      if (row.op === "decode") {
        expect(row.expect_error, row.id).toBeTruthy();
        expect(() => decodeEvaluationIR(row.payload)).toThrow(
          new RegExp(row.expect_error as string),
        );
        const payload = row.payload as {
          candidate?: boolean;
          n_expected: number;
          n_cells: number;
          n_complete: number;
          n_collapsed?: number;
          n_broken?: number;
        };
        const grade = jobCandidateGrade({
          n_expected: payload.n_expected,
          n_cells: payload.n_cells,
          n_complete: payload.n_complete,
          n_collapsed: payload.n_collapsed,
          n_broken: payload.n_broken,
        });
        if (payload.candidate === true && grade === false) {
          expect(row.expect_error).toBe("job_candidate_grade");
        }
        continue;
      }
      const encoded = encodeEvaluationIR(row.args as EvaluationIREncodeArgs);
      const grade = jobCandidateGrade({
        n_expected: encoded.n_expected,
        n_cells: encoded.n_cells,
        n_complete: encoded.n_complete,
        n_collapsed: encoded.n_collapsed,
        n_broken: encoded.n_broken,
      });
      expect(encoded.candidate, row.id).toBe(grade);
      expect(encoded.candidate, row.id).toBe(row.expect?.candidate);
      expect(encoded.failure_reason, row.id).toBe(row.expect?.failure_reason);
      const decoded = decodeEvaluationIR(encoded);
      expect(decoded.candidate, row.id).toBe(grade);
      expect(decoded.failure_reason, row.id).toBe(row.expect?.failure_reason);
      if (grade === false) {
        expect(() =>
          decodeEvaluationIR({ ...encoded, candidate: true }),
        ).toThrow(/job_candidate_grade/);
      }
    }
  });
});
