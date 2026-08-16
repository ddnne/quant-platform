# W77 / w0816k — Hypothesis space redesign (not simple daily sign mass production)

**Phase:** Research entry space redesign（READY 未宣言）  
**Wave:** W77 / w0816k · 2026-08-16  
**Purpose:** Split research hypotheses into explicit **classes** so default generation is multi-structure and **not** mass simple daily sign.  
**Code:** `packages/product/research/hypothesis_classes.py` · `idea_generator.py` · `scheduler.py` (class mix helpers)  
**Prior:** W65 S1–S5 rejected · W66 standard eval checklist · W74 research entry · W75 milestone freeze (human hypothesis class wait)

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| edge / significance / operational GO | **none** |
| densify / invent COMPLETE 23 | **none** |
| S1–S5 un-reject | **none** (catalog stays `research_baseline_rejected`) |
| simple_daily_sign default generation | **OFF** (explicit opt-in only) |
| mass-default daily sign mix | **forbidden** |

This wave **does not** claim edge, arm Mass, mint READY, un-reject S1–S5, or invent COMPLETE 23.

---

## Why class split

### Problem

W57–W65 concentrated research energy on **simple daily sign** hypotheses
(`sign(feature_1d)` → nextday close-to-close ±1). That family:

1. Overstated tip/short-window wins (W58 illusion).
2. Failed multi-year cost-aware gate (W63–W64) for S1; S2–S5 never became candidates.
3. Was fixed as **`research_baseline_rejected`** (W65 catalog) — a valid research outcome.
4. Risked becoming the **default mass-generation shape** if entry remained “one more daily sign.”

After W74 research entry readiness under COMPLETE 22 and W75 freeze, residual
status was **waiting for human hypothesis class** — not “mint more S6 daily signs.”

### Solution

Declare a **hypothesis class registry** with required structure fields and a
**generation policy**:

* Default generation pool = multi-day / event / cross-section / macro /
  fundamentals / flow classes.
* **`simple_daily_sign` = lowest priority + default generation OFF**.
* Explicit opt-in required to include simple_daily_sign; mix cannot be
  simple_daily_sign-only or majority-skewed to it.
* Fields align with `ResearchIdea` (`target_horizon`, `intended_universe`,
  `candidate_concepts`, `constraints`, lineage).

Class split is a **research design control**, not an operational GO.

---

## Classes

| class_id | default gen | priority | horizon (template) | role |
|----------|:-----------:|---------:|--------------------|------|
| `multi_day_hold` | ON | 10 | `5d_to_20d_hold` | multi-day hold; not 1d flip |
| `event_post` | ON | 20 | `1d_to_5d_post_event` | post-disclosure / post-earnings |
| `cross_section_relative` | ON | 30 | `5d_to_20d_cross_section` | rank / relative L-S |
| `macro_conditioned` | ON | 40 | `20d_to_60d_regime_conditioned` | regime-conditioned |
| `fundamentals_price` | ON | 50 | `20d_to_60d_fundamental` | fundamentals vs price (PIT) |
| `flow_demand` | ON | 60 | `5d_to_20d_flow` | margin/short/investor flow |
| **`simple_daily_sign`** | **OFF** | **99** | `1d_nextday_close_to_close` | documentation + opt-in only |

### Required fields (every class)

| field | ResearchIdea alignment |
|-------|------------------------|
| `horizon` | `target_horizon` |
| `universe` | `intended_universe` |
| `datasets_required` | `lineage["datasets_required"]` |
| `feature_kinds` | `candidate_concepts` |
| `constraints` | `constraints` |

Plus policy: `generation_enabled_by_default`, `priority`, `opt_in_required`.

---

## Default OFF for `simple_daily_sign`

| rule | held |
|------|------|
| `generation_enabled_by_default` | **False** |
| `opt_in_required` | **True** |
| In `DEFAULT_GENERATION_CLASS_IDS` | **No** |
| `is_generation_enabled("simple_daily_sign")` without opt-in | **False** |
| Alone as generation mix | **rejected** (`assert_generation_mix_not_skewed`) |
| Majority share in mix | **rejected** (max share ≈ 1/3) |
| S1–S5 catalog | still **`research_baseline_rejected`** |

**Why default OFF:** the class already exhausted the standard checklist path for
S1–S5 without becoming `research_candidate`. Keeping it default-on would
recreate mass daily-sign production and ignore W65. Opt-in remains for
controlled re-runs / documentation only — never Mass/READY path.

---

## Wiring

| surface | behavior |
|---------|----------|
| `hypothesis_classes.select_generation_classes` | default mix excludes simple_daily_sign |
| `idea_generator.generate_idea_payloads` | builds `ResearchIdea`s from default mix |
| `scheduler.select_schedule_hypothesis_classes` | same policy for schedule planning |
| `ExperimentScheduler.schedule(..., hypothesis_class=)` | rejects non-opt-in simple_daily_sign before mass gate |
| `baseline_catalog` | S1–S5 rejected **untouched** |
| `run_standard_research_eval` | checklist still required for any future candidate |

Mass experiment `schedule()` remains fail-closed without `VerifiedResearchReadiness`.

---

## Usage (research declaration only)

```python
from research.hypothesis_classes import (
    assert_simple_daily_sign_not_default_enabled,
    default_generation_class_ids,
    select_generation_classes,
)
from research.idea_generator import generate_idea_payloads

assert_simple_daily_sign_not_default_enabled()
assert "simple_daily_sign" not in default_generation_class_ids()

batch = generate_idea_payloads(author="human", batch_id="w77-demo")
assert batch.simple_daily_sign_included is False
# Each idea.lineage["hypothesis_class"] is a non-daily-sign class by default.
```

---

## Forbidden (this wave)

- Mass / READY / Phase7 ON  
- S1–S5 un-reject  
- invent COMPLETE 23 / empty-raw COMPLETE  
- new simple daily signs as mass-default  
- short-window-only `research_candidate`  
- claiming edge / operational GO from class registry alone  

---

## Tests

`tests/test_hypothesis_classes.py`:

* registry required fields present  
* `simple_daily_sign` not default-enabled  
* default generation mix excludes simple_daily_sign  
* opt-in path works; skew/solo mix fail-closed  
* freezes closed (READY/Mass/Phase7)  

---

## Residual link

Research entry remains under COMPLETE 22 health + standard eval checklist.  
Next human step after this redesign: **pick a non-daily-sign class** and run
`run_standard_research_eval` under that class’s datasets/horizon — still no
READY/Mass auto-connect.

Residual SoT: [`docs/phase62_residual_status.md`](../phase62_residual_status.md).
