# W52 / w0815as_g1 — candidate → approved feature promotion eval (2026-08-15)

**Wave:** W52 / w0815as_g1 · T1–T4  
**Phase:** COMPLETE 21 利用品質 — feature governance promotion (max **2**)  
**Mass / READY / Phase7:** still **NO-GO / not declared / OFF**  
**densify:** **none** · tip densify **not** run · push **not** this task (G4)  
**Criteria SoT:** [`complete21_feature_candidate_to_approved_criteria_20260815.md`](complete21_feature_candidate_to_approved_criteria_20260815.md) (I1–I6 / Q1–Q7 / O1–O5)

**Promotion result:** **2** approved · **8** remain candidate  
| promoted | version pin | intended_role | note |
|----------|-------------|---------------|------|
| `is_trading_day` | **1.0.0** | utility | strongest utility; calendar COMPLETE; W51 E2E 11/11 |
| `volume_change_1d` | **1.0.0** | signal | W51 E2E live; single-dataset; seeded + insufficient tests |

**Not promoted (8):** `topix_relative_1d` · `disclosure_flag_fins` · `margin_interest_change_1d` · `short_ratio_level` · `repo_rate_level` · `return_1d_c21` · `margin_alert_flag` · `futures_activity_proxy` — see §5.

---

## 0. Scope and hard non-claims

This proof:

* evaluates all **10** complete21 min features against I\* / Q\* / O\*
* promotes **at most 2** that **clearly** pass hard gates + quality + O2 smoke
* pins promoted versions at **1.0.0** (no formula change)
* does **not** declare READY / Mass GO / Phase7 ON
* does **not** densify, invent Dataset COMPLETE 22, or force promotion of weak candidates
* does **not** merge `return_1d_c21` into v0 `return_1d`

Code / catalog / tests updated this wave:

| artifact | path |
|----------|------|
| Registry | `packages/research_runtime/features/complete21_min.py` |
| Catalog | [`complete21_min_feature_catalog_20260815.md`](complete21_min_feature_catalog_20260815.md) |
| Tip path status | `packages/product/research/single_shot_job.py` |
| Tests | `tests/test_complete21_min_features.py` · `tests/test_single_shot_research_job.py` |
| Criteria | [`complete21_feature_candidate_to_approved_criteria_20260815.md`](complete21_feature_candidate_to_approved_criteria_20260815.md) |
| CF read paths | [`complete21_cf_read_paths_20260815.md`](complete21_cf_read_paths_20260815.md) |
| Residual SoT | [`../phase62_residual_status.md`](../phase62_residual_status.md) |

---

## 1. Evidence inventory (W48–W51 + residual)

| source | role |
|--------|------|
| W48 CF read paths + DEFER | I1/I2/I6 foundation · [`.glm-logs/w0815ao_g2_smoke/`](../../.glm-logs/w0815ao_g2_smoke/) T4 bars×calendar · T5 bars×fins · T6 bars×TOPIX |
| W49 deepen smokes | [`.glm-logs/w0815ap_g1_smoke/`](../../.glm-logs/w0815ap_g1_smoke/) T1 bars×margin_interest · T3 bars×repo |
| W50 usage E2E | [`.glm-logs/w0815aq_g1_e2e/`](../../.glm-logs/w0815aq_g1_e2e/) · DEFER fail-closed |
| W51 feature E2E | [`.glm-logs/w0815ar_g1_e2e/summary.json`](../../.glm-logs/w0815ar_g1_e2e/summary.json) · tip FeatureContext → **volume_change_1d** · **is_trading_day** · **topix_relative_1d** → R2 |
| W51 smokes expand | [`.glm-logs/w0815ar_g3_smoke/smoke_results.json`](../../.glm-logs/w0815ar_g3_smoke/smoke_results.json) T8a bars×margin_alert · T8b bars×breakdown |
| Unit tests | `tests/test_complete21_min_features.py` (~48+) · DEFER / as_of / MissingInput / PIT / seeded |
| Dataset COMPLETE **21** | residual SoT · **actionable_gap=0** · permanent DEFER **5** only |

### W51 E2E live feature smoke (O2 primary for default tip set)

Job `w0815ar-g1-e2e` · tip `2026-08-01`…`2026-08-15` · as_of `2026-08-15T15:30:00+09:00` · codes `13010`, `72030`

