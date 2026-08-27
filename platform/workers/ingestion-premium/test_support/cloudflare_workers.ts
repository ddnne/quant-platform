/** Minimal constructor semantics for node-side behavioral tests only. */
export abstract class WorkerEntrypoint<Env = Cloudflare.Env> {
  protected readonly ctx: ExecutionContext;
  protected readonly env: Env;

  constructor(ctx: ExecutionContext, env: Env) {
    this.ctx = ctx;
    this.env = env;
  }
}
