# COMPLETE 21 — candidate → approved promotion criteria (draft)

**Wave:** W51 / w0815ar_g2 · T7  
**Phase:** COMPLETE 21 利用準備 (利用品質) — feature governance criteria only  
**Mass / READY / Phase7:** **not** declared · densify **not** run · push **not** this task  
**Promotion this wave:** **none** — all complete21 min features remain `status="candidate"`

**Sources:**

| source | path |
|--------|------|
| Min feature catalog | [`complete21_min_feature_catalog_20260815.md`](complete21_min_feature_catalog_20260815.md) |
| Features contract | [`../features.md`](../features.md) |
| CF read paths + DEFER | [`complete21_cf_read_paths_20260815.md`](complete21_cf_read_paths_20260815.md) |
| Permanent DEFER lock | [`w0815ak_w44_defer_lock_20260815.md`](w0815ak_w44_defer_lock_20260815.md) |
| Code | `packages/research_runtime/features/complete21_min.py` · `dataset_guard.py` · `runtime.py` |
| Residual SoT | [`../phase62_residual_status.md`](../phase62_residual_status.md) |

---

## 0. Purpose and hard non-claims

This document **drafts** the gate criteria for promoting a COMPLETE-21 min feature
from registry `status="candidate"` to `status="approved"` (and thus eligible for
default strategy consumption via `features.get_for_strategy`).

It does **not**:

* promote any feature this wave
* declare production **READY** / Mass **GO** / Phase7 **ON**
* invent Dataset COMPLETE **22**
* re-open densify / tip densify as primary
* treat local SQLite as CF SoT
* waive permanent DEFER exclusion for history loads

Live residual remains: Mass **NO-GO** · READY **not** declared · Phase7 **OFF**.

---

## 1. Lifecycle reminder

| status | meaning | strategy default |
|--------|---------|------------------|
| `candidate` | unvetted / utilization-prep only | **not** admitted by `get_for_strategy` |
| `shadow` | logged / observed, not used for decisions | **not** default |
| `approved` | vetted for strategy-facing consumption | **yes** (role-gated) |
| `retired` | kept for audit only | **no** |

Built-in v0 (`return_1d`, `momentum_n`, `volatility_n`) are already `approved`.  
All `complete21_min` features ship as `candidate` until an explicit promotion wave
satisfies §2–§4 below **and** records a promotion proof (not this document alone).

---

## 2. Input eligibility (hard gates — fail any → no promote)

| # | criterion | evidence |
|--:|-----------|----------|
| I1 | **COMPLETE 21 only** — every declared history dataset is in `COMPLETE_21_DATASETS` | catalog row + module `_*_DATASETS` constants + unit test |
| I2 | **No permanent DEFER 5** — feature never reads `equities_master`, `equities_earnings_calendar`, `equities_bars_daily_am`, `fins_earnings_date`, `jsda_otc_bond_reference_prices` for history | `require_feature_datasets` preflight + `FeatureContext` guards + DEFER poison tests |
| I3 | **PIT hard gate** — all fact reads go through `FeatureContext` / PIT (`available_at <= as_of`); no wall-clock, no raw SQLite in feature modules | `tests/test_features_data_boundary.py` + PIT gate tests per feature |
| I4 | **as_of required** — compute raises `AsOfRequired` without `as_of` | runtime + unit test |
| I5 | **Required inputs enforced** — missing required kwargs raise `MissingInput` before compute body | runtime + unit test |
| I6 | **CF-SoT honesty** — production evaluation path is D1 hot tip / R2 history / receipt-owned COMPLETE; local SQLite is not claimed as SoT | promotion proof cites CF read path for each dataset |

---

## 3. Compute quality (must pass before promotion)

