/// <reference types="@cloudflare/workers-types" />

import { evaluateLogicAcrossPeriods, rankSurvivors } from "./eval";
import {
  cellsFromPeriodPacks,
  evalLogicDailyPathOnPanel,
} from "./daily_path";
import {
  buildSyntheticPanels,
  defaultPeriodsFromRequest,
  loadR2Panels,
} from "./panels";
import type { Env, MassEvalJobResult, MassEvalRequest } from "./types";
import {
  freezePayload,
  putChildrenThenManifest,
  putImmutableJson,
} from "./http";
import { dispatchMassEvalFetch } from "./http_routes";
import { encodeEvaluationIR } from "./evaluation_ir";
import { isPathBroken } from "./path_broken";
import {
  PersonalResearchContainer,
  personalResearchStatus,
  submitPersonalResearch,
} from "./personal_research_container";
import { runPersonalVolResearch } from "./personal_vol_research";

export { ContainerProxy } from "./personal_research_container";
export { PersonalResearchContainer };

const RESEARCH_PREFIX = "research/mass_eval";

async function runMassEval(
  env: Env,
  req: MassEvalRequest,
): Promise<MassEvalJobResult> {
  const t0 = Date.now();
  const version = env.MASS_EVAL_VERSION;
  const wave = env.MASS_EVAL_WAVE;
  const mode = req.mode || "synthetic";
  const oneWay = req.one_way_cost ?? 0.001;
  const maxCodes = Math.max(2, Math.min(40, req.max_codes ?? 8));
  const maxDays = Math.max(20, Math.min(260, req.max_days ?? 120));
  const periodSpecs = defaultPeriodsFromRequest(req.periods, req.seed);
  const panelsPrefix =
    req.panels_prefix || `research/mass_eval/job=${req.job_id}/panels`;

  let panels =
    mode === "nets_only"
      ? []
      : buildSyntheticPanels(periodSpecs, req.seed, maxCodes, maxDays);
  let panelNotes: string[] = [];

  if (mode === "r2_panels") {
    const loaded = await loadR2Panels(
      env.STRUCTURED_BUCKET,
      periodSpecs,
      panelsPrefix,
    );
    panels = loaded.panels;
    panelNotes = loaded.notes;
  }

  const results = req.logics.map((logic, index) =>
    evaluateLogicAcrossPeriods(logic, panels, {
      oneWayCost: oneWay,
      nearZeroAbs: req.near_zero_abs,
      minActivation: req.min_activation,
      seed: req.seed,
      index,
    }),
  );

  const ranking = rankSurvivors(results);
  const nOk = results.filter((r) => r.status === "ok").length;
  const nFail = results.length - nOk;
  const nSurvivors = ranking.length;

  const prefix = `${RESEARCH_PREFIX}/job=${req.job_id}`;
  const freezes = freezePayload(env);

  const summary = {
    version,
    wave,
    job_id: req.job_id,
    seed: req.seed,
    mode,
    n_logics: req.logics.length,
    n_periods: periodSpecs.length,
    n_eval_ok: nOk,
    n_eval_fail: nFail,
    n_survivors: nSurvivors,
    n_survivors_are_not_a_pass: true,
    screen_kind: "period_net",
    daily_path_complete: false,
    candidate_grade: false,
    wall_time_ms: Date.now() - t0,
    freezes,
    note: "Period-net screen only; n_survivors is not a pass.",
  };

  const manifest = {
    version,
    wave,
    job_id: req.job_id,
    created_at: new Date().toISOString(),
    bucket: "quant-structured",
    prefix,
    keys: {
      manifest: `${prefix}/manifest.json`,
      request: `${prefix}/request.json`,
      summary: `${prefix}/summary.json`,
      results: `${prefix}/results.json`,
      ranking: `${prefix}/ranking.json`,
      panels_meta: `${prefix}/panels_meta.json`,
    },
    freezes,
  };

  const panelsMeta = {
    mode,
    n_panels: panels.length,
    notes: panelNotes,
    panels: panels.map((p) => ({
      period_id: p.period_id,
      year: p.year,
      status: p.status,
      source: p.source,
      n_codes: Object.keys(p.bars || {}).length,
      n_days: Object.values(p.bars || {})[0]?.length ?? 0,
    })),
  };

  const resultsArt = await putImmutableJson(
    env.STRUCTURED_BUCKET,
    "research/mass_eval/artifacts",
    { kind: "results", job_id: req.job_id, results, freezes },
  );
  const commit = await putChildrenThenManifest(
    env.STRUCTURED_BUCKET,
    [
      {
        key: manifest.keys.request,
        data: {
          ...req,
          freezes,
          received_at: new Date().toISOString(),
        },
      },
      { key: manifest.keys.summary, data: summary },
      {
        key: manifest.keys.results,
        data: {
          version,
          wave,
          job_id: req.job_id,
          results,
          freezes,
          artifact_digest: resultsArt.digest,
        },
      },
      {
        key: manifest.keys.ranking,
        data: {
          version,
          wave,
          job_id: req.job_id,
          ranking,
          freezes,
        },
      },
      { key: manifest.keys.panels_meta, data: panelsMeta },
    ],
    {
      key: manifest.keys.manifest,
      data: {
        ...manifest,
        schema_version: "research_artifact/v1",
        artifact_digest: resultsArt.digest,
        artifact_key: resultsArt.key,
      },
    },
    resultsArt.digest,
  );
  if (!commit.ok) {
    throw Object.assign(new Error("artifact_conflict"), { code: "artifact_conflict" });
  }

  return {
    version,
    wave,
    job_id: req.job_id,
    seed: req.seed,
    mode,
    n_logics: req.logics.length,
    n_periods: periodSpecs.length,
    n_eval_ok: nOk,
    n_eval_fail: nFail,
    n_survivors: nSurvivors,
    n_survivors_are_not_a_pass: true,
    screen_kind: "period_net",
    daily_path_complete: false,
    candidate_grade: false,
    wall_time_ms: Date.now() - t0,
    ranking,
    results,
    r2_keys: manifest.keys,
    freezes,
    note: summary.note,
  };
}

