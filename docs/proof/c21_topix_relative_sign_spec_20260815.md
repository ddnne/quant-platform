# Fixed signal spec — `c21_topix_relative_sign` (2026-08-15)

**Wave:** W53 / w0815at_g2 · T5 (freeze)  
**Code module:** `packages/research_runtime/features/minimal_signal.py`  
**Consumer path:** `packages/product/research/single_shot_job.py` (`compute_signals=True`)  
**Prior E2E:** [`w0815as_w52_signal_e2e_20260815.md`](w0815as_w52_signal_e2e_20260815.md) (job `w0815as-g2-signal-e2e`)  
**Second E2E:** [`w0815at_w53_signal_e2e_20260815.md`](w0815at_w53_signal_e2e_20260815.md)

**Mass / Phase7:** **NO-GO / OFF** (held · not armed)  
**READY:** **not** declared  
**Order execution:** **none**  
**densify / invent COMPLETE 22 / push:** **out of scope**

This document freezes the **research signal contract** as implemented. It does **not** promote the signal beyond `candidate`, arm Mass/Phase7, mint READY, or connect order routing.

---

## 1. Identity (frozen)

| field | value |
|-------|-------|
| **signal_id** | `c21_topix_relative_sign` |
| **version** | `1.0.0` |
| **status** | `candidate` |
| **candidate_only** | **true** |
| **artifact surface** | R2 `quant-structured` · `research/single_shot/job={id}/signals/{content_hash}.json` |

### Why `candidate_only=True`

The **primary** leg `topix_relative_1d` remains registry **candidate** (W52 G1 promoted only `is_trading_day` + `volume_change_1d`). The overall signal therefore stays candidate-only even though filter/gate prefer approved features. No strategy-default / READY claim.

---

## 2. Inputs

### 2.1 Feature legs

| role | feature_id | registry status (pin) | version pin | role in signal |
|------|------------|----------------------|-------------|----------------|
| **primary** | `topix_relative_1d` | **candidate** | 1.0.0 | `sign(·)` → +1 / 0 / −1 |
| **filter** | `is_trading_day` | **approved** (W52 G1) | 1.0.0 | non-trading or missing → `value=None` |
| **gate** | `volume_change_1d` | **approved** (W52 G1) | 1.0.0 | optional `\|·\| >= abs_min`; default **disabled** |

Feature catalog: [`complete21_min_feature_catalog_20260815.md`](complete21_min_feature_catalog_20260815.md).  
Promotion eval: [`w0815as_w52_feature_promotion_eval_20260815.md`](w0815as_w52_feature_promotion_eval_20260815.md).

### 2.2 Dataset inputs (COMPLETE 21 subset only)

| dataset | use |
|---------|-----|
| `equities_bars_daily` | equity returns + volume for primary / gate |
| `markets_calendar` | trading-day filter |
| `indices_bars_daily_topix` | TOPIX leg of relative return |

**Forbidden inputs:** permanent DEFER 5 (`equities_master`, `equities_earnings_calendar`, `equities_bars_daily_am`, `fins_earnings_date`, `jsda_otc_bond_reference_prices`) — fail-closed via `data_contracts.permanent_defer` before D1.

**Count constraint:** residual Dataset COMPLETE **21** held. Do **not** invent COMPLETE **22**.

### 2.3 Read plane

| item | contract |
|------|----------|
| Tip read | remote D1 `quant-ingest` · `jquants_records` · date-bounded tip window |
| FeatureContext | tip in-memory · **not** local SQLite SoT |
| History SoT | R2 (not re-materialized by this signal path) |
| densify / tip collect as primary | **not** this signal |

---

## 3. Formula and thresholds

### 3.1 Formula (canonical)

```text
value = sign(topix_relative_1d)
  if is_trading_day == 1.0
  and (volume_change_abs_min is None or |volume_change_1d| >= abs_min)
  else None
```

Where:

```text
sign(x) =
  +1.0  if x > 0
   0.0  if x == 0
  -1.0  if x < 0
  None  if x is missing / non-numeric
```

### 3.2 Thresholds / defaults (frozen)

| parameter | default | meaning |
|-----------|---------|---------|
| `volume_change_abs_min` | **`None`** | volume gate **off** (sign + trading-day only) |
| trading-day pass | `is_trading_day == 1.0` | strict equality on float 1.0 |
| missing filter | `is_trading_day is None` or non-numeric | → `value=None` |
| missing primary | `topix_relative_1d is None` | → `value=None` |
| missing gate (when enabled) | `volume_change_1d is None` | → `value=None` |
| gate fail (when enabled) | `|volume_change_1d| < abs_min` | → `value=None` |

Code constants:

| constant | value |
|----------|-------|
| `DEFAULT_VOLUME_CHANGE_ABS_MIN` | `None` |
| `PRIMARY_FEATURE_ID` | `topix_relative_1d` |
| `FILTER_FEATURE_ID` | `is_trading_day` |
| `GATE_FEATURE_ID` | `volume_change_1d` |

### 3.3 Discrete value domain

| value | interpretation |
|------:|----------------|
| `+1.0` | long (equity outperformance vs TOPIX on as_of day) |
| `0.0` | flat relative |
| `-1.0` | short (underperformance) |
| `None` | filtered / gated / missing input (not a trade signal) |