| feature_id | version | computed | non_null | null | sample |
|------------|---------|---------:|---------:|-----:|--------|
| `volume_change_1d` | 1.0.0 | 2 | 2 | 0 | 13010 ≈ −0.268 · 72030 ≈ −0.044 |
| `is_trading_day` | 1.0.0 | 11 | 11 | 0 | 2026-08-01=0 · 2026-08-03=1 … |
| `topix_relative_1d` | 1.0.0 | 2 | 2 | 0 | 13010 ≈ −0.0085 · 72030 ≈ −0.0060 |

Tip input rows: `equities_bars_daily` **26671** · `markets_calendar` **11** · `indices_bars_daily_topix` **6**.

---

## 2. Shared hard-gate baseline (all 10)

| gate | result | evidence |
|------|--------|----------|
| **I1** COMPLETE 21 only | **PASS** (all 10) | `_*_DATASETS` constants ⊆ `COMPLETE_21_DATASETS` · `test_new_feature_dataset_constants_are_complete_only` |
| **I2** No permanent DEFER 5 | **PASS** (all 10) | `require_feature_datasets` preflight · FeatureContext guards · DEFER poison tests · W51 live DEFER reject |
| **I3** PIT hard gate | **PASS** (all 10) | facts only via `FeatureContext` / PIT · `tests/test_features_data_boundary.py` + feature PIT multi-`available_at` tests (margin/disclosure/short/alert/futures) · bars/calendar via runtime PIT |
| **I4** as_of required | **PASS** (all 10) | runtime `AsOfRequired` · `test_complete21_min_requires_as_of` (sample) + universal compute path |
| **I5** Required inputs | **PASS** (all 10) | parametrized MissingInput for kwargs-required features · empty required_kwargs for calendar/repo/futures is intentional |
| **I6** CF-SoT honesty | **PASS** (all 10) | CF read paths doc · tip path `plane=D1_hot_tip` · `local_sot=false` · local SQLite not claimed SoT |
| **O1** Dataset COMPLETE held | **PASS** (all 10 inputs) | residual COMPLETE **21** · every declared dataset in COMPLETE list |
| **O3** Policy | **PASS** (narrow) | feature `approved` ≠ Mass/READY/Phase7 ON · residual holds NO-GO/OFF · promotion does not arm strategy mass path |
| **O4** Version pin | **PASS** for promoted | pin **1.0.0**; major bump if meaning changes |
| **O5** Promotion proof | **this document** | required artifact |

Legend used below: **Y** = clearly pass · **~** = partial / weaker evidence · **N** = fail or not clear enough for promote.

---

## 3. Per-feature evaluation matrix

### 3.1 Summary matrix

| feature_id | I1–I6 | Q1 | Q2 | Q3 | Q4 | Q5 | Q6 | Q7 | O2 smoke | promote? |
|------------|-------|----|----|----|----|----|----|----|----------|----------|
| **`is_trading_day`** | Y | Y | Y | Y | Y | Y | n/a | Y utility | **Y** W51 E2E 11/11 + W48 T4 calendar | **YES** |
| **`volume_change_1d`** | Y | Y | Y | Y\* | Y | Y | n/a | Y signal | **Y** W51 E2E 2/2 + bars COMPLETE | **YES** |
| `topix_relative_1d` | Y | Y | Y | ~ | Y | Y | Y RAW | Y signal | Y W51 E2E but weaker unit integrate | **no** (slot filled; dual-leg unit gap) |
| `disclosure_flag_fins` | Y | Y | Y | Y | Y | Y | n/a | Y | ~ W48 T5 dataset only | **no** (no feature-level CF E2E) |
| `margin_interest_change_1d` | Y | Y | Y | Y | Y | Y | n/a | Y | ~ W49 T1 join only | **no** (no feature-level CF E2E) |
| `short_ratio_level` | Y | Y | Y | Y | Y | Y | n/a | Y | ~ dataset COMPLETE only | **no** (no tip default path; needs `section`) |
| `repo_rate_level` | Y | Y | Y | ~ | Y | Y | n/a | Y state | ~ W49 T3 join only | **no** (no feature-level CF E2E) |
| `return_1d_c21` | Y | Y | Y | Y\* | Y | Y | Y RAW | Y | ~ bars path only | **no** (twin of approved v0 `return_1d`; keep candidate export) |
| `margin_alert_flag` | Y | Y | Y | Y | Y | Y | n/a | Y | ~ W51 T8a join only | **no** (flag sparse; no feature E2E) |
| `futures_activity_proxy` | Y | Y | Y | Y | Y | Y | n/a | Y state | ~ dataset COMPLETE only | **no** (no feature-level CF E2E) |

