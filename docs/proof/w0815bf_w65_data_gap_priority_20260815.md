# W65 / w0815bf — Data gap inventory & priority (C)

**Phase:** データ穴の整理（inventory only · densify なし）  
**Wave:** W65 / w0815bf  
**Generated:** 2026-08-15T14:43:00Z  
**SoT:** R2 `quant-structured` history · D1 tip not long-history SoT · local mirrors disposable  
**Machine log:** [`.glm-logs/w0815bf_w65_baselines/data_gap_priority.json`](../../.glm-logs/w0815bf_w65_baselines/data_gap_priority.json)

## Explicit non-actions / non-declarations

| claim / action | status |
|----------------|--------|
| densify / invent COMPLETE | **forbidden** (COMPLETE remains **21** / DEFER **5**) |
| auto-fill missing years | **no** |
| READY / Mass / Phase7 | **not declared / NO-GO / OFF** |
| operational GO / edge | **refused** |
| commit / push this wave | **out of scope** |

This document consolidates known holes so research windows are chosen from **observed coverage**, not tip illusion. Gaps are **loader/routing facts**, not densify tickets.

## Sources (held)

| wave | path |
|------|------|
| W61 coverage | [`w0815bb_w61_coverage_inventory_20260815.md`](w0815bb_w61_coverage_inventory_20260815.md) · [`.glm-logs/w0815bb_w61_multiperiod/coverage_inventory.json`](../../.glm-logs/w0815bb_w61_multiperiod/coverage_inventory.json) |
| W63 year avail | [`w0815bd_w63_year_availability_20260815.md`](w0815bd_w63_year_availability_20260815.md) · [`.glm-logs/w0815bd_w63_multiyear/availability_table.json`](../../.glm-logs/w0815bd_w63_multiyear/availability_table.json) |
| W63 window inventory | [`w0815bd_w63_multi_year_window_inventory_20260815.md`](w0815bd_w63_multi_year_window_inventory_20260815.md) |
| W64 cost eval gaps | [`w0815be_w64_cost_multi_year_eval_20260815.md`](w0815be_w64_cost_multi_year_eval_20260815.md) §C · [`.glm-logs/w0815be_w64_cost_full/`](../../.glm-logs/w0815be_w64_cost_full/) |
| W62 S4/S5 gaps | [`w0815bc_w62_extra_hyp_s4_s5_20260815.md`](w0815bc_w62_extra_hyp_s4_s5_20260815.md) |

## Legend

### Status codes (year × dataset)

| code | meaning |
|------|---------|
| **OK** | JSONL present (or continuous-ish) for that year |
| **ARCH** | JSONL hole / tip-only; **archive (+ PIT repair)** usable for research |
| **GAP** | empty / missing for that year; **do not invent** |
| **SPARSE** | present but sparse / sample-bound (honest bound, not invent) |
| **N/A** | outside known inventory floor (pre-start or tip-only plane) |
| **—** | not inventoried at year granularity in source waves |

### Priority

| P | meaning |
|---|---------|
| **P0** | blocks primary multi-year research path with **no** honest archive/skip route |
| **P1** | blocks a secondary hyp year or forces archive/skip; research can continue around it |
| **P2** | quality / tip / sample-span issue; not a research blocker for current hyp set |

### Action

| action | meaning |
|--------|---------|
| **HOLD** | known; leave as-is; document only |
| **ARCHIVE_OK** | use archive (and research PIT repair if needed); not a densify ticket |
| **MANUAL_LIST_ONLY** | human re-pull could close JSONL hole later; **no auto densify** |
| **DO_NOT_DENSIFY** | permanent / policy gap or DEFER class — invent forbidden |

### fill needed for next research?

**yes** only if the next planned research window **cannot** proceed honestly without new raw.  
Default after W63/W64: **no** (archive/skip/`empty_allowed` already used).

---

## 1. Dataset summary (research eval plane)

| dataset | JSONL years (known) | archive / alternate | primary gap | research usable? |
|---------|---------------------|---------------------|-------------|------------------|
| `equities_bars_daily` | **2008–2026** continuous-ish | cold archive batches (supplement) | pre-2008 DEFER; full-year sample often ends ~Oct | **YES** (floor ≈2008-05) |
| `indices_bars_daily_topix` | **2008–2023 + 2026** | archive **4440d** · 2008-05-07…2026-06-30 | **JSONL gap 2024–2025** | **YES via archive** |
| `markets_calendar` | **2026 tip only** | archive **6756d** · 2008-01-01…2026-06-30 + PIT repair | JSONL not multi-year SoT | **YES via archive+PIT** |
| `markets_margin_interest` | **2013–2023 + 2025–2026** | archive samples not period-aligned for 2024 | **JSONL empty 2024** | **Partial** (`empty_allowed` / skip S4) |
| `markets_short_ratio` | **2013–2023 + 2026** | same class as margin | **JSONL gap 2024–2025** | **Partial** (skip S5) |
| `markets_margin_alert` | present **incl. 2024** | — | none for S1–S3 | optional |
| `fins_summary` | **2008–2026** monthly-ish sparse | — | sparse code-filtered rows | sparse OK |

