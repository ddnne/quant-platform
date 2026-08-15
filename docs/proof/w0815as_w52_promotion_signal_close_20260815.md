# W52 / w0815as — COMPLETE 21 approved/シグナル下地 close (READY 未宣言) (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF / not declared**  
**empty COMPLETE:** **0** (ban held)  
**tip densify / tip collect:** **SKIP** (approved/シグナル下地; tip not primary)  
**densify:** **none** this wave  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Promotion:** **2** approved (cap max **2** · v**1.0.0**) · **8** remain candidate  
**Signal:** `c21_topix_relative_sign@1.0.0` · **candidate_only** · Mass **OFF** · no orders  
**Primary this wave:** candidate→approved (max 2) + minimal tip signal E2E → R2 `…/signals/` · residual 下地 · G5 FINAL merge + **push**  
**Not:** READY declaration · Mass ON · Phase7 ON · densify · invent COMPLETE 22 · promote >2 · treat signal as READY

**Live verified:** 2026-08-15 (JST) / G1 promotion · G2 signal E2E ~`10:24Z` UTC · G3 smoke+FRESH ~`10:19–10:20Z` · G4 residual ~`10:18–10:20Z` · G5 merge+push this close  
**Wave start HEAD (PRE_sha):** `816fed4d98e8ad6dbec26f0152a36e013f574167` (W51 post-fill)  
**Proof HEAD (post-push):** `POST_PUSH_SHA_PENDING`  
**Projection (G3 T9 reclock; residual sync):** **FRESH** `projgen-97e38cc4670f4003901a2ca3b1b0ba37` (pre-gen `projgen-48993e3f05814d759576c01f65196041`)

**Artifacts:**

| track | path |
|-------|------|
| G1 promotion eval | [`w0815as_w52_feature_promotion_eval_20260815.md`](w0815as_w52_feature_promotion_eval_20260815.md) · `packages/research_runtime/features/complete21_min.py` · catalog |
| G2 signal E2E | [`w0815as_w52_signal_e2e_20260815.md`](w0815as_w52_signal_e2e_20260815.md) · [`.glm-logs/w0815as_g2_signal/`](../../.glm-logs/w0815as_g2_signal/) · job `w0815as-g2-signal-e2e` · **e2e_pass=true** |
| G3 smokes + FRESH | [`.glm-logs/w0815as_g3_ops/`](../../.glm-logs/w0815as_g3_ops/) · T8 bars×short_ratio **pass** · T9 FRESH `projgen-97e38cc…` · T10 pytest **32** |
| G4 residual 下地 | [`.glm-logs/w0815as_g4_ops/`](../../.glm-logs/w0815as_g4_ops/) · [`FINAL_metrics.json`](../../.glm-logs/w0815as_g4_ops/FINAL_metrics.json) · [`switch_check.json`](../../.glm-logs/w0815as_g4_ops/switch_check.json) |
| Residual SoT | [`docs/phase62_residual_status.md`](../phase62_residual_status.md) · § approved/シグナル下地 |
| Catalog | [`complete21_min_feature_catalog_20260815.md`](complete21_min_feature_catalog_20260815.md) |
| Criteria | [`complete21_feature_candidate_to_approved_criteria_20260815.md`](complete21_feature_candidate_to_approved_criteria_20260815.md) |
| Prior W51 feature E2E | [`w0815ar_w51_feature_e2e_close_20260815.md`](w0815ar_w51_feature_e2e_close_20260815.md) |

---

## 1. Parallel agent split (W52 / w0815as)

| lane | tasks | owner / logs | outcome |
|------|-------|--------------|---------|
| **G1** | T1–T4 candidate→approved eval (max **2**) · version pin 1.0.0 · catalog/tests | proof + `complete21_min.py` | **2 approved**: `volume_change_1d` · `is_trading_day` · **8** candidate remain |
| **G2** | T5–T7 minimal signal (Mass OFF) · single_shot `compute_signals` → R2 `…/signals/` | `.glm-logs/w0815as_g2_signal/` · job `w0815as-g2-signal-e2e` | **E2E PASS** · 5 R2 keys · candidate_only · non_null shorts |
| **G3** | T8 bars×short_ratio smoke · T9 FRESH reclock · T10 freeze pytest | `.glm-logs/w0815as_g3_ops/` | **T8 pass** · **FRESH** `projgen-97e38cc…` · pytest **32** |
| **G4** | T11 residual 下地 · T12 tip densify SKIP · empty/dc remote verify · **no push** | `.glm-logs/w0815as_g4_ops/` | residual section **added** · empty **0** · dc **21** · segs **3478** · OTC **93** · switches **OFF** |
| **G5 merge (this)** | unit tests · commit code+docs · promotion/signal close proof · residual FRESH sync · **push** · SHA lock · remote re-verify | this proof | HEAD==origin · empty **0** · dc **21** · Phase7 **OFF** · READY **not** declared · promotion **2/2** · signal **candidate_only** |