async function runDailyPath(
  env: Env,
  req: MassEvalRequest,
): Promise<Record<string, unknown>> {
  const t0 = Date.now();
  const version = env.MASS_EVAL_VERSION;
  const mode = req.mode || "r2_panels";
  const oneWay = req.one_way_cost ?? 0.001;
  const maxCodes = Math.max(2, Math.min(40, req.max_codes ?? 8));
  const maxDays = Math.max(20, Math.min(260, req.max_days ?? 120));
  const periodSpecs = defaultPeriodsFromRequest(req.periods, req.seed);
  const panelsPrefix =
    req.panels_prefix || `research/mass_eval/job=${req.job_id}/panels`;

  let panels =
    mode === "nets_only"
      ? []
      : buildSyntheticPanels(periodSpecs, req.seed, maxCodes, maxDays);
  let panelNotes: string[] = [];
  if (mode === "r2_panels") {
    const loaded = await loadR2Panels(
      env.STRUCTURED_BUCKET,
      periodSpecs,
      panelsPrefix,
    );
    panels = loaded.panels;
    panelNotes = loaded.notes;
  }

  const cells: Array<Record<string, unknown>> = [];
  for (const logic of req.logics) {
    const packs = panels.map((p) =>
      evalLogicDailyPathOnPanel(logic, p, oneWay),
    );
    cells.push(...cellsFromPeriodPacks(String(logic.logic_id), packs));
  }

  const nComplete = cells.filter((c) => c.daily_path_complete).length;
  const nBroken = cells.filter((c) =>
    isPathBroken(c.eval_path, c.path_fallback),
  ).length;
  const nCollapsed = cells.filter((c) => {
    const fb = String(c.path_fallback || "");
    const skip = String(c.skip_reason || c.incomplete_reason || "");
    return fb.includes("path_collapsed") || skip.startsWith("unique_unsupported");
  }).length;
  const nExpected = req.logics.length * periodSpecs.length;
  const freezes = freezePayload(env);
  const evaluation_ir = encodeEvaluationIR({
    n_expected: nExpected,
    n_cells: cells.length,
    n_complete: nComplete,
    n_collapsed: nCollapsed,
    n_broken: nBroken,
  });
  const payload: Record<string, unknown> = {
    version,
    wave: env.MASS_EVAL_WAVE,
    job_id: req.job_id,
    eval_kind: "daily_path",
    // Grade authority is jobCandidateGrade via encode; do not grade twice.
    candidate_grade: evaluation_ir.candidate,
    evaluation_ir,
    parallel_model: "isolate_fanout_one_logic",
    mode,
    n_logics: req.logics.length,
    n_periods: periodSpecs.length,
    n_cells: cells.length,
    n_daily_path_complete: nComplete,
    cells,
    panel_notes: panelNotes,
    panels_prefix: panelsPrefix,
    wall_time_ms: Date.now() - t0,
    survived: false,
    promote_as_main: false,
    go: false,
    freezes,
    note: "Candidate-grade daily MTM. Not a promotion.",
  };
  if (req.write_artifacts === true) {
    const prefix = `research/eval/job=${req.job_id}`;
    const artifact = await putImmutableJson(
      env.STRUCTURED_BUCKET,
      "research/eval/artifacts",
      payload,
    );
    payload.artifact_digest = artifact.digest;
    payload.artifact_key = artifact.key;
    const commit = await putChildrenThenManifest(
      env.STRUCTURED_BUCKET,
      [],
      { key: `${prefix}/daily_path.json`, data: payload },
      artifact.digest,
    );
    payload.r2_keys = {
      daily_path: `${prefix}/daily_path.json`,
      artifact: artifact.key,
      digest: artifact.digest,
    };
    payload.artifact_created = commit.manifest.created;
    if (!commit.ok) {
      payload.artifact_conflict = true;
    }
  }
  return payload;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    return dispatchMassEvalFetch(request, env, {
      runMassEval,
      runDailyPath,
      submitPersonalResearch,
      personalResearchStatus,
      runPersonalVolResearch,
    });
  },
};
