# Coverage baseline — 21 COMPLETE datasets usage notes (2026-08-15)

**Wave:** W47 / w0815an_g3 · T7–T9 usage readiness groundwork  
**Scope:** research usage guidance only  
**Mass / READY / Phase7:** **not** claimed · **not** enabled · **not** declared READY

**Source of list:** remote/catalog residual SoT  
[`docs/phase62_residual_status.md`](../phase62_residual_status.md) (W44 list held through W46; Dataset COMPLETE **21**)  
**CF-SoT (held):** D1 = **hot tip** · R2 = **history** · receipt = **COMPLETE** ownership  
**Logs:** [`.glm-logs/w0815an_g3_usage/`](../../.glm-logs/w0815an_g3_usage/) · switch check [`switch_check.json`](../../.glm-logs/w0815an_g3_usage/switch_check.json)

---

## 1. Dataset COMPLETE list (**21**)

Use these for history research. Names from residual SoT (remote/catalog-aligned; includes `markets_breakdown`).

| # | dataset |
|--:|---------|
| 1 | `derivatives_bars_daily_futures` |
| 2 | `derivatives_bars_daily_options` |
| 3 | `derivatives_bars_daily_options_225` |
| 4 | `edinet_cross_shareholdings` |
| 5 | `edinet_large_volume_shareholders` |
| 6 | `edinet_major_shareholders` |
| 7 | `equities_bars_daily` |
| 8 | `equities_investor_types` |
| 9 | `fins_details` |
| 10 | `fins_dividend` |
| 11 | `fins_summary` |
| 12 | `indices_bars_daily` |
| 13 | `indices_bars_daily_topix` |
| 14 | `jsda_corporate_bond_transactions` |
| 15 | `jsda_tokyo_repo_rates` |
| 16 | `markets_breakdown` |
| 17 | `markets_calendar` |
| 18 | `markets_margin_alert` |
| 19 | `markets_margin_interest` |
| 20 | `markets_short_ratio` |
| 21 | `markets_short_sale_report` |

**Count:** **21** held. Do **not** invent 22.

---

## 2. Research usage notes

| rule | guidance |
|------|----------|
| History research | Prefer the **21 COMPLETE** datasets above for full-history / coverage-complete claims. |
| CF-SoT read path | **D1** = hot tip only · **R2** = history plane · **COMPLETE** is **receipt-owned** (not row-count min/max alone). |
| Segment COMPLETE | A dataset is COMPLETE only when required segments are receipt-sealed COMPLETE under Coverage V2. |
| Tip densify | Tip raw growth is secondary ops signal — **not** a substitute for dataset COMPLETE. |
| Empty COMPLETE | Ban held (**0**). Never treat empty-raw COMPLETE as research-grade. |

### Do **not** use for full-history claims

The following are **permanent DEFER residual PARTIALs** (W44 FINAL lock; densify ban). They are **not** Dataset COMPLETE. Do **not** use them for full-history / all-required-segment claims.

| dataset | permanent DEFER id | note |
|---------|--------------------|------|
| `equities_master` | PD-D2-MASTER | MISDATE + PRE_PLAN residual |
| `equities_earnings_calendar` | PD-D4-EARN-CAL | vendor tip-only history |
| `equities_bars_daily_am` | PD-D4-BARS-AM | tip-only AM |
| `jsda_otc_bond_reference_prices` | PD-D5-JSDA-OTC | tip island COMPLETE only; archive long-tail DEFER (never dataset COMPLETE) |
| `fins_earnings_date` | PD-MX-EARN-TIP | tip holes `2026-01…04` FINAL; not Dataset COMPLETE |

**Permanent DEFER n = 5.** Densify on these classes is **FORBIDDEN** unless residual SoT explicitly re-opens (it has not).

---

## 3. CF-SoT reminder

| plane | role |
|-------|------|
| **D1** | Hot tip (ops / recent publish surface) |
| **R2** | History (raw + cold structured history) |
| **Receipt** | COMPLETE ownership (Coverage V2 segment seals) |

Local SQLite mirrors are **not** Source of Truth. Prefer remote D1/R2 + receipts when making research-facing statements.

---

## 4. Explicit non-claims (this document)

This note is **usage groundwork only**. It does **not**:

- declare Mass Autonomous Research **ON**
- declare production **READY** / B0 **GO**
- declare **Phase7** production ready or enable Phase7
- invent Dataset COMPLETE **22**
- re-open permanent DEFER densify

Live residual remains: Mass **NO-GO** · READY **not** declared · Phase7 **OFF** (foundation stubs only).  
See residual SoT and [`docs/operations/phase7_foundation_off.md`](../operations/phase7_foundation_off.md).

---

## 5. T9 checklist — readiness **not** declared because

Checklist only (no GO language):

- [ ] **Phase7 OFF** — foundation / fail-closed only; no env or flag arms mass research (`PHASE7_*` / enable switches do not exist; switch check OFF)
- [ ] **5 DEFER residual** — permanent DEFER PARTIALs remain (`equities_master`, `equities_earnings_calendar`, `equities_bars_daily_am`, `jsda_otc_bond_reference_prices` archive, `fins_earnings_date` tip4)
- [ ] **Mass NO-GO** — `mass_research` hard-coded / fail-closed; no production READY ≥1 GO

Until residual SoT and an explicit human decision change those three, **do not** declare readiness.

---

## 6. Related artifacts

| artifact | path |
|----------|------|
| Residual SoT | `docs/phase62_residual_status.md` |
| Phase7 foundation OFF (ops) | `docs/operations/phase7_foundation_off.md` |
| Phase7 fail-closed (arch) | `docs/architecture/phase7_fail_closed.md` |
| T8 switch check | `.glm-logs/w0815an_g3_usage/switch_check.json` |
| W44 DEFER lock proof | `docs/proof/w0815ak_w44_defer_lock_20260815.md` |
