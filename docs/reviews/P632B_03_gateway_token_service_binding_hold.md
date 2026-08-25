# P632B-03 GATEWAY_TOKEN service-binding residual — HOLD

**Status:** HOLD (not CLOSED). Production `authorized()` unchanged.  
**Isolation worktree:** `/private/tmp/qp-p632b-03-gateway-hold` on `docs/p632b-03-gateway-token-hold`. Do not push `main`.  
**HEAD measured:** `3b64bdfc` (`origin/grok/phase63-ci-source-closure`).  
**Mass / READY / Phase 7:** not armed.

## Residual (still OPEN)

Mass-eval still requires a second copy of `GATEWAY_TOKEN` on the `AI_GATEWAY` service-binding path:

```23:52:platform/workers/research-mass-eval/src/ai_gateway_client.ts
function gatewayToken(env: Env): string | undefined {
  const rec = env as Env & { GATEWAY_TOKEN?: string };
  return rec.GATEWAY_TOKEN;
}
// ...
  if (!token) {
    return { ok: false, reason: "gateway_token_unbound" };
  }
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "X-Gateway-Token": token,
  };
```

Gateway `authorized()` still compares only `X-Gateway-Token` to `env.GATEWAY_TOKEN`. Unbound `GATEWAY_TOKEN` denies. `MASS_EVAL_TOKEN` is a different secret; tests in `platform/workers/research-ai-gateway/src/index.test.ts` already pin it is not a substitute.

That shared bearer is Independent B P632B-03 remaining OPEN across waves. This isolation does **not** close it.

## Detector search (why no code close)

Intended close was: keep public/preview `fetch` fail-closed on `X-Gateway-Token`, and skip the token only if Cloudflare documents a reliable service-binding caller identity (`CF-Worker` or equivalent). A guessed header is forbidden.

| Candidate | Documented as | Usable as fail-closed auth? |
|-----------|---------------|-----------------------------|
| `CF-Worker` | Edge Worker **subrequest** header on global `fetch()`, zone name not Worker name. Recipients may filter Worker-originated traffic. [HTTP headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/#cf-worker) | **No.** Official blog: “This header is not intended for authorization. You should not implement a private API that grants access to your Workers based solely on the `CF-Worker` header matching your domain.” ([Workers live-object bindings](https://blog.cloudflare.com/workers-environment-live-object-bindings/), 2024-04-01). WAF custom rules must not match the header because they run **before** Cloudflare adds it — inbound public/preview callers can supply it. |
| Service-binding HTTP `env.BINDING.fetch()` | Forwards the constructed `Request`. [Service bindings HTTP](https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/http/) | **No caller identity.** Docs do not say the runtime sets `CF-Worker` (or any other unspoofable caller header) on this path. |
| `cf.worker.upstream_zone` | Ruleset-engine field for WAF/Transform, same zone value as `CF-Worker`. | **Not** exposed as a Worker `request` auth signal. |
| `ctx.props` | Caller-set RPC metadata on service-binding RPC. | **Not** platform identity. Current mass-eval uses HTTP `fetch`, not RPC. |
| Absence of `request.cf` | Community observation that service-binding invocations lack eyeball `cf`. | **Guess.** Forbidden. |

Cloudflare staff (2025-07, Cloudflare Developers): there is no native way to tell service-binding invocation from external HTTP; attach a custom secret header instead.

## Unchanged (must stay)

- Public / unauthenticated / preview `fetch` still requires `X-Gateway-Token` matching `GATEWAY_TOKEN`.
- Unbound `GATEWAY_TOKEN` still denies.
- `MASS_EVAL_TOKEN` must never substitute for `GATEWAY_TOKEN` (tests remain).
- No production auth change. No YAML. No COMPLETE. No deploy.

Close later only with a **documented** unspoofable binding signal (or by keeping public `fetch` token-gated and moving the internal path to a binding-only RPC surface that does not invent `CF-Worker` checks). Until then P632B-03 stays HOLD.
