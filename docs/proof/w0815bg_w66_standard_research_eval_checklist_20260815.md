# W66 / w0815bg — Standard research evaluation checklist (lock)

**Phase:** 標準研究評価手順の固定（READY 未宣言）  
**Wave:** W66 / w0815bg · 2026-08-15  
**Purpose:** Any new hypothesis must pass this checklist **before** it may be labeled `research_candidate`.  
**Harness entry:** `research.eval_harness.run_standard_research_eval`  
**Code anchors:** `robustness_gate.py` (v2 cost gate) · `eval_harness.py` (multi-year) · `holding_metrics.py` · `baseline_catalog.py`  
**Prior proofs:** W63 multi-year · W64 cost-after · W65 S1–S5 rejected + holding + data-gap

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** (`ready_declared=False`) |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| edge / significance / operational GO | **none** |
| densify / COMPLETE invent | **none** (COMPLETE remains **21**) |
| Mass artifact mass-gen | **none** |
| Gate / checklist pass → READY/Mass/GO | **never auto-connects** |

This document is a **research procedure lock**. Completing the checklist does **not** mint READY, arm Mass, open Phase7, authorize orders, or claim edge.

---

## Purpose

Before any hypothesis is promoted to **`research_candidate`**, it must be evaluated under this standard procedure. The bar exists because short tip-window wins (W57–W58) systematically overstated S1 and related daily-sign hyps; multi-year + cost-after (W63–W64) collapsed those illusions.

**Skip the checklist → not a `research_candidate`.**  
Informal single-window notebooks, tip-only demos, and gross-only soft majority without cost are **insufficient**.

---

## Required steps

### 1. Multi-year **or** non-overlapping multi long periods

| requirement | detail |
|-------------|--------|
| **Required** | Evaluate on **multi-year** windows **or** multiple **non-overlapping long** periods (not a single tip / short window) |
| Preferred API | `design_yearly_eval_windows` + `run_multi_year_s1_eval` / `run_multi_year_extra_hyp_eval` / `run_standard_research_eval` |
| Default years | non-contiguous sample e.g. 2015 / 2017 / 2019 / 2021 / 2023 / 2025 (inventory-aware; gaps OK) |
| Fail-one-year safe | one year skip/error must not invent data or kill the whole batch |
| Short-window-only | **insufficient** for `research_candidate` |

### 2. Cost assumption (default 10bp one-way)

| field | default | note |
|-------|---------|------|
| `one_way_cost` | **0.001 (10bp)** | research-only; 仮定に依存・運用GOではない |
| round-trip illustration | 20bp | not an execution model |
| formula | `net_one_way = gross_signed_mean_active − one_way_cost` | matches `robustness_gate` v2 |
| change | **needs explicit reason** in proof / eval return (`cost_assumption.change_reason`) | silent cost change forbidden |

### 3. Robustness gate with cost (v2) — **required**

| criterion | rule |
|-----------|------|
| `multi_period` | ≥ `min_periods` (default 2) non-skipped periods with metrics |
| `sign_majority` | strict majority of eligible periods share gross sign |
| `not_catastrophic` | no majority-eligible period with \|gross\| > catastrophic threshold |
| **`net_sign_majority`** | **default ON** — majority share same sign of **net** after one-way cost |
| Module | `packages/product/research/robustness_gate.py` · `GATE_VERSION = research-robustness-gate/v2` |
| Pass meaning | research checklist only — **pass ≠ READY / Mass / GO** |

Gross-only soft PASS is **not** enough when the cost gate is on (W64 lesson: S1 gross PASS → cost FAIL).

### 4. Explicit data-gap disclosure — **required**

| requirement | detail |
|-------------|--------|
| **Required** | Every eval result must disclose known data gaps that affect the hyp (empty years, archive fallbacks, s4_eligible false, short_ratio gaps, etc.) |
| Sources | `design_yearly_eval_windows` → `coverage_notes`; W65 data-gap inventory; caller `data_gap_notes` |
| Honesty | gap years **skipped** or marked empty_allowed — **never densify / invent** |
| Examples | topix JSONL gap 2024–2025 (archive) · margin 2024 empty · calendar tip/archive PIT · short_ratio 2024–2025 |

### 5. Holding / turnover metrics — **recommended**

| item | detail |
|------|--------|
| Module | `packages/product/research/holding_metrics.py` |
| What | sign run-length distribution · turnover proxy · cost amortization illustration |
| Label | 仮定に依存・研究用・未宣言 |
| Why recommend | daily-sign hyps often re-trade every day; cost amortization clarifies residual scale |

Not a hard fail of the checklist if omitted, but should be present for daily-sign style hyps before candidate discussion.

### 6. Pass does **not** connect READY / Mass / GO — **required**

