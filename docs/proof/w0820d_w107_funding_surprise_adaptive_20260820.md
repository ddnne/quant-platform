# W107 / w0820d Track C — funding/surprise adaptive side + fixed L/S table

**Wave:** W107 / `w0820d` · Track C  
**Recipe:** `scripts/run_w107_funding_surprise_adaptive.py`  
**Artifacts:** [`.glm-logs/w0820d_w107_otc11_adaptive/`](../../.glm-logs/w0820d_w107_otc11_adaptive/) · `funding_surprise_side_table.json` · `w107_c_summary.json`  
**Prior L/S:** [`w0820c_w106_funding_surprise_ls_20260820.md`](w0820c_w106_funding_surprise_ls_20260820.md)  
**Implementer:** Grok (this wave).

**Do not conclude “sign flipped so kill”.** The W106 fixed L/S table is kept. This wave adds a trail-K PIT adaptive overlay beside orig / flip / conditional L/S.

---

## Verdict

| metric | value |
|--------|------:|
| adaptive logics | **2** (`event_funding_adaptive_side` · `surprise_xs_rank_adaptive`) |
| daily_path_DD complete | **7 / 7** (2 parents + 3 W106 L/S + 2 adaptive) |
| occupancy vs parent | **held** (easy-funding 26/57 · 6/39 · 36/52; surprise ranked occupancy same) |
| trail K / min | **10 / 5** completed holds or ranked-day nets with hold_end / date **< entry** (PIT) |
| sign_flip_is_not_a_kill | **true** |
| did_not_kill_funding_surprise | **true** |
| threshold / hold grid | **not run** |
| promote_as_main / go | **false / false** |

---

## Adaptive design

- **Funding:** same easy-overnight occupancy as `event_funding_stress_skip`. At each PIT entry, last K completed-hold mean orig vs flip (`hold_end < entry_date`). Insufficient history → orig. Missing overnight → skip (no ffill).
- **Surprise:** same ranked occupancy as `surprise_xs_rank_hold`. Each day, last K completed orig daily nets (`date < d`). Mean ≥ 0 → orig book; else flip. Cost drag stays a drag under the flip (gross sign-flipped, cost not inverted).

---

## Window side table (preferred = max total_ret_net; not a kill)

| window | book | preferred | orig net | flip net | adaptive net |
|--------|------|-----------|----------|----------|--------------|
| 2017–19 | funding | `event_funding_stress_skip` | +1.0% | −1.9% | −1.5% |
| 2020–22 | funding | `event_funding_easy_short` | −4.2% | **+4.1%** | −4.2% |
| 2023–25 | funding | `event_funding_stress_ls` | +8.9% | −9.1% | −2.0% |
| 2017–19 | surprise | `surprise_xs_rank_hold` | **+10.3%** | −10.1% | +5.3% |
| 2020–22 | surprise | `surprise_xs_rank_hold` | −0.2% | −0.4% | −1.1% |
| 2023–25 | surprise | `surprise_xs_rank_adaptive` | −2.6% | +1.6% | **+7.9%** |

Worst daily_path_DD: skip **−11.4%** · easy_short **−9.1%** · stress_ls **−18.6%** · surprise orig **−8.7%** · surprise flip **−11.9%** · funding adaptive **−9.1%** · surprise adaptive **−5.1%**.

2020–22 funding still prefers the **short side**. 2023–25 funding still prefers **conditional L/S**. Adaptive does **not** uniformly dominate. **Not a kill. Not GO.**

---

## Explicit non-declarations

- “sign flipped so kill” funding/surprise — **FORBIDDEN / not done**
- occupancy collapse — **not** (adaptive occupancy matches parent)
- threshold/hold grid farm — **not**
- promote_as_main / GO / research_candidate — **not**
