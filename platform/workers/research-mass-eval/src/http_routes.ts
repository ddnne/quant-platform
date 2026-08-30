/// <reference types="@cloudflare/workers-types" />

import {
  netsOnlyGate,
  researchCapabilities,
  requireCapability,
} from "./capabilities";
import {
  authorized,
  freezePayload,
  isObject,
  json,
  putChildrenThenManifest,
  readBoundedJson,
} from "./http";
import { parseRequest } from "./parse_request";
import { runProposeThesis } from "./propose_thesis";
import {
  PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS,
  isPersonalResearchJobId,
  parsePersonalResearchRequest,
  personalResearchJobIdFromPath,
  type PersonalResearchRequest,
} from "./personal_research_contract";
import {
  PERSONAL_SNAPSHOT_MAX_REQUEST_BYTES,
  parsePersonalSnapshotBuildRequest,
  personalSnapshotJobIdFromPath,
  type PersonalSnapshotBuildRequest,
} from "./personal_snapshot_contract";
import {
  PERSONAL_RESEARCH_BATCH_MAX_BYTES,
  parsePersonalResearchBatchRequest,
  personalResearchBatchJobIdsFromUrl,
} from "./personal_research_batch";
import {
  parsePersonalVolResearchRequest,
  type PersonalVolResearchRequest,
} from "./personal_vol_research";
import {
  parsePersonalVolAmPmResearchRequest,
  type PersonalVolAmPmResearchRequest,
} from "./personal_vol_am_pm";
import {
  parsePersonalSvi2023Request,
  personalSviJobIdFromPath,
  type PersonalSvi2023Request,
} from "./personal_svi_2023_contract";
import {
  parsePersonalIndexVolOverlay2023Request,
  personalIndexVolOverlay2023JobIdFromPath,
  type PersonalIndexVolOverlay2023Request,
} from "./personal_index_vol_overlay_2023_contract";
import type { Env, MassEvalJobResult, MassEvalRequest } from "./types";

export type MassEvalFetchHandlers = {
  runMassEval: (env: Env, req: MassEvalRequest) => Promise<MassEvalJobResult>;
  runDailyPath: (
    env: Env,
    req: MassEvalRequest,
  ) => Promise<Record<string, unknown>>;
  submitPersonalResearch?: (
    env: Env,
    request: PersonalResearchRequest,
  ) => Promise<Response>;
  personalResearchStatus?: (env: Env, jobId: string) => Promise<Response>;
  runPersonalVolResearch?: (
    env: Env,
    request: PersonalVolResearchRequest,
  ) => Promise<Record<string, unknown>>;
  runPersonalVolAmPmResearch?: (
    env: Env,
    request: PersonalVolAmPmResearchRequest,
  ) => Promise<Record<string, unknown>>;
  submitPersonalSvi2023?: (
    env: Env,
    request: PersonalSvi2023Request,
  ) => Promise<Response>;
  personalSvi2023Status?: (env: Env, jobId: string) => Promise<Response>;
  submitPersonalIndexVolOverlay2023?: (
    env: Env,
    request: PersonalIndexVolOverlay2023Request,
  ) => Promise<Response>;
  personalIndexVolOverlay2023Status?: (
    env: Env,
    jobId: string,
  ) => Promise<Response>;
  submitPersonalSnapshotBuild?: (
    env: Env,
    request: PersonalSnapshotBuildRequest,
  ) => Promise<Response>;
  personalSnapshotBuildStatus?: (env: Env, jobId: string) => Promise<Response>;
  submitPersonalResearchJobs?: (
    env: Env,
    requests: PersonalResearchRequest[],
  ) => Promise<Response>;
  personalResearchBatchStatus?: (
    env: Env,
    jobIds: string[],
  ) => Promise<Response>;
};

