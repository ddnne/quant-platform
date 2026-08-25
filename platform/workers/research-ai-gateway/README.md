# quant-platform-research-ai-gateway

Strict Workers AI gateway. The research mass-eval worker **must not** bind `AI`.

## Contract

- Allowed models only
- Unknown request fields rejected
- Token comparison fail-closed (unbound `GATEWAY_TOKEN` denies)
- Measures input/output tokens and a monetary estimate
- Enforces message-count, UTF-8 byte, and conservative input-token upper bounds before Workers AI
- Content-addressed prompt/output digests
- Does not mint READY, Mass, or GO

## Durable budget settlement

`BudgetLedger` persists a lease, a `provider_started_at` recovery marker, and a
one-shot settlement capability before Workers AI is invoked. The production
Gateway path is the sole settlement coordinator: generic HTTP
`/finalize`, `/reconcile`, `/provider-started`, and capability-mint routes are
not settlement authority. Exact usage is derived privately by Gateway from the
provider response; the Durable Object derives uncertain settlement from the
reserved maximum and ignores caller-authored receipt/result/settlement claims.
A timeout, provider error without usage, lost/invalid finalize response, Worker
interruption, or expired provider-started lease can never be treated as zero
usage: the ledger charges the persisted reservation maximum, freezes new work,
records an audit entry, and caches a fail-closed response. A Durable Object
alarm is written with the reservation and rebuilt on restart, so recovery does
not depend on the request Worker remaining alive.

Only a reservation that has not crossed the durable provider-start marker may
be released at zero cost. Idempotent retries return the terminal cached result
and do not call Workers AI twice.

Health (`GET /health`) returns `{ok, service}` only.

## Bindings

Research mass-eval uses the named `GatewayService` RPC entrypoint through the
`AI_GATEWAY` service binding. The binding itself is the capability; mass-eval
does not hold or send `GATEWAY_TOKEN`. Header-token auth remains only for the
closed HTTP defense-in-depth surface.