Plane sketch (held from W63):

```
bars      JSONL 2008..2026  ── usable continuous multi-year
topix     JSONL 2008..2023,2026  | ARCHIVE fills 2024-2025
calendar  JSONL tip-2026 only    | ARCHIVE + aa research repair
margin    JSONL 2013..2023,2025..2026  | GAP 2024
short     JSONL 2013..2023,2026        | GAP 2024-2025
D1 tip    2026-07-01..~2026-08 only (~20–28 as_of days)
```

---

## 2. Year × dataset availability (2015–2026)

Status = **research-plane honest view** (JSONL primary; ARCH when archive is the working path).  
Does **not** invent COMPLETE. Does **not** claim every calendar day is filled.

| year | equities_bars_daily | indices_bars_daily_topix | markets_calendar | markets_margin_interest | markets_short_ratio | notes |
|-----:|---------------------|--------------------------|------------------|-------------------------|---------------------|-------|
| 2015 | **OK** | **OK** / ARCH | **ARCH** | **OK** | **OK** | W63 y2015_q4 S1/S4 live ok · full-year sample span →~2015-10-21 (W64) |
| 2016 | **OK** | **OK** / ARCH | **ARCH** | **OK** | **OK** | not in W63 biennial set; inventory-supported |
| 2017 | **OK** | **OK** / ARCH | **ARCH** | **OK** | **OK** | W63 y2017_q4 ok |
| 2018 | **OK** | **OK** / ARCH | **ARCH** | **OK** | **OK** | not in biennial set |
| 2019 | **OK** | **OK** / ARCH | **ARCH** | **OK** | **OK** | W63 y2019_q4 · full-year sample →~2019-10-18 |
| 2020 | **OK** | **OK** / ARCH | **ARCH** | **OK** | **OK** | not in biennial set |
| 2021 | **OK** | **OK** / ARCH | **ARCH** | **OK** | **OK** | W63 y2021_q4 · full-year sample →~2021-10-15 |
| 2022 | **OK** | **OK** / ARCH | **ARCH** | **OK** | **OK** | W61 w2022q4 proven (81d bars) · W62 S4/S5 yes |
| 2023 | **OK** | **OK** / ARCH | **ARCH** | **OK** | **OK** | W61/W63 proven · full-year sample →~2023-10-13 |
| 2024 | **OK** | **GAP→ARCH** | **ARCH** | **GAP** | **GAP** | topix JSONL missing · margin empty · short empty · S1–S3 only if archive topix/cal |
| 2025 | **OK** | **GAP→ARCH** | **ARCH** | **OK** | **GAP** | topix JSONL gap · short empty · margin ok (W62/W63) · y2025_q4 topix via archive |
| 2026 | **OK** (tip+JSONL) | **OK** tip / ARCH to 2026-06-30 | **OK** tip / **ARCH** history | **OK** (tip) | **OK** (JSONL+tip) | D1 tip plane ~Jul–Aug only for hot path; not multi-year depth |

### 2.1 JSONL-only view (without archive routing)

| year | bars | topix JSONL | calendar JSONL | margin JSONL | short JSONL |
|-----:|:----:|:-----------:|:--------------:|:------------:|:-----------:|
| 2015–2023 | Y | Y | N (tip-only dataset) | Y (≥2013) | Y (≥2013) |
| 2024 | Y | **N** | N | **N** | **N** |
| 2025 | Y | **N** | N | Y | **N** |
| 2026 | Y | Y (tip shards) | Y (tip) | Y | Y |

---

## 3. Priority gap table

| id | dataset | gap description | research impact (blocks which hyp) | priority | action | fill needed for next research? |
|----|---------|-----------------|------------------------------------|----------|--------|--------------------------------|
| G1 | `indices_bars_daily_topix` | JSONL **missing 2024–2025**; archive covers 2008-05-07…2026-06-30 | S1 `topix_rel` if forced JSONL-only on 2024–25 windows; **archive resolves** (W61/W63/W64 used archive) | **P1** | **ARCHIVE_OK** · **DO_NOT_DENSIFY** | **no** |
| G2 | `markets_calendar` | JSONL **tip 2026 only**; history needs archive + research PIT (`available_at` often ingest-polluted ~2026) | S1–S5 all need trading-day calendar; **archive+PIT resolves** (no SoT rewrite) | **P1** | **ARCHIVE_OK** · **DO_NOT_DENSIFY** | **no** |
| G3 | `markets_margin_interest` | JSONL **2024 empty**; archive samples not period-aligned for w2024q4 | **S4** margin_change empty on 2024; S1–S3 unaffected (`empty_allowed`) | **P1** | **HOLD** · **DO_NOT_DENSIFY** · optional **MANUAL_LIST_ONLY** | **no** (W63/W64 S4 used non-2024 years; residual weak) |
| G4 | `markets_short_ratio` | JSONL **gap 2024–2025** | **S5** short_ratio_delta empty on those years (W62: FAIL gate already) | **P2** | **HOLD** · **DO_NOT_DENSIFY** · optional **MANUAL_LIST_ONLY** | **no** |
| G5 | `equities_bars_daily` | Full-year **sample span** often ends mid-year (~Oct) when keys_sampled=80; not a missing year | False “full calendar year” if period_end=Dec while bars end earlier → nextday R null (W64 lesson); bind period to bar span | **P2** | **HOLD** · **DO_NOT_DENSIFY** | **no** (honest bar-span bound) |
| G6 | `equities_bars_daily` | Pre-floor **2004-01…2008-04** NO_RAW/EMPTY (DEFER D7 class) | any hyp wanting pre-2008 history | **P2** | **DO_NOT_DENSIFY** | **no** |
| G7 | `fins_summary` | monthly-ish sparse; code-filtered rows small (W61: 50–77/Q) | **S3** disclosure non_null low; report honestly | **P2** | **HOLD** · **DO_NOT_DENSIFY** | **no** |
| G8 | D1 tip plane | bars/topix tip only ~**2026-07-01…~2026-08** (~20–28d) | tip compare only; **not** multi-year R2 history | **P2** | **HOLD** | **no** |
| G9 | topix / calendar / margin / short | archive envelopes `available_at≈2026` ingest pollution on historical events | historical as_of fails without **research** aa repair | **P1** | **ARCHIVE_OK** (repair policy documented; no SoT rewrite) | **no** |

