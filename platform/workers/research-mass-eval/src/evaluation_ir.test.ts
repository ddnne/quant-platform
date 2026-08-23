import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { jobCandidateGrade } from "./candidate";
import {
  ALLOWED_FIELDS,
  EVALUATION_IR_VERSION,
  GOLDEN_REL,
  SCHEMA_REL,
  decodeEvaluationIR,
  encodeEvaluationIR,
  jobCandidateGrade as irGrade,
  type EvaluationIREncodeArgs,
} from "./evaluation_ir";

/** Walk up from src/ until repo specs/evaluation_ir/golden.jsonl. */
function goldenPathFromSrc(srcDir: string): string {
  let dir = srcDir;
  for (let i = 0; i < 8; i++) {
    const candidate = join(dir, GOLDEN_REL);
    if (existsSync(candidate)) return candidate;
    dir = join(dir, "..");
  }
  throw new Error(`evaluation-ir golden not found walking up from ${srcDir}`);
}

const SRC_DIR = dirname(fileURLToPath(import.meta.url));
const GOLDEN_PATH = goldenPathFromSrc(SRC_DIR);
const SCHEMA_PATH = join(dirname(GOLDEN_PATH), "schema.json");
const SCHEMA = JSON.parse(readFileSync(SCHEMA_PATH, "utf8")) as {
  additionalProperties?: unknown;
  properties?: Record<string, { const?: unknown }>;
};

/** Decode must fail extra keys the same way schema additionalProperties: false does. */
function decodeUnknownField(payload: unknown): void {
  expect(() => decodeEvaluationIR(payload)).toThrow(/unknown field/);
}

type GoldenRow = {
  id: string;
  op: string;
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

const GOLDEN_ROWS = loadGolden();

function countsGrade(payload: {
  n_expected: number;
  n_cells: number;
  n_complete: number;
  n_collapsed?: number;
  n_broken?: number;
}): boolean {
  return jobCandidateGrade({
    n_expected: payload.n_expected,
    n_cells: payload.n_cells,
    n_complete: payload.n_complete,
    n_collapsed: payload.n_collapsed,
    n_broken: payload.n_broken,
  });
}

describe("Evaluation IR golden vectors", () => {
  it("version and jobCandidateGrade identity", () => {
    expect(EVALUATION_IR_VERSION).toBe("evaluation-ir/v1");
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

  it("decodeUnknownField", () => {
    expect(SCHEMA.additionalProperties).toBe(false);
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
    decodeUnknownField({ ...good, go: true });
    decodeUnknownField({ ...good, operator_override: true });
    expect(() =>
      decodeEvaluationIR({ ...good, version: "evaluation-ir/v0" }),
    ).toThrow(/unsupported Evaluation IR version/);
    const decoded = decodeEvaluationIR(good);
    expect(decoded.candidate).toBe(
      jobCandidateGrade({
        n_expected: good.n_expected,
        n_cells: good.n_cells,
        n_complete: good.n_complete,
        n_collapsed: good.n_collapsed,
        n_broken: good.n_broken,
      }),
    );
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

  it("loads every encoder-owned golden.jsonl row from src/", () => {
    expect(GOLDEN_PATH.endsWith(GOLDEN_REL)).toBe(true);
    expect(GOLDEN_ROWS.length).toBeGreaterThan(0);
    const ids = GOLDEN_ROWS.map((row) => row.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toContain("smuggled_candidate_partial");
    expect(
      GOLDEN_ROWS.every((row) => row.op === "roundtrip" || row.op === "decode"),
    ).toBe(true);
  });

  it("schema.json exists next to golden and locks additionalProperties and version", () => {
    expect(SCHEMA_PATH.endsWith(SCHEMA_REL)).toBe(true);
    expect(existsSync(SCHEMA_PATH)).toBe(true);
    expect(SCHEMA.additionalProperties).toBe(false);
    expect(SCHEMA.properties?.version?.const).toBe("evaluation-ir/v1");
    expect(EVALUATION_IR_VERSION).toBe(SCHEMA.properties?.version?.const);
    expect([...ALLOWED_FIELDS].sort()).toEqual(
      Object.keys(SCHEMA.properties ?? {}).sort(),
    );
    const encodedKeys = Object.keys(
      encodeEvaluationIR({ n_expected: 1, n_cells: 1, n_complete: 1 }),
    ).sort();
    expect(encodedKeys).toEqual(Object.keys(SCHEMA.properties ?? {}).sort());
    expect(encodedKeys).toEqual([...ALLOWED_FIELDS].sort());
    const generated = readFileSync(
      join(SRC_DIR, "evaluation_ir_allowed_fields.generated.ts"),
      "utf8",
    );
    expect(generated).toMatch(/Do not edit by hand/);
    expect(generated).toContain("schema.json");
    const codec = readFileSync(join(SRC_DIR, "evaluation_ir.ts"), "utf8");
    expect(codec).not.toMatch(/CANONICAL_FIELDS/);
    expect(codec).toContain("jobCandidateGrade");
  });

  it.each(GOLDEN_ROWS)("golden $id ($op) encode/decode match", (row) => {
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
      if (
        payload.candidate === true &&
        countsGrade(payload) === false
      ) {
        expect(row.expect_error).toBe("job_candidate_grade");
      }
      return;
    }
    if (row.op !== "roundtrip") {
      throw new Error(`unknown golden op ${String(row.op)} (${row.id})`);
    }
    const encoded = encodeEvaluationIR(row.args as EvaluationIREncodeArgs);
    const grade = countsGrade(encoded);
    expect(encoded.candidate, row.id).toBe(grade);
    expect(encoded.candidate, row.id).toBe(row.expect?.candidate);
    expect(encoded.failure_reason, row.id).toBe(row.expect?.failure_reason);
    const decoded = decodeEvaluationIR(encoded);
    expect(decoded.candidate, row.id).toBe(grade);
    expect(decoded.failure_reason, row.id).toBe(row.expect?.failure_reason);
    expect(decoded.toDict().candidate, row.id).toBe(grade);
    if (grade === false) {
      expect(() =>
        decodeEvaluationIR({ ...encoded, candidate: true }),
      ).toThrow(/job_candidate_grade/);
    }
  });
});
