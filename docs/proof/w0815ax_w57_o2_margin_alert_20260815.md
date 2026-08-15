# W57 / w0815ax_g3 — optional O2 (margin_alert_flag) + careful promotion (2026-08-15)

**Wave:** W57 / w0815ax_g3 · T7  
**Phase:** COMPLETE 21 利用品質 — optional feature-level O2 smoke + promote **one** if clear pass  
**Mass / READY / Phase7:** still **NO-GO / not declared / OFF**  
**densify:** **none** · tip densify **SKIP** · push **not** this task (G4 final)  
**Criteria SoT:** [`complete21_feature_candidate_to_approved_criteria_20260815.md`](complete21_feature_candidate_to_approved_criteria_20260815.md)

**Chosen feature:** `margin_alert_flag` (binary flag; required kwargs `code`)  
**Policy no-promote (T7):** `return_1d_c21` (twin of approved v0 `return_1d`)

| result | feature_id | version pin | intended_role | O2 |
|--------|------------|-------------|---------------|----|
| **promoted** | `margin_alert_flag` | **1.0.0** | signal | job `w0815ax-g3-o2-margin-alert` · non_null **5** · tip rows **1094** · sample **1.0** |
| not promoted | `return_1d_c21` | 1.0.0 | signal | policy twin of v0 — **no** |

**Totals after W57:** **9** approved · **1** candidate (was 8 / 2).

---

## 0. Hard non-claims

* does **not** declare READY / Mass GO / Phase7 ON
* does **not** densify or invent Dataset COMPLETE 22
* does **not** force-promote features without O2
* does **not** promote `return_1d_c21`
* does **not** push (G4 final will push)

---

## 1. Why margin_alert_flag now (T7)

| criterion | note |
|-----------|------|
| CF tip plane | D1 `jquants_records` / `markets_margin_alert` — tip window **1094** rows (event 2026-08-03…08-11) |
| required kwargs | **`code`** — tip codes present (`13250` · `13660` · `13680` · `14190` · `14930`) |
| entity grain | per-code binary flag if any PIT-visible alert row at as_of |
| prior wave | W56 chose futures; margin_alert left candidate with tip n=1094 |

---

## 2. O2 results (T7)

**Plane:** D1 `quant-ingest` hot tip (`markets_margin_alert`) · tip `FeatureContext` · R2 `quant-structured`  
**as_of:** `2026-08-15T15:30:00+09:00` (after tip `available_at` ≤ 2026-08-11)  
**event window:** 2026-08-01…08-15 (`event_time` substr)

| # | feature_id | job_id | tip rows | non_null | sample | O2 |
|--:|------------|--------|---------:|---------:|--------|----|
| T7 | `margin_alert_flag` | `w0815ax-g3-o2-margin-alert` | **1094** | **5** (≥1 entity) | **1.0** ×5 codes | **PASS** |

**Observation meta (per code):**

| key | value |
|-----|------:|
| codes | 13250 / 13660 / 13680 / 14190 / 14930 |
| rows_seen (per code) | 5 |
| flag / value | 1.0 |
| datasets | `markets_margin_alert` |

**R2 artifacts (put_ok ×4):**

* `research/single_shot/job=w0815ax-g3-o2-margin-alert/input_plan.json`
* `…/result/sha256_32e4fec77af38c42118177852a901ee58ad3e23844ad526201549321bb720090.json`
* `…/features/sha256_32e4fec77af38c42118177852a901ee58ad3e23844ad526201549321bb720090.json`
* `…/manifest.json`

**Machine matrix:** [`.glm-logs/w0815ax_g3_o2/O2_RESULTS_MATRIX.json`](../../.glm-logs/w0815ax_g3_o2/O2_RESULTS_MATRIX.json)  
**Summary:** [`.glm-logs/w0815ax_g3_o2/t7_margin_alert_flag_summary.json`](../../.glm-logs/w0815ax_g3_o2/t7_margin_alert_flag_summary.json)

---

## 3. I/Q/O re-eval — promote?

Shared hard gates held from W52–W56 (I1–I6, O1, O3–O4). Feature-specific:

| gate | verdict | evidence |
|------|---------|----------|
| I1–I6 | **Y** | `_MARGIN_ALERT_DATASETS` = COMPLETE `markets_margin_alert` · DEFER preflight · PIT via `get_jquants_records` · as_of · CF D1 tip |
| Q1 | **Y** | pure helper + seeded unit (`test_margin_alert_flag_on_seeded_records`) |
| Q2 | **Y** | empty rows → `0.0` (`test_margin_alert_flag_empty_is_zero`) |
| Q3 | **Y** | multi-as_of unit hides later margin-alert row (`available_at` gate) |
| Q4–Q7 | **Y** | binary flag · provenance · role=`signal` · required `code` |
| O1–O2 | **Y** | COMPLETE input · W57 tip E2E non_null **5** · R2 put_ok ×4 |
| O5 | **Y** | this proof |

**Decision:** promote `margin_alert_flag` → **approved@1.0.0**.

### Not promoted

| feature_id | reason |
|------------|--------|
| `return_1d_c21` | **T7 policy** — twin of approved v0 `return_1d`; keep candidate export only |

---

## 4. Code / catalog / tests

| surface | change |
|---------|--------|
| `packages/research_runtime/features/complete21_min.py` | `margin_alert_flag` status → `approved` (v1.0.0 pin) |
| `tests/test_complete21_min_features.py` | COMPLETE21_MIN_APPROVED_IDS **9**; candidate **1**; get_for_strategy admits margin_alert |
| Catalog | [`complete21_min_feature_catalog_20260815.md`](complete21_min_feature_catalog_20260815.md) |

**No READY / Mass / Phase7 claim from this promotion.**
