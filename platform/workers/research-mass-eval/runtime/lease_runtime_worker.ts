import { controlledContainerR2Outbound } from "../src/controlled_pilot_container_r2";

type RuntimeEnv = { STRUCTURED_BUCKET: R2Bucket };

export default {
  async fetch(request: Request, env: RuntimeEnv): Promise<Response> {
    const url = new URL(request.url);
    const key = url.pathname.startsWith("/") ? url.pathname.slice(1) : url.pathname;
    const handled = await controlledContainerR2Outbound(request, env, key);
    return (
      handled ??
      new Response(JSON.stringify({ error: "not handled" }), {
        status: 404,
        headers: { "content-type": "application/json; charset=utf-8" },
      })
    );
  },
};
