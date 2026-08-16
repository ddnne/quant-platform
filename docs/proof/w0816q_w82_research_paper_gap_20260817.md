# W82 / w0816q — Task B: research ↔ paper StrategySpec gap + recompute + decision

**Wave:** W82 / `w0816q` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Task:** **B** Diff research eval vs paper proxy · align · recompute stats · limited paper re-trial · holistic decision  
**Logs:** [`.glm-logs/w0816q_w82_event/`](../../.glm-logs/w0816q_w82_event/)  
**Prior:** W81 event_post **KEEP** (t=2.83 · Sharpe=1.15) · paper limited −4.37% proxy rehearsal  
**Linked Task A:** [`w0816q_w82_event_post_pit_definition_20260817.md`](w0816q_w82_event_post_pit_definition_20260817.md)

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| READY | **未宣言** |
| Mass | **NO-GO** |
| Phase7 | **OFF** |
| operational GO | **closed** |
| continuous / unlimited paper arm | **OFF** |
| live orders | **OFF** |
| S1–S5 un-reject | **forbidden** |
| mean-bp-only promotion | **forbidden** |
| hide paper negatives | **forbidden** |
| commit / push | **not this task** |

**Policy:** t / Sharpe / win-rate **always computed and shown**; floors are **guidelines** for holistic maintain / conditional / demote — not hard one-strike alone.

---

## 1. Diff: research eval vs paper StrategySpec proxy

| dimension | Research `event_post` (class_hyp) | Paper StrategySpec v2 proxy | alignable? |
|-----------|-----------------------------------|-----------------------------|------------|
| **Signal** | `sign(surprise_proxy)` on fins disclosure events only | `disclosure_flag_fins ≥ 0.5` (any PIT-visible fins_summary row ever) | **No** — irreducible in v2 rule language |
| **Direction** | long **or short** by surprise sign | **long-only** equal weight | **No** |
| **Event intensity** | sparse (~0.4 scored events / trading day; ~3.6 / code-year) | near-continuous once any historical fins row is visible | **No** |
| **Rebalance** | event entry + sticky **5d** hold | schema **daily** only | **No** (schema hard constraint) |
| **Entry timing** | W82 PIT: first session close not looking ahead of DiscDate+DiscTime | paper `next_close` (decision at close → fill next close) | **Partial** — both avoid same-day after-hours look-ahead; mid-day research can same-day |
| **Hold return** | close[t]→close[t+5] per event | daily mark-to-market portfolio | **Partial** (horizon intent in envelope only) |
| **Universe** | DEFAULT_EVAL_CODES **30** large-cap | same **30** codes (W81 seed reused) | **Yes — aligned** |
| **Cost** | 10bp one-way base · liquidity mult · amortized /5 on research mean | **10.0 bps** one-way standard | **Yes — aligned** |
| **Data** | bars R2 mirrors + sqlite fins_summary + fins_earnings_date | offline seeded sqlite (bars NDJSON + fins extract) | **Yes** for trial surface |
| **Fidelity tag** | research truth | `strategy_spec_fidelity=proxy` | documented |

### Irreducible gaps (StrategySpec v2)

1. No surprise / signed event feature on the approved whitelist used by the proxy.  
2. `disclosure_flag_fins` is cumulative “any visible fins_summary”, not event-day.  
3. Only `rebalance=daily` allowed (`StrategySpec` schema).  
4. Threshold/TopK rules cannot express sticky post-event hold or short leg.

**Aligned this wave:** universe n=30 · cost_bps=10 · `execution_mode=next_close` · documented envelope · research PIT entry (Task A).

---

## 2. Research recompute after PIT entry (W82)

Source: `.glm-logs/w0816q_w82_event/class_hyp_multi_year_bundle.json` · `candidate_summary.json`  
Periods: y2015_full · y2017_q4 · y2019_full · y2021_full · y2023_full · y2025_q4  
Codes: 30 · cost: liquidity-linked 10bp · thickened fins calendar · **entry_mode=`same_day_close_if_pre_close`**

### 2.1 Period nets (event_post · post-hold=5d · PIT)

| period | gross | net | n_scored | trade t | trade Sharpe_ann | trade winrate |
|--------|------:|----:|---------:|--------:|-----------------:|--------------:|
| y2015_full | +35.6bp | +33.6bp | 74 | 0.80 | 0.65 | 0.49 |
| y2017_q4 | +46.5bp | +44.5bp | 25 | 0.59 | 0.83 | 0.56 |
| y2019_full | −29.5bp | **−31.5bp** | 82 | −0.74 | −0.57 | 0.49 |
| y2021_full | +60.0bp | +58.0bp | 83 | 1.41 | 1.09 | 0.64 |
| y2023_full | +23.5bp | +21.5bp | 80 | 0.52 | 0.41 | 0.54 |
| y2025_q4 | −89.0bp | **−91.0bp** | 27 | −1.00 | −1.35 | 0.48 |

### 2.2 Period-level stats bar (guidelines · always shown)

| metric | W81 (pre-PIT) | **W82 (PIT)** | guideline | pass? |
|--------|--------------:|--------------:|-----------|:-----:|
| mean net | **+53.0bp** | **+5.9bp** | ≥20bp economic | **no** |
| **t-stat** | **2.83** | **0.25** | \|t\|≥1.5 | **no** |
| **Sharpe** (period) | **1.15** | **0.10** | ≥0.50 | **no** |
| win-rate | **0.833** (5/6) | **0.667** (4/6) | ≥0.60 | yes |
| positive periods | 5 | 4 | ≥4 | yes |
| payoff | 12.4 | 0.64 | soft | weak |
| max DD (cum period nets) | −5.2bp | **−0.91%** | soft | worse |
| occurrence | ~3.61/code-yr | ~3.60/code-yr | rate OK | **yes** |
| gate / risk / skew | PASS | PASS | | yes |
| economic_net_ok | yes | **no** | | |
| stats_ok | yes | **no** | | |
| **research_candidate** | **True** | **False** | | |