CF-SoT held: **D1 = hot tip · R2 = history · COMPLETE = receipt-owned**.

**Not done:** densify · tip collect as primary · Phase7/Mass/READY · invent COMPLETE 22 · floor lower · promote >2 · signal→approved / READY claim.

---

## 2. Metrics held (remote D1 `quant-ingest`)

Source: [`.glm-logs/w0815as_g4_ops/FINAL_metrics.json`](../../.glm-logs/w0815as_g4_ops/FINAL_metrics.json) · G5 re-verify after push.

| Metric | value | role |
|--------|------:|------|
| Segment COMPLETE total | **3478** | held (Δ0 this wave) |
| Dataset COMPLETE | **21 / 26** | **PRIMARY** baseline (not invent 22) |
| PARTIAL | **5** permanent DEFER only | non-actionable |
| **actionable_gap** | **0** | W44 lock held |
| empty COMPLETE | **0** | ban held |
| JSDA OTC COMPLETE | **93** | tip island held · never dataset COMPLETE |
| raw_retention_manifests | **15915** | remote count at G4 (W46 tip secondary baseline **15869** held; not coverage primary) |
| FRESH generation | **`projgen-97e38cc4670f4003901a2ca3b1b0ba37`** | G3 T9 reclock; residual sync this close |
| tip densify | **SKIP** | 下地 only |
| Mass / READY / Phase7 | **NO-GO / not declared / OFF** | held |
| complete21 promotion | **2 approved** / **8 candidate** | cap max **2** · v**1.0.0** |
| signal | `c21_topix_relative_sign@1.0.0` | **candidate_only** · Mass **OFF** |

### Residual phase section name

**`approved/シグナル下地（READY 未宣言）`** in `docs/phase62_residual_status.md`  
(W51 § 特徴量込み E2E + W50 § 利用準備 E2E + W49 deepen + W48 groundwork held underneath; coverage baseline **W47 FINAL** held; this wave does **not** re-open densify).

### Dataset COMPLETE list (**21**) — held

`derivatives_bars_daily_futures` · `derivatives_bars_daily_options` · `derivatives_bars_daily_options_225` · `edinet_cross_shareholdings` · `edinet_large_volume_shareholders` · `edinet_major_shareholders` · `equities_bars_daily` · `equities_investor_types` · `fins_details` · `fins_dividend` · `fins_summary` · `indices_bars_daily` · `indices_bars_daily_topix` · `jsda_corporate_bond_transactions` · `jsda_tokyo_repo_rates` · `markets_breakdown` · `markets_calendar` · `markets_margin_alert` · `markets_margin_interest` · `markets_short_ratio` · `markets_short_sale_report`

**Still not Dataset COMPLETE (permanent DEFER residual):** `equities_master` · `equities_earnings_calendar` · `equities_bars_daily_am` · `jsda_otc_bond_reference_prices` (tip island **93** only) · `fins_earnings_date` (PARTIAL tip holes — W44 FINAL DEFER).

---

## 3. G1 — feature promotion (2 approved)

Detailed proof: [`w0815as_w52_feature_promotion_eval_20260815.md`](w0815as_w52_feature_promotion_eval_20260815.md)

| promoted | version | intended_role | note |
|----------|---------|---------------|------|
| `volume_change_1d` | **1.0.0** | signal | W51 E2E live; bars COMPLETE; seeded + insufficient tests |
| `is_trading_day` | **1.0.0** | utility | calendar COMPLETE; W51 E2E 11/11; utility role (not default strategy admit) |

**Remain candidate (8):** `topix_relative_1d` · `disclosure_flag_fins` · `margin_interest_change_1d` · `short_ratio_level` · `repo_rate_level` · `return_1d_c21` · `margin_alert_flag` · `futures_activity_proxy`

Gates: I1–I6 / Q1–Q7 / O1–O5 per criteria SoT. Cap **max 2** held. No READY claim from promotion.

---

## 4. G2 — minimal signal E2E (PASS)

Detailed proof: [`w0815as_w52_signal_e2e_20260815.md`](w0815as_w52_signal_e2e_20260815.md)  
Source: [`.glm-logs/w0815as_g2_signal/summary.json`](../../.glm-logs/w0815as_g2_signal/summary.json)

**Job id:** `w0815as-g2-signal-e2e`  
**Tip window:** `2026-08-01` … `2026-08-15`  
**Feature/signal as_of:** `2026-08-10T15:30:00+09:00` (last tip trading day)  
**Codes:** `13010`, `72030`  
**content_hash:** `sha256:aff4f27386ba99adbf28d4ad0d80b925d5327215c3e0dbe9d0071b79aa8887f9`

