# W107 / w0820d Track D — curve_steepen_impulse_cs light deep-dive

**Wave:** W107 / `w0820d` · Track D  
**Logic:** `curve_steepen_impulse_cs` only (W106 mixed unique_logic, not headline there)  
**Recipe:** `scripts/run_w107_curve_steepen_deepdive.py`  
**Artifacts:** [`.glm-logs/w0820d_w107_otc11_adaptive/`](../../.glm-logs/w0820d_w107_otc11_adaptive/) · `w107_d_curve_steepen_deepdive.json`  
**Implementer:** Grok (this wave).

Occupancy / window stability / cost feel only. **No** threshold / hold / mom grid. promote_as_main=false · go=false.

---

## Verdict

| metric | value |
|--------|------:|
| daily_path_DD worst | **−8.3%** (2023–25) |
| window sign pattern (total_ret_net) | **[+1, −1, +1]** |
| occupancy | 27.8% / 19.2% / 32.5% (not always-on) |
| tx bands | 5 / 10 / 20 bp replay; **not pick-best** |
| hold/mom / thresh grid | **not run** |
| ffill / invent | **false / false** |
| promote_as_main / go | **false / false** |

Cost-feel 5→20 bp does not reorder windows. Occupancy stays in the sparse impulse band. Sign is window-unstable — **not a kill of the parent unique_logic**, and **not** a promotion.

Complete measurement ≠ GO.
