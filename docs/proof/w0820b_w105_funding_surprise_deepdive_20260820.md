# W105 / w0820b Track C — light deep-dive (`event_funding_stress_skip` · `surprise_xs_rank_hold`)

**Wave:** W105 / `w0820b` · Track C  
**Logics (only these two):** `event_funding_stress_skip` · `surprise_xs_rank_hold`  
**Scope:** occupancy · window stability · cost feel  
**Not run:** threshold / hold / mom grid farm · extra `xs_cs_dispersion_gate` grid · pick-best cost  
**Data path:** `local_real_mirrors` + `ingestion.sqlite` (same W99/W104 honest shards)  
**Method:** daily MTM after cost — `scripts/run_w104_new_hyps_daily_dd.py` evaluators  
**Recipe:** `scripts/run_w105_funding_surprise_deepdive.py`  
**Artifacts:** [`.glm-logs/w0820b_w105_otc9_family_hyps/`](../../.glm-logs/w0820b_w105_otc9_family_hyps/) · `deepdive_summary.json` · `deepdive_occupancy.json` · `deepdive_window_stability.json` · `deepdive_tx_cost_feel.json`  
**W104 daily_path_DD (cited, not remapped):** [`w0820a_w104_hyps_new_logic_20260820.md`](w0820a_w104_hyps_new_logic_20260820.md)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| field | value |
|-------|-------|
| promote_as_main | **false** |
| go / go_eligible | **false** |
| hold/mom micro-grid | **not run** |
| threshold grid | **not run** |
| extra dispersion_gate grid | **not run** |
| cost over-tune / pick-best | **false** (tx 5/10/20 bp feel only) |
| ffill / invent | **false** |
| `event_funding_stress_skip` worst daily_path_DD | **−11.4%** (`w2017_2019`, unrecovered) |
| `surprise_xs_rank_hold` worst daily_path_DD | **−8.7%** (`w2023_2025`, unrecovered) |
| window sign-stable | **no** (both flip) |
| stance | **RESEARCH_ONLY** |
| 3-default pins | **untouched** |
| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |

Light quality check, not a promotion. Complete measurement **≠** GO.

---

## Occupancy

Event book / ranked-day occupancy is **sparse** on the calendar. Not filled. Overnight missing = skip (0 this stitch). No ffill.

### `event_funding_stress_skip`

Skip when overnight Tokyo repo ≥ PIT trailing median. Missing same-date overnight → skip.

| window | n_days | n_events | n_entered | enter_frac | skip_stress | skip_missing | n_active | active_frac |
|--------|-------:|---------:|----------:|-----------:|------------:|-------------:|---------:|------------:|
| w2017_2019 | 272 | 57 | 26 | 45.6% | 24 | 0 | 42 | 15.5% |
| w2020_2022 | 193 | 39 | 6 | 15.4% | 32 | 0 | 10 | 5.2% |
| w2023_2025 | 273 | 52 | 36 | 69.2% | 12 | 0 | 46 | 16.9% |

2025-q4 took **0 / 12** events (all 12 funding-stress skips in the BOJ-hike window). 2020–22 is the thin book: 6 entries, 5.2% active. Occupancy is **not** uniform across windows.

### `surprise_xs_rank_hold`

CS rank of surprise among names in a PIT event window. `<2` names → flat (no invent).

| window | n_days | n_events | n_ranked | ranked_frac | n_flat_sparse | n_active | active_frac |
|--------|-------:|---------:|---------:|------------:|--------------:|---------:|------------:|
| w2017_2019 | 272 | 57 | 51 | 18.8% | 222 | 51 | 18.8% |
| w2020_2022 | 193 | 39 | 41 | 21.4% | 152 | 41 | 21.4% |
| w2023_2025 | 273 | 52 | 49 | 18.0% | 225 | 49 | 18.0% |

Ranked-day occupancy is modest (~18–21% of calendar). Not an always-on CS-mom book.

---

## Window stability

