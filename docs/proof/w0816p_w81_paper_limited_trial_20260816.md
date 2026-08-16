# W81 / w0816p — Task B: paper single-shot then LIMITED period trial (stats-bar survivors only)

**Phase:** research_candidate → production StrategySpec → single-shot paper → limited paper trial  
**Wave:** W81 / `w0816p` · 2026-08-16  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Task:** **B** paper single-shot + LIMITED period trial — **only** for stats-bar survivors  
**Logs:** [`.glm-logs/w0816p_w81_stats/paper_*`](../../.glm-logs/w0816p_w81_stats/)  
**Prior:** W81 Task A stats bar · W80 unarmed paper receptacle · StrategySpec v2 paper runner

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **paper_scheduler_armed** | **False** (not continuous) |
| **paper_continuous / unlimited arm** | **False** |
| **live_orders / live_order_path** | **False** |
| **READY** | **未宣言** (`ready_declared=False`) |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| **operational GO** | **closed** |
| edge / significance claim from paper | **none** (trial metrics only) |
| S1–S5 un-reject | **forbidden** |
| push / commit | **not this task** |

Paper here = **offline, fixed-window pseudo-ops trial** between research and live.  
**Not** a continuously armed paper scheduler. **Not** live.

---

## W81 A input (must follow)

| class | W81 A decision | Task B action |
|-------|----------------|---------------|
| **event_post** | **KEEP** `research_candidate` (t=2.83 · Sharpe=1.15) | **StrategySpec + single-shot + LIMITED trial** |
| **multi_day_hold 10d** | **DEMOTED** `discussion_only_noisy_stats` (t=0.62 · Sharpe=0.25) | **Unarmed adapter artifact only** — **no** limited trial arm |
| Mass / READY / operational GO | OFF / undeclared / closed | **held** |

---

## Delivered

### 1. StrategySpec (event_post · production paper)

| artifact | path |
|----------|------|
| bare StrategySpec | [`.glm-logs/w0816p_w81_stats/paper_specs/event_post_strategy_spec.json`](../../.glm-logs/w0816p_w81_stats/paper_specs/event_post_strategy_spec.json) |
| paper envelope | [`.glm-logs/w0816p_w81_stats/paper_specs/event_post_paper_envelope.json`](../../.glm-logs/w0816p_w81_stats/paper_specs/event_post_paper_envelope.json) |
| index | [`.glm-logs/w0816p_w81_stats/paper_specs/index.json`](../../.glm-logs/w0816p_w81_stats/paper_specs/index.json) |

```json
{
  "version": "strategy-spec/v2",
  "strategy_id": "w81_event_post_disclosure_proxy_paper",
  "rebalance": "daily",
  "rule": {
    "type": "threshold",
    "feature": {"id": "disclosure_flag_fins", "version": "1.0.0", "params": {}},
    "threshold": 0.5
  }
}
```

**Fidelity note (unchanged from W80):** full surprise-proxy sticky event hold is **not** expressible in StrategySpec v2 rule language. Nested rule is the **approved-feature proxy** (`disclosure_flag_fins` threshold). Research envelope records `post_hold_days=5` / event rebalance intent; interpreter rebalance remains `daily`.

Built via:

* `research.paper_candidate_adapter.build_event_post_strategy_spec`
* `strategies.spec.interpret_strategy_spec` (feature resolve OK · approved · signal role)

### 2. multi_day (optional unarmed only — no trial)

| artifact | path |
|----------|------|
| unarmed receptacle | [`.glm-logs/w0816p_w81_stats/paper_specs/multi_day_hold_10d_unarmed_only.json`](../../.glm-logs/w0816p_w81_stats/paper_specs/multi_day_hold_10d_unarmed_only.json) |
| bare StrategySpec | [`.glm-logs/w0816p_w81_stats/paper_specs/multi_day_hold_10d_strategy_spec.json`](../../.glm-logs/w0816p_w81_stats/paper_specs/multi_day_hold_10d_strategy_spec.json) |

Status: `paper_receptacle_unarmed`. **No** single-shot trial · **no** limited trial · continuous arm **False**.

### 3. Fixed trial surface (universe / costs / window)

| knob | value |
|------|-------|
| **universe** | 30 codes from W81 class_hyp bundle (same research set) |
| **cost_bps** | **10.0** (one_way 0.001 · research aligned) |
| **execution_mode** | `next_close` |
| **lookback_days** | 35 |
| **starting_capital** | 1_000_000 |
| **require_ready_snapshot** | **False** (READY undeclared) |
| **bars source** | W64 R2 mirror NDJSON `equities_bars_daily_y2023_full` |
| **fins source** | local `data/structured/ingestion.sqlite` `jquants_records.fins_summary` (per-code extract) |
| **paper DB** | [`.glm-logs/w0816p_w81_stats/paper_db/event_post_limited_paper.sqlite`](../../.glm-logs/w0816p_w81_stats/paper_db/) (seeded offline; not continuous ingest) |

Seed window for lookback+trial: **2023-07-11 … 2023-10-13** (65 trading days seeded).

### 4. Single-shot dry paper run