| freeze | value after any checklist outcome |
|--------|-----------------------------------|
| `ready_declared` | **False** |
| `mass_research` | **NO-GO** |
| `phase7` | **OFF** |
| `operational_go` | **False** |
| `connected_to_ready` / `connected_to_mass` | **False** |
| `edge_claimed` / `significance_claimed` | **False** |

Even if `robustness_gate.passed is True`, the hyp is **not** automatically `research_candidate`, READY, or Mass. Candidate status is a **separate** research documentation decision that still cannot arm Mass/READY from this plane.

---

## Results that skip the checklist

| outcome | status |
|---------|--------|
| Tip-only / short single window | **NOT** `research_candidate` |
| Multi-period without multi-year **or** non-overlapping long periods | **NOT** `research_candidate` |
| Gross-only majority without cost-aware v2 gate | **NOT** `research_candidate` |
| Cost assumption changed without reason | **invalid** procedure |
| Data gaps hidden / densified | **invalid** procedure |
| Gate pass used to claim READY/Mass/GO | **forbidden** |

---

## Failed examples: S1–S5 (`research_baseline_rejected`)

S1–S5 simple daily sign baselines **failed this bar** (or never completed multi-year cost-aware evaluation) and are fixed as **`research_baseline_rejected`** in the research-only catalog.

| id | signal_id | why it fails the standard bar |
|----|-----------|-------------------------------|
| **S1** | `c21_topix_relative_sign` | W63 multi-year gross soft PASS → **W64 cost-aware FAIL** (net +3/−3); tip overstated |
| **S2** | `c21_volume_change_sign` | tip gross −; multi-period fire-rate unstable; **no** multi-year cost campaign |
| **S3** | `c21_topix_rel_disclosure_filter` | S1-dependent; multi-period unstable after cost; **no** independent multi-year rescue |
| **S4** | `c21_margin_change_sign` | multi-year cost soft PASS (all −) but **weak magnitude** → explicit non-candidate |
| **S5** | `c21_short_ratio_delta_sign` | multi-period FAIL; inventory gaps; **never** multi-year cost-robust |

**Catalog:** `packages/product/research/baseline_catalog.py`  
**Proofs:**

- [`w0815bf_w65_simple_daily_sign_baselines_rejected_20260815.md`](w0815bf_w65_simple_daily_sign_baselines_rejected_20260815.md)
- [`w0815bf_w65_baseline_close_20260815.md`](w0815bf_w65_baseline_close_20260815.md)
- [`w0815be_w64_cost_multi_year_eval_20260815.md`](w0815be_w64_cost_multi_year_eval_20260815.md)
- [`w0815bd_w63_multi_year_eval_20260815.md`](w0815bd_w63_multi_year_eval_20260815.md)

These remain **rejected baselines** for dry demonstration of the harness. They must **not** be un-rejected by this wave.

---

## Default harness entry (future hyps)

```python
from research.eval_harness import run_standard_research_eval

# Wiring-only (no heavy R2): validates checklist surface + freezes
out = run_standard_research_eval(dry_run=True)
assert out["ready_declared"] is False
assert out["mass_research"] == "NO-GO"
assert out["phase7"] == "OFF"
assert out["research_candidate"] is False  # this entry never auto-promotes

# Full multi-year S1 path is a rejected-baseline dry demo only (not a new signal)
# Provide designed periods + R2/D1 fixtures as with run_multi_year_s1_eval.
```

| rule | held |
|------|------|
| Default entry | `run_standard_research_eval` |
| Short-window-only | insufficient |
| New signals | **not** invented by this entry |
| S1 re-run | allowed only as **rejected baseline** demonstration |
| Candidate promotion | **out of band** (docs); never READY/Mass arm |

Proof of harness entry: [`w0815bg_w66_standard_eval_harness_entry_20260815.md`](w0815bg_w66_standard_eval_harness_entry_20260815.md).

---

## Freeze flags (checklist return must include)

```text
mass_research      = "NO-GO"
phase7             = "OFF"
ready_declared     = False
operational_go     = False
connected_to_ready = False
connected_to_mass  = False
edge_claimed       = False
significance_claimed = False
research_candidate = False   # auto-promotion forbidden from harness
densify            = False
```

---

## Non-goals (this wave)

- no new daily sign signals  
- no S1–S5 un-reject  
- no READY / Mass / Phase7 ON  
- no densify / COMPLETE invent  
- no mass artifacts  
- no edge claims  

---

## Related

| artifact | path |
|----------|------|
| Gate v2 | `packages/product/research/robustness_gate.py` |
| Multi-year eval | `run_multi_year_s1_eval` / `run_multi_year_extra_hyp_eval` in `eval_harness.py` |
| Standard entry | `run_standard_research_eval` in `eval_harness.py` |
| Holding metrics | `packages/product/research/holding_metrics.py` |
| Rejected catalog | `packages/product/research/baseline_catalog.py` |
| Data-gap priority | [`w0815bf_w65_data_gap_priority_20260815.md`](w0815bf_w65_data_gap_priority_20260815.md) |
