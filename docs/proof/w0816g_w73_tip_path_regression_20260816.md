# W73 / w0816g — tip auto path regression (2026-08-16)

**Wave:** W73 / `w0816g` · Task B  
**Implementer:** GLM5.3 (Grok does not implement)  
**Mass / READY / Phase7:** **NO-GO / not declared / OFF**  
**bars_am history re-probe:** **FORBIDDEN** (W71 LIVE_API_EMPTY · W72 lock)  
**OTC bulk densify:** **FORBIDDEN**  
**empty-raw COMPLETE / invent 23:** **FORBIDDEN**

**Tests:** [`tests/test_tip_auto_path_regression.py`](../../tests/test_tip_auto_path_regression.py)  
**Policy SoT:** [`packages/data_plane/data_contracts/permanent_defer.py`](../../packages/data_plane/data_contracts/permanent_defer.py) `TIP_ONLY_POLICY`  
**Prior path doc:** [`w0816f_w72_tip_auto_collect_path_20260816.md`](w0816f_w72_tip_auto_collect_path_20260816.md)

---

## 1. Tip-only policy forbids history_reprobe (bars_am)

| assertion | result |
|-----------|:------:|
| `is_tip_only_policy(equities_bars_daily_am)` | **true** |
| `history_reprobe` | **FORBIDDEN** |
| `history_densify` | **FORBIDDEN** |
| `history` | **DEFER** |
| `history_reprobe_forbidden(...)` | **true** |
| `history_densify_forbidden(...)` | **true** (W73 helper) |
| reason retains LIVE_API_EMPTY | **yes** |

OTC:

| assertion | result |
|-----------|:------:|
| `bulk_densify` | **FORBIDDEN** |
| `seal_gate` | **FULL_OK** |
| densify/reprobe helpers | **true** (forbidden) |

`TIP_ONLY_POLICY` map size remains **exactly 2** (bars_am + OTC).

---

## 2. Seal/issue path calls aggregate sync

Static AST + source guards (mock not required — call sites present):

| path | `sync_dataset_coverage_from_segments` import | call site |
|------|:--------------------------------------------:|:---------:|
| `scripts/issue_signed_receipts_for_segments.py` | ✓ | ✓ post-refresh |
| `scripts/issue_receipts_parallel.py` | ✓ | ✓ post-refresh |
| `scripts/restore_local_complete_from_receipt.py` | ✓ | ✓ (W70 held) |

Aggregate rules (unchanged W70/W72):

- promotes dataset COMPLETE only when **all** segs COMPLETE  
- never invents / rewrites `coverage_segments`  
- refuses empty COMPLETE  
- safe on tip-only PARTIAL (bars_am 1/31, OTC 93/…) → verify/counts only  

---

## 3. History densify not invoked on tip-only via seal path

Issue/restore scripts:

- **must** call aggregate sync  
- **must not** call `history_reprobe(`, `history_densify(`, `bulk_densify(`, `cf_premium_backfill`, `run_historical_backfill`  
- **must not** import densify/reprobe symbols or backfill planner  

Tip continuous collect remains cron-only:

- premium hourly (`15 * * * *`) for bars_am `date_mode=today`  
- JSDA daily (`30 1 * * *`) for OTC wait FULL_OK  

No history densify queue in this maintain wave.

---

## 4. Path reminder (tip only)

```text
[1 COLLECT tip]  premium cron / JSDA cron  (no history queue)
[2 EVIDENCE]     nz raw + structured
[3 SEAL]         issue_signed / issue_parallel / restore
[4 AGGREGATE]    sync_dataset_coverage_from_segments  ← wired
[5 FRESH]        ops_reeval_freshness.py
```

COMPLETE expand remains **tip-wait** — never invent 23.

---

## 5. Return

| check | result |
|-------|--------|
| bars_am history_reprobe FORBIDDEN | **pass** |
| tip densify FORBIDDEN | **pass** |
| issue→aggregate sync wired | **pass** (static) |
| densify/backfill absent on seal scripts | **pass** |
| invent COMPLETE 23 | **no** |
