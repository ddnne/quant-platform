# Audit A14 — Git / CI remaining

**Lane:** A14 (CI policy + pre-push)  
**HEAD at remaining-audit:** `03cd1b1`  
**Mass / READY / Phase 7:** NO-GO. `verify_all.sh` is not live deploy.

---

ID: A14-NO-GHA-BY-POLICY  
severity: info (policy HOLD)  
affected: no `.github/`; `README.md`; `docs/architecture.md`; `docs/architecture/adr_llm_friendly_refactor.md` §3.2  
observed fact: Project policy: CI/CD on Cloudflare, **not** GitHub Actions. ADR lists “Adding GitHub Actions CI” as a non-goal.  
root cause: by design.  
why it matters: empty GHA is not a missing pipeline to add.  
structural fix: none. Do not add `.github/workflows`.  
status: HOLD (policy)  

---

ID: A14-VERIFY-ALL  
severity: info  
affected: `scripts/verify_all.sh`; `tests/test_verify_all_script.py`  
observed fact: Pre-push entry exists (`e8e65ee`): pytest + catalog freeze + worker `npm test`. Bans `npm ci --legacy-peer-deps`. No `wrangler deploy`. Missing `.venv` fails closed. Optional `VERIFY_NPM_CI=1`.  
status: FIXED (`e8e65ee`) — was OPEN when the script was missing; do not re-open as “no verify entry”.  

---

ID: A14-WORKERS-DEV  
severity: medium  
affected: all six `platform/workers/*/wrangler.toml`  
observed fact: `workers_dev = true` on `ingestion-jsda`, `ingestion-premium`, `ingestion-secrets`, `quant-ops-mcp`, `research-ai-gateway`, `research-mass-eval`. Production names (`quant-platform-*`) therefore keep `*.workers.dev` routes (ops MCP OAUTH URL is a `workers.dev` host).  
root cause: wrangler default preview subdomain left on for shipped workers.  
why it matters: unauthenticated `workers.dev` surface next to production bindings (D1/R2/AI). Mass/gateway still fail-closed on tokens, but the hostname policy is looser than “custom domain only”.  
structural fix: set `workers_dev = false` where a custom route exists; keep preview explicit in non-prod configs.  
status: OPEN  

---

ID: A14-CHECK-RUNS-0  
severity: info  
affected: GitHub `ddnne/quant-platform` commit `03cd1b1`  
observed fact: Actions workflows **0**. Commit check-runs **0**. `verify_all.sh` is local/pre-push only; Cloudflare deploy is not a GitHub check.  
root cause: A14-NO-GHA-BY-POLICY.  
why it matters: PR merge has no GitHub green check; “CI passed” cannot be read from GitHub. Operators must run `scripts/verify_all.sh`.  
status: observed (not a defect to “add GHA”)  