| field | value |
|-------|-------|
| **lifecycle** | `Draft` (dry / no store persist) |
| **period** | **2023-08-31 … 2023-09-06** (**5** trading days) |
| **ok / healthy** | **True** |
| **experiment_id** | `7924c5a9bc66693088613a579e7b3bf5b41f6c885721f553cb417dd277071c15` |
| total_return_post_cost | **+1.3800%** |
| total_return_pre_cost | +1.4728% |
| max_drawdown | −0.0906% |
| num_trades | 108 |
| num_trading_days | 5 |

Logs:

* [`.glm-logs/w0816p_w81_stats/paper_single_shot.log`](../../.glm-logs/w0816p_w81_stats/paper_single_shot.log)
* [`.glm-logs/w0816p_w81_stats/paper_single_shot/`](../../.glm-logs/w0816p_w81_stats/paper_single_shot/)

Healthy gate: metrics present · equity curve non-empty · finite post-cost return · no exception → **proceed to limited trial**.

### 5. LIMITED period paper trial (fixed short window)

| field | value |
|-------|-------|
| **lifecycle** | `Paper` |
| **period** | **2023-08-31 … 2023-10-13** (**30** trading days · within 20–40) |
| **ok** | **True** |
| **experiment_id** | `37161358d221704b9b8438ad2846f36f656ec8d15d4f268d14e24ef14688a25d` |
| total_return_post_cost | **−4.3710%** |
| total_return_pre_cost | −4.2545% |
| max_drawdown | −9.8083% |
| num_trades | 783 |
| num_trading_days | 30 |
| cost_drag (JPY) | ~1165.63 |
| data_snapshot_id | `sha256:1ddc2c478e5a7b9adaffd43ab9fb4715f7d567bc9ad275b2f9c35a57a3ebb1b5` |

Logs:

* [`.glm-logs/w0816p_w81_stats/paper_limited_trial.log`](../../.glm-logs/w0816p_w81_stats/paper_limited_trial.log)
* [`.glm-logs/w0816p_w81_stats/paper_limited_trial/`](../../.glm-logs/w0816p_w81_stats/paper_limited_trial/)
* store under `paper_limited_trial/store/` (persisted paper result)

Card / rollup:

* [`.glm-logs/w0816p_w81_stats/paper_trial_card.json`](../../.glm-logs/w0816p_w81_stats/paper_trial_card.json)
* [`.glm-logs/w0816p_w81_stats/paper_results.json`](../../.glm-logs/w0816p_w81_stats/paper_results.json)

---

## Results interpretation (explicit)

1. **Pipeline proof:** event_post StrategySpec interprets · paper runner completes single-shot and limited window with fixed universe/costs — **healthy**.
2. **Limited-window PnL is not a significance / edge claim.** 30 trading days on the StrategySpec **proxy** (disclosure flag threshold, daily rebalance) is **not** the multi-year research signal with sticky post-event hold. Negative limited-window post-cost return does **not** revoke W81 A multi-year KEEP, and does **not** authorize live / continuous arm.
3. **Research vs paper fidelity gap:** class_hyp `event_post` scores surprise + post-hold on fins events; StrategySpec v2 can only long equal-weight names with `disclosure_flag_fins ≥ 0.5` (often many names once any PIT-visible fins row exists). Treat limited trial as **ops path rehearsal**, not alpha confirmation.
4. **No promotion:** READY / Mass / operational GO remain closed. No continuous paper scheduler.

---

## Runner path used

```text
packages/product/research/paper_candidate_adapter.py   # StrategySpec builders
packages/research_runtime/strategies/spec/schema.py    # StrategySpec v2
packages/research_runtime/strategies/spec/interpreter.py
packages/research_runtime/strategies/paper/runner.py   # run_paper
```

Entry used for this wave (inline offline driver under logs — **not** continuous scheduler):

* `interpret_strategy_spec(spec)` → `run_paper(strategy, PaperRunConfig(...))`
* single-shot: `lifecycle=Draft`, no store
* limited: `lifecycle=Paper`, `JsonPaperStore` under log dir

`scripts/run_paper_once.py` only ships bundled `return-1d` / `momentum` examples; StrategySpec path uses the library API above.

---

## Non-goals (explicit)

* Continuous paper scheduler arming  
* Unlimited / rolling paper arm  
* Live orders / broker / trader prepare  
* Mass / READY / Phase7 / operational GO  
* Limited trial for multi_day_hold (demoted)  
* Claiming significance or production edge from the 30-day window  
* Commit / push  

---

## Summary table

| step | status | notes |
|------|--------|-------|
| Emit event_post StrategySpec | **done** | `w81_event_post_disclosure_proxy_paper` |
| multi_day unarmed artifact | **done** | no trial |
| Single-shot dry paper | **healthy** | 5d · +1.38% post-cost · Draft |
| LIMITED paper trial | **done** | 30d · −4.37% post-cost · Paper · fixed 30 codes · 10 bps |
| Continuous arm | **OFF** | held |
| Live | **OFF** | held |

**Return for orchestrator:** paper results recorded under `.glm-logs/w0816p_w81_stats/paper_*` · proof this file · **no push**.
