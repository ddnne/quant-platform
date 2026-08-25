# quant-platform-research-ai-gateway

Strict Workers AI gateway. The research mass-eval worker **must not** bind `AI`.

## Contract

- Allowed models only
- Unknown request fields rejected
- Token comparison fail-closed (unbound `GATEWAY_TOKEN` denies)
- Measures input/output tokens and a monetary estimate
- Content-addressed prompt/output digests
- Does not mint READY, Mass, or GO

Health (`GET /health`) returns `{ok, service}` only.

## Bindings

Research mass-eval uses the named `GatewayService` RPC entrypoint through the
`AI_GATEWAY` service binding. The binding itself is the capability; mass-eval
does not hold or send `GATEWAY_TOKEN`. Header-token auth remains only for the
closed HTTP defense-in-depth surface.