---

## 4. Observation and artifact shape

### 4.1 Per-code observation (logical)

```json
{
  "signal_id": "c21_topix_relative_sign",
  "version": "1.0.0",
  "status": "candidate",
  "candidate_only": true,
  "value": -1.0,
  "code": "13010",
  "date": "2026-08-10",
  "as_of": "2026-08-10T15:30:00+09:00",
  "metadata": {
    "primary_feature_id": "topix_relative_1d",
    "filter_feature_id": "is_trading_day",
    "gate_feature_id": "volume_change_1d",
    "topix_relative": -0.00847,
    "raw_sign": -1.0,
    "filter": {"filter": "is_trading_day", "passed": true, "is_trading_day": 1.0},
    "gate": {"gate": "volume_change_1d", "enabled": false, "passed": true},
    "mass_research": "NO-GO",
    "phase7": "OFF",
    "ready_declared": false,
    "order_execution": false
  }
}
```

### 4.2 Aggregate signal artifact (R2 `…/signals/`)

| field | notes |
|-------|-------|
| `version` | `minimal-signal/v1` (payload schema) |
| `signal_id` / `signal_version` / `status` / `candidate_only` | frozen identity |
| `as_of` | feature/signal as_of timestamp |
| `feature_ids` | primary · filter · gate |
| `volume_change_abs_min` | threshold used (default null) |
| `codes` | codes with primary/gate feature values present |
| `row_counts` | `computed` · `non_null` · `null` · `long` · `short` · `flat` |
| `observations` | per-code records |
| `mass_research` / `phase7` / `ready_declared` / `order_execution` / `local_sot` | freeze surface |

### 4.3 single_shot write keys

When `compute_signals=True`, job writes (bucket `quant-structured`):

| key | content |
|-----|---------|
| `research/single_shot/job={id}/input_plan.json` | planned datasets / window |
| `…/result/{content_hash}.json` | tip summary + execution metadata |
| `…/features/{content_hash}.json` | tip candidate feature observations |
| `…/signals/{content_hash}.json` | **this signal** aggregate |
| `…/manifest.json` | keys + freeze + `signal{}` block |

---

## 5. Scope: Mass / READY / order — **non-connect**

Hard closed (code freeze + AST guards + live metadata):

| surface | held value | meaning |
|---------|------------|---------|
| `mass_research` | **NO-GO** | mass loop **not** connected; no `agents.mass_research` import |
| `phase7` | **OFF** | foundation only; no arming switches |
| `ready_declared` | **false** | no READY mint / no `VerifiedResearchReadiness` |
| `ready_publication` | **OFF** | no READY publication path |
| `order_execution` | **false** | no `OrderIntent` / paper place/submit |
| `local_sot` | **false** | tip FeatureContext only; local FS not SoT |
| `connected_to_mass_research_loop` | **false** | single_shot skeleton only |

**Not in scope for this signal:**

* densify / tip collect as primary  
* mass_research loop wiring  
* Phase7 arming / READY mint  
* order execution / paper fill  
* promoting `topix_relative_1d` or the signal to approved / strategy-default  
* invent Dataset COMPLETE 22  
* push (unless a later wave explicitly requests)

Unit/AST guard: `tests/test_single_shot_research_job.py::test_t7_signal_and_single_shot_no_mass_ready_or_orders`.

---

## 6. Runtime entry (reference)

```python
from research.single_shot_job import execute_single_shot_job, DEFAULT_SIGNAL_ID

ex = execute_single_shot_job(
    dataset_ids=[
        "equities_bars_daily",
        "markets_calendar",
        "indices_bars_daily_topix",
    ],
    period_start="2026-08-01",
    period_end="2026-08-15",
    job_id="demo-job",
    dry_run=False,
    compute_signals=True,  # implies feature compute for the three legs
    feature_codes=["13010", "72030"],
    feature_as_of="2026-08-10T15:30:00+09:00",  # prefer a tip trading day
)
assert DEFAULT_SIGNAL_ID == "c21_topix_relative_sign"
assert ex.signal_result["candidate_only"] is True
assert ex.mass_research == "NO-GO"
assert ex.ready_declared is False
assert ex.signals_r2_key is not None
```

Notes:

* Prefer `feature_as_of` on a **tip trading day** (calendar filter otherwise yields nulls by design).  
* Pure helpers live in `features.minimal_signal` (`compute_topix_relative_sign_signal`, `compute_signal_from_feature_observations`, `signal_definition`).

---

## 7. Freeze checklist

| check | expected |
|-------|----------|
| signal_id | `c21_topix_relative_sign` |
| version | `1.0.0` |
| candidate_only | true |
| volume gate default | off (`None`) |
| inputs | COMPLETE 21 subset only |
| DEFER 5 | fail-closed |
| Mass | NO-GO |
| Phase7 | OFF |
| READY | not declared |
| orders | none |
| write path | R2 `…/signals/` |

**Spec freeze date:** 2026-08-15 (W53 / w0815at_g2 T5).  
**Code SoT:** `features.minimal_signal` constants + `signal_definition()`.
