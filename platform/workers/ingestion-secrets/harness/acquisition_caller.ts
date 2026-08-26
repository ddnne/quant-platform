import type IngestionSecretsWorker from "../src/index";

type CallerEnv = {
  JQUANTS_ACQUISITION: Service<IngestionSecretsWorker>;
};

/** Test-only caller; returns the transferable RPC Response without reading it. */
export default {
  async fetch(request: Request, env: CallerEnv): Promise<Response> {
    if (request.method !== "POST") return new Response("POST required", { status: 405 });
    const value: unknown = await request.json();
    return env.JQUANTS_ACQUISITION.fetch_governed_page(value as never);
  },
} satisfies ExportedHandler<CallerEnv>;