\*Q3 for bars-path features: runtime PIT + v0 bars discipline; dedicated multi-`available_at` unit tests exist for margin/disclosure/short/futures families, not a separate volume-specific seed (acceptable for promote given universal PIT gate).

### 3.2 Promoted detail

#### `is_trading_day` → **approved** @ **1.0.0**

| gate | verdict | evidence |
|------|---------|----------|
| I1–I6 | **Y** | `_CALENDAR_DATASETS=("markets_calendar",)` COMPLETE · DEFER poison · PIT via `get_market_calendar` · as_of required · no required kwargs · CF path §2.1 markets_calendar |
| Q1 | **Y** | pure `is_trading_day_from_division` + deterministic calendar read |
| Q2 | **Y** | missing row → `None` + reason; non-trading division → `0.0` |
| Q3 | **Y** | calendar rows gated by `available_at` through FeatureContext |
| Q4 | **Y** | catalog: holiday_division=="1" ↔ code |
| Q5 | **Y** | runtime injects feature_id/version/as_of; meta has date/datasets/rows_seen |
| Q6 | n/a | not price-derived |
| Q7 | **Y** | `intended_role=utility` honest — **not** default strategy signal |
| O1–O2 | **Y** | markets_calendar COMPLETE · W51 E2E 11/11 · W48 bars×calendar smoke |
| O4 | **Y** | pin **1.0.0** |

**`get_for_strategy`:** default **rejects** (utility role). Explicit:

```python
get_for_strategy(
    "is_trading_day",
    version="1.0.0",
    allowed_roles=("utility", "signal", "state", "structural"),
)
```

#### `volume_change_1d` → **approved** @ **1.0.0**

| gate | verdict | evidence |
|------|---------|----------|
| I1–I6 | **Y** | `_VOLUME_DATASETS=("equities_bars_daily",)` · DEFER preflight · PIT bars · as_of · MissingInput `code` · CF bars path |
| Q1 | **Y** | pure `volume_change_from_pairs` + seeded compute 0.0 on constant volume |
| Q2 | **Y** | insufficient history / zero prior volume → `None` + reason |
| Q3 | **Y\*** | bars via `get_equity_bars_daily` PIT (same path as approved v0 return) |
| Q4 | **Y** | (V_t−V_{t−1})/V_{t−1} matches code |
| Q5 | **Y** | feature_id/datasets/prior_date/last_volume provenance |
| Q6 | n/a | volume, not price (`price_basis=None`) |
| Q7 | **Y** | intended_role=`signal` |
| O1–O2 | **Y** | bars COMPLETE · W51 E2E live values non-null · tip 26671 rows |
| O4 | **Y** | pin **1.0.0** |

**`get_for_strategy`:** default **admits** (`approved` + `signal`).

```python
get_for_strategy("volume_change_1d", version="1.0.0")
# → FeatureDefinition status=approved, version=1.0.0
```

---

## 4. Checklist for promoted features

### `is_trading_day`

```text
[x] I1 COMPLETE 21 only (constants + catalog)
[x] I2 DEFER 5 fail-closed (preflight + context + tests)
[x] I3 PIT-only data boundary
[x] I4 as_of required
[x] I5 MissingInput N/A (no required kwargs)
[x] I6 CF read path documented (markets_calendar)
[x] Q1 deterministic
[x] Q2 None + reason on insufficient history
[x] Q3 PIT lookahead (calendar available_at)
[x] Q4 formula = code
[x] Q5 provenance metadata
[x] Q6 price_basis n/a
[x] Q7 intended_role reviewed (utility)
[x] O1 coverage held
[x] O2 CF smoke (W51 E2E + W48 T4)
[x] O3 policy allows narrow feature approve
[x] O4 version pin 1.0.0
[x] O5 this promotion proof
[x] status flipped candidate → approved
```

### `volume_change_1d`

