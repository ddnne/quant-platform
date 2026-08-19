# W102 / w0819e Track B — event / rate extra-dataset daily_path_DD

**Wave:** W102 / `w0819e` · Track B  
**Targets:** `event_post_disclosure_hold` · `rate_curve_shape_xs`  
**Method:** daily MTM after cost — same as W99/W100 (`scripts/run_w99_sticky_daily_dd.py`, `scripts/run_w100_peer_daily_dd.py`)  
**Recipe:** `scripts/run_w102_event_rate_daily_dd.py`  
**Logs:** [`.glm-logs/w0819e_w102_otc6_event_rate_dd`](../../.glm-logs/w0819e_w102_otc6_event_rate_dd/)  
**HEAD (pre-commit):** `6186cc9bef6603c8d477a26dbb1e7f27c05fc459`  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| field | value |
|-------|-------|
| `event_post_disclosure_hold` daily_path_DD | **complete** |
| `rate_curve_shape_xs` daily_path_DD | **complete** |
| period_net_DD-only pass | **forbidden / not used** |
| promote_as_main | **False** |
| go / go_eligible | **False** |
| Complete measurement = GO/main | **no** |
| 3-default pins untouched | **True** |
| hold/mom micro-grid | **not run** |
| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |

W100/W101 left these two as **unmeasured → incomplete** because the peer bars-MTM path did not wire extra datasets. This wave **identifies the exact files**, **wires what is local**, and emits the required scorecard. Complete measurement is **not** a GO.

## 1. Extra datasets required for a daily equity curve

### `event_post_disclosure_hold`

| need | path |
|------|------|
| bars (close panel) | local `real_mirrors` shards (same W99/W100 windows) |
| disclosure events | `fins_summary` via `data/structured/ingestion.sqlite` → `jquants_records` |
| PIT fields | `DiscDate` + `DiscTime` (never invented) |
| surprise proxy | `FEPS−EPS` else `EPS−prior_eps` (else skip) |
| loader | `load_fins_events_from_sqlite` |

Local status: **ok** · n_events=716 · n_codes=15 · DiscTime present=716 · surprise fields=641 · span 2016-01-27→2026-07-31.

### `rate_curve_shape_xs`

| need | path |
|------|------|
| bars (close panel) | local `real_mirrors` shards (same W99/W100 windows) |
| funding curve | `jsda_tokyo_repo_rates` via `data/structured/ingestion.sqlite` → `jsda_repo_rates` |
| tenors (observed only) | `overnight/翌日物/T+0` and `3M/T+1` |
| curve | `spread = 3M − overnight` same `as_of_date` (no ffill) |
| loader | `load_repo_rows_all_tenors_from_sqlite` + `build_repo_curve_series` |

Local status: **ok** · n_repo_rows=23346 · n_spread=2594 · n_gap_either_leg=0 · span 2016-01-04→2026-08-14 · ffill=False invent=False.

## 2. Wiring result

| logic | extra dataset | wired | daily_path_complete | missing |
|-------|---------------|:-----:|:-------------------:|---------|
| `event_post_disclosure_hold` | `fins_summary` | yes | yes | — |
| `rate_curve_shape_xs` | `jsda_tokyo_repo_rates` | yes | yes | — |

## 3. Daily path table (after cost)

Required columns: **daily_path_DD** · **dd_duration** · **recovery** · **total_ret_net**.

| logic | window | n_days | daily_path_DD | dd_duration | recovery | recovered | total_ret_net | complete | missing |
|-------|--------|-------:|--------------:|------------:|---------:|:---------:|--------------:|:--------:|---------|
| `event_post_disclosure_hold` | w2017_2019 | 272 | −0.084166 | 117 | 69 | True | 0.079814 | yes | — |
| `event_post_disclosure_hold` | w2020_2022 | 193 | −0.055684 | 3 | 8 | True | 0.070840 | yes | — |
| `event_post_disclosure_hold` | w2023_2025 | 273 | −0.113934 | 89 | — | False | −0.034478 | yes | — |
| `rate_curve_shape_xs` | w2017_2019 | 272 | −0.177664 | 142 | — | False | −0.048683 | yes | — |
| `rate_curve_shape_xs` | w2020_2022 | 193 | −0.195470 | 165 | — | False | −0.184247 | yes | — |
| `rate_curve_shape_xs` | w2023_2025 | 273 | −0.202368 | 175 | — | False | −0.016830 | yes | — |

