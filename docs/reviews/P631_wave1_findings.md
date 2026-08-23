# Phase 6.3.1 Wave-1 findings (implementation-time)

Starting HEAD: `069913c`. Brief review SHA `96264f0` was not frozen.

## P0-A1 eval_loaders production DB

- **severity:** P0
- **affected:** `tests/test_eval_loaders.py`, `eval_loaders_sidecars.py`
- **observed:** loaders default to gitignored `data/structured/ingestion.sqlite`
- **fix:** tmp sqlite fixture (`4cc0a47`)
- **status:** FIXED

## P0-A2 receipt tests mutate production public keys

- **severity:** P0
- **affected:** `tests/test_phase623_receipt_signature.py`, `receipt_crypto.py`
- **observed:** tests wrote `receipt_verify_public_keys.json` in the repo
- **fix:** tmp Ed25519 fixture + `QUANT_RECEIPT_VERIFY_KEYS` (`3e46c97`)
- **status:** FIXED

## P0-A3 ambient HTTP proxy

- **severity:** P1
- **affected:** `ingestion/common/http.py`
- **observed:** `httpx.Client` default `trust_env=True`
- **fix:** default `trust_env=False`; opt-in `QP_HTTP_TRUST_ENV=1`
- **status:** FIXED (this commit)

## P0-B ops-mcp lockfile

- **severity:** P0
- **affected:** `platform/workers/quant-ops-mcp/package-lock.json`
- **observed:** `npm ci` Missing lock entries (`@babel/core`, rolldown, react, …)
- **fix:** regenerated lock without `--legacy-peer-deps` (`992ff41`)
- **status:** FIXED

## P0-C mutation before receipt authority

- **severity:** P0
- **affected:** JSDA archive/corrections + JQ pipeline persist
- **observed:** facts upserted then unsigned `RECOVERED_RAW_ONLY`
- **fix:** verify `SignedReceiptAuthority` before structured register (`5f95b8f`)
- **status:** FIXED

## P0-D duck `bound=True` pilot construct

- **severity:** P0
- **affected:** `phase7_pilot.py`
- **observed:** `SimpleNamespace(bound=True)` satisfied construct; `require_valid()` not called
- **fix:** `74853fa`
- **status:** FIXED

## P0-E raw AI text fallback

- **severity:** P0
- **affected:** `research-ai-gateway`
- **observed:** `extractText` returned raw model string
- **fix:** strict typed artifact only (`ccf486a`)
- **status:** FIXED (Edge DO budget ledger still DEFERRED)

## P0-F manifest before children

- **severity:** P0
- **affected:** mass-eval job R2 writes
- **fix:** children then manifest (`4d0180f`)
- **status:** FIXED (Python CLI PUT remains TOCTOU, not authority)

## Live ops (not invented)

Coverage 22/4 PARTIAL, Projection STALE, B0 UNKNOWN, READY null, applied unpinned.
Phase 6.4 / Phase 7 GO: **NOT COMPLETE / NO-GO**.