```text
[x] I1–I6 as above (equities_bars_daily)
[x] Q1–Q5, Q7
[x] Q6 n/a (volume)
[x] O1–O5
[x] status flipped candidate → approved · pin 1.0.0
```

---

## 5. Non-promoted — fail / defer reasons (T3)

| feature_id | primary blocker | detail |
|------------|-----------------|--------|
| `topix_relative_1d` | **slot + unit depth** | W51 E2E live **pass**, but no positive seeded dual-leg integration unit test (only DEFER poison + helpers). Dual-dataset relative harder to audit than volume. Prefer volume for 2nd slot. Revisit next wave with dedicated seeded TOPIX unit + multi-avail Q3. |
| `disclosure_flag_fins` | **O2 weak** | Unit empty→0 + PIT disclosure gate **Y**; no feature-level tip E2E compute. Only W48 bars×fins **dataset** join smoke. |
| `margin_interest_change_1d` | **O2 weak** | Strong unit (seeded + insufficient + PIT multi-avail); only W49 join smoke, not feature E2E on CF tip. |
| `short_ratio_level` | **O2 + tip path** | Needs `section` (not in default tip feature path); no CF feature smoke. Dataset COMPLETE only. |
| `repo_rate_level` | **O2 weak** | Unit seeded + empty; W49 bars×repo join only; no feature E2E values on tip. |
| `return_1d_c21` | **product policy** | Parallel export of approved v0 `return_1d` on complete21 path. Criteria + catalog: **do not merge / do not promote as second approved return**. Stays candidate twin for path comparison. |
| `margin_alert_flag` | **O2 weak + sparsity** | Unit + PIT ok; W51 T8a is bars×alert join not feature compute E2E; sparse alerts per code. |
| `futures_activity_proxy` | **O2 weak** | Unit + PIT ok; no tip feature E2E; derivatives volume proxy needs more ops smoke. |

**Hard rule held:** no force-promote. Max **2**. Prefer clear O2 feature-level smoke + full Q\*.

---

## 6. Registry / governance after flip (T4)

| feature_id | before | after | version pin |
|------------|--------|-------|-------------|
| `is_trading_day` | candidate | **approved** | **1.0.0** |
| `volume_change_1d` | candidate | **approved** | **1.0.0** |
| (8 others) | candidate | candidate | 1.0.0 |

### `get_for_strategy` contract (tests)

| call | expected |
|------|----------|
| `get_for_strategy("volume_change_1d", version="1.0.0")` | **admits** |
| `get_for_strategy("is_trading_day", version="1.0.0")` | **FeatureGovernanceError** (utility) |
| `get_for_strategy("is_trading_day", version="1.0.0", allowed_roles=(…,"utility",…))` | **admits** |
| `get_for_strategy("topix_relative_1d")` | **FeatureGovernanceError** (candidate) |
| `get_for_strategy("return_1d")` | **admits** (v0, unchanged) |

### Tip single_shot path

* `DEFAULT_CANDIDATE_FEATURES` name retained (default tip set).
* Per-feature `status` now mirrors registry (approved / candidate).
* Overall features artifact `status` may be `mixed` when default set spans both tiers.
* `ready_declared` remains **false** · Mass **NO-GO** · Phase7 **OFF**.

---

## 7. Explicit non-declarations (held)

- **READY** — not declared
- **Mass Autonomous Research** — **NO-GO / OFF**
- **Phase7** — **OFF**
- **densify / tip densify** — none / not this task
- **Dataset COMPLETE 22** — forbidden
- **push** — not this task (G4)
- **Force promotion** of remaining 8 — **no**
- **Merge** `return_1d_c21` into v0 `return_1d` — **no**

---

## 8. Related

| artifact | path |
|----------|------|
| Criteria | [`complete21_feature_candidate_to_approved_criteria_20260815.md`](complete21_feature_candidate_to_approved_criteria_20260815.md) |
| Catalog | [`complete21_min_feature_catalog_20260815.md`](complete21_min_feature_catalog_20260815.md) |
| W51 feature E2E close | [`w0815ar_w51_feature_e2e_close_20260815.md`](w0815ar_w51_feature_e2e_close_20260815.md) |
| Min features code | `packages/research_runtime/features/complete21_min.py` |
| Registry governance | `packages/research_runtime/features/registry.py` (`get_for_strategy`) |
| Tests | `tests/test_complete21_min_features.py` |
