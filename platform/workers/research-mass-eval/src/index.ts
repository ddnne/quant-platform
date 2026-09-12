/// <reference types="@cloudflare/workers-types" />

import type { Env } from "./types";
import { json } from "./http";
import { dispatchMassEvalFetch } from "./http_routes";
import {
  PersonalResearchContainer,
  personalResearchStatus,
  submitPersonalResearch,
  submitPersonalResearchJobs,
} from "./personal_research_container";
import { personalResearchBatchStatus } from "./personal_research_batch";
import {
  personalSnapshotBuildStatus,
  submitPersonalSnapshotBuild,
} from "./personal_snapshot";
import { runPersonalVolResearch } from "./personal_vol_research";
import { runPersonalVolAmPmResearch } from "./personal_vol_am_pm";
import {
  personalVolAmPmPanelBuildStatus,
  submitPersonalVolAmPmPanelBuild,
} from "./personal_vol_am_pm_panel_writer";
import {
  personalOptionSidecarProduceStatus,
  submitPersonalOptionSidecarProduce,
} from "./personal_option_sidecar_producer";
import {
  personalSvi2023Status,
  submitPersonalSvi2023,
} from "./personal_svi_2023";
import {
  personalIndexVolOverlay2023Status,
  submitPersonalIndexVolOverlay2023,
} from "./personal_index_vol_overlay_2023";
import type { PersonalResearchRequest } from "./personal_research_contract";
import {
  controlledPilotStatus,
  submitControlledPilot,
} from "./controlled_pilot";

export { ContainerProxy } from "./personal_research_container";
export { PersonalResearchContainer };

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    return dispatchMassEvalFetch(request, env, {
      submitPersonalResearch,
      personalResearchStatus,
      runPersonalVolResearch,
      runPersonalVolAmPmResearch,
      submitPersonalSvi2023,
      personalSvi2023Status,
      submitPersonalIndexVolOverlay2023,
      personalIndexVolOverlay2023Status,
      submitPersonalSnapshotBuild,
      personalSnapshotBuildStatus,
      submitPersonalVolAmPmPanelBuild,
      personalVolAmPmPanelBuildStatus,
      submitPersonalOptionSidecarProduce,
      personalOptionSidecarProduceStatus,
      submitPersonalResearchJobs: async (
        env: Env,
        requests: PersonalResearchRequest[],
      ) => {
        const jobs = await submitPersonalResearchJobs(env, requests);
        return json({
          ok: jobs.every((job) => job.state !== "rejected"),
          jobs,
          go: false,
          automatic_promotion: false,
          live_orders_enabled: false,
        });
      },
      personalResearchBatchStatus,
      submitControlledPilot,
      controlledPilotStatus,
    }, ctx);
  },
};
