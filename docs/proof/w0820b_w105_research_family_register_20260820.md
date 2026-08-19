# W105 / w0820b Track D — research-family registration (recognition, not promotion)

**Wave:** W105 / `w0820b` · Track D  
**Register id:** `w104_w105_unique_logic_research_family`  
**Factory:** `mass-strategy-factory/v2.6`  
**Recipe:** `scripts/run_w105_research_family_register.py`  
**Code:** `packages/product/research/mass_strategy_factory.py`  
**Tests:** `tests/test_w105_research_family_register.py` · `tests/test_mass_strategy_factory.py`  
**Artifacts:** [`.glm-logs/w0820b_w105_otc9_family_hyps/`](../../.glm-logs/w0820b_w105_otc9_family_hyps/) · `research_family_register.json` · `research_family_register_summary.json` · `w105_def_summary.json`  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Registration = recognition, not pass / not promotion

W104 (and this-wave W105) unique_logic was accepted as **ad-hoc** `family_id`s. Catalog dispatch returned `unknown_family` → factory synthetic period-net stuck at **0 ok periods**. That 0 was **not** an eval of the unique_logic; it was a missing-family skip.

This wave **registers** those unique_logics as a **research family** so factory period-net can dispatch. That is **recognition**, not a pass, not promotion.

| must | held |
|------|------|
| registration = recognition | **yes** |
| registration is **not** a pass | **yes** |
| registration is **not** promotion | **yes** |
| auto `research_candidate` | **false / not done** |
| Mass / READY / GO / main | **not** |
| `generation_enabled` | **false** (not in factory generation pass) |
| remap onto sticky / event_post / vol | **not** |
| period-net survival treated as pass | **forbidden** |
| daily_path_DD remains the required eval | **yes** |

---

## What was registered

**Register id:** `w104_w105_unique_logic_research_family`  
**Family group:** `research_unique_logic`  
**n_logic_ids:** **8** (W104 four + W105 four that landed this wave)

| logic_id | family_id | wave | generation_enabled | research_candidate | GO / main |
|----------|-----------|------|:------------------:|:------------------:|:---------:|
| `event_funding_stress_skip` | `event_funding_combo` | W104 | false | false | false |
| `curve_steep_event_confirm` | `event_macro_curve_combo` | W104 | false | false | false |
| `disclosure_cluster_mom_gate` | `disclosure_cluster_gate` | W104 | false | false | false |
| `surprise_xs_rank_hold` | `surprise_xs_rank` | W104 | false | false | false |
| `large_surprise_event_hold` | `large_surprise_filter` | W105 | false | false | false |
| `afterclose_only_event_hold` | `afterclose_event_timing` | W105 | false | false | false |
| `event_pre_mom_agree_hold` | `event_mom_agree_combo` | W105 | false | false | false |
| `event_margin_crowding_skip` | `event_margin_crowd_combo` | W105 | false | false | false |

Distinct family_ids are kept (not remapped onto `event_post` / `cross_section_relative` / `flow_demand`). Recognition is **not** a catalog-map of sticky / event / vol.

---

## Factory period-net after recognition

`propose_profit_hypotheses` (synthetic, evaluate=True) on the 8 registered unique_logics:

| metric | value |
|--------|------:|
| n_proposed / n_accepted | **8 / 8** |
| n_unknown_family (strategies) | **0** |
| n_periods_ok_total | **24** (8 × 3 synthetic periods) |
| factory_period_net_not_stuck_unknown | **true** |
| n_survivors_period_net | **0** |
| period_net_is_not_a_pass | **true** |
| auto_research_candidate | **false** |
| promote_as_main | **false** |
| go | **false** |

W104 four now evaluate (`n_periods_ok=3` each) instead of `no_ok_periods` from `unknown_family`. W105 four likewise. Screen rejects are **near_zero / both_signs / low_activation / inflated_t** — i.e. real recognition eval, not a missing-family skip.

**n_survivors_period_net = 0 is honest and is not a pass.** Factory synthetic period-net **cannot** pass this gate. daily_path_DD of the min-impl remains the required eval (W104 / W105 Track B proofs).

`generate_strategy_batch` does **not** emit these logics (`generation_enabled=False`). They are not auto-generated Mass diversity.

---

## Track E confirm (held this wave)

| item | status |
|------|--------|
| extra `xs_cs_dispersion_gate` threshold grid | **not run** |
| extra hold/mom grid | **not run** |
| `xs_cs_dispersion_gate` stance | **RESEARCH_ONLY** |
| `xs_rank_ls_sticky` stance | **STABLE_RESEARCH_ONLY** |
| repo invent / ffill | **false** |
| W103 3-pt coarse thresh | **cited, not rerun** |

---

## Track F confirm (held this wave)

| item | status |
|------|--------|
| 3-default pins | **untouched** (`cross_section_hold_10` KEEP · `cross_section_hold_10_mom3` PROMOTE · `fundamentals_hold_10` KEEP) |
| equities_master MISDATE | **KEEP PARTIAL** (COMPLETE **220** / PARTIAL **21** · no floor raise) |
| projection | **FRESH** (`projgen-6be6453281b44928b2738c96f5de2011`) |
| Mass / READY / GO / live | **NO-GO / false / false / false** |

---

## Explicit non-declarations

- Registration **is not** a pass
- Registration **is not** promotion
- Auto `research_candidate` **not** minted
- Survivors **not** main / **not** GO
- Factory period-net after recognition **cannot** replace daily_path_DD
- Grok did **not** implement

GLM implementer only. Grok did not implement.
