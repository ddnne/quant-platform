> **Historical snapshot** — not current residual SoT.
> Current residual: [phase62_residual_status.md](phase62_residual_status.md).
> Mass / READY / Phase7: **NO-GO / OFF** unless residual says otherwise.

# Phase 6.2.3 Evidence Integrity & Sync Closure — Status

**HEAD:** see `git log -1` after land  
**Developer:** Grok (GLM rate-limited / OAuth unavailable)  
**Independent GLM review:** **NOT done** — do not treat as GLM-approved or “P0 unresolved=0”

## Honest labels (pre/post)

| Topic | Honest status |
|-------|----------------|
| Receipt authority | **Ed25519 foundation** (signed COMPLETE); not yet full runtime isolation of private key process |
| JSDA structured | **staging path** `PARSED_STAGING_ONLY`; final fact-table adapters still foundation |
| Projection | **generation-aware metadata** (`active_generation`, age from request time, `DEGRADED_MIXED_GENERATION`) |
| Mass research | **NO-GO** |
| Operational closure | **NO-GO** (backfill + sync evidence still live) |

## P0 landed (code)

1. **Signed receipts** (`storage/receipt_crypto.py`, `SignedReceiptAuthority`)
   - COMPLETE requires valid Ed25519 over canonical body
   - string `issuer_class` / `issuer_id` alone rejected
   - `mint_ingestion_issuer()` removed from public path
   - `emit_segment_receipt` requires authority (no auto-mint)
2. **JSDA r2_parse** no longer issues false COMPLETE; staging only
3. **ResearchReadiness** bound to READY verifier path; operator override cannot substitute
4. **BackfillPlanner** segment_id = `YYYY-MM` (Coverage identity); `backfill_status_rows` returns 26
5. **Projection meta v3** generation + honest age + mixed-generation state
6. **AgentCapabilityRouter** rename (honest: not OS sandbox)

## Still open (live / further code)

| Item | Notes |
|------|--------|
| JQ structured+receipt same TX full pipeline | foundation; Worker path still separate |
| D1→local applied cursor non-null for 23 | live ops |
| Projection atomic multi-table switch on D1 | partial (meta only) |
| JSDA source-specific final adapters | foundation |
| Real container sandbox | not implemented |
| Independent GLM review | required before any GO claim |

## Mass research GO

**NO-GO.** Attestation + signed receipts + live COMPLETE all required; none of live gates closed.

## Commands

```bash
# Verify public keys + signing (local)
python -c "from storage.receipt_crypto import load_signing_key, load_verify_keys; print(load_signing_key().key_id, list(load_verify_keys()))"

# Backfill status 26 rows
python -c "from ops.backfill_planner import backfill_status_rows; print(len(backfill_status_rows()), backfill_status_rows()[:3])"
```

## Remainder land (same phase, follow-up)

- JQ pipeline: signed receipt required for governed success; receipt fail fails run
- JSDA source-specific adapters module (`ingestion/jsda/adapters.py`)
- Paper authorization binds ready_snapshot_id / period / universe / expiry
- Gateway nested banned-key scan + pre-call budget reserve/reconcile
- MCP `sync_status` exposes per-dataset export cursor, lag, null counts
- JSDA worker: timing-safe token compare, 32MiB artifact cap, bounded body read

Still NO-GO for mass research; GLM independent review still required.

## Code-complete inventory (implementable scope)

Closed in code:
- Signed Ed25519 receipts + pipeline fail-closed
- JSDA staging-only + adapters + durable job queue (bounded cron drain)
- Projection generation pointer + active generation filter in MCP
- ProcessIsolatedRunner foundation (not CF container sandbox)
- Paper snapshot/period binding, gateway nested ban + reserve
- sync_status lag/cursors

Explicitly NOT closed (not forgeable / not claimed):
- Live 26/26 COMPLETE + READY mint + AM SLA evidence
- Full Cloudflare Queues/Workflow productization
- OS/container non-circumventable agent sandbox
- Independent GLM review → never claim P0 unresolved=0 without it
- Mass research GO