### Signal contract

| field | value |
|-------|-------|
| signal_id | `c21_topix_relative_sign` |
| version | `1.0.0` |
| status | `candidate` |
| candidate_only | **true** (primary `topix_relative_1d` not promoted) |
| formula | `sign(topix_relative_1d)` if `is_trading_day==1` |
| order_execution | **false** |
| mass_research | **NO-GO** |
| ready_declared | **false** |

### Feature legs

| leg | feature_id | registry status |
|-----|------------|-----------------|
| primary | `topix_relative_1d` | **candidate** |
| filter | `is_trading_day` | **approved** |
| gate (optional) | `volume_change_1d` | **approved** |

### Signal values (non-null)

| code | topix_relative_1d | signal |
|------|------------------:|-------:|
| `13010` | ≈ −0.00847 | **−1.0** |
| `72030` | ≈ −0.00597 | **−1.0** |

Row counts: computed **2** · non_null **2** · null **0** · short **2**.

### R2 keys (`quant-structured`)

| key | role |
|-----|------|
| `research/single_shot/job=w0815as-g2-signal-e2e/input_plan.json` | plan |
| `…/result/sha256_aff4f273….json` | tip extract |
| `…/features/sha256_aff4f273….json` | tip features |
| `…/signals/sha256_aff4f273….json` | **signals** (new path) |
| `…/manifest.json` | manifest (`signal{}`) |

R2 put statuses: `put_ok` × **5** · heads all exist.

---

## 5. G3 — smokes + FRESH

| gate | result |
|------|--------|
| T8 bars × `markets_short_ratio` | **pass** (30 rows) |
| T9 FRESH reclock | **FRESH** `projgen-97e38cc4670f4003901a2ca3b1b0ba37` (age wall ~1108s → ops_reeval_freshness; coverage_segments untouched) |
| T10 freeze pytest | **32/32** · mass=NO-GO · phase7=OFF · ready=false |

---

## 6. G5 merge — unit tests + commit + push

### Unit tests (merge)

```text
.venv/bin/python -m pytest \
  tests/test_complete21_min_features.py \
  tests/test_single_shot_research_job.py \
  tests/test_mass_research_gate.py \
  tests/test_permanent_defer_history_guard.py -q
# 84 passed
```

| suite | count |
|-------|------:|
| complete21 min features | 49 |
| single_shot research job | 23 |
| mass research gate | 6 |
| permanent defer history guard | 6 |
| **total** | **84** |

### Freeze surface (reconfirm)

| constant | value |
|----------|------:|
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| ready_publication | **OFF** |
| ready_declared | **false** |
| COMPLETE 21 count | **21** |
| permanent DEFER count | **5** |
| approved features | **2** (`volume_change_1d` · `is_trading_day`) |
| remain candidate | **8** |
| signal status | **candidate** · **candidate_only=true** |
| densify | **none** |

### Commits / SHA lock

| field | value |
|-------|-------|
| PRE_sha | `816fed4d98e8ad6dbec26f0152a36e013f574167` |
| POST_PUSH_SHA (feat commit) | `POST_PUSH_SHA_PENDING` |
| origin/main after push | `POST_PUSH_SHA_PENDING` |
| HEAD == origin/main | **pending push** |

---

## 7. Explicit non-declarations (held)

- **READY** — not declared (approved/シグナル下地 only; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF** (signal E2E Mass OFF)
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)
- **Signal approved / strategy-default** — none (`c21_topix_relative_sign` remains candidate_only)
- **Dataset COMPLETE 22** — forbidden
- **densify / tip densify as primary** — none / SKIP
- **Promote beyond cap 2** — not done

---

## 8. Related code entry

```python
from research.single_shot_job import (
    DEFAULT_CANDIDATE_FEATURES,
    execute_single_shot_job,
    assert_mass_and_phase7_off,
)
from features.minimal_signal import SIGNAL_ID  # c21_topix_relative_sign

assert_mass_and_phase7_off()
ex = execute_single_shot_job(
    dataset_ids=[
        "equities_bars_daily",
        "markets_calendar",
        "indices_bars_daily_topix",
    ],
    period_start="2026-08-01",
    period_end="2026-08-15",
    job_id="w0815as-g2-signal-e2e",
    dry_run=False,
    compute_features=True,
    compute_signals=True,  # writes …/signals/
    feature_ids=DEFAULT_CANDIDATE_FEATURES,
    feature_codes=["13010", "72030"],
    feature_as_of="2026-08-10T15:30:00+09:00",
)
# ex.signals_r2_key · ex.features_r2_key · ex.manifest_r2_key
# signal remains candidate_only; Mass/READY/Phase7 still OFF
```