Required: **daily_path_DD** · **dd_duration** · **recovery** · **total_ret_net**. Base tx **10 bp**. Numbers **match W104**.

| logic | window | n_days | daily_path_DD | dd_dur | recov | recovered | total_ret_net | sign | n_ep | time UW |
|-------|--------|-------:|--------------:|-------:|------:|:---------:|--------------:|-----:|-----:|--------:|
| `event_funding_stress_skip` | w2017_2019 | 272 | −0.114099 | 119 | — | False | 0.009860 | + | 1 | 83.8% |
| `event_funding_stress_skip` | w2020_2022 | 193 | −0.069721 | 71 | — | False | −0.042163 | − | 2 | 57.3% |
| `event_funding_stress_skip` | w2023_2025 | 273 | −0.048347 | 14 | 108 | True | 0.089428 | + | 4 | 48.5% |
| `surprise_xs_rank_hold` | w2017_2019 | 272 | −0.026524 | 2 | 3 | True | 0.102792 | + | 8 | 80.1% |
| `surprise_xs_rank_hold` | w2020_2022 | 193 | −0.061688 | 60 | — | False | −0.002355 | − | 2 | 88.5% |
| `surprise_xs_rank_hold` | w2023_2025 | 273 | −0.087448 | 87 | — | False | −0.026201 | − | 7 | 58.5% |

Sign of `total_ret_net` **flips** across windows (`funding` +/−/+ · `surprise` +/−/−). That is the stability story: neither book is window-robust. Period-net DD=0 **must not** be read as riskless.

Funding worst path is the 2017–19 stitch (peak 2017-11-08 → trough 2019-05-14, unrecovered). Surprise worst path is 2023–25 (peak 2023-08-21 → trough 2025-11-14, unrecovered; 2025-q4 shard −8.7%).

---

## Cost feel (tx 5 / 10 / 20 bp)

Replay only. **Not** a strategy grid. **Not** pick-best. Occupancy (entered / ranked) is unchanged across bands.

| logic | window | DD @5bp | DD @10bp | DD @20bp | net @5bp | net @10bp | net @20bp |
|-------|--------|--------:|---------:|---------:|---------:|----------:|----------:|
| `event_funding_stress_skip` | w2017_2019 | −0.113654 | −0.114099 | −0.114989 | 0.010708 | 0.009860 | 0.008165 |
| `event_funding_stress_skip` | w2020_2022 | −0.069627 | −0.069721 | −0.069910 | −0.041970 | −0.042163 | −0.042548 |
| `event_funding_stress_skip` | w2023_2025 | −0.048080 | −0.048347 | −0.048882 | 0.090429 | 0.089428 | 0.087429 |
| `surprise_xs_rank_hold` | w2017_2019 | −0.026485 | −0.026524 | −0.026603 | 0.103915 | 0.102792 | 0.100548 |
| `surprise_xs_rank_hold` | w2020_2022 | −0.061461 | −0.061688 | −0.062140 | −0.001537 | −0.002355 | −0.003990 |
| `surprise_xs_rank_hold` | w2023_2025 | −0.087263 | −0.087448 | −0.087816 | −0.025246 | −0.026201 | −0.028109 |

Cost feel is **small** relative to path DD: doubling tx from 10→20 bp moves funding worst DD from **−11.41%** to **−11.50%**, surprise worst from **−8.74%** to **−8.78%**. These books are occupancy-sparse (amortized drag is light). Cost is **not** the binding constraint; occupancy + window sign-flip are.

Repo-linked short (W103 overnight, gaps=0) is **not** re-tuned here. No invent / no ffill.

---

## Freezes held

- Mass = NO-GO · READY = false · ops GO = false · continuous paper = UNARMED
- 3-default pins **untouched**
- No threshold / hold / mom farm
- No extra `xs_cs_dispersion_gate` grid
- sticky stays **STABLE_RESEARCH_ONLY** · gate stays **RESEARCH_ONLY**
- Survivors **not** promoted as main / GO
- Complete daily_path_DD **≠** GO

GLM implementer only. Grok did not implement.
