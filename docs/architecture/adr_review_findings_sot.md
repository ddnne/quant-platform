# ADR: Review findings SoT (stop wave-file proliferation)

| Field | Value |
|-------|--------|
| **Status** | **Accepted** |
| **Date** | 2026-08-24 |
| **Supersedes** | Informal practice of minting `docs/reviews/P632_wave*` / Independent A/B/C revisit files as live findings |
| **Related** | [`adr_llm_friendly_refactor.md`](./adr_llm_friendly_refactor.md) (D4 / D11), [`../phase62_residual_status.md`](../phase62_residual_status.md), [`../phase633_finding_ledger.md`](../phase633_finding_ledger.md), [`../reviews/README.md`](../reviews/README.md), [`llm_nav_map.md`](./llm_nav_map.md) |

**Hard constraints (unchanged):** Mass NO-GO · production READY 未宣言 · Phase 7 OFF · invent COMPLETE 禁止 · Projection FRESH 禁止 unless residual + MCP · GO judgment **deferred**.

---

## Context

Phase 6.3.2 review waves wrote a new `P632_waveN_status.md` plus Independent A/B/C revisits at each named SHA. Those files are **dated freezes**, not a queryable ledger. Agents then treated the newest wave file as live SoT and minted another.

`docs/reviews/` stays as an audit trail. This lane does **not** delete historical review files (later lane, after decided rows are copied).

## Decision

| Store | Holds |
|-------|--------|
| **`docs/phase62_residual_status.md`** | Live residual **flags only** (one file) |
| **`docs/phase633_finding_ledger.md`** | Live review **findings** (one file; P0/P1 by Data/PIT, Cloudflare/CI, Architecture/Test, Integration) |
| **`docs/reviews/*.md`** | Historical freezes. Keep. **Do not add** `P632_wave*` or Independent A/B/C revisit files. |
| **`docs/proof/*`** | Dated evidence snapshots — not residual, not the finding ledger |

Wave files under `docs/reviews/` are **historical freezes, not live SoT**. Do not add more.

## Agents must not

- Create `docs/reviews/P632_wave*`
- Create Independent A/B/C revisit files under `docs/reviews/`
- Treat wave / revisit files as live OPEN / FIXED / HOLD SoT
- Declare GO from the finding ledger or from historical reviews
- Duplicate residual flags (COMPLETE counts, last_run, projection, READY) into the finding ledger
- Delete historical review files in this lane

## Consequences

Independent reviewers fill `docs/phase633_finding_ledger.md`. Residual last_run / projection / READY stay MCP-remeasured in the residual file only. `docs/reviews/README.md` points at the live ledger and remains an index of freezes — not a new wave.