Occurrence: n_events=694 · n_scored=371 · events/td≈0.40 · ~3.60/code-yr · sufficient.

### 2.3 Honesty: W81 edge was look-ahead-contaminated

W81 entered at DiscDate close **regardless of DiscTime**. ~45% of eval-window entries under W82 are next-session (after-close / at-close); shifting the 5d window by one session collapses mean net from **+53bp → +5.9bp** and t/Sharpe into noise. This is **not** hidden: paper negatives already warned fidelity gap; PIT fix confirms research KEEP was unsafe.

---

## 3. Limited paper re-trial (proxy · honest)

Artifacts under `.glm-logs/w0816q_w82_event/paper_*`  
DB reused: W81 offline seed (same 30 codes · 10bp · 2023 window) — not continuous ingest.

| run | lifecycle | window | post-cost | maxDD | trades | days |
|-----|-----------|--------|----------:|------:|-------:|-----:|
| single-shot | Draft | 2023-08-31…09-06 | **+1.38%** | −0.09% | 108 | 5 |
| LIMITED | Paper | 2023-08-31…10-13 | **−4.37%** | −9.81% | 783 | 30 |

Matches W81 paper numbers (same proxy + DB). **Not an edge claim.** Pipeline healthy; continuous arm **OFF**.

Interpretation:

* High trade count (783/30d) = daily rebalance on near-always-on disclosure flag → **not** event-sparse research.  
* Negative limited window is consistent with proxy ≠ research and with W82 research demotion.  
* Do **not** promote on single-shot +1.38%.

---

## 4. Holistic decision

### event_post

| axis | judgment |
|------|----------|
| Economic residual after costs | **weak** (+5.9bp << 20bp bar; amortized cost 2bp already material) |
| Statistical quality | **noise** (t=0.25 · Sharpe=0.10) despite win-rate 4/6 |
| Year stability | **fragile** (2019 −31.5bp · 2025 −91bp) |
| Occurrence | OK for continued research discussion |
| PIT integrity | **required** — W81 KEEP invalidated by look-ahead |
| Paper path | proxy healthy as ops rehearsal; PnL **negative**; fidelity **irreducible** |
| Mass/READY/GO | still closed |

**Decision: DEMOTE** `research_candidate` → **`not_candidate`**  
**verdict:** `not_candidate_economic_net_not_meaningful`  
**Reasons (written):**

1. After PIT-safe entry, mean net and t/Sharpe fail economic + statistical quality — residual is not production-grade.  
2. W81 KEEP depended on same-day close for after-hours DiscTime (look-ahead); must not maintain candidate on contaminated metrics.  
3. Paper StrategySpec cannot express the research signal; limited trial remains −4.37% post-cost and is not alpha evidence.  
4. Bars are guidelines: even with win-rate 4/6, holistic view is demote, not conditional keep — edge magnitude and t are near zero.  
5. Optional future path = rebuild a true event feature (signed surprise, event-day only) into StrategySpec/runtime **before** any re-candidate; not this wave.

**Not conditional keep:** conditional would require economic residual still interesting with PIT intact; +5.9bp is not.

### multi_day_hold 10d (context · unchanged)

Still `discussion_only_noisy_stats` (t=0.62 · Sharpe=0.25) — demoted W81; no re-promotion.

### Production research candidates after W82

**0** (none). event_post no longer sole candidate.

---

## 5. Freeze reaffirmation

| item | status |
|------|--------|
| any_research_candidate | **False** |
| ready_declared | **False** |
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| operational_go | **False** |
| paper continuous | **UNARMED** |
| live | **OFF** |
| commit / push | **not done** |

---

## 6. Log index

| path | content |
|------|---------|
| `.glm-logs/w0816q_w82_event/class_hyp_multi_year_bundle.json` | full multi-year recompute |
| `.glm-logs/w0816q_w82_event/candidate_summary.json` | candidate bar extract |
| `.glm-logs/w0816q_w82_event/class_hyp_multi_year_eval.log` | eval stdout |
| `.glm-logs/w0816q_w82_event/entry_split.json` | same-day vs next-session counts |
| `.glm-logs/w0816q_w82_event/pytest_class_signals.log` | PIT unit tests |
| `.glm-logs/w0816q_w82_event/paper_results.json` | paper trial card |
| `.glm-logs/w0816q_w82_event/paper_specs/` | StrategySpec + envelope |
| `.glm-logs/w0816q_w82_event/paper_limited_trial/` | limited store + summary |

---

## 7. Summary table for orchestrator

| item | value |
|------|------:|
| event_post mean net | **+5.9bp** |
| event_post t | **0.25** |
| event_post Sharpe | **0.10** |
| event_post win-rate | **0.667** (4/6) |
| research_candidate | **False** |
| **decision** | **demote → not_candidate** |
| paper limited post-cost | **−4.37%** (proxy rehearsal) |
| continuous paper | **OFF** |
| Mass/READY/GO | **closed** |

**Return:** decision + metrics above · proofs A+B · logs under `w0816q_w82_event` · **no push**.
