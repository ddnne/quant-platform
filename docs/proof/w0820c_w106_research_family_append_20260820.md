# W106 / w0820c Track D — research-family APPEND (recognition, not promotion)

**Wave:** W106 / `w0820c` · Track D  
**Append id:** `w106_unique_logic_family_append`  
**Parent register:** `w104_w105_unique_logic_research_family`  
**Factory:** `mass-strategy-factory/v2.7`  
**Recipe:** `scripts/run_w106_research_family_append.py`  
**Code:** `packages/product/research/mass_strategy_factory.py`  
**Tests:** `tests/test_w106_research_family_append.py` · `tests/test_w106_funding_surprise_ls.py` · `tests/test_mass_strategy_factory.py`  
**Artifacts:** [`.glm-logs/w0820c_w106_otc10_ls_hyps/`](../../.glm-logs/w0820c_w106_otc10_ls_hyps/) · `research_family_append.json` · `research_family_append_summary.json` · `w106_de_summary.json`  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Registration = recognition, not pass / not promotion

W106 **appends this-wave newly min-implemented logics only** (Track B mixed unique_logic + Track C funding/surprise L/S variants). That is **recognition**, not a pass, not promotion.

W104/W105 members stay on the parent register. This append does **not** re-promote them.

| must | held |
|------|------|
| family append = recognition | **yes** |
| registration is **not** a pass | **yes** |
| registration is **not** promotion | **yes** |
| this-wave newly min-implemented only | **yes** (7) |
| auto `research_candidate` | **false / not done** |
| Mass / READY / GO / main | **not** |
| `generation_enabled` | **false** |
| remap onto sticky / event_post / vol | **not** |
| period-net survival treated as pass | **forbidden** |
| daily_path_DD remains the required eval | **yes** |
| kill funding/surprise because sign flipped | **not** (explicitly not) |

**Proof: registration = recognition, not pass.**

---

## What was appended (this wave only)

**Append id:** `w106_unique_logic_family_append`  
**n_appended:** **7** (B four mixed unique_logic + C three L/S)

| logic_id | family_id | track | generation_enabled | research_candidate | GO / main |
|----------|-----------|-------|:------------------:|:------------------:|:---------:|
| `funding_impulse_cs_tilt` | `funding_impulse_cs` | B | false | false | false |
| `curve_steepen_impulse_cs` | `curve_steepen_impulse_cs` | B | false | false | false |
| `xs_margin_delta_rank` | `xs_margin_delta` | B | false | false | false |
| `idio_mom_macro_impulse` | `idio_mom_macro` | B | false | false | false |
| `event_funding_easy_short` | `event_funding_combo` | C | false | false | false |
| `event_funding_stress_ls` | `event_funding_combo` | C | false | false | false |
| `surprise_xs_rank_flip` | `surprise_xs_rank` | C | false | false | false |

C L/S variants append onto parent families (`event_funding_combo`, `surprise_xs_rank`). B mixed unique_logic keep distinct family_ids (not remapped onto sticky / event / vol / rate_curve).

---

## Factory period-net after append

`propose_profit_hypotheses` (synthetic, evaluate=True) on the **7** this-wave append members:

| metric | value |
|--------|------:|
| n_proposed / n_accepted | **7 / 7** |
| n_unknown_family (strategies) | **0** |
| n_unknown_family_period_rows | **0** |
| n_periods_ok_total | **18** |
| factory_period_net_not_stuck_unknown | **true** |
| n_survivors_period_net | **0** |
| period_net_is_not_a_pass | **true** |
| auto_research_candidate | **false** |
| promote_as_main | **false** |
| go | **false** |
| generation_enabled (all 7) | **false** |
| sign_flip_is_not_a_kill | **true** |

`n_periods_ok=18` (not 21): `idio_mom_macro_impulse` has no TOPIX series on the factory synthetic panel → honest `data_missing`, **not** `unknown_family`. That is recognition dispatch working.

**n_survivors_period_net = 0 is honest and is not a pass.** Factory synthetic period-net **cannot** pass this gate. daily_path_DD of the min-impl remains the required eval (Track B / Track C proofs).

`generate_strategy_batch` does **not** emit these logics (`generation_enabled=False`).

---

## Track E confirm (held this wave)

| item | status |
|------|--------|
| extra `xs_cs_dispersion_gate` threshold grid | **not run** |
| extra hold/mom grid | **not run** |
| `xs_cs_dispersion_gate` stance | **RESEARCH_ONLY** |
| `xs_rank_ls_sticky` stance | **STABLE_RESEARCH_ONLY** |
| repo invent / ffill | **false** |
| 3-default pins | **untouched** |
| equities_master MISDATE | **KEEP PARTIAL** (COMPLETE **220** / PARTIAL **21** · no floor raise) |
| Mass / READY / GO / live | **NO-GO / false / false / false** |

Projection FRESH is re-published on this close (see residual).

---

## Explicit non-declarations

- Family append **is not** a pass
- Family append **is not** promotion
- Auto `research_candidate` **not** minted
- Survivors **not** main / **not** GO
- Did **not** kill funding/surprise for sign-flip
- Factory period-net after recognition **cannot** replace daily_path_DD
- Grok did **not** implement

GLM implementer only. Grok did not implement.
