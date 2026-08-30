import { WorkerEntrypoint } from "cloudflare:workers";

/**
 * Test-only JQUANTS_ACQUISITION target for the mass-eval/gateway harness.
 * Production and staging keep binding quant-platform-ingestion-secrets.
 */
export class IngestionSecretsService extends WorkerEntrypoint {
  fetch(): Promise<Response> {
    return Promise.resolve(new Response("not found", { status: 404 }));
  }

  fetch_governed_page(_request: unknown): Promise<Response> {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          ok: false,
          error: "governed page test target does not acquire",
        }),
        {
          status: 503,
          headers: { "content-type": "application/json; charset=utf-8" },
        },
      ),
    );
  }
}

export default IngestionSecretsService;