**No P0 gaps** for the current S1/S4 multi-year research path: every known hole has an archive, skip, or `empty_allowed` route already exercised in W61–W64.

---

## 4. Impact by hypothesis (held)

| hyp | datasets | gap sensitivity | current research status (W62–W64) |
|-----|----------|-----------------|-----------------------------------|
| **S1** topix_rel | bars · topix · calendar | G1/G2 → archive+PIT; G5 → bar-span bind | Q4 multi-year gross soft PASS → **cost-aware FAIL**; full-span FAIL |
| **S2** volume gate | bars | none structural; long windows may report non_null=0 honestly | not primary multi-year driver |
| **S3** disclosure | bars · fins | G7 sparse | non_null reported; no densify |
| **S4** margin_change | margin · bars · calendar | **G3 blocks 2024 only** | cost-aware multi-year PASS (all −) but **weak residual** ≠ GO |
| **S5** short_ratio_delta | short · bars · calendar | **G4 blocks 2024–2025** | gate **FAIL** (sign split) |

**Research implication:** filling JSONL holes does **not** unlock READY/Mass. Cost-aware multi-year already failed or only weakly passed without inventing data.

---

## 5. Loader policy (held · no densify)

| rule | action |
|------|--------|
| topix 2024–2025 | load **archive**, not JSONL year shards |
| calendar history | load **archive**; research `available_at=event_time` when envelope aa is ingest-polluted |
| margin 2024 | `r2_allow_empty_datasets=["markets_margin_interest"]` **or omit S4** |
| short 2024–2025 | same for `markets_short_ratio` **or omit S5** |
| full-year bars | bound `period_end` to **observed bar day span**; do not invent Dec |
| DEFER permanent | hard reject as history densify target |
| densify / invent COMPLETE | **forbidden** |

---

## 6. 人手で取る価値がある穴

Bullet list only (no fill implementation this wave).  
Selection criterion: human re-pull might improve **JSONL continuity** for a future optional hyp year — **not** required for next research and **not** a densify job.

- `markets_margin_interest` **2024** full-year JSONL (only if a future design insists on continuous S4 through 2024; current residual is weak → **low value**)
- `markets_short_ratio` **2024–2025** JSONL (only if S5 is revived after redesign; W62 already FAIL → **low value**)
- `indices_bars_daily_topix` **2024–2025** JSONL shards (optional parity with other years; **archive already research-OK** → **very low value**)
- `markets_calendar` multi-year JSONL shards (optional; **archive+PIT already research-OK** → **very low value**)
- full-year `equities_bars_daily` key coverage past ~Oct for sampled full-year jobs (optional nicer spans; **bar-span bind already honest** → **low value**)

**Default recommendation:** do **not** spend human cycles filling the above for the next research wave. Prefer new hyp design / cost-aware evaluation over hole-filling.

---

## 7. Freeze (held)

| flag | value |
|------|------:|
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| ready_declared | **false** |
| operational_go | **false** |
| COMPLETE / DEFER | **21 / 5** |
| densify this wave | **none** |
| invent COMPLETE | **forbidden** |
| return_1d_c21 promote | **forbidden** |

---

## 8. Residual pointer

Coverage baseline remains COMPLETE **21** / DEFER **5** / actionable densify gap **0**.  
JSONL year holes remain **inventory facts**. Next research should continue to:

1. route topix/calendar via archive (+ PIT repair),  
2. skip or `empty_allowed` margin/short gap years,  
3. bind full-year periods to observed bar spans,  
4. treat cost-aware multi-year as the stricter research bar (W64).

*End of W65 / w0815bf data gap priority. No densify · no Mass · no READY · no invent COMPLETE.*