### Per-shard

| logic | window | period_id | n_days | daily_path_DD | total_ret_net | extra |
|-------|--------|-----------|-------:|--------------:|--------------:|-------|
| `event_post_disclosure_hold` | w2017_2019 | y2017_q4 | 81 | −0.044395 | 0.018620 | entered=12 events=14 |
| `event_post_disclosure_hold` | w2017_2019 | y2019_full | 192 | −0.057962 | 0.060076 | entered=38 events=43 |
| `event_post_disclosure_hold` | w2020_2022 | y2021_full | 193 | −0.055684 | 0.070840 | entered=38 events=39 |
| `event_post_disclosure_hold` | w2023_2025 | y2023_full | 193 | −0.048347 | 0.089428 | entered=36 events=40 |
| `event_post_disclosure_hold` | w2023_2025 | y2025_q4 | 81 | −0.113934 | −0.113734 | entered=12 events=12 |
| `rate_curve_shape_xs` | w2017_2019 | y2017_q4 | 81 | −0.088537 | −0.078303 | gap=0 inv=960 steep=12 |
| `rate_curve_shape_xs` | w2017_2019 | y2019_full | 192 | −0.104401 | 0.032136 | gap=0 inv=2256 steep=48 |
| `rate_curve_shape_xs` | w2020_2022 | y2021_full | 193 | −0.195470 | −0.184247 | gap=0 inv=2244 steep=72 |
| `rate_curve_shape_xs` | w2023_2025 | y2023_full | 193 | −0.162523 | −0.070509 | gap=0 inv=2148 steep=168 |
| `rate_curve_shape_xs` | w2023_2025 | y2025_q4 | 81 | −0.098810 | 0.057750 | gap=0 steep=900 inv=60 flat=12 |

## Headline (research-only · not GO)

- `event_post_disclosure_hold`: daily_path_DD **complete** on all three windows. Worst path DD **−11.4%** (2023–25 stitch, unrecovered, negative net). Sparse event book (hold=5 PIT post-disclosure). **Research-only. Not main. Not GO.**
- `rate_curve_shape_xs`: daily_path_DD **complete** on all three windows. Worst path DD **−20.2%** (2023–25 stitch, unrecovered, negative net). NIRP-era windows are almost all inverted (reverse CS). Curve = JSDA 3M−ON (funding term-structure proxy, **not** JGB/OIS). **Research-only. Not main. Not GO.**

> **Warning:** period-net DD = 0 when all period nets are positive is an
> **aggregation artifact**. It does **not** mean the strategy is riskless.
> Use **daily_path_DD** (duration / recovery / total_ret_net).
>
> **Complete measurement ≠ GO / main.** These rows remain research-only.

## Method

1. Identify extra datasets: `fins_summary` (events) and `jsda_tokyo_repo_rates` (curve). Load from local `ingestion.sqlite`.
2. Load local `real_mirrors` bars for W98/W99 honest shards (2018/2020/2022/2024 absent — omitted, no synthetic fill).
3. **Event book:** PIT entry (`same_day_close_if_pre_close`); explicit hold window of `post_hold_days=5`; last-event-wins if overlap.
4. **Rate book:** CS mom ranks × curve-shape transform (steep keep / inverted reverse / flat no-trade) + sticky hold=10 mom=5.
5. Mark the held book to market **daily** (equal-weight active names).
6. Subtract Python amortized daily cost drag while active (one_way=0.001).
7. Equity-curve peak-to-trough → max DD, duration, recovery, after-cost total return.
8. `evaluate_daily_path_dd_gate` must **complete**; period-net-only is **forbidden**.

Codes: first 15 of `DEFAULT_EVAL_CODES`; max_days/shard=200. Catalog base params — **not** a retune.

## Freezes held

- promote_as_main = **false** · go = **false**
- no hold/mom micro-grid · no 3-default pin retune
- Mass NO-GO · READY 未宣言 · Phase7 OFF · continuous paper UNARMED
- period_net_DD-only **cannot pass**
- no invent DiscTime · no repo ffill

## Non-claims

- No READY / Mass / GO / live / pin retune / hold-mom grid / full catalog grid.
- Neither logic promoted as main. Sticky not re-promoted.
- Local mirrors + local sqlite ≠ CF SoT.
- Period-net DD=0 **must not** be read as riskless.
- Complete daily_path_DD is **not** a production candidate / GO.

GLM implementer only. Grok did not implement.
