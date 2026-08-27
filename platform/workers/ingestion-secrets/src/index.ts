/**
 * J-Quants credential holder.
 *
 * Public HTTP preserves the time-bounded authenticated legacy proxy.  The new
 * governed acquisition surface is a closed WorkerEntrypoint RPC method; no HTTP
 * route dispatches or tunnels it.
 */
import { WorkerEntrypoint } from "cloudflare:workers";
import { fetchGovernedPage, type AcquisitionEnv } from "./jquants_acquisition";
import type {
  JquantsAcquisitionRequestV2,
  JquantsAcquisitionRpc,
} from "./jquants_acquisition_types";
import { handleHttpRequest, type LegacyHttpEnv } from "./legacy_http";

export type Env = AcquisitionEnv & LegacyHttpEnv & {
  ENVIRONMENT?: "production" | "staging";
};

export class IngestionSecretsService
  extends WorkerEntrypoint<Env>
  implements JquantsAcquisitionRpc {
  override fetch(request: Request): Promise<Response> {
    return handleHttpRequest(request, this.env);
  }

  fetch_governed_page(request: JquantsAcquisitionRequestV2): Promise<Response> {
    return fetchGovernedPage(request, this.env);
  }
}

export default IngestionSecretsService;