/** HTTP path dispatch. Orchestration stays in index.ts; R2 put stays in http.ts. */
export async function dispatchMassEvalFetch(
  request: Request,
  env: Env,
  handlers: MassEvalFetchHandlers,
): Promise<Response> {
  const url = new URL(request.url);

  if (url.pathname === "/v1/personal-index-vol-overlay-2023") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    if (
      !env.STRUCTURED_BUCKET ||
      !env.PERSONAL_RESEARCH_CONTAINER ||
      !handlers.submitPersonalIndexVolOverlay2023
    ) {
      return json({ error: "personal index-vol overlay unavailable" }, 503);
    }
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON body" }, 400);
    }
    const parsed = parsePersonalIndexVolOverlay2023Request(body);
    if (!parsed.ok) return json({ error: parsed.error }, 400);
    return handlers.submitPersonalIndexVolOverlay2023(env, parsed.value);
  }

  if (url.pathname.startsWith("/v1/personal-index-vol-overlay-2023/jobs/")) {
    if (request.method !== "GET") {
      return json({ error: "GET required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    const jobId = personalIndexVolOverlay2023JobIdFromPath(url.pathname);
    if (!jobId) return json({ error: "job_id is invalid" }, 400);
    if (!env.STRUCTURED_BUCKET || !handlers.personalIndexVolOverlay2023Status) {
      return json({ error: "personal index-vol overlay status unavailable" }, 503);
    }
    return handlers.personalIndexVolOverlay2023Status(env, jobId);
  }

  if (url.pathname === "/v1/personal-svi-2023") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    if (
      !env.STRUCTURED_BUCKET ||
      !env.PERSONAL_RESEARCH_CONTAINER ||
      !handlers.submitPersonalSvi2023
    ) {
      return json({ error: "personal SVI research unavailable" }, 503);
    }
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON body" }, 400);
    }
    const parsed = parsePersonalSvi2023Request(body);
    if (!parsed.ok) return json({ error: parsed.error }, 400);
    return handlers.submitPersonalSvi2023(env, parsed.value);
  }

  if (url.pathname.startsWith("/v1/personal-svi-2023/jobs/")) {
    if (request.method !== "GET") {
      return json({ error: "GET required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    const jobId = personalSviJobIdFromPath(url.pathname);
    if (!jobId) return json({ error: "job_id is invalid" }, 400);
    if (!env.STRUCTURED_BUCKET || !handlers.personalSvi2023Status) {
      return json({ error: "personal SVI status unavailable" }, 503);
    }
    return handlers.personalSvi2023Status(env, jobId);
  }

  if (url.pathname === "/v1/personal-vol-am-pm-research") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    if (!env.STRUCTURED_BUCKET || !handlers.runPersonalVolAmPmResearch) {
      return json({ error: "personal vol AM/PM research unavailable" }, 503);
    }
    let amPmBody: unknown;
    try {
      amPmBody = await request.json();
    } catch {
      return json({ error: "invalid JSON body" }, 400);
    }
    const amPmParsed = parsePersonalVolAmPmResearchRequest(amPmBody);
    if (!amPmParsed.ok) return json({ error: amPmParsed.error }, 400);
    try {
      const result = await handlers.runPersonalVolAmPmResearch(
        env,
        amPmParsed.value,
      );
      return json({ ok: true, ...result });
    } catch (error) {
      const code = (error as { code?: string }).code;
      if (code === "artifact_conflict") {
        return json(
          {
            ok: false,
            error: "artifact_conflict",
            job_id: amPmParsed.value.job_id,
            go: false,
            not_a_pass: true,
          },
          409,
        );
      }
      const detail =
        error instanceof Error ? `${error.name}: ${error.message}` : String(error);
      return json(
        {
          ok: false,
          error: "personal_vol_am_pm_research_failed",
          detail,
          go: false,
          not_a_pass: true,
        },
        500,
      );
    }
  }

  if (url.pathname === "/v1/personal-vol-research") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    if (!env.STRUCTURED_BUCKET || !handlers.runPersonalVolResearch) {
      return json({ error: "personal vol research unavailable" }, 503);
    }
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON body" }, 400);
    }
    const parsed = parsePersonalVolResearchRequest(body);
    if (!parsed.ok) return json({ error: parsed.error }, 400);
    try {
      const result = await handlers.runPersonalVolResearch(env, parsed.value);
      return json({ ok: true, ...result });
    } catch (error) {
      const code = (error as { code?: string }).code;
      if (code === "artifact_conflict") {
        return json(
          {
            ok: false,
            error: "artifact_conflict",
            job_id: parsed.value.job_id,
            go: false,
            not_a_pass: true,
          },
          409,
        );
      }
      const detail =
        error instanceof Error ? `${error.name}: ${error.message}` : String(error);
      return json(
        {
          ok: false,
          error: "personal_vol_research_failed",
          detail,
          go: false,
          not_a_pass: true,
        },
        500,
      );
    }
  }

  if (url.pathname === "/v1/personal-snapshot-build") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    if (
      !env.STRUCTURED_BUCKET ||
      !env.PERSONAL_RESEARCH_CONTAINER ||
      !handlers.submitPersonalSnapshotBuild
    ) {
      return json({ error: "personal snapshot bindings unavailable" }, 503);
    }
    const bounded = await readBoundedJson(
      request,
      PERSONAL_SNAPSHOT_MAX_REQUEST_BYTES,
    );
    if (!bounded.ok) return json({ error: bounded.error }, bounded.status);
    const parsed = parsePersonalSnapshotBuildRequest(bounded.value);
    if (!parsed.ok) return json({ error: parsed.error }, 400);
    return handlers.submitPersonalSnapshotBuild(env, parsed.value);
  }

  if (url.pathname.startsWith("/v1/personal-snapshot-build/")) {
    if (request.method !== "GET") {
      return json({ error: "GET required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    const jobId = personalSnapshotJobIdFromPath(url.pathname);
    if (!jobId) return json({ error: "job_id is invalid" }, 400);
    if (!env.STRUCTURED_BUCKET || !handlers.personalSnapshotBuildStatus) {
      return json({ error: "personal snapshot status unavailable" }, 503);
    }
    return handlers.personalSnapshotBuildStatus(env, jobId);
  }

  if (url.pathname === "/v1/personal-research-batch") {
    if (request.method === "GET") {
      if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
        return json({ error: "unauthorized" }, 401);
      }
      const jobIds = personalResearchBatchJobIdsFromUrl(url);
      if (!jobIds || jobIds.length < 1) {
        return json({ error: "job_id query is required" }, 400);
      }
      if (jobIds.length > PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS) {
        return json(
          {
            error: `batch status must contain 1-${PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS} job ids`,
          },
          400,
        );
      }
      if (jobIds.some((jobId) => !isPersonalResearchJobId(jobId))) {
        return json({ error: "job_id is invalid" }, 400);
      }
      if (
        !env.STRUCTURED_BUCKET ||
        !handlers.personalResearchBatchStatus
      ) {
        return json({ error: "personal research batch status unavailable" }, 503);
      }
      return handlers.personalResearchBatchStatus(env, jobIds);
    }
    if (request.method !== "POST") {
      return json({ error: "POST or GET required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    const rawLength = request.headers.get("content-length") ?? "";
    if (
      !/^\d+$/.test(rawLength) ||
      Number(rawLength) < 1 ||
      Number(rawLength) > PERSONAL_RESEARCH_BATCH_MAX_BYTES
    ) {
      return json({ error: "batch request is too large" }, 413);
    }
    if (
      !env.STRUCTURED_BUCKET ||
      !env.PERSONAL_RESEARCH_CONTAINER ||
      !handlers.submitPersonalResearchJobs
    ) {
      return json({ error: "personal research bindings unavailable" }, 503);
    }
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON body" }, 400);
    }
    const parsed = parsePersonalResearchBatchRequest(body);
    if (!parsed.ok) return json({ error: parsed.error }, 400);
    return handlers.submitPersonalResearchJobs(env, parsed.value);
  }

  if (url.pathname === "/v1/personal-research") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    if (!env.STRUCTURED_BUCKET || !env.PERSONAL_RESEARCH_CONTAINER) {
      return json({ error: "personal research bindings unavailable" }, 503);
    }
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON body" }, 400);
    }
    const parsed = parsePersonalResearchRequest(body);
    if (!parsed.ok) return json({ error: parsed.error }, 400);
    if (!handlers.submitPersonalResearch) {
      return json({ error: "personal research handler unavailable" }, 503);
    }
    return handlers.submitPersonalResearch(env, parsed.value);
  }

  if (url.pathname.startsWith("/v1/personal-research/jobs/")) {
    if (request.method !== "GET") {
      return json({ error: "GET required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    const jobId = personalResearchJobIdFromPath(url.pathname);
    if (!jobId) return json({ error: "job_id is invalid" }, 400);
    if (!env.STRUCTURED_BUCKET || !handlers.personalResearchStatus) {
      return json({ error: "personal research handler unavailable" }, 503);
    }
    return handlers.personalResearchStatus(env, jobId);
  }

  if (url.pathname === "/health" || url.pathname === "/") {
    if (request.method !== "GET") {
      return json({ error: "GET required" }, 405);
    }
    return json({
      ok: true,
      service: "quant-platform-research-mass-eval",
      version: env.MASS_EVAL_VERSION,
    });
  }

  if (url.pathname === "/v1/mass-eval") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    const massCaps = researchCapabilities(env);
    const massGate = requireCapability("mass_screen", massCaps);
    if (!massGate.allowed) {
      return json(
        {
          ok: false,
          error: "capability_missing",
          capability: "mass_screen",
          reasons: massGate.reasons,
          go: false,
          not_a_pass: true,
        },
        403,
      );
    }
    if (!env.STRUCTURED_BUCKET) {
      return json({ error: "STRUCTURED_BUCKET not bound" }, 500);
    }

    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON body" }, 400);
    }

    const parsed = parseRequest(body);
    if (!parsed.ok) {
      return json({ error: parsed.error }, 400);
    }
    const netsGate = netsOnlyGate(parsed.value.mode, env, massGate.allowed);
    if (!netsGate.allowed) {
      return json(
        {
          ok: false,
          error: "nets_only_denied",
          capability: "mass_screen",
          reasons: netsGate.reasons,
          go: false,
          not_a_pass: true,
        },
        403,
      );
    }

    try {
      const result = await handlers.runMassEval(env, parsed.value);
      return json({
        ok: true,
        ...result,
      });
    } catch (e) {
      const code = (e as { code?: string }).code;
      if (code === "artifact_conflict") {
        return json(
          {
            ok: false,
            error: "artifact_conflict",
            job_id: parsed.value.job_id,
            go: false,
            not_a_pass: true,
          },
          409,
        );
      }
      const msg = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
      return json(
        {
          ok: false,
          error: "mass_eval_failed",
          detail: msg,
          freezes: freezePayload(env),
        },
        500,
      );
    }
  }

  if (url.pathname === "/v1/daily-path") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    const pathCaps = researchCapabilities(env);
    const pathGate = requireCapability("mass_screen", pathCaps);
    if (!pathGate.allowed) {
      return json(
        {
          ok: false,
          error: "capability_missing",
          capability: "mass_screen",
          reasons: pathGate.reasons,
          go: false,
          not_a_pass: true,
        },
        403,
      );
    }
    if (!env.STRUCTURED_BUCKET) {
      return json({ error: "STRUCTURED_BUCKET not bound" }, 500);
    }
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON body" }, 400);
    }
    const parsed = parseRequest(body);
    if (!parsed.ok) {
      return json({ error: parsed.error }, 400);
    }
    const netsGate = netsOnlyGate(parsed.value.mode, env, pathGate.allowed);
    if (!netsGate.allowed) {
      return json(
        {
          ok: false,
          error: "nets_only_denied",
          capability: "mass_screen",
          reasons: netsGate.reasons,
          go: false,
          not_a_pass: true,
        },
        403,
      );
    }
    parsed.value.eval_kind = "daily_path";
    if ((body as { write_artifacts?: boolean }).write_artifacts !== true) {
      parsed.value.write_artifacts = false;
    }
    try {
      const result = await handlers.runDailyPath(env, parsed.value);
      if (result.artifact_conflict === true) {
        return json(
          {
            ok: false,
            error: "artifact_conflict",
            job_id: parsed.value.job_id,
            r2_keys: result.r2_keys,
            go: false,
            not_a_pass: true,
          },
          409,
        );
      }
      return json({ ok: true, ...result });
    } catch (e) {
      const msg = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
      return json(
        {
          ok: false,
          error: "daily_path_failed",
          detail: msg,
          freezes: freezePayload(env),
        },
        500,
      );
    }
  }

  if (url.pathname === "/v1/children-then-manifest") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!env.MASS_EVAL_TOKEN) {
      return json({ error: "MASS_EVAL_TOKEN not bound" }, 503);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    if (!env.STRUCTURED_BUCKET) {
      return json({ error: "STRUCTURED_BUCKET not bound" }, 500);
    }
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON body" }, 400);
    }
    if (!isObject(body)) {
      return json({ error: "body must be JSON object" }, 400);
    }
    if (!Array.isArray(body.children)) {
      return json({ error: "children[] required" }, 400);
    }
    const children: Array<{ key: string; data: unknown }> = [];
    for (let i = 0; i < body.children.length; i++) {
      const raw = body.children[i];
      if (!isObject(raw)) {
        return json({ error: `children[${i}] must be object` }, 400);
      }
      const key = String(raw.key ?? "").trim();
      if (!key) {
        return json({ error: `children[${i}].key required` }, 400);
      }
      if (!("data" in raw)) {
        return json({ error: `children[${i}].data required` }, 400);
      }
      children.push({ key, data: raw.data });
    }
    if (!isObject(body.manifest)) {
      return json({ error: "manifest object required" }, 400);
    }
    const manifestKey = String(body.manifest.key ?? "").trim();
    if (!manifestKey) {
      return json({ error: "manifest.key required" }, 400);
    }
    if (!("data" in body.manifest)) {
      return json({ error: "manifest.data required" }, 400);
    }
    // Digest is Worker-computed in putJsonCreateOnly. Pass through only a
    // caller-supplied string; do not hash here.
    let expected: string | undefined;
    if (typeof body.expected_child_digest === "string") {
      const digest = body.expected_child_digest.trim();
      if (digest) expected = digest;
    }
    const commit = await putChildrenThenManifest(
      env.STRUCTURED_BUCKET,
      children,
      { key: manifestKey, data: body.manifest.data },
      expected,
    );
    const status = commit.ok ? 200 : commit.conflict ? 409 : 500;
    return json(
      {
        ok: commit.ok,
        children: commit.children,
        manifest: commit.manifest,
        conflict: commit.conflict,
        verified: commit.verified,
        go: false,
        not_a_pass: true,
        ...(commit.ok
          ? {}
          : {
              error: commit.conflict
                ? "artifact_conflict"
                : "children_then_manifest_failed",
            }),
      },
      status,
    );
  }

  if (url.pathname === "/v1/propose-thesis") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    const genCaps = researchCapabilities(env);
    const genGate = requireCapability("generation", genCaps);
    if (!genGate.allowed) {
      return json(
        {
          ok: false,
          error: "capability_missing",
          capability: "generation",
          reasons: genGate.reasons,
          go: false,
          not_a_pass: true,
        },
        403,
      );
    }
    let body: unknown = {};
    const text = await request.text();
    if (text.trim()) {
      try {
        body = JSON.parse(text);
      } catch {
        return json({ error: "invalid JSON body" }, 400);
      }
    }
    if (text.trim() && !isObject(body)) {
      return json({ error: "body must be JSON object" }, 400);
    }
    const obj = isObject(body) ? body : {};
    try {
      const result = await runProposeThesis(env, obj);
      // llm_failed is fail-closed success-of-contract (HTTP 200, ok:false).
      const status =
        result.error === "window_tweak_only_forbidden" ||
        result.error === "job_id required for write_artifacts" ||
        result.error === "STRUCTURED_BUCKET not bound"
          ? 400
          : 200;
      return json(result, status);
    } catch (e) {
      const msg = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
      return json(
        {
          ok: false,
          error: "propose_thesis_failed",
          detail: msg,
          auto_inject: false,
          go: false,
          not_a_pass: true,
          freezes: freezePayload(env),
        },
        500,
      );
    }
  }

  return json({ error: "not found", path: url.pathname }, 404);
}