| # | criterion | evidence |
|--:|-----------|----------|
| Q1 | **Determinism** — same `(as_of, inputs, db snapshot)` → same `value` and provenance keys | unit reproducibility test or golden vector |
| Q2 | **Insufficient-history semantics** — returns `FeatureOutput(value=None, metadata.reason=...)` rather than raising when history is short / missing | unit tests (empty / single-obs / zero-denominator cases) |
| Q3 | **PIT lookahead zero** — rows with `available_at > as_of` do not change the value | seeded multi-`available_at` unit tests |
| Q4 | **Formula documented** — catalog formula sketch matches implementation (field names, grain, optional filters) | catalog §2 row + code docstring |
| Q5 | **Provenance** — output metadata includes `feature_id`, `feature_version`, `as_of`, `datasets` (or equivalent), and enough keys to audit the last observation used | unit assert on metadata |
| Q6 | **Price basis** — if price-derived, `price_basis=RAW` declared and echoed in metadata (aligned with v0) | registry + compute metadata |
| Q7 | **Role honesty** — `intended_role` matches real use (`signal` / `state` / `utility` / `structural`); utility flags not promoted as default signals without review | registry field + review note |

---

## 4. Operational / coverage readiness (promotion wave, not this draft)

| # | criterion | note |
|--:|-----------|------|
| O1 | Dataset COMPLETE held for every input (receipt-owned; not PARTIAL/DEFER) | residual SoT + coverage baseline |
| O2 | Tip and/or history smoke on CF path for each input dataset (PIT join) | smoke log under `.glm-logs/` |
| O3 | No promotion while Mass/READY/Phase7 policy forbids strategy default expansion (if so declared) | residual SoT |
| O4 | Version pin plan — consumers pin `(id, version)`; major bump if meaning changes | registry semver |
| O5 | Explicit promotion PR/proof listing feature ids, before/after status, test counts, and residual non-claims | **required artifact** on promotion wave |

---

## 5. Suggested checklist (copy into a future promotion proof)

```text
[ ] I1 COMPLETE 21 only (constants + catalog)
[ ] I2 DEFER 5 fail-closed (preflight + context + tests)
[ ] I3 PIT-only data boundary
[ ] I4 as_of required
[ ] I5 MissingInput for required kwargs
[ ] I6 CF read path documented per dataset
[ ] Q1 deterministic
[ ] Q2 None + reason on insufficient history
[ ] Q3 PIT lookahead tests
[ ] Q4 formula = code
[ ] Q5 provenance metadata
[ ] Q6 price_basis if applicable
[ ] Q7 intended_role reviewed
[ ] O1 coverage held
[ ] O2 CF smoke
[ ] O3 policy allows
[ ] O4 version pin note
[ ] O5 promotion proof committed
[ ] status flipped candidate → approved ONLY after all above
```

---

## 6. Explicitly out of scope for this draft wave (W51 T7)

| item | status |
|------|--------|
| Flip any `complete21_min` feature to `approved` | **not done** |
| Merge `return_1d_c21` into approved v0 `return_1d` | **not done** (parallel export only) |
| READY / Mass / Phase7 | **not** declared / **OFF** |
| densify | **none** |
| push | **not** this task |

### Current candidate inventory (held at draft time)

| feature_id | wave | status |
|------------|------|--------|
| `volume_change_1d` | W49 | candidate |
| `topix_relative_1d` | W49 | candidate |
| `disclosure_flag_fins` | W49 | candidate |
| `margin_interest_change_1d` | W50 | candidate |
| `short_ratio_level` | W50 | candidate |
| `is_trading_day` | W50 | candidate |
| `repo_rate_level` | W50 | candidate |
| `return_1d_c21` | W51 | candidate |
| `margin_alert_flag` | W51 | candidate |
| `futures_activity_proxy` | W51 | candidate |

---

## 7. Related

| artifact | path |
|----------|------|
| Catalog | [`complete21_min_feature_catalog_20260815.md`](complete21_min_feature_catalog_20260815.md) |
| Min features | `packages/research_runtime/features/complete21_min.py` |
| Dataset guard | `packages/research_runtime/features/dataset_guard.py` |
| Tests | `tests/test_complete21_min_features.py` |
| Features contract | [`../features.md`](../features.md) |
